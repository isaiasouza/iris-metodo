from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

import cv2
import numpy as np

import analise
from amostragem import probe
from analise import VERSAO_MOTOR, analisar_clipe
import presets
import segmentos
from tests import sinteticos


def _info(n_quadros=40, largura=320, altura=180):
    return dataclasses.replace(probe(sinteticos.clipes()["parado"]), duracao=n_quadros / 4.0,
                               largura=largura, altura=altura)


def _medir_quadros(quadros):
    """Roda analise._medir sobre quadros prontos (sem ffmpeg)."""
    falso = lambda info, a, l, hw: iter([(i / 4.0, q) for i, q in enumerate(quadros)])  # noqa: E731
    with mock.patch.object(analise, "amostrar", falso):
        return analise._medir(_info(len(quadros)), 4.0, 320, False)


def parede(semente=0, n=40, ruido=2.0, brilho=180.0):
    """Parede lisa (quase sem textura) com ruído de sensor independente em cada quadro."""
    rng = np.random.default_rng(semente)
    yy, xx = np.mgrid[0:180, 0:320]
    base = brilho + 10 * np.sin(xx / 80.0) + 5 * np.cos(yy / 60.0)
    return [np.clip(base + rng.normal(0, ruido, base.shape), 0, 255).astype(np.uint8) for _ in range(n)]


def media(v, desde=1):
    return float(np.mean(v[desde:]))


class TestAnalise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = sinteticos.clipes()
        cls.r = {n: analisar_clipe(c[n], hw=False) for n in ("parado", "pan_esq", "push_in", "tremido", "corte")}

    def test_formato_do_sidecar(self):
        s = self.r["parado"]
        self.assertEqual(s["versao_motor"], VERSAO_MOTOR)
        self.assertTrue(s["caminho"].startswith("/"))
        self.assertAlmostEqual(s["fps"], 24.0, places=2)
        tamanhos = {len(v) for v in s["quadros"].values()}
        self.assertEqual(len(tamanhos), 1)
        for campo in ("t", "nitidez", "brilho", "cam_dx", "cam_escala", "tremor", "corte", "duplicado"):
            self.assertIn(campo, s["quadros"])

    def test_parado_nao_mexe(self):
        q = self.r["parado"]["quadros"]
        self.assertLess(abs(media(q["cam_dx"])), 0.01)
        self.assertLess(media(q["tremor"], 0), 0.02)
        self.assertFalse(any(q["corte"]))

    def test_pan_esq_tem_cam_dx_negativo(self):
        q = self.r["pan_esq"]["quadros"]
        self.assertAlmostEqual(media(q["cam_dx"]), -0.0625, delta=0.02)

    def test_push_in_tem_escala_positiva(self):
        self.assertGreater(media(self.r["push_in"]["quadros"]["cam_escala"]), 0.02)

    def test_tremido_treme(self):
        self.assertGreater(media(self.r["tremido"]["quadros"]["tremor"], 0), 0.05)

    def test_corte_detectado_uma_vez_perto_de_4s(self):
        q = self.r["corte"]["quadros"]
        idx = [i for i, c in enumerate(q["corte"]) if c]
        self.assertEqual(len(idx), 1)
        self.assertAlmostEqual(q["t"][idx[0]], 4.0, delta=0.5)
        i = idx[0]
        self.assertEqual(q["confianca_cam"][i], q["confianca_cam"][i + 1])
        self.assertEqual(q["movimento_assunto"][i], q["movimento_assunto"][i + 1])

    def test_deterministico(self):
        self.assertEqual(analisar_clipe(sinteticos.clipes()["pan_esq"], hw=False), self.r["pan_esq"])

    def test_duracao_desconhecida_vem_dos_quadros(self):
        caminho = sinteticos.clipes()["parado"]
        sem_duracao = dataclasses.replace(probe(caminho), duracao=0.0)
        with mock.patch.object(analise, "probe", return_value=sem_duracao):
            s = analisar_clipe(caminho, hw=False)
        n = len(s["quadros"]["t"])
        self.assertGreater(n, 10)
        self.assertAlmostEqual(s["duracao"], n / 4.0)


def cena_pequena(semente=42, minimo=40, maximo=200):
    return cv2.resize(sinteticos.cena(semente, minimo, maximo), (320, 180), interpolation=cv2.INTER_AREA)


def mais(q, v):
    return np.clip(q.astype(float) + v, 0, 255).astype(np.uint8)


def flash(q):
    """Flash de perto: um clarão que estoura uma área grande do quadro (muda a forma do histograma)."""
    yy, xx = np.mgrid[0:q.shape[0], 0:q.shape[1]]
    return mais(q, 400 * np.exp(-(((xx - 120) / 100.0) ** 2 + ((yy - 80) / 70.0) ** 2)))


def paisagem(semente, minimo, maximo, ceu=190.0, horizonte=45):
    """Mesmo layout (céu liso em cima, horizonte na mesma altura), chão com conteúdo próprio."""
    yy = np.mgrid[0:180, 0:320][0]
    chao = cv2.resize(sinteticos.cena(semente, minimo, maximo, 640, 360), (320, 180),
                      interpolation=cv2.INTER_AREA).astype(float)
    return np.clip(np.where(yy < horizonte, ceu - 0.2 * yy, chao), 0, 255).astype(np.uint8)


class TestCorteSintetico(unittest.TestCase):
    def test_troca_entre_planos_de_mesmo_layout_e_corte(self):
        a, b = paisagem(1, 20, 100), paisagem(2, 90, 180)
        q = _medir_quadros([a] * 20 + [b] * 20)
        self.assertEqual([i for i, c in enumerate(q["corte"]) if c], [20])

    def test_troca_de_cena_e_corte(self):
        a, b = cena_pequena(42, 40, 200), cena_pequena(7, 15, 100)
        q = _medir_quadros([a] * 20 + [b] * 20)
        self.assertEqual([i for i, c in enumerate(q["corte"]) if c], [20])

    def test_quadro_de_corte_copia_confianca_e_movimento_do_vizinho(self):
        a, b = cena_pequena(42, 40, 200), cena_pequena(7, 15, 100)
        q = _medir_quadros([a] * 20 + [b] * 20)
        self.assertEqual(q["confianca_cam"][20], q["confianca_cam"][21])
        self.assertEqual(q["movimento_assunto"][20], q["movimento_assunto"][21])

    def test_degrau_de_brilho_nao_e_corte(self):
        a = cena_pequena()
        self.assertFalse(any(_medir_quadros([a] * 20 + [mais(a, 30)] * 20)["corte"]))
        w = parede(0)
        self.assertFalse(any(_medir_quadros(w[:20] + [mais(x, 30) for x in w[20:]])["corte"]))

    def test_flash_de_um_quadro_nao_e_corte(self):
        a = cena_pequena()
        self.assertFalse(any(_medir_quadros([a] * 20 + [flash(a)] + [a] * 19)["corte"]))


class TestPoucaTextura(unittest.TestCase):
    def test_parede_lisa_nao_vira_tremido(self):
        p = presets.carregar("imovel")
        limite = p["tremor_max"] * (1.0 - p["limites"]["tremido"])  # acima disso o quadro ganha `tremido`
        for semente in (0, 1, 2):
            q = _medir_quadros(parede(semente))
            self.assertLess(max(q["tremor"]), limite, f"semente {semente}")
            self.assertLess(float(np.mean(q["tremor"])), 0.02, f"semente {semente}")
            self.assertLess(float(np.mean(q["movimento_assunto"][1:])), 0.5, f"semente {semente}")


def pan_suave(n=40, passo=8):
    """Pan para a direita sobre uma textura suave: janela 320x180 andando `passo` px por amostra."""
    faixa = cv2.resize(sinteticos.cena(5, 40, 200, 2400, 1080), (320 + n * passo + 8, 180),
                       interpolation=cv2.INTER_AREA)
    return [faixa[:, i * passo:i * passo + 320].copy() for i in range(n)]


def _medir_com_fracos(quadros, fracos):
    """Como _medir_quadros, mas a correlação de fase que chega aos quadros `fracos` (índices) sai sem
    confiança e com deslocamento lixo, como num pan rápido com motion blur."""
    alvo = {id(quadros[i]) for i in fracos}
    real = analise.deslocamento

    def falso(ant, atual):
        sx, sy, r = real(ant, atual)
        return (0.0, 0.0, 0.05) if id(atual) in alvo else (sx, sy, r)

    with mock.patch.object(analise, "deslocamento", falso):
        return _medir_quadros(quadros)


class TestPreenchimento(unittest.TestCase):
    def test_um_quadro_sem_confianca_e_interpolado(self):
        sx = [0.0, -4.0, -4.0, -4.0, -4.0, 37.0, -8.0, -8.0]
        r = [-1.0, 0.9, 0.9, 0.9, 0.9, 0.05, 0.9, 0.9]
        fx, fy = analise.preencher_deslocamento(sx, [0.0] * 8, r, janela=4)
        self.assertAlmostEqual(fx[5], -6.0)
        self.assertEqual(fx[1:5], sx[1:5])
        self.assertEqual(fx[6:], sx[6:])

    def test_dois_quadros_seguidos_sao_interpolados_em_linha(self):
        sx = [0.0, -4.0, 9.0, 9.0, -10.0, -10.0]
        r = [-1.0, 0.9, 0.1, 0.1, 0.9, 0.9]
        fx, _ = analise.preencher_deslocamento(sx, [0.0] * 6, r, janela=4)
        self.assertAlmostEqual(fx[2], -6.0)
        self.assertAlmostEqual(fx[3], -8.0)

    def test_so_um_lado_copia_e_sem_nenhum_vira_zero(self):
        sx = [0.0, -4.0, -5.0, 9.0, 9.0]
        r = [-1.0, 0.9, 0.9, 0.1, 0.1]
        fx, _ = analise.preencher_deslocamento(sx, [0.0] * 5, r, janela=4)
        self.assertEqual(fx[3:], [-5.0, -5.0])
        # O primeiro quadro (resposta -1) não serve de âncora; o segundo copia o terceiro.
        self.assertEqual(analise.preencher_deslocamento([0.0, 3.0, -5.0], [0.0] * 3, [-1.0, 0.1, 0.9], 4)[0][1],
                         -5.0)
        # Nada confiável dentro da janela (parede, céu): zero.
        sx = [0.0] + [3.0] * 12
        r = [-1.0, 0.9] + [0.1] * 11
        fx, _ = analise.preencher_deslocamento(sx, [0.0] * 13, r, janela=4)
        self.assertEqual(fx[2:6], [3.0] * 4)
        self.assertEqual(fx[6:], [0.0] * 7)

    def test_pan_com_quadros_sem_confianca_continua_pan(self):
        p = presets.carregar("imovel")
        limite = p["tremor_max"] * (1.0 - p["limites"]["tremido"])
        qs = pan_suave()
        for fracos in ([], [10], [20, 21], [10, 25, 26]):
            q = _medir_com_fracos(qs, fracos)
            tipo, _ = segmentos.etiqueta_camera(q["cam_dx"], q["cam_dy"], q["cam_escala"], q["tremor"], p["camera"])
            self.assertTrue(tipo.startswith("pan_"), f"{fracos}: {tipo}")
            self.assertLess(max(q["tremor"]), limite, f"{fracos}")
            self.assertLess(max(q["movimento_assunto"][1:]), 1.0, f"{fracos}")


if __name__ == "__main__":
    unittest.main()

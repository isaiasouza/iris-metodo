from __future__ import annotations

import copy
import unittest

import numpy as np

import presets
from analise import analisar_clipe
from segmentos import (agrupar, codigo_caminho, etiqueta_camera, flags_quadros, montar_selects,
                       normalizar, notas_quadros, trechos_do_clipe)
from tests import sinteticos

DT = 0.25


def preset(**over):
    p = presets.carregar("imovel")
    p.update(over)
    return p


def quadros_fake(n, **over):
    q = {
        "t": [i * DT for i in range(n)], "nitidez": [1000.0] * n, "brilho": [0.5] * n,
        "estourado": [0.0] * n, "esmagado": [0.0] * n, "contraste": [0.4] * n,
        "cam_dx": [0.0] * n, "cam_dy": [0.0] * n, "cam_escala": [0.0] * n, "confianca_cam": [1.0] * n,
        "movimento_assunto": [0.0] * n, "tremor": [0.0] * n, "corte": [False] * n, "duplicado": [False] * n,
    }
    q.update(over)
    return q


class TestAgrupar(unittest.TestCase):
    def setUp(self):
        self.p = preset()

    def test_tudo_bom(self):
        self.assertEqual(agrupar([0.9] * 12, [False] * 12, DT, self.p), [(0, 11)])

    def test_buraco_curto_e_preenchido(self):
        notas = [0.9] * 10 + [0.1] + [0.9] * 10
        self.assertEqual(agrupar(notas, [False] * 21, DT, self.p), [(0, 20)])

    def test_buraco_longo_separa(self):
        notas = [0.9] * 10 + [0.1] * 4 + [0.9] * 10
        self.assertEqual(agrupar(notas, [False] * 24, DT, self.p), [(0, 9), (14, 23)])

    def test_none_conta_como_ruim(self):
        notas = [0.9] * 10 + [None] * 4 + [0.9] * 10
        self.assertEqual(agrupar(notas, [False] * 24, DT, self.p), [(0, 9), (14, 23)])

    def test_corte_sempre_separa(self):
        cortes = [False] * 24
        cortes[11] = True
        self.assertEqual(agrupar([0.9] * 24, cortes, DT, self.p), [(0, 10), (11, 23)])

    def test_curto_demais_some(self):
        self.assertEqual(agrupar([0.9] * 5, [False] * 5, DT, self.p), [])

    def test_longo_demais_e_dividido(self):
        notas = [0.9] * 100
        notas[50] = 0.7
        blocos = agrupar(notas, [False] * 100, DT, self.p)
        self.assertEqual(blocos, [(0, 49), (51, 99)])
        for i0, i1 in blocos:
            self.assertLessEqual((i1 - i0 + 1) * DT, self.p["duracao_max_s"])

    def test_corrida_uniforme_vira_poucos_pedacos_longos(self):
        n = int(100 / DT)
        blocos = agrupar([0.9] * n, [False] * n, DT, self.p)
        duracoes = [(i1 - i0 + 1) * DT for i0, i1 in blocos]
        self.assertLessEqual(len(blocos), 6, duracoes)
        self.assertTrue(all(d <= self.p["duracao_max_s"] for d in duracoes), duracoes)
        self.assertGreater(sum(duracoes), 90.0)

    def test_corrida_de_uma_hora_nao_estoura_a_recursao(self):
        n = int(3600 / DT)
        blocos = agrupar([0.9] * n, [False] * n, DT, self.p)
        self.assertTrue(blocos)
        self.assertTrue(all((i1 - i0 + 1) * DT <= self.p["duracao_max_s"] for i0, i1 in blocos))


class TestEtiquetaCamera(unittest.TestCase):
    cam = presets.PADRAO["camera"]

    def etiqueta(self, dx=0.0, dy=0.0, esc=0.0, tremor=0.0):
        return etiqueta_camera([dx] * 8, [dy] * 8, [esc] * 8, [tremor] * 8, self.cam)[0]

    def test_tipos(self):
        self.assertEqual(self.etiqueta(), "parada")
        self.assertEqual(self.etiqueta(dx=-0.06), "pan_esq")
        self.assertEqual(self.etiqueta(dx=0.06), "pan_dir")
        self.assertEqual(self.etiqueta(dy=0.05), "tilt_baixo")
        self.assertEqual(self.etiqueta(dy=-0.05), "tilt_cima")
        self.assertEqual(self.etiqueta(esc=0.05), "push_in")
        self.assertEqual(self.etiqueta(esc=-0.05), "pull_out")
        self.assertEqual(self.etiqueta(dx=0.06, tremor=0.1), "mao")

    def test_parada_sem_movimento_tem_confianca_1(self):
        self.assertEqual(etiqueta_camera([0.0], [0.0], [0.0], [0.0], self.cam), ("parada", 1.0))


class TestNotaEFlags(unittest.TestCase):
    def test_foco_relativo_ao_clipe(self):
        q = quadros_fake(4, nitidez=[100.0, 200.0, 400.0, 400.0])
        foco = normalizar(q, preset(foco_piso_absoluto=10.0))["foco"]
        self.assertAlmostEqual(float(foco[0]), 0.25)
        self.assertAlmostEqual(float(foco[3]), 1.0)

    def test_foco_por_cena(self):
        q = quadros_fake(8, nitidez=[4000.0] * 4 + [1000.0] * 4, corte=[False] * 4 + [True] + [False] * 3)
        foco = normalizar(q, preset(foco_piso_absoluto=10.0))["foco"]
        for v in foco:
            self.assertAlmostEqual(float(v), 1.0, places=2)

    def test_exposicao_fora_da_faixa(self):
        q = quadros_fake(3, brilho=[0.5, 0.95, 0.05])
        exp = normalizar(q, preset())["exposicao"]
        self.assertAlmostEqual(float(exp[0]), 1.0)
        self.assertEqual(float(exp[1]), 0.0)
        self.assertEqual(float(exp[2]), 0.0)

    def test_flag_excluir_zera_o_quadro(self):
        q = quadros_fake(2, estourado=[0.0, 0.5])
        p = preset()
        norm = normalizar(q, p)
        flags = flags_quadros(q, norm, p)
        self.assertIn("estourado", flags[1])
        notas = notas_quadros(norm, flags, p)
        self.assertGreater(notas[0], 0.9)
        self.assertIsNone(notas[1])

    def test_flag_desfavorecer_multiplica_por_0_6(self):
        q = quadros_fake(2, esmagado=[0.0, 0.2])
        p = preset()
        norm = normalizar(q, p)
        notas = notas_quadros(norm, flags_quadros(q, norm, p), p)
        esperado = sum(p["pesos"][k] * float(norm[k][1]) for k in p["pesos"]) / sum(p["pesos"].values()) * 0.6
        self.assertAlmostEqual(notas[1], esperado)

    def test_clipe_curto_gera_aviso(self):
        sidecar = {"caminho": "/x/curto.mp4", "fps": 24.0, "duracao": 0.5, "amostras_por_s": 4.0,
                   "quadros": quadros_fake(2)}
        self.assertEqual(trechos_do_clipe(sidecar, preset()), ([], ["curto"]))

    def test_codigo_caminho(self):
        self.assertEqual(len(codigo_caminho("/a/C0001.MP4")), 8)
        self.assertNotEqual(codigo_caminho("/a/C0001.MP4"), codigo_caminho("/b/C0001.MP4"))


class TestPontaAPonta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = sinteticos.clipes()
        cls.sc = {n: analisar_clipe(caminho, hw=False) for n, caminho in c.items()}
        p95 = float(np.percentile(cls.sc["parado"]["quadros"]["nitidez"], 95))
        cls.p = preset(foco_piso_absoluto=p95 * 0.2)

    def trechos(self, nome):
        return trechos_do_clipe(self.sc[nome], self.p)

    def test_parado(self):
        t, avisos = self.trechos("parado")
        self.assertEqual(len(t), 1)
        self.assertEqual(t[0]["camera"]["tipo"], "parada")
        self.assertEqual(t[0]["flags"], [])
        self.assertGreater(t[0]["nota"], 0.8)
        self.assertEqual(avisos, [])
        self.assertTrue(t[0]["id"].startswith("parado-"))
        codigo = codigo_caminho(self.sc["parado"]["caminho"])[:6]
        self.assertEqual(t[0]["id"], f"parado-{codigo}_01")
        self.assertIn("sem flags", t[0]["motivo"])

    def test_blur_nao_vira_select(self):
        t, avisos = self.trechos("blur")
        self.assertEqual(t, [])
        self.assertIn("sem_foco", avisos)

    def test_estourado_nao_vira_select(self):
        self.assertEqual(self.trechos("estourado")[0], [])

    def test_pan_esq(self):
        t, _ = self.trechos("pan_esq")
        self.assertEqual([x["camera"]["tipo"] for x in t], ["pan_esq"])

    def test_push_in(self):
        t, _ = self.trechos("push_in")
        self.assertEqual([x["camera"]["tipo"] for x in t], ["push_in"])

    def test_tremido_nao_vira_select_no_imovel(self):
        self.assertEqual(self.trechos("tremido")[0], [])

    def test_corte_separa_em_dois(self):
        t, _ = self.trechos("corte")
        self.assertEqual(len(t), 2)
        self.assertLessEqual(t[0]["fim_s"], t[1]["inicio_s"])

    def test_montar_selects_ordena_e_filtra(self):
        r = montar_selects(list(self.sc.values()), self.p)
        notas = [x["nota"] for x in r["trechos"]]
        self.assertEqual(notas, sorted(notas, reverse=True))
        self.assertEqual(len({x["id"] for x in r["trechos"]}), len(r["trechos"]))
        so_pan = montar_selects(list(self.sc.values()), self.p, cameras=["pan_esq"])
        self.assertTrue(so_pan["trechos"])
        self.assertTrue(all(x["camera"]["tipo"] == "pan_esq" for x in so_pan["trechos"]))
        self.assertEqual(montar_selects(list(self.sc.values()), self.p, nota_min=1.01)["trechos"], [])

    def test_deterministico(self):
        a = montar_selects(list(self.sc.values()), self.p)
        b = montar_selects(copy.deepcopy(list(self.sc.values())), self.p)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()

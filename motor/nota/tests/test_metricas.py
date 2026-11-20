from __future__ import annotations

import unittest

import cv2
import numpy as np

from metricas import (deslocamento, diferenca_bruta, escala, exposicao, movimento_assunto,
                      nitidez, semelhanca_histograma, tremor_serie)
from tests.sinteticos import cena


def quadro(semente=1, minimo=40, maximo=200):
    return cena(semente, minimo, maximo, w=320, h=180)


class TestNitidez(unittest.TestCase):
    def test_cai_com_blur(self):
        q = quadro()
        self.assertLess(nitidez(cv2.GaussianBlur(q, (0, 0), 3)), 0.2 * nitidez(q))


class TestExposicao(unittest.TestCase):
    def test_branco_estoura(self):
        e = exposicao(np.full((180, 320), 255, np.uint8))
        self.assertAlmostEqual(e["brilho"], 1.0)
        self.assertAlmostEqual(e["estourado"], 1.0)
        self.assertAlmostEqual(e["esmagado"], 0.0)

    def test_preto_esmaga(self):
        e = exposicao(np.zeros((180, 320), np.uint8))
        self.assertAlmostEqual(e["esmagado"], 1.0)

    def test_cinza_medio_sem_contraste(self):
        e = exposicao(np.full((180, 320), 128, np.uint8))
        self.assertAlmostEqual(e["brilho"], 128 / 255)
        self.assertAlmostEqual(e["contraste"], 0.0)


class TestDeslocamento(unittest.TestCase):
    def test_conteudo_para_direita_da_sx_positivo(self):
        a = quadro()
        sx, sy, resp = deslocamento(a, np.roll(a, 5, axis=1))
        self.assertAlmostEqual(sx, 5, delta=0.5)
        self.assertAlmostEqual(sy, 0, delta=0.5)
        self.assertGreater(resp, 0.3)

    def test_conteudo_para_cima_da_sy_negativo(self):
        a = quadro()
        _, sy, _ = deslocamento(a, np.roll(a, -3, axis=0))
        self.assertAlmostEqual(sy, -3, delta=0.5)


class TestEscala(unittest.TestCase):
    def test_aproximacao_da_fator_maior_que_1(self):
        a = quadro()
        b = cv2.resize(a[9:171, 16:304], (320, 180), interpolation=cv2.INTER_AREA)
        fator, ok = escala(a, b)
        self.assertTrue(ok)
        self.assertAlmostEqual(fator, 320 / 288, delta=0.03)

    def test_cenas_nao_relacionadas_nao_dao_escala_valida(self):
        fator, ok = escala(quadro(1), quadro(2))
        self.assertFalse(ok, f"fator={fator}")

    def test_quadro_liso_nao_tem_pontos(self):
        liso = np.full((180, 320), 100, np.uint8)
        self.assertEqual(escala(liso, liso), (1.0, False))


class TestMovimentoAssunto(unittest.TestCase):
    def test_pan_compensado_nao_e_movimento(self):
        a = quadro()
        self.assertLess(movimento_assunto(a, np.roll(a, 5, axis=1), 5.0, 0.0), 0.01)

    def test_cena_diferente_e_movimento(self):
        self.assertGreater(movimento_assunto(quadro(1), quadro(2), 0.0, 0.0), 0.05)


class TestHistogramaEDiferenca(unittest.TestCase):
    def test_mesma_cena(self):
        a = quadro()
        self.assertAlmostEqual(semelhanca_histograma(a, a), 1.0, places=5)
        self.assertEqual(diferenca_bruta(a, a), 0.0)

    def test_cenas_com_luz_diferente(self):
        self.assertLess(semelhanca_histograma(quadro(1, 40, 200), quadro(2, 15, 100)), 0.5)


class TestTremor(unittest.TestCase):
    def test_movimento_constante_nao_treme(self):
        t = tremor_serie([0.06] * 20, [0.0] * 20, 4)
        self.assertLess(float(np.max(t)), 1e-9)

    def test_movimento_alternado_treme(self):
        dx = [0.1 if i % 2 else -0.1 for i in range(20)]
        self.assertGreater(float(np.mean(tremor_serie(dx, [0.0] * 20, 4))), 0.05)


if __name__ == "__main__":
    unittest.main()

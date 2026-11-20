"""Submétricas: medidas novas por quadro (detalhe, percentis de brilho, rotação)."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

from metricas import afim, detalhe, escala, exposicao
from tests.sinteticos import cena


def quadro(semente=1, minimo=40, maximo=200):
    return cena(semente, minimo, maximo, w=320, h=180)


def girar(q, graus):
    """Gira o conteúdo `graus` no sentido anti-horário na tela (convenção do OpenCV), sem bordas pretas."""
    m = cv2.getRotationMatrix2D((q.shape[1] / 2, q.shape[0] / 2), graus, 1.0)
    return cv2.warpAffine(q, m, (q.shape[1], q.shape[0]), borderMode=cv2.BORDER_REFLECT)


class TestDetalhe(unittest.TestCase):
    def test_textura_tem_detalhe_e_parede_lisa_nao(self):
        self.assertGreater(detalhe(quadro()), 0.02)
        self.assertEqual(detalhe(np.full((180, 320), 120, np.uint8)), 0.0)

    def test_borrar_tira_detalhe(self):
        q = quadro()
        self.assertLess(detalhe(cv2.GaussianBlur(q, (0, 0), 4)), 0.5 * detalhe(q))

    def test_fica_entre_0_e_1(self):
        v = detalhe(quadro())
        self.assertTrue(0.0 <= v <= 1.0)


class TestPercentisDeBrilho(unittest.TestCase):
    def test_gradiente_tem_margem_nas_duas_pontas(self):
        q = np.tile(np.linspace(30, 220, 320).astype(np.uint8), (180, 1))
        e = exposicao(q)
        self.assertAlmostEqual(e["luma_p01"], 32 / 255, delta=0.02)
        self.assertAlmostEqual(e["luma_p99"], 218 / 255, delta=0.02)

    def test_estourado_encosta_no_teto(self):
        q = np.full((180, 320), 255, np.uint8)
        self.assertEqual(exposicao(q)["luma_p99"], 1.0)

    def test_chaves_antigas_continuam(self):
        self.assertTrue({"brilho", "estourado", "esmagado", "contraste"} <= set(exposicao(quadro())))


class TestAfim(unittest.TestCase):
    def setUp(self):
        cv2.setRNGSeed(0)   # o RANSAC da afim sorteia pontos: semente fixa, teste estável

    def test_giro_anti_horario_do_conteudo_da_angulo_negativo(self):
        a = quadro()
        fator, rot, ok = afim(a, girar(a, 5))
        self.assertTrue(ok)
        self.assertAlmostEqual(rot, -5.0, delta=0.5)
        self.assertAlmostEqual(fator, 1.0, delta=0.02)

    def test_giro_horario_da_angulo_positivo(self):
        a = quadro()
        _, rot, ok = afim(a, girar(a, -3))
        self.assertTrue(ok)
        self.assertAlmostEqual(rot, 3.0, delta=0.5)

    def test_sem_pontos(self):
        liso = np.full((180, 320), 100, np.uint8)
        self.assertEqual(afim(liso, liso), (1.0, 0.0, False))

    def test_escala_continua_igual(self):
        a = quadro()
        b = cv2.resize(a[9:171, 16:304], (320, 180), interpolation=cv2.INTER_AREA)
        fator, ok = escala(a, b)
        self.assertTrue(ok)
        self.assertAlmostEqual(fator, 320 / 288, delta=0.03)


if __name__ == "__main__":
    unittest.main()

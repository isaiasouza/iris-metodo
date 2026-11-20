"""Submétricas: colunas novas na análise e análise antiga sendo completada pelo `analisar`."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import nota
from analise import COLUNAS_QUADRO, analisar_clipe
from tests import sinteticos
from tests.sinteticos import cena
from tests.test_analise import _medir_quadros, parede


def girando(n=12, passo=2.0):
    """Quadros cujo conteúdo gira `passo` graus anti-horário a cada amostra (câmera girando no sentido horário)."""
    base = cena(3, 40, 200, w=320, h=180)
    centro = (160, 90)
    return [cv2.warpAffine(base, cv2.getRotationMatrix2D(centro, passo * i, 1.0), (320, 180),
                           borderMode=cv2.BORDER_REFLECT) for i in range(n)]


class TestColunasNovas(unittest.TestCase):
    def test_todas_as_colunas_atuais_estao_no_resultado(self):
        r = _medir_quadros(girando())
        for c in COLUNAS_QUADRO:
            self.assertIn(c, r)
        for c in ("detalhe", "luma_p01", "luma_p99", "cam_rot"):
            self.assertIn(c, COLUNAS_QUADRO)

    def test_rotacao_em_graus_por_segundo(self):
        r = _medir_quadros(girando(passo=2.0))
        # 2° por amostra a 4 amostras/s; conteúdo anti-horário = valor negativo.
        self.assertAlmostEqual(float(np.mean(r["cam_rot"][1:])), -8.0, delta=1.5)
        self.assertEqual(r["cam_rot"][0], r["cam_rot"][1])   # primeiro quadro copia o vizinho

    def test_parado_nao_gira(self):
        q = cena(3, 40, 200, w=320, h=180)
        r = _medir_quadros([q] * 8)
        self.assertLess(abs(float(np.mean(r["cam_rot"]))), 0.5)

    def test_textura_tem_mais_detalhe_que_parede(self):
        textura = _medir_quadros(girando())
        lisa = _medir_quadros(parede(n=12))
        self.assertGreater(np.mean(textura["detalhe"]), np.mean(lisa["detalhe"]))

    def test_percentis_dentro_de_0_1(self):
        r = _medir_quadros(girando())
        self.assertTrue(all(0.0 <= a <= b <= 1.0 for a, b in zip(r["luma_p01"], r["luma_p99"])))


class TestAnaliseAntigaECompletada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.video = sinteticos.clipes()["parado"]
        cls.sc = analisar_clipe(cls.video, hw=False)

    def gravar(self, quadros):
        d = dict(self.sc, quadros=quadros)
        tmp = Path(tempfile.mkdtemp()) / "parado.nota.json"
        tmp.write_text(json.dumps(d), encoding="utf-8")
        return tmp

    def test_completa_e_atualizada(self):
        self.assertTrue(nota._atualizado(self.gravar(self.sc["quadros"]), self.video, 4.0, 320, []))

    def test_sem_coluna_nova_precisa_refazer(self):
        q = {k: v for k, v in self.sc["quadros"].items() if k != "detalhe"}
        self.assertFalse(nota._atualizado(self.gravar(q), self.video, 4.0, 320, []))


if __name__ == "__main__":
    unittest.main()

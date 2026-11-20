"""Filtro por faixa de direção do movimento de câmera (0 = direita, 90 = cima, 180 = esquerda, 270 = baixo)."""
from __future__ import annotations

import copy
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import nota
import presets
from segmentos import ler_faixas, montar_selects, na_faixa
from tests.test_segmentos import DT, preset, quadros_fake

N = 40
NIT = [600.0 + 40.0 * ((i * 7) % 10) for i in range(N)]


def clipe(nome, **over):
    return {"caminho": f"/m/{nome}.MP4", "fps": 24.0, "duracao": N * DT, "amostras_por_s": 1 / DT,
            "quadros": quadros_fake(N, **{"nitidez": NIT, **over})}


CLIPES = [clipe("direita", cam_dx=[0.15] * N), clipe("esquerda", cam_dx=[-0.15] * N),
          clipe("cima", cam_dy=[-0.15] * N), clipe("baixo", cam_dy=[0.15] * N), clipe("parado")]


def nomes(r):
    return sorted({t["caminho"].split("/")[-1][:-4] for t in r["trechos"]})


class TestFaixa(unittest.TestCase):
    def test_na_faixa(self):
        self.assertTrue(na_faixa(90.0, [60, 120]))
        self.assertTrue(na_faixa(60.0, [60, 120]) and na_faixa(120.0, [60, 120]))
        self.assertFalse(na_faixa(121.0, [60, 120]))
        self.assertTrue(na_faixa(355.0, [350, 10]) and na_faixa(0.0, [350, 10]) and na_faixa(10.0, [350, 10]))
        self.assertFalse(na_faixa(180.0, [350, 10]))
        self.assertTrue(na_faixa(0.0, [350, 360]))     # 360° é o mesmo que 0°
        self.assertTrue(na_faixa(0.0, [0, 360]) and na_faixa(200.0, [0, 360]))

    def test_ler_faixas(self):
        self.assertEqual(ler_faixas("60-120"), [[60.0, 120.0]])
        self.assertEqual(ler_faixas(" 350-10 , 170.5-190 "), [[350.0, 10.0], [170.5, 190.0]])
        for ruim in ("60", "a-b", "60-400", "-10-20", "", " , "):
            with self.assertRaises(ValueError, msg=ruim):
                ler_faixas(ruim)


class TestSelects(unittest.TestCase):
    def setUp(self):
        self.p = preset()

    def test_sem_filtro_entram_todos(self):
        self.assertEqual(nomes(montar_selects(CLIPES, self.p)), ["baixo", "cima", "direita", "esquerda", "parado"])

    def test_uma_faixa(self):
        self.assertEqual(nomes(montar_selects(CLIPES, self.p, direcoes=[[60, 120]])), ["cima"])

    def test_faixa_que_passa_por_zero_e_varias_faixas(self):
        self.assertEqual(nomes(montar_selects(CLIPES, self.p, direcoes=[[350, 10]])), ["direita"])
        self.assertEqual(nomes(montar_selects(CLIPES, self.p, direcoes=[[350, 10], [170, 190]])),
                         ["direita", "esquerda"])

    def test_direcao_no_preset_e_no_ajuste(self):
        p = preset(direcao_faixas=[[250, 290]])
        self.assertEqual(nomes(montar_selects(CLIPES, p)), ["baixo"])
        self.assertEqual(nomes(montar_selects(CLIPES, p, direcoes=[[60, 120]])), ["cima"])   # o argumento vence
        r = montar_selects(CLIPES, self.p, ajustes={"esquerda": {"direcao_faixas": [[0, 45]]}})
        self.assertEqual(nomes(r), ["baixo", "cima", "direita", "parado"])

    def test_trecho_forcado_passa(self):
        p = copy.deepcopy(self.p)
        p["flags"]["estourado"] = "forcar"
        est = [0.0] * N
        est[5] = 1.0
        r = montar_selects([clipe("parado_forcado", estourado=est)], p, direcoes=[[60, 120]])
        self.assertTrue(r["trechos"] and all(t["forcado"] for t in r["trechos"]))

    def test_preset_valida_as_faixas(self):
        base = copy.deepcopy(presets.carregar("imovel"))
        self.assertIsNone(base["direcao_faixas"])
        for ruim in ([[0, 400]], [[10]], "60-120", [["a", 10]], [[True, 10]], []):
            p = copy.deepcopy(base)
            p["direcao_faixas"] = ruim
            with self.assertRaises(ValueError, msg=repr(ruim)):
                presets._validar(p)
        p = copy.deepcopy(base)
        p["direcao_faixas"] = [[350, 10], [60.5, 120]]
        presets._validar(p)


class TestCli(unittest.TestCase):
    def test_direcao_invalida_sai_com_erro(self):
        saida = Path(tempfile.mkdtemp()) / "analise"
        erro = io.StringIO()
        with contextlib.redirect_stderr(erro):
            self.assertEqual(nota.principal(["selecionar", "--direcao", "60-400", "--saida", str(saida)]), 2)
            self.assertEqual(nota.principal(["selecionar", "--direcao", "", "--saida", str(saida)]), 2)
        self.assertIn("--direcao", erro.getvalue())
        self.assertIn("nenhuma faixa", erro.getvalue())


if __name__ == "__main__":
    unittest.main()

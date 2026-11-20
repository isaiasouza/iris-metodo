"""Lote 1 do comparativo com o Cutdown: foco por região, flags como no Cutdown, máximo por clipe, teto de
nota, ordens invertidas e o preset seletivo "melhores"."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

import presets
from metricas import nitidez, nitidez_regiao
from segmentos import (ORDENS, flags_quadros, forcados_quadros, montar_selects, normalizar, notas_quadros)
from tests.sinteticos import cena
from tests.test_segmentos import DT, preset, quadros_fake


def sidecar(nome, n=40, **over):
    return {"caminho": f"/m/{nome}", "fps": 24.0, "duracao": n * DT, "amostras_por_s": 1 / DT,
            "quadros": quadros_fake(n, **over)}


class TestFocoPorRegiao(unittest.TestCase):
    def test_assunto_nitido_com_fundo_liso_ganha_do_quadro_inteiro(self):
        q = np.full((180, 320), 120, np.uint8)
        q[60:120, 120:200] = cena(1, 40, 200, w=80, h=60)  # só o centro tem detalhe
        self.assertGreater(nitidez_regiao(q), 3 * nitidez(q))

    def test_ignora_barras_pretas(self):
        q = cena(1, 40, 200, w=320, h=180)
        com_barras = q.copy()
        com_barras[:30] = 0
        com_barras[-30:] = 0
        self.assertAlmostEqual(nitidez_regiao(com_barras), nitidez_regiao(q), delta=0.35 * nitidez_regiao(q))

    def test_borrado_continua_baixo(self):
        q = cena(1, 40, 200, w=320, h=180)
        self.assertLess(nitidez_regiao(cv2.GaussianBlur(q, (0, 0), 4)), 0.2 * nitidez_regiao(q))

    def test_modo_regiao_usa_a_coluna_nova(self):
        q = quadros_fake(4, nitidez=[100.0] * 4, nitidez_regiao=[100.0, 100.0, 400.0, 400.0])
        p = preset(foco_piso_absoluto=10.0, foco_modo="regiao")
        self.assertAlmostEqual(float(normalizar(q, p)["foco"][0]), 0.25)

    def test_modo_regiao_sem_coluna_cai_no_quadro_inteiro(self):
        q = quadros_fake(4, nitidez=[100.0, 100.0, 400.0, 400.0])
        p = preset(foco_piso_absoluto=10.0, foco_modo="regiao")
        self.assertAlmostEqual(float(normalizar(q, p)["foco"][0]), 0.25)


class TestFlagsComoNoCutdown(unittest.TestCase):
    def test_excluir_vence_forcar(self):
        p = preset()
        p["flags"]["estourado"] = "forcar"
        self.assertEqual(forcados_quadros([["estourado", "blur"]], p), [False])
        norm = {k: [0.9] for k in ("foco", "exposicao", "estabilidade", "movimento")}
        self.assertIsNone(notas_quadros(norm, [["estourado", "blur"]], p)[0])

    def test_desfavorecer_multiplica_por_0_6_e_preferir_por_1_2(self):
        p = preset()
        norm = {k: [0.5] for k in ("foco", "exposicao", "estabilidade", "movimento")}
        p["flags"]["esmagado"] = "desfavorecer"
        self.assertAlmostEqual(notas_quadros(norm, [["esmagado"]], p)[0], 0.3)
        p["flags"]["esmagado"] = "preferir"
        self.assertAlmostEqual(notas_quadros(norm, [["esmagado"]], p)[0], 0.6)

    def test_cor_solida(self):
        q = quadros_fake(2, contraste=[0.4, 0.005])
        p = preset()
        flags = flags_quadros(q, normalizar(q, p), p)
        self.assertNotIn("cor_solida", flags[0])
        self.assertIn("cor_solida", flags[1])
        self.assertEqual(presets.PADRAO["flags"]["cor_solida"], "excluir")


class TestMaximoTetoOrdens(unittest.TestCase):
    def test_maximo_por_clipe_fica_com_os_melhores(self):
        p = preset(duracao_max_s=2.5)
        sc = sidecar("A.MP4", n=60)
        todos = montar_selects([sc], p)["trechos"]
        self.assertGreater(len(todos), 2)
        r = montar_selects([sc], p, max_por_clipe=2)["trechos"]
        self.assertEqual(len(r), 2)
        self.assertEqual(sorted(t["nota"] for t in r), sorted(t["nota"] for t in todos)[-2:])

    def test_teto_de_nota(self):
        r = montar_selects([sidecar("A.MP4")], preset(), nota_max=0.5)["trechos"]
        self.assertEqual(r, [])

    def test_ordens_invertidas(self):
        self.assertIn("nota_asc", ORDENS)
        self.assertIn("duracao_asc", ORDENS)
        sc = [sidecar("A.MP4", n=40), sidecar("B.MP4", n=20, brilho=[0.7] * 20)]
        r = montar_selects(sc, preset(), ordem="duracao_asc")["trechos"]
        d = [t["duracao_s"] for t in r]
        self.assertEqual(d, sorted(d))
        r = montar_selects(sc, preset(), ordem="nota_asc")["trechos"]
        n = [t["nota"] for t in r]
        self.assertEqual(n, sorted(n))


class TestPresetMelhores(unittest.TestCase):
    def test_carrega_e_e_mais_seletivo(self):
        p = presets.carregar("melhores")
        self.assertGreaterEqual(p["nota_min"], 0.8)
        self.assertEqual(p["foco_modo"], "regiao")
        self.assertGreater(p["pesos"]["foco"], 0.5)


if __name__ == "__main__":
    unittest.main()

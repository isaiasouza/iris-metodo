"""Reajuste de takes de uma timeline já montada (reajuste.py e davinci.planejar_reajuste)."""
from __future__ import annotations

import unittest

from davinci import planejar_reajuste
from reajuste import reajustar, resumo
from tests.test_segmentos import DT, preset, quadros_fake

FPS = 24.0  # 6 quadros por amostra de 0,25 s


def sidecar(n, ruins=(), caminho="/m/A.MP4"):
    """Clipe de n amostras; as amostras em `ruins` estão borradas."""
    nit = [1000.0] * n
    for i in ruins:
        nit[i] = 5.0
    return {"caminho": caminho, "fps": FPS, "duracao": n * DT, "amostras_por_s": 1 / DT,
            "quadros": quadros_fake(n, nitidez=nit)}


def take(i, o, caminho="/m/A.MP4", inicio_tl=0):
    return {"caminho": caminho, "in": i, "out": o, "fps": FPS, "inicio_tl": inicio_tl, "fim_tl": inicio_tl + o - i}


class TestReajustar(unittest.TestCase):
    def setUp(self):
        self.p = preset(foco_piso_absoluto=10.0)

    def test_foge_do_trecho_borrado(self):
        # Amostras 8–15 borradas (quadros 48–96); o take [48, 120) cai nelas.
        an = {"/m/A.MP4": sidecar(60, ruins=range(8, 16))}
        r = reajustar([take(48, 120)], an, self.p)[0]
        self.assertTrue(r["mudou"])
        self.assertGreaterEqual(r["novo_in"], 96)
        self.assertEqual(r["novo_out"] - r["novo_in"], 72)
        self.assertGreater(r["nota_depois"], r["nota_antes"])

    def test_nao_anda_mais_que_o_raio(self):
        an = {"/m/A.MP4": sidecar(200, ruins=range(20, 60))}
        r = reajustar([take(144, 216)], an, self.p, raio_s=2.0)[0]
        self.assertLessEqual(abs(r["novo_in"] - 144), 48)

    def test_ganho_pequeno_mantem_o_take(self):
        an = {"/m/A.MP4": sidecar(60)}
        r = reajustar([take(48, 120)], an, self.p)[0]
        self.assertFalse(r["mudou"])
        self.assertEqual((r["novo_in"], r["novo_out"]), (48, 120))

    def test_takes_do_mesmo_clipe_nao_se_sobrepoem_nem_trocam_de_ordem(self):
        an = {"/m/A.MP4": sidecar(80, ruins=range(10, 20))}
        r = reajustar([take(24, 96), take(100, 172, inicio_tl=72)], an, self.p)
        self.assertLessEqual(r[0]["novo_out"], r[1]["novo_in"])
        self.assertLess(r[0]["novo_in"], r[1]["novo_in"])

    def test_sem_analise_fica_igual(self):
        r = reajustar([take(0, 72, caminho="/m/X.MP4")], {}, self.p)[0]
        self.assertFalse(r["mudou"])
        self.assertIsNone(r["nota_antes"])

    def test_nao_passa_do_fim_do_clipe(self):
        an = {"/m/A.MP4": sidecar(20, ruins=range(0, 8))}
        r = reajustar([take(0, 72)], an, self.p)[0]
        self.assertLessEqual(r["novo_out"], 20 * 6)

    def test_resumo(self):
        an = {"/m/A.MP4": sidecar(60, ruins=range(8, 16))}
        s = resumo(reajustar([take(48, 120), take(0, 24, caminho="/m/X.MP4")], an, self.p))
        self.assertEqual((s["takes"], s["analisados"], s["mudaram"]), (2, 1, 1))


class TestPlanejarReajuste(unittest.TestCase):
    def test_mantem_a_posicao_e_usa_a_janela_nova(self):
        t = dict(take(48, 120, inicio_tl=86540), novo_in=96, novo_out=168)
        self.assertEqual(planejar_reajuste([t]), [{"caminho": "/m/A.MP4", "startFrame": 96, "endFrame": 168,
                                                   "recordFrame": 86540, "trackIndex": 2, "mediaType": 1}])


if __name__ == "__main__":
    unittest.main()

"""Perfis de log por fabricante: fórmulas, gamut, tom, LUT .cube, XML da Sony e escolha do perfil por clipe."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

import perfis_log as pl

# Matriz S-Gamut3.Cine → Rec.709 publicada pela Sony.
SONY_SG3C_709 = np.array([[1.6269474, -0.5401385, -0.0868089],
                          [-0.1785155, 1.4179409, -0.2394254],
                          [-0.0444361, -0.1959199, 1.2403560]])


def xml_sony(pasta: Path, nome: str, valor: str, arquivo: str = None) -> None:
    (pasta / (arquivo or f"{nome}M01.XML")).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">'
        '<AcquisitionRecord><Group name="CameraUnitMetadataSet">'
        f'<Item name="CaptureGammaEquation" value="{valor}"/>'
        '<Item name="CaptureColorPrimaries" value="s-gamut3-cine"/>'
        '</Group></AcquisitionRecord></NonRealTimeMeta>', encoding="utf-8")


class TestCurvas(unittest.TestCase):
    def test_cinza_18(self):
        self.assertAlmostEqual(float(pl.slog3_para_linear(420 / 1023)), 0.18, places=4)
        self.assertAlmostEqual(float(pl.vlog_para_linear(0.423)), 0.18, delta=0.002)
        self.assertAlmostEqual(float(pl.clog3_para_linear(0.343)), 0.18, delta=0.005)

    def test_monotonicas(self):
        x = np.linspace(0, 1, 1001)
        for f in (pl.slog3_para_linear, pl.vlog_para_linear, pl.clog3_para_linear):
            self.assertTrue(np.all(np.diff(f(x)) > 0), f.__name__)

    def test_faixa_legal(self):
        self.assertAlmostEqual(float(pl.codigo_de_rgb(0.0)), 64 / 1023)
        self.assertAlmostEqual(float(pl.codigo_de_rgb(1.0)), 940 / 1023)


class TestGamut(unittest.TestCase):
    def test_sgamut3cine_bate_com_a_sony(self):
        np.testing.assert_allclose(pl.matriz_para_709("sgamut3cine"), SONY_SG3C_709, atol=1e-3)

    def test_branco_continua_branco(self):
        for g in ("sgamut3cine", "vgamut", "cinemagamut"):
            np.testing.assert_allclose(pl.matriz_para_709(g) @ np.ones(3), np.ones(3), atol=1e-6)


class TestTom(unittest.TestCase):
    def test_cinza_e_extremos(self):
        self.assertAlmostEqual(float(pl.para_tela(0.18)), 0.41, delta=0.02)
        self.assertEqual(float(pl.para_tela(0.0)), 0.0)
        x = np.linspace(0, 16, 2000)
        y = pl.para_tela(x)
        self.assertTrue(np.all(np.diff(y) >= 0))
        self.assertLessEqual(float(y.max()), 1.0)


class TestLut(unittest.TestCase):
    def test_arquivo_cube(self):
        with tempfile.TemporaryDirectory() as d:
            c = pl.lut("slog3", pasta=Path(d))
            self.assertEqual(c.name, "slog3-v1.cube")
            linhas = c.read_text().splitlines()
            self.assertIn("LUT_3D_SIZE 33", linhas)
            dados = [l for l in linhas if l and (l[0].isdigit() or l[0] == "-")]
            self.assertEqual(len(dados), 33 ** 3)
            v = np.array([[float(n) for n in l.split()] for l in dados])
            self.assertTrue(np.all((v >= 0) & (v <= 1)))
            for i in range(33):   # entrada neutra (R=G=B) sai neutra; R varia mais rápido
                r, g, b = v[i + i * 33 + i * 33 * 33]
                self.assertAlmostEqual(r, g, delta=0.01)
                self.assertAlmostEqual(g, b, delta=0.01)

    def test_cache(self):
        with tempfile.TemporaryDirectory() as d:
            c = pl.lut("vlog", pasta=Path(d))
            antes = c.stat().st_mtime_ns
            time.sleep(0.01)
            self.assertEqual(pl.lut("vlog", pasta=Path(d)), c)
            self.assertEqual(c.stat().st_mtime_ns, antes)

    def test_filtros(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pl.filtro("generico"), pl.FILTRO_LOG)
            self.assertIsNone(pl.filtro("nenhum"))
            self.assertIsNone(pl.filtro(None))
            f = pl.filtro("clog3", pasta=Path(d))
            self.assertTrue(f.startswith("lut3d=file='"))
            self.assertIn("clog3-v1.cube", f)
        with self.assertRaises(ValueError):
            pl.filtro_de_lut("/nao/existe.cube")


class TestSony(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valores(self):
        for nome, valor, esperado in (("A", "s-log3-cine", "slog3"), ("B", "s-log3", "slog3"),
                                      ("C", "rec709", "nenhum"), ("D", "s-log2", "slog2"),
                                      ("E", "hlg3", "nenhum")):
            xml_sony(self.d, nome, valor)
            self.assertEqual(pl.perfil_sony(str(self.d / f"{nome}.MP4")), esperado, valor)

    def test_minusculas_ausente_e_quebrado(self):
        xml_sony(self.d, "F", "s-log3-cine", arquivo="FM01.xml")
        self.assertEqual(pl.perfil_sony(str(self.d / "F.MP4")), "slog3")
        self.assertIsNone(pl.perfil_sony(str(self.d / "G.MP4")))
        (self.d / "HM01.XML").write_text("<quebrado", encoding="utf-8")
        self.assertIsNone(pl.perfil_sony(str(self.d / "H.MP4")))


class TestEscolha(unittest.TestCase):
    def test_perfil_do_clipe(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            xml_sony(d, "A", "s-log3-cine")
            self.assertEqual(pl.perfil_do_clipe(str(d / "A.MP4"), "vlog"), "vlog")
            self.assertEqual(pl.perfil_do_clipe(str(d / "A.MP4"), "auto"), "slog3")
            self.assertEqual(pl.perfil_do_clipe(str(d / "Z.MP4"), "auto"), "generico")
            self.assertEqual(pl.perfil_do_clipe(str(d / "A.MP4"), None), "nenhum")

    def test_lut_propria_tem_prioridade(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            minha = d / "minha.cube"
            minha.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n")
            xml_sony(d, "A", "s-log3-cine")
            f = pl.filtro_do_clipe(str(d / "A.MP4"), "auto", lut_propria=str(minha), pasta=d)
            self.assertIn("minha.cube", f)
            self.assertIn("slog3-v1.cube", pl.filtro_do_clipe(str(d / "A.MP4"), "auto", pasta=d))

    def test_perfil_sem_curva_levanta(self):
        for p in ("generico", "nenhum", "xyz"):
            with self.assertRaisesRegex(ValueError, "perfil sem curva"):
                pl._para_linear(p, np.zeros((1, 3)))


if __name__ == "__main__":
    unittest.main()

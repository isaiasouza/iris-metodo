"""Os 15 perfis de log novos: curvas e gamuts contra a colour-science (referência só dos testes) e a LUT de cada um."""
from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np

import perfis_log as pl

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import colour
except ImportError:   # o motor não depende da colour-science; sem ela, só os testes de referência ficam de fora
    colour = None

NOVOS = ("slog2", "logc3", "logc4", "applelog", "bmdgen5", "davinci", "clog", "clog2", "dlog", "flog", "flog2",
         "protune", "llog", "nlog", "log3g10")
REFERENCIA = {
    "slog2": ("log", "S-Log2", "S-Gamut"), "logc3": ("log", "ARRI LogC3", "ARRI Wide Gamut 3"),
    "logc4": ("log", "ARRI LogC4", "ARRI Wide Gamut 4"), "applelog": ("log", "Apple Log Profile", "ITU-R BT.2020"),
    "bmdgen5": ("oetf", "Blackmagic Film Generation 5", "Blackmagic Wide Gamut"),
    "davinci": ("oetf", "DaVinci Intermediate", "DaVinci Wide Gamut"),
    "clog": ("log", "Canon Log", "Cinema Gamut"), "clog2": ("log", "Canon Log 2", "Cinema Gamut"),
    "dlog": ("log", "D-Log", "DJI D-Gamut"), "flog": ("log", "F-Log", "F-Gamut"),
    "flog2": ("log", "F-Log2", "F-Gamut"), "protune": ("log", "Protune", "Protune Native"),
    "llog": ("log", "L-Log", "ITU-R BT.2020"), "nlog": ("log", "N-Log", "N-Gamut"),
    "log3g10": ("log", "Log3G10", "REDWideGamutRGB"),
}
CODIGOS = pl.codigo_de_rgb(np.linspace(0.0, 1.0, 101))


def referencia(tipo, nome, x):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return colour.log_decoding(x, function=nome) if tipo == "log" else colour.oetf_inverse(x, function=nome)


class TestPerfisNovos(unittest.TestCase):
    def test_lista_de_perfis(self):
        for p in NOVOS:
            self.assertIn(p, pl.PERFIS)
            self.assertIn(p, pl.GAMUT_DO_PERFIL)
            self.assertIn(p, pl.CURVAS)
        self.assertEqual(pl.PERFIS[-2:], ("generico", "nenhum"))
        self.assertEqual(len(pl.PERFIS), 20)

    def test_curvas_finitas_e_crescentes(self):
        for p in NOVOS:
            y = pl.CURVAS[p](CODIGOS)
            self.assertTrue(np.all(np.isfinite(y)), p)
            self.assertTrue(np.all(np.diff(y) > 0), p)

    def test_cinza_medio_perto_do_publicado(self):
        # Código (10 bits normalizado) do cinza 18% publicado por cada fabricante.
        publicado = {"slog2": 0.339, "logc3": 0.391, "logc4": 0.278, "applelog": 0.488, "bmdgen5": 0.384,
                     "davinci": 0.336, "clog": 0.343, "clog2": 0.398, "dlog": 0.399, "flog": 0.459, "flog2": 0.391,
                     "protune": 0.646, "llog": 0.435, "nlog": 0.364, "log3g10": 0.333}
        for p, codigo in publicado.items():
            y = pl.CURVAS[p](CODIGOS)
            self.assertAlmostEqual(float(np.interp(0.18, y, CODIGOS)), codigo, delta=0.003, msg=p)

    def test_lut_de_todos(self):
        pasta = Path(tempfile.mkdtemp())
        for p in NOVOS:
            linhas = pl.lut(p, pasta).read_text().splitlines()
            self.assertEqual(linhas[1], f"LUT_3D_SIZE {pl.TAMANHO_LUT}", p)
            valores = np.array([[float(v) for v in l.split()] for l in linhas[4:]])
            self.assertEqual(valores.shape, (pl.TAMANHO_LUT ** 3, 3), p)
            self.assertTrue(np.all((valores >= 0) & (valores <= 1)), p)

    def test_os_de_antes_continuam_iguais(self):
        rgb = np.linspace(0.0, 1.0, 11)
        np.testing.assert_allclose(pl.CURVAS["slog3"](pl.codigo_de_rgb(rgb)), pl.slog3_para_linear(pl.codigo_de_rgb(rgb)))
        np.testing.assert_allclose(pl._para_linear("clog3", rgb), pl.clog3_para_linear(rgb))
        np.testing.assert_allclose(pl._para_linear("vlog", rgb), pl.vlog_para_linear(pl.codigo_de_rgb(rgb)))


class TestContraAColourScience(unittest.TestCase):
    def test_curvas(self):
        for p, (tipo, nome, _) in REFERENCIA.items():
            np.testing.assert_allclose(pl.CURVAS[p](CODIGOS), referencia(tipo, nome, CODIGOS), rtol=1e-6, atol=1e-9,
                                       err_msg=p)

    def test_para_linear_usa_o_codigo_de_10_bits(self):
        rgb = np.linspace(0.0, 1.0, 21)
        for p, (tipo, nome, _) in REFERENCIA.items():
            np.testing.assert_allclose(pl._para_linear(p, rgb), referencia(tipo, nome, pl.codigo_de_rgb(rgb)),
                                       rtol=1e-6, atol=1e-9, err_msg=p)

    def test_gamuts_e_matrizes(self):
        for p, (_, _, gamut) in REFERENCIA.items():
            cs = colour.RGB_COLOURSPACES[gamut]
            np.testing.assert_allclose(np.array(pl.PRIMARIAS[pl.GAMUT_DO_PERFIL[p]]), cs.primaries, atol=1e-6,
                                       err_msg=p)
            esperado = colour.matrix_RGB_to_RGB(cs, colour.RGB_COLOURSPACES["ITU-R BT.709"],
                                                chromatic_adaptation_transform=None)
            np.testing.assert_allclose(pl.matriz_para_709(pl.GAMUT_DO_PERFIL[p]), esperado, atol=1e-4, err_msg=p)


if __name__ == "__main__":
    unittest.main()

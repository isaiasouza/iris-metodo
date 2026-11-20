"""Export em planilha (colunas do Cutdown) e em texto."""
from __future__ import annotations

import csv
import io
import subprocess
import sys
import unittest

from exportar_tabela import COLUNAS, para_csv, para_txt
from tests import test_saida
from tests.test_saida import INFO, NOTA, TRECHOS

CABECALHO_CUTDOWN = ("index,clip_name,source_path,proxy_path,src_tc_in,src_tc_out,tl_tc_in,tl_tc_out,duration,"
                     "mean_score,peak_score,focus,exposure,motion")


class TestCsv(unittest.TestCase):
    def setUp(self):
        self.texto = para_csv(TRECHOS, INFO)
        self.linhas = list(csv.DictReader(io.StringIO(self.texto)))

    def test_cabecalho_comeca_igual_ao_do_cutdown(self):
        cab = self.texto.splitlines()[0]
        self.assertTrue(cab.startswith(CABECALHO_CUTDOWN + ","), cab)
        self.assertEqual(tuple(cab.split(",")), COLUNAS)

    def test_tempos(self):
        a = self.linhas[0]
        self.assertEqual((a["index"], a["clip_name"], a["source_path"], a["proxy_path"]), ("1", "A.MP4", "/m/A.MP4", ""))
        # A_01: 2–4 s a 23,976 → quadros 48–96, somando o timecode do arquivo (1000 quadros).
        self.assertEqual((a["src_tc_in"], a["src_tc_out"]), ("00:00:43:16", "00:00:45:16"))
        self.assertEqual((a["tl_tc_in"], a["tl_tc_out"], a["duration"]), ("00:00:00:00", "00:00:02:00", "00:00:02:00"))
        self.assertEqual(self.linhas[1]["tl_tc_in"], "00:00:02:00")
        self.assertEqual(self.linhas[2]["tl_tc_in"], "00:00:03:00")

    def test_notas(self):
        a = self.linhas[0]
        self.assertEqual((a["mean_score"], a["peak_score"]), ("0.9000", ""))
        self.assertEqual((a["camera"], a["flags"], a["marker_name"]), ("parada", "", "A_01"))


class TestTxt(unittest.TestCase):
    def test_linha(self):
        linhas = para_txt(TRECHOS, INFO).splitlines()
        self.assertEqual(len(linhas), 3)
        self.assertEqual(linhas[0], "01  A.MP4  00:00:43:16–00:00:45:16  (2,0 s)  nota 0,90  pico —  parada  sem flags")

    def test_com_pico_e_flags(self):
        t = dict(TRECHOS[0], pico=0.934, flags=["tremido"])
        self.assertIn("pico 0,93  parada  tremido", para_txt([t], INFO))


class TestCLITabela(test_saida.TestCLI):
    def test_csv_e_txt(self):
        for formato in ("csv", "txt"):
            r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", formato, "--nome", "SEL",
                                "--saida", str(self.saida)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((self.saida / "export" / f"SEL.{formato}").read_text().strip())


if __name__ == "__main__":
    unittest.main()

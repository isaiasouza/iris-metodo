"""Escolha entre original e proxy no export, e timecode em texto."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from exportar import escolher_midia, quadros_em_timecode, trocar_midia


class TestTimecode(unittest.TestCase):
    def test_formata(self):
        self.assertEqual(quadros_em_timecode(86400, 24.0), "01:00:00:00")
        self.assertEqual(quadros_em_timecode(24 * 3661 + 5, 24000 / 1001), "01:01:01:05")
        self.assertEqual(quadros_em_timecode(0, 25.0), "00:00:00:00")
        self.assertEqual(quadros_em_timecode(30 * 59 + 29, 30000 / 1001), "00:00:59:29")


class TestMidia(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_midia_"))
        (self.tmp / "Proxy").mkdir()
        for nome in ("C0001.MP4", "C0002.braw", "C0003.MP4"):
            (self.tmp / nome).write_bytes(b"x")
        (self.tmp / "Proxy" / "C0001.mov").write_bytes(b"x")
        (self.tmp / "Proxy" / "C0002.mov").write_bytes(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def c(self, nome):
        return str(self.tmp / nome)

    def test_original(self):
        self.assertEqual(escolher_midia(self.c("C0001.MP4"), "original"), (self.c("C0001.MP4"), False))

    def test_proxy(self):
        self.assertEqual(escolher_midia(self.c("C0001.MP4"), "proxy"), (str(self.tmp / "Proxy" / "C0001.mov"), False))
        self.assertEqual(escolher_midia(self.c("C0003.MP4"), "proxy"), (self.c("C0003.MP4"), True))

    def test_auto_so_para_o_que_nao_decodifica(self):
        self.assertEqual(escolher_midia(self.c("C0001.MP4"), "auto"), (self.c("C0001.MP4"), False))
        self.assertEqual(escolher_midia(self.c("C0002.braw"), "auto"), (str(self.tmp / "Proxy" / "C0002.mov"), False))

    def test_auto_troca_a_pasta_cinemadng(self):
        (self.tmp / "A001_C003").mkdir()
        (self.tmp / "Proxy" / "A001_C003.mov").write_bytes(b"x")
        self.assertEqual(escolher_midia(self.c("A001_C003"), "auto"), (str(self.tmp / "Proxy" / "A001_C003.mov"), False))
        (self.tmp / "A001_C004").mkdir()
        self.assertEqual(escolher_midia(self.c("A001_C004"), "auto"), (self.c("A001_C004"), True))

    def test_trocar_midia(self):
        trechos = [{"caminho": self.c("C0001.MP4"), "id": "a"}, {"caminho": self.c("C0003.MP4"), "id": "b"},
                   {"caminho": self.c("C0003.MP4"), "id": "c"}]
        novos, faltam = trocar_midia(trechos, "proxy")
        self.assertEqual([t["caminho"] for t in novos],
                         [str(self.tmp / "Proxy" / "C0001.mov"), self.c("C0003.MP4"), self.c("C0003.MP4")])
        self.assertEqual(faltam, ["C0003.MP4"])
        self.assertEqual(trechos[0]["caminho"], self.c("C0001.MP4"))  # não altera a lista de entrada


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2

from relatorio import miniatura
from tests import sinteticos

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")


class TestRelatorio(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_rel_"))
        media = self.tmp / "media"
        media.mkdir()
        c = sinteticos.clipes()
        shutil.copy(c["parado"], media / "A001.mp4")
        shutil.copy(c["corte"], media / "A002.mp4")
        self.saida = self.tmp / "analise"
        for args in (["analisar", str(media), "--sem-hw"], ["selecionar", "--preset", "broll_acao"]):
            subprocess.run([sys.executable, NOTA, *args, "--saida", str(self.saida)], check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_miniatura(self):
        img = miniatura(sinteticos.clipes()["parado"], 1.0)
        self.assertEqual(img.shape[:2], (180, 320))

    def test_relatorio_gera_markdown_e_contact_sheets(self):
        r = subprocess.run([sys.executable, NOTA, "relatorio", "--saida", str(self.saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        selects = json.loads((self.saida / "selects.json").read_text())
        md = (self.saida / "selects.md").read_text()
        self.assertIn("broll_acao", md)
        self.assertTrue(selects["trechos"])
        for t in selects["trechos"]:
            self.assertIn(t["id"], md)
            img = cv2.imread(str(self.saida / "contact" / f"{t['id']}.jpg"))
            self.assertEqual(img.shape[:2], (180, 960))


if __name__ == "__main__":
    unittest.main()

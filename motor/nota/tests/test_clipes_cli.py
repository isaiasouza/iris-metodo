"""Tela inicial do IRISCUT: a lista de clipes com os dados do arquivo antes de analisar, e o progresso por clipe."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import sinteticos

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")


class TestClipes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_clipes_"))
        self.media = self.tmp / "media"
        self.media.mkdir()
        c = sinteticos.clipes()
        shutil.copy(c["parado"], self.media / "A001.mp4")
        shutil.copy(c["pan_esq"], self.media / "A002.mp4")
        (self.media / "quebrado.mp4").write_bytes(b"nao e video")
        (self.media / "notas.txt").write_text("x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lista_os_clipes_com_dados_do_ffprobe(self):
        r = subprocess.run([sys.executable, NOTA, "clipes", str(self.media)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        dados = json.loads(r.stdout)
        self.assertEqual([Path(c["caminho"]).name for c in dados], ["A001.mp4", "A002.mp4", "quebrado.mp4"])
        a = dados[0]
        self.assertGreater(a["duracao"], 0)
        self.assertGreater(a["largura"], 0)
        self.assertGreater(a["fps"], 0)
        self.assertIsNone(a["erro"])
        self.assertTrue(a["online"])
        self.assertIn("tc_inicio_s", a)
        self.assertIsNone(dados[2]["duracao"])
        self.assertTrue(dados[2]["erro"])

    def test_clipe_que_sumiu_sai_offline(self):
        # A lista por clipe do IRISCUT passa os caminhos da revisão, mesmo de um cartão já ejetado.
        r = subprocess.run([sys.executable, NOTA, "clipes", str(self.media / "A001.mp4"), str(self.tmp / "sumiu.mp4")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        sumiu = json.loads(r.stdout)[-1]
        self.assertEqual((Path(sumiu["caminho"]).name, sumiu["online"]), ("sumiu.mp4", False))

    def test_analisar_avisa_cada_clipe_que_comeca(self):
        saida = self.tmp / "analise"
        r = subprocess.run([sys.executable, NOTA, "analisar", str(self.media / "A001.mp4"), str(self.media / "A002.mp4"),
                            "--sem-hw", "--workers", "2", "--saida", str(saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("analisando: "), 2)


if __name__ == "__main__":
    unittest.main()


class TestFormatos(unittest.TestCase):
    def test_lista_extensoes_e_quem_precisa_de_proxy(self):
        r = subprocess.run([sys.executable, NOTA, "formatos"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        por = {f["extensao"]: f["analise"] for f in d["formatos"]}
        self.assertEqual(por[".mp4"], "direta")
        self.assertEqual(por[".braw"], "proxy")
        self.assertEqual(por[".dng"], "proxy")
        self.assertTrue(d["versao_motor"])

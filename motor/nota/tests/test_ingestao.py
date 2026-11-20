"""P2 do PRD: pasta monitorada e proxy automático."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from proxy import achar_proxy
from tests import sinteticos
from vigia import Estabilidade

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")


class TestEstabilidade(unittest.TestCase):
    def test_arquivo_parado_fica_pronto_depois_do_tempo(self):
        e = Estabilidade(estavel_s=10)
        self.assertEqual(e.prontos({"/a": 100}, agora=0), [])
        self.assertEqual(e.prontos({"/a": 100}, agora=5), [])
        self.assertEqual(e.prontos({"/a": 100}, agora=10), ["/a"])

    def test_arquivo_crescendo_reinicia_a_contagem(self):
        e = Estabilidade(estavel_s=10)
        e.prontos({"/a": 100}, agora=0)
        self.assertEqual(e.prontos({"/a": 200}, agora=9), [])
        self.assertEqual(e.prontos({"/a": 200}, agora=15), [])
        self.assertEqual(e.prontos({"/a": 200}, agora=19), ["/a"])

    def test_pronto_so_uma_vez(self):
        e = Estabilidade(estavel_s=0)
        e.prontos({"/a": 1}, agora=0)
        self.assertEqual(e.prontos({"/a": 1}, agora=1), ["/a"])
        self.assertEqual(e.prontos({"/a": 1}, agora=2), [])

    def test_arquivo_que_some_e_esquecido(self):
        e = Estabilidade(estavel_s=0)
        e.prontos({"/a": 1}, agora=0)
        e.prontos({}, agora=1)
        e.prontos({"/a": 1}, agora=2)
        self.assertEqual(e.prontos({"/a": 1}, agora=3), ["/a"])


class TestAcharProxy(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_proxy_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def criar(self, rel):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_pasta_proxy_ao_lado(self):
        orig = self.criar("dia/A001.braw")
        prox = self.criar("dia/Proxy/A001.mp4")
        self.assertEqual(achar_proxy(str(orig)), str(prox))

    def test_pasta_proxies_maiuscula(self):
        orig = self.criar("dia/A002.R3D")
        prox = self.criar("dia/PROXIES/A002.mov")
        self.assertEqual(achar_proxy(str(orig)), str(prox))

    def test_sony_sub(self):
        orig = self.criar("card/PRIVATE/M4ROOT/CLIP/C0001.MP4")
        prox = self.criar("card/PRIVATE/M4ROOT/SUB/C0001S03.MP4")
        self.assertEqual(achar_proxy(str(orig)), str(prox))

    def test_sem_proxy(self):
        self.assertIsNone(achar_proxy(str(self.criar("dia/A003.braw"))))


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_ingest_"))
        self.media = self.tmp / "media"
        self.media.mkdir()
        self.saida = self.tmp / "analise"
        self.c = sinteticos.clipes()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analisar(self):
        return subprocess.run([sys.executable, NOTA, "analisar", str(self.media), "--sem-hw", "--saida",
                               str(self.saida)], capture_output=True, text=True)

    def sidecars(self):
        return [json.loads(f.read_text()) for f in sorted((self.saida / "nota").glob("*.nota.json"))]

    def test_braw_usa_o_proxy_e_aponta_para_o_original(self):
        (self.media / "A001.braw").write_bytes(b"braw que o ffmpeg nao le")
        (self.media / "Proxy").mkdir()
        shutil.copy(self.c["parado"], self.media / "Proxy" / "A001.mp4")
        r = self.analisar()
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.sidecars()
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["caminho"].endswith("A001.braw"))
        self.assertTrue(s[0]["proxy"].endswith("Proxy/A001.mp4"))

    def test_original_quebrado_cai_no_proxy_sony(self):
        clip = self.media / "PRIVATE" / "M4ROOT" / "CLIP"
        sub = self.media / "PRIVATE" / "M4ROOT" / "SUB"
        clip.mkdir(parents=True)
        sub.mkdir(parents=True)
        (clip / "C0001.MP4").write_bytes(b"cartao corrompido")
        shutil.copy(self.c["parado"], sub / "C0001S03.MP4")
        r = self.analisar()
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.sidecars()
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["caminho"].endswith("CLIP/C0001.MP4"))

    def test_braw_sem_proxy_vira_falha_explicada(self):
        (self.media / "A002.braw").write_bytes(b"x")
        self.analisar()
        falhas = json.loads((self.saida / "nota" / "falhas.json").read_text())
        self.assertIn("proxy", next(iter(falhas.values())))

    def test_vigiar_analisa_o_que_chega_e_atualiza_selects(self):
        proc = subprocess.Popen([sys.executable, NOTA, "vigiar", str(self.media), "--sem-hw", "--preset",
                                 "broll_acao", "--saida", str(self.saida), "--intervalo", "0.3", "--estavel", "0.5",
                                 "--ciclos", "12"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.8)
        shutil.copy(self.c["parado"], self.media / "A001.mp4")
        out, err = proc.communicate(timeout=120)
        self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(len(self.sidecars()), 1)
        selects = json.loads((self.saida / "selects.json").read_text())
        self.assertTrue(selects["trechos"])
        self.assertTrue((self.saida / "selects.md").exists())


if __name__ == "__main__":
    unittest.main()

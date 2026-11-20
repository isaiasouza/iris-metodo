"""Proxy casado pelo timecode de início e pela duração quando o nome não bate."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import proxy
from proxy import achar_proxy


@unittest.skipIf(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, "ffmpeg ausente")
class TestProxyPorTimecode(unittest.TestCase):
    def setUp(self):
        proxy._ASSINATURAS.clear()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "Proxy").mkdir()

    def clipe(self, caminho, tc="10:00:00:00", dur=2):
        args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=d={dur}:s=64x36:r=24"]
        if tc:
            args += ["-timecode", tc]
        subprocess.run(args + ["-c:v", "mpeg4", str(caminho)], check=True)
        return str(caminho)

    def test_acha_pelo_timecode_quando_o_nome_nao_bate(self):
        original = self.clipe(self.tmp / "A001.mov")
        renomeado = self.clipe(self.tmp / "Proxy" / "A001_lowres_v2.mov")
        self.assertEqual(achar_proxy(original), renomeado)

    def test_timecode_ou_duracao_diferente_nao_casa(self):
        original = self.clipe(self.tmp / "A001.mov")
        self.clipe(self.tmp / "Proxy" / "X.mov", tc="10:00:05:00")
        self.clipe(self.tmp / "Proxy" / "Y.mov", dur=3)
        self.assertIsNone(achar_proxy(original))

    def test_dois_candidatos_iguais_nao_escolhe(self):
        original = self.clipe(self.tmp / "A001.mov")
        self.clipe(self.tmp / "Proxy" / "X.mov")
        self.clipe(self.tmp / "Proxy" / "Y.mov")
        self.assertIsNone(achar_proxy(original))

    def test_sem_timecode_nao_casa(self):
        original = self.clipe(self.tmp / "A001.mov", tc=None)
        self.clipe(self.tmp / "Proxy" / "X.mov", tc=None)
        self.assertIsNone(achar_proxy(original))

    def test_nome_vence_o_timecode(self):
        original = self.clipe(self.tmp / "A001.mov")
        pelo_nome = self.clipe(self.tmp / "Proxy" / "A001.mov", tc="11:00:00:00")
        self.clipe(self.tmp / "Proxy" / "Z.mov")
        self.assertEqual(achar_proxy(original), pelo_nome)

    def test_sem_pasta_de_proxy_nao_chama_o_ffprobe(self):
        shutil.rmtree(self.tmp / "Proxy")
        original = self.clipe(self.tmp / "A001.mov")
        with mock.patch("proxy.subprocess.run", side_effect=AssertionError("chamou o ffprobe")):
            self.assertIsNone(achar_proxy(original))

    def test_ffprobe_fica_em_cache(self):
        original = self.clipe(self.tmp / "A001.mov")
        renomeado = self.clipe(self.tmp / "Proxy" / "B.mov")
        self.assertEqual(achar_proxy(original), renomeado)
        with mock.patch("proxy.subprocess.run", side_effect=AssertionError("chamou o ffprobe de novo")):
            self.assertEqual(achar_proxy(original), renomeado)

    def test_proxy_de_outro_clipe_nao_e_roubado(self):
        # Câmeras sincronizadas por jam-sync dividem timecode e duração: sem proxy próprio, B não leva o de A.
        a = self.clipe(self.tmp / "A001.mov")
        b = self.clipe(self.tmp / "B001.mov")
        proxy_a = self.clipe(self.tmp / "Proxy" / "A001.mov")
        self.assertIsNone(achar_proxy(b))
        self.assertEqual(achar_proxy(a), proxy_a)

    def test_limite_de_candidatos_nao_chama_o_ffprobe(self):
        original = self.clipe(self.tmp / "A001.mov")
        self.clipe(self.tmp / "Proxy" / "X.mov")
        self.clipe(self.tmp / "Proxy" / "Y.mov")
        with mock.patch.object(proxy, "MAX_CANDIDATOS", 1), \
                mock.patch("proxy.subprocess.run", side_effect=AssertionError("chamou o ffprobe")):
            self.assertIsNone(achar_proxy(original))


if __name__ == "__main__":
    unittest.main()

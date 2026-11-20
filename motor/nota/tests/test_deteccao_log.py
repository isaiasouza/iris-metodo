"""Detecção do perfil de log em câmeras que não são Sony: tags do arquivo (ffprobe) e sidecars de texto."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import perfis_log as pl


class TestTexto(unittest.TestCase):
    def test_nomes_por_fabricante(self):
        casos = {
            "Gamma: S-Log3 / S-Gamut3.Cine": "slog3", "S-Log2": "slog2", "Panasonic V-Log": "vlog",
            "Canon Log 3": "clog3", "C-Log2": "clog2", "Canon Log": "clog", "CLog3": "clog3",
            "ARRI LogC4": "logc4", "Log C3 EI800": "logc3", "LogC": "logc3", "Apple Log": "applelog",
            "Blackmagic Design Film Gen 5": "bmdgen5", "DaVinci Intermediate": "davinci",
            "DJI D-Log": "dlog", "F-Log2": "flog2", "FUJIFILM F-Log": "flog", "N-Log": "nlog",
            "Leica L-Log": "llog", "GoPro Protune Log": "protune", "GP-Log": "protune", "REDWideGamutRGB/Log3G10": "log3g10",
        }
        for texto, esperado in casos.items():
            self.assertEqual(pl.perfil_no_texto(texto), esperado, texto)

    def test_o_mais_especifico_vence(self):
        self.assertEqual(pl.perfil_no_texto("D-Log M"), "generico")
        self.assertEqual(pl.perfil_no_texto("canon log 2"), "clog2")
        self.assertEqual(pl.perfil_no_texto("f-log2 (not f-log)"), "flog2")

    def test_palavras_soltas_nao_contam(self):
        for texto in ("my travel vlog", "blog", "catalog", "logcat", "slogan", "Rec.709", ""):
            self.assertIsNone(pl.perfil_no_texto(texto), texto)


class TestArquivo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_sidecar_de_texto_com_o_mesmo_nome(self):
        video = self.tmp / "A001.MOV"
        video.write_bytes(b"")
        (self.tmp / "A001.xml").write_text("<Clip><Gamma>C-Log2</Gamma></Clip>", encoding="utf-8")
        self.assertEqual(pl.perfil_por_metadados(str(video)), "clog2")
        self.assertEqual(pl.perfil_do_clipe(str(video), "auto"), "clog2")

    def test_panasonic_declara_a_gama(self):
        # XML que a Lumix grava dentro do .MOV (com.panasonic.Semi-Pro.metadata.xml), como os da S1 II.
        casos = {"V-Log": "vlog", "ARRI LogC3": "logc3", "PORTRAIT": "nenhum", "STANDARD": "nenhum", "HLG": "nenhum"}
        for i, (gama, esperado) in enumerate(casos.items()):
            video = self.tmp / f"P10{i}.MOV"
            video.write_bytes(b"")
            (self.tmp / f"P10{i}.xml").write_text(
                f"<Gamma><CaptureGamma>{gama}</CaptureGamma></Gamma><CaptureGamut>AWG3</CaptureGamut>",
                encoding="utf-8")
            self.assertEqual(pl.perfil_por_metadados(str(video)), esperado, gama)
            self.assertEqual(pl.perfil_do_clipe(str(video), "auto"), esperado, gama)

    def test_sem_nada_continua_generico(self):
        video = self.tmp / "B001.MOV"
        video.write_bytes(b"")
        self.assertIsNone(pl.perfil_por_metadados(str(video)))
        self.assertEqual(pl.perfil_do_clipe(str(video), "auto"), "generico")

    def test_sidecar_grande_demais_e_ignorado(self):
        video = self.tmp / "C001.MOV"
        video.write_bytes(b"")
        (self.tmp / "C001.txt").write_text("x" * (1024 * 1024 + 1) + " N-Log", encoding="utf-8")
        self.assertIsNone(pl.perfil_por_metadados(str(video)))

    def test_xml_da_sony_vem_antes(self):
        video = self.tmp / "C0001.MP4"
        video.write_bytes(b"")
        (self.tmp / "C0001M01.XML").write_text(
            '<NonRealTimeMeta><Item name="CaptureGammaEquation" value="s-log3-cine"/></NonRealTimeMeta>',
            encoding="utf-8")
        (self.tmp / "C0001.txt").write_text("V-Log", encoding="utf-8")
        self.assertEqual(pl.perfil_do_clipe(str(video), "auto"), "slog3")

    @unittest.skipIf(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, "ffmpeg ausente")
    def test_tag_do_arquivo_pelo_ffprobe(self):
        video = self.tmp / "D001.mov"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=64x36:r=24",
                        "-metadata", "comment=Nikon Z9 N-Log", "-c:v", "mpeg4", str(video)], check=True)
        self.assertEqual(pl.perfil_por_metadados(str(video)), "nlog")
        outro = self.tmp / "E001.mov"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=64x36:r=24",
                        "-metadata:s:v:0", "handler_name=F-Log2", "-c:v", "mpeg4", str(outro)], check=True)
        self.assertEqual(pl.perfil_por_metadados(str(outro)), "flog2")


if __name__ == "__main__":
    unittest.main()

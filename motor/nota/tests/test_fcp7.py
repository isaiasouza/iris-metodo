"""FCP7 XML (xmeml 5), o formato que o Premiere importa."""
from __future__ import annotations

import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from exportar_fcp7 import para_xml
from tests import test_saida
from tests.test_saida import INFO, NOTA, TRECHOS


class TestXml(unittest.TestCase):
    def setUp(self):
        texto = para_xml(TRECHOS, INFO, "SELECTS")
        self.assertTrue(texto.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'))
        self.raiz = ET.fromstring(texto.split("\n", 2)[2])
        self.seq = self.raiz.find("sequence")

    def test_sequencia(self):
        self.assertEqual((self.raiz.tag, self.raiz.get("version")), ("xmeml", "5"))
        self.assertEqual(self.seq.findtext("name"), "SELECTS")
        self.assertEqual(self.seq.findtext("duration"), "120")
        self.assertEqual((self.seq.findtext("rate/timebase"), self.seq.findtext("rate/ntsc")), ("24", "TRUE"))
        self.assertEqual((self.seq.findtext("timecode/string"), self.seq.findtext("timecode/frame")),
                         ("01:00:00:00", "86400"))
        fmt = self.seq.find("media/video/format/samplecharacteristics")
        self.assertEqual((fmt.findtext("width"), fmt.findtext("height")), ("3840", "2160"))

    def test_clipes_de_video(self):
        clips = self.seq.findall("media/video/track/clipitem")
        self.assertEqual([c.findtext("name") for c in clips], ["A_01", "B_01", "A_02"])
        self.assertEqual([(c.findtext("start"), c.findtext("end")) for c in clips],
                         [("0", "48"), ("48", "72"), ("72", "120")])
        # in/out contam do começo do arquivo; o timecode fica no <file>.
        self.assertEqual((clips[0].findtext("in"), clips[0].findtext("out")), ("48", "96"))
        arq = clips[0].find("file")
        self.assertEqual(arq.get("id"), "file-1")
        self.assertEqual(arq.findtext("pathurl"), "file://localhost/m/A.MP4")
        self.assertEqual(arq.findtext("timecode/frame"), "1000")
        self.assertEqual(arq.findtext("duration"), "2400")
        repetido = clips[2].find("file")
        self.assertEqual((repetido.get("id"), len(list(repetido))), ("file-1", 0))
        self.assertEqual((clips[0].findtext("marker/name"), clips[0].findtext("marker/comment")), ("A_01", "m"))
        self.assertEqual(clips[0].findtext("labels/label2"), "Green")

    def test_audio(self):
        clips = self.seq.findall("media/audio/track/clipitem")
        self.assertEqual(len(clips), 3)
        self.assertEqual(clips[1].find("file").get("id"), "file-2")
        self.assertEqual(clips[0].findtext("sourcetrack/mediatype"), "audio")

    def test_imagem_e_som_ligados(self):
        for trilha in ("video", "audio"):
            clip = self.seq.findall(f"media/{trilha}/track/clipitem")[1]
            self.assertEqual([(l.findtext("linkclipref"), l.findtext("mediatype"), l.findtext("trackindex"),
                               l.findtext("clipindex")) for l in clip.findall("link")],
                             [("clipitem-v2", "video", "1", "2"), ("clipitem-a2", "audio", "1", "2")])

    def test_caminho_com_espaco(self):
        t = dict(TRECHOS[0], caminho="/Volumes/LaCie/DAY 3/A.MP4")
        info = {"/Volumes/LaCie/DAY 3/A.MP4": INFO["/m/A.MP4"]}
        raiz = ET.fromstring(para_xml([t], info, "S").split("\n", 2)[2])
        self.assertEqual(raiz.findtext(".//file/pathurl"), "file://localhost/Volumes/LaCie/DAY%203/A.MP4")


class TestCLIXml(test_saida.TestCLI):
    def test_xml(self):
        r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", "xml", "--nome", "SEL",
                            "--saida", str(self.saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        ET.fromstring((self.saida / "export" / "SEL.xml").read_text().split("\n", 2)[2])


if __name__ == "__main__":
    unittest.main()

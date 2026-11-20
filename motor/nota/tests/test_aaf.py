"""AAF (Avid) com pyaaf2: escreve e lê de volta."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from exportar import info_clipe, quadros_do_trecho, timecode_em_quadros
from tests import sinteticos
from tests import test_saida
from tests.test_saida import NOTA

try:
    import aaf2
except ImportError:  # pragma: no cover
    aaf2 = None


def trecho(caminho, inicio, fim, ident, nota=0.9):
    return {"id": ident, "caminho": caminho, "inicio_s": inicio, "fim_s": fim, "nota": nota, "flags": [],
            "camera": {"tipo": "parada", "confianca": 1.0}, "motivo": "m", "marcador": {"nome": ident, "nota": "m"}}


@unittest.skipIf(aaf2 is None, "pyaaf2 não instalado")
class TestAaf(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_aaf_"))
        self.clipe = str(self.tmp / "A001.mp4")
        shutil.copy(sinteticos.clipes()["parado"], self.clipe)
        self.info = {self.clipe: info_clipe(self.clipe)}
        self.trechos = [trecho(self.clipe, 0.5, 1.5, "A_01"), trecho(self.clipe, 2.0, 2.5, "A_02")]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_escreve_e_le_de_volta(self):
        from exportar_aaf import escrever_aaf
        destino = self.tmp / "SEL.aaf"
        escrever_aaf(self.trechos, self.info, "SEL", destino)
        self.assertFalse(destino.with_name("SEL.aaf.tmp").exists())
        fps = self.info[self.clipe]["fps"]
        esperado = [quadros_do_trecho(t, fps) for t in self.trechos]
        with aaf2.open(str(destino), "r") as f:
            comp = next(f.content.compositionmobs())
            self.assertEqual(comp.name, "SEL")
            imagem = next(s for s in comp.slots if s.media_kind == "Picture")
            clips = list(imagem.segment.components)
            self.assertEqual([(c.start, c.length) for c in clips], esperado)
            marcas = [c for s in comp.slots if s.media_kind == "DescriptiveMetadata" for c in s.segment.components]
            self.assertEqual([m["CommentMarkerUser"].value for m in marcas], ["A_01", "A_02"])
            self.assertEqual([m["Position"].value for m in marcas], [0, esperado[0][1]])

    def test_estrutura_classica_sem_ama(self):
        """MasterMob → file mob (CDCI + NetworkLocator) → tape mob, sem MultipleDescriptor/ImportDescriptor."""
        from exportar_aaf import escrever_aaf
        destino = self.tmp / "SEL.aaf"
        escrever_aaf(self.trechos, self.info, "SEL", destino)
        with aaf2.open(str(destino), "r") as f:
            tipos = {type(m.descriptor).__name__ for m in f.content.sourcemobs()}
            self.assertEqual(tipos, {"CDCIDescriptor", "TapeDescriptor"})  # o clipe sintético não tem som
            mestres = list(f.content.mastermobs())
            self.assertEqual([m.name for m in mestres], ["A001"])
            self.assertEqual([s.media_kind for s in mestres[0].slots], ["Picture"])
            arquivo = mestres[0].slots[0].segment.mob
            self.assertEqual(arquivo.name, "A001")
            loc = arquivo.descriptor["Locator"].value[0]["URLString"].value
            self.assertEqual(loc, Path(self.clipe).as_uri())
            self.assertEqual(arquivo.descriptor["StoredWidth"].value, self.info[self.clipe]["largura"])
            comp = next(f.content.compositionmobs())
            som = next(s for s in comp.slots if s.media_kind == "Sound")
            self.assertEqual([type(c).__name__ for c in som.segment.components], ["Filler", "Filler"])

    def test_url_codificada(self):
        from exportar_aaf import escrever_aaf
        pasta = self.tmp / "DAY 3 11.05.2026"
        pasta.mkdir()
        clipe = str(pasta / "C0001.MP4")
        shutil.copy(self.clipe, clipe)
        destino = self.tmp / "SEL.aaf"
        escrever_aaf([trecho(clipe, 0.5, 1.5, "A_01")], {clipe: self.info[self.clipe]}, "SEL", destino)
        with aaf2.open(str(destino), "r") as f:
            urls = {m.descriptor["Locator"].value[0]["URLString"].value
                    for m in f.content.sourcemobs() if "Locator" in m.descriptor}
        self.assertEqual(urls, {"file://" + str(self.tmp).replace(" ", "%20") + "/DAY%203%2011.05.2026/C0001.MP4"})

    @unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg ausente")
    def test_erros_com_nome_do_arquivo(self):
        from exportar_aaf import escrever_aaf
        wav = self.tmp / "SOM01.WAV"  # só áudio: o AAF só leva clipes com imagem
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                        "-t", "1", str(wav)], check=True)
        for caminho in (str(wav), str(self.tmp / "sumiu.mp4")):
            with self.subTest(caminho=caminho):
                info = {caminho: self.info[self.clipe]}
                destino = self.tmp / "SEL.aaf"
                with self.assertRaises(RuntimeError) as ctx:
                    escrever_aaf([trecho(caminho, 0.5, 1.5, "A_01")], info, "SEL", destino)
                self.assertIn(Path(caminho).name, str(ctx.exception))
                self.assertFalse(destino.exists())
                self.assertFalse(destino.with_name("SEL.aaf.tmp").exists())

    @unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg ausente")
    def test_mts_agora_entra(self):
        """MPEG-TS (AVCHD) não passava pelo link AMA; na estrutura clássica é só um locator."""
        from exportar_aaf import escrever_aaf
        mts = self.tmp / "C0001.MTS"
        subprocess.run(["ffmpeg", "-v", "error", "-i", self.clipe, "-c", "copy", "-f", "mpegts", str(mts)], check=True)
        destino = self.tmp / "SEL.aaf"
        escrever_aaf([trecho(str(mts), 0.5, 1.5, "A_01")], {str(mts): info_clipe(str(mts))}, "SEL", destino)
        with aaf2.open(str(destino), "r") as f:
            self.assertEqual([m.name for m in f.content.mastermobs()], ["C0001"])

    def _video_sem_contagem(self, **extra):
        v = {"codec_type": "video", "width": 640, "height": 360, "avg_frame_rate": "24/1"}
        v.update(extra)
        return {"streams": [v], "format": {}}

    def test_sem_nb_frames_nem_duracao_usa_info(self):
        import exportar_aaf
        destino = self.tmp / "SEL.aaf"
        info = {self.clipe: dict(self.info[self.clipe], duracao_quadros=500)}
        with mock.patch.object(exportar_aaf, "_ffprobe", return_value=self._video_sem_contagem()):
            exportar_aaf.escrever_aaf(self.trechos, info, "SEL", destino)
        with aaf2.open(str(destino), "r") as f:
            arquivo = next(f.content.mastermobs()).slots[0].segment.mob
            self.assertEqual(arquivo.descriptor["Length"].value, 500)
            self.assertEqual(arquivo.slots[0].segment.length, 500)

    def test_trecho_alem_da_contagem_estende_a_midia(self):
        import exportar_aaf
        destino = self.tmp / "SEL.aaf"
        info = {self.clipe: dict(self.info[self.clipe], duracao_quadros=10)}
        fps = info[self.clipe]["fps"]
        fim = sum(quadros_do_trecho(self.trechos[-1], fps))
        with mock.patch.object(exportar_aaf, "_ffprobe", return_value=self._video_sem_contagem()):
            exportar_aaf.escrever_aaf(self.trechos, info, "SEL", destino)
        with aaf2.open(str(destino), "r") as f:
            arquivo = next(f.content.mastermobs()).slots[0].segment.mob
            self.assertEqual(arquivo.descriptor["Length"].value, fim)

    def test_sem_contagem_nenhuma_da_erro(self):
        import exportar_aaf
        destino = self.tmp / "SEL.aaf"
        info = {self.clipe: dict(self.info[self.clipe], duracao_quadros=0)}
        with mock.patch.object(exportar_aaf, "_ffprobe", return_value=self._video_sem_contagem()):
            with self.assertRaises(RuntimeError) as ctx:
                exportar_aaf.escrever_aaf(self.trechos, info, "SEL", destino)
        self.assertIn("A001.mp4", str(ctx.exception))
        self.assertFalse(destino.exists())
        self.assertFalse(destino.with_name("SEL.aaf.tmp").exists())

    def test_aspecto_invalido_cai_para_largura_altura(self):
        import exportar_aaf
        for aspecto in ("0:1", "1:0", "N/A", ""):
            with self.subTest(aspecto=aspecto):
                destino = self.tmp / "SEL.aaf"
                meta = self._video_sem_contagem(nb_frames="200", display_aspect_ratio=aspecto)
                with mock.patch.object(exportar_aaf, "_ffprobe", return_value=meta):
                    exportar_aaf.escrever_aaf(self.trechos, self.info, "SEL", destino)
                with aaf2.open(str(destino), "r") as f:
                    d = next(f.content.mastermobs()).slots[0].segment.mob.descriptor
                    self.assertEqual(d["ImageAspectRatio"].value, aaf2.rational.AAFRational(16, 9))

    def test_capa_embutida_nao_conta_como_video(self):
        import exportar_aaf
        meta = {"streams": [{"codec_type": "audio", "sample_rate": "44100", "channels": 2, "duration": "3.0"},
                            {"codec_type": "video", "codec_name": "mjpeg", "width": 600, "height": 600,
                             "disposition": {"attached_pic": 1}}], "format": {"duration": "3.0"}}
        destino = self.tmp / "SEL.aaf"
        with mock.patch.object(exportar_aaf, "_ffprobe", return_value=meta):
            with self.assertRaises(RuntimeError) as ctx:
                exportar_aaf.escrever_aaf(self.trechos, self.info, "SEL", destino)
        self.assertIn("A001.mp4", str(ctx.exception))
        self.assertIn("não tem imagem", str(ctx.exception))

    def test_sem_pyaaf2(self):
        import exportar_aaf
        with mock.patch.dict(sys.modules, {"aaf2": None}):
            with self.assertRaises(exportar_aaf.SemPyaaf2) as ctx:
                exportar_aaf.escrever_aaf(self.trechos, self.info, "SEL", self.tmp / "x.aaf")
        self.assertIn("pip install --user pyaaf2", str(ctx.exception))


@unittest.skipIf(aaf2 is None or shutil.which("ffmpeg") is None, "pyaaf2 ou ffmpeg ausente")
class TestAafComAudio(unittest.TestCase):
    """Clipe 23.976 com som estéreo e TC 23:17:27:00, como os MP4 da Sony."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_aaf_audio_"))
        self.clipe = str(self.tmp / "C0001.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24000/1001",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-ac", "2", "-t", "4",
                        "-c:v", "libx264", "-c:a", "aac", "-timecode", "23:17:27:00", self.clipe], check=True)
        self.info = {self.clipe: info_clipe(self.clipe)}
        self.trechos = [trecho(self.clipe, 1.0, 2.0, "C_01"), trecho(self.clipe, 2.5, 3.5, "C_02")]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_imagem_e_som_alinhados_e_timecode(self):
        from exportar_aaf import escrever_aaf
        destino = self.tmp / "SEL.aaf"
        escrever_aaf(self.trechos, self.info, "SEL", destino)
        fps = self.info[self.clipe]["fps"]
        esperado = [quadros_do_trecho(t, fps) for t in self.trechos]
        self.assertEqual(esperado, [(24, 24), (60, 24)])
        taxa = aaf2.rational.AAFRational(24000, 1001)
        with aaf2.open(str(destino), "r") as f:
            comp = next(f.content.compositionmobs())
            self.assertEqual([(s.slot_id, s.media_kind) for s in comp.slots],
                             [(1, "Timecode"), (2, "Picture"), (3, "Sound"), (4, "DescriptiveMetadata")])
            slots = {s.media_kind: s for s in comp.slots}
            self.assertTrue(all(s.edit_rate == taxa for s in comp.slots))
            tc_comp = slots["Timecode"].segment
            self.assertEqual((tc_comp.start, tc_comp.fps, tc_comp.length), (24 * 3600, 24, 48))
            imagem = [(c.start, c.length) for c in slots["Picture"].segment.components]
            som = [(c.start, c.length) for c in slots["Sound"].segment.components]
            self.assertEqual(imagem, esperado)
            self.assertEqual(som, esperado)
            self.assertTrue(all(c.media_kind == "Sound" for c in slots["Sound"].segment.components))
            marcas = list(slots["DescriptiveMetadata"].segment.components)
            self.assertEqual([(m["Position"].value, m["CommentMarkerUser"].value) for m in marcas],
                             [(0, "C_01"), (24, "C_02")])

            mestre = next(f.content.mastermobs())
            self.assertEqual(mestre.name, "C0001")
            self.assertEqual([(s.slot_id, s.media_kind, s.edit_rate) for s in mestre.slots],
                             [(1, "Picture", taxa), (2, "Sound", taxa)])
            self.assertTrue(all(c.mob is mestre or c.mob.mob_id == mestre.mob_id
                                for s in (slots["Picture"], slots["Sound"]) for c in s.segment.components))
            self.assertEqual([c.slot_id for c in slots["Picture"].segment.components], [1, 1])
            self.assertEqual([c.slot_id for c in slots["Sound"].segment.components], [2, 2])

            url = Path(self.clipe).as_uri()
            quadros = self.info[self.clipe]["duracao_quadros"]
            arq_img = mestre.slots[0].segment.mob
            arq_som = mestre.slots[1].segment.mob
            d_img, d_som = arq_img.descriptor, arq_som.descriptor
            self.assertEqual(type(d_img).__name__, "CDCIDescriptor")
            self.assertEqual((d_img["StoredWidth"].value, d_img["StoredHeight"].value), (320, 240))
            self.assertEqual((d_img["SampleRate"].value, d_img["Length"].value), (taxa, quadros))
            self.assertEqual(d_img["Locator"].value[0]["URLString"].value, url)
            self.assertEqual(type(d_som).__name__, "PCMDescriptor")
            self.assertEqual((d_som["AudioSamplingRate"].value, d_som["SampleRate"].value), (48000, 48000))
            self.assertEqual((d_som["Channels"].value, d_som["QuantizationBits"].value), (2, 16))
            self.assertAlmostEqual(d_som["Length"].value, 4 * 48000, delta=2048)
            self.assertEqual(d_som["Locator"].value[0]["URLString"].value, url)
            self.assertEqual([(s.media_kind, s.edit_rate) for s in arq_som.slots], [("Sound", taxa)])

            for arq, tipo in ((arq_img, "Picture"), (arq_som, "Sound")):
                with self.subTest(tipo=tipo):
                    ref = arq.slots[0].segment
                    self.assertEqual((ref.slot_id, ref.start, ref.length), (2, 0, quadros))
                    fita = ref.mob
                    self.assertEqual(type(fita.descriptor).__name__, "TapeDescriptor")
                    self.assertEqual([s.media_kind for s in fita.slots], ["Timecode", tipo])
                    tc = fita.slots[0].segment
                    self.assertEqual(tc.start, timecode_em_quadros("23:17:27:00", fps))
                    self.assertEqual(tc.start, self.info[self.clipe]["tc_inicio"])
                    self.assertEqual((tc.fps, tc["Drop"].value), (24, False))
                    self.assertIsNone(fita.slots[1].segment.mob)


@unittest.skipIf(aaf2 is None or shutil.which("ffmpeg") is None, "pyaaf2 ou ffmpeg ausente")
class TestAafFormatosDeAudio(unittest.TestCase):
    """PCMDescriptor tirado do stream: mono, 24 bits; 16 bits estéreo fica igual ao do Resolve."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_aaf_pcm_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pcm(self, nome, args):
        clipe = str(self.tmp / nome)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
                        "-c:v", "libx264"] + args + [clipe], check=True)
        from exportar_aaf import escrever_aaf
        destino = self.tmp / "SEL.aaf"
        escrever_aaf([trecho(clipe, 0.5, 1.5, "P_01")], {clipe: info_clipe(clipe)}, "SEL", destino)
        with aaf2.open(str(destino), "r") as f:
            d = next(f.content.mastermobs()).slots[1].segment.mob.descriptor
            return {k: d[k].value for k in ("Channels", "QuantizationBits", "BlockAlign", "AverageBPS")}

    def test_mono_16(self):
        self.assertEqual(self._pcm("M.mov", ["-ac", "1", "-c:a", "pcm_s16le"]),
                         {"Channels": 1, "QuantizationBits": 16, "BlockAlign": 2, "AverageBPS": 96000})

    def test_estereo_16_igual_ao_resolve(self):
        self.assertEqual(self._pcm("E.mov", ["-ac", "2", "-c:a", "pcm_s16be"]),
                         {"Channels": 2, "QuantizationBits": 16, "BlockAlign": 2, "AverageBPS": 96000})

    def test_24_bits(self):
        self.assertEqual(self._pcm("V.mov", ["-ac", "2", "-c:a", "pcm_s24le"]),
                         {"Channels": 2, "QuantizationBits": 24, "BlockAlign": 3, "AverageBPS": 144000})

    def test_aac_vai_como_16(self):
        self.assertEqual(self._pcm("A.mp4", ["-ac", "1", "-c:a", "aac"])["QuantizationBits"], 16)


@unittest.skipIf(aaf2 is None, "pyaaf2 não instalado")
class TestCLIAaf(test_saida.TestCLI):
    def test_aaf(self):
        r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", "aaf", "--nome", "SEL",
                            "--saida", str(self.saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.saida / "export" / "SEL.aaf").stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()

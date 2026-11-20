"""P3 do PRD: campos personalizados no marcador e no relatório, export OpenTimelineIO e FCPXML."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import presets
from davinci import planejar_marcadores
from exportar import fps_racional, para_fcpxml, para_otio, timecode_em_quadros
from segmentos import trechos_do_clipe, valores_trecho
from tests import sinteticos
from tests.test_segmentos import DT, preset, quadros_fake

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")
FPS = 24000 / 1001


def sidecar(nome="A.MP4", n=40):
    return {"caminho": f"/m/{nome}", "fps": FPS, "duracao": n * DT, "amostras_por_s": 1 / DT,
            "quadros": quadros_fake(n)}


class TestCampos(unittest.TestCase):
    def test_padrao_e_id_e_motivo(self):
        t = trechos_do_clipe(sidecar(), preset())[0][0]
        self.assertEqual(t["marcador"], {"nome": t["id"], "nota": t["motivo"]})

    def test_modelo_personalizado(self):
        p = preset()
        p["campos"]["marcador_nome"] = "{clipe} · {nota} · {camera}"
        t = trechos_do_clipe(sidecar(), p)[0][0]
        nota = f"{t['nota']:.2f}".replace(".", ",")
        self.assertEqual(t["marcador"]["nome"], f"A.MP4 · {nota} · {t['camera']['tipo']}")

    def test_campo_desconhecido_e_recusado(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "p.json"
            arq.write_text(json.dumps({"campos": {"marcador_nome": "{inexistente}"}}))
            with self.assertRaises(ValueError):
                presets.carregar(str(arq))
            arq.write_text(json.dumps({"campos": {"relatorio": ["foco", "nao_existe"]}}))
            with self.assertRaises(ValueError):
                presets.carregar(str(arq))

    def test_valores_disponiveis(self):
        t = trechos_do_clipe(sidecar(), preset())[0][0]
        v = valores_trecho(t)
        for chave in ("id", "clipe", "nota", "duracao", "camera", "confianca", "flags", "motivo", "foco",
                      "exposicao", "estabilidade", "movimento", "inicio", "fim"):
            self.assertIn(chave, v)

    def test_davinci_usa_o_marcador_do_trecho(self):
        t = {"id": "A-1_01", "caminho": "/m/A.MP4", "inicio_s": 0.0, "fim_s": 2.0, "nota": 0.9, "motivo": "m",
             "marcador": {"nome": "personalizado", "nota": "nota livre"}}
        novos, _, _ = planejar_marcadores([t], {"/m/A.MP4": (FPS, set())})
        self.assertEqual((novos[0]["nome"], novos[0]["nota"]), ("personalizado", "nota livre"))


class TestTempo(unittest.TestCase):
    def test_fps_racional(self):
        self.assertEqual(fps_racional(FPS), Fraction(24000, 1001))
        self.assertEqual(fps_racional(25.0), Fraction(25))
        self.assertEqual(fps_racional(30000 / 1001), Fraction(30000, 1001))

    def test_timecode(self):
        self.assertEqual(timecode_em_quadros("23:17:27:00", FPS), (23 * 3600 + 17 * 60 + 27) * 24)
        self.assertEqual(timecode_em_quadros("00:00:01:05", 25.0), 30)
        self.assertEqual(timecode_em_quadros(None, 25.0), 0)


def trecho(caminho, inicio, fim, ident):
    return {"id": ident, "caminho": caminho, "inicio_s": inicio, "fim_s": fim, "fps": FPS, "nota": 0.9,
            "flags": [], "camera": {"tipo": "parada", "confianca": 1.0}, "motivo": "m",
            "marcador": {"nome": ident, "nota": "m"}}


INFO = {"/m/A.MP4": {"fps": FPS, "largura": 3840, "altura": 2160, "duracao_quadros": 2400, "tc_inicio": 1000},
        "/m/B.MP4": {"fps": FPS, "largura": 3840, "altura": 2160, "duracao_quadros": 480, "tc_inicio": 0}}
TRECHOS = [trecho("/m/A.MP4", 2.0, 4.0, "A_01"), trecho("/m/B.MP4", 0.0, 1.0, "B_01"), trecho("/m/A.MP4", 10.0, 12.0, "A_02")]


class TestOtio(unittest.TestCase):
    def test_estrutura(self):
        o = para_otio(TRECHOS, INFO, "SELECTS")
        self.assertEqual(o["OTIO_SCHEMA"], "Timeline.1")
        clips = o["tracks"]["children"][0]["children"]
        self.assertEqual([c["name"] for c in clips], ["A_01", "B_01", "A_02"])
        r = clips[0]["source_range"]
        self.assertEqual((r["start_time"]["value"], r["duration"]["value"]), (1000 + 48, 48))
        self.assertAlmostEqual(r["start_time"]["rate"], FPS)
        self.assertEqual(clips[0]["media_reference"]["target_url"], "/m/A.MP4")
        self.assertEqual([t["kind"] for t in o["tracks"]["children"]], ["Video", "Audio"])
        self.assertEqual(clips[0]["markers"][0]["metadata"]["Resolve_OTIO"]["Note"], "m")
        self.assertEqual(clips[0]["markers"][0]["name"], "A_01")
        self.assertEqual(o["global_start_time"]["value"], 86400)
        json.dumps(o)


class TestFcpxml(unittest.TestCase):
    def setUp(self):
        self.raiz = ET.fromstring(para_fcpxml(TRECHOS, INFO, "SELECTS").split("\n", 2)[2])

    def test_assets_e_formatos(self):
        self.assertEqual(self.raiz.get("version"), "1.14")
        self.assertEqual(len(self.raiz.findall("./resources/asset")), 2)
        fmt = self.raiz.find("./resources/format")
        self.assertEqual((fmt.get("frameDuration"), fmt.get("width")), ("1001/24000s", "3840"))
        self.assertEqual(fmt.get("colorSpace"), "1-1-1 (Rec. 709)")
        a = self.raiz.find("./resources/asset[@name='A.MP4']")
        # O Final Cut não lê o timecode de MP4 (conferido com os MP4 da Sony): o asset começa em 0.
        self.assertEqual(a.get("start"), "0s")
        self.assertEqual(a.find("media-rep").get("src"), "file:///m/A.MP4")

    def test_mov_usa_o_timecode_do_arquivo(self):
        info = {"/m/C.MOV": dict(INFO["/m/A.MP4"])}
        raiz = ET.fromstring(para_fcpxml([trecho("/m/C.MOV", 2.0, 4.0, "C_01")], info, "S").split("\n", 2)[2])
        self.assertEqual(raiz.find("./resources/asset").get("start"), "1001000/24000s")
        clip = raiz.find(".//spine/asset-clip")
        self.assertEqual(clip.get("start"), f"{(1000 + 48) * 1001}/24000s")
        self.assertEqual(clip.find("marker").get("start"), f"{(1000 + 48) * 1001}/24000s")

    def test_clipes_em_sequencia_com_timecode(self):
        clips = self.raiz.findall(".//spine/asset-clip")
        self.assertEqual([c.get("name") for c in clips], ["A_01", "B_01", "A_02"])
        self.assertEqual([c.get("offset") for c in clips], ["0s", "48048/24000s", "72072/24000s"])
        self.assertEqual(clips[0].get("start"), "48048/24000s")
        self.assertEqual(clips[0].get("duration"), "48048/24000s")
        self.assertEqual(clips[0].find("marker").get("value"), "A_01")
        self.assertEqual(clips[0].find("marker").get("start"), "48048/24000s")
        seq = self.raiz.find(".//sequence")
        self.assertEqual((seq.get("audioLayout"), seq.get("audioRate")), ("stereo", "48k"))
        self.assertEqual(seq.get("duration"), "120120/24000s")
        self.assertEqual(seq.get("tcStart"), f"{86400 * 1001}/24000s")


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_exp_"))
        media = self.tmp / "media"
        media.mkdir()
        shutil.copy(sinteticos.clipes()["parado"], media / "A001.mp4")
        self.saida = self.tmp / "analise"
        for a in (["analisar", str(media), "--sem-hw"], ["selecionar", "--preset", "broll_acao"]):
            subprocess.run([sys.executable, NOTA, *a, "--saida", str(self.saida)], check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exporta_os_dois_formatos(self):
        for formato in ("otio", "fcpxml"):
            r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", formato, "--nome", "SEL",
                                "--saida", str(self.saida)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((self.saida / "export" / f"SEL.{formato}").exists())

    def test_exporta_de_outro_selects_do_trabalho(self):
        # O painel de seleção grava selects_painel.json; o export do painel sai dele, não do selects.json.
        (self.saida / "selects.json").rename(self.saida / "selects_painel.json")
        r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", "csv", "--nome", "SEL", "--selects",
                            "selects_painel.json", "--saida", str(self.saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.saida / "export" / "SEL.csv").exists())
        r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", "csv", "--nome", "SEL", "--selects",
                            "../fora.json", "--saida", str(self.saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_midia_proxy_avisa_quando_falta(self):
        r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", "otio", "--nome", "SEL", "--midia", "proxy",
                            "--saida", str(self.saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("aviso: sem proxy para 1 clipe(s): A001.mp4", r.stdout)

    def test_midia_proxy_usa_o_proxy(self):
        proxy = self.tmp / "media" / "Proxy"
        proxy.mkdir()
        shutil.copy(self.tmp / "media" / "A001.mp4", proxy / "A001.mov")
        r = subprocess.run([sys.executable, NOTA, "exportar", "--formato", "otio", "--nome", "SEL", "--midia", "proxy",
                            "--saida", str(self.saida)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        o = json.loads((self.saida / "export" / "SEL.otio").read_text())
        ref = o["tracks"]["children"][0]["children"][0]["media_reference"]["target_url"]
        self.assertEqual(ref, str((proxy / "A001.mov").resolve()))

    def test_relatorio_com_coluna_extra(self):
        preset_arq = self.tmp / "p.json"
        preset_arq.write_text(json.dumps({"campos": {"relatorio": ["movimento", "confianca"]}}))
        subprocess.run([sys.executable, NOTA, "selecionar", "--preset", str(preset_arq), "--saida", str(self.saida)],
                       check=True, capture_output=True)
        subprocess.run([sys.executable, NOTA, "relatorio", "--saida", str(self.saida)], check=True,
                       capture_output=True)
        md = (self.saida / "selects.md").read_text()
        cabecalho = next(linha for linha in md.splitlines() if linha.startswith("| # |"))
        self.assertTrue(cabecalho.endswith("| movimento | confianca |"), cabecalho)


if __name__ == "__main__":
    unittest.main()

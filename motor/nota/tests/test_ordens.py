"""Ordens de importação do Cutdown: alfabética, data de gravação e timecode de origem."""
from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import davinci
import decisoes
import proxy
from exportar import com_metadados, metadados_clipe
from segmentos import ORDENS, ORDENS_ORIGEM, _ordenar
from tests import sinteticos


def T(caminho, inicio=0.0, **over):
    t = {"id": f"{Path(caminho).stem}_{int(inicio)}", "caminho": caminho, "inicio_s": inicio, "fim_s": inicio + 2.0,
         "duracao_s": 2.0, "nota": 0.8}
    t.update(over)
    return t


class TestChaves(unittest.TestCase):
    def ordem(self, trechos, nome):
        lista = list(trechos)
        _ordenar(lista, nome)
        return [t["id"] for t in lista]

    def test_ordens_novas_existem_em_todo_lugar(self):
        for nome in ("alfabetica", "data", "timecode"):
            self.assertIn(nome, ORDENS)
            self.assertIn(nome, ORDENS_ORIGEM)
            self.assertIn(nome, davinci._ORDENS)

    def test_alfabetica_ignora_a_pasta(self):
        trechos = [T("/b/A.MP4"), T("/a/b.MP4"), T("/a/a2.MP4", 5.0), T("/a/a2.MP4", 1.0)]
        self.assertEqual(self.ordem(trechos, "alfabetica"), ["A_0", "a2_1", "a2_5", "b_0"])

    def test_data_com_os_sem_data_no_fim(self):
        trechos = [T("/m/X.MP4", gravado_em="2026-05-11T15:00:00Z"), T("/m/Y.MP4", gravado_em="2026-05-11T09:00:00Z"),
                   T("/m/A.MP4", gravado_em=None), T("/m/Z.MP4")]
        self.assertEqual(self.ordem(trechos, "data"), ["Y_0", "X_0", "A_0", "Z_0"])

    def test_timecode_soma_o_inicio_do_trecho(self):
        trechos = [T("/m/X.MP4", 5.0, tc_origem_s=100.0), T("/m/Y.MP4", 0.0, tc_origem_s=102.0),
                   T("/m/X.MP4", 1.0, tc_origem_s=100.0), T("/m/S.MP4", 0.0)]
        self.assertEqual(self.ordem(trechos, "timecode"), ["X_1", "Y_0", "X_5", "S_0"])

    def test_davinci_e_decisoes_usam_as_mesmas_chaves(self):
        trechos = [T("/m/X.MP4", 5.0, tc_origem_s=100.0), T("/m/Y.MP4", 0.0, tc_origem_s=102.0)]
        self.assertEqual([t["id"] for t in sorted(trechos, key=davinci._ORDENS["timecode"])], ["Y_0", "X_5"])
        self.assertEqual([t["id"] for t in decisoes.ordenar(trechos, "timecode")], ["Y_0", "X_5"])

    def test_revisao_copia_os_campos(self):
        t = T("/m/X.MP4", tc_origem_s=36000.0, gravado_em="2026-05-11T15:00:00Z", fps=24.0,
              camera={"tipo": "parada", "confianca": 1.0}, flags=[])
        rev = decisoes.montar([t], [(86400, 86448)], selects="/a/s.json", projeto="P", timeline="R",
                              fps_timeline=24.0, inicio_timeline=86400)
        self.assertEqual(rev["trechos"][0]["tc_origem_s"], 36000.0)
        self.assertEqual(rev["trechos"][0]["gravado_em"], "2026-05-11T15:00:00Z")


@unittest.skipIf(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, "ffmpeg ausente")
class TestMetadados(unittest.TestCase):
    def setUp(self):
        proxy._ASSINATURAS.clear()
        self.tmp = Path(tempfile.mkdtemp())

    def clipe(self, nome, *extra):
        caminho = self.tmp / nome
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=64x36:r=24", *extra,
                        "-c:v", "mpeg4", str(caminho)], check=True)
        return str(caminho)

    def test_timecode_e_data_do_arquivo(self):
        c = self.clipe("A.mov", "-timecode", "10:00:00:12", "-metadata", "creation_time=2026-05-11T14:03:22Z")
        self.assertEqual(metadados_clipe(c), {"tc_origem_s": 36000.5, "gravado_em": "2026-05-11T14:03:22Z"})

    def test_sem_creation_time_usa_a_data_de_modificacao(self):
        c = self.clipe("B.mov")
        os.utime(c, (1778508202, 1778508202))   # 2026-05-11T14:03:22Z
        m = metadados_clipe(c)
        self.assertIsNone(m["tc_origem_s"])
        self.assertEqual(m["gravado_em"], "2026-05-11T14:03:22Z")

    def test_arquivo_que_nao_existe(self):
        self.assertEqual(metadados_clipe(str(self.tmp / "nada.mov")), {"tc_origem_s": None, "gravado_em": None})

    def test_com_metadados_le_cada_clipe_uma_vez(self):
        c = self.clipe("C.mov", "-timecode", "01:00:00:00")
        trechos = [T(c, 0.0), T(c, 3.0)]
        com_metadados(trechos)
        self.assertEqual([t["tc_origem_s"] for t in trechos], [3600.0, 3600.0])
        self.assertTrue(all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", t["gravado_em"]) for t in trechos))


@unittest.skipIf(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, "ffmpeg ausente")
class TestSelecionarGravaOsCampos(unittest.TestCase):
    """Ponta a ponta: clipe com timecode e data -> analisar -> selecionar --ordem timecode -> selects.json."""

    def setUp(self):
        proxy._ASSINATURAS.clear()
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_ordens_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        media = self.tmp / "media"
        media.mkdir()
        self.saida = self.tmp / "analise"
        # Cena sintética do motor (tem trechos de verdade), reembalada com timecode e data de gravação.
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(sinteticos.clipes()["parado"]),
                        "-c", "copy", "-timecode", "10:00:00:00", "-metadata", "creation_time=2026-05-11T14:03:22Z",
                        str(media / "A001.mov")], check=True)
        nota_py = str(Path(__file__).resolve().parents[1] / "nota.py")
        self.rodar = lambda *a: subprocess.run([sys.executable, nota_py, *a], capture_output=True, text=True)
        r = self.rodar("analisar", str(media), "--sem-hw", "--saida", str(self.saida))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_selects_traz_timecode_e_data_de_gravacao(self):
        r = self.rodar("selecionar", "--preset", "broll_acao", "--min", "0", "--ordem", "timecode",
                       "--saida", str(self.saida))
        self.assertEqual(r.returncode, 0, r.stderr)
        selects = json.loads((self.saida / "selects.json").read_text())
        self.assertEqual(selects["filtros"]["ordem"], "timecode")
        self.assertTrue(selects["trechos"])
        for t in selects["trechos"]:
            self.assertEqual(t["tc_origem_s"], 36000.0)
            self.assertEqual(t["gravado_em"], "2026-05-11T14:03:22Z")


if __name__ == "__main__":
    unittest.main()

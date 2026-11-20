"""P0 do PRD: perfil de computação (pular métricas), taxa de amostragem por preset e tempo no fim."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from analise import METRICAS_OPCIONAIS, analisar_clipe
from tests import sinteticos

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")


def rodar(*args):
    return subprocess.run([sys.executable, NOTA, *args], capture_output=True, text=True)


class TestPular(unittest.TestCase):
    def test_pular_escala_zera_a_coluna_e_registra(self):
        s = analisar_clipe(sinteticos.clipes()["push_in"], hw=False, pular=("escala",))
        self.assertEqual(s["metricas_puladas"], ["escala"])
        self.assertTrue(all(v == 0.0 for v in s["quadros"]["cam_escala"]))

    def test_pular_movimento_zera_movimento_do_assunto(self):
        s = analisar_clipe(sinteticos.clipes()["corte"], hw=False, pular=("movimento",))
        self.assertTrue(all(v == 0.0 for v in s["quadros"]["movimento_assunto"]))
        self.assertEqual(sum(s["quadros"]["corte"]), 1)

    def test_sem_pular_registra_lista_vazia(self):
        self.assertEqual(analisar_clipe(sinteticos.clipes()["parado"], hw=False)["metricas_puladas"], [])

    def test_metrica_desconhecida(self):
        with self.assertRaises(ValueError):
            analisar_clipe(sinteticos.clipes()["parado"], hw=False, pular=("foco",))

    def test_opcionais(self):
        self.assertEqual(set(METRICAS_OPCIONAIS), {"escala", "movimento"})


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nota_perfil_"))
        self.media = self.tmp / "media"
        self.media.mkdir()
        shutil.copy(sinteticos.clipes()["parado"], self.media / "A001.mp4")
        self.saida = self.tmp / "analise"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sidecar(self):
        return json.loads(next((self.saida / "nota").glob("*.nota.json")).read_text())

    def test_sem_metricas_e_reanalise_quando_muda(self):
        r = rodar("analisar", str(self.media), "--sem-hw", "--saida", str(self.saida), "--sem-metricas", "escala")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sidecar()["metricas_puladas"], ["escala"])
        r = rodar("analisar", str(self.media), "--sem-hw", "--saida", str(self.saida))
        self.assertNotIn("já analisado", r.stdout)
        self.assertEqual(self.sidecar()["metricas_puladas"], [])

    def test_sem_metricas_invalida(self):
        r = rodar("analisar", str(self.media), "--sem-hw", "--saida", str(self.saida), "--sem-metricas", "foco")
        self.assertEqual(r.returncode, 2)
        self.assertIn("foco", r.stderr)

    def test_taxa_do_preset(self):
        preset = self.tmp / "lento.json"
        preset.write_text(json.dumps({"amostras_por_s": 2}))
        r = rodar("analisar", str(self.media), "--sem-hw", "--saida", str(self.saida), "--preset", str(preset))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sidecar()["amostras_por_s"], 2)

    def test_amostras_explicitas_vencem_o_preset(self):
        preset = self.tmp / "lento.json"
        preset.write_text(json.dumps({"amostras_por_s": 2}))
        rodar("analisar", str(self.media), "--sem-hw", "--saida", str(self.saida), "--preset", str(preset),
              "--amostras", "3")
        self.assertEqual(self.sidecar()["amostras_por_s"], 3)

    def test_imprime_tempo(self):
        r = rodar("analisar", str(self.media), "--sem-hw", "--saida", str(self.saida))
        self.assertIn("tempo:", r.stdout)


if __name__ == "__main__":
    unittest.main()

"""Painel de seleção ao vivo: o preset completo que o painel lê e grava de volta carrega igual ao original."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import presets

NOTA = str(Path(__file__).resolve().parents[1] / "nota.py")


class TestPresetBruto(unittest.TestCase):
    def test_bruto_regravado_carrega_igual_ao_original(self):
        for nome in presets.listar():
            with self.subTest(nome=nome), tempfile.TemporaryDirectory() as d:
                arq = Path(d) / "preset_painel.json"
                arq.write_text(json.dumps(presets.bruto(nome)), encoding="utf-8")
                original, regravado = presets.carregar(nome), presets.carregar(str(arq))
                original.pop("nome"), regravado.pop("nome")
                self.assertEqual(original, regravado)

    def test_bruto_nao_tem_nome(self):
        self.assertNotIn("nome", presets.bruto("melhores"))

    def test_cli_preset_imprime_json(self):
        r = subprocess.run([sys.executable, NOTA, "preset", "melhores"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), presets.bruto("melhores"))
        r = subprocess.run([sys.executable, NOTA, "preset", "nao_existe"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()


class TestPresetsMeus(unittest.TestCase):
    """Presets salvos pelo painel ficam em presets/meus/ e o motor os acha pelo nome."""

    def setUp(self):
        self.antiga = presets.PASTA
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "meus").mkdir()
        (self.tmp / "melhores.json").write_text(json.dumps({"nota_min": 0.8}))
        (self.tmp / "meus" / "festa.json").write_text(json.dumps({"nota_min": 0.5}))
        presets.PASTA = self.tmp

    def tearDown(self):
        presets.PASTA = self.antiga

    def test_lista_e_carrega_os_meus(self):
        self.assertEqual(presets.listar(), ["festa", "melhores"])
        self.assertEqual(presets.carregar("festa")["nota_min"], 0.5)
        self.assertEqual(presets.carregar("melhores")["nota_min"], 0.8)
        self.assertEqual(presets.meus(), ["festa"])
        (self.tmp / "meus" / ".festa.validar.json").write_text("{}")   # sobra de uma validação que caiu
        self.assertEqual(presets.meus(), ["festa"])

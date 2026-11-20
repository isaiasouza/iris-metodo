"""Nota de pico: a maior nota por amostra dentro do trecho."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import presets
from segmentos import trechos_do_clipe, valores_trecho
from tests.test_saida import sidecar
from tests.test_segmentos import preset


class TestPico(unittest.TestCase):
    def test_trecho_tem_pico_coerente(self):
        p = preset()
        trechos, _ = trechos_do_clipe(sidecar(), p)
        self.assertTrue(trechos)
        for t in trechos:
            self.assertIn("pico", t)
            self.assertLessEqual(t["pico"], 1.0)
            # A média das amostras (nota sem o bônus de duração) nunca passa do pico.
            self.assertGreaterEqual(t["pico"] + 1e-3, t["nota"] / (1.0 + p["bonus_duracao"]))

    def test_campo_pico(self):
        t = trechos_do_clipe(sidecar(), preset())[0][0]
        self.assertEqual(valores_trecho(t)["pico"], f"{t['pico']:.2f}".replace(".", ","))
        antigo = dict(t)
        del antigo["pico"]
        self.assertEqual(valores_trecho(antigo)["pico"], "—")

    def test_preset_aceita_pico_no_marcador(self):
        self.assertIn("pico", presets.CAMPOS_TRECHO)
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "p.json"
            arq.write_text(json.dumps({"campos": {"marcador_nome": "{id} · pico {pico}"}}))
            self.assertEqual(presets.carregar(str(arq))["campos"]["marcador_nome"], "{id} · pico {pico}")


if __name__ == "__main__":
    unittest.main()

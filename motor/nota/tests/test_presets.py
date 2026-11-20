from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import presets


class TestPresets(unittest.TestCase):
    def test_lista_os_tres_presets(self):
        self.assertTrue({"imovel", "entrevista", "broll_acao"} <= set(presets.listar()))

    def test_imovel_tem_os_pesos_do_spec(self):
        p = presets.carregar("imovel")
        self.assertEqual(p["pesos"], {"foco": 0.25, "exposicao": 0.30, "estabilidade": 0.35, "movimento": 0.10})
        self.assertEqual(p["camera_comportamento"]["mao"], "desfavorecer")

    def test_preset_parcial_herda_o_padrao(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "meu.json"
            arq.write_text(json.dumps({"nota_min": 0.7, "pesos": {"foco": 1.0}}))
            p = presets.carregar(str(arq))
        self.assertEqual(p["nota_min"], 0.7)
        self.assertEqual(p["pesos"]["foco"], 1.0)
        self.assertEqual(p["pesos"]["exposicao"], presets.PADRAO["pesos"]["exposicao"])
        self.assertEqual(p["duracao_min_s"], presets.PADRAO["duracao_min_s"])

    def test_perfil_log_padrao_e_compatibilidade(self):
        self.assertIsNone(presets.carregar("imovel")["perfil_log"])
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "log.json"
            arq.write_text(json.dumps({"log": True}))
            self.assertEqual(presets.carregar(str(arq))["perfil_log"], "auto")
            arq.write_text(json.dumps({"log": True, "perfil_log": "vlog"}))
            self.assertEqual(presets.carregar(str(arq))["perfil_log"], "vlog")
            arq.write_text(json.dumps({"perfil_log": "inexistente"}))
            with self.assertRaises(ValueError):
                presets.carregar(str(arq))

    def test_log_amplia_a_faixa_de_brilho(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "log.json"
            arq.write_text(json.dumps({"log": True, "brilho_min": 0.2, "brilho_max": 0.8}))
            p = presets.carregar(str(arq))
        self.assertAlmostEqual(p["brilho_min"], 0.1)
        self.assertAlmostEqual(p["brilho_max"], 0.9)

    def test_preset_inexistente(self):
        with self.assertRaises(ValueError):
            presets.carregar("nao_existe")

    def test_comportamento_invalido(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "ruim.json"
            arq.write_text(json.dumps({"flags": {"blur": "talvez"}}))
            with self.assertRaises(ValueError):
                presets.carregar(str(arq))

    def _carregar_texto(self, texto):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "x.json"
            arq.write_text(texto)
            return presets.carregar(str(arq))

    def test_chave_desconhecida_e_recusada(self):
        with self.assertRaises(ValueError) as ctx:
            self._carregar_texto(json.dumps({"nota_minima": 0.7}))
        msg = str(ctx.exception)
        self.assertIn("nota_minima", msg)
        self.assertIn("nota_min", msg)

    def test_nome_no_arquivo_e_recusado(self):
        with self.assertRaises(ValueError):
            self._carregar_texto(json.dumps({"nome": "outro"}))

    def test_aninhado_que_nao_e_objeto_e_recusado(self):
        with self.assertRaises(ValueError) as ctx:
            self._carregar_texto(json.dumps({"pesos": [0.3, 0.3]}))
        self.assertIn("pesos", str(ctx.exception))

    def test_json_que_nao_e_objeto_e_recusado(self):
        for texto in ("[1, 2]", "3", '"imovel"'):
            with self.assertRaises(ValueError):
                self._carregar_texto(texto)

    def test_os_tres_presets_carregam(self):
        for nome in ("imovel", "entrevista", "broll_acao"):
            presets.carregar(nome)

    def test_flags_conhecidas_batem_com_o_padrao(self):
        from segmentos import FLAGS
        self.assertEqual(set(FLAGS), set(presets.PADRAO["flags"]))

    def test_carregar_nao_altera_o_padrao(self):
        antes = json.dumps(presets.PADRAO, sort_keys=True)
        presets.carregar("broll_acao")
        self.assertEqual(json.dumps(presets.PADRAO, sort_keys=True), antes)


if __name__ == "__main__":
    unittest.main()

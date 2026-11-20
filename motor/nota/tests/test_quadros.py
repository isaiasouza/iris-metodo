"""IRISCUT: comando quadros do davinci.py (nota e métricas de cada amostra de um trecho, só leitura)."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import davinci
import perfis_log
from segmentos import trechos_do_clipe
from tests.test_segmentos import DT, preset, quadros_fake

N = 40


def sidecar(caminho, **over):
    """Clipe de N amostras com nitidez variando (notas no meio da escala, não todas 1)."""
    nit = [600.0 + 40.0 * ((i * 7) % 10) for i in range(N)]
    q = quadros_fake(N, **{"nitidez": nit, **over})
    return {"caminho": caminho, "fps": 24.0, "duracao": N * DT, "amostras_por_s": 1 / DT, "quadros": q}


class TestQuadros(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.video = str(self.tmp / "A.MP4")
        self.p = preset(bonus_duracao=0.0)

    def montar(self, sc, trechos, preset_nome="imovel", selects=True):
        caminho_sc = self.tmp / "A.nota.json"
        if sc is not None:
            caminho_sc.write_text(json.dumps(sc), encoding="utf-8")
        arquivo_selects = self.tmp / "selects.json"
        if selects:
            arquivo_selects.write_text(json.dumps({"preset": preset_nome, "trechos": []}), encoding="utf-8")
        rev = {"versao": 1, "selects": str(arquivo_selects), "projeto": "P", "timeline": "REVISÃO", "trechos": [
            {"id": t["id"], "caminho": self.video, "inicio_s": t["inicio_s"], "fim_s": t["fim_s"], "fps": 24.0,
             "camera": "parada", "sidecar": str(caminho_sc) if sc is not None else None}
            for t in trechos]}
        caminho = self.tmp / "revisao.json"
        caminho.write_text(json.dumps(rev), encoding="utf-8")
        return caminho

    def rodar(self, revisao, trecho_id, perfil=None):
        with mock.patch("presets.carregar", return_value=self.p):
            return davinci.cmd_quadros(revisao, trecho_id, perfil)

    def test_notas_reproduzem_o_motor(self):
        sc = sidecar(self.video)
        trechos, _ = trechos_do_clipe(sc, self.p)
        self.assertTrue(trechos)
        rev = self.montar(sc, trechos)
        for t in trechos:
            r = self.rodar(rev, t["id"])
            validas = [n for n in r["amostras"]["nota"] if n is not None]
            # Sem bônus de duração e sem comportamento de câmera, a nota do trecho é a média das amostras válidas.
            self.assertAlmostEqual(sum(validas) / len(validas), t["nota"], delta=0.002)
            self.assertAlmostEqual(max(validas), t["pico"], delta=0.001)
            self.assertEqual(r["camera"]["tipo"], t["camera"]["tipo"])
            self.assertEqual(r["camera"]["confianca"], t["camera"]["confianca"])
            self.assertEqual(r["camera"]["direcao"], t["direcao"])
            self.assertEqual(len(r["amostras"]["t"]), round(t["duracao_s"] / DT))
            self.assertEqual(set(r["amostras"]["metricas"]), set(t["metricas"]))
            self.assertEqual(set(r["amostras"]["submetricas"]), set(t["submetricas"]))
            self.assertEqual(r["aps"], 1 / DT)
            self.assertEqual(r["t0"], t["inicio_s"])
            self.assertEqual(r["nota_min"], self.p["nota_min"])   # o corte do selo PASSA/FORA do IRISCUT

    def test_amostra_excluida_vira_null(self):
        est = [0.0] * N
        est[10] = 1.0
        rev = self.montar(sidecar(self.video, estourado=est), [{"id": "A_01", "inicio_s": 0.0, "fim_s": N * DT}])
        r = self.rodar(rev, "A_01")
        self.assertIsNone(r["amostras"]["nota"][10])
        self.assertIn("estourado", r["amostras"]["flags"][10])
        self.assertIsNotNone(r["amostras"]["nota"][9])
        self.assertNotIn("estourado", r["amostras"]["flags"][9])

    def test_recorte_preso_ao_fim_do_clipe(self):
        rev = self.montar(sidecar(self.video), [{"id": "A_01", "inicio_s": 7.9, "fim_s": 30.0}])
        r = self.rodar(rev, "A_01")
        self.assertEqual(r["t0"], 7.75)
        self.assertEqual(len(r["amostras"]["t"]), N - 31)

    def test_recorte_nao_pula_amostra_por_erro_de_ponto_flutuante(self):
        sc = sidecar(self.video)
        sc["amostras_por_s"] = 5.0
        sc["quadros"]["t"] = [i * 0.2 for i in range(N)]
        sc["duracao"] = N * 0.2
        rev = self.montar(sc, [{"id": "A_01", "inicio_s": 0.6, "fim_s": 1.4}])
        r = self.rodar(rev, "A_01")
        self.assertEqual(len(r["amostras"]["t"]), 4)   # 1,4 × 5 = 7,000000000000001 não pode virar 8
        self.assertEqual(r["t0"], 0.6)

    def test_sem_sidecar_ainda_da_midia_e_filtro(self):
        rev = self.montar(None, [{"id": "A_01", "inicio_s": 0.0, "fim_s": 2.0}])
        r = self.rodar(rev, "A_01")
        self.assertIsNone(r["amostras"])
        self.assertIsNone(r["camera"])
        self.assertEqual(r["midia"], self.video)
        self.assertIsNone(r["filtro"])

    def test_proxy_e_perfil_de_log(self):
        (self.tmp / "Proxy").mkdir()
        proxy = self.tmp / "Proxy" / "A.mov"
        proxy.write_bytes(b"")
        rev = self.montar(None, [{"id": "A_01", "inicio_s": 0.0, "fim_s": 2.0}])
        r = self.rodar(rev, "A_01", "generico")
        self.assertEqual(r["midia"], str(proxy))
        self.assertEqual(r["filtro"], perfis_log.FILTRO_LOG)

    def test_proxy_gravado_no_sidecar_vence_a_busca(self):
        # O IRISCUT chama por trecho em processo novo: o proxy já achado fica no sidecar e evita o ffprobe.
        gravado = self.tmp / "gravado.mov"
        gravado.write_bytes(b"")
        sc = sidecar(self.video)
        sc["proxy"] = str(gravado)
        trechos, _ = trechos_do_clipe(sc, self.p)
        rev = self.montar(sc, trechos)
        with mock.patch("exportar.escolher_midia", side_effect=AssertionError("buscou o proxy")):
            r = self.rodar(rev, trechos[0]["id"])
        self.assertEqual(r["midia"], str(gravado))

    def test_preset_do_painel_vem_da_pasta_do_selects(self):
        # O painel de seleção grava preset_painel.json ao lado do selects_painel.json; não está na pasta de presets.
        (self.tmp / "preset_painel.json").write_text(json.dumps({"nota_min": 0.5}), encoding="utf-8")
        rev = self.montar(None, [{"id": "A_01", "inicio_s": 0.0, "fim_s": 2.0}], preset_nome="preset_painel")
        r = davinci.cmd_quadros(rev, "A_01")
        self.assertEqual(r["id"], "A_01")

    def test_erros_saem_com_mensagem(self):
        rev = self.montar(None, [{"id": "A_01", "inicio_s": 0.0, "fim_s": 2.0}])
        with self.assertRaises(SystemExit) as c:
            self.rodar(rev, "B_09")
        self.assertIn("B_09", str(c.exception.code))
        rev = self.montar(None, [{"id": "A_01", "inicio_s": 0.0, "fim_s": 2.0}], preset_nome="nao-existe")
        with self.assertRaises(SystemExit) as c:
            davinci.cmd_quadros(rev, "A_01")
        self.assertIn("preset", str(c.exception.code))
        (self.tmp / "selects.json").unlink()
        rev = self.montar(None, [{"id": "A_01", "inicio_s": 0.0, "fim_s": 2.0}], selects=False)
        with self.assertRaises(SystemExit) as c:
            self.rodar(rev, "A_01")
        self.assertIn("selects", str(c.exception.code))

    def test_principal_responde_sem_abrir_o_resolve(self):
        rev = self.montar(None, [{"id": "A_01", "inicio_s": 0.0, "fim_s": 2.0}])
        saida = io.StringIO()
        with mock.patch.object(davinci, "_conectar", side_effect=AssertionError("abriu o Resolve")), \
                mock.patch("presets.carregar", return_value=self.p), contextlib.redirect_stdout(saida):
            self.assertEqual(davinci.principal(["quadros", str(rev), "--trecho", "A_01"]), 0)
        self.assertEqual(json.loads(saida.getvalue().strip().splitlines()[-1])["id"], "A_01")


if __name__ == "__main__":
    unittest.main()

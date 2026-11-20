"""IRISCUT: o revisao.json (montar, mesclar decisões, aprovados, marcadores de decisão, gravação)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import decisoes

FPS = 24000 / 1001


def trecho(ident, caminho="/m/A.MP4", inicio=0.0, fim=4.0, nota=0.9):
    return {"id": ident, "caminho": caminho, "inicio_s": inicio, "fim_s": fim, "fps": FPS, "nota": nota,
            "metricas": {"foco": 0.9, "exposicao": 1.0, "estabilidade": 0.8, "movimento": 0.5},
            "camera": {"tipo": "parada", "confianca": 0.9}, "flags": ["blur"] if nota < 0.85 else []}


AGORA = datetime(2026, 10, 24, 18, 0, 0)


def montar(trechos, posicoes, anterior=None):
    return decisoes.montar(trechos, posicoes, selects="/a/exemplo/selects.json", projeto="P", timeline="REVISÃO",
                           fps_timeline=23.976, inicio_timeline=86400,
                           sidecars={"/m/A.MP4": "/a/exemplo/nota/A_x.nota.json"},
                           miniaturas={"A_01": "/a/exemplo/contact/A_01.jpg"}, anterior=anterior, agora=AGORA)


class TestMontar(unittest.TestCase):
    def setUp(self):
        self.trechos = [trecho("A_01", inicio=0, fim=4), trecho("A_02", inicio=10, fim=12, nota=0.8)]
        self.pos = [(86400, 86496), (86496, 86544)]

    def test_campos(self):
        r = montar(self.trechos, self.pos)
        self.assertEqual(r["versao"], 1)
        self.assertEqual((r["projeto"], r["timeline"], r["inicio_timeline"]), ("P", "REVISÃO", 86400))
        self.assertEqual(r["criado_em"], "2026-10-24T18:00:00")
        t = r["trechos"][0]
        self.assertEqual((t["tl_inicio"], t["tl_fim"]), (86400, 86496))
        self.assertEqual(t["camera"], "parada")
        self.assertEqual(t["decisao"], "pendente")
        self.assertIsNone(t["decidido_em"])
        self.assertEqual(t["sidecar"], "/a/exemplo/nota/A_x.nota.json")
        self.assertEqual(t["miniatura"], "/a/exemplo/contact/A_01.jpg")
        self.assertIsNone(r["trechos"][1]["miniatura"])
        self.assertEqual(r["trechos"][1]["flags"], ["blur"])
        self.assertEqual(r["orfaos"], [])

    def test_posicoes_precisam_bater(self):
        with self.assertRaises(ValueError):
            montar(self.trechos, self.pos[:1])

    def test_mantem_decisoes_e_guarda_orfaos(self):
        anterior = montar(self.trechos, self.pos)
        anterior["trechos"][0].update(decisao="aprovado", decidido_em="2026-10-24T17:00:00")
        anterior["trechos"][1].update(decisao="rejeitado", decidido_em="2026-10-24T17:01:00")
        novos = [trecho("A_01", inicio=0, fim=4), trecho("A_03", inicio=20, fim=22)]
        r = montar(novos, [(86400, 86496), (86496, 86544)], anterior=anterior)
        self.assertEqual(r["trechos"][0]["decisao"], "aprovado")
        self.assertEqual(r["trechos"][0]["decidido_em"], "2026-10-24T17:00:00")
        self.assertEqual(r["trechos"][1]["decisao"], "pendente")
        self.assertEqual(r["orfaos"], [{"id": "A_02", "caminho": "/m/A.MP4", "inicio_s": 10, "fim_s": 12,
                                        "decisao": "rejeitado", "decidido_em": "2026-10-24T17:01:00"}])

    def test_orfao_que_volta_recupera_a_decisao(self):
        anterior = montar(self.trechos, self.pos)
        anterior["trechos"] = []
        anterior["orfaos"] = [{"id": "A_02", "caminho": "/m/A.MP4", "inicio_s": 10.02, "fim_s": 11.98,
                               "decisao": "rejeitado", "decidido_em": "x"}]
        r = montar(self.trechos, self.pos, anterior=anterior)
        self.assertEqual(r["trechos"][1]["decisao"], "rejeitado")
        self.assertEqual(r["orfaos"], [])

    def test_orfao_so_volta_com_o_mesmo_caminho_e_intervalo(self):
        anterior = montar(self.trechos, self.pos)
        anterior["trechos"] = []
        anterior["orfaos"] = [
            {"id": "A_02", "caminho": "/m/A.MP4", "inicio_s": 30, "fim_s": 32, "decisao": "rejeitado", "decidido_em": "x"},
            {"id": "A_01", "caminho": "/m/B.MP4", "inicio_s": 0, "fim_s": 4, "decisao": "aprovado", "decidido_em": "y"},
            {"id": "A_01", "decisao": "aprovado", "decidido_em": "z"}]   # órfão antigo, sem caminho: não casa
        r = montar(self.trechos, self.pos, anterior=anterior)
        self.assertEqual([t["decisao"] for t in r["trechos"]], ["pendente", "pendente"])
        self.assertEqual(len(r["orfaos"]), 3)

    def test_mesmo_id_com_outro_intervalo_vira_orfao(self):
        anterior = montar(self.trechos, self.pos)
        anterior["trechos"][0].update(decisao="aprovado", decidido_em="t0")
        anterior["trechos"][1].update(decisao="rejeitado", decidido_em="t1")
        # A_01 mexeu 0,04 s (tolerância 0,05): mantém. A_02 agora aponta para outro pedaço do clipe: órfão.
        novos = [trecho("A_01", inicio=0.04, fim=3.96), trecho("A_02", inicio=50, fim=52)]
        r = montar(novos, self.pos, anterior=anterior)
        self.assertEqual([t["decisao"] for t in r["trechos"]], ["aprovado", "pendente"])
        self.assertEqual([(o["id"], o["inicio_s"], o["decisao"]) for o in r["orfaos"]], [("A_02", 10, "rejeitado")])

    def test_mesmo_id_em_outro_clipe_nao_herda(self):
        anterior = montar(self.trechos, self.pos)
        anterior["trechos"][0].update(decisao="aprovado", decidido_em="t0")
        r = montar([trecho("A_01", caminho="/m/Z.MP4", inicio=0, fim=4), self.trechos[1]], self.pos, anterior=anterior)
        self.assertEqual(r["trechos"][0]["decisao"], "pendente")
        self.assertEqual([o["caminho"] for o in r["orfaos"]], ["/m/A.MP4"])

    def test_revisao_de_outro_projeto_nao_mistura(self):
        anterior = montar(self.trechos, self.pos)
        anterior["projeto"] = "OUTRO"
        anterior["trechos"][0].update(decisao="aprovado", decidido_em="t0")
        anterior["orfaos"] = [{"id": "Q_01", "caminho": "/m/Q.MP4", "inicio_s": 0, "fim_s": 1, "decisao": "aprovado",
                               "decidido_em": "t"}]
        r = montar(self.trechos, self.pos, anterior=anterior)
        self.assertEqual([t["decisao"] for t in r["trechos"]], ["pendente", "pendente"])
        self.assertEqual(r["orfaos"], [])


class TestOrdenarEAprovados(unittest.TestCase):
    def test_ordenar(self):
        t = [trecho("B_01", caminho="/m/B.MP4", nota=0.95), trecho("A_01", nota=0.9)]
        self.assertEqual([x["id"] for x in decisoes.ordenar(t, "gravacao")], ["A_01", "B_01"])
        self.assertEqual([x["id"] for x in decisoes.ordenar(t, "nota")], ["B_01", "A_01"])

    def test_aprovados(self):
        r = montar([trecho("A_01", inicio=0, fim=4, nota=0.86), trecho("A_02", inicio=10, fim=12, nota=0.99)],
                   [(86400, 86496), (86496, 86544)])
        self.assertEqual(decisoes.aprovados(r), [])
        for t in r["trechos"]:
            t["decisao"] = "aprovado"
        self.assertEqual([t["id"] for t in decisoes.aprovados(r, "gravacao")], ["A_01", "A_02"])
        self.assertEqual([t["id"] for t in decisoes.aprovados(r, "nota")], ["A_02", "A_01"])


class TestMarcadores(unittest.TestCase):
    def setUp(self):
        self.r = montar([trecho("A_01", inicio=0, fim=4), trecho("A_02", inicio=10, fim=12),
                         trecho("C_01", caminho="/m/C.MP4")], [(0, 96), (96, 144), (144, 240)])
        self.r["trechos"][0]["decisao"] = "aprovado"
        self.r["trechos"][1]["decisao"] = "rejeitado"
        self.r["trechos"][2]["decisao"] = "aprovado"

    def planejar(self, marcadores):
        return decisoes.planejar_marcadores_decisao(self.r, {"/m/A.MP4": (FPS, marcadores)})

    def test_so_decididos_sem_duplicar(self):
        novos, sem_clipe, existentes = self.planejar({0: {"customData": "outro", "color": "Blue"}})
        self.assertEqual(existentes, 1)   # marcador de outra origem no mesmo quadro: fica
        self.assertEqual(sem_clipe, ["/m/C.MP4"])
        self.assertEqual(len(novos), 1)
        m = novos[0]
        self.assertEqual((m["quadro"], m["cor"], m["nome"], m["duracao"]), (240, "Red", "A_02", 48))
        self.assertEqual((m["tipo"], m["apagar"]), ("novo", False))
        self.assertIn("rejeitado", m["nota"])

    def test_pendente_nao_marca(self):
        r = montar([trecho("A_01")], [(0, 96)])
        self.assertEqual(decisoes.planejar_marcadores_decisao(r, {"/m/A.MP4": (FPS, {})}), ([], [], 0))

    def test_substitui_marcador_do_motor(self):
        novos, _, existentes = self.planejar({0: {"customData": "motor-de-nota", "color": "Green", "name": "A_01"}})
        self.assertEqual(existentes, 0)
        m = [x for x in novos if x["quadro"] == 0][0]
        self.assertEqual((m["tipo"], m["apagar"], m["cor"]), ("novo", True, "Green"))

    def test_atualiza_o_proprio_marcador_quando_a_decisao_muda(self):
        antes, _, _ = self.planejar({})
        proprio = {m["quadro"]: {"customData": "iriscut", "color": m["cor"], "name": m["nome"], "note": m["nota"],
                                 "duration": m["duracao"]} for m in antes}
        self.r["trechos"][0]["decisao"] = "rejeitado"
        novos, _, existentes = self.planejar(proprio)
        self.assertEqual(existentes, 1)   # A_02 não mudou
        self.assertEqual(len(novos), 1)
        m = novos[0]
        self.assertEqual((m["quadro"], m["cor"], m["tipo"], m["apagar"]), (0, "Red", "atualizado", True))
        self.assertIn("rejeitado", m["nota"])

    def test_proprio_marcador_igual_nao_mexe(self):
        antes, _, _ = self.planejar({})
        proprio = {m["quadro"]: {"customData": "iriscut", "color": m["cor"], "name": m["nome"], "note": m["nota"],
                                 "duration": m["duracao"]} for m in antes}
        self.assertEqual(self.planejar(proprio), ([], ["/m/C.MP4"], 2))


class TestArquivo(unittest.TestCase):
    def test_gravar_e_ler(self):
        with tempfile.TemporaryDirectory() as d:
            c = Path(d) / "revisao.json"
            decisoes.gravar(c, {"versao": 1, "timeline": "REVISÃO", "trechos": []})
            self.assertEqual(decisoes.ler(c)["timeline"], "REVISÃO")
            self.assertIn("REVISÃO", c.read_text(encoding="utf-8"))  # sem escapar acento
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["revisao.json"])  # sem temporário
            json.loads(c.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

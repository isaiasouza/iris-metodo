"""IRISCUT: comandos revisao, aprovados e marcar-decisoes do davinci.py, com um Resolve falso."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import davinci
import decisoes
from segmentos import codigo_caminho

FPS = 24000 / 1001


class Item:
    def __init__(self, inicio, fim):
        self.inicio, self.fim = inicio, fim

    def GetStart(self):
        return self.inicio

    def GetEnd(self):
        return self.fim


class Timeline:
    def __init__(self, nome):
        self.nome, self.itens = nome, []

    def GetName(self):
        return self.nome

    def GetItemListInTrack(self, tipo, trilha):
        return list(self.itens) if (tipo, trilha) == ("video", 1) else []

    def GetStartFrame(self):
        return 86400

    def GetSetting(self, chave):
        return "23.976" if chave == "timelineFrameRate" else ""


class Clipe:
    def __init__(self, caminho):
        self.caminho, self.marcadores = caminho, {}

    def GetClipProperty(self, k):
        return {"File Path": self.caminho, "FPS": "23.976", "Resolution": "3840x2160"}.get(k, "")

    def GetMarkers(self):
        return self.marcadores

    def AddMarker(self, quadro, cor, nome, nota, duracao, dados):
        if quadro in self.marcadores:
            return False   # o Resolve recusa dois marcadores no mesmo quadro
        self.marcadores[quadro] = {"color": cor, "name": nome, "note": nota, "duration": duracao, "customData": dados}
        return True

    def DeleteMarkerAtFrame(self, quadro):
        return self.marcadores.pop(quadro, None) is not None


class Pasta:
    def __init__(self, clipes):
        self.clipes = clipes

    def GetClipList(self):
        return self.clipes

    def GetSubFolderList(self):
        return []


class Pool:
    def __init__(self, projeto, clipes):
        self.projeto, self.raiz = projeto, Pasta(clipes)

    def GetRootFolder(self):
        return self.raiz

    def CreateEmptyTimeline(self, nome):
        if any(t.nome == nome for t in self.projeto.timelines):
            return None
        t = Timeline(nome)
        self.projeto.timelines.append(t)
        return t

    def ImportMedia(self, infos):
        # Como o Resolve: referencia o arquivo no Media Pool (não copia nada).
        self.importados = getattr(self, "importados", []) + list(infos)
        novos = [Clipe(i) for i in infos if isinstance(i, str)]
        self.raiz.clipes.extend(novos)
        return novos

    def AppendToTimeline(self, infos):
        t = self.projeto.atual
        for info in infos:
            pos = t.itens[-1].fim if t.itens else 86400
            t.itens.append(Item(pos, pos + info["endFrame"] - info["startFrame"]))
        return True


class Projeto:
    def __init__(self, caminhos, nome="P"):
        self.nome, self.timelines, self.atual = nome, [], None
        self.clipes = {c: Clipe(c) for c in caminhos}
        self.pool = Pool(self, list(self.clipes.values()))

    def GetName(self):
        return self.nome

    def GetMediaPool(self):
        return self.pool

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, i):
        return self.timelines[i - 1]

    def SetCurrentTimeline(self, t):
        self.atual = t
        return True

    def GetCurrentTimeline(self):
        return self.atual

    def SetSetting(self, k, v):
        return True


def trecho(ident, caminho, inicio, fim, nota=0.9):
    return {"id": ident, "caminho": caminho, "inicio_s": inicio, "fim_s": fim, "fps": FPS, "nota": nota,
            "metricas": {"foco": 0.9}, "camera": {"tipo": "parada", "confianca": 1.0}, "flags": [],
            "motivo": "foco 0,90"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # resolve(): no macOS o temporário fica em /var, que é atalho de /private/var; o comando devolve caminhos
        # resolvidos, então o teste também usa.
        raiz = Path(self.tmp.name).resolve() / "analise"
        self.trab = raiz / "teste"
        self.trab.mkdir(parents=True)
        (raiz / "exemplo" / "nota").mkdir(parents=True)
        self.sidecar = raiz / "exemplo" / "nota" / f"A_{codigo_caminho('/m/A.MP4')}.nota.json"
        self.sidecar.write_text("{}", encoding="utf-8")
        self.selects = self.trab / "selects_x.json"
        self.selects.write_text(json.dumps({"miniatura_filtro": None, "trechos": [
            trecho("B_01", "/m/B.MP4", 0, 2), trecho("A_02", "/m/A.MP4", 10, 12, 0.99),
            trecho("A_01", "/m/A.MP4", 0, 4, 0.85), trecho("X_01", "/m/X.MP4", 0, 1)]}), encoding="utf-8")
        self.projeto = Projeto(["/m/A.MP4", "/m/B.MP4"])
        self.revisao = self.trab / "revisao_selects_x.json"   # o selects não se chama selects.json

    def tearDown(self):
        self.tmp.cleanup()


class TestRevisao(Base):
    def test_importar_traz_ao_media_pool_os_clipes_que_faltam(self):
        r = davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False, importar=True)
        self.assertEqual(r["importados"], ["/m/X.MP4"])
        self.assertEqual(self.projeto.pool.importados, ["/m/X.MP4"])
        self.assertEqual(r["trechos"], 4)
        self.assertEqual(r["sem_clipe"], [])

    def test_sem_importar_nao_chama_o_import(self):
        r = davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        self.assertFalse(hasattr(self.projeto.pool, "importados"))
        self.assertEqual(r["sem_clipe"], ["/m/X.MP4"])

    def test_monta_timeline_e_revisao(self):
        r = davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        self.assertEqual(r["timeline"], "REVISÃO")
        self.assertEqual(r["trechos"], 3)
        self.assertEqual(r["sem_clipe"], ["/m/X.MP4"])
        self.assertEqual(Path(r["revisao"]), self.revisao)
        rev = decisoes.ler(self.revisao)
        self.assertEqual([t["id"] for t in rev["trechos"]], ["A_01", "A_02", "B_01"])
        self.assertEqual([(t["tl_inicio"], t["tl_fim"]) for t in rev["trechos"]],
                         [(86400, 86496), (86496, 86544), (86544, 86592)])
        self.assertEqual((rev["projeto"], rev["fps_timeline"], rev["inicio_timeline"]), ("P", 23.976, 86400))
        self.assertEqual(rev["trechos"][0]["sidecar"], str(self.sidecar))
        self.assertIsNone(rev["trechos"][2]["sidecar"])

    def test_remontar_mantem_decisoes(self):
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        rev = decisoes.ler(self.revisao)
        rev["trechos"][1]["decisao"] = "aprovado"
        decisoes.gravar(self.revisao, rev)
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO 2", miniaturas=False)
        rev = decisoes.ler(self.revisao)
        self.assertEqual(rev["timeline"], "REVISÃO 2")
        self.assertEqual([t["decisao"] for t in rev["trechos"]], ["pendente", "aprovado", "pendente"])

    def test_nome_repetido_recusa(self):
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        with self.assertRaises(SystemExit):
            davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)

    def test_saida_personalizada(self):
        destino = self.trab / "revisao_melhores.json"
        r = davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", saida=destino, miniaturas=False)
        self.assertEqual(Path(r["revisao"]), destino)
        self.assertTrue(destino.exists())

    def test_selects_json_grava_revisao_json(self):
        selects = self.trab / "selects.json"
        selects.write_text(self.selects.read_text(encoding="utf-8"), encoding="utf-8")
        r = davinci.cmd_revisao(self.projeto, selects, "REVISÃO", miniaturas=False)
        self.assertEqual(Path(r["revisao"]), self.trab / "revisao.json")

    def test_dois_selects_na_mesma_pasta_nao_misturam_decisoes(self):
        # Mesmo id, outro intervalo (ids são número de sequência): cada selects tem a sua revisão.
        outro = self.trab / "selects_melhores.json"
        outro.write_text(json.dumps({"trechos": [trecho("A_01", "/m/A.MP4", 30, 33), trecho("A_02", "/m/A.MP4", 40, 41)]}),
                         encoding="utf-8")
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        rev = decisoes.ler(self.revisao)
        for t in rev["trechos"]:
            t["decisao"] = "aprovado"
        decisoes.gravar(self.revisao, rev)
        r = davinci.cmd_revisao(self.projeto, outro, "REVISÃO 2", miniaturas=False)
        self.assertEqual(Path(r["revisao"]), self.trab / "revisao_selects_melhores.json")
        self.assertEqual(r["decisoes_mantidas"], 0)
        novo = decisoes.ler(self.trab / "revisao_selects_melhores.json")
        self.assertEqual([t["decisao"] for t in novo["trechos"]], ["pendente", "pendente"])
        self.assertEqual(novo["orfaos"], [])
        self.assertEqual([t["decisao"] for t in decisoes.ler(self.revisao)["trechos"]], ["aprovado"] * 3)

    def test_selects_refeito_com_outro_intervalo_vira_orfao(self):
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        rev = decisoes.ler(self.revisao)
        rev["trechos"][0]["decisao"] = "aprovado"    # A_01, 0–4 s
        decisoes.gravar(self.revisao, rev)
        dados = json.loads(self.selects.read_text(encoding="utf-8"))
        for t in dados["trechos"]:
            if t["id"] == "A_01":
                t["inicio_s"], t["fim_s"] = 20, 24
        self.selects.write_text(json.dumps(dados), encoding="utf-8")
        r = davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO 2", miniaturas=False)
        self.assertEqual(r["decisoes_mantidas"], 0)
        rev = decisoes.ler(self.revisao)
        self.assertEqual([t["decisao"] for t in rev["trechos"]], ["pendente"] * 3)
        self.assertEqual([(o["id"], o["inicio_s"], o["decisao"]) for o in rev["orfaos"]], [("A_01", 0, "aprovado")])

    def test_revisao_de_outro_projeto_comeca_do_zero(self):
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        rev = decisoes.ler(self.revisao)
        rev["trechos"][0]["decisao"] = "aprovado"
        decisoes.gravar(self.revisao, rev)
        outro = Projeto(["/m/A.MP4", "/m/B.MP4"], nome="OUTRO")
        r = davinci.cmd_revisao(outro, self.selects, "REVISÃO", miniaturas=False)
        self.assertEqual((r["decisoes_mantidas"], r["revisao_anterior_de_outro_projeto"]), (0, "P"))
        rev = decisoes.ler(self.revisao)
        self.assertEqual((rev["projeto"], rev["orfaos"]), ("OUTRO", []))
        self.assertEqual([t["decisao"] for t in rev["trechos"]], ["pendente"] * 3)

    def test_decisao_gravada_durante_as_miniaturas_nao_se_perde(self):
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        original = davinci._miniaturas

        def painel_decide(trechos, pasta, filtro):   # o painel grava enquanto as miniaturas são feitas
            rev = decisoes.ler(self.revisao)
            rev["trechos"][2]["decisao"] = "rejeitado"   # B_01
            decisoes.gravar(self.revisao, rev)
            return {}, 0

        davinci._miniaturas = painel_decide
        try:
            r = davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO 2")
        finally:
            davinci._miniaturas = original
        self.assertEqual(r["decisoes_mantidas"], 1)
        self.assertEqual([t["decisao"] for t in decisoes.ler(self.revisao)["trechos"]],
                         ["pendente", "pendente", "rejeitado"])

    def test_pasta_analise(self):
        self.assertEqual(davinci.pasta_analise(self.selects), Path(self.tmp.name).resolve() / "analise")


class TestSaidas(Base):
    def setUp(self):
        super().setUp()
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        self.rev = self.revisao
        r = decisoes.ler(self.rev)
        r["trechos"][0]["decisao"] = "rejeitado"   # A_01
        r["trechos"][1]["decisao"] = "aprovado"    # A_02
        r["trechos"][2]["decisao"] = "aprovado"    # B_01
        decisoes.gravar(self.rev, r)

    def test_aprovados(self):
        r = davinci.cmd_aprovados(self.projeto, self.rev, "APROVADOS", "gravacao")
        self.assertEqual((r["timeline"], r["itens_na_timeline"]), ("APROVADOS", 2))

    def test_aprovados_sem_nenhum(self):
        r = decisoes.ler(self.rev)
        for t in r["trechos"]:
            t["decisao"] = "pendente"
        decisoes.gravar(self.rev, r)
        with self.assertRaises(SystemExit):
            davinci.cmd_aprovados(self.projeto, self.rev, "APROVADOS")

    def test_marcar_decisoes(self):
        r = davinci.cmd_marcar_decisoes(self.projeto, self.rev)
        self.assertEqual((r["marcadores_novos"], r["ja_existiam"], r["falhas"]), (3, 0, []))
        marcas = self.projeto.clipes["/m/A.MP4"].marcadores
        self.assertEqual(sorted(m["color"] for m in marcas.values()), ["Green", "Red"])
        self.assertEqual({m["customData"] for m in marcas.values()}, {"iriscut"})
        r = davinci.cmd_marcar_decisoes(self.projeto, self.rev)
        self.assertEqual((r["marcadores_novos"], r["atualizados"], r["ja_existiam"]), (0, 0, 3))

    def test_marcar_decisoes_troca_o_do_motor_atualiza_o_proprio_e_deixa_o_alheio(self):
        a = self.projeto.clipes["/m/A.MP4"]
        b = self.projeto.clipes["/m/B.MP4"]
        a.AddMarker(0, "Green", "A_01", "foco", 96, "motor-de-nota")        # A_01 no quadro 0: do motor
        b.AddMarker(0, "Purple", "do editor", "", 1, "")                       # B_01 no quadro 0: do editor
        r = davinci.cmd_marcar_decisoes(self.projeto, self.rev)
        self.assertEqual((r["marcadores_novos"], r["atualizados"], r["ja_existiam"], r["falhas"]), (2, 0, 1, []))
        self.assertEqual((a.marcadores[0]["customData"], a.marcadores[0]["color"]), ("iriscut", "Red"))
        self.assertEqual(b.marcadores[0]["name"], "do editor")
        rev = decisoes.ler(self.rev)
        rev["trechos"][1]["decisao"] = "rejeitado"    # A_02: aprovado → rejeitado
        decisoes.gravar(self.rev, rev)
        r = davinci.cmd_marcar_decisoes(self.projeto, self.rev)
        self.assertEqual((r["marcadores_novos"], r["atualizados"], r["ja_existiam"]), (0, 1, 2))
        quadro = round(10 * FPS)
        self.assertEqual(a.marcadores[quadro]["color"], "Red")
        self.assertIn("rejeitado", a.marcadores[quadro]["note"])


class Gerente:
    def __init__(self, projeto):
        self.projeto, self.salvos = projeto, 0

    def GetCurrentProject(self):
        return self.projeto

    def SaveProject(self):
        self.salvos += 1
        return True


class Resolve:
    def __init__(self, projeto):
        self.gerente = Gerente(projeto)

    def GetProjectManager(self):
        return self.gerente


class TestPrincipal(Base):
    def setUp(self):
        super().setUp()
        davinci.cmd_revisao(self.projeto, self.selects, "REVISÃO", miniaturas=False)
        r = decisoes.ler(self.revisao)
        r["trechos"][0]["decisao"] = "aprovado"
        decisoes.gravar(self.revisao, r)
        self.original = davinci._conectar

    def tearDown(self):
        davinci._conectar = self.original
        super().tearDown()

    def rodar(self, projeto_aberto, argv):
        import contextlib
        import io

        davinci._conectar = lambda: Resolve(projeto_aberto)
        erro, saida = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(erro), contextlib.redirect_stdout(saida):
            codigo = davinci.principal(argv)
        return codigo, saida.getvalue(), erro.getvalue()

    def test_recusa_revisao_de_outro_projeto(self):
        # O projeto aberto é o pedido no --projeto, mas a revisão é de outro: recusa sem mexer no Resolve.
        outro = Projeto(["/m/A.MP4", "/m/B.MP4"], nome="OUTRO")
        for argv in (["aprovados", str(self.revisao), "--projeto", "OUTRO"],
                     ["marcar-decisoes", str(self.revisao), "--projeto", "OUTRO"]):
            codigo, saida, erro = self.rodar(outro, argv)
            self.assertEqual(codigo, 2)
            self.assertIn("recusado", erro)
            self.assertIn("'P'", erro)
            self.assertEqual(saida, "")
        self.assertEqual(outro.timelines, [])
        self.assertEqual(outro.clipes["/m/A.MP4"].marcadores, {})

    def test_aceita_revisao_do_projeto(self):
        codigo, saida, _ = self.rodar(self.projeto, ["marcar-decisoes", str(self.revisao), "--projeto", "P"])
        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(saida)["marcadores_novos"], 1)


class TestMiniaturas(unittest.TestCase):
    def setUp(self):
        import relatorio

        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name) / "contact"
        self.feitas = []
        self.relatorio, self.original = relatorio, relatorio.contact_sheet

        def falsa(t, pasta, filtro=None, largura=320):
            self.feitas.append((t["id"], filtro, largura))
            destino = pasta / f"{t['id']}.jpg"
            destino.write_bytes(b"jpg")
            return destino

        relatorio.contact_sheet = falsa

    def tearDown(self):
        self.relatorio.contact_sheet = self.original
        self.tmp.cleanup()

    def test_nao_reaproveita_miniatura_de_outro_intervalo_ou_perfil(self):
        self.pasta.mkdir()
        (self.pasta / "A_01.jpg").write_bytes(b"do relatorio")   # do relatorio.py, intervalo desconhecido
        sem = lambda c: (None, None)   # noqa: E731
        t1 = trecho("A_01", "/m/A.MP4", 0, 4)
        feitas, novas = davinci._miniaturas([t1], self.pasta, sem)
        self.assertEqual((novas, feitas), (1, {"A_01": str(self.pasta / "A_01_0-4000_w960.jpg")}))
        self.assertEqual((self.pasta / "A_01.jpg").read_bytes(), b"do relatorio")   # intocada
        t2 = trecho("A_01", "/m/A.MP4", 30, 33.5)
        feitas, novas = davinci._miniaturas([t2], self.pasta, sem)
        self.assertEqual((novas, feitas["A_01"]), (1, str(self.pasta / "A_01_30000-33500_w960.jpg")))
        feitas, novas = davinci._miniaturas([t1], self.pasta, lambda c: ("slog3", "lut3d=file='/x/slog3-v1.cube'"))
        self.assertEqual((novas, feitas["A_01"]), (1, str(self.pasta / "A_01_0-4000_slog3_w960.jpg")))
        self.assertEqual(self.feitas[-1][1], "lut3d=file='/x/slog3-v1.cube'")
        # Igual em tudo: reaproveita.
        feitas, novas = davinci._miniaturas([t1, t2], self.pasta, sem)
        self.assertEqual(novas, 0)
        self.assertEqual(len(self.feitas), 3)
        self.assertEqual({x[2] for x in self.feitas}, {davinci.LARGURA_PREVIA})
        self.assertEqual(davinci.LARGURA_PREVIA, 960)

    def test_escolha_de_filtro(self):
        import perfis_log
        from relatorio import FILTRO_LOG

        antiga, perfis_log.PASTA_LUTS = perfis_log.PASTA_LUTS, Path(self.tmp.name) / "luts"
        try:
            d = Path(self.tmp.name)
            (d / "AM01.XML").write_text('<X><Item name="CaptureGammaEquation" value="s-log3-cine"/></X>',
                                        encoding="utf-8")
            a, b = str(d / "A.MP4"), str(d / "B.MP4")
            # Selects novo com perfil automático: Sony pelo XML, o resto na curva genérica.
            e = davinci.escolha_de_filtro({"miniatura_filtro": None, "miniatura_perfil": "auto"})
            self.assertEqual(e(a)[0], "slog3v1")
            self.assertIn("slog3-v1.cube", e(a)[1])
            self.assertEqual(e(b), ("generico", FILTRO_LOG))
            self.assertEqual(davinci.escolha_de_filtro({"miniatura_perfil": "auto"}, None)(b), ("generico", FILTRO_LOG))
            # Escolha explícita vence o selects.
            self.assertEqual(davinci.escolha_de_filtro({"miniatura_perfil": "auto"}, "nenhum")(a), (None, None))
            self.assertEqual(davinci.escolha_de_filtro({"miniatura_perfil": None}, "vlog")(b)[0], "vlogv1")
            # LUT própria gravada no selects.
            e = davinci.escolha_de_filtro({"miniatura_filtro": "lut3d=file='/x/minha.cube'", "miniatura_perfil": None})
            self.assertRegex(e(a)[0], r"^lut[0-9a-f]{8}$")
            self.assertEqual(e(a)[1], "lut3d=file='/x/minha.cube'")
            # Selects antigo: filtro gravado.
            self.assertEqual(davinci.escolha_de_filtro({"miniatura_filtro": FILTRO_LOG})(a), ("generico", FILTRO_LOG))
            self.assertEqual(davinci.escolha_de_filtro({"miniatura_filtro": None})(a), (None, None))
        finally:
            perfis_log.PASTA_LUTS = antiga


class TestCLI(unittest.TestCase):
    def test_subcomandos_existem(self):
        for argv in (["revisao", "s.json", "--projeto", "P", "--log", "--sem-miniaturas"],
                     ["aprovados", "r.json", "--projeto", "P", "--ordem", "nota"],
                     ["marcar-decisoes", "r.json", "--projeto", "P"]):
            args = davinci.argumentos().parse_args(argv)
            self.assertEqual(args.projeto, "P")
        self.assertEqual(davinci.argumentos().parse_args(["revisao", "s.json", "--projeto", "P"]).nome, "REVISÃO")
        self.assertEqual(davinci.argumentos().parse_args(["aprovados", "r.json", "--projeto", "P"]).nome, "APROVADOS")

    def test_perfil_log(self):
        a = davinci.argumentos().parse_args(["revisao", "s.json", "--projeto", "P", "--perfil-log", "vlog"])
        self.assertEqual(a.perfil_log, "vlog")
        self.assertIsNone(davinci.argumentos().parse_args(["revisao", "s.json", "--projeto", "P"]).perfil_log)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            davinci.argumentos().parse_args(["revisao", "s.json", "--projeto", "P", "--perfil-log", "rec2020"])


if __name__ == "__main__":
    unittest.main()

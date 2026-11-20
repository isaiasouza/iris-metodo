"""Proxies renderizados pelo Resolve em analise/proxies/ (nota.py proxies), com um Resolve falso."""
from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import davinci
import nota
import proxy


class Item:
    def __init__(self, inicio, fim):
        self.inicio, self.fim = inicio, fim

    def GetStart(self):
        return self.inicio

    def GetEnd(self):
        return self.fim


class Clipe:
    def __init__(self, caminho, resolucao="3840x2160", erro_ao_ligar=False, tc=""):
        self.caminho, self.resolucao, self.proxy, self.tc = caminho, resolucao, None, tc
        self.erro_ao_ligar = erro_ao_ligar

    def GetClipProperty(self, chave):
        return {"File Path": self.caminho, "Resolution": self.resolucao, "Start TC": self.tc}.get(chave, "")

    def LinkProxyMedia(self, caminho):
        if self.erro_ao_ligar:
            raise RuntimeError("interrompido ao ligar")
        self.proxy = caminho
        return True


class Pasta:
    def __init__(self, clipes):
        self.clipes = clipes

    def GetClipList(self):
        return self.clipes

    def GetSubFolderList(self):
        return []


class Timeline:
    def __init__(self, nome, itens):
        self.nome, self.itens = nome, itens

    def GetName(self):
        return self.nome

    def GetItemListInTrack(self, tipo, trilha):
        return self.itens if (tipo, trilha) == ("video", 1) else []


class MediaPool:
    def __init__(self, raiz, importaveis):
        self.raiz, self.importaveis = raiz, importaveis
        self.importados, self.apagadas, self.timeline = [], [], None
        self.sem_timeline, self.clipes_apagados = False, []

    def GetRootFolder(self):
        return self.raiz

    def ImportMedia(self, infos):
        self.importados.extend(infos)
        # Como o Resolve: arquivo comum vai como caminho; sequência de imagens, como {"FilePath": padrão, ...}.
        chaves = [i if isinstance(i, str) else i["FilePath"] for i in infos]
        novos = [self.importaveis[k] for k in chaves if k in self.importaveis]
        self.raiz.clipes.extend(novos)
        return novos

    def DeleteClips(self, clipes):
        self.clipes_apagados.extend(clipes)
        for c in clipes:
            if c in self.raiz.clipes:
                self.raiz.clipes.remove(c)
        return True

    def CreateTimelineFromClips(self, nome, clipes):
        if self.sem_timeline:
            return None
        itens = [Item(86400 + 100 * i, 86400 + 100 * i + 48) for i in range(len(clipes))]
        self.timeline = Timeline(nome, itens)
        return self.timeline

    def DeleteTimelines(self, timelines):
        self.apagadas.extend(timelines)
        return True


class Projeto:
    def __init__(self, pool, falha=(), parcial=False, sem_job=(), travado=False, explode=False,
                 preset_falha=False):
        self.pool, self.falha, self.preset_falha = pool, set(falha), preset_falha
        self.parcial, self.sem_job, self.travado, self.explode = parcial, set(sem_job), travado, explode
        self.ajustes, self.jobs, self.apagados = [], [], []
        self.job_nome, self.iniciados, self.parou = {}, [], 0
        # Estado de render do usuário (o que existia antes do proxy) e o que o proxy aplicou.
        self.modo, self.formato = 0, ("mp4", "H265")
        self.modo_aplicado, self.formato_aplicado = None, None
        self.presets, self.presets_carregados, self.presets_apagados = {}, [], []
        self.atual = Timeline("MONTAGEM", [])
        self.voltou = None
        self.pulsos = 2
        self.consultas = 0

    def GetMediaPool(self):
        return self.pool

    def GetName(self):
        return "TESTE"

    def GetCurrentTimeline(self):
        return self.atual

    def SetCurrentTimeline(self, tl):
        self.voltou = tl
        return True

    def GetCurrentRenderMode(self):
        return self.modo

    def GetCurrentRenderFormatAndCodec(self):
        return {"format": self.formato[0], "codec": self.formato[1]}

    def SaveAsNewRenderPreset(self, nome):
        if self.preset_falha:
            return False
        self.presets[nome] = (self.modo, self.formato)
        return True

    def LoadRenderPreset(self, nome):
        self.presets_carregados.append(nome)
        return nome in self.presets

    def DeleteRenderPreset(self, nome):
        self.presets_apagados.append(nome)
        return self.presets.pop(nome, None) is not None

    def SetCurrentRenderMode(self, modo):
        self.modo = modo
        self.modo_aplicado = self.modo_aplicado if self.modo_aplicado is not None else modo
        return True

    def SetCurrentRenderFormatAndCodec(self, formato, codec):
        self.formato = (formato, codec)
        self.formato_aplicado = self.formato_aplicado or (formato, codec)
        return True

    def SetRenderSettings(self, ajustes):
        self.ajustes.append(dict(ajustes))
        return True

    def AddRenderJob(self):
        if self.ajustes[-1]["CustomName"] in self.sem_job:
            return ""
        self.jobs.append(f"job{len(self.jobs) + 1}")
        self.job_nome[self.jobs[-1]] = self.ajustes[-1]["CustomName"]
        return self.jobs[-1]

    def StartRendering(self, ids):
        self.iniciados = list(ids)
        # O "render": grava o arquivo de cada job no destino e com o nome pedidos. Job que falha deixa o parcial.
        for job in self.jobs:
            nome = self.job_nome[job]
            a = next(x for x in self.ajustes if x["CustomName"] == nome)
            if nome not in self.falha or self.parcial:
                (Path(a["TargetDir"]) / f"{nome}.mov").write_bytes(b"")
        return ids == self.jobs

    def IsRenderingInProgress(self):
        self.consultas += 1
        if self.explode and self.consultas == 1:
            raise RuntimeError("Resolve caiu")
        if self.travado:
            return not self.parou
        self.pulsos -= 1
        return self.pulsos > 0

    def StopRendering(self):
        self.parou += 1

    def GetRenderJobStatus(self, job):
        if self.travado:
            return {"JobStatus": "Rendering"} if not self.parou else {"JobStatus": "Cancelled"}
        return ({"JobStatus": "Failed", "Error": "codec"} if self.job_nome[job] in self.falha
                else {"JobStatus": "Complete"})

    def DeleteRenderJob(self, job):
        self.apagados.append(job)
        return True


class TestCmdProxies(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.destino = self.tmp / "analise" / "proxies"
        self.mp4 = "/m/C0001.MP4"
        self.pasta = self.tmp / "A001_C003"
        self.pasta.mkdir()
        for i in range(100, 130):
            (self.pasta / f"A001_C003_{i:06d}.dng").write_bytes(b"")
        self.ja = Clipe(self.mp4)
        self.dng = Clipe(f"{self.pasta}/A001_C003_[000100-000129].dng", "4096x2160")
        self.pool = MediaPool(Pasta([self.ja]), {f"{self.pasta}/A001_C003_%06d.dng": self.dng})

    def rodar(self, falha=(), limite_s=6 * 3600, **kw):
        self.projeto = Projeto(self.pool, falha, **kw)
        return davinci.cmd_proxies(self.projeto, [self.mp4, str(self.pasta)], self.destino, espera=lambda s: None,
                                   limite_s=limite_s)

    def nome(self, c):
        return proxy.nome_no_cache(c)

    def assertProjetoComoEstava(self, apagou_importado):
        p = self.projeto
        self.assertEqual((p.modo, p.formato), (0, ("mp4", "H265")))
        self.assertEqual(len(p.presets_carregados), 1)
        self.assertEqual(p.presets_apagados, p.presets_carregados)
        self.assertTrue(p.presets_carregados[0].startswith("IRISCUT_ANTES_"))
        self.assertEqual(p.presets, {})
        self.assertEqual(p.apagados, p.jobs)
        self.assertEqual(self.pool.apagadas, [self.pool.timeline])
        self.assertIs(p.voltou, p.atual)
        self.assertEqual(self.pool.clipes_apagados, [self.dng] if apagou_importado else [])

    def test_importa_so_o_que_falta_pelo_padrao_da_sequencia(self):
        self.rodar()
        self.assertEqual(self.pool.importados,
                         [{"FilePath": f"{self.pasta}/A001_C003_%06d.dng", "StartIndex": 100, "EndIndex": 129}])

    def test_um_job_por_clipe_com_os_ajustes_do_proxy(self):
        r = self.rodar()
        self.assertEqual(self.projeto.modo_aplicado, 1)
        self.assertEqual(self.projeto.formato_aplicado, ("mov", "H264"))
        a, b = self.projeto.ajustes
        self.assertEqual((a["MarkIn"], a["MarkOut"], b["MarkIn"], b["MarkOut"]), (86400, 86447, 86500, 86547))
        self.assertEqual((a["FormatWidth"], a["FormatHeight"], b["FormatWidth"], b["FormatHeight"]),
                         (1280, 720, 1280, 676))
        self.assertEqual(a["CustomName"], proxy.nome_no_cache(self.mp4))
        self.assertEqual(b["CustomName"], proxy.nome_no_cache(str(self.pasta)))
        self.assertTrue(all(x["TargetDir"] == str(self.destino) and x["ExportAudio"] is False
                            and x["ExportVideo"] is True and x["SelectAllFrames"] is False for x in (a, b)))
        self.assertEqual(len(r["renderizados"]), 2)
        self.assertEqual(r["falhas"], [])

    def test_liga_o_proxy_e_limpa_tudo(self):
        self.rodar()
        self.assertEqual(self.ja.proxy, str(self.destino / f"{proxy.nome_no_cache(self.mp4)}.mov"))
        self.assertEqual(self.dng.proxy, str(self.destino / f"{proxy.nome_no_cache(str(self.pasta))}.mov"))
        self.assertEqual(self.projeto.apagados, ["job1", "job2"])
        self.assertEqual(self.pool.apagadas, [self.pool.timeline])
        self.assertTrue(self.pool.timeline.GetName().startswith("PROXIES "))
        self.assertIs(self.projeto.voltou, self.projeto.atual)

    def test_falha_de_um_job_vai_para_falhas(self):
        r = self.rodar(falha={proxy.nome_no_cache(self.mp4)})
        self.assertEqual(r["falhas"], [{"caminho": self.mp4, "erro": "codec"}])
        self.assertEqual(len(r["renderizados"]), 1)
        self.assertIsNone(self.ja.proxy)
        self.assertEqual(self.projeto.apagados, ["job1", "job2"])

    def test_clipe_que_nao_importa(self):
        self.projeto = Projeto(self.pool)
        r = davinci.cmd_proxies(self.projeto, [self.mp4, "/m/SUMIU.MXF"], self.destino, espera=lambda s: None)
        self.assertEqual(r["sem_importar"], ["/m/SUMIU.MXF"])
        self.assertEqual(len(r["renderizados"]), 1)

    def test_devolve_as_configuracoes_de_render_do_usuario(self):
        r = self.rodar()
        self.assertProjetoComoEstava(apagou_importado=False)
        self.assertEqual(r["importados"], [str(self.pasta)])

    def test_render_restaurado_tambem_com_job_que_falha(self):
        self.rodar(falha={self.nome(self.mp4)})
        self.assertProjetoComoEstava(apagou_importado=False)

    def test_importado_que_falhou_sai_do_pool_e_o_que_ganhou_proxy_fica(self):
        r = self.rodar(falha={self.nome(str(self.pasta))})
        self.assertEqual(self.pool.clipes_apagados, [self.dng])
        self.assertNotIn(self.dng, self.pool.raiz.clipes)
        self.assertEqual(r["importados"], [])
        self.assertEqual([f["caminho"] for f in r["falhas"]], [str(self.pasta)])
        self.assertProjetoComoEstava(apagou_importado=True)

    def test_interrupcao_depois_do_primeiro_link_nao_apaga_o_proxy_ligado(self):
        self.dng.erro_ao_ligar = True
        self.projeto = Projeto(self.pool)
        with self.assertRaises(RuntimeError):
            davinci.cmd_proxies(self.projeto, [self.mp4, str(self.pasta)], self.destino, espera=lambda s: None)
        pronto = self.destino / f"{self.nome(self.mp4)}.mov"
        self.assertTrue(pronto.is_file())                      # completo e ligado: fica
        self.assertEqual(self.ja.proxy, str(pronto))
        self.assertFalse((self.destino / f"{self.nome(str(self.pasta))}.mov").exists())   # parcial: some
        self.assertEqual(self.pool.clipes_apagados, [self.dng])

    def test_preset_que_nao_salva_recusa_antes_de_mexer_no_render(self):
        self.projeto = Projeto(self.pool, preset_falha=True)
        with self.assertRaises(SystemExit) as e:
            davinci.cmd_proxies(self.projeto, [self.mp4, str(self.pasta)], self.destino, espera=lambda s: None)
        self.assertIn("preset", str(e.exception))
        self.assertEqual(self.projeto.ajustes, [])
        self.assertEqual(self.projeto.jobs, [])
        self.assertIsNone(self.projeto.modo_aplicado)
        self.assertIsNone(self.projeto.formato_aplicado)
        self.assertEqual((self.projeto.modo, self.projeto.formato), (0, ("mp4", "H265")))
        self.assertEqual(self.pool.clipes_apagados, [self.dng])
        self.assertEqual(self.pool.apagadas, [self.pool.timeline])
        self.assertIs(self.projeto.voltou, self.projeto.atual)

    def test_timeline_que_nao_nasce_apaga_o_importado(self):
        self.pool.sem_timeline = True
        self.projeto = Projeto(self.pool)
        with self.assertRaises(SystemExit):
            davinci.cmd_proxies(self.projeto, [self.mp4, str(self.pasta)], self.destino, espera=lambda s: None)
        self.assertEqual(self.pool.clipes_apagados, [self.dng])
        self.assertNotIn(self.dng, self.pool.raiz.clipes)
        self.assertEqual(self.pool.apagadas, [])
        self.assertEqual(self.projeto.jobs, [])
        self.assertEqual((self.projeto.modo, self.projeto.formato), (0, ("mp4", "H265")))

    def test_itens_a_menos_apaga_timeline_e_importado(self):
        original = self.pool.CreateTimelineFromClips

        def uma_so(nome, clipes):
            return original(nome, clipes[:1])

        self.pool.CreateTimelineFromClips = uma_so
        self.projeto = Projeto(self.pool)
        with self.assertRaises(SystemExit):
            davinci.cmd_proxies(self.projeto, [self.mp4, str(self.pasta)], self.destino, espera=lambda s: None)
        self.assertEqual(self.pool.clipes_apagados, [self.dng])
        self.assertEqual(self.pool.apagadas, [self.pool.timeline])
        self.assertIs(self.projeto.voltou, self.projeto.atual)
        self.assertEqual((self.projeto.modo, self.projeto.formato), (0, ("mp4", "H265")))

    def test_excecao_no_meio_do_render_limpa_tudo_e_propaga(self):
        self.projeto = Projeto(self.pool, explode=True)
        with self.assertRaises(RuntimeError):
            davinci.cmd_proxies(self.projeto, [self.mp4, str(self.pasta)], self.destino, espera=lambda s: None)
        self.assertProjetoComoEstava(apagou_importado=True)
        self.assertNotIn(self.dng, self.pool.raiz.clipes)
        self.assertEqual(list(self.destino.glob("*.mov")), [])

    def test_keyboardinterrupt_para_o_render_e_limpa(self):
        self.projeto = Projeto(self.pool, travado=True)

        def ctrl_c(s):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            davinci.cmd_proxies(self.projeto, [self.mp4, str(self.pasta)], self.destino, espera=ctrl_c)
        self.assertEqual(self.projeto.parou, 1)
        self.assertProjetoComoEstava(apagou_importado=True)
        self.assertEqual(list(self.destino.glob("*.mov")), [])   # nada pela metade onde achar_proxy acharia

    def test_tempo_esgotado_para_o_render_e_registra_falha(self):
        r = self.rodar(travado=True, limite_s=10)
        self.assertEqual(self.projeto.parou, 1)
        self.assertEqual([f["erro"] for f in r["falhas"]], ["tempo esgotado", "tempo esgotado"])
        self.assertEqual(r["renderizados"], [])
        self.assertProjetoComoEstava(apagou_importado=True)

    def test_arquivo_parcial_de_job_que_falha_e_apagado(self):
        nome = self.nome(self.mp4)
        r = self.rodar(falha={nome}, parcial=True)
        self.assertFalse((self.destino / f"{nome}.mov").exists())
        with mock.patch.object(proxy, "PASTA_PROXIES", self.destino):
            self.assertIsNone(proxy.achar_proxy(self.mp4))
        self.assertEqual(len(r["falhas"]), 1)
        self.assertTrue((self.destino / f"{self.nome(str(self.pasta))}.mov").is_file())

    def test_parcial_do_tempo_esgotado_tambem_sai(self):
        self.rodar(travado=True, limite_s=0)
        self.assertEqual(list(self.destino.glob("*.mov")), [])

    def test_job_que_o_resolve_nao_criou_vai_para_falhas(self):
        r = self.rodar(sem_job={self.nome(self.mp4)})
        self.assertEqual(r["falhas"], [{"caminho": self.mp4, "erro": "o Resolve não criou o job"}])
        self.assertEqual(self.projeto.iniciados, ["job1"])
        self.assertEqual(self.projeto.apagados, ["job1"])
        self.assertEqual(len(r["renderizados"]), 1)


class TestTimecodeDoOriginal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.destino = self.tmp / "analise" / "proxies"
        self.mp4 = "/m/C0001.MP4"
        self.ja = Clipe(self.mp4, tc="23:17:27:00")
        self.novo = Clipe("/m/C0002.MP4")
        self.pool = MediaPool(Pasta([self.ja]), {"/m/C0002.MP4": self.novo})

    def test_arquivo_comum_e_importado_pelo_caminho(self):
        with mock.patch.object(davinci, "_gravar_timecode", return_value=True):
            r = davinci.cmd_proxies(Projeto(self.pool), [self.mp4, "/m/C0002.MP4"], self.destino,
                                    espera=lambda s: None)
        self.assertEqual(self.pool.importados, ["/m/C0002.MP4"])
        self.assertEqual(r["importados"], ["/m/C0002.MP4"])

    def test_proxy_ganha_o_timecode_do_original_antes_de_ligar(self):
        chamadas = []

        def gravar(arquivo, tc):
            chamadas.append((Path(arquivo).name, tc, self.ja.proxy))
            return True

        with mock.patch.object(davinci, "_gravar_timecode", side_effect=gravar):
            r = davinci.cmd_proxies(Projeto(self.pool), [self.mp4], self.destino, espera=lambda s: None)
        self.assertEqual(chamadas, [(f"{proxy.nome_no_cache(self.mp4)}.mov", "23:17:27:00", None)])   # antes de ligar
        self.assertEqual(len(r["renderizados"]), 1)
        self.assertIsNotNone(self.ja.proxy)

    def test_timecode_que_nao_grava_vira_falha_e_apaga_o_proxy(self):
        with mock.patch.object(davinci, "_gravar_timecode", return_value=False):
            r = davinci.cmd_proxies(Projeto(self.pool), [self.mp4], self.destino, espera=lambda s: None)
        self.assertEqual([f["caminho"] for f in r["falhas"]], [self.mp4])
        self.assertIn("timecode", r["falhas"][0]["erro"])
        self.assertIsNone(self.ja.proxy)
        self.assertEqual(list(self.destino.glob("*.mov")), [])

    @unittest.skipIf(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, "ffmpeg ausente")
    def test_gravar_timecode_de_verdade(self):
        arquivo = self.tmp / "p.mov"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=64x36:r=24",
                        "-timecode", "01:00:00:00", "-c:v", "mpeg4", str(arquivo)], check=True)
        self.assertTrue(davinci._gravar_timecode(str(arquivo), "23:17:27:00"))
        tc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream_tags=timecode", "-of",
                             "default=nw=1:nk=1", str(arquivo)], capture_output=True, text=True).stdout.split()
        self.assertIn("23:17:27:00", tc)
        self.assertNotIn("01:00:00:00", tc)
        self.assertEqual(sorted(x.name for x in self.tmp.iterdir()), ["p.mov"])   # sem temporário sobrando
        self.assertFalse(davinci._gravar_timecode(str(self.tmp / "nada.mov"), "00:00:00:00"))


class TestAcharNoCache(unittest.TestCase):
    def test_achar_proxy_acha_o_renderizado(self):
        tmp = Path(tempfile.mkdtemp())
        original = str(tmp / "cartao" / "A001.MXF")
        cache = tmp / "proxies"
        cache.mkdir()
        feito = cache / f"{proxy.nome_no_cache(original)}.mov"
        feito.write_bytes(b"")
        with mock.patch.object(proxy, "PASTA_PROXIES", cache):
            self.assertEqual(proxy.achar_proxy(original), str(feito))
        self.assertTrue(proxy.nome_no_cache(original).startswith("A001_"))
        self.assertEqual(len(proxy.nome_no_cache(original)), len("A001_") + 6)

    def test_decodifica(self):
        self.assertFalse(proxy.decodifica("/m/A.braw"))
        self.assertFalse(proxy.decodifica(tempfile.mkdtemp()))
        with mock.patch("proxy.subprocess.run", return_value=mock.Mock(returncode=0)):
            self.assertTrue(proxy.decodifica("/m/A.MP4"))
        with mock.patch("proxy.subprocess.run", return_value=mock.Mock(returncode=1)):
            self.assertFalse(proxy.decodifica("/m/A.MXF"))


class TestComando(unittest.TestCase):
    def test_nenhum_clipe_precisa_e_nao_abre_o_resolve(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "C0001.MP4").write_bytes(b"")
        saida = io.StringIO()
        with mock.patch("proxy.decodifica", return_value=True), \
                mock.patch.object(davinci, "_conectar", side_effect=AssertionError("abriu o Resolve")), \
                contextlib.redirect_stdout(saida):
            self.assertEqual(nota.principal(["proxies", str(tmp), "--projeto", "TESTE"]), 0)
        self.assertIn("nenhum clipe precisa de proxy", saida.getvalue())

    def test_recusa_projeto_errado(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "C0001.MP4").write_bytes(b"")
        gerente = mock.Mock()
        gerente.GetCurrentProject.return_value.GetName.return_value = "KELLY CURSO"
        resolve = mock.Mock()
        resolve.GetProjectManager.return_value = gerente
        erro = io.StringIO()
        with mock.patch.object(davinci, "_conectar", return_value=resolve), \
                mock.patch.object(davinci, "cmd_proxies", side_effect=AssertionError("renderizou")), \
                contextlib.redirect_stderr(erro):
            self.assertEqual(nota.principal(["proxies", str(tmp), "--projeto", "TESTE", "--todos"]), 2)
        self.assertIn("KELLY CURSO", erro.getvalue())


if __name__ == "__main__":
    unittest.main()

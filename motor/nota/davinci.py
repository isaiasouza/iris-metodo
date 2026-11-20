"""Leva um selects.json ao DaVinci Resolve: marcadores nos clipes, timeline com os trechos e a revisão do IRISCUT.

Roda com o Python do sistema (é o que tem cv2 para as miniaturas e alcança a API do Resolve), com o Resolve
aberto no projeto certo:

  python3 ferramentas/nota/davinci.py marcar analise/x/selects.json --projeto "NOME"
  python3 ferramentas/nota/davinci.py timeline analise/x/selects.json --projeto "NOME" \
      --nome "SELECTS" [--min 0.98] [--sem-flags] [--sem-mao]
  python3 ferramentas/nota/davinci.py revisao analise/x/selects.json --projeto "NOME" [--log]
  python3 ferramentas/nota/davinci.py aprovados analise/x/revisao.json --projeto "NOME" [--ordem nota]
  python3 ferramentas/nota/davinci.py marcar-decisoes analise/x/revisao.json --projeto "NOME"

As funções de planejamento são puras e testáveis sem o Resolve; só `principal` e `_conectar`
tocam a API.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from exportar import colorir, cor_da_nota
from perfis_log import PERFIS as PERFIS_LOG
from segmentos import ORDENS_ORIGEM

DADOS_MARCADOR = "motor-de-nota"
_TAMANHO_LOTE = 50
# Largura de cada quadro da prévia do IRISCUT. A de 320 px do relatório fica borrada ampliada no painel.
LARGURA_PREVIA = 960
# Largura dos proxies que o Resolve renderiza para o que o ffmpeg não lê (nota.py proxies).
LARGURA_PROXY = 1280
_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
_LIB = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"


def cor_marcador(nota: float) -> str:
    return cor_da_nota(nota)


def filtrar_trechos(trechos: list, nota_min: Optional[float] = None, sem_flags: bool = False,
                    sem_mao: bool = False) -> list:
    saida = []
    for t in trechos:
        if nota_min is not None and t["nota"] < nota_min:
            continue
        if sem_flags and t["flags"]:
            continue
        if sem_mao and t["camera"]["tipo"] == "mao":
            continue
        saida.append(t)
    return saida


def _quadros(t: dict, fps: float):
    inicio = int(round(t["inicio_s"] * fps))
    fim = int(round(t["fim_s"] * fps))
    return inicio, max(inicio + 1, fim)


def planejar_marcadores(trechos: list, clipes: dict):
    """clipes: {caminho: (fps, {quadros com marcador já existente})}.

    Devolve (marcadores a criar, caminhos sem clipe no Media Pool, quantos já existiam).
    """
    novos, sem_clipe, existentes = [], set(), 0
    for t in trechos:
        if t["caminho"] not in clipes:
            sem_clipe.add(t["caminho"])
            continue
        fps, ocupados = clipes[t["caminho"]]
        inicio, fim = _quadros(t, fps)
        if inicio in ocupados:
            existentes += 1
            continue
        novos.append({"caminho": t["caminho"], "quadro": inicio, "cor": t.get("cor") or cor_marcador(t["nota"]),
                      "nome": t.get("marcador", {}).get("nome", t["id"]),
                      "nota": t.get("marcador", {}).get("nota", t["motivo"]), "duracao": fim - inicio})
    return novos, sorted(sem_clipe), existentes


_ORDENS = {
    "gravacao": lambda x: (x["caminho"], x["inicio_s"]),
    "nota": lambda x: (-x["nota"], x["caminho"], x["inicio_s"]),
    "nota_asc": lambda x: (x["nota"], x["caminho"], x["inicio_s"]),
    "duracao": lambda x: (-(x["fim_s"] - x["inicio_s"]), -x["nota"], x["caminho"], x["inicio_s"]),
    "duracao_asc": lambda x: (x["fim_s"] - x["inicio_s"], -x["nota"], x["caminho"], x["inicio_s"]),
}
_ORDENS.update(ORDENS_ORIGEM)


def planejar_timeline(trechos: list, fps_por_caminho: dict, ordem: str = "gravacao"):
    """Trechos na ordem pedida: (caminho, quadro inicial, quadro final) e os caminhos sem clipe.

    O AppendToTimeline do Resolve não inclui o endFrame: passar fim − 1 deixava cada trecho 1 quadro curto
    (conferido contra o FCPXML e o OTIO importados num corte de teste)."""
    itens, sem_clipe = [], set()
    for t in sorted(trechos, key=_ORDENS[ordem]):
        if t["caminho"] not in fps_por_caminho:
            sem_clipe.add(t["caminho"])
            continue
        inicio, fim = _quadros(t, fps_por_caminho[t["caminho"]])
        itens.append((t["caminho"], inicio, fim))
    return itens, sorted(sem_clipe)


def planejar_reajuste(takes: list, trilha: int = 2) -> list:
    """Takes reajustados (reajuste.reajustar) → itens para o AppendToTimeline, na posição original."""
    return [{"caminho": t["caminho"], "startFrame": t["novo_in"], "endFrame": t["novo_out"],
             "recordFrame": t["inicio_tl"], "trackIndex": trilha, "mediaType": 1} for t in takes]


def cmd_reajustar(projeto, takes: list, original: str, nome: str, trilha: int = 2) -> dict:
    """Duplica a timeline `original` como `nome` e troca, só na cópia, os takes da `trilha` pelos reajustados."""
    if original == nome:
        raise SystemExit("o nome da timeline ajustada precisa ser diferente do da original")
    timelines = {projeto.GetTimelineByIndex(i).GetName(): projeto.GetTimelineByIndex(i)
                 for i in range(1, projeto.GetTimelineCount() + 1)}
    if original not in timelines:
        raise SystemExit(f"timeline não encontrada: {original}")
    if nome in timelines:
        raise SystemExit(f"já existe uma timeline '{nome}'; apague ou escolha outro nome")
    projeto.SetCurrentTimeline(timelines[original])
    copia = timelines[original].DuplicateTimeline(nome)
    if not copia or copia.GetName() != nome:
        raise SystemExit("o DaVinci não duplicou a timeline")
    projeto.SetCurrentTimeline(copia)
    # Só os itens que são takes saem (pela posição na timeline); o resto da trilha (ex.: logo na V1) fica.
    posicoes = {t["inicio_tl"] for t in takes}
    antigos = [i for i in copia.GetItemListInTrack("video", trilha) or [] if i.GetStart() in posicoes]
    if len(antigos) != len(takes):
        raise SystemExit(f"a trilha V{trilha} da cópia tem {len(antigos)} takes nas posições, esperava {len(takes)}")
    copia.DeleteClips(antigos, False)
    pool = projeto.GetMediaPool()
    por_caminho = {caminho_no_resolve(c.GetClipProperty("File Path")): c for c in _clipes(pool.GetRootFolder())}
    infos = []
    for item in planejar_reajuste(takes, trilha):
        mpi = por_caminho.get(item.pop("caminho"))
        if mpi is None:
            raise SystemExit("clipe do take não está no Media Pool")
        infos.append(dict(item, mediaPoolItem=mpi))
    for i in range(0, len(infos), _TAMANHO_LOTE):
        pool.AppendToTimeline(infos[i:i + _TAMANHO_LOTE])
    novos = [i for i in copia.GetItemListInTrack("video", trilha) or [] if i.GetStart() in posicoes]
    return {"timeline": copia.GetName(), "takes": len(takes), "itens_na_trilha": len(novos),
            "mudaram": sum(1 for t in takes if t.get("mudou"))}


def _conectar():
    os.environ.setdefault("RESOLVE_SCRIPT_API", _API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", _LIB)
    sys.path.append(os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules"))
    import DaVinciResolveScript as dvr  # noqa: E402

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise SystemExit("o DaVinci Resolve não está aberto (ou o scripting externo está desligado)")
    return resolve


# Sequência de imagens no Media Pool do Resolve: '…/A001_C003_[000100-000129].dng'.
_SEQUENCIA = re.compile(r"\[\d+-\d+\]\.dng$", re.IGNORECASE)


def caminho_no_resolve(caminho):
    """Caminho do clipe do Resolve como o motor guarda: a sequência CinemaDNG vira a pasta dela."""
    return str(Path(caminho).parent) if caminho and _SEQUENCIA.search(caminho) else caminho


def _clipes(pasta):
    for c in pasta.GetClipList() or []:
        yield c
    for sub in pasta.GetSubFolderList() or []:
        yield from _clipes(sub)


def _fps(clipe, padrao: float) -> float:
    try:
        return float(clipe.GetClipProperty("FPS") or padrao)
    except ValueError:
        return padrao


def cmd_marcar(projeto, trechos: list) -> dict:
    por_caminho = {caminho_no_resolve(c.GetClipProperty("File Path")): c for c in _clipes(projeto.GetMediaPool().GetRootFolder())}
    fps_padrao = trechos[0]["fps"] if trechos else 24.0
    clipes = {k: (_fps(c, fps_padrao), set((c.GetMarkers() or {}).keys())) for k, c in por_caminho.items() if k}
    novos, sem_clipe, existentes = planejar_marcadores(trechos, clipes)
    falhas = []
    for m in novos:
        ok = por_caminho[m["caminho"]].AddMarker(m["quadro"], m["cor"], m["nome"], m["nota"], m["duracao"],
                                                 DADOS_MARCADOR)
        if not ok:
            falhas.append(m["nome"])
    return {"marcadores_novos": len(novos) - len(falhas), "ja_existiam": existentes,
            "clipes_nao_encontrados": sem_clipe, "falhas": falhas}


def cmd_timeline(projeto, trechos: list, nome: str, ordem: str = "gravacao") -> dict:
    pool = projeto.GetMediaPool()
    por_caminho = {caminho_no_resolve(c.GetClipProperty("File Path")): c for c in _clipes(pool.GetRootFolder())}
    fps_padrao = trechos[0]["fps"] if trechos else 24.0
    itens, sem_clipe = planejar_timeline(trechos, {k: _fps(c, fps_padrao) for k, c in por_caminho.items() if k},
                                         ordem)
    if not itens:
        raise SystemExit("nenhum trecho para montar (filtros restritivos demais ou clipes fora do Media Pool)")
    if projeto.GetTimelineCount() == 0:
        # Sem timeline no projeto ainda: herda fps e resolução do primeiro clipe.
        primeiro = por_caminho[itens[0][0]]
        largura, altura = (primeiro.GetClipProperty("Resolution") or "x").split("x")
        if largura and altura:
            projeto.SetSetting("timelineResolutionWidth", largura)
            projeto.SetSetting("timelineResolutionHeight", altura)
        fps = str(primeiro.GetClipProperty("FPS") or "")
        if fps:
            projeto.SetSetting("timelineFrameRate", fps)
            projeto.SetSetting("timelinePlaybackFrameRate", fps)
    timeline = pool.CreateEmptyTimeline(nome)
    if not timeline:
        raise SystemExit(f"não consegui criar a timeline '{nome}' (já existe uma com esse nome?)")
    projeto.SetCurrentTimeline(timeline)
    infos = [{"mediaPoolItem": por_caminho[c], "startFrame": a, "endFrame": b} for c, a, b in itens]
    for i in range(0, len(infos), _TAMANHO_LOTE):
        pool.AppendToTimeline(infos[i:i + _TAMANHO_LOTE])
    return {"timeline": timeline.GetName(), "itens_pedidos": len(infos),
            "itens_na_timeline": len(timeline.GetItemListInTrack("video", 1) or []),
            "clipes_nao_encontrados": sem_clipe}


def pasta_analise(selects: Path) -> Path:
    """A pasta `analise/` que contém o selects (ou o avô dele, se não houver uma com esse nome)."""
    for p in Path(selects).resolve().parents:
        if p.name == "analise":
            return p
    return Path(selects).resolve().parent.parent


def achar_sidecar(caminho: str, analise: Path) -> Optional[str]:
    """Arquivo de análise do clipe em qualquer `analise/*/nota/` (o selects pode estar em outra pasta)."""
    from segmentos import codigo_caminho

    nome = f"{Path(caminho).stem}_{codigo_caminho(caminho)}.nota.json"
    achados = sorted(analise.glob(f"*/nota/{nome}"))
    return str(achados[0]) if achados else None


def nome_miniatura(t: dict, rotulo: Optional[str]) -> str:
    """Nome da contact sheet de um trecho da revisão: id + intervalo em ms + perfil/filtro + largura. O id sozinho não
    serve (é número de sequência, e outro selects usa o mesmo id para outro pedaço do clipe), nem o `<id>.jpg` do
    relatorio.py."""
    nome = f"{t['id']}_{int(round(t['inicio_s'] * 1000))}-{int(round(t['fim_s'] * 1000))}"
    return f"{nome}{'_' + rotulo if rotulo else ''}_w{LARGURA_PREVIA}"


def escolha_de_filtro(dados: dict, perfil_log: Optional[str] = None):
    """caminho → (rótulo, filtro) das prévias. Escolha explícita (`--perfil-log`) vence; senão o selects novo (LUT
    própria ou perfil por clipe); senão o filtro gravado num selects antigo."""
    import hashlib

    from perfis_log import FILTRO_LOG, VERSAO_LUT, filtro, perfil_do_clipe

    def por_perfil(perfil):
        def escolha(caminho):
            p = perfil_do_clipe(caminho, perfil)
            return (None, None) if p == "nenhum" else (p, filtro(p)) if p == "generico" else (f"{p}v{VERSAO_LUT}", filtro(p))
        return escolha

    def fixo(f):
        if not f:
            return lambda caminho: (None, None)
        if f == FILTRO_LOG:
            return lambda caminho: ("generico", f)
        prefixo = "lut" if f.startswith("lut3d=") else "f"
        rotulo = prefixo + hashlib.sha1(f.encode("utf-8")).hexdigest()[:8]
        return lambda caminho: (rotulo, f)

    if perfil_log:
        return por_perfil(perfil_log)
    if "miniatura_perfil" in dados:
        return fixo(dados["miniatura_filtro"]) if dados.get("miniatura_filtro") else por_perfil(dados["miniatura_perfil"])
    return fixo(dados.get("miniatura_filtro"))


def _miniaturas(trechos: list, pasta: Path, escolha) -> tuple:
    """Contact sheet (início, meio, fim) de cada trecho em `pasta`, com o filtro que `escolha(caminho)` der para o
    clipe; reaproveita só a que bate em id, intervalo e perfil. Devolve ({id: caminho}, quantas foram feitas agora)."""
    from concurrent.futures import ThreadPoolExecutor

    import relatorio

    pasta.mkdir(parents=True, exist_ok=True)
    por_clipe = {c: escolha(c) for c in {t["caminho"] for t in trechos}}
    nomes = {t["id"]: nome_miniatura(t, por_clipe[t["caminho"]][0]) for t in trechos}
    faltam = [t for t in trechos if not (pasta / f"{nomes[t['id']]}.jpg").exists()]
    with ThreadPoolExecutor(4) as ex:
        # contact_sheet grava em <id>.jpg: passa o nome completo no lugar do id.
        list(ex.map(lambda t: relatorio.contact_sheet(dict(t, id=nomes[t["id"]]), pasta, por_clipe[t["caminho"]][1],
                                                      LARGURA_PREVIA), faltam))
    feitas = {i: str(pasta / f"{n}.jpg") for i, n in nomes.items() if (pasta / f"{n}.jpg").exists()}
    return feitas, len(faltam)


def destino_revisao(selects: Path) -> Path:
    """`selects.json` → `revisao.json` ao lado; `selects_x.json` → `revisao_selects_x.json`. Cada selects tem a sua
    revisão: os ids se repetem entre selects da mesma pasta, apontando para pedaços diferentes dos clipes."""
    selects = Path(selects)
    if selects.name == "selects.json":
        return selects.with_name("revisao.json")
    return selects.with_name(f"revisao_{selects.stem}.json")


def cmd_revisao(projeto, selects: Path, nome: str, ordem: str = "gravacao", saida: Optional[Path] = None,
                miniaturas: bool = True, log: bool = False, perfil_log: Optional[str] = None,
                importar: bool = False) -> dict:
    """Timeline `nome` com todos os trechos do selects e a revisão ao lado (decisões antigas mantidas). `importar`
    traz antes ao Media Pool os clipes do selects que ainda não estão no projeto (takes recém-analisados)."""
    import decisoes

    selects = Path(selects)
    dados = json.loads(selects.read_text(encoding="utf-8"))
    destino = Path(saida) if saida else destino_revisao(selects)
    ordenados = decisoes.ordenar(dados["trechos"], ordem)
    importados = []
    if importar:
        pool = projeto.GetMediaPool()
        por_caminho = {caminho_no_resolve(c.GetClipProperty("File Path")): c for c in _clipes(pool.GetRootFolder())}
        importados = [c for c, _ in importar_no_pool(pool, [t["caminho"] for t in ordenados], por_caminho)]
    r = cmd_timeline(projeto, ordenados, nome, ordem)
    faltam = set(r["clipes_nao_encontrados"])
    na_timeline = [t for t in ordenados if t["caminho"] not in faltam]
    timeline = projeto.GetCurrentTimeline()
    posicoes = sorted((i.GetStart(), i.GetEnd()) for i in timeline.GetItemListInTrack("video", 1) or [])
    if len(posicoes) != len(na_timeline):
        raise SystemExit(f"a timeline '{nome}' ficou com {len(posicoes)} itens, esperava {len(na_timeline)}")
    analise = pasta_analise(selects)
    sidecars = {c: achar_sidecar(c, analise) for c in {t["caminho"] for t in na_timeline}}
    feitas, novas = ({}, 0)
    if miniaturas:
        escolha = escolha_de_filtro(dados, perfil_log or ("auto" if log else None))
        feitas, novas = _miniaturas(na_timeline, selects.parent / "contact", escolha)
    # Lê a revisão anterior só agora: as miniaturas podem levar minutos, e o painel pode ter decidido nesse meio-tempo.
    anterior = decisoes.ler(destino) if destino.exists() else None
    de_outro = anterior.get("projeto") if anterior and anterior.get("projeto") != projeto.GetName() else None
    revisao = decisoes.montar(na_timeline, posicoes, selects=str(selects.resolve()), projeto=projeto.GetName(),
                              timeline=timeline.GetName(),
                              fps_timeline=float(timeline.GetSetting("timelineFrameRate") or 24),
                              inicio_timeline=int(timeline.GetStartFrame()), sidecars=sidecars,
                              miniaturas=feitas, anterior=anterior)
    decisoes.gravar(destino, revisao)
    return {"timeline": timeline.GetName(), "trechos": len(na_timeline), "revisao": str(destino.resolve()),
            "sem_clipe": sorted(faltam), "importados": importados, "miniaturas_novas": novas,
            "decisoes_mantidas": sum(1 for t in revisao["trechos"] if t["decisao"] != "pendente"),
            "orfaos": len(revisao["orfaos"]), "revisao_anterior_de_outro_projeto": de_outro}


def cmd_aprovados(projeto, revisao: Path, nome: str, ordem: str = "gravacao") -> dict:
    import decisoes

    trechos = decisoes.aprovados(decisoes.ler(revisao), ordem)
    if not trechos:
        raise SystemExit("nenhum trecho aprovado ainda")
    return cmd_timeline(projeto, trechos, nome, ordem)


def cmd_marcar_decisoes(projeto, revisao: Path) -> dict:
    """Marcador verde/vermelho no in de cada trecho decidido. Troca o marcador do motor no mesmo quadro, atualiza o
    nosso se a decisão mudou e não toca em marcador de outra origem."""
    import decisoes

    rev = decisoes.ler(revisao)
    por_caminho = {caminho_no_resolve(c.GetClipProperty("File Path")): c for c in _clipes(projeto.GetMediaPool().GetRootFolder())}
    fps_padrao = rev["trechos"][0]["fps"] if rev["trechos"] else 24.0
    clipes = {k: (_fps(c, fps_padrao), dict(c.GetMarkers() or {})) for k, c in por_caminho.items() if k}
    planos, sem_clipe, existentes = decisoes.planejar_marcadores_decisao(rev, clipes)
    falhas, contagem = [], {"novo": 0, "atualizado": 0}
    for m in planos:
        clipe = por_caminho[m["caminho"]]
        if m["apagar"] and not clipe.DeleteMarkerAtFrame(m["quadro"]):
            falhas.append(m["nome"])
            continue
        if not clipe.AddMarker(m["quadro"], m["cor"], m["nome"], m["nota"], m["duracao"], decisoes.DADOS_MARCADOR):
            falhas.append(m["nome"])
            continue
        contagem[m["tipo"]] += 1
    return {"marcadores_novos": contagem["novo"], "atualizados": contagem["atualizado"], "ja_existiam": existentes,
            "clipes_nao_encontrados": sem_clipe, "falhas": falhas}


def _info_importacao(caminho: str):
    """ImportMedia: o caminho do arquivo (o Resolve 21 recusa um arquivo comum como {"FilePath": …}), ou o padrão
    %0Nd da sequência CinemaDNG com o primeiro e o último quadro."""
    from proxy import quadros_dng

    quadros = quadros_dng(caminho)
    if not quadros:
        return caminho
    primeiro = re.match(r"^(.*?)(\d+)$", quadros[0].stem)
    ultimo = re.match(r"^(.*?)(\d+)$", quadros[-1].stem)
    padrao = f"{primeiro.group(1)}%0{len(primeiro.group(2))}d{quadros[0].suffix}"
    return {"FilePath": str(Path(caminho) / padrao), "StartIndex": int(primeiro.group(2)),
            "EndIndex": int(ultimo.group(2))}


def importar_no_pool(pool, caminhos, por_caminho: dict) -> list:
    """Importa no Media Pool os `caminhos` que ainda não estão em `por_caminho` (o Resolve só referencia o arquivo: nada
    é copiado nem alterado). Atualiza `por_caminho` e devolve [(caminho, item)] dos importados."""
    faltam = [c for c in dict.fromkeys(caminhos) if c not in por_caminho]
    if not faltam:
        return []
    infos = [_info_importacao(c) for c in faltam]
    # Arquivos e sequências em chamadas separadas: as duas formas não se misturam numa lista só.
    lotes = [[i for i in infos if isinstance(i, str)], [i for i in infos if not isinstance(i, str)]]
    novos = []
    for item in [x for lote in lotes if lote for x in (pool.ImportMedia(lote) or [])]:
        chave = caminho_no_resolve(item.GetClipProperty("File Path"))
        por_caminho[chave] = item
        novos.append((chave, item))
    return novos


def _gravar_timecode(arquivo: str, tc: str) -> bool:
    """Regrava o arquivo (remux, sem recodificar) com o timecode de início `tc`. Temporário na mesma pasta + troca;
    False se o ffmpeg falhar (o arquivo fica como estava)."""
    destino = Path(arquivo)
    tmp = destino.with_name(f".{destino.stem}.tc{destino.suffix}")
    try:
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(destino), "-c", "copy",
                            "-timecode", tc, str(tmp)], capture_output=True, timeout=300)
        if r.returncode != 0 or not tmp.is_file():
            return False
        os.replace(tmp, destino)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        if tmp.exists():
            tmp.unlink()


def _tamanho_proxy(clipe, largura: int = LARGURA_PROXY) -> tuple:
    """Largura fixa e altura pela proporção do clipe (par); sem a resolução, 16:9."""
    try:
        w, h = (int(x) for x in str(clipe.GetClipProperty("Resolution")).lower().split("x"))
    except (ValueError, ZeroDivisionError):
        w, h = 16, 9
    return largura, int(round(largura * h / w / 2)) * 2


def cmd_proxies(projeto, caminhos: list, destino: Optional[Path] = None, espera=None,
                limite_s: float = 6 * 3600) -> dict:
    """Proxy H.264 de cada clipe, renderizado pelo Resolve em analise/proxies/ e ligado ao clipe (LinkProxyMedia).

    Para o que o ffmpeg não lê (X-OCN, N-RAW, CinemaDNG…): a análise, o export e a prévia passam a achar o proxy.
    Uma timeline temporária e um job por clipe (modo clipe único, mark in/out no item). Em qualquer saída, inclusive
    erro e Ctrl+C: o render é parado, jobs e timeline são apagados, o que foi importado nesta rodada some se ela
    não terminou, as configurações de render do usuário voltam e a timeline que estava aberta também.
    Nada é gravado ao lado da mídia; render que não completou não deixa arquivo em analise/proxies/."""
    from proxy import PASTA_PROXIES, nome_no_cache

    destino = Path(destino) if destino else PASTA_PROXIES
    espera = espera or time.sleep
    destino.mkdir(parents=True, exist_ok=True)
    pool = projeto.GetMediaPool()
    por_caminho = {caminho_no_resolve(c.GetClipProperty("File Path")): c for c in _clipes(pool.GetRootFolder())}
    faltam = [c for c in caminhos if c not in por_caminho]
    importados, itens_importados = [], []
    saida = {"renderizados": [], "falhas": [], "sem_importar": [], "destino": str(destino), "importados": importados}
    atual = tl = None
    jobs = []
    antes = {"salvo": None, "modo": None, "formato": None}
    terminou = False

    def tentar(passo, *args):
        """Um passo da limpeza; se falhar, os outros ainda rodam."""
        try:
            return passo(*args)
        except Exception:  # noqa: BLE001 — limpeza nunca esconde o erro original nem pula o resto
            return None

    try:
        if faltam:
            for chave, item in importar_no_pool(pool, faltam, por_caminho):
                itens_importados.append((chave, item))
                importados.append(chave)
        alvos = [c for c in caminhos if c in por_caminho]
        saida["sem_importar"] = [c for c in caminhos if c not in por_caminho]
        if not alvos:
            terminou = True
            return saida
        atual = projeto.GetCurrentTimeline()
        tl = pool.CreateTimelineFromClips(f"PROXIES {datetime.now():%Y-%m-%d %H%M%S}", [por_caminho[c] for c in alvos])
        if tl is None:
            raise SystemExit("o Resolve não criou a timeline dos proxies")
        itens = sorted(tl.GetItemListInTrack("video", 1) or [], key=lambda i: i.GetStart())
        if len(itens) != len(alvos):
            raise SystemExit(f"a timeline dos proxies ficou com {len(itens)} itens, esperava {len(alvos)}")
        # Foto das configurações de render do usuário antes de mexer: preset nomeado + modo + formato.
        modo_antes = projeto.GetCurrentRenderMode()
        formato_antes = projeto.GetCurrentRenderFormatAndCodec()
        nome_preset = f"IRISCUT_ANTES_{datetime.now():%Y%m%d%H%M%S}"
        if not projeto.SaveAsNewRenderPreset(nome_preset):
            raise SystemExit("não deu para guardar os ajustes de render do projeto (preset); nada foi mudado")
        antes.update(salvo=nome_preset, modo=modo_antes, formato=formato_antes)
        projeto.SetCurrentRenderMode(1)
        projeto.SetCurrentRenderFormatAndCodec("mov", "H264")
        for c, item in zip(alvos, itens):
            w, h = _tamanho_proxy(por_caminho[c])
            projeto.SetRenderSettings({"SelectAllFrames": False, "MarkIn": item.GetStart(),
                                       "MarkOut": item.GetEnd() - 1, "TargetDir": str(destino),
                                       "CustomName": nome_no_cache(c), "ExportVideo": True, "ExportAudio": False,
                                       "FormatWidth": w, "FormatHeight": h})
            job = projeto.AddRenderJob()
            if job:
                jobs.append((c, job))
            else:
                saida["falhas"].append({"caminho": c, "erro": "o Resolve não criou o job"})
        if jobs:
            if not projeto.StartRendering([j for _, j in jobs]):
                raise SystemExit("o Resolve não começou o render dos proxies")
            esperado, esgotou = 0.0, False
            while projeto.IsRenderingInProgress():
                if esperado >= limite_s:
                    projeto.StopRendering()
                    esgotou = True
                    break
                espera(2)
                esperado += 2
            for c, j in jobs:
                st = projeto.GetRenderJobStatus(j) or {}
                arquivo = destino / f"{nome_no_cache(c)}.mov"
                if st.get("JobStatus") == "Complete":
                    # O render sai com o timecode da timeline, e o Resolve só liga proxy com o timecode do original.
                    tc = por_caminho[c].GetClipProperty("Start TC")
                    if arquivo.is_file() and tc and not _gravar_timecode(str(arquivo), tc):
                        saida["falhas"].append({"caminho": c, "erro": "não deu para gravar o timecode do original"})
                        tentar(arquivo.unlink)
                    elif arquivo.is_file() and por_caminho[c].LinkProxyMedia(str(arquivo)):
                        saida["renderizados"].append(str(arquivo))
                    else:
                        saida["falhas"].append({"caminho": c, "erro": "sem arquivo ou sem ligar o proxy"})
                    continue
                saida["falhas"].append({"caminho": c, "erro": "tempo esgotado" if esgotou
                                        else st.get("Error") or st.get("JobStatus") or "sem status"})
                if arquivo.is_file():  # render pela metade: não deixa parcial onde achar_proxy acharia
                    tentar(arquivo.unlink)
        terminou = True
    finally:
        if tentar(projeto.IsRenderingInProgress):
            tentar(projeto.StopRendering)
        for _, j in jobs:
            tentar(projeto.DeleteRenderJob, j)
        if not terminou:  # interrompido no meio: nenhum proxy pela metade fica onde achar_proxy acharia
            for c, _ in jobs:
                parcial = destino / f"{nome_no_cache(c)}.mov"
                if str(parcial) in saida["renderizados"]:  # já completo e ligado ao clipe: fica
                    continue
                if parcial.is_file():
                    tentar(parcial.unlink)
        if tl is not None:
            tentar(pool.DeleteTimelines, [tl])
        if not terminou and itens_importados:
            tentar(pool.DeleteClips, [i for _, i in itens_importados])
        elif terminou:  # terminou: só sai do pool o importado que não ganhou proxy
            falhou = {f["caminho"] for f in saida["falhas"]}
            for chave, item in itens_importados:
                if chave in falhou:
                    tentar(pool.DeleteClips, [item])
                    if chave in importados:
                        importados.remove(chave)
        if antes["salvo"]:
            tentar(projeto.LoadRenderPreset, antes["salvo"])
            tentar(projeto.DeleteRenderPreset, antes["salvo"])
        fmt = antes["formato"] or {}
        if fmt.get("format") and fmt.get("codec"):
            tentar(projeto.SetCurrentRenderFormatAndCodec, fmt["format"], fmt["codec"])
        if antes["modo"] is not None:
            tentar(projeto.SetCurrentRenderMode, antes["modo"])
        if atual:  # por último: a timeline do usuário volta depois de tudo
            tentar(projeto.SetCurrentTimeline, atual)
    return saida


def cmd_quadros(revisao: Path, trecho_id: str, perfil_log: Optional[str] = None) -> dict:
    """IRISCUT: nota, métricas, submétricas e flags de cada amostra de um trecho da revisão, com a mídia da prévia
    (o proxy, quando existe) e o filtro de log do clipe. Só lê: não abre o Resolve nem grava nada."""
    import math

    import decisoes
    import presets
    from exportar import escolher_midia
    from segmentos import direcao_camera, etiqueta_camera, flags_quadros, normalizar_tudo, notas_quadros

    rev = decisoes.ler(revisao)
    t = next((x for x in rev.get("trechos", []) if x.get("id") == trecho_id), None)
    if t is None:
        raise SystemExit(f"trecho não está na revisão: {trecho_id}")
    selects = Path(rev["selects"]) if rev.get("selects") else None
    if selects is None or not selects.is_file():
        raise SystemExit(f"selects da revisão não encontrado: {rev.get('selects')}")
    dados = json.loads(selects.read_text(encoding="utf-8"))
    # O preset do painel de seleção (preset_painel.json) fica na pasta do trabalho, ao lado do selects; os outros,
    # na pasta de presets.
    nome_preset = dados.get("preset") or ""
    junto = selects.parent / f"{nome_preset}.json"
    try:
        p = presets.carregar(str(junto) if nome_preset and junto.is_file() else nome_preset)
    except (ValueError, OSError) as e:
        raise SystemExit(f"preset do selects não carrega ({dados.get('preset')}): {e}")
    sidecar = t.get("sidecar")
    sc = json.loads(Path(sidecar).read_text(encoding="utf-8")) if sidecar and Path(sidecar).is_file() else None
    # O IRISCUT chama por trecho, em processo novo: o proxy que a análise já achou fica no sidecar.
    if sc and sc.get("proxy") and Path(sc["proxy"]).is_file():
        midia = sc["proxy"]
    else:
        midia, _ = escolher_midia(t["caminho"], "proxy")
    _, filtro = escolha_de_filtro(dados, perfil_log)(t["caminho"])
    saida = {"id": t["id"], "midia": midia, "filtro": filtro, "aps": None, "t0": None, "camera": None,
             "nota_min": p["nota_min"],
             "amostras": None}
    if sc is None:
        return saida
    q, aps = sc["quadros"], float(sc["amostras_por_s"])
    n = len(q["t"])
    if n == 0:
        return saida
    # Folga de 1e-6: 1,4 s × 5 amostras/s dá 7,000000000000001, e o ceil pularia para a amostra 8.
    a = min(int(math.floor(t["inicio_s"] * aps + 1e-6)), n - 1)
    b = min(max(a + 1, int(math.ceil(t["fim_s"] * aps - 1e-6))), n)
    norm, sub, base = normalizar_tudo(q, p)
    flags = flags_quadros(q, base, p)
    notas = notas_quadros(norm, flags, p)
    f = slice(a, b)
    tipo, confianca = etiqueta_camera(q["cam_dx"][f], q["cam_dy"][f], q["cam_escala"][f], q["tremor"][f],
                                      p["camera"], q["cam_rot"][f] if "cam_rot" in q else None)

    def r3(v):
        return round(float(v), 3)

    saida.update(aps=aps, t0=r3(q["t"][a]),
                 camera={"tipo": tipo, "confianca": confianca,
                         "direcao": direcao_camera(q["cam_dx"][f], q["cam_dy"][f], tipo)},
                 amostras={"t": [r3(x) for x in q["t"][f]],
                           "nota": [None if x is None else r3(x) for x in notas[f]],
                           "metricas": {k: [r3(x) for x in v[f]] for k, v in norm.items()},
                           "submetricas": {k: [r3(x) for x in v[f]] for k, v in sub.items()},
                           "flags": flags[f]})
    return saida


def argumentos() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="davinci", description="Leva um selects.json ao DaVinci Resolve.")
    sub = ap.add_subparsers(dest="comando", required=True)
    for nome in ("marcar", "timeline"):
        p = sub.add_parser(nome)
        p.add_argument("selects", help="caminho do selects.json")
        p.add_argument("--projeto", required=True, help="nome exato do projeto aberto no Resolve (proteção)")
        p.add_argument("--min", type=float, default=None, help="nota mínima do trecho")
        p.add_argument("--sem-flags", action="store_true", help="só trechos sem nenhuma flag")
        p.add_argument("--sem-mao", action="store_true", help="tira trechos de câmera na mão")
    sub.choices["timeline"].add_argument("--nome", required=True, help="nome da timeline nova")
    sub.choices["timeline"].add_argument("--ordem", default="gravacao", choices=sorted(_ORDENS),
                                         help="gravacao (padrão), nota ou duracao")
    rj = sub.add_parser("reajustar", help="duplica uma timeline e troca os takes pelos reajustados")
    rj.add_argument("takes", help="JSON com os takes reajustados (reajuste.reajustar)")
    rj.add_argument("--projeto", required=True)
    rj.add_argument("--original", required=True, help="nome da timeline original (não é alterada)")
    rj.add_argument("--nome", required=True, help="nome da timeline ajustada")
    rj.add_argument("--trilha", type=int, default=2, help="trilha de vídeo dos takes (padrão V2)")
    rv = sub.add_parser("revisao", help="IRISCUT: timeline REVISÃO com todos os trechos e o revisao.json")
    rv.add_argument("selects", help="caminho do selects.json")
    rv.add_argument("--projeto", required=True)
    rv.add_argument("--nome", default="REVISÃO", help="nome da timeline (padrão REVISÃO)")
    rv.add_argument("--ordem", default="gravacao", choices=sorted(_ORDENS))
    rv.add_argument("--saida", default=None,
                    help="caminho da revisão (padrão: ao lado do selects; revisao.json para selects.json, "
                         "revisao_<selects>.json para os outros)")
    rv.add_argument("--perfil-log", default=None, choices=["auto", *PERFIS_LOG],
                    help="perfil de log das prévias (padrão: o do selects; auto lê os metadados da câmera)")
    rv.add_argument("--log", action="store_true", help="atalho de --perfil-log auto")
    rv.add_argument("--sem-miniaturas", action="store_true", help="não gera as contact sheets")
    rv.add_argument("--importar", action="store_true",
                    help="importa antes no Media Pool os clipes do selects que ainda não estão no projeto")
    ap_ = sub.add_parser("aprovados", help="IRISCUT: timeline só com os trechos aprovados")
    ap_.add_argument("revisao", help="caminho do revisao.json")
    ap_.add_argument("--projeto", required=True)
    ap_.add_argument("--nome", default="APROVADOS")
    ap_.add_argument("--ordem", default="gravacao", choices=sorted(_ORDENS))
    md = sub.add_parser("marcar-decisoes", help="IRISCUT: marcador verde/vermelho nos clipes decididos")
    md.add_argument("revisao", help="caminho do revisao.json")
    md.add_argument("--projeto", required=True)
    qd = sub.add_parser("quadros", help="IRISCUT: nota, métricas e flags de cada amostra de um trecho (só leitura)")
    qd.add_argument("revisao", help="caminho do revisao.json")
    qd.add_argument("--trecho", required=True, help="id do trecho")
    qd.add_argument("--perfil-log", default=None, choices=["auto", *PERFIS_LOG],
                    help="perfil de log da prévia (padrão: o do selects)")
    return ap


def principal(argv: Optional[list] = None) -> int:
    args = argumentos().parse_args(argv)
    if args.comando == "quadros":
        # Só leitura e sem Resolve: o IRISCUT chama a cada trecho, com o Resolve aberto ou não.
        print(json.dumps(cmd_quadros(Path(args.revisao), args.trecho, args.perfil_log), ensure_ascii=False))
        return 0
    if args.comando == "reajustar":
        takes = json.loads(Path(args.takes).read_text(encoding="utf-8"))
    elif args.comando in ("marcar", "timeline"):
        dados = json.loads(Path(args.selects).read_text(encoding="utf-8"))
        # A cor sai da divisão do que vai para o Resolve (depois dos filtros); selects antigos ficam nas faixas fixas.
        trechos = colorir(filtrar_trechos(dados["trechos"], args.min, args.sem_flags, args.sem_mao),
                          dados.get("cor_marcador", "fixa"))
    elif args.comando in ("aprovados", "marcar-decisoes"):
        dono = json.loads(Path(args.revisao).read_text(encoding="utf-8")).get("projeto")
        if dono != args.projeto:
            print(f"recusado: a revisão é do projeto '{dono}', não '{args.projeto}'", file=sys.stderr)
            return 2
    gerente = _conectar().GetProjectManager()
    projeto = gerente.GetCurrentProject()
    if projeto is None or projeto.GetName() != args.projeto:
        aberto = projeto.GetName() if projeto else "nenhum"
        print(f"recusado: o projeto aberto é '{aberto}', não '{args.projeto}'", file=sys.stderr)
        return 2
    if args.comando == "reajustar":
        resultado = cmd_reajustar(projeto, takes, args.original, args.nome, args.trilha)
    elif args.comando == "marcar":
        resultado = cmd_marcar(projeto, trechos)
    elif args.comando == "timeline":
        resultado = cmd_timeline(projeto, trechos, args.nome, args.ordem)
    elif args.comando == "revisao":
        resultado = cmd_revisao(projeto, Path(args.selects), args.nome, args.ordem,
                                Path(args.saida) if args.saida else None, not args.sem_miniaturas, args.log,
                                args.perfil_log, args.importar)
    elif args.comando == "aprovados":
        resultado = cmd_aprovados(projeto, Path(args.revisao), args.nome, args.ordem)
    else:
        resultado = cmd_marcar_decisoes(projeto, Path(args.revisao))
    gerente.SaveProject()
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(principal())

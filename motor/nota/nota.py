"""Motor de nota — selects automáticos por foco, exposição, estabilidade e movimento.

  python3 ferramentas/nota/nota.py analisar <pasta|arquivos...>
  python3 ferramentas/nota/nota.py selecionar [pasta...] --preset imovel [--min 0.7] [--camera parada,push_in]
  python3 ferramentas/nota/nota.py relatorio [pasta...]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import resource
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import presets  # noqa: E402
from amostragem import ErroLeitura  # noqa: E402
from analise import COLUNAS_QUADRO, METRICAS_OPCIONAIS, VERSAO_MOTOR, analisar_clipe  # noqa: E402
from proxy import NAO_DECODIFICA, PASTAS_PROXY, achar_proxy, quadros_dng  # noqa: E402
from vigia import Estabilidade  # noqa: E402
from segmentos import (FLAGS, ORDENS, ORDENS_ORIGEM, TIPOS_CAMERA, _ordenar, codigo_caminho, ler_faixas,  # noqa: E402
                       montar_selects)

RAIZ = Path(__file__).resolve().parents[2]
SAIDA_PADRAO = RAIZ / "analise"
EXTENSOES = {".mov", ".mp4", ".mxf", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".mpg"} | NAO_DECODIFICA


def pasta_saida(caminho: str) -> Path:
    p = Path(caminho).expanduser().resolve()
    if "analise" not in p.parts:
        raise SystemExit(f"recusado: a saída precisa ficar dentro de uma pasta 'analise' (recebi {p})")
    return p


def escrever_json(caminho: Path, dados, indent: Optional[int] = None) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=indent), encoding="utf-8")
    os.replace(tmp, caminho)


def _ler_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return padrao


def _pulado(relativo: Path) -> bool:
    """Pastas ocultas (.Trashes, .cache…), pastas de proxy e proxies da Sony (M4ROOT/SUB) não entram:
    o proxy é usado no lugar do original só quando o original não decodifica."""
    partes = relativo.parts[:-1]
    if any(x.startswith(".") or x.lower() in PASTAS_PROXY for x in partes):
        return True
    return any(a.upper() == "M4ROOT" and b.upper() == "SUB" for a, b in zip(partes, partes[1:]))


def coletar_com_contagem(entradas: list):
    """(vídeos, quantos arquivos foram ignorados por causa da extensão)."""
    videos = set()
    pulados = set()
    dng = {}   # pasta → arquivos .dng: a pasta é um clipe se for uma sequência CinemaDNG
    for e in entradas:
        p = Path(e).expanduser().resolve()
        candidatos = p.rglob("*") if p.is_dir() else [p]
        for c in candidatos:
            if not c.is_file() or c.name.startswith("."):
                continue
            if p.is_dir() and _pulado(c.relative_to(p)):
                continue
            if c.suffix.lower() == ".dng":
                dng.setdefault(c.parent, set()).add(str(c))
            elif c.suffix.lower() in EXTENSOES:
                videos.add(str(c))
            else:
                pulados.add(str(c))
    for pasta, arquivos in dng.items():
        if quadros_dng(pasta):
            videos.add(str(pasta))
        else:
            pulados.update(arquivos)
    return sorted(videos), len(pulados)


def coletar(entradas: list) -> list:
    return coletar_com_contagem(entradas)[0]


def filtro_entradas(entradas: Optional[list]):
    """Predicado caminho -> bool: o clipe é um dos coletados das entradas ou fica dentro de uma delas.
    Cada entrada vale como prefixo de caminho mesmo sem existir (cartão ejetado depois do analisar),
    com um aviso no stderr. Sem entradas, aceita tudo (todos os sidecars da saída)."""
    if not entradas:
        return lambda caminho: True
    prefixos = [Path(e).expanduser().resolve() for e in entradas]
    for p in prefixos:
        if not p.exists():
            print(f"aviso: {p} não existe; vale só como prefixo dos caminhos já analisados", file=sys.stderr)
    arquivos = set(coletar([str(p) for p in prefixos if p.exists()]))
    return lambda caminho: caminho in arquivos or any(Path(caminho).is_relative_to(p) for p in prefixos)


def caminho_sidecar(saida: Path, video: str) -> Path:
    return saida / "nota" / f"{Path(video).stem}_{codigo_caminho(video)}.nota.json"


def _tamanho_e_data(video: str) -> tuple:
    """(tamanho, mtime) do clipe. Arquivo: o stat dele. Pasta CinemaDNG: soma dos quadros e o mais recente deles,
    porque o stat da pasta muda com um .DS_Store ou um áudio solto e não diz nada sobre a imagem."""
    quadros = quadros_dng(video) if Path(video).is_dir() else None
    if not quadros:
        st = os.stat(video)
        return st.st_size, st.st_mtime
    sts = [os.stat(q) for q in quadros]
    return sum(x.st_size for x in sts), max(x.st_mtime for x in sts)


def _estado(sidecar: Path, video: str, amostras_por_s: float, largura: int, pular: list) -> str:
    """"ok", "sem_colunas" (bate em tudo, só faltam colunas novas) ou "outro"."""
    d = _ler_json(sidecar, {})
    tamanho, mtime = _tamanho_e_data(video)
    if not (d.get("versao_motor") == VERSAO_MOTOR and d.get("tamanho") == tamanho
            and d.get("mtime") == mtime and d.get("amostras_por_s") == amostras_por_s
            and d.get("largura") == largura and d.get("metricas_puladas", []) == pular):
        return "outro"
    return "ok" if set(COLUNAS_QUADRO) <= set(d.get("quadros", {})) else "sem_colunas"


def _atualizado(sidecar: Path, video: str, amostras_por_s: float, largura: int, pular: list) -> bool:
    return _estado(sidecar, video, amostras_por_s, largura, pular) == "ok"


def _analisar_um(video: str, amostras: float, largura: int, hw: bool, pular: tuple = ()):
    """Roda num processo separado: devolve (vídeo, sidecar, None) ou (vídeo, None, erro)."""
    # Avisa daqui (o worker herda o stdout): com vários workers, o IRISCUT sabe qual clipe começou.
    print(f"analisando: {video}", flush=True)
    try:
        try:
            if Path(video).suffix.lower() in NAO_DECODIFICA or Path(video).is_dir():
                raise ErroLeitura("formato que o ffmpeg não decodifica")
            return video, analisar_clipe(video, amostras, largura, hw=hw, pular=pular), None
        except ErroLeitura as e:
            proxy = achar_proxy(video)
            if proxy is None:
                raise ErroLeitura(f"{e}; nenhum proxy encontrado (pasta Proxy/Proxies ao lado ou M4ROOT/SUB)")
        dados = analisar_clipe(proxy, amostras, largura, hw=hw, pular=pular)
        tamanho, mtime = _tamanho_e_data(video)
        # Os trechos apontam para o original (é ele que está no DaVinci); o proxy fica registrado.
        dados.update(caminho=os.path.abspath(video), tamanho=tamanho, mtime=mtime,
                     proxy=os.path.abspath(proxy))
        return video, dados, None
    except (ErroLeitura, OSError, ValueError, KeyError) as e:
        return video, None, str(e)


def _analisar_lista(pendentes: list, saida: Path, falhas: dict, amostras: float, largura: int, hw: bool,
                    pular: list, workers: int) -> None:
    """Analisa `pendentes` (em paralelo quando workers > 1), grava os sidecars e atualiza `falhas`."""
    def registrar(feitos: int, video: str, dados, erro) -> None:
        # Só o processo principal grava, então não há disputa por arquivo.
        if erro is not None:
            falhas[video] = erro
            print(f"[{feitos}/{len(pendentes)}] falhou: {video}: {erro}", file=sys.stderr, flush=True)
            return
        escrever_json(caminho_sidecar(saida, video), dados)
        falhas.pop(video, None)
        via = f" (via proxy {Path(dados['proxy']).name})" if dados.get("proxy") else ""
        print(f"[{feitos}/{len(pendentes)}] analisado: {video}{via}", flush=True)

    if workers == 1 or len(pendentes) <= 1:
        for n, video in enumerate(pendentes, 1):
            registrar(n, *_analisar_um(video, amostras, largura, hw, tuple(pular)))
    else:
        with ProcessPoolExecutor(max_workers=min(workers, len(pendentes))) as pool:
            tarefas = [pool.submit(_analisar_um, v, amostras, largura, hw, tuple(pular)) for v in pendentes]
            for n, tarefa in enumerate(as_completed(tarefas), 1):
                registrar(n, *tarefa.result())


def cmd_analisar(args) -> int:
    if args.workers < 1:
        print("--workers precisa ser 1 ou mais", file=sys.stderr)
        return 2
    pular = sorted(set(_lista(args.sem_metricas) or []))
    erro = _desconhecidos(pular, METRICAS_OPCIONAIS, "--sem-metricas")
    if erro:
        print(erro, file=sys.stderr)
        return 2
    if args.amostras is None:
        args.amostras = 4.0
        if args.preset:
            try:
                p = presets.carregar(args.preset)
            except ValueError as e:
                print(str(e), file=sys.stderr)
                return 2
            args.amostras = float(p["amostras_por_s"] or 4.0)
    inicio = time.monotonic()
    saida = pasta_saida(args.saida)
    videos, pulados = coletar_com_contagem(args.entradas)
    if pulados:
        print(f"{pulados} arquivo(s) ignorado(s) pela extensão (aceitas: {', '.join(sorted(EXTENSOES))})")
    arquivo_falhas = saida / "nota" / "falhas.json"
    falhas = _ler_json(arquivo_falhas, {})
    total = len(videos)
    pendentes = []
    antigas = 0
    for i, video in enumerate(videos, 1):
        sidecar = caminho_sidecar(saida, video)
        estado = _estado(sidecar, video, args.amostras, args.largura, pular) if sidecar.exists() else "outro"
        if not args.forcar and estado == "ok":
            print(f"[{i}/{total}] já analisado: {video}")
        else:
            antigas += not args.forcar and estado == "sem_colunas"
            pendentes.append(video)
    if antigas:
        print(f"refazendo {antigas} análise(s) antiga(s) sem as colunas novas (detalhe, luma, rotação)")

    _analisar_lista(pendentes, saida, falhas, args.amostras, args.largura, not args.sem_hw, pular, args.workers)
    escrever_json(arquivo_falhas, falhas, indent=2)
    print(f"{total - len([v for v in videos if v in falhas])} de {total} clipes analisados → {saida / 'nota'}")
    cpu = sum(resource.getrusage(q).ru_utime + resource.getrusage(q).ru_stime
              for q in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN))
    gasto = time.monotonic() - inicio
    print(f"tempo: {gasto / 60:.1f} min · CPU {cpu / 60:.1f} min · {args.workers} worker(s)"
          + (f" · sem {', '.join(pular)}" if pular else ""))
    return 0


def _lista(texto: Optional[str]) -> Optional[list]:
    return [x.strip() for x in texto.split(",") if x.strip()] if texto else None


def _desconhecidos(valores: Optional[list], validos: tuple, nome: str) -> Optional[str]:
    ruins = [v for v in valores or [] if v not in validos]
    if ruins:
        return f"{nome} desconhecido(s): {', '.join(ruins)} (válidos: {', '.join(validos)})"
    return None


def _info_do_clipe(video: str) -> dict:
    """Dados do arquivo para a lista de clipes do IRISCUT, só pelo ffprobe (nada é gravado)."""
    from amostragem import probe
    from proxy import timecode_de_inicio
    base = {"caminho": video, "nome": Path(video).name, "duracao": None, "largura": None, "altura": None,
            "fps": None, "codec": None, "tc_inicio_s": None, "online": os.path.exists(video), "erro": None}
    if not base["online"]:
        return {**base, "erro": "arquivo não encontrado (disco desconectado?)"}
    if Path(video).is_dir():   # sequência CinemaDNG: os dados vêm na análise (via proxy), não é erro
        return {**base, "codec": "cinemadng"}
    try:
        i = probe(video, timeout=20)
    except (ErroLeitura, OSError, ValueError, KeyError) as e:
        return {**base, "erro": str(e) or "o ffprobe não leu o arquivo"}
    return {**base, "duracao": round(i.duracao, 3), "largura": i.largura, "altura": i.altura,
            "fps": round(i.fps, 3), "codec": i.codec, "tc_inicio_s": timecode_de_inicio(video)}


def cmd_clipes(args) -> int:
    from concurrent.futures import ThreadPoolExecutor
    # Arquivos que não existem mais (cartão ejetado) entram como estão, para a lista mostrar Offline.
    videos = coletar([e for e in args.entradas if os.path.exists(e)]) + [e for e in args.entradas if not os.path.exists(e)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        print(json.dumps(list(pool.map(_info_do_clipe, videos)), ensure_ascii=False))
    return 0


def cmd_formatos(_args) -> int:
    """Tabela de compatibilidade do IRISCUT (a Compatibility do Cutdown): o que o motor lê direto e o que vai pelo
    proxy (RAW e sequência CinemaDNG)."""
    from proxy import NAO_DECODIFICA
    linhas = [{"extensao": e, "analise": "proxy" if e in NAO_DECODIFICA else "direta"} for e in sorted(EXTENSOES)]
    linhas.append({"extensao": ".dng", "analise": "proxy"})
    print(json.dumps({"versao_motor": VERSAO_MOTOR, "formatos": linhas}, ensure_ascii=False))
    return 0


def cmd_preset(args) -> int:
    try:
        print(json.dumps(presets.bruto(args.nome), ensure_ascii=False))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


def cmd_selecionar(args) -> int:
    saida = pasta_saida(args.saida)
    nome_arquivo = getattr(args, "arquivo", None) or "selects.json"
    if not re.fullmatch(r"selects[\w-]*\.json", nome_arquivo):
        print(f"--arquivo precisa ser selects*.json na pasta de saída (recebi {nome_arquivo})", file=sys.stderr)
        return 2
    for erro in (_desconhecidos(_lista(args.camera), TIPOS_CAMERA, "--camera"),
                 _desconhecidos(_lista(args.excluir), FLAGS, "--excluir")):
        if erro:
            print(erro, file=sys.stderr)
            return 2
    try:
        direcoes = ler_faixas(args.direcao) if args.direcao is not None else None
        p = presets.carregar(args.preset)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    for flag in _lista(args.excluir) or []:
        p["flags"][flag] = "excluir"
    arquivo_ajustes = Path(args.ajustes).expanduser() if args.ajustes else saida / "ajustes.json"
    ajustes = {}
    if arquivo_ajustes.exists():
        try:
            ajustes = json.loads(arquivo_ajustes.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"{arquivo_ajustes}: não é JSON válido: {e}", file=sys.stderr)
            return 2
        if not isinstance(ajustes, dict):
            print(f"{arquivo_ajustes}: precisa ser um objeto {{clipe: ajuste}}", file=sys.stderr)
            return 2
    elif args.ajustes:
        print(f"arquivo de ajustes não encontrado: {arquivo_ajustes}", file=sys.stderr)
        return 2
    sidecars = [_ler_json(f, None) for f in sorted((saida / "nota").glob("*.nota.json"))]
    aceita = filtro_entradas(args.entradas)
    sidecars = [s for s in sidecars if s and s.get("versao_motor") == VERSAO_MOTOR and aceita(s.get("caminho", ""))]
    cameras = _lista(args.camera)
    from perfis_log import filtro_de_lut
    try:
        filtro = filtro_de_lut(p["miniatura_lut"]) if p["miniatura_lut"] else None
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        resultado = montar_selects(sidecars, p, nota_min=args.min, cameras=cameras, ordem=args.ordem, direcoes=direcoes,
                                   ajustes=ajustes, nota_max=args.max, max_por_clipe=args.max_por_clipe)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    # Timecode e data de cada clipe, para as ordens timecode e data (inclusive quem reordenar depois).
    from exportar import com_metadados
    com_metadados(resultado["trechos"])
    if args.ordem in ORDENS_ORIGEM:
        _ordenar(resultado["trechos"], args.ordem)
    for chave in resultado["ajustes_sem_clipe"]:
        print(f"aviso: o ajuste '{chave}' não casou com nenhum clipe analisado", file=sys.stderr)
    falhas = {k: v for k, v in _ler_json(saida / "nota" / "falhas.json", {}).items() if aceita(k)}
    selects = {
        "versao_motor": VERSAO_MOTOR,
        "preset": p["nome"],
        "cor_marcador": p["cor_marcador"],
        "filtros": {"min": args.min, "max": args.max, "max_por_clipe": args.max_por_clipe, "camera": cameras, "direcao": direcoes, "excluir": _lista(args.excluir), "ordem": args.ordem,
                    "ajustes": str(arquivo_ajustes) if ajustes else None,
                    "entradas": [str(Path(e).expanduser().resolve()) for e in args.entradas] or None},
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "campos_relatorio": p["campos"]["relatorio"],
        "miniatura_filtro": filtro,
        "miniatura_perfil": p["perfil_log"],
        "trechos": resultado["trechos"],
        "avisos": resultado["avisos"],
        "falhas": [{"caminho": k, "erro": v} for k, v in sorted(falhas.items())],
    }
    if getattr(args, "com_descartados", False):
        selects["descartados"] = resultado["descartados"]
        from segmentos import segundos_por_flag
        flags_s = {}
        for sc in sidecars:
            for f, seg in segundos_por_flag(sc, p).items():
                flags_s[f] = flags_s.get(f, 0.0) + seg
        selects["material"] = {"clipes": len(sidecars), "duracao_s": round(sum(s.get("duracao") or 0 for s in sidecars), 3),
                               "flags_s": {f: round(v, 2) for f, v in sorted(flags_s.items())}}
    destino = saida / nome_arquivo
    escrever_json(destino, selects, indent=2)
    print(f"{len(selects['trechos'])} trechos de {len(sidecars)} clipes (preset {p['nome']}) → {destino}")
    return 0


def cmd_relatorio(args) -> int:
    from relatorio import gerar

    saida = pasta_saida(args.saida)
    selects = _ler_json(saida / "selects.json", None)
    if selects is None:
        print("rode 'selecionar' antes do relatório", file=sys.stderr)
        return 2
    if args.entradas:
        aceita = filtro_entradas(args.entradas)
        for chave in ("trechos", "avisos", "falhas"):
            selects[chave] = [x for x in selects.get(chave) or [] if aceita(x["caminho"])]
    print(f"relatório → {gerar(selects, saida, args.top)} e {saida / 'selects.html'}")
    return 0


def _exportar_otio(trechos, info, nome, destino):
    from exportar import para_otio
    escrever_json(destino, para_otio(trechos, info, nome), indent=2)


def _exportar_fcpxml(trechos, info, nome, destino):
    from exportar import escrever_texto, para_fcpxml
    escrever_texto(destino, para_fcpxml(trechos, info, nome))


def _exportar_xml(trechos, info, nome, destino):
    from exportar import escrever_texto
    from exportar_fcp7 import para_xml
    escrever_texto(destino, para_xml(trechos, info, nome))


def _exportar_csv(trechos, info, nome, destino):
    from exportar import escrever_texto
    from exportar_tabela import para_csv
    escrever_texto(destino, para_csv(trechos, info))


def _exportar_txt(trechos, info, nome, destino):
    from exportar import escrever_texto
    from exportar_tabela import para_txt
    escrever_texto(destino, para_txt(trechos, info))


def _exportar_aaf(trechos, info, nome, destino):
    from exportar_aaf import escrever_aaf
    escrever_aaf(trechos, info, nome, destino)


# Formato → função (trechos, info, nome, destino). As tabelas (csv, txt) mostram original e proxy lado a lado,
# então não trocam a mídia.
_EXPORTADORES = {"otio": _exportar_otio, "fcpxml": _exportar_fcpxml, "xml": _exportar_xml, "aaf": _exportar_aaf,
                 "csv": _exportar_csv, "txt": _exportar_txt}
_TABELAS = ("csv", "txt")


def cmd_exportar(args) -> int:
    from davinci import _ORDENS, filtrar_trechos
    from exportar import colorir, info_clipe, trocar_midia

    saida = pasta_saida(args.saida)
    nome_selects = getattr(args, "selects", None) or "selects.json"
    if not re.fullmatch(r"selects[\w-]*\.json", nome_selects):
        print(f"--selects precisa ser selects*.json na pasta de saída (recebi {nome_selects})", file=sys.stderr)
        return 2
    selects = _ler_json(saida / nome_selects, None)
    if selects is None:
        print("rode 'selecionar' antes do exportar", file=sys.stderr)
        return 2
    aceita = filtro_entradas(args.entradas)
    trechos = [t for t in filtrar_trechos(selects["trechos"], args.min, args.sem_flags, args.sem_mao)
               if aceita(t["caminho"])]
    if not trechos:
        print("nenhum trecho para exportar (filtros restritivos demais?)", file=sys.stderr)
        return 2
    trechos.sort(key=_ORDENS[args.ordem])
    trechos = colorir(trechos, selects.get("cor_marcador", "fixa"))
    if args.formato not in _TABELAS:
        trechos, sem_proxy = trocar_midia(trechos, args.midia)
        if sem_proxy:
            nomes = ", ".join(sem_proxy[:5]) + ("…" if len(sem_proxy) > 5 else "")
            print(f"aviso: sem proxy para {len(sem_proxy)} clipe(s): {nomes}")
    info = {c: info_clipe(c) for c in sorted({t["caminho"] for t in trechos})}
    destino = saida / "export" / f"{args.nome}.{args.formato}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        _EXPORTADORES[args.formato](trechos, info, args.nome, destino)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"{len(trechos)} trechos de {len(info)} clipes → {destino}")
    return 0


def cmd_proxies(args) -> int:
    """Proxies renderizados pelo Resolve para o que o ffmpeg não lê e ainda não tem proxy."""
    import davinci
    import proxy

    videos = coletar(args.entradas)
    alvos = [v for v in videos if args.todos or (not proxy.decodifica(v) and proxy.achar_proxy(v) is None)]
    if not alvos:
        print("nenhum clipe precisa de proxy")
        return 0
    gerente = davinci._conectar().GetProjectManager()
    projeto = gerente.GetCurrentProject()
    if projeto is None or projeto.GetName() != args.projeto:
        aberto = projeto.GetName() if projeto else "nenhum"
        print(f"recusado: o projeto aberto é '{aberto}', não '{args.projeto}'", file=sys.stderr)
        return 2
    print(f"renderizando {len(alvos)} proxy(s) no Resolve → {proxy.PASTA_PROXIES}", flush=True)
    resultado = davinci.cmd_proxies(projeto, alvos)
    gerente.SaveProject()
    print(json.dumps(resultado, ensure_ascii=False))
    return 1 if resultado["falhas"] else 0


def cmd_vigiar(args) -> int:
    try:
        p = presets.carregar(args.preset)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    saida = pasta_saida(args.saida)
    # Os mesmos ajustes de amostragem e métricas do analisar: com outros, a vigia refaria o que já foi analisado.
    amostras = float(args.amostras or p["amostras_por_s"] or 4.0)
    pular = sorted(set(_lista(args.sem_metricas) or []))
    erro = _desconhecidos(pular, METRICAS_OPCIONAIS, "--sem-metricas")
    if erro:
        print(erro, file=sys.stderr)
        return 2
    estabilidade = Estabilidade(args.estavel)
    print(f"vigiando {', '.join(args.entradas)} (preset {p['nome']}; Ctrl-C para parar)", flush=True)
    ciclo = 0
    try:
        while True:
            ciclo += 1
            tamanhos = {}
            for v in coletar(args.entradas):
                try:
                    tamanhos[v] = os.stat(v).st_size
                except OSError:
                    continue
            prontos = [v for v in estabilidade.prontos(tamanhos, time.monotonic())
                       if not (caminho_sidecar(saida, v).exists()
                               and _atualizado(caminho_sidecar(saida, v), v, amostras, args.largura, pular))]
            if prontos:
                arquivo_falhas = saida / "nota" / "falhas.json"
                falhas = _ler_json(arquivo_falhas, {})
                _analisar_lista(prontos, saida, falhas, amostras, args.largura, not args.sem_hw, pular, args.workers)
                escrever_json(arquivo_falhas, falhas, indent=2)
                base = dict(entradas=args.entradas, saida=args.saida)
                cmd_selecionar(argparse.Namespace(**base, preset=args.preset, min=None, max=None, max_por_clipe=None,
                                                  camera=None, direcao=None, excluir=None, ordem=args.ordem,
                                                  ajustes=None))
                cmd_relatorio(argparse.Namespace(**base, top=args.top))
            if args.ciclos and ciclo >= args.ciclos:
                break
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("vigia parada")
    return 0


def principal(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="nota", description="Selects automáticos por foco, exposição e movimento.")
    sub = ap.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("analisar", help="analisa os clipes (passo pesado, uma vez)")
    a.add_argument("entradas", nargs="+", help="pastas ou arquivos de vídeo")
    a.add_argument("--amostras", type=float, default=None,
                   help="quadros analisados por segundo (padrão: o do --preset, senão 4)")
    a.add_argument("--preset", default=None, help="usa o amostras_por_s deste preset")
    a.add_argument("--forcar", action="store_true",
                   help="analisa de novo mesmo o que já foi analisado (ex.: para ganhar uma medida nova)")
    a.add_argument("--sem-metricas", default=None,
                   help=f"pula métricas caras que o preset não usa: {', '.join(METRICAS_OPCIONAIS)}")
    a.add_argument("--largura", type=int, default=320, help="largura de análise em pixels")
    a.add_argument("--sem-hw", action="store_true", help="não usar VideoToolbox")
    a.add_argument("--workers", type=int, default=3,
                   help="clipes analisados ao mesmo tempo (padrão 3; no M4 Pro com HEVC 4K satura em 3–4)")
    a.add_argument("--saida", default=str(SAIDA_PADRAO))
    a.set_defaults(func=cmd_analisar)

    s = sub.add_parser("selecionar", help="aplica um preset e gera selects.json (rápido)")
    s.add_argument("entradas", nargs="*", help="só os clipes destas pastas/arquivos (padrão: todos da saída)")
    s.add_argument("--preset", default="imovel", help=f"nome ou caminho .json ({', '.join(presets.listar())})")
    s.add_argument("--min", type=float, default=None, help="nota mínima do trecho")
    s.add_argument("--max", type=float, default=None, help="nota máxima do trecho (modo limpeza: pega os piores)")
    s.add_argument("--max-por-clipe", type=int, default=None, help="no máximo N trechos por clipe (os melhores)")
    s.add_argument("--camera", default=None, help="tipos aceitos, ex.: parada,push_in")
    s.add_argument("--direcao", default=None,
                   help="faixas de direção da câmera em graus (0 = direita, 90 = cima), ex.: 60-120 ou 350-10,170-190")
    s.add_argument("--excluir", default=None, help="flags que passam a excluir, ex.: blur,tremido")
    s.add_argument("--ordem", default="nota", choices=ORDENS,
                   help="nota (padrão), nota_asc, duracao, duracao_asc ou gravacao")
    s.add_argument("--ajustes", default=None,
                   help="JSON {clipe: ajuste} por clipe (padrão: ajustes.json na pasta de saída, se existir)")
    s.add_argument("--arquivo", default="selects.json",
                   help="nome do arquivo na pasta de saída (selects*.json; o painel de seleção usa selects_painel.json)")
    s.add_argument("--com-descartados", action="store_true",
                   help="grava também os trechos que os filtros tiraram, com o motivo (gráfico do IRISCUT)")
    s.add_argument("--saida", default=str(SAIDA_PADRAO))
    s.set_defaults(func=cmd_selecionar)

    cl = sub.add_parser("clipes", help="lista os clipes das entradas com duração, resolução e fps, em JSON (IRISCUT)")
    cl.add_argument("entradas", nargs="+", help="pastas ou arquivos de vídeo")
    cl.set_defaults(func=cmd_clipes)

    fo = sub.add_parser("formatos", help="extensões que o motor lê e as que vão pelo proxy, em JSON (IRISCUT)")
    fo.set_defaults(func=cmd_formatos)

    pr = sub.add_parser("preset", help="imprime o preset mesclado com o padrão, em JSON (painel de seleção)")
    pr.add_argument("nome", help="nome ou caminho .json do preset")
    pr.set_defaults(func=cmd_preset)

    r = sub.add_parser("relatorio", help="gera selects.md e contact sheets")
    r.add_argument("entradas", nargs="*", help="só os trechos destas pastas/arquivos (padrão: todos)")
    r.add_argument("--top", type=int, default=50, help="quantos trechos entram no relatório")
    r.add_argument("--saida", default=str(SAIDA_PADRAO))
    r.set_defaults(func=cmd_relatorio)

    e = sub.add_parser("exportar", help="exporta os selects para Resolve, Premiere, Final Cut, Avid ou planilha")
    e.add_argument("entradas", nargs="*", help="só os trechos destas pastas/arquivos (padrão: todos)")
    e.add_argument("--formato", required=True, choices=tuple(_EXPORTADORES))
    e.add_argument("--midia", default="original", choices=("original", "proxy", "auto"),
                   help="original, proxy (quando existe) ou auto (proxy só para o que o ffmpeg não lê)")
    e.add_argument("--nome", required=True, help="nome da timeline e do arquivo")
    e.add_argument("--ordem", default="gravacao", choices=ORDENS)
    e.add_argument("--min", type=float, default=None, help="nota mínima do trecho")
    e.add_argument("--sem-flags", action="store_true", help="só trechos sem nenhuma flag")
    e.add_argument("--sem-mao", action="store_true", help="tira trechos de câmera na mão")
    e.add_argument("--selects", default="selects.json",
                   help="arquivo de selects na pasta de saída (o painel de seleção usa selects_painel.json)")
    e.add_argument("--saida", default=str(SAIDA_PADRAO))
    e.set_defaults(func=cmd_exportar)

    v = sub.add_parser("vigiar", help="analisa cada clipe que chega na pasta e atualiza selects e relatório")
    v.add_argument("entradas", nargs="+", help="pastas a vigiar")
    v.add_argument("--preset", default="imovel", help="preset dos selects (e do amostras_por_s)")
    v.add_argument("--estavel", type=float, default=10.0, help="segundos com o tamanho parado = cópia terminou")
    v.add_argument("--amostras", type=float, default=None, help="quadros analisados por segundo (padrão: o do preset)")
    v.add_argument("--sem-metricas", default=None, help=f"pula métricas caras: {', '.join(METRICAS_OPCIONAIS)}")
    v.add_argument("--intervalo", type=float, default=5.0, help="segundos entre as varreduras")
    v.add_argument("--ciclos", type=int, default=0, help="para depois de N varreduras (0 = até Ctrl-C)")
    v.add_argument("--ordem", default="nota", choices=ORDENS)
    v.add_argument("--top", type=int, default=50, help="trechos no relatório")
    v.add_argument("--largura", type=int, default=320)
    v.add_argument("--workers", type=int, default=3)
    v.add_argument("--sem-hw", action="store_true")
    v.add_argument("--saida", default=str(SAIDA_PADRAO))
    v.set_defaults(func=cmd_vigiar)

    px = sub.add_parser("proxies", help="o Resolve renderiza proxies (analise/proxies/) do que o ffmpeg não lê")
    px.add_argument("entradas", nargs="+", help="pastas ou arquivos de vídeo")
    px.add_argument("--projeto", required=True, help="nome exato do projeto aberto no Resolve (proteção)")
    px.add_argument("--todos", action="store_true", help="renderiza todos, mesmo os que o ffmpeg lê (para teste)")
    px.set_defaults(func=cmd_proxies)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(principal())

"""Acha o proxy de um original que o ffmpeg não decodifica (BRAW, R3D) ou que está corrompido: pelo nome, ou pelo
timecode de início e pela duração quando o nome não bate."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

# Formatos de câmera que o ffmpeg não decodifica: vão direto para o proxy.
NAO_DECODIFICA = {".braw", ".r3d", ".ari", ".arx", ".crm", ".nev"}
# Nomes de pasta onde câmeras, o Resolve e geradores externos costumam pôr proxies (comparados sem maiúsculas).
PASTAS_PROXY = {"proxy", "proxies", "clip_proxy", "proxy media", "proxy_media"}
EXT_PROXY = {".mov", ".mp4", ".mxf", ".m4v"}
# ffprobe de cada arquivo já lido: (caminho, tamanho, mtime) → (início do timecode em s, duração em s, fps) ou None.
_ASSINATURAS: dict = {}
# Acima disso o casamento pelo timecode desiste: um ffprobe por candidato numa pasta enorme custaria minutos.
MAX_CANDIDATOS = 50
# Sequência CinemaDNG: uma pasta com pelo menos isto de .dng de mesmo prefixo e numeração seguida é um clipe.
QUADROS_MIN_DNG = 24
_NUMERADO = re.compile(r"^(.*?)(\d+)$")
# Proxies que o próprio Resolve renderiza (nota.py proxies) para o que o ffmpeg não lê: X-OCN, N-RAW, CinemaDNG…
PASTA_PROXIES = Path(__file__).resolve().parents[2] / "analise" / "proxies"


def _no_diretorio(pasta: Path, aceita) -> Optional[str]:
    if not pasta.is_dir():
        return None
    for c in sorted(pasta.iterdir()):
        if c.is_file() and not c.name.startswith(".") and c.suffix.lower() in EXT_PROXY and aceita(c.stem):
            return str(c)
    return None


def quadros_dng(pasta) -> Optional[list]:
    """Quadros da sequência CinemaDNG da pasta, em ordem, ou None. Fotos .dng soltas (numeração com buracos) e
    pastas com menos de QUADROS_MIN_DNG quadros não são sequência."""
    p = Path(pasta)
    if not p.is_dir():
        return None
    grupos = {}
    for f in p.iterdir():
        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() == ".dng":
            m = _NUMERADO.match(f.stem)
            if m:
                grupos.setdefault(m.group(1), []).append((int(m.group(2)), f))
    if not grupos:
        return None
    quadros = sorted(max(grupos.values(), key=len))
    if len(quadros) < QUADROS_MIN_DNG or quadros[-1][0] - quadros[0][0] + 1 != len(quadros):
        return None
    return [f for _, f in quadros]


def nome_no_cache(original: str) -> str:
    """Nome (sem extensão) do proxy em PASTA_PROXIES: nome do clipe + 6 primeiros do código do caminho, para dois
    clipes de mesmo nome em pastas diferentes não se misturarem."""
    from segmentos import codigo_caminho

    return f"{Path(original).stem}_{codigo_caminho(original)[:6]}"


def decodifica(caminho: str) -> bool:
    """O ffmpeg tira o primeiro quadro? X-OCN em .mxf, por exemplo, não."""
    if Path(caminho).is_dir() or Path(caminho).suffix.lower() in NAO_DECODIFICA:
        return False
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", caminho, "-frames:v", "1", "-f", "null", "-"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _ler_assinatura(caminho: str) -> Optional[tuple]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=r_frame_rate,duration:stream_tags=timecode:format=duration:format_tags=timecode", "-of", "json", caminho]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        d = json.loads(r.stdout or "{}")
        video = (d.get("streams") or [{}])[0]
        fmt = d.get("format") or {}
        tc = (video.get("tags") or {}).get("timecode") or (fmt.get("tags") or {}).get("timecode")
        num, den = (video.get("r_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den)
        # Duração do fluxo de vídeo quando existe (a do contêiner inclui o áudio, que pode ser mais longo).
        duracao = float(video.get("duration") or fmt.get("duration"))
        h, m, s, f = (int(x) for x in str(tc).replace(";", ":").split(":"))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, ZeroDivisionError):
        return None
    if fps <= 0:
        return None
    # O timecode conta quadros nominais (23,976 → 24).
    return (h * 60 + m) * 60 + s + f / round(fps), duracao, fps


def _assinatura(caminho) -> Optional[tuple]:
    try:
        st = os.stat(caminho)
    except OSError:
        return None
    chave = (str(caminho), st.st_size, st.st_mtime)
    if chave not in _ASSINATURAS:
        _ASSINATURAS[chave] = _ler_assinatura(str(caminho))
    return _ASSINATURAS[chave]


def timecode_de_inicio(caminho) -> Optional[float]:
    """Início do timecode do arquivo em segundos (quadros nominais), ou None sem timecode."""
    a = _assinatura(caminho)
    return a[0] if a else None


def _casa(a: tuple, b: Optional[tuple]) -> bool:
    """Mesmo início de timecode e mesma duração, com folga de 1 quadro."""
    if b is None:
        return False
    folga = 1.0 / min(a[2], b[2]) + 1e-6
    return abs(a[0] - b[0]) <= folga and abs(a[1] - b[1]) <= folga


def _radical(stem: str) -> str:
    """Nome-base de um arquivo: sem maiúsculas, sem _proxy/-proxy e sem o sufixo S<dígitos> dos SUB da Sony."""
    s = stem.lower()
    for suf in ("_proxy", "-proxy"):
        if s.endswith(suf):
            return s[:-len(suf)]
    i = s.rfind("s")
    if i > 0 and s[i + 1:].isdigit():
        return s[:i]
    return s


def _candidatos(o: Path) -> list:
    """Arquivos das pastas onde o casamento pelo nome procura (Sony M4ROOT/SUB e pastas de proxy), menos os que
    já levam o nome de outro original da mesma pasta (o proxy de outra câmera sincronizada não é o deste clipe)."""
    outros = set()
    if o.parent.is_dir():
        outros = {_radical(f.stem) for f in o.parent.iterdir()
                  if f.is_file() and not f.name.startswith(".") and f != o}
    pastas = []
    if o.parent.name.upper() == "CLIP" and o.parent.parent.name.upper() == "M4ROOT":
        pastas.append(o.parent.parent / "SUB")
    for base in (o.parent, o.parent.parent):
        if base.is_dir():
            pastas.extend(p for p in sorted(base.iterdir()) if p.is_dir() and p.name.lower() in PASTAS_PROXY)
    saida = []
    for pasta in pastas:
        if not pasta.is_dir():
            continue
        for c in sorted(pasta.iterdir()):
            if (c.is_file() and not c.name.startswith(".") and c.suffix.lower() in EXT_PROXY and c != o
                    and c not in saida and _radical(c.stem) not in outros):
                saida.append(c)
    return saida


def achar_proxy(original: str) -> Optional[str]:
    o = Path(original)
    nome = o.stem.lower()

    # Sony: .../M4ROOT/CLIP/C0001.MP4 → .../M4ROOT/SUB/C0001S03.MP4
    if o.parent.name.upper() == "CLIP" and o.parent.parent.name.upper() == "M4ROOT":
        achado = _no_diretorio(o.parent.parent / "SUB",
                               lambda s: s.lower().startswith(nome + "s") and s[len(nome) + 1:].isdigit())
        if achado:
            return achado

    # Pasta de proxy dentro da pasta do original ou ao lado dela, com o mesmo nome (ou nome_proxy).
    aceita = lambda s: s.lower() in (nome, nome + "_proxy", nome + "-proxy")  # noqa: E731
    for base in (o.parent, o.parent.parent):
        if not base.is_dir():
            continue
        for pasta in sorted(base.iterdir()):
            if pasta.is_dir() and pasta.name.lower() in PASTAS_PROXY:
                achado = _no_diretorio(pasta, aceita)
                if achado:
                    return achado
    # Proxy que o Resolve renderizou (nota.py proxies), pelo nome com o código do caminho.
    no_cache = nome_no_cache(original).lower()
    feito = _no_diretorio(PASTA_PROXIES, lambda s: s.lower() == no_cache)
    if feito:
        return feito
    # Nome diferente (proxy renomeado, gerador externo): casa pelo timecode de início e pela duração. Sem
    # candidato não chama o ffprobe; com mais de um igual, não escolhe.
    candidatos = _candidatos(o)
    if len(candidatos) > MAX_CANDIDATOS:
        return None
    alvo = _assinatura(o) if candidatos else None
    if alvo is None:
        return None
    achados = [c for c in candidatos if _casa(alvo, _assinatura(c))]
    return str(achados[0]) if len(achados) == 1 else None

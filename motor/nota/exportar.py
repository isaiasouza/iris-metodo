"""Export dos selects para outros editores: OpenTimelineIO (.otio) e FCPXML 1.14, e o que todos os formatos usam (tempo, timecode, mídia).

Cada trecho vira um clipe na timeline, em sequência, com um marcador de mesmo nome. Os tempos de origem
somam o timecode de início do arquivo (câmeras Sony gravam o timecode da hora do dia), senão o editor
abre o trecho no lugar errado. Só lê os vídeos (ffprobe); não escreve nada perto deles.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

from proxy import NAO_DECODIFICA, achar_proxy, timecode_de_inicio

_CORES_OTIO = {"Green": "GREEN", "Yellow": "YELLOW", "Blue": "BLUE"}
# A timeline começa em 01:00:00:00, como as timelines novas do DaVinci.


def fps_racional(fps: float) -> Fraction:
    """23.976… → 24000/1001, 25.0 → 25, 29.97… → 30000/1001."""
    return Fraction(fps).limit_denominator(1001)


def timecode_em_quadros(tc: Optional[str], fps: float) -> int:
    """'HH:MM:SS:FF' (ou ';' em drop frame, tratado como contagem simples) em quadros desde 00:00:00:00."""
    if not tc:
        return 0
    partes = [int(x) for x in tc.replace(";", ":").split(":")]
    if len(partes) != 4:
        return 0
    h, m, s, f = partes
    return (h * 3600 + m * 60 + s) * round(fps) + f


def quadros_em_timecode(quadros: int, fps: float) -> str:
    """Quadros desde 00:00:00:00 em 'HH:MM:SS:FF' (contagem simples, como timecode_em_quadros)."""
    base = round(fps)
    segundos, f = divmod(int(quadros), base)
    return f"{segundos // 3600:02d}:{segundos // 60 % 60:02d}:{segundos % 60:02d}:{f:02d}"



def info_clipe(caminho: str) -> dict:
    """fps, largura, altura, duração em quadros e timecode de início, pelo ffprobe (só leitura)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,avg_frame_rate,r_frame_rate,duration:stream_tags=timecode"
                        ":format=duration:format_tags=timecode", "-of", "json", caminho],
                       capture_output=True, text=True)
    dados = json.loads(r.stdout or "{}")
    video = next((s for s in dados.get("streams", []) if s.get("codec_type") == "video"), {})
    fracao = video.get("avg_frame_rate") or video.get("r_frame_rate") or "24/1"
    n, d = (fracao.split("/") + ["1"])[:2]
    fps = float(n) / float(d) if float(d) else 24.0
    tc = (dados.get("format", {}).get("tags", {}) or {}).get("timecode")
    for s in dados.get("streams", []):
        tc = tc or (s.get("tags") or {}).get("timecode")
    duracao = float(video.get("duration") or dados.get("format", {}).get("duration") or 0.0)
    return {"fps": fps, "largura": int(video.get("width") or 1920), "altura": int(video.get("height") or 1080),
            "duracao_quadros": int(round(duracao * fps)), "tc_inicio": timecode_em_quadros(tc, fps)}


def metadados_clipe(caminho: str) -> dict:
    """Timecode de início (s) e data de gravação (UTC) do clipe, para as ordens timecode e data. Só leitura.

    A data é o creation_time do arquivo; sem ele, a data de modificação. Arquivo inacessível: os dois None."""
    gravado = None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time", "-of", "json",
                            caminho], capture_output=True, text=True, timeout=10)
        bruto = ((json.loads(r.stdout or "{}").get("format") or {}).get("tags") or {}).get("creation_time")
        if bruto and len(bruto) >= 19:
            gravado = bruto[:19] + "Z"
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if gravado is None:
        try:
            gravado = datetime.fromtimestamp(os.stat(caminho).st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            pass
    return {"tc_origem_s": timecode_de_inicio(caminho), "gravado_em": gravado}


def com_metadados(trechos: list) -> None:
    """Põe tc_origem_s e gravado_em em cada trecho (uma leitura por clipe)."""
    meta = {c: metadados_clipe(c) for c in sorted({t["caminho"] for t in trechos})}
    for t in trechos:
        t.update(meta[t["caminho"]])



def escolher_midia(caminho: str, modo: str):
    """Arquivo que o export referencia: (caminho escolhido, faltou_proxy).

    original: sempre o original. proxy: o proxy quando existe. auto: proxy só para o que o ffmpeg não decodifica.
    """
    # Pasta = sequência CinemaDNG: o ffmpeg também não lê, então vai para o proxy como BRAW e R3D.
    nao_le = Path(caminho).suffix.lower() in NAO_DECODIFICA or Path(caminho).is_dir()
    if modo == "original" or (modo == "auto" and not nao_le):
        return caminho, False
    proxy = achar_proxy(caminho)
    return (proxy, False) if proxy else (caminho, True)


def trocar_midia(trechos: list, modo: str):
    """Cópia dos trechos apontando para a mídia escolhida, e os nomes dos clipes que ficaram sem proxy."""
    novos, faltam = [], set()
    for t in trechos:
        caminho, faltou = escolher_midia(t["caminho"], modo)
        if faltou:
            faltam.add(Path(t["caminho"]).name)
        novos.append(dict(t, caminho=caminho))
    return novos, sorted(faltam)


def escrever_texto(destino: Path, texto: str) -> None:
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, destino)


def quadros_do_trecho(t: dict, fps: float):
    inicio = int(round(t["inicio_s"] * fps))
    return inicio, max(1, int(round(t["fim_s"] * fps)) - inicio)


def _url(caminho: str) -> str:
    return "file://" + quote(str(Path(caminho)))


def cor_da_nota(nota: float) -> str:
    return "Green" if nota >= 0.8 else "Yellow" if nota >= 0.6 else "Blue"


def cores_dos_trechos(trechos: list, modo: str = "exportacao") -> list:
    """Cor de cada trecho (Green/Yellow/Blue), na ordem de `trechos`.

    "fixa": faixas de nota (0,8 e 0,6). "exportacao": terços da própria saída, como o Cutdown; nota igual fica com
    a mesma cor (a de cima), e um trecho só é verde.
    """
    if modo not in ("exportacao", "fixa"):
        raise ValueError(f"cor_marcador '{modo}' inválido (use exportacao ou fixa)")
    if modo == "fixa" or not trechos:
        return [cor_da_nota(t["nota"]) for t in trechos]
    notas = sorted((t["nota"] for t in trechos), reverse=True)
    n = len(notas)
    verde, amarelo = notas[math.ceil(n / 3) - 1], notas[math.ceil(2 * n / 3) - 1]
    return ["Green" if t["nota"] >= verde else "Yellow" if t["nota"] >= amarelo else "Blue" for t in trechos]


def colorir(trechos: list, modo: str) -> list:
    """Cópias dos trechos com a cor (`"cor"`) que marcadores e exports usam."""
    return [dict(t, cor=c) for t, c in zip(trechos, cores_dos_trechos(trechos, modo))]


def _tempo_otio(valor: int, fps: float) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": fps, "value": valor}


def _intervalo_otio(inicio: int, duracao: int, fps: float) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _tempo_otio(inicio, fps),
            "duration": _tempo_otio(duracao, fps)}


def para_otio(trechos: list, info: dict, nome: str) -> dict:
    """Timeline OTIO (dicionário pronto para json.dump) com os trechos na ordem recebida."""
    clipes = []
    for t in trechos:
        i = info[t["caminho"]]
        fps = i["fps"]
        inicio, duracao = quadros_do_trecho(t, fps)
        marcador = t.get("marcador", {"nome": t["id"], "nota": t.get("motivo", "")})
        clipes.append({
            "OTIO_SCHEMA": "Clip.1", "name": t["id"], "enabled": True, "effects": [],
            "source_range": _intervalo_otio(i["tc_inicio"] + inicio, duracao, fps),
            # Caminho puro, como o OTIO que o próprio DaVinci exporta: com file:// e %20 o Resolve recusa a importação.
            "media_reference": {"OTIO_SCHEMA": "ExternalReference.1", "name": Path(t["caminho"]).name,
                                "target_url": str(Path(t["caminho"])), "metadata": {},
                                "available_range": _intervalo_otio(i["tc_inicio"], i["duracao_quadros"], fps)},
            "markers": [{"OTIO_SCHEMA": "Marker.2", "name": marcador["nome"], "comment": marcador["nota"],
                         "color": _CORES_OTIO[t.get("cor") or cor_da_nota(t["nota"])],
                         "metadata": {"Resolve_OTIO": {"Note": marcador["nota"], "Keywords": []}},
                         "marked_range": _intervalo_otio(i["tc_inicio"] + inicio, duracao, fps)}],
            "metadata": {"motor-de-nota": {"nota": t["nota"], "camera": t.get("camera", {}).get("tipo"),
                                            "flags": t.get("flags", [])}},
        })
    def trilha(nome: str, tipo: str, filhos: list) -> dict:
        return {"OTIO_SCHEMA": "Track.1", "name": nome, "kind": tipo, "children": filhos, "source_range": None,
                "effects": [], "markers": [], "metadata": {}}

    # O áudio repete os mesmos trechos, sem marcadores (eles já estão no vídeo).
    audio = [dict(c, markers=[]) for c in clipes]
    fps_tl = info[trechos[0]["caminho"]]["fps"] if trechos else 24.0
    return {"OTIO_SCHEMA": "Timeline.1", "name": nome, "metadata": {},
            "global_start_time": _tempo_otio(round(fps_tl) * 3600, fps_tl),
            "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks",
                       "children": [trilha("Video 1", "Video", clipes), trilha("Audio 1", "Audio", audio)],
                       "source_range": None,
                       "effects": [], "markers": [], "metadata": {}}}


def _r(quadros: int, fps: Fraction) -> str:
    """Quadros em tempo racional do FCPXML ('48048/24000s'), sem simplificar o denominador do fps."""
    if quadros == 0:
        return "0s"
    passo = 1 / fps
    return f"{quadros * passo.numerator}/{passo.denominator}s"


def _tc_no_fcp(caminho: str, tc: int) -> int:
    """Timecode de início que o Final Cut enxerga no arquivo. Conferido no Final Cut: num MOV ele lê o timecode
    (asset com start = timecode entra), num MP4 (os da Sony) não lê e trata o arquivo como começando em 0 — com o
    timecode no start, ele recusa o clipe como "edição inválida sem mídia"."""
    return 0 if Path(caminho).suffix.lower() in (".mp4", ".m4v") else tc


def para_fcpxml(trechos: list, info: dict, nome: str) -> str:
    """FCPXML 1.14 com os trechos na ordem recebida, um asset por arquivo e um formato por fps+resolução."""
    formatos, assets = {}, {}
    for t in trechos:
        i = info[t["caminho"]]
        chave_fmt = (fps_racional(i["fps"]), i["largura"], i["altura"])
        formatos.setdefault(chave_fmt, f"r{len(formatos) + 1}")
        assets.setdefault(t["caminho"], f"a{len(assets) + 1}")

    linhas = ['<?xml version="1.0" encoding="UTF-8"?>', "<!DOCTYPE fcpxml>", '<fcpxml version="1.14">',
              "  <resources>"]
    for (fps, w, h), ident in formatos.items():
        # Sem colorSpace (e sem o áudio na sequência) o Final Cut avisa "valor inesperado" no format da sequência.
        linhas.append(f'    <format id="{ident}" frameDuration="{_r(1, fps)}" width="{w}" height="{h}" '
                      f'colorSpace="1-1-1 (Rec. 709)"/>')
    for caminho, ident in assets.items():
        i = info[caminho]
        fps = fps_racional(i["fps"])
        fmt = formatos[(fps, i["largura"], i["altura"])]
        linhas.append(f'    <asset id="{ident}" name={quoteattr(Path(caminho).name)} '
                      f'start="{_r(_tc_no_fcp(caminho, i["tc_inicio"]), fps)}" '
                      f'duration="{_r(i["duracao_quadros"], fps)}" hasVideo="1" hasAudio="1" format="{fmt}">')
        linhas.append(f'      <media-rep kind="original-media" src={quoteattr(_url(caminho))}/>')
        linhas.append("    </asset>")
    linhas.append("  </resources>")

    primeiro = info[trechos[0]["caminho"]] if trechos else {"fps": 24.0, "largura": 1920, "altura": 1080}
    fps_seq = fps_racional(primeiro["fps"])
    fmt_seq = formatos.get((fps_seq, primeiro["largura"], primeiro["altura"]), "r1")
    corpo, deslocamento = [], Fraction(0)
    for t in trechos:
        i = info[t["caminho"]]
        fps = fps_racional(i["fps"])
        inicio, duracao = quadros_do_trecho(t, i["fps"])
        marcador = t.get("marcador", {"nome": t["id"], "nota": t.get("motivo", "")})
        fmt = formatos[(fps, i["largura"], i["altura"])]
        tc = _tc_no_fcp(t["caminho"], i["tc_inicio"])
        corpo.append(f'        <asset-clip ref="{assets[t["caminho"]]}" name={quoteattr(t["id"])} '
                     f'offset="{_r(round(deslocamento * fps_seq), fps_seq)}" '
                     f'start="{_r(tc + inicio, fps)}" duration="{_r(duracao, fps)}" format="{fmt}">')
        corpo.append(f'          <marker start="{_r(tc + inicio, fps)}" duration="{_r(1, fps)}" '
                     f'value={quoteattr(marcador["nome"])} note={quoteattr(marcador["nota"])}/>')
        corpo.append("        </asset-clip>")
        deslocamento += Fraction(duracao) / fps
    total = round(deslocamento * fps_seq)
    linhas += [f"  <library>", f"    <event name={quoteattr(nome)}>", f"      <project name={quoteattr(nome)}>",
               f'        <sequence format="{fmt_seq}" duration="{_r(total, fps_seq)}" '
               f'tcStart="{_r(round(fps_seq) * 3600, fps_seq)}" tcFormat="NDF" audioLayout="stereo" audioRate="48k">',
               "      <spine>"]
    linhas += corpo
    linhas += ["      </spine>", "        </sequence>", "      </project>", "    </event>", "  </library>",
               "</fcpxml>", ""]
    return "\n".join(linhas)

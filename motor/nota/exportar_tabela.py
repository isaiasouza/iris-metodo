"""Export dos selects em planilha (CSV com as colunas do relatório do Cutdown, mais as nossas) e em texto.

Os tempos de origem somam o timecode do arquivo; a coluna de timeline começa em 00:00:00:00, como no Cutdown.
Original e proxy aparecem lado a lado, então estes formatos ignoram --midia.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

from exportar import quadros_do_trecho, quadros_em_timecode
from proxy import achar_proxy

COLUNAS = ("index", "clip_name", "source_path", "proxy_path", "src_tc_in", "src_tc_out", "tl_tc_in", "tl_tc_out",
           "duration", "mean_score", "peak_score", "focus", "exposure", "motion",
           "stability", "camera", "confidence", "flags", "marker_name", "marker_note")


def _n(x: Optional[float]) -> str:
    return "" if x is None else f"{x:.4f}"


def _br(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def linhas_tabela(trechos: list, info: dict) -> list:
    """Uma linha (dicionário com as COLUNAS) por trecho, na ordem recebida."""
    fps_tl = info[trechos[0]["caminho"]]["fps"] if trechos else 24.0
    pos, linhas = 0, []
    for n, t in enumerate(trechos, 1):
        i = info[t["caminho"]]
        inicio, dur = quadros_do_trecho(t, i["fps"])
        dur_tl = max(1, round(dur * fps_tl / i["fps"]))
        m = t.get("metricas", {})
        camera = t.get("camera", {})
        marcador = t.get("marcador", {"nome": t["id"], "nota": t.get("motivo", "")})
        linhas.append({
            "index": n, "clip_name": Path(t["caminho"]).name, "source_path": t["caminho"],
            "proxy_path": achar_proxy(t["caminho"]) or "",
            "src_tc_in": quadros_em_timecode(i["tc_inicio"] + inicio, i["fps"]),
            "src_tc_out": quadros_em_timecode(i["tc_inicio"] + inicio + dur, i["fps"]),
            "tl_tc_in": quadros_em_timecode(pos, fps_tl), "tl_tc_out": quadros_em_timecode(pos + dur_tl, fps_tl),
            "duration": quadros_em_timecode(dur_tl, fps_tl),
            "mean_score": _n(t["nota"]), "peak_score": _n(t.get("pico")),
            "focus": _n(m.get("foco")), "exposure": _n(m.get("exposicao")), "motion": _n(m.get("movimento")),
            "stability": _n(m.get("estabilidade")), "camera": camera.get("tipo", ""),
            "confidence": _n(camera.get("confianca")), "flags": ";".join(t.get("flags", [])),
            "marker_name": marcador["nome"], "marker_note": marcador["nota"],
        })
        pos += dur_tl
    return linhas


def para_csv(trechos: list, info: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUNAS, lineterminator="\n")
    w.writeheader()
    w.writerows(linhas_tabela(trechos, info))
    return buf.getvalue()


def para_txt(trechos: list, info: dict) -> str:
    saida = []
    for linha, t in zip(linhas_tabela(trechos, info), trechos):
        pico = f"pico {_br(t['pico'])}" if t.get("pico") is not None else "pico —"
        flags = ", ".join(t.get("flags", [])) or "sem flags"
        saida.append(f"{linha['index']:02d}  {linha['clip_name']}  {linha['src_tc_in']}–{linha['src_tc_out']}  "
                     f"({_br(t['fim_s'] - t['inicio_s'], 1)} s)  nota {_br(t['nota'])}  {pico}  "
                     f"{linha['camera']}  {flags}")
    return "\n".join(saida) + "\n"

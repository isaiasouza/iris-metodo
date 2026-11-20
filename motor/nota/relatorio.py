"""Relatório legível dos selects: selects.md, página de revisão selects.html e contact sheets
(início, meio, fim de cada trecho)."""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from segmentos import codigo_caminho, valores_trecho

from perfis_log import FILTRO_LOG, filtro_de_lut, filtro_do_clipe


def filtro_miniatura(p: dict) -> Optional[str]:
    """Filtro fixo das miniaturas de um preset: a LUT própria, a curva genérica se o material é log, ou nada.
    O relatório usa filtro_trecho (perfil por clipe); esta continua para quem pede um filtro único."""
    if p.get("miniatura_lut"):
        return filtro_de_lut(p["miniatura_lut"])
    return FILTRO_LOG if p.get("log") else None


def filtro_trecho(caminho: str, selects: dict) -> Optional[str]:
    """Filtro da miniatura de um trecho: selects antigo (sem miniatura_perfil) usa o filtro gravado; o novo usa a
    LUT própria se houver, senão o perfil do clipe."""
    if "miniatura_perfil" not in selects or selects.get("miniatura_filtro"):
        return selects.get("miniatura_filtro")
    return filtro_do_clipe(caminho, selects["miniatura_perfil"])


def miniatura(caminho: str, t: float, largura: int = 320, filtro: Optional[str] = None) -> Optional[np.ndarray]:
    vf = f"scale={largura}:-2" + (f",{filtro}" if filtro else "")
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(t, 0.0):.3f}", "-i", caminho,
           "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)


def contact_sheet(trecho: dict, pasta: Path, filtro: Optional[str] = None, largura: int = 320) -> Optional[Path]:
    ini, fim = trecho["inicio_s"], trecho["fim_s"]
    tempos = (ini, (ini + fim) / 2.0, max(ini, fim - 0.1))
    imagens = [m for m in (miniatura(trecho["caminho"], t, largura, filtro) for t in tempos) if m is not None]
    if not imagens:
        return None
    altura = min(m.shape[0] for m in imagens)
    destino = pasta / f"{trecho['id']}.jpg"
    cv2.imwrite(str(destino), cv2.hconcat([m[:altura] for m in imagens]))
    return destino


def _tc(segundos: float) -> str:
    m, s = divmod(segundos, 60.0)
    return f"{int(m)}:{s:04.1f}".replace(".", ",")


def _br(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def gerar(selects: dict, saida: Path, top: int = 50) -> Path:
    pasta = saida / "contact"
    pasta.mkdir(parents=True, exist_ok=True)
    trechos = selects["trechos"]
    extras = selects.get("campos_relatorio") or []
    linhas = [
        f"# Selects — preset `{selects['preset']}`",
        "",
        f"{len(trechos)} trechos · gerado em {selects['gerado_em']} · mostrando os {min(top, len(trechos))} melhores",
        "",
        "| # | Trecho | Nota | Duração | Câmera | Motivo | Prévia |" + "".join(f" {c} |" for c in extras),
        "|---|---|---|---|---|---|---|" + "---|" * len(extras),
    ]
    imagens = {}
    for n, t in enumerate(trechos[:top], 1):
        img = contact_sheet(t, pasta, filtro_trecho(t["caminho"], selects))
        imagens[t["id"]] = img
        previa = f"![{t['id']}](contact/{img.name})" if img else "—"
        arquivo = Path(t["caminho"]).name
        linhas.append(
            f"| {n} | {t['id']} (`{arquivo}` {_tc(t['inicio_s'])}–{_tc(t['fim_s'])}) | {_br(t['nota'])} | "
            f"{_br(t['duracao_s'], 1)} s | {t['camera']['tipo']} | {t['motivo']} | {previa} |"
            + "".join(f" {valores_trecho(t)[c]} |" for c in extras)
        )
    if selects.get("avisos"):
        linhas += ["", "## Avisos", ""]
        linhas += [f"- `{Path(a['caminho']).name}`: {', '.join(a['avisos'])}" for a in selects["avisos"]]
    if selects.get("falhas"):
        linhas += ["", "## Falhas", ""]
        linhas += [f"- `{f['caminho']}`: {f['erro']}" for f in selects["falhas"]]
    destino = saida / "selects.md"
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    (saida / "selects.html").write_text(pagina(selects, saida, trechos[:top], imagens), encoding="utf-8")
    return destino


_CORES = {"Green": "#2f9e44", "Yellow": "#e8a317", "Blue": "#3b6fd8"}


def _cor(nota: float) -> str:
    return _CORES["Green"] if nota >= 0.8 else _CORES["Yellow"] if nota >= 0.6 else _CORES["Blue"]


def _curvas(trecho: dict, saida: Path) -> str:
    """Curvas quadro a quadro de foco, brilho e estabilidade do trecho, lidas do arquivo de análise."""
    arq = saida / "nota" / f"{Path(trecho['caminho']).stem}_{codigo_caminho(trecho['caminho'])}.nota.json"
    try:
        q = json.loads(arq.read_text(encoding="utf-8"))["quadros"]
    except (OSError, ValueError, KeyError):
        return ""
    idx = [i for i, t in enumerate(q["t"]) if trecho["inicio_s"] - 1e-6 <= t < trecho["fim_s"]]
    if len(idx) < 2:
        return ""
    ref = max(max(q["nitidez"]), 1e-9)
    series = {
        "foco": [q["nitidez"][i] / ref for i in idx],
        "brilho": [q["brilho"][i] for i in idx],
        "estabilidade": [1.0 - min(q["tremor"][i] / 0.08, 1.0) for i in idx],
    }
    w, h = 300, 60
    partes = []
    for nome, vals in series.items():
        pts = " ".join(f"{k * w / (len(vals) - 1):.1f},{h - 4 - v * (h - 8):.1f}" for k, v in enumerate(vals))
        partes.append(f'<polyline class="curva curva-{nome}" points="{pts}"/>')
    legenda = "".join(f'<span class="leg leg-{n}">{n}</span>' for n in series)
    return (f'<svg class="curvas" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
            f'aria-label="foco, brilho e estabilidade por quadro">{"".join(partes)}</svg><div>{legenda}</div>')


def pagina(selects: dict, saida: Path, trechos: list, imagens: dict) -> str:
    """Página de revisão offline: gráfico nota × duração (cada ponto leva ao trecho) e um cartão por trecho."""
    e = html.escape
    w, h, m = 720, 320, 44
    dmax = max([t["duracao_s"] for t in trechos] + [1.0])
    x = lambda d: m + d / dmax * (w - 2 * m)  # noqa: E731
    # O eixo da nota começa logo abaixo da menor nota mostrada (em décimos), senão os pontos se espremem no topo.
    piso = max(0.0, min([t["nota"] for t in trechos] + [1.0]) - 0.05)
    piso = min(int(piso * 10) / 10, 0.9)
    y = lambda n: h - m - (n - piso) / (1.0 - piso) * (h - 2 * m)  # noqa: E731
    marcas = [round(piso + k / 10, 1) for k in range(int(round((1.0 - piso) * 10)) + 1)]
    if len(marcas) > 6:
        marcas = marcas[::2] if marcas[-1] in marcas[::2] else marcas[::2] + [1.0]
    pontos = "".join(
        f'<a href="#t-{e(t["id"])}"><circle cx="{x(t["duracao_s"]):.1f}" cy="{y(t["nota"]):.1f}" r="5" '
        f'fill="{_cor(t["nota"])}"><title>{e(t["id"])} · nota {_br(t["nota"])} · {_br(t["duracao_s"], 1)} s'
        f'</title></circle></a>' for t in trechos)
    eixos = (f'<line x1="{m}" y1="{h - m}" x2="{w - m}" y2="{h - m}" class="eixo"/>'
             f'<line x1="{m}" y1="{m}" x2="{m}" y2="{h - m}" class="eixo"/>'
             f'<text x="{w / 2}" y="{h - 10}" text-anchor="middle">duração (s), até {_br(dmax, 0)}</text>'
             f'<text x="14" y="{h / 2}" transform="rotate(-90 14 {h / 2})" text-anchor="middle">nota</text>'
             + "".join(f'<text x="{m - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{_br(v, 1)}</text>'
                       f'<line x1="{m}" y1="{y(v):.1f}" x2="{w - m}" y2="{y(v):.1f}" class="grade"/>'
                       for v in marcas))
    cartoes = []
    for n, t in enumerate(trechos, 1):
        img = imagens.get(t["id"])
        foto = f'<img src="contact/{e(img.name)}" alt="{e(t["id"])}" loading="lazy">' if img else ""
        flags = ", ".join(t["flags"]) or "sem flags"
        cartoes.append(
            f'<article id="t-{e(t["id"])}"><header><span class="bola" style="background:{_cor(t["nota"])}"></span>'
            f'<b>{n}. {e(t["id"])}</b> <span class="nota">nota {_br(t["nota"])}</span></header>'
            f'<p>{e(Path(t["caminho"]).name)} · {_tc(t["inicio_s"])}–{_tc(t["fim_s"])} · '
            f'{_br(t["duracao_s"], 1)} s · {e(t["camera"]["tipo"])} · {e(flags)}</p>{foto}'
            f'{_curvas(t, saida)}<p class="motivo">{e(t["motivo"])}</p><a class="topo" href="#grafico">↑ gráfico</a>'
            f'</article>')
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisão de selects</title>
<style>
:root{{--fundo:#fafaf8;--texto:#1c1c1a;--quieto:#6b6b66;--linha:#d9d9d4;--cartao:#fff}}
@media (prefers-color-scheme:dark){{:root{{--fundo:#161615;--texto:#ecece8;--quieto:#a3a39d;--linha:#3a3a37;--cartao:#20201f}}}}
body{{margin:0;padding:24px 16px;background:var(--fundo);color:var(--texto);font:15px/1.45 -apple-system,system-ui,sans-serif}}
main{{max-width:760px;margin:0 auto}} h1{{font-size:22px;margin:0 0 4px}} .sub{{color:var(--quieto);margin:0 0 20px}}
svg.grafico{{width:100%;height:auto;background:var(--cartao);border:1px solid var(--linha);border-radius:8px}}
svg text{{fill:var(--quieto);font-size:12px}} .eixo{{stroke:var(--quieto)}} .grade{{stroke:var(--linha);stroke-dasharray:3 3}}
circle{{stroke:var(--cartao);stroke-width:1.5;cursor:pointer}} circle:hover{{r:8}}
article{{background:var(--cartao);border:1px solid var(--linha);border-radius:8px;padding:14px 16px;margin:16px 0}}
article:target{{outline:2px solid #3b6fd8}} article p{{margin:6px 0;color:var(--quieto)}}
article img{{width:100%;border-radius:6px;margin-top:8px}} .bola{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}}
.nota{{float:right;font-variant-numeric:tabular-nums}} .motivo{{font-size:13px}} .topo{{font-size:13px;color:var(--quieto)}}
svg.curvas{{width:100%;height:60px;margin-top:8px}} .curva{{fill:none;stroke-width:1.5}}
.curva-foco,.leg-foco{{stroke:#3b6fd8;color:#3b6fd8}} .curva-brilho,.leg-brilho{{stroke:#e8a317;color:#e8a317}}
.curva-estabilidade,.leg-estabilidade{{stroke:#2f9e44;color:#2f9e44}} .leg{{font-size:12px;margin-right:12px}}
</style></head><body><main>
<h1>Selects — preset {e(selects["preset"])}</h1>
<p class="sub">{len(selects["trechos"])} trechos · gerado em {e(selects["gerado_em"])} · mostrando {len(trechos)} · clique num ponto para ir ao trecho</p>
<svg id="grafico" class="grafico" viewBox="0 0 {w} {h}" role="img" aria-label="nota por duração de cada trecho">{eixos}{pontos}</svg>
{"".join(cartoes)}
</main></body></html>
"""

"""Reajuste de takes de uma timeline já montada: cada take escorrega dentro do mesmo clipe até a janela de
melhor nota, sem mudar a duração, a posição na timeline nem a ordem dos passos.

Puro: recebe os takes e os arquivos de análise; quem lê e escreve no DaVinci é o davinci.py.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from segmentos import flags_quadros, normalizar_tudo, notas_quadros

# Quanto um take pode andar para cada lado (segundos): o suficiente para fugir de um borrão ou de uma mão
# na frente, sem trocar o passo que a narração está descrevendo.
RAIO_S = 3.0
# Ganho mínimo de nota para trocar a janela; abaixo disso o take fica como estava.
GANHO_MIN = 0.05


def notas_por_amostra(sidecar: dict, p: dict) -> np.ndarray:
    """Nota de cada amostra do clipe (0–1); amostra excluída por flag vira 0."""
    q = sidecar["quadros"]
    norm, _, base = normalizar_tudo(q, p)
    notas = notas_quadros(norm, flags_quadros(q, base, p), p)
    return np.array([0.0 if n is None else n for n in notas])


def nota_janela(notas: np.ndarray, aps: float, fps: float, inicio: int, fim: int) -> float:
    """Média das notas das amostras dentro de [inicio, fim) em quadros do clipe."""
    a = int(np.floor(inicio / fps * aps))
    b = max(a + 1, int(np.ceil(fim / fps * aps)))
    trecho = notas[a:min(b, len(notas))]
    return float(trecho.mean()) if trecho.size else 0.0


def reajustar(takes: list, analises: dict, p: dict, raio_s: float = RAIO_S, ganho_min: float = GANHO_MIN) -> list:
    """`takes`: [{caminho, in, out, fps, ...}] na ordem da timeline. `analises`: {caminho: sidecar}.

    Devolve os takes com `novo_in`, `novo_out`, `nota_antes`, `nota_depois` e `mudou`. Um take de um clipe
    sem análise fica igual. Takes seguidos do mesmo clipe não se sobrepõem nem trocam de ordem.
    """
    saida = []
    cache = {}
    fim_anterior = {}  # caminho -> out do take anterior do mesmo clipe (já reajustado)
    for i, t in enumerate(takes):
        novo = dict(t, novo_in=t["in"], novo_out=t["out"], nota_antes=None, nota_depois=None, mudou=False)
        sc = analises.get(t["caminho"])
        if sc is None or not t.get("fps"):
            saida.append(novo)
            continue
        if t["caminho"] not in cache:
            cache[t["caminho"]] = notas_por_amostra(sc, p)
        notas, aps, fps = cache[t["caminho"]], sc["amostras_por_s"], t["fps"]
        dur = t["out"] - t["in"]
        total = int(round(sc["duracao"] * fps))
        raio = int(round(raio_s * fps))
        proximo = next((u["in"] for u in takes[i + 1:] if u["caminho"] == t["caminho"]), None)
        lo = max(0, t["in"] - raio, fim_anterior.get(t["caminho"], 0))
        hi = min(total - dur, t["in"] + raio, (proximo - dur) if proximo is not None else total)
        antes = nota_janela(notas, aps, fps, t["in"], t["out"])
        melhor, melhor_in = antes, t["in"]
        passo = max(1, int(round(fps / aps)))
        for ini in range(lo, max(lo, hi) + 1, passo):
            n = nota_janela(notas, aps, fps, ini, ini + dur)
            # Empate: fica mais perto do original (menos chance de mudar o passo da receita).
            if n > melhor + 1e-9 or (abs(n - melhor) <= 1e-9 and abs(ini - t["in"]) < abs(melhor_in - t["in"])):
                melhor, melhor_in = n, ini
        if melhor - antes >= ganho_min and lo <= melhor_in <= hi:
            novo.update(novo_in=melhor_in, novo_out=melhor_in + dur, mudou=True)
        novo.update(nota_antes=round(antes, 3),
                    nota_depois=round(nota_janela(notas, aps, fps, novo["novo_in"], novo["novo_out"]), 3))
        fim_anterior[t["caminho"]] = novo["novo_out"]
        saida.append(novo)
    return saida


def resumo(takes: list) -> dict:
    com_nota = [t for t in takes if t["nota_antes"] is not None]
    mudaram = [t for t in com_nota if t["mudou"]]
    media = lambda xs: round(float(np.mean(xs)), 3) if xs else None  # noqa: E731
    return {"takes": len(takes), "analisados": len(com_nota), "mudaram": len(mudaram),
            "nota_antes": media([t["nota_antes"] for t in com_nota]),
            "nota_depois": media([t["nota_depois"] for t in com_nota]),
            "piores_antes": sorted(round(t["nota_antes"], 2) for t in com_nota)[:5]}


def pior_take(takes: list) -> Optional[dict]:
    com_nota = [t for t in takes if t["nota_depois"] is not None]
    return min(com_nota, key=lambda t: t["nota_depois"]) if com_nota else None

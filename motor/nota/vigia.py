"""Pasta monitorada: decide quando um arquivo terminou de chegar (tamanho parado por um tempo)."""
from __future__ import annotations


class Estabilidade:
    """Entrega cada arquivo uma vez, quando o tamanho ficou igual por `estavel_s` segundos.

    Um arquivo que muda de tamanho recomeça a contagem; um que some é esquecido (se voltar, conta de novo).
    """

    def __init__(self, estavel_s: float):
        self.estavel_s = estavel_s
        self._vistos = {}
        self._entregues = set()

    def prontos(self, tamanhos: dict, agora: float) -> list:
        for caminho in list(self._vistos):
            if caminho not in tamanhos:
                del self._vistos[caminho]
                self._entregues.discard(caminho)
        saida = []
        for caminho, tamanho in tamanhos.items():
            visto = self._vistos.get(caminho)
            if visto is None or visto[0] != tamanho:
                self._vistos[caminho] = (tamanho, agora)
                self._entregues.discard(caminho)
                continue
            if caminho not in self._entregues and agora - visto[1] >= self.estavel_s:
                self._entregues.add(caminho)
                saida.append(caminho)
        return sorted(saida)

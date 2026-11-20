"""IRISCUT: o revisao.json, com os trechos da timeline REVISÃO e a decisão de cada um.

Puro: quem fala com o Resolve é o davinci.py. Depois de criado pelo comando `davinci.py revisao`, o arquivo só
é gravado pelo painel (aprovar, rejeitar, voltar a pendente).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from davinci import DADOS_MARCADOR as DADOS_MOTOR, _ORDENS, _quadros

VERSAO = 1
DECISOES = ("pendente", "aprovado", "rejeitado")
COR_MARCADOR = {"aprovado": "Green", "rejeitado": "Red"}
DADOS_MARCADOR = "iriscut"


def ordenar(trechos: list, ordem: str = "gravacao") -> list:
    return sorted(trechos, key=_ORDENS[ordem])


TOLERANCIA_S = 0.05


def mesmo_trecho(a: dict, b: dict) -> bool:
    """Mesmo id, mesmo clipe e mesmo intervalo (±0,05 s). O id sozinho não basta: é número de sequência, e
    selects diferentes (ou o mesmo refeito) usam o mesmo id para pedaços diferentes do clipe."""
    try:
        return (a["id"] == b["id"] and a["caminho"] == b["caminho"]
                and abs(a["inicio_s"] - b["inicio_s"]) <= TOLERANCIA_S and abs(a["fim_s"] - b["fim_s"]) <= TOLERANCIA_S)
    except (KeyError, TypeError):
        return False   # órfão antigo, gravado só com o id: não dá para provar que é o mesmo trecho


def montar(trechos: list, posicoes: list, *, selects: str, projeto: str, timeline: str, fps_timeline: float,
           inicio_timeline: int, sidecars: Optional[dict] = None, miniaturas: Optional[dict] = None,
           anterior: Optional[dict] = None, agora: Optional[datetime] = None) -> dict:
    """`trechos` na ordem da timeline e `posicoes` [(inicio, fim)] dos itens que o Resolve criou para eles.

    Decisões de uma revisão `anterior` continuam valendo para cada trecho que seguir existindo (mesmo id, clipe e
    intervalo: `mesmo_trecho`); os que sumiram ficam em `orfaos` (só os decididos), e voltam se o trecho
    reaparecer numa remontagem futura. Uma revisão `anterior` de outro projeto é ignorada inteira.
    """
    if len(trechos) != len(posicoes):
        raise ValueError(f"{len(trechos)} trechos e {len(posicoes)} itens na timeline: não dá para casar")
    sidecars = sidecars or {}
    miniaturas = miniaturas or {}
    if anterior is not None and anterior.get("projeto") != projeto:
        anterior = None
    # Os trechos da revisão anterior vêm antes dos órfãos: são a decisão mais recente.
    antigas = [dict(x) for x in (anterior or {}).get("trechos", []) + (anterior or {}).get("orfaos", [])]
    lista = []
    for t in trechos:
        achou = next((x for x in antigas if mesmo_trecho(x, t)), None)
        if achou is not None:
            antigas = [x for x in antigas if not mesmo_trecho(x, t)]
        decisao, quando = (achou["decisao"], achou.get("decidido_em")) if achou else ("pendente", None)
        lista.append((t, decisao, quando))
    saida = []
    for (t, decisao, quando), (inicio, fim) in zip(lista, posicoes):
        saida.append({
            "id": t["id"], "caminho": t["caminho"], "inicio_s": t["inicio_s"], "fim_s": t["fim_s"],
            "fps": t["fps"], "nota": t["nota"], "metricas": t.get("metricas", {}),
            "camera": t["camera"]["tipo"], "flags": list(t["flags"]),
            "tl_inicio": int(inicio), "tl_fim": int(fim),
            "sidecar": sidecars.get(t["caminho"]), "miniatura": miniaturas.get(t["id"]),
            "decisao": decisao, "decidido_em": quando,
            "tc_origem_s": t.get("tc_origem_s"), "gravado_em": t.get("gravado_em"),
        })
    orfaos = []
    for x in antigas:
        if x.get("decisao", "pendente") == "pendente":
            continue
        o = {"id": x["id"]}
        for k in ("caminho", "inicio_s", "fim_s"):
            if k in x:
                o[k] = x[k]
        o.update(decisao=x["decisao"], decidido_em=x.get("decidido_em"))
        orfaos.append(o)
    return {"versao": VERSAO, "selects": str(selects), "projeto": projeto, "timeline": timeline,
            "fps_timeline": fps_timeline, "inicio_timeline": int(inicio_timeline),
            "criado_em": (agora or datetime.now()).isoformat(timespec="seconds"),
            "trechos": saida, "orfaos": orfaos}


def aprovados(revisao: dict, ordem: str = "gravacao") -> list:
    return ordenar([t for t in revisao["trechos"] if t["decisao"] == "aprovado"], ordem)


def planejar_marcadores_decisao(revisao: dict, clipes: dict):
    """clipes: {caminho: (fps, {quadro: marcador já existente, como o GetMarkers devolve})}.

    Só trechos aprovados ou rejeitados. No quadro do trecho:
    - nada → marcador novo;
    - marcador do motor (`motor-de-nota`) → trocado pelo de decisão (`apagar`, tipo `novo`);
    - marcador nosso (`iriscut`) com cor, nome, nota ou duração diferentes → atualizado (`apagar`, tipo `atualizado`);
      igual → nada a fazer (conta como já existente);
    - marcador de qualquer outra origem → fica como está (conta como já existente).
    Devolve (planos, caminhos sem clipe no Media Pool, quantos ficaram como estavam).
    """
    planos, sem_clipe, existentes = [], set(), 0
    for t in revisao["trechos"]:
        if t["decisao"] not in COR_MARCADOR:
            continue
        if t["caminho"] not in clipes:
            sem_clipe.add(t["caminho"])
            continue
        fps, marcadores = clipes[t["caminho"]]
        inicio, fim = _quadros(t, fps)
        plano = {"caminho": t["caminho"], "quadro": inicio, "cor": COR_MARCADOR[t["decisao"]], "nome": t["id"],
                 "nota": f"IRISCUT: {t['decisao']} · nota {round(t['nota'] * 100)}", "duracao": fim - inicio,
                 "tipo": "novo", "apagar": False}
        atual = marcadores.get(inicio)
        if atual is not None:
            dono = (atual or {}).get("customData")
            if dono == DADOS_MARCADOR:
                igual = (atual.get("color"), atual.get("name"), atual.get("note"), atual.get("duration")) == \
                    (plano["cor"], plano["nome"], plano["nota"], plano["duracao"])
                if igual:
                    existentes += 1
                    continue
                plano.update(tipo="atualizado", apagar=True)
            elif dono == DADOS_MOTOR:
                plano["apagar"] = True
            else:
                existentes += 1
                continue
        planos.append(plano)
    return planos, sorted(sem_clipe), existentes


def ler(caminho: Path) -> dict:
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def gravar(caminho: Path, dados: dict) -> None:
    """Grava num temporário da mesma pasta e troca de nome: quem lê nunca vê o arquivo pela metade."""
    caminho = Path(caminho)
    fd, tmp = tempfile.mkstemp(prefix=f".{caminho.name}.", suffix=".tmp", dir=str(caminho.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)
        os.replace(tmp, caminho)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

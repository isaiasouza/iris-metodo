"""Analisa um clipe (uma passada de decodificação) e devolve o sidecar com métricas brutas por quadro."""
from __future__ import annotations

import os
from collections import deque

import cv2

from amostragem import ErroLeitura, amostrar, probe
from metricas import (afim, deslocamento, detalhe, diferenca_bruta, diferenca_estrutura, exposicao,
                      movimento_assunto, nitidez, nitidez_regiao, semelhanca_histograma, tremor_serie)

VERSAO_MOTOR = "1.2"
LIMIAR_CORTE = 0.5
# Segundo sinal do corte: estrutura diferente mesmo com brilho/contraste padronizados e câmera compensada.
# Nos sintéticos: mesmo plano ≤ 0.41 (push_in), parede lisa com ruído ~0.35, troca de cena ~1.16.
# Entre fotos reais de mesmo layout (horizonte/céu na mesma altura) a troca fica em 0.45–0.67; 0.7 perdia
# esses cortes, 0.55 pega a maior parte e segue acima do máximo do mesmo plano.
LIMIAR_ESTRUTURA = 0.55
LIMIAR_DUPLICADO = 0.0005
# Abaixo desta resposta a correlação de fase não achou nada (parede lisa, céu): o deslocamento é ruído.
# O achado sugeria 0.1, mas com 0.1 ainda passam saltos de 3–4 px em parede lisa com ruído (tremor acima
# do limite de `tremido`); com 0.2 o tremor fica baixo e os clipes com textura seguem acima de 0.9.
LIMIAR_RESPOSTA = 0.2
# Quadro sem confiança no meio de um movimento (pan rápido com motion blur) herda o deslocamento dos
# quadros confiáveis vizinhos, buscados até esta distância; zerá-lo viraria um dente de serra (falso tremido).
JANELA_PREENCHIMENTO_S = 1.0
# Perfil de computação: métricas que dá para pular quando o preset não precisa delas.
# escala = zoom da câmera por ORB (a parte mais cara); movimento = movimento do assunto.
METRICAS_OPCIONAIS = ("escala", "movimento")

_NUMERICOS = ("t", "nitidez", "nitidez_regiao", "brilho", "estourado", "esmagado", "contraste", "cam_dx", "cam_dy",
              "cam_escala", "confianca_cam", "movimento_assunto", "detalhe", "luma_p01", "luma_p99", "cam_rot")
_CAMERA = ("cam_dx", "cam_dy", "cam_escala", "cam_rot")
# Colunas que, num quadro de corte, mediriam a passagem entre duas cenas: copiam o vizinho.
_COPIA_NO_CORTE = _CAMERA + ("confianca_cam", "movimento_assunto")
# Todas as colunas de `quadros` numa análise atual. Uma análise a que falte alguma é refeita pelo `analisar`
# (VERSAO_MOTOR não muda: o `selecionar` descartaria todas as análises antigas).
COLUNAS_QUADRO = _NUMERICOS + ("tremor", "corte", "duplicado")


def _sem_resposta(sx: float, sy: float, resposta: float):
    return (0.0, 0.0) if resposta < LIMIAR_RESPOSTA else (sx, sy)


def _preencher_um(i: int, sx: list, sy: list, resposta: list, janela: int):
    """Deslocamento do quadro i: o medido se confiável; senão interpolado entre os confiáveis mais próximos
    dos dois lados (até `janela` quadros), copiado se só houver um lado, 0 se não houver nenhum."""
    if resposta[i] >= LIMIAR_RESPOSTA:
        return sx[i], sy[i]
    esq = next((j for j in range(i - 1, max(-1, i - janela - 1), -1) if resposta[j] >= LIMIAR_RESPOSTA), None)
    dir_ = next((j for j in range(i + 1, min(len(resposta), i + janela + 1)) if resposta[j] >= LIMIAR_RESPOSTA),
                None)
    if esq is not None and dir_ is not None:
        f = (i - esq) / (dir_ - esq)
        return sx[esq] + f * (sx[dir_] - sx[esq]), sy[esq] + f * (sy[dir_] - sy[esq])
    if esq is not None or dir_ is not None:
        j = esq if esq is not None else dir_
        return sx[j], sy[j]
    return 0.0, 0.0


def preencher_deslocamento(sx: list, sy: list, resposta: list, janela: int):
    """Aplica _preencher_um à série inteira (resposta < 0 marca um quadro que nunca serve de âncora)."""
    pares = [_preencher_um(i, sx, sy, resposta, janela) for i in range(len(sx))]
    return [p[0] for p in pares], [p[1] for p in pares]


def _e_corte(a, b, sx: float, sy: float) -> bool:
    """Histograma mudou E a estrutura mudou (o degrau de exposição muda só o histograma)."""
    return semelhanca_histograma(a, b) < LIMIAR_CORTE and diferenca_estrutura(a, b, sx, sy) > LIMIAR_ESTRUTURA


def _voltou(a, b) -> bool:
    """O quadro b é o mesmo plano do quadro a (dois quadros atrás): o que houve no meio foi um flash."""
    sx, sy, resposta = deslocamento(a, b)
    return not _e_corte(a, b, *_sem_resposta(sx, sy, resposta))


def _medir(info, amostras_por_s: float, largura: int, hw: bool, pular: frozenset = frozenset()) -> dict:
    col = {c: [] for c in _NUMERICOS}
    col["corte"] = []
    col["duplicado"] = []
    janela = max(1, int(round(JANELA_PREENCHIMENTO_S * amostras_por_s)))
    # Deslocamento bruto por quadro; o primeiro quadro (resposta -1) nunca serve de âncora.
    bruto_x, bruto_y, bruto_r = [], [], []
    # Quadros ainda necessários: o preenchimento olha `janela` quadros à frente, então a parte que depende
    # do deslocamento (câmera, movimento do assunto, corte, flash) é calculada com esse atraso.
    quadros = {}
    pendentes = deque()

    def concluir(i: int) -> None:
        if i == 0:
            sx = sy = 0.0
            mov, corte = 0.0, False
        else:
            sx, sy = _preencher_um(i, bruto_x, bruto_y, bruto_r, janela)
            ant, q = quadros[i - 1], quadros[i]
            mov = 0.0 if "movimento" in pular else movimento_assunto(ant, q, sx, sy)
            corte = _e_corte(ant, q, sx, sy)
        # O conteúdo anda para o lado oposto ao da câmera.
        col["cam_dx"].append(-sx / largura * amostras_por_s)
        col["cam_dy"].append(-sy / largura * amostras_por_s)
        col["movimento_assunto"].append(mov)
        col["corte"].append(corte)
        # Flash de um quadro (i-1 → clarão em i → volta em i+1): os dois "cortes" em volta são falsos.
        if i >= 2 and (col["corte"][i] or col["corte"][i - 1]) and _voltou(quadros[i - 2], quadros[i]):
            col["corte"][i] = col["corte"][i - 1] = False
        quadros.pop(i - 2, None)

    ant = None
    for t, q in amostrar(info, amostras_por_s, largura, hw):
        i = len(col["t"])
        quadros[i] = q
        col["t"].append(t)
        col["nitidez"].append(nitidez(q))
        col["nitidez_regiao"].append(nitidez_regiao(q))
        col["detalhe"].append(detalhe(q))
        for k, v in exposicao(q).items():
            col[k].append(v)
        if ant is None:
            sx = sy = 0.0
            resposta, fator, rot, ok, dif = -1.0, 1.0, 0.0, True, 1.0
        else:
            sx, sy, resposta = deslocamento(ant, q)
            fator, rot, ok = (1.0, 0.0, True) if "escala" in pular else afim(ant, q)
            dif = diferenca_bruta(ant, q)
        bruto_x.append(sx)
        bruto_y.append(sy)
        bruto_r.append(resposta)
        conf = 1.0 if ant is None else resposta
        col["cam_escala"].append((fator - 1.0) * amostras_por_s)
        col["cam_rot"].append(rot * amostras_por_s)
        col["confianca_cam"].append(conf if ok else conf * 0.5)
        col["duplicado"].append(dif < LIMIAR_DUPLICADO)
        pendentes.append(i)
        while pendentes and pendentes[0] + janela <= i:
            concluir(pendentes.popleft())
        ant = q
    while pendentes:
        concluir(pendentes.popleft())

    n = len(col["t"])
    # O primeiro quadro e os quadros de corte não têm movimento de câmera medível: copiam o vizinho.
    for i in range(n):
        if i == 0 or col["corte"][i]:
            viz = i + 1 if i + 1 < n else i - 1
            if 0 <= viz < n and viz != i:
                for c in _COPIA_NO_CORTE if col["corte"][i] else _CAMERA:
                    col[c][i] = col[c][viz]
    tremor = tremor_serie(col["cam_dx"], col["cam_dy"], amostras_por_s)

    saida = {c: [round(float(v), 6) for v in col[c]] for c in _NUMERICOS}
    saida["tremor"] = [round(float(v), 6) for v in tremor]
    saida["corte"] = [bool(v) for v in col["corte"]]
    saida["duplicado"] = [bool(v) for v in col["duplicado"]]
    return saida


def analisar_clipe(caminho: str, amostras_por_s: float = 4.0, largura: int = 320, hw: bool = True,
                   pular=()) -> dict:
    pular = frozenset(pular)
    desconhecidas = pular - set(METRICAS_OPCIONAIS)
    if desconhecidas:
        raise ValueError(f"métrica(s) que não dá para pular: {', '.join(sorted(desconhecidas))} "
                         f"(opcionais: {', '.join(METRICAS_OPCIONAIS)})")
    cv2.setRNGSeed(0)
    caminho = os.path.abspath(caminho)
    info = probe(caminho)
    try:
        quadros = _medir(info, amostras_por_s, largura, hw, pular)
    except ErroLeitura:
        if not hw:
            raise
        cv2.setRNGSeed(0)
        quadros = _medir(info, amostras_por_s, largura, False, pular)
    st = os.stat(caminho)
    # Duração desconhecida no container (ffprobe "N/A"): vale o que foi decodificado.
    duracao = info.duracao or len(quadros["t"]) / amostras_por_s
    return {
        "versao_motor": VERSAO_MOTOR,
        "caminho": caminho,
        "tamanho": st.st_size,
        "mtime": st.st_mtime,
        "fps": info.fps,
        "duracao": duracao,
        "codec": info.codec,
        "amostras_por_s": amostras_por_s,
        "largura": largura,
        "metricas_puladas": sorted(pular),
        "quadros": quadros,
    }

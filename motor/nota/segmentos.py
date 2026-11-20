"""Transforma métricas brutas em notas, flags e trechos. Puro: não decodifica vídeo."""
from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Optional

import numpy as np

import presets

# Como no Cutdown: desfavorecer multiplica a nota do quadro por 0,6 e preferir por 1,2.
_DESFAVORECER_FLAG = 0.6
_PREFERIR_FLAG = 1.2
_PREFERIR_CAMERA = 0.1
_DESFAVORECER_CAMERA = 0.15
_QUEDA_EXPOSICAO = 0.15
# Submétricas bipolares (spec 2026-10-25): métrica de cada uma e colunas da análise que só existem em análises
# novas. Referências: o valor que leva a submétrica ao polo (0 ou 1).
METRICA_DA_PREFERENCIA = {
    "nitidez": "foco", "detalhe": "foco", "estab_foco": "foco",
    "folga_cor": "exposicao", "flicker": "exposicao", "luma": "exposicao", "contraste": "exposicao",
    "camera": "movimento", "assunto": "movimento", "estab_movimento": "movimento",
}
_COLUNAS_DA_PREFERENCIA = {"detalhe": ("detalhe",), "folga_cor": ("luma_p01", "luma_p99")}
_DETALHE_PISO = 0.01
_ESTAB_FOCO_CV = 0.5
_FOLGA_REF = 0.08
_FLICKER_REF = 0.03
_CONTRASTE_REF = 0.5
_CAMERA_REF = 0.1
_ASSUNTO_REF = 0.08
_ACELERACAO_REF = 0.05
# A nota base do foco já é a nitidez e a do movimento (pesos padrão) já é "assunto parado": ligar a preferência
# espelho substitui a base, senão o polo oposto só conseguiria anular a base (decisão de 2026-10-25).
_ESPELHO = {"nitidez": "foco", "assunto": "movimento"}

TIPOS_CAMERA = ("parada", "pan_esq", "pan_dir", "tilt_cima", "tilt_baixo", "push_in", "pull_out", "mao", "rotacao")
FLAGS = ("blur", "blur_movimento", "tremido", "estourado", "esmagado", "pouca_luz", "quadro_duplicado",
         "cor_solida")
ORDENS = ("nota", "nota_asc", "duracao", "duracao_asc", "gravacao", "alfabetica", "data", "timecode")
# Ordens de importação do Cutdown. tc_origem_s e gravado_em vêm do selecionar; trecho sem o campo (selects antigo,
# clipe sem timecode) vai para o fim, por caminho.
ORDENS_ORIGEM = {
    "alfabetica": lambda t: (Path(t["caminho"]).name.lower(), t["caminho"], t["inicio_s"]),
    "data": lambda t: (t.get("gravado_em") is None, t.get("gravado_em") or "", t["caminho"], t["inicio_s"]),
    "timecode": lambda t: (t.get("tc_origem_s") is None, (t.get("tc_origem_s") or 0.0) + t["inicio_s"],
                           t["caminho"], t["inicio_s"]),
}


def codigo_caminho(caminho: str) -> str:
    return hashlib.sha1(os.path.abspath(caminho).encode("utf-8")).hexdigest()[:8]


def _arr(q: dict, campo: str) -> np.ndarray:
    return np.asarray(q[campo], dtype=float)


def _cenas(cortes) -> list:
    n = len(cortes)
    inicios = [0] + [i for i in range(1, n) if cortes[i]]
    fins = [i - 1 for i in inicios[1:]] + [n - 1]
    return list(zip(inicios, fins)) if n else []


def _normalizar_base(q: dict, p: dict) -> dict:
    usa_regiao = p.get("foco_modo") == "regiao" and "nitidez_regiao" in q
    nit = _arr(q, "nitidez_regiao" if usa_regiao else "nitidez")
    foco = np.zeros_like(nit)
    for i0, i1 in _cenas(q["corte"]):
        ref = max(float(np.percentile(nit[i0:i1 + 1], 95)), p["foco_piso_absoluto"])
        foco[i0:i1 + 1] = np.clip(nit[i0:i1 + 1] / ref, 0.0, 1.0)

    sub = p["submetricas"]
    b = _arr(q, "brilho")
    fora = np.maximum(p["brilho_min"] - b, 0.0) + np.maximum(b - p["brilho_max"], 0.0)
    partes_exp = {
        "brilho": np.clip(1.0 - fora / _QUEDA_EXPOSICAO, 0.0, 1.0),
        "estourado": 1.0 - np.clip(_arr(q, "estourado") * 5.0, 0.0, 1.0),
        "esmagado": 1.0 - np.clip(_arr(q, "esmagado") * 3.0, 0.0, 1.0),
    }
    # Produto ponderado: peso 1 em todas = cada parte derruba a nota inteira; peso 0 = parte ignorada.
    exposicao = np.ones_like(b)
    for parte, peso in sub["exposicao"].items():
        if peso > 0:
            exposicao = exposicao * partes_exp[parte] ** peso

    estabilidade = 1.0 - np.clip(_arr(q, "tremor") / p["tremor_max"], 0.0, 1.0)
    m = _arr(q, "movimento_assunto")
    vel = np.hypot(_arr(q, "cam_dx"), _arr(q, "cam_dy"))
    partes_mov = {
        "assunto": np.clip(1.0 - np.abs(m - p["movimento_alvo"]) / p["movimento_tolerancia"], 0.0, 1.0),
        "camera": np.clip(1.0 - np.abs(vel - p["camera_vel_alvo"]) / p["camera_vel_tolerancia"], 0.0, 1.0),
    }
    total = sum(sub["movimento"].values())
    movimento = sum(peso * partes_mov[parte] for parte, peso in sub["movimento"].items()) / total
    return {"foco": foco, "exposicao": exposicao, "estabilidade": estabilidade, "movimento": movimento}


def _janela(q: dict) -> int:
    """Amostras em ~1 s."""
    t = _arr(q, "t")
    passo = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
    if not passo > 0:
        return max(2, 4)
    return max(2, int(round(1.0 / passo)))


def _movel(v: np.ndarray, k: int, fn) -> np.ndarray:
    """`fn` (np.mean, np.median, np.std) numa janela centrada de k amostras, repetindo as pontas."""
    esq = k // 2
    pad = np.pad(v, (esq, k - 1 - esq), mode="edge")
    return fn(np.lib.stride_tricks.sliding_window_view(pad, k), axis=1)


def colunas_faltando(q: dict) -> list:
    return sorted({c for colunas in _COLUNAS_DA_PREFERENCIA.values() for c in colunas if c not in q})


def submetricas_quadros(q: dict, foco: np.ndarray) -> dict:
    """Cada submétrica por quadro, de 0 a 1 (1 = polo positivo). Fica de fora a que depende de coluna ausente."""
    k = _janela(q)
    nit = _arr(q, "nitidez")
    b = _arr(q, "brilho")
    vel = np.hypot(_arr(q, "cam_dx"), _arr(q, "cam_dy"))
    s = {"nitidez": np.asarray(foco, dtype=float)}
    if "detalhe" in q:
        d = _arr(q, "detalhe")
        det = np.zeros_like(d)
        for i0, i1 in _cenas(q["corte"]):
            ref = max(float(np.percentile(d[i0:i1 + 1], 95)), _DETALHE_PISO)
            det[i0:i1 + 1] = d[i0:i1 + 1] / ref
        s["detalhe"] = det
    cenas = _cenas(q["corte"])

    def por_cena(v, fn):
        # janela de ~1 s sem atravessar cortes de cena
        r = np.empty_like(v, dtype=float)
        for i0, i1 in cenas:
            r[i0:i1 + 1] = _movel(v[i0:i1 + 1], k, fn)
        return r

    variacao = por_cena(nit, np.std) / np.maximum(por_cena(nit, np.mean), 1e-9)
    s["estab_foco"] = 1.0 - variacao / _ESTAB_FOCO_CV
    if "luma_p01" in q and "luma_p99" in q:
        s["folga_cor"] = np.minimum(_arr(q, "luma_p01"), 1.0 - _arr(q, "luma_p99")) / _FOLGA_REF
    s["flicker"] = 1.0 - np.abs(b - por_cena(b, np.median)) / _FLICKER_REF
    s["luma"] = b
    s["contraste"] = _arr(q, "contraste") / _CONTRASTE_REF
    s["camera"] = 1.0 - vel / _CAMERA_REF
    s["assunto"] = _arr(q, "movimento_assunto") / _ASSUNTO_REF
    acel = np.abs(np.diff(vel, prepend=vel[:1]))
    for i0, _ in cenas:
        acel[i0] = 0.0   # sem aceleração através de um corte
    s["estab_movimento"] = 1.0 - acel / _ACELERACAO_REF
    return {nome: np.clip(v, 0.0, 1.0) for nome, v in s.items()}


def aplicar_preferencias(base: dict, sub: dict, p: dict) -> dict:
    """Mistura as preferências ligadas na métrica delas: (base + Σ|p|·x) / (1 + Σ|p|).

    Se a preferência espelho da métrica (`_ESPELHO`) está ligada, a base sai: a nota é só Σ|p|·x / Σ|p|.
    """
    saida = dict(base)
    prefs = p.get("preferencias", {})
    for metrica in ("foco", "exposicao", "movimento"):
        espelho = any(prefs.get(nome) and nome in sub for nome, m in _ESPELHO.items() if m == metrica)
        if espelho:
            soma, pesos = np.zeros_like(np.asarray(base[metrica], dtype=float)), 0.0
        else:
            soma, pesos = np.asarray(base[metrica], dtype=float).copy(), 1.0
        for nome, v in prefs.items():
            if not v or METRICA_DA_PREFERENCIA[nome] != metrica or nome not in sub:
                continue
            soma = soma + abs(v) * (sub[nome] if v > 0 else 1.0 - sub[nome])
            pesos += abs(v)
        saida[metrica] = soma / pesos
    return saida


def normalizar_tudo(q: dict, p: dict):
    """(norm, sub, base): `norm` com as preferências (vai para a nota), `base` sem elas (vai para as flags)."""
    base = _normalizar_base(q, p)
    sub = submetricas_quadros(q, base["foco"])
    return aplicar_preferencias(base, sub, p), sub, base


def normalizar_com_submetricas(q: dict, p: dict):
    norm, sub, _ = normalizar_tudo(q, p)
    return norm, sub


def normalizar(q: dict, p: dict) -> dict:
    return normalizar_com_submetricas(q, p)[0]


def flags_quadros(q: dict, norm: dict, p: dict) -> list:
    lim = p["limites"]
    saida = []
    for i in range(len(q["t"])):
        f = []
        if norm["foco"][i] < lim["blur"]:
            rapido = (np.hypot(q["cam_dx"][i], q["cam_dy"][i]) > lim["blur_movimento_camera"]
                      or q["movimento_assunto"][i] > lim["blur_movimento_assunto"])
            f.append("blur_movimento" if rapido else "blur")
        if norm["estabilidade"][i] < lim["tremido"]:
            f.append("tremido")
        if q["estourado"][i] > lim["estourado"]:
            f.append("estourado")
        if q["esmagado"][i] > lim["esmagado"]:
            f.append("esmagado")
        if q["brilho"][i] < lim["pouca_luz"]:
            f.append("pouca_luz")
        if q["duplicado"][i]:
            f.append("quadro_duplicado")
        if q["contraste"][i] < lim["cor_solida"]:
            f.append("cor_solida")
        saida.append(f)
    return saida


def notas_quadros(norm: dict, flags: list, p: dict) -> list:
    pesos = p["pesos"]
    total = sum(pesos.values())
    notas = []
    for i, fl in enumerate(flags):
        comportamentos = [p["flags"].get(f, "ignorar") for f in fl]
        # Como no Cutdown, excluir vence tudo, até forcar.
        if "excluir" in comportamentos:
            notas.append(None)
            continue
        n = sum(pesos[k] * float(norm[k][i]) for k in pesos) / total
        n *= _DESFAVORECER_FLAG ** comportamentos.count("desfavorecer")
        n *= _PREFERIR_FLAG ** comportamentos.count("preferir")
        notas.append(min(max(n, 0.0), 1.0))
    return notas


def forcados_quadros(flags: list, p: dict) -> list:
    """Quadros com alguma flag em `forcar` (e nenhuma em `excluir`): entram mesmo abaixo da nota mínima."""
    saida = []
    for fl in flags:
        comp = [p["flags"].get(f, "ignorar") for f in fl]
        saida.append("forcar" in comp and "excluir" not in comp)
    return saida


def _dividir(i0: int, i1: int, notas: list, dt: float, p: dict) -> list:
    """Quebra [i0, i1] em blocos de até duracao_max_s, cortando no quadro de pior nota.

    Iterativo (uma hora de corrida não estoura a recursão). Empate de nota (corrida uniforme) vai para o
    quadro mais perto do ponto que divide o bloco em partes inteiras de duracao_max_s — num bloco que
    cabe em duas partes, o meio —, então 100 s iguais viram ~5 pedaços de ~20 s, não 37 de 2 s.
    """
    blocos = []
    pilha = [(i0, i1)]
    margem = max(1, int(round(p["duracao_min_s"] / dt)))
    while pilha:
        a, b = pilha.pop()
        if a > b:
            continue
        tamanho = b - a + 1
        if tamanho * dt <= p["duracao_max_s"] + 1e-9:
            blocos.append((a, b))
            continue
        lo, hi = a + margem, b - margem
        if lo > hi:
            meio = (a + b) // 2
        else:
            partes = int(np.ceil(tamanho * dt / p["duracao_max_s"] - 1e-9))
            alvo = a + int(round(tamanho * (partes // 2) / partes))
            meio = min(range(lo, hi + 1),
                       key=lambda k: (notas[k] if notas[k] is not None else -1.0, abs(k - alvo), k))
        pilha.append((meio + 1, b))
        pilha.append((a, meio - 1))
    return blocos


def agrupar(notas: list, cortes: list, dt: float, p: dict, forcados: Optional[list] = None) -> list:
    n = len(notas)
    forcados = forcados or [False] * n
    bom = [forcados[i] or (notas[i] is not None and notas[i] >= p["nota_min"]) for i in range(n)]

    corridas = []
    i = 0
    while i < n:
        if not bom[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and bom[j + 1] and not cortes[j + 1]:
            j += 1
        corridas.append([i, j])
        i = j + 1

    fundidas = []
    for r in corridas:
        if fundidas:
            a = fundidas[-1]
            buraco = (r[0] - a[1] - 1) * dt
            if buraco <= p["buraco_max_s"] + 1e-9 and not any(cortes[a[1] + 1:r[0] + 1]):
                a[1] = r[1]
                continue
        fundidas.append(list(r))

    blocos = []
    for i0, i1 in fundidas:
        blocos.extend(_dividir(i0, i1, notas, dt, p))
    return [(i0, i1) for i0, i1 in blocos if (i1 - i0 + 1) * dt >= p["duracao_min_s"] - 1e-9]


def etiqueta_camera(dx, dy, escala, tremor, cam: dict, rot=None):
    mdx, mdy, mes, mtr = (float(np.mean(v)) for v in (dx, dy, escala, tremor))
    if mtr > cam["tremor_mao"]:
        return "mao", round(min(mtr / (2 * cam["tremor_mao"]), 1.0), 2)
    forcas = {"pan": abs(mdx) / cam["pan_min"], "tilt": abs(mdy) / cam["pan_min"], "zoom": abs(mes) / cam["zoom_min"]}
    if rot is not None:
        # Análise antiga não tem cam_rot: sem rotação, a etiqueta fica como antes.
        # Mediana, não média: uma mão passando na frente (~2 s de giro falso) não vira rotação num tripé.
        forcas["rotacao"] = abs(float(np.median(rot))) / cam.get("rot_min", 2.0)
    eixo = max(forcas, key=lambda k: (forcas[k], k))
    forca = forcas[eixo]
    if forca < 1.0:
        return "parada", round(1.0 - forca, 2)
    tipo = {
        "pan": "pan_dir" if mdx > 0 else "pan_esq",
        "tilt": "tilt_baixo" if mdy > 0 else "tilt_cima",
        "zoom": "push_in" if mes > 0 else "pull_out",
        "rotacao": "rotacao",
    }[eixo]
    return tipo, round(min(forca / 2.0, 1.0), 2)


def direcao_camera(dx, dy, tipo: str) -> Optional[float]:
    """Para onde a câmera anda, em graus (0 = direita, 90 = cima, 180 = esquerda, 270 = baixo)."""
    if tipo not in ("pan_esq", "pan_dir", "tilt_cima", "tilt_baixo"):
        return None
    # cam_dy > 0 = câmera descendo; na convenção do ângulo, cima é positivo.
    # Arredonda antes do módulo: -1e-9° viraria 360,0 depois do round.
    return round(math.degrees(math.atan2(-float(np.mean(dy)), float(np.mean(dx)))), 1) % 360.0 + 0.0


def na_faixa(angulo: float, faixa) -> bool:
    """Ângulo (graus) dentro de [início, fim], pontas incluídas; início maior que o fim (350-10) dá a volta por 0°."""
    a, b = faixa
    # A direção vem de 0 a 359,9: 0° também é 360°, então 350-360 pega o 0.
    for x in ((angulo, 360.0) if angulo == 0 else (angulo,)):
        if (a <= x <= b) if a <= b else (x >= a or x <= b):
            return True
    return False


def ler_faixas(texto: str) -> list:
    """'60-120,350-10' → [[60.0, 120.0], [350.0, 10.0]]. ValueError com a parte que não serve."""
    faixas = []
    for parte in (texto or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", parte)
        if not m:
            raise ValueError(f"--direcao: faixa inválida '{parte}' (use graus, ex.: 60-120 ou 350-10)")
        a, b = float(m.group(1)), float(m.group(2))
        if a > 360 or b > 360:
            raise ValueError(f"--direcao: '{parte}' fora de 0–360°")
        faixas.append([a, b])
    if not faixas:
        raise ValueError("--direcao: nenhuma faixa (ex.: 60-120)")
    return faixas


def _br(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _tempo(s: float) -> str:
    m, seg = divmod(s, 60.0)
    return f"{int(m)}:{seg:04.1f}".replace(".", ",")


def _resumo_submetricas(sub: dict) -> str:
    """As 3 submétricas mais altas e as 2 mais baixas, da maior para a menor: "nitidez 0,91 · … / flicker 0,31"."""
    if not sub:
        return "—"
    ordem = sorted(sub.items(), key=lambda kv: (-kv[1], kv[0]))
    texto = lambda par: f"{par[0]} {_br(par[1])}"  # noqa: E731
    fortes, fracas = ordem[:3], ordem[3:][-2:]
    return " · ".join(map(texto, fortes)) + (" / " + " · ".join(map(texto, fracas)) if fracas else "")


def valores_trecho(t: dict) -> dict:
    """Valores de um trecho para os modelos de campo (presets.CAMPOS_TRECHO), já formatados em português."""
    m = t["metricas"]
    v = {
        "id": t["id"], "clipe": Path(t["caminho"]).name, "nota": _br(t["nota"]),
        "duracao": f"{_br(t['duracao_s'], 1)} s", "camera": t["camera"]["tipo"],
        "confianca": _br(t["camera"]["confianca"]), "flags": ", ".join(t["flags"]) or "sem flags",
        "motivo": t["motivo"], "foco": _br(m["foco"]), "exposicao": _br(m["exposicao"]),
        "estabilidade": _br(m["estabilidade"]), "movimento": _br(m["movimento"]),
        "inicio": _tempo(t["inicio_s"]), "fim": _tempo(t["fim_s"]),
        "direcao": f"{t['direcao']:.0f}°" if t.get("direcao") is not None else "—",
        "pico": _br(t["pico"]) if t.get("pico") is not None else "—",
    }
    sub = t.get("submetricas") or {}
    v.update({f"sub_{nome}": _br(sub[nome]) if nome in sub else "—" for nome in presets.PREFERENCIAS})
    v["submetricas"] = _resumo_submetricas(sub)
    v["estrela"] = "★" if t.get("melhor_do_clipe") else ""
    cheias = min(5, max(1, int(t["nota"] * 5 + 0.5)))
    v["estrelas"] = "★" * cheias + "☆" * (5 - cheias)
    return v


def _motivo(metricas: dict, tipo: str, flags: list) -> str:
    partes = [f"foco {_br(metricas['foco'])}", f"exposição {_br(metricas['exposicao'])}",
              f"estabilidade {_br(metricas['estabilidade'])}", tipo,
              ", ".join(flags) if flags else "sem flags"]
    return " · ".join(partes)


def segundos_por_flag(sidecar: dict, p: dict) -> dict:
    """Segundos do clipe com cada problema (flag), inclusive os que o preset ignora: a contagem do painel de seleção,
    como o número ao lado de cada flag no Cutdown."""
    q = sidecar["quadros"]
    if not len(q["t"]):
        return {}
    dt = 1.0 / sidecar["amostras_por_s"]
    _norm, _sub, base = normalizar_tudo(q, p)
    total = {}
    for fl in flags_quadros(q, base, p):
        for f in fl:
            total[f] = total.get(f, 0.0) + dt
    return total


def trechos_do_clipe(sidecar: dict, p: dict):
    q = sidecar["quadros"]
    n = len(q["t"])
    if sidecar["duracao"] < 1.0 or n == 0:
        return [], ["curto"]
    dt = 1.0 / sidecar["amostras_por_s"]
    fps = sidecar["fps"]
    avisos = []
    if float(np.percentile(_arr(q, "nitidez"), 95)) < p["foco_piso_absoluto"]:
        avisos.append("sem_foco")

    norm, sub, base = normalizar_tudo(q, p)
    faltam = colunas_faltando(q)
    precisam = [n for n, v in p.get("preferencias", {}).items()
                if v and any(c in faltam for c in _COLUNAS_DA_PREFERENCIA.get(n, ()))]
    if precisam:
        avisos.append("sem_colunas:" + ",".join(faltam))
    # Flags pelas métricas base: uma preferência não tira um quadro borrado do limite de blur.
    flags = flags_quadros(q, base, p)
    notas = notas_quadros(norm, flags, p)
    forcados = forcados_quadros(flags, p)
    nome = Path(sidecar["caminho"]).stem
    codigo = codigo_caminho(sidecar["caminho"])[:6]

    trechos = []
    for i0, i1 in agrupar(notas, q["corte"], dt, p, forcados):
        fatia = slice(i0, i1 + 1)
        tipo, confianca = etiqueta_camera(q["cam_dx"][fatia], q["cam_dy"][fatia], q["cam_escala"][fatia],
                                          q["tremor"][fatia], p["camera"],
                                          q["cam_rot"][fatia] if "cam_rot" in q else None)
        comportamento = p["camera_comportamento"].get(tipo)
        if comportamento == "excluir":
            continue
        inicio = float(q["t"][i0])
        fim = min(float(q["t"][i1]) + dt, float(sidecar["duracao"]))
        duracao = fim - inicio
        validas = [x for x in notas[fatia] if x is not None]
        nota = float(np.mean(validas)) * (1.0 + p["bonus_duracao"] * min(duracao / 10.0, 1.0))
        if comportamento == "preferir":
            nota += _PREFERIR_CAMERA
        elif comportamento == "desfavorecer":
            nota -= _DESFAVORECER_CAMERA
        metricas = {k: round(float(np.mean(norm[k][fatia])), 2) for k in norm}
        visiveis = sorted({f for fl in flags[fatia] for f in fl if p["flags"].get(f, "ignorar") != "ignorar"})
        trechos.append({
            "id": f"{nome}-{codigo}_{len(trechos) + 1:02d}",
            "caminho": sidecar["caminho"],
            "inicio_s": round(inicio, 3),
            "fim_s": round(fim, 3),
            "duracao_s": round(duracao, 3),
            "fps": fps,
            "inicio_frame": int(round(inicio * fps)),
            "fim_frame": int(round(fim * fps)),
            "nota": round(min(max(nota, 0.0), 1.0), 3),
            "pico": round(max(validas), 3) if validas else 0.0,
            "metricas": metricas,
            "submetricas": {k: round(float(np.mean(v[fatia])), 2) for k, v in sub.items()},
            "camera": {"tipo": tipo, "confianca": confianca},
            "direcao": direcao_camera(q["cam_dx"][fatia], q["cam_dy"][fatia], tipo),
            "flags": visiveis,
            "motivo": _motivo(metricas, tipo, visiveis),
            "forcado": bool(any(forcados[fatia])),
        })
    # O texto do marcador só sai com todos os trechos do clipe: {estrela} vai no de maior nota (empate: o primeiro).
    melhor = max(trechos, key=lambda t: t["nota"]) if trechos else None
    for t in trechos:
        t["melhor_do_clipe"] = t is melhor
        valores = valores_trecho(t)
        t["marcador"] = {"nome": p["campos"]["marcador_nome"].format_map(valores),
                         "nota": p["campos"]["marcador_nota"].format_map(valores)}
    return trechos, avisos


def _chaves_do_clipe(caminho: str) -> set:
    nome = Path(caminho).name
    return {caminho.lower(), nome.lower(), Path(nome).stem.lower()}


def _ordenar(trechos: list, ordem: str) -> None:
    if ordem in ORDENS_ORIGEM:
        trechos.sort(key=ORDENS_ORIGEM[ordem])
        return
    if ordem == "nota":
        trechos.sort(key=lambda t: (-t["nota"], t["caminho"], t["inicio_s"]))
    elif ordem == "nota_asc":
        trechos.sort(key=lambda t: (t["nota"], t["caminho"], t["inicio_s"]))
    elif ordem == "duracao":
        trechos.sort(key=lambda t: (-t["duracao_s"], -t["nota"], t["caminho"], t["inicio_s"]))
    elif ordem == "duracao_asc":
        trechos.sort(key=lambda t: (t["duracao_s"], -t["nota"], t["caminho"], t["inicio_s"]))
    else:
        trechos.sort(key=lambda t: (t["caminho"], t["inicio_s"]))


def montar_selects(sidecars: list, p: dict, nota_min: Optional[float] = None, cameras: Optional[list] = None,
                   ordem: str = "nota", ajustes: Optional[dict] = None, nota_max: Optional[float] = None,
                   max_por_clipe: Optional[int] = None, direcoes: Optional[list] = None) -> dict:
    """`ajustes`: {clipe: ajuste}, a chave = caminho, nome do arquivo ou nome sem extensão (sem maiúsculas).

    `nota_max` e `max_por_clipe` (padrão: os do preset de cada clipe) limitam a faixa de nota e quantos
    trechos cada clipe dá. `direcoes` (padrão: `direcao_faixas` do preset de cada clipe) são faixas de graus
    [início, fim]: com elas só entra trecho com direção de câmera numa faixa (parada e zoom ficam de fora). Um trecho
    forçado (flag em `forcar`) passa por cima da faixa de nota, dos filtros de câmera e de direção e do máximo por
    clipe, como o force include do Cutdown. `descartados` traz os trechos que esses filtros tiraram, cada um com o
    `motivo` (nota_min, nota_max, camera, direcao ou max_por_clipe), para o gráfico do painel de seleção."""
    if ordem not in ORDENS:
        raise ValueError(f"ordem '{ordem}' inválida (use {', '.join(ORDENS)})")
    ajustes = ajustes or {}
    por_chave = {k.lower(): (k, v) for k, v in ajustes.items()}
    usados = set()
    todos = []
    descartados = []
    avisos = []
    for sc in sorted(sidecars, key=lambda s: s["caminho"]):
        p_clipe = p
        for chave in _chaves_do_clipe(sc["caminho"]):
            if chave in por_chave:
                original, ajuste = por_chave[chave]
                usados.add(original)
                p_clipe = presets.aplicar_ajuste(p, ajuste, f"ajuste de {original}")
                break
        if p_clipe is None:
            continue
        trechos, av = trechos_do_clipe(sc, p_clipe)
        if av:
            avisos.append({"caminho": sc["caminho"], "avisos": av})
        teto = nota_max if nota_max is not None else p_clipe.get("nota_max", 1.0)
        limite = max_por_clipe if max_por_clipe is not None else p_clipe.get("max_por_clipe")
        faixas = direcoes if direcoes is not None else p_clipe.get("direcao_faixas")
        aceitos = []
        for t in trechos:
            motivo = None
            if not t.get("forcado"):
                if nota_min is not None and t["nota"] < nota_min:
                    motivo = "nota_min"
                elif t["nota"] > teto + 1e-9:
                    motivo = "nota_max"
                elif cameras and t["camera"]["tipo"] not in cameras:
                    motivo = "camera"
                elif faixas and (t.get("direcao") is None or not any(na_faixa(t["direcao"], f) for f in faixas)):
                    motivo = "direcao"
            if motivo:
                descartados.append({**t, "motivo": motivo})
            else:
                aceitos.append(t)
        if limite:
            normais = sorted((t for t in aceitos if not t.get("forcado")), key=lambda t: -t["nota"])[:limite]
            descartados.extend({**t, "motivo": "max_por_clipe"} for t in aceitos
                               if not t.get("forcado") and t not in normais)
            aceitos = [t for t in aceitos if t.get("forcado") or t in normais]
        todos.extend(aceitos)
    _ordenar(todos, ordem)
    return {"trechos": todos, "descartados": descartados, "avisos": avisos,
            "ajustes_sem_clipe": sorted(set(ajustes) - usados)}

"""Presets de nota: JSON editável mesclado sobre um padrão."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from perfis_log import PERFIS_PRESET

PASTA = Path(__file__).resolve().parent / "presets"

COMPORTAMENTOS_FLAG = ("excluir", "desfavorecer", "ignorar", "preferir", "forcar")
FOCO_MODOS = ("quadro", "regiao")
COMPORTAMENTOS_CAMERA = ("preferir", "desfavorecer", "excluir")
CORES_MARCADOR = ("exportacao", "fixa")
# Submétricas bipolares do Cutdown, como preferência de -1 a 1 (sinal = polo, tamanho = peso, 0 = desligada).
PREFERENCIAS = ("nitidez", "detalhe", "estab_foco", "folga_cor", "flicker", "luma", "contraste", "camera",
                "assunto", "estab_movimento")
_ANINHADOS = ("pesos", "limites", "camera", "flags", "camera_comportamento", "campos", "preferencias")
# Valores que um modelo de campo pode usar ({id}, {nota}…); espelha segmentos.valores_trecho.
CAMPOS_TRECHO = ("id", "clipe", "nota", "duracao", "camera", "confianca", "flags", "motivo", "foco", "exposicao",
                 "estabilidade", "movimento", "inicio", "fim", "direcao", "pico", "estrela", "estrelas",
                 "submetricas") + tuple(f"sub_{nome}" for nome in PREFERENCIAS)

PADRAO = {
    "pesos": {"foco": 0.30, "exposicao": 0.30, "estabilidade": 0.30, "movimento": 0.10},
    "brilho_min": 0.20,
    "brilho_max": 0.80,
    "log": False,
    "tremor_max": 0.08,
    "movimento_alvo": 0.0,
    "movimento_tolerancia": 0.08,
    "camera_vel_alvo": 0.0,
    "camera_vel_tolerancia": 0.1,
    "foco_piso_absoluto": 40.0,
    # "quadro": nitidez do quadro inteiro; "regiao": da região mais nítida (3×3), como no Cutdown. Precisa de
    # análise feita a partir da coluna nitidez_regiao; sem ela, cai no quadro inteiro.
    "foco_modo": "quadro",
    # Teto da nota do trecho (com nota_min forma a faixa; teto baixo = modo limpeza, pega os piores).
    "nota_max": 1.0,
    # Quantos trechos cada clipe pode dar no máximo (os de maior nota); None = sem limite.
    "max_por_clipe": None,
    # Faixas de direção da câmera em graus, [[início, fim], ...] (0 = direita, 90 = cima); None = sem filtro. Com
    # faixas, só entra trecho de pan/tilt com direção numa delas; 350-10 dá a volta por 0°.
    "direcao_faixas": None,
    # Quadros analisados por segundo no `analisar --preset` (None = o padrão do analisar, 4/s).
    "amostras_por_s": None,
    # LUT .cube própria para as miniaturas (vence o perfil_log).
    "miniatura_lut": None,
    # Perfil de log das miniaturas e prévias: None (nenhum), "auto" (lê metadados e sidecars da câmera; sem nada,
    # curva genérica), um dos perfis_log.PERFIS (slog3, vlog, clog3, logc4, applelog, flog2…), "generico" ou
    # "nenhum". A miniatura_lut, se houver, vence. Não muda a nota.
    "perfil_log": None,
    "nota_min": 0.6,
    "buraco_max_s": 0.5,
    "duracao_min_s": 2.0,
    "duracao_max_s": 20.0,
    "bonus_duracao": 0.1,
    "limites": {"blur": 0.35, "tremido": 0.3, "estourado": 0.10, "esmagado": 0.15, "pouca_luz": 0.12,
                "blur_movimento_camera": 0.15, "blur_movimento_assunto": 0.08, "cor_solida": 0.02},
    "camera": {"pan_min": 0.02, "zoom_min": 0.01, "tremor_mao": 0.05, "rot_min": 2.0},
    "flags": {
        "blur": "excluir",
        "blur_movimento": "desfavorecer",
        "tremido": "excluir",
        "estourado": "excluir",
        "esmagado": "desfavorecer",
        "pouca_luz": "desfavorecer",
        "quadro_duplicado": "ignorar",
        "cor_solida": "excluir",
    },
    "camera_comportamento": {},
    # Cor dos marcadores e clipes: "exportacao" divide a própria saída em terços (verde, amarelo, azul), como o
    # Cutdown; "fixa" usa as faixas de nota (verde ≥ 0,8, amarelo ≥ 0,6).
    "cor_marcador": "exportacao",
    # Textos dos marcadores no DaVinci e colunas extras do relatório; {campo} = um valor do trecho
    # (lista em segmentos.CAMPOS_TRECHO).
    "campos": {"marcador_nome": "{id}", "marcador_nota": "{motivo}", "relatorio": []},
    # Pesos dentro de cada métrica. Padrão = comportamento de antes da P1; peso 0 desliga a parte.
    "submetricas": {
        "exposicao": {"brilho": 1.0, "estourado": 1.0, "esmagado": 1.0},
        "movimento": {"assunto": 1.0, "camera": 0.0},
    },
    # Polo positivo: nítida, detalhada, foco travado, folga para a cor, sem flicker, clara, contrastada,
    # câmera parada, assunto ativo, movimento suave. Negativo = o outro polo.
    "preferencias": {nome: 0.0 for nome in PREFERENCIAS},
}


def meus() -> list:
    """Presets salvos pelo editor (painel de seleção do IRISCUT), em presets/meus/."""
    return sorted(p.stem for p in (PASTA / "meus").glob("*.json") if not p.name.startswith("."))


def listar() -> list:
    return sorted({p.stem for p in PASTA.glob("*.json") if not p.name.startswith(".")} | set(meus()))


def _arquivo(nome_ou_caminho: str) -> Path:
    if nome_ou_caminho.endswith(".json") or "/" in nome_ou_caminho:
        caminho = Path(nome_ou_caminho)
    else:
        caminho = PASTA / f"{nome_ou_caminho}.json"
        if not caminho.is_file():   # um pronto vence um meu com o mesmo nome
            caminho = PASTA / "meus" / f"{nome_ou_caminho}.json"
    if not caminho.is_file():
        raise ValueError(f"preset não encontrado: {nome_ou_caminho} (disponíveis: {', '.join(listar())})")
    return caminho


def _validar(p: dict) -> None:
    if sum(p["pesos"].values()) <= 0:
        raise ValueError("a soma dos pesos precisa ser maior que zero")
    for flag, comp in p["flags"].items():
        if comp not in COMPORTAMENTOS_FLAG:
            raise ValueError(f"flag {flag}: comportamento '{comp}' inválido (use {', '.join(COMPORTAMENTOS_FLAG)})")
    for tipo, comp in p["camera_comportamento"].items():
        if comp not in COMPORTAMENTOS_CAMERA:
            raise ValueError(f"câmera {tipo}: comportamento '{comp}' inválido (use {', '.join(COMPORTAMENTOS_CAMERA)})")
    if p["foco_modo"] not in FOCO_MODOS:
        raise ValueError(f"foco_modo '{p['foco_modo']}' inválido (use {', '.join(FOCO_MODOS)})")
    if p["cor_marcador"] not in CORES_MARCADOR:
        raise ValueError(f"cor_marcador '{p['cor_marcador']}' inválido (use {', '.join(CORES_MARCADOR)})")
    if p["perfil_log"] not in PERFIS_PRESET:
        validos = ", ".join(v for v in PERFIS_PRESET if v)
        raise ValueError(f"perfil_log '{p['perfil_log']}' inválido (use {validos} ou null)")
    faixas = p["direcao_faixas"]
    if faixas is not None and (not isinstance(faixas, list) or not faixas or not all(
            isinstance(f, list) and len(f) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                         and 0 <= x <= 360 for x in f) for f in faixas)):
        raise ValueError("direcao_faixas precisa ser null ou uma lista não vazia de [início, fim] em graus de 0 a 360")
    if p["max_por_clipe"] is not None and (not isinstance(p["max_por_clipe"], int) or p["max_por_clipe"] < 1):
        raise ValueError("max_por_clipe precisa ser um inteiro ≥ 1 (ou null para sem limite)")
    if p["amostras_por_s"] is not None and (not isinstance(p["amostras_por_s"], (int, float))
                                            or p["amostras_por_s"] <= 0):
        raise ValueError("amostras_por_s precisa ser um número maior que zero")
    for chave in ("pan_min", "zoom_min", "rot_min"):
        v = p["camera"].get(chave)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
            raise ValueError(f"camera.{chave} precisa ser um número maior que zero")
    if p["brilho_min"] >= p["brilho_max"]:
        raise ValueError("brilho_min precisa ser menor que brilho_max")
    exemplo = {c: c for c in CAMPOS_TRECHO}
    for chave in ("marcador_nome", "marcador_nota"):
        try:
            str(p["campos"][chave]).format_map(exemplo)
        except (KeyError, ValueError, IndexError) as e:
            raise ValueError(f"campos.{chave}: modelo inválido ({e}); campos: {', '.join(CAMPOS_TRECHO)}") from e
    extras = [c for c in p["campos"]["relatorio"] if c not in CAMPOS_TRECHO]
    if extras:
        raise ValueError(f"campos.relatorio: desconhecido(s) {', '.join(extras)} (campos: {', '.join(CAMPOS_TRECHO)})")
    for metrica, partes in p["submetricas"].items():
        validas = PADRAO["submetricas"].get(metrica)
        if validas is None or set(partes) - set(validas):
            raise ValueError(f"submetricas.{metrica}: partes inválidas (válidas: {', '.join(validas or [])})")
        if any(not isinstance(v, (int, float)) or v < 0 for v in partes.values()):
            raise ValueError(f"submetricas.{metrica}: pesos precisam ser números ≥ 0")
        if sum(partes.values()) <= 0:
            raise ValueError(f"submetricas.{metrica}: a soma dos pesos precisa ser maior que zero")
    for nome, v in p["preferencias"].items():
        if nome not in PREFERENCIAS:
            raise ValueError(f"preferencias.{nome}: desconhecida (válidas: {', '.join(PREFERENCIAS)})")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not -1.0 <= v <= 1.0:
            raise ValueError(f"preferencias.{nome}: precisa ser um número de -1 a 1")


def _mesclar(p: dict, dados: dict, origem: str) -> dict:
    """Aplica `dados` sobre uma cópia de `p`, um nível em dicionários (dois em `submetricas`)."""
    if not isinstance(dados, dict):
        raise ValueError(f"{origem}: o JSON precisa ser um objeto {{...}}")
    p = copy.deepcopy(p)
    for chave, valor in dados.items():
        if chave not in PADRAO:
            raise ValueError(f"{origem}: chave desconhecida '{chave}' (válidas: {', '.join(sorted(PADRAO))})")
        if chave in _ANINHADOS or chave == "submetricas":
            if not isinstance(valor, dict):
                raise ValueError(f"{origem}: '{chave}' precisa ser um objeto {{...}}")
            if chave == "submetricas":
                for metrica, partes in valor.items():
                    if not isinstance(partes, dict):
                        raise ValueError(f"{origem}: 'submetricas.{metrica}' precisa ser um objeto {{...}}")
                    p[chave].setdefault(metrica, {}).update(partes)
            else:
                p[chave].update(valor)
        else:
            p[chave] = valor
    return p


def _ler(nome_ou_caminho: str) -> tuple:
    arquivo = _arquivo(nome_ou_caminho)
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"preset {arquivo.name} não é JSON válido: {e}") from e
    return arquivo, dados, _mesclar(PADRAO, dados, f"preset {arquivo.name}")


def bruto(nome_ou_caminho: str) -> dict:
    """O preset mesclado com o padrão, antes dos ajustes de carga (log alarga o brilho) e sem `nome`: o painel de
    seleção mostra estes valores e grava a versão editada como arquivo, que `carregar` lê igual ao original."""
    _arquivo_, dados, p = _ler(nome_ou_caminho)
    if p["log"] and "perfil_log" not in dados:
        p["perfil_log"] = "auto"
    _validar(p)
    return p


def carregar(nome_ou_caminho: str) -> dict:
    arquivo, dados, p = _ler(nome_ou_caminho)
    if p["log"]:
        p["brilho_min"] = max(0.0, p["brilho_min"] - 0.1)
        p["brilho_max"] = min(1.0, p["brilho_max"] + 0.1)
        if "perfil_log" not in dados:   # presets antigos com só "log": true passam a ler o perfil do clipe
            p["perfil_log"] = "auto"
    _validar(p)
    p["nome"] = arquivo.stem
    return p


def aplicar_ajuste(p: dict, ajuste: dict, origem: str = "ajuste") -> "dict | None":
    """Preset de um clipe a partir do ajuste dele: None = clipe excluído.

    `preset` troca a base; as outras chaves sobrescrevem o preset como num arquivo de preset.
    """
    if not isinstance(ajuste, dict):
        raise ValueError(f"{origem}: precisa ser um objeto {{...}}")
    if ajuste.get("excluir"):
        return None
    resto = {k: v for k, v in ajuste.items() if k not in ("excluir", "preset")}
    base = carregar(ajuste["preset"]) if "preset" in ajuste else p
    novo = _mesclar(base, resto, origem)
    _validar(novo)
    novo["nome"] = base.get("nome", "")
    return novo

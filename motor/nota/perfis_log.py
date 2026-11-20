"""Perfis de log por fabricante para miniaturas e prévias: Sony (S-Log2/3), Panasonic (V-Log), Canon (C-Log/2/3), ARRI
(LogC3/LogC4), Apple Log, Blackmagic (Gen 5), DaVinci Intermediate, DJI D-Log, Fujifilm (F-Log/2), GoPro Protune,
Leica L-Log, Nikon N-Log e RED Log3G10.

Converte log para Rec.709 a partir das fórmulas e das primárias publicadas pelos fabricantes, numa LUT 3D (.cube)
gerada uma vez em analise/.luts/ e aplicada pelo FFmpeg (lut3d). Só muda o que se vê: a nota não usa nada daqui.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import numpy as np

PERFIS = ("slog3", "slog2", "vlog", "clog3", "clog2", "clog", "logc3", "logc4", "applelog", "bmdgen5", "davinci",
          "dlog", "flog", "flog2", "protune", "llog", "nlog", "log3g10", "generico", "nenhum")
PERFIS_PRESET = (None, "auto") + PERFIS
PASTA_LUTS = Path(__file__).resolve().parents[2] / "analise" / ".luts"
VERSAO_LUT = 1
TAMANHO_LUT = 33
CINZA_TELA = 0.41
# Curva genérica de log → visualização (sobe o contraste e a saturação de material log sem perfil conhecido).
FILTRO_LOG = "curves=all='0/0 0.18/0.08 0.5/0.55 0.82/0.94 1/1',eq=saturation=1.4"

D65 = (0.3127, 0.3290)
# Branco publicado pela Blackmagic (D65 com mais casas); os outros gamuts usam D65.
BRANCO_DO_GAMUT = {"bmdwg": (0.312717, 0.3290312)}
PRIMARIAS = {
    "rec709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "sgamut3cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087)),
    "vgamut": ((0.730, 0.280), (0.165, 0.840), (0.100, -0.030)),
    "cinemagamut": ((0.740, 0.270), (0.170, 1.140), (0.080, -0.100)),
    "sgamut": ((0.730, 0.280), (0.140, 0.855), (0.100, -0.050)),
    "awg3": ((0.684, 0.313), (0.221, 0.848), (0.0861, -0.102)),
    "awg4": ((0.7347, 0.2653), (0.1424, 0.8576), (0.0991, -0.0308)),
    "rec2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
    "bmdwg": ((0.7177215, 0.3171181), (0.228041, 0.861569), (0.1005841, -0.0820452)),
    "dwg": ((0.8000, 0.3130), (0.1682, 0.9877), (0.0790, -0.1155)),
    "dgamut": ((0.71, 0.31), (0.21, 0.88), (0.09, -0.08)),
    "protune": ((0.69848, 0.193026), (0.329555, 1.024597), (0.108443, -0.034679)),
    "redwg": ((0.780308, 0.304253), (0.121595, 1.493994), (0.095612, -0.084589)),
}
GAMUT_DO_PERFIL = {"slog3": "sgamut3cine", "vlog": "vgamut", "clog3": "cinemagamut", "slog2": "sgamut",
                   "logc3": "awg3", "logc4": "awg4", "applelog": "rec2020", "bmdgen5": "bmdwg", "davinci": "dwg",
                   "clog": "cinemagamut", "clog2": "cinemagamut", "dlog": "dgamut", "flog": "rec2020",
                   "flog2": "rec2020", "protune": "protune", "llog": "rec2020", "nlog": "rec2020",
                   "log3g10": "redwg"}


# ---------- curvas log → luz de cena (0,18 = cinza médio) ----------

def slog3_para_linear(x):
    """Sony S-Log3; x = código de 10 bits / 1023."""
    c = np.asarray(x, dtype=float) * 1023
    return np.where(c >= 171.2102946929, 10 ** ((c - 420) / 261.5) * 0.19 - 0.01,
                    (c - 95) * 0.01125 / (171.2102946929 - 95))


def vlog_para_linear(x):
    """Panasonic V-Log; x = código de 10 bits / 1023."""
    x = np.asarray(x, dtype=float)
    return np.where(x < 0.181, (x - 0.125) / 5.6, 10 ** ((x - 0.598206) / 0.241514) - 0.00873)


def clog3_para_linear(ire):
    """Canon C-Log3; ire = sinal 0–1 da faixa legal. A fórmula da Canon devolve a luz de cena / 0,9."""
    x = np.asarray(ire, dtype=float)
    entrada = np.where(x < 0.097465473, -(10 ** ((0.12783901 - x) / 0.36726845) - 1) / 14.98325,
                       np.where(x <= 0.15277891, (x - 0.12512219) / 1.9754798,
                                (10 ** ((x - 0.12240537) / 0.36726845) - 1) / 14.98325))
    return 0.9 * entrada


def slog2_para_linear(x):
    """Sony S-Log2 (Technical Summary for S-Gamut/S-Log2); x = código de 10 bits / 1023."""
    x = np.asarray(x, dtype=float)
    c = (x * 1023 - 64) / 876
    slog = np.where(x >= 0.088251291513445768, 10 ** ((c - 0.616596 - 0.03) / 0.432699) - 0.037584,
                    (c - 0.030001222851889303) / 5.0)
    return 0.9 * slog * 219 / 155


def logc3_para_linear(x):
    """ARRI LogC3 (Alexa Log C Curve, EI 800, SUP 3.x, fator de exposição linear); x = código normalizado."""
    t = np.asarray(x, dtype=float)
    cut, a, b, c, d, e, f = 0.010591, 5.555556, 0.052272, 0.24719, 0.385537, 5.367655, 0.092809
    return np.where(t > e * cut + f, (10 ** ((t - d) / c) - b) / a, (t - f) / e)


def logc4_para_linear(x):
    """ARRI LogC4 (LogC4 Logarithmic Color Space Specification); x = código normalizado."""
    p = np.asarray(x, dtype=float)
    a = (2 ** 18 - 16) / 117.45
    b = (1023 - 95) / 1023
    c = 95 / 1023
    s = (7 * np.log(2) * 2 ** (7 - 14 * c / b)) / (a * b)
    t = (2 ** (14 * (-c / b) + 6) - 64) / a
    return np.where(p >= 0, (2 ** (14 * ((p - c) / b) + 6) - 64) / a, p * s + t)


def applelog_para_linear(x):
    """Apple Log (Apple Log Profile White Paper); x = código normalizado."""
    p = np.asarray(x, dtype=float)
    r0, rt, sigma, beta, gamma, delta = -0.05641088, 0.01, 47.28711236, 0.00964052, 0.08550479, 0.69336945
    pt = sigma * (rt - r0) ** 2
    return np.select([p >= pt, p >= 0], [2 ** ((p - delta) / gamma) - beta, np.sqrt(np.maximum(p, 0) / sigma) + r0],
                     r0)


def bmdgen5_para_linear(x):
    """Blackmagic Film Generation 5 (Blackmagic Design, Generation 5 Color Science); x = código normalizado."""
    y = np.asarray(x, dtype=float)
    a, b, c, d, e, lin_cut = 0.08692876065491224, 0.005494072432257808, 0.5300133392291939, 8.283605932402494, \
        0.09246575342465753, 0.005
    return np.where(y < d * lin_cut + e, (y - e) / d, np.exp((y - c) / a) - b)


def davinci_para_linear(x):
    """DaVinci Intermediate (Blackmagic Design, DaVinci Resolve Wide Gamut Intermediate); x = código normalizado."""
    v = np.asarray(x, dtype=float)
    a, b, c, cut, m = 0.0075, 7.0, 0.07329248, 0.02740668, 10.44426855
    return np.where(v <= cut, v / m, 2 ** (v / c - b) - a)


def _canon_para_linear(x, corte, c, k):
    x = np.asarray(x, dtype=float)
    return 0.9 * np.where(x < corte, -(10 ** ((corte - x) / c) - 1) / k, (10 ** ((x - corte) / c) - 1) / k)


def clog_para_linear(x):
    """Canon Log (Canon, Canon Log Gamma Curve v1.2); x = código de 10 bits / 1023."""
    return _canon_para_linear(x, 0.12512248, 0.45310179, 10.1596)


def clog2_para_linear(x):
    """Canon Log 2 (Canon, Canon Log 2 Gamma Curve v1.2); x = código de 10 bits / 1023."""
    return _canon_para_linear(x, 0.092864125, 0.24136077, 87.09937546)


def dlog_para_linear(x):
    """DJI D-Log (DJI, D-Log and D-Gamut White Paper); x = código normalizado."""
    y = np.asarray(x, dtype=float)
    return np.where(y <= 0.14, (y - 0.0929) / 6.025, (10 ** (3.89616 * y - 2.27752) - 0.0108) / 0.9892)


def _fuji_para_linear(x, a, b, c, d, e, f, corte):
    x = np.asarray(x, dtype=float)
    return np.where(x < corte, (x - f) / e, 10 ** ((x - d) / c) / a - b / a)


def flog_para_linear(x):
    """Fujifilm F-Log (Fujifilm, F-Log Data Sheet); x = código de 10 bits / 1023."""
    return _fuji_para_linear(x, 0.555556, 0.009468, 0.344676, 0.790453, 8.735631, 0.092864, 0.100537775223865)


def flog2_para_linear(x):
    """Fujifilm F-Log2 (Fujifilm, F-Log2 Data Sheet); x = código de 10 bits / 1023."""
    return _fuji_para_linear(x, 5.555556, 0.064829, 0.245281, 0.384316, 8.799461, 0.092864, 0.100686685370811)


def protune_para_linear(x):
    """GoPro Protune (GoPro, Protune Flat); x = código normalizado."""
    return (113 ** np.asarray(x, dtype=float) - 1) / 112


def llog_para_linear(x):
    """Leica L-Log (Leica, L-Log Reference Manual); x = código de 10 bits / 1023."""
    x = np.asarray(x, dtype=float)
    a, b, c, d, e, f, corte = 8, 0.09, 0.27, 1.3, 0.0115, 0.6, 0.138
    return np.where(x <= corte, (x - b) / a, (10 ** ((x - f) / c) - e) / d)


def nlog_para_linear(x):
    """Nikon N-Log (Nikon, N-Log Specification Document); x = código de 10 bits / 1023."""
    x = np.asarray(x, dtype=float)
    a, b, c, d, corte = 0.635386119257087, 0.0075, 0.1466275659824047, 0.6050830889540567, 0.4418377321603128
    return np.where(x < corte, (np.maximum(x, 0) / a) ** 3 - b, np.exp((x - d) / c))


def log3g10_para_linear(x):
    """RED Log3G10 v3 (RED Digital Cinema, REDWideGamutRGB and Log3G10); x = código normalizado."""
    y = np.asarray(x, dtype=float)
    a, b, c, g = 0.224282, 155.975327, 0.01, 15.1927
    return np.where(y < 0.0, y / g - c, np.sign(y) * (10 ** (np.abs(y) / a) - 1.0) / b - c)


def codigo_de_rgb(v):
    """O FFmpeg expande a faixa legal (64–940) para RGB 0–1; volta ao código de 10 bits / 1023."""
    return (np.asarray(v, dtype=float) * 876 + 64) / 1023


# Curva de cada perfil, sobre o código de 10 bits normalizado (codigo_de_rgb). C-Log3 fica de fora: trabalha no sinal
# da faixa legal, que é o RGB cheio que o FFmpeg entrega.
CURVAS = {"slog3": slog3_para_linear, "vlog": vlog_para_linear, "slog2": slog2_para_linear,
          "logc3": logc3_para_linear, "logc4": logc4_para_linear, "applelog": applelog_para_linear,
          "bmdgen5": bmdgen5_para_linear, "davinci": davinci_para_linear, "clog": clog_para_linear,
          "clog2": clog2_para_linear, "dlog": dlog_para_linear, "flog": flog_para_linear,
          "flog2": flog2_para_linear, "protune": protune_para_linear, "llog": llog_para_linear,
          "nlog": nlog_para_linear, "log3g10": log3g10_para_linear}


# ---------- gamut ----------

def _rgb_para_xyz(primarias, branco=D65) -> np.ndarray:
    def xyz(x, y):
        return np.array([x / y, 1.0, (1 - x - y) / y])
    p = np.column_stack([xyz(*c) for c in primarias])
    return p * np.linalg.solve(p, xyz(*branco))


# Matriz RGB → XYZ que o próprio fabricante publica (4 casas), quando difere da derivada das primárias.
MATRIZ_XYZ_PUBLICADA = {"dgamut": np.array([[0.6482, 0.1940, 0.1082], [0.2830, 0.8132, -0.0962],
                                            [-0.0183, -0.0832, 1.1903]])}   # DJI, D-Log and D-Gamut White Paper


def matriz_para_709(gamut: str) -> np.ndarray:
    """Matriz linear primárias do fabricante → Rec.709: das coordenadas xy e do branco publicados de cada gamut, ou
    da matriz RGB → XYZ que o fabricante publica (MATRIZ_XYZ_PUBLICADA), quando houver."""
    origem = MATRIZ_XYZ_PUBLICADA.get(gamut)
    if origem is None:
        origem = _rgb_para_xyz(PRIMARIAS[gamut], BRANCO_DO_GAMUT.get(gamut, D65))
    return np.linalg.inv(_rgb_para_xyz(PRIMARIAS["rec709"])) @ origem


# ---------- tom: luz de cena → imagem Rec.709 ----------

_BRANCO = 16.0   # luz de cena (já com a exposição) que chega ao branco da tela


def _oetf709(l):
    l = np.clip(l, 0, 1)
    return np.where(l < 0.018, 4.5 * l, 1.099 * np.power(l, 0.45) - 0.099)


def _tom(l, ganho):
    l = np.maximum(np.asarray(l, dtype=float), 0) * ganho
    return np.minimum(l * (1 + l / _BRANCO ** 2) / (1 + l), 1.0)


def _achar_ganho() -> float:
    baixo, alto = 0.01, 100.0
    for _ in range(80):   # bissecção: o cinza 0,18 cai em CINZA_TELA
        meio = (baixo + alto) / 2
        if float(_oetf709(_tom(0.18, meio))) < CINZA_TELA:
            baixo = meio
        else:
            alto = meio
    return (baixo + alto) / 2


_GANHO = _achar_ganho()


def para_tela(lin):
    return _oetf709(_tom(lin, _GANHO))


# ---------- LUT .cube ----------

def _para_linear(perfil: str, rgb: np.ndarray) -> np.ndarray:
    if perfil == "clog3":
        return clog3_para_linear(rgb)   # C-Log3 já trabalha no sinal da faixa legal (= RGB cheio do FFmpeg)
    if perfil not in CURVAS:
        raise ValueError(f"perfil sem curva: {perfil}")
    return CURVAS[perfil](codigo_de_rgb(rgb))


def _gerar(perfil: str) -> str:
    n = TAMANHO_LUT
    eixo = np.linspace(0, 1, n)
    b, g, r = np.meshgrid(eixo, eixo, eixo, indexing="ij")   # R varia mais rápido, como pede o .cube
    rgb = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)
    lin = np.einsum("ij,kj->ik", _para_linear(perfil, rgb), matriz_para_709(GAMUT_DO_PERFIL[perfil]))
    tela = np.clip(para_tela(lin), 0, 1)
    linhas = [f"TITLE \"{perfil} para Rec.709 (motor de nota v{VERSAO_LUT})\"", f"LUT_3D_SIZE {n}",
              "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    linhas += [f"{a:.6f} {c:.6f} {d:.6f}" for a, c, d in tela]
    return "\n".join(linhas) + "\n"


def lut(perfil: str, pasta: Optional[Path] = None) -> Path:
    """LUT 3D do perfil em `pasta` (padrão analise/.luts/); gera uma vez e reaproveita."""
    if perfil not in GAMUT_DO_PERFIL:
        raise ValueError(f"perfil sem LUT: {perfil}")
    pasta = Path(pasta) if pasta else PASTA_LUTS
    destino = pasta / f"{perfil}-v{VERSAO_LUT}.cube"
    if destino.exists():
        return destino
    pasta.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{destino.name}.", dir=str(pasta))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_gerar(perfil))
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return destino


def filtro_de_lut(caminho) -> str:
    c = Path(caminho).expanduser()
    if not c.is_file():
        raise ValueError(f"LUT não encontrada: {c}")
    # Entre aspas simples o filtro do ffmpeg lê tudo literal (espaços, dois-pontos); a própria aspa fecha,
    # entra escapada e reabre.
    escapado = str(c.resolve()).replace("'", "'\\''")
    return f"lut3d=file='{escapado}'"


def filtro(perfil: Optional[str], pasta: Optional[Path] = None) -> Optional[str]:
    if perfil in (None, "nenhum"):
        return None
    if perfil == "generico":
        return FILTRO_LOG
    return filtro_de_lut(lut(perfil, pasta))


# ---------- qual perfil cada clipe usa ----------

def perfil_sony(caminho: str) -> Optional[str]:
    """Lê CaptureGammaEquation do <clipe>M01.XML que as câmeras Sony gravam ao lado do vídeo."""
    c = Path(caminho)
    xml = next((x for x in (c.with_name(f"{c.stem}M01.XML"), c.with_name(f"{c.stem}M01.xml")) if x.is_file()), None)
    if xml is None:
        return None
    try:
        raiz = ET.parse(str(xml)).getroot()
    except (ET.ParseError, OSError):
        return None
    for el in raiz.iter():
        if el.tag.endswith("Item") and el.get("name") == "CaptureGammaEquation":
            valor = (el.get("value") or "").lower()
            if valor.startswith("s-log3"):
                return "slog3"
            if valor.startswith("s-log2"):
                return "slog2"
            return "generico" if "log" in valor else "nenhum"
    return None


# Nomes de perfil que câmeras e geradores escrevem nos metadados, do mais específico ao mais geral (D-Log M antes de
# D-Log, C-Log3 antes de C-Log…). Só formas com hífen, espaço ou o fabricante: "vlog" solto é vídeo de blog.
_NOMES_PERFIL = [
    (r"d-log ?m\b", "generico"),   # DJI D-Log M: fórmula não publicada
    (r"\bs-?log ?3", "slog3"), (r"\bs-log ?2\b|\bslog2\b", "slog2"), (r"\bv-log\b", "vlog"),
    (r"\bc-?log ?3\b|canon log ?3", "clog3"), (r"\bc-?log ?2\b|canon log ?2", "clog2"),
    (r"\bc-log\b|canon log\b", "clog"),
    (r"\blog ?c ?4\b", "logc4"), (r"\blog ?c ?3\b|\blogc\b", "logc3"), (r"\bapple ?log\b", "applelog"),
    (r"film gen(eration)? ?5", "bmdgen5"), (r"davinci intermediate", "davinci"), (r"\bd-log\b", "dlog"),
    (r"\bf-?log ?2\b", "flog2"), (r"\bf-log\b", "flog"), (r"\bn-log\b", "nlog"), (r"\bl-log\b", "llog"),
    (r"protune ?log|\bgp-?log\b", "protune"), (r"log3g10", "log3g10"),
]
_MAX_SIDECAR = 1024 * 1024
_EXT_SIDECAR = (".xml", ".XML", ".txt", ".json")


def perfil_no_texto(texto: str) -> Optional[str]:
    """Primeiro perfil de _NOMES_PERFIL achado no texto (minúsculas), ou None."""
    t = (texto or "").lower()
    for padrao, perfil in _NOMES_PERFIL:
        if re.search(padrao, t):
            return perfil
    return None


def perfil_por_metadados(caminho: str) -> Optional[str]:
    """Perfil pelas tags do arquivo (ffprobe: chaves e valores) e pelos sidecars de texto com o mesmo nome. Só lê."""
    c = Path(caminho)
    textos = []
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags:stream_tags", "-of", "json",
                            str(c)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        d = json.loads(r.stdout or "{}")
        for bloco in [d.get("format") or {}] + (d.get("streams") or []):
            textos.extend(f"{k} {v}" for k, v in (bloco.get("tags") or {}).items())
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    for ext in _EXT_SIDECAR:
        s = c.with_name(c.stem + ext)
        try:
            if s.is_file() and s.stat().st_size <= _MAX_SIDECAR:
                textos.append(s.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    texto = "\n".join(textos)
    achado = perfil_no_texto(texto)
    # A câmera declarou a gama (Panasonic: <CaptureGamma> no XML do .MOV) e não é log: PORTRAIT, STANDARD, HLG…
    if achado is None and re.search(r"<capturegamma>\s*[^<\s]", texto, re.IGNORECASE):
        return "nenhum"
    return achado


def perfil_do_clipe(caminho: str, preset_perfil: Optional[str]) -> str:
    if preset_perfil in PERFIS:
        return preset_perfil
    if preset_perfil == "auto":
        return perfil_sony(caminho) or perfil_por_metadados(caminho) or "generico"
    return "nenhum"


def filtro_do_clipe(caminho: str, preset_perfil: Optional[str], lut_propria: Optional[str] = None,
                    pasta: Optional[Path] = None) -> Optional[str]:
    if lut_propria:
        return filtro_de_lut(lut_propria)
    return filtro(perfil_do_clipe(caminho, preset_perfil), pasta)

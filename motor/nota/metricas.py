"""Métricas por quadro. Funções puras sobre arrays uint8 em cinza; não sabem de arquivos."""
from __future__ import annotations

import math

import cv2
import numpy as np

_HANN: dict = {}
_ORB = cv2.ORB_create(nfeatures=500)
_PAREADOR = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
_MIN_PONTOS = 10


def nitidez(q: np.ndarray) -> float:
    return float(cv2.Laplacian(q, cv2.CV_64F).var())


def _sem_barras(q: np.ndarray, limiar: int = 12) -> np.ndarray:
    """Recorta barras pretas (letterbox/pillarbox): linhas e colunas inteiras quase pretas nas bordas."""
    linhas = np.where(q.mean(axis=1) > limiar)[0]
    colunas = np.where(q.mean(axis=0) > limiar)[0]
    if linhas.size == 0 or colunas.size == 0:
        return q
    return q[linhas[0]:linhas[-1] + 1, colunas[0]:colunas[-1] + 1]


def nitidez_regiao(q: np.ndarray, grade=(3, 3)) -> float:
    """Nitidez da região mais nítida de uma grade 3×3, sem as barras pretas.

    Um assunto em foco contra um fundo liso ou desfocado puxa a nota para cima, como no Cutdown, em vez de
    ser diluído pela média do quadro inteiro."""
    q = _sem_barras(q)
    h, w = q.shape
    lin, col = grade
    if h < 3 * lin or w < 3 * col:
        return nitidez(q)
    lap = cv2.Laplacian(q, cv2.CV_64F)
    return float(max(lap[i * h // lin:(i + 1) * h // lin, j * w // col:(j + 1) * w // col].var()
                     for i in range(lin) for j in range(col)))


def exposicao(q: np.ndarray) -> dict:
    p01, p99 = np.percentile(q, (1, 99))
    return {
        "brilho": float(q.mean() / 255.0),
        "estourado": float((q > 250).mean()),
        "esmagado": float((q < 5).mean()),
        "contraste": float(q.std() / 128.0),
        # Margem até estourar ou esmagar: a "folga para a cor" do Cutdown.
        "luma_p01": float(p01 / 255.0),
        "luma_p99": float(p99 / 255.0),
    }


def detalhe(q: np.ndarray) -> float:
    """Fração de pixels de borda: textura fina. Diferente da nitidez (quão afiada é cada borda)."""
    return float((cv2.Canny(q, 60, 180) > 0).mean())


def _hann(forma) -> np.ndarray:
    if forma not in _HANN:
        _HANN[forma] = cv2.createHanningWindow((forma[1], forma[0]), cv2.CV_32F)
    return _HANN[forma]


def deslocamento(ant: np.ndarray, atual: np.ndarray):
    """Quanto o conteúdo andou de `ant` para `atual`, em pixels (sx > 0 = para a direita), e a resposta 0–1."""
    (sx, sy), resposta = cv2.phaseCorrelate(ant.astype(np.float32), atual.astype(np.float32), _hann(ant.shape))
    return float(sx), float(sy), float(resposta)


def afim(ant: np.ndarray, atual: np.ndarray):
    """Escala (> 1 = aproximou), rotação em graus e se havia pontos suficientes para medir.

    A rotação é o ângulo da afim que leva `ant` em `atual`, em coordenadas de imagem (y para baixo): positivo =
    o conteúdo girou no sentido horário na tela.
    """
    k1, d1 = _ORB.detectAndCompute(ant, None)
    k2, d2 = _ORB.detectAndCompute(atual, None)
    if d1 is None or d2 is None or len(k1) < _MIN_PONTOS or len(k2) < _MIN_PONTOS:
        return 1.0, 0.0, False
    pares = _PAREADOR.match(d1, d2)
    if len(pares) < _MIN_PONTOS:
        return 1.0, 0.0, False
    p1 = np.float32([k1[m.queryIdx].pt for m in pares])
    p2 = np.float32([k2[m.trainIdx].pt for m in pares])
    m, mascara = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if m is None or mascara is None or int(mascara.sum()) < _MIN_PONTOS:
        return 1.0, 0.0, False
    return float(math.hypot(m[0, 0], m[1, 0])), float(math.degrees(math.atan2(m[1, 0], m[0, 0]))), True


def escala(ant: np.ndarray, atual: np.ndarray):
    """Fator de escala do conteúdo (> 1 = aproximou) e se havia pontos suficientes para medir."""
    fator, _, ok = afim(ant, atual)
    return fator, ok


def movimento_assunto(ant: np.ndarray, atual: np.ndarray, sx: float, sy: float) -> float:
    """Diferença média (0–1) entre os quadros depois de desfazer o movimento da câmera."""
    h, w = ant.shape
    m = np.float32([[1, 0, -sx], [0, 1, -sy]])
    alinhado = cv2.warpAffine(atual, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mx = max(int(0.1 * w), int(math.ceil(abs(sx))) + 2)
    my = max(int(0.1 * h), int(math.ceil(abs(sy))) + 2)
    if mx * 2 >= w or my * 2 >= h:
        return 1.0
    return float(cv2.absdiff(ant, alinhado)[my:h - my, mx:w - mx].mean() / 255.0)


def semelhanca_histograma(a: np.ndarray, b: np.ndarray) -> float:
    ha = cv2.calcHist([a], [0], None, [64], [0, 256])
    hb = cv2.calcHist([b], [0], None, [64], [0, 256])
    cv2.normalize(ha, ha)
    cv2.normalize(hb, hb)
    return float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))


def _padronizado(q: np.ndarray) -> np.ndarray:
    """Quadro com média 0 e desvio 1: tira brilho e contraste, sobra a estrutura."""
    f = q.astype(np.float32)
    return (f - float(f.mean())) / max(float(f.std()), 1.0)


def diferenca_estrutura(ant: np.ndarray, atual: np.ndarray, sx: float, sy: float) -> float:
    """Diferença média entre os quadros padronizados (brilho/contraste) depois de desfazer o movimento
    da câmera. ~0 no mesmo plano (mesmo com degrau de exposição), ~1 ou mais entre cenas diferentes."""
    h, w = ant.shape
    m = np.float32([[1, 0, -sx], [0, 1, -sy]])
    alinhado = cv2.warpAffine(_padronizado(atual), m, (w, h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    mx = max(int(0.1 * w), int(math.ceil(abs(sx))) + 2)
    my = max(int(0.1 * h), int(math.ceil(abs(sy))) + 2)
    if mx * 2 >= w or my * 2 >= h:
        return 2.0
    return float(np.abs(_padronizado(ant) - alinhado)[my:h - my, mx:w - mx].mean())


def diferenca_bruta(a: np.ndarray, b: np.ndarray) -> float:
    return float(cv2.absdiff(a, b).mean() / 255.0)


def _media_movel(v: np.ndarray, k: int) -> np.ndarray:
    pad = np.pad(v, (k // 2, k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def tremor_serie(dx, dy, janela: float) -> np.ndarray:
    """RMS, numa janela móvel, do componente de alta frequência do movimento da câmera."""
    dx = np.asarray(dx, dtype=float)
    dy = np.asarray(dy, dtype=float)
    if dx.size == 0:
        return dx
    k = max(3, int(janela) | 1)
    alta = np.hypot(dx - _media_movel(dx, k), dy - _media_movel(dy, k))
    return np.sqrt(_media_movel(alta ** 2, k))

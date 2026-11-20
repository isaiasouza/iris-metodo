"""Clipes de teste com características conhecidas, gerados com ffmpeg a partir de cenas determinísticas."""
from __future__ import annotations

import atexit
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

_CACHE: dict = {}
_EXTRAS: dict = {}


def cena(semente: int, minimo: int, maximo: int, w: int = 2560, h: int = 1440) -> np.ndarray:
    """Textura suave + retângulos (cantos para o ORB), em cinza, com valores entre minimo e maximo."""
    rng = np.random.default_rng(semente)
    base = rng.random((max(2, h // 8), max(2, w // 8))).astype(np.float32)
    base = cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)
    img = minimo + np.clip(base, 0, 1) * (maximo - minimo)
    rmin, rmax = max(3, w // 128), max(4, w // 16)
    for _ in range(400):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        ww, hh = (int(v) for v in rng.integers(rmin, rmax, size=2))
        cor = float(rng.uniform(minimo, maximo))
        cv2.rectangle(img, (x, y), (x + ww, y + hh), cor, -1)
    return np.clip(img, 0, 255).astype(np.uint8)


def _ffmpeg(args: list) -> None:
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y"] + args
    subprocess.run(cmd, check=True)


_SAIDA = ["-r", "24", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"]


def _gerar(pasta: Path) -> dict:
    a = pasta / "cena_a.png"
    b = pasta / "cena_b.png"
    cv2.imwrite(str(a), cena(42, 40, 200))
    cv2.imwrite(str(b), cena(7, 15, 100))
    img = ["-loop", "1", "-framerate", "24", "-t", "3", "-i", str(a)]
    c = {k: str(pasta / f"{k}.mp4") for k in ("parado", "blur", "estourado", "pan_esq", "push_in", "tremido", "corte")}
    _ffmpeg(img + ["-vf", "crop=1920:1080:300:180"] + _SAIDA + [c["parado"]])
    _ffmpeg(img + ["-vf", "crop=1920:1080:300:180,gblur=sigma=30"] + _SAIDA + [c["blur"]])
    _ffmpeg(img + ["-vf", "crop=1920:1080:300:180,eq=brightness=0.6"] + _SAIDA + [c["estourado"]])
    # x diminui: a janela anda para a esquerda = câmera faz pan para a esquerda (120 px/s em 1920)
    _ffmpeg(img + ["-vf", "crop=1920:1080:600-120*t:180"] + _SAIDA + [c["pan_esq"]])
    _ffmpeg(img + ["-vf", "crop=1920:1080:320+40*sin(37*t)+30*sin(71*t):180+30*sin(53*t)"] + _SAIDA + [c["tremido"]])
    _ffmpeg(["-loop", "1", "-framerate", "1", "-i", str(a),
             "-vf", "scale=5120:2880,zoompan=z='1+0.002*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=72:s=1920x1080:fps=24",
             "-frames:v", "72"] + _SAIDA + [c["push_in"]])
    _ffmpeg(["-loop", "1", "-framerate", "24", "-t", "4", "-i", str(a),
             "-loop", "1", "-framerate", "24", "-t", "4", "-i", str(b),
             "-filter_complex", "[0]crop=1920:1080:300:180[x];[1]crop=1920:1080:300:180[y];[x][y]concat=n=2:v=1[v]",
             "-map", "[v]"] + _SAIDA + [c["corte"]])
    return c


def _pasta() -> Path:
    if "_pasta" not in _EXTRAS:
        pasta = Path(tempfile.mkdtemp(prefix="nota_sint_extra_"))
        atexit.register(shutil.rmtree, pasta, True)
        _EXTRAS["_pasta"] = pasta
    return _EXTRAS["_pasta"]


def girado() -> str:
    """O clipe `parado` (1920x1080 codificado) com metadado de rotação de 90° (vídeo de celular em pé)."""
    if "girado" not in _EXTRAS:
        destino = _pasta() / "girado.mp4"
        _ffmpeg(["-display_rotation", "90", "-i", clipes()["parado"], "-c", "copy", str(destino)])
        _EXTRAS["girado"] = str(destino)
    return _EXTRAS["girado"]


def clipes() -> dict:
    """Gera (uma vez por processo) e devolve {nome: caminho} dos clipes sintéticos."""
    if not _CACHE:
        pasta = Path(tempfile.mkdtemp(prefix="nota_sint_"))
        atexit.register(shutil.rmtree, pasta, True)
        _CACHE.update(_gerar(pasta))
    return dict(_CACHE)

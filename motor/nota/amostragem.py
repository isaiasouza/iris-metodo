"""Lê clipes com ffprobe/ffmpeg (só leitura) e entrega quadros reduzidos em cinza por pipe."""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple

import numpy as np


# Vigia: o ffmpeg é morto se passar de max(_TEMPO_MIN_S, _FATOR_TEMPO × duração × max(1, fps/30)).
_TEMPO_MIN_S = 60.0
_FATOR_TEMPO = 3.0
_COMPLETO_MIN = 0.9
_CAUDA_ERRO = 4096


class ErroLeitura(Exception):
    """O ffprobe/ffmpeg não conseguiu ler o clipe."""


@dataclass(frozen=True)
class InfoClipe:
    caminho: str
    duracao: float
    fps: float
    largura: int
    altura: int
    codec: str


def _numero(texto) -> float:
    """Converte o texto do ffprobe em float; "N/A", vazio ou lixo viram 0."""
    try:
        v = float(texto)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and v > 0 else 0.0


def _fracao(texto) -> float:
    if not texto or texto == "0/0":
        return 0.0
    if "/" in texto:
        n, d = texto.split("/")
        return _numero(n) / _numero(d) if _numero(d) else 0.0
    return _numero(texto)


def _fps(stream: dict) -> float:
    return _fracao(stream.get("avg_frame_rate")) or _fracao(stream.get("r_frame_rate"))


def _duracao(dados: dict) -> float:
    """Duração do stream de vídeo, senão do formato, senão nb_frames / fps; 0 quando desconhecida.
    O stream vem primeiro: o container pode durar mais por causa do áudio, e a contagem é de quadros de vídeo."""
    s = (dados.get("streams") or [{}])[0]
    duracao = _numero(s.get("duration")) or _numero((dados.get("format") or {}).get("duration"))
    if not duracao and _fps(s):
        duracao = _numero(s.get("nb_frames")) / _fps(s)
    return duracao


def _rotacao(stream: dict) -> int:
    """Rotação de exibição em graus, 0–359 (matriz de exibição ou a tag antiga `rotate`)."""
    valores = [sd["rotation"] for sd in stream.get("side_data_list") or [] if "rotation" in sd]
    valores.append((stream.get("tags") or {}).get("rotate"))
    for v in valores:
        try:
            return int(round(float(v))) % 360
        except (TypeError, ValueError):
            continue
    return 0


def probe(caminho: str, timeout: Optional[float] = None) -> InfoClipe:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,codec_name,avg_frame_rate,r_frame_rate,duration,nb_frames"
           ":stream_side_data=rotation:stream_tags=rotate:format=duration",
           "-of", "json", caminho]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ErroLeitura(f"o ffprobe não respondeu em {timeout:.0f} s") from e
    if r.returncode != 0:
        raise ErroLeitura(r.stderr.strip() or "ffprobe falhou")
    dados = json.loads(r.stdout or "{}")
    streams = dados.get("streams") or []
    if not streams:
        raise ErroLeitura("sem stream de vídeo")
    s = streams[0]
    largura, altura = int(s["width"]), int(s["height"])
    # O ffmpeg gira os quadros sozinho (autorotate); a escala precisa usar as dimensões já giradas.
    if _rotacao(s) % 180 == 90:
        largura, altura = altura, largura
    return InfoClipe(caminho, _duracao(dados), _fps(s), largura, altura, s.get("codec_name", "?"))


def altura_reduzida(info: InfoClipe, largura: int) -> int:
    return max(2, int(round(info.altura * largura / info.largura / 2.0)) * 2)


def _comando(caminho: str, amostras_por_s: float, largura: int, altura: int, hw: bool) -> list:
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if hw:
        cmd += ["-hwaccel", "videotoolbox"]
    filtro = f"fps={amostras_por_s},scale={largura}:{altura}:flags=area,format=gray"
    return cmd + ["-i", caminho, "-an", "-vf", filtro, "-f", "rawvideo", "-pix_fmt", "gray", "-"]


def _limite_s(info: InfoClipe, decodificado_s: float) -> float:
    base = max(info.duracao, decodificado_s) * max(1.0, info.fps / 30.0)
    return max(_TEMPO_MIN_S, _FATOR_TEMPO * base)


def _ultima_mensagem(texto: str) -> str:
    """Última linha útil do stderr: pula linhas vazias e o "Last message repeated N times" do ffmpeg."""
    for linha in reversed(texto.splitlines()):
        linha = linha.strip()
        if linha and not linha.startswith("Last message repeated"):
            return linha
    return ""


def _cauda(arquivo) -> str:
    arquivo.seek(0, 2)
    tamanho = arquivo.tell()
    arquivo.seek(max(0, tamanho - _CAUDA_ERRO))
    return arquivo.read().decode(errors="replace").strip()


def amostrar(info: InfoClipe, amostras_por_s: float = 4.0, largura: int = 320,
             hw: bool = True) -> Iterator[Tuple[float, np.ndarray]]:
    """Gera (t, quadro) com t = i / amostras_por_s. Nada é gravado em disco.

    O stderr do ffmpeg vai para um arquivo temporário (um pipe cheio travaria o ffmpeg), um vigia
    mata o ffmpeg se ele passar do tempo, e decodificação interrompida ou incompleta vira ErroLeitura.
    """
    altura = altura_reduzida(info, largura)
    tamanho = largura * altura
    with tempfile.TemporaryFile() as erros:
        proc = subprocess.Popen(_comando(info.caminho, amostras_por_s, largura, altura, hw),
                                stdout=subprocess.PIPE, stderr=erros)
        progresso = [0.0]
        parar = threading.Event()
        estourou = threading.Event()
        inicio = time.monotonic()

        def vigiar():
            while not parar.wait(0.2):
                if time.monotonic() - inicio > _limite_s(info, progresso[0]):
                    estourou.set()
                    proc.kill()
                    return

        vigia = threading.Thread(target=vigiar, daemon=True)
        vigia.start()
        i = 0
        terminou = False
        try:
            while True:
                buf = proc.stdout.read(tamanho)
                if len(buf) < tamanho:
                    terminou = True
                    break
                yield i / amostras_por_s, np.frombuffer(buf, np.uint8).reshape(altura, largura)
                i += 1
                progresso[0] = i / amostras_por_s
        finally:
            parar.set()
            proc.stdout.close()
            if not terminou:
                proc.kill()  # quem consumia parou antes do fim
            proc.wait()
            vigia.join()
        erro = _cauda(erros)
    if estourou.is_set():
        raise ErroLeitura(f"tempo esgotado decodificando ({i} quadros lidos); ffmpeg interrompido")
    if proc.returncode != 0:
        raise ErroLeitura(erro or f"ffmpeg saiu com código {proc.returncode}")
    if i == 0:
        raise ErroLeitura(erro or "nenhum quadro decodificado")
    esperados = int(round(info.duracao * amostras_por_s))
    if info.duracao > 0 and i < _COMPLETO_MIN * esperados:
        ultima = _ultima_mensagem(erro)
        detalhe = f": {ultima}" if ultima else ""
        raise ErroLeitura(f"decodificação incompleta: {i} de {esperados} quadros{detalhe}")

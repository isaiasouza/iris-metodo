"""Export AAF (Avid Media Composer, DaVinci Resolve, Premiere), com o pyaaf2.

A mídia não é copiada nem convertida: cada arquivo entra na estrutura clássica que o próprio Resolve exporta (e
que ele liga à mídia ao importar com importSourceClips), sem o link AMA do pyaaf2:

    CompositionMob ── slot 1 Timecode (01:00:00:00), slot 2 Picture, slot 3 Sound, slot 4 marcadores
      └─ SourceClip → MasterMob (nome do clipe; Picture e Sound na taxa do vídeo)
           ├─ SourceClip → SourceMob de imagem (CDCIDescriptor + NetworkLocator file:///…)
           │    └─ SourceClip → SourceMob de fita (TapeDescriptor; Timecode = TC de início do arquivo)
           └─ SourceClip → SourceMob de som (PCMDescriptor + o mesmo NetworkLocator)
                └─ SourceClip → outra SourceMob de fita, como o Resolve faz

Uma MasterMob por arquivo (o padrão do Avid; o Resolve faz uma por trecho). Arquivo sem som: sem file mob de som e
Filler no slot de som da composição. O pyaaf2 é opcional: só este formato precisa dele.

Unidades: no AAF o StartTime e o Length de um SourceClip contam na taxa do slot que *contém* o clipe. Todos os slots
da composição estão na taxa da sequência, então imagem e som usam o mesmo início e a mesma duração, em quadros da
sequência (iguais aos quadros do arquivo quando a taxa é a mesma). Dentro das mobs de origem tudo está na taxa do
vídeo; só o PCMDescriptor conta em amostras.
"""
from __future__ import annotations

import json
import os
import subprocess
from fractions import Fraction
from pathlib import Path

from exportar import fps_racional, quadros_do_trecho


class SemPyaaf2(RuntimeError):
    pass


def _ffprobe(caminho: str) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", caminho],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {}


def _slot(mob, tipo: str):
    return next((s for s in mob.slots if s.media_kind == tipo), None)


def _novo_slot(f, mob, slot_id: int, taxa, segmento, nome: str = ""):
    slot = f.create.TimelineMobSlot(slot_id, edit_rate=taxa)
    slot["PhysicalTrackNumber"].value = 1
    slot["SlotName"].value = nome
    slot.segment = segmento
    mob.slots.append(slot)
    return slot


def _clipe(f, tipo: str, comprimento: int, mob=None, slot_id: int = 0, inicio: int = 0):
    """SourceClip para (mob, slot_id); sem mob é o fim da cadeia (o clipe vazio da fita)."""
    c = f.create.SourceClip(media_kind=tipo, length=comprimento, start=inicio)
    if mob is not None:
        c.mob_id = mob.mob_id
        c.slot_id = slot_id
    return c


def _fita(f, tipo: str, taxa, quadros: int, tc_inicio: int, tc_fps: int):
    """SourceMob de fita (TapeDescriptor): slot 1 Timecode com o TC do arquivo, slot 2 do tipo pedido."""
    fita = f.create.SourceMob()
    fita.name = ""  # o Resolve deixa a fita sem nome
    fita.descriptor = f.create.TapeDescriptor()
    tc = f.create.Timecode(tc_fps, drop=False, length=quadros)
    tc.start = tc_inicio
    _novo_slot(f, fita, 1, taxa, tc)
    _novo_slot(f, fita, 2, taxa, _clipe(f, tipo, quadros))
    f.content.mobs.append(fita)
    return fita


def _localizador(f, caminho: str):
    loc = f.create.NetworkLocator()
    loc["URLString"].value = Path(os.path.abspath(caminho)).as_uri()
    return loc


def _arquivo(f, nome: str, descritor, tipo: str, taxa, quadros: int, fita):
    mob = f.create.SourceMob(nome)
    mob.descriptor = descritor
    _novo_slot(f, mob, 1, taxa, _clipe(f, tipo, quadros, fita, 2))
    f.content.mobs.append(mob)
    return mob


def _descritor_imagem(f, caminho: str, video: dict, taxa, quadros: int):
    d = f.create.CDCIDescriptor()
    largura, altura = int(video["width"]), int(video["height"])
    aspecto = video.get("display_aspect_ratio") or ""
    try:
        n, m = (int(x) for x in aspecto.split(":"))
        razao = Fraction(n, m)
    except (ValueError, ZeroDivisionError):
        razao = None
    if not razao:  # "0:1", "N/A" ou ausente
        razao = Fraction(largura, altura)
    d["StoredWidth"].value = largura
    d["StoredHeight"].value = altura
    d["FrameLayout"].value = "FullFrame"
    d["VideoLineMap"].value = [0, 1]
    d["ImageAspectRatio"].value = razao
    d["ComponentWidth"].value = 8
    d["HorizontalSubsampling"].value = 2
    d["FrameSampleSize"].value = largura * altura * 2
    d["SampleRate"].value = taxa
    d["Length"].value = quadros
    d["ContainerFormat"].value = f.dictionary.lookup_containerdef("AAFKLV")
    d["Locator"].append(_localizador(f, caminho))
    return d


def _bits(audio: dict) -> int:
    """Bits por amostra do stream (PCM dá bits_per_sample; FLAC/ALAC, bits_per_raw_sample); AAC e afins: 16."""
    for chave in ("bits_per_sample", "bits_per_raw_sample"):
        try:
            bits = int(audio.get(chave) or 0)
        except (TypeError, ValueError):
            bits = 0
        if bits > 0:
            return bits
    return 16


def _descritor_som(f, caminho: str, audio: dict, segundos: float):
    d = f.create.PCMDescriptor()
    taxa = int(audio.get("sample_rate") or 48000)
    canais = int(audio.get("channels") or 2)
    bits = _bits(audio)
    # O Resolve escreve o bloco por canal (16 bits estéreo 48k: BlockAlign 2, AverageBPS 96000), e é essa a
    # leitura que ele liga à mídia; canais*bits/8 daria 4 e 192000.
    bloco = max(1, (bits + 7) // 8)
    d["SampleRate"].value = taxa
    d["AudioSamplingRate"].value = taxa
    d["Channels"].value = canais
    d["QuantizationBits"].value = bits
    d["BlockAlign"].value = bloco
    d["AverageBPS"].value = taxa * bloco
    d["Length"].value = int(round(segundos * taxa))
    d["Locator"].append(_localizador(f, caminho))
    return d


def _eh_imagem(s: dict) -> bool:
    """Stream de vídeo de verdade: capa embutida (attached_pic, MP3/M4A com arte) não conta."""
    return (s.get("codec_type") == "video" and bool(s.get("width"))
            and not (s.get("disposition") or {}).get("attached_pic"))


def _linkar(f, caminho: str, i: dict, fim_trechos: int = 0):
    """Monta as mobs de origem do arquivo e devolve a MasterMob."""
    nome = Path(caminho).name
    meta = _ffprobe(caminho)
    streams = meta.get("streams") or []
    if not streams:
        raise RuntimeError(f"o ffprobe não leu {nome} (arquivo sumiu ou disco desconectado?)")
    video = next((s for s in streams if _eh_imagem(s)), None)
    if video is None:
        raise RuntimeError(f"{nome} não tem imagem; o AAF só leva clipes de vídeo (arquivo só de áudio?)")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = i["fps"]
    taxa = fps_racional(fps)
    segundos = float(video.get("duration") or meta.get("format", {}).get("duration") or 0.0)
    nb = video.get("nb_frames")
    do_ffprobe = int(nb) if nb and str(nb).isdigit() else int(round(segundos * fps))
    quadros = max(int(i.get("duracao_quadros") or 0), do_ffprobe)
    if quadros <= 0:
        raise RuntimeError(f"não deu para saber quantos quadros {nome} tem (o ffprobe não deu duração)")
    quadros = max(quadros, fim_trechos)  # nenhum trecho passa do fim da mídia
    tc_fps = round(fps)
    clipe = Path(caminho).stem

    mestre = f.create.MasterMob(clipe)
    fita = _fita(f, "picture", taxa, quadros, i["tc_inicio"], tc_fps)
    imagem = _arquivo(f, clipe, _descritor_imagem(f, caminho, video, taxa, quadros), "picture", taxa, quadros, fita)
    _novo_slot(f, mestre, 1, taxa, _clipe(f, "picture", quadros, imagem, 1))
    if audio is not None:
        seg_audio = float(audio.get("duration") or 0.0) or segundos or quadros / fps
        fita_som = _fita(f, "sound", taxa, quadros, i["tc_inicio"], tc_fps)
        som = _arquivo(f, clipe, _descritor_som(f, caminho, audio, seg_audio), "sound", taxa, quadros, fita_som)
        _novo_slot(f, mestre, 2, taxa, _clipe(f, "sound", quadros, som, 1))
    f.content.mobs.append(mestre)
    return mestre


def escrever_aaf(trechos: list, info: dict, nome: str, destino: Path) -> None:
    try:
        import aaf2
    except ImportError as e:
        raise SemPyaaf2("o export AAF precisa do pyaaf2; instale com: python3 -m pip install --user pyaaf2") from e
    fps_seq = info[trechos[0]["caminho"]]["fps"]
    taxa = fps_racional(fps_seq)
    tmp = destino.with_name(destino.name + ".tmp")
    try:
        with aaf2.open(str(tmp), "w") as f:
            fins = {}
            for t in trechos:
                inicio, dur = quadros_do_trecho(t, info[t["caminho"]]["fps"])
                fins[t["caminho"]] = max(fins.get(t["caminho"], 0), inicio + dur)
            mestres = {c: _linkar(f, c, info[c], fins[c]) for c in fins}
            comp = f.create.CompositionMob(nome)
            comp.usage = "Usage_TopLevel"
            f.content.mobs.append(comp)
            tc = f.create.Timecode(round(fps_seq), drop=False, length=0)
            tc.start = round(fps_seq) * 3600  # 01:00:00:00
            _novo_slot(f, comp, 1, taxa, tc)
            imagem = _novo_slot(f, comp, 2, taxa, f.create.Sequence(media_kind="picture"))
            som = _novo_slot(f, comp, 3, taxa, f.create.Sequence(media_kind="sound"), "Audio 1")
            evento = f.create.EventMobSlot()
            evento["EditRate"].value = taxa
            evento["SlotID"].value = 4
            marcas = f.create.Sequence(media_kind="DescriptiveMetadata")
            evento.segment = marcas
            comp.slots.append(evento)
            pos = 0
            for t in trechos:
                i = info[t["caminho"]]
                mestre = mestres[t["caminho"]]
                _, dur = quadros_do_trecho(t, i["fps"])
                dur_seq = max(1, round(dur * fps_seq / i["fps"]))
                inicio_seq = int(round(t["inicio_s"] * fps_seq))  # na taxa do slot da composição
                origem = _slot(mestre, "Picture")
                imagem.segment.components.append(
                    mestre.create_source_clip(slot_id=origem.slot_id, start=inicio_seq, length=dur_seq))
                audio = _slot(mestre, "Sound")
                if audio is not None:
                    som.segment.components.append(
                        mestre.create_source_clip(slot_id=audio.slot_id, start=inicio_seq, length=dur_seq))
                else:
                    som.segment.components.append(f.create.Filler("sound", dur_seq))
                marcador = t.get("marcador", {"nome": t["id"], "nota": t.get("motivo", "")})
                m = f.create.DescriptiveMarker()
                m["Position"].value = pos
                m["Length"].value = 1
                m["Comment"].value = marcador["nota"]
                m["CommentMarkerUser"].value = marcador["nome"]
                m["DescribedSlots"].value = {imagem.slot_id}
                marcas.components.append(m)
                pos += dur_seq
            tc.length = pos
        os.replace(tmp, destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

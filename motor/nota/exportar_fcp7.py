"""Export FCP7 XML (xmeml 5): o formato de intercâmbio que o Premiere importa (o Resolve também).

Uma sequência começando em 01:00:00:00, trilha de vídeo e de áudio com os trechos em sequência. No xmeml,
<in>/<out> contam quadros desde o começo do arquivo; o timecode de origem vai no <file>. Cada arquivo é descrito
por inteiro na primeira vez e depois só referenciado pelo id.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from exportar import cor_da_nota, fps_racional, quadros_do_trecho, quadros_em_timecode


def _rate(fps: float) -> str:
    ntsc = "TRUE" if fps_racional(fps).denominator == 1001 else "FALSE"
    return f"<rate><timebase>{round(fps)}</timebase><ntsc>{ntsc}</ntsc></rate>"


def _timecode(quadros: int, fps: float) -> str:
    return (f"<timecode>{_rate(fps)}<string>{quadros_em_timecode(quadros, fps)}</string><frame>{quadros}</frame>"
            "<displayformat>NDF</displayformat></timecode>")


def _pathurl(caminho: str) -> str:
    return "file://localhost" + quote(str(Path(caminho)))


def _arquivo(ident: str, caminho: str, i: dict) -> str:
    return (f'<file id="{ident}"><name>{escape(Path(caminho).name)}</name>'
            f"<pathurl>{escape(_pathurl(caminho))}</pathurl>{_rate(i['fps'])}"
            f"<duration>{i['duracao_quadros']}</duration>{_timecode(i['tc_inicio'], i['fps'])}"
            f"<media><video><samplecharacteristics>{_rate(i['fps'])}<width>{i['largura']}</width>"
            f"<height>{i['altura']}</height></samplecharacteristics></video>"
            "<audio><channelcount>2</channelcount></audio></media></file>")


def para_xml(trechos: list, info: dict, nome: str) -> str:
    """xmeml 5 com os trechos na ordem recebida."""
    primeiro = info[trechos[0]["caminho"]] if trechos else {"fps": 24.0, "largura": 1920, "altura": 1080}
    fps_seq = primeiro["fps"]
    arquivos, video, audio, pos = {}, [], [], 0
    for n, t in enumerate(trechos, 1):
        i = info[t["caminho"]]
        inicio, dur = quadros_do_trecho(t, i["fps"])
        dur_seq = max(1, round(dur * fps_seq / i["fps"]))
        if t["caminho"] in arquivos:
            arq = f'<file id="{arquivos[t["caminho"]]}"/>'
        else:
            arquivos[t["caminho"]] = f"file-{len(arquivos) + 1}"
            arq = _arquivo(arquivos[t["caminho"]], t["caminho"], i)
        marcador = t.get("marcador", {"nome": t["id"], "nota": t.get("motivo", "")})
        comum = (f"<name>{escape(t['id'])}</name><duration>{i['duracao_quadros']}</duration>{_rate(i['fps'])}"
                 f"<start>{pos}</start><end>{pos + dur_seq}</end><in>{inicio}</in><out>{inicio + dur}</out>")
        # Liga imagem e som do trecho (como o export do próprio Premiere): mover um move o outro.
        links = (f"<link><linkclipref>clipitem-v{n}</linkclipref><mediatype>video</mediatype>"
                 f"<trackindex>1</trackindex><clipindex>{n}</clipindex></link>"
                 f"<link><linkclipref>clipitem-a{n}</linkclipref><mediatype>audio</mediatype>"
                 f"<trackindex>1</trackindex><clipindex>{n}</clipindex><groupindex>1</groupindex></link>")
        video.append(f'<clipitem id="clipitem-v{n}">{comum}{arq}{links}'
                     f"<marker><name>{escape(marcador['nome'])}</name><comment>{escape(marcador['nota'])}</comment>"
                     f"<in>{inicio}</in><out>-1</out></marker>"
                     f"<labels><label2>{t.get('cor') or cor_da_nota(t['nota'])}</label2></labels></clipitem>")
        audio.append(f'<clipitem id="clipitem-a{n}">{comum}<file id="{arquivos[t["caminho"]]}"/>'
                     "<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>"
                     f"{links}</clipitem>")
        pos += dur_seq
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>', "<!DOCTYPE xmeml>", '<xmeml version="5">',
              f'<sequence id="sequence-1"><name>{escape(nome)}</name><duration>{pos}</duration>{_rate(fps_seq)}'
              f"{_timecode(round(fps_seq) * 3600, fps_seq)}",
              f"<media><video><format><samplecharacteristics>{_rate(fps_seq)}<width>{primeiro['largura']}</width>"
              f"<height>{primeiro['altura']}</height><pixelaspectratio>square</pixelaspectratio>"
              "</samplecharacteristics></format>",
              "<track>", *video, "</track></video>",
              "<audio><track>", *audio, "</track></audio></media></sequence>", "</xmeml>", ""]
    return "\n".join(linhas)

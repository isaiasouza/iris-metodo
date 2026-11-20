"""Camada de fala do motor de nota (Iris).

Junta a nota de IMAGEM do motor (selects.json) com o que é DITO (transcrição local, faster-whisper)
e decide, frase a frase: qual take fica, o que é falso começo, onde cortar respiro e pausa.
Só lê o material original. Grava tudo na mesma pasta de saída do motor.

Uso (Python do sistema, sem -I):
  /usr/bin/python3 ferramentas/fala/fala.py analise/<trabalho>
  /usr/bin/python3 ferramentas/fala/fala.py analise/<trabalho> --peso-imagem 0.4 --pausa 0.35 --min-final 0.45

Saída em analise/<trabalho>/:
  fala/<clipe>.json      transcrição por palavra (cache; não refaz se o arquivo não mudou)
  decupagem.json         todas as frases com notas e a decisão (fica / take repetido / falso começo / ...)
  decupagem.md           a mesma coisa para ler
  selects_fala.json      só o que fica, já sem respiros, no formato do motor
                         -> nota.py exportar --selects selects_fala.json --formato fcpxml|otio|aaf ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

MODELO_PADRAO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
VICIOS = {"é", "éh", "eh", "ahn", "ah", "hum", "hmm", "uhm", "ãh", "tipo", "assim", "então"}
VICIOS_FORTES = {"éh", "eh", "ahn", "ah", "hum", "hmm", "uhm", "ãh"}
FIM_FRASE = re.compile(r"[.!?…]$")


# ---------- transcrição ----------
def _chave_arquivo(caminho: str) -> str:
    st = os.stat(caminho)
    return hashlib.sha1(f"{caminho}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]


def transcrever(caminho: str, pasta: Path, modelo: str, idioma: str, _cache={}) -> list:
    pasta.mkdir(parents=True, exist_ok=True)
    chave = _chave_arquivo(caminho)
    destino = pasta / f"{Path(caminho).stem}-{chave}.json"
    if destino.exists():
        return json.loads(destino.read_text())["palavras"]
    if "m" not in _cache:
        from faster_whisper import WhisperModel
        _cache["m"] = WhisperModel(modelo, device="cpu", compute_type="int8")
    segs, _ = _cache["m"].transcribe(caminho, language=idioma, word_timestamps=True, vad_filter=True,
                                     condition_on_previous_text=False)
    palavras = [{"p": w.word.strip(), "i": round(w.start, 3), "f": round(w.end, 3), "c": round(w.probability, 3)}
                for s in segs for w in (s.words or []) if w.word.strip()]
    destino.write_text(json.dumps({"caminho": caminho, "modelo": modelo, "palavras": palavras}, ensure_ascii=False))
    return palavras


# ---------- frases ----------
def _limpa(p: str) -> str:
    p = unicodedata.normalize("NFKC", p.lower())
    return re.sub(r"[^\wáàâãéêíóôõúç-]", "", p)


def frases_de(palavras: list, pausa_frase: float) -> list:
    frases, atual = [], []
    for k, w in enumerate(palavras):
        if atual and w["i"] - atual[-1]["f"] > pausa_frase:
            frases.append(atual); atual = []
        atual.append(w)
        if FIM_FRASE.search(w["p"]):
            frases.append(atual); atual = []
    if atual:
        frases.append(atual)
    return frases


def nota_fala(ws: list, pausa: float) -> tuple[float, list]:
    motivos, toks = [], [_limpa(w["p"]) for w in ws]
    vicios = sum(t in VICIOS_FORTES for t in toks) + 0.5 * sum(t in VICIOS - VICIOS_FORTES for t in toks)
    gaguejo = sum(1 for a, b in zip(toks, toks[1:]) if a and a == b)
    pausas = sum(1 for a, b in zip(ws, ws[1:]) if b["i"] - a["f"] > pausa)
    duvida = sum(1 for w in ws if w["c"] < 0.5)
    completa = bool(FIM_FRASE.search(ws[-1]["p"]))
    n = 1.0 - 0.12 * vicios - 0.2 * gaguejo - 0.04 * pausas - 0.05 * duvida - (0 if completa else 0.15)
    if vicios: motivos.append(f"{vicios:g} vício(s)")
    if gaguejo: motivos.append(f"{gaguejo} gaguejo(s)")
    if pausas: motivos.append(f"{pausas} pausa(s) longa(s)")
    if duvida: motivos.append(f"{duvida} palavra(s) incerta(s)")
    if not completa: motivos.append("frase sem fim claro")
    return max(0.0, min(1.0, n)), motivos


def nota_imagem(caminho: str, i: float, f: float, trechos: list) -> tuple[float, list]:
    """Média da nota do motor ponderada pela sobreposição; sem sobreposição = imagem reprovada (0)."""
    soma = peso = 0.0
    flags: set = set()
    for t in trechos:
        if t["caminho"] != caminho:
            continue
        sob = min(f, t["fim_s"]) - max(i, t["inicio_s"])
        if sob > 0:
            soma += t["nota"] * sob; peso += sob; flags.update(t.get("flags") or [])
    cobertura = peso / max(f - i, 1e-6)
    return (soma / peso * min(1.0, cobertura + 0.25) if peso else 0.0), sorted(flags)


# ---------- takes repetidos e falsos começos ----------
def _norm(texto: str) -> list:
    return [t for t in (_limpa(x) for x in texto.split()) if t and t not in VICIOS]


def agrupar_takes(frases: list, sim: float) -> None:
    pai = list(range(len(frases)))

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]; x = pai[x]
        return x

    toks = [_norm(fr["texto"]) for fr in frases]
    for a in range(len(frases)):
        for b in range(a + 1, len(frases)):
            ta, tb = toks[a], toks[b]
            if len(ta) < 3 or len(tb) < 3:
                continue
            r = SequenceMatcher(None, ta, tb, autojunk=False).ratio()
            mesmo_inicio = ta[:4] == tb[:4]
            if r >= sim or (mesmo_inicio and r >= sim - 0.2):
                pai[raiz(b)] = raiz(a)
            elif len(ta) < len(tb) and tb[:len(ta)] == ta and b == a + 1:
                frases[a]["decisao"] = "falso começo"
                frases[a]["motivo_decisao"] = f"recomeça em {frases[b]['id']}"
    grupos: dict = {}
    for k in range(len(frases)):
        grupos.setdefault(raiz(k), []).append(k)
    for n, membros in enumerate(g for g in grupos.values() if len(g) > 1):
        gid = f"T{n + 1:02d}"
        # melhor nota final; empate (diferença < 0,03) fica com o take mais tarde (o editor costuma acertar no fim)
        melhor = max(membros, key=lambda k: (round(frases[k]["nota_final"] / 0.03), frases[k]["ordem"]))
        for k in membros:
            frases[k]["grupo_take"] = gid
            if k != melhor and frases[k]["decisao"] == "fica":
                frases[k]["decisao"] = "take repetido"
                frases[k]["motivo_decisao"] = f"o melhor take é {frases[melhor]['id']}"


# ---------- cortes sem respiro ----------
def pedacos(ws: list, pausa: float, respiro: float, alca: float) -> list:
    """Divide a frase nas pausas longas e devolve [(inicio, fim)], com alça curta e respiro mantido."""
    blocos, ini = [], 0
    for k in range(1, len(ws)):
        if ws[k]["i"] - ws[k - 1]["f"] > pausa:
            blocos.append((ws[ini]["i"], ws[k - 1]["f"])); ini = k
    blocos.append((ws[ini]["i"], ws[-1]["f"]))
    return [(max(0.0, a - alca), b + max(alca, respiro / 2)) for a, b in blocos]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saida", help="pasta de saída do motor (a mesma de nota.py --saida)")
    ap.add_argument("--selects", default="selects.json", help="selects do motor a cruzar")
    ap.add_argument("--modelo", default=MODELO_PADRAO)
    ap.add_argument("--idioma", default="pt")
    ap.add_argument("--peso-imagem", type=float, default=0.5, help="0 = só fala, 1 = só imagem")
    ap.add_argument("--pausa", type=float, default=0.35, help="pausa acima disso é cortada (s)")
    ap.add_argument("--respiro", type=float, default=0.12, help="respiro mantido em cada corte (s)")
    ap.add_argument("--alca", type=float, default=0.05, help="folga antes/depois da palavra (s)")
    ap.add_argument("--pausa-frase", type=float, default=0.9, help="silêncio que separa frases (s)")
    ap.add_argument("--sim", type=float, default=0.62, help="semelhança para contar como o mesmo take (0-1)")
    ap.add_argument("--min-final", type=float, default=0.4, help="frase abaixo disso sai")
    ap.add_argument("--exigir-imagem", action="store_true",
                    help="tira toda frase cuja imagem o motor reprovou (padrão: só se a fala também for fraca)")
    a = ap.parse_args()

    saida = Path(a.saida)
    sel = json.loads((saida / a.selects).read_text())
    trechos = sel.get("trechos", [])
    caminhos = list(dict.fromkeys(t["caminho"] for t in trechos))
    # inclui clipes que o motor analisou mas reprovou inteiros: a fala pode valer mesmo assim (aviso no relatório)
    for nj in sorted((saida / "nota").glob("*.nota.json")) if (saida / "nota").exists() else []:
        try:
            c = json.loads(nj.read_text()).get("caminho")
        except Exception:
            c = None
        if c and c not in caminhos and os.path.exists(c):
            caminhos.append(c)
    fps = {t["caminho"]: t.get("fps") for t in trechos}

    frases, ordem = [], 0
    for c in caminhos:
        print(f"transcrevendo {Path(c).name}…", file=sys.stderr)
        ws_all = transcrever(c, saida / "fala", a.modelo, a.idioma)
        for ws in frases_de(ws_all, a.pausa_frase):
            ordem += 1
            texto = " ".join(w["p"] for w in ws).strip()
            nf, mf = nota_fala(ws, a.pausa)
            ni, flags = nota_imagem(c, ws[0]["i"], ws[-1]["f"], trechos)
            final = a.peso_imagem * ni + (1 - a.peso_imagem) * nf
            frases.append({"id": f"F{ordem:03d}", "ordem": ordem, "caminho": c, "inicio_s": ws[0]["i"],
                           "fim_s": ws[-1]["f"], "texto": texto, "nota_imagem": round(ni, 3), "flags_imagem": flags,
                           "nota_fala": round(nf, 3), "motivos_fala": mf, "nota_final": round(final, 3),
                           "decisao": "fica", "motivo_decisao": "", "grupo_take": None, "_ws": ws})

    for fr in frases:
        if len(_norm(fr["texto"])) == 0:
            fr["decisao"], fr["motivo_decisao"] = "só vício", "nenhuma palavra de conteúdo"
        elif fr["nota_imagem"] == 0 and (a.exigir_imagem or fr["nota_fala"] < 0.8):
            fr["decisao"], fr["motivo_decisao"] = "imagem reprovada", "o motor não aprovou a imagem desse trecho"
        elif fr["nota_imagem"] == 0:
            # fala boa sobre imagem fraca: fica, mas avisa (em vídeo de fala o conteúdo manda; cobrir com B-roll)
            fr["nota_final"] = round(max(fr["nota_final"], fr["nota_fala"] * 0.7), 3)
            fr["motivo_decisao"] = "imagem fraca: cobrir com B-roll ou conferir"
    agrupar_takes(frases, a.sim)
    for fr in frases:
        if fr["decisao"] == "fica" and fr["nota_final"] < a.min_final:
            fr["decisao"], fr["motivo_decisao"] = "nota baixa", f"nota final < {a.min_final}"

    modelo_trecho = {}
    for t in trechos:
        modelo_trecho.setdefault(t["caminho"], t)
    novos = []
    for fr in frases:
        if fr["decisao"] != "fica":
            continue
        base = modelo_trecho.get(fr["caminho"], {})
        q = fps.get(fr["caminho"]) or base.get("fps") or 30
        for n, (i, f) in enumerate(pedacos(fr["_ws"], a.pausa, a.respiro, a.alca), 1):
            novos.append({**base, "id": f"{fr['id']}_{n}", "caminho": fr["caminho"], "inicio_s": round(i, 3),
                          "fim_s": round(f, 3), "duracao_s": round(f - i, 3), "fps": q,
                          "inicio_frame": int(round(i * q)), "fim_frame": int(round(f * q)),
                          "nota": fr["nota_final"], "pico": fr["nota_final"],
                          "metricas": {**(base.get("metricas") or {}), "imagem": fr["nota_imagem"], "fala": fr["nota_fala"]},
                          "flags": fr["flags_imagem"], "forcado": False, "melhor_do_clipe": False,
                          "marcador": {"nome": f"{fr['id']}_{n}",
                                       "nota": f"fala {fr['nota_fala']:.2f} · imagem {fr['nota_imagem']:.2f} · {fr['texto'][:60]}"}, "motivo": f"{fr['id']}: {fr['texto'][:80]}",
                          "texto": fr["texto"]})

    # sem sobreposição: dois pedaços do mesmo clipe nunca repetem o mesmo quadro
    novos.sort(key=lambda x: (x["caminho"], x["inicio_s"]))
    limpos = []
    for t in novos:
        ant = limpos[-1] if limpos and limpos[-1]["caminho"] == t["caminho"] else None
        if ant and t["inicio_s"] < ant["fim_s"]:
            t["inicio_s"] = ant["fim_s"]
        t["duracao_s"] = round(t["fim_s"] - t["inicio_s"], 3)
        if t["duracao_s"] >= 0.2:
            q = t["fps"]; t["inicio_frame"] = int(round(t["inicio_s"] * q)); t["fim_frame"] = int(round(t["fim_s"] * q))
            limpos.append(t)
    novos = sorted(limpos, key=lambda x: (x["caminho"], x["inicio_s"]))
    for fr in frases:
        fr.pop("_ws", None)
    agora = datetime.now().isoformat(timespec="seconds")
    (saida / "decupagem.json").write_text(json.dumps({"gerado_em": agora, "parametros": vars(a),
                                                       "frases": frases}, ensure_ascii=False, indent=1))
    (saida / "selects_fala.json").write_text(json.dumps({**{k: v for k, v in sel.items() if k != "trechos"},
                                                         "gerado_em": agora, "origem": "fala.py", "trechos": novos},
                                                        ensure_ascii=False, indent=1))
    cont: dict = {}
    for fr in frases:
        cont[fr["decisao"]] = cont.get(fr["decisao"], 0) + 1
    bruto = 0.0
    for c in caminhos:
        try:
            bruto += float(json.loads(next((saida / "nota").glob(f"{Path(c).stem}_*.nota.json")).read_text())["duracao"])
        except Exception:
            bruto += max((fr["fim_s"] for fr in frases if fr["caminho"] == c), default=0)
    fica = sum(t["duracao_s"] for t in novos)
    L = [f"# Decupagem (motor de imagem + fala) — {agora}", "",
         f"{len(frases)} frases · material {bruto:.1f} s → corte {fica:.1f} s em {len(novos)} pedaços · "
         + " · ".join(f"{k}: {v}" for k, v in cont.items()), "",
         "| id | decisão | final | imagem | fala | take | início | texto | por quê |", "|---|---|---|---|---|---|---|---|---|"]
    for fr in frases:
        por = fr["motivo_decisao"] or ", ".join(fr["motivos_fala"] + fr["flags_imagem"])
        L.append(f"| {fr['id']} | {fr['decisao']} | {fr['nota_final']:.2f} | {fr['nota_imagem']:.2f} | "
                 f"{fr['nota_fala']:.2f} | {fr['grupo_take'] or ''} | {Path(fr['caminho']).name} {fr['inicio_s']:.1f}s | "
                 f"{fr['texto'][:70].replace('|', '/')} | {por} |")
    (saida / "decupagem.md").write_text("\n".join(L) + "\n")
    print(json.dumps({"frases": len(frases), "decisoes": cont, "material_s": round(bruto, 1),
                      "corte_s": round(fica, 1), "pedacos": len(novos)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

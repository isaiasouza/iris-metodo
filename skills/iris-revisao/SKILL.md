---
name: iris-revisao
description: Controle de qualidade no método Iris — assiste o render como alguém de fora, roda as checagens técnicas (ffprobe, tela preta, integridade, loudness, frames) e de conteúdo (legenda, montagem, fim do vídeo) e devolve "OK para entrega" ou ajustes com timecode e quem corrige. Só lê, nunca edita. Use antes de toda entrega: "revisa", "tá pronto pra mandar?", "confere esse vídeo".
---

# Revisão Iris (só lê)

Tudo que gerar vai para `<pasta do vídeo>/_revisao/<nome>/`. Se conferir algo exigiria mexer no projeto, marque "não conferido".

## Técnico (todo vídeo)
- Especificação: `ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate,pix_fmt -of default=nw=1 <arq>` — contra o pedido e contra entregas já aprovadas do mesmo tipo.
- Tela preta: `ffmpeg -i <arq> -vf scale=160:-1,blackdetect=d=0.04:pix_th=0.08 -an -f null -` (fade proposital não é erro).
- Íntegro: `ffmpeg -sseof -1 -i <arq> -f null -`.
- Áudio: existe; `volumedetect`/`ebur128` — alvo −14 LUFS, ≤ −1 dBTP; silêncio onde há fala = erro.

## Conteúdo (olhe, não suponha)
- Prancha de frames (um a cada poucos segundos + meio de cada legenda/título) e **olhe as imagens**.
- Fala: transcreva o render e compare com o roteiro; procure palavra errada, frase cortada, take repetido que escapou, respiro longo (> 0,35 s), corte no meio de palavra.
- Legenda: regras do `iris-legenda`. Texto sobre rosto = sugestão.
- Fim: logo/encerramento no tempo certo, música termina junto.
- Critério de pronto da tarefa (skill `criterio-de-pronto`): item por item, com evidência.

## Relatório
**Veredito:** `OK para entrega` ou `Precisa de ajuste (N)`.
**Ajustes** (do mais grave): `[timecode] problema → o que fazer → quem (montagem, ritmo, som, legenda, cor, editor)`.
**Conferido** · **Não conferido** (nunca vazio; se viu tudo, "nada") · **Sugestões (opcional, máx. 3)**. Gosto pessoal não é ajuste. Não aprove o que não viu.

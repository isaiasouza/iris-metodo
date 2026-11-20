---
name: iris-ritmo
description: Ritmo no método Iris — corte na batida, speed ramp, transições de impacto (whip, invert shake, swish glow, halation) e pacing de reel. Planeja com frame exato a partir da música e do corte, e aplica no DaVinci (Retime, Fusion, Power Bin), no Premiere ou renderizado em código. Use para "corta na batida", "speed ramp", "põe uma transição", "deixa mais dinâmico", "o ritmo tá arrastado".
---

# Ritmo Iris

## 1. Planejar antes de aplicar
- Ache as batidas: BPM e onsets da música (`ffmpeg`/`librosa` se houver; senão marcadores na mão, tecla M no app). Para reel, use a skill `beat-sync-editing` para o plano em frames.
- Regra de pacing: **algo muda a cada 2–4 s** (corte, punch-in, gráfico, ênfase de legenda, transição). Ideia mais forte no começo só se o pedido ou a referência fizer isso.
- Corte em fronteira de palavra (vem pronto do `iris-decupagem`) e, havendo música, no frame da batida mais próxima (±2 frames).
- Entrega do plano: tabela timecode → evento → o que acontece.

## 2. Speed ramp
- Receita: 1.0 → 0.3–0.4 em ~0,3 s com ease-out logo antes do momento, segura, volta a 1.0. Velocity edit: rampa contada em batidas.
- Motion blur vende o movimento rápido (~180° de obturador).
- **DaVinci**: Cmd+R › Retime Controls › pontos de velocidade nos marcadores › Retime Curve (bezier) para suavizar. A API do Resolve **não** cria ramp: descreva os passos ou entregue o clipe renderizado.
- **Render fora do app** (quando pedirem automático): `ffmpeg` com `setpts` por trecho + `minterpolate` opcional; importe o clipe pronto como "<clipe> - RAMP".
- Extras: replay (duplicar e tocar a 0.5 logo depois), freeze no pico, rewind (trecho invertido curto).

## 3. Transições da Iris (DaVinci, nativo)
- **Invert Shake**: Adjustment Clip 4–8 frames sobre o corte; Invert Color + Camera Shake (Motion 2.0, Speed 2.0, Tilt 0.3, Zoom Outward Only); Zoom 1.28 com keyframe sobe-e-volta.
- **Swish Glow**: Adjustment 8 frames; no Fusion, Directional Blur Linear, Length 0.1 com keyframe, Angle 180→−180, Glow partindo de 0; SFX "camera flick" (`iris-som`).
- **Halation / blur de filme**: duplicar o clipe por cima, Directional Blur, opacidade ~30 %, máscara nas altas luzes.
- **Whip pan**: o motor acha whips no material (`preset whip_pans`); corte no meio do borrão.
Toda receita que funcionou vai para o **Power Bin** (DaVinci) ou vira **preset** (Premiere).

## Regras
Trabalhe numa cópia da timeline (`<nome> - RITMO`). Nada de transição em todo corte: transição pontua mudança de assunto, de lugar ou de energia.

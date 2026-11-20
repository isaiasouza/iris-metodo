---
name: iris-motion
description: Motion graphics no padrão Iris — título de ênfase, lower third, logo animado, texto cinético, número/gráfico animado, cartela de abertura e fecho, transição gráfica e call-to-action. Dois caminhos — Remotion (código, templates e lote) ou After Effects (conector higgsfield-use-after-effects) — e entrega com transparência no frame da fala para o DaVinci, Premiere ou Final Cut. Use para "faz um motion", "anima esse título", "lower third", "logo animado", "texto animado na fala", "anima esse número", "vinheta", "abertura", "cartela", "CTA animado".
---

# Motion Iris

Entra **depois da montagem e antes da legenda**, só quando o pedido tem grafismo. Não edita a timeline do Montador: entrega arquivos com alfa e o plano de onde cada um entra.

## 1. Entender
Formato (16:9 / 9:16 / 4:5), **24 fps exatos**, timeline e projeto exatos, marca (cores, fontes, logo) e referência. Board da Pré-produção em `EDICAO-IA/analise/<trabalho>/board/`, se houver. Padrão de cliente só quando o pedido é daquele cliente (nota dele no Obsidian).

## 2. Onde animar (a partir da fala)
Use a transcrição do motor (`analise/<trabalho>/fala/*.json`, palavras com tempo) e escolha os momentos:
- virada emocional, promessa, número marcante, nome de pessoa/lugar/marca, fecho e CTA;
- buracos sem legenda que o editor deixou para animar.
Ritmo: poucos e bons (≈ 2–4 por minuto), nunca dois colados (mín. ~3 s), nunca ao mesmo tempo que a legenda, nunca sobre rosto ou mão, dentro da área segura (vertical 1080×1920: x 80–940, y 220–1480).

`plano-motion.json`: peça, tipo, texto, início/fim (s e frame a 24 fps), posição, caminho. Mostre a tabela ao editor antes de construir.

## 3. Escolher o caminho
| Quando | Caminho |
|---|---|
| peça em série, template, lote, reel sem abrir app, muitos números/dados | **Remotion** |
| acabamento de AE, efeitos nativos (blur, glow, trim paths, partículas), editor vai mexer depois no .aep | **After Effects** |
Na dúvida: Remotion para a primeira versão (rápido de revisar), AE quando precisa do .aep.

### Remotion
- Projeto base: `~/Desktop/DESK/02_DESENVOLVIMENTO_TECH/IRIS REMOTION` (crie uma composição por peça em `src/`, `fps={24}`). Regras da API na skill `remotion`; princípios de tempo e easing em `motion-design`; motion de marca com storyboard em `human-motion-design`.
- Animação só por `useCurrentFrame()` + `interpolate`/`spring` — nada de CSS animation nem `setTimeout`. Fontes locais em `public/fonts/`.
- Overlay com alfa: `npx remotion render <Comp> out/<peca>.mov --codec=prores --prores-profile=4444 --pixel-format=yuva444p10le` (fundo transparente na composição). Peça cheia (abertura/fecho): H.264 `--crf=16`.
- Prévia rápida: `--scale=0.5`; still de conferência: `npx remotion still <Comp> --frame=<n>`.

### After Effects
- Conector MCP `higgsfield-use-after-effects` (`ae_do batch.run`, `ae_save_project`). O AE precisa estar aberto **pelo editor**; nunca abrir sozinho. Se o conector não responder, avise e siga pelo Remotion.
- Projeto novo `MOTION - <trabalho> vN.aep` em `analise/<trabalho>/motion/`, nunca por cima do anterior. Comp por peça, 24 fps, tamanho da timeline.
- Receitas que funcionam: revelar texto letra a letra com animator (Opacity 0 + Blur + Position Y, Range Selector com ease); contador por expressão; filete com escala X a partir da borda; desenho de traço por Trim Paths; nuvem escura desfocada atrás do texto para legibilidade (limite a camada com um retângulo invisível para o bounding box não estourar).
- Render: ProRes 4444 com alfa (Media Encoder ou fila do AE).

## 4. Estilo Iris (padrão quando não houver marca)
- Duas vozes: rótulo pequeno CAIXA-ALTA espaçado (sans) + palavra grande em serifada itálica entrando com blur→foco e leve subida.
- Entrada 0,6–1,3 s com easeOut; saída 0,4–0,6 s em fade; última peça antes do corte sai curta (0,2 s).
- Movimento sempre motivado: entra na batida (`iris-ritmo`) ou na palavra; nada de bounce gratuito.
- Legível em fundo claro e escuro (sombra suave ou nuvem).

## 5. Entregar e encaixar
- Arquivos em `analise/<trabalho>/motion/`: `.mov` ProRes 4444 por peça (+ `.aep` ou a composição Remotion) e `plano-motion.json`.
- Encaixe numa **cópia** da timeline `<nome> - MOTION`, faixa própria acima do vídeo, no frame do plano: DaVinci pelo MCP/arquivo, Premiere pelo cliente `montar-por-musica-premiere/scripts/pr.py` (overwrite no frame), Final Cut por FCPXML. Se não houver app aberto, entregue o plano para o Montador encaixar.
- A legenda (`iris-legenda`) depois marca esses trechos como **X** (sem legenda por cima).

## 6. Conferir (pronto)
- [ ] ffprobe: 24 fps, tamanho certo, canal alfa presente nos overlays.
- [ ] Frame no meio de cada peça e a cada 0,25 s na entrada: nada cortado na borda, nada sobre rosto.
- [ ] Texto, nomes e números conferidos com a fala.
- [ ] Nenhuma peça colada em outra nem em cima da legenda.
- [ ] Timeline original intocada; trabalho numa cópia.

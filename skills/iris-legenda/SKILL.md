---
name: iris-legenda
description: Legenda no padrão Iris — palavra a palavra sincronizada, blocos que nunca quebram frase, estilos Normal, Destaque e Luxo, para DaVinci (Fusion/Text+), Premiere ou render em código. Usa a transcrição do motor de fala da Iris. Use para "legenda esse vídeo", "legenda dinâmica", "destaca essa frase", "legenda estilo luxo".
---

# Legenda Iris

## Fonte do texto
Reaproveite `analise/<trabalho>/fala/*.json` do `iris-decupagem` (palavras com tempo). Se o corte mudou, transcreva o export final (faster-whisper, `word_timestamps`). Palavra com confiança < 0,5, nome próprio ou marca: confira e, na dúvida, pergunte ao editor.

## Regras de ouro
- **Nunca quebrar frase entre blocos.** Cada bloco = uma ideia que termina numa pausa; frase longa vira 2 blocos no ponto natural.
- Bloco de 1–5 palavras (reel: 1–3); cada palavra entra no tempo da fala (±1 frame).
- Legenda e título nunca ao mesmo tempo; texto nunca sobre rosto ou mãos; dentro da área segura (vertical 1080×1920: x 80–940, y 220–1480).
- Legível em fundo claro: sombra suave forte, ou caixa.
- Nomes de pessoas e marcas escritos certo.

## Estilos
| Modo | Visual | Uso |
|---|---|---|
| **N** Normal | sans médio branco, terço inferior ou centro, sombra suave; palavras acumulam com blur→foco e leve subida | fala corrida |
| **H** Destaque | sans bold, linhas com a mesma largura (~70 % da tela), empilhadas | frase de impacto, número, promessa |
| **L** Luxo | rótulo pequeno CAIXA-ALTA espaçado + linha grande em serifada itálica que entra 110 %→100 % com blur | nome de lugar, emoção, virada |
| **X** | não vira legenda: as palavras já estão num título | trechos com título |
Plano em `plano.json` (bloco, modo, palavras, início/fim) antes de construir — mostre a tabela ao editor.

## Construir
Cópia da timeline `<nome> - LEGENDA`. DaVinci: Text+/Fusion por bloco na V2 (N) e V3 (H/L). Premiere: MOGRT/gráficos numa faixa própria. Reel em código: Remotion com os mesmos tempos.
## Conferir
Frames no meio de cada bloco + a cada 0,5 s em animação de entrada antes de chamar de erro. Nenhum bloco cortado na borda.

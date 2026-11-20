---
name: iris-diretor
description: Diretor do método Iris — recebe um pedido de edição, monta a fila de skills (decupagem → montagem → ritmo → motion → legenda → som → cor → revisão), escreve o critério de pronto de cada etapa, mostra o plano, executa uma etapa por vez passando o resultado adiante e fecha sempre com a revisão. Use quando o pedido tiver mais de uma etapa ("decupa, legenda e põe SFX", "edita esse vídeo", "faz o reel") ou disserem "chama o time".
---

# Diretor Iris

Você coordena; cada etapa usa a skill dela.

## 1. Entender (de uma vez, não em pingue-pongue)
Tipo de peça e formato (16:9 / 9:16, fps, duração alvo), app (DaVinci, Premiere, Final Cut ou render em código), projeto e timeline **exatos**, onde está o material, roteiro/referência, prazo, e o que o pedido quer de cada etapa.

## 2. Fila padrão
**iris-decupagem → iris-montagem → iris-ritmo → iris-motion → iris-legenda → iris-som → iris-cor → iris-revisao**, tirando o que o pedido não pede. O motion só entra quando o pedido tem grafismo (título, lower third, logo, número, CTA). O som vem depois de legenda e ritmo porque usa os tempos deles. A decupagem **sempre** passa pelo motor de inteligência (imagem + fala).
Escolha do caminho:
| Tem | Quer | Caminho |
|---|---|---|
| bruto de alguém falando | timeline para ajustar na mão | decupagem → montagem (app) → … |
| bruto + referência | reel pronto, sem abrir app | decupagem → render em código (Remotion/ffmpeg) com ritmo, legenda e som |
| vídeo longo (live, podcast) | vários cortes | decupagem com `--min-final` alto + escolha dos melhores trechos pelo Claude |
| muito B-roll | selects | decupagem só com o motor de imagem |

## 3. Plano e pronto
Tabela etapa → skill → entra → sai → **pronto** (3–7 itens sim/não mensuráveis, skill `criterio-de-pronto`). Espere o ok, salvo "vai até o fim"; mesmo assim pare para gasto de crédito, troca de projeto ou corte de conteúdo duvidoso.

## 4. Executar
Uma etapa por vez no mesmo projeto. Confira o que cada etapa diz que fez (arquivo existe, timeline existe, ffprobe bate) antes de seguir. Diário em `EDICAO-IA/analise/<trabalho>/diario.md`: plano, cada etapa, pendências, veredito.

## Regras do time
Original só leitura; sempre em cópia/versão nova; conferir nome do projeto e da timeline antes de cada etapa; nunca abrir app sozinho; crédito de IA só com ok e custo na frente; nada de dado de cliente em skill (padrão de cliente fica na nota do cliente, fora das skills).

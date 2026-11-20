---
name: iris-decupagem
description: Decupagem e seleção de takes no método Iris — usa SEMPRE o motor de inteligência da Iris (imagem + fala) e o julgamento do Claude. Use quando pedirem "decupa", "faz os selects", "escolhe os melhores takes", "tira respiros e repetições", "qual o melhor take dessa fala", "monta o corte bruto", "separa o que presta desse material". Não usa painel nem plugin: o resultado vai para qualquer app de edição (DaVinci, Premiere, Final Cut) por FCPXML/OTIO/AAF ou pelo MCP.
---

# Decupagem Iris (motor de imagem + fala + Claude)

Três camadas, nesta ordem. Nunca pule a primeira: **toda decupagem passa pelo motor**.

1. **Imagem** (`nota.py`): nota 0–1 por trecho — foco, exposição, estabilidade, movimento, flags (blur, tremido, estourado…).
2. **Fala** (`fala.py`): transcreve local (faster-whisper large-v3-turbo, sem internet, sem crédito), divide em frases, dá nota de fala (vícios, gaguejo, pausas, palavras incertas, frase incompleta), acha **takes repetidos** e **falsos começos**, e corta pausas longas mantendo o respiro.
3. **Claude**: lê `decupagem.md`, confere as decisões duvidosas e aplica o que só um editor sabe (roteiro, ordem, emoção, o que o pedido manda tirar).

Raiz de tudo: `EDICAO=~/Desktop/DESK/02_DESENVOLVIMENTO_TECH/EDICAO-IA`, comandos com `cd "$EDICAO"` e **`/usr/bin/python3` sem `-I`** (o OpenCV e o faster-whisper estão no site-packages do usuário).

## Regras
- O original é só lido. Nunca transcodificar, mover, renomear ou apagar footage.
- Uma pasta por trabalho: `analise/<trabalho>/`, a mesma em todos os comandos.
- `analisar` e a transcrição são pesados (minutos): rode em segundo plano; os dois retomam do cache.
- Material de terceiros/pessoas: nada sobe para serviço externo. Tudo roda no Mac.

## Fluxo
```bash
cd "$EDICAO"
T=analise/<trabalho>
# 1. imagem (escolha o preset pelo tipo de material — tabela abaixo)
/usr/bin/python3 ferramentas/nota/nota.py analisar /Volumes/<disco>/<pasta> --preset talking_head --saida $T
/usr/bin/python3 ferramentas/nota/nota.py selecionar --preset talking_head --saida $T
# 2. fala (só quando há fala)
/usr/bin/python3 ferramentas/fala/fala.py $T
# 3. ler e decidir
sed -n '1,80p' $T/decupagem.md
# 4. exportar o corte para o app
/usr/bin/python3 ferramentas/nota/nota.py exportar --selects selects_fala.json --formato fcpxml --nome "CORTE v1 - <trabalho>" --ordem gravacao --saida $T
```
Sem fala (B-roll, imóvel, evento sem som útil): pare no passo 1 e exporte `selects.json`.

| Material | Preset do motor | `fala.py` |
|---|---|---|
| alguém falando para a câmera, entrevista, depoimento, podcast | `talking_head` ou `entrevista` | sim, `--peso-imagem 0.3` (a fala manda) |
| aula, palestra | `entrevista` | sim, `--peso-imagem 0.3 --pausa 0.5` |
| evento com discursos | `broll_acao` + `entrevista` só nos discursos | sim nos discursos |
| B-roll, ação, esporte | `broll_acao` / `action_sport` | não |
| imóvel, produto, tripé | `imovel` / `locked_off` | não |
| "só os melhores" | `melhores` | opcional |

## Como o Claude julga (o que o motor não sabe)
Leia `decupagem.md`. Para cada decisão:
- **take repetido**: o motor escolhe pela nota (imagem + fala) e, no empate, o **último take** (o falante costuma acertar no fim). Troque se o texto do take descartado estiver mais completo ou mais natural — e diga por quê.
- **falso começo** / **só vício**: confirme lendo o texto; sai.
- **imagem fraca: cobrir com B-roll**: a fala fica; anote onde precisa de cobertura.
- **nota baixa**: sai, a não ser que a frase seja essencial ao roteiro (então fica e vai para a lista "conferir").
- Pedido com roteiro ou ordem de beats: reordene pelos `id` das frases, não pela gravação.
- Música ou ruído transcrito como fala aparece com palavras incertas e sem sentido: marque como "não é fala".
Para mudar o critério do motor, ajuste os parâmetros e rode de novo (segundos, usa o cache): `--peso-imagem`, `--pausa`, `--respiro`, `--sim` (semelhança de take), `--min-final`, `--exigir-imagem`.

## Entrega
- `selects_fala.json` / `selects.json` exportado em FCPXML (DaVinci e Final Cut), OTIO ou AAF/XML (Premiere) — ver `iris-montagem`.
- Relatório curto: material → corte (segundos), frases que ficaram e saíram por motivo, takes trocados pelo Claude e por quê, trechos para cobrir com B-roll, o que ficou para conferir. O polimento é do editor.

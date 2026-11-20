# Método Iris — edição de vídeo com Claude

Um conjunto de skills e um motor de inteligência para editar vídeo com o **Claude + o seu app de edição** (DaVinci Resolve, Premiere Pro ou Final Cut). Criado pela Iris Media.

## O motor de inteligência
Roda no seu Mac, offline, sem crédito de IA, e explica cada decisão.
- **Imagem** (`motor/nota/`): nota 0–1 por trecho de cada clipe — foco, exposição, estabilidade, movimento — com flags (blur, tremido, estourado…), presets por tipo de material e exportação para FCPXML, OTIO, AAF e XML.
- **Fala** (`motor/fala/fala.py`): transcrição local (faster-whisper), nota de fala por frase (vícios, gaguejo, pausas, palavras incertas), **takes repetidos** (fica o melhor), **falsos começos** e corte de pausas mantendo o respiro.
- O **Claude** lê as decisões e faz o julgamento final: roteiro, ordem, emoção.

## As skills (`skills/`)
| Skill | Faz |
|---|---|
| `iris-diretor` | monta a fila de etapas e o critério de pronto |
| `iris-decupagem` | decupagem e seleção de takes: sempre motor de imagem + fala + Claude |
| `iris-motor` | roda o motor de imagem direto |
| `iris-montagem` | leva o corte para DaVinci, Premiere ou Final Cut, sem painel |
| `iris-ritmo` | corte na batida, speed ramp, transições |
| `iris-motion` | título, lower third, logo, número e CTA animados (Remotion ou After Effects), ProRes 4444 com alfa |
| `iris-som` | SFX no frame do evento e trilha |
| `iris-legenda` | legenda palavra a palavra (Normal, Destaque, Luxo) |
| `iris-cor` | correção e look |
| `iris-revisao` | controle de qualidade antes da entrega |

## Instalar
1. `pip install --user faster-whisper opencv-python numpy` e `brew install ffmpeg`.
2. Copie `motor/nota` e `motor/fala` para uma pasta sua, por exemplo `EDICAO-IA/ferramentas/`.
3. Copie as pastas `skills/iris-*` para `~/.claude/skills/`. Nas skills, troque o caminho `~/Desktop/DESK/02_DESENVOLVIMENTO_TECH/EDICAO-IA` pela sua pasta.
4. Skills de apoio usadas por algumas etapas: `beat-sync-editing`, `color-grade`, `criterio-de-pronto`, `earshot`.

## Uso rápido
```bash
cd <sua pasta EDICAO-IA>
/usr/bin/python3 ferramentas/nota/nota.py analisar /caminho/do/material --preset talking_head --saida analise/meu-video
/usr/bin/python3 ferramentas/nota/nota.py selecionar --preset talking_head --saida analise/meu-video
/usr/bin/python3 ferramentas/fala/fala.py analise/meu-video
/usr/bin/python3 ferramentas/nota/nota.py exportar --selects selects_fala.json --formato fcpxml --nome "CORTE v1" --saida analise/meu-video
```
Ou só peça ao Claude: "decupa esse material".

O material original nunca é alterado: o motor só lê.

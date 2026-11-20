# Skills Iris — o método de edição da Iris Media

Conjunto próprio de skills, tirado por engenharia reversa de tudo que a Iris já fazia (montador, sonoplasta, revisor, motor de nota, reel-editor, receitas de transição, beat-sync, legendas, color-grade, critério de pronto) e reescrito sem nada de cliente e sem painel. Funciona com **Claude + qualquer app de edição** (DaVinci Resolve, Premiere, Final Cut).

O coração é o **motor de inteligência da Iris**: `EDICAO-IA/ferramentas/nota` (imagem) + `EDICAO-IA/ferramentas/fala` (fala). Ele é offline, determinístico e explica cada decisão. O Claude lê o que o motor decidiu e faz o julgamento final (roteiro, ordem, emoção).

| Skill | Quando |
|---|---|
| `iris-diretor` | qualquer pedido com mais de uma etapa; monta a fila e o critério de pronto |
| `iris-decupagem` | **sempre** que for decupar, escolher takes ou fazer selects |
| `iris-motor` | rodar o motor de imagem direto (presets, filtros, exportar) |
| `iris-montagem` | levar o corte para o DaVinci, Premiere ou Final Cut; montar por roteiro |
| `iris-ritmo` | cortar na batida, speed ramp, transições |
| `iris-motion` | título, lower third, logo, número e CTA animados (Remotion ou After Effects), ProRes 4444 com alfa |
| `iris-som` | SFX no frame do evento e trilha |
| `iris-legenda` | legenda palavra a palavra no padrão Iris |
| `iris-cor` | look e correção de cor |
| `iris-revisao` | controle de qualidade antes de entregar |

Instalar: copiar cada pasta `iris-*` para `~/.claude/skills/`.

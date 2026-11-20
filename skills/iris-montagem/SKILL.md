---
name: iris-montagem
description: Leva o corte da Iris para o app de edição sem painel nem plugin — DaVinci Resolve, Premiere Pro ou Final Cut — por arquivo de intercâmbio (FCPXML, OTIO, XML/AAF) ou pelo MCP do app, e monta por roteiro/beats a partir dos selects do motor. Use quando pedirem "manda pro DaVinci", "monta a timeline", "monta pelo roteiro", "abre no Premiere", "corte bruto na timeline".
---

# Montagem Iris

Entrada: `analise/<trabalho>/selects_fala.json` (com fala) ou `selects.json` (só imagem), vindos de `iris-decupagem`.

## Caminho 1 — arquivo de intercâmbio (padrão, funciona em todos)
```bash
cd ~/Desktop/DESK/02_DESENVOLVIMENTO_TECH/EDICAO-IA
/usr/bin/python3 ferramentas/nota/nota.py exportar --selects selects_fala.json --formato <f> --nome "CORTE v1 - <trabalho>" --ordem gravacao --saida analise/<trabalho>
```
| App | Formato | Como abrir |
|---|---|---|
| DaVinci Resolve | `fcpxml` (ou `otio`) | File › Import › Timeline |
| Final Cut Pro | `fcpxml` | File › Import › XML |
| Premiere Pro | `fcp7` (XML) ou `aaf` | File › Import |
Diga ao editor onde está o arquivo; a mídia é ligada pelo caminho original (disco precisa estar montado).

## Caminho 2 — MCP do app (quando o app está aberto e o pedido é montar direto)
- **DaVinci (MCP `DaVinci Resolve`)**: confira status e nome do projeto/timeline ativa; **nunca** abra o Resolve sozinho. Modelo mental: *montar a partir do source com in/out*, não editar timeline existente. `append_to_timeline` com `startFrame`/`endFrame` do source e `recordFrame` absoluto (= `timeline.GetStartFrame()` + posição). Confira com `GetItemListInTrack`. A API não faz blade, trim, mover item, transição, speed ramp nem volume — isso fica para o editor ou para `iris-ritmo`.
- **Premiere (MCP `higgsfield-use-premiere`)** e **Final Cut (`fcpxml`)**: importe o arquivo do caminho 1.

## Montar por roteiro
Recebeu roteiro ou ordem de beats: leia `decupagem.md` e case cada beat com os `id` das frases. O exportador do motor só ordena por nota, duração, gravação, timecode ou nome — **não** pela ordem do roteiro. Então:
- App aberto com MCP (DaVinci): monte pelo caminho 2, trecho a trecho na ordem do roteiro, com `recordFrame` somando as durações.
- Sem MCP: exporte o corte (caminho 1) e entregue ao editor a lista de ordem (beat → `id` → timecode de origem) para reordenar no app.

## Regras
- Sempre timeline/arquivo **novo** (`CORTE vN`); nunca por cima de versão anterior.
- O que sai fica no material original: nada é apagado.
- Antes de qualquer coisa no app: nome do projeto e da timeline conferidos. Não troque de projeto sem perguntar.
- Relato: app, timeline/arquivo, duração, nº de trechos, o que a API não fez e ficou para o editor.

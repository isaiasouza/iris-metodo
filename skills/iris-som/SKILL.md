---
name: iris-som
description: Sonoplastia no método Iris — escolhe SFX (biblioteca própria, SFX Kit CC0, Openverse) e trilha, ouve antes de escolher (Earshot) e põe cada som no frame exato do evento (legenda, destaque, título, corte, logo) em faixas próprias, no DaVinci, Premiere ou num render em código. Não mexe em volume: entrega sugestão de níveis. Use para "põe SFX", "whoosh nos destaques", "pop nas legendas", "sonoriza", "acha uma trilha".
---

# Som Iris

## Eventos primeiro, som depois
Tempos vêm do que já existe — nunca adivinhe olhando: início dos blocos de legenda (`iris-legenda`), entrada de cada gráfico/motion, cortes da faixa principal, primeiro frame do logo final. Sem fonte de tempos: peça o que sonorizar.
**Antes de escolher, liste o áudio que já existe**: evento já coberto por um SFX não ganha outro.

## Escolha
- Padrão Iris: **whoosh nos destaques, pop nas legendas, hit/impacto em corte de energia, SFX junto de flash e zoom**. Som pontua informação: não sonorizar todo corte.
- Fontes, nesta ordem: biblioteca própria (índice `EDICAO-IA/sonoplasta/sfx_indice.json`, disco de SFX montado) → SFX Kit CC0 (`EDICAO-IA/sonoplasta/sfx-kit/`, respeite `avoid_for`) → Openverse (`license_type=commercial`, nunca CC BY-NC; anote créditos em `SFX/creditos.txt`) → só então sintetizado (avisar).
- Recorte só o trecho útil: pop 0,1–0,3 s, whoosh ≤ 1 s. Pico do som no frame do evento: `inicio = frame_evento − round(pico_em × fps)`.
- Ouça antes: `earshot rank "<descrição>" a.wav b.wav …` e `describe`. Em dúvida, marque "escuta pendente".
- Não repita o mesmo arquivo em eventos seguidos.
- Copie os escolhidos para `<projeto>/SFX/` e use a cópia (timeline não fica offline).

## Trilha
Arquivo do editor primeiro; senão 3 opções com motivo — baixar só com ok (pode gastar licença). Peça de marca: a música **termina junto com o logo** (use o final da faixa).

## Colocar
Faixas novas (pop/legenda, whoosh/hit, trilha), nunca a da fala, numa cópia `<nome> - SOM`. DaVinci: `AppendToTimeline` com `mediaType: 2` e `recordFrame` absoluto; confira ±1 frame. Premiere: overwrite em faixa de áudio vazia.

## Níveis (só sugestão)
Com voz: SFX ~12 dB e trilha ~25 dB abaixo da voz (LUFS de cada camada); ducking ≈ −8 dB sob a fala (ataque 150 ms, release 500 ms); master −14 LUFS, ≤ −1 dBTP. Escuta final: `earshot timeline <export>` (offset ≥ 2 frames = reposicionar).

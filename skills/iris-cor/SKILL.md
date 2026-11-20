---
name: iris-cor
description: Cor no método Iris — correção primária e look a partir de referência (still, filme ou paleta), para DaVinci, Premiere ou render em código, com diagnóstico de colorista (exposição, balanço por zona, separação, pele, textura). Use para "corrige a cor", "deixa com esse look", "iguala as câmeras", "material em log", "look de filme".
---

# Cor Iris

1. **Conhecer o material**: câmera, perfil (S-Log3, V-Log, C-Log3, Rec.709), fps. Log sempre começa pela transformação de cor certa (CST/LUT de conversão), nunca "no olho".
2. **Primária**: preto no lugar, médios, roll-off das altas; balanço de branco; igualar câmeras numa cena antes de qualquer look.
3. **Look**: com referência, use a skill `color-grade` (stills do filme, `--look`, receita salva). Diagnóstico de colorista, nesta ordem: exposição e contraste → cor por zona (sombras/médios/altas) → separação (céu, pele, verdes) → **pele humana** (salvo se o look colore pele) → textura (grain, halation, vinheta).
4. **Aplicar**: DaVinci — nodes nomeados (CST → Primária → Look → Textura), grade salvo como still/DRX para copiar; Premiere — Lumetri + LUT exportada; código — LUT .cube gerada.
5. **Conferir** com scopes (waveform, vetorscópio) e 3 frames de cenas diferentes lado a lado.

Regras: nunca sobrescrever um grade aprovado (versão nova). A cor final é decisão do editor; entregue o look com o motivo de cada ajuste.

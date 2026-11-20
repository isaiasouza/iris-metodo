---
name: iris-motor
description: Motor de nota de imagem da Iris (EDICAO-IA/ferramentas/nota) — analisa footage offline e dá nota por foco, exposição, estabilidade e movimento, gera selects, relatório com prévias e exporta para qualquer editor (FCPXML, OTIO, AAF, XML, planilha). Use para rodar o motor direto, criar preset, filtrar por câmera/flag ou vigiar uma pasta. Para decupagem completa use iris-decupagem. Não usa painel nem plugin de DaVinci.
---

# Motor de nota (imagem)

`cd ~/Desktop/DESK/02_DESENVOLVIMENTO_TECH/EDICAO-IA` e `/usr/bin/python3` (sem `-I`). Guia completo: `ferramentas/nota/COMO_USAR.md`; opções: `--help` de cada subcomando.

```bash
nota.py analisar <pastas/arquivos> --preset <p> --saida analise/<t>     # pesado, retoma do cache
nota.py selecionar --preset <p> --saida analise/<t> [--min 0.75] [--camera parada,push_in] [--excluir blur,tremido] [--max-por-clipe N] [--ordem nota|gravacao|duracao]
nota.py relatorio --saida analise/<t>                                     # selects.md + contact sheets
nota.py exportar --formato fcpxml|otio|aaf|fcp7|tabela --nome "<timeline>" --saida analise/<t> [--selects selects_fala.json] [--sem-flags] [--sem-mao]
nota.py vigiar <pasta> --preset <p> --saida analise/<t>                  # cartão chegando aos poucos
```
`selecionar` refaz em segundos: troque preset e filtros à vontade.

## Presets (`ferramentas/nota/presets/`)
`talking_head`, `entrevista`, `broll_acao`, `action_sport`, `imovel`, `locked_off`, `whip_pans`, `log_cinema` (material em log), `social_media`, `cutdown`, `cleanup` (pega os piores, para limpar), `melhores`. Preset novo: copie um JSON e mude só o necessário; material log: `"log": true`.

## Lendo `selects.json`
Cada trecho: `caminho`, `inicio_s`/`fim_s`, `nota`, `metricas`, `camera.tipo`, `flags`, `motivo`. Ao resumir: quantos trechos, duração total, faixa de notas, melhores por clipe, flags mais comuns, `avisos` e `falhas`. Página offline para o editor revisar: `open analise/<t>/selects.html`.

## Regras
Original só leitura. Tudo em `analise/<trabalho>/`. Nunca apagar marcador que o motor não criou.

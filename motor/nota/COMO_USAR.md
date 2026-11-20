# Motor de nota — como usar

Dá nota a cada trecho de cada clipe por foco, exposição, estabilidade e movimento e separa os melhores
(selects). Determinístico, offline, sem IA. Só lê o material; escreve apenas em `analise/`.

## Comandos (a partir da raiz da EDICAO-IA)

    python3 ferramentas/nota/nota.py analisar /Volumes/CARTAO/DCIM          # passo pesado, uma vez
    python3 ferramentas/nota/nota.py selecionar --preset imovel              # refaz em segundos
    python3 ferramentas/nota/nota.py selecionar --preset imovel --min 0.75 --camera parada,push_in
    python3 ferramentas/nota/nota.py relatorio                               # selects.md, selects.html, contact/
    python3 ferramentas/nota/nota.py vigiar /Volumes/CARTAO --preset imovel  # analisa o que for chegando
    python3 ferramentas/nota/nota.py exportar --formato xml --nome SELECTS    # Premiere (xml), Final Cut (fcpxml), Avid (aaf), planilha (csv)

- Rodar `analisar` de novo na mesma pasta pula o que já foi analisado (retoma de onde parou). Mudar
  `--amostras`, `--largura` ou `--sem-metricas` reanalisa.
- Velocidade: `analisar` roda 3 clipes ao mesmo tempo (`--workers`, padrão 3; no M4 Pro com HEVC 4K satura em
  3–4). `--sem-metricas escala,movimento` pula métricas que o preset não usa, mas a decodificação domina o tempo,
  então o ganho é pequeno. `analisar --preset X` usa o `amostras_por_s` do preset. O fim mostra tempo e CPU.
- Vários projetos: por padrão todos gravam em `analise/nota/`, e `selecionar`/`relatorio` sem pasta usam
  **todos** os sidecars de lá. Para um job só, passe a mesma pasta para os três comandos
  (`selecionar /Volumes/CARTAO/DCIM --preset imovel`, `relatorio /Volumes/CARTAO/DCIM`) ou dê a cada
  projeto a sua saída com `--saida analise/<projeto>` nos três comandos.
  A pasta não precisa estar montada no `selecionar`/`relatorio` (cartão já ejetado): ela vale como prefixo
  dos caminhos analisados, e o comando avisa no stderr que ela não existe.
- Pastas ocultas e os proxies da Sony (`M4ROOT/SUB`) são ignorados; o `analisar` avisa quantos arquivos
  ficaram de fora pela extensão.
- Presets: `imovel`, `entrevista`, `broll_acao`, `melhores`, `cutdown` e os equivalentes aos do
  Cutdown Pro: `talking_head` (foco e exposição, câmera parada, trechos de 3 a 60 s), `social_media` (trechos de
  1,5 a 8 s, assunto ativo, até 3 por clipe), `cleanup` (só os trechos com problema: borrado, tremido, estourado…,
  para revisar e jogar fora), `action_sport` (assunto em movimento, tremor tolerado), `locked_off` (só câmera
  parada) e `whip_pans` (pan rápido, blur de movimento aceito, 0,5 a 4 s). Todos em `ferramentas/nota/presets/`.
  Para criar um, copie um JSON, mude só o que precisa (o resto vem do padrão em `presets.py`) e use `--preset meu` ou `--preset caminho.json`.
- Material log: ponha `"log": true` no preset (alarga a faixa de brilho; veja `perfil_log` abaixo para as prévias).
- BRAW, R3D e outros formatos que o ffmpeg não lê, ou um original corrompido: o `analisar` usa o proxy sozinho
  (mesmo nome numa pasta `Proxy`, `Proxies` ou `Clip_Proxy` ao lado, ou `M4ROOT/SUB` da Sony). Os trechos
  apontam para o original; o proxy fica registrado no arquivo de análise. Pastas de proxy não entram como clipes.
  Quando o nome do proxy não bate com o do original (proxy renomeado, gerador externo), ele é casado pelo timecode
  de início e pela duração (folga de 1 quadro), lidos pelo ffprobe, entre os arquivos das mesmas pastas; com dois
  candidatos iguais, nenhum é escolhido. Original que o ffprobe não lê (BRAW) só casa pelo nome.
- **N-RAW e CinemaDNG:** `.nev` (Nikon) entra como clipe e vai direto para o proxy, como BRAW e R3D. Uma pasta com
  24 ou mais `.dng` de mesmo prefixo e numeração seguida é um clipe CinemaDNG (o caminho é a pasta) e também vai
  para o proxy; fotos `.dng` soltas não viram clipe. X-OCN (`.mxf` da Sony) entra como clipe e cai no proxy quando o
  ffmpeg não lê. Sem proxy da câmera, gere com `nota.py proxies` (abaixo).
- **Proxies pelo Resolve** (a API do Resolve não gera proxy, então ele renderiza um):

      python3 ferramentas/nota/nota.py proxies /Volumes/CARTAO --projeto "NOME"

  Com o projeto `NOME` aberto no Resolve, pega os clipes que o ffmpeg não lê e não têm proxy, importa no Media Pool,
  renderiza cada um em H.264 de 1280 px (sem áudio) em `analise/proxies/<clipe>_<código>.mov`, liga o proxy ao
  clipe e apaga a timeline e os jobs temporários. Depois, `analisar` usa esses proxies. `--todos` renderiza todos
  (para teste). O proxy sai na taxa de quadros do projeto; nada é gravado ao lado da mídia.
- **Pasta monitorada:** `vigiar <pasta> --preset X` varre a pasta a cada `--intervalo` s (padrão 5) e analisa
  cada clipe quando o tamanho fica parado por `--estavel` s (padrão 10), depois refaz selects e relatório.
  Para com Ctrl-C.
- O foco é comparado dentro de cada cena (separada nos cortes). Clipes borrados por inteiro são pegos pelo piso `foco_piso_absoluto` do preset; ele ainda precisa ser calibrado com material real.

## Controlando a seleção (sem reanalisar)

- **Flags** (no preset, em `flags`): `blur`, `blur_movimento`, `tremido`, `estourado`, `esmagado`, `pouca_luz`,
  `quadro_duplicado`. Cada uma recebe um comportamento:
  `excluir` (o quadro sai), `desfavorecer` (−0,2), `ignorar`, `preferir` (+0,1) ou `forcar`
  (o quadro entra no trecho mesmo abaixo da nota mínima; vence o `excluir` de outra flag).
- **Motion blur:** quadro borrado com a câmera rápida (> `limites.blur_movimento_camera`, fração da largura
  por segundo) ou o assunto rápido (> `limites.blur_movimento_assunto`) recebe `blur_movimento` em vez de `blur`.
  O padrão é `desfavorecer`, porque borrão num pan costuma ser aceitável.
- **Submétricas** (no preset, em `submetricas`): pesos dentro de cada métrica, peso 0 desliga a parte.
  - `exposicao`: `brilho`, `estourado`, `esmagado` (padrão 1 cada).
  - `movimento`: `assunto` (padrão 1) e `camera` (padrão 0). Com peso na câmera, a nota busca a velocidade
    `camera_vel_alvo` ± `camera_vel_tolerancia`. Ex.: câmera parada com bastante movimento do assunto =
    `{"assunto": 1, "camera": 1}`, `movimento_alvo` 0,06 e `camera_vel_alvo` 0.
- **Ajuste por clipe:** um `ajustes.json` na pasta de saída (ou `--ajustes arquivo.json`). A chave é o caminho,
  o nome do arquivo ou o nome sem extensão (maiúsculas não importam):

      {"C0261": {"excluir": true},
       "C0262": {"preset": "entrevista", "nota_min": 0.8},
       "C0300.MP4": {"duracao_max_s": 30}}

  `excluir` tira o clipe, `preset` troca a base e as outras chaves sobrescrevem o preset como num arquivo de
  preset. Chave errada dá erro com o nome do clipe; ajuste que não casa com nenhum clipe gera aviso.
- **Ordem:** `selecionar --ordem nota|duracao|gravacao` (padrão `nota`) e
  `davinci.py timeline --ordem gravacao|nota|duracao` (padrão `gravacao`).

## Preferências (submétricas bipolares, como no Cutdown Pro)

No preset, `preferencias` dá a cada submétrica um valor de -1 a 1: o sinal escolhe o polo, o tamanho é o peso,
0 desliga (padrão). Ex.: `"preferencias": {"nitidez": -0.5, "detalhe": 0.3}` prefere imagem suave mas com textura.

| Métrica | Preferência | -1 ↔ +1 |
|---|---|---|
| foco | `nitidez` | suave ↔ nítida |
| foco | `detalhe` | lisa ↔ detalhada |
| foco | `estab_foco` | foco variando (rack focus) ↔ travado |
| exposição | `folga_cor` | limitada ↔ com folga para a cor |
| exposição | `flicker` | piscando ↔ estável |
| exposição | `luma` | escura ↔ clara |
| exposição | `contraste` | chapada ↔ contrastada |
| movimento | `camera` | câmera ativa ↔ parada |
| movimento | `assunto` | assunto parado ↔ ativo |
| movimento | `estab_movimento` | errático ↔ suave |

Cada preferência ligada entra na média com a nota base da métrica: `(base + Σ|p|·x) / (1 + Σ|p|)`. A exceção são
`nitidez` e `assunto`, que espelham a base (o foco já é a nitidez; o movimento padrão já premia assunto parado):
ligada qualquer uma delas, a métrica dela passa a ser **só** a média das suas preferências ligadas, sem a base.
Assim `nitidez: -0.5` prefere de verdade a imagem suave e `assunto: 0.5` prefere de verdade o assunto ativo (com
a base na conta, elas só a anulariam). `nitidez` positiva dá a mesma nota de foco de sempre.

As preferências mudam a nota, não as flags: `blur`, `tremido` etc. são medidos nas métricas base, então um
quadro borrado continua sendo `blur` (e excluído no padrão) mesmo com `estab_foco` ou `detalhe` ligados.

`detalhe` e `folga_cor` precisam de colunas que só existem em análises feitas depois de 25/10/2026; numa análise
antiga elas ficam desligadas e o clipe ganha o aviso `sem_colunas:...`. Rodar `analisar` de novo na pasta refaz só
as análises a que falta coluna (e avisa quantas: `refazendo N análise(s) antiga(s) sem as colunas novas`).
O preset `cutdown` reproduz os ajustes do All-Rounder do Cutdown Pro, não as escolhas dele: no teste de 10
clipes, com exatamente o mesmo volume (381 s), ele concordou 53% com o Cutdown, contra 51% do `melhores`.

A câmera ganhou o tipo `rotacao` (`--camera rotacao`, `camera_comportamento`, limiar `camera.rot_min` em °/s) e cada
trecho grava `direcao` em graus (0 = direita, 90 = cima, 180 = esquerda, 270 = baixo), também como campo
`{direcao}` de marcador e relatório. Só trechos de pan e tilt têm direção; os outros tipos mostram "—". A rotação
do trecho usa a mediana do giro, então uma mão passando na frente de um plano de tripé não o vira `rotacao`.

Para escolher pela direção: `selecionar --direcao 60-120` (graus, pontas incluídas; várias faixas com vírgula, e
`350-10` dá a volta por 0°, ex.: `--direcao 350-10,170-190` para pans quase horizontais) ou `"direcao_faixas":
[[60, 120]]` no preset ou no ajuste de um clipe (`--direcao` vence o preset). Com faixas, só entram trechos de pan e
tilt com direção dentro delas; parada, zoom, mão e rotação ficam de fora, a não ser os forçados por flag.

## Saída

- **Ordem** (`--ordem` do `selecionar`, do `exportar` e do `davinci.py timeline|revisao|aprovados`): `nota`,
  `nota_asc`, `duracao`, `duracao_asc`, `gravacao` (caminho do arquivo e início) e as ordens de importação do
  Cutdown: `alfabetica` (nome do arquivo, sem a pasta), `data` (data de gravação do arquivo; sem ela, a de
  modificação) e `timecode` (timecode de origem do clipe + início do trecho). O `selecionar` grava `tc_origem_s` e
  `gravado_em` em cada trecho; em selects antigos, refaça o `selecionar` para usar `data` e `timecode`.
- **Cor dos marcadores** (no preset, em `cor_marcador`): `"exportacao"` (padrão) divide cada saída em terços pela
  nota (o terço de cima verde, o do meio amarelo, o de baixo azul; nota igual, mesma cor), como o Cutdown, então
  um material todo bom ainda separa o melhor do resto; `"fixa"` usa as faixas de nota (verde ≥ 0,8, amarelo ≥ 0,6).
  Vale para `davinci.py marcar`, OTIO e XML do Premiere, sobre os trechos que saem depois dos filtros. Selects
  feitos antes desta opção ficam nas faixas fixas.
- **Campos** (no preset, em `campos`): `marcador_nome` e `marcador_nota` são modelos com `{campo}` (padrão `{id}`
  e `{motivo}`), e `relatorio` lista colunas extras. Campos: `id`, `clipe`, `nota`, `duracao`, `camera`,
  `confianca`, `flags`, `motivo`, `foco`, `exposicao`, `estabilidade`, `movimento`, `inicio`, `fim`, `direcao`,
  `pico`, `estrela`, `estrelas`, `submetricas` e `sub_<nome>` para as 10 submétricas (`sub_nitidez`,
  `sub_detalhe`, `sub_estab_foco`, `sub_folga_cor`, `sub_flicker`, `sub_luma`, `sub_contraste`, `sub_camera`,
  `sub_assunto`, `sub_estab_movimento`). `pico` é a maior nota por amostra dentro do trecho (a nota do trecho é a
  média); `estrela` é `★` no trecho de maior nota de cada clipe; `estrelas` vai de `★☆☆☆☆` a `★★★★★` pela nota;
  `submetricas` resume as 3 mais altas e as 2 mais baixas. Selects antigos, sem submétricas, mostram "—".
  Exemplo: `"campos": {"marcador_nome": "{estrela}{id} {estrelas}", "marcador_nota": "{submetricas}"}`.
- **Export:** `exportar --formato FORMATO --nome X` grava `analise/<…>/export/X.<formato>`:
  `otio` (Resolve), `fcpxml` 1.14 (Final Cut), `xml` (FCP7, para o Premiere), `aaf` (Avid; precisa do pyaaf2:
  `python3 -m pip install --user pyaaf2`), `csv` (as colunas do relatório do Cutdown, mais estabilidade, câmera,
  confiança, flags e marcador) e `txt` (uma linha por trecho). Nos formatos de timeline os trechos ficam em
  sequência, com um marcador por trecho, e os tempos somam o timecode de início do arquivo (Sony grava a hora do
  dia). `--midia proxy` aponta para o proxy de cada clipe (avisa os que não têm) e `--midia auto` só troca o que
  o ffmpeg não decodifica (BRAW, R3D…); CSV e TXT ignoram `--midia` (o CSV traz original e proxy lado a lado).
  No CSV e no TXT, `pico` é a maior nota por amostra e pode ficar abaixo da nota do trecho, que inclui o bônus de
  duração. Aceita `--ordem`, `--min`, `--sem-flags`, `--sem-mao` e as pastas do job.
- **Página de revisão:** `relatorio` grava também `selects.html` (abre offline): gráfico nota × duração em que
  cada ponto leva ao trecho, e um cartão por trecho com prévias e as curvas de foco, brilho e estabilidade.
- **Preview de log:** `perfil_log` no preset (`null`, `"auto"`, um dos perfis `slog3`, `slog2`, `vlog`, `clog3`,
  `clog2`, `clog`, `logc3`, `logc4`, `applelog`, `bmdgen5`, `davinci`, `dlog`, `flog`, `flog2`, `protune`, `llog`,
  `nlog`, `log3g10`, `"generico"` ou `"nenhum"`) escolhe a conversão das miniaturas para Rec.709. `auto` lê o XML
  da Sony, depois as tags do arquivo e os sidecars de texto com o mesmo nome (procura o nome do perfil: "C-Log2",
  "F-Log2", "Apple Log"…), e sem nada usa a curva genérica; D-Log M (DJI) não tem fórmula pública e fica na
  genérica. Presets com `"log": true` e sem `perfil_log` valem `"auto"`; `{"log": true, "perfil_log": null}` fica
  sem curva.
  `miniatura_lut` própria no preset vence o perfil. As LUTs geradas ficam em `analise/.luts/`.
  O perfil vale para o trabalho inteiro (`perfil_log` em `ajustes.json` por clipe não muda as prévias) e as LUTs
  assumem vídeo em faixa legal (o padrão das câmeras); material gravado em faixa cheia ("data levels") sai com
  contraste errado.

## Arquivos

| Arquivo | O que é |
|---|---|
| `analise/nota/<clipe>_<hash>.nota.json` | métricas brutas por quadro (não editar) |
| `analise/nota/falhas.json` | clipes que não abriram e o motivo |
| `analise/selects.json` | trechos ranqueados — é o que o Claude lê |
| `analise/selects.md` | relatório legível com prévias |
| `analise/selects.html` | página de revisão com gráfico e curvas |
| `analise/export/*.otio`, `*.fcpxml` | timelines para outros editores |
| `analise/ajustes.json` | ajustes por clipe (opcional, escrito por você) |

## Levando para o DaVinci

`ferramentas/nota/davinci.py` faz isso pela API do Resolve. Roda com o Python do DAVINCI-MCP (é ele que
carrega a API), com o Resolve aberto no projeto certo e os clipes já importados no Media Pool:

    ../DAVINCI-MCP/venv/bin/python ferramentas/nota/davinci.py marcar analise/<projeto>/selects.json --projeto "NOME"
    ../DAVINCI-MCP/venv/bin/python ferramentas/nota/davinci.py timeline analise/<projeto>/selects.json \
        --projeto "NOME" --nome "SELECTS - <projeto>"
    # só os melhores (corte de teste longo):
    ../DAVINCI-MCP/venv/bin/python ferramentas/nota/davinci.py timeline analise/<projeto>/selects.json \
        --projeto "NOME" --nome "MELHORES - <projeto>" --min 0.98 --sem-flags --sem-mao

- `--projeto` é uma trava: se o projeto aberto no Resolve tiver outro nome, o script recusa e não mexe em nada.
- `marcar` põe um marcador de duração por trecho no clipe do Media Pool, casando pelo `File Path`:
  **Green** se `nota >= 0.8`, **Yellow** se `>= 0.6`, **Blue** abaixo. Nome = `id`, nota = `motivo`,
  custom data = `motor-de-nota`. O quadro vem de `inicio_s × FPS do clipe no Resolve` (certo também em VFR).
  Rodar de novo não duplica: quadro que já tem marcador é pulado.
- `timeline` cria uma timeline nova com os trechos na `--ordem` pedida (padrão: gravação). Se o projeto ainda não tem timeline,
  herda fps e resolução do primeiro clipe. Não sobrescreve: nome repetido é recusado.
- Os filtros `--min`, `--sem-flags` e `--sem-mao` valem para os dois comandos.
- Clipe que não está no Media Pool aparece em `clipes_nao_encontrados`; o Claude pergunta antes de importar.
- Nunca apagar marcadores que não foram criados por este procedimento (os nossos têm custom data `motor-de-nota`
  e nome no formato `<clipe>-<hash6>_<nn>`).

## IRISCUT — revisar e aprovar dentro do DaVinci

Painel do Resolve Studio (Workspace → Workflow Integrations → IRISCUT) para passar pelos selects trecho a trecho.

Instalar (pede a senha do Mac; depois reinicie o Resolve):

    ferramentas/nota/iriscut/instalar.sh

O instalador copia o painel para a pasta de plugins do Resolve, porque o Resolve 21.1.1 não lê plugin por atalho.
Por isso, sempre que o código do painel mudar, rode o instalador de novo e reinicie o Resolve.

Usar:
1. Abra o projeto no Resolve e o IRISCUT. Para analisar material novo sem terminal, use **Analisar takes**: escolha
   uma pasta ou clipes (ou "Clipes da timeline aberta", os arquivos da timeline atual do Resolve), o preset e o nome
   do trabalho (pasta em `analise/`, padrão o nome do projeto) e clique em "Analisar e montar a revisão". O painel roda
   o `analisar` e o `selecionar` do motor (local, sem internet nem IA), mostra o progresso, deixa cancelar (o que já foi
   analisado não é refeito) e no fim monta e abre a timeline REVISÃO. Com uma pasta escolhida, **Vigiar pasta** roda o
   `vigiar` (a pasta vigiada do Cutdown): cada clipe que termina de copiar para a pasta é analisado, a tela conta os
   clipes, e **Parar** refaz os selects e monta a REVISÃO. Nos dois casos, os takes que ainda não estão no projeto
   são importados no Media Pool antes de montar (só referência: o arquivo não é copiado nem alterado).
   Com uma revisão aberta, a aba **Seleção** ajusta a escolha ao vivo, como a aba Export do Cutdown: presets em
   botões, nota mínima e máxima, duração, máximo por clipe, queda tolerada, pesos, o comportamento de cada problema
   (excluir, desfavorecer, ignorar, preferir, forçar, com o tempo do material que tem cada um), tipos de câmera e o
   mostrador de direção. O gráfico nota × duração mostra os escolhidos e os descartados; o rodapé dá trechos e minutos.
   Tudo vai para `selects_painel.json` e `preset_painel.json` do trabalho (o `selects.json` não muda), e **Montar
   REVISÃO** monta a timeline com essa seleção. Ou escolha uma revisão do projeto ou um
   `selects.json` para montar a
   timeline REVISÃO. O seletor "Perfil de log das prévias" tem: Do preset (padrão, vale o perfil gravado no
   selects), Automático (lê os metadados da câmera), os 18 perfis de fabricante, Genérico e Nenhum; as outras
   opções forçam o perfil.
2. Clique num trecho (lista ou timeline de baixo) para levar o playhead até ele; dar play no Resolve faz o painel
   acompanhar. `A` aprova, `R` rejeita, `P` volta a pendente, setas andam. O item fica verde ou laranja na REVISÃO.
3. Aba Montar: "Montar APROVADOS" (ordem de gravação ou de nota) e "Marcar decisões nos clipes".

A prévia mostra o quadro de verdade do ponto onde o playhead parou (o painel pede o quadro ~0,5 s depois que o
playhead para; tocando, fica no último). O quadro vem do proxy quando ele existe (pasta `Proxy`/`SUB` da câmera),
senão do original, com o perfil de log escolhido; sai do ffmpeg direto para a memória, nada é gravado. Sem ffmpeg ou
sem o disco do material, fica a contact sheet com o selo "sem quadro". Sobreposições, nos botões do topo da prévia
ou pelas teclas: `Z` foco (bordas nítidas em vermelho), `F` falsa cor (faixas de IRE: roxo < 2, azuis até 20, verde
42–52 para pele, amarelo 78–93, laranja até 100, vermelho estourado), `H` histograma (luma e RGB) e `C` câmera
(seta na direção do movimento, tipo e confiança). Foco e falsa cor não ficam ligados juntos. O bloco "Quadro", abaixo
das curvas, mostra a nota, as 4 métricas, as submétricas e as flags da amostra sob o playhead; a curva tracejada
vermelha é a nota de cada amostra (buraco = amostra excluída por flag). Pelo terminal:

    python3 ferramentas/nota/davinci.py quadros analise/x/revisao.json --trecho C0001-ab12cd_01

As decisões ficam em `analise/<trabalho>/revisao.json` (ou `revisao_<selects>.json` quando o selects não se chama
`selects.json`) e sobrevivem a fechar o Resolve e a remontar a revisão, enquanto o trecho tiver o mesmo clipe e
intervalo. "Marcar decisões" troca o marcador do motor no mesmo quadro, atualiza o do IRISCUT se a decisão mudou e
não mexe nos seus.
Pelo terminal, os mesmos passos:

    python3 ferramentas/nota/davinci.py revisao analise/x/selects.json --projeto "NOME" [--log]
    python3 ferramentas/nota/davinci.py aprovados analise/x/revisao.json --projeto "NOME" [--ordem nota]
    python3 ferramentas/nota/davinci.py marcar-decisoes analise/x/revisao.json --projeto "NOME"

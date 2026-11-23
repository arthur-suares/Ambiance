# Aparência e componentes dos dashboards

O renderizador (`src/dashboard/renderer.py`) transforma a especificação JSON do Agente de Dashboard e os
DataFrames das consultas numa página HTML única. Ele não usa IA: todo número exibido sai dos DataFrames.

## Ver sem chave e sem banco

```bash
python scripts/preview_dashboard.py
```

Gera `outputs/dashboards/_preview_claro.html` e `_preview_escuro.html` com **dados de exemplo**
(sintéticos), usando todos os tipos de componente. Por padrão o Plotly vai embutido e a página
funciona offline; `--cdn` gera um arquivo menor que carrega o Plotly da internet.

## Página

- Barra lateral clara com âncoras para as seções e botão de tema (claro ou escuro; a escolha fica salva no
  navegador e, sem escolha, segue o sistema). Em telas estreitas vira uma barra superior.
- **Embutido no chat** (`?embed=1` ou dentro de um iframe): sem barra lateral, sem a pergunta (o chat já
  mostra), fundo transparente e altura natural. A página do chat (`web/index.html`) ajusta a altura do
  iframe ao conteúdo, então o painel não tem rolagem própria. Chat e painel usam a mesma chave de tema
  (`trase-dash-theme`): trocar num troca no outro.
- Cabeçalho sem cartão, aberto por um fio grosso: título, subtítulo em até 2 linhas e a pergunta.
- Seções automáticas, sem campo novo no JSON: `kpi`/`gauge` → Visão geral (uma fileira de indicadores,
  não uma grade de cartões); `line`/`area` → Evolução; `bar`/`progress`/`pie`/`donut`/`waterfall` →
  Rankings; `table` → Detalhamento. Seção vazia não aparece.
- **Um gráfico principal por seção:** o primeiro de linha, área, barras ou variação ocupa a largura toda;
  os demais ficam em meia largura, alinhados à grade.
- **Gráficos menores** (pizza, rosca, participações, ranking curto em meia largura): título pequeno, em
  maiúsculas e centralizado.
- Rastreabilidade: as consultas SQL de cada `[Dn]`, com botão Copiar, e as notas completas do recorte.
- Rodapé: "Dados: Trase (CC BY 4.0). Exposição ao desmatamento é uma associação estatística e não prova
  ilegalidade."
- Sem fontes, ícones ou estilos externos. O Plotly vai embutido por padrão
  (`render_dashboard_html(..., plotlyjs="inline" | "cdn")`) e é carregado uma única vez no `<head>`,
  antes de qualquer gráfico: as seções reordenam os cartões, então o primeiro gráfico do JSON nem
  sempre é o primeiro da página.

## Sistema de design

Tudo está em `PAGE_CSS` (`src/dashboard/renderer.py`), como variáveis CSS nos dois temas.

| Item | Regra |
|---|---|
| Fonte | Só as do sistema, sem recurso externo. Texto e números em sans (`ui-sans-serif, system-ui…`, números com `tabular-nums`); título do painel, das seções e dos cartões em serifa (`--serif`: Iowan Old Style, Palatino, Charter, Georgia), para o tom de relatório. |
| Marca visual | Fio ocre curto sobre a linha de cada seção; ele se estende quando a seção aparece. |
| Movimento | Uma personalidade só, suave e sem quique: cabeçalho sobe em cascata, cartões entram ao rolar, barras crescem uma a uma na ordem de leitura (rótulo depois da barra), linhas se desenham, troca de visão com fade curto. Tudo desligado com "reduzir movimento" e na impressão. |
| Tipografia | Escala 12 / 13 / 14 (texto) / 18 (título de cartão, serifa) / 20 (título de seção, serifa) / 28 (indicador) / 34 (título do painel, serifa) / 36 px (indicador principal). |
| Espaço | Múltiplos de 4 px: `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 40, `--s8` 48. |
| Cantos | 6 px em controles e tabelas, 8 px em cartões. Nada de pílulas. |
| Sombras e linhas | Sem sombras; bordas e divisórias de 1 px. |
| Cores de categoria | 5, terrosas: floresta `#3f8a5c`, petróleo `#3d8789`, terracota `#c4643f`, oliva `#7f8f36`, ameixa `#8f7a9c`. Cada uma tem contraste ≥ 3:1 no fundo claro e no escuro (os gráficos não trocam de cor com o tema). |
| Neutro | Cinza quente `#8f8a7c` para "Outros" e "não identificado". |
| Acento | Um só: ocre `#b5832a` (ponto máximo anotado, item ativo do menu, foco do teclado). |
| Texto | Contraste AA (≥ 4,5:1) em todos os fundos dos dois temas; conferido nos testes. |
| Proibido | Degradê, efeito de vidro, sombra brilhante, texto com degradê, emoji como ícone, borda colorida só na lateral, grade de cartões idênticos, cantos muito arredondados. |

**Gráficos**

- Linha reta (sem suavizar), com marcadores em círculo vazado; uma segunda série só com dados reais, com
  traço diferente (contínuo, tracejado, pontilhado), para não depender só da cor.
- Rótulo direto no fim de cada linha (nome e último valor) em vez de legenda; numa série única, o ponto
  máximo é anotado em ocre ("máx. 2017: 29,0 mil"). Com até 8 pontos, o valor aparece em cada ponto.
- Barras com valor no fim; sem moldura; grade fina só no eixo de valor.
- Marcas dos eixos no mesmo padrão do painel: "500", "2,5 mil", "15 mi", "1,5 bi".

## Componentes

| `kind` | Uso | Observações |
|---|---|---|
| `kpi` | Número de destaque | Na fileira de indicadores: ícone da medida à esquerda, rótulo pequeno, número grande (formato curto, `13,9 mi t`; o valor exato fica no `title`). Com `trend_x` e `trend_y`, uma linha cinza com a variação calculada dos dados ("+11,2% vs 2021") e uma mini-série; sem período anterior, sem variação. |
| `line` | Série temporal | Ponto final destacado; eixo a partir de zero em séries não negativas. |
| `area` | Série com preenchimento | `stacked: true` empilha categorias dentro de cada ano. Herda todas as checagens de `line`. |
| `bar` | Ranking ou comparação | Sem `sort_by`, ordena do maior para o menor; valor curto no fim de cada barra (com "%" quando a unidade é percentual). |
| `progress` | Participações (até 10) | Se a coluna for percentual ou fração, usa o valor; senão calcula sobre a soma das linhas do conjunto e avisa que não é o total geral. Herda as checagens de `bar`. |
| `table` | Detalhamento | Tabela HTML com cabeçalho fixo, números à direita e barra de dados na primeira coluna numérica. |
| `pie` (pizza) | Quanto cada parte representa do total | Até 8 fatias; "Outros" vem do SQL e fica por último, em cinza. Rótulo direto (nome e %) nas fatias com 6% ou mais; as menores vão para a legenda ao lado. Hover com valor e %. Sem "Outros", o cartão avisa "Participação entre os N itens mostrados, não sobre o total geral". Mais de 8 partes: vira barras, com aviso. Herda as regras de `bar`. |
| `donut` (rosca) | Igual à pizza, em anel | Mesmas regras da pizza. |
| `gauge` (medidor) | Um único percentual dos dados (ex.: % do volume que foi para a China) | Rosca com o % no centro, na seção Visão geral. Só aceita coluna percentual entre 0 e 100; sem meta. Herda as regras de `kpi`. |
| `waterfall` (variação por item) | O que mais pesou numa alta ou queda entre dois períodos | Cada barra é a variação do item, já calculada no SQL; a última é a variação total. Só para métricas aditivas (o revisor bloqueia percentuais e médias). Herda as regras de `bar`. |
| barras e linha | Duas medidas no mesmo período | Dois componentes (`bar` e `line`) com o mesmo `group`: ficam juntos, na largura total, com o mesmo intervalo de tempo no eixo x e cada um com a sua unidade. Nunca dois eixos com escalas diferentes. |

## Regras que continuam valendo

- A mini-série do KPI não agrega: se o mesmo período aparece em mais de uma linha, ela não é exibida
  (somar poderia juntar janelas de 5 anos ou regiões).
- `BRAZIL` em coluna de destino aparece como "BRASIL (processamento doméstico)".
- Todo texto vindo da IA passa por `html.escape`.
- Gráfico reprovado com dados vira **lista com os mesmos dados**, com uma frase simples do motivo
  ("… Mostrei os mesmos dados como lista."). O cartão de aviso fica só para quando não há dado.

## O que o leitor vê quando algo dá errado

- **Bloqueante x observação.** Só ocultam um gráfico os problemas conferidos em código: soma de janela
  de 5 anos entre anos, soma de percentuais/intensidades entre grupos (incluindo barras ou área
  empilhadas), alegação de ilegalidade e coluna inexistente. Recomendações do revisor LLM são
  observações: podem pedir mais uma tentativa ao gerador, mas nunca ocultam o gráfico.
- **Mostrar o percentual de cada grupo é permitido**; somá-los (KPI com soma, barras empilhadas) não é.
- **Sem texto interno na tela.** Cada problema tem um tipo (`WidgetIssue.code`), e a tela mostra uma frase
  fixa para esse tipo (`src/dashboard/messages.py`). O texto técnico do revisor vai só para o log.
- **Termo proibido no texto da IA:** título ou subtítulo é reescrito, o gráfico continua e o leitor vê
  "Reescrevi um texto do painel para falar apenas de exposição ao desmatamento." Textos do próprio
  revisor que citam o termo são descartados sem aviso.
- **Rótulos dos dados em português:** UNKNOWN → "não identificado", UNKNOWN CUSTOMER → "cliente não
  identificado", PROCESSED DOMESTICALLY → "consumo no Brasil"; nomes de campo que a IA escreva no texto
  ("(exporter_group)") somem.
- **Subtítulo do painel em até 2 linhas**; o texto completo fica em "Rastreabilidade → Notas do recorte".
- **"Outros" e "não identificado" sempre no fim** dos rankings, listas e tabelas, em cinza neutro, e
  nunca cortados pelo limite de itens.
- **Tabela com unidades diferentes:** cada coluna declara a sua (`column_units`), o cabeçalho mostra
  "Volume (t)" e "Participação (%)" e o selo do cartão mostra "t / %".

## Clareza para quem não é da área (Parte F)

Tudo nesta seção é calculado em código (`src/dashboard/renderer.py`, seção "Parte F") com textos fixos.
A IA não escreve nenhum número nem nenhuma destas frases.

- **Frase-conclusão** (`chart_conclusion`), logo abaixo do título de cada gráfico:
  - linha, área ou barras por ano: "Volume subiu 71,6% entre 2011 e 2022: de 8,10 mi t para 13,9 mi t.
    O pico foi em 2017 (…)". Compara dois anos e nunca soma anos. Em exposição e emissões, zero antes de
    2015 é "sem dado" e não vira ponto de partida. Com mais de um valor por ano, não há frase.
  - várias séries: "Em 2022, CERRADO teve o maior valor: …".
  - ranking, pizza, rosca: "RIO VERDE lidera com 1,63 mi t, 24,1% do total mostrado." A participação só
    aparece com um único ano e medida somável; com "Outros", diz "do total". Percentual e valor por
    tonelada recebem só "tem o maior valor: …".
  - variação por item: "Maior alta: … ; maior queda: …".
- **"?" Como ler** (`how_to_read`): uma frase fixa por tipo de gráfico e as ressalvas que valem para a
  medida, copiadas literalmente de `src/data_dictionary.CAVEATS` (`CAVEAT_FRAGMENTS`; só "NÃO" → "não"
  e "0/NULL" → "zero ou vazio"). A ressalva de 2011–2014 só aparece quando os dados mostram esses anos
  zerados ou vazios. Um teste garante que cada trecho continua existindo nas CAVEATS.
- **Rodapé de publicação**: "Fonte: … [D1] · Período: 2011–2022 · Limite: janela de 5 anos, não some
  anos; exposição ao desmatamento não é prova de ilegalidade". O período sai dos anos presentes nos
  dados. Os indicadores mostram "Fonte: … [D1] · 2011–2022".
- **Estados** (`render_status_page("loading" | "empty" | "error")`, textos em `messages.py`):
  carregando com as etapas "Entendendo o pedido → Buscando os dados → Conferindo os números → Montando
  os gráficos"; sem dados com "O que tentar"; erro sem nome técnico (o motivo fica no log e no trace).
  No chat, o erro de painel agora é sempre `ERROR_MESSAGE`. A página de carregando está pronta, mas
  ainda não é exibida pelo chat: isso exige mudar `web/index.html`, que está fora do escopo.
- **Acessibilidade**: foco visível em tudo que é clicável; cada gráfico tem `aria-label` com título e
  conclusão; "Ver dados" abre a tabela com as mesmas linhas do gráfico; movimento reduzido desliga
  animações e transições.
- **Impressão/PDF**: sempre no tema claro, sem menu, botões, "?" e "Ver dados"; cartões não quebram
  entre páginas; os números impressos são os valores finais escritos no HTML.

Prévia dos estados: `python scripts/preview_dashboard.py` também grava
`_estado_<carregando|sem_dados|erro>_<claro|escuro>.html`.

## Movimento e interação (Parte D)

Tudo em `src/dashboard/interaction.py`, sem biblioteca nova (só o Plotly embutido, funciona offline).

- **Entrada**: cartões aparecem em sequência (opacidade + subida de 8 px, 450 ms, atraso escalonado de
  70 ms) quando entram na tela. KPIs contam do zero até o valor em pt-BR (800 ms); linhas se desenham
  da esquerda para a direita (900 ms); barras crescem do zero (700 ms); fatias se abrem (750 ms);
  minigráficos e medidor se desenham (900 ms).
- **Valor final sempre no HTML**: o texto final e o `data-value` já estão na página; a animação só passa
  por números intermediários. Sem JavaScript, com "reduzir movimento" ou na impressão, tudo aparece pronto.
- **Passar o mouse**: o item em foco se destaca e os demais clareiam; a dica mostra o valor. Clique na
  legenda (onde há legenda) liga/desliga a série. Cartões sobem 2 px.
- **Controles do cartão**: "Ver como: barras · pizza · lista" quando o dado permite (a pizza só aparece se
  não enganar: um único período, medida somável, até 8 partes); as visões são montadas no servidor com as
  mesmas linhas, trocar não consulta nem recalcula. Tela cheia, baixar imagem (PNG) e baixar CSV (`;`,
  vírgula decimal, cabeçalhos como na tela, números exatos).
- **Período**: só em gráficos por ano com 3 anos ou mais. "De/até" com os anos que já estão nos dados;
  esconde pontos e linhas da tabela fora do período, nunca soma nem cria valores. A frase de conclusão
  continua valendo para o período completo, e o filtro diz isso.
- **Testes no navegador** (`tests/test_dashboard_parte_d.py`, Playwright com o Edge do sistema): números
  finais iguais aos dados, nenhum erro no console, movimento reduzido, troca de visão, filtro de período
  e celular de 390 px sem rolagem lateral. Capturas em `outputs/capturas_parte_d/`.
- **Tamanho do Plotly**: o arquivo embutido tem cerca de 4,6 MB. Um pacote parcial (barras, linhas,
  pizza) teria cerca de 1 MB, mas não vem com o Plotly para Python e não inclui a variação por item
  (waterfall); usá-lo exigiria guardar um arquivo novo no projeto. Mantido o completo.

## Polimento (Parte H)

- **Pizza e rosca**: 6 cores de categoria (floresta, petróleo, terracota, oliva, ameixa, azul-rio) mais o
  cinza de "Outros"/"não identificado", na ordem `PIE_ORDER`, para que fatias vizinhas (inclusive a última
  com a primeira) nunca tenham tons parecidos. Todo rótulo fica fora da fatia, com linha-guia, em 12 px e
  na cor do tema, inclusive o das fatias pequenas; sem legenda (ela só repetia as fatias).
- **Nomes**: empresas, municípios e importadores aparecem em formato de título ("Rio Verde", "Louis
  Dreyfus"), mantendo siglas (ADM, COFCO, LDC, UFs). Só na tela; os dados não mudam.
- **Base na conclusão**: "24,1% do volume dos 10 municípios mostrados com origem identificada, em 2022";
  com "Outros", "do volume total". Nunca só "do total".
- **Unidade uma vez só**: o selo do cartão traz a unidade e o eixo diz só a medida ("Volume"). Pizza, rosca
  e participações têm selo "%". Contagens (normas, municípios) têm marcas inteiras no eixo.

## Painéis de leis (Parte G)

- **Quando**: pedido de painel, gráfico ou tabela com termo de lei ("monte um painel das multas do Código
  Florestal") vira painel de leis (domínio `law`). Com dados do Trase na mesma mensagem, vira misto
  (dados + leis). Pergunta de lei sem pedido de painel continua em texto.
- **Agente de leis** (`src/dashboard/law_agent.py`), com fonte "Legislação — Planalto [Dn]":
  - metadados do acervo por SQL somente-leitura: normas, tipo, ano, artigos, temas (pelo título, regra
    fixa), linha do tempo por ano e matriz leis × tema;
  - fatos dos trechos recuperados pela busca existente (`src.rag.retrieve`, só importada): lei, artigo,
    tipo, valor mínimo e máximo, unidade por linha, prazo, citação literal e link.
- **Conferência em código**: a IA só extrai. A citação precisa estar, palavra por palavra, no texto do
  trecho; o valor mínimo, o valor máximo e os números do prazo precisam estar DENTRO da citação (não
  basta aparecer em outra frase do trecho), sem contar números de "art. 70", "§ 3º", inciso ou número
  de lei; e a unidade precisa ter palavra correspondente na citação (R$ pede "R$" ou "reais", % pede
  "%" ou "por cento", dias pede "dia", e assim por diante). Lei, artigo e link vêm do trecho, não da IA.
  O que não passa é descartado e o painel diz quantas informações ficaram de fora. Nada é somado entre
  leis; nenhuma multa total é calculada.
- **Visuais** (montados em código, a IA não escolhe): comparativo das normas, faixa de valores por
  artigo (do mínimo ao máximo, um gráfico por unidade, escala logarítmica quando os valores vão de
  dezenas a milhões), valores por artigo, normas por ano, leis × tema e cartões de artigo-chave com a
  citação e o link do Planalto.
- **Seção "Base legal"** separada dos dados do Trase; rodapé "Texto das normas conforme o acervo
  consolidado; confirme a vigência. Isto não é aconselhamento jurídico."
- **Regras**: toda linha com link e citação; unidade em cada linha com valor; a faixa só compara a mesma
  unidade. Texto que liga exposição ao desmatamento a infração, multa ou sanção é bloqueado.
- **Termos jurídicos (R5-e)**: o nome oficial "Lei de Crimes Ambientais" passa só em componente de leis
  legítimo e só em frase sem acusação; "crime", "ilegal" etc. em qualquer outro uso continuam bloqueados.
  Detalhes em "Segurança dos textos" abaixo.
- **Sem acervo** (Postgres desligado): o painel de leis explica em uma frase; o misto entrega os dados.
- Prévia: `_preview_leis_claro.html` e `_preview_leis_escuro.html`.

## Segurança dos textos (auditoria)

O painel nunca diz que uma empresa ou um município cometeu crime ou agiu contra a lei: os dados medem
exposição ao desmatamento, não culpa. A checagem (`find_illegality_claim` em `src/dashboard/validator.py`)
vale para o validador, para a limpeza final do orquestrador e para o monitor de saída.

- **Todos os textos que a IA escreve** são checados: título e subtítulo do painel e de cada componente,
  avisos, unidade, fonte, grupo, rótulos e unidades de coluna da tabela. O monitor de saída checa também
  os componentes que não puderam ser mostrados (o título deles aparece na tela).
  - Título e subtítulo com acusação são trocados por um texto neutro, com um aviso curto.
  - Textos curtos voltam ao padrão: rótulo de coluna vira o nome da coluna, a unidade some, a fonte
    volta a ser a do próprio dataset e o grupo é retirado.
  - O que escapar disso, o monitor de saída bloqueia.
- **Truques de escrita** não passam: caracteres invisíveis, letras de largura diferente, acentos,
  maiúsculas e letras separadas ("c r i m e", "c.r.i.m.e") são desfeitos antes da checagem.
- **Termos bloqueados**: crime (e "crimen"), criminoso, ilegal (e "ilégal"), culpado, ilícito, delito,
  infrator, infração cometida, multada, autuada, embargada, condenada, "fora da lei", clandestino,
  irregular como acusação, "violou/descumpriu/desrespeitou/burlou/infringiu a lei, a legislação ou o
  Código Florestal", "responsável pelo desmatamento", "desmatou ilegalmente", e texto que liga
  exposição ao desmatamento a infração, multa ou sanção.
- **Continua permitido**: ressalvas negadas ("exposição não é prova de ilegalidade") e a descrição neutra
  de uma lei em componente de leis ("a Lei 9.605 prevê multa de R$ 50,00 por hectare").
- **Nome oficial "Lei de Crimes Ambientais"**: só é liberado quando as duas condições valem:
  1. o componente é de leis de verdade: a fonte é "Legislação — Planalto [Dn]" E o dataset [Dn] veio do
     acervo de leis. O texto da fonte, que a IA escreve, sozinho não basta; sem os dados, nada é liberado;
  2. a frase não tem verbo ou termo de acusação ("violou", "descumpriu", "cometeu", "culpada",
     "responsável"...). "A Bunge violou a Lei de Crimes Ambientais" é bloqueado mesmo em painel de leis.
- **Países e biomas** aparecem em português na tela ("CHINA (MAINLAND)" vira "China", "THAILAND" vira
  "Tailândia", "MATA ATLANTICA" vira "Mata Atlântica"). Os dados e o CSV baixado continuam como vieram.
  Dicionário em `src/dashboard/place_names.py`.

## Por qual coluna agrupar (A4, itens 1 a 3)

- **Glossário** (`src/dashboard/dimensions.py`): "município", "municípios exportadores", "de onde vem",
  "origem" → município de origem (só origem rastreada); "exportador", "empresa", "trading", "grupo",
  "quem exporta" → grupo exportador; "porto" → porto; "destino", "país", "para onde vai" → país de
  destino; "importador" → grupo importador. Em "municípios exportadores", "exportadores" descreve o
  município. O glossário entra no prompt do planejador e do Agente de Dados.
- **Edição x painel novo**: com um painel aberto, "faz em pizza", "mostra de outro jeito" e "põe como
  lista" são edição sem nova consulta. Se a mensagem cita entidade, dimensão, filtro, ano ou cadeia,
  é painel novo. Se pede uma dimensão que o painel não usa, é painel novo com dados novos; o Result Store
  nunca é reaproveitado quando os dados guardados não têm a coluna pedida.
- **Revisor**: o plano guarda a dimensão pedida; se nenhum gráfico agrupa por ela (apelidos do SQL
  contam), devolve para refazer. Se ainda não bater, o painel diz "Não consegui montar por município;
  mostrei por empresa." Por município, o subtítulo diz "Município de origem da soja exportada; cobre só
  a origem rastreada."

## Mesma base em todo o painel (adendo A4)

- O planejador define uma base comum (`common_base`: ano, origem rastreada ou todas, só exportação
  ou cadeia inteira) e o Agente de Dados recebe a ordem de usar essa base em todas as consultas.
- O código lê a base de cada conjunto de dados (`src/dashboard/data_base.py`): anos presentes na tabela
  ou filtrados na consulta, `<> 'UNKNOWN'` (origem rastreada), `<> 'BRAZIL'` / consumo doméstico
  (só exportação). A IA não escreve a base.
- O revisor avisa (`base_diferente`, sem reprovar) quando KPIs, pizza, ranking ou tabela usam bases
  diferentes. Uma série de vários anos ao lado de um recorte de um ano não conta como base diferente.
- Nesse caso, cada widget recebe no subtítulo a frase da base usada, por exemplo
  "Base: exportações com origem rastreada de 2022."
- O selo de pizza e rosca é sempre "%"; a quantidade (t) aparece ao passar o mouse.

## Como o pedido vira gráfico

Quem usa o chat não precisa saber o nome dos gráficos. `src/dashboard/chart_intent.py` lê a frase e
escolhe o formato:

1. **Dicionário** de expressões do dia a dia, sem diferenciar acentos e aceitando erros de digitação:
   "pizza", "piza", "torta", "uma bolinha mostrando quanto cada um representa", "proporção" → pizza;
   "rosquinha", "anel" → rosca; "barras", "colunas", "os maiores", "quem mais", "ranking" → barras;
   "evolução", "ao longo dos anos", "como mudou", "subiu ou caiu" → linha; "composição ao longo do tempo",
   "empilhado" → área empilhada; "tabela", "como lista", "números exatos" → lista; "medidor",
   "quanto % foi para" → medidor; "o que mais pesou na queda" → variação por item; "barras e linha juntas"
   → dois gráficos alinhados no mesmo eixo de tempo.
   Nome de formato vence descrição ("barras com a evolução" → barras). Entre nomes, vale o último
   ("troque as barras por linha" → linha).
2. Se o dicionário não resolver, **uma chamada curta à IA** só para classificar o formato. Se ela falhar,
   o gerador escolhe pela intenção: participação → pizza; "maiores" → barras horizontais ordenadas;
   evolução → linha; composição no tempo → área empilhada; detalhe → lista.

O formato entendido fica no plano (`OrchestratorPlan.requested_chart`) e segue para o planejador, o
Agente de Dados, o gerador e o revisor, que confere se o pedido foi atendido.

- **Nunca recusa.** Formato que ainda não existe vira o mais próximo, com um aviso de uma frase
  ("Ainda não faço mapa, então mostrei em barras."). Quando o tipo passa a existir em
  `ALLOWED_WIDGET_KINDS`, o aviso some sozinho.
- **Não engana.** Pizza de série de anos vira linha; pizza de percentuais, médias, intensidades,
  exposição de 5 anos somada entre anos ou com valores negativos vira barras. Cada troca gera um aviso.
- **"Outros" vem do SQL.** Em participação, o Agente de Dados devolve até 7 itens e uma linha "Outros"
  calculada na consulta (total menos os maiores). Sem total disponível, o texto diz "participação entre
  os N maiores".
- **Sem jargão na tela:** pizza, rosca, barras, linha, lista, medidor. Os nomes técnicos ficam no código.
- **Edição em linguagem simples** com o painel aberto: "faz em pizza", "quero ver em linha", "põe como
  lista", "mostra de outro jeito" trocam o formato, reaproveitando os dados.
- No fim da resposta, uma sugestão: "Quer ver em pizza ou como lista? É só pedir."
- "Tabela" e "lista" sozinhas, sem "gráfico"/"painel", continuam indo para a resposta em texto.

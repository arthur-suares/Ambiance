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

- Barra lateral com âncoras para as seções e botão de tema (claro ou escuro; a escolha fica salva no
  navegador e, sem escolha, segue o sistema). Em telas estreitas vira uma barra superior.
- Seções automáticas, sem campo novo no JSON: `kpi` → Visão geral; `line`/`area` → Evolução;
  `bar`/`progress` → Rankings; `table` → Detalhamento. Seção vazia não aparece.
- Rastreabilidade: as consultas SQL de cada `[Dn]`, com botão Copiar.
- Rodapé: "Dados: Trase (CC BY 4.0). Exposição ao desmatamento é uma associação estatística e não prova
  ilegalidade."
- Sem fontes, ícones ou estilos externos. O Plotly vai embutido por padrão
  (`render_dashboard_html(..., plotlyjs="inline" | "cdn")`) e é carregado uma única vez no `<head>`,
  antes de qualquer gráfico: as seções reordenam os cartões, então o primeiro gráfico do JSON nem
  sempre é o primeiro da página.

## Componentes

| `kind` | Uso | Observações |
|---|---|---|
| `kpi` | Número de destaque | Formato curto (`13,9 mi t`, `US$ 6,07 bi`, `21,7 mil ha`); o valor exato fica no `title` do número. Com `trend_x` e `trend_y`, mostra a variação em relação ao período anterior e uma mini-série, calculadas em código. Setas neutras, sem cor de "bom" ou "ruim". |
| `line` | Série temporal | Ponto final destacado; eixo a partir de zero em séries não negativas. |
| `area` | Série com preenchimento | `stacked: true` empilha categorias dentro de cada ano. Herda todas as checagens de `line`. |
| `bar` | Ranking ou comparação | Sem `sort_by`, ordena do maior para o menor; rótulos curtos nas barras. |
| `progress` | Participações (até 10) | Se a coluna for percentual ou fração, usa o valor; senão calcula sobre a soma das linhas do conjunto e avisa que não é o total geral. Herda as checagens de `bar`. |
| `table` | Detalhamento | Tabela HTML com cabeçalho fixo, números à direita e barra de dados na primeira coluna numérica. |

## Regras que continuam valendo

- A mini-série do KPI não agrega: se o mesmo período aparece em mais de uma linha, ela não é exibida
  (somar poderia juntar janelas de 5 anos ou regiões).
- `BRAZIL` em coluna de destino aparece como "BRASIL (processamento doméstico)".
- Todo texto vindo da IA passa por `html.escape`.
- Componente inválido vira cartão de aviso; o resto do painel continua.

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

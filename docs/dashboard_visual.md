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
- Sem fontes, ícones ou estilos externos. A única dependência externa é o Plotly
  (`render_dashboard_html(..., plotlyjs="cdn" | "inline")`).

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

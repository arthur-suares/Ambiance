"""Agente de dashboard (3): escolhe tipos de gráfico, monta layout em JSON e renderiza com Plotly.

Tipos suportados nesta etapa: `kpi`, `bar`, `line` e `table`.
O LLM devolve apenas uma especificação JSON declarativa (`DashboardSpec`), sem qualquer
código Python, HTML ou JavaScript; o módulo `renderer.py` transforma a especificação
e os DataFrames em um dashboard HTML interativo com Plotly.
"""

from __future__ import annotations

import json

from src.dashboard._llm import call_structured_llm
from src.dashboard.chart_intent import CHOICE_BY_INTENT, kinds_for_prompt
from src.dashboard.renderer import render_dashboard_html
from src.dashboard.schemas import (
    ALLOWED_KPI_AGGS,
    ALLOWED_WIDGET_KINDS,
    DashboardSpec,
    DatasetResult,
    MAX_ROWS_TO_LLM,
    OrchestratorPlan,
    ReviewResult,
    format_dataset_for_llm,
    parse_dashboard_spec,
)

DASHBOARD_SYSTEM_PROMPT = """\
Você é o Agente de Dashboard dedicado do sistema Trase RAG.
Você recebe DataFrames já extraídos do DuckDB ([D1], [D2]...) e projeta um dashboard analítico \
interativo em português por meio de uma especificação JSON declarativa.

Tipos de componentes permitidos (`kind`), e só estes (sem mapas):
{kinds}
{choice_by_intent}
Se a mensagem trouxer "Tipo de gráfico pedido pelo usuário", o componente principal DEVE usar esse `kind`; os demais componentes complementam. Nunca recuse um pedido por causa do tipo de gráfico.
Nos textos da tela (títulos, subtítulos, rótulos), use palavras do dia a dia ("pizza", "rosca", "barras", "linha", "lista", "medidor"), nunca os nomes técnicos (donut, gauge, waterfall, combo).

Estrutura mínima obrigatória de um painel executivo (siga sempre que os datasets permitirem):
- FAIXA DE KPIs NO TOPO: crie de 3 a 6 componentes `kpi` (nunca 0 KPIs). Derive KPIs úteis dos datasets disponíveis (ex.: total de exposição ou volume no ano, líder do ranking com `agg="max"`, contagem de municípios/destinos com `agg="count"`, participação do principal destino ou valor médio, respeitando sempre a regra de não somar exposição de 5 anos entre anos nem somar `%`). Sempre que houver dataset com vários anos para a métrica, informe `trend_x` (ex.: `"year"`) e `trend_y` para mostrar variação contra o período anterior e mini-linha.
- VARIEDADE DE GRÁFICOS: inclua pelo menos 3 gráficos de tipos diferentes quando os datasets permitirem, combinando:
  * ranking em barras horizontais (`kind="bar"`, `orientation="h"`);
  * participação em rosca (`kind="donut"`, até 8 fatias);
  * lista de top destinos/itens com barras de progresso (`kind="progress"`, até 10 linhas);
  * evolução no tempo (`kind="line"` ou `kind="area"`, `span=2`) ou segunda comparação (`kind="bar"`).
- TABELAS: NÃO coloque widgets `table` no corpo principal — cada gráfico já inclui automaticamente uma tabela recolhida "Ver dados". Só inclua `table` se o usuário pedir explicitamente uma tabela (e nunca coloque mais tabelas do que gráficos).
- DISPOSIÇÃO (`span`): use `span=2` para séries temporais; use `span=1` em rankings horizontais, roscas e listas de progresso para formar pares lado a lado na grade de 2 colunas.

Quando usar cada tipo:
- `kpi`: indicadores-chave de destaque no topo (informe `dataset_id`, `column`, `agg` entre \
first/last/sum/mean/max/min/count e `value` numérico exato calculado a partir do dataset; use `agg="last"` para pegar o último ano de uma série ordenada por ano crescente).
- `line`: evolução temporal por ano (`x="year"`, `y=["coluna_numerica"]`, opcional `color`).
- `bar`: rankings e comparações entre categorias (`x="coluna_categoria"`, `y=["coluna_numerica"]`, \
use `orientation="h"` quando os nomes de municípios/empresas forem longos).
- `area`: como `line`, com preenchimento; use `stacked=true` só para somar regiões/categorias \
aditivas DENTRO de cada ano (nunca percentuais ou intensidades).
- `progress`: lista de participações (ex.: % do volume por destino), com `x` = categoria e \
`y` = [coluna]; até 10 linhas. Se a coluna já for percentual ou fração, ela é usada como está; \
senão o percentual é calculado sobre o total do dataset.
- `table`: tabela detalhada com as colunas relevantes e rótulos amigáveis em `column_labels`. Quando as colunas tiverem unidades diferentes (ex.: toneladas e %), informe a unidade DE CADA COLUNA em `column_units` (ex.: {{"volume_t": "t", "share_pct": "%"}}); `unit` pode resumir ("t / %").
- `pie`/`donut`: `x` = categoria, `y` = [valor aditivo de um único período]; no máximo 8 linhas, com "Outros" vindo da consulta. Nunca para anos, percentuais, médias, intensidades ou valores negativos.
- `gauge`: como `kpi` (`column`, `agg`, `value`), mas só para UM percentual calculado dos dados (0 a 100, `unit="%"`), ex.: "% do volume exportado para a China". Sem meta.
- `waterfall`: `x` = item, `y` = [variação do item entre dois períodos, já calculada no SQL]; só para métricas aditivas (volume, FOB, exposição de um mesmo par de anos).
- Barras e linha juntas: DOIS componentes (`bar` e `line`) com o mesmo `x` de tempo e o mesmo `group`, cada um com a sua unidade. Nunca dois eixos com escalas diferentes.
- Em `kpi`, opcionalmente informe `trend_x` (ex.: "year") e `trend_y` (coluna numérica) de um \
dataset com vários anos: a variação e a mini-série são calculadas em código. Não informe valores.

Regras obrigatórias de qualidade e citação:
1. Todo componente DEVE ter `title` claro (com recorte e ano/período), `unit` explícita \
(ex.: "ha", "t", "US$", "tCO2e", "%", "ha/t") e `source` citando explicitamente "Trase" e o \
dataset de origem (ex.: "Trase — Carne bovina v2.2.2 [D1]" ou "Trase — Soja [D2]").
2. Use exclusivamente nomes de colunas que existam no `dataset_id` referenciado.
3. Em KPIs, o campo `value` deve bater exatamente com o valor do SQL (`column` + `agg`).
4. NUNCA some exposição ao desmatamento ou emissões de janela de 5 anos entre anos diferentes \
(ex.: nunca use `agg="sum"` num dataset de vários anos para exposição).
5. NUNCA some percentuais (`%`) ou intensidades (`ha/t`, `t/ha`) entre regiões.
6. Em rankings municipais da `supply_chain`, indique no `subtitle` que se trata da origem rastreada \
(excluindo 'UNKNOWN'). Os dados do Trase medem só exposição ao desmatamento associada à cadeia. \
Em `title`, `subtitle` e qualquer texto do painel, NUNCA use as palavras "ilegal", "ilegalidade", \
"crime", "criminoso", "culpado", "violou a lei" nem "responsável pelo desmatamento" (ou "autor do \
desmatamento"), NEM MESMO para negá-las (ex.: proibido "não indica ilegalidade" ou "não é crime"); \
o rodapé do painel já traz essa ressalva. Escreva sempre "exposição ao desmatamento" \
(ex.: "Municípios com maior exposição ao desmatamento", nunca "maiores responsáveis pelo desmatamento").
7. Não combine várias colunas em `y` com `color` ao mesmo tempo no mesmo gráfico.
8. Escreva sempre "Brasil" (nunca "Brazil") em títulos, subtítulos e rótulos.
9. Em destinos da soja, o valor BRAZIL de `country_of_first_import` é soja processada no próprio \
Brasil (consumo doméstico), não é exportação. Se um gráfico ou tabela de destinos o incluir, diga no \
`subtitle` que "Brasil = processamento doméstico". KPIs que contam países de destino devem excluir BRAZIL, \
e o título deve dizer "(exceto Brasil)".
10. `importer` e `importer_group` são os compradores: chame de "importadores" ou "grupos importadores", \
nunca de "tradings". "Exportadoras" e "tradings" valem só para `exporter` e `exporter_group`.
11. Não repita a unidade no rótulo do eixo: se `unit` já traz a unidade, o rótulo em `column_labels` \
não deve conter "(t)", "(ha)" etc.
12. Títulos, subtítulos e rótulos são para leigos: NUNCA escreva nomes de colunas, tabelas ou campos (ex.: exporter_group, share_pct, supply_chain), nem rótulos crus dos dados (UNKNOWN, PROCESSED DOMESTICALLY); diga "grupo exportador", "participação", "origem não identificada", "consumo no Brasil". O subtítulo do painel tem no máximo 2 frases curtas.
""".format(kinds=kinds_for_prompt(), choice_by_intent=CHOICE_BY_INTENT)

WIDGET_ITEM_SCHEMA = {
    "type": "object",
    "required": ["id", "kind", "title", "dataset_id", "unit", "source"],
    "properties": {
        "id": {"type": "string", "description": "Identificador único do componente (ex.: kpi1, w1, w2)."},
        "kind": {"type": "string", "enum": list(ALLOWED_WIDGET_KINDS)},
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "dataset_id": {"type": "string", "description": "ID do dataset (ex.: D1, D2)."},
        "unit": {"type": "string", "description": "Unidade (ex.: ha, t, US$, tCO2e, %, ha/t, múltiplas)."},
        "source": {"type": "string", "description": "Deve citar 'Trase' e o ID [Dn]."},
        "span": {"type": "integer", "enum": [1, 2], "description": "1 = meia largura, 2 = largura total."},
        "column": {"type": "string", "description": "Para kpi e gauge: coluna numérica no dataset."},
        "agg": {"type": "string", "enum": list(ALLOWED_KPI_AGGS), "description": "Apenas para kpi."},
        "value": {"type": "number", "description": "Apenas para kpi: valor numérico exato esperado do SQL."},
        "x": {"type": "string", "description": "Para bar/line/area/progress: coluna de categoria ou tempo."},
        "y": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Para bar/line/area/progress: uma ou mais colunas numéricas.",
        },
        "color": {"type": "string", "description": "Opcional para bar/line com uma única coluna em y."},
        "orientation": {"type": "string", "enum": ["v", "h"], "description": "Para bar: v ou h."},
        "barmode": {"type": "string", "enum": ["group", "stack"]},
        "markers": {"type": "boolean"},
        "stacked": {"type": "boolean", "description": "Para area: empilha as séries (só métricas aditivas)."},
        "trend_x": {"type": "string", "description": "Opcional para kpi: coluna de tempo da mini-série."},
        "trend_y": {"type": "string", "description": "Opcional para kpi: coluna numérica da mini-série."},
        "columns": {"type": "array", "items": {"type": "string"}, "description": "Para table: colunas exibidas."},
        "column_labels": {"type": "object", "description": "Mapeamento opcional coluna -> rótulo legível."},
        "column_units": {"type": "object", "description": "Para table: unidade de cada coluna (coluna -> unidade)."},
        "sort_by": {"type": "string"},
        "ascending": {"type": "boolean"},
        "top_n": {"type": "integer", "minimum": 1, "maximum": 200},
        "group": {"type": "string", "description": "Mesmo valor em dois gráficos (barras e linha) que devem "
                                                   "ficar juntos e alinhados no mesmo eixo de tempo."},
    },
}

DASHBOARD_SPEC_SCHEMA = {
    "type": "object",
    "required": ["title", "subtitle", "widgets"],
    "properties": {
        "title": {"type": "string", "description": "Título principal do dashboard."},
        "subtitle": {"type": "string", "description": "Resumo do escopo, período e cuidados de leitura."},
        "widgets": {
            "type": "array",
            "minItems": 1,
            "items": WIDGET_ITEM_SCHEMA,
        },
    },
}


def _chart_line(plan) -> str:
    chart = getattr(plan, "requested_chart", None)
    return f"{chart.prompt_line()}\n" if chart is not None else ""


def _datasets_context(datasets: list[DatasetResult]) -> str:
    return "\n".join(format_dataset_for_llm(d, max_rows=MAX_ROWS_TO_LLM) for d in datasets)


def _chat_context_block(chat_context: dict | None) -> str:
    if not chat_context:
        return ""
    from src.dashboard.chat_context import format_chat_context_prompt
    block = format_chat_context_prompt(chat_context)
    return f"\n{block}\n" if block else ""


def propose_dashboard_spec(
    question: str,
    plan: OrchestratorPlan,
    datasets: list[DatasetResult],
    *,
    chat_context: dict | None = None,
) -> tuple[DashboardSpec, int, int]:
    """Gera a especificação JSON inicial do dashboard a partir dos DataFrames."""
    reqs = "\n".join(
        f"- [{r.request_id}] visual sugerido={r.suggested_visual}: {r.description}"
        for r in plan.data_requests
    )
    ctx_part = _chat_context_block(chat_context)
    user_msg = (
        f"Pergunta do usuário: {question}\n"
        f"Objetivo do painel: {plan.dashboard_goal}\n"
        f"{_chart_line(plan)}"
        f"Sugestões do Orquestrador:\n{reqs}\n"
        f"{ctx_part}\n"
        f"Datasets disponíveis (truncados em {MAX_ROWS_TO_LLM} linhas):\n"
        f"{_datasets_context(datasets)}"
    )
    payload, in_tok, out_tok = call_structured_llm(
        system=DASHBOARD_SYSTEM_PROMPT,
        user_content=user_msg,
        tool_name="emit_dashboard_spec",
        tool_description="Devolve a especificação JSON completa do dashboard.",
        input_schema=DASHBOARD_SPEC_SCHEMA,
        max_tokens=4096,
    )
    return parse_dashboard_spec(payload), in_tok, out_tok


def revise_dashboard_spec(
    question: str,
    plan: OrchestratorPlan,
    datasets: list[DatasetResult],
    previous_spec: DashboardSpec,
    review: ReviewResult,
    *,
    chat_context: dict | None = None,
) -> tuple[DashboardSpec, int, int]:
    """Corrige a especificação JSON do dashboard com base nos apontamentos do Agente Revisor."""
    issues_txt = "\n".join(
        f"- [{i.widget_id or 'GERAL'}] ({i.check_type}): {i.message}"
        for i in review.issues
    )
    prev_json = json.dumps(previous_spec.to_dict(), ensure_ascii=False, indent=2)
    ctx_part = _chat_context_block(chat_context)
    user_msg = (
        f"Pergunta do usuário: {question}\n"
        f"Objetivo do painel: {plan.dashboard_goal}\n"
        f"{_chart_line(plan)}"
        f"{ctx_part}\n"
        f"Datasets disponíveis (truncados em {MAX_ROWS_TO_LLM} linhas):\n"
        f"{_datasets_context(datasets)}\n"
        f"Especificação JSON anterior:\n{prev_json}\n\n"
        f"Problemas apontados pelo Agente Revisor (corrija TODOS mantendo os gráficos válidos):\n"
        f"{issues_txt}"
    )
    payload, in_tok, out_tok = call_structured_llm(
        system=DASHBOARD_SYSTEM_PROMPT,
        user_content=user_msg,
        tool_name="emit_dashboard_spec",
        tool_description="Devolve a especificação JSON corrigida do dashboard.",
        input_schema=DASHBOARD_SPEC_SCHEMA,
        max_tokens=4096,
    )
    return parse_dashboard_spec(payload), in_tok, out_tok


def edit_dashboard_spec(
    request: str,
    current_spec: DashboardSpec,
    datasets: list[DatasetResult],
    plan_or_goal: OrchestratorPlan | str | None = None,
) -> tuple[DashboardSpec, int, int]:
    """Altera incrementalmente a especificação atual do painel em 1 chamada estruturada (R4)."""
    if isinstance(plan_or_goal, OrchestratorPlan):
        goal = plan_or_goal.dashboard_goal
    elif isinstance(plan_or_goal, str) and plan_or_goal.strip():
        goal = plan_or_goal.strip()
    else:
        goal = current_spec.title or request

    current_json = json.dumps(current_spec.to_dict(), ensure_ascii=False, indent=2)
    user_msg = (
        f"Pedido de edição do usuário: {request}\n"
        f"Contexto/objetivo do painel: {goal}\n"
        f"{_chart_line(plan_or_goal)}\n"
        f"Especificação JSON atual do painel (PRESERVE os `id` e configurações dos componentes "
        f"que não foram alvo da alteração):\n{current_json}\n\n"
        f"Datasets disponíveis (truncados em {MAX_ROWS_TO_LLM} linhas):\n"
        f"{_datasets_context(datasets)}\n"
        "Aplique exatamente a alteração solicitada mantendo intactos os demais componentes válidos."
    )
    payload, in_tok, out_tok = call_structured_llm(
        system=DASHBOARD_SYSTEM_PROMPT,
        user_content=user_msg,
        tool_name="emit_dashboard_spec",
        tool_description="Devolve a especificação JSON atualizada do dashboard após aplicar a edição pedida.",
        input_schema=DASHBOARD_SPEC_SCHEMA,
        max_tokens=4096,
    )
    return parse_dashboard_spec(payload), in_tok, out_tok


def build_dashboard_html(
    spec: DashboardSpec,
    datasets: list[DatasetResult],
    *,
    question: str = "",
) -> str:
    """Renderiza a especificação JSON em HTML interativo com Plotly."""
    return render_dashboard_html(spec, datasets, question=question)

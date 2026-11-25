"""Agente revisor (4): valida números, metadados obrigatórios e metodologia do Trase.

Em duas etapas, nesta ordem:
1. Checagens determinísticas em código Python (`check_deterministic`):
   - título do dashboard e de cada gráfico presentes;
   - unidade e fonte presentes em cada gráfico, com menção a "Trase" e ao dataset `[Dn]`;
   - tipo de gráfico permitido (`kpi`, `bar`, `line`, `table`);
   - dataset existe e não está vazio; colunas mapeadas existem (e colunas de valor são numéricas);
   - em KPIs, o `value` informado pelo Agente de Dashboard bate com o cálculo exato no DataFrame SQL.
2. Revisão metodológica via LLM (`check_methodological_llm`):
   - executada APENAS quando todas as checagens determinísticas passam;
   - confere regras do Trase (não somar exposição/emissões de 5 anos entre anos, não somar `%` ou
     intensidades entre regiões, coerência semântica entre coluna/unidade/título, não afirmar ilegalidade).
"""

from __future__ import annotations

import json
import math

import pandas as pd

from dataclasses import replace as _replace

from src.dashboard._llm import call_structured_llm
from src.dashboard.schemas import BASE_KIND
from src.dashboard.schemas import (
    ALLOWED_KPI_AGGS,
    ALLOWED_WIDGET_KINDS,
    LAW_WIDGET_KINDS,
    LAWS_DATABASE,
    LAWS_SOURCE,
    WIDGET_KINDS,
    DashboardSpec,
    DatasetResult,
    MAX_ROWS_TO_LLM,
    ReviewResult,
    WidgetIssue,
    WidgetSpec,
    compute_kpi_value,
    format_dataset_for_llm,
)
from src.dashboard.data_base import check_common_base
from src.dashboard.messages import log_issues
from src.dashboard.validator import (
    is_non_additive_column_or_unit,
    is_percentage_column_or_unit,
    validate_spec_methodological,
    validate_widget_methodological,
)

KPI_REL_TOL = 0.01
KPI_ABS_TOL = 0.05

REVIEWER_SYSTEM_PROMPT = """\
Você é o Agente Revisor metodológico de dashboards do Trase.
As checagens estruturais e aritméticas (existência de colunas, correspondência numérica dos KPIs, \
presença de título, unidade e fonte Trase) JÁ foram verificadas em código.

Sua tarefa exclusiva é auditar a CORREÇÃO METODOLÓGICA e SEMÂNTICA de cada componente:
1. Janela de 5 anos: exposição ao desmatamento (`deforestation_exposure_ha`, `exposure_ha`, \
`soy_deforestation_5y_ha`, `cattle_deforestation_ha`) e emissões associadas NUNCA podem ser somadas \
entre anos diferentes (ex.: `agg="sum"` num dataset com vários anos, ou gráfico `bar` agrupando sem \
filtrar um único ano quando o dataset tem vários anos). Séries anuais em `line` ou média/ano único são válidos.
2. Métricas não aditivas: percentuais (`%`) e intensidades (`ha/t`, `t/ha`, `tCO2e/t`) NÃO podem ser \
somados (`agg="sum"`) entre regiões, municípios ou empresas.
3. Coerência semântica: o título e a unidade declarada devem corresponder à coluna realmente plotada \
(ex.: não chamar `volume_t` de exposição ao desmatamento, nem declarar `ha` para `fob_usd`).
4. Limite jurídico e rastreabilidade: nenhum título ou subtítulo pode afirmar ilegalidade ou crime \
ambiental a partir de exposição do Trase. Rankings municipais da `supply_chain` não devem afirmar \
representar 100% do desmatamento nacional (cobrem a parte rastreada).

Se tudo estiver metodologicamente correto, aprove (`approved=true`, `issues=[]`).
Se houver erro metodológico, reprove (`approved=false`) apontando o `widget_id` exato e como corrigir.
"""

REVIEW_TOOL_SCHEMA = {
    "type": "object",
    "required": ["approved", "summary", "issues"],
    "properties": {
        "approved": {"type": "boolean", "description": "true se não houver problemas metodológicos."},
        "summary": {"type": "string", "description": "Parecer curto em português."},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["message"],
                "properties": {
                    "widget_id": {
                        "type": ["string", "null"],
                        "description": "ID do componente com problema (ex.: 'w1'), ou null se geral.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Explicação clara do problema metodológico e como corrigi-lo.",
                    },
                },
            },
        },
    },
}


def _has_numeric_values(df: pd.DataFrame, col: str) -> bool:
    return pd.to_numeric(df[col], errors="coerce").notna().any()


def _check_new_kind(w: WidgetSpec, datasets_by_id: dict[str, DatasetResult]) -> list[WidgetIssue]:
    """Regras próprias dos tipos novos, antes de herdarem as do tipo-base (BASE_KIND)."""
    ds = datasets_by_id.get(w.dataset_id)
    if ds is None or ds.df.empty:
        return []
    df = ds.df
    if w.kind == "gauge" and w.column in df.columns:
        # Medidor: só um percentual calculado dos dados (participação), sem meta inventada.
        valor = compute_kpi_value(df, w.column, w.agg)
        if not is_percentage_column_or_unit(w.column, w.unit, df):
            return [WidgetIssue(w.id, "deterministic",
                                f"Medidor exige coluna percentual; '{w.column}' (unidade '{w.unit}') não é.",
                                code="medidor")]
        if valor is None or not (0 <= valor <= 100):
            return [WidgetIssue(w.id, "deterministic", f"Medidor fora de 0–100%: {valor}.", code="medidor")]
    if w.kind == "waterfall" and any(c in df.columns and is_non_additive_column_or_unit(c, w.unit, df) for c in w.y):
        # Variação por item soma as contribuições: não serve para percentuais, médias ou intensidades.
        return [WidgetIssue(w.id, "methodological",
                            f"Variação por item soma contribuições; '{', '.join(w.y)}' não é aditiva.",
                            code="soma_percentual")]
    return []


def validate_law_widget(w: WidgetSpec, ds: DatasetResult) -> list[WidgetIssue]:
    """G7 (R5 para leis): fonte do acervo com [Dn]; toda linha com url_fonte (e citação literal, nos fatos);
    unidade em cada linha com valor; faixa de multa só compara linhas da MESMA unidade."""
    import re as _re

    issues: list[WidgetIssue] = []
    if LAWS_SOURCE not in w.source or not _re.search(rf"\[{_re.escape(w.dataset_id)}\]", w.source):
        issues.append(WidgetIssue(w.id, "deterministic",
                                  f"A fonte de um componente de leis deve ser '{LAWS_SOURCE} [{w.dataset_id}]'.",
                                  code="lei_fonte"))
    df = ds.df

    def _vazios(col: str) -> int:
        return int(df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum())

    if "url_fonte" not in df.columns or _vazios("url_fonte"):
        issues.append(WidgetIssue(w.id, "deterministic", "Linha de lei sem url_fonte.", code="lei_fonte"))
    elif not df["url_fonte"].astype(str).str.match(r"https?://").all():
        issues.append(WidgetIssue(w.id, "deterministic", "url_fonte inválida.", code="lei_fonte"))
    if "citacao_literal" in df.columns and _vazios("citacao_literal"):
        issues.append(WidgetIssue(w.id, "deterministic", "Linha de lei sem citação literal.", code="lei_fonte"))
    tem_valor = [c for c in ("valor_min", "valor_max") if c in df.columns]
    if tem_valor:
        com_valor = df[tem_valor].notna().any(axis=1)
        if "unidade" not in df.columns or (df.loc[com_valor, "unidade"].astype(str).str.strip().isin(["", "None", "nan"])).any():
            issues.append(WidgetIssue(w.id, "deterministic", "Valor de lei sem unidade na linha.",
                                      code="lei_unidade"))
    if w.kind == "range":
        if "unidade" not in df.columns or df["unidade"].nunique(dropna=False) != 1:
            issues.append(WidgetIssue(w.id, "deterministic",
                                      "Faixa de multa com unidades diferentes no mesmo gráfico.",
                                      code="lei_unidade"))
    return issues


def validate_widget_deterministic(
    w: WidgetSpec,
    datasets_by_id: dict[str, DatasetResult],
) -> list[WidgetIssue]:
    """Valida um único componente deterministicamente contra os DataFrames do SQL."""
    issues: list[WidgetIssue] = []

    # `area` e `progress` herdam todas as checagens (colunas e metodologia) de `line` e `bar`.
    issues.extend(_check_new_kind(w, datasets_by_id))
    original_kind = w.kind
    if w.kind in BASE_KIND:
        w = _replace(w, kind=BASE_KIND[w.kind])
    if w.kind == "kpi" and (w.trend_x or w.trend_y) and w.dataset_id in datasets_by_id:
        cols = set(datasets_by_id[w.dataset_id].df.columns)
        for campo, col in (("trend_x", w.trend_x), ("trend_y", w.trend_y)):
            if not col:
                issues.append(WidgetIssue(w.id, "deterministic", f"KPI com tendência deve informar '{campo}'."))
            elif col not in cols:
                issues.append(WidgetIssue(
                    w.id, "deterministic", f"Coluna {campo}='{col}' não existe em {w.dataset_id}.",
                ))

    if not w.valid and w.validation_error:
        issues.append(WidgetIssue(w.id, "deterministic", w.validation_error))
        return issues

    if w.kind not in WIDGET_KINDS:
        issues.append(WidgetIssue(
            w.id, "deterministic",
            f"Tipo '{w.kind}' inválido. Use apenas: {', '.join(ALLOWED_WIDGET_KINDS)}.",
        ))
        return issues

    if not w.title.strip():
        issues.append(WidgetIssue(w.id, "deterministic", "Título ausente no componente."))
    if not w.unit.strip():
        issues.append(WidgetIssue(w.id, "deterministic", "Unidade ausente no componente."))

    ds_law = datasets_by_id.get(w.dataset_id)
    law_widget = ds_law is not None and ds_law.database == LAWS_DATABASE
    src_lower = w.source.lower()
    if not w.source.strip():
        issues.append(WidgetIssue(w.id, "deterministic", "Fonte de dados ausente no componente."))
    elif law_widget:
        issues.extend(validate_law_widget(w, ds_law))
    else:
        if original_kind in LAW_WIDGET_KINDS or LAWS_SOURCE.lower() in src_lower:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                "Componente de leis precisa usar um dataset do acervo de leis.",
            ))
        if "trase" not in src_lower:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                f"A fonte ('{w.source}') deve citar explicitamente 'Trase'.",
            ))
        if w.dataset_id and w.dataset_id.lower() not in src_lower:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                f"A fonte ('{w.source}') deve citar o identificador do dataset [{w.dataset_id}].",
            ))

    if not w.dataset_id or w.dataset_id not in datasets_by_id:
        avail = ", ".join(sorted(datasets_by_id)) or "nenhum"
        issues.append(WidgetIssue(
            w.id, "deterministic",
            f"Dataset '{w.dataset_id}' não existe (disponíveis: {avail}).",
            code="sem_dados",
        ))
        issues.extend(validate_widget_methodological(w, None))
        return issues

    ds = datasets_by_id[w.dataset_id]
    df = ds.df
    if df.empty:
        issues.append(WidgetIssue(w.id, "deterministic", f"Dataset '{w.dataset_id}' não possui linhas.",
                                  code="sem_dados"))
        issues.extend(validate_widget_methodological(w, None))
        return issues

    cols = set(df.columns)

    if w.kind == "kpi":
        if not w.column:
            issues.append(WidgetIssue(w.id, "deterministic", "KPI deve especificar o campo 'column'."))
        elif w.column not in cols:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                f"Coluna '{w.column}' não existe em {w.dataset_id} (colunas: {', '.join(df.columns)}).",
            ))
        elif w.agg not in ALLOWED_KPI_AGGS:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                f"Agregação '{w.agg}' inválida em KPI (permitidas: {', '.join(ALLOWED_KPI_AGGS)}).",
            ))
        else:
            actual = compute_kpi_value(df, w.column, w.agg)
            if actual is None:
                issues.append(WidgetIssue(
                    w.id, "deterministic",
                    f"Coluna '{w.column}' em {w.dataset_id} não possui valores numéricos válidos para '{w.agg}'.",
                ))
            elif w.value is None:
                issues.append(WidgetIssue(
                    w.id, "deterministic",
                    f"KPI deve informar 'value' numérico correspondente a {w.dataset_id}.{w.column} "
                    f"({w.agg} = {actual:.6g}).",
                    code="kpi_valor",
                ))
            elif not math.isclose(w.value, actual, rel_tol=KPI_REL_TOL, abs_tol=KPI_ABS_TOL):
                issues.append(WidgetIssue(
                    w.id, "deterministic",
                    f"Valor do KPI ({w.value}) diverge do resultado SQL em {w.dataset_id}.{w.column} "
                    f"com agg='{w.agg}' (valor real = {actual:.6g}).",
                    code="kpi_valor",
                ))

    elif w.kind in ("bar", "line"):
        if not w.x:
            issues.append(WidgetIssue(w.id, "deterministic", f"Gráfico '{w.kind}' deve informar a coluna 'x'."))
        elif w.x not in cols:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                f"Coluna x='{w.x}' não existe em {w.dataset_id} (colunas: {', '.join(df.columns)}).",
            ))

        if not w.y:
            issues.append(WidgetIssue(
                w.id, "deterministic", f"Gráfico '{w.kind}' deve informar ao menos uma coluna em 'y'.",
            ))
        else:
            for y_col in w.y:
                if y_col not in cols:
                    issues.append(WidgetIssue(
                        w.id, "deterministic",
                        f"Coluna y='{y_col}' não existe em {w.dataset_id} (colunas: {', '.join(df.columns)}).",
                    ))
                elif not _has_numeric_values(df, y_col):
                    issues.append(WidgetIssue(
                        w.id, "deterministic",
                        f"Coluna y='{y_col}' em {w.dataset_id} não contém valores numéricos.",
                    ))

        if w.color:
            if w.color not in cols:
                issues.append(WidgetIssue(
                    w.id, "deterministic",
                    f"Coluna color='{w.color}' não existe em {w.dataset_id}.",
                ))
            elif len(w.y) > 1:
                issues.append(WidgetIssue(
                    w.id, "deterministic",
                    "Não combine múltiplas colunas em 'y' com 'color' no mesmo gráfico; "
                    "use uma única coluna 'y' com 'color' ou várias colunas 'y' sem 'color'.",
                ))

        if w.sort_by and w.sort_by not in cols:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                f"Coluna sort_by='{w.sort_by}' não existe em {w.dataset_id}.",
            ))

    elif w.kind == "table":
        if w.columns:
            missing = [c for c in w.columns if c not in cols]
            if missing:
                issues.append(WidgetIssue(
                    w.id, "deterministic",
                    f"Colunas inexistentes na tabela ({w.dataset_id}): {', '.join(missing)}.",
                ))
        if w.sort_by and w.sort_by not in cols:
            issues.append(WidgetIssue(
                w.id, "deterministic",
                f"Coluna sort_by='{w.sort_by}' não existe em {w.dataset_id}.",
            ))

    issues.extend(validate_widget_methodological(w, ds))
    return issues


def check_deterministic(
    spec: DashboardSpec,
    datasets: list[DatasetResult] | dict[str, DatasetResult],
) -> list[WidgetIssue]:
    """Executa todas as verificações determinísticas e metodológicas em Python puro."""
    by_id = datasets if isinstance(datasets, dict) else {d.dataset_id: d for d in datasets}
    issues: list[WidgetIssue] = []

    if not spec.title.strip():
        issues.append(WidgetIssue(None, "deterministic", "O dashboard precisa de um título principal ('title')."))
    issues.extend(validate_spec_methodological(spec, by_id))
    if not spec.widgets:
        issues.append(WidgetIssue(None, "deterministic", "O dashboard não contém nenhum componente em 'widgets'."))
        return issues

    seen_ids: set[str] = set()
    for w in spec.widgets:
        if w.id in seen_ids:
            issues.append(WidgetIssue(w.id, "deterministic", f"ID de componente duplicado: '{w.id}'."))
        seen_ids.add(w.id)
        issues.extend(validate_widget_deterministic(w, by_id))

    return issues


def check_methodological_llm(
    question: str,
    spec: DashboardSpec,
    datasets: list[DatasetResult],
) -> ReviewResult:
    """Usa o LLM apenas para revisar coerência metodológica e semântica."""
    ds_text = "\n".join(format_dataset_for_llm(d, max_rows=MAX_ROWS_TO_LLM) for d in datasets)
    spec_json = json.dumps(spec.to_dict(), ensure_ascii=False, indent=2)
    user_msg = (
        f"Pergunta do usuário: {question}\n\n"
        f"Datasets SQL disponíveis (truncados em {MAX_ROWS_TO_LLM} linhas):\n{ds_text}\n"
        f"Especificação JSON proposta para o dashboard:\n{spec_json}"
    )

    payload, in_tok, out_tok = call_structured_llm(
        system=REVIEWER_SYSTEM_PROMPT,
        user_content=user_msg,
        tool_name="emit_review",
        tool_description="Registra o parecer metodológico sobre a especificação do dashboard.",
        input_schema=REVIEW_TOOL_SCHEMA,
        max_tokens=2048,
    )

    valid_ids = {w.id for w in spec.widgets}
    issues: list[WidgetIssue] = []
    for raw_issue in payload.get("issues") or []:
        if not isinstance(raw_issue, dict) or not raw_issue.get("message"):
            continue
        wid = raw_issue.get("widget_id")
        wid_str = str(wid).strip() if wid else None
        if wid_str and wid_str not in valid_ids:
            wid_str = None
        # Recomendação do revisor LLM é observação: vai para o log e nunca oculta o gráfico.
        # As regras que bloqueiam (R5, colunas) são conferidas em código, antes desta etapa.
        issues.append(WidgetIssue(wid_str, "methodological", str(raw_issue["message"]).strip(),
                                  code="observacao", blocking=False))

    # Reprovação do LLM ainda pede uma nova tentativa ao gerador, mas, como são observações,
    # nunca ocultam o gráfico quando as tentativas acabam (ver `_apply_final_review_isolation`).
    approved = bool(payload.get("approved", False)) and len(issues) == 0
    return ReviewResult(
        approved=approved,
        issues=issues,
        summary=str(payload.get("summary") or "").strip(),
        llm_called=True,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def check_requested_chart(spec: DashboardSpec, requested) -> list[WidgetIssue]:
    """O tipo de gráfico que o usuário pediu está no painel? (em linguagem simples, sem jargão)."""
    if requested is None or getattr(requested, "kind", None) in (None, "other"):
        return []
    kinds = {w.kind for w in spec.widgets}
    if requested.kind == "bar_line":
        missing = not {"bar", "line"} <= kinds
    elif requested.kind == "area" and requested.stacked:
        missing = not any(w.kind == "area" and w.stacked for w in spec.widgets)
    else:
        missing = requested.kind not in kinds
    if not missing:
        return []
    return [WidgetIssue(
        None, "deterministic",
        f"O pedido foi {requested.kind_label} e o painel ainda não tem esse gráfico.",
        code="pedido", blocking=False,
    )]


_GROUPING_KINDS = ("bar", "pie", "donut", "progress", "waterfall", "table", "line", "area")


def _renamed_in_query(col: str, dim, query: str) -> bool:
    """Apelido livre ("CASE ... exporter_group ... END AS grupo"): a consulta usa a coluna da dimensão
    e o nome do eixo não é de nenhuma outra dimensão."""
    import re as _re

    from src.dashboard.dimensions import DIMENSIONS, column_matches

    if not query or not _re.search(rf"\bAS\s+\"?{_re.escape(col)}\b", query, _re.IGNORECASE):
        return False
    if not any(_re.search(rf"\b{_re.escape(c)}\b", query, _re.IGNORECASE) for c in dim.columns):
        return False
    return not any(column_matches(col, d) for d in DIMENSIONS.values() if d.key != dim.key)


def dimension_widgets(spec: DashboardSpec, dim, datasets=None) -> tuple[list, list]:
    """(widgets que agrupam pela dimensão pedida, widgets que agrupam por alguma categoria).

    Agrupar = eixo x de categoria (não o ano), a cor de uma série, ou a 1ª coluna de texto da tabela.
    Um apelido do SQL ("municipality_of_production AS m") também conta como a dimensão."""
    from src.dashboard.dimensions import aliased_from, column_matches

    queries = {d.dataset_id: d.query_summary or "" for d in (datasets or [])}
    grouped, matched = [], []
    for w in spec.widgets:
        if not w.valid or w.kind not in _GROUPING_KINDS:
            continue
        cols = [c for c in (w.x, w.color) if c and c.lower() not in ("year", "ano")]
        if w.kind == "table" and w.columns:
            cols.append(w.columns[0])
        if not cols:
            continue
        grouped.append(w)
        q = queries.get(w.dataset_id, "")
        if any(column_matches(c, dim) or aliased_from(c, dim, q) or _renamed_in_query(c, dim, q) for c in cols):
            matched.append(w)
    return matched, grouped


def check_requested_dimension(spec: DashboardSpec, dimension: str | None, datasets=None) -> list[WidgetIssue]:
    """A3: o gráfico principal precisa agrupar pela dimensão pedida (ex.: município, não empresa)."""
    from src.dashboard.dimensions import DIMENSIONS

    dim = DIMENSIONS.get(dimension or "")
    if dim is None:
        return []
    matched, grouped = dimension_widgets(spec, dim, datasets)
    if not grouped or matched:
        return []
    cols = ", ".join(dim.columns)
    return [WidgetIssue(
        None, "deterministic",
        f"O pedido foi por {dim.label} e nenhum gráfico agrupa por essa dimensão. Use a coluna {cols} "
        "no eixo x do gráfico principal, se ela estiver nos datasets.",
        code="dimensao", blocking=False,
    )]


_CHART_KINDS = frozenset({"bar", "line", "area", "pie", "donut", "progress", "waterfall"})
_TIME_COLS = frozenset({"year", "ano"})


def _structural_capacity(datasets: list[DatasetResult]) -> tuple[int, bool, bool]:
    """Calcula a capacidade estrutural dos datasets: (max_kpis_uteis, pode_ter_3_graficos, pode_ter_grafico)."""
    data_ds = [d for d in datasets if getattr(d, "database", "") != LAWS_DATABASE and not d.df.empty]
    if not data_ds:
        return 0, False, False

    numeric_cols_total = 0
    chartable_ds = 0
    metric_views = 0
    for ds in data_ds:
        df = ds.df
        num_cols = [c for c in df.columns if c.lower() not in _TIME_COLS and _has_numeric_values(df, c)]
        cat_or_time = [c for c in df.columns if c.lower() in _TIME_COLS or not pd.api.types.is_numeric_dtype(df[c])]
        numeric_cols_total += len(num_cols)
        if len(df) >= 2 and num_cols and cat_or_time:
            chartable_ds += 1
            # Cada dataset com >=2 linhas e dimensão + métrica suporta ao menos 1 gráfico;
            # com >=2 métricas ou >=4 categorias suporta visões complementares (ex.: barras + rosca/progresso).
            metric_views += max(len(num_cols), 2 if len(df) >= 4 else 1)

    can_have_chart = chartable_ds >= 1
    can_have_3_charts = chartable_ds >= 2 or metric_views >= 3
    # Cada coluna numérica + contagens de linhas de rankings podem gerar KPIs reais do SQL.
    max_kpis = numeric_cols_total + chartable_ds
    return max_kpis, can_have_3_charts, can_have_chart


def check_dashboard_structure(
    spec: DashboardSpec,
    datasets: list[DatasetResult] | dict[str, DatasetResult],
) -> list[WidgetIssue]:
    """Checagem determinística de composição executiva: KPIs no topo, >=3 gráficos variados e sem domínio de tabelas.

    Usa `blocking=False` para pedir revisão ao Agente de Dashboard sem ocultar gráficos válidos caso
    as tentativas de revisão se esgotem.
    """
    ds_list = list(datasets.values()) if isinstance(datasets, dict) else list(datasets)
    by_id = {d.dataset_id: d for d in ds_list}
    data_ds = [d for d in ds_list if getattr(d, "database", "") != LAWS_DATABASE and not d.df.empty]
    max_kpis, can_have_3_charts, can_have_chart = _structural_capacity(ds_list)
    if max_kpis == 0 and not can_have_chart:
        return []

    data_widgets = [
        w for w in spec.widgets
        if w.valid and not (w.dataset_id in by_id and getattr(by_id[w.dataset_id], "database", "") == LAWS_DATABASE)
        and LAWS_SOURCE not in (w.source or "")
    ]
    # Painéis mínimos de 1 único dataset com 1 métrica e 1 componente (ex.: tabela única ou gráfico isolado)
    # não são forçados a gerar composição executiva completa.
    num_cols_total = sum(
        len([c for c in d.df.columns if c.lower() not in _TIME_COLS and _has_numeric_values(d.df, c)])
        for d in data_ds
    )
    if len(data_ds) < 2 and num_cols_total < 2 and len(data_widgets) <= 1:
        return []
    kpis = [w for w in data_widgets if w.kind in ("kpi", "gauge")]
    charts = [w for w in data_widgets if w.kind in _CHART_KINDS]
    tables = [w for w in data_widgets if w.kind == "table"]
    chart_kinds = {w.kind for w in charts}

    issues: list[WidgetIssue] = []
    if max_kpis > 0 and len(kpis) == 0:
        issues.append(WidgetIssue(
            None, "deterministic",
            "O painel tem 0 KPIs. Inclua de 3 a 6 componentes `kpi` no topo (use os datasets disponíveis com "
            "agg sum/max/count/first respeitando as regras metodológicas, e informe trend_x/trend_y se houver série anual).",
            code="estrutura", blocking=False,
        ))
    elif max_kpis >= 3 and len(kpis) < 3:
        issues.append(WidgetIssue(
            None, "deterministic",
            f"O painel tem apenas {len(kpis)} KPI(s), mas os dados permitem de 3 a 6 KPIs executivos no topo.",
            code="estrutura", blocking=False,
        ))

    if can_have_3_charts and len(charts) < 3:
        issues.append(WidgetIssue(
            None, "deterministic",
            f"O painel tem apenas {len(charts)} gráfico(s), mas os datasets permitem pelo menos 3 gráficos de tipos "
            "diferentes (ex.: ranking em barras horizontais `bar`, participação em rosca `donut`, lista `progress` "
            "e/ou evolução temporal `line`/`area`).",
            code="estrutura", blocking=False,
        ))
    elif can_have_3_charts and len(charts) >= 3 and len(chart_kinds) < 2:
        issues.append(WidgetIssue(
            None, "deterministic",
            f"Todos os {len(charts)} gráficos usam o mesmo tipo ({', '.join(sorted(chart_kinds))}). "
            "Varie os tipos entre barras horizontais (`bar`), rosca (`donut`), lista de progresso (`progress`) "
            "e/ou linha temporal (`line`).",
            code="estrutura", blocking=False,
        ))

    if can_have_chart and len(tables) > len(charts):
        issues.append(WidgetIssue(
            None, "deterministic",
            f"Há mais tabelas ({len(tables)}) do que gráficos ({len(charts)}). Remova as tabelas redundantes do "
            "corpo principal e use gráficos (`bar`, `donut`, `progress`, `line`); cada gráfico já inclui 'Ver dados' recolhido.",
            code="estrutura", blocking=False,
        ))
    return issues


def review_dashboard(
    question: str,
    spec: DashboardSpec,
    datasets: list[DatasetResult],
    requested=None,
    dimension: str | None = None,
    *,
    enforce_structure: bool = False,
) -> ReviewResult:
    """Revisa o dashboard: primeiro determinístico em código; depois LLM só para metodologia.

    `requested` é o `ChartChoice` guardado no plano: o revisor confere se o tipo pedido foi atendido.
    `dimension` é a dimensão pedida (município, empresa...): o revisor confere o agrupamento.
    `enforce_structure`: quando True (fluxo de geração completa), reprova painéis sem KPIs,
    com menos de 3 gráficos podendo ter mais, ou com mais tabelas do que gráficos.
    """
    # A4: bases diferentes entre widgets não se corrigem reescrevendo o JSON (os dados são os mesmos):
    # o aviso vai no resultado, sem reprovar, e o orquestrador escreve a base em cada widget.
    base_issues = check_common_base(spec, datasets)
    log_issues("revisor_base", base_issues)
    struct_issues = check_dashboard_structure(spec, datasets) if enforce_structure else []
    det_issues = (check_requested_chart(spec, requested) + check_requested_dimension(spec, dimension, datasets)
                  + struct_issues + check_deterministic(spec, datasets))
    log_issues("revisor", det_issues)
    if det_issues:
        return ReviewResult(
            approved=False,
            issues=det_issues + base_issues,
            summary=f"{len(det_issues)} problema(s) encontrado(s) na verificação determinística.",
            llm_called=False,
        )
    review = check_methodological_llm(question, spec, datasets)
    log_issues("revisor_llm", review.issues)
    review.issues.extend(base_issues)
    return review

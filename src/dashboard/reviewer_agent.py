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

from src.dashboard._llm import call_structured_llm
from src.dashboard.schemas import (
    ALLOWED_KPI_AGGS,
    ALLOWED_WIDGET_KINDS,
    DashboardSpec,
    DatasetResult,
    MAX_ROWS_TO_LLM,
    ReviewResult,
    WidgetIssue,
    WidgetSpec,
    compute_kpi_value,
    format_dataset_for_llm,
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


def validate_widget_deterministic(
    w: WidgetSpec,
    datasets_by_id: dict[str, DatasetResult],
) -> list[WidgetIssue]:
    """Valida um único componente deterministicamente contra os DataFrames do SQL."""
    issues: list[WidgetIssue] = []

    if not w.valid and w.validation_error:
        issues.append(WidgetIssue(w.id, "deterministic", w.validation_error))
        return issues

    if w.kind not in ALLOWED_WIDGET_KINDS:
        issues.append(WidgetIssue(
            w.id, "deterministic",
            f"Tipo '{w.kind}' inválido. Use apenas: {', '.join(ALLOWED_WIDGET_KINDS)}.",
        ))
        return issues

    if not w.title.strip():
        issues.append(WidgetIssue(w.id, "deterministic", "Título ausente no componente."))
    if not w.unit.strip():
        issues.append(WidgetIssue(w.id, "deterministic", "Unidade ausente no componente."))

    src_lower = w.source.lower()
    if not w.source.strip():
        issues.append(WidgetIssue(w.id, "deterministic", "Fonte de dados ausente no componente."))
    else:
        if "trase" not in src_lower and getattr(datasets_by_id.get(w.dataset_id), "database", None) != "postgresql":
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
        ))
        return issues

    df = datasets_by_id[w.dataset_id].df
    if df.empty:
        issues.append(WidgetIssue(w.id, "deterministic", f"Dataset '{w.dataset_id}' não possui linhas."))
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
                ))
            elif not math.isclose(w.value, actual, rel_tol=KPI_REL_TOL, abs_tol=KPI_ABS_TOL):
                issues.append(WidgetIssue(
                    w.id, "deterministic",
                    f"Valor do KPI ({w.value}) diverge do resultado SQL em {w.dataset_id}.{w.column} "
                    f"com agg='{w.agg}' (valor real = {actual:.6g}).",
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

    return issues


def check_deterministic(
    spec: DashboardSpec,
    datasets: list[DatasetResult] | dict[str, DatasetResult],
) -> list[WidgetIssue]:
    """Executa todas as verificações determinísticas em Python puro."""
    by_id = datasets if isinstance(datasets, dict) else {d.dataset_id: d for d in datasets}
    issues: list[WidgetIssue] = []

    if not spec.title.strip():
        issues.append(WidgetIssue(None, "deterministic", "O dashboard precisa de um título principal ('title')."))
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
        issues.append(WidgetIssue(wid_str, "methodological", str(raw_issue["message"]).strip()))

    approved = bool(payload.get("approved", False)) and len(issues) == 0
    return ReviewResult(
        approved=approved,
        issues=issues,
        summary=str(payload.get("summary") or "").strip(),
        llm_called=True,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def review_dashboard(
    question: str,
    spec: DashboardSpec,
    datasets: list[DatasetResult],
) -> ReviewResult:
    """Revisa o dashboard: primeiro determinístico em código; depois LLM só para metodologia."""
    det_issues = check_deterministic(spec, datasets)
    if det_issues:
        return ReviewResult(
            approved=False,
            issues=det_issues,
            summary=f"{len(det_issues)} problema(s) encontrado(s) na verificação determinística.",
            llm_called=False,
        )
    return check_methodological_llm(question, spec, datasets)

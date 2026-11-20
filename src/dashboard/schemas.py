"""Contratos de dados e validação declarativa do sistema multiagente de dashboards.

Nenhum código arbitrário (Python/JS/HTML) vindo do LLM é aceito: o Agente de
Dashboard devolve apenas uma especificação JSON declarativa (DashboardSpec),
que é validada por componente antes de ser renderizada em Plotly.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ALLOWED_WIDGET_KINDS = ("kpi", "bar", "line", "area", "progress", "table", "pie", "donut", "gauge", "waterfall")
# Tipos novos herdam as regras de um tipo existente (colunas e metodologia), sem duplicar o validador.
# Nomes técnicos ficam no código; a tela diz pizza, rosca, medidor, variação por item.
BASE_KIND = {"area": "line", "progress": "bar", "pie": "bar", "donut": "bar", "waterfall": "bar", "gauge": "kpi",
             "range": "bar", "quote": "table"}
# G4: tipos só dos painéis de leis. São montados pelo código (src/dashboard/law_agent.py), nunca pela IA,
# por isso ficam fora de ALLOWED_WIDGET_KINDS (a lista que os prompts mostram).
LAW_WIDGET_KINDS = ("range", "quote")
WIDGET_KINDS = (*ALLOWED_WIDGET_KINDS, *LAW_WIDGET_KINDS)
LAWS_DATABASE = "laws"
LAWS_SOURCE = "Legislação — Planalto"
ALLOWED_KPI_AGGS = ("first", "sum", "mean", "max", "min", "count")
MAX_REVISIONS = 2
MAX_ROWS_TO_LLM = 60


# --- 1. Orquestrador -------------------------------------------------------------

@dataclass
class DataRequest:
    request_id: str
    description: str
    suggested_visual: str = "bar"
    database_hint: str = "auto"


@dataclass
class OrchestratorPlan:
    question: str
    domain: str
    dashboard_goal: str
    data_requests: list[DataRequest] = field(default_factory=list)
    methodological_notes: list[str] = field(default_factory=list)
    # Tipo de gráfico entendido do pedido (`chart_intent.ChartChoice`), ou None.
    requested_chart: object | None = None
    # A4: base comum do painel (year, origin "rastreada"|"toda", flow "exportacao"|"cadeia").
    common_base: dict = field(default_factory=dict)
    # A4: dimensão de agrupamento pedida (chave de src/dashboard/dimensions.DIMENSIONS).
    requested_dimension: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


# --- 2. Agente de dados ----------------------------------------------------------

@dataclass
class DatasetResult:
    dataset_id: str          # "D1", "D2"...
    database: str            # "trase.duckdb" | "soy.duckdb"
    source_label: str        # ex.: "Trase — Carne bovina (trase.duckdb)"
    tool_name: str           # consulta pronta ou run_sql / run_soy_sql
    query_summary: str       # assinatura da função ou SELECT executado
    df: pd.DataFrame
    purpose: str = ""
    truncated: bool = False
    seconds: float = 0.0


@dataclass
class DataAgentResult:
    datasets: list[DatasetResult] = field(default_factory=list)
    notes: str = ""
    tool_calls: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


# --- 3. Agente de dashboard (especificação JSON) ---------------------------------

@dataclass
class WidgetSpec:
    id: str
    kind: str                # "kpi" | "bar" | "line" | "area" | "progress" | "table"
    title: str
    dataset_id: str
    unit: str
    source: str
    subtitle: str = ""
    span: int = 1            # 1 = meia largura, 2 = largura total
    # Campos de KPI
    column: str | None = None
    agg: str = "first"
    value: float | None = None
    # Campos de gráficos (bar / line)
    x: str | None = None
    y: list[str] = field(default_factory=list)
    color: str | None = None
    orientation: str = "v"   # "v" | "h" (bar)
    barmode: str = "group"   # "group" | "stack" (bar)
    markers: bool = True     # (line)
    stacked: bool = False    # (area) empilha as séries
    # KPI: série e variação calculadas em código a partir de colunas do mesmo dataset
    trend_x: str | None = None
    trend_y: str | None = None
    # Campos de tabela e ordenação/recorte
    columns: list[str] = field(default_factory=list)
    column_labels: dict[str, str] = field(default_factory=dict)
    column_units: dict[str, str] = field(default_factory=dict)   # unidade de cada coluna (table)
    sort_by: str | None = None
    ascending: bool = False
    top_n: int | None = None
    # Componentes com o mesmo `group` são desenhados juntos e alinhados no mesmo eixo de tempo
    # ("barras e linha" em dois gráficos, nunca dois eixos com escalas diferentes).
    group: str | None = None
    # Estado de validação por componente (permite degradar só o gráfico inválido)
    valid: bool = True
    validation_error: str | None = None      # frase simples para a tela (nunca texto técnico)
    validation_codes: list[str] = field(default_factory=list)  # tipos dos problemas bloqueantes

    def to_dict(self) -> dict:
        out: dict = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "dataset_id": self.dataset_id,
            "unit": self.unit,
            "source": self.source,
            "span": self.span,
        }
        if self.kind in ("kpi", "gauge"):
            out.update({"column": self.column, "agg": self.agg, "value": self.value,
                        "trend_x": self.trend_x, "trend_y": self.trend_y})
        elif self.kind in ("bar", "line", "area", "progress", "pie", "donut", "waterfall"):
            out.update({"x": self.x, "y": self.y, "color": self.color,
                        "sort_by": self.sort_by, "ascending": self.ascending, "top_n": self.top_n})
            if self.kind == "bar":
                out.update({"orientation": self.orientation, "barmode": self.barmode})
            elif self.kind == "area":
                out["stacked"] = self.stacked
            elif self.kind == "line":
                out["markers"] = self.markers
        elif self.kind == "table":
            out.update({"columns": self.columns, "column_labels": self.column_labels,
                        "column_units": self.column_units,
                        "sort_by": self.sort_by, "ascending": self.ascending, "top_n": self.top_n})
        if self.group:
            out["group"] = self.group
        if not self.valid and self.validation_error:
            out["validation_error"] = self.validation_error
        return out


@dataclass
class DashboardSpec:
    title: str
    subtitle: str = ""
    widgets: list[WidgetSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "widgets": [w.to_dict() for w in self.widgets],
        }


# --- 4. Agente revisor -----------------------------------------------------------

@dataclass
class WidgetIssue:
    widget_id: str | None    # None = problema geral do dashboard
    check_type: str          # "deterministic" | "methodological"
    message: str             # texto técnico, para o agente e para o log (nunca para a tela)
    # Tipo do problema; a tela mostra uma frase simples escolhida por ele (`messages.user_message`).
    code: str = "estrutura"
    # Só problemas bloqueantes (regras R5 e colunas inexistentes) ocultam um gráfico.
    # Observações (ex.: recomendações do revisor LLM) vão para o log e nunca invalidam o componente.
    blocking: bool = True


@dataclass
class ReviewResult:
    approved: bool
    issues: list[WidgetIssue] = field(default_factory=list)
    summary: str = ""
    llm_called: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


# --- Resultado consolidado da execução ------------------------------------------

@dataclass
class DashboardRunResult:
    question: str
    domain: str
    html: str
    output_path: Path | None
    plan: OrchestratorPlan
    datasets: list[DatasetResult]
    spec: DashboardSpec
    reviews: list[ReviewResult] = field(default_factory=list)
    revisions_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


# --- Utilitários de parsing, truncamento e cálculo de KPI ------------------------

def round_sig(v):
    if isinstance(v, float) and math.isfinite(v) and v != 0:
        return float(f"{v:.6g}")
    return v


def format_dataset_for_llm(ds: DatasetResult, max_rows: int = MAX_ROWS_TO_LLM) -> str:
    """Formata metadados e até `max_rows` (60) linhas do DataFrame para envio ao LLM."""
    cols = ", ".join(f"{c} ({ds.df[c].dtype})" for c in ds.df.columns)
    header = (
        f"### Dataset [{ds.dataset_id}] — {ds.source_label}\n"
        f"Consulta: {ds.query_summary}\n"
        f"Finalidade: {ds.purpose or '-'}\n"
        f"Total de linhas no DataFrame: {len(ds.df)}"
        f"{' (truncado no banco)' if ds.truncated else ''}\n"
        f"Colunas: {cols}\n"
    )
    if ds.df.empty:
        return header + "(nenhuma linha)\n"
    shown = ds.df.head(max_rows).map(round_sig)
    csv_body = shown.to_csv(index=False).strip()
    if len(ds.df) > max_rows:
        note = f"\n(... truncado em {max_rows} de {len(ds.df)} linhas para o prompt)"
    else:
        note = f"\n({len(ds.df)} linhas)"
    return f"{header}{csv_body}{note}\n"


def compute_kpi_value(df: pd.DataFrame, column: str, agg: str = "first") -> float | None:
    """Calcula o valor numérico exato de um KPI diretamente a partir do DataFrame SQL."""
    if df.empty or column not in df.columns or agg not in ALLOWED_KPI_AGGS:
        return None
    if agg == "count":
        return float(int(df[column].notna().sum()))
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return None
    if agg == "first":
        val = float(series.iloc[0])
    elif agg == "sum":
        val = float(series.sum())
    elif agg == "mean":
        val = float(series.mean())
    elif agg == "max":
        val = float(series.max())
    elif agg == "min":
        val = float(series.min())
    else:
        return None
    return val if math.isfinite(val) else None


def extract_json_dict(raw: str | dict) -> dict:
    """Extrai um dicionário JSON de texto (com ou sem bloco ```json) ou devolve cópia do dict."""
    if isinstance(raw, dict):
        return dict(raw)
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("A especificação JSON deve ser um objeto na raiz.")
    return parsed


def _as_str_list(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [val.strip()] if val.strip() else []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    return []


def parse_widget_spec(raw: object, index: int) -> WidgetSpec:
    """Converte um item bruto em WidgetSpec; erros estruturais marcam apenas este widget como inválido."""
    fallback_id = f"w{index}"
    if not isinstance(raw, dict):
        return WidgetSpec(
            id=fallback_id, kind="invalid", title=f"Componente {index}",
            dataset_id="", unit="", source="",
            valid=False, validation_error="Especificação do componente não é um objeto JSON válido.",
        )

    wid = str(raw.get("id") or fallback_id).strip() or fallback_id
    kind = str(raw.get("kind") or "").strip().lower()
    title = str(raw.get("title") or "").strip()
    subtitle = str(raw.get("subtitle") or "").strip()
    dataset_id = str(raw.get("dataset_id") or "").strip().strip("[]")
    unit = str(raw.get("unit") or "").strip()
    source = str(raw.get("source") or "").strip()

    try:
        span = max(1, min(int(raw.get("span") or 1), 2))
    except (TypeError, ValueError):
        span = 1

    raw_val = raw.get("value")
    kpi_val: float | None = None
    val_error: str | None = None
    if raw_val is not None and raw_val != "":
        try:
            kpi_val = float(raw_val)
            if not math.isfinite(kpi_val):
                kpi_val = None
                val_error = "Valor numérico do KPI não é finito."
        except (TypeError, ValueError):
            val_error = f"Valor do KPI inválido: {raw_val!r}."

    top_n = None
    if raw.get("top_n") not in (None, ""):
        try:
            top_n = max(1, int(raw["top_n"]))
        except (TypeError, ValueError):
            top_n = None

    raw_labels = raw.get("column_labels")
    col_labels = (
        {str(k): str(v) for k, v in raw_labels.items()}
        if isinstance(raw_labels, dict) else {}
    )

    raw_units = raw.get("column_units")
    col_units = (
        {str(k): str(v).strip() for k, v in raw_units.items() if str(v).strip()}
        if isinstance(raw_units, dict) else {}
    )

    valid = True
    err = val_error
    if kind not in ALLOWED_WIDGET_KINDS:
        valid = False
        err = (
            f"Tipo de gráfico '{kind or 'vazio'}' não suportado nesta versão "
            f"(permitidos: {', '.join(ALLOWED_WIDGET_KINDS)})."
        )

    orientation = str(raw.get("orientation") or "v").strip().lower()
    if orientation not in ("v", "h"):
        orientation = "v"
    barmode = str(raw.get("barmode") or "group").strip().lower()
    if barmode not in ("group", "stack"):
        barmode = "group"

    return WidgetSpec(
        id=wid,
        kind=kind,
        title=title,
        subtitle=subtitle,
        dataset_id=dataset_id,
        unit=unit,
        source=source,
        span=span,
        column=str(raw["column"]).strip() if raw.get("column") else None,
        agg=str(raw.get("agg") or "first").strip().lower(),
        value=kpi_val,
        x=str(raw["x"]).strip() if raw.get("x") else None,
        y=_as_str_list(raw.get("y")),
        color=str(raw["color"]).strip() if raw.get("color") else None,
        orientation=orientation,
        barmode=barmode,
        markers=bool(raw.get("markers", True)),
        stacked=bool(raw.get("stacked", False)),
        trend_x=str(raw["trend_x"]).strip() if raw.get("trend_x") else None,
        trend_y=str(raw["trend_y"]).strip() if raw.get("trend_y") else None,
        columns=_as_str_list(raw.get("columns")),
        column_labels=col_labels,
        column_units=col_units,
        sort_by=str(raw["sort_by"]).strip() if raw.get("sort_by") else None,
        ascending=bool(raw.get("ascending", False)),
        top_n=top_n,
        group=str(raw["group"]).strip() if raw.get("group") else None,
        valid=valid,
        validation_error=err,
    )


def parse_dashboard_spec(raw: str | dict) -> DashboardSpec:
    """Converte JSON do Agente de Dashboard em DashboardSpec sem abortar por erro num único gráfico."""
    data = extract_json_dict(raw)
    title = str(data.get("title") or "").strip()
    subtitle = str(data.get("subtitle") or "").strip()
    raw_widgets = data.get("widgets")
    if not isinstance(raw_widgets, list):
        raw_widgets = []
    widgets = [parse_widget_spec(item, idx) for idx, item in enumerate(raw_widgets, start=1)]
    return DashboardSpec(title=title, subtitle=subtitle, widgets=widgets)

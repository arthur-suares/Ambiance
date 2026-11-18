"""Renderizador determinístico: DashboardSpec (JSON validado) + DataFrames -> HTML Plotly.

Segurança e resiliência:
- Nenhum código ou HTML vindo do LLM é executado; todo texto passa por `html.escape()`.
- Os números dos gráficos e KPIs saem diretamente dos `pd.DataFrame` retornados pelo DuckDB.
- Se um componente individual falhar na validação ou na construção da figura, apenas ele
  é substituído por um cartão de aviso no painel, mantendo todos os demais gráficos ativos.
"""

from __future__ import annotations

import html
import math
import re

import pandas as pd
import plotly.graph_objects as go

from src.dashboard.reviewer_agent import validate_widget_deterministic
from src.dashboard.schemas import (
    DashboardSpec,
    DatasetResult,
    WidgetSpec,
    compute_kpi_value,
)

PALETTE = [
    "#1b6ca8",
    "#2d8a56",
    "#d97706",
    "#b91c1c",
    "#6d28d9",
    "#0f766e",
    "#be185d",
    "#4b5563",
]


# Colunas que guardam o país de destino. Nelas, BRAZIL é soja processada no próprio Brasil
# (consumo doméstico), e não uma exportação.
DESTINATION_COLUMNS = {"country_of_first_import", "country_of_destination", "pais_destino", "destino"}


def display_label(value, col_name: str = "") -> str:
    """Rótulo para exibição: "BRAZIL" vira "BRASIL" e, em coluna de destino, recebe a ressalva."""
    text = str(value)
    if text.strip().upper() == "BRAZIL":
        return "BRASIL (processamento doméstico)" if col_name.lower() in DESTINATION_COLUMNS else "BRASIL"
    return text


def pt_text(text: str | None) -> str:
    """Texto livre (título, subtítulo, aviso): troca a palavra "Brazil" por "Brasil"."""
    return re.sub(r"\bBrazil\b", "Brasil", text or "", flags=re.IGNORECASE)


def _axis_title(label: str, unit: str) -> str:
    """Título do eixo sem repetir a unidade (ex.: "Volume (t)" + "t" não vira "Volume (t) (t)")."""
    label, unit = (label or "").strip(), (unit or "").strip()
    if not unit:
        return label
    if not label:
        return unit
    if f"({unit.lower()})" in label.lower() or re.search(r"\([^)]*\)\s*$", label):
        return label
    return f"{label} ({unit})"


def _starts_at_zero(df: pd.DataFrame, cols: list[str]) -> bool:
    """True se todas as séries são não negativas: nesse caso o eixo Y deve partir de zero."""
    vals = pd.concat([pd.to_numeric(df[c], errors="coerce") for c in cols if c in df.columns], ignore_index=True)
    vals = vals.dropna()
    return not vals.empty and bool((vals >= 0).all())


def format_br_value(val, col_name: str = "") -> str:
    """Formata valores escalares no padrão brasileiro para tabelas e textos auxiliares."""
    if val is None or (isinstance(val, float) and math.isnan(val)) or pd.isna(val):
        return "—"
    if isinstance(val, bool):
        return "Sim" if val else "Não"
    if isinstance(val, int) or (isinstance(val, float) and val.is_integer()):
        iv = int(val)
        if col_name.lower() in ("year", "ano"):
            return str(iv)
        return f"{iv:,}".replace(",", ".")
    if isinstance(val, float):
        if abs(val) >= 100:
            s = f"{val:,.1f}"
        elif abs(val) >= 1:
            s = f"{val:,.2f}"
        else:
            s = f"{val:,.4f}".rstrip("0").rstrip(".")
        return s.replace(",", "_").replace(".", ",").replace("_", ".")
    return display_label(val, col_name)


def _prepare_slice(df: pd.DataFrame, w: WidgetSpec, default_top_n: int | None = None) -> pd.DataFrame:
    out = df.copy()
    if w.sort_by and w.sort_by in out.columns:
        out = out.sort_values(by=w.sort_by, ascending=w.ascending, na_position="last")
    elif w.kind == "line" and w.x and w.x in out.columns:
        out = out.sort_values(by=w.x, ascending=True, na_position="last")
    limit = w.top_n or default_top_n
    if limit:
        out = out.head(limit)
    return out


def _base_layout(height: int = 340, margin: dict | None = None) -> dict:
    return {
        "template": "plotly_white",
        "separators": ",.",
        "height": height,
        "margin": margin or {"l": 56, "r": 24, "t": 24, "b": 52},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "#ffffff",
        "font": {"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "size": 12.5, "color": "#1f2328"},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
    }


def _build_kpi_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    actual = compute_kpi_value(df, w.column or "", w.agg)
    if actual is None:
        raise ValueError(f"Não foi possível calcular o KPI em {w.dataset_id}.{w.column}.")

    is_int = float(actual).is_integer() and abs(actual) < 1e12
    val_fmt = ",.0f" if is_int else (",.1f" if abs(actual) >= 100 else ",.2f")
    unit_clean = w.unit.strip()
    prefix = "US$ " if unit_clean.upper() in ("US$", "USD") else ""
    suffix = "" if prefix or unit_clean.lower() in ("nº", "numero", "número", "contagem", "unidades") else f" {unit_clean}"

    fig = go.Figure(go.Indicator(
        mode="number",
        value=actual,
        number={
            "valueformat": val_fmt,
            "prefix": prefix,
            "suffix": suffix,
            "font": {"size": 30, "color": "#0f4c81"},
        },
    ))
    fig.update_layout(**_base_layout(height=105, margin={"l": 12, "r": 12, "t": 14, "b": 10}))
    return fig


def _build_bar_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    work = _prepare_slice(df, w)
    horiz = w.orientation == "h"
    if horiz:
        work = work.iloc[::-1]

    cat_col = w.x or ""
    fig = go.Figure()

    if w.color and len(w.y) == 1:
        y_col = w.y[0]
        for idx, (grp, sub) in enumerate(work.groupby(w.color, sort=False, dropna=False)):
            label = "Não informado" if pd.isna(grp) else display_label(grp, w.color or "")
            cats = sub[cat_col].map(lambda v: display_label(v, cat_col))
            vals = pd.to_numeric(sub[y_col], errors="coerce")
            fig.add_trace(go.Bar(
                name=label,
                x=vals if horiz else cats,
                y=cats if horiz else vals,
                orientation="h" if horiz else "v",
                marker_color=PALETTE[idx % len(PALETTE)],
            ))
    else:
        cats = work[cat_col].map(lambda v: display_label(v, cat_col))
        for idx, y_col in enumerate(w.y):
            vals = pd.to_numeric(work[y_col], errors="coerce")
            name = w.column_labels.get(y_col, y_col)
            fig.add_trace(go.Bar(
                name=name,
                x=vals if horiz else cats,
                y=cats if horiz else vals,
                orientation="h" if horiz else "v",
                marker_color=PALETTE[idx % len(PALETTE)],
            ))

    height = max(340, 48 + 26 * len(work)) if horiz and len(work) > 10 else 360
    left_margin = 160 if horiz else 64
    fig.update_layout(
        **_base_layout(height=height, margin={"l": left_margin, "r": 24, "t": 28, "b": 64}),
        barmode=w.barmode,
        showlegend=(len(w.y) > 1 or bool(w.color)),
    )
    axis_label = _axis_title(w.column_labels.get(w.y[0], w.y[0]), w.unit) if len(w.y) == 1 else w.unit
    cat_label = w.column_labels.get(cat_col, cat_col)
    if horiz:
        fig.update_xaxes(title_text=axis_label, gridcolor="#eaeef2")
        fig.update_yaxes(title_text="", type="category")
    else:
        fig.update_xaxes(title_text=cat_label, type="category" if cat_col.lower() != "year" else None)
        fig.update_yaxes(title_text=axis_label, gridcolor="#eaeef2")
    return fig


def _build_line_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    work = _prepare_slice(df, w)
    x_col = w.x or ""
    mode = "lines+markers" if w.markers else "lines"
    fig = go.Figure()

    if w.color and len(w.y) == 1:
        y_col = w.y[0]
        for idx, (grp, sub) in enumerate(work.groupby(w.color, sort=False, dropna=False)):
            sub = sub.sort_values(by=x_col, ascending=True, na_position="last")
            label = "Não informado" if pd.isna(grp) else display_label(grp, w.color or "")
            fig.add_trace(go.Scatter(
                name=label,
                x=sub[x_col],
                y=pd.to_numeric(sub[y_col], errors="coerce"),
                mode=mode,
                line={"color": PALETTE[idx % len(PALETTE)], "width": 2.5},
                marker={"size": 7},
            ))
    else:
        for idx, y_col in enumerate(w.y):
            name = w.column_labels.get(y_col, y_col)
            fig.add_trace(go.Scatter(
                name=name,
                x=work[x_col],
                y=pd.to_numeric(work[y_col], errors="coerce"),
                mode=mode,
                line={"color": PALETTE[idx % len(PALETTE)], "width": 2.5},
                marker={"size": 7},
            ))

    fig.update_layout(
        **_base_layout(height=360, margin={"l": 64, "r": 24, "t": 28, "b": 56}),
        showlegend=(len(w.y) > 1 or bool(w.color)),
        hovermode="x unified",
    )
    y_title = _axis_title(w.column_labels.get(w.y[0], w.y[0]), w.unit) if len(w.y) == 1 else w.unit
    x_title = w.column_labels.get(x_col, x_col)
    fig.update_xaxes(title_text=x_title, gridcolor="#f0f3f6")
    if x_col.lower() in ("year", "ano") and work[x_col].nunique() <= 16:
        fig.update_xaxes(dtick=1)
    fig.update_yaxes(title_text=y_title, gridcolor="#eaeef2")
    if _starts_at_zero(work, list(w.y)):
        fig.update_yaxes(rangemode="tozero")  # série não negativa: o eixo parte de zero
    return fig


def _build_table_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    work = _prepare_slice(df, w, default_top_n=50)
    cols = w.columns if w.columns else list(work.columns)
    headers = [f"<b>{html.escape(w.column_labels.get(c, c))}</b>" for c in cols]
    cells = [[html.escape(format_br_value(v, c)) for v in work[c].tolist()] for c in cols]

    row_colors = [["#ffffff" if i % 2 == 0 else "#f6f8fa" for i in range(len(work))]] * len(cols)
    visible_rows = min(len(work), 12)
    height = max(180, 68 + 30 * visible_rows)

    fig = go.Figure(go.Table(
        header={
            "values": headers,
            "fill_color": "#eef2f6",
            "line_color": "#d0d7de",
            "align": "left",
            "font": {"color": "#1f2328", "size": 12.5},
            "height": 32,
        },
        cells={
            "values": cells,
            "fill_color": row_colors,
            "line_color": "#e5e9ef",
            "align": "left",
            "font": {"color": "#1f2328", "size": 12},
            "height": 28,
        },
    ))
    fig.update_layout(**_base_layout(height=height, margin={"l": 8, "r": 8, "t": 8, "b": 8}))
    return fig


def build_widget_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """Constrói a figura Plotly correspondente ao WidgetSpec."""
    if w.kind == "kpi":
        return _build_kpi_figure(w, df)
    if w.kind == "bar":
        return _build_bar_figure(w, df)
    if w.kind == "line":
        return _build_line_figure(w, df)
    if w.kind == "table":
        return _build_table_figure(w, df)
    raise ValueError(f"Tipo de componente não suportado: '{w.kind}'.")


def _render_warning_card(w: WidgetSpec, reason: str) -> str:
    span_cls = " span-2" if w.span == 2 else ""
    title = html.escape(pt_text(w.title) or f"Componente {w.id}")
    msg = html.escape(reason)
    return (
        f'<article class="card card-warning{span_cls}" data-widget-id="{html.escape(w.id)}">\n'
        f'  <div class="card-header">\n'
        f'    <div>\n'
        f'      <span class="badge badge-warn">Aviso de validação</span>\n'
        f'      <h3>{title}</h3>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'  <p class="warn-text">Este gráfico não pôde ser exibido: {msg}</p>\n'
        f'</article>'
    )


def _render_valid_card(w: WidgetSpec, fig_html: str) -> str:
    is_kpi = w.kind == "kpi"
    cls = "card kpi-card" if is_kpi else f"card{' span-2' if w.span == 2 else ''}"
    title = html.escape(pt_text(w.title))
    subtitle_html = f'<p class="subtitle">{html.escape(pt_text(w.subtitle))}</p>' if w.subtitle else ""
    unit_badge = f'<span class="badge">{html.escape(w.unit)}</span>' if w.unit else ""
    source = html.escape(w.source)
    return (
        f'<article class="{cls}" data-widget-id="{html.escape(w.id)}" data-widget-kind="{html.escape(w.kind)}">\n'
        f'  <div class="card-header">\n'
        f'    <div>\n'
        f'      <h3>{title}</h3>\n'
        f'      {subtitle_html}\n'
        f'    </div>\n'
        f'    {unit_badge}\n'
        f'  </div>\n'
        f'  <div class="plot-wrap">{fig_html}</div>\n'
        f'  <footer class="card-footer">Fonte: {source}</footer>\n'
        f'</article>'
    )


def render_dashboard_html(
    spec: DashboardSpec,
    datasets: list[DatasetResult],
    *,
    question: str = "",
) -> str:
    """Renderiza o dashboard completo em HTML5 interativo com Plotly."""
    by_id = {d.dataset_id: d for d in datasets}
    kpi_cards: list[str] = []
    main_cards: list[str] = []
    plotly_js_loaded = False

    for w in spec.widgets:
        det_issues = validate_widget_deterministic(w, by_id)
        if not w.valid or det_issues:
            reason = w.validation_error or "; ".join(i.message for i in det_issues)
            main_cards.append(_render_warning_card(w, reason))
            continue

        try:
            fig = build_widget_figure(w, by_id[w.dataset_id].df)
            fig_html = fig.to_html(
                full_html=False,
                include_plotlyjs="cdn" if not plotly_js_loaded else False,
                config={"responsive": True, "displaylogo": False},
            )
            plotly_js_loaded = True
            rendered = _render_valid_card(w, fig_html)
            if w.kind == "kpi":
                kpi_cards.append(rendered)
            else:
                main_cards.append(rendered)
        except Exception as exc:
            main_cards.append(_render_warning_card(w, f"{type(exc).__name__}: {exc}"))

    page_title = html.escape(pt_text(spec.title) or (f"Dashboard — {question}" if question else "Dashboard Trase"))
    page_subtitle = (
        f'<p class="hero-subtitle">{html.escape(pt_text(spec.subtitle))}</p>' if spec.subtitle else ""
    )
    question_banner = (
        f'<div class="question-pill"><strong>Pergunta:</strong> {html.escape(question)}</div>'
        if question else ""
    )

    top_warnings = ""
    if spec.warnings:
        items = "".join(f"<li>{html.escape(pt_text(msg))}</li>" for msg in spec.warnings)
        top_warnings = f'<section class="banner-warn"><strong>Avisos:</strong><ul>{items}</ul></section>'

    kpi_section = f'<section class="kpi-grid">\n{chr(10).join(kpi_cards)}\n</section>' if kpi_cards else ""
    if main_cards:
        charts_section = f'<section class="chart-grid">\n{chr(10).join(main_cards)}\n</section>'
    elif not kpi_cards:
        charts_section = (
            '<section class="banner-warn">Nenhum componente visual pôde ser gerado para esta consulta.</section>'
        )
    else:
        charts_section = ""

    queries_items = []
    for d in datasets:
        queries_items.append(
            f'<div class="query-item">'
            f'<div><strong>[{html.escape(d.dataset_id)}]</strong> {html.escape(d.source_label)} '
            f'<span class="meta">({len(d.df)} linhas · {d.seconds}s)</span></div>'
            f'<code>{html.escape(d.query_summary)}</code>'
            f'</div>'
        )
    queries_html = "\n".join(queries_items) or "<p class='meta'>Nenhuma consulta registrada.</p>"

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<style>
  :root {{
    --bg: #f6f8fa;
    --panel: #ffffff;
    --fg: #1f2328;
    --muted: #57606a;
    --border: #d0d7de;
    --accent: #0f4c81;
    --warn-bg: #fff8c5;
    --warn-border: #d4a72c;
    --warn-fg: #7d4e00;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font: 14.5px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }}
  main {{ max-width: 1240px; margin: 0 auto; padding: 28px 20px 56px; }}
  .hero {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 20px;
  }}
  h1 {{ font-size: 22px; margin: 0 0 6px; color: var(--fg); }}
  .hero-subtitle {{ margin: 0 0 10px; color: var(--muted); font-size: 14.5px; }}
  .question-pill {{
    display: inline-block;
    background: #eef4fa;
    color: #0f4c81;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
  }}
  .banner-warn {{
    background: var(--warn-bg);
    border: 1px solid var(--warn-border);
    color: var(--warn-fg);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 18px;
  }}
  .banner-warn ul {{ margin: 6px 0 0; padding-left: 20px; }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 16px;
    margin-bottom: 18px;
  }}
  .chart-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  @media (max-width: 860px) {{
    .chart-grid {{ grid-template-columns: 1fr; }}
    .span-2 {{ grid-column: auto !important; }}
  }}
  .span-2 {{ grid-column: 1 / -1; }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px 12px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .card-warning {{
    background: var(--warn-bg);
    border-color: var(--warn-border);
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
    margin-bottom: 6px;
  }}
  .card-header h3 {{ font-size: 15.5px; margin: 0; line-height: 1.35; }}
  .subtitle {{ margin: 3px 0 0; color: var(--muted); font-size: 12.5px; }}
  .badge {{
    flex-shrink: 0;
    background: #eef2f6;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 9px;
    font-size: 11.5px;
    font-weight: 600;
  }}
  .badge-warn {{
    display: inline-block;
    background: #f5e08e;
    color: var(--warn-fg);
    border-color: var(--warn-border);
    margin-bottom: 4px;
  }}
  .warn-text {{ margin: 8px 0 4px; color: var(--warn-fg); font-size: 13.5px; }}
  .plot-wrap {{ width: 100%; overflow-x: auto; }}
  .card-footer {{
    border-top: 1px solid #eef2f6;
    margin-top: 8px;
    padding-top: 8px;
    font-size: 12px;
    color: var(--muted);
  }}
  details.provenance {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
  }}
  details.provenance summary {{
    cursor: pointer;
    font-weight: 600;
    color: var(--muted);
  }}
  .query-item {{
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid #eef2f6;
  }}
  .query-item code {{
    display: block;
    margin-top: 4px;
    padding: 8px 10px;
    background: var(--bg);
    border-radius: 6px;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .meta {{ color: var(--muted); font-size: 12.5px; }}
</style>
</head>
<body>
<main>
  <header class="hero">
    <h1>{page_title}</h1>
    {page_subtitle}
    {question_banner}
  </header>

  {top_warnings}
  {kpi_section}
  {charts_section}

  <details class="provenance">
    <summary> Rastreabilidade — Consultas SQL e fontes de dados (Trase / DuckDB)</summary>
    {queries_html}
  </details>
</main>
</body>
</html>
"""

"""Renderizador determinístico: DashboardSpec (JSON validado) + DataFrames -> página HTML.

Segurança e resiliência:
- Nenhum código ou HTML vindo do LLM é executado; todo texto passa por `html.escape()`.
- Os números dos gráficos e KPIs saem diretamente dos `pd.DataFrame` retornados pelo DuckDB.
- Se um componente individual falhar na validação ou na construção da figura, apenas ele
  é substituído por um cartão de aviso no painel, mantendo todos os demais gráficos ativos.
"""

from __future__ import annotations

import html
import logging
import math
import re
from dataclasses import replace

import pandas as pd
import plotly.graph_objects as go

from src.dashboard.messages import NO_DATA_TITLE, SHOWN_AS_LIST, is_residual_label, plain_labels, short_subtitle, user_message
from src.dashboard.reviewer_agent import validate_widget_deterministic
from src.dashboard.schemas import (
    DashboardSpec,
    DatasetResult,
    WidgetSpec,
    compute_kpi_value,
)

logger = logging.getLogger(__name__)

# Paleta terrosa, legível nos temas claro e escuro (verde-floresta, limão, teal, âmbar,
# terracota, petróleo, lilás-acinzentado, pedra).
PALETTE = [
    "#2f7d4f",
    "#93c83e",
    "#1f9e8f",
    "#d99a2b",
    "#c2603a",
    "#2c6e8a",
    "#8a7fa8",
    "#7d8579",
]


NEUTRAL = "#9a9789"  # cinza quente para "Outros" e "não identificado"

# Colunas que guardam o país de destino. Nelas, BRAZIL é soja processada no próprio Brasil
# (consumo doméstico), e não uma exportação.
DESTINATION_COLUMNS = {"country_of_first_import", "country_of_destination", "pais_destino", "destino"}


def display_label(value, col_name: str = "") -> str:
    """Rótulo para exibição: "BRAZIL" vira "BRASIL" (com a ressalva em coluna de destino) e rótulos
    técnicos como UNKNOWN ou PROCESSED DOMESTICALLY viram português simples."""
    text = str(value)
    if text.strip().upper() == "BRAZIL":
        return "BRASIL (processamento doméstico)" if col_name.lower() in DESTINATION_COLUMNS else "BRASIL"
    plain = plain_labels(text)
    if plain != text and plain[:1].islower():
        plain = plain[:1].upper() + plain[1:]
    return plain


def pt_text(text: str | None) -> str:
    """Texto livre (título, subtítulo, aviso): "Brazil" vira "Brasil" e rótulos técnicos dos dados
    (UNKNOWN, PROCESSED DOMESTICALLY...) viram português simples."""
    return plain_labels(re.sub(r"\bBrazil\b", "Brasil", text or "", flags=re.IGNORECASE))



# Nome amigável de coluna quando a IA não deu rótulo: nunca o nome cru do campo na tela.
_FRIENDLY_COLUMNS = (
    (r"(?:^|_)(?:pct|perc|percent|share|participac\w*|participation)(?:_|$)", "Participação"),
    (r"(?:^|_)(?:fob|usd|valor)(?:_|$)", "Valor FOB"),
    (r"expos|deforest|desmat", "Exposição ao desmatamento"),
    (r"co2|emiss", "Emissões"),
    (r"(?:^|_)(?:volume|tonnes|toneladas)(?:_|$)", "Volume"),
    (r"^(?:municipality|municipio|municipality_of_production)$", "Município"),
    (r"^exporter_group$", "Grupo exportador"),
    (r"^exporter$", "Exportador"),
    (r"^importer_group$", "Grupo importador"),
    (r"^importer$", "Importador"),
    (r"^(?:country_of_first_import|country_of_destination|destination|destino|pais_destino)$", "País de destino"),
    (r"^(?:state|uf|estado)$", "Estado"),
    (r"^(?:biome|bioma)$", "Bioma"),
    (r"^(?:year|ano)$", "Ano"),
)


def _label(w: WidgetSpec, col: str | None) -> str:
    """Rótulo da coluna para a tela: o que a IA deu em `column_labels` ou um nome amigável."""
    if not col:
        return ""
    if col in w.column_labels:
        return w.column_labels[col]
    low = col.lower()
    for pattern, nome in _FRIENDLY_COLUMNS:
        if re.search(pattern, low):
            return nome
    txt = plain_labels(col).replace("_", " ").strip()
    return txt[:1].upper() + txt[1:]

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
        if re.search(r"(?:^|_)(?:year|ano)(?:_|$)", col_name.lower()):
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



# CSS da página (sem recursos externos). Tokens nos dois temas; os textos dos gráficos Plotly
# (SVG) são recoloridos por CSS, então a troca de tema não exige redesenhar as figuras.
PAGE_CSS = """
:root {
  --bg: #eef3ea; --panel: #ffffff; --panel-2: #f6f9f3; --fg: #18271f; --muted: #5b6b60;
  --border: #dde5d6; --accent: #2f7d4f; --accent-soft: #e3f0e2; --lime: #d6f26a; --lime-ink: #173a2b;
  --side-bg: #173a2b; --side-fg: #dfe9e1; --side-muted: #9fb7a6; --hero-tint: #eaf6d2;
  --chart-text: #4d5d53; --track: #e6ede1; --shadow: 0 1px 2px rgba(16,40,28,.05), 0 10px 28px rgba(16,40,28,.07);
  --warn-bg: #fff6e0; --warn-border: #ecc977; --warn-fg: #7a4f0e; --focus: #2f7d4f; --code-bg: #f1f5ee;
  color-scheme: light;
}
:root[data-theme="dark"] {
  --bg: #0f1a14; --panel: #16241c; --panel-2: #1b2c22; --fg: #e8f0ea; --muted: #a3b5a8;
  --border: #25382c; --accent: #8bd17c; --accent-soft: #1f3527; --lime: #d6f26a; --lime-ink: #10251a;
  --side-bg: #0a130e; --side-fg: #dfe9e1; --side-muted: #8aa292; --hero-tint: #1d3324;
  --chart-text: #b9c8bd; --track: #22362a; --shadow: 0 1px 2px rgba(0,0,0,.3), 0 10px 28px rgba(0,0,0,.25);
  --warn-bg: #2c2414; --warn-border: #6b5424; --warn-fg: #f0d28e; --focus: #d6f26a; --code-bg: #0f1a14;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 14.5px/1.55 Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  -webkit-font-smoothing: antialiased;
}
:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; border-radius: 8px; }
.skip { position: absolute; left: -999px; top: 8px; background: var(--panel); color: var(--fg); padding: 8px 12px; border-radius: 8px; z-index: 10; }
.skip:focus { left: 12px; }
.icon { width: 18px; height: 18px; flex-shrink: 0; }
.icon-sm { width: 14px; height: 14px; vertical-align: -2px; }
.icon-lg { width: 40px; height: 40px; color: var(--muted); }
.icon-logo { width: 26px; height: 26px; color: var(--lime); }

.shell { display: grid; grid-template-columns: 252px minmax(0, 1fr); min-height: 100vh; }
.sidebar {
  position: sticky; top: 0; height: 100vh; overflow-y: auto; background: var(--side-bg); color: var(--side-fg);
  padding: 24px 16px; display: flex; flex-direction: column; gap: 18px;
}
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; letter-spacing: .2px; padding: 0 8px; }
.side-title { margin: 0; padding: 0 8px; color: var(--side-muted); font-size: 12.5px; line-height: 1.4; }
.sidebar nav { display: flex; flex-direction: column; gap: 4px; }
.sidebar nav a {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 12px;
  color: var(--side-fg); text-decoration: none; font-weight: 500; transition: background .15s, color .15s;
}
.sidebar nav a:hover { background: rgba(255,255,255,.07); }
.sidebar nav a.is-active { background: var(--lime); color: var(--lime-ink); font-weight: 650; }
.side-bottom { margin-top: auto; display: flex; flex-direction: column; gap: 10px; }
.theme-toggle {
  display: flex; align-items: center; gap: 10px; width: 100%; padding: 10px 12px; border-radius: 12px;
  border: 1px solid rgba(255,255,255,.14); background: transparent; color: var(--side-fg); font: inherit; cursor: pointer;
}
.theme-toggle:hover { background: rgba(255,255,255,.07); }
.side-foot { margin: 0; padding: 0 8px; color: var(--side-muted); font-size: 12px; }

main { padding: 28px 32px 48px; max-width: 1320px; width: 100%; }
.hero {
  display: flex; justify-content: space-between; align-items: flex-start; gap: 16px;
  background: linear-gradient(135deg, var(--panel) 0%, var(--panel) 45%, var(--hero-tint) 100%);
  border: 1px solid var(--border); border-radius: 22px; padding: 24px 28px; box-shadow: var(--shadow); margin-bottom: 22px;
}
.eyebrow { display: inline-block; font-size: 11.5px; font-weight: 700; letter-spacing: .9px; text-transform: uppercase; color: var(--accent); margin-bottom: 6px; }
h1 { font-size: 26px; line-height: 1.25; margin: 0 0 8px; letter-spacing: -.2px; }
.hero-subtitle { margin: 0 0 12px; color: var(--muted); max-width: 860px; }
.question-pill { display: inline-block; background: var(--accent-soft); color: var(--fg); border-radius: 999px; padding: 6px 14px; font-size: 13px; }
.source-pill { flex-shrink: 0; background: var(--lime); color: var(--lime-ink); font-weight: 650; font-size: 12.5px; border-radius: 999px; padding: 6px 12px; }

.banner-warn {
  display: flex; gap: 12px; align-items: flex-start; background: var(--warn-bg); border: 1px solid var(--warn-border);
  color: var(--warn-fg); border-radius: 16px; padding: 14px 18px; margin-bottom: 22px;
}
.banner-warn ul { margin: 4px 0 0; padding-left: 18px; }

.dash-section { margin-bottom: 26px; scroll-margin-top: 16px; }
.section-title {
  display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 700; letter-spacing: .9px;
  text-transform: uppercase; color: var(--muted); margin: 0 0 12px;
}
.section-title::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.span-2 { grid-column: 1 / -1; }

.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 18px 20px 14px;
  box-shadow: var(--shadow); display: flex; flex-direction: column; min-width: 0;
}
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
.card-header h3 { font-size: 15.5px; font-weight: 650; margin: 0; line-height: 1.35; }
.scope-notes { font-size: 13px; color: var(--muted); margin: 8px 0 12px; }
.scope-notes p { margin: 4px 0 0; }
.gauge { position: relative; width: 132px; height: 132px; margin: 6px auto 4px; }
.gauge svg { width: 100%; height: 100%; }
.gauge-track { fill: none; stroke: var(--panel-2); stroke-width: 10; }
.gauge-fill { fill: none; stroke: #93c83e; stroke-width: 10; stroke-linecap: butt; }
.gauge-value { position: absolute; inset: 0; display: grid; place-items: center; font-size: 22px; font-weight: 700;
  font-variant-numeric: tabular-nums; }
.fallback-note { margin: 0 0 10px; font-size: 12.5px; color: var(--muted); }
.subtitle { margin: 4px 0 0; color: var(--muted); font-size: 12.5px; }
.badge {
  flex-shrink: 0; background: var(--panel-2); color: var(--muted); border: 1px solid var(--border);
  border-radius: 999px; padding: 2px 10px; font-size: 11.5px; font-weight: 650; white-space: nowrap;
}
.card-body { flex: 1; min-width: 0; }
.card-footer { border-top: 1px solid var(--border); margin-top: 10px; padding-top: 9px; font-size: 12px; color: var(--muted); }

.kpi-card { gap: 6px; }
.kpi-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.kpi-label { margin: 0; font-size: 12px; font-weight: 700; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); line-height: 1.4; }
.kpi-value { margin: 2px 0 0; font-size: 34px; font-weight: 750; letter-spacing: -.6px; line-height: 1.1; color: var(--fg); font-variant-numeric: tabular-nums; }
.kpi-meta { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 8px 10px; color: var(--accent); min-height: 40px; }
.spark { flex: 1 1 72px; width: 100%; max-width: 132px; min-width: 0; height: 40px; }
.delta { font-size: 12.5px; font-weight: 650; color: var(--fg); background: var(--panel-2); border: 1px solid var(--border); border-radius: 999px; padding: 2px 9px; white-space: nowrap; }
.delta-ref { font-weight: 500; color: var(--muted); }
.kpi-card .card-footer { margin-top: auto; }
.kpi-card.is-featured { background: var(--side-bg); border-color: transparent; color: #eef5ef; }
.kpi-card.is-featured .kpi-label, .kpi-card.is-featured .subtitle, .kpi-card.is-featured .card-footer, .kpi-card.is-featured .delta-ref { color: #a9c2b1; }
.kpi-card.is-featured .kpi-value { color: var(--lime); }
.kpi-card.is-featured .kpi-meta { color: var(--lime); }
.kpi-card.is-featured .badge, .kpi-card.is-featured .delta { background: rgba(255,255,255,.08); border-color: rgba(255,255,255,.14); color: #eef5ef; }
.kpi-card.is-featured .card-footer { border-top-color: rgba(255,255,255,.12); }

.plot-wrap { width: 100%; }
/* Rótulos dentro das fatias usam a cor escolhida pelo contraste com a fatia (ver _ink_on). */
.js-plotly-plot .plotly .main-svg text:not(.slicetext) { fill: var(--chart-text) !important; }
.js-plotly-plot .plotly .main-svg .hoverlayer text { fill: #ffffff !important; }
.js-plotly-plot .plotly .modebar { background: transparent !important; }
.js-plotly-plot .plotly .modebar-btn path { fill: var(--muted) !important; }

.table-wrap { max-height: 440px; overflow: auto; border: 1px solid var(--border); border-radius: 14px; }
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; font-variant-numeric: tabular-nums; }
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--panel-2); color: var(--muted); text-align: left;
  font-size: 11.5px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase; padding: 10px 12px; border-bottom: 1px solid var(--border);
}
tbody td { padding: 9px 12px; border-bottom: 1px solid var(--border); }
tbody tr:nth-child(even) td { background: color-mix(in srgb, var(--panel-2) 55%, transparent); }
tbody tr:hover td { background: var(--accent-soft); }
th.num, td.num { text-align: right; }
td.has-bar { position: relative; }
.databar { position: absolute; right: 0; top: 6px; bottom: 6px; background: var(--accent-soft); border-radius: 6px 0 0 6px; }
:root[data-theme="dark"] .databar { background: rgba(139,209,124,.18); }
.cell-v { position: relative; }

.progress-list { list-style: none; margin: 4px 0 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.prog-row { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; font-size: 13.5px; }
.prog-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 550; }
.prog-v { color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; }
.prog-pct { font-weight: 700; font-variant-numeric: tabular-nums; min-width: 52px; text-align: right; }
.prog-track { height: 9px; border-radius: 999px; background: var(--track); overflow: hidden; }
.prog-fill { display: block; height: 100%; border-radius: 999px; }
.note { margin: 12px 0 0; color: var(--muted); font-size: 12px; }

.card-warning { background: var(--warn-bg); border-color: var(--warn-border); box-shadow: none; }
.badge-warn { display: inline-flex; align-items: center; gap: 6px; background: transparent; color: var(--warn-fg); border-color: var(--warn-border); margin-bottom: 8px; }
.warn-text { margin: 6px 0 2px; color: var(--warn-fg); font-size: 13.5px; }
.empty-state { text-align: center; padding: 48px 16px; color: var(--muted); background: var(--panel); border: 1px dashed var(--border); border-radius: 20px; margin-bottom: 24px; }

details.provenance { background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 16px 20px; box-shadow: var(--shadow); scroll-margin-top: 16px; }
details.provenance summary { cursor: pointer; font-weight: 650; color: var(--fg); }
.query-item { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
.query-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.query-item pre { margin: 8px 0 0; padding: 10px 12px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 12px; overflow-x: auto; }
.query-item code { font-size: 12px; white-space: pre-wrap; word-break: break-word; }
.btn-ghost { border: 1px solid var(--border); background: var(--panel-2); color: var(--fg); border-radius: 999px; padding: 4px 12px; font: inherit; font-size: 12px; cursor: pointer; }
.btn-ghost:hover { background: var(--accent-soft); }
.meta { color: var(--muted); font-size: 12.5px; }
.page-footer { margin-top: 22px; color: var(--muted); font-size: 12px; text-align: center; }

@media (max-width: 900px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar { position: sticky; top: 0; z-index: 5; height: auto; flex-direction: row; align-items: center; gap: 10px; padding: 10px 12px; overflow-x: auto; }
  .brand span, .side-title, .side-foot { display: none; }
  .sidebar nav { flex-direction: row; gap: 4px; }
  .sidebar nav a { padding: 8px 10px; white-space: nowrap; font-size: 13px; }
  .sidebar nav a span { display: none; }
  .side-bottom { margin: 0 0 0 auto; }
  .theme-toggle { padding: 8px 10px; }
  .theme-toggle .theme-label { display: none; }
  main { padding: 16px 14px 32px; }
  .hero { flex-direction: column; padding: 18px; border-radius: 18px; }
  h1 { font-size: 21px; }
  .chart-grid { grid-template-columns: 1fr; }
  .kpi-grid { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  .kpi-value { font-size: 28px; }
  .span-2 { grid-column: auto; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } * { transition: none !important; } }
@media print {
  .sidebar, .theme-toggle, .btn-ghost, .skip { display: none !important; }
  .shell { grid-template-columns: 1fr; }
  body { background: #ffffff; }
  .card, .hero, details.provenance { box-shadow: none; break-inside: avoid; }
}
"""
FONT_STACK = 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif'
GRID_COLOR = "rgba(120, 140, 128, 0.18)"
HOVER_BG = "#173a2b"
TIME_COLUMNS = ("year", "ano")
COUNT_UNITS = {
    "nº", "n°", "numero", "número", "contagem", "unidades", "municípios", "municipios", "países",
    "paises", "empresas", "tradings", "importadores", "exportadores", "grupos", "registros", "linhas",
}
PCT_HINTS = ("pct", "perc", "percent", "particip", "share", "fracao", "fração", "proporc")

# Seções da página: cada tipo de componente cai numa seção fixa (sem mudar o schema).
SECTIONS = (
    ("visao-geral", "Visão geral"),
    ("evolucao", "Evolução"),
    ("rankings", "Rankings"),
    ("detalhamento", "Detalhamento"),
)
SECTION_OF = {
    "kpi": "visao-geral",
    "line": "evolucao",
    "area": "evolucao",
    "bar": "rankings",
    "progress": "rankings",
    "pie": "rankings",
    "donut": "rankings",
    "waterfall": "rankings",
    "gauge": "visao-geral",
    "table": "detalhamento",
}

ICONS = {
    "logo": '<path d="M5 19c8 0 14-6 14-14-8 0-14 6-14 14Z"/><path d="M5 19 13 11"/>',
    "visao-geral": '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/>'
                   '<rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>',
    "evolucao": '<path d="M4 17l5-5 4 3 7-8"/><path d="M15 7h5v5"/>',
    "rankings": '<path d="M5 20V10"/><path d="M12 20V4"/><path d="M19 20v-7"/>',
    "detalhamento": '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M10 10v9"/>',
    "rastreabilidade": '<path d="M9 7 4 12l5 5M15 7l5 5-5 5"/>',
    "tema": '<path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9Z"/>',
    "aviso": '<path d="M12 4 2.5 20h19L12 4Z"/><path d="M12 10v4M12 17h.01"/>',
}


def _icon(name: str, cls: str = "icon") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


# --- Números ---------------------------------------------------------------------

def _br_number(v: float, decimals: int, strip_zeros: bool = True) -> str:
    s = f"{v:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if strip_zeros and decimals and "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def format_compact_br(value, unit: str = "", *, with_unit: bool = True) -> str:
    """Número curto no padrão brasileiro: 13,9 mi t · US$ 6,07 bi · 21,7 mil ha · 44,0% · 181 municípios."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    u = (unit or "").strip()
    ul = u.lower()
    if ul in ("%", "pct", "percentual"):
        txt = f"{v:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{txt}%" if with_unit else txt
    if ul in COUNT_UNITS:
        num = _br_number(v, 0 if v.is_integer() else 1)
        return f"{num} {u}" if with_unit else num
    scaled, suffix = v, ""
    for base, name in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(v) >= base:
            scaled, suffix = v / base, name
            break
    a = abs(scaled)
    # Com sufixo (mil, mi, bi) mantém as casas, para não virar "1 mi" quando o valor é 1,00 mi.
    num = _br_number(scaled, 0 if a >= 100 else (1 if a >= 10 else 2), strip_zeros=not suffix)
    text = f"{num} {suffix}".strip()
    if not with_unit or not u or ul in ("múltiplas", "multiplas"):
        return text
    if ul in ("us$", "usd"):
        return f"US$ {text}"
    return f"{text} {u}"


def _fmt_axis_value(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f.is_integer() else _br_number(f, 2)


def kpi_trend(df: pd.DataFrame, w: WidgetSpec) -> dict | None:
    """Mini-série e variação do KPI, calculadas do DataFrame (nunca informadas pela IA).

    Exige um valor por período: se o mesmo período aparece em mais de uma linha, não agrega
    (somar linhas poderia somar janelas de 5 anos ou regiões) e devolve None.
    """
    if not (w.trend_x and w.trend_y) or w.trend_x not in df.columns or w.trend_y not in df.columns:
        return None
    t = df[[w.trend_x, w.trend_y]].copy()
    t[w.trend_y] = pd.to_numeric(t[w.trend_y], errors="coerce")
    t = t.dropna()
    if t.empty or t[w.trend_x].duplicated().any():
        return None
    t = t.sort_values(w.trend_x)
    xs = t[w.trend_x].tolist()
    ys = [float(v) for v in t[w.trend_y]]
    out = {"xs": xs, "ys": ys, "delta_pct": None, "prev_x": None, "last_x": xs[-1]}
    if len(ys) >= 2 and ys[-2] != 0:
        out["delta_pct"] = (ys[-1] - ys[-2]) / abs(ys[-2]) * 100
        out["prev_x"] = xs[-2]
    return out


# --- Recorte dos dados -------------------------------------------------------------

def _is_time(col: str | None) -> bool:
    return bool(col) and col.lower() in TIME_COLUMNS


def _prepare_slice(df: pd.DataFrame, w: WidgetSpec, default_top_n: int | None = None) -> pd.DataFrame:
    out = df.copy()
    if w.sort_by and w.sort_by in out.columns:
        out = out.sort_values(by=w.sort_by, ascending=w.ascending, na_position="last")
    elif w.kind in ("line", "area") and w.x and w.x in out.columns:
        out = out.sort_values(by=w.x, ascending=True, na_position="last")
    elif (w.kind in ("bar", "progress", "pie", "donut", "waterfall") and w.x and not _is_time(w.x) and not w.color
          and len(w.y) == 1 and w.y[0] in out.columns):
        # Ranking: do maior para o menor quando a IA não pediu outra ordem.
        key = pd.to_numeric(out[w.y[0]], errors="coerce")
        out = out.assign(_ordem=key).sort_values("_ordem", ascending=False, na_position="last").drop(columns="_ordem")
    limit = w.top_n or default_top_n
    if limit and w.kind in ("line", "area") and w.x in out.columns:
        return _limit_time_series(out, w, limit)
    residual_col = _residual_column(out, w)
    if residual_col is not None:
        # "Outros" e "não identificado" vão sempre no fim e nunca são cortados pelo top_n.
        mask = out[residual_col].map(is_residual_label)
        rest, residual = out[~mask], out[mask]
        if limit:
            rest = rest.head(max(limit - len(residual), 1))
        return pd.concat([rest, residual])
    if limit:
        out = out.head(limit)
    return out


def _residual_column(df: pd.DataFrame, w: WidgetSpec) -> str | None:
    """Coluna de categoria de um ranking (barras, participações, lista) que tem linhas residuais."""
    if w.kind not in ("bar", "progress", "table", "pie", "donut", "waterfall"):
        return None
    if w.kind == "table":
        col = next((c for c in (w.columns or list(df.columns))
                    if c in df.columns and not pd.api.types.is_numeric_dtype(df[c])), None)
    else:
        col = w.x
    if not col or col not in df.columns or _is_time(col):
        return None
    return col if df[col].map(is_residual_label).any() else None


def _limit_time_series(out: pd.DataFrame, w: WidgetSpec, limit: int) -> pd.DataFrame:
    """`top_n` numa série temporal limita séries ou períodos, nunca linhas soltas da tabela.

    Com `color`, mantém as N séries de maior valor no período mais recente (sem somar anos:
    janelas de 5 anos não podem ser somadas). Sem `color`, mantém os N períodos mais recentes.
    """
    if not w.color:
        periodos = sorted(out[w.x].dropna().unique())[-limit:]
        return out[out[w.x].isin(periodos)]
    if w.color not in out.columns or len(w.y) != 1 or w.y[0] not in out.columns:
        return out
    ultimo = out[w.x].max()
    ref = out[out[w.x] == ultimo]
    valores = pd.to_numeric(ref[w.y[0]], errors="coerce").groupby(ref[w.color]).max()
    manter = valores.nlargest(limit).index
    return out[out[w.color].isin(manter)]


# --- Figuras Plotly ------------------------------------------------------------------

def _base_layout(height: int = 340, margin: dict | None = None) -> dict:
    return {
        "template": "none",
        "separators": ",.",
        "height": height,
        "margin": margin or {"l": 56, "r": 24, "t": 16, "b": 48},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": FONT_STACK, "size": 12.5, "color": "#5b6b60"},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0,
                   "font": {"size": 12}},
        "hoverlabel": {"bgcolor": HOVER_BG, "bordercolor": HOVER_BG,
                       "font": {"family": FONT_STACK, "color": "#ffffff", "size": 12.5}},
        "bargap": 0.32,
    }


def _style_axes(fig: go.Figure, value_axis: str = "y") -> None:
    common = {"showline": False, "zeroline": False, "ticks": "", "automargin": True,
              "tickfont": {"size": 11.5}, "title_font": {"size": 12}}
    fig.update_xaxes(**common, showgrid=value_axis == "x", gridcolor=GRID_COLOR)
    fig.update_yaxes(**common, showgrid=value_axis == "y", gridcolor=GRID_COLOR)


def _hex_rgba(color: str, alpha: float) -> str:
    c = color.lstrip("#")
    return f"rgba({int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)}, {alpha})"


def _safe_update(trace, **props) -> None:
    """Aplica propriedades que só existem em versões recentes do Plotly, sem quebrar nas antigas."""
    for key, val in props.items():
        try:
            trace.update({key: val})
        except (ValueError, TypeError):
            pass


def _build_kpi_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """Mantida por compatibilidade: a página usa o cartão HTML de `_render_kpi_card`."""
    actual = compute_kpi_value(df, w.column or "", w.agg)
    if actual is None:
        raise ValueError(f"Não foi possível calcular o KPI em {w.dataset_id}.{w.column}.")
    fig = go.Figure(go.Indicator(mode="number", value=actual,
                                 number={"valueformat": ",.1f", "font": {"size": 30, "color": "#2f7d4f"}}))
    fig.update_layout(**_base_layout(height=105, margin={"l": 12, "r": 12, "t": 14, "b": 10}))
    return fig


def _build_bar_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    work = _prepare_slice(df, w)
    horiz = w.orientation == "h"
    if horiz:
        work = work.iloc[::-1]
    cat_col = w.x or ""
    fig = go.Figure()
    single = len(w.y) == 1 and not w.color
    hover_val = "%{x:,.2f}" if horiz else "%{y:,.2f}"
    hover_cat = "%{y}" if horiz else "%{x}"
    unit = f" {w.unit}" if w.unit else ""

    def _add(name, cats, vals, color, show_text):
        tr = go.Bar(
            name=name,
            x=vals if horiz else cats,
            y=cats if horiz else vals,
            orientation="h" if horiz else "v",
            marker={"color": color, "line": {"width": 0}},
            hovertemplate=f"{hover_cat}<br><b>{hover_val}</b>{html.escape(unit)}<extra>{html.escape(str(name))}</extra>",
        )
        if show_text:
            tr.update(text=[format_compact_br(v, w.unit, with_unit=(w.unit or "").strip() == "%") for v in vals],
                      textposition="outside", cliponaxis=False, textfont={"size": 11})
        _safe_update(tr, marker_cornerradius=6)
        fig.add_trace(tr)

    if w.color and len(w.y) == 1:
        y_col = w.y[0]
        for idx, (grp, sub) in enumerate(work.groupby(w.color, sort=False, dropna=False)):
            label = "Não informado" if pd.isna(grp) else display_label(grp, w.color or "")
            _add(label, sub[cat_col].map(lambda v: display_label(v, cat_col)),
                 pd.to_numeric(sub[y_col], errors="coerce"), PALETTE[idx % len(PALETTE)], False)
    else:
        cats = work[cat_col].map(lambda v: display_label(v, cat_col))
        residual = work[cat_col].map(is_residual_label).tolist() if cat_col in work.columns else []
        for idx, y_col in enumerate(w.y):
            color = PALETTE[idx % len(PALETTE)]
            if single and any(residual):  # "Outros"/"não identificado" em cor neutra
                color = [NEUTRAL if r else color for r in residual]
            _add(_label(w, y_col), cats, pd.to_numeric(work[y_col], errors="coerce"),
                 color, single)

    n = len(work)
    height = max(320, 56 + 32 * n) if horiz else 360
    fig.update_layout(
        **_base_layout(height=height, margin={"l": 8, "r": 56 if horiz else 16, "t": 18, "b": 40}),
        barmode=w.barmode,
        showlegend=(len(w.y) > 1 or bool(w.color)),
    )
    axis_label = _axis_title(_label(w, w.y[0]), w.unit) if len(w.y) == 1 else w.unit
    _style_axes(fig, value_axis="x" if horiz else "y")
    if horiz:
        fig.update_xaxes(title_text=axis_label)
        fig.update_yaxes(title_text="", type="category")
    else:
        fig.update_xaxes(title_text=_label(w, cat_col) if not _is_time(cat_col) else "",
                         type=None if _is_time(cat_col) else "category")
        fig.update_yaxes(title_text=axis_label)
        if _is_time(cat_col) and work[cat_col].nunique() <= 12:
            fig.update_xaxes(dtick=1)
    return fig


def _build_line_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    work = _prepare_slice(df, w)
    x_col = w.x or ""
    is_area = w.kind == "area"
    stacked = is_area and w.stacked
    fig = go.Figure()
    unit = f" {w.unit}" if w.unit else ""

    def _add(name, sub, y_col, color):
        xs = sub[x_col]
        ys = pd.to_numeric(sub[y_col], errors="coerce")
        n = len(sub)
        sizes = [0] * max(n - 1, 0) + [9] if n else []
        tr = go.Scatter(
            name=name, x=xs, y=ys,
            mode="lines+markers" if w.markers else "lines",
            line={"color": color, "width": 2.6, "shape": "spline", "smoothing": 0.5},
            marker={"size": sizes, "color": color, "line": {"width": 2, "color": "#ffffff"}},
            hovertemplate=f"<b>%{{y:,.2f}}</b>{html.escape(unit)}<extra>{html.escape(str(name))}</extra>",
        )
        if stacked:
            tr.update(stackgroup="s", fillcolor=_hex_rgba(color, 0.35))
        elif is_area:
            tr.update(fill="tozeroy", fillcolor=_hex_rgba(color, 0.16))
            _safe_update(tr, fillgradient={"type": "vertical",
                                           "colorscale": [[0, _hex_rgba(color, 0.02)], [1, _hex_rgba(color, 0.32)]]})
        fig.add_trace(tr)

    if w.color and len(w.y) == 1:
        for idx, (grp, sub) in enumerate(work.groupby(w.color, sort=False, dropna=False)):
            sub = sub.sort_values(by=x_col, ascending=True, na_position="last")
            label = "Não informado" if pd.isna(grp) else display_label(grp, w.color or "")
            _add(label, sub, w.y[0], PALETTE[idx % len(PALETTE)])
    else:
        for idx, y_col in enumerate(w.y):
            _add(_label(w, y_col), work, y_col, PALETTE[idx % len(PALETTE)])

    fig.update_layout(
        **_base_layout(height=360, margin={"l": 8, "r": 20, "t": 18, "b": 40}),
        showlegend=(len(w.y) > 1 or bool(w.color)),
        hovermode="x unified",
    )
    _style_axes(fig, value_axis="y")
    y_title = _axis_title(_label(w, w.y[0]), w.unit) if len(w.y) == 1 else w.unit
    fig.update_xaxes(title_text="" if _is_time(x_col) else _label(w, x_col))
    if _is_time(x_col) and work[x_col].nunique() <= 12:
        fig.update_xaxes(dtick=1)
    fig.update_yaxes(title_text=y_title)
    if stacked or _starts_at_zero(work, list(w.y)):
        fig.update_yaxes(rangemode="tozero")  # série não negativa: o eixo parte de zero
    return fig


def _build_table_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """Mantida por compatibilidade: a página usa a tabela HTML de `_render_table_html`."""
    work = _prepare_slice(df, w, default_top_n=50)
    cols = w.columns if w.columns else list(work.columns)
    fig = go.Figure(go.Table(
        header={"values": [html.escape(_label(w, c)) for c in cols]},
        cells={"values": [[format_br_value(v, c) for v in work[c].tolist()] for c in cols]},
    ))
    fig.update_layout(**_base_layout(height=max(180, 68 + 30 * min(len(work), 12))))
    return fig


MAX_SLICES = 8
SLICE_LABEL_MIN = 0.06  # rótulo direto só nas fatias com 6% ou mais; as menores ficam na legenda


def _pct_br(v: float) -> str:
    return f"{v:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".") + "%"


def _build_pie_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """Pizza/rosca: até 8 fatias, "Outros" (do SQL) por último em cinza, rótulo direto nas fatias grandes.

    As porcentagens são a parte de cada linha na soma das linhas mostradas; se não houver "Outros",
    o cartão avisa que é a participação entre os itens mostrados (ver `_share_note`)."""
    work = _prepare_slice(df, w)
    y_col = w.y[0]
    cats = work[w.x].map(lambda v: display_label(v, w.x or "")).tolist()
    vals = pd.to_numeric(work[y_col], errors="coerce").fillna(0.0).tolist()
    total = sum(vals) or 1.0
    shares = [v / total for v in vals]
    residual = work[w.x].map(is_residual_label).tolist()
    colors = [NEUTRAL if r else PALETTE[i % len(PALETTE)] for i, r in enumerate(residual)]
    texts = [f"{c}<br>{_pct_br(sh * 100)}" if sh >= SLICE_LABEL_MIN else "" for c, sh in zip(cats, shares)]
    inks = [_ink_on(c) for c in colors]
    custom = [[format_compact_br(v, w.unit), _pct_br(sh * 100)] for v, sh in zip(vals, shares)]
    fig = go.Figure(go.Pie(
        labels=cats, values=vals, sort=False, direction="clockwise", rotation=90,
        hole=0.58 if w.kind == "donut" else 0,
        marker={"colors": colors, "line": {"color": "rgba(255,255,255,0.9)", "width": 1.5}},
        text=texts, textinfo="text", textposition="inside", insidetextorientation="horizontal",
        insidetextfont={"color": inks, "size": 12},
        customdata=custom,
        hovertemplate="<b>%{label}</b><br>%{customdata[0]} · %{customdata[1]}<extra></extra>",
    ))
    small = any(sh < SLICE_LABEL_MIN for sh in shares)
    layout = _base_layout(height=340, margin={"l": 8, "r": 8, "t": 8, "b": 8})
    layout["legend"] = {**layout.get("legend", {}), "orientation": "v", "x": 1.02, "y": 0.5}
    fig.update_layout(**layout, showlegend=small)
    return fig


def _ink_on(hex_color: str) -> str:
    """Texto branco ou quase preto, o que tiver mais contraste (WCAG) com a cor de fundo."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    contraste_branco = 1.05 / (lum + 0.05)
    contraste_escuro = (lum + 0.05) / (0.0137 + 0.05)  # #18271f
    return "#ffffff" if contraste_branco >= contraste_escuro else "#18271f"


def _share_note(w: WidgetSpec, df: pd.DataFrame) -> str:
    """A5: sem linha "Outros", a pizza mostra a participação entre os itens exibidos, não o total."""
    work = _prepare_slice(df, w)
    if work[w.x].map(is_residual_label).any():
        return ""
    return (f'<p class="fallback-note">Participação entre os {len(work)} itens mostrados, '
            "não sobre o total geral.</p>")


def _build_waterfall_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """Variação por item: contribuição de cada item para a variação entre dois períodos.

    O valor de cada barra vem pronto do SQL (a diferença entre os períodos); o total no fim é a soma
    dessas contribuições, e só é permitido para métricas aditivas (o revisor bloqueia as demais)."""
    work = _prepare_slice(df, w)
    y_col = w.y[0]
    cats = work[w.x].map(lambda v: display_label(v, w.x or "")).tolist()
    vals = pd.to_numeric(work[y_col], errors="coerce").fillna(0.0).tolist()
    total = sum(vals)
    fig = go.Figure(go.Waterfall(
        x=[*cats, "Variação total"], y=[*vals, total], measure=["relative"] * len(vals) + ["total"],
        text=[format_compact_br(v, w.unit) for v in [*vals, total]], textposition="outside",
        increasing={"marker": {"color": PALETTE[0]}}, decreasing={"marker": {"color": PALETTE[4]}},
        totals={"marker": {"color": NEUTRAL}}, connector={"line": {"color": "rgba(128,128,128,0.4)", "width": 1}},
        hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>", cliponaxis=False,
    ))
    fig.update_layout(**_base_layout(height=360), showlegend=False)
    _style_axes(fig, value_axis="y")
    fig.update_yaxes(title_text=w.unit)
    return fig


def _render_gauge_card(w: WidgetSpec, df: pd.DataFrame) -> str:
    """Medidor: rosca de um percentual único calculado dos dados (ex.: % do volume para a China)."""
    valor = compute_kpi_value(df, w.column or "", w.agg)
    if valor is None:
        raise ValueError("medidor sem valor")
    pct = max(0.0, min(100.0, float(valor)))
    circ = 2 * math.pi * 42
    filled = circ * pct / 100
    txt = _pct_br(pct)
    subtitle = f'<p class="subtitle">{html.escape(pt_text(w.subtitle))}</p>' if w.subtitle else ""
    return (
        f'<article class="card kpi-card gauge-card" data-widget-id="{html.escape(w.id)}" data-widget-kind="gauge">\n'
        f'  <div class="kpi-top"><h3 class="kpi-label">{html.escape(pt_text(w.title))}</h3></div>\n'
        f'  <div class="gauge" role="img" aria-label="{html.escape(pt_text(w.title))}: {txt}">'
        f'<svg viewBox="0 0 100 100" aria-hidden="true">'
        f'<circle class="gauge-track" cx="50" cy="50" r="42"/>'
        f'<circle class="gauge-fill" cx="50" cy="50" r="42" stroke-dasharray="{filled:.2f} {circ:.2f}" '
        f'transform="rotate(-90 50 50)"/></svg>'
        f'<span class="gauge-value" data-value="{pct:.4f}" title="{html.escape(format_br_value(valor))}%">{txt}</span></div>\n'
        f'  {subtitle}\n'
        f'  <footer class="card-footer">Fonte: {html.escape(w.source)}</footer>\n'
        f'</article>'
    )


def build_widget_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """Constrói a figura Plotly correspondente ao WidgetSpec."""
    if w.kind == "kpi":
        return _build_kpi_figure(w, df)
    if w.kind == "bar":
        return _build_bar_figure(w, df)
    if w.kind in ("pie", "donut"):
        return _build_pie_figure(w, df)
    if w.kind == "waterfall":
        return _build_waterfall_figure(w, df)
    if w.kind in ("line", "area"):
        return _build_line_figure(w, df)
    if w.kind == "table":
        return _build_table_figure(w, df)
    raise ValueError(f"Tipo de componente sem figura Plotly: '{w.kind}'.")


# --- Componentes em HTML -------------------------------------------------------------

def _sparkline_svg(ys: list[float], uid: str, label: str) -> str:
    if len(ys) < 2:
        return ""
    w_, h_, pad = 132, 40, 4
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    step = (w_ - 2 * pad) / (len(ys) - 1)
    pts = [(pad + i * step, h_ - pad - (y - lo) / span * (h_ - 2 * pad)) for i, y in enumerate(ys)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pts[0][0]:.1f},{h_} {line} {pts[-1][0]:.1f},{h_}"
    gid = f"g-{uid}"
    lx, ly = pts[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {w_} {h_}" preserveAspectRatio="none" role="img" '
        f'aria-label="{html.escape(label)}">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="currentColor" stop-opacity=".30"/>'
        f'<stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="{area}" fill="url(#{gid})"/>'
        f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.2" fill="currentColor"/></svg>'
    )


def _uid(w: WidgetSpec) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", w.id) or "w"


def _card_header(w: WidgetSpec) -> str:
    subtitle = f'<p class="subtitle">{html.escape(pt_text(w.subtitle))}</p>' if w.subtitle else ""
    units = list(dict.fromkeys(u for u in w.column_units.values() if u)) if w.kind == "table" else []
    unit_txt = " / ".join(units) if len(units) > 1 else w.unit
    badge = f'<span class="badge">{html.escape(unit_txt)}</span>' if unit_txt else ""
    return (f'<div class="card-header"><div><h3>{html.escape(pt_text(w.title))}</h3>{subtitle}</div>'
            f'{badge}</div>')


def _render_valid_card(w: WidgetSpec, inner_html: str) -> str:
    span_cls = " span-2" if w.span == 2 else ""
    return (
        f'<article class="card chart-card{span_cls}" data-widget-id="{html.escape(w.id)}" '
        f'data-widget-kind="{html.escape(w.kind)}">\n'
        f'  {_card_header(w)}\n'
        f'  <div class="card-body">{inner_html}</div>\n'
        f'  <footer class="card-footer">Fonte: {html.escape(w.source)}</footer>\n'
        f'</article>'
    )


def _render_kpi_card(w: WidgetSpec, df: pd.DataFrame, featured: bool = False) -> str:
    actual = compute_kpi_value(df, w.column or "", w.agg)
    if actual is None:
        raise ValueError(f"Não foi possível calcular o KPI em {w.dataset_id}.{w.column}.")
    exact = format_br_value(actual) + (f" {w.unit}" if w.unit else "")
    # Em contagens o selo já diz a unidade ("municípios"); no número ela só repetiria.
    value_txt = format_compact_br(actual, w.unit, with_unit=(w.unit or "").strip().lower() not in COUNT_UNITS)
    trend = kpi_trend(df, w)
    meta = ""
    if trend:
        delta = ""
        if trend["delta_pct"] is not None:
            d = trend["delta_pct"]
            arrow = "▲" if d > 0 else ("▼" if d < 0 else "■")
            pct = f"{abs(d):,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
            delta = (f'<span class="delta" title="Variação em relação a {html.escape(_fmt_axis_value(trend["prev_x"]))}">'
                     f'{arrow} {pct}% <span class="delta-ref">vs {html.escape(_fmt_axis_value(trend["prev_x"]))}</span></span>')
        label = (f"Série de {_label(w, w.trend_y)} de "
                 f"{_fmt_axis_value(trend['xs'][0])} a {_fmt_axis_value(trend['last_x'])}")
        meta = f'<div class="kpi-meta">{delta}{_sparkline_svg(trend["ys"], _uid(w), label)}</div>'
    subtitle = f'<p class="subtitle">{html.escape(pt_text(w.subtitle))}</p>' if w.subtitle else ""
    badge = f'<span class="badge">{html.escape(w.unit)}</span>' if w.unit else ""
    cls = "card kpi-card is-featured" if featured else "card kpi-card"
    return (
        f'<article class="{cls}" data-widget-id="{html.escape(w.id)}" data-widget-kind="kpi">\n'
        f'  <div class="kpi-top"><h3 class="kpi-label">{html.escape(pt_text(w.title))}</h3>{badge}</div>\n'
        f'  <p class="kpi-value" title="{html.escape(exact)}">{html.escape(value_txt)}</p>\n'
        f'  {meta}{subtitle}\n'
        f'  <footer class="card-footer">Fonte: {html.escape(w.source)}</footer>\n'
        f'</article>'
    )


def _column_header(w: WidgetSpec, col: str) -> str:
    """Rótulo da coluna com a SUA unidade (`column_units`), sem repetir se o rótulo já a traz."""
    label = _label(w, col)
    unit = w.column_units.get(col, "")
    return _axis_title(label, unit) if unit else label


def _render_table_html(w: WidgetSpec, df: pd.DataFrame) -> str:
    work = _prepare_slice(df, w, default_top_n=50)
    cols = [c for c in (w.columns or list(work.columns)) if c in work.columns]
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(work[c]) and not _is_time(c)]
    bar_col = numeric[0] if numeric else None
    max_v = None
    if bar_col is not None:
        vals = pd.to_numeric(work[bar_col], errors="coerce").dropna()
        if not vals.empty and (vals >= 0).all() and vals.max() > 0:
            max_v = float(vals.max())
    head = "".join(
        f'<th scope="col" class="{"num" if c in numeric else ""}">{html.escape(_column_header(w, c))}</th>'
        for c in cols
    )
    rows = []
    for _, row in work.iterrows():
        cells = []
        for c in cols:
            txt = html.escape(format_br_value(row[c], c))
            if c == bar_col and max_v:
                v = pd.to_numeric(pd.Series([row[c]]), errors="coerce").iloc[0]
                pct = 0.0 if pd.isna(v) else max(0.0, min(100.0, float(v) / max_v * 100))
                cells.append(f'<td class="num has-bar"><span class="databar" style="width:{pct:.1f}%"></span>'
                             f'<span class="cell-v">{txt}</span></td>')
            else:
                cells.append(f'<td class="{"num" if c in numeric else ""}">{txt}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (f'<div class="table-wrap" tabindex="0" role="region" aria-label="{html.escape(pt_text(w.title))}">'
            f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _render_progress_html(w: WidgetSpec, df: pd.DataFrame) -> str:
    x_col, y_col = w.x or "", w.y[0]
    work = _prepare_slice(df, w)
    vals_all = pd.to_numeric(df[y_col], errors="coerce")
    name = y_col.lower()
    pct_like = any(h in name for h in PCT_HINTS) or (w.unit or "").strip() == "%"
    if pct_like:
        scale = 100.0 if vals_all.max(skipna=True) <= 1.0 else 1.0
        note = ""
    else:
        total = float(vals_all[vals_all > 0].sum())
        if total <= 0:
            raise ValueError(f"Sem total positivo em {w.dataset_id}.{y_col} para calcular participações.")
        scale = 100.0 / total
        n_rows = int((vals_all > 0).sum())
        note = (f'<p class="note">Percentual sobre a soma de {html.escape(_label(w, y_col))} '
                f'nas {n_rows} linhas de [{html.escape(w.dataset_id)}], não sobre o total geral.</p>')
    rows = []
    cap = min(w.top_n or 10, 10)
    if len(work) > cap:  # mantém "Outros" (já no fim) dentro do limite de 10 linhas
        res_mask = work[x_col].map(is_residual_label) if x_col in work.columns else pd.Series(False, index=work.index)
        work = pd.concat([work[~res_mask].head(max(cap - int(res_mask.sum()), 1)), work[res_mask]])
    for idx, (_, row) in enumerate(work.iterrows()):
        v = pd.to_numeric(pd.Series([row[y_col]]), errors="coerce").iloc[0]
        if pd.isna(v):
            continue
        pct = float(v) * scale
        pct_txt = f"{pct:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
        value_txt = "" if pct_like else f'<span class="prog-v">{html.escape(format_compact_br(v, w.unit))}</span>'
        color = NEUTRAL if is_residual_label(row[x_col]) else (PALETTE[idx % len(PALETTE)] if idx < 3 else PALETTE[0])
        rows.append(
            f'<li><div class="prog-row"><span class="prog-label">{html.escape(display_label(row[x_col], x_col))}</span>'
            f'{value_txt}<span class="prog-pct">{pct_txt}%</span></div>'
            f'<div class="prog-track" role="presentation"><span class="prog-fill" '
            f'style="width:{max(0.0, min(100.0, pct)):.1f}%;background:{color}"></span></div></li>'
        )
    return f'<ol class="progress-list">{"".join(rows)}</ol>{note}'


def _render_warning_card(w: WidgetSpec, reason: str) -> str:
    """Cartão de aviso: só quando realmente não há dado para mostrar."""
    span_cls = " span-2" if w.span == 2 else ""
    title = html.escape(pt_text(w.title) or "Gráfico do painel")
    return (
        f'<article class="card card-warning{span_cls}" data-widget-id="{html.escape(w.id)}">\n'
        f'  <div class="card-header">\n'
        f'    <div>\n'
        f'      <span class="badge badge-warn">{_icon("aviso", "icon-sm")} {NO_DATA_TITLE}</span>\n'
        f'      <h3>{title}</h3>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'  <p class="warn-text">{html.escape(reason)}</p>\n'
        f'</article>'
    )



def _plan_groups(widgets, by_id):
    """B2: componentes com o mesmo `group` (ex.: barras e linha) ficam juntos, na largura total, na seção
    do primeiro, e com o mesmo intervalo de tempo no eixo x. Cada um mantém a sua unidade."""
    members: dict[str, list] = {}
    for w in widgets:
        if w.group and w.kind in ("bar", "line", "area"):
            members.setdefault(w.group, []).append(w)
    members = {g: ws for g, ws in members.items() if len(ws) > 1}
    ordered, seen = [], set()
    ranges, sections = {}, {}
    for w in widgets:
        g = w.group if w.group in members else None
        if g is None:
            ordered.append(w)
            continue
        if g in seen:
            continue
        seen.add(g)
        sections[g] = SECTION_OF.get(members[g][0].kind, "evolucao")
        xs = []
        for m in members[g]:
            m.span = 2
            ds = by_id.get(m.dataset_id)
            if ds is not None and m.x in ds.df.columns:
                xs.extend(pd.to_numeric(ds.df[m.x], errors="coerce").dropna().tolist())
        if xs:
            ranges[g] = [min(xs) - 0.5, max(xs) + 0.5]
        ordered.extend(members[g])
    return ordered, ranges, sections

def _render_fallback(w: WidgetSpec, by_id: dict[str, DatasetResult], codes: list[str]) -> str:
    """Gráfico reprovado: mostra os MESMOS dados como lista, com uma frase simples do motivo.

    A lista só exibe as linhas que vieram da consulta (não soma nem cria valores), então não fere as
    regras R5. O texto técnico do revisor nunca chega aqui (ver `messages.user_message`)."""
    reason = user_message(codes)
    ds = by_id.get(w.dataset_id)
    if ds is None or ds.df.empty or "sem_dados" in codes:
        return _render_warning_card(w, user_message(["sem_dados"]))
    df = ds.df
    wanted = list(w.columns) if w.kind == "table" else [c for c in [w.x, *w.y, w.column, w.color] if c]
    cols = [c for c in dict.fromkeys(wanted) if c in df.columns] or list(df.columns)
    lista = replace(w, kind="table", columns=cols, sort_by=w.sort_by if w.sort_by in df.columns else None,
                    valid=True, validation_error=None, validation_codes=[])
    note = f'<p class="fallback-note">{html.escape(reason)} {SHOWN_AS_LIST}</p>'
    return _render_valid_card(lista, note + _render_table_html(lista, df))


# --- Página --------------------------------------------------------------------------

_CDN_SCRIPT_RE = re.compile(r'<script\b[^>]*\bsrc="https://cdn\.plot\.ly/[^"]+"[^>]*>\s*</script>')


def _plotly_loader(plotlyjs: str) -> str:
    """Tag que carrega o Plotly uma única vez no <head>, antes de qualquer gráfico."""
    if plotlyjs == "inline":
        from plotly.offline import get_plotlyjs
        return f'<script type="text/javascript">{get_plotlyjs()}</script>'
    # Mesma URL (versão e integridade) que o próprio Plotly usaria.
    match = _CDN_SCRIPT_RE.search(go.Figure().to_html(full_html=False, include_plotlyjs="cdn"))
    if match is None:  # pragma: no cover - depende do formato interno do Plotly
        raise RuntimeError("Não foi possível obter a tag do Plotly por CDN.")
    return match.group(0)


def render_dashboard_html(
    spec: DashboardSpec,
    datasets: list[DatasetResult],
    *,
    question: str = "",
    plotlyjs: str = "inline",
    theme: str | None = None,
) -> str:
    """Renderiza o dashboard completo numa página HTML única.

    plotlyjs: "inline" (padrão, página 100% offline) ou "cdn" (arquivo menor, carrega o Plotly da
    internet). O Plotly é carregado uma vez no <head>: as seções reordenam os cartões, então o
    primeiro gráfico do JSON nem sempre é o primeiro da página. theme: None (segue o sistema e a
    escolha salva), "light" ou "dark".
    """
    if plotlyjs not in ("inline", "cdn"):
        raise ValueError(f"plotlyjs deve ser 'inline' ou 'cdn', não {plotlyjs!r}.")
    by_id = {d.dataset_id: d for d in datasets}
    cards: dict[str, list[str]] = {sid: [] for sid, _ in SECTIONS}
    needs_plotly = False
    first_kpi = True

    ordered, group_ranges, group_section = _plan_groups(spec.widgets, by_id)
    for w in ordered:
        section = group_section.get(w.group or "", SECTION_OF.get(w.kind, "detalhamento"))
        note = ""
        if w.kind in ("pie", "donut") and w.valid and w.dataset_id in by_id and w.x in by_id[w.dataset_id].df.columns:
            n_partes = len(_prepare_slice(by_id[w.dataset_id].df, w))
            if n_partes > MAX_SLICES:
                # Pizza com muitas fatias fica ilegível; "Outros" só pode vir do SQL, então vira barras.
                w = replace(w, kind="bar", orientation="h")
                note = ('<p class="fallback-note">Com mais de 8 partes a pizza fica difícil de ler, '
                        "então mostrei em barras.</p>")
            else:
                note = _share_note(w, by_id[w.dataset_id].df)
        blocking = [i for i in validate_widget_deterministic(w, by_id) if i.blocking]
        if not w.valid or blocking:
            codes = list(w.validation_codes) or [i.code for i in blocking]
            cards[section].append(_render_fallback(w, by_id, codes))
            continue
        df = by_id[w.dataset_id].df
        try:
            if w.kind == "kpi":
                cards[section].append(_render_kpi_card(w, df, featured=first_kpi))
                first_kpi = False
            elif w.kind == "gauge":
                cards[section].append(_render_gauge_card(w, df))
            elif w.kind == "table":
                cards[section].append(_render_valid_card(w, _render_table_html(w, df)))
            elif w.kind == "progress":
                cards[section].append(_render_valid_card(w, _render_progress_html(w, df)))
            else:
                fig = build_widget_figure(w, df)
                if w.group in group_ranges:  # mesmo intervalo de tempo nos gráficos do par
                    fig.update_xaxes(range=group_ranges[w.group], dtick=1 if _is_time(w.x) else None)
                fig_html = fig.to_html(
                    full_html=False,
                    include_plotlyjs=False,
                    config={"responsive": True, "displaylogo": False,
                            "modeBarButtons": [["toImage"]], "toImageButtonOptions": {"scale": 2}},
                )
                needs_plotly = True
                aria = html.escape(pt_text(w.title) + (f". {pt_text(w.subtitle)}" if w.subtitle else ""))
                cards[section].append(_render_valid_card(
                    w, f'{note}<div class="plot-wrap" role="img" aria-label="{aria}">{fig_html}</div>'))
        except Exception:
            logger.exception("Falha ao desenhar o componente %s", w.id)
            cards[section].append(_render_fallback(w, by_id, []))

    page_title = html.escape(pt_text(spec.title) or (f"Dashboard — {question}" if question else "Dashboard Trase"))
    short_title = page_title if len(page_title) <= 48 else page_title[:46].rstrip() + "…"
    # Subtítulo em até 2 linhas; o texto completo fica em "Rastreabilidade".
    full_subtitle = pt_text(spec.subtitle)
    hero_sub = short_subtitle(full_subtitle)
    page_subtitle = f'<p class="hero-subtitle">{html.escape(hero_sub)}</p>' if hero_sub else ""
    scope_notes = (f'<div class="scope-notes"><strong>Notas do recorte</strong><p>{html.escape(full_subtitle)}</p></div>'
                   if full_subtitle and full_subtitle != hero_sub else "")
    question_banner = (
        f'<div class="question-pill"><strong>Pergunta:</strong> {html.escape(question)}</div>' if question else ""
    )
    top_warnings = ""
    if spec.warnings:
        items = "".join(f"<li>{html.escape(pt_text(msg))}</li>" for msg in spec.warnings)
        top_warnings = (f'<section class="banner-warn" aria-label="Avisos">{_icon("aviso")}'
                        f'<div><strong>Avisos</strong><ul>{items}</ul></div></section>')

    nav_items, sections_html = [], []
    for sid, label in SECTIONS:
        if not cards[sid]:
            continue
        nav_items.append(f'<a href="#{sid}" data-section="{sid}">{_icon(sid)}<span>{label}</span></a>')
        grid = "kpi-grid" if sid == "visao-geral" else "chart-grid"
        sections_html.append(
            f'<section class="dash-section" id="{sid}" aria-labelledby="{sid}-h">\n'
            f'  <h2 class="section-title" id="{sid}-h">{label}</h2>\n'
            f'  <div class="{grid}">\n{chr(10).join(cards[sid])}\n  </div>\n</section>'
        )
    nav_items.append(f'<a href="#rastreabilidade" data-section="rastreabilidade">{_icon("rastreabilidade")}'
                     f'<span>Rastreabilidade</span></a>')
    if not sections_html:
        sections_html.append('<section class="empty-state">' + _icon("visao-geral", "icon-lg")
                             + '<p>Nenhum componente visual pôde ser gerado para esta consulta.</p></section>')

    queries_items = []
    for d in datasets:
        queries_items.append(
            f'<div class="query-item">'
            f'<div class="query-head"><div><strong>[{html.escape(d.dataset_id)}]</strong> {html.escape(d.source_label)} '
            f'<span class="meta">({len(d.df)} linhas · {d.seconds}s)</span></div>'
            f'<button type="button" class="btn-ghost" data-copy>Copiar</button></div>'
            f'<pre><code>{html.escape(d.query_summary)}</code></pre>'
            f'</div>'
        )
    queries_html = "\n".join(queries_items) or "<p class='meta'>Nenhuma consulta registrada.</p>"
    theme_attr = f' data-theme="{theme}"' if theme in ("light", "dark") else ""
    plotly_head = _plotly_loader(plotlyjs) if needs_plotly else ""

    return f"""<!doctype html>
<html lang="pt-BR"{theme_attr}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<script>
(function () {{
  var d = document.documentElement, t = null;
  if (d.getAttribute("data-theme")) return;
  try {{ t = localStorage.getItem("trase-dash-theme"); }} catch (e) {{}}
  if (t !== "light" && t !== "dark") {{
    t = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
  }}
  d.setAttribute("data-theme", t);
}})();
</script>
<style>
{PAGE_CSS}
</style>
{plotly_head}
</head>
<body>
<a class="skip" href="#conteudo">Pular para o conteúdo</a>
<div class="shell">
  <aside class="sidebar">
    <div class="brand">{_icon("logo", "icon-logo")}<span>Trase · Painel</span></div>
    <p class="side-title" title="{page_title}">{short_title}</p>
    <nav aria-label="Seções do painel">
      {"".join(nav_items)}
    </nav>
    <div class="side-bottom">
      <button type="button" class="theme-toggle" id="theme-toggle" aria-pressed="false">
        {_icon("tema")}<span class="theme-label">Tema escuro</span>
      </button>
      <p class="side-foot">Dados: Trase</p>
    </div>
  </aside>
  <main id="conteudo">
    <header class="hero">
      <div class="hero-text">
        <span class="eyebrow">Painel analítico</span>
        <h1>{page_title}</h1>
        {page_subtitle}
        {question_banner}
      </div>
      <span class="source-pill">Fonte: Trase</span>
    </header>
    {top_warnings}
    {chr(10).join(sections_html)}
    <details class="provenance" id="rastreabilidade">
      <summary>Rastreabilidade: consultas SQL e fontes de dados</summary>
      {scope_notes}
      {queries_html}
    </details>
    <footer class="page-footer">
      Dados: Trase (CC BY 4.0). Exposição ao desmatamento é uma associação estatística e não prova ilegalidade.
    </footer>
  </main>
</div>
<script>
(function () {{
  var d = document.documentElement, btn = document.getElementById("theme-toggle");
  function sync() {{
    var dark = d.getAttribute("data-theme") === "dark";
    btn.setAttribute("aria-pressed", dark ? "true" : "false");
    btn.querySelector(".theme-label").textContent = dark ? "Tema claro" : "Tema escuro";
  }}
  btn.addEventListener("click", function () {{
    var next = d.getAttribute("data-theme") === "dark" ? "light" : "dark";
    d.setAttribute("data-theme", next);
    try {{ localStorage.setItem("trase-dash-theme", next); }} catch (e) {{}}
    sync();
  }});
  sync();
  document.querySelectorAll("[data-copy]").forEach(function (b) {{
    b.addEventListener("click", function () {{
      var code = b.closest(".query-item").querySelector("code");
      try {{
        navigator.clipboard.writeText(code.textContent).then(function () {{
          b.textContent = "Copiado"; setTimeout(function () {{ b.textContent = "Copiar"; }}, 1500);
        }});
      }} catch (e) {{}}
    }});
  }});
  if ("IntersectionObserver" in window) {{
    var links = {{}};
    document.querySelectorAll(".sidebar nav a").forEach(function (a) {{ links[a.dataset.section] = a; }});
    var obs = new IntersectionObserver(function (entries) {{
      entries.forEach(function (e) {{
        if (e.isIntersecting && links[e.target.id]) {{
          Object.keys(links).forEach(function (k) {{ links[k].classList.remove("is-active"); }});
          links[e.target.id].classList.add("is-active");
        }}
      }});
    }}, {{ rootMargin: "-30% 0px -60% 0px" }});
    document.querySelectorAll(".dash-section, #rastreabilidade").forEach(function (s) {{ obs.observe(s); }});
  }}
}})();
</script>
</body>
</html>
"""

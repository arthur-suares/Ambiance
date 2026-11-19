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

# E3: paleta derivada do assunto (floresta, petróleo, terracota, oliva, ameixa). Cada cor tem contraste
# >= 3:1 no fundo claro (#ffffff) e no escuro (#1b1f1b); "Outros" usa o cinza quente NEUTRAL e o ocre
# ACCENT é o único acento (máximo anotado, item ativo). Nunca só cor: há rótulo direto, forma ou posição.
PALETTE = [
    "#3f8a5c",  # floresta
    "#3d8789",  # petróleo
    "#c4643f",  # terracota
    "#7f8f36",  # oliva
    "#8f7a9c",  # ameixa
]
ACCENT = "#b5832a"


NEUTRAL = "#8f8a7c"  # cinza quente para "Outros" e "não identificado"

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
/* Sistema de design dos painéis (ver docs/dashboard_visual.md).
   Tipografia: fontes do sistema, escala 12/13/14/16/20/28/36 px; números em tabular-nums.
   Espaço: múltiplos de 4 px (--s1..--s8). Raio: 6 px (controles) e 8 px (cartões). Linhas de 1 px, sem sombras.
   Cores: terrosas, um único acento (ocre); séries com contraste >= 3:1 nos dois temas. */
:root {
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 40px; --s8: 48px;
  --r-sm: 6px; --r-md: 8px;
  --t-xs: 12px; --t-sm: 13px; --t-md: 14px; --t-lg: 16px; --t-xl: 20px; --t-2xl: 28px; --t-3xl: 36px;
  --bg: #f6f5f0; --panel: #ffffff; --panel-2: #f1efe8; --fg: #1e231f; --muted: #5d6259; --border: #e2dfd5;
  --line: #d6d2c6; --accent: #b5832a; --accent-soft: #f5ecd9; --brand: #3f8a5c;
  --chart-text: #555a52; --track: #ebe8df; --icon: #3f8a5c;
  --warn-bg: #fbf3e2; --warn-border: #e2c88f; --warn-fg: #6e4a0c; --focus: #b5832a; --code-bg: #f6f5f0;
  color-scheme: light;
}
:root[data-theme="dark"] {
  --bg: #121512; --panel: #1b1f1b; --panel-2: #222722; --fg: #eceee7; --muted: #a9ada2; --border: #2c322c;
  --line: #3a413a; --accent: #d1a04a; --accent-soft: #2c2618; --brand: #7cc596;
  --chart-text: #b3b7ac; --track: #2a302a; --icon: #7cc596;
  --warn-bg: #2a2416; --warn-border: #5e4c22; --warn-fg: #ecd29a; --focus: #d1a04a; --code-bg: #121512;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: var(--t-md)/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: var(--r-sm); }
.skip { position: absolute; left: -999px; top: var(--s2); background: var(--panel); color: var(--fg); padding: var(--s2) var(--s3); border-radius: var(--r-sm); z-index: 10; }
.skip:focus { left: var(--s3); }
.icon { width: 18px; height: 18px; flex-shrink: 0; }
.icon-sm { width: 14px; height: 14px; vertical-align: -2px; }
.icon-lg { width: 40px; height: 40px; color: var(--muted); }
.icon-logo { width: 22px; height: 22px; color: var(--brand); }

/* Estrutura */
.shell { display: grid; grid-template-columns: 220px minmax(0, 1fr); min-height: 100vh; }
.sidebar {
  position: sticky; top: 0; height: 100vh; overflow-y: auto; background: var(--panel); color: var(--fg);
  border-right: 1px solid var(--border); padding: var(--s5) var(--s3); display: flex; flex-direction: column; gap: var(--s4);
}
.brand { display: flex; align-items: center; gap: var(--s2); font-weight: 700; font-size: var(--t-md); padding: 0 var(--s2); }
.side-title { margin: 0; padding: 0 var(--s2); color: var(--muted); font-size: var(--t-xs); line-height: 1.4; }
.sidebar nav { display: flex; flex-direction: column; gap: 2px; }
.sidebar nav a {
  display: flex; align-items: center; gap: var(--s2); padding: var(--s2); border-radius: var(--r-sm);
  color: var(--muted); text-decoration: none; font-weight: 500; font-size: var(--t-sm);
}
.sidebar nav a:hover { color: var(--fg); background: var(--panel-2); }
.sidebar nav a.is-active { color: var(--fg); background: var(--panel-2); font-weight: 650; }
.sidebar nav a.is-active .icon { color: var(--accent); }
.side-bottom { margin-top: auto; display: flex; flex-direction: column; gap: var(--s2); }
.theme-toggle {
  display: flex; align-items: center; gap: var(--s2); width: 100%; padding: var(--s2); border-radius: var(--r-sm);
  border: 1px solid var(--border); background: transparent; color: var(--fg); font: inherit; font-size: var(--t-sm); cursor: pointer;
}
.theme-toggle:hover { background: var(--panel-2); }
.side-foot { margin: 0; padding: 0 var(--s2); color: var(--muted); font-size: var(--t-xs); }

main { padding: var(--s6) var(--s7) var(--s8); max-width: 1280px; width: 100%; }

/* Cabeçalho: texto direto sobre o fundo, sem cartão nem degradê */
.hero { margin-bottom: var(--s6); }
.hero-top { display: flex; justify-content: space-between; align-items: baseline; gap: var(--s4); }
.eyebrow { font-size: var(--t-xs); font-weight: 650; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); }
.source-pill { flex-shrink: 0; color: var(--muted); font-size: var(--t-xs); }
h1 { font-size: var(--t-2xl); line-height: 1.2; margin: var(--s1) 0 var(--s2); letter-spacing: -.3px; font-weight: 700; max-width: 900px; }
.hero-subtitle { margin: 0 0 var(--s3); color: var(--muted); max-width: 820px; font-size: var(--t-md); }
.question-pill { font-size: var(--t-sm); color: var(--muted); }
.question-pill strong { color: var(--fg); font-weight: 600; }

.banner-warn {
  display: flex; gap: var(--s3); align-items: flex-start; background: var(--warn-bg); border: 1px solid var(--warn-border);
  color: var(--warn-fg); border-radius: var(--r-md); padding: var(--s3) var(--s4); margin-bottom: var(--s5); font-size: var(--t-sm);
}
.banner-warn ul { margin: var(--s1) 0 0; padding-left: var(--s4); }

/* Seções */
.dash-section { margin-bottom: var(--s7); scroll-margin-top: var(--s4); }
.section-title {
  font-size: var(--t-xs); font-weight: 700; letter-spacing: .8px; text-transform: uppercase; color: var(--muted);
  margin: 0 0 var(--s3); padding-bottom: var(--s2); border-bottom: 1px solid var(--line);
}
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--s4); }
.span-2 { grid-column: 1 / -1; }

/* C1: fileira de indicadores (sem cartões), separados por linhas finas */
.kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--s5) 0;
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--s5) 0; }
.kpi { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: var(--s3); align-items: start;
  padding: 0 var(--s5); border-left: 1px solid var(--border); min-width: 0; }
.kpi:first-child { border-left: 0; }
.kpi-icon { width: 36px; height: 36px; color: var(--icon); margin-top: 2px; }
.kpi-label { margin: 0; font-size: var(--t-sm); font-weight: 500; color: var(--muted); line-height: 1.35; }
.kpi-value { margin: var(--s1) 0 0; font-size: var(--t-2xl); font-weight: 750; letter-spacing: -.5px; line-height: 1.1;
  color: var(--fg); font-variant-numeric: tabular-nums; white-space: nowrap; }
.kpi.is-featured .kpi-value { font-size: var(--t-3xl); }
.kpi-delta { margin: var(--s1) 0 0; font-size: var(--t-xs); color: var(--muted); font-variant-numeric: tabular-nums;
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--s2); }
.kpi-delta .delta { color: var(--fg); font-weight: 650; }
.delta-ref { font-weight: 400; color: var(--muted); }
.spark { width: 72px; height: 20px; color: var(--icon); flex-shrink: 0; }
.kpi-note { margin: var(--s1) 0 0; font-size: var(--t-xs); color: var(--muted); }
.kpi-source { margin: var(--s1) 0 0; font-size: 11px; color: var(--muted); }
.kpi-gauge { width: 56px; height: 56px; }
.kpi-gauge svg { width: 100%; height: 100%; display: block; }
.gauge-track { fill: none; stroke: var(--track); stroke-width: 9; }
.gauge-fill { fill: none; stroke: var(--brand); stroke-width: 9; }

/* Cartões de gráfico */
.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--s4) var(--s5) var(--s3);
  display: flex; flex-direction: column; min-width: 0;
}
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--s3); margin-bottom: var(--s2); }
.card-header h3 { font-size: var(--t-lg); font-weight: 650; margin: 0; line-height: 1.35; }
.subtitle { margin: 2px 0 0; color: var(--muted); font-size: var(--t-sm); }
.badge { flex-shrink: 0; color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0 var(--s2);
  font-size: 11px; font-weight: 600; line-height: 20px; white-space: nowrap; }
/* C3: gráficos menores com título pequeno, em maiúsculas e centralizado */
.card.is-compact .card-header { position: relative; justify-content: center; text-align: center; padding: 0 var(--s7); }
.card.is-compact .card-header h3 { font-size: var(--t-sm); font-weight: 700; letter-spacing: .6px; text-transform: uppercase; }
.card.is-compact .card-header .badge { position: absolute; right: 0; top: 0; }
.card.is-compact .subtitle { font-size: var(--t-xs); }
.card-body { flex: 1; min-width: 0; }
.card-footer { border-top: 1px solid var(--border); margin-top: var(--s2); padding-top: var(--s2); font-size: var(--t-xs); color: var(--muted); }
.fallback-note { margin: 0 0 var(--s2); font-size: var(--t-sm); color: var(--muted); }
.scope-notes { font-size: var(--t-sm); color: var(--muted); margin: var(--s2) 0 var(--s3); }
.scope-notes p { margin: var(--s1) 0 0; }

.plot-wrap { width: 100%; }
/* Rótulos dentro das fatias usam a cor escolhida pelo contraste com a fatia (ver _ink_on). */
.js-plotly-plot .plotly .main-svg text:not(.slicetext) { fill: var(--chart-text) !important; }
.js-plotly-plot .plotly .main-svg .annotation-text { fill: var(--fg) !important; }
.js-plotly-plot .plotly .main-svg .hoverlayer text { fill: #ffffff !important; }
.js-plotly-plot .plotly .modebar { background: transparent !important; }
.js-plotly-plot .plotly .modebar-btn path { fill: var(--muted) !important; }

/* Tabela */
.table-wrap { max-height: 440px; overflow: auto; border: 1px solid var(--border); border-radius: var(--r-sm); }
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--t-sm); font-variant-numeric: tabular-nums; }
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--panel-2); color: var(--muted); text-align: left;
  font-size: 11px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase; padding: var(--s2) var(--s3); border-bottom: 1px solid var(--line);
}
tbody td { padding: var(--s2) var(--s3); border-bottom: 1px solid var(--border); }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: var(--panel-2); }
th.num, td.num { text-align: right; }
td.has-bar { position: relative; }
.databar { position: absolute; right: 0; top: 7px; bottom: 7px; background: var(--accent-soft); border-radius: 2px 0 0 2px; }
.cell-v { position: relative; }

/* Participações em lista */
.progress-list { list-style: none; margin: var(--s1) 0 0; padding: 0; display: flex; flex-direction: column; gap: var(--s3); }
.prog-row { display: flex; align-items: baseline; gap: var(--s2); margin-bottom: var(--s1); font-size: var(--t-sm); }
.prog-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 550; }
.prog-v { color: var(--muted); font-size: var(--t-xs); font-variant-numeric: tabular-nums; }
.prog-pct { font-weight: 700; font-variant-numeric: tabular-nums; min-width: 52px; text-align: right; }
.prog-track { height: 6px; border-radius: 2px; background: var(--track); overflow: hidden; }
.prog-fill { display: block; height: 100%; border-radius: 2px; }
.note { margin: var(--s3) 0 0; color: var(--muted); font-size: var(--t-xs); }

.card-warning { background: var(--warn-bg); border-color: var(--warn-border); }
.badge-warn { display: inline-flex; align-items: center; gap: var(--s1); color: var(--warn-fg); border-color: var(--warn-border); margin-bottom: var(--s2); }
.warn-text { margin: var(--s1) 0 2px; color: var(--warn-fg); font-size: var(--t-sm); }
.empty-state { text-align: center; padding: var(--s8) var(--s4); color: var(--muted); background: var(--panel); border: 1px dashed var(--line); border-radius: var(--r-md); margin-bottom: var(--s5); }

details.provenance { background: var(--panel); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--s3) var(--s5); scroll-margin-top: var(--s4); }
details.provenance summary { cursor: pointer; font-weight: 600; color: var(--fg); font-size: var(--t-sm); }
.query-item { margin-top: var(--s3); padding-top: var(--s3); border-top: 1px solid var(--border); }
.query-head { display: flex; justify-content: space-between; align-items: center; gap: var(--s3); font-size: var(--t-sm); }
.query-item pre { margin: var(--s2) 0 0; padding: var(--s2) var(--s3); background: var(--code-bg); border: 1px solid var(--border); border-radius: var(--r-sm); overflow-x: auto; }
.query-item code { font-size: var(--t-xs); white-space: pre-wrap; word-break: break-word; }
.btn-ghost { border: 1px solid var(--border); background: transparent; color: var(--fg); border-radius: var(--r-sm); padding: 2px var(--s3); font: inherit; font-size: var(--t-xs); cursor: pointer; }
.btn-ghost:hover { background: var(--panel-2); }
.meta { color: var(--muted); font-size: var(--t-xs); }
.page-footer { margin-top: var(--s5); color: var(--muted); font-size: var(--t-xs); }

@media (max-width: 900px) {
  .shell { grid-template-columns: minmax(0, 1fr); }
  .sidebar { position: sticky; top: 0; z-index: 5; height: auto; flex-direction: row; align-items: center; gap: var(--s2);
    padding: var(--s2) var(--s3); overflow-x: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  .brand span, .side-title, .side-foot { display: none; }
  .sidebar nav { flex-direction: row; }
  .sidebar nav a { white-space: nowrap; }
  .sidebar nav a span { display: none; }
  .side-bottom { margin: 0 0 0 auto; }
  .theme-toggle .theme-label { display: none; }
  main { padding: var(--s4) var(--s4) var(--s6); }
  h1 { font-size: var(--t-xl); }
  .chart-grid { grid-template-columns: minmax(0, 1fr); }
  .kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi-value { white-space: normal; }
  h1, .hero-subtitle { overflow-wrap: anywhere; }
  .kpi { border-left: 0; padding: 0 var(--s4); }
  .kpi-value, .kpi.is-featured .kpi-value { font-size: var(--t-xl); }
  .span-2 { grid-column: auto; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } * { transition: none !important; } }
@media print {
  .sidebar, .theme-toggle, .btn-ghost, .skip { display: none !important; }
  .shell { grid-template-columns: 1fr; }
  body { background: #ffffff; }
  .card, details.provenance, .kpi-strip { break-inside: avoid; }
}
"""
FONT_STACK = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
GRID_COLOR = "rgba(128, 124, 112, 0.16)"
HOVER_BG = "#1e231f"
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
    "m-volume": '<path d="M3 8l9-4 9 4-9 4-9-4Z"/><path d="M3 12l9 4 9-4"/><path d="M3 16l9 4 9-4"/>',
    "m-area": '<path d="M12 21V11"/><path d="M12 11c0-4 3-7 7-7 0 4-3 7-7 7Z"/><path d="M12 14c0-3-2-5-6-5 0 3 2 5 6 5Z"/>',
    "m-dinheiro": '<circle cx="12" cy="12" r="8.5"/><path d="M14.5 9.2c-.5-.8-1.4-1.2-2.5-1.2-1.5 0-2.5.8-2.5 1.9 0 2.6 5 1.4 5 4.2 0 1.1-1.1 1.9-2.6 1.9-1.1 0-2-.4-2.5-1.2M12 6.5V8m0 8v1.5"/>',
    "m-nuvem": '<path d="M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6 11a3.5 3.5 0 0 0 1 7Z"/>',
    "m-parte": '<path d="M12 3a9 9 0 1 0 9 9h-9V3Z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15V3.5Z"/>',
    "m-local": '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11Z"/><circle cx="12" cy="10" r="2.3"/>',
    "m-grafico": '<path d="M4 20h16"/><path d="M7 16v-5M12 16V7M17 16v-8"/>',
}


def _metric_icon(w: WidgetSpec) -> str:
    """Ícone da medida do indicador, pela unidade ou pelo nome da coluna."""
    unit = (w.unit or "").strip().lower()
    col = (w.column or "").lower()
    if unit in ("%",) or "pct" in col or "share" in col or "particip" in col:
        return "m-parte"
    if "us$" in unit or "r$" in unit or "fob" in col or "usd" in col:
        return "m-dinheiro"
    if "co2" in unit or "co2" in col or "emiss" in col:
        return "m-nuvem"
    if unit == "ha" or "expos" in col or "defor" in col or "desmat" in col:
        return "m-area"
    if unit in ("t", "kt", "mi t") or "volume" in col or "tonel" in col:
        return "m-volume"
    if unit in COUNT_UNITS:
        return "m-local"
    return "m-grafico"


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
        "font": {"family": FONT_STACK, "size": 12, "color": "#555a52"},
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


def _short_num(v: float) -> str:
    """Número curto para marcas de eixo, no mesmo padrão do painel: 500 · 2,5 mil · 10 mi · 1,5 bi."""
    a = abs(v)
    for scale, suf in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if a >= scale:
            txt = _br_number(v / scale, 1)
            return txt + suf
    return _br_number(v, 0 if a >= 10 or float(v).is_integer() else 1)


def _nice_step(span: float, target: int = 4) -> float:
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _br_ticks(fig: go.Figure, axis: str, values) -> None:
    """Marcas do eixo de valor com texto em pt-BR (o Plotly só abrevia em inglês: 5M, 1B)."""
    vals = [float(v) for v in pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()]
    if not vals:
        return
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    step = _nice_step(hi - lo)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 0.001:
        ticks.append(round(t, 10))
        t += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    upd = {"tickmode": "array", "tickvals": ticks, "ticktext": [_short_num(x) for x in ticks]}
    (fig.update_xaxes if axis == "x" else fig.update_yaxes)(**upd)


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
        _safe_update(tr, marker_cornerradius=3)
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
    _br_ticks(fig, "x" if horiz else "y", [v for y_col in w.y for v in pd.to_numeric(work[y_col], errors="coerce")])
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

    series: list[tuple[str, pd.Series, pd.Series, str]] = []

    def _add(name, sub, y_col, color):
        xs = sub[x_col]
        ys = pd.to_numeric(sub[y_col], errors="coerce")
        dash = LINE_DASHES[len(series) % len(LINE_DASHES)]
        tr = go.Scatter(
            name=name, x=xs, y=ys,
            mode="lines+markers" if (w.markers and not is_area) else "lines",
            # Linha reta (sem suavizar): a curva suavizada passava acima e abaixo dos valores reais.
            line={"color": color, "width": 2.2, "dash": "solid" if is_area else dash},
            marker={"size": 8, "symbol": "circle-open", "color": color, "line": {"width": 2, "color": color}},
            hovertemplate=f"<b>%{{y:,.2f}}</b>{html.escape(unit)}<extra>{html.escape(str(name))}</extra>",
        )
        if stacked:
            tr.update(stackgroup="s", fillcolor=_hex_rgba(color, 0.45))
        elif is_area:
            tr.update(fill="tozeroy", fillcolor=_hex_rgba(color, 0.14))
        fig.add_trace(tr)
        series.append((str(name), xs, ys, color))

    if w.color and len(w.y) == 1:
        for idx, (grp, sub) in enumerate(work.groupby(w.color, sort=False, dropna=False)):
            sub = sub.sort_values(by=x_col, ascending=True, na_position="last")
            label = "Não informado" if pd.isna(grp) else display_label(grp, w.color or "")
            _add(label, sub, w.y[0], PALETTE[idx % len(PALETTE)])
    else:
        for idx, y_col in enumerate(w.y):
            _add(_label(w, y_col), work, y_col, PALETTE[idx % len(PALETTE)])

    direct = not stacked and 1 <= len(series) <= 6
    _direct_line_labels(fig, series, w, single=len(series) == 1)
    fig.update_layout(
        **_base_layout(height=360, margin={"l": 8, "r": 112 if (direct and len(series) > 1) else 56,
                                           "t": 24, "b": 40}),
        showlegend=not direct and (len(w.y) > 1 or bool(w.color)),
        hovermode="x unified",
    )
    _style_axes(fig, value_axis="y")
    y_title = _axis_title(_label(w, w.y[0]), w.unit) if len(w.y) == 1 else w.unit
    fig.update_xaxes(title_text="" if _is_time(x_col) else _label(w, x_col))
    if _is_time(x_col) and work[x_col].nunique() <= 12:
        fig.update_xaxes(dtick=1)
    anos = pd.to_numeric(work[x_col], errors="coerce").dropna() if _is_time(x_col) else pd.Series(dtype=float)
    if not anos.empty:
        # Só os anos que existem nos dados: o rótulo do fim da linha fica na margem, não estica o eixo.
        fig.update_xaxes(range=[anos.min() - 0.4, anos.max() + 0.4])
    fig.update_yaxes(title_text=y_title)
    if stacked or _starts_at_zero(work, list(w.y)):
        fig.update_yaxes(rangemode="tozero")  # série não negativa: o eixo parte de zero
    if stacked:
        totais = work.assign(_v=pd.to_numeric(work[w.y[0]], errors="coerce")).groupby(x_col)["_v"].sum()
        _br_ticks(fig, "y", totais.tolist())
    else:
        _br_ticks(fig, "y", [v for _n, _x, ys, _c in series for v in ys.tolist()])
    return fig


LINE_DASHES = ("solid", "dash", "dot", "dashdot")


def _direct_line_labels(fig: go.Figure, series, w: WidgetSpec, *, single: bool) -> None:
    """E4: rótulo no fim de cada linha (nome e último valor) em vez de legenda; numa série única,
    anota também o ponto máximo. Poucos pontos (até 8): valor escrito em cada ponto (C4)."""
    if not series or len(series) > 6 or w.stacked:
        return
    for name, xs, ys, color in series:
        valid = ys.notna()
        if not valid.any():
            continue
        x_last, y_last = xs[valid].iloc[-1], ys[valid].iloc[-1]
        txt = format_compact_br(y_last, w.unit, with_unit=False)
        fig.add_annotation(x=x_last, y=y_last, text=txt if single else f"{html.escape(name)} · {txt}",
                           showarrow=False, xanchor="left", xshift=8, font={"size": 11.5, "color": color})
    if not single:
        return
    name, xs, ys, color = series[0]
    valid = ys.notna()
    if valid.sum() <= 8:
        fig.data[0].update(mode="lines+markers+text", textposition="top center", textfont={"size": 11},
                           text=[format_compact_br(v, w.unit, with_unit=False) if pd.notna(v) else "" for v in ys])
        return
    i_max = ys[valid].idxmax()
    if i_max != ys[valid].index[-1]:
        x_max, y_max = xs.loc[i_max], ys.loc[i_max]
        fig.add_annotation(x=x_max, y=y_max, ax=0, ay=-28, arrowhead=0, arrowwidth=1, arrowcolor=ACCENT,
                           text=f"máx. {_fmt_axis_value(x_max)}: {format_compact_br(y_max, w.unit, with_unit=False)}",
                           font={"size": 11, "color": ACCENT})


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
        increasing={"marker": {"color": PALETTE[0]}}, decreasing={"marker": {"color": PALETTE[2]}},
        totals={"marker": {"color": NEUTRAL}}, connector={"line": {"color": "rgba(128,128,128,0.4)", "width": 1}},
        hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>", cliponaxis=False,
    ))
    fig.update_layout(**_base_layout(height=360), showlegend=False)
    _style_axes(fig, value_axis="y")
    fig.update_yaxes(title_text=w.unit)
    acumulado = pd.Series([*vals, 0.0]).cumsum().tolist()
    _br_ticks(fig, "y", [*acumulado, total])
    return fig


def _render_gauge_card(w: WidgetSpec, df: pd.DataFrame) -> str:
    """Medidor (B3) na fileira de indicadores: rosca pequena no lugar do ícone e o % ao lado."""
    valor = compute_kpi_value(df, w.column or "", w.agg)
    if valor is None:
        raise ValueError("medidor sem valor")
    pct = max(0.0, min(100.0, float(valor)))
    circ = 2 * math.pi * 40
    filled = circ * pct / 100
    txt = _pct_br(pct)
    note = f'<p class="kpi-note">{html.escape(pt_text(w.subtitle))}</p>' if w.subtitle else ""
    return (
        f'<article class="kpi kpi-gauge-item" data-widget-id="{html.escape(w.id)}" data-widget-kind="gauge">\n'
        f'  <div class="kpi-gauge gauge" role="img" aria-label="{html.escape(pt_text(w.title))}: {txt}">'
        f'<svg viewBox="0 0 100 100" aria-hidden="true">'
        f'<circle class="gauge-track" cx="50" cy="50" r="40"/>'
        f'<circle class="gauge-fill" cx="50" cy="50" r="40" stroke-dasharray="{filled:.2f} {circ:.2f}" '
        f'transform="rotate(-90 50 50)"/></svg></div>\n'
        f'  <div class="kpi-body">\n'
        f'    <h3 class="kpi-label">{html.escape(pt_text(w.title))}</h3>\n'
        f'    <p class="kpi-value"><span class="gauge-value" data-value="{pct:.4f}" '
        f'title="{html.escape(format_br_value(valor))}%">{txt}</span></p>\n'
        f'    {note}\n'
        f'    <p class="kpi-source">Fonte: {html.escape(w.source)}</p>\n'
        f'  </div>\n'
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
    lx, ly = pts[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {w_} {h_}" preserveAspectRatio="none" role="img" '
        f'aria-label="{html.escape(label)}">'
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


COMPACT_KINDS = ("pie", "donut", "progress")


def _is_compact(w: WidgetSpec) -> bool:
    """C3: gráficos menores (pizza, rosca, participações, ranking curto em meia largura) usam título
    pequeno, em maiúsculas e centralizado."""
    return w.span != 2 and (w.kind in COMPACT_KINDS or (w.kind == "bar" and w.orientation == "h"))


def _render_valid_card(w: WidgetSpec, inner_html: str) -> str:
    span_cls = " span-2" if w.span == 2 else ""
    span_cls += " is-compact" if _is_compact(w) else ""
    return (
        f'<article class="card chart-card{span_cls}" data-widget-id="{html.escape(w.id)}" '
        f'data-widget-kind="{html.escape(w.kind)}">\n'
        f'  {_card_header(w)}\n'
        f'  <div class="card-body">{inner_html}</div>\n'
        f'  <footer class="card-footer">Fonte: {html.escape(w.source)}</footer>\n'
        f'</article>'
    )


def _render_kpi_card(w: WidgetSpec, df: pd.DataFrame, featured: bool = False) -> str:
    """C1: ícone grande à esquerda, rótulo pequeno, número grande e, embaixo, a variação calculada dos
    dados ("+11,2% vs 2021"). Sem período anterior, não há linha de variação."""
    actual = compute_kpi_value(df, w.column or "", w.agg)
    if actual is None:
        raise ValueError(f"Não foi possível calcular o KPI em {w.dataset_id}.{w.column}.")
    exact = format_br_value(actual) + (f" {w.unit}" if w.unit else "")
    # Em contagens o rótulo já diz a unidade ("municípios"); no número ela só repetiria.
    count_unit = (w.unit or "").strip().lower() in COUNT_UNITS
    value_txt = format_compact_br(actual, w.unit, with_unit=not count_unit)
    trend = kpi_trend(df, w)
    delta = ""
    if trend and trend["delta_pct"] is not None:
        d = trend["delta_pct"]
        sinal = "+" if d > 0 else ("−" if d < 0 else "")
        pct = f"{abs(d):,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
        ref = html.escape(_fmt_axis_value(trend["prev_x"]))
        label = (f"Série de {_label(w, w.trend_y)} de "
                 f"{_fmt_axis_value(trend['xs'][0])} a {_fmt_axis_value(trend['last_x'])}")
        delta = (f'<p class="kpi-delta"><span class="delta" title="Variação em relação a {ref}">'
                 f'{sinal}{pct}% <span class="delta-ref">vs {ref}</span></span>'
                 f'{_sparkline_svg(trend["ys"], _uid(w), label)}</p>')
    rotulo = pt_text(w.title) + (f" ({w.unit})" if count_unit and w.unit and w.unit.lower() not in pt_text(w.title).lower() else "")
    note = f'<p class="kpi-note">{html.escape(pt_text(w.subtitle))}</p>' if w.subtitle else ""
    cls = "kpi is-featured" if featured else "kpi"
    return (
        f'<article class="{cls}" data-widget-id="{html.escape(w.id)}" data-widget-kind="kpi">\n'
        f'  {_icon(_metric_icon(w), "kpi-icon")}\n'
        f'  <div class="kpi-body">\n'
        f'    <h3 class="kpi-label">{html.escape(rotulo)}</h3>\n'
        f'    <p class="kpi-value" title="{html.escape(exact)}" data-value="{actual}">{html.escape(value_txt)}</p>\n'
        f'    {delta}{note}\n'
        f'    <p class="kpi-source">Fonte: {html.escape(w.source)}</p>\n'
        f'  </div>\n'
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



MAIN_KINDS = ("line", "area", "bar", "waterfall")


def _main_chart_ids(widgets, group_section) -> set[str]:
    """E5: em cada seção de gráficos, o primeiro de linha/área/barras/variação é o principal
    (largura total); os demais ficam em meia largura, alinhados à grade."""
    seen: set[str] = set()
    out: set[str] = set()
    for w in widgets:
        sec = group_section.get(w.group or "", SECTION_OF.get(w.kind, "detalhamento"))
        if sec in ("visao-geral", "detalhamento") or sec in seen or w.kind not in MAIN_KINDS:
            continue
        seen.add(sec)
        out.add(w.id)
    return out


def _final_spans(widgets, group_section, main_ids) -> dict[str, int]:
    """Largura final de cada cartão de gráfico: o principal da seção ocupa a largura toda e um cartão
    de meia largura que ficaria sozinho na linha (seguido de um de largura toda, ou no fim) também."""
    por_secao: dict[str, list] = {}
    for w in widgets:
        sec = group_section.get(w.group or "", SECTION_OF.get(w.kind, "detalhamento"))
        if sec != "visao-geral":
            por_secao.setdefault(sec, []).append(w)
    spans: dict[str, int] = {}
    for ws in por_secao.values():
        base = [2 if (w.id in main_ids or w.span == 2) else 1 for w in ws]
        col = 0
        for i, w in enumerate(ws):
            span = base[i]
            if span == 1 and col == 0 and (i + 1 == len(ws) or base[i + 1] == 2):
                span = 2
            spans[w.id] = span
            col = 0 if span == 2 else (col + 1) % 2
    return spans


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
    spans = _final_spans(ordered, group_section, _main_chart_ids(ordered, group_section))
    for w in ordered:
        if spans.get(w.id, w.span) != w.span:
            w = replace(w, span=spans[w.id])  # E5: principal na largura toda; nenhum cartão sozinho pela metade
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
        grid = "kpi-strip" if sid == "visao-geral" else "chart-grid"
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
      <div class="hero-top"><span class="eyebrow">Painel analítico</span><span class="source-pill">Fonte: Trase</span></div>
      <h1>{page_title}</h1>
      {page_subtitle}
      {question_banner}
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

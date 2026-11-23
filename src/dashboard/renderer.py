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

from src.dashboard.messages import (
    EMPTY_PAGE_TITLE,
    EMPTY_SUGGESTIONS,
    ERROR_MESSAGE,
    ERROR_PAGE_TITLE,
    NO_DATA_HINT,
    NO_DATA_TITLE,
    PROGRESS_STEPS,
    SHOWN_AS_LIST,
    is_residual_label,
    plain_labels,
    short_subtitle,
    user_message,
)
from src.dashboard.interaction import MOTION_CSS, MOTION_JS, card_actions, csv_template, period_filter, view_switch
from src.dashboard.law_agent import LAW_FOOTER
from src.dashboard.place_names import place_name_pt
from src.dashboard.reviewer_agent import validate_widget_deterministic
from src.dashboard.schemas import (
    LAWS_DATABASE,
    LAWS_SOURCE,
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
    "#4f7cac",  # azul-rio
]
ACCENT = "#b5832a"
# H1: ordem das cores nas fatias, para que vizinhas (inclusive a última com a primeira) nunca tenham
# tons quase iguais: floresta, terracota, petróleo, ameixa, oliva, azul-rio.
PIE_ORDER = (0, 2, 1, 4, 3, 5)


NEUTRAL = "#8f8a7c"  # cinza quente para "Outros" e "não identificado"

# Colunas que guardam o país de destino. Nelas, BRAZIL é soja processada no próprio Brasil
# (consumo doméstico), e não uma exportação.
DESTINATION_COLUMNS = {"country_of_first_import", "country_of_destination", "pais_destino", "destino"}


# H2: nomes de empresas e municípios em formato de título só na tela ("RIO VERDE" -> "Rio Verde"),
# mantendo siglas. Os dados continuam como vieram.
ACRONYMS = frozenset({
    "ADM", "COFCO", "LDC", "BRF", "JBS", "CHS", "CJ", "ALZ", "CGG", "BTG", "SLC", "GTA", "BR", "SA", "S.A.",
    "LTDA", "LTDA.", "EIRELI", "ME", "EPP", "CO", "CO.", "LLC", "INC", "INC.", "AG", "BV", "NV", "GMBH", "PLC",
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "EUA", "UE", "II", "III", "IV",
})
_SMALL_WORDS = frozenset({"de", "da", "do", "das", "dos", "e", "d'", "del", "la", "of", "and", "y"})
_NAME_DIMENSIONS = ("municipio", "empresa", "importador")


def title_case_name(text: str) -> str:
    """"LOUIS DREYFUS COMPANY" -> "Louis Dreyfus Company"; "ADM" e "COFCO" ficam como estão."""
    out = []
    for i, tok in enumerate(str(text).split(" ")):
        core = tok.strip("()[],;")
        if not core:
            out.append(tok)
        elif core.upper() in ACRONYMS or (len(core) <= 4 and core.isalpha() and not re.search(r"[AEIOUÁÉÍÓÚÂÊÔÃÕY]", core.upper())):
            out.append(tok.upper())
        elif i > 0 and core.lower() in _SMALL_WORDS:
            out.append(tok.lower())
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in tok.split("-")))
    return " ".join(out)


def _is_name_column(col_name: str) -> bool:
    from src.dashboard.dimensions import DIMENSIONS, column_matches

    return any(column_matches(col_name, DIMENSIONS[k]) for k in _NAME_DIMENSIONS) if col_name else False


def display_label(value, col_name: str = "") -> str:
    """Rótulo para a TELA: como `csv_label` e, além disso, países e biomas em português
    ("CHINA (MAINLAND)" -> "China", "MATA ATLANTICA" -> "Mata Atlântica"). Os dados não mudam."""
    pt = place_name_pt(value) if not (isinstance(value, float) and pd.isna(value)) else None
    return pt if pt is not None else csv_label(value, col_name)


def csv_label(value, col_name: str = "") -> str:
    """Rótulo para exibição e para o CSV baixado: "BRAZIL" vira "BRASIL" (com a ressalva em coluna de
    destino), rótulos técnicos como UNKNOWN ou PROCESSED DOMESTICALLY viram português simples e nomes
    de empresas e municípios em maiúsculas viram formato de título (H2). Nomes de países continuam
    como vieram nos dados (a tradução é só da tela)."""
    text = str(value)
    if text.strip().upper() == "BRAZIL":
        return "BRASIL (processamento doméstico)" if col_name.lower() in DESTINATION_COLUMNS else "BRASIL"
    plain = plain_labels(text)
    if plain != text and plain[:1].islower():
        plain = plain[:1].upper() + plain[1:]
    if plain == text and text.isupper() and _is_name_column(col_name):
        plain = title_case_name(text)
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
  /* Títulos em serifa do próprio sistema (nada é baixado): dá o tom de relatório, não de painel SaaS. */
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Charter, Georgia, serif;
  --ease: cubic-bezier(.2, .7, .2, 1);
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
.hero-top { border-top: 3px solid var(--fg); padding-top: var(--s2); }
.eyebrow { font-size: var(--t-xs); font-weight: 650; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); }
.source-pill { flex-shrink: 0; color: var(--muted); font-size: var(--t-xs); }
h1 { font-family: var(--serif); font-size: 34px; line-height: 1.12; margin: var(--s3) 0 var(--s3); letter-spacing: -.4px;
  font-weight: 600; max-width: 900px; text-wrap: balance; }
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
  position: relative; font-family: var(--serif); font-size: var(--t-xl); font-weight: 600; letter-spacing: -.1px;
  color: var(--fg); margin: 0 0 var(--s4); padding-bottom: var(--s2); border-bottom: 1px solid var(--line);
}
/* Fio ocre curto sobre a linha da seção: a marca visual do painel. */
.section-title::after { content: ""; position: absolute; left: 0; bottom: -1px; width: 48px; height: 2px;
  background: var(--accent); transform-origin: left center; }
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
.card-header h3 { font-family: var(--serif); font-size: 18px; font-weight: 600; margin: 0; line-height: 1.3; text-wrap: balance; }
.subtitle { margin: 2px 0 0; color: var(--muted); font-size: var(--t-sm); }
.badge { flex-shrink: 0; color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0 var(--s2);
  font-size: 11px; font-weight: 600; line-height: 20px; white-space: nowrap; }
/* C3: gráficos menores com título pequeno, em maiúsculas e centralizado */
.card.is-compact .card-header { position: relative; justify-content: center; text-align: center; padding: 0 var(--s7); }
.card.is-compact .card-header h3 { font-size: var(--t-sm); font-weight: 700; letter-spacing: .6px; text-transform: uppercase; }
.card.is-compact .subtitle { font-size: var(--t-xs); }
.card-body { flex: 1; min-width: 0; }
.card-footer { border-top: 1px solid var(--border); margin-top: var(--s2); padding-top: var(--s2); font-size: var(--t-xs); color: var(--muted); }
.fallback-note { margin: 0 0 var(--s2); font-size: var(--t-sm); color: var(--muted); }
.scope-notes { font-size: var(--t-sm); color: var(--muted); margin: var(--s2) 0 var(--s3); }
.scope-notes p { margin: var(--s1) 0 0; }

.plot-wrap { width: 100%; }
/* Rótulos dentro das fatias usam a cor escolhida pelo contraste com a fatia (ver _ink_on). */
/* H1: rótulos das fatias ficam fora da fatia, então também seguem o tema. */
.js-plotly-plot .plotly .main-svg text { fill: var(--chart-text) !important; }
.js-plotly-plot .plotly .main-svg .slicetext { fill: var(--fg) !important; }
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
.warn-hint { margin: 0; color: var(--warn-fg); font-size: var(--t-xs); }

/* F1-F3: conclusão calculada, "Como ler" e rodapé de publicação */
.card-titles { min-width: 0; }
.conclusion { margin: var(--s1) 0 0; font-size: var(--t-md); line-height: 1.45; color: var(--fg); font-variant-numeric: tabular-nums; }
.card-tools { display: flex; align-items: center; gap: var(--s2); flex-shrink: 0; }
.card.is-compact .card-header .card-tools { position: absolute; right: 0; top: 0; }
.help { position: relative; }
.help summary {
  list-style: none; cursor: pointer; width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--line);
  display: grid; place-items: center; font-size: var(--t-xs); font-weight: 700; color: var(--muted); user-select: none;
}
.help summary::-webkit-details-marker { display: none; }
.help summary:hover, .help[open] summary { color: var(--fg); border-color: var(--muted); }
.help-body {
  position: absolute; right: 0; top: 28px; z-index: 4; width: min(320px, 80vw); text-align: left; text-transform: none;
  letter-spacing: 0; background: var(--panel); color: var(--fg); border: 1px solid var(--line); border-radius: var(--r-md);
  padding: var(--s3) var(--s4); font-size: var(--t-sm); font-weight: 400; line-height: 1.5;
}
.help-body ul { margin: var(--s1) 0 0; padding-left: var(--s4); }
.help-body li + li { margin-top: var(--s1); }
.card-footer { display: flex; flex-wrap: wrap; gap: 2px var(--s3); }
.foot-period::before { content: "·"; margin-right: var(--s3); color: var(--muted); }
.foot-limit { flex-basis: 100%; color: var(--muted); }
details.data-view { margin-top: var(--s2); }
details.data-view summary {
  cursor: pointer; display: inline-block; font-size: var(--t-xs); font-weight: 600; color: var(--fg);
  padding: 2px var(--s2); border: 1px solid var(--border); border-radius: var(--r-sm);
}
details.data-view summary:hover { background: var(--panel-2); }
details.data-view .table-wrap { margin-top: var(--s2); max-height: 280px; }

/* G4: artigos-chave (citação literal + fonte) */
.quote-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--s3); }
.quote { margin: 0; padding: var(--s3) var(--s4); border: 1px solid var(--border); border-radius: var(--r-md); background: var(--panel-2); }
.quote blockquote { margin: 0; font-size: var(--t-sm); line-height: 1.55; color: var(--fg); }
.quote figcaption { margin-top: var(--s2); font-size: var(--t-xs); color: var(--muted); }
.quote a, td a { color: var(--fg); text-underline-offset: 2px; }
.law-note { color: var(--muted); }

/* F4: estados */
.state { background: var(--panel); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--s6) var(--s5); margin-bottom: var(--s5); color: var(--fg); }
.empty-state, .error-state { text-align: center; }
.state-title { margin: var(--s2) 0; font-size: var(--t-lg); font-weight: 650; display: flex; align-items: center; justify-content: center; gap: var(--s2); }
.state-detail, .state-lead { margin: var(--s2) 0 0; color: var(--muted); font-size: var(--t-sm); }
.state-tips { display: inline-block; text-align: left; margin: var(--s2) 0 0; padding-left: var(--s5); color: var(--fg); font-size: var(--t-sm); }
.error-state .icon-lg { color: var(--warn-fg); }
.error-state p { color: var(--muted); margin: 0 auto; max-width: 520px; }
.state-loading .state-title { justify-content: flex-start; }
.state-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
.state-steps { list-style: none; margin: var(--s3) 0 0; padding: 0; display: flex; flex-direction: column; gap: var(--s2); font-size: var(--t-sm); color: var(--muted); }
.state-steps li { padding-left: var(--s5); position: relative; }
.state-steps li::before { content: ""; position: absolute; left: 4px; top: 7px; width: 7px; height: 7px; border-radius: 50%; border: 1px solid var(--line); }
.state-steps li.is-current { color: var(--fg); font-weight: 600; }
.state-steps li.is-current::before { background: var(--accent); border-color: var(--accent); }
.state-steps li.is-done::before { background: var(--brand); border-color: var(--brand); }
.state-page main { max-width: 640px; margin: 0 auto; padding: var(--s7) var(--s4); }

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
/* Embutido no chat: o painel vira parte da conversa (sem barra lateral, sem rolagem própria, fundo do chat). */
.is-embed body { background: transparent; }
.is-embed .shell { display: block; min-height: 0; }
.is-embed .sidebar, .is-embed .skip, .is-embed .question-pill { display: none; }
.is-embed main { padding: var(--s2) 0 var(--s4); max-width: none; }
.is-embed .hero { margin-bottom: var(--s5); }
.is-embed h1 { font-size: 28px; }
/* Na largura do chat cabem menos indicadores por linha; o número nunca invade o vizinho. */
.is-embed .kpi-strip { grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }
.is-embed .kpi-value { font-size: 24px; }
.is-embed .kpi.is-featured .kpi-value { font-size: 30px; }
@media (max-width: 900px) { .is-embed main { padding: var(--s2) 0 var(--s4); } .is-embed h1 { font-size: 23px; } }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { transition: none !important; animation: none !important; }
}
/* F6: impressão e PDF — sempre no tema claro, sem controles, com os valores finais e o rodapé de cada cartão */
@media print {
  @page { margin: 14mm; }
  :root, :root[data-theme="dark"] {
    --bg: #ffffff; --panel: #ffffff; --panel-2: #f4f3ee; --fg: #111411; --muted: #45493f; --border: #cfcabd;
    --line: #bdb8aa; --chart-text: #33372f; --track: #e6e2d8; --icon: #2f6e48; --brand: #2f6e48; --accent: #8a6015;
    --warn-bg: #ffffff; --warn-border: #bdb8aa; --warn-fg: #4f3608; color-scheme: light;
  }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  html, body { background: #ffffff !important; color: var(--fg); }
  .sidebar, .theme-toggle, .btn-ghost, .skip, .help, details.data-view, .modebar-container, .js-plotly-plot .modebar { display: none !important; }
  .shell { display: block; }
  main { padding: 0; max-width: none; }
  .hero { margin-bottom: var(--s4); }
  .dash-section { margin-bottom: var(--s5); }
  .card, .kpi, .kpi-strip, details.provenance, .state { break-inside: avoid; page-break-inside: avoid; }
  .section-title { break-after: avoid; page-break-after: avoid; }
  .chart-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .span-2 { grid-column: 1 / -1; }
  .kpi-value { white-space: normal; }
  details.provenance:not([open]) { display: none; }
  .table-wrap { max-height: none; overflow: visible; }
  thead th { position: static; }
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
    ("base-legal", "Base legal"),  # G6: leis em seção própria, separada dos dados do Trase
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
    "base-legal": '<path d="M12 4v16M7 20h10"/><path d="M5 8h14"/><path d="M5 8l-2.5 6a3 3 0 0 0 5 0L5 8Z"/>'
                  '<path d="M19 8l-2.5 6a3 3 0 0 0 5 0L19 8Z"/>',
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
    if ul.startswith("r$"):
        resto = u[2:].strip()
        return f"R$ {text}" + (f" {resto}" if resto else "")
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
    if step < 1 and all(v.is_integer() for v in vals):
        step = 1.0  # H4: contagem (normas, municípios) não tem marca fracionária
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


def _exact_br(v, unit: str = "") -> str:
    """Valor exato legível para o balão: inteiro acima de mil (1.890.651 t), 2 casas abaixo disso."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    if math.isnan(n):
        return ""
    txt = f"{n:,.0f}" if abs(n) >= 1000 else f"{n:,.2f}"
    txt = txt.replace(",", "§").replace(".", ",").replace("§", ".")
    if unit.endswith("$"):  # moeda vem antes: US$ 6.100.000.000
        return f"{unit} {txt}"
    return f"{txt} {unit}".strip()


def _hover_values(vals, unit: str) -> list[str]:
    """Balão em português simples: valor arredondado como no gráfico e, entre parênteses, o exato."""
    out = []
    for v in vals:
        curto = format_compact_br(v, unit)
        try:
            grande = abs(float(v)) >= 1000
        except (TypeError, ValueError):
            grande = False
        exato = _exact_br(v, unit) if grande else ""
        out.append(f"{curto} ({exato})" if exato and exato != curto else curto)
    return out


def _drop_lone_series_name(fig: go.Figure) -> None:
    """Com uma série só, o nome dela ao lado do balão ("Volume") só confunde: o título já diz o que é."""
    if len(fig.data) == 1 and fig.data[0].hovertemplate:
        fig.data[0].hovertemplate = re.sub(r"<extra>.*?</extra>", "<extra></extra>", fig.data[0].hovertemplate)


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
            customdata=_hover_values(vals, (w.unit or "").strip()),
            hovertemplate=f"<b>{hover_cat}</b><br>%{{customdata}}<extra>{html.escape(str(name))}</extra>",
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
    # H4: a unidade fica só no selo do cartão; o eixo diz a medida.
    axis_label = _label(w, w.y[0]) if len(w.y) == 1 else ""
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
            customdata=_hover_values(ys, (w.unit or "").strip()),
            hovertemplate=f"<b>%{{x}}</b><br>%{{customdata}}<extra>{html.escape(str(name))}</extra>",
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
    # H4: a unidade fica só no selo do cartão; o eixo diz a medida.
    y_title = _label(w, w.y[0]) if len(w.y) == 1 else ""
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
    colors = pie_colors(residual)
    # H1: todo rótulo fica FORA da fatia, com linha-guia e o mesmo tamanho (12 px); a cor do texto segue o
    # tema (CSS). Assim a fatia pequena também tem rótulo e a legenda, que repetia as fatias, sai.
    texts = [f"{c} · {_pct_br(sh * 100)}" for c, sh in zip(cats, shares)]
    custom = [[format_compact_br(v, w.unit), _pct_br(sh * 100)] for v, sh in zip(vals, shares)]
    fig = go.Figure(go.Pie(
        labels=cats, values=vals, sort=False, direction="clockwise", rotation=90,
        hole=0.58 if w.kind == "donut" else 0,
        marker={"colors": colors, "line": {"color": "rgba(255,255,255,0.9)", "width": 1.5}},
        text=texts, textinfo="text", textposition="outside", automargin=True,
        outsidetextfont={"size": 12, "color": "#555a52"},
        customdata=custom,
        hovertemplate="<b>%{label}</b><br>%{customdata[0]} · %{customdata[1]}<extra></extra>",
    ))
    layout = _base_layout(height=360, margin={"l": 24, "r": 24, "t": 24, "b": 24})
    fig.update_layout(**layout, showlegend=False)
    return fig


def pie_colors(residual: list[bool]) -> list[str]:
    """Cores das fatias na ordem PIE_ORDER; "Outros"/"não identificado" em cinza neutro."""
    out, k = [], 0
    for r in residual:
        if r:
            out.append(NEUTRAL)
        else:
            out.append(PALETTE[PIE_ORDER[k % len(PIE_ORDER)]])
            k += 1
    return out


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


def _safe_url(url) -> str | None:
    u = str(url or "").strip()
    return u if re.match(r"https?://[^\s\"'<>]+$", u) else None


def _source_link(url) -> str:
    """Link da norma (só http/https); o texto diz o site, nunca o endereço cru."""
    u = _safe_url(url)
    if u is None:
        return "—"
    site = "Planalto" if "planalto.gov.br" in u else re.sub(r"^https?://(?:www\.)?([^/]+).*$", r"\1", u)
    return (f'<a href="{html.escape(u)}" target="_blank" rel="noopener noreferrer">'
            f'ver no {html.escape(site)}</a>')


def _render_quote_html(w: WidgetSpec, df: pd.DataFrame) -> str:
    """G4: cartões de "artigo-chave": a citação literal (conferida no texto), a norma, o artigo e o link."""
    itens = []
    for _, row in df.head(8).iterrows():
        cit = str(row.get("citacao_literal") or "").strip()
        if not cit:
            continue
        ref = ", ".join(t for t in (str(row.get("lei") or ""), str(row.get("artigo") or "")) if t)
        itens.append(f'<figure class="quote"><blockquote>“{html.escape(cit)}”</blockquote>'
                     f'<figcaption>{html.escape(ref)} · {_source_link(row.get("url_fonte"))}</figcaption></figure>')
    return f'<div class="quote-list">{"".join(itens)}</div>'


def _build_range_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """G4: faixa de valor de cada artigo (do mínimo ao máximo), numa única unidade. Nada é somado."""
    lo_col, hi_col = w.y[0], w.y[-1]
    work = df.copy()
    lo = pd.to_numeric(work[lo_col], errors="coerce")
    hi = pd.to_numeric(work[hi_col], errors="coerce")
    lo, hi = lo.fillna(hi), hi.fillna(lo)
    labels = work[w.x].astype(str).tolist()
    # A unidade já está no selo e no eixo: o rótulo da barra traz só os números.
    textos = [_short_num(a) if a == b else f"{_short_num(a)} a {_short_num(b)}" for a, b in zip(lo, hi)]
    usa_log = bool((lo > 0).all() and hi.max() / max(lo.min(), 1e-9) > 1000)
    largura = [max(b - a, (b * 0.02 if b else 1)) for a, b in zip(lo, hi)]
    fig = go.Figure(go.Bar(
        y=labels, x=largura, base=lo.tolist(), orientation="h", marker={"color": PALETTE[2]},
        text=textos, textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(height=max(220, 64 + 44 * len(labels)),
                                     margin={"l": 8, "r": 120, "t": 8, "b": 40}), showlegend=False)
    _style_axes(fig, value_axis="x")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title_text="escala logarítmica" if usa_log else "",
                     type="log" if usa_log else "linear")
    if usa_log:  # só as potências de 10, em pt-BR ("100", "10 mil", "1 mi")
        k0, k1 = int(math.floor(math.log10(lo.min()))), int(math.ceil(math.log10(hi.max())))
        vals = [10 ** k for k in range(k0, k1 + 1)]
        fig.update_xaxes(tickvals=vals, ticktext=[_short_num(v) for v in vals])
    else:
        _br_ticks(fig, "x", [*lo.tolist(), *hi.tolist(), 0])
    return fig


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
    fig.update_yaxes(title_text="")  # H4: unidade no selo
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
        f'    <p class="kpi-source">{_kpi_source(w, df)}</p>\n'
        f'  </div>\n'
        f'</article>'
    )


def build_widget_figure(w: WidgetSpec, df: pd.DataFrame) -> go.Figure:
    """Constrói a figura Plotly correspondente ao WidgetSpec."""
    if w.kind == "kpi":
        return _build_kpi_figure(w, df)
    if w.kind == "bar":
        fig = _build_bar_figure(w, df)
        _drop_lone_series_name(fig)
        return fig
    if w.kind in ("pie", "donut"):
        return _build_pie_figure(w, df)
    if w.kind == "waterfall":
        return _build_waterfall_figure(w, df)
    if w.kind == "range":
        return _build_range_figure(w, df)
    if w.kind in ("line", "area"):
        fig = _build_line_figure(w, df)
        _drop_lone_series_name(fig)
        return fig
    if w.kind == "table":
        return _build_table_figure(w, df)
    raise ValueError(f"Tipo de componente sem figura Plotly: '{w.kind}'.")


# --- Parte F: leitura para leigos ------------------------------------------------------
# Frase-conclusão, "Como ler" e rodapé saem do DataFrame e de textos fixos. O LLM não escreve
# nenhum número nem nenhuma destas frases; nada aqui soma anos.

_EXPOSURE_RE = re.compile(r"expos|deforest|desmat", re.IGNORECASE)
_EMISSION_RE = re.compile(r"co2|emiss", re.IGNORECASE)
_STABLE_PCT = 1.0  # variação menor que 1% conta como "ficou estável"


def _is_exposure(col: str) -> bool:
    return bool(_EXPOSURE_RE.search(col or ""))


def _is_five_year(col: str) -> bool:
    """Exposição e emissões do Trase usam janelas de 5 anos (ver CAVEATS)."""
    return bool(_EXPOSURE_RE.search(col or "") or _EMISSION_RE.search(col or ""))


def _is_ratio(w: WidgetSpec, col: str) -> bool:
    """Percentual ou valor por tonelada: não pode ser somado entre itens."""
    unit = (w.column_units.get(col) or w.unit or "").strip().lower()
    low = (col or "").lower()
    return (unit in ("%", "pct", "percentual") or "/" in unit or any(h in low for h in PCT_HINTS)
            or "per_t" in low or "_por_" in low)


def _measure_name(w: WidgetSpec, col: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", _label(w, col)).strip() or "Valor"


def _is_plural(name: str) -> bool:
    first = (name.split() or [""])[0].lower()
    return len(first) > 3 and first.endswith("s") and not first.endswith(("ís", "ês"))


def _signed_pct(v: float) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + _br_number(abs(v), 1, strip_zeros=False) + "%"


def _signed_value(v: float, unit: str) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + format_compact_br(abs(v), unit)


def _time_column(df: pd.DataFrame, w: WidgetSpec) -> str | None:
    if w.x and _is_time(w.x) and w.x in df.columns:
        return w.x
    return next((c for c in df.columns if _is_time(c)), None)


def _years(df: pd.DataFrame, w: WidgetSpec) -> list[int]:
    col = _time_column(df, w)
    if col is None:
        return []
    return sorted({int(v) for v in pd.to_numeric(df[col], errors="coerce").dropna()})


def _clean_series(df: pd.DataFrame, x: str, y: str) -> pd.DataFrame:
    """Um valor por período. Em exposição e emissões, zero antes de 2015 significa "sem dado"."""
    t = df[[x, y]].copy()
    t[y] = pd.to_numeric(t[y], errors="coerce")
    t = t.dropna()
    if _is_five_year(y) and _is_time(x):
        t = t[~((t[y] == 0) & (pd.to_numeric(t[x], errors="coerce") < 2015))]
    return t.sort_values(x)


def _trend_sentence(w: WidgetSpec, series: pd.DataFrame, x: str, y: str) -> str | None:
    if len(series) < 2 or series[x].duplicated().any():
        return None  # mais de um valor por período: não agrega (poderia somar janelas ou regiões)
    unit = w.column_units.get(y) or w.unit or ""
    name = _measure_name(w, y)
    plural = _is_plural(name)
    x0, xn = _fmt_axis_value(series[x].iloc[0]), _fmt_axis_value(series[x].iloc[-1])
    a, b = float(series[y].iloc[0]), float(series[y].iloc[-1])
    de_para = f"de {format_compact_br(a, unit)} para {format_compact_br(b, unit)}"
    if a > 0 and b >= 0:
        pct = (b - a) / a * 100
        if abs(pct) < _STABLE_PCT:
            verbo = "ficaram estáveis" if plural else "ficou estável"
            frase = f"{name} {verbo} entre {x0} e {xn}: {de_para}."
        else:
            verbo = ("subiram" if plural else "subiu") if pct > 0 else ("caíram" if plural else "caiu")
            frase = f"{name} {verbo} {_br_number(abs(pct), 1, strip_zeros=False)}% entre {x0} e {xn}: {de_para}."
    else:
        frase = f"{name}: {de_para} entre {x0} e {xn}."
    pico = series[y].idxmax()
    if pico not in (series.index[0], series.index[-1]) and series[y].max() > max(a, b):
        frase += (f" O pico foi em {_fmt_axis_value(series.loc[pico, x])} "
                  f"({format_compact_br(series.loc[pico, y], unit)}).")
    return frase


def _leader_sentence(w: WidgetSpec, df: pd.DataFrame, base=None) -> str | None:
    x, y = w.x or "", w.y[0]
    work = _prepare_slice(df, w)
    vals = pd.to_numeric(work[y], errors="coerce")
    residual = work[x].map(is_residual_label)
    ranked = vals[~residual].dropna()
    if ranked.empty:
        return None
    top = ranked.idxmax()
    nome = display_label(work.loc[top, x], x)
    unit = w.column_units.get(y) or w.unit or ""
    valor = format_compact_br(ranked[top], unit)
    years = _years(df, w)
    aditivo = (not _is_ratio(w, y) and bool((vals.dropna() >= 0).all()) and len(years) <= 1
               and len(vals.dropna()) >= 2 and w.kind != "progress")
    total = float(vals.dropna().sum())
    if not aditivo or total <= 0:
        return f"{nome} tem o maior valor: {valor}."
    share = _pct_br(float(ranked[top]) / total * 100)
    escopo = _share_scope(w, y, work[x], len(ranked), base, years)
    if w.kind in ("pie", "donut"):
        return f"{nome} responde por {share} {escopo}."
    return f"{nome} lidera com {valor}, {share} {escopo}."


_PLURAL_ITENS = {"municipio": "municípios", "empresa": "empresas", "destino": "países", "porto": "portos",
                 "estado": "estados", "bioma": "biomas", "importador": "importadores"}


def _with_article(name: str) -> str:
    """"Volume" -> "do volume"; "Exposição ao desmatamento" -> "da exposição ao desmatamento"."""
    low = name[:1].lower() + name[1:] if not name[:2].isupper() else name
    first = low.split()[0] if low.split() else low
    if first.endswith(("ões", "as")):
        return f"das {low}"
    if first.endswith("os") or (first.endswith("s") and len(first) > 3 and not first.endswith(("ís", "ês"))):
        return f"dos {low}"
    if first.endswith(("ção", "são", "a", "ade", "agem", "ão")) and not first.endswith("ma"):
        return f"da {low}"
    return f"do {low}"


def _share_scope(w: WidgetSpec, y: str, cats: pd.Series, n_itens: int, base, years: list[int]) -> str:
    """H3: a BASE da participação em palavras simples, nunca só "do total".

    Ex.: "do volume total com origem identificada, em 2022"; "do volume dos 10 municípios mostrados"."""
    from src.dashboard.dimensions import DIMENSIONS, column_matches

    medida = _with_article(_measure_name(w, y))
    residuais = cats.map(is_residual_label)
    tem_outros = bool(cats[residuais].astype(str).str.contains(r"(?i)outr|demais|resto|other").any())
    tem_nao_ident = bool(cats.astype(str).str.contains(r"(?i)unknown|n[aã]o identificad").any())
    if tem_outros:
        partes = [f"{medida} total"]
    else:
        dim = next((k for k, d in DIMENSIONS.items() if column_matches(w.x, d)), None)
        partes = [f"{medida} dos {n_itens} {_PLURAL_ITENS.get(dim, 'itens')} mostrados"]
    origem = getattr(base, "origin", None)
    if tem_nao_ident or origem == "toda":
        partes.append(", incluindo origem não identificada")
    elif origem == "rastreada":
        partes.append(" com origem identificada")
    anos = list(getattr(base, "years", None) or years or [])
    if len(anos) == 1:
        partes.append(f", em {anos[0]}")
    return "".join(partes)


def _waterfall_sentence(w: WidgetSpec, df: pd.DataFrame) -> str | None:
    work = _prepare_slice(df, w)
    x, y = w.x or "", w.y[0]
    vals = pd.to_numeric(work[y], errors="coerce")
    partes = []
    if (vals > 0).any():
        i = vals.idxmax()
        partes.append(f"Maior alta: {display_label(work.loc[i, x], x)} ({_signed_value(vals[i], w.unit)})")
    if (vals < 0).any():
        i = vals.idxmin()
        partes.append(f"maior queda: {display_label(work.loc[i, x], x)} ({_signed_value(vals[i], w.unit)})")
    if not partes:
        return None
    frase = "; ".join(partes) + "."
    return frase[:1].upper() + frase[1:]


def chart_conclusion(w: WidgetSpec, df: pd.DataFrame, base=None) -> str | None:
    """F1: uma frase de conclusão calculada do DataFrame, com modelo de texto fixo.

    Não soma anos: variação compara dois períodos; participação só quando há um único período e a
    medida pode ser somada entre itens (nunca percentuais ou valores por tonelada)."""
    try:
        if df is None or df.empty or not w.y or w.y[0] not in df.columns:
            return None
        if w.kind == "waterfall":
            return _waterfall_sentence(w, df)
        x = w.x or ""
        if x not in df.columns:
            return None
        if w.kind in ("line", "area") or (w.kind == "bar" and _is_time(x)):
            work = _prepare_slice(df, w)
            series_cols = [c for c in w.y if c in work.columns]
            if w.color and w.color in work.columns and len(series_cols) == 1:
                y = series_cols[0]
                ultimo = work[x].max()
                ref = work[work[x] == ultimo].assign(_v=lambda d: pd.to_numeric(d[y], errors="coerce")).dropna(subset=["_v"])
                if ref[w.color].nunique() < 2 or ref[w.color].duplicated().any():
                    return None
                top = ref["_v"].idxmax()
                unit = w.column_units.get(y) or w.unit or ""
                return (f"Em {_fmt_axis_value(ultimo)}, {display_label(ref.loc[top, w.color], w.color)} "
                        f"teve o maior valor: {format_compact_br(ref.loc[top, '_v'], unit)}.")
            if len(series_cols) != 1:
                return None
            return _trend_sentence(w, _clean_series(work, x, series_cols[0]), x, series_cols[0])
        if w.kind in ("bar", "pie", "donut", "progress") and not w.color and len(w.y) == 1:
            return _leader_sentence(w, df, base)
    except Exception:  # a frase é um extra: nunca derruba o cartão
        logger.exception("Falha ao calcular a conclusão de %s", w.id)
    return None


# F2: trechos LITERAIS das ressalvas do dicionário de dados (src/data_dictionary.CAVEATS). Se uma
# ressalva mudar e o trecho deixar de existir, ele some do "Como ler" (e o teste avisa).
CAVEAT_FRAGMENTS = {
    "janela": "Exposição e emissões com janela de 5 anos: NÃO some entre anos (as janelas se sobrepõem e "
              "contam o mesmo desmatamento várias vezes)",
    "antes_2015": "exposição e emissões só existem de 2015 em diante; 2011-2014 aparecem como 0/NULL e "
                  "significam 'sem dado', não 'zero desmatamento'",
    "estimativa": "Exposição ao desmatamento é uma estimativa de associação da cadeia, não prova de "
                  "ilegalidade nem de responsabilidade direta de uma empresa",
    "razao": "Métricas por tonelada e percentuais não podem ser somados nem tirada média simples entre regiões",
    "origem": "o consumo interno não é rastreado até o município",
}
_CAVEAT_PLAIN = (("NÃO ", "não "), ("0/NULL", "zero ou vazio"))

HOW_TO_READ = {
    "line": "Cada ponto é o valor de um período; a linha só liga os pontos.",
    "area": "Cada ponto é o valor de um período; a área só preenche até a linha.",
    "area_stacked": "As faixas ficam empilhadas: a altura de cada faixa é o seu valor no período.",
    "bar": "Cada barra é um item e o comprimento é o valor. Passe o mouse para ver o número exato.",
    "bar_time": "Cada barra é o valor de um período. Passe o mouse para ver o número exato.",
    "pie": "Cada fatia é a parte de um item na soma dos itens mostrados.",
    "waterfall": "Cada barra mostra quanto um item somou (para cima) ou tirou (para baixo) da variação; "
                 "a última barra é a variação total.",
    "progress": "Cada barra mostra a participação do item, em porcentagem.",
    "table": "Cada linha é um registro da consulta, sem somas extras.",
    "range": "Cada barra vai do valor mínimo ao máximo previsto no artigo, sempre na mesma unidade. "
             "Valores de leis diferentes não são somados.",
    "quote": "Trechos copiados do texto da norma e conferidos no acervo, com o link para a fonte.",
}


def caveat_text(key: str) -> str | None:
    """Ressalva do dicionário de dados em texto simples, ou None se o trecho não existir mais."""
    from src.data_dictionary import CAVEATS

    frag = CAVEAT_FRAGMENTS[key]
    if not any(frag in c for c in CAVEATS):
        logger.warning("Ressalva '%s' não encontrada em CAVEATS; fora do 'Como ler'.", key)
        return None
    for old, new in _CAVEAT_PLAIN:
        frag = frag.replace(old, new)
    return frag[:1].upper() + frag[1:] + "."


def _empty_before_2015(df: pd.DataFrame, w: WidgetSpec, cols: list[str]) -> bool:
    """Os dados trazem anos antes de 2015 com a medida zerada ou vazia (= sem dado, não zero)."""
    tcol = _time_column(df, w)
    if tcol is None:
        return False
    antes = df[pd.to_numeric(df[tcol], errors="coerce") < 2015]
    for c in cols:
        if c in antes.columns and not antes.empty:
            v = pd.to_numeric(antes[c], errors="coerce")
            if (v.isna() | (v == 0)).any():
                return True
    return False


def how_to_read(w: WidgetSpec, df: pd.DataFrame | None) -> list[str]:
    """F2: como ler o gráfico (texto fixo por tipo) e as ressalvas do dicionário que valem para a medida."""
    if w.kind in ("area",) and w.stacked:
        chave = "area_stacked"
    elif w.kind == "bar" and _is_time(w.x):
        chave = "bar_time"
    elif w.kind == "donut":
        chave = "pie"
    else:
        chave = w.kind
    itens = [HOW_TO_READ[chave]] if chave in HOW_TO_READ else []
    cols = [c for c in [*w.y, *(w.columns if w.kind == "table" else [])] if c]
    chaves = []
    if any(_is_five_year(c) for c in cols):
        chaves.append("janela")
        if df is not None and _empty_before_2015(df, w, [c for c in cols if _is_five_year(c)]):
            chaves.append("antes_2015")
    if any(_is_exposure(c) for c in cols):
        chaves.append("estimativa")
    if any(_is_ratio(w, c) for c in cols):
        chaves.append("razao")
    if df is not None:
        cat = w.x if w.kind != "table" else next((c for c in df.columns if df[c].dtype == object), None)
        if cat and cat in df.columns and df[cat].astype(str).str.upper().str.startswith("UNKNOWN").any():
            chaves.append("origem")
    itens += [t for t in (caveat_text(k) for k in dict.fromkeys(chaves)) if t]
    return itens


def measure_limit(w: WidgetSpec) -> str | None:
    """F3: o limite da medida, curto, para o rodapé do cartão."""
    if LAWS_SOURCE in (w.source or ""):
        return "texto conforme o acervo consolidado; confirme a vigência; não é aconselhamento jurídico"
    cols = [c for c in [*w.y, w.column, *(w.columns if w.kind == "table" else [])] if c]
    partes = []
    if any(_is_five_year(c) for c in cols):
        partes.append("janela de 5 anos, não some anos")
    if any(_is_exposure(c) for c in cols):
        partes.append("exposição ao desmatamento não é prova de ilegalidade")
    if any(_is_ratio(w, c) for c in cols):
        partes.append("percentuais e valores por tonelada não se somam")
    return "; ".join(partes) or None


def period_text(w: WidgetSpec, df: pd.DataFrame | None) -> str | None:
    """F3: período coberto pelos dados do cartão (dos anos presentes, sem inventar nenhum)."""
    anos = _years(df, w) if df is not None else []
    if not anos:
        return None
    return str(anos[0]) if len(anos) == 1 else f"{anos[0]}–{anos[-1]}"


def _source_with_id(w: WidgetSpec) -> str:
    tag = f"[{w.dataset_id}]"
    return w.source if tag in (w.source or "") else f"{w.source} {tag}".strip()


def _card_footer(w: WidgetSpec, df: pd.DataFrame | None) -> str:
    partes = [f'<span class="foot-src">Fonte: {html.escape(_source_with_id(w))}</span>']
    periodo = period_text(w, df)
    if periodo:
        partes.append(f'<span class="foot-period">Período: {periodo}</span>')
    limite = measure_limit(w)
    if limite:
        partes.append(f'<span class="foot-limit">Limite: {html.escape(limite)}</span>')
    return f'<footer class="card-footer">{"".join(partes)}</footer>'


def _help_html(w: WidgetSpec, df: pd.DataFrame | None) -> str:
    itens = how_to_read(w, df)
    if not itens:
        return ""
    lis = "".join(f"<li>{html.escape(t)}</li>" for t in itens)
    return (f'<details class="help"><summary aria-label="Como ler este gráfico" title="Como ler">?</summary>'
            f'<div class="help-body"><strong>Como ler</strong><ul>{lis}</ul></div></details>')


def _data_view(w: WidgetSpec, df: pd.DataFrame) -> str:
    """F5: a mesma informação do gráfico em tabela ("ver dados"), com as linhas que o gráfico usa."""
    work = _prepare_slice(df, w)
    cols = [c for c in dict.fromkeys([w.x, w.color, *w.y]) if c and c in work.columns]
    if not cols or work.empty:
        return ""
    unidades = {c: w.column_units.get(c) or w.unit for c in w.y if w.column_units.get(c) or w.unit}
    lista = replace(w, kind="table", columns=cols, sort_by=None, top_n=max(len(work), 1),
                    column_units={**w.column_units, **unidades})
    tabela = _render_table_html(lista, work).replace(
        f'aria-label="{html.escape(pt_text(w.title))}"',
        f'aria-label="Dados do gráfico: {html.escape(pt_text(w.title))}"', 1)
    return f'<details class="data-view"><summary>Ver dados</summary>{tabela}</details>'


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
        f'<polyline points="{line}" pathLength="1" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.2" fill="currentColor"/></svg>'
    )


def _uid(w: WidgetSpec) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", w.id) or "w"


def _card_header(w: WidgetSpec, df: pd.DataFrame | None = None, conclusion: str | None = None) -> str:
    subtitle = f'<p class="subtitle">{html.escape(pt_text(w.subtitle))}</p>' if w.subtitle else ""
    lead = f'<p class="conclusion">{html.escape(conclusion)}</p>' if conclusion else ""
    units = list(dict.fromkeys(u for u in w.column_units.values() if u)) if w.kind == "table" else []
    unit_txt = " / ".join(units) if len(units) > 1 else w.unit
    if w.kind in ("pie", "donut", "progress"):
        unit_txt = "%"  # A4: pizza e rosca mostram participação; a quantidade fica no passar do mouse
    badge = f'<span class="badge">{html.escape(unit_txt)}</span>' if unit_txt else ""
    tools = f'<div class="card-tools">{badge}{_help_html(w, df)}</div>'
    return (f'<div class="card-header"><div class="card-titles"><h3>{html.escape(pt_text(w.title))}</h3>'
            f'{lead}{subtitle}</div>{tools}</div>')


COMPACT_KINDS = ("pie", "donut", "progress")


def _is_compact(w: WidgetSpec) -> bool:
    """C3: gráficos menores (pizza, rosca, participações, ranking curto em meia largura) usam título
    pequeno, em maiúsculas e centralizado."""
    return w.span != 2 and (w.kind in COMPACT_KINDS or (w.kind == "bar" and w.orientation == "h"))


def _csv_header(w: WidgetSpec, col: str) -> str:
    """Cabeçalho do CSV: o nome da tela com a unidade (no CSV não há selo)."""
    unit = w.column_units.get(col) or (w.unit if col in (*w.y, w.column) and w.kind != "table" else "")
    return _axis_title(_label(w, col), unit) if unit else _label(w, col)


def _fig_html(fig: go.Figure) -> str:
    # D3: tela cheia e "baixar imagem" ficam nos botões do cartão; a barra do Plotly sai.
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={"responsive": True, "displaylogo": False, "displayModeBar": False,
                               "toImageButtonOptions": {"scale": 2}})


def _pie_allowed(w: WidgetSpec, df: pd.DataFrame) -> bool:
    """D3: "ver como pizza" só quando a pizza não engana: um único período, medida somável, sem
    negativos e no máximo 8 partes."""
    y = w.y[0]
    vals = pd.to_numeric(df[y], errors="coerce").dropna()
    if vals.empty or (vals < 0).any() or _is_ratio(w, y) or len(_years(df, w)) > 1:
        return False
    return len(_prepare_slice(df, replace(w, kind="pie"))) <= MAX_SLICES


def _with_views(w: WidgetSpec, df: pd.DataFrame, plot_html: str, aria: str) -> str:
    """D3: "Ver como: barras · pizza · lista" quando o dado permite. As visões são montadas aqui, com
    as MESMAS linhas; trocar de visão não consulta nem recalcula nada."""
    if (w.kind not in ("bar", "pie", "donut") or not w.x or _is_time(w.x) or w.color or len(w.y) != 1
            or w.y[0] not in df.columns or LAWS_SOURCE in (w.source or "")):
        return plot_html
    circular = "donut" if w.kind == "donut" else "pie"
    views = ["bar"] + ([circular] if _pie_allowed(w, df) else []) + ["list"]
    if w.kind in ("pie", "donut") and circular not in views:
        return plot_html
    blocos = []
    for v in views:
        if v == w.kind:
            corpo = plot_html
        elif v == "list":
            work = _prepare_slice(df, w)
            cols = [c for c in (w.x, *w.y) if c in work.columns]
            corpo = _render_table_html(replace(w, kind="table", columns=cols, sort_by=None,
                                               top_n=max(len(work), 1)), work)
        else:
            alt = replace(w, kind=v, orientation="h" if v == "bar" else w.orientation)
            corpo = f'<div class="plot-wrap" role="img" aria-label="{aria}">{_fig_html(build_widget_figure(alt, df))}</div>'
        blocos.append(f'<div class="view" data-view="{v}"{"" if v == w.kind else " hidden"}>{corpo}</div>')
    return view_switch(views, w.kind) + "".join(blocos)


def _render_valid_card(w: WidgetSpec, inner_html: str, df: pd.DataFrame | None = None,
                       conclusion: str | None = None, extra_html: str = "", orient: str | None = None) -> str:
    span_cls = " span-2" if w.span == 2 else ""
    span_cls += " is-compact" if _is_compact(w) else ""
    orient_attr = f' data-orient="{html.escape(orient)}"' if orient else ""
    return (
        f'<article class="card chart-card{span_cls}" data-widget-id="{html.escape(w.id)}" '
        f'data-widget-kind="{html.escape(w.kind)}"{orient_attr}>\n'
        f'  {_card_header(w, df, conclusion)}\n'
        f'  <div class="card-body">{inner_html}</div>\n'
        f'  {extra_html}{_card_footer(w, df)}\n'
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
        f'    <p class="kpi-source">{_kpi_source(w, df)}</p>\n'
        f'  </div>\n'
        f'</article>'
    )


def _kpi_source(w: WidgetSpec, df: pd.DataFrame) -> str:
    periodo = period_text(w, df)
    return f"Fonte: {html.escape(_source_with_id(w))}" + (f" · {periodo}" if periodo else "")


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
    ano_col = next((c for c in cols if _is_time(c)), None)  # D4: o filtro de período esconde linhas
    for _, row in work.iterrows():
        cells = []
        ano = pd.to_numeric(pd.Series([row[ano_col]]), errors="coerce").iloc[0] if ano_col else None
        tr_attr = f' data-year="{int(ano)}"' if ano is not None and not pd.isna(ano) else ""
        for c in cols:
            if c == "url_fonte":
                cells.append(f"<td>{_source_link(row[c])}</td>")
                continue
            txt = html.escape(format_br_value(row[c], c))
            if c == bar_col and max_v:
                v = pd.to_numeric(pd.Series([row[c]]), errors="coerce").iloc[0]
                pct = 0.0 if pd.isna(v) else max(0.0, min(100.0, float(v) / max_v * 100))
                cells.append(f'<td class="num has-bar"><span class="databar" style="width:{pct:.1f}%"></span>'
                             f'<span class="cell-v">{txt}</span></td>')
            else:
                cells.append(f'<td class="{"num" if c in numeric else ""}">{txt}</td>')
        rows.append(f"<tr{tr_attr}>{''.join(cells)}</tr>")
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
        f'  <p class="warn-hint">{NO_DATA_HINT}</p>\n'
        f'</article>'
    )



MAIN_KINDS = ("line", "area", "bar", "waterfall")


def _base_of(w: WidgetSpec, by_id):
    """Base do dataset do componente (ano, origem), lida em código; None se não houver."""
    from src.dashboard.data_base import infer_base

    ds = (by_id or {}).get(w.dataset_id)
    return infer_base(ds) if ds is not None and getattr(ds, "database", "") != LAWS_DATABASE else None


def _is_law(w: WidgetSpec, by_id=None) -> bool:
    ds = (by_id or {}).get(w.dataset_id)
    if ds is not None:
        return getattr(ds, "database", "") == LAWS_DATABASE
    return LAWS_SOURCE in (w.source or "")


def _section_of(w: WidgetSpec, group_section, by_id=None) -> str:
    if _is_law(w, by_id):
        return "base-legal"
    return group_section.get(w.group or "", SECTION_OF.get(w.kind, "detalhamento"))


def _main_chart_ids(widgets, group_section, by_id=None) -> set[str]:
    """E5: em cada seção de gráficos, o primeiro de linha/área/barras/variação é o principal
    (largura total); os demais ficam em meia largura, alinhados à grade."""
    seen: set[str] = set()
    out: set[str] = set()
    for w in widgets:
        sec = _section_of(w, group_section, by_id)
        if sec in ("visao-geral", "detalhamento", "base-legal") or sec in seen or w.kind not in MAIN_KINDS:
            continue
        seen.add(sec)
        out.add(w.id)
    return out


def _final_spans(widgets, group_section, main_ids, by_id=None) -> dict[str, int]:
    """Largura final de cada cartão de gráfico: o principal da seção ocupa a largura toda e um cartão
    de meia largura que ficaria sozinho na linha (seguido de um de largura toda, ou no fim) também."""
    por_secao: dict[str, list] = {}
    for w in widgets:
        sec = _section_of(w, group_section, by_id)
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
    return _render_valid_card(lista, note + _render_table_html(lista, df), df)


# --- F4: estados do painel (carregando, sem dados, erro) ---------------------------------

_THEME_BOOT_JS = """
(function () {
  var d = document.documentElement, t = null;
  if (d.getAttribute("data-theme")) return;
  try { t = localStorage.getItem("trase-dash-theme"); } catch (e) {}
  if (t !== "light" && t !== "dark") {
    t = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
  }
  d.setAttribute("data-theme", t);
})();
"""

_LOADING_JS = """
(function () {
  var box = document.querySelector(".state-loading");
  if (!box) return;
  var steps = box.querySelectorAll(".state-steps li"), now = box.querySelector(".state-now"), i = 0;
  function show() {
    steps.forEach(function (li, k) {
      li.className = k < i ? "is-done" : (k === i ? "is-current" : "");
      if (k === i) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    now.textContent = steps[i].textContent + "…";
  }
  show();
  var timer = setInterval(function () { if (i >= steps.length - 1) { clearInterval(timer); return; } i += 1; show(); }, 1800);
})();
"""


def _state_block(state: str, detail: str | None = None) -> str:
    """Bloco de estado com o mesmo sistema de design do painel, em frases simples."""
    extra = f'<p class="state-detail">{html.escape(detail)}</p>' if detail else ""
    if state == "loading":
        steps = "".join(f"<li>{html.escape(t)}</li>" for t in PROGRESS_STEPS)
        return (f'<section class="state state-loading" role="status" aria-live="polite">'
                f'<p class="state-title"><span class="state-dot" aria-hidden="true"></span>'
                f'<span class="state-now">{html.escape(PROGRESS_STEPS[0])}…</span></p>{extra}'
                f'<ol class="state-steps">{steps}</ol></section>')
    if state == "empty":
        tips = "".join(f"<li>{html.escape(t)}</li>" for t in EMPTY_SUGGESTIONS)
        return (f'<section class="state empty-state" role="status">{_icon("visao-geral", "icon-lg")}'
                f'<h2 class="state-title">{html.escape(EMPTY_PAGE_TITLE)}</h2>{extra}'
                f'<p class="state-lead">O que tentar:</p><ul class="state-tips">{tips}</ul></section>')
    if state == "error":
        return (f'<section class="state error-state" role="alert">{_icon("aviso", "icon-lg")}'
                f'<h2 class="state-title">{html.escape(ERROR_PAGE_TITLE)}</h2>'
                f'<p>{html.escape(ERROR_MESSAGE.split(". ", 1)[1])}</p></section>')
    raise ValueError(f"Estado desconhecido: {state!r}")


def render_status_page(state: str, *, detail: str | None = None, theme: str | None = None) -> str:
    """Página só de estado ("loading", "empty" ou "error"), para a tela que espera o painel.

    O texto técnico de um erro nunca entra aqui: ele vai para o log e para o trace."""
    titulos = {"loading": "Montando o painel", "empty": EMPTY_PAGE_TITLE, "error": ERROR_PAGE_TITLE}
    if state not in titulos:
        raise ValueError(f"Estado desconhecido: {state!r}")
    bloco = _state_block(state, None if state == "error" else detail)
    theme_attr = f' data-theme="{theme}"' if theme in ("light", "dark") else ""
    script = f"<script>{_LOADING_JS}</script>" if state == "loading" else ""
    return (f'<!doctype html>\n<html lang="pt-BR"{theme_attr}>\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{html.escape(titulos[state])}</title>\n<script>{_THEME_BOOT_JS}</script>\n'
            f'<style>\n{PAGE_CSS}\n</style>\n</head>\n'
            f'<body class="state-page">\n<main id="conteudo">\n{bloco}\n</main>\n{script}\n</body>\n</html>')


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
    spans = _final_spans(ordered, group_section, _main_chart_ids(ordered, group_section, by_id), by_id)
    for w in ordered:
        if spans.get(w.id, w.span) != w.span:
            w = replace(w, span=spans[w.id])  # E5: principal na largura toda; nenhum cartão sozinho pela metade
        section = _section_of(w, group_section, by_id)
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
                acoes = card_actions(image=False, csv_html=csv_template(
                    _prepare_slice(df, w, default_top_n=50), list(w.columns or df.columns),
                    header=lambda c, w=w: _csv_header(w, c), label=csv_label))
                cards[section].append(_render_valid_card(w, _render_table_html(w, df), df, extra_html=acoes))
            elif w.kind == "quote":
                cards[section].append(_render_valid_card(w, _render_quote_html(w, df), df))
            elif w.kind == "progress":
                acoes = card_actions(image=False, csv_html=csv_template(
                    _prepare_slice(df, w), [c for c in (w.x, *w.y) if c],
                    header=lambda c, w=w: _csv_header(w, c), label=csv_label))
                cards[section].append(_render_valid_card(w, _render_progress_html(w, df), df,
                                                         chart_conclusion(w, df, _base_of(w, by_id)), acoes))
            else:
                fig = build_widget_figure(w, df)
                if w.group in group_ranges:  # mesmo intervalo de tempo nos gráficos do par
                    fig.update_xaxes(range=group_ranges[w.group], dtick=1 if _is_time(w.x) else None)
                fig_html = _fig_html(fig)
                needs_plotly = True
                conclusao = None if _is_law(w, by_id) else chart_conclusion(w, df, _base_of(w, by_id))
                aria = html.escape(". ".join(t.rstrip(".") for t in (pt_text(w.title), conclusao, pt_text(w.subtitle)) if t)
                                   + ". A tabela em Ver dados traz os mesmos números.")
                plot = f'<div class="plot-wrap" role="img" aria-label="{aria}">{fig_html}</div>'
                body = note + _with_views(w, df, plot, aria)
                anos = _years(df, w) if _is_time(w.x) and w.kind in ("line", "area", "bar") else []
                if len(anos) >= 3:
                    body = period_filter(anos) + body
                work = _prepare_slice(df, w)
                csv = csv_template(work, [c for c in dict.fromkeys([w.x, w.color, *w.y]) if c],
                                   header=lambda c, w=w: _csv_header(w, c), label=csv_label)
                cards[section].append(_render_valid_card(
                    w, body, df, conclusao, card_actions(image=True, csv_html=csv) + _data_view(w, df),
                    orient=w.orientation))
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
        sections_html.append(_state_block("empty"))

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
    law_note = (f'<br><span class="law-note">{html.escape(LAW_FOOTER)}</span>'
                if any(getattr(d, "database", "") == LAWS_DATABASE for d in datasets) else "")
    plotly_head = _plotly_loader(plotlyjs) if needs_plotly else ""

    return f"""<!doctype html>
<html lang="pt-BR"{theme_attr}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<script>
(function () {{
  var d = document.documentElement, t = null, fixed = !!d.getAttribute("data-theme");
  // Embutido no chat (?embed=1 ou dentro de um iframe): sem barra lateral, fundo do chat, altura natural.
  var embed = /[?&]embed=1\b/.test(location.search);
  try {{ embed = embed || window.self !== window.top; }} catch (e) {{ embed = true; }}
  if (embed) d.classList.add("is-embed");
  function pick() {{
    try {{ t = localStorage.getItem("trase-dash-theme"); }} catch (e) {{}}
    if (t !== "light" && t !== "dark") {{
      t = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
    }}
    d.setAttribute("data-theme", t);
  }}
  if (!fixed) {{
    pick();
    // O chat e o painel guardam o tema na mesma chave: trocar num lado troca no outro.
    window.addEventListener("storage", function (e) {{ if (e.key === "trase-dash-theme") pick(); }});
  }}
}})();
</script>
<style>
{PAGE_CSS}
{MOTION_CSS}
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
      Dados: Trase (CC BY 4.0). Exposição ao desmatamento é uma associação estatística e não prova ilegalidade.{law_note}
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
<script>{MOTION_JS}</script>
</body>
</html>
"""

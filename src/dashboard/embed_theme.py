"""Tema claro do Studio para o modo embed (?embed=1 / .is-embed) do Painel completo.

Lê as variáveis de `web/studio.css` e `CHART_COLORS` de `web/studio.js` como fonte única de design.
Todas as regras são escopadas em `.is-embed` para que o painel aberto fora do embed permaneça intacto.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"

_STUDIO_TOKENS_FALLBACK: dict[str, str] = {
    "bg": "#f6f7f4",
    "surface": "#ffffff",
    "surface-soft": "#eef2ee",
    "border": "#dfe5df",
    "border-strong": "#c8d3c9",
    "text": "#16211b",
    "muted": "#5a6a61",
    "accent": "#15803d",
    "accent-hover": "#166534",
    "accent-soft": "#eaf5ee",
    "accent-border": "#b8dfc4",
    "amber-bg": "#fef3c7",
    "amber-text": "#92400e",
    "amber-border": "#fcd34d",
    "shadow-sm": "0 1px 3px rgba(16, 28, 21, 0.05)",
    "shadow-md": "0 8px 28px rgba(16, 28, 21, 0.07)",
    "font": '"Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    "serif": '"Newsreader", Georgia, serif',
    "mono": "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
}

_STUDIO_CHART_COLORS_FALLBACK: tuple[str, ...] = (
    "#10b981", "#38bdf8", "#f59e0b", "#f43f5e", "#a855f7", "#eab308", "#14b8a6", "#fb7185",
)


@lru_cache(maxsize=1)
def load_studio_tokens() -> dict[str, str]:
    """Lê as variáveis CSS do :root em web/studio.css (fonte única de design no modo embed)."""
    tokens = dict(_STUDIO_TOKENS_FALLBACK)
    css_path = _WEB_DIR / "studio.css"
    try:
        text = css_path.read_text(encoding="utf-8")
        m = re.search(r":root\s*\{([^}]*)\}", text, flags=re.S)
        if m:
            for name, val in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", m.group(1)):
                tokens[name.strip()] = val.strip()
    except OSError:
        pass
    return tokens


@lru_cache(maxsize=1)
def load_studio_chart_colors() -> tuple[str, ...]:
    """Lê CHART_COLORS de web/studio.js para alinhar as séries Plotly no modo embed."""
    js_path = _WEB_DIR / "studio.js"
    try:
        text = js_path.read_text(encoding="utf-8")
        m = re.search(r"CHART_COLORS\s*=\s*\[([^\]]+)\]", text)
        if m:
            colors = tuple(re.findall(r"#[0-9a-fA-F]{6}", m.group(1)))
            if colors:
                return colors
    except OSError:
        pass
    return _STUDIO_CHART_COLORS_FALLBACK


def build_embed_studio_css() -> str:
    """CSS aplicado SOMENTE em .is-embed (?embed=1 / iframe), sempre no tema claro do studio."""
    t = load_studio_tokens()
    return f"""
/* Tema claro do studio para o painel embutido (.is-embed); não altera o painel aberto fora do embed. */
:root.is-embed,
:root.is-embed[data-theme="light"],
:root.is-embed[data-theme="dark"] {{
  --studio-bg: {t["bg"]};
  --studio-surface: {t["surface"]};
  --studio-surface-soft: {t["surface-soft"]};
  --studio-border: {t["border"]};
  --studio-border-strong: {t["border-strong"]};
  --studio-text: {t["text"]};
  --studio-muted: {t["muted"]};
  --studio-accent: {t["accent"]};
  --studio-accent-hover: {t["accent-hover"]};
  --studio-accent-soft: {t["accent-soft"]};
  --studio-accent-border: {t["accent-border"]};
  --studio-amber-bg: {t["amber-bg"]};
  --studio-amber-text: {t["amber-text"]};
  --studio-amber-border: {t["amber-border"]};
  --studio-shadow-sm: {t["shadow-sm"]};
  --studio-shadow-md: {t["shadow-md"]};
  --studio-font: {t["font"]};
  --studio-serif: {t["serif"]};
  --studio-mono: {t["mono"]};
  --bg: var(--studio-bg);
  --panel: var(--studio-surface);
  --panel-2: var(--studio-surface-soft);
  --fg: var(--studio-text);
  --muted: var(--studio-muted);
  --border: var(--studio-border);
  --line: var(--studio-border-strong);
  --accent: var(--studio-accent);
  --accent-soft: var(--studio-accent-soft);
  --brand: var(--studio-accent);
  --icon: var(--studio-accent);
  --focus: var(--studio-accent);
  --chart-text: var(--studio-muted);
  --track: var(--studio-surface-soft);
  --code-bg: var(--studio-bg);
  --warn-bg: var(--studio-amber-bg);
  --warn-border: var(--studio-amber-border);
  --warn-fg: var(--studio-amber-text);
  --r-sm: 8px;
  --r-md: 14px;
  color-scheme: light;
}}
html.is-embed,
html.is-embed body {{
  background: var(--studio-bg);
  color: var(--studio-text);
  font-family: var(--studio-font);
  font-size: 14px;
  line-height: 1.5;
  overflow-x: hidden;
}}
.is-embed .sidebar,
.is-embed .skip,
.is-embed .question-pill {{ display: none !important; }}
.is-embed main {{ padding: 16px 18px 26px; max-width: none; width: 100%; }}

/* Cabeçalho executivo: título à esquerda e 2 a 3 números-síntese à direita */
.is-embed .hero {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 18px;
  box-shadow: var(--studio-shadow-sm);
  margin-bottom: 14px;
}}
.is-embed .hero-top {{ border-top: 0; padding-top: 0; margin-bottom: 4px; }}
.is-embed .eyebrow {{ color: var(--accent); font-weight: 600; letter-spacing: .04em; font-size: 11px; }}
.is-embed .hero-main {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}}
.is-embed .hero-copy {{ flex: 1 1 280px; min-width: 0; }}
.is-embed h1 {{
  font-family: var(--studio-font);
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.015em;
  line-height: 1.25;
  margin: 0 0 4px;
}}
.is-embed .hero-subtitle {{ font-size: 12.5px; margin: 0; color: var(--muted); }}
.is-embed .hero-stats {{
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}}
.is-embed .hero-stat {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding-left: 14px;
  border-left: 1px solid var(--border);
}}
.is-embed .hero-stat:first-child {{ border-left: 0; padding-left: 0; }}
.is-embed .hero-stat-label {{ font-size: 11px; color: var(--muted); font-weight: 500; }}
.is-embed .hero-stat-val {{
  font-size: 16px;
  font-weight: 700;
  color: var(--accent);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}}

/* Seções e faixa de KPIs no topo (cartões iguais lado a lado com sparkline discreta ao fundo) */
.is-embed .dash-section {{ margin-bottom: 16px; }}
.is-embed #visao-geral .section-title,
.is-embed #detalhamento .section-title {{ display: none; }}
.is-embed .section-title {{
  font-family: var(--studio-font);
  font-size: 13.5px;
  font-weight: 700;
  letter-spacing: 0;
  margin: 0 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}}
.is-embed .section-title::after {{ background: var(--accent); width: 32px; height: 2px; }}

.is-embed .kpi-strip {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
  gap: 12px;
  align-items: stretch;
  background: transparent;
  border: 0;
  box-shadow: none;
  padding: 0;
}}
.is-embed .kpi {{
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--studio-shadow-sm);
  padding: 13px 14px;
  min-height: 108px;
}}
.is-embed .kpi:first-child {{ border-left: 1px solid var(--border); }}
.is-embed .kpi-icon {{ display: none; }}
.is-embed .kpi-body {{
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  height: 100%;
}}
.is-embed .kpi-label {{ font-size: 11.5px; font-weight: 600; color: var(--muted); line-height: 1.3; }}
.is-embed .kpi-value,
.is-embed .kpi.is-featured .kpi-value {{
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.15;
  color: var(--fg);
  margin: 4px 0 2px;
  white-space: normal;
  word-break: break-word;
}}
.is-embed .kpi-delta {{
  margin: 2px 0 0;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}}
.is-embed .kpi-delta .delta {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--panel-2);
  color: var(--fg);
  font-weight: 600;
  font-size: 11px;
}}
.is-embed .kpi-delta .delta[data-dir="up"] {{
  background: var(--studio-accent-soft);
  color: var(--studio-accent);
}}
.is-embed .kpi-delta .delta[data-dir="up"]::before {{ content: "▲"; font-size: 8.5px; }}
.is-embed .kpi-delta .delta[data-dir="down"] {{
  background: #fef2f2;
  color: #b91c1c;
}}
.is-embed .kpi-delta .delta[data-dir="down"]::before {{ content: "▼"; font-size: 8.5px; }}
.is-embed .kpi-delta .delta-prev {{ display: inline; color: var(--muted); font-weight: 400; }}
.is-embed .kpi .spark {{
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 48%;
  color: var(--studio-accent);
  opacity: 0.14;
  pointer-events: none;
  z-index: 0;
}}
.is-embed .kpi .spark-area {{ display: block; opacity: 0.55; }}
.is-embed .kpi-source {{ margin-top: auto; padding-top: 4px; font-size: 10.5px; color: var(--muted); }}

/* Grade de cartões em 2 colunas (12 trilhas: 7+5 para largo+rosca, 6+6 para pares, 12 para série temporal) */
.is-embed .chart-grid {{
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 14px;
}}
.is-embed .card {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 15px 16px;
  box-shadow: var(--studio-shadow-sm);
  min-width: 0;
  overflow: hidden;
  grid-column: span 12;
}}
.is-embed .card[data-embed-span="7"] {{ grid-column: span 7; }}
.is-embed .card[data-embed-span="6"] {{ grid-column: span 6; }}
.is-embed .card[data-embed-span="5"] {{ grid-column: span 5; }}
.is-embed .card[data-embed-span="12"] {{ grid-column: span 12; }}

.is-embed .card-header {{ margin-bottom: 10px; }}
.is-embed .card-header h3 {{
  font-family: var(--studio-font);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.35;
  text-align: left;
}}
.is-embed .card.is-compact .card-header {{ justify-content: space-between; text-align: left; padding: 0; }}
.is-embed .card.is-compact .card-header h3 {{
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: none;
}}
.is-embed .card.is-compact .card-header .card-tools {{ position: static; }}
.is-embed .subtitle {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
.is-embed .conclusion {{ font-size: 12.5px; color: var(--fg); margin-top: 4px; }}
.is-embed .badge {{
  border-radius: 999px;
  background: var(--accent-soft);
  border-color: var(--studio-accent-border);
  color: var(--accent);
  padding: 1px 8px;
}}
.is-embed .btn-ghost,
.is-embed details.data-view summary {{
  font-family: var(--studio-font);
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--fg);
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 11.5px;
  font-weight: 600;
}}
.is-embed .btn-ghost:hover,
.is-embed details.data-view summary:hover {{
  border-color: var(--accent);
  color: var(--studio-accent-hover);
  background: var(--panel);
}}

/* Tabelas recolhidas e com o mesmo estilo do studio */
.is-embed .full-data-collapse {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 12px 16px;
  box-shadow: var(--studio-shadow-sm);
}}
.is-embed .full-data-collapse > summary {{
  background: transparent;
  border: 0;
  padding: 2px 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--fg);
}}
.is-embed .table-wrap {{ border: 1px solid var(--border); border-radius: 10px; max-width: 100%; }}
.is-embed table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; font-family: var(--studio-font); }}
.is-embed thead th {{
  background: var(--bg);
  color: var(--muted);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0;
  text-transform: none;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}}
.is-embed tbody td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--fg); }}
.is-embed tbody tr:hover td {{ background: var(--panel-2); }}
.is-embed .databar {{ background: var(--accent-soft); }}

/* Rastreabilidade e blocos SQL */
.is-embed details.provenance {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 12px 16px;
  box-shadow: var(--studio-shadow-sm);
}}
.is-embed .query-item pre {{
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-family: var(--studio-mono);
  font-size: 11.5px;
}}
.is-embed .query-item code {{ font-family: var(--studio-mono); font-size: 11.5px; }}
.is-embed .plot-wrap {{ width: 100%; max-width: 100%; overflow: hidden; }}
.is-embed .js-plotly-plot .plotly .main-svg text {{ font-family: var(--studio-font) !important; }}

/* Responsivo: vira 1 coluna em tela estreita, sem rolagem horizontal */
@media (max-width: 760px) {{
  .is-embed main {{ padding: 12px 12px 22px; }}
  .is-embed .chart-grid {{ grid-template-columns: minmax(0, 1fr); }}
  .is-embed .card,
  .is-embed .card[data-embed-span] {{ grid-column: auto; }}
  .is-embed .hero-stats {{ width: 100%; justify-content: flex-start; }}
  .is-embed .hero-stat {{ align-items: flex-start; }}
  .is-embed h1 {{ font-size: 17px; }}
}}
@media (max-width: 480px) {{
  .is-embed .kpi-strip {{ grid-template-columns: minmax(0, 1fr); }}
}}
"""


def build_embed_studio_js(palette: list[str], accent: str) -> str:
    """No modo embed (.is-embed), aplica CHART_COLORS, tipografia do studio e redimensiona Plotly sem estouro."""
    t = load_studio_tokens()
    studio_colors = list(load_studio_chart_colors())
    return f"""
(function () {{
  if (!document.documentElement.classList.contains("is-embed")) return;
  document.documentElement.setAttribute("data-theme", "light");
  var STUDIO_COLORS = {json.dumps(studio_colors)};
  var STANDALONE = {json.dumps(palette)};
  var ACCENT_OLD = {json.dumps(accent)};
  var ACCENT_NEW = {json.dumps(t["accent"])};
  var STUDIO_FONT = {json.dumps(t["font"])};
  var STUDIO_TEXT = {json.dumps(t["text"])};
  var STUDIO_MUTED = {json.dumps(t["muted"])};
  var COLOR_MAP = {{}};
  for (var i = 0; i < STANDALONE.length; i++) {{
    COLOR_MAP[STANDALONE[i].toLowerCase()] = STUDIO_COLORS[i % STUDIO_COLORS.length];
  }}
  COLOR_MAP[ACCENT_OLD.toLowerCase()] = ACCENT_NEW;

  function rgbToHex(r, g, b) {{
    return "#" + [r, g, b].map(function (v) {{ return ("0" + parseInt(v, 10).toString(16)).slice(-2); }}).join("");
  }}
  function mapColor(c) {{
    if (typeof c !== "string") return c;
    var low = c.trim().toLowerCase();
    if (COLOR_MAP[low]) return COLOR_MAP[low];
    var rgba = low.match(/^rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([0-9.]+))?\\s*\\)$/);
    if (rgba) {{
      var mapped = COLOR_MAP[rgbToHex(rgba[1], rgba[2], rgba[3])];
      if (mapped) {{
        if (rgba[4] == null) return mapped;
        var r = parseInt(mapped.slice(1, 3), 16), g = parseInt(mapped.slice(3, 5), 16), b = parseInt(mapped.slice(5, 7), 16);
        return "rgba(" + r + "," + g + "," + b + "," + rgba[4] + ")";
      }}
    }}
    return c;
  }}

  document.querySelectorAll(".prog-fill").forEach(function (el) {{
    var bg = el.style && el.style.background;
    if (bg) {{
      var mapped = mapColor(bg);
      if (mapped && mapped !== bg) el.style.background = mapped;
    }}
  }});

  function applyStudioPlots() {{
    if (!window.Plotly) return;
    document.querySelectorAll(".js-plotly-plot").forEach(function (gd) {{
      if (!gd.data || !gd.data.length) return;
      var newData = gd.data.map(function (tr) {{
        var copy = Object.assign({{}}, tr);
        if (copy.type === "pie") {{
          if (copy.marker && Array.isArray(copy.marker.colors)) {{
            copy.marker = Object.assign({{}}, copy.marker, {{
              colors: copy.marker.colors.map(mapColor),
              line: Object.assign({{}}, copy.marker.line || {{}}, {{ color: "#ffffff", width: 2 }}),
            }});
          }}
        }} else {{
          if (copy.marker) {{
            var mk = Object.assign({{}}, copy.marker);
            if (Array.isArray(mk.color)) {{
              mk.color = mk.color.map(mapColor);
            }} else if (typeof mk.color === "string") {{
              mk.color = mapColor(mk.color);
            }}
            if (mk.line && typeof mk.line.color === "string") {{
              mk.line = Object.assign({{}}, mk.line, {{ color: mapColor(mk.line.color) }});
            }}
            if (copy.type === "bar") mk.cornerradius = 5;
            copy.marker = mk;
          }}
          if (copy.line && typeof copy.line.color === "string") {{
            copy.line = Object.assign({{}}, copy.line, {{ color: mapColor(copy.line.color) }});
          }}
          if (typeof copy.fillcolor === "string") {{
            copy.fillcolor = mapColor(copy.fillcolor);
          }}
        }}
        return copy;
      }});
      var lay = Object.assign({{}}, gd.layout || {{}});
      lay.paper_bgcolor = "rgba(0,0,0,0)";
      lay.plot_bgcolor = "rgba(0,0,0,0)";
      lay.font = Object.assign({{}}, lay.font || {{}}, {{ family: STUDIO_FONT, color: STUDIO_MUTED, size: 11 }});
      lay.hoverlabel = Object.assign({{}}, lay.hoverlabel || {{}}, {{
        bgcolor: STUDIO_TEXT,
        bordercolor: STUDIO_TEXT,
        font: Object.assign({{}}, (lay.hoverlabel && lay.hoverlabel.font) || {{}}, {{
          family: STUDIO_FONT, color: "#ffffff", size: 12,
        }}),
      }});
      ["xaxis", "yaxis"].forEach(function (ax) {{
        if (lay[ax]) {{
          lay[ax] = Object.assign({{}}, lay[ax], {{
            gridcolor: "rgba(22, 33, 27, 0.08)",
            zerolinecolor: "rgba(22, 33, 27, 0.14)",
            tickfont: Object.assign({{}}, lay[ax].tickfont || {{}}, {{ family: STUDIO_FONT, color: STUDIO_MUTED, size: 11 }}),
          }});
        }}
      }});
      try {{ window.Plotly.react(gd, newData, lay); }} catch (e) {{}}
    }});
  }}

  var resizeTimer = null;
  function resizePlots() {{
    if (!window.Plotly) return;
    document.querySelectorAll(".js-plotly-plot").forEach(function (gd) {{
      try {{ window.Plotly.Plots.resize(gd); }} catch (e) {{}}
    }});
  }}
  window.addEventListener("resize", function () {{
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resizePlots, 120);
  }});

  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", function () {{ applyStudioPlots(); setTimeout(resizePlots, 60); }});
  }} else {{
    applyStudioPlots();
    setTimeout(resizePlots, 60);
  }}
}})();
"""

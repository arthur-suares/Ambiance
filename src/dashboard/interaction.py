"""Parte D: movimento e interação dos painéis, sem biblioteca nova (só o Plotly já embutido).

Regras (D5):
- O valor final exato e formatado está SEMPRE no HTML (texto do elemento e `data-value`). A animação só
  decora: sem JavaScript, com "reduzir movimento" ou na impressão, aparecem os valores finais.
- Animações de 250 a 900 ms, disparadas quando o cartão entra na tela (IntersectionObserver).
- Os controles (ver como, período, tela cheia, baixar) nunca consultam dados nem recalculam números:
  trocam visões já montadas no servidor ou filtram linhas que já estão na página.
"""

from __future__ import annotations

import html

import pandas as pd

MOTION_CSS = """
/* D1/D2: movimento. Só existe com a classe js-motion, que o script põe se o leitor não pediu menos
   movimento; sem JS tudo aparece pronto. */
.js-motion .card, .js-motion .kpi { opacity: 0; transform: translateY(8px);
  transition: opacity .45s ease-out, transform .45s ease-out, border-color .2s ease; }
.js-motion .card.is-in, .js-motion .kpi.is-in { opacity: 1; transform: none; }
.js-motion .card.is-in:hover { transform: translateY(-2px); border-color: var(--line); }
.js-plotly-plot .point, .js-plotly-plot .slice, .js-plotly-plot .trace { transition: opacity .2s ease; }
.js-plotly-plot .is-dim { opacity: .3; }

/* D3: controles do cartão */
.card-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s2); margin-top: var(--s2); }
.card-actions .btn-ghost { display: inline-flex; align-items: center; gap: var(--s1); }
.view-switch { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s1); margin: 0 0 var(--s2);
  font-size: var(--t-xs); color: var(--muted); }
.view-switch button { border: 1px solid var(--border); background: transparent; color: var(--fg); font: inherit;
  font-size: var(--t-xs); padding: 2px var(--s2); border-radius: var(--r-sm); cursor: pointer; }
.view-switch button[aria-pressed="true"] { background: var(--panel-2); border-color: var(--muted); font-weight: 650; }
.view[hidden] { display: none !important; }
.period-filter { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s2); margin: 0 0 var(--s2);
  font-size: var(--t-xs); color: var(--muted); }
.period-filter select { font: inherit; font-size: var(--t-xs); color: var(--fg); background: var(--panel);
  border: 1px solid var(--border); border-radius: var(--r-sm); padding: 2px var(--s1); }
.period-note { font-size: var(--t-xs); color: var(--muted); }
.card:fullscreen { overflow: auto; padding: var(--s6); background: var(--panel); }
.card:fullscreen .plot-wrap .js-plotly-plot { min-height: 70vh; }
tr[hidden] { display: none; }
@media (prefers-reduced-motion: reduce) {
  .js-motion .card, .js-motion .kpi { opacity: 1 !important; transform: none !important; }
}
@media print {
  .js-motion .card, .js-motion .kpi { opacity: 1 !important; transform: none !important; }
  .card-actions, .view-switch, .period-filter { display: none !important; }
}
"""

MOTION_JS = r"""
(function () {
  var d = document.documentElement;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var EASE = function (t) { return 1 - Math.pow(1 - t, 3); };

  // --- D5: o texto final fica guardado; a animação só passa por números intermediários ---------------
  function numParts(txt) {
    var m = /^([^0-9]*?)(-?[0-9][0-9.]*(?:,[0-9]+)?)(.*)$/.exec(txt || "");
    if (!m) return null;
    var dec = m[2].indexOf(",") >= 0 ? m[2].split(",")[1].length : 0;
    var thousands = m[2].indexOf(".") >= 0;
    var n = parseFloat(m[2].replace(/\./g, "").replace(",", "."));
    return isNaN(n) ? null : { pre: m[1], n: n, dec: dec, thousands: thousands, post: m[3] };
  }
  function fmt(p, v) {
    var s = v.toFixed(p.dec).replace(".", ",");
    if (p.thousands) {
      var parts = s.split(","); parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      s = parts.join(",");
    }
    return p.pre + s + p.post;
  }
  function countUp(el) {
    var final = el.getAttribute("data-final") || el.textContent;
    el.setAttribute("data-final", final);
    var p = numParts(final);
    if (!p) return;
    var t0 = null, dur = 800;
    function step(ts) {
      if (t0 === null) t0 = ts;
      var k = Math.min(1, (ts - t0) / dur);
      el.textContent = k < 1 ? fmt(p, p.n * EASE(k)) : final;
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  function finishAll() {
    document.querySelectorAll("[data-final]").forEach(function (el) { el.textContent = el.getAttribute("data-final"); });
    document.querySelectorAll(".card, .kpi").forEach(function (c) { c.classList.add("is-in"); });
  }
  window.addEventListener("beforeprint", finishAll);

  // --- D1: entrada dos gráficos ---------------------------------------------------------------------
  function animateTo(el, prop, from, to, dur) {
    el.style.transition = "none"; el.style[prop] = from;
    void el.getBoundingClientRect();
    el.style.transition = prop + " " + dur + "ms cubic-bezier(.2,.7,.2,1)"; el.style[prop] = to;
    setTimeout(function () { el.style.transition = ""; el.style[prop] = ""; }, dur + 60);
  }
  function drawPlot(card) {
    var kind = card.getAttribute("data-widget-kind");
    var horiz = card.getAttribute("data-orient") === "h";
    card.querySelectorAll(".js-plotly-plot").forEach(function (gd) {
      if (gd.closest(".view[hidden]")) return;
      gd.querySelectorAll(".scatterlayer .js-line").forEach(function (path) {
        if (path.style.strokeDasharray && path.style.strokeDasharray !== "none" && path.style.strokeDasharray.indexOf(",") >= 0) return;
        var len = path.getTotalLength ? path.getTotalLength() : 0;
        if (!len) return;
        path.style.strokeDasharray = len + " " + len;
        animateTo(path, "strokeDashoffset", String(len), "0", 900);
        setTimeout(function () { path.style.strokeDasharray = ""; }, 980);
      });
      gd.querySelectorAll(".barlayer .point path, .waterfalllayer .point path").forEach(function (bar) {
        bar.style.transformBox = "fill-box";
        bar.style.transformOrigin = horiz ? "left center" : "center bottom";
        animateTo(bar, "transform", horiz ? "scaleX(0)" : "scaleY(0)", "none", 700);
      });
      gd.querySelectorAll(".pielayer .trace").forEach(function (pie) {
        pie.style.transformBox = "fill-box"; pie.style.transformOrigin = "center";
        animateTo(pie, "transform", "rotate(-24deg) scale(.86)", "none", 750);
      });
    });
    card.querySelectorAll(".prog-fill").forEach(function (f) {
      f.style.transformOrigin = "left center"; animateTo(f, "transform", "scaleX(0)", "none", 700);
    });
    void kind;
  }
  function drawKpi(item) {
    item.querySelectorAll(".kpi-value, .gauge-value").forEach(countUp);
    item.querySelectorAll(".spark polyline").forEach(function (pl) {
      pl.style.strokeDasharray = "1 1"; animateTo(pl, "strokeDashoffset", "1", "0", 900);
      setTimeout(function () { pl.style.strokeDasharray = ""; }, 980);
    });
    item.querySelectorAll(".gauge-fill").forEach(function (g) {
      var full = g.getAttribute("stroke-dasharray");
      var circ = (full || "0 0").split(" ")[1];
      g.style.transition = "none"; g.style.strokeDasharray = "0 " + circ; void g.getBoundingClientRect();
      g.style.transition = "stroke-dasharray 900ms cubic-bezier(.2,.7,.2,1)"; g.style.strokeDasharray = full;
      setTimeout(function () { g.style.transition = ""; g.style.strokeDasharray = ""; }, 980);
    });
  }

  if (!reduce && "IntersectionObserver" in window) {
    d.classList.add("js-motion");
    var seen = 0;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target; io.unobserve(el);
        var delay = Math.min(seen++ % 6, 5) * 70;
        setTimeout(function () {
          el.classList.add("is-in");
          if (el.classList.contains("kpi")) drawKpi(el); else drawPlot(el);
        }, delay);
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".card, .kpi").forEach(function (c) { io.observe(c); });
  }

  // --- D2: destaque ao passar o mouse --------------------------------------------------------------
  function bindHover(gd) {
    if (!gd.on || gd.__hoverBound) return;
    gd.__hoverBound = true;
    gd.on("plotly_hover", function (ev) {
      var pt = ev.points && ev.points[0]; if (!pt) return;
      var traces = gd.querySelectorAll(".trace");
      var multi = gd.querySelectorAll(".scatterlayer .trace").length > 1;
      traces.forEach(function (t, i) {
        var pts = t.querySelectorAll(".point, .slice");
        if (multi && t.closest(".scatterlayer")) { t.classList.toggle("is-dim", i !== pt.curveNumber); return; }
        pts.forEach(function (p, j) { p.classList.toggle("is-dim", !(i === pt.curveNumber && j === pt.pointNumber)); });
      });
    });
    gd.on("plotly_unhover", function () {
      gd.querySelectorAll(".is-dim").forEach(function (el) { el.classList.remove("is-dim"); });
    });
  }
  document.querySelectorAll(".js-plotly-plot").forEach(bindHover);

  // --- D3: ver como, tela cheia, baixar ----------------------------------------------------------
  function resizeIn(root) {
    if (!window.Plotly) return;
    root.querySelectorAll(".js-plotly-plot").forEach(function (gd) {
      try { window.Plotly.Plots.resize(gd); } catch (e) {}
      bindHover(gd);
    });
  }
  document.querySelectorAll(".view-switch").forEach(function (sw) {
    var card = sw.closest(".card");
    sw.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.getAttribute("data-view");
        sw.querySelectorAll("button").forEach(function (o) { o.setAttribute("aria-pressed", o === b ? "true" : "false"); });
        card.querySelectorAll(".view").forEach(function (el) { el.hidden = el.getAttribute("data-view") !== v; });
        var shown = card.querySelector('.view[data-view="' + v + '"]');
        resizeIn(shown);
        if (!reduce) drawPlot(card);
      });
    });
  });
  document.querySelectorAll("[data-action]").forEach(function (b) {
    b.addEventListener("click", function () {
      var card = b.closest(".card"), act = b.getAttribute("data-action");
      var name = (card.getAttribute("data-widget-id") || "grafico");
      if (act === "fullscreen") {
        if (document.fullscreenElement) document.exitFullscreen(); else if (card.requestFullscreen) card.requestFullscreen();
      } else if (act === "image") {
        var gd = card.querySelector(".view:not([hidden]) .js-plotly-plot") || card.querySelector(".js-plotly-plot");
        if (gd && window.Plotly) window.Plotly.downloadImage(gd, { format: "png", filename: name, scale: 2 });
      } else if (act === "csv") {
        var tpl = card.querySelector("script.csv-data");
        if (!tpl) return;
        var blob = new Blob(["﻿" + tpl.textContent.replace(/<\\\//g, "</")], { type: "text/csv;charset=utf-8" });
        var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name + ".csv";
        document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
      }
    });
  });
  document.addEventListener("fullscreenchange", function () { resizeIn(document.fullscreenElement || document); });

  // --- D4: período (só filtra linhas que já existem) ---------------------------------------------------
  document.querySelectorAll(".period-filter").forEach(function (pf) {
    var card = pf.closest(".card");
    var from = pf.querySelector("[data-from]"), to = pf.querySelector("[data-to]");
    function apply() {
      var a = parseInt(from.value, 10), z = parseInt(to.value, 10);
      if (a > z) { var t = a; a = z; z = t; }
      card.querySelectorAll(".js-plotly-plot").forEach(function (gd) {
        if (!window.Plotly || !gd.data) return;
        // Guarda os pontos originais (já estão na página) e mostra só os do período; nada é criado.
        if (!gd.__orig) gd.__orig = (gd._fullData || gd.data).map(function (t) {
          // _fullData traz os números já decodificados (gd.data guarda {dtype, bdata}); Array.from
          // transforma os vetores tipados (Int16Array...) em listas comuns.
          return { x: Array.from(t.x || []), y: Array.from(t.y || []),
                   text: t.text && typeof t.text !== "string" ? Array.from(t.text) : null };
        });
        var xs = [], ys = [], txt = [], idx = [];
        gd.__orig.forEach(function (o, i) {
          var keep = o.x.map(function (v) { var n = parseFloat(v); return !isNaN(n) && n >= a && n <= z; });
          xs.push(o.x.filter(function (_, k) { return keep[k]; }));
          ys.push(o.y.filter(function (_, k) { return keep[k]; }));
          txt.push(o.text ? o.text.filter(function (_, k) { return keep[k]; }) : gd.data[i].text);
          idx.push(i);
        });
        try {
          window.Plotly.restyle(gd, { x: xs, y: ys, text: txt }, idx);
          window.Plotly.relayout(gd, { "xaxis.range": [a - 0.5, z + 0.5] });
        } catch (e) {}
      });
      card.querySelectorAll("tr[data-year]").forEach(function (tr) {
        var y = parseInt(tr.getAttribute("data-year"), 10); tr.hidden = y < a || y > z;
      });
      card.setAttribute("data-period", a + "-" + z);
    }
    from.addEventListener("change", apply); to.addEventListener("change", apply);
  });
})();
"""


def csv_template(df: pd.DataFrame, columns: list[str], *, header=None, label=None) -> str:
    """D3: CSV das linhas que o cartão mostra (as mesmas da consulta), no padrão do Excel brasileiro.

    Cabeçalhos e rótulos como na tela (`header(col)`, `label(valor, col)`); números exatos, sem arredondar.
    Fica num <script type="text/csv">, que o navegador não exibe."""
    cols = [c for c in columns if c in df.columns] or list(df.columns)
    out = df[cols].copy()
    if label is not None:
        for c in cols:
            if not pd.api.types.is_numeric_dtype(out[c]):
                out[c] = out[c].map(lambda v, c=c: label(v, c) if pd.notna(v) else "")
    if header is not None:
        out.columns = [header(c) for c in cols]
    texto = out.to_csv(index=False, sep=";", decimal=",").replace("</", _ESCAPED_CLOSE)
    return f'<script type="text/csv" class="csv-data">{texto}</script>'


_ESCAPED_CLOSE = "<" + chr(92) + "/"  # "</" vira "<\/" para não fechar o <script>


def card_actions(*, image: bool, csv_html: str) -> str:
    botoes = ['<button type="button" class="btn-ghost" data-action="fullscreen" aria-label="Ver em tela cheia">Tela cheia</button>']
    if image:
        botoes.append('<button type="button" class="btn-ghost" data-action="image" aria-label="Baixar imagem do gráfico">Baixar imagem</button>')
    if csv_html:
        botoes.append('<button type="button" class="btn-ghost" data-action="csv" aria-label="Baixar os dados em CSV">Baixar CSV</button>')
    return f'<div class="card-actions">{"".join(botoes)}{csv_html}</div>'


VIEW_LABELS = {"bar": "barras", "pie": "pizza", "donut": "rosca", "list": "lista"}


def view_switch(views: list[str], current: str) -> str:
    botoes = "".join(
        f'<button type="button" data-view="{v}" aria-pressed="{"true" if v == current else "false"}">{VIEW_LABELS[v]}</button>'
        for v in views)
    return f'<div class="view-switch" role="group" aria-label="Ver como"><span>Ver como:</span>{botoes}</div>'


def period_filter(years: list[int]) -> str:
    """D4: de/até com os anos que JÁ estão nos dados. Nada é somado: só esconde linhas e ajusta o eixo."""
    opts_de = "".join(f'<option value="{a}"{" selected" if i == 0 else ""}>{a}</option>' for i, a in enumerate(years))
    opts_ate = "".join(f'<option value="{a}"{" selected" if i == len(years) - 1 else ""}>{a}</option>'
                       for i, a in enumerate(years))
    return (f'<div class="period-filter"><span>Período:</span>'
            f'<label>de <select data-from aria-label="Ano inicial">{opts_de}</select></label>'
            f'<label>até <select data-to aria-label="Ano final">{opts_ate}</select></label>'
            f'<span class="period-note">a frase acima vale para todo o período</span></div>')


__all__ = ["MOTION_CSS", "MOTION_JS", "VIEW_LABELS", "card_actions", "csv_template", "period_filter", "view_switch"]

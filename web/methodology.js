"use strict";

(async () => {
  const status = document.getElementById("methodology-status");
  try {
    const response = await fetch("/api/agro/methodology");
    if (!response.ok) throw new Error("Catálogo indisponível.");
    const {metrics} = await response.json();
    const index = document.getElementById("methodology-index");
    const cards = document.getElementById("methodology-cards");
    for (const [id, metric] of Object.entries(metrics)) {
      const details = document.createElement("article");
      details.id = id;
      const summary = document.createElement("h3");
      summary.textContent = metric.label;
      details.append(summary);
      const list = document.createElement("dl");
      const years = metric.years?.join(", ") || [metric.start_year, metric.end_year].filter(Boolean).join("–");
      for (const [label, value] of [
        ["O que mede", metric.meaning], ["Unidade", metric.unit], ["Como é calculado", metric.calculation],
        ["Frequência", metric.frequency], ["Fonte", [metric.source, metric.version].filter(Boolean).join(" · ")],
        ["Anos carregados", years],
        ["Cobertura por bioma", metric.coverage?.map(m => `${m.bioma} · ${m.first} a ${m.last}`).join(" | ")],
        ["Limites de interpretação", metric.caveat],
      ]) {
        if (!value) continue;
        const term = document.createElement("dt");
        term.textContent = label;
        const description = document.createElement("dd");
        description.textContent = value;
        list.append(term, description);
      }
      details.append(list);
      if (metric.url && /^https:\/\//.test(metric.url)) {
        const source = document.createElement("a");
        source.href = metric.url;
        source.textContent = "Acessar a fonte";
        details.append(source);
      }
      cards.append(details);
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = "#" + id;
      link.textContent = metric.label;
      item.append(link);
      index.append(item);
    }
    let active = cards.firstElementChild?.id;
    function openAnchor() {
      const anchor = location.hash.slice(1);
      if (Object.hasOwn(metrics, anchor)) active = anchor;
      for (const card of cards.children) card.hidden = card.id !== active;
      for (const link of index.querySelectorAll("a")) {
        if (link.hash === "#" + active) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
      }
      if (Object.hasOwn(metrics, anchor)) document.getElementById("catalogo").scrollIntoView({block: "start"});
    }
    addEventListener("hashchange", openAnchor);
    openAnchor();
    status.hidden = true;
  } catch (error) {
    status.textContent = error.message;
  }
})();

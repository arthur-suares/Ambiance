"use strict";

(() => {
  const pages = {
    studio: {label: "Studio", href: "/", icon: "✦"},
    explore: {label: "Explorar", href: "/explorar", icon: "◇"},
    timeline: {label: "Linha do Tempo", href: "/?view=timeline", icon: "◷"},
    dashboard: {label: "Dashboard", href: "/?view=dashboard", icon: "▥"},
    data: {label: "Dados", href: "/?view=data", icon: "▤"},
    method: {label: "Metodologia", href: "/metodologia", icon: "◎"},
    monitor: {label: "Monitor IA", href: "/monitor", icon: "◈"},
  };
  const layout = document.body;
  const hosted = window.parent !== window && new URLSearchParams(location.search).get("embedded") === "1";

  function highlight(view) {
    document.querySelectorAll(".product-nav [data-view]").forEach(link => {
      if (link.dataset.view === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function navigate(view, href, carryContext = false) {
    document.dispatchEvent(new CustomEvent("ambiance:navigate", {detail: {view, href, carryContext}}));
  }

  if (hosted) {
    layout.dataset.embedded = "true";
  } else {
    const rail = document.createElement("aside");
    rail.className = "product-rail";
    rail.innerHTML = '<a href="/" class="product-brand" aria-label="Ambiance · Studio"><i aria-hidden="true"></i>Ambiance</a>';
    rail.firstElementChild.dataset.view = "studio";
    const nav = document.createElement("nav");
    nav.className = "product-nav";
    nav.setAttribute("aria-label", "Áreas do Ambiance");
    for (const [view, page] of Object.entries(pages)) {
      const a = document.createElement("a");
      a.href = page.href;
      a.dataset.view = view;
      const icon = document.createElement("span");
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = page.icon;
      a.append(icon, page.label);
      nav.append(a);
    }
    rail.append(nav);
    layout.prepend(rail);
    highlight(layout.dataset.productPage);
  }

  if (hosted || layout.dataset.productPage === "studio") {
    document.addEventListener("click", event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const jump = event.target.closest("[data-product-jump]");
      const link = event.target.closest("a[href]");
      const url = link ? new URL(link.href) : null;
      if (hosted && url?.protocol === "https:" && url.origin !== location.origin && !link.target) {
        link.target = "_blank";
        link.rel = "noopener";
      }
      if (!jump && (!url || url.origin !== location.origin || link.target || link.download)) return;
      const view = jump?.dataset.productJump || link?.dataset.view ||
        (url.pathname === "/metodologia" && layout.dataset.productPage !== "method" ? "method" :
          url.pathname === "/monitor" && layout.dataset.productPage !== "monitor" ? "monitor" :
            url.pathname === "/explorar" && layout.dataset.productPage !== "explore" ? "explore" : null);
      if (!pages[view]) return;
      event.preventDefault();
      const carryContext = Boolean(jump);
      if (hosted) {
        window.parent.postMessage({type: "ambiance:navigate", view, href: url?.href, carryContext}, location.origin);
      } else {
        navigate(view, link?.dataset.view ? null : url?.href, carryContext);
      }
    });
  }

  window.AmbianceProduct = {pages, highlight, navigate};
})();

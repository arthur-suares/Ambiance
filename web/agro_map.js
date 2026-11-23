"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 1});
  const fmtInt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 0});
  const n = (v, dec = 1) => v == null ? "—" : (dec === 0 ? fmtInt.format(v) : fmt.format(v));

  const BRAZIL_3D = {longitude: -57, latitude: -15.5, zoom: 3.9, pitch: 45, bearing: -10};  // centro deslocado: a legenda ocupa o canto esquerdo
  const BRAZIL_2D = {longitude: -53.2, latitude: -14.2, zoom: 3.7, pitch: 0, bearing: 0};

  const BASEMAPS = {
    dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    terrain: "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json",
  };

  const TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
  const SATELLITE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  const ELEVATION_DECODER = {rScaler: 256, gScaler: 1, bScaler: 1 / 256, offset: -32768};

  // Paletas sequenciais de uma matiz, com passos de luminosidade bem separados
  // (mapa claro: pouco = claro, muito = escuro).
  const PALETTES = {
    reds: [[255, 240, 190], [253, 204, 120], [247, 150, 72], [230, 92, 54], [186, 40, 46]],
    oranges: [[253, 238, 200], [247, 200, 115], [232, 150, 58], [194, 104, 28], [128, 64, 16]],
    greens: [[226, 241, 206], [174, 217, 143], [109, 180, 90], [47, 138, 62], [18, 86, 42]],
    blues: [[221, 238, 246], [163, 205, 227], [94, 166, 207], [43, 116, 174], [16, 66, 120]],
    purples: [[236, 230, 243], [195, 181, 220], [151, 127, 194], [106, 76, 159], [64, 38, 108]],
  };

  // Colunas de alerta e instalações: matizes diferentes do coroplético, para não se confundirem.
  const HEX_RANGES = {
    deter: {
      // Alertas em azul-ardósia: contrasta com o coroplético quente sem virar "lama".
      light: [[96, 140, 196], [70, 116, 180], [48, 92, 160], [30, 70, 138], [18, 50, 112], [8, 30, 80]],
      dark: [[96, 32, 16], [142, 46, 22], [190, 70, 34], [228, 110, 56], [247, 160, 100], [254, 218, 176]],
    },
    facilities: {
      light: [[214, 236, 228], [160, 210, 194], [100, 178, 152], [52, 140, 112], [22, 100, 78], [8, 62, 48]],
      dark: [[16, 64, 52], [24, 98, 78], [38, 136, 106], [72, 172, 138], [130, 206, 178], [204, 236, 224]],
    },
  };

  const isLight = () => AppState.basemap === "light";
  const hexRange = kind => HEX_RANGES[kind][isLight() ? "light" : "dark"];
  const arcFrom = () => isLight() ? [214, 128, 36] : [212, 162, 76];
  const arcTo = () => isLight() ? [52, 58, 54] : [236, 235, 230];

  const MATERIAL_3D = {ambient: 0.55, diffuse: 0.65, shininess: 36, specularColor: [60, 64, 70]};

  // Estado único centralizado (fonte única da verdade)
  const AppState = {
    preset: "risco",
    chain: "bovinos",
    uf: "",
    bioma: "",
    year: 2022,
    metric: "trase_bovinos_exposicao_5a_ha",
    basemap: "light",
    extrudeMun: false,
    hexMode: true,
    hexRadiusKm: 18,
    hexElevation: 120,
    showUfs: true,
    layers: {choro: true, deter: true, flows: false, facilities: false},
    flowCountry: "",
    selectedCode: null,
    highlightCodes: [],
    undoSnapshot: null,
    activeTab: "layers",
  };

  let deckgl = null;
  let geojson = null;
  let ufsGeo = null;
  let choroBreaks = null;
  let meta = null;
  let choroData = null;
  let flowsData = null;
  let deterData = null;
  let facilitiesData = null;
  let lastMunicipality = null;
  let currentView = {...BRAZIL_3D};
  let searchTimer = null;
  let playTimer = null;
  let lastHover = null;
  const munNames = new Map();
  const sessionHistory = [];

  function makeLighting() {
    const ambientLight = new deck.AmbientLight({color: [255, 255, 255], intensity: 1.1});
    const dirLight1 = new deck.DirectionalLight({color: [255, 248, 235], intensity: 1.8, direction: [-2, -6, -3]});
    const dirLight2 = new deck.DirectionalLight({color: [180, 215, 255], intensity: 0.8, direction: [4, 2, -2]});
    return new deck.LightingEffect({ambientLight, dirLight1, dirLight2});
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  function renderInline(s) {
    return escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function renderMarkdown(text) {
    const lines = String(text ?? "").split("\n");
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (/^\s*\|.*\|\s*$/.test(l)) {
        // Tabela em markdown: | a | b | + linha |---|---| opcional
        const rows = [];
        for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) {
          if (/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) continue;
          rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim()));
        }
        i--;
        const [head, ...body] = rows;
        out.push(`<div class="table-wrap"><table><thead><tr>${head.map(c => `<th>${renderInline(c)}</th>`).join("")}</tr></thead>` +
          `<tbody>${body.map(r => `<tr>${r.map(c => `<td>${renderInline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      } else if (/^\s*#{1,4}\s+/.test(l)) {
        out.push(`<h4>${renderInline(l.replace(/^\s*#{1,4}\s+/, ""))}</h4>`);
      } else if (/^\s*[-*•]\s+/.test(l)) {
        let html = "<ul>";
        for (; i < lines.length && /^\s*[-*•]\s+/.test(lines[i]); i++) {
          html += `<li>${renderInline(lines[i].replace(/^\s*[-*•]\s+/, ""))}</li>`;
        }
        i--;
        out.push(html + "</ul>");
      } else if (/^\s*\d+[.)]\s+/.test(l)) {
        let html = "<ol>";
        for (; i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i]); i++) {
          html += `<li>${renderInline(lines[i].replace(/^\s*\d+[.)]\s+/, ""))}</li>`;
        }
        i--;
        out.push(html + "</ol>");
      } else if (l.trim()) {
        out.push(`<p>${renderInline(l)}</p>`);
      }
    }
    return out.join("");
  }

  // Visão do Brasil ajustada ao tamanho do mapa: em telas largas o centro vai para a
  // direita (a legenda ocupa a esquerda); em telas estreitas centraliza e afasta.
  function brazilView() {
    const w = $("map-canvas").clientWidth || 1000;
    if (w < 700) return {longitude: -52.5, latitude: -15, zoom: 2.9, pitch: 35, bearing: -8};
    if (w < 1000) return {longitude: -56, latitude: -15, zoom: 3.4, pitch: 42, bearing: -10};
    const h = $("map-canvas").clientHeight || 700;
    const fit = Math.log2(Math.min(w / 1150, h / 720));  // telas maiores aproximam mais
    return {...BRAZIL_3D, zoom: Math.min(5, BRAZIL_3D.zoom + Math.max(0, fit))};
  }

  function setView(viewState, duration = 900) {
    const next = {
      longitude: viewState.longitude ?? currentView.longitude ?? BRAZIL_3D.longitude,
      latitude: viewState.latitude ?? currentView.latitude ?? BRAZIL_3D.latitude,
      zoom: viewState.zoom ?? currentView.zoom ?? BRAZIL_3D.zoom,
      pitch: viewState.pitch ?? currentView.pitch ?? 0,
      bearing: viewState.bearing ?? currentView.bearing ?? 0,
      transitionDuration: duration,
      transitionInterpolator: new deck.FlyToInterpolator({speed: 1.4}),
    };
    currentView = {
      longitude: next.longitude,
      latitude: next.latitude,
      zoom: next.zoom,
      pitch: next.pitch,
      bearing: next.bearing,
    };
    if (deckgl) deckgl.setProps({initialViewState: next});
  }

  function fitBbox(bbox) {
    if (!bbox || bbox.length !== 4) return;
    const [minLon, minLat, maxLon, maxLat] = bbox;
    const el = $("map-canvas");
    const vp = new deck.WebMercatorViewport({width: el.clientWidth || 800, height: el.clientHeight || 600})
      .fitBounds([[minLon, minLat], [maxLon, maxLat]], {padding: 80, maxZoom: 8.5, minExtent: 0.2});
    setView({
      longitude: vp.longitude,
      latitude: vp.latitude,
      zoom: vp.zoom,
      pitch: currentView.pitch,
      bearing: currentView.bearing,
    });
  }

  // As paletas vão do claro ao escuro; sobre o mapa escuro invertemos para que
  // o valor alto seja o mais claro. A legenda usa a mesma função.
  const DARK_PALETTES = {
    reds: [[74, 22, 16], [124, 34, 24], [176, 52, 34], [222, 92, 54], [250, 156, 98]],
    oranges: [[72, 36, 10], [122, 60, 14], [176, 92, 20], [222, 132, 40], [250, 186, 94]],
    greens: [[14, 52, 36], [22, 88, 58], [36, 128, 82], [72, 170, 112], [150, 214, 160]],
    blues: [[14, 36, 66], [22, 62, 108], [36, 96, 156], [72, 138, 200], [150, 196, 236]],
    purples: [[40, 22, 66], [66, 36, 108], [98, 62, 156], [138, 102, 200], [192, 166, 236]],
  };

  function paletteFor(name) {
    if (isLight()) return PALETTES[name] || PALETTES.reds;
    return DARK_PALETTES[name] || DARK_PALETTES.reds;
  }

  // Limites de cada faixa de cor (mesma escala log usada no mapa).
  // Quebras por quantis (20/40/60/80%) dos valores positivos do recorte.
  function quantileBreaks(values, steps = 5) {
    const v = Object.values(values || {}).map(Number).filter(x => x > 0).sort((a, b) => a - b);
    if (v.length < steps * 2) return null;
    const q = p => v[Math.min(v.length - 1, Math.floor(p * (v.length - 1)))];
    const edges = [0];
    for (let i = 1; i < steps; i++) edges.push(q(i / steps));
    edges.push(v[v.length - 1]);
    for (let i = 1; i < edges.length; i++) if (edges[i] <= edges[i - 1]) return null;
    return edges;
  }

  function stepEdges(maxVal, steps = 5) {
    const top = Math.log1p(Math.max(maxVal, 1));
    return Array.from({length: steps + 1}, (_, i) => Math.expm1((i / steps) * top));
  }

  const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;

  function rampColor(value, maxVal, paletteName, alpha = 195) {
    // Sem dado = transparente: deixa o mapa-base (rios, estados, nomes) aparecer.
    if (!value || value <= 0 || !maxVal) return [0, 0, 0, 0];
    const pal = paletteFor(paletteName);
    // Faixas por quantis: cada cor cobre ~20% dos municípios com dado,
    // então o mapa não fica todo da mesma cor quando poucos valores são enormes.
    const edges = choroBreaks || stepEdges(maxVal, pal.length);
    let idx = 0;
    while (idx < pal.length - 1 && value > edges[idx + 1]) idx++;
    return [...pal[idx], alpha];
  }

  function switchTab(tabName) {
    AppState.activeTab = tabName;
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("is-active", b.dataset.tab === tabName));
    document.querySelectorAll(".tab-panel").forEach(p => {
      const active = p.id === `tab-${tabName}`;
      p.classList.toggle("is-active", active);
      p.hidden = !active;
    });
  }

  function snapshotState() {
    return {
      preset: AppState.preset,
      chain: AppState.chain,
      uf: AppState.uf,
      bioma: AppState.bioma,
      year: AppState.year,
      metric: AppState.metric,
      basemap: AppState.basemap,
      extrudeMun: AppState.extrudeMun,
      hexMode: AppState.hexMode,
      layers: {...AppState.layers},
      flowCountry: AppState.flowCountry,
      highlightCodes: [...AppState.highlightCodes],
    };
  }

  function syncUI() {
    document.querySelectorAll(".preset-btn").forEach(b => {
      b.classList.toggle("is-active", b.dataset.preset === AppState.preset);
    });
    $("toggle-ufs").checked = AppState.showUfs;
    const crumb = [AppState.uf ? `Estado: ${AppState.uf}` : "Brasil"];
    if (AppState.bioma) crumb.push(AppState.bioma);
    if (lastMunicipality && AppState.selectedCode) crumb.push(lastMunicipality.municipio);
    $("crumb-text").textContent = crumb.join(" · ");
    $("chain-select").value = AppState.chain;
    $("bioma-select").value = AppState.bioma;
    $("uf-select").value = AppState.uf;
    $("year-slider").value = String(AppState.year);
    $("year-label").textContent = String(AppState.year);
    if ($("metric-select").options.length) $("metric-select").value = AppState.metric;

    $("toggle-choro").checked = AppState.layers.choro;
    $("toggle-deter").checked = AppState.layers.deter;
    $("toggle-flows").checked = AppState.layers.flows;
    $("toggle-facilities").checked = AppState.layers.facilities;
    $("flow-country").value = AppState.flowCountry;

    $("basemap-mode").value = AppState.basemap;
    $("toggle-extrude-mun").checked = AppState.extrudeMun;
    $("toggle-hex-mode").checked = AppState.hexMode;
    $("hex-controls").hidden = !AppState.hexMode;
    $("hex-radius").value = String(AppState.hexRadiusKm);
    $("hex-radius-val").textContent = `${AppState.hexRadiusKm} km`;
    $("hex-elevation").value = String(AppState.hexElevation);
    $("hex-elev-val").textContent = `${AppState.hexElevation}×`;

    $("ai-spec-banner").hidden = !AppState.undoSnapshot || !isMapOpen();

    const ctxParts = [
      AppState.uf || AppState.bioma || "Brasil",
      AppState.chain === "all" ? "Todas cadeias" : (AppState.chain === "soja" ? "Soja" : "Bovinos"),
      String(AppState.year),
    ];
    if (lastMunicipality && AppState.selectedCode) {
      ctxParts.push(lastMunicipality.municipio);
    }
    $("context-pill").textContent = isMapOpen() ? `Mapa: ${ctxParts.join(" · ")}` : "";
  }

  function applyPreset(name, autoRefresh = true) {
    AppState.preset = name;
    const soy = AppState.chain === "soja";
    const all = AppState.chain === "all";
    if (name === "risco") {
      AppState.metric = all ? "mapbiomas_desmatamento_ha" : (soy ? "trase_soja_exposicao_5a_ha" : "trase_bovinos_exposicao_5a_ha");
      AppState.layers = {choro: true, deter: true, flows: false, facilities: false};
      AppState.hexMode = true;
      AppState.extrudeMun = false;
    } else if (name === "emissoes") {
      AppState.metric = AppState.chain === "bovinos" ? "seeg_emissao_agro_tco2e" : "seeg_emissao_mut_tco2e";
      AppState.layers = {choro: true, deter: false, flows: false, facilities: false};
      AppState.extrudeMun = AppState.basemap !== "terrain";
      if (AppState.extrudeMun && (currentView.pitch || 0) < 30) setView({pitch: 48});
    } else if (name === "cadeias") {
      AppState.metric = soy ? "comex_soja_t" : "trase_bovinos_volume_t";
      // Frigoríficos ficam desligados por padrão (31 mil pontos competem com os arcos);
      // a câmera abre para mostrar os destinos do outro lado do oceano.
      AppState.layers = {choro: true, deter: false, flows: true, facilities: false};
      AppState.hexMode = false;
      AppState.extrudeMun = false;
      if (autoRefresh) setView({longitude: -20, latitude: 5, zoom: 2.3, pitch: 35, bearing: 0}, 1600);
    } else if (name === "producao") {
      AppState.metric = soy ? "ibge_soja_producao_t" : "ibge_bovinos_rebanho_cab";
      AppState.layers = {choro: true, deter: false, flows: false, facilities: false};
      AppState.extrudeMun = false;
    }
    syncUI();
    if (autoRefresh) refreshActiveLayers(false);
  }

  function munName(code) {
    if (munNames.has(code)) return munNames.get(code);
    munNames.set(code, null);
    fetch(`/api/agro/search?q=${encodeURIComponent(code)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        const hit = d?.results?.find(r => String(r.code) === code) || d?.results?.[0];
        if (hit) munNames.set(code, `${hit.municipio} (${hit.uf})`);
        if (lastHover && String(lastHover.object?.properties?.codarea || "") === code) showTooltip(lastHover);
      })
      .catch(() => {});
    return null;
  }

  function showTooltip(info) {
    const tip = $("map-tooltip");
    lastHover = info?.object ? info : null;
    if (!info || !info.object) {
      tip.hidden = true;
      return;
    }
    const o = info.object;
    let html = "";
    if (info.layer.id === "municipalities") {
      const code = String(o.properties?.codarea || "");
      const val = choroData?.values?.[code];
      const unit = choroData?.meta?.unit || "";
      const name = munName(code) || "Município";
      const sw = rampColor(val, choroData?.p95 || choroData?.max || 1, choroData?.meta?.palette || "reds");
      html = `<span class="tt-title">${escapeHtml(name)}</span>` +
        `<span class="tt-value">${val != null ? `<i style="background:${rgb(sw)}"></i>` + n(val) + " " + escapeHtml(unit) : "Sem registro"}</span>` +
        `<span class="tt-label">${escapeHtml((choroData?.meta?.label || "").split("(")[0])} · ${escapeHtml(choroData?.year || "")}</span><br>` +
        `<small>Clique para ver o raio-x</small>`;
    } else if (info.layer.id === "deter-hex") {
      const pts = o.points || [];
      const count = o.count ?? pts.length;
      const area = o.elevationValue ?? pts.reduce((acc, p) => acc + (p.source?.area_km2 || p.area_km2 || 0), 0);
      html = `<span class="tt-title">Alertas de desmatamento</span>` +
        `<span class="tt-value">${n(area, 1)} km²</span>` +
        `<span class="tt-label">${n(count, 0)} alertas INPE DETER · ${escapeHtml(deterData?.year || AppState.year)}</span>`;
    } else if (info.layer.id === "facilities-hex") {
      const count = o.count ?? (o.points ? o.points.length : 0);
      html = `<span class="tt-title">Frigoríficos e silos</span><span class="tt-value">${n(count, 0)}</span><span class="tt-label">unidades nesta área</span>`;
    } else if (info.layer.id === "trade-flows") {
      html = `<span class="tt-title">${escapeHtml(o.origin_name)} → ${escapeHtml(o.target_name)}</span>` +
        `<span class="tt-value">${n(o.volume_t, 0)} t</span>` +
        `<span class="tt-label">Exposição ao desmatamento (5 anos): ${n(o.exposicao_ha)} ha</span>`;
    } else if (info.layer.id === "deter-alerts") {
      html = `<strong>INPE DETER · ${escapeHtml(o.bioma)}</strong><br>` +
        `${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})<br>` +
        `Classe: ${escapeHtml(o.classname || "—")} · ${n(o.area_km2, 2)} km²`;
    } else if (info.layer.id === "facilities") {
      const cap = o.capacidade_valor ? `${n(o.capacidade_valor, 0)} ${escapeHtml(o.capacidade_unidade || "")}` : "Sem capacidade";
      html = `<strong>${escapeHtml(o.empresa || "Instalação")}</strong><br>` +
        `${escapeHtml(o.tipo || o.cadeia)} · ${escapeHtml(o.nivel_inspecao || "")} ${escapeHtml(o.numero_inspecao || "")}<br>` +
        `${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})<br><small>${cap}</small>`;
    }
    if (!html) {
      tip.hidden = true;
      return;
    }
    tip.innerHTML = html;
    // Mantém o tooltip dentro do mapa (vira para a esquerda/cima perto das bordas).
    const stage = $("map-canvas");
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    const x = info.x + 14 + w > stage.clientWidth ? info.x - w - 14 : info.x + 14;
    const y = info.y + 14 + h > stage.clientHeight ? info.y - h - 14 : info.y + 14;
    tip.style.left = `${Math.max(6, x)}px`;
    tip.style.top = `${Math.max(6, y)}px`;
  }

  function updateLegendAndUncertainty() {
    if (!choroData) return;
    const pal = paletteFor(choroData.meta.palette);
    const unit = choroData.meta.unit;
    const edges = choroBreaks || stepEdges(choroData.p95 || choroData.max || 0, pal.length);
    // Arredonda para 2 algarismos significativos: 0,034 · 2,8 · 62 · 710 · 1.200
    const fmtEdge = v => {
      if (!v) return "0";
      const p = Math.pow(10, Math.floor(Math.log10(Math.abs(v))) - 1);
      const r = Math.round(v / p) * p;
      return new Intl.NumberFormat("pt-BR", {maximumFractionDigits: Math.max(0, -Math.floor(Math.log10(p)))}).format(r);
    };
    const steps = pal.map((c, i) => {
      const label = i === pal.length - 1 ? `acima de ${fmtEdge(edges[i])}` : `${fmtEdge(edges[i])} – ${fmtEdge(edges[i + 1])}`;
      return `<li><span class="sw" style="background:${rgb(c)}"></span>${label} ${escapeHtml(unit)}</li>`;
    }).reverse();
    steps.push(`<li class="nodata"><span class="sw"></span>Sem registro</li>`);
    $("legend-steps").innerHTML = steps.join("");

    const extra = [];
    if (AppState.showUfs) extra.push(`<div class="row"><span class="line" style="border-color:#eceeea"></span>Limite estadual</div>`);
    if (AppState.layers.deter) {
      const r = hexRange("deter");
      extra.push(`<div class="row"><span class="col" style="background:linear-gradient(90deg, ${rgb(r[1])}, ${rgb(r[5])})"></span>Alertas DETER (altura = área)</div>`);
    }
    if (AppState.layers.flows) extra.push(`<div class="row"><span class="arc" style="background:linear-gradient(90deg, ${rgb(arcFrom())}, ${rgb(arcTo())})"></span>Fluxo de exportação</div>`);
    $("legend-extra").innerHTML = extra.join("");
    $("legend-title").textContent = choroData.meta.label;
    $("legend-mid").textContent = n((choroData.p95 || choroData.max || 0) * 0.5, 0);
    $("legend-max").textContent = `${n(choroData.p95 || choroData.max || 0, 0)}+`;

    $("ub-source").textContent = `Fonte: ${choroData.meta.source} · Ano ${choroData.year}`;
    if (choroData.coverage) {
      const pct = choroData.coverage.pct_rastreado;
      const unk = (100 - Number(pct)).toFixed(1).replace(".", ",");
      $("ub-coverage").textContent = `Cobertura rastreada: ${n(pct)}% (${unk}% UNKNOWN fora do mapa).`;
    } else {
      $("ub-coverage").textContent = `${n(choroData.count, 0)} municípios com registro neste recorte.`;
    }
    $("ub-caveat").textContent = choroData.meta.caveat;

    // Aviso inteligente de fallback de ano
    const notes = [];
    if (choroData.year_fallback) notes.push(`Coroplético: último ano ${choroData.year}`);
    if (AppState.layers.flows && flowsData?.year_fallback) notes.push(`Fluxos: último ano ${flowsData.year}`);
    if (AppState.layers.deter && deterData?.year_fallback) notes.push(`DETER: último ano ${deterData.year}`);
    $("year-fallback-badge").hidden = notes.length === 0;
    $("year-fallback-badge").textContent = notes.join(" · ");
  }

  function renderRanking() {
    const list = $("top-list");
    if (!choroData?.top?.length) {
      $("top-count").textContent = "0 municípios";
      list.innerHTML = "<li class='meta'>Sem dados neste recorte.</li>";
      return;
    }
    const unit = choroData.meta.unit;
    const topMax = choroData.top[0]?.value || 1;
    $("top-title").textContent = `Top 15 · ${choroData.year}`;
    $("top-count").textContent = `${n(choroData.count, 0)} municípios`;
    list.replaceChildren(...choroData.top.slice(0, 15).map((row, idx) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rank-item";
      const pct = Math.max(4, Math.min(100, (row.value / topMax) * 100));
      btn.innerHTML = `
        <div class="rank-row">
          <span>${idx + 1}. ${escapeHtml(row.name)} (${escapeHtml(row.uf)})</span>
          <strong>${n(row.value)} ${escapeHtml(unit)}</strong>
        </div>
        <div class="rank-bar-bg"><div class="rank-bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
      `;
      btn.addEventListener("click", () => {
        openMunicipality(row.code);
        if (row.lon && row.lat) {
          setView({longitude: row.lon, latitude: row.lat, zoom: 7.5, pitch: currentView.pitch || 48, bearing: currentView.bearing});
        }
      });
      li.append(btn);
      return li;
    }));
  }

  function drawLayers() {
    if (!deckgl || !geojson) return;
    const layers = [];
    const values = choroData?.values || {};
    const maxRef = choroData?.p95 || choroData?.max || 1;
    const palette = choroData?.meta?.palette || "reds";
    const terrainMode = AppState.basemap === "terrain";
    const extrudeMun = AppState.extrudeMun && !terrainMode;
    const hlSet = new Set(AppState.highlightCodes);

    const terrainExtensions = [];
    if (terrainMode && deck.TerrainLayer) {
      layers.push(new deck.TerrainLayer({
        id: "terrain-3d",
        minZoom: 0,
        maxZoom: 12,
        strategy: "no-overlap",
        elevationData: TERRARIUM_URL,
        elevationDecoder: ELEVATION_DECODER,
        texture: SATELLITE_URL,
        meshMaxError: 6.0,
        operation: "terrain+draw",
      }));
      if (deck._TerrainExtension) terrainExtensions.push(new deck._TerrainExtension());
    }

    if (AppState.layers.choro) {
      // Com hexágonos por cima, o coroplético recua para virar contexto.
      const hexOver = AppState.hexMode && AppState.layers.deter;
      const munAlpha = terrainMode ? 150 : (extrudeMun ? 220 : (hexOver ? (isLight() ? 225 : 110) : (isLight() ? 235 : 190)));
      layers.push(new deck.GeoJsonLayer({
        id: "municipalities",
        data: geojson,
        pickable: true,
        stroked: !extrudeMun,
        filled: true,
        extruded: extrudeMun,
        elevationScale: 1,
        material: MATERIAL_3D,
        lineWidthMinPixels: 0.3,
        autoHighlight: true,
        highlightColor: [236, 235, 230, 70],
        extensions: terrainExtensions,
        terrainDrawMode: terrainMode ? "drape" : undefined,
        getElevation: f => {
          if (!extrudeMun) return 0;
          const v = values[String(f.properties?.codarea || "")] || 0;
          if (!v || !maxRef) return 0;
          return Math.min(180000, (Math.log1p(v) / Math.log1p(Math.max(maxRef, 1))) * 140000);
        },
        getFillColor: f => {
          const code = String(f.properties?.codarea || "");
          if (code === AppState.selectedCode) return [212, 162, 76, 235];
          if (hlSet.has(code)) return [212, 162, 76, 170];
          return rampColor(values[code], maxRef, palette, munAlpha);
        },
        getLineColor: f => {
          const code = String(f.properties?.codarea || "");
          if (code === AppState.selectedCode || hlSet.has(code)) return [255, 255, 255, 255];
          return terrainMode ? [255, 255, 255, 50] : (isLight() ? [255, 255, 255, 120] : [236, 235, 230, 22]);
        },
        getLineWidth: f => {
          const code = String(f.properties?.codarea || "");
          return (code === AppState.selectedCode || hlSet.has(code)) ? 2 : 0.3;
        },
        lineWidthUnits: "pixels",
        updateTriggers: {
          getFillColor: [choroData, AppState.selectedCode, AppState.basemap, extrudeMun, AppState.highlightCodes.join(",")],
          getElevation: [choroData, extrudeMun],
          getLineColor: [AppState.selectedCode, AppState.basemap, AppState.highlightCodes.join(",")],
          getLineWidth: [AppState.selectedCode, AppState.highlightCodes.join(",")],
        },
        onHover: showTooltip,
        onClick: info => {
          const code = String(info?.object?.properties?.codarea || "");
          if (code) openMunicipality(code);
        },
      }));
    }

    if (AppState.showUfs && ufsGeo) {
      const light = isLight() && !terrainMode;
      const ink = light ? [34, 38, 35] : [240, 242, 238];
      const halo = light ? [255, 255, 255] : [16, 18, 17];
      layers.push(new deck.GeoJsonLayer({
        id: "ufs",
        data: ufsGeo,
        stroked: true,
        filled: false,
        pickable: false,
        lineWidthUnits: "pixels",
        getLineColor: f => f.properties.sigla === AppState.uf ? [63, 174, 122, 255] : [...ink, light ? 210 : 190],
        getLineWidth: f => f.properties.sigla === AppState.uf ? 3.2 : 1.4,
        extensions: terrainExtensions,
        updateTriggers: {getLineColor: [AppState.uf, AppState.basemap], getLineWidth: [AppState.uf]},
      }));
      layers.push(new deck.TextLayer({
        id: "uf-labels",
        data: ufsGeo.features,
        getPosition: f => f.properties.label,
        getText: f => f.properties.sigla,
        getSize: f => f.properties.sigla === AppState.uf ? 15 : 12,
        sizeUnits: "pixels",
        getColor: f => f.properties.sigla === AppState.uf ? [20, 110, 70, 255] : [...ink, 235],
        fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
        fontWeight: 700,
        characterSet: "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        fontSettings: {sdf: true, fontSize: 48, buffer: 6},
        outlineWidth: 3,
        outlineColor: [...halo, 230],
        billboard: true,
        parameters: {depthTest: false},
        updateTriggers: {getColor: [AppState.uf, AppState.basemap], getSize: [AppState.uf]},
      }));
    }

    if (AppState.layers.flows && flowsData?.arcs?.length) {
      // Município selecionado: seus fluxos acendem e os demais recuam.
      const sel = AppState.selectedCode;
      const hasSel = sel && flowsData.arcs.some(d => String(d.origin_code) === sel);
      const alphaFor = d => !hasSel ? 120 : (String(d.origin_code) === sel ? 255 : 18);
      layers.push(new deck.ArcLayer({
        id: "trade-flows",
        data: flowsData.arcs,
        pickable: true,
        greatCircle: true,
        getHeight: 0.35,
        getSourcePosition: d => d.source,
        getTargetPosition: d => d.target,
        getSourceColor: d => [...arcFrom(), alphaFor(d)],
        getTargetColor: d => [...arcTo(), Math.round(alphaFor(d) * 0.6)],
        getWidth: d => Math.min(4, 0.5 + Math.log1p(d.volume_t / 20000) * 0.6) * (hasSel && String(d.origin_code) === sel ? 2 : 1),
        widthUnits: "pixels",
        autoHighlight: true,
        highlightColor: [255, 255, 255, 220],
        updateTriggers: {getSourceColor: [sel], getTargetColor: [sel], getWidth: [sel]},
        transitions: {getSourceColor: 400, getTargetColor: 400, getWidth: 400},
        onHover: showTooltip,
      }));
    }

    if (AppState.layers.deter && deterData?.points?.length) {
      if (AppState.hexMode && deck.HexagonLayer) {
        layers.push(new deck.HexagonLayer({
          id: "deter-hex",
          data: deterData.points,
          pickable: true,
          extruded: true,
          gpuAggregation: false,
          radius: AppState.hexRadiusKm * 1000,
          coverage: 0.84,
          upperPercentile: 98,
          lowerPercentile: 35,  // esconde as colunas minúsculas que viravam "chuvisco" no mapa
          // Colunas mais baixas: altas demais elas furam a câmera quando a visão fica de cima (2D).
          elevationScale: AppState.hexElevation / 120,
          elevationRange: [0, 300000],  // metros: coluna mais alta ≈ 300 km no padrão
          colorRange: hexRange("deter"),
          material: MATERIAL_3D,
          getPosition: d => [d.lon, d.lat],
          getElevationWeight: d => Math.max(0.05, d.area_km2 || 0.1),
          elevationAggregation: "SUM",
          getColorWeight: d => Math.max(0.05, d.area_km2 || 0.1),
          colorAggregation: "SUM",
          extensions: terrainExtensions,
          onHover: showTooltip,
        }));
      } else {
        layers.push(new deck.ScatterplotLayer({
          id: "deter-alerts",
          data: deterData.points,
          pickable: true,
          radiusUnits: "pixels",
          radiusMinPixels: 2.5,
          radiusMaxPixels: 9,
          extensions: terrainExtensions,
          getPosition: d => [d.lon, d.lat],
          getRadius: d => Math.min(9, 2.5 + Math.sqrt(d.area_km2 || 0.1) * 2.5),
          getFillColor: d => {
            const c = String(d.classname || "").toUpperCase();
            if (c.includes("DESMAT")) return [222, 94, 48, 220];
            if (c.includes("QUEIM")) return [251, 184, 134, 200];
            return [244, 138, 84, 190];
          },
          onHover: showTooltip,
        }));
      }
    }

    if (AppState.layers.facilities && facilitiesData?.points?.length) {
      if (AppState.hexMode && deck.HexagonLayer && !AppState.layers.deter) {
        layers.push(new deck.HexagonLayer({
          id: "facilities-hex",
          data: facilitiesData.points,
          pickable: true,
          extruded: true,
          gpuAggregation: false,
          radius: AppState.hexRadiusKm * 1000,
          coverage: 0.82,
          upperPercentile: 98,
          elevationScale: AppState.hexElevation / 120,
          elevationRange: [0, 200000],
          colorRange: hexRange("facilities"),
          material: MATERIAL_3D,
          getPosition: d => [d.lon, d.lat],
          extensions: terrainExtensions,
          onHover: showTooltip,
        }));
      } else {
        layers.push(new deck.ScatterplotLayer({
          id: "facilities",
          data: facilitiesData.points,
          pickable: true,
          stroked: false,
          radiusUnits: "pixels",
          radiusMinPixels: 1.5,
          radiusMaxPixels: 5,
          extensions: terrainExtensions,
          getPosition: d => [d.lon, d.lat],
          getRadius: 2.5,
          getFillColor: d => d.cadeia === "bovinos" ? [102, 194, 164, 170] : [212, 162, 76, 170],
          onHover: showTooltip,
        }));
      }
    }

    deckgl.setProps({layers});
  }

  async function refreshActiveLayers(autoFit = false) {
    $("map-status").textContent = "Atualizando camadas…";
    const tasks = [];

    const choroQs = new URLSearchParams({metric: AppState.metric, year: String(AppState.year)});
    if (AppState.uf) choroQs.set("uf", AppState.uf);
    if (AppState.bioma) choroQs.set("bioma", AppState.bioma);
    tasks.push(
      fetch(`/api/agro/choropleth?${choroQs}`).then(r => r.json()).then(d => { choroData = d; choroBreaks = quantileBreaks(d.values); })
    );

    if (AppState.layers.flows) {
      const flowProd = AppState.chain === "soja" ? "soja" : "bovinos";
      const fqs = new URLSearchParams({product: flowProd, year: String(AppState.year)});
      if (AppState.uf) fqs.set("uf", AppState.uf);
      if (AppState.flowCountry) fqs.set("country", AppState.flowCountry);
      tasks.push(fetch(`/api/agro/flows?${fqs}`).then(r => r.json()).then(d => { flowsData = d; }));
    } else {
      flowsData = null;
    }

    if (AppState.layers.deter) {
      const dqs = new URLSearchParams({year: String(AppState.year), limit: "10000"});
      if (AppState.uf) dqs.set("uf", AppState.uf);
      if (AppState.bioma) dqs.set("bioma", AppState.bioma);
      tasks.push(fetch(`/api/agro/deter?${dqs}`).then(r => r.json()).then(d => { deterData = d; }));
    } else {
      deterData = null;
    }

    if (AppState.layers.facilities) {
      const iqs = new URLSearchParams({chain: AppState.chain, limit: "10000"});
      if (AppState.uf) iqs.set("uf", AppState.uf);
      tasks.push(fetch(`/api/agro/facilities?${iqs}`).then(r => r.json()).then(d => { facilitiesData = d; }));
    } else {
      facilitiesData = null;
    }

    try {
      await Promise.all(tasks);
      updateLegendAndUncertainty();
      renderRanking();
      drawLayers();
      $("map-status").textContent = `${n(choroData?.count || 0, 0)} municípios · PostGIS`;
      if (autoFit && choroData?.bbox) fitBbox(choroData.bbox);
    } catch (err) {
      $("map-status").textContent = `Erro ao carregar: ${err.message}`;
    }
  }

  function renderSparkline(series, metricKey) {
    const wrap = $("mun-sparkline");
    const pts = (series || [])
      .map(r => ({ano: r.ano, val: r[metricKey]}))
      .filter(p => p.val != null && Number.isFinite(Number(p.val)));
    if (pts.length < 2) {
      $("spark-title").textContent = "Série histórica";
      $("spark-range").textContent = "";
      wrap.innerHTML = "<p class='meta'>Sem série suficiente para esta métrica.</p>";
      return;
    }
    const vals = pts.map(p => Number(p.val));
    const minV = Math.min(...vals);
    const maxV = Math.max(...vals);
    const span = maxV - minV || 1;
    const W = 280;
    const H = 64;
    const pad = 6;
    const coords = pts.map((p, i) => {
      const x = pad + (i / (pts.length - 1)) * (W - pad * 2);
      const y = H - pad - ((Number(p.val) - minV) / span) * (H - pad * 2);
      return [x, y];
    });
    const pathD = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const areaD = `${pathD} L${coords[coords.length - 1][0].toFixed(1)},${H - pad} L${coords[0][0].toFixed(1)},${H - pad} Z`;
    const last = coords[coords.length - 1];

    $("spark-title").textContent = `${choroData?.meta?.label?.split("(")[0]?.trim() || metricKey} (${pts[0].ano}–${pts[pts.length - 1].ano})`;
    $("spark-range").textContent = `${n(minV, 0)} – ${n(maxV, 0)}`;
    wrap.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#d4a24c" stop-opacity="0.28"/>
            <stop offset="100%" stop-color="#d4a24c" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <path d="${areaD}" fill="url(#sparkFill)"/>
        <path d="${pathD}" fill="none" stroke="#d4a24c" stroke-width="1.75" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
        <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3" fill="#ecebe6"/>
      </svg>
    `;
  }

  async function openMunicipality(code) {
    AppState.selectedCode = code;
    drawLayers();
    const res = await fetch(`/api/agro/municipality?code=${encodeURIComponent(code)}&year=${encodeURIComponent(AppState.year)}`);
    if (!res.ok) return;
    const data = await res.json();
    lastMunicipality = data.municipality;
    const m = data.municipality;
    const s = data.snapshot || {};
    $("mun-title").textContent = `${m.municipio} (${m.uf})`;
    $("mun-sub").textContent = `IBGE ${m.code} · ${m.bioma || "—"} · ${n(m.area_km2, 0)} km² · Dados ${data.effective_year}`;

    // Cada indicador separado, com nome claro e um (i) que explica o que é e de onde vem.
    const v = (x, unit, dec = 0) => x != null ? `${n(x, dec)} ${unit}`.trim() : "—";
    const kpis = [
      {label: "Rebanho bovino", value: v(s.ibge_bovinos_rebanho_cab, "cabeças"),
       info: "Número de bois e vacas no município no ano, segundo a Pesquisa da Pecuária Municipal (IBGE PPM)."},
      {label: "Produção de soja", value: v(s.ibge_soja_producao_t, "t"),
       info: "Toneladas de soja colhidas no município no ano, segundo a Produção Agrícola Municipal (IBGE PAM)."},
      {label: "Desmatamento no ano", value: v(s.mapbiomas_desmatamento_ha, "ha", 1), wide: true,
       info: "Área de vegetação nativa removida no município neste ano, medida por satélite pelo MapBiomas. 1 hectare (ha) ≈ um campo de futebol."},
      {label: "Emissões da agropecuária", value: v(s.seeg_emissao_agro_tco2e, "t CO₂e"),
       info: "Gases de efeito estufa vindos da criação de animais e das lavouras (ex.: metano do gado, adubos), em toneladas de CO₂ equivalente. Fonte: SEEG."},
      {label: "Emissões por desmatamento", value: v(s.seeg_emissao_mut_tco2e, "t CO₂e"),
       info: "Gases emitidos pela mudança de uso da terra — principalmente derrubada e queima de vegetação. Fonte: SEEG (setor MUT)."},
      {label: "Exposição ao desmat. · carne", value: v(s.trase_bovinos_exposicao_5a_ha, "ha", 1),
       info: "Quanto do desmatamento dos últimos 5 anos no município está ligado à carne bovina que sai dele, segundo a Trase. É um indicador de risco, não prova de irregularidade de uma fazenda específica."},
      {label: "Exposição ao desmat. · soja", value: v(s.trase_soja_exposicao_5a_ha, "ha", 1),
       info: "Quanto do desmatamento dos últimos 5 anos no município está ligado à soja produzida nele, segundo a Trase. Indicador de risco, não prova de irregularidade."},
      {label: "Estabelecimentos de origem animal", value: v(s.inst_bovinos_total || 0, ""),
       info: "Unidades com inspeção sanitária (SIF/SIE/SIM) que processam produtos de origem animal: frigoríficos e abatedouros, laticínios, queijarias, pescado, ovos etc. Fonte: Trase Beef Logistics."},
      {label: "Armazéns de soja (silos)", value: v(s.inst_soja_total || 0, ""),
       info: "Silo é uma estrutura para guardar grãos depois da colheita. Aqui são os armazéns de soja registrados no município. Fonte: Trase Soy Facilities."},
    ];
    $("mun-grid").innerHTML = kpis.map((k, i) => `
      <div class="kpi${k.wide ? " kpi-wide" : ""}">
        <strong>${k.value}</strong>
        <span>${escapeHtml(k.label)}
          <button type="button" class="kpi-i" data-k="${i}" title="${escapeHtml(k.info)}" aria-label="O que é ${escapeHtml(k.label)}?" aria-expanded="false">i</button>
        </span>
      </div>`).join("") + `<div id="kpi-help" class="kpi-help" hidden></div>`;
    $("mun-grid").querySelectorAll(".kpi-i").forEach(btn => {
      btn.addEventListener("click", () => {
        const help = $("kpi-help");
        const k = kpis[Number(btn.dataset.k)];
        const open = btn.getAttribute("aria-expanded") === "true";
        $("mun-grid").querySelectorAll(".kpi-i").forEach(b => b.setAttribute("aria-expanded", "false"));
        if (open) { help.hidden = true; return; }
        btn.setAttribute("aria-expanded", "true");
        help.innerHTML = `<strong>${escapeHtml(k.label)}</strong>${escapeHtml(k.info)}`;
        help.hidden = false;
      });
    });

    renderSparkline(data.series, AppState.metric);

    if (data.deter_recent?.length) {
      $("mun-deter").textContent = "INPE DETER (2023–2026): " + data.deter_recent
        .map(d => `${d.ano}: ${n(d.alertas, 0)} alertas (${n(d.area_km2)} km²)`)
        .join(" · ");
    } else {
      $("mun-deter").textContent = "Sem alertas DETER registrados entre 2023 e 2026.";
    }
    $("mun-drawer").hidden = false;
    document.querySelector(".stage").classList.add("mun-open");
    syncUI();
  }

  async function applyMapSpec(spec) {
    if (!spec) return;
    AppState.undoSnapshot = snapshotState();
    if (spec.metric && meta?.metrics?.[spec.metric]) AppState.metric = spec.metric;
    if (spec.year) AppState.year = spec.year;
    if ("uf" in spec) AppState.uf = spec.uf || "";
    if ("bioma" in spec) AppState.bioma = spec.bioma || "";
    if (typeof spec.show_flows === "boolean") {
      AppState.layers.flows = spec.show_flows;
      if (spec.flow_product) AppState.chain = spec.flow_product;
    }
    if (typeof spec.show_deter === "boolean") {
      AppState.layers.deter = spec.show_deter;
      if (spec.deter_year && !spec.year) AppState.year = spec.deter_year;
    }
    AppState.highlightCodes = Array.isArray(spec.highlight_codes) ? spec.highlight_codes : [];
    if (!("uf" in spec) && !("bioma" in spec)) { AppState.uf = ""; AppState.bioma = ""; }
    syncUI();
    const fitRegion = Boolean(spec.uf || spec.bioma);
    await refreshActiveLayers(fitRegion);
    if (!fitRegion) {
      const bb = bboxOfCodes(AppState.highlightCodes);
      if (bb) fitBbox(bb); else setView(brazilView(), 1400);
    }
  }

  // Caixa que envolve os municípios citados pela IA (para enquadrar o mapa neles).
  function bboxOfCodes(codes) {
    if (!geojson || !codes?.length) return null;
    const want = new Set(codes.map(String));
    let b = null;
    for (const f of geojson.features) {
      if (!want.has(String(f.properties?.codarea))) continue;
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      for (const poly of polys) for (const [x, y] of poly[0]) {
        b = b ? [Math.min(b[0], x), Math.min(b[1], y), Math.max(b[2], x), Math.max(b[3], y)] : [x, y, x, y];
      }
    }
    return b;
  }

  // Reserva: se a IA não definiu o estado, mas a pergunta cita um pelo nome, usa ele.
  const UF_NAMES = {
    AC: "acre", AL: "alagoas", AP: "amapa", AM: "amazonas", BA: "bahia", CE: "ceara", DF: "distrito federal",
    ES: "espirito santo", GO: "goias", MA: "maranhao", MT: "mato grosso", MS: "mato grosso do sul",
    MG: "minas gerais", PA: "para", PB: "paraiba", PR: "parana", PE: "pernambuco", PI: "piaui",
    RJ: "rio de janeiro", RN: "rio grande do norte", RS: "rio grande do sul", RO: "rondonia",
    RR: "roraima", SC: "santa catarina", SP: "sao paulo", SE: "sergipe", TO: "tocantins",
  };
  function ufFromText(text) {
    const t = " " + String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z ]/g, " ") + " ";
    // nomes mais longos primeiro ("mato grosso do sul" antes de "mato grosso", "paraiba" antes de "para")
    const hits = Object.entries(UF_NAMES).sort((a, b) => b[1].length - a[1].length);
    for (const [uf, name] of hits) {
      if (t.includes(` ${name} `) || t.includes(` do ${name} `) || t.includes(` de ${name} `)) return uf;
    }
    return null;
  }
  const UF_LABEL = uf => {
    const name = UF_NAMES[uf];
    const pretty = {amapa: "Amapá", ceara: "Ceará", "espirito santo": "Espírito Santo", goias: "Goiás", maranhao: "Maranhão",
      para: "Pará", paraiba: "Paraíba", parana: "Paraná", piaui: "Piauí", rondonia: "Rondônia", "sao paulo": "São Paulo"}[name];
    return (pretty || name.replace(/\b\w/g, c => c.toUpperCase())) + ` (${uf})`;
  };
  const hasPlace = spec => Boolean(spec && (spec.uf || spec.bioma || spec.highlight_codes?.length));

  function renderAIResponse(data) {
    $("ai-answer").innerHTML = renderMarkdown(data.answer);
    const tablesWrap = $("ai-tables");
    tablesWrap.innerHTML = "";
    for (const tbl of (data.tables || [])) {
      if (!tbl.rows?.length) continue;
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      const cols = tbl.columns.slice(0, 6);
      wrap.innerHTML = `<table><thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>` +
        `<tbody>${tbl.rows.slice(0, 10).map(r => `<tr>${cols.map(c => `<td>${escapeHtml(r[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
      tablesWrap.append(wrap);
    }

    const laws = data.sources || [];
    $("ai-laws-box").hidden = laws.length === 0;
    if (laws.length) {
      $("ai-laws-summary").textContent = `Fontes jurídicas (${laws.length} trechos)`;
      $("ai-laws").innerHTML = laws.map(s =>
        `<li>${s.label ? "[" + escapeHtml(s.label) + "] " : ""}<strong>${escapeHtml(s.title)}</strong>, art. ${escapeHtml(s.artigo)} — ` +
        `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">fonte</a></li>`
      ).join("");
    }

    const calls = data.tool_calls || [];
    $("ai-sql-box").hidden = calls.length === 0;
    $("ai-sql").innerHTML = calls.map(c =>
      `<div class="sql-block"><strong>[${escapeHtml(c.label)}] ${escapeHtml(c.summary)} (${c.rows} linhas · ${c.seconds}s)</strong>\n${escapeHtml(c.output)}</div>`
    ).join("");

    $("ai-usage").textContent = `Tempo: ${data.seconds}s · Tokens: ${data.input_tokens} in / ${data.output_tokens} out · Domínio: ${data.domain}`;
    $("ai-result").hidden = false;
  }

  function renderHistory() {
    $("history-box").hidden = sessionHistory.length === 0;
    $("history-count").textContent = String(sessionHistory.length);
    $("history-list").replaceChildren(...sessionHistory.map(item => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.innerHTML = `<span>${escapeHtml(item.question.slice(0, 56))}${item.question.length > 56 ? "…" : ""}</span><strong>${escapeHtml(item.data.domain || "")}</strong>`;
      btn.addEventListener("click", async () => {
        $("question").value = item.question;
        $("asked-q").textContent = item.question;
        renderAIResponse(item.data);
        offerViews(item.data, item.data.domain === "law" ? "laws" : "agro");
      });
      li.append(btn);
      return li;
    }));
  }

  function openDrawer(tab) {
    $("left-drawer").hidden = false;
    document.querySelector(".stage").classList.add("drawer-open");
    switchTab(tab || AppState.activeTab);
  }

  function closeDrawer() {
    $("left-drawer").hidden = true;
    document.querySelector(".stage").classList.remove("drawer-open");
  }

  // ▶ percorre os anos; cada passo espera as camadas carregarem antes do próximo.
  function togglePlay() {
    const btn = $("year-play");
    if (playTimer) {
      clearTimeout(playTimer);
      playTimer = null;
      btn.textContent = "▶";
      btn.classList.remove("is-playing");
      return;
    }
    btn.textContent = "❚❚";
    btn.classList.add("is-playing");
    const slider = $("year-slider");
    if (AppState.year >= Number(slider.max)) AppState.year = Number(slider.min) - 1;
    const step = async () => {
      if (!playTimer) return;
      if (AppState.year >= Number(slider.max)) { togglePlay(); return; }
      AppState.year += 1;
      syncUI();
      await refreshActiveLayers(false);
      if (playTimer) playTimer = setTimeout(step, 900);
    };
    playTimer = setTimeout(step, 0);
  }

  function isMapOpen() { return $("app").classList.contains("map-open"); }

  function setPage(state) {
    const app = $("app");
    app.classList.toggle("is-home", state === "home");
    app.classList.toggle("has-answer", state !== "home");
    $("new-chat").hidden = state === "home";
  }

  // Abre o mapa (criando-o na primeira vez) e aplica o recorte vindo da IA.
  async function showMap(spec) {
    const firstTime = !isMapOpen();
    $("app").classList.add("map-open");
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    ensureMap();
    if (firstTime) window.dispatchEvent(new Event("resize"));
    if (spec) await applyMapSpec(spec);
    else {
      await refreshActiveLayers(false);
      setView(brazilView(), 1600);
    }
    syncUI();
  }

  function hideMap() {
    $("app").classList.remove("map-open");
    if (playTimer) togglePlay();
    syncUI();
  }

  async function askAI(question) {
    setPage("answer");
    $("ask-btn").disabled = true;
    const mode = $("ask-mode").value;
    $("asked-q").textContent = question;
    $("asked-q").hidden = false;
    $("ai-result").hidden = true;
    $("views").hidden = true;
    $("views-none").hidden = true;
    closeViews();
    $("pending").hidden = false;
    $("pending-txt").textContent = mode === "laws" ? "Buscando nas 29 leis…" : "Consultando dados e leis…";
    $("ask-status").textContent = "";
    $("question").value = "";

    const viewContext = isMapOpen() ? {
      preset: AppState.preset,
      chain: AppState.chain,
      uf: AppState.uf || null,
      bioma: AppState.bioma || null,
      year: AppState.year,
      metric: AppState.metric,
      selected_municipality: lastMunicipality && AppState.selectedCode
        ? {code: AppState.selectedCode, municipio: lastMunicipality.municipio, uf: lastMunicipality.uf}
        : null,
    } : null;

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question, mode, domain: mode === "laws" ? "law" : "auto", k: 6, view_context: viewContext}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Erro ao consultar IA.");

      // Se a IA não fixou o estado mas a pergunta cita um, o mapa abre nele.
      const spec = data.map_spec ? {...data.map_spec} : {};
      if (!spec.uf && !spec.bioma && mode !== "laws") {
        const uf = ufFromText(question);
        if (uf) spec.uf = uf;
      }
      data.map_spec = Object.keys(spec).length ? spec : null;

      $("pending").hidden = true;
      renderAIResponse(data);
      sessionHistory.unshift({question, data});
      if (sessionHistory.length > 12) sessionHistory.pop();
      renderHistory();
      offerViews(data, mode);
    } catch (err) {
      $("pending").hidden = true;
      $("ai-answer").innerHTML = `<p class="err">Não consegui responder agora: ${escapeHtml(err.message)}</p>`;
      for (const id of ["ai-tables", "ai-sql"]) $(id).innerHTML = "";
      for (const id of ["ai-laws-box", "ai-sql-box"]) $(id).hidden = true;
      $("ai-usage").textContent = "";
      $("ai-result").hidden = false;
    } finally {
      $("ask-btn").disabled = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Depois de cada resposta: avalia o que dá para mostrar e oferece as opções.
  // Pergunta só de lei → nenhuma; com lugar/indicador → Mapa; com tabelas numéricas → Gráficos.
  // ---------------------------------------------------------------------------
  let lastAnswer = null;

  function offerViews(data, mode) {
    lastAnswer = data;
    closeViews();
    const spec = data.map_spec;
    const charts = buildChartSpecs(data.tables || []);
    data._charts = charts;
    const mapOk = mode !== "laws" && spec && (hasPlace(spec) || spec.metric);

    if (mapOk) {
      const where = spec.uf ? UF_LABEL(spec.uf) : (spec.bioma || "Brasil");
      const metric = meta?.metrics?.[spec.metric || AppState.metric]?.label?.split("(")[0]?.trim() || "indicador";
      const n = spec.highlight_codes?.length || 0;
      $("view-map-desc").textContent = `${where} · ${metric}${n ? ` · ${n} municípios citados destacados` : ""}`;
    }
    if (charts.length) {
      $("view-charts-desc").textContent = `${charts.length} ${charts.length === 1 ? "gráfico" : "gráficos"} com os números usados na resposta`;
    }
    $("view-map").hidden = !mapOk;
    $("view-charts").hidden = !charts.length;
    $("views").hidden = !mapOk && !charts.length;
    $("views-none").hidden = mapOk || charts.length;
    $("views-none").textContent = data.domain === "law" || mode === "laws"
      ? "Resposta jurídica: não há mapa nem gráfico para esta pergunta."
      : "Esta resposta não tem números ou lugares para mostrar em mapa ou gráfico.";
  }

  function closeViews() {
    hideMap();
    $("app").classList.remove("charts-open");
    $("view-map").classList.remove("is-active");
    $("view-charts").classList.remove("is-active");
  }

  async function openMapView() {
    if (!lastAnswer?.map_spec) return;
    $("app").classList.remove("charts-open");
    $("view-charts").classList.remove("is-active");
    $("view-map").classList.add("is-active");
    await showMap(lastAnswer.map_spec);
    $("map-desc").textContent = describeMap(lastAnswer.map_spec);
    $("map-desc").hidden = false;
  }

  function openChartsView() {
    if (!lastAnswer?._charts?.length) return;
    hideMap();
    $("view-map").classList.remove("is-active");
    $("view-charts").classList.add("is-active");
    renderCharts(lastAnswer._charts, lastAnswer);
    $("app").classList.add("charts-open");
  }

  // Texto "o que você está vendo" do mapa, montado a partir do recorte aplicado.
  function describeMap(spec) {
    const m = meta?.metrics?.[AppState.metric];
    const metric = m?.label || "o indicador escolhido";
    const where = AppState.uf ? UF_LABEL(AppState.uf) : (AppState.bioma ? `o bioma ${AppState.bioma}` : "o Brasil");
    const parts = [`Cada município de ${where} está pintado pelo indicador "${metric}" em ${choroData?.year || AppState.year}: quanto mais escura a cor, maior o valor (as faixas estão logo abaixo).`];
    const n = AppState.highlightCodes.length;
    if (n) parts.push(`Os ${n} municípios citados na resposta aparecem contornados.`);
    if (AppState.layers.deter) parts.push("As colunas azuis são alertas de desmatamento do INPE (DETER): quanto mais alta, maior a área.");
    if (AppState.layers.flows) parts.push("Os arcos mostram para onde a produção é exportada (Trase).");
    parts.push("Clique em um município para ver todos os números dele.");
    return parts.join(" ");
  }

  // ---- Gráficos a partir das tabelas consultadas pela IA ----
  const SKIP_COL = /(^|_)(codigo|cod|code|ibge|id|geocodigo|lat|lon|latitude|longitude)(_|$)/i;
  const LABEL_PREF = /(municipio|munic|nome|name|pais|country|uf|estado|bioma|exportador|empresa|porto|destino)/i;
  const prettyCol = c => String(c).replace(/_/g, " ").replace(/\btco2e\b/i, "tCO₂e").replace(/^\w/, ch => ch.toUpperCase());
  const num = v => (v === null || v === "" || v === undefined) ? NaN : Number(String(v).replace(",", "."));

  function buildChartSpecs(tables) {
    const charts = [];
    for (const t of tables) {
      const rows = t.rows || [];
      const cols = t.columns || [];
      if (rows.length < 2) continue;
      const numeric = cols.filter(c => !SKIP_COL.test(c) && c.toLowerCase() !== "ano" &&
        rows.filter(r => Number.isFinite(num(r[c]))).length >= Math.max(2, rows.length * 0.7));
      const textCols = cols.filter(c => !numeric.includes(c) && !SKIP_COL.test(c) && c.toLowerCase() !== "ano");
      const yearCol = cols.find(c => /^ano$/i.test(c));
      const labelCol = textCols.find(c => LABEL_PREF.test(c)) || textCols[0];
      // Série no tempo: uma linha por ano e sem rótulo variando → gráfico de linha
      const labelsVary = labelCol && new Set(rows.map(r => r[labelCol])).size > 1;
      if (yearCol && !labelsVary) {
        for (const c of numeric.slice(0, 2)) {
          const pts = rows.map(r => ({x: Number(r[yearCol]), y: num(r[c])})).filter(p => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x);
          if (pts.length >= 3) charts.push({kind: "line", title: `${prettyCol(c)} ao longo dos anos`, col: c, pts, table: t});
        }
        continue;
      }
      if (!labelCol) continue;
      for (const c of numeric.slice(0, 3)) {
        const items = rows.map(r => ({label: String(r[labelCol] ?? "—") + (r.uf && labelCol !== "uf" ? ` (${r.uf})` : ""), v: num(r[c])}))
          .filter(d => Number.isFinite(d.v)).sort((a, b) => b.v - a.v).slice(0, 12);
        if (items.length >= 2 && items.some(d => d.v !== 0)) {
          charts.push({kind: "bar", title: `${prettyCol(c)} por ${prettyCol(labelCol).toLowerCase()}`, col: c, labelCol, items, table: t});
        }
      }
    }
    return charts.slice(0, 6);
  }

  function renderCharts(charts, data) {
    $("charts-title").textContent = $("asked-q").textContent || "Gráficos";
    $("charts-desc").textContent = "Estes gráficos usam exatamente as tabelas que a IA consultou no banco para escrever a resposta. " +
      "Cada gráfico diz o que está medindo e de qual consulta veio (D1, D2… são as mesmas referências citadas no texto).";
    $("charts-body").innerHTML = charts.map((c, k) => {
      const what = c.kind === "bar"
        ? `Cada barra é um(a) ${prettyCol(c.labelCol).toLowerCase()}; o comprimento é o valor de "${prettyCol(c.col)}". Ordenado do maior para o menor${c.items.length >= 12 ? " (12 primeiros)" : ""}.`
        : `A linha mostra como "${prettyCol(c.col)}" variou de ${c.pts[0].x} a ${c.pts[c.pts.length - 1].x}.`;
      const src = `Consulta [${escapeHtml(c.table.label || "D")}]: ${escapeHtml(c.table.purpose || "")}`;
      const svg = c.kind === "bar" ? barSvg(c) : lineSvg(c);
      return `<article class="chart-card" style="animation-delay:${k * 60}ms"><h3>${escapeHtml(c.title)}</h3><p class="chart-what">${escapeHtml(what)}</p>${svg}<p class="chart-src">${src}</p></article>`;
    }).join("");
  }

  function barSvg(c) {
    const W = 520, rowH = 26, labW = 170, valW = 78;
    const H = c.items.length * rowH + 6;
    const max = Math.max(...c.items.map(d => Math.abs(d.v))) || 1;
    const bw = W - labW - valW;
    const cut = s => s.length > 24 ? s.slice(0, 23) + "…" : s;
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(c.title)}">` +
      c.items.map((d, i) => {
        const y = i * rowH + 3, w = Math.max(2, (Math.abs(d.v) / max) * bw);
        return `<g class="bar-row"><title>${escapeHtml(d.label)}: ${n(d.v)}</title>` +
          `<text class="bar-label" x="${labW - 8}" y="${y + 16}" text-anchor="end">${escapeHtml(cut(d.label))}</text>` +
          `<rect class="bar" x="${labW}" y="${y + 4}" width="${w.toFixed(1)}" height="${rowH - 10}" rx="3" style="animation-delay:${i * 35}ms"/>` +
          `<text class="bar-val" x="${labW + w + 6}" y="${y + 16}">${n(d.v)}</text></g>`;
      }).join("") + `</svg>`;
  }

  function lineSvg(c) {
    const W = 520, H = 200, pl = 56, pr = 16, pt = 12, pb = 26;
    const xs = c.pts.map(p => p.x), ys = c.pts.map(p => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y1 = Math.max(...ys) * 1.08 || 1, y0 = Math.min(0, Math.min(...ys));
    const X = x => pl + ((x - x0) / (x1 - x0 || 1)) * (W - pl - pr);
    const Y = y => pt + (1 - (y - y0) / (y1 - y0 || 1)) * (H - pt - pb);
    const d = c.pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ");
    const ticks = [0, .5, 1].map(t => y0 + t * (y1 - y0));
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(c.title)}">` +
      ticks.map(t => `<line class="grid-line" x1="${pl}" x2="${W - pr}" y1="${Y(t)}" y2="${Y(t)}"/><text class="bar-label" x="${pl - 6}" y="${Y(t) + 4}" text-anchor="end">${n(t, 0)}</text>`).join("") +
      `<path d="${d}" fill="none" stroke="#2b74ae" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>` +
      c.pts.map(p => `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="3.5" fill="#2b74ae"><title>${p.x}: ${n(p.y)}</title></circle>`).join("") +
      `<text class="bar-label" x="${pl}" y="${H - 6}">${x0}</text><text class="bar-label" x="${W - pr}" y="${H - 6}" text-anchor="end">${x1}</text>` +
      `</svg>`;
  }

  function setupListeners() {
    document.querySelectorAll(".preset-btn").forEach(btn => {
      btn.addEventListener("click", () => applyPreset(btn.dataset.preset, true));
    });

    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    $("toggle-left").addEventListener("click", closeDrawer);
    document.querySelectorAll("[data-open]").forEach(btn => {
      btn.addEventListener("click", () => openDrawer(btn.dataset.open));
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && !$("left-drawer").hidden && !e.target.closest("textarea, input, select")) closeDrawer();
    });
    $("year-play").addEventListener("click", togglePlay);
    $("close-map").addEventListener("click", () => { hideMap(); $("view-map").classList.remove("is-active"); });
    $("open-map-btn").addEventListener("click", () => { $("map-desc").hidden = true; showMap(null); });
    $("view-map").addEventListener("click", openMapView);
    $("view-charts").addEventListener("click", openChartsView);
    $("close-charts").addEventListener("click", () => { $("app").classList.remove("charts-open"); $("view-charts").classList.remove("is-active"); });
    $("new-chat").addEventListener("click", () => {
      AppState.undoSnapshot = null;
      closeViews();
      $("views").hidden = true;
      $("views-none").hidden = true;
      setPage("home");
      $("asked-q").hidden = true;
      $("ai-result").hidden = true;
      $("question").focus();
    });
    $("map-canvas").addEventListener("mouseleave", () => { $("map-tooltip").hidden = true; lastHover = null; });
    $("btn-presentation").addEventListener("click", () => {
      document.body.classList.add("presentation-mode");
      $("exit-presentation").hidden = false;
    });
    $("exit-presentation").addEventListener("click", () => {
      document.body.classList.remove("presentation-mode");
      $("exit-presentation").hidden = true;
    });

    $("chain-select").addEventListener("change", () => {
      AppState.chain = $("chain-select").value;
      applyPreset(AppState.preset, true);
    });
    $("bioma-select").addEventListener("change", () => {
      AppState.bioma = $("bioma-select").value;
      syncUI();
      refreshActiveLayers(true);
    });
    $("uf-select").addEventListener("change", () => {
      AppState.uf = $("uf-select").value;
      syncUI();
      refreshActiveLayers(true);
    });

    $("year-slider").addEventListener("input", () => {
      AppState.year = Number($("year-slider").value);
      $("year-label").textContent = String(AppState.year);
    });
    $("year-slider").addEventListener("change", () => {
      syncUI();
      refreshActiveLayers(false);
    });

    $("metric-select").addEventListener("change", () => {
      AppState.metric = $("metric-select").value;
      syncUI();
      refreshActiveLayers(false);
    });
    $("toggle-choro").addEventListener("change", () => {
      AppState.layers.choro = $("toggle-choro").checked;
      drawLayers();
    });
    $("toggle-deter").addEventListener("change", () => {
      AppState.layers.deter = $("toggle-deter").checked;
      refreshActiveLayers(false);
    });
    $("toggle-flows").addEventListener("change", () => {
      AppState.layers.flows = $("toggle-flows").checked;
      refreshActiveLayers(false);
    });
    $("flow-country").addEventListener("change", () => {
      AppState.flowCountry = $("flow-country").value;
      if (AppState.layers.flows) refreshActiveLayers(false);
    });
    $("toggle-facilities").addEventListener("change", () => {
      AppState.layers.facilities = $("toggle-facilities").checked;
      refreshActiveLayers(false);
    });

    $("basemap-mode").addEventListener("change", () => {
      AppState.basemap = $("basemap-mode").value;
      deckgl?.setProps({mapStyle: BASEMAPS[AppState.basemap] || BASEMAPS.dark});
      if (AppState.basemap === "terrain") {
        AppState.extrudeMun = false;
        setView({pitch: 56, zoom: Math.max(currentView.zoom || 4, 5.2)});
      }
      syncUI();
      updateLegendAndUncertainty();
      drawLayers();
    });
    $("toggle-extrude-mun").addEventListener("change", () => {
      AppState.extrudeMun = $("toggle-extrude-mun").checked;
      if (AppState.extrudeMun && AppState.basemap === "terrain") {
        AppState.basemap = "dark";
        deckgl?.setProps({mapStyle: BASEMAPS.dark});
      }
      if (AppState.extrudeMun && (currentView.pitch || 0) < 30) setView({pitch: 48});
      syncUI();
      drawLayers();
    });
    $("toggle-ufs").addEventListener("change", () => {
      AppState.showUfs = $("toggle-ufs").checked;
      updateLegendAndUncertainty();
      drawLayers();
    });
    $("zoom-in").addEventListener("click", () => setView({zoom: (currentView.zoom || 4) + 1}, 400));
    $("zoom-out").addEventListener("click", () => setView({zoom: (currentView.zoom || 4) - 1}, 400));
    $("toggle-hex-mode").addEventListener("change", () => {
      AppState.hexMode = $("toggle-hex-mode").checked;
      syncUI();
      drawLayers();
    });
    $("hex-radius").addEventListener("input", () => {
      AppState.hexRadiusKm = Number($("hex-radius").value);
      $("hex-radius-val").textContent = `${AppState.hexRadiusKm} km`;
      drawLayers();
    });
    $("hex-elevation").addEventListener("input", () => {
      AppState.hexElevation = Number($("hex-elevation").value);
      $("hex-elev-val").textContent = `${AppState.hexElevation}×`;
      drawLayers();
    });

    const setCam = is3d => {
      $("cam-2d").classList.toggle("is-active", !is3d);
      $("cam-3d").classList.toggle("is-active", is3d);
      setView(is3d ? {pitch: 48, bearing: -12} : {pitch: 0, bearing: 0});
    };
    $("cam-2d").addEventListener("click", () => setCam(false));
    $("cam-3d").addEventListener("click", () => setCam(true));
    $("reset-view").addEventListener("click", () => {
      AppState.uf = "";
      AppState.bioma = "";
      AppState.highlightCodes = [];
      setView(brazilView());
      syncUI();
      refreshActiveLayers(false);
    });

    $("toggle-caveat").addEventListener("click", () => {
      const box = $("ub-caveat");
      box.hidden = !box.hidden;
      $("toggle-caveat").setAttribute("aria-expanded", String(!box.hidden));
    });

    // Busca autocomplete de municípios
    $("mun-search").addEventListener("input", () => {
      clearTimeout(searchTimer);
      const q = $("mun-search").value.trim();
      const box = $("mun-search-results");
      if (q.length < 2) {
        box.hidden = true;
        return;
      }
      searchTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/agro/search?q=${encodeURIComponent(q)}`);
          if (!res.ok) return;
          const {results} = await res.json();
          if (!results?.length) {
            box.innerHTML = "<div class='search-item'><span>Nenhum município encontrado</span></div>";
            box.hidden = false;
            return;
          }
          box.replaceChildren(...results.map(item => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "search-item";
            btn.innerHTML = `<strong>${escapeHtml(item.municipio)} (${escapeHtml(item.uf)})</strong><span>${escapeHtml(item.bioma || item.code)}</span>`;
            btn.addEventListener("click", () => {
              box.hidden = true;
              $("mun-search").value = `${item.municipio} (${item.uf})`;
              openMunicipality(item.code);
              if (item.lon && item.lat) setView({longitude: item.lon, latitude: item.lat, zoom: 8, pitch: 50, bearing: -10});
            });
            return btn;
          }));
          box.hidden = false;
        } catch {
          box.hidden = true;
        }
      }, 220);
    });
    document.addEventListener("click", e => {
      if (!e.target.closest(".search-wrap")) $("mun-search-results").hidden = true;
    });

    $("mun-close").addEventListener("click", () => {
      AppState.selectedCode = null;
      $("mun-drawer").hidden = true;
      document.querySelector(".stage").classList.remove("mun-open");
      syncUI();
      drawLayers();
    });
    $("mun-ask-ai").addEventListener("click", () => {
      if (!lastMunicipality) return;
      const m = lastMunicipality;
      const q = `Faça uma análise socioambiental completa de ${m.municipio} (${m.uf}, IBGE ${m.code}) cruzando IBGE, MapBiomas, SEEG, Trase e alertas INPE DETER recentes, e indique quais obrigações do Código Florestal se aplicam ao bioma ${m.bioma || ""}.`;
      $("question").value = q;
      askAI(q);
    });

    $("undo-ai-spec").addEventListener("click", async () => {
      const snap = AppState.undoSnapshot;
      if (!snap) return;
      Object.assign(AppState, snap);
      AppState.undoSnapshot = null;
      deckgl?.setProps({mapStyle: BASEMAPS[AppState.basemap] || BASEMAPS.dark});
      syncUI();
      await refreshActiveLayers(Boolean(AppState.uf || AppState.bioma));
    });

    $("question").addEventListener("keydown", e => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        $("ask-form").requestSubmit();
      }
    });
    $("ask-form").addEventListener("submit", e => {
      e.preventDefault();
      const q = $("question").value.trim();
      if (q) askAI(q);
    });
    document.querySelectorAll(".chip").forEach(btn => {
      btn.addEventListener("click", () => {
        $("question").value = btn.dataset.q;
        askAI(btn.dataset.q);
      });
    });
  }

  // O mapa (deck.gl + MapLibre) só é criado na primeira vez que aparece.
  function ensureMap() {
    if (deckgl) return;
    deckgl = new deck.DeckGL({
      container: "map-canvas",
      mapLib: maplibregl,
      mapStyle: BASEMAPS[AppState.basemap],
      initialViewState: {longitude: -50, latitude: -14, zoom: 2.6, pitch: 20, bearing: 0},
      controller: {maxPitch: 75},
      effects: [makeLighting()],
      onViewStateChange: ({viewState}) => {
        currentView = {
          longitude: viewState.longitude,
          latitude: viewState.latitude,
          zoom: viewState.zoom,
          pitch: viewState.pitch,
          bearing: viewState.bearing,
        };
      },
      layers: [],
    });
    drawLayers();
  }

  async function init() {
    setupListeners();
    syncUI();
    $("question").focus();

    try {
      const [metaRes, geoRes] = await Promise.all([
        fetch("/api/agro/meta"),
        fetch("/api/agro/geojson"),
      ]);
      fetch("/explorar/ufs.geojson").then(r => r.ok ? r.json() : null).then(d => {
        ufsGeo = d;
        drawLayers();
        updateLegendAndUncertainty();
      }).catch(() => {});
      if (!metaRes.ok) {
        const err = await metaRes.json().catch(() => ({}));
        $("map-status").textContent = `Banco indisponível: ${err.error || metaRes.status}`;
        return;
      }
      meta = await metaRes.json();
      geojson = await geoRes.json();

      $("metric-select").replaceChildren(
        ...Object.entries(meta.metrics).map(([k, v]) => new Option(v.label, k))
      );
      $("uf-select").replaceChildren(new Option("Brasil", ""), ...meta.ufs.map(u => new Option(u, u)));
      $("bioma-select").replaceChildren(new Option("Todos", ""), ...meta.biomes.map(b => new Option(b, b)));
      applyPreset("risco", false);
    } catch (err) {
      $("map-status").textContent = `Erro na inicialização: ${err.message}`;
    }
  }

  // O gesto de pinça do trackpad (Safari/Chrome no Mac, Windows com touchpad) ampliava a
  // PÁGINA inteira e obrigava a arrastar para ver as bordas. Aqui a pinça nunca amplia a
  // página: sobre o mapa ela vira zoom do mapa; fora dele é ignorada.
  function lockPageZoom() {
    let base = null;
    const overMap = e => e.target && e.target.closest && e.target.closest("#map-canvas");
    // Safari (macOS/iOS): eventos "gesture*"
    document.addEventListener("gesturestart", e => {
      e.preventDefault();
      base = overMap(e) ? (currentView.zoom || 4) : null;
    }, {passive: false});
    document.addEventListener("gesturechange", e => {
      e.preventDefault();
      if (base != null && deckgl) {
        const zoom = Math.max(1, Math.min(14, base + Math.log2(e.scale || 1)));
        currentView = {...currentView, zoom};
        deckgl.setProps({initialViewState: {...currentView, transitionDuration: 0}});
      }
    }, {passive: false});
    document.addEventListener("gestureend", e => { e.preventDefault(); base = null; }, {passive: false});
    // Chrome/Edge/Firefox: pinça chega como wheel + ctrlKey. Fora do mapa, bloqueia;
    // sobre o mapa, o próprio deck.gl já trata como zoom do mapa.
    document.addEventListener("wheel", e => {
      if (e.ctrlKey && !overMap(e)) e.preventDefault();
    }, {passive: false});
    // Ctrl/Cmd + "+"/"-"/"0" continuam funcionando (zoom de acessibilidade do navegador),
    // porque o layout se ajusta a qualquer tamanho.
  }

  lockPageZoom();
  window.addEventListener("DOMContentLoaded", init);
})();

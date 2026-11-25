"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 1});
  const fmtInt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 0});
  const n = (v, dec = 1) => v == null ? "—" : (dec === 0 ? fmtInt.format(v) : fmt.format(v));

  const BRAZIL_3D = {longitude: -53.2, latitude: -14.2, zoom: 3.9, pitch: 48, bearing: -12};
  const BRAZIL_2D = {longitude: -53.2, latitude: -14.2, zoom: 3.7, pitch: 0, bearing: 0};
  const BRAZIL_BOUNDS = [-74, -34, -34, 6];

  const BASEMAPS = {
    dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    terrain: "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json",
  };

  const TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
  const SATELLITE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  const ELEVATION_DECODER = {rScaler: 256, gScaler: 1, bScaler: 1 / 256, offset: -32768};

  const PALETTES = {
    reds: [[254, 229, 217], [252, 174, 145], [251, 106, 74], [222, 45, 38], [165, 15, 21]],
    oranges: [[254, 237, 222], [253, 190, 133], [253, 141, 60], [230, 85, 13], [166, 54, 3]],
    greens: [[237, 248, 233], [186, 228, 179], [116, 196, 118], [49, 163, 84], [0, 109, 44]],
    blues: [[239, 243, 255], [189, 215, 231], [107, 174, 214], [49, 130, 189], [8, 81, 156]],
    purples: [[242, 240, 247], [203, 201, 226], [158, 154, 200], [117, 107, 177], [84, 39, 143]],
  };

  const HEX_DETER_RANGE = [
    [1, 152, 189], [73, 227, 206], [216, 254, 181],
    [254, 237, 177], [254, 173, 84], [209, 55, 78],
  ];

  const MATERIAL_3D = {ambient: 0.55, diffuse: 0.65, shininess: 36, specularColor: [60, 64, 70]};

  const THEMES = {
    producao: ["ibge_soja_producao_t", "ibge_bovinos_rebanho_cab"],
    cadeias: ["comex_soja_t", "comex_bovinos_t", "trase_soja_volume_t", "trase_bovinos_volume_t"],
    risco: ["mapbiomas_desmatamento_ha", "inpe_deter_area_km2", "trase_soja_exposicao_5a_ha", "trase_bovinos_exposicao_5a_ha"],
    emissoes: ["seeg_emissao_agro_tco2e", "seeg_emissao_mut_tco2e"],
  };
  const METRIC_CHAIN = {
    ibge_soja_producao_t: "soja",
    trase_soja_volume_t: "soja",
    trase_soja_exposicao_5a_ha: "soja",
    comex_soja_t: "soja",
    ibge_bovinos_rebanho_cab: "bovinos",
    trase_bovinos_volume_t: "bovinos",
    trase_bovinos_exposicao_5a_ha: "bovinos",
    comex_bovinos_t: "bovinos",
  };
  const biomeKey = value => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  // Estado único centralizado (fonte única da verdade)
  const AppState = {
    preset: "",
    chain: "soja",
    uf: "",
    bioma: "",
    year: null,
    yearPinned: false,
    facilityChain: "all",
    metric: "",
    basemap: "light",
    extrudeMun: false,
    hexMode: true,
    deterHeat: "",
    hexRadiusKm: 18,
    hexElevation: 120,
    layers: {choro: false, deter: false, flows: false, facilities: false},
    flowCountry: "",
    selectedCode: null,
    highlightCodes: [],
    undoSnapshot: null,
    activeTab: "ranking",
  };

  let deckgl = null;
  let geojson = null;
  let states = null;
  let layersRequest = null;
  let meta = null;
  let choroData = null;
  let flowsData = null;
  let deterData = null;
  let deterHeatData = null;
  let facilitiesData = null;
  let lastMunicipality = null;
  let yearOptions = [];
  let currentView = {...BRAZIL_2D};
  let municipalityRequest;
  let searchTimer = null;
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
      if (/^\s*#{1,4}\s+/.test(l)) {
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

  function setView(viewState) {
    const next = {
      longitude: viewState.longitude ?? currentView.longitude ?? BRAZIL_3D.longitude,
      latitude: viewState.latitude ?? currentView.latitude ?? BRAZIL_3D.latitude,
      zoom: viewState.zoom ?? currentView.zoom ?? BRAZIL_3D.zoom,
      pitch: viewState.pitch ?? currentView.pitch ?? 0,
      bearing: viewState.bearing ?? currentView.bearing ?? 0,
      transitionDuration: 600,
      transitionInterpolator: new deck.FlyToInterpolator(),
    };
    currentView = {
      longitude: next.longitude,
      latitude: next.latitude,
      zoom: next.zoom,
      pitch: next.pitch,
      bearing: next.bearing,
    };
    $("cam-2d").setAttribute("aria-pressed", String(next.pitch < 1));
    $("cam-3d").setAttribute("aria-pressed", String(next.pitch >= 1));
    deckgl.setProps({initialViewState: next});
  }

  function fitBbox(bbox) {
    if (!bbox || bbox.length !== 4) return;
    const [minLon, minLat, maxLon, maxLat] = bbox;
    const el = $("map-canvas");
    const width = el.clientWidth || 800;
    const height = el.clientHeight || 600;
    const padding = Math.round(Math.min(72, width * 0.12, height * 0.14));
    const vp = new deck.WebMercatorViewport({width, height})
      .fitBounds([[minLon, minLat], [maxLon, maxLat]], {padding, maxZoom: 8.5, minExtent: 0.2});
    setView({
      longitude: vp.longitude,
      latitude: vp.latitude,
      zoom: vp.zoom,
      pitch: currentView.pitch,
      bearing: currentView.bearing,
    });
  }

  function rampColor(value, maxVal, paletteName, alpha = 195) {
    if (!value || value <= 0 || !maxVal) {
      return AppState.basemap === "light" ? [230, 236, 233, 110] : [26, 38, 35, 75];
    }
    const pal = PALETTES[paletteName] || PALETTES.reds;
    const t = Math.min(1, value / maxVal);
    const idx = Math.min(pal.length - 1, Math.floor(t * pal.length));
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

  function setPanel(open) {
    $("left-drawer").hidden = !open;
    $("reopen-left").hidden = open;
    document.body.classList.toggle("panel-closed", !open);
  }

  function snapshotState() {
    return {
      preset: AppState.preset,
      chain: AppState.chain,
      uf: AppState.uf,
      bioma: AppState.bioma,
      year: AppState.year,
      yearPinned: AppState.yearPinned,
      facilityChain: AppState.facilityChain,
      metric: AppState.metric,
      basemap: AppState.basemap,
      extrudeMun: AppState.extrudeMun,
      hexMode: AppState.hexMode,
      deterHeat: AppState.deterHeat,
      layers: {...AppState.layers},
      flowCountry: AppState.flowCountry,
      highlightCodes: [...AppState.highlightCodes],
    };
  }

  function deterTriples(uf = "", bioma = "") {
    const targetBiome = bioma ? biomeKey(bioma) : "";
    return (meta?.alert_triples || []).filter(([ano, rowUf, rowBiome]) =>
      ano != null &&
      (!uf || rowUf === uf) &&
      (!targetBiome || biomeKey(rowBiome || "") === targetBiome)
    );
  }

  function syncFlowCountries() {
    const countries = meta?.flow_countries_by_product?.[AppState.chain] || meta?.flow_countries || {};
    const entries = Object.entries(countries).sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
    const select = $("flow-country");
    select.replaceChildren(new Option("Todos os destinos", ""), ...entries.map(([id, name]) => new Option(name, id)));
    if (AppState.flowCountry && !Object.hasOwn(countries, AppState.flowCountry)) AppState.flowCountry = "";
    select.value = AppState.flowCountry;
  }

  function syncBiomes(adjustNotes = []) {
    const {layers, uf, metric} = AppState;
    const anyLayer = layers.choro || layers.flows || layers.deter || layers.facilities;
    const select = $("bioma-select");
    if (!anyLayer) {
      AppState.bioma = "";
      select.replaceChildren(new Option("Todos", ""));
      select.value = "";
      select.disabled = true;
      return;
    }
    const allBiomes = meta?.biomes || [];
    const ufBiomes = new Set(uf ? (meta?.biomes_by_uf?.[uf] || []) : allBiomes);
    const validKeys = new Set();
    if (layers.choro && metric) {
      const mBiomes = meta?.metric_biomes?.[metric] || allBiomes;
      for (const b of mBiomes) {
        if (ufBiomes.has(b)) validKeys.add(biomeKey(b));
      }
    }
    if (layers.flows || layers.facilities) {
      for (const b of ufBiomes) validKeys.add(biomeKey(b));
    }
    if (layers.deter) {
      for (const [, , b] of deterTriples(uf, "")) {
        if (b) validKeys.add(biomeKey(b));
      }
    }
    const options = allBiomes.filter(name => validKeys.has(biomeKey(name)));
    select.replaceChildren(new Option("Todos", ""), ...options.map(name => new Option(name, name)));
    if (AppState.bioma && !options.includes(AppState.bioma)) {
      adjustNotes.push(`Bioma ${AppState.bioma} redefinido por ausência de dados neste recorte.`);
      AppState.bioma = "";
    }
    select.value = AppState.bioma;
    select.disabled = !options.length;
  }

  function syncUFs(adjustNotes = []) {
    const {layers, metric, bioma, chain, facilityChain} = AppState;
    const allUfs = meta?.ufs || [];
    const anyLayer = layers.choro || layers.flows || layers.deter || layers.facilities;
    let validSet;
    if (!anyLayer) {
      validSet = new Set(allUfs);
    } else {
      validSet = new Set();
      const biomeUfs = bioma
        ? new Set(allUfs.filter(u => (meta?.biomes_by_uf?.[u] || []).includes(bioma)))
        : new Set(allUfs);
      if (layers.choro && metric) {
        for (const u of (meta?.metric_ufs?.[metric] || allUfs)) {
          if (biomeUfs.has(u)) validSet.add(u);
        }
      }
      if (layers.flows) {
        for (const u of (meta?.flow_ufs?.[chain] || allUfs)) {
          if (biomeUfs.has(u)) validSet.add(u);
        }
      }
      if (layers.deter) {
        for (const [, u] of deterTriples("", bioma)) {
          if (u) validSet.add(u);
        }
      }
      if (layers.facilities) {
        for (const u of (meta?.facility_ufs?.[facilityChain] || allUfs)) {
          if (biomeUfs.has(u)) validSet.add(u);
        }
      }
    }
    const validUfs = allUfs.filter(u => validSet.has(u));
    const stateNames = new Map((states?.features || []).map(f => [f.properties.uf, f.properties.name]));
    const select = $("uf-select");
    select.replaceChildren(new Option("Brasil", ""), ...validUfs.map(u => new Option(stateNames.get(u) || u, u)));
    let changed = false;
    if (AppState.uf && !validSet.has(AppState.uf)) {
      adjustNotes.push(`Território voltou para Brasil porque ${AppState.uf} não tem dados neste recorte.`);
      AppState.uf = "";
      clearMunicipality();
      changed = true;
    }
    select.value = AppState.uf;
    return changed;
  }

  function syncYear(adjustNotes = []) {
    const {metric, layers, chain, yearPinned, uf, bioma} = AppState;
    const activeAnnual = [];
    if (metric && layers.choro) {
      activeAnnual.push({key: "choro", label: "Indicador", years: meta?.metric_years?.[metric] || []});
    }
    if (layers.flows) {
      activeAnnual.push({key: "flows", label: "Fluxos", years: meta?.flow_years?.[chain] || []});
    }
    if (layers.deter) {
      const dYears = [...new Set(deterTriples(uf, bioma).map(t => t[0]))].sort((a, b) => a - b);
      activeAnnual.push({key: "deter", label: "Alertas", years: dYears});
    }
    const available = new Set(activeAnnual.flatMap(item => item.years));
    let year = AppState.year;
    if (!activeAnnual.length) {
      year = null;
    } else {
      const commonYears = activeAnnual[0].years.filter(y => activeAnnual.every(item => item.years.includes(y)));
      if (year == null || !yearPinned || !available.has(year)) {
        const choroYears = activeAnnual.find(item => item.key === "choro")?.years || [];
        const picked = commonYears.length
          ? commonYears[commonYears.length - 1]
          : (choroYears.length ? choroYears[choroYears.length - 1] : Math.max(...available));
        if (Number.isFinite(picked)) {
          if (year != null && year !== picked) {
            adjustNotes.push(`Ano ajustado de ${year} para ${picked} conforme disponibilidade do recorte.`);
          }
          year = picked;
        } else {
          year = null;
        }
      }
      if (activeAnnual.length > 1 && year != null) {
        const missing = activeAnnual.filter(item => item.years.length && !item.years.includes(year)).map(item => item.label);
        if (missing.length) {
          const spanText = commonYears.length ? ` Em comum: ${commonYears[0]}–${commonYears[commonYears.length - 1]}.` : "";
          adjustNotes.push(`${missing.join(" e ")} sem dados em ${year}.${spanText}`);
        }
      }
    }
    if (!Number.isFinite(year)) year = null;
    AppState.year = year;
    if (year == null) AppState.yearPinned = false;
    yearOptions = [...available].sort((a, b) => a - b);
    if (year != null && !available.has(year)) yearOptions.push(year);
    yearOptions.sort((a, b) => a - b);
    const select = $("year-select");
    select.replaceChildren(...(yearOptions.length
      ? [...yearOptions].reverse().map(value => {
        const missing = activeAnnual.filter(item => item.years.length && !item.years.includes(value)).map(item => item.label);
        const label = !available.has(value) ? `${value} (sem cobertura)`
          : (missing.length && activeAnnual.length > 1 ? `${value} (sem ${missing.join(", ")})` : String(value));
        return new Option(label, value);
      })
      : [new Option(activeAnnual.length ? "Sem anos carregados" : "Sem recorte", "")]));
    select.disabled = !yearOptions.length;
    select.value = year ?? "";
    const slider = $("year-slider");
    slider.min = 0;
    slider.max = Math.max(0, yearOptions.length - 1);
    slider.value = Math.max(0, yearOptions.indexOf(year));
    slider.disabled = yearOptions.length < 2;
    slider.closest(".timeline-group").hidden = year == null;
    slider.setAttribute("aria-valuetext", year ?? "");
    $("year-label").textContent = year ?? "";
  }

  function syncUI() {
    const {layers} = AppState;
    const adjustNotes = [];
    syncFlowCountries();
    syncBiomes(adjustNotes);
    if (syncUFs(adjustNotes)) syncBiomes(adjustNotes);
    syncYear(adjustNotes);
    document.querySelectorAll(".preset-btn").forEach(button => {
      const active = button.dataset.preset === AppState.preset;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    $("chain-select").value = AppState.chain;
    $("chain-select").disabled = !layers.flows;
    $("flow-country").value = AppState.flowCountry;
    $("flow-country").disabled = !layers.flows;
    $("facility-chain").value = AppState.facilityChain;
    $("facility-chain").disabled = !layers.facilities;
    $("uf-select").value = AppState.uf;
    $("metric-select").value = AppState.metric;
    $("toggle-choro").checked = layers.choro;
    $("toggle-choro").disabled = !AppState.metric;
    $("toggle-deter").checked = layers.deter;
    $("deter-heatmap").value = AppState.deterHeat;
    $("deter-heatmap").disabled = !layers.deter;
    $("toggle-flows").checked = layers.flows;
    $("toggle-facilities").checked = layers.facilities;

    $("basemap-mode").value = AppState.basemap;
    $("toggle-extrude-mun").checked = AppState.extrudeMun;
    $("toggle-extrude-mun").disabled = !layers.choro || !AppState.uf || AppState.basemap === "terrain";
    $("toggle-hex-mode").checked = AppState.hexMode;
    $("toggle-hex-mode").disabled = !layers.deter || Boolean(AppState.deterHeat);
    $("hex-controls").hidden = !layers.deter || !AppState.hexMode || Boolean(AppState.deterHeat);
    $("hex-radius").value = String(AppState.hexRadiusKm);
    $("hex-radius-val").textContent = `${AppState.hexRadiusKm} km`;
    $("hex-elevation").value = String(AppState.hexElevation);
    $("hex-elev-val").textContent = `${AppState.hexElevation}×`;
    $("ai-spec-banner").hidden = !AppState.undoSnapshot;
    $("clear-filters").hidden = !(AppState.uf || AppState.bioma || AppState.metric || Object.values(layers).some(Boolean));

    const area = lastMunicipality?.municipio || (AppState.uf
      ? states?.features.find(feature => feature.properties.uf === AppState.uf)?.properties.name || AppState.uf : "Brasil");
    const {year, bioma, chain} = AppState;
    const indicator = layers.choro ? meta?.metrics[AppState.metric]?.label : null;
    const layerLabel = indicator || (layers.flows ? `Fluxos de ${chain} (Trase)` : layers.deter
      ? "Alertas por satélite" : layers.facilities ? "Cadastro de instalações" : null);
    const scope = [area, bioma, layerLabel, year].filter(Boolean).join(" · ");
    $("context-pill").textContent = `Contexto: ${scope}`;
    $("explore-scope").textContent = scope;
    const notes = [...adjustNotes];
    if (layers.facilities) notes.push("O cadastro de instalações é independente do ano.");
    if (indicator && AppState.metric.startsWith("comex_")) notes.push("Comex Stat localiza o domicílio fiscal do exportador.");
    if (bioma && (layers.choro || layers.flows || layers.facilities)) notes.push("Bioma predominante do município.");
    if (bioma && layers.deter) notes.push("Nos alertas, vale o bioma registrado pelo INPE.");
    $("filter-note").textContent = notes.join(" ");
    $("filter-note").hidden = !notes.length;
    const metric = indicator ? AppState.metric : layers.flows ? `flows_${chain}`
      : layers.deter ? `deter_${AppState.deterHeat || "count"}` : null;
    $("explore-timeline").hidden = !metric || year == null;
    const municipalityOutside = lastMunicipality && bioma && biomeKey(lastMunicipality.bioma || "") !== biomeKey(bioma);
    $("mun-dashboard").hidden = !indicator || year == null || Boolean(municipalityOutside);
    if (metric && year != null) {
      const route = new URLSearchParams({view: "timeline", metric, start_year: Math.max(1985, year - 10), end_year: year});
      if (AppState.uf) route.set("uf", AppState.uf);
      if (bioma) route.set("bioma", bioma);
      if (lastMunicipality?.code && !municipalityOutside) route.set("code", lastMunicipality.code);
      $("explore-timeline").href = `/?${route}`;
      route.set("view", "dashboard");
      $("mun-dashboard").href = `/?${route}`;
    }
  }

  function selectMetric(metric) {
    AppState.metric = metric;
    AppState.layers.choro = Boolean(metric);
    AppState.preset = Object.keys(THEMES).find(key => THEMES[key].includes(metric)) || "";
    if (metric) {
      AppState.deterHeat = "";
      const chain = METRIC_CHAIN[metric];
      if (chain) {
        AppState.chain = chain;
        if (!AppState.layers.facilities) AppState.facilityChain = chain;
      }
      const validYears = meta?.metric_years?.[metric];
      if (AppState.yearPinned && validYears?.length && !validYears.includes(AppState.year)) {
        AppState.yearPinned = false;
      }
    }
    if (!metric) AppState.extrudeMun = false;
  }

  function clearMunicipality() {
    municipalityRequest?.abort();
    AppState.selectedCode = null;
    lastMunicipality = null;
    $("mun-drawer").hidden = true;
    document.body.classList.remove("municipality-open");
  }

  function drillState(uf, fit = true) {
    if (uf !== AppState.uf && AppState.layers.deter) AppState.hexMode = !uf;
    AppState.uf = uf;
    clearMunicipality();
    syncUI();
    return refreshActiveLayers(fit);
  }

  function showTooltip(info) {
    const tip = $("map-tooltip");
    if (!info || !info.object) {
      tip.hidden = true;
      return;
    }
    const o = info.object;
    let html = "";
    if (info.layer.id === "states") {
      const {uf, name} = o.properties;
      const value = choroData?.values?.[uf];
      html = `<strong>${escapeHtml(name)}</strong><br>` +
        `${choroData ? (value == null ? "Sem registros no recorte" : n(value) + " " + escapeHtml(choroData.meta.unit)) + "<br>" : ""}` +
        "<small>Clique para ver os municípios</small>";
    } else if (info.layer.id === "municipalities") {
      const code = String(o.properties?.codarea || "");
      const val = choroData?.values?.[code];
      const unit = choroData?.meta?.unit || "";
      html = `<strong>Município IBGE ${escapeHtml(code)}</strong><br>` +
        `${choroData ? `<strong>${val != null ? n(val) + " " + escapeHtml(unit) : "Sem registros no recorte"}</strong><br>` : ""}` +
        `<small>Clique para abrir o Raio-X</small>`;
    } else if (info.layer.id === "deter-hex") {
      const pts = o.points || [];
      const count = o.count ?? pts.length;
      const area = o.elevationValue ?? pts.reduce((acc, p) => acc + (p.source?.area_km2 || p.area_km2 || 0), 0);
      html = `<strong>Alertas por satélite (${escapeHtml(deterData?.year || AppState.year)})</strong><br>` +
        `Alertas no hexágono: <strong>${n(count, 0)}</strong><br>` +
        `Área somada: <strong>${n(area, 2)} km²</strong>`;
    } else if (info.layer.id === "trade-flows") {
      html = `<strong>${escapeHtml(o.origin_name)} → ${escapeHtml(o.target_name)}</strong><br>` +
        `Volume: ${n(o.volume_t)} t<br>Exposição 5a: ${n(o.exposicao_ha)} ha`;
    } else if (info.layer.id === "deter-alerts") {
      html = `<strong>Alerta por satélite · ${escapeHtml(o.bioma)}</strong><br>` +
        `${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})<br>` +
        `Classe: ${escapeHtml(o.classname || "—")} · ${n(o.area_km2, 2)} km²<br>` +
        "<small>Clique para comparar imagens</small>";
    } else if (info.layer.id === "facilities") {
      if (facilitiesData?.grain === "state") {
        html = `<strong>${escapeHtml(o.uf_name)}</strong><br>${n(o.total, 0)} instalações de ${o.cadeia === "soja" ? "soja" : "bovinos"}<br><small>Clique para ver as instalações</small>`;
      } else {
        const cap = o.capacidade_valor ? `${n(o.capacidade_valor, 0)} ${escapeHtml(o.capacidade_unidade || "")}` : "Sem capacidade";
        html = `<strong>${escapeHtml(o.empresa || "Instalação")}</strong><br>` +
          `${escapeHtml(o.tipo || o.cadeia)} · ${escapeHtml(o.nivel_inspecao || "")} ${escapeHtml(o.numero_inspecao || "")}<br>` +
          `${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})<br><small>${cap}</small>`;
      }
    }
    if (!html) {
      tip.hidden = true;
      return;
    }
    tip.innerHTML = html;
    tip.style.left = `${info.x + 12}px`;
    tip.style.top = `${info.y + 12}px`;
    tip.hidden = false;
  }

  function updateLegendAndUncertainty() {
    $("legend-card").hidden = !choroData && !deterHeatData;
    if (deterHeatData) {
      const frame = deterHeatData.frames[0];
      $("legend-title").textContent = deterHeatData.label;
      $("legend-bar").style.background = "linear-gradient(90deg, #ffffb2, #fd8d3c, #f03b20, #bd0026)";
      $("legend-mid").textContent = n(deterHeatData.max / 2);
      $("legend-max").textContent = `${n(deterHeatData.max)} ${deterHeatData.unit}`;
      $("ub-source").textContent = `INPE (DETER) · ${frame.period}`;
      $("ub-coverage").textContent = frame.value == null ? "Sem registros no recorte" : `${n(frame.records, 0)} registros na agregação`;
      $("ub-caveat").textContent = "Os registros com localização foram agrupados em células de 0,25°. A taxa anual oficial vem do PRODES.";
      $("ub-method").href = "/metodologia#" + deterHeatData.metric;
      return;
    }
    if (!choroData) return;
    const territory = choroData.grain === "state" ? "estados" : "municípios";
    const pal = PALETTES[choroData.meta.palette] || PALETTES.reds;
    const stops = pal.map(c => `rgb(${c[0]},${c[1]},${c[2]})`).join(", ");
    $("legend-bar").style.background = `linear-gradient(90deg, ${stops})`;
    $("legend-title").textContent = `${choroData.meta.label} (${choroData.meta.unit})`;
    $("legend-mid").textContent = n((choroData.p95 || choroData.max || 0) * 0.5, 0);
    $("legend-max").textContent = `${n(choroData.p95 || choroData.max || 0, 0)}+`;

    $("ub-source").textContent = `Fonte: ${choroData.meta.source} · Ano ${choroData.year}`;
    if (choroData.coverage) {
      const pct = choroData.coverage.pct_rastreado;
      const unk = (100 - Number(pct)).toFixed(1).replace(".", ",");
      $("ub-coverage").textContent = `Rastreabilidade no Brasil: ${n(pct)}% (${unk}% sem município de origem).`;
    } else {
      $("ub-coverage").textContent = `${n(choroData.count, 0)} ${territory} com registro neste recorte.`;
    }
    $("ub-caveat").textContent = choroData.meta.caveat;
    $("ub-method").href = "/metodologia#" + (deterHeatData?.metric || choroData.metric);
  }

  function renderRanking() {
    const list = $("top-list");
    const byState = choroData ? choroData.grain === "state" : !AppState.uf;
    const territory = byState ? "estados" : "municípios";
    $("top-title").textContent = choroData ? (byState ? "Estados por valor" : "Municípios por valor") : "Ranking territorial";
    if (!choroData) {
      $("top-count").textContent = "";
      list.innerHTML = "<li class='meta'>Selecione um indicador para comparar os territórios.</li>";
      return;
    }
    if (!choroData?.top?.length) {
      $("top-count").textContent = `0 ${territory}`;
      list.innerHTML = "<li class='meta'>Sem dados neste recorte.</li>";
      return;
    }
    const unit = choroData.meta.unit;
    const topMax = choroData.top[0]?.value || 1;
    $("top-count").textContent = `${choroData.year} · ${n(choroData.count, 0)} ${territory} com dados`;
    list.replaceChildren(...choroData.top.slice(0, 15).map((row, idx) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rank-item";
      const pct = Math.max(4, Math.min(100, (row.value / topMax) * 100));
      btn.innerHTML = `
        <div class="rank-row">
          <span>${idx + 1}. ${escapeHtml(row.name)}${byState ? "" : ` · ${escapeHtml(row.uf)}`}</span>
          <strong>${n(row.value)} ${escapeHtml(unit)}</strong>
        </div>
        <div class="rank-bar-bg"><div class="rank-bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
      `;
      btn.addEventListener("click", () => {
        if (byState) { drillState(row.code); return; }
        openMunicipality(row.code);
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
    const extrudeMun = AppState.extrudeMun && AppState.layers.choro && Boolean(AppState.uf) && !terrainMode;
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

    const byState = !AppState.uf && !AppState.highlightCodes.length;
    if (byState && states) {
      layers.push(new deck.GeoJsonLayer({
        id: "states",
        data: states,
        pickable: true,
        filled: true,
        stroked: true,
        lineWidthMinPixels: 1,
        getFillColor: f => AppState.layers.choro && !deterHeatData
          ? rampColor(values[f.properties.uf], maxRef, palette, 180) : [100, 130, 124, 28],
        getLineColor: [160, 184, 174, 170],
        updateTriggers: {getFillColor: [choroData, AppState.layers.choro, deterHeatData]},
        onHover: showTooltip,
        onClick: info => { if (info.object) drillState(info.object.properties.uf); },
      }));
    }
    if (!byState) {
      const munAlpha = terrainMode ? 150 : (extrudeMun ? 220 : 185);
      layers.push(new deck.GeoJsonLayer({
        id: "municipalities",
        data: AmbianceMap.municipalitiesIn(geojson, states, AppState.uf),
        pickable: true,
        stroked: !extrudeMun,
        filled: true,
        extruded: extrudeMun,
        elevationScale: 1,
        material: MATERIAL_3D,
        lineWidthMinPixels: 0.4,
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
          if (code === AppState.selectedCode) return [35, 91, 66, 235];
          if (hlSet.has(code)) return [249, 115, 22, 235];
          return choroData ? rampColor(values[code], maxRef, palette, munAlpha) : [216, 225, 218, 32];
        },
        getLineColor: f => {
          const code = String(f.properties?.codarea || "");
          if (code === AppState.selectedCode || hlSet.has(code)) return [255, 255, 255, 255];
          return terrainMode ? [255, 255, 255, 70] : [110, 130, 124, 70];
        },
        getLineWidth: f => {
          const code = String(f.properties?.codarea || "");
          return (code === AppState.selectedCode || hlSet.has(code)) ? 2.5 : 0.4;
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

    if (!byState && states && !terrainMode) {
      layers.push(new deck.GeoJsonLayer({
        id: "state-outlines",
        data: states,
        filled: false,
        stroked: true,
        getLineColor: feature => feature.properties.uf === AppState.uf ? [59, 100, 76, 220] : [116, 151, 122, 95],
        lineWidthMinPixels: 1,
        updateTriggers: {getLineColor: [AppState.uf]},
      }));
    }

    if (AppState.layers.flows && flowsData?.arcs?.length) {
      layers.push(new deck.ArcLayer({
        id: "trade-flows",
        data: flowsData.arcs,
        pickable: true,
        greatCircle: true,
        getHeight: 0.35,
        getSourcePosition: d => d.source,
        getTargetPosition: d => d.target,
        getSourceColor: d => d.exposicao_ha > 500 ? [244, 63, 94, 225] : [16, 185, 129, 200],
        getTargetColor: [56, 189, 248, 210],
        getWidth: d => Math.min(5, 1.2 + Math.log1p(d.volume_t / 5000) * 0.65),
        widthUnits: "pixels",
        onHover: showTooltip,
        onClick: info => {
          const flow = info.object;
          if (!flow) return;
          if (flowsData.grain === "state") drillState(flow.origin_uf);
          else openMunicipality(flow.origin_code);
        },
      }));
    }

    const heat = deterHeatData?.frames[0];
    if (AppState.layers.deter && heat?.cells.length && deck.HeatmapLayer) {
      layers.push(new deck.HeatmapLayer({
        id: "deter-heat", data: heat.cells, radiusPixels: 42, aggregation: "SUM",
        colorDomain: [0, deterHeatData.max || 1], getPosition: d => d.position,
        getWeight: d => d.value ?? 0,
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
          elevationScale: AppState.hexElevation * 6,
          elevationRange: [0, 3000],
          colorRange: HEX_DETER_RANGE,
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
            if (c.includes("QUEIM")) return [249, 115, 22, 215];
            if (c.includes("DESMAT")) return [239, 68, 68, 230];
            return [168, 85, 247, 210];
          },
          onHover: showTooltip,
          onClick: info => AmbianceMap.compareAlert(info.object),
        }));
      }
    }

    if (AppState.layers.facilities && facilitiesData?.points?.length) {
      layers.push(AmbianceMap.facilityLayer(facilitiesData, terrainExtensions, showTooltip, drillState));
    }

    if (lastMunicipality?.code === AppState.selectedCode && lastMunicipality?.lon != null && lastMunicipality.lat != null && !terrainMode && !extrudeMun) {
      const data = [lastMunicipality];
      layers.push(new deck.ScatterplotLayer({
        id: "selected-municipality-marker", data,
        getPosition: d => [d.lon, d.lat], radiusUnits: "pixels", getRadius: 4,
        getFillColor: [20, 62, 42], stroked: true, getLineColor: [255, 254, 249],
        lineWidthUnits: "pixels", getLineWidth: 1.5,
      }), new deck.TextLayer({
        id: "selected-municipality-label", data,
        getPosition: d => [d.lon, d.lat], getText: d => d.municipio,
        getTextAnchor: "start", getPixelOffset: [9, 0], getSize: 13,
        getColor: [20, 62, 42], background: true,
        getBackgroundColor: [255, 254, 249, 235], backgroundPadding: [4, 2], fontWeight: 650,
      }));
    }

    deckgl.setProps({layers});
  }

  function territoryBounds(uf) {
    const state = states?.features.find(feature => feature.properties.uf === uf);
    if (!state) return BRAZIL_BOUNDS;
    const coords = state.geometry.coordinates.flat(Infinity);
    const bounds = [Infinity, Infinity, -Infinity, -Infinity];
    for (let i = 0; i < coords.length; i += 2) {
      bounds[0] = Math.min(bounds[0], coords[i]);
      bounds[1] = Math.min(bounds[1], coords[i + 1]);
      bounds[2] = Math.max(bounds[2], coords[i]);
      bounds[3] = Math.max(bounds[3], coords[i + 1]);
    }
    return bounds;
  }

  async function refreshActiveLayers(autoFit = false) {
    layersRequest?.abort();
    const request = new AbortController();
    layersRequest = request;
    const {uf, bioma, year, chain, facilityChain, metric, layers, flowCountry, deterHeat} = AppState;
    const byState = !uf && !AppState.highlightCodes.length;
    const scope = {uf, bioma};
    const grain = byState ? "state" : "municipality";
    const annualScope = {...scope, year, strict_year: "1"};
    const tasks = {};
    if (year != null && layers.choro && metric) tasks.indicator = ["choropleth", {...annualScope, metric, grain}];
    if (year != null && layers.flows) tasks.flows = ["flows", {
      ...annualScope, product: chain, country: flowCountry, origin: AppState.selectedCode || "",
      grain: uf ? "municipality" : "state", limit: uf ? 180 : 90,
    }];
    if (year != null && layers.deter) tasks.alerts = deterHeat
      ? ["deter-grid", {...annualScope, weight: deterHeat}]
      : ["deter", {...annualScope, limit: 10000}];
    if (layers.facilities) tasks.facilities = ["facilities", {...scope, chain: facilityChain, grain, limit: 10000}];

    const entries = Object.entries(tasks);
    if (entries.length) $("map-status").textContent = "Atualizando camadas…";
    const responses = await Promise.allSettled(entries.map(async ([, [name, params]]) => {
      const qs = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== ""));
      const res = await fetch(`/api/agro/${name}?${qs}`, {signal: request.signal});
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    }));
    if (request.signal.aborted) return;

    const results = Object.fromEntries(responses.map((response, index) => [entries[index][0], response.value]));
    choroData = results.indicator || null;
    flowsData = results.flows || null;
    deterData = deterHeat ? null : results.alerts || null;
    deterHeatData = deterHeat ? results.alerts || null : null;
    facilitiesData = results.facilities || null;

    const labels = {indicator: "Indicador", flows: "Fluxos", alerts: "Alertas", facilities: "Instalações"};
    const notes = entries.filter((_, index) => responses[index].status === "rejected")
      .map(([key]) => `${labels[key]} indisponíveis`);
    if (choroData && !choroData.count) notes.push(`Indicador sem registros em ${year}`);
    if (flowsData) {
      const scale = flowsData.grain === "state" ? "estados → países" : "municípios → países";
      $("flow-scope").textContent = flowsData.count ? `${year} · ${n(flowsData.count, 0)} ligações (${scale}).` : `Sem fluxos em ${year} neste recorte.`;
      if (!flowsData.count) notes.push(`Sem fluxos em ${year}`);
    }
    $("flow-scope").hidden = !flowsData;
    const alertFrame = deterHeatData?.frames[0];
    if (deterData) $("deter-scope").textContent = `${year} · ${n(deterData.returned, 0)} de ${n(deterData.total_alerts, 0)} registros com localização exibidos.`;
    if (alertFrame) $("deter-scope").textContent = alertFrame.value == null ? `Sem registros em ${year} neste recorte.`
      : `${year} · ${n(alertFrame.value)} ${deterHeatData.unit} · ${n(alertFrame.records, 0)} registros na agregação`;
    $("deter-scope").hidden = !deterData && !alertFrame;
    if (deterData?.total_alerts === 0 || (alertFrame && alertFrame.value == null)) notes.push(`Sem alertas registrados em ${year}`);
    $("facility-scope").hidden = !facilitiesData;
    if (facilitiesData) {
      $("facility-scope").textContent = `${n(facilitiesData.total, 0)} instalações cadastradas neste recorte.`;
      if (!facilitiesData.total) notes.push("Sem instalações cadastradas");
    }

    updateLegendAndUncertainty();
    renderRanking();
    drawLayers();
    $("map-status").textContent = notes.join(" · ") || (choroData
      ? `${n(choroData.count, 0)} ${byState ? "estados" : "municípios"} com registros`
      : uf ? "Clique no mapa para selecionar um município" : "Clique no mapa para selecionar um estado");
    if (autoFit) fitBbox((bioma && choroData?.bbox) || territoryBounds(uf));
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
            <stop offset="0%" stop-color="#10b981" stop-opacity="0.45"/>
            <stop offset="100%" stop-color="#10b981" stop-opacity="0.02"/>
          </linearGradient>
        </defs>
        <path d="${areaD}" fill="url(#sparkFill)"/>
        <path d="${pathD}" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round"/>
        <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3.5" fill="#fcd34d"/>
      </svg>
    `;
  }

  async function openMunicipality(code, reloadFlows = true) {
    AppState.selectedCode = code;
    drawLayers();
    if (reloadFlows && AppState.layers.flows) refreshActiveLayers(false);
    municipalityRequest?.abort();
    const request = new AbortController();
    municipalityRequest = request;
    let data;
    try {
      const args = new URLSearchParams({code, strict_year: "1"});
      if (AppState.year != null && AppState.layers.choro) args.set("year", AppState.year);
      else args.set("profile", "territory");
      const response = await fetch(`/api/agro/municipality?${args}`, {signal: request.signal});
      if (!response.ok) throw new Error("Detalhes municipais indisponíveis.");
      data = await response.json();
    } catch (error) {
      if (!request.signal.aborted) $("map-status").textContent = error.message;
      return;
    }
    if (request.signal.aborted || AppState.selectedCode !== code) return;
    lastMunicipality = data.municipality;
    const m = data.municipality;
    const s = data.snapshot || {};
    $("mun-title").textContent = m.municipio;
    $("mun-sub").textContent = [m.uf, data.effective_year, `IBGE ${m.code}`].filter(Boolean).join(" · ");
    const metric = data.effective_year != null ? meta.metrics[AppState.metric] : null;
    const inScope = !AppState.bioma || biomeKey(m.bioma || "") === biomeKey(AppState.bioma);
    const value = inScope ? s[AppState.metric] : null;
    $("mun-feature-label").textContent = metric?.label || "Bioma predominante";
    $("mun-feature-value").textContent = metric
      ? (!inScope ? "Fora do bioma selecionado" : value == null ? "Sem dados para o ano" : `${n(value)} ${metric.unit}`)
      : m.bioma || "Sem informação";
    $("mun-feature-source").textContent = metric?.source || `${n(m.area_km2)} km² · IBGE`;
    $("mun-method").href = "/metodologia" + (metric ? "#" + AppState.metric : "#indicadores");
    document.querySelector(".spark-card").hidden = !metric || !inScope;
    document.querySelector(".mun-details").hidden = !metric || !inScope;

    const kpis = [
      ["Rebanho (IBGE PPM)", s.ibge_bovinos_rebanho_cab != null ? `${n(s.ibge_bovinos_rebanho_cab, 0)} cab.` : "—"],
      ["Soja (IBGE PAM)", s.ibge_soja_producao_t != null ? `${n(s.ibge_soja_producao_t, 0)} t` : "—"],
      ["Desmat. (MapBiomas)", s.mapbiomas_desmatamento_ha != null ? `${n(s.mapbiomas_desmatamento_ha)} ha` : "—"],
      ["SEEG Agro / MUT (tCO2e)", `${s.seeg_emissao_agro_tco2e != null ? n(s.seeg_emissao_agro_tco2e, 0) : "—"} / ${s.seeg_emissao_mut_tco2e != null ? n(s.seeg_emissao_mut_tco2e, 0) : "—"}`],
      ["Exp. Bovinos / Soja 5a", `${s.trase_bovinos_exposicao_5a_ha != null ? n(s.trase_bovinos_exposicao_5a_ha) : "—"} / ${s.trase_soja_exposicao_5a_ha != null ? n(s.trase_soja_exposicao_5a_ha) : "—"} ha`],
      ["Frigoríficos / Silos", `${n(s.inst_bovinos_total || 0, 0)} / ${n(s.inst_soja_total || 0, 0)}`],
    ];
    $("mun-grid").innerHTML = kpis.map(([k, v]) => `<div class="kpi"><strong>${v}</strong><span>${k}</span></div>`).join("");

    if (metric && inScope) renderSparkline(data.series, AppState.metric);

    if (data.deter_recent?.length) {
      $("mun-deter").textContent = "Alertas por satélite desde 2023 (INPE): " + data.deter_recent
        .map(d => `${d.ano}: ${n(d.alertas, 0)} alertas (${n(d.area_km2)} km²)`)
        .join(" · ");
    } else {
      $("mun-deter").textContent = "Sem alertas por satélite registrados na base local desde 2023.";
    }
    $("mun-drawer").hidden = false;
    document.body.classList.add("municipality-open");
    syncUI();
    drawLayers();
  }

  async function applyMapSpec(spec) {
    if (!spec) return;
    AppState.undoSnapshot = snapshotState();
    if (spec.metric && meta?.metrics?.[spec.metric]) selectMetric(spec.metric);
    if (spec.year || spec.deter_year) {
      AppState.year = spec.year || spec.deter_year;
      AppState.yearPinned = true;
    }
    if ("uf" in spec && (spec.uf || "") !== AppState.uf) {
      AppState.uf = spec.uf || "";
      clearMunicipality();
    }
    if ("bioma" in spec) AppState.bioma = spec.bioma || "";
    if (typeof spec.show_flows === "boolean") {
      AppState.layers.flows = spec.show_flows;
      if (spec.flow_product) AppState.chain = spec.flow_product;
    }
    if (typeof spec.show_deter === "boolean") {
      AppState.layers.deter = spec.show_deter;
    }
    if (typeof spec.show_facilities === "boolean") AppState.layers.facilities = spec.show_facilities;
    if (["all", "soja", "bovinos"].includes(spec.facilities_chain)) AppState.facilityChain = spec.facilities_chain;
    AppState.highlightCodes = Array.isArray(spec.highlight_codes) ? spec.highlight_codes : [];
    syncUI();
    await refreshActiveLayers(Boolean(spec.uf || spec.bioma));
  }

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
        renderAIResponse(item.data);
        if (item.data.map_spec) await applyMapSpec(item.data.map_spec);
      });
      li.append(btn);
      return li;
    }));
  }

  async function askAI(question) {
    $("mun-drawer").hidden = true;
    document.body.classList.remove("municipality-open");
    setPanel(true);
    switchTab("ai");
    $("ask-btn").disabled = true;
    const mode = $("ask-mode").value;
    $("ask-status").textContent = mode === "laws" ? "Buscando nas 29 leis…" : "Consultando PostgreSQL + Leis…";

    const viewContext = {
      preset: AppState.preset,
      chain: AppState.chain,
      uf: AppState.uf || null,
      bioma: AppState.bioma || null,
      year: AppState.year,
      metric: AppState.metric,
      selected_municipality: lastMunicipality && AppState.selectedCode
        ? {code: AppState.selectedCode, municipio: lastMunicipality.municipio, uf: lastMunicipality.uf}
        : null,
    };

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question, mode, domain: mode === "laws" ? "law" : "auto", k: 6, view_context: viewContext}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Erro ao consultar IA.");

      renderAIResponse(data);
      sessionHistory.unshift({question, data});
      if (sessionHistory.length > 12) sessionHistory.pop();
      renderHistory();

      if (data.map_spec) await applyMapSpec(data.map_spec);
      $("ask-status").textContent = "";
    } catch (err) {
      $("ask-status").textContent = err.message;
    } finally {
      $("ask-btn").disabled = false;
    }
  }

  function setupListeners() {
    document.querySelectorAll(".preset-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        selectMetric(THEMES[btn.dataset.preset][0]);
        refreshSelection();
      });
    });

    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    $("toggle-left").addEventListener("click", () => setPanel(false));
    $("reopen-left").addEventListener("click", () => setPanel(true));
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
      refreshSelection();
    });
    $("facility-chain").addEventListener("change", () => {
      AppState.facilityChain = $("facility-chain").value;
      refreshSelection();
    });
    $("bioma-select").addEventListener("change", () => {
      AppState.bioma = $("bioma-select").value;
      refreshSelection(true);
    });
    $("uf-select").addEventListener("change", () => {
      drillState($("uf-select").value);
    });

    $("year-slider").addEventListener("input", () => {
      const year = yearOptions[Number($("year-slider").value)];
      $("year-label").textContent = year;
      $("year-select").value = year;
      $("year-slider").setAttribute("aria-valuetext", year);
    });
    function refreshSelection(fit = false) {
      syncUI();
      refreshActiveLayers(fit);
      if (AppState.selectedCode && !$("mun-drawer").hidden) openMunicipality(AppState.selectedCode, false);
    }
    function changeYear(event) {
      const selector = event.currentTarget;
      AppState.year = selector.id === "year-slider" ? yearOptions[Number(selector.value)] : Number(selector.value);
      AppState.yearPinned = true;
      refreshSelection();
    }
    $("year-slider").addEventListener("change", changeYear);
    $("year-select").addEventListener("change", changeYear);

    $("metric-select").addEventListener("change", () => {
      selectMetric($("metric-select").value);
      refreshSelection();
    });
    $("toggle-choro").addEventListener("change", () => {
      AppState.layers.choro = $("toggle-choro").checked;
      if (AppState.layers.choro) AppState.deterHeat = "";
      refreshSelection();
    });
    $("deter-heatmap").addEventListener("change", () => {
      AppState.deterHeat = $("deter-heatmap").value;
      if (AppState.deterHeat) AppState.layers.choro = false;
      refreshSelection();
    });
    $("toggle-deter").addEventListener("change", () => {
      AppState.layers.deter = $("toggle-deter").checked;
      if (!AppState.layers.deter) AppState.deterHeat = "";
      refreshSelection();
    });
    $("toggle-flows").addEventListener("change", () => {
      AppState.layers.flows = $("toggle-flows").checked;
      refreshSelection();
    });
    $("flow-country").addEventListener("change", () => {
      AppState.flowCountry = $("flow-country").value;
      if (AppState.layers.flows) refreshActiveLayers(false);
    });
    $("toggle-facilities").addEventListener("change", () => {
      AppState.layers.facilities = $("toggle-facilities").checked;
      refreshSelection();
    });

    $("basemap-mode").addEventListener("change", () => {
      AppState.basemap = $("basemap-mode").value;
      deckgl.setProps({mapStyle: BASEMAPS[AppState.basemap] || BASEMAPS.dark});
      if (AppState.basemap === "terrain") {
        AppState.extrudeMun = false;
        setView({pitch: 56, zoom: Math.max(currentView.zoom || 4, 5.2)});
      }
      syncUI();
      drawLayers();
    });
    $("toggle-extrude-mun").addEventListener("change", () => {
      AppState.extrudeMun = $("toggle-extrude-mun").checked;
      if (AppState.extrudeMun && AppState.basemap === "terrain") {
        AppState.basemap = "dark";
        deckgl.setProps({mapStyle: BASEMAPS.dark});
      }
      if (AppState.extrudeMun && (currentView.pitch || 0) < 30) setView({pitch: 48});
      syncUI();
      drawLayers();
    });
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

    $("cam-2d").addEventListener("click", () => setView({pitch: 0, bearing: 0}));
    $("cam-3d").addEventListener("click", () => setView({pitch: 48, bearing: -12}));
    $("zoom-in").addEventListener("click", () => setView({zoom: currentView.zoom + 1}));
    $("zoom-out").addEventListener("click", () => setView({zoom: Math.max(0, currentView.zoom - 1)}));
    $("reset-view").addEventListener("click", () => {
      AppState.bioma = "";
      AppState.highlightCodes = [];
      setView(BRAZIL_2D);
      drillState("");
    });
    $("clear-filters").addEventListener("click", () => {
      selectMetric("");
      Object.assign(AppState, {
        year: null, yearPinned: false, bioma: "", chain: "soja", facilityChain: "all",
        flowCountry: "", deterHeat: "", highlightCodes: [], undoSnapshot: null,
        layers: {choro: false, deter: false, flows: false, facilities: false},
      });
      $("mun-search").value = "";
      drillState("");
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
          const searchQs = new URLSearchParams({q});
          if (AppState.uf) searchQs.set("uf", AppState.uf);
          if (AppState.bioma) searchQs.set("bioma", AppState.bioma);
          const res = await fetch(`/api/agro/search?${searchQs}`);
          if (!res.ok) return;
          const {results} = await res.json();
          if (!results?.length) {
            const scopeHint = AppState.uf || AppState.bioma ? " neste recorte (UF/bioma)" : "";
            box.innerHTML = `<div class='search-item'><span>Nenhum município encontrado${scopeHint}</span></div>`;
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
              if (AppState.bioma && item.bioma && biomeKey(item.bioma) !== biomeKey(AppState.bioma)) {
                AppState.bioma = "";
              }
              if (AppState.uf !== item.uf) drillState(item.uf, false);
              openMunicipality(item.code);
              if (item.lon && item.lat) setView({longitude: item.lon, latitude: item.lat, zoom: 8});
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
      clearMunicipality();
      syncUI();
      if (AppState.layers.flows) refreshActiveLayers(false);
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
      if (snap.uf !== AppState.uf) clearMunicipality();
      Object.assign(AppState, snap);
      AppState.undoSnapshot = null;
      deckgl.setProps({mapStyle: BASEMAPS[AppState.basemap] || BASEMAPS.dark});
      syncUI();
      await refreshActiveLayers(true);
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

  async function init() {
    setPanel(!matchMedia("(max-width: 650px)").matches);
    deckgl = new deck.DeckGL({
      container: "map-canvas",
      mapLib: maplibregl,
      mapStyle: BASEMAPS.light,
      initialViewState: BRAZIL_2D,
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
        $("cam-2d").setAttribute("aria-pressed", String(viewState.pitch < 1));
        $("cam-3d").setAttribute("aria-pressed", String(viewState.pitch >= 1));
      },
      layers: [],
    });

    setupListeners();
    syncUI();

    try {
      const [metaRes, geoRes, stateShapes] = await Promise.all([
        fetch("/api/agro/meta"),
        fetch("/api/agro/geojson"),
        AmbianceMap.loadStates(),
      ]);
      if (!metaRes.ok) {
        const err = await metaRes.json().catch(() => ({}));
        $("map-status").textContent = `Banco indisponível: ${err.error || metaRes.status}`;
        return;
      }
      meta = await metaRes.json();
      geojson = await geoRes.json();
      states = stateShapes;

      $("metric-select").replaceChildren(
        new Option("Nenhum indicador", ""),
        ...[...document.querySelectorAll(".preset-btn")].map(button => {
          const group = document.createElement("optgroup");
          group.label = button.textContent;
          group.append(...THEMES[button.dataset.preset].map(key => new Option(meta.metrics[key].label, key)));
          return group;
        })
      );
      const stateNames = new Map(states.features.map(feature => [feature.properties.uf, feature.properties.name]));
      $("uf-select").replaceChildren(new Option("Brasil", ""), ...meta.ufs.map(u => new Option(stateNames.get(u) || u, u)));
      $("flow-country").replaceChildren(new Option("Todos os destinos", ""),
        ...Object.entries(meta.flow_countries).sort((a, b) => a[1].localeCompare(b[1], "pt-BR"))
          .map(([id, name]) => new Option(name, id)));

      const scope = new URLSearchParams(location.search);
      const metric = scope.get("metric") || "";
      const requestedUF = scope.get("uf");
      const requestedYear = Number(scope.get("year"));
      const requestedBioma = scope.get("bioma");
      const chain = scope.get("flow") || /^flows_(soja|bovinos)$/.exec(metric)?.[1];
      if (meta.ufs.includes(requestedUF)) AppState.uf = requestedUF;
      if (meta.biomes.includes(requestedBioma)) AppState.bioma = requestedBioma;
      if (Number.isInteger(requestedYear) && requestedYear >= 1985 && requestedYear <= 2100) {
        AppState.year = requestedYear;
        AppState.yearPinned = true;
      }
      if (Object.hasOwn(meta.metrics, metric)) selectMetric(metric);
      if (chain === "soja" || chain === "bovinos") {
        AppState.chain = chain;
        AppState.layers.flows = true;
      }
      if (metric === "deter_count" || metric === "deter_area") {
        AppState.layers.deter = true;
        AppState.deterHeat = metric === "deter_count" ? "count" : "area";
      }
      syncUI();
      await refreshActiveLayers(true);
      const code = scope.get("code");
      if (code && /^\d{7}$/.test(code)) await openMunicipality(code);
    } catch (err) {
      $("map-status").textContent = `Erro na inicialização: ${err.message}`;
    }
  }

  window.addEventListener("DOMContentLoaded", init);
})();

"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 1});
  const fmtInt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 0});
  const n = (v, dec = 1) => v == null ? "—" : (dec === 0 ? fmtInt.format(v) : fmt.format(v));

  const BRAZIL_3D = {longitude: -53.2, latitude: -14.2, zoom: 3.9, pitch: 48, bearing: -12};
  const BRAZIL_2D = {longitude: -53.2, latitude: -14.2, zoom: 3.7, pitch: 0, bearing: 0};

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

  const HEX_FACILITY_RANGE = [
    [20, 83, 45], [22, 163, 74], [74, 222, 128],
    [250, 204, 21], [249, 115, 22], [239, 68, 68],
  ];

  const MATERIAL_3D = {ambient: 0.55, diffuse: 0.65, shininess: 36, specularColor: [60, 64, 70]};

  // Estado único centralizado (fonte única da verdade)
  const AppState = {
    preset: "risco",
    chain: "bovinos",
    uf: "",
    bioma: "",
    year: 2022,
    metric: "trase_bovinos_exposicao_5a_ha",
    basemap: "dark",
    extrudeMun: false,
    hexMode: true,
    hexRadiusKm: 18,
    hexElevation: 120,
    layers: {choro: true, deter: true, flows: false, facilities: false},
    flowCountry: "",
    selectedCode: null,
    highlightCodes: [],
    undoSnapshot: null,
    activeTab: "ai",
  };

  let deckgl = null;
  let geojson = null;
  let meta = null;
  let choroData = null;
  let flowsData = null;
  let deterData = null;
  let facilitiesData = null;
  let lastMunicipality = null;
  let currentView = {...BRAZIL_3D};
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
    deckgl.setProps({initialViewState: next});
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

  function rampColor(value, maxVal, paletteName, alpha = 195) {
    if (!value || value <= 0 || !maxVal) {
      return AppState.basemap === "light" ? [230, 236, 233, 110] : [26, 38, 35, 75];
    }
    const pal = PALETTES[paletteName] || PALETTES.reds;
    const t = Math.min(1, Math.log1p(value) / Math.log1p(Math.max(maxVal, 1)));
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

    $("ai-spec-banner").hidden = !AppState.undoSnapshot;

    const ctxParts = [
      AppState.uf || AppState.bioma || "Brasil",
      AppState.chain === "all" ? "Todas cadeias" : (AppState.chain === "soja" ? "Soja" : "Bovinos"),
      String(AppState.year),
    ];
    if (lastMunicipality && AppState.selectedCode) {
      ctxParts.push(lastMunicipality.municipio);
    }
    $("context-pill").textContent = `Contexto: ${ctxParts.join(" · ")}`;
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
      AppState.layers = {choro: true, deter: false, flows: true, facilities: true};
      AppState.hexMode = false;
      AppState.extrudeMun = false;
    } else if (name === "producao") {
      AppState.metric = soy ? "ibge_soja_producao_t" : "ibge_bovinos_rebanho_cab";
      AppState.layers = {choro: true, deter: false, flows: false, facilities: false};
      AppState.extrudeMun = false;
    }
    syncUI();
    if (autoRefresh) refreshActiveLayers(false);
  }

  function showTooltip(info) {
    const tip = $("map-tooltip");
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
      html = `<strong>Município IBGE ${escapeHtml(code)}</strong><br>` +
        `${escapeHtml(choroData?.meta?.label || "")}: <strong>${val != null ? n(val) + " " + escapeHtml(unit) : "Sem registro"}</strong><br>` +
        `<small>Clique para abrir o Raio-X</small>`;
    } else if (info.layer.id === "deter-hex") {
      const pts = o.points || [];
      const count = o.count ?? pts.length;
      const area = o.elevationValue ?? pts.reduce((acc, p) => acc + (p.source?.area_km2 || p.area_km2 || 0), 0);
      html = `<strong>Hexágono INPE DETER (${escapeHtml(deterData?.year || AppState.year)})</strong><br>` +
        `Alertas no hexágono: <strong>${n(count, 0)}</strong><br>` +
        `Área somada: <strong>${n(area, 2)} km²</strong>`;
    } else if (info.layer.id === "facilities-hex") {
      const count = o.count ?? (o.points ? o.points.length : 0);
      html = `<strong>Concentração de Instalações</strong><br>Unidades no hexágono: <strong>${n(count, 0)}</strong>`;
    } else if (info.layer.id === "trade-flows") {
      html = `<strong>${escapeHtml(o.origin_name)} → ${escapeHtml(o.target_name)}</strong><br>` +
        `Volume: ${n(o.volume_t)} t<br>Exposição 5a: ${n(o.exposicao_ha)} ha`;
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
    tip.style.left = `${info.x + 12}px`;
    tip.style.top = `${info.y + 12}px`;
    tip.hidden = false;
  }

  function updateLegendAndUncertainty() {
    if (!choroData) return;
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
      const munAlpha = terrainMode ? 150 : (extrudeMun ? 220 : 185);
      layers.push(new deck.GeoJsonLayer({
        id: "municipalities",
        data: geojson,
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
          if (code === AppState.selectedCode) return [250, 204, 21, 240];
          if (hlSet.has(code)) return [249, 115, 22, 235];
          return rampColor(values[code], maxRef, palette, munAlpha);
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
          elevationScale: AppState.hexElevation * 4,
          elevationRange: [0, 2500],
          colorRange: HEX_FACILITY_RANGE,
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
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 1,
          getLineColor: [255, 255, 255, 220],
          radiusUnits: "pixels",
          radiusMinPixels: 3,
          radiusMaxPixels: 7,
          extensions: terrainExtensions,
          getPosition: d => [d.lon, d.lat],
          getRadius: 4,
          getFillColor: d => d.cadeia === "bovinos" ? [20, 184, 166, 230] : [250, 204, 21, 230],
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
      fetch(`/api/agro/choropleth?${choroQs}`).then(r => r.json()).then(d => { choroData = d; })
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

    const kpis = [
      ["Rebanho (IBGE PPM)", s.ibge_bovinos_rebanho_cab != null ? `${n(s.ibge_bovinos_rebanho_cab, 0)} cab.` : "—"],
      ["Soja (IBGE PAM)", s.ibge_soja_producao_t != null ? `${n(s.ibge_soja_producao_t, 0)} t` : "—"],
      ["Desmat. (MapBiomas)", s.mapbiomas_desmatamento_ha != null ? `${n(s.mapbiomas_desmatamento_ha)} ha` : "—"],
      ["SEEG Agro / MUT (tCO2e)", `${s.seeg_emissao_agro_tco2e != null ? n(s.seeg_emissao_agro_tco2e, 0) : "—"} / ${s.seeg_emissao_mut_tco2e != null ? n(s.seeg_emissao_mut_tco2e, 0) : "—"}`],
      ["Exp. Bovinos / Soja 5a", `${s.trase_bovinos_exposicao_5a_ha != null ? n(s.trase_bovinos_exposicao_5a_ha) : "—"} / ${s.trase_soja_exposicao_5a_ha != null ? n(s.trase_soja_exposicao_5a_ha) : "—"} ha`],
      ["Frigoríficos / Silos", `${n(s.inst_bovinos_total || 0, 0)} / ${n(s.inst_soja_total || 0, 0)}`],
    ];
    $("mun-grid").innerHTML = kpis.map(([k, v]) => `<div class="kpi"><strong>${v}</strong><span>${k}</span></div>`).join("");

    renderSparkline(data.series, AppState.metric);

    if (data.deter_recent?.length) {
      $("mun-deter").textContent = "INPE DETER (2023–2026): " + data.deter_recent
        .map(d => `${d.ano}: ${n(d.alertas, 0)} alertas (${n(d.area_km2)} km²)`)
        .join(" · ");
    } else {
      $("mun-deter").textContent = "Sem alertas DETER registrados entre 2023 e 2026.";
    }
    $("mun-drawer").hidden = false;
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
      btn.addEventListener("click", () => applyPreset(btn.dataset.preset, true));
    });

    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    $("toggle-left").addEventListener("click", () => {
      $("left-drawer").hidden = true;
      $("reopen-left").hidden = false;
    });
    $("reopen-left").addEventListener("click", () => {
      $("left-drawer").hidden = false;
      $("reopen-left").hidden = true;
    });
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
    $("reset-view").addEventListener("click", () => {
      AppState.uf = "";
      AppState.bioma = "";
      AppState.highlightCodes = [];
      setView(BRAZIL_3D);
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
      deckgl.setProps({mapStyle: BASEMAPS[AppState.basemap] || BASEMAPS.dark});
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

  async function init() {
    deckgl = new deck.DeckGL({
      container: "map-canvas",
      mapLib: maplibregl,
      mapStyle: BASEMAPS.dark,
      initialViewState: BRAZIL_3D,
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

    setupListeners();
    syncUI();

    try {
      const [metaRes, geoRes] = await Promise.all([
        fetch("/api/agro/meta"),
        fetch("/api/agro/geojson"),
      ]);
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
      $("uf-select").replaceChildren(new Option("Brasil (UFs)", ""), ...meta.ufs.map(u => new Option(u, u)));
      $("bioma-select").replaceChildren(new Option("Todos biomas", ""), ...meta.biomes.map(b => new Option(b, b)));

      applyPreset("risco", false);
      await refreshActiveLayers(false);
    } catch (err) {
      $("map-status").textContent = `Erro na inicialização: ${err.message}`;
    }
  }

  window.addEventListener("DOMContentLoaded", init);
})();

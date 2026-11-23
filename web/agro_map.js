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

  // AWS Open Data Terrarium DEM (sem API key) + ESRI World Imagery Satélite
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

  // Paleta clássica do exemplo oficial deck.gl HexagonLayer (calor / risco)
  const HEX_DETER_RANGE = [
    [1, 152, 189],
    [73, 227, 206],
    [216, 254, 181],
    [254, 237, 177],
    [254, 173, 84],
    [209, 55, 78],
  ];

  const HEX_FACILITY_RANGE = [
    [20, 83, 45],
    [22, 163, 74],
    [74, 222, 128],
    [250, 204, 21],
    [249, 115, 22],
    [239, 68, 68],
  ];

  const MATERIAL_3D = {
    ambient: 0.55,
    diffuse: 0.65,
    shininess: 36,
    specularColor: [60, 64, 70],
  };

  let deckgl = null;
  let geojson = null;
  let meta = null;
  let choroData = null;
  let flowsData = null;
  let deterData = null;
  let facilitiesData = null;
  let highlightCodes = new Set();
  let selectedCode = null;
  let lastMunicipality = null;
  let currentView = {...BRAZIL_3D};
  const sessionHistory = [];

  function makeLighting() {
    const ambientLight = new deck.AmbientLight({color: [255, 255, 255], intensity: 1.1});
    const dirLight1 = new deck.DirectionalLight({color: [255, 248, 235], intensity: 1.8, direction: [-2, -6, -3]});
    const dirLight2 = new deck.DirectionalLight({color: [180, 215, 255], intensity: 0.8, direction: [4, 2, -2]});
    return new deck.LightingEffect({ambientLight, dirLight1, dirLight2});
  }

  function rampColor(value, maxVal, paletteName, alpha = 195) {
    if (!value || value <= 0 || !maxVal) {
      const mode = $("basemap-mode").value;
      return mode === "light" ? [232, 238, 235, 110] : [26, 38, 35, 75];
    }
    const pal = PALETTES[paletteName] || PALETTES.reds;
    const t = Math.min(1, Math.log1p(value) / Math.log1p(Math.max(maxVal, 1)));
    const idx = Math.min(pal.length - 1, Math.floor(t * pal.length));
    return [...pal[idx], alpha];
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
      .fitBounds([[minLon, minLat], [maxLon, maxLat]], {padding: 70, maxZoom: 8.5, minExtent: 0.2});
    setView({
      longitude: vp.longitude,
      latitude: vp.latitude,
      zoom: vp.zoom,
      pitch: currentView.pitch || 45,
      bearing: currentView.bearing || -10,
    });
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
        `<small>Clique para abrir o raio-X completo</small>`;
    } else if (info.layer.id === "deter-hex") {
      const pts = o.points || [];
      const count = o.count ?? pts.length;
      const area = o.elevationValue ?? pts.reduce((acc, p) => acc + (p.source?.area_km2 || p.area_km2 || 0), 0);
      html = `<strong>Hexágono INPE DETER (${escapeHtml($("deter-year").value)})</strong><br>` +
        `Alertas no hexágono: <strong>${n(count, 0)}</strong><br>` +
        `Área somada: <strong>${n(area, 2)} km²</strong>`;
    } else if (info.layer.id === "facilities-hex") {
      const count = o.count ?? (o.points ? o.points.length : 0);
      html = `<strong>Concentração de Instalações</strong><br>` +
        `Unidades no hexágono: <strong>${n(count, 0)}</strong>`;
    } else if (info.layer.id === "trade-flows") {
      html = `<strong>${escapeHtml(o.origin_name)} → ${escapeHtml(o.target_name)}</strong><br>` +
        `Volume: ${n(o.volume_t)} t<br>` +
        `Exposição 5a: ${n(o.exposicao_ha)} ha`;
    } else if (info.layer.id === "deter-alerts") {
      html = `<strong>INPE DETER · ${escapeHtml(o.bioma)}</strong><br>` +
        `${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})<br>` +
        `Classe: ${escapeHtml(o.classname || "—")}<br>` +
        `Data: ${escapeHtml(o.view_date || "—")} · Área: ${n(o.area_km2, 2)} km²`;
    } else if (info.layer.id === "facilities") {
      const cap = o.capacidade_valor ? `${n(o.capacidade_valor, 0)} ${escapeHtml(o.capacidade_unidade || "")}` : "Sem capacidade informada";
      html = `<strong>${escapeHtml(o.empresa || "Instalação")}</strong><br>` +
        `${escapeHtml(o.tipo || o.cadeia)} · ${escapeHtml(o.nivel_inspecao || "")} ${escapeHtml(o.numero_inspecao || "")}<br>` +
        `${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})<br>` +
        `<small>${cap}</small>`;
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

  function updateLegend() {
    if (!choroData) return;
    const pal = PALETTES[choroData.meta.palette] || PALETTES.reds;
    const stops = pal.map(c => `rgb(${c[0]},${c[1]},${c[2]})`).join(", ");
    $("legend-bar").style.background = `linear-gradient(90deg, ${stops})`;
    $("legend-title").textContent = `${choroData.meta.label} (${choroData.meta.unit})`;
    $("legend-mid").textContent = n((choroData.p95 || choroData.max || 0) * 0.5, 0);
    $("legend-max").textContent = `${n(choroData.p95 || choroData.max || 0, 0)}+`;
  }

  function drawLayers() {
    if (!deckgl || !geojson) return;
    const layers = [];
    const values = choroData?.values || {};
    const maxRef = choroData?.p95 || choroData?.max || 1;
    const palette = choroData?.meta?.palette || "reds";
    const basemapMode = $("basemap-mode").value;
    const terrainMode = basemapMode === "terrain";
    const extrudeMun = $("toggle-extrude-mun").checked && !terrainMode;
    const hexMode = $("toggle-hex-mode").checked;
    const hexRadiusMeters = Number($("hex-radius").value) * 1000;
    const hexElevScale = Number($("hex-elevation").value);

    // 1. Camada de Relevo 3D + Satélite (deck.gl TerrainLayer + operation: 'terrain+draw')
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
        wireframe: false,
        operation: "terrain+draw",
      }));
      if (deck._TerrainExtension) {
        terrainExtensions.push(new deck._TerrainExtension());
      }
    }

    // 2. Municípios (Coroplético 2D / 3D Extrudado / Draped sobre Relevo 3D)
    const munAlpha = terrainMode ? 150 : (extrudeMun ? 220 : 185);
    layers.push(new deck.GeoJsonLayer({
      id: "municipalities",
      data: geojson,
      pickable: true,
      stroked: !extrudeMun,
      filled: true,
      extruded: extrudeMun,
      wireframe: false,
      elevationScale: 1,
      material: MATERIAL_3D,
      lineWidthMinPixels: 0.4,
      extensions: terrainExtensions,
      terrainDrawMode: terrainMode ? "drape" : undefined,
      getElevation: f => {
        if (!extrudeMun) return 0;
        const code = String(f.properties?.codarea || "");
        const v = values[code] || 0;
        if (!v || !maxRef) return 0;
        return Math.min(180000, (Math.log1p(v) / Math.log1p(Math.max(maxRef, 1))) * 140000);
      },
      getFillColor: f => {
        const code = String(f.properties?.codarea || "");
        if (code === selectedCode) return [250, 204, 21, 240];
        if (highlightCodes.has(code)) return [249, 115, 22, 235];
        return rampColor(values[code], maxRef, palette, munAlpha);
      },
      getLineColor: f => {
        const code = String(f.properties?.codarea || "");
        if (code === selectedCode || highlightCodes.has(code)) return [255, 255, 255, 255];
        return terrainMode ? [255, 255, 255, 70] : [110, 130, 124, 70];
      },
      getLineWidth: f => {
        const code = String(f.properties?.codarea || "");
        return (code === selectedCode || highlightCodes.has(code)) ? 2.5 : 0.4;
      },
      lineWidthUnits: "pixels",
      updateTriggers: {
        getFillColor: [choroData, selectedCode, basemapMode, extrudeMun, [...highlightCodes].join(",")],
        getElevation: [choroData, extrudeMun],
        getLineColor: [selectedCode, basemapMode, [...highlightCodes].join(",")],
        getLineWidth: [selectedCode, [...highlightCodes].join(",")],
      },
      onHover: showTooltip,
      onClick: info => {
        const code = String(info?.object?.properties?.codarea || "");
        if (code) openMunicipality(code);
      },
    }));

    // 3. Fluxos Comerciais (ArcLayer 3D luminoso)
    if ($("toggle-flows").checked && flowsData?.arcs?.length) {
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

    // 4. Alertas INPE DETER -> HexagonLayer 3D (padrão) ou ScatterplotLayer
    if ($("toggle-deter").checked && deterData?.points?.length) {
      if (hexMode && deck.HexagonLayer) {
        layers.push(new deck.HexagonLayer({
          id: "deter-hex",
          data: deterData.points,
          pickable: true,
          extruded: true,
          gpuAggregation: false,
          radius: hexRadiusMeters,
          coverage: 0.84,
          upperPercentile: 98,
          elevationScale: hexElevScale * 6,
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

    // 5. Instalações (Frigoríficos e Silos) -> HexagonLayer 3D ou ScatterplotLayer
    if ($("toggle-facilities").checked && facilitiesData?.points?.length) {
      if (hexMode && deck.HexagonLayer && !$("toggle-deter").checked) {
        layers.push(new deck.HexagonLayer({
          id: "facilities-hex",
          data: facilitiesData.points,
          pickable: true,
          extruded: true,
          gpuAggregation: false,
          radius: hexRadiusMeters,
          coverage: 0.82,
          upperPercentile: 98,
          elevationScale: hexElevScale * 4,
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

  function updateUncertaintyBadge() {
    if (!choroData) return;
    $("ub-source").textContent = `Fonte: ${choroData.meta.source} · Ano ${choroData.year}`;
    if (choroData.coverage) {
      const pct = choroData.coverage.pct_rastreado;
      const unk = (100 - Number(pct)).toFixed(1).replace(".", ",");
      $("ub-coverage").textContent = `Cobertura municipal rastreada: ${n(pct)}% (${unk}% UNKNOWN fora do mapa).`;
    } else {
      $("ub-coverage").textContent = `${n(choroData.count, 0)} municípios com registro neste recorte.`;
    }
    $("ub-caveat").textContent = choroData.meta.caveat;
  }

  function renderTopList() {
    const list = $("top-list");
    if (!choroData?.top?.length) {
      $("top-count").textContent = "0 municípios";
      list.innerHTML = "<li class='meta'>Sem dados neste recorte.</li>";
      return;
    }
    const unit = choroData.meta.unit;
    $("top-title").textContent = `Top municípios · ${choroData.year}`;
    $("top-count").textContent = `${n(choroData.count, 0)} com registro`;
    list.replaceChildren(...choroData.top.slice(0, 10).map(row => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.innerHTML = `<span>${escapeHtml(row.name)} (${escapeHtml(row.uf)})</span><strong>${n(row.value)} ${escapeHtml(unit)}</strong>`;
      btn.addEventListener("click", () => {
        openMunicipality(row.code);
        if (row.lon && row.lat) setView({longitude: row.lon, latitude: row.lat, zoom: 7.5, pitch: 52, bearing: -15});
      });
      li.append(btn);
      return li;
    }));
  }

  async function refreshChoropleth(autoFit = false) {
    const metric = $("metric-select").value;
    const year = $("year-slider").value;
    const uf = $("uf-select").value;
    const bioma = $("bioma-select").value;
    $("year-label").textContent = year;
    $("map-status").textContent = "Consultando PostgreSQL…";

    const qs = new URLSearchParams({metric, year});
    if (uf) qs.set("uf", uf);
    if (bioma) qs.set("bioma", bioma);

    const res = await fetch(`/api/agro/choropleth?${qs}`);
    choroData = await res.json();
    $("map-status").textContent = `${n(choroData.count, 0)} municípios · PostGIS`;
    updateUncertaintyBadge();
    updateLegend();
    renderTopList();
    drawLayers();
    if (autoFit && choroData.bbox) fitBbox(choroData.bbox);
  }

  async function refreshFlows() {
    if (!$("toggle-flows").checked) {
      flowsData = null;
      drawLayers();
      return;
    }
    const qs = new URLSearchParams({
      product: $("flow-product").value,
      year: $("year-slider").value,
    });
    if ($("uf-select").value) qs.set("uf", $("uf-select").value);
    if ($("flow-country").value) qs.set("country", $("flow-country").value);
    const res = await fetch(`/api/agro/flows?${qs}`);
    flowsData = await res.json();
    drawLayers();
  }

  async function refreshDeter() {
    if (!$("toggle-deter").checked) {
      deterData = null;
      drawLayers();
      return;
    }
    const qs = new URLSearchParams({year: $("deter-year").value, limit: "10000"});
    if ($("uf-select").value) qs.set("uf", $("uf-select").value);
    if ($("bioma-select").value) qs.set("bioma", $("bioma-select").value);
    const res = await fetch(`/api/agro/deter?${qs}`);
    deterData = await res.json();
    drawLayers();
  }

  async function refreshFacilities() {
    if (!$("toggle-facilities").checked) {
      facilitiesData = null;
      drawLayers();
      return;
    }
    const qs = new URLSearchParams({chain: $("facility-chain").value, limit: "10000"});
    if ($("uf-select").value) qs.set("uf", $("uf-select").value);
    const res = await fetch(`/api/agro/facilities?${qs}`);
    facilitiesData = await res.json();
    drawLayers();
  }

  async function openMunicipality(code) {
    selectedCode = code;
    drawLayers();
    const year = $("year-slider").value;
    const res = await fetch(`/api/agro/municipality?code=${encodeURIComponent(code)}&year=${encodeURIComponent(year)}`);
    if (!res.ok) return;
    const data = await res.json();
    lastMunicipality = data.municipality;
    const m = data.municipality;
    const s = data.snapshot || {};
    $("mun-title").textContent = `${m.municipio} (${m.uf})`;
    $("mun-sub").textContent = `IBGE ${m.code} · ${m.bioma || "—"} · ${n(m.area_km2, 0)} km² · Ano ${data.year}`;

    const kpis = [
      ["Rebanho (IBGE PPM)", s.ibge_bovinos_rebanho_cab != null ? `${n(s.ibge_bovinos_rebanho_cab, 0)} cab.` : "—"],
      ["Soja (IBGE PAM)", s.ibge_soja_producao_t != null ? `${n(s.ibge_soja_producao_t, 0)} t` : "—"],
      ["Desmat. (MapBiomas)", s.mapbiomas_desmatamento_ha != null ? `${n(s.mapbiomas_desmatamento_ha)} ha` : "—"],
      ["SEEG MUT (tCO2e)", s.seeg_emissao_mut_tco2e != null ? `${n(s.seeg_emissao_mut_tco2e, 0)}` : "—"],
      ["Exp. Bovinos 5a (Trase)", s.trase_bovinos_exposicao_5a_ha != null ? `${n(s.trase_bovinos_exposicao_5a_ha)} ha` : "—"],
      ["Instalações (Frig./Silos)", `${n(s.inst_bovinos_total || 0, 0)} / ${n(s.inst_soja_total || 0, 0)}`],
    ];
    $("mun-grid").innerHTML = kpis.map(([k, v]) => `<div class="kpi"><strong>${v}</strong><span>${k}</span></div>`).join("");

    if (data.deter_recent?.length) {
      $("mun-deter").textContent = "INPE DETER recente: " + data.deter_recent
        .map(d => `${d.ano}: ${n(d.alertas, 0)} alertas (${n(d.area_km2)} km²)`)
        .join(" · ");
    } else {
      $("mun-deter").textContent = "Sem alertas DETER registrados entre 2023 e 2026.";
    }
    $("mun-card").hidden = false;
  }

  async function applyMapSpec(spec) {
    if (!spec) return;
    if (spec.metric && meta?.metrics?.[spec.metric]) $("metric-select").value = spec.metric;
    if (spec.year) $("year-slider").value = String(spec.year);
    $("uf-select").value = spec.uf || "";
    $("bioma-select").value = spec.bioma || "";

    highlightCodes = new Set(spec.highlight_codes || []);
    $("clear-highlight").hidden = highlightCodes.size === 0;

    if (typeof spec.show_flows === "boolean") {
      $("toggle-flows").checked = spec.show_flows;
      if (spec.flow_product) $("flow-product").value = spec.flow_product;
    }
    if (typeof spec.show_deter === "boolean") {
      $("toggle-deter").checked = spec.show_deter;
      if (spec.deter_year) $("deter-year").value = String(spec.deter_year);
    }

    await refreshChoropleth(Boolean(spec.uf || spec.bioma));
    await Promise.all([refreshFlows(), refreshDeter(), refreshFacilities()]);
  }

  async function askAI(question) {
    $("ask-btn").disabled = true;
    const mode = $("ask-mode").value;
    $("ask-status").textContent = mode === "laws" ? "Buscando nas 29 leis…" : "Consultando PostgreSQL + Leis…";
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question, mode, domain: mode === "laws" ? "law" : "auto", k: 6}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Erro ao consultar IA.");

      renderAIResponse(question, data);
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

  function renderAIResponse(question, data) {
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
    $("history-card").hidden = sessionHistory.length === 0;
    $("history-list").replaceChildren(...sessionHistory.map(item => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.innerHTML = `<span>${escapeHtml(item.question.slice(0, 68))}${item.question.length > 68 ? "…" : ""}</span><strong>${escapeHtml(item.data.domain || "")}</strong>`;
      btn.addEventListener("click", async () => {
        $("question").value = item.question;
        renderAIResponse(item.question, item.data);
        if (item.data.map_spec) await applyMapSpec(item.data.map_spec);
      });
      li.append(btn);
      return li;
    }));
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

    // Registra controles de câmera e UI primeiro (funciona mesmo se o banco demorar)
    $("basemap-mode").addEventListener("change", () => {
      const mode = $("basemap-mode").value;
      deckgl.setProps({mapStyle: BASEMAPS[mode] || BASEMAPS.dark});
      if (mode === "terrain") {
        $("toggle-extrude-mun").checked = false;
        setView({pitch: 56, zoom: Math.max(currentView.zoom || 4, 5.2)});
      }
      drawLayers();
    });
    $("toggle-extrude-mun").addEventListener("change", () => {
      if ($("toggle-extrude-mun").checked && $("basemap-mode").value === "terrain") {
        $("basemap-mode").value = "dark";
        deckgl.setProps({mapStyle: BASEMAPS.dark});
      }
      if ($("toggle-extrude-mun").checked && (currentView.pitch || 0) < 30) {
        setView({pitch: 48});
      }
      drawLayers();
    });
    $("toggle-hex-mode").addEventListener("change", () => {
      $("hex-controls").hidden = !$("toggle-hex-mode").checked;
      drawLayers();
    });
    $("hex-radius").addEventListener("input", () => {
      $("hex-radius-val").textContent = `${$("hex-radius").value} km`;
      drawLayers();
    });
    $("hex-elevation").addEventListener("input", () => {
      $("hex-elev-val").textContent = `${$("hex-elevation").value}×`;
      drawLayers();
    });
    $("cam-3d").addEventListener("click", () => setView({pitch: 48, bearing: -12}));
    $("cam-2d").addEventListener("click", () => setView({pitch: 0, bearing: 0}));
    $("reset-view").addEventListener("click", () => {
      $("uf-select").value = "";
      $("bioma-select").value = "";
      setView(BRAZIL_3D);
      refreshChoropleth(false);
      refreshDeter();
    });

    $("metric-select").addEventListener("change", () => refreshChoropleth(false));
    $("uf-select").addEventListener("change", () => { refreshChoropleth(true); refreshFlows(); refreshDeter(); refreshFacilities(); });
    $("bioma-select").addEventListener("change", () => { refreshChoropleth(true); refreshDeter(); });
    $("year-slider").addEventListener("input", () => { $("year-label").textContent = $("year-slider").value; });
    $("year-slider").addEventListener("change", () => { refreshChoropleth(false); refreshFlows(); });
    $("toggle-flows").addEventListener("change", refreshFlows);
    $("flow-product").addEventListener("change", refreshFlows);
    $("flow-country").addEventListener("change", refreshFlows);
    $("toggle-deter").addEventListener("change", refreshDeter);
    $("deter-year").addEventListener("change", refreshDeter);
    $("toggle-facilities").addEventListener("change", refreshFacilities);
    $("facility-chain").addEventListener("change", refreshFacilities);

    $("question").addEventListener("keydown", e => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        $("ask-form").requestSubmit();
      }
    });
    $("mun-close").addEventListener("click", () => {
      selectedCode = null;
      $("mun-card").hidden = true;
      drawLayers();
    });
    $("mun-ask-ai").addEventListener("click", () => {
      if (!lastMunicipality) return;
      const m = lastMunicipality;
      const q = `Faça uma análise socioambiental completa de ${m.municipio} (${m.uf}, IBGE ${m.code}) cruzando IBGE, MapBiomas, SEEG, Trase e alertas INPE DETER recentes, e indique quais obrigações do Código Florestal se aplicam ao bioma ${m.bioma || ""}.`;
      $("question").value = q;
      askAI(q);
    });
    $("clear-highlight").addEventListener("click", () => {
      highlightCodes.clear();
      $("clear-highlight").hidden = true;
      drawLayers();
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
    $("uf-select").append(...meta.ufs.map(u => new Option(u, u)));
    $("bioma-select").append(...meta.biomes.map(b => new Option(b, b)));

    // Carga inicial: coroplético + hexágonos 3D do INPE DETER 2026
    await Promise.all([refreshChoropleth(false), refreshDeter()]);
  }

  window.addEventListener("DOMContentLoaded", init);
})();

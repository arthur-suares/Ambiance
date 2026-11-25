"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 1});
  const fmtInt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 0});
  const n = (v, dec = 1) => (v == null ? "—" : (dec === 0 ? fmtInt.format(v) : fmt.format(v)));

  const BRAZIL_3D = {longitude: -53.2, latitude: -14.2, zoom: 3.9, pitch: 44, bearing: -10};
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
    [254, 240, 217], [253, 204, 138], [252, 141, 89],
    [227, 74, 51], [179, 0, 0], [127, 0, 0],
  ];
  const CHART_COLORS = ["#10b981", "#38bdf8", "#f59e0b", "#f43f5e", "#a855f7", "#eab308", "#14b8a6", "#fb7185"];
  const MATERIAL_3D = {ambient: 0.55, diffuse: 0.65, shininess: 36, specularColor: [60, 64, 70]};

  const turns = [];
  const sessionHistory = [];
  let activeTurnId = null;
  let activeSpec = null;
  let activeTab = "map";
  let selectedCode = null;
  let selectedMun = null;

  let deckgl = null;
  let geojson = null;
  let geojsonPromise = null;
  let choroData = null;
  let flowsData = null;
  let deterData = null;
  let facilitiesData = null;
  let currentView = {...BRAZIL_3D};
  let currentBasemap = "light";
  let lastBbox = null;
  let chartInstances = [];
  let progressTimer = null;
  let mbData = null;
  let mbState = {year: 2025, mode: "dominant", classIds: [], uf: "", bioma: ""};
  let mbPlayTimer = null;
  let activeTurnObj = null;
  const MB_PRESETS = {
    all: [],
    forest: [3, 4, 5, 6, 49],
    agro: [15, 39, 20, 40, 41, 46, 47, 48, 9, 21],
  };

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  function renderInline(s) {
    return escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[(D\d+)\]/g, '<span class="cite-pill cite-data">[$1]</span>')
      .replace(/\[(L\d+)\]/g, '<span class="cite-pill cite-law">[$1]</span>');
  }

  function renderMarkdown(text) {
    const lines = String(text ?? "").split("\n");
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (/^\s*#{1,4}\s+/.test(l)) {
        out.push(`<h4>${renderInline(l.replace(/^\s*#{1,4}\s+/, ""))}</h4>`);
      } else if (/^\s*\|/.test(l) && i + 1 < lines.length && /^\s*\|[\s:-]+\|/.test(lines[i + 1])) {
        const parseRow = r => r.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());
        const headers = parseRow(l);
        i += 2;
        let html = '<div class="chat-table-wrap"><table><thead><tr>' +
          headers.map(h => `<th>${renderInline(h)}</th>`).join("") +
          "</tr></thead><tbody>";
        for (; i < lines.length && /^\s*\|/.test(lines[i]); i++) {
          const cells = parseRow(lines[i]);
          html += "<tr>" + headers.map((_, idx) => `<td>${renderInline(cells[idx] ?? "")}</td>`).join("") + "</tr>";
        }
        i--;
        out.push(html + "</tbody></table></div>");
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

  function makeLighting() {
    const ambientLight = new deck.AmbientLight({color: [255, 255, 255], intensity: 1.1});
    const dirLight1 = new deck.DirectionalLight({color: [255, 248, 235], intensity: 1.8, direction: [-2, -6, -3]});
    const dirLight2 = new deck.DirectionalLight({color: [180, 215, 255], intensity: 0.8, direction: [4, 2, -2]});
    return new deck.LightingEffect({ambientLight, dirLight1, dirLight2});
  }

  async function ensureGeojson() {
    if (geojson) return geojson;
    if (!geojsonPromise) {
      geojsonPromise = fetch("/api/agro/geojson")
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(data => {
          geojson = data;
          return data;
        });
    }
    return geojsonPromise;
  }

  function ensureDeck() {
    const container = $("canvas-map-container");
    if (deckgl) return deckgl;
    deckgl = new deck.DeckGL({
      container,
      mapLib: maplibregl,
      mapStyle: BASEMAPS[currentBasemap] || BASEMAPS.dark,
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
    if (window.ResizeObserver) {
      new ResizeObserver(() => window.dispatchEvent(new Event("resize"))).observe(container);
    }
    return deckgl;
  }

  function setView(viewState) {
    if (!deckgl) return;
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
    $("btn-cam-2d").classList.toggle("is-active", (next.pitch || 0) < 10);
    $("btn-cam-3d").classList.toggle("is-active", (next.pitch || 0) >= 10);
  }

  function fitBbox(bbox, pitch) {
    if (!bbox || bbox.length !== 4 || !deckgl) return;
    const el = $("canvas-map-container");
    const w = Math.max(el.clientWidth || 700, 320);
    const h = Math.max(el.clientHeight || 500, 280);
    const vp = new deck.WebMercatorViewport({width: w, height: h})
      .fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], {padding: 64, maxZoom: 8.4, minExtent: 0.25});
    setView({
      longitude: vp.longitude,
      latitude: vp.latitude,
      zoom: vp.zoom,
      pitch: pitch ?? currentView.pitch,
      bearing: currentView.bearing,
    });
  }

  function computeHighlightBbox(codes) {
    if (!geojson?.features?.length || !codes?.length) return null;
    const set = new Set(codes);
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    const scan = coords => {
      if (typeof coords[0] === "number") {
        if (coords[0] < minX) minX = coords[0];
        if (coords[0] > maxX) maxX = coords[0];
        if (coords[1] < minY) minY = coords[1];
        if (coords[1] > maxY) maxY = coords[1];
      } else {
        for (const c of coords) scan(c);
      }
    };
    for (const f of geojson.features) {
      if (set.has(String(f.properties?.codarea || "")) && f.geometry?.coordinates) {
        scan(f.geometry.coordinates);
      }
    }
    return Number.isFinite(minX) ? [minX, minY, maxX, maxY] : null;
  }

  function rampColor(value, maxVal, paletteName, alpha = 190) {
    if (!value || value <= 0 || !maxVal) {
      return currentBasemap === "light" ? [230, 236, 233, 95] : [24, 36, 33, 70];
    }
    const pal = PALETTES[paletteName] || PALETTES.reds;
    const t = Math.min(1, Math.log1p(value) / Math.log1p(Math.max(maxVal, 1)));
    const idx = Math.min(pal.length - 1, Math.floor(t * pal.length));
    return [...pal[idx], alpha];
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
      if (activeSpec?.mapbiomas_mode && mbData) {
        const v = mbData.values?.[code];
        const domMeta = v ? mbData.classes_meta?.[String(v.dom)] : null;
        if (!v) {
          html = `<strong>Município (código ${escapeHtml(code)})</strong><br>Sem dados neste recorte`;
        } else {
          const swatch = domMeta ? `<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${domMeta.color};margin-right:5px;"></span>` : "";
          html = `<strong>${escapeHtml(v.name)} (${escapeHtml(v.uf)})</strong><br>` +
            `${swatch}Principal: <strong>${escapeHtml(domMeta?.label || "—")}</strong> (${n(v.dom_pct)}%)<br>` +
            `Área selecionada: <strong>${n(v.sel_ha, 0)} ha</strong> (${n(v.sel_pct)}%)<br>` +
            `<small>Uso do solo ${mbData.year} · Clique para ver resumo</small>`;
        }
      } else {
        const val = choroData?.values?.[code];
        const unit = choroData?.meta?.unit || "";
        html = `<strong>Município (código ${escapeHtml(code)})</strong><br>` +
          `${escapeHtml(choroData?.meta?.label || "")}: <strong>${val != null ? n(val) + " " + escapeHtml(unit) : "Sem registro"}</strong><br>` +
          `<small>Clique para ver o resumo</small>`;
      }
    } else if (info.layer.id === "deter-hex") {
      const pts = o.points || [];
      const count = o.count ?? pts.length;
      const area = o.elevationValue ?? pts.reduce((acc, p) => acc + (p.source?.area_km2 || p.area_km2 || 0), 0);
      html = `<strong>Alertas de satélite (${escapeHtml(deterData?.year || "")})</strong><br>` +
        `Ocorrências: <strong>${n(count, 0)}</strong> · Área: <strong>${n(area, 2)} km²</strong>`;
    } else if (info.layer.id === "deter-alerts") {
      html = `<strong>Alerta por satélite · ${escapeHtml(o.bioma)}</strong><br>` +
        `${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})<br>` +
        `${escapeHtml(o.classname || "—")} · ${n(o.area_km2, 2)} km²`;
    } else if (info.layer.id === "trade-flows") {
      html = `<strong>${escapeHtml(o.origin_name)} → ${escapeHtml(o.target_name)}</strong><br>` +
        `Volume: ${n(o.volume_t)} t<br>Exposição recente ao desmatamento: ${n(o.exposicao_ha)} ha`;
    } else if (info.layer.id === "facilities") {
      html = `<strong>${escapeHtml(o.empresa || "Unidade produtiva")}</strong><br>` +
        `${escapeHtml(o.tipo || o.cadeia)} · ${escapeHtml(o.municipio || "—")} (${escapeHtml(o.uf || "—")})`;
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

  function drawMapLayers(spec) {
    if (!deckgl || !geojson) return;
    const layers = [];
    const values = choroData?.values || {};
    const maxRef = choroData?.p95 || choroData?.max || 1;
    const palette = choroData?.meta?.palette || "reds";
    const terrainMode = currentBasemap === "terrain";
    const hexDeterActive = Boolean(spec?.show_deter && spec?.deter_mode === "hex" && deterData?.points?.length);
    const hlSet = new Set(spec?.highlight_codes || []);

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

    layers.push(new deck.GeoJsonLayer({
      id: "municipalities",
      data: geojson,
      pickable: true,
      stroked: true,
      filled: true,
      extruded: false,
      lineWidthMinPixels: 0.4,
      extensions: terrainExtensions,
      terrainDrawMode: terrainMode ? "drape" : undefined,
      getFillColor: f => {
        const code = String(f.properties?.codarea || "");
        if (code === selectedCode) return [250, 204, 21, 210];
        if (hlSet.has(code)) {
          return hexDeterActive ? [245, 158, 11, 85] : [245, 158, 11, 205];
        }
        if (spec?.mapbiomas_mode && mbData) {
          const v = mbData.values?.[code];
          if (!v) return currentBasemap === "light" ? [230, 236, 233, 85] : [20, 30, 28, 60];
          const rgb = mbData.classes_meta?.[String(v.dom)]?.rgb || [100, 116, 139];
          if (mbState.mode === "dominant") {
            return [rgb[0], rgb[1], rgb[2], terrainMode ? 170 : 220];
          }
          const ratio = Math.min(1, Math.sqrt((v.sel_pct || 0) / Math.max(mbData.max_pct || 100, 1)));
          const alpha = Math.round(45 + ratio * 200);
          return [rgb[0], rgb[1], rgb[2], alpha];
        }
        if (hexDeterActive) {
          return terrainMode ? [226, 232, 228, 35] : [226, 232, 228, 90];
        }
        return rampColor(values[code], maxRef, palette, terrainMode ? 145 : 185);
      },
      getLineColor: f => {
        const code = String(f.properties?.codarea || "");
        if (code === selectedCode) return [180, 83, 9, 255];
        if (hlSet.has(code)) return [217, 119, 6, 255];
        if (hexDeterActive) return [140, 154, 146, 110];
        return terrainMode ? [255, 255, 255, 65] : [110, 130, 124, 65];
      },
      getLineWidth: f => {
        const code = String(f.properties?.codarea || "");
        if (code === selectedCode || hlSet.has(code)) return 2.8;
        return 0.4;
      },
      lineWidthUnits: "pixels",
      updateTriggers: {
        getFillColor: [choroData, mbData, mbState.mode, hexDeterActive, selectedCode, currentBasemap, (spec?.highlight_codes || []).join(",")],
        getLineColor: [hexDeterActive, selectedCode, currentBasemap, (spec?.highlight_codes || []).join(",")],
        getLineWidth: [selectedCode, (spec?.highlight_codes || []).join(",")],
      },
      onHover: showTooltip,
      onClick: info => {
        const code = String(info?.object?.properties?.codarea || "");
        if (code) openMunicipality(code);
      },
    }));

    if (spec?.show_flows && flowsData?.arcs?.length) {
      layers.push(new deck.ArcLayer({
        id: "trade-flows",
        data: flowsData.arcs,
        pickable: true,
        greatCircle: true,
        getHeight: 0.35,
        getSourcePosition: d => d.source,
        getTargetPosition: d => d.target,
        getSourceColor: d => d.exposicao_ha > 500 ? [244, 63, 94, 225] : [16, 185, 129, 205],
        getTargetColor: [56, 189, 248, 210],
        getWidth: d => Math.min(5, 1.2 + Math.log1p(d.volume_t / 5000) * 0.65),
        widthUnits: "pixels",
        onHover: showTooltip,
      }));
    }

    if (spec?.show_deter && deterData?.points?.length) {
      if (spec.deter_mode === "hex" && deck.HexagonLayer) {
        layers.push(new deck.HexagonLayer({
          id: "deter-hex",
          data: deterData.points,
          pickable: true,
          extruded: true,
          gpuAggregation: false,
          radius: 24000,
          coverage: 0.78,
          lowerPercentile: 10,
          upperPercentile: 98,
          elevationScale: 520,
          elevationRange: [0, 2200],
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

    if (spec?.show_facilities && facilitiesData?.points?.length) {
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
        getRadius: 4.5,
        getFillColor: d => d.cadeia === "bovinos" ? [20, 184, 166, 235] : [250, 204, 21, 235],
        onHover: showTooltip,
      }));
    }

    deckgl.setProps({layers});
  }

  function updateLegendAndScope(spec) {
    if (!choroData) return;
    const hexDeterActive = Boolean(spec.show_deter && spec.deter_mode === "hex" && deterData?.points?.length);
    if (hexDeterActive) {
      const stops = HEX_DETER_RANGE.map(c => `rgb(${c[0]},${c[1]},${c[2]})`).join(", ");
      $("legend-bar").style.background = `linear-gradient(90deg, ${stops})`;
      $("legend-title").textContent = "Concentração de alertas por satélite (área atingida)";
      $("legend-min").textContent = "Menor";
      $("legend-mid").textContent = "Moderada";
      $("legend-max").textContent = "Crítica (mais alta)";
      $("ub-source").textContent = `Alertas de satélite · Ano ${deterData.year}`;
      $("ub-coverage").textContent = "Cada coluna agrupa alertas próximos. Quanto mais alta e vermelha, maior a área de alerta.";
    } else {
      const pal = PALETTES[choroData.meta.palette] || PALETTES.reds;
      const stops = pal.map(c => `rgb(${c[0]},${c[1]},${c[2]})`).join(", ");
      $("legend-bar").style.background = `linear-gradient(90deg, ${stops})`;
      $("legend-title").textContent = `${choroData.meta.label} (${choroData.meta.unit})`;
      $("legend-min").textContent = "0";
      $("legend-mid").textContent = n((choroData.p95 || choroData.max || 0) * 0.5, 0);
      $("legend-max").textContent = `${n(choroData.p95 || choroData.max || 0, 0)}+`;
      $("ub-source").textContent = `Fonte: ${choroData.meta.source} · Ano ${choroData.year}`;
      if (choroData.coverage) {
        const pct = choroData.coverage.pct_rastreado;
        const unk = (100 - Number(pct)).toFixed(1).replace(".", ",");
        $("ub-coverage").textContent = `Origem identificada: ${n(pct)}% (${unk}% sem origem informada nos registros).`;
      } else {
        $("ub-coverage").textContent = `${n(choroData.count, 0)} municípios com dados neste recorte.`;
      }
    }

    const extras = [];
    if (spec.highlight_codes?.length) {
      extras.push(`<div class="legend-extra-item"><span class="legend-swatch-box" style="background:rgba(245,158,11,0.35);border:2px solid #d97706;"></span><span>Município(s) principal(is) da sua pergunta</span></div>`);
    }
    if (spec.show_flows && flowsData?.arcs?.length) {
      extras.push(`<div class="legend-extra-item"><span class="legend-swatch-line" style="background:linear-gradient(90deg,#10b981,#38bdf8);"></span><span>Rotas de exportação para países de destino</span></div>`);
    }
    if (spec.show_facilities && facilitiesData?.points?.length) {
      extras.push(`<div class="legend-extra-item"><span class="legend-swatch-dot" style="background:#14b8a6;border:1px solid #fff;"></span><span>Frigoríficos e armazéns registrados</span></div>`);
    }
    $("legend-extras").innerHTML = extras.join("");
    $("legend-extras").hidden = extras.length === 0;

    $("ub-caveat").textContent = choroData.meta.caveat;
    $("map-legend-card").hidden = false;

    const scopeParts = [spec.uf || spec.bioma || "Brasil"];
    if (spec.show_deter) scopeParts.push(`Alertas por satélite ${deterData?.year || spec.deter_year || spec.year || 2026}`);
    if (spec.show_flows) scopeParts.push(`Exportações de ${spec.flow_product || "bovinos"} (${flowsData?.year || spec.year || 2022})`);
    if (spec.show_facilities) scopeParts.push("Frigoríficos e armazéns");
    if (spec.highlight_codes?.length) scopeParts.push(`${spec.highlight_codes.length} município(s) em destaque`);
    $("map-scope-pill").textContent = scopeParts.join(" · ");

    const notes = [];
    if (choroData.year_fallback) notes.push(`Indicador do mapa: último ano disponível (${choroData.year})`);
    if (spec.show_flows && flowsData?.year_fallback) notes.push(`Exportações: último ano disponível (${flowsData.year})`);
    if (spec.show_deter && deterData?.year_fallback) notes.push(`Alertas: último ano disponível (${deterData.year})`);
    $("map-fallback-badge").hidden = notes.length === 0;
    $("map-fallback-badge").textContent = notes.join(" · ");
  }

  function stopMbPlay() {
    if (mbPlayTimer) {
      clearInterval(mbPlayTimer);
      mbPlayTimer = null;
    }
    $("mb-play").textContent = "▶";
  }

  function renderMapbiomasLegend() {
    if (!mbData) return;
    $("mb-year-slider").value = String(mbState.year);
    $("mb-year-label").textContent = String(mbState.year);
    document.querySelectorAll(".mb-mode-btn").forEach(b => {
      b.classList.toggle("is-active", b.dataset.mbMode === mbState.mode);
    });
    const selSet = new Set(mbState.classIds);
    const list = $("mb-class-list");
    list.replaceChildren(...(mbData.summary || []).slice(0, 18).map(item => {
      const btn = document.createElement("button");
      btn.type = "button";
      const active = selSet.size === 0 || selSet.has(item.classe_id);
      btn.className = `mb-class-item ${selSet.has(item.classe_id) ? "is-selected" : ""} ${active ? "" : "is-muted"}`;
      const mha = item.area_ha / 1e6;
      const areaTxt = mha >= 1 ? `${n(mha, 1)} M ha` : `${n(item.area_ha / 1000, 0)} mil ha`;
      btn.innerHTML = `
        <span class="mb-swatch-wrap">
          <span class="mb-swatch" style="background:${escapeHtml(item.color)}"></span>
          <span class="mb-class-label">${escapeHtml(item.label)}</span>
        </span>
        <span class="mb-class-val">${n(item.pct, 1)}% · ${areaTxt}</span>
      `;
      btn.addEventListener("click", () => {
        const s = new Set(mbState.classIds);
        if (s.has(item.classe_id)) s.delete(item.classe_id);
        else s.add(item.classe_id);
        mbState.classIds = [...s];
        document.querySelectorAll(".mb-preset-btn").forEach(b => b.classList.remove("is-active"));
        loadMapbiomas(false);
      });
      return btn;
    }));
  }

  function buildMapbiomasChart(series) {
    if (!series?.length) return null;
    return {
      title: `Evolução da Cobertura do Solo (${series[0].ano}–${series[series.length - 1].ano})`,
      subtitle: `${mbState.uf || mbState.bioma || "Brasil"} · MapBiomas (milhões de hectares)`,
      chart_type: "area",
      stacked: true,
      unit: "M ha",
      labels: series.map(r => String(r.ano)),
      series: [
        {name: "Floresta e Savana", values: series.map(r => +(r.floresta_ha / 1e6).toFixed(2)), color: "#1f8d49"},
        {name: "Pastagem", values: series.map(r => +(r.pastagem_ha / 1e6).toFixed(2)), color: "#edde8e"},
        {name: "Agricultura", values: series.map(r => +(r.agricultura_ha / 1e6).toFixed(2)), color: "#f54ca9"},
        {name: "Mosaico / Silvicultura", values: series.map(r => +(r.mosaico_silv_ha / 1e6).toFixed(2)), color: "#c29b61"},
        {name: "Veg. Campestre / Alagada", values: series.map(r => +(r.herbacea_alagada_ha / 1e6).toFixed(2)), color: "#519799"},
        {name: "Água / Urbano / Outros", values: series.map(r => +(r.outros_agua_ha / 1e6).toFixed(2)), color: "#2532e4"},
      ],
    };
  }

  async function loadMapbiomas(includeSeries = true) {
    const qs = new URLSearchParams({
      year: String(mbState.year),
      mode: mbState.mode,
      include_series: includeSeries ? "1" : "0",
    });
    if (mbState.classIds.length) qs.set("classes", mbState.classIds.join(","));
    if (mbState.uf) qs.set("uf", mbState.uf);
    if (mbState.bioma) qs.set("bioma", mbState.bioma);

    $("map-scope-pill").textContent = `MapBiomas ${mbState.year} · carregando…`;
    const prevSeries = mbData?.series || null;
    const res = await fetch(`/api/agro/mapbiomas?${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    mbData = await res.json();
    if (!includeSeries && prevSeries) mbData.series = prevSeries;

    $("map-legend-card").hidden = true;
    $("map-fallback-badge").hidden = true;
    $("mb-legend-card").hidden = false;
    $("mb-timebar").hidden = false;

    const scopeParts = ["MapBiomas", mbState.uf || mbState.bioma || "Brasil", String(mbData.year)];
    scopeParts.push(mbState.classIds.length ? `${mbState.classIds.length} classe(s)` : "Todas as classes");
    $("map-scope-pill").textContent = scopeParts.join(" · ");

    renderMapbiomasLegend();
    drawMapLayers(activeSpec);

    if (includeSeries && mbData.series?.length) {
      const chart = buildMapbiomasChart(mbData.series);
      if (chart) {
        $("tab-btn-data").hidden = false;
        $("tab-btn-data").textContent = "Dados";
        $("charts-container").hidden = false;
        renderCharts([chart]);
      }
    }
  }

  async function renderMapSpec(spec) {
    activeSpec = spec;
    if (!spec) return;
    $("map-scope-pill").textContent = "Carregando camadas do mapa…";
    await ensureGeojson();
    ensureDeck();

    const targetBasemap = spec.basemap === "terrain" ? "terrain" : "light";
    if (currentBasemap !== targetBasemap) {
      currentBasemap = targetBasemap;
      deckgl.setProps({mapStyle: BASEMAPS[currentBasemap]});
    }
    $("btn-terrain").classList.toggle("is-active", currentBasemap === "terrain");

    if (spec.mapbiomas_mode) {
      mbState = {
        year: spec.mapbiomas_year || spec.year || 2025,
        mode: spec.mapbiomas_classes?.length ? "share" : "dominant",
        classIds: Array.isArray(spec.mapbiomas_classes) ? [...spec.mapbiomas_classes] : [],
        uf: spec.uf || "",
        bioma: spec.bioma || "",
      };
      flowsData = null;
      deterData = null;
      facilitiesData = null;
      await loadMapbiomas(true);
      lastBbox = computeHighlightBbox(spec.highlight_codes) || mbData?.bbox || null;
      const targetPitch = spec.view_3d ? 46 : 0;
      if (lastBbox) fitBbox(lastBbox, targetPitch);
      else setView({...BRAZIL_3D, pitch: targetPitch});
      return;
    }

    stopMbPlay();
    $("mb-legend-card").hidden = true;
    $("mb-timebar").hidden = true;

    const metric = spec.metric || (
      spec.show_deter ? "inpe_deter_area_km2" :
      spec.show_flows ? (spec.flow_product === "soja" ? "trase_soja_volume_t" : "trase_bovinos_volume_t") :
      "mapbiomas_desmatamento_ha"
    );
    const year = spec.year || spec.deter_year || 2025;

    const choroQs = new URLSearchParams({metric, year: String(year)});
    if (spec.uf) choroQs.set("uf", spec.uf);
    if (spec.bioma) choroQs.set("bioma", spec.bioma);

    const tasks = [fetch(`/api/agro/choropleth?${choroQs}`).then(r => r.json()).then(d => { choroData = d; })];

    if (spec.show_flows) {
      const fqs = new URLSearchParams({product: spec.flow_product || "bovinos", year: String(year)});
      if (spec.uf) fqs.set("uf", spec.uf);
      tasks.push(fetch(`/api/agro/flows?${fqs}`).then(r => r.json()).then(d => { flowsData = d; }));
    } else {
      flowsData = null;
    }

    if (spec.show_deter) {
      const dqs = new URLSearchParams({year: String(spec.deter_year || spec.year || 2026), limit: "10000"});
      if (spec.uf) dqs.set("uf", spec.uf);
      if (spec.bioma) dqs.set("bioma", spec.bioma);
      tasks.push(fetch(`/api/agro/deter?${dqs}`).then(r => r.json()).then(d => { deterData = d; }));
    } else {
      deterData = null;
    }

    if (spec.show_facilities) {
      const iqs = new URLSearchParams({chain: spec.facilities_chain || spec.flow_product || "bovinos", limit: "6000"});
      if (spec.uf) iqs.set("uf", spec.uf);
      tasks.push(fetch(`/api/agro/facilities?${iqs}`).then(r => r.json()).then(d => { facilitiesData = d; }));
    } else {
      facilitiesData = null;
    }

    await Promise.all(tasks);
    updateLegendAndScope(spec);
    drawMapLayers(spec);

    const hlBbox = computeHighlightBbox(spec.highlight_codes);
    lastBbox = hlBbox || choroData?.bbox || null;
    const want3d = spec.view_3d === true || spec.deter_mode === "hex";
    const targetPitch = want3d ? 42 : 0;
    if (lastBbox) {
      fitBbox(lastBbox, targetPitch);
    } else {
      setView({...BRAZIL_3D, pitch: targetPitch});
    }
  }

  async function openMunicipality(code) {
    selectedCode = code;
    drawMapLayers(activeSpec);
    const year = activeSpec?.year || 2025;
    const res = await fetch(`/api/agro/municipality?code=${encodeURIComponent(code)}&year=${encodeURIComponent(year)}`);
    if (!res.ok) return;
    const data = await res.json();
    const m = data.municipality;
    const s = data.snapshot || {};
    selectedMun = m;

    $("mun-mini-title").textContent = `${m.municipio} (${m.uf})`;
    $("mun-mini-sub").textContent = `${m.bioma || "Brasil"} · Dados de ${data.effective_year}`;
    const kpis = [
      ["Desmatamento no ano", s.mapbiomas_desmatamento_ha != null ? `${n(s.mapbiomas_desmatamento_ha)} ha` : "—"],
      ["Rebanho ou soja", s.ibge_soja_producao_t ? `${n(s.ibge_soja_producao_t, 0)} t` : `${n(s.ibge_bovinos_rebanho_cab, 0)} cabeças`],
      ["Emissões (agro / floresta)", `${n(s.seeg_emissao_agro_tco2e, 0)} / ${n(s.seeg_emissao_mut_tco2e, 0)} t`],
      ["Exposição recente (5 anos)", `${n(s.trase_bovinos_exposicao_5a_ha, 0)} / ${n(s.trase_soja_exposicao_5a_ha, 0)} ha`],
    ];
    $("mun-mini-kpis").innerHTML = kpis.map(([k, v]) => `<div class="mini-kpi"><strong>${v}</strong><span>${k}</span></div>`).join("");
    $("mun-minicard").hidden = false;
  }

  function destroyCharts() {
    for (const c of chartInstances) {
      try { c.destroy(); } catch {}
    }
    chartInstances = [];
  }

  function renderCharts(charts) {
    destroyCharts();
    const wrap = $("charts-container");
    wrap.innerHTML = "";
    if (!charts?.length) return;

    charts.forEach((ch, idx) => {
      const card = document.createElement("div");
      card.className = "chart-card";
      const sub = ch.subtitle ? `<p>${escapeHtml(ch.subtitle)}</p>` : "";
      card.innerHTML = `
        <div class="chart-head">
          <div><h3>${escapeHtml(ch.title)}</h3>${sub}</div>
          <button type="button" class="btn-ghost-sm" data-dl="${idx}">Baixar imagem</button>
        </div>
        <div class="chart-canvas-wrap"><canvas></canvas></div>
      `;
      wrap.append(card);

      const ctx = card.querySelector("canvas").getContext("2d");
      const isHoriz = ch.chart_type === "horizontal_bar";
      const isDoughnut = ch.chart_type === "doughnut";
      const isArea = ch.chart_type === "area";
      const chartJsType = isHoriz ? "bar" : (isArea ? "line" : ch.chart_type);

      const datasets = ch.series.map((s, sIdx) => {
        // Mesma paleta e mesma ordem do Painel completo (a cor sugerida pela IA em s.color destoava dele).
        const base = CHART_COLORS[sIdx % CHART_COLORS.length];
        if (isDoughnut) {
          return {
            label: s.name,
            data: s.values,
            backgroundColor: ch.labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
            borderColor: "#ffffff",
            borderWidth: 2,
          };
        }
        return {
          label: s.name,
          data: s.values,
          // Barras sólidas e arredondadas, sem contorno: iguais às do Painel completo.
          backgroundColor: isArea ? `${base}33` : base,
          borderColor: base,
          borderWidth: chartJsType === "bar" ? 0 : 2,
          borderRadius: (chartJsType === "bar") ? 5 : 0,
          fill: isArea,
          tension: 0.25,
          pointRadius: (chartJsType === "line") ? 3 : 0,
        };
      });

      const instance = new Chart(ctx, {
        type: chartJsType,
        data: {labels: ch.labels, datasets},
        options: {
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: isHoriz ? "y" : "x",
          plugins: {
            legend: {
              display: ch.series.length > 1 || isDoughnut,
              labels: {color: "#16211b", font: {size: 11}},
            },
            tooltip: {
              callbacks: {
                label: c => {
                  const val = typeof c.raw === "number" ? fmt.format(c.raw) : c.raw;
                  return `${c.dataset.label}: ${val}${ch.unit ? " " + ch.unit : ""}`;
                },
              },
            },
          },
          scales: isDoughnut ? {} : {
            x: {
              ticks: {color: "#5a6a61", font: {size: 11}},
              grid: {color: "rgba(22, 33, 27, 0.08)"},
              title: ch.x_label ? {display: true, text: ch.x_label, color: "#5a6a61"} : undefined,
            },
            y: {
              stacked: Boolean(ch.stacked),
              ticks: {color: "#5a6a61", font: {size: 11}},
              grid: {color: "rgba(22, 33, 27, 0.08)"},
              title: ch.y_label ? {display: true, text: ch.y_label, color: "#5a6a61"} : undefined,
            },
          },
        },
      });
      chartInstances.push(instance);

      card.querySelector("[data-dl]").addEventListener("click", () => {
        const a = document.createElement("a");
        a.href = instance.toBase64Image();
        a.download = `agro-grafico-${idx + 1}.png`;
        a.click();
      });
    });
  }

  function downloadCsv(tbl) {
    const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [tbl.columns.map(esc).join(",")];
    for (const r of tbl.rows) {
      lines.push(tbl.columns.map(c => esc(r[c])).join(","));
    }
    const blob = new Blob(["\uFEFF" + lines.join("\n")], {type: "text/csv;charset=utf-8;"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(tbl.label || "dados").toLowerCase()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Células da tabela: números em pt-BR (no máximo 2 casas), anos e códigos sem separador de milhar.
  const fmtCell2 = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 2});
  const RAW_NUM_COL = /(^|_)(ano|year|codigo|code|ibge|id|cnpj|cep)(_|$)/i;
  function fmtCell(col, v) {
    if (v === null || v === undefined || v === "") return "";
    const n = typeof v === "number" ? v : (typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v.trim()) ? Number(v) : NaN);
    if (!Number.isFinite(n) || RAW_NUM_COL.test(col)) return String(v);
    return fmtCell2.format(n);
  }
  const prettyCol = c => String(c).replace(/_/g, " ").replace(/\btco2e\b/i, "tCO₂e").replace(/^\w/, ch => ch.toUpperCase());

  // Quando a IA não desenhou gráfico, monta um a partir da primeira tabela com rótulo + número
  // (ranking em barras horizontais), para a aba Dados nunca ficar só com tabelas.
  function autoChartsFromTables(tables) {
    for (const t of (tables || [])) {
      const rows = t.rows || [], cols = t.columns || [];
      if (rows.length < 2) continue;
      const isNum = c => rows.filter(r => r[c] !== null && r[c] !== "" && Number.isFinite(Number(r[c]))).length >= rows.length * 0.8;
      const numCols = cols.filter(c => !RAW_NUM_COL.test(c) && isNum(c));
      const labelCol = cols.find(c => !numCols.includes(c) && !RAW_NUM_COL.test(c));
      if (!numCols.length || !labelCol) continue;
      const items = rows.map(r => ({l: String(r[labelCol] ?? "—"), v: Number(r[numCols[0]])}))
        .filter(d => Number.isFinite(d.v)).sort((a, b) => b.v - a.v).slice(0, 12);
      if (items.length < 2) continue;
      return [{
        title: t.purpose || `${prettyCol(numCols[0])} por ${prettyCol(labelCol).toLowerCase()}`,
        subtitle: `Gráfico automático a partir da tabela [${t.label || "D"}]`,
        chart_type: "horizontal_bar",
        labels: items.map(d => d.l),
        series: [{name: prettyCol(numCols[0]), values: items.map(d => d.v)}],
        unit: "",
      }];
    }
    return [];
  }

  function renderDataTab(tables, toolCalls) {
    const wrap = $("data-container");
    wrap.innerHTML = "";
    const sqlByLabel = new Map((toolCalls || []).filter(c => c.name === "query_agro_sql").map(c => [c.label, c]));

    for (const tbl of (tables || [])) {
      const card = document.createElement("div");
      card.className = "data-card";
      const meta = sqlByLabel.get(tbl.label);
      const sqlHtml = meta
        ? `<details class="sql-details"><summary>Detalhes técnicos da consulta (${meta.rows} registros em ${meta.seconds}s)</summary><pre>${escapeHtml(meta.output)}</pre></details>`
        : "";
      const tableHtml = tbl.rows?.length
        ? `<div class="table-scroll"><table><thead><tr>${tbl.columns.map(c => `<th>${escapeHtml(prettyCol(c))}</th>`).join("")}</tr></thead><tbody>` +
          tbl.rows.map(r => `<tr>${tbl.columns.map(c => `<td>${escapeHtml(fmtCell(c, r[c]))}</td>`).join("")}</tr>`).join("") +
          `</tbody></table></div>`
        : "<p class='msg-meta'>Nenhum registro encontrado para este recorte.</p>";

      card.innerHTML = `
        <div class="data-card-head">
          <strong>${escapeHtml(tbl.purpose || "Tabela de resultados")}</strong>
          <button type="button" class="btn-ghost-sm">Baixar planilha</button>
        </div>
        ${tableHtml}
        ${sqlHtml}
      `;
      card.querySelector("button").addEventListener("click", () => downloadCsv(tbl));
      wrap.append(card);
    }
  }

  function renderLawsTab(sources) {
    const wrap = $("laws-container");
    wrap.innerHTML = "";
    for (const s of (sources || [])) {
      const card = document.createElement("div");
      card.className = "law-card";
      card.innerHTML = `
        <div class="law-card-head">
          <strong>[${escapeHtml(s.label)}] ${escapeHtml(s.title)} · art. ${escapeHtml(s.artigo || "—")}</strong>
          <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">Texto oficial ↗</a>
        </div>
        <div class="msg-meta">${escapeHtml(s.parte || "")} · Relevância ${fmt.format(Number(s.score || 0))}</div>
        ${s.excerpt ? `<p class="law-excerpt">${escapeHtml(s.excerpt)}</p>` : ""}
      `;
      wrap.append(card);
    }
  }

  function normalizeViews(d) {
    const raw = Array.isArray(d.available_views) && d.available_views.length
      ? d.available_views
      : [
          ...(d.map_spec ? [{key: "map", label: "Mapa", summary: d.map_spec.title || "Mapa interativo"}] : []),
          ...((d.charts?.length || d.tables?.length) ? [{
            key: "data",
            label: "Dados",
            summary: d.charts?.[0]?.title || d.tables?.[0]?.purpose || "Gráficos e tabelas dos resultados",
            what_you_see: "Gráficos interativos e tabelas completas com os números usados na resposta.",
            what_you_receive: "Valores ao passar o mouse, download do gráfico como imagem e planilha em CSV pronta para Excel.",
          }] : []),
          ...(d.sources?.length ? [{key: "laws", label: `Trechos da Lei (${d.sources.length})`, summary: "Artigos citados na resposta"}] : []),
        ];
    const out = [];
    let dataView = null;
    for (const v of raw) {
      if (d.domain === "law" && v.key !== "laws") continue;
      if (v.key === "charts" || v.key === "data") {
        if (!dataView) {
          dataView = {...v, key: "data", label: "Dados"};
          out.push(dataView);
        } else {
          dataView.summary = [dataView.summary, v.summary].filter(Boolean).join(" · ");
          dataView.what_you_see = [dataView.what_you_see, v.what_you_see].filter(Boolean).join(" ");
          dataView.what_you_receive = [dataView.what_you_receive, v.what_you_receive].filter(Boolean).join(" ");
        }
      } else {
        out.push({...v});
      }
    }
    if (d.tables?.length && d.domain !== "law" && !out.some(v => v.key === "dash")) {
      out.push({
        key: "dash",
        label: "Painel completo",
        summary: "Gerado pelo agente de dashboard (leva cerca de 1 minuto)",
        what_you_see: "Painel montado pelo agente de dashboard: ele escolhe os dados na base Trase (carne e soja), desenha os gráficos e um revisor confere antes de mostrar.",
        what_you_receive: "Indicadores e gráficos interativos (passe o mouse para ver os valores). Por usar consulta própria, alguns números podem diferir dos da resposta.",
      });
    }
    return out;
  }

  function updateCanvasDescription(turn, tabName) {
    const views = turn?.views || turn?.data?.available_views || [];
    let view = views.find(v => v.key === tabName);
    if (!view && activeSpec?.mapbiomas_mode && !turn) {
      view = tabName === "map"
        ? {
            what_you_see: "Mapa do Brasil por município mostrando o principal uso do solo (floresta, pastagem, lavoura e água) de 1985 a 2025.",
            what_you_receive: "Filtro por tipo de cobertura, alternância entre uso principal e porcentagem da área, linha do tempo animada e resumo ao clicar nos municípios.",
          }
        : {
            what_you_see: "Gráfico com a mudança da cobertura do solo ao longo de 40 anos (florestas, pastagens, lavouras e água).",
            what_you_receive: "Valores anuais detalhados ao passar o mouse e opção para baixar o gráfico como imagem.",
          };
    }
    if (!view && tabName === "dash") {
      view = {
        what_you_see: "Painel montado pelo agente de dashboard: ele escolhe os dados na base Trase (carne e soja), desenha os gráficos e um revisor confere antes de mostrar.",
        what_you_receive: "Indicadores e gráficos interativos (passe o mouse para ver os valores). Por usar consulta própria, alguns números podem diferir dos da resposta.",
      };
    }
    if (!view) {
      $("canvas-desc-bar").hidden = true;
      return;
    }
    $("canvas-desc-see").textContent = view.what_you_see || "";
    $("canvas-desc-receive").textContent = view.what_you_receive || "";
    $("canvas-desc-bar").hidden = false;
  }

  function switchCanvasTab(tabName) {
    const resolved = tabName === "charts" ? "data" : tabName;
    activeTab = resolved;
    document.querySelectorAll(".canvas-tab").forEach(b => b.classList.toggle("is-active", b.dataset.tab === resolved));
    document.querySelectorAll(".canvas-panel").forEach(p => {
      const on = p.id === `panel-${resolved}`;
      p.classList.toggle("is-active", on);
      p.hidden = !on;
    });
    updateCanvasDescription(activeTurnObj, resolved);
    if (activeTurnId) {
      document.querySelectorAll(".view-action-btn").forEach(el => {
        el.classList.toggle("is-active", el.dataset.turnId === String(activeTurnId) && el.dataset.viewKey === resolved);
      });
    }
    if (resolved === "map") {
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    }
    if (resolved === "dash") loadDashboard(activeTurnObj);
  }

  // Painel completo: só é pedido quando há intenção (clique, abrir o canvas da resposta ou hover/foco no cartão).
  // Hover, abertura do canvas e clique compartilham a mesma promessa: o painel nunca é gerado duas vezes.
  function requestDashboard(turn) {
    if (!turn) return Promise.reject(new Error("Turno inválido."));
    if (turn.dashUrl) return Promise.resolve(turn.dashUrl);
    if (!turn.dashPromise) {
      turn.dashPromise = fetchDashboard(turn).catch(err => { turn.dashPromise = null; throw err; });
    }
    return turn.dashPromise;
  }

  async function loadDashboard(turn) {
    if (!turn) return;
    const frame = $("dash-frame"), loading = $("dash-loading");
    if (turn.dashUrl) { showDashFrame(turn.dashUrl); return; }
    frame.hidden = true;
    loading.hidden = false;
    $("dash-loading-txt").textContent = "O agente de dashboard está montando o painel: escolhe os dados, desenha os gráficos e revisa… (cerca de 30 segundos)";
    try {
      const url = await requestDashboard(turn);
      if (activeTurnObj === turn && activeTab === "dash") showDashFrame(url);
    } catch (err) {
      $("dash-loading-txt").textContent = `Não foi possível gerar o painel: ${err.message}`;
    }
  }

  async function fetchDashboard(turn) {
    const chatCharts = (turn.data?.charts || []).map(c => ({
      title: c.title || "",
      subtitle: c.subtitle || "",
      chart_type: c.chart_type || "bar",
      x_label: c.x_label || "",
      y_label: c.y_label || "",
      unit: c.unit || "",
      labels: Array.isArray(c.labels) ? c.labels.slice(0, 30) : [],
      series: Array.isArray(c.series)
        ? c.series.map(s => ({name: s.name || "", values: Array.isArray(s.values) ? s.values.slice(0, 30) : []}))
        : [],
    }));
    const chatTables = (turn.data?.tables || []).map(t => ({
      label: t.label || "",
      purpose: t.purpose || "",
      columns: Array.isArray(t.columns) ? t.columns : [],
      rows: Array.isArray(t.rows) ? t.rows.slice(0, 60) : [],
    }));
    const payload = {question: turn.question};
    if (chatCharts.length || chatTables.length) {
      payload.context = {charts: chatCharts, tables: chatTables};
    }
    const res = await fetch("/api/dashboard", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const d = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(d.error || "Falha ao gerar o painel.");
    if (!d.url) throw new Error("Resposta do servidor sem URL do painel.");
    turn.dashUrl = d.url;
    return d.url;
  }

  function showDashFrame(url) {
    const frame = $("dash-frame");
    $("dash-loading").hidden = true;
    frame.hidden = false;
    if (frame.dataset.src === url) return;
    frame.dataset.src = url;
    frame.onload = () => {
      try {
        const doc = frame.contentDocument;
        if (!doc) return;
        doc.documentElement.classList.add("is-embed");
        doc.documentElement.setAttribute("data-theme", "light");
        const fontLink = document.querySelector('link[href*="fonts.googleapis.com"]');
        if (fontLink && !doc.head.querySelector('link[href*="fonts.googleapis.com"]')) {
          doc.head.appendChild(fontLink.cloneNode(true));
        }
      } catch { /* mesma origem */ }
    };
    frame.src = `${url}?embed=1&theme=light`;
  }

  async function openCanvasForTurn(turn, targetTab = null) {
    if (activeTurnId === turn.id && targetTab && document.body.classList.contains("canvas-open")) {
      switchCanvasTab(targetTab);
      return;
    }
    const d = turn.data;
    const isLawOnly = d.domain === "law";
    const hasMap = !isLawOnly && Boolean(d.map_spec);
    const hasCharts = !isLawOnly && Boolean(d.charts?.length);
    const hasTables = !isLawOnly && Boolean(d.tables?.length);
    const hasDados = hasCharts || hasTables;
    const hasLaws = Boolean(d.sources?.length);

    if (!hasMap && !hasDados && !hasLaws) return;
    const hasDash = hasTables && !isLawOnly;

    activeTurnId = turn.id;
    activeTurnObj = turn;

    document.body.classList.add("canvas-open");
    $("canvas-pane").hidden = false;

    $("tab-btn-map").hidden = !hasMap;
    $("tab-btn-data").hidden = !hasDados;
    $("tab-btn-laws").hidden = !hasLaws;
    $("tab-btn-dash").hidden = !hasDash;

    $("tab-btn-data").textContent = "Dados";
    $("tab-btn-laws").textContent = hasLaws ? `Trechos da Lei (${d.sources.length})` : "Trechos da Lei";

    $("canvas-title").textContent = d.map_spec?.title || d.charts?.[0]?.title || "Detalhes da Resposta";
    $("canvas-badge").hidden = !d.domain;
    $("canvas-badge").textContent = d.domain === "mixed" ? "Dados + Leis" : (d.domain === "law" ? "Legislação" : "Dados do Território");

    const defaultTab = targetTab || (hasMap ? "map" : (hasDados ? "data" : "laws"));
    switchCanvasTab(defaultTab);
    // Abrir o canvas da resposta (qualquer aba) já indica interesse: aquece o Painel completo uma única vez.
    if (hasDash && defaultTab !== "dash") requestDashboard(turn).catch(() => {});

    const chartsWrap = $("charts-container");
    const dataWrap = $("data-container");
    if (hasCharts) {
      chartsWrap.hidden = false;
      renderCharts(d.charts);
    } else {
      destroyCharts();
      chartsWrap.hidden = true;
    }

    if (hasTables) {
      dataWrap.hidden = false;
      renderDataTab(d.tables, d.tool_calls);
    } else {
      dataWrap.innerHTML = "";
      dataWrap.hidden = true;
    }
    if (hasLaws) renderLawsTab(d.sources);
    if (hasMap) {
      try {
        await renderMapSpec(d.map_spec);
      } catch (err) {
        $("map-scope-pill").textContent = `Erro no mapa: ${err.message}`;
      }
    }
  }

  function buildFollowups(data) {
    const chips = [];
    const ms = data.map_spec;
    if (ms?.show_deter && ms.deter_mode !== "hex") chips.push("Mostre esses alertas de satélite em colunas 3D");
    if (ms && !ms.show_facilities) chips.push("Adicione os frigoríficos e armazéns da região");
    if (data.domain !== "mixed") chips.push("Quais leis ambientais se aplicam a esse caso?");
    chips.push("Mostre a evolução ano a ano (2015–2025) em gráfico");
    return chips.slice(0, 3);
  }

  function appendMessageTurn(turn) {
    document.body.classList.add("has-messages");
    $("chat-welcome").hidden = true;
    $("chat-messages").hidden = false;
    $("new-chat-btn").hidden = false;

    const wrap = $("chat-messages");

    const uEl = document.createElement("div");
    uEl.className = "msg msg-user";
    uEl.textContent = turn.question;
    wrap.append(uEl);

    const aEl = document.createElement("div");
    aEl.className = "msg msg-assistant";
    const d = turn.data;
    const body = document.createElement("div");
    body.className = "msg-body";
    body.innerHTML = renderMarkdown(d.answer || "Sem resposta textual.");
    aEl.append(body);

    const views = normalizeViews(d);
    turn.views = views;

    if (views.length) {
      const box = document.createElement("div");
      box.className = "view-actions-box";
      box.innerHTML = `<div class="view-actions-title">O que você deseja explorar a partir desta resposta:</div><div class="view-actions-grid"></div>`;
      const grid = box.querySelector(".view-actions-grid");
      views.forEach(v => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "view-action-btn";
        btn.dataset.turnId = String(turn.id);
        btn.dataset.viewKey = v.key;
        btn.innerHTML = `
          <div>
            <strong>${escapeHtml(v.label)}</strong>
            <small>${escapeHtml(v.summary || "")}</small>
          </div>
          <span class="view-action-cta">Abrir visualização →</span>
        `;
        if (v.key === "dash") {
          // Hover/foco por ~420 ms no cartão indica intenção: aquece o painel (os listeners vivem só neste botão).
          let hoverTimer = null;
          const startWarmup = () => {
            if (turn.dashUrl || turn.dashPromise || hoverTimer) return;
            hoverTimer = setTimeout(() => {
              hoverTimer = null;
              if (turns.includes(turn)) requestDashboard(turn).catch(() => {});
            }, 420);
          };
          const cancelWarmup = () => {
            if (!hoverTimer) return;
            clearTimeout(hoverTimer);
            hoverTimer = null;
          };
          btn.addEventListener("mouseenter", startWarmup);
          btn.addEventListener("mouseleave", cancelWarmup);
          btn.addEventListener("focus", startWarmup);
          btn.addEventListener("blur", cancelWarmup);
          btn.addEventListener("click", cancelWarmup);
        }
        btn.addEventListener("click", () => openCanvasForTurn(turn, v.key));
        grid.append(btn);
      });
      aEl.append(box);
    }

    const followups = buildFollowups(d);
    if (followups.length) {
      const row = document.createElement("div");
      row.className = "followup-row";
      followups.forEach(q => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "followup-chip";
        chip.textContent = q;
        chip.addEventListener("click", () => sendQuestion(q));
        row.append(chip);
      });
      aEl.append(row);
    }

    const metaEl = document.createElement("div");
    metaEl.className = "msg-meta";
    metaEl.textContent = `Respondido em ${d.seconds}s`;
    aEl.append(metaEl);

    wrap.append(aEl);
    $("chat-scroll").scrollTop = $("chat-scroll").scrollHeight;
  }

  function startProgress(mode) {
    document.body.classList.add("has-messages");
    $("chat-welcome").hidden = true;
    const stages = mode === "laws"
      ? ["Consultando as leis ambientais brasileiras…", "Organizando os artigos encontrados…"]
      : ["Consultando os dados oficiais do território…", "Verificando as leis ambientais aplicáveis…", "Preparando sua resposta e as opções de visualização…"];
    let idx = 0;
    $("progress-text").textContent = stages[0];
    $("chat-progress").hidden = false;
    $("chat-scroll").scrollTop = $("chat-scroll").scrollHeight;
    progressTimer = setInterval(() => {
      idx = Math.min(stages.length - 1, idx + 1);
      $("progress-text").textContent = stages[idx];
    }, 2400);
  }

  function stopProgress() {
    clearInterval(progressTimer);
    progressTimer = null;
    $("chat-progress").hidden = true;
  }

  async function sendQuestion(question) {
    const q = question.trim();
    if (!q) return;

    $("chat-input").value = "";
    $("send-btn").disabled = true;
    const mode = $("ask-mode").value;
    startProgress(mode);

    const viewContext = activeSpec ? {
      ...activeSpec,
      selected_municipality: selectedMun ? {code: selectedMun.code, municipio: selectedMun.municipio, uf: selectedMun.uf} : null,
    } : null;

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          question: q,
          mode,
          domain: mode === "laws" ? "law" : "auto",
          k: 6,
          view_context: viewContext,
          history: sessionHistory.slice(-6),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Erro ao consultar o assistente.");

      sessionHistory.push({role: "user", content: q}, {role: "assistant", content: data.answer || ""});
      if (!data.charts?.length && data.tables?.length && data.domain !== "law") {
        data.charts = autoChartsFromTables(data.tables);
      }
      const turn = {id: turns.length + 1, question: q, data};
      turns.push(turn);
      appendMessageTurn(turn);
    } catch (err) {
      document.body.classList.add("has-messages");
      $("chat-welcome").hidden = true;
      $("chat-messages").hidden = false;
      const errBox = document.createElement("div");
      errBox.className = "msg msg-assistant";
      errBox.innerHTML = `<div class="msg-body"><p><strong>Erro:</strong> ${escapeHtml(err.message)}</p></div>`;
      $("chat-messages").append(errBox);
    } finally {
      stopProgress();
      $("send-btn").disabled = false;
      $("chat-input").focus();
    }
  }

  function resetConversation() {
    stopMbPlay();
    turns.length = 0;
    sessionHistory.length = 0;
    activeTurnId = null;
    activeTurnObj = null;
    activeSpec = null;
    selectedCode = null;
    selectedMun = null;
    currentBasemap = "light";
    destroyCharts();
    $("data-container").innerHTML = "";
    const frame = $("dash-frame");
    delete frame.dataset.src;
    frame.src = "about:blank";
    frame.hidden = true;
    $("chat-messages").innerHTML = "";
    $("chat-messages").hidden = true;
    $("chat-welcome").hidden = false;
    $("new-chat-btn").hidden = true;
    $("mun-minicard").hidden = true;
    $("canvas-pane").hidden = true;
    document.body.classList.remove("canvas-open", "has-messages");
  }

  async function openStandaloneMapbiomas() {
    activeTurnId = null;
    activeTurnObj = null;
    activeSpec = {mapbiomas_mode: true, mapbiomas_year: 2025};
    document.body.classList.add("canvas-open");
    $("canvas-pane").hidden = false;
    $("tab-btn-map").hidden = false;
    $("tab-btn-data").hidden = false;
    $("tab-btn-data").textContent = "Dados";
    $("tab-btn-dash").hidden = true;
    $("tab-btn-laws").hidden = true;
    $("charts-container").hidden = false;
    $("data-container").innerHTML = "";
    $("data-container").hidden = true;
    $("canvas-title").textContent = "Uso e Cobertura do Solo no Brasil (1985–2025)";
    $("canvas-badge").hidden = false;
    $("canvas-badge").textContent = "Todos os municípios";
    switchCanvasTab("map");
    await renderMapSpec({
      mapbiomas_mode: true,
      mapbiomas_year: 2025,
      title: "Uso e Cobertura do Solo no Brasil (1985–2025)",
      view_3d: false,
    });
  }

  function setupListeners() {
    $("open-mapbiomas-btn").addEventListener("click", openStandaloneMapbiomas);

    document.querySelectorAll(".mb-mode-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        mbState.mode = btn.dataset.mbMode;
        renderMapbiomasLegend();
        drawMapLayers(activeSpec);
      });
    });
    document.querySelectorAll(".mb-preset-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".mb-preset-btn").forEach(b => b.classList.toggle("is-active", b === btn));
        mbState.classIds = [...(MB_PRESETS[btn.dataset.mbPreset] || [])];
        mbState.mode = mbState.classIds.length ? "share" : "dominant";
        loadMapbiomas(false);
      });
    });
    $("mb-year-slider").addEventListener("input", () => {
      mbState.year = Number($("mb-year-slider").value);
      $("mb-year-label").textContent = String(mbState.year);
    });
    $("mb-year-slider").addEventListener("change", () => {
      stopMbPlay();
      loadMapbiomas(false);
    });
    $("mb-play").addEventListener("click", () => {
      if (mbPlayTimer) {
        stopMbPlay();
        return;
      }
      $("mb-play").textContent = "⏸";
      mbPlayTimer = setInterval(async () => {
        mbState.year = mbState.year >= 2025 ? 1985 : mbState.year + 1;
        await loadMapbiomas(false);
      }, 1100);
    });

    document.querySelectorAll(".starter-card").forEach(btn => {
      btn.addEventListener("click", () => sendQuestion(btn.dataset.q));
    });
    $("chat-form").addEventListener("submit", e => {
      e.preventDefault();
      sendQuestion($("chat-input").value);
    });
    $("chat-input").addEventListener("keydown", e => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        $("chat-form").requestSubmit();
      }
    });
    $("new-chat-btn").addEventListener("click", resetConversation);

    document.querySelectorAll(".canvas-tab").forEach(btn => {
      btn.addEventListener("click", () => switchCanvasTab(btn.dataset.tab));
    });
    $("canvas-close").addEventListener("click", () => {
      stopMbPlay();
      $("canvas-pane").hidden = true;
      document.body.classList.remove("canvas-open");
    });
    $("canvas-desc-toggle").addEventListener("click", () => {
      $("canvas-desc-bar").hidden = true;
    });

    $("btn-cam-2d").addEventListener("click", () => setView({pitch: 0, bearing: 0}));
    $("btn-cam-3d").addEventListener("click", () => setView({pitch: 46, bearing: -10}));
    $("btn-terrain").addEventListener("click", () => {
      currentBasemap = currentBasemap === "terrain" ? "light" : "terrain";
      $("btn-terrain").classList.toggle("is-active", currentBasemap === "terrain");
      if (deckgl) deckgl.setProps({mapStyle: BASEMAPS[currentBasemap]});
      if (currentBasemap === "terrain") setView({pitch: 56, zoom: Math.max(currentView.zoom || 4, 5.2)});
      drawMapLayers(activeSpec);
    });
    $("btn-fit").addEventListener("click", () => {
      if (lastBbox) fitBbox(lastBbox);
      else setView(BRAZIL_3D);
    });
    $("toggle-caveat").addEventListener("click", () => {
      const box = $("ub-caveat");
      box.hidden = !box.hidden;
      $("toggle-caveat").setAttribute("aria-expanded", String(!box.hidden));
    });
    $("mun-mini-close").addEventListener("click", () => {
      selectedCode = null;
      $("mun-minicard").hidden = true;
      drawMapLayers(activeSpec);
    });
    $("mun-mini-ask").addEventListener("click", () => {
      if (!selectedMun) return;
      sendQuestion(
        `Faça um resumo completo de ${selectedMun.municipio} (${selectedMun.uf}): principais números de produção, desmatamento, emissões e regras ambientais para o bioma ${selectedMun.bioma || "local"}.`
      );
    });
  }

  function init() {
    setupListeners();
  }

  window.addEventListener("DOMContentLoaded", init);
})();

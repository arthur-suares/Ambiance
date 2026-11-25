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
  const CHART_COLORS = ["#2f7956", "#39768c", "#b37639", "#a74e61", "#8063a4", "#a98a30", "#2b8c80", "#b96989"];
  const MATERIAL_3D = {ambient: 0.55, diffuse: 0.65, shininess: 36, specularColor: [60, 64, 70]};

  const turns = [];
  const exampleScope = {metric: "ibge_soja_producao_t", uf: "MT", start_year: 2015, end_year: 2025};
  const tabViews = {timeline: "timeline", charts: "dashboard", data: "data"};
  const sessionHistory = [];
  let activeTurnId = null;
  let activeSpec = null;
  let activeTab = "map";
  let selectedCode = null;
  let selectedMun = null;

  let deckgl = null;
  let geojson = null;
  let states = null;
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
  let mbRequest = null;
  let mbTiles = null;
  let mbRasterRequest = null;
  let mbPlayTimer = null;
  let activeTurnObj = null;
  let temporalRequest = null;
  const MB_PRESETS = {
    all: [],
    forest: [3, 4, 5, 6, 7, 49],
    agro: [15, 39, 20, 40, 41, 46, 47, 48, 35, 62, 9, 21],
  };

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  function renderInline(s) {
    return escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([DT]\d+)\]/g, '<span class="cite-pill cite-data">[$1]</span>')
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

  function drillState(uf) {
    if (!activeSpec || activeSpec.mapbiomas_mode) return;
    selectedCode = null;
    selectedMun = null;
    $("mun-minicard").hidden = true;
    const deterMode = uf && activeSpec.show_deter ? "points" : activeSpec.deter_mode;
    renderMapSpec({...activeSpec, uf, deter_mode: deterMode, highlight_codes: [], flow_origin: null}).catch(error => {
      $("map-scope-pill").textContent = `Erro no mapa · ${error.message}`;
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
    if (info.layer.id === "states") {
      const {uf, name} = o.properties;
      const value = choroData?.values?.[uf];
      html = `<strong>${escapeHtml(name)}</strong><br>` +
        `${value == null ? "Sem registro" : n(value) + " " + escapeHtml(choroData?.meta?.unit)}<br>` +
        "<small>Clique para ver os municípios</small>";
    } else if (info.layer.id === "municipalities") {
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
        `${escapeHtml(o.classname || "—")} · ${n(o.area_km2, 2)} km²<br>` +
        "<small>Clique para comparar imagens</small>";
    } else if (info.layer.id === "trade-flows") {
      html = `<strong>${escapeHtml(o.origin_name)} → ${escapeHtml(o.target_name)}</strong><br>` +
        `Volume: ${n(o.volume_t)} t<br>Exposição recente ao desmatamento: ${n(o.exposicao_ha)} ha`;
    } else if (info.layer.id === "facilities") {
      html = facilitiesData?.grain === "state"
        ? `<strong>${escapeHtml(o.uf_name)}</strong><br>${n(o.total, 0)} instalações de ${o.cadeia === "soja" ? "soja" : "bovinos"}<br><small>Clique para ver as instalações</small>`
        : `<strong>${escapeHtml(o.empresa || "Unidade produtiva")}</strong><br>` +
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
    const pixelMode = Boolean(spec?.mapbiomas_mode && mbTiles);

    const terrainExtensions = [];
    if (terrainMode && !pixelMode && deck.TerrainLayer) {
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

    if (pixelMode) {
      const state = states?.features.find(f => f.properties.uf === mbData.uf);
      const mask = state && deck.MaskExtension ? {
        maskId: "mapbiomas-state", extensions: [new deck.MaskExtension()], maskByInstance: false,
      } : {};
      if (mask.maskId) layers.push(new deck.GeoJsonLayer({id: mask.maskId, data: state, operation: "mask"}));
      layers.push(new deck.TileLayer({
        id: "mapbiomas-pixels", data: mbTiles, tileSize: 256, maxZoom: 14, maxRequests: 6,
        renderSubLayers: props => {
          if (!props.data) return null;
          const {west, south, east, north} = props.tile.bbox;
          return new deck.BitmapLayer(props, {
            data: null, image: props.data, bounds: [west, south, east, north],
            textureParameters: {minFilter: "nearest", magFilter: "nearest"},
            ...mask,
          });
        },
        onTileError: () => {
          if (mbTiles) $("mb-pixels-status").textContent = "Alguns blocos do mapa de pixels estão indisponíveis neste zoom.";
        },
      }));
    }

    const byState = !spec?.mapbiomas_mode && choroData?.grain === "state";
    if (byState && states) {
      layers.push(new deck.GeoJsonLayer({
        id: "states", data: states, pickable: true,
        lineWidthMinPixels: 1,
        getFillColor: f => rampColor(values[f.properties.uf], maxRef, palette, hexDeterActive ? 80 : 180),
        getLineColor: [100, 135, 125, 195],
        updateTriggers: {getFillColor: [choroData, hexDeterActive]},
        onHover: showTooltip,
        onClick: info => { if (info.object) drillState(info.object.properties.uf); },
      }));
    }
    if (!byState) layers.push(new deck.GeoJsonLayer({
      id: "municipalities",
      data: AmbianceMap.municipalitiesIn(geojson, states, spec?.mapbiomas_mode ? mbData?.uf : spec?.uf),
      pickable: true,
      stroked: true,
      filled: true,
      extruded: false,
      lineWidthMinPixels: 0.4,
      extensions: terrainExtensions,
      terrainDrawMode: terrainMode ? "drape" : undefined,
      getFillColor: f => {
        const code = String(f.properties?.codarea || "");
        if (pixelMode) return code === selectedCode ? [250, 204, 21, 65] : [0, 0, 0, 0];
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
        getFillColor: [choroData, mbData, mbState.mode, hexDeterActive, selectedCode, currentBasemap, pixelMode, (spec?.highlight_codes || []).join(",")],
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
        onClick: info => {
          const flow = info.object;
          if (!flow) return;
          if (flowsData.grain === "state") drillState(flow.origin_uf);
          else openMunicipality(flow.origin_code);
        },
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
          onClick: info => AmbianceMap.compareAlert(info.object),
        }));
      }
    }

    if (spec?.show_facilities && facilitiesData?.points?.length) {
      layers.push(AmbianceMap.facilityLayer(facilitiesData, terrainExtensions, showTooltip, drillState));
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
      $("ub-source").textContent = `INPE (DETER) · ${deterData.year}`;
      $("ub-coverage").textContent = `${n(deterData.returned, 0)} de ${n(deterData.total_alerts, 0)} registros com localização exibidos. Cada coluna agrupa alertas próximos.`;
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
        $("ub-coverage").textContent = `Rastreabilidade no Brasil: ${n(pct)}% (${unk}% sem município de origem).`;
      } else {
        const territory = choroData.grain === "state" ? "estados" : "municípios";
      $("ub-coverage").textContent = `${n(choroData.count, 0)} ${territory} com dados neste recorte.`;
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

    $("ub-caveat").textContent = hexDeterActive
      ? "Alertas destinados à fiscalização. A taxa oficial anual de desmatamento vem do PRODES."
      : choroData.meta.caveat;
    $("studio-method").href = "/metodologia#" + (hexDeterActive ? "deter_area" : choroData.metric);
    $("map-legend-card").hidden = false;

    const scopeParts = [spec.uf || spec.bioma || "Brasil"];
    if (choroData.grain === "state") scopeParts.push("por estado · clique para detalhar");
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
    list.replaceChildren(...(mbData.summary || []).map(item => {
      const btn = document.createElement("button");
      btn.type = "button";
      const active = selSet.size === 0 || selSet.has(item.classe_id);
      btn.className = `mb-class-item ${selSet.has(item.classe_id) ? "is-selected" : ""} ${active ? "" : "is-muted"}`;
      btn.setAttribute("aria-pressed", String(selSet.has(item.classe_id)));
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
        loadMapbiomas();
      });
      return btn;
    }));
  }

  function buildMapbiomasChart(series, classes, territory) {
    if (!series?.length) return null;
    if (classes.length) {
      return {
        title: classes.length === 1 ? classes[0] : "Evolução das classes selecionadas",
        subtitle: `${territory} · MapBiomas (hectares)`,
        chart_type: "line",
        unit: "ha",
        labels: series.map(r => String(r.ano)),
        series: [{name: "Área selecionada", values: series.map(r => r.area_selecionada_ha)}],
      };
    }
    return {
      title: `Evolução da Cobertura do Solo (${series[0].ano}–${series[series.length - 1].ano})`,
      subtitle: `${territory} · MapBiomas (milhões de hectares)`,
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

  async function loadMapbiomasRaster() {
    mbRasterRequest?.abort();
    mbTiles = null;
    const status = $("mb-pixels-status");
    const spec = activeSpec;
    const data = mbData;
    const enabled = spec?.mapbiomas_mode && data && $("mb-pixels").checked;
    status.hidden = !enabled;
    drawMapLayers(spec);
    if (!enabled) return;

    status.textContent = "Carregando pixels da Coleção 11…";
    const request = new AbortController();
    mbRasterRequest = request;
    const qs = new URLSearchParams({year: data.year, classes: data.class_ids.join(",")});
    try {
      const res = await fetch(`/api/agro/mapbiomas-tiles?${qs}`, {signal: request.signal});
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || "Camada de pixels indisponível.");
      if (request.signal.aborted || activeSpec !== spec || mbData !== data) return;
      mbTiles = result.url;
      status.textContent = result.url
        ? "MapBiomas · Coleção 11 · cobertura de 30 m"
        : "A seleção só tem classes das estatísticas municipais.";
      if (result.url && result.omitted.length) {
        status.textContent += ". Algumas classes selecionadas aparecem só nas estatísticas.";
      }
      drawMapLayers(spec);
    } catch (error) {
      if (!request.signal.aborted && activeSpec === spec) {
        status.textContent = "Pixels indisponíveis. Exibindo o resumo municipal.";
      }
    } finally {
      if (mbRasterRequest === request) mbRasterRequest = null;
    }
  }

  async function loadMapbiomas() {
    mbRequest?.abort();
    const request = new AbortController();
    mbRequest = request;
    const spec = activeSpec;
    const {year, mode, uf, bioma, classIds} = mbState;
    const prev = mbData?.uf === (uf || null) && mbData?.bioma === (bioma || null)
      && mbData.class_ids.join(",") === classIds.join(",") ? mbData : null;
    const includeSeries = !prev;
    const qs = new URLSearchParams({
      year: String(year),
      mode,
      include_series: includeSeries ? "1" : "0",
    });
    if (classIds.length) qs.set("classes", classIds.join(","));
    if (uf) qs.set("uf", uf);
    if (bioma) qs.set("bioma", bioma);

    $("map-scope-pill").textContent = `MapBiomas ${year} · carregando…`;
    let data;
    try {
      const res = await fetch(`/api/agro/mapbiomas?${qs}`, {signal: request.signal});
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (error) {
      if (!request.signal.aborted && activeSpec === spec) {
        stopMbPlay();
        $("map-scope-pill").textContent = `Erro ao carregar MapBiomas ${year} · ${error.message}`;
      }
      return false;
    } finally {
      if (mbRequest === request) mbRequest = null;
    }
    if (request.signal.aborted || activeSpec !== spec) return false;
    mbData = data;
    if (prev) mbData.series = prev.series;

    $("map-legend-card").hidden = true;
    $("map-fallback-badge").hidden = true;
    $("mb-legend-card").hidden = false;
    $("mb-timebar").hidden = false;

    const territory = [uf, bioma].filter(Boolean).join(" · ") || "Brasil";
    const scopeParts = ["MapBiomas", territory, String(mbData.year)];
    scopeParts.push(classIds.length ? `${classIds.length} classe(s)` : "Todas as classes");
    $("map-scope-pill").textContent = scopeParts.join(" · ");

    renderMapbiomasLegend();
    loadMapbiomasRaster();

    if (includeSeries && !activeTurnObj?.data?.dashboard) {
      const classes = classIds.map(id => mbData.classes_meta[id]?.label || String(id));
      const chart = buildMapbiomasChart(mbData.series, classes, territory);
      const charts = [...(activeTurnObj?.data?.charts || []), ...(chart ? [chart] : [])];
      $("tab-btn-charts").hidden = !charts.length;
      $("tab-btn-charts").textContent = "Dashboard";
      renderCharts(charts);
    }
    const columns = ["Ano", "Território", "Código da classe", "Classe", "Área (ha)", "% da área mapeada"];
    const rows = mbData.summary
      .filter(row => !classIds.length || classIds.includes(row.classe_id))
      .map(row => {
        const values = [mbData.year, territory, row.classe_id, row.label, row.area_ha, row.pct];
        return Object.fromEntries(columns.map((col, index) => [col, values[index]]));
      });
    $("tab-btn-data").hidden = false;
    $("tab-btn-data").textContent = "Tabela";
    const turnData = activeTurnObj?.data;
    renderDataTab([
      {label: "mapbiomas-cobertura", purpose: `Área por classe · ${territory} · ${mbData.year}`, columns, rows},
      ...(turnData?.tables || []),
    ], turnData?.tool_calls);
    if (selectedCode) renderMapbiomasMunicipality(selectedCode);
    return true;
  }

  async function renderMapSpec(spec) {
    stopMbPlay();
    mbRequest?.abort();
    mbRasterRequest?.abort();
    mbTiles = null;
    activeSpec = spec;
    if (!spec) return;
    $("map-scope-pill").textContent = "Carregando camadas do mapa…";
    const [, stateShapes] = await Promise.all([ensureGeojson(), AmbianceMap.loadStates()]);
    if (activeSpec !== spec) return;
    states = stateShapes;
    ensureDeck();
    $("map-brazil").hidden = spec.mapbiomas_mode || !spec.uf;

    const targetBasemap = spec.basemap === "terrain" ? "terrain" : "light";
    if (currentBasemap !== targetBasemap) {
      currentBasemap = targetBasemap;
      deckgl.setProps({mapStyle: BASEMAPS[currentBasemap]});
    }
    $("btn-terrain").classList.toggle("is-active", currentBasemap === "terrain");

    if (spec.mapbiomas_mode) {
      mbData = null;
      $("mb-pixels").checked = false;
      $("mb-pixels-status").hidden = true;
      selectedCode = null;
      selectedMun = null;
      $("mun-minicard").hidden = true;
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
      const ufSelect = $("mb-uf");
      if (ufSelect.options.length === 1) {
        try {
          const res = await fetch("/api/agro/meta");
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const meta = await res.json();
          ufSelect.replaceChildren(new Option("Brasil", ""), ...meta.ufs.map(uf => new Option(uf, uf)));
          ufSelect.disabled = false;
        } catch {
          ufSelect.disabled = true;
        }
      }
      if (activeSpec !== spec) return;
      ufSelect.value = mbState.uf;
      if (!await loadMapbiomas()) return;
      lastBbox = computeHighlightBbox(spec.highlight_codes) || mbData?.bbox || null;
      const targetPitch = spec.view_3d ? 46 : 0;
      if (lastBbox) fitBbox(lastBbox, targetPitch);
      else setView({...BRAZIL_3D, pitch: targetPitch});
      return;
    }

    $("mb-legend-card").hidden = true;
    $("mb-timebar").hidden = true;

    const metric = spec.metric || (
      spec.show_deter ? "inpe_deter_area_km2" :
      spec.show_flows ? (spec.flow_product === "soja" ? "trase_soja_volume_t" : "trase_bovinos_volume_t") :
      "mapbiomas_desmatamento_ha"
    );
    const year = spec.year || spec.deter_year || 2025;

    const uf = spec.uf || "";
    const bioma = spec.bioma || "";
    const detailed = (spec.highlight_codes?.length || 0) && (!spec.show_flows || spec.highlight_codes.length === 1);
    const grain = uf || detailed ? "municipality" : "state";
    const flowGrain = uf || detailed ? "municipality" : "state";
    const flowOrigin = spec.flow_origin || (detailed && spec.highlight_codes?.length === 1 ? spec.highlight_codes[0] : "");
    const readLayer = async (name, params) => {
      const qs = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== ""));
      const res = await fetch(`/api/agro/${name}?${qs}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    };
    const [choro, flows, deter, facilities] = await Promise.all([
      readLayer("choropleth", {metric, year, uf, bioma, grain}),
      spec.show_flows ? readLayer("flows", {
        product: spec.flow_product || "bovinos", year, uf,
        origin: flowOrigin, grain: flowGrain, limit: flowGrain === "state" ? 90 : 180,
      }) : null,
      spec.show_deter ? readLayer("deter", {year: spec.deter_year || spec.year || 2026, limit: 10000, uf, bioma}) : null,
      spec.show_facilities ? readLayer("facilities", {
        chain: spec.facilities_chain || spec.flow_product || "bovinos", limit: 6000, uf, grain,
      }) : null,
    ]);
    if (activeSpec !== spec) return;
    [choroData, flowsData, deterData, facilitiesData] = [choro, flows, deter, facilities];
    updateLegendAndScope(spec);
    drawMapLayers(spec);

    const hlBbox = grain === "municipality" ? computeHighlightBbox(spec.highlight_codes) : null;
    lastBbox = hlBbox || choroData?.bbox || null;
    const want3d = spec.view_3d === true || spec.deter_mode === "hex";
    const targetPitch = want3d ? 42 : 0;
    if (lastBbox) {
      fitBbox(lastBbox, targetPitch);
    } else {
      setView({...BRAZIL_3D, pitch: targetPitch});
    }
  }

  function renderMapbiomasMunicipality(code) {
    const value = mbData?.values?.[code];
    selectedMun = value ? {code, municipio: value.name, uf: value.uf} : null;
    $("mun-mini-title").textContent = value ? `${value.name} (${value.uf})` : `Município IBGE ${code}`;
    $("mun-mini-sub").textContent = `MapBiomas · ${mbData?.year || mbState.year}`;
    $("mun-mini-kpis").innerHTML = value ? [
      ["Classe principal do recorte", mbData.classes_meta[value.dom]?.label || "—"],
      ["Área das classes selecionadas", `${n(value.sel_ha)} ha · ${n(value.sel_pct)}%`],
    ].map(([label, metric]) => `<div class="mini-kpi"><strong>${escapeHtml(metric)}</strong><span>${label}</span></div>`).join("")
      : "<p>Sem dados das classes neste recorte.</p>";
    $("mun-mini-ask").hidden = !value;
    $("mun-minicard").hidden = false;
  }

  async function openMunicipality(code) {
    selectedCode = code;
    drawMapLayers(activeSpec);
    if (activeSpec?.mapbiomas_mode) {
      renderMapbiomasMunicipality(code);
      return;
    }
    const spec = activeSpec;
    if (spec?.show_flows && spec.uf && spec.flow_origin !== code) {
      renderMapSpec({...spec, flow_origin: code, highlight_codes: [code]}).catch(error => {
        $("map-scope-pill").textContent = `Erro no mapa · ${error.message}`;
      });
    }
    const year = spec?.year || 2025;
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
    $("mun-mini-ask").hidden = false;
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
    if (typeof window.Chart !== "function") {
      const status = document.createElement("p");
      status.setAttribute("role", "status");
      status.textContent = "O visualizador de gráficos está indisponível. Os valores estão na tabela abaixo.";
      wrap.append(status);
      return;
    }

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
      if (ch.milestone) {
        const note = document.createElement("p");
        note.className = "chart-annotation";
        note.textContent = ch.milestone.label;
        card.append(note);
      }
      wrap.append(card);

      const ctx = card.querySelector("canvas").getContext("2d");
      const isHoriz = ch.chart_type === "horizontal_bar";
      const isDoughnut = ch.chart_type === "doughnut";
      const isArea = ch.chart_type === "area";
      const chartJsType = isHoriz ? "bar" : (isArea ? "line" : ch.chart_type);

      const datasets = ch.series.map((s, sIdx) => {
        const base = s.color || CHART_COLORS[sIdx % CHART_COLORS.length];
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
          backgroundColor: isArea ? `${base}33` : `${base}cc`,
          borderColor: base,
          borderWidth: 2,
          borderRadius: (chartJsType === "bar") ? 5 : 0,
          fill: isArea,
          tension: ch.timeline ? 0 : 0.25,
          pointRadius: chartJsType === "line" ? context =>
            ch.labels[context.dataIndex] === ch.milestone?.period ? 6 : 3 : 0,
          pointBackgroundColor: context => ch.labels[context.dataIndex] === ch.milestone?.period ? "#a66a2b" : base,
          pointBorderColor: context => ch.labels[context.dataIndex] === ch.milestone?.period ? "#a66a2b" : base,
          spanGaps: false,
        };
      });

      let instance;
      try {
        instance = new Chart(ctx, {
          type: chartJsType,
          data: {labels: ch.labels, datasets},
          options: {
            responsive: true,
            locale: "pt-BR",
            maintainAspectRatio: false,
            indexAxis: isHoriz ? "y" : "x",
            onClick: ch.timeline ? (_event, elements) => {
              const point = elements[0];
              if (point) {
                switchCanvasTab("timeline");
                AmbianceTimeline.goTo(ch.labels[point.index]);
              }
            } : undefined,
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
                stacked: Boolean(ch.stacked && isHoriz),
                ticks: {color: "#5a6a61", font: {size: 11}},
                grid: {color: "rgba(22, 33, 27, 0.08)"},
                title: ch.x_label ? {display: true, text: ch.x_label, color: "#5a6a61"} : undefined,
              },
              y: {
                stacked: Boolean(ch.stacked && (!isHoriz || isArea)),
                ticks: {color: "#5a6a61", font: {size: 11}},
                grid: {color: "rgba(22, 33, 27, 0.08)"},
                title: ch.y_label ? {display: true, text: ch.y_label, color: "#5a6a61"} : undefined,
              },
            },
          },
        });
      } catch {
        const status = document.createElement("p");
        status.textContent = "Falha ao desenhar este gráfico. Os valores estão disponíveis na tabela.";
        card.querySelector(".chart-canvas-wrap").replaceWith(status);
        card.querySelector("[data-dl]").hidden = true;
        return;
      }
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

  function renderDataTab(tables, toolCalls, wrap = $("data-container")) {
    const inspect = wrap.id === "data-container";
    if (inspect) {
      $("data-detail").hidden = true;
      wrap.parentElement.classList.remove("has-selection");
    }
    wrap.innerHTML = "";
    const sqlByLabel = new Map((toolCalls || []).filter(c => c.name === "query_agro_sql").map(c => [c.label, c]));

    for (const tbl of (tables || [])) {
      const card = document.createElement("div");
      card.className = "data-card";
      const meta = sqlByLabel.get(tbl.label);
      const sqlHtml = meta
        ? `<details class="sql-details"><summary>Detalhes técnicos da consulta (${meta.rows} registros em ${meta.seconds}s)</summary><pre>${escapeHtml(meta.output)}</pre></details>`
        : "";
      const formatCell = (col, val) => {
        if (val == null) return col === "valor" && tbl.label === "T1" ? "Sem dados" : "";
        if (typeof val === "number" && Number.isFinite(val) && !/^(ano|year|periodo|codigo|code|ibge)/i.test(col)) {
          return n(val, Number.isInteger(val) ? 0 : 1);
        }
        return String(val);
      };
      const tableHtml = tbl.rows?.length
        ? `<div class="table-scroll"><table><thead><tr>${tbl.columns.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>` +
          tbl.rows.map(r => `<tr${tbl.label === "T1" ? ` data-period="${escapeHtml(r.periodo)}"` : ""}>${tbl.columns.map(c => `<td>${escapeHtml(formatCell(c, r[c]))}</td>`).join("")}</tr>`).join("") +
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
      if (inspect) {
        card.querySelectorAll("tbody tr").forEach((row, index) => {
          row.tabIndex = 0;
          row.dataset.record = "";
          const select = () => showDataRecord(tbl, tbl.rows[index], row);
          row.addEventListener("click", select);
          row.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              select();
            }
          });
        });
      }
      if (tbl.source || tbl.method_url) {
        const source = document.createElement(tbl.method_url ? "a" : "p");
        if (tbl.method_url) source.href = tbl.method_url;
        source.textContent = tbl.source || "Metodologia do indicador";
        card.append(source);
      }
      if (tbl.at_limit) {
        const note = document.createElement("p");
        note.className = "msg-meta";
        note.textContent = `A consulta atingiu o limite de ${tbl.row_limit} linhas. O CSV contém os resultados exibidos.`;
        card.append(note);
      }
      wrap.append(card);
    }
  }

  function showDataRecord(table, record, row) {
    $("data-container").querySelector(".timeline-selected-row")?.classList.remove("timeline-selected-row");
    row.classList.add("timeline-selected-row");
    $("data-detail-title").textContent = record.periodo ? `Registro de ${record.periodo}` : table.purpose;
    const fields = $("data-detail-fields");
    fields.replaceChildren();
    for (const column of table.columns) {
      const term = document.createElement("dt");
      term.textContent = column.replaceAll("_", " ");
      const value = document.createElement("dd");
      value.textContent = typeof record[column] === "number" ? n(record[column]) : record[column] ?? "Sem dados";
      fields.append(term, value);
    }
    const action = $("data-to-timeline");
    action.hidden = !row.dataset.period;
    action.dataset.period = row.dataset.period || "";
    $("data-detail-method").href = table.method_url || "/metodologia";
    $("data-detail").hidden = false;
    row.closest(".product-data-layout").classList.add("has-selection");
  }

  async function renderDashboardTerritory(evidence, frame) {
    const card = $("dashboard-territory");
    const hideCard = () => {
      const had = !card.hidden;
      card.hidden = true;
      card.parentElement.classList.remove("has-territory");
      if (had) requestAnimationFrame(() => chartInstances.forEach(c => c.resize()));
    };
    if (!frame?.areas?.length) {
      hideCard();
      return;
    }
    try {
      const [states, municipalities] = await Promise.all([
        AmbianceMap.loadStates(), evidence.grain === "state" ? null : ensureGeojson(),
      ]);
      if (activeTurnObj?.data.temporal !== evidence) return;
      const shapes = evidence.grain === "state" ? states
        : AmbianceMap.municipalitiesIn(municipalities, states, evidence.uf);
      const values = new Map(frame.areas.map(area => [String(area.code), area.value]));
      const features = shapes.features.filter(feature =>
        values.has(String(feature.properties.uf || feature.properties.codarea)) ||
        (evidence.uf && evidence.grain !== "state"));
      const polygons = features.map(feature => ({
        code: String(feature.properties.uf || feature.properties.codarea || ""),
        value: values.get(String(feature.properties.uf || feature.properties.codarea)),
        parts: feature.geometry.type === "Polygon" ? [feature.geometry.coordinates] : feature.geometry.coordinates,
      }));
      let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
      for (const {parts} of polygons) for (const part of parts) for (const ring of part) for (const [lon, lat] of ring) {
        west = Math.min(west, lon); east = Math.max(east, lon);
        south = Math.min(south, lat); north = Math.max(north, lat);
      }
      if (!Number.isFinite(west) || east === west || north === south) {
        hideCard();
        return;
      }
      const canvas = $("dashboard-overview");
      const ctx = canvas.getContext("2d");
      const cosLat = Math.max(0.25, Math.cos(((north + south) / 2) * Math.PI / 180));
      const scale = Math.min((canvas.width - 28) / ((east - west) * cosLat), (canvas.height - 28) / (north - south));
      const x = lon => canvas.width / 2 + (lon - (east + west) / 2) * cosLat * scale;
      const y = lat => canvas.height / 2 - (lat - (north + south) / 2) * scale;
      const max = frame.areas.reduce((cap, area) => Math.max(cap, area.value), 1);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const {code, value, parts} of polygons) {
        ctx.beginPath();
        for (const part of parts) for (const ring of part) {
          ring.forEach(([lon, lat], index) => index ? ctx.lineTo(x(lon), y(lat)) : ctx.moveTo(x(lon), y(lat)));
          ctx.closePath();
        }
        if (evidence.code) {
          ctx.fillStyle = code === evidence.code ? "#216247" : "#e5e7dd";
        } else {
          ctx.fillStyle = value == null ? "#e5e7dd" : `hsl(143 38% ${83 - 52 * Math.sqrt(Math.max(0, value / max))}%)`;
        }
        ctx.fill("evenodd");
        ctx.strokeStyle = "#fffef9";
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }
      $("dashboard-territory-title").textContent = `${evidence.scope} · ${frame.period}`;
      $("dashboard-overview-note").textContent = `${evidence.label} por ${evidence.grain === "state" ? "UF" : "município"} · ${evidence.source}`;
      card.hidden = false;
      card.parentElement.classList.add("has-territory");
      requestAnimationFrame(() => chartInstances.forEach(c => c.resize()));
    } catch {
      hideCard();
    }
  }

  function renderDashboard(dashboard, toolCalls, evidence = null) {
    const summary = $("dashboard-summary");
    const dataArea = $("dashboard-data");
    summary.replaceChildren();
    dataArea.replaceChildren();
    const latest = evidence?.frames.findLast(frame => frame.value != null);
    const territoryCard = $("dashboard-territory");
    const hasTerritory = Boolean(latest?.areas?.length);
    territoryCard.hidden = !hasTerritory;
    territoryCard.parentElement.classList.toggle("has-territory", hasTerritory);
    renderDashboardTerritory(evidence, latest);
    if (!dashboard) {
      renderCharts([]);
      return;
    }
    const title = document.createElement("h3");
    title.textContent = dashboard.title;
    const method = document.createElement("a");
    method.href = dashboard.method_url;
    method.textContent = "Metodologia e fontes";
    summary.append(title, method);
    if (dashboard.scope) {
      const scope = document.createElement("p");
      scope.textContent = dashboard.scope;
      summary.append(scope);
    }
    const kpis = document.createElement("div");
    kpis.className = "dashboard-kpis";
    function addKpi(title, value, source) {
      const item = document.createElement("div");
      const emphasis = document.createElement("strong");
      emphasis.textContent = value;
      const foot = document.createElement("small");
      foot.textContent = source;
      item.append(title, emphasis, foot);
      kpis.append(item);
    }
    if (latest) {
      addKpi(`Último valor disponível · ${latest.period}`, `${n(latest.value)} ${evidence.unit}`, evidence.source);
      const change = evidence.facts.find(fact => fact.title === "Variação no período");
      if (change) addKpi(`Variação · ${change.baseline_period} a ${change.period}`,
        `${change.change_pct > 0 ? "+" : ""}${n(change.change_pct)}%`, evidence.source);
      const lead = latest.areas?.reduce((top, area) => !top || area.value > top.value ? area : top, null);
      if (lead && latest.areas.length > 1) addKpi(`Maior valor por ${evidence.grain === "state" ? "UF" : "município"} · ${latest.period}`,
        lead.name, `${n(lead.value)} ${evidence.unit} · ${evidence.source}`);
    }
    const tableById = new Map(dashboard.tables.map(t => [t.label, t]));
    const dip = evidence?.facts.find(fact => fact.title === "Maior queda entre períodos consecutivos");
    const milestone = dip && {period: dip.period, label: AmbianceTimeline.describeFact(dip, evidence.unit)};
    const toNumber = val => {
      if (val == null || val === "") return null;
      const num = Number(val);
      return Number.isFinite(num) ? num : null;
    };
    const charts = [];
    for (const widget of dashboard.widgets) {
      const data = tableById.get(widget.dataset_id);
      if (!data) continue;
      if (widget.kind === "kpi") {
        if (!latest && widget.value != null && Number.isFinite(Number(widget.value))) {
          addKpi(widget.title, `${n(Number(widget.value))} ${widget.unit}`, widget.source);
        }
      } else if (widget.kind === "line" || widget.kind === "bar") {
        let rows = data.rows;
        if (widget.sort_by && data.label !== "T1") {
          rows = [...rows].sort((a, b) => {
            const va = a[widget.sort_by], vb = b[widget.sort_by];
            const sign = widget.ascending ? 1 : -1;
            if (va == null || vb == null) return Number(va == null) - Number(vb == null);
            return sign * (typeof va === "number" && typeof vb === "number"
              ? va - vb : String(va).localeCompare(String(vb), "pt-BR", {numeric: true}));
          });
        }
        if (widget.top_n && data.label !== "T1") rows = rows.slice(0, widget.top_n);
        let labels;
        let series;
        if (widget.color && widget.y.length === 1) {
          const yCol = widget.y[0];
          const xSet = [];
          const groups = [];
          const grid = new Map();
          for (const row of rows) {
            const xv = String(row[widget.x] ?? "—");
            const gv = String(row[widget.color] ?? "—");
            if (!xSet.includes(xv)) xSet.push(xv);
            if (!groups.includes(gv) && groups.length < 8) groups.push(gv);
            grid.set(`${xv}\0${gv}`, toNumber(row[yCol]));
          }
          labels = xSet;
          series = groups.map(gv => ({
            name: gv,
            values: xSet.map(xv => grid.get(`${xv}\0${gv}`) ?? null),
          }));
        } else {
          labels = rows.map(row => String(row[widget.x] ?? "—"));
          series = widget.y.map(column => ({
            name: column === "valor" ? dashboard.title : column,
            values: rows.map(row => toNumber(row[column])),
          }));
        }
        charts.push({
          title: widget.title,
          subtitle: [widget.subtitle, widget.source].filter(Boolean).join(" · "),
          chart_type: widget.kind === "bar" && widget.orientation === "h" ? "horizontal_bar" : widget.kind,
          stacked: widget.barmode === "stack",
          unit: widget.unit,
          labels,
          timeline: widget.dataset_id === "T1",
          milestone: widget.dataset_id === "T1" ? milestone : null,
          series,
        });
      }
    }
    if (kpis.children.length) summary.append(kpis);
    renderCharts(charts);
    if (!charts.length && dashboard.tables.length) {
      const note = document.createElement("p");
      note.className = "msg-meta";
      note.textContent = "Este resultado está disponível como indicadores e tabela.";
      summary.append(note);
    }
    renderDataTab(dashboard.tables, toolCalls, dataArea);
  }

  async function setTimelineInputs(evidence) {
    const select = $("timeline-metric");
    if (!select.options.length) {
      const res = await fetch("/api/agro/methodology");
      if (!res.ok) throw new Error("Não foi possível carregar os indicadores.");
      const {metrics} = await res.json();
      select.replaceChildren(...Object.entries(metrics)
        .filter(([key]) => key !== "inpe_deter_area_km2")
        .map(([key, metric]) => new Option(metric.label, key)));
    }
    const start = evidence.frames[0].period.split("-");
    const end = evidence.frames.at(-1).period.split("-");
    const form = $("timeline-scope").elements;
    const input = {metric: evidence.metric, uf: evidence.uf, code: evidence.code, bioma: evidence.bioma,
      start_year: start[0], end_year: end[0], frequency: start[1] ? "monthly" : "annual",
      start_month: start[1] || "", end_month: end[1] || "", classes: (evidence.classes || []).join(",")};
    for (const [name, field] of Object.entries(input)) form.namedItem(name).value = field || "";
  }

  async function requestTemporal(scope, targetTab = "timeline") {
    temporalRequest?.abort();
    const request = new AbortController();
    temporalRequest = request;
    $("timeline-status").textContent = "Consultando o recorte…";
    try {
      const res = await fetch("/api/agro/temporal", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(scope), signal: request.signal,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      if (request.signal.aborted) return;
      await openCanvasForTurn({
        id: `timeline-${Date.now()}`, data: {...data, tables: data.dashboard.tables, domain: "agro"},
      }, targetTab);
      $("timeline-status").textContent = "";
    } catch (error) {
      if (!request.signal.aborted) {
        $("timeline-status").textContent = error.message;
        if ($("canvas-badge").dataset.loading) {
          $("canvas-badge").textContent = error.message;
          $("canvas-badge").hidden = false;
        }
      }
    } finally {
      if (temporalRequest === request) {
        temporalRequest = null;
      }
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

  function updateCanvasDescription(turn, tabName) {
    let view = turn?.data?.available_views?.find(v => v.key === tabName || (tabName === "charts" && v.key === "dashboard"));
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
    if (!view || (!view.what_you_see && !view.what_you_receive)) {
      $("canvas-desc-bar").hidden = true;
      return;
    }
    $("canvas-desc-see").textContent = view.what_you_see || "";
    $("canvas-desc-receive").textContent = view.what_you_receive || "";
    $("canvas-desc-bar").hidden = false;
  }

  function switchCanvasTab(tabName, preview = false) {
    activeTab = tabName;
    showProductView(preview ? "studio" : tabViews[tabName] || "studio");
    if (tabName !== "timeline") AmbianceTimeline.hide();
    document.querySelectorAll(".canvas-tab").forEach(b => b.classList.toggle("is-active", b.dataset.tab === tabName));
    document.querySelectorAll(".canvas-panel").forEach(p => {
      const on = p.id === `panel-${tabName}`;
      p.classList.toggle("is-active", on);
      p.hidden = !on;
    });
    updateCanvasDescription(activeTurnObj, tabName);
    if (activeTurnId) {
      document.querySelectorAll(".view-action-btn").forEach(el => {
        el.classList.toggle("is-active", el.dataset.turnId === String(activeTurnId) && (el.dataset.viewKey === tabName || (tabName === 'charts' && el.dataset.viewKey === 'dashboard')));
      });
    }
    if (tabName === "timeline") AmbianceTimeline.show();
    if (tabName === "charts") requestAnimationFrame(() => {
      if (activeTab === "charts") chartInstances.forEach(chart => chart.resize());
    });
    if (tabName === "map") {
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    }
  }

  async function openCanvasForTurn(turn, targetTab = null, preview = false) {
    if (activeTurnId === turn.id && targetTab) {
      document.body.classList.add("canvas-open");
      $("canvas-pane").hidden = false;
      switchCanvasTab(targetTab === "dashboard" ? "charts" : targetTab, preview);
      return;
    }
    const d = turn.data;
    const hasMap = Boolean(d.map_spec);
    const hasTimeline = Boolean(d.temporal);
    const hasCharts = Boolean(d.dashboard || d.charts?.length);
    const hasData = Boolean(d.tables?.length);
    const hasLaws = Boolean(d.sources?.length);

    if (!hasTimeline && !hasMap && !hasCharts && !hasData && !hasLaws) return;

    stopMbPlay();
    mbRequest?.abort();
    if (!hasMap) activeSpec = null;
    activeTurnId = turn.id;
    activeTurnObj = turn;

    document.body.classList.add("canvas-open");
    $("canvas-pane").hidden = false;

    $("tab-btn-map").hidden = !hasMap;
    $("tab-btn-timeline").hidden = !hasTimeline;
    AmbianceTimeline.setEvidence(d.temporal);
    if (hasTimeline) setTimelineInputs(d.temporal).catch(error => {
      $("timeline-status").textContent = error.message;
    });
    $("tab-btn-charts").hidden = !hasCharts;
    $("tab-btn-data").hidden = !hasData;
    $("tab-btn-laws").hidden = !hasLaws;

    $("tab-btn-charts").textContent = "Dashboard";
    $("tab-btn-data").textContent = hasData ? `Dados (${d.tables.length})` : "Dados";
    $("tab-btn-laws").textContent = hasLaws ? `Trechos da Lei (${d.sources.length})` : "Trechos da Lei";

    $("canvas-title").textContent = d.temporal?.label || d.map_spec?.title || d.dashboard?.title || d.charts?.[0]?.title || "Detalhes da Resposta";
    $("canvas-badge").hidden = !d.domain;
    delete $("canvas-badge").dataset.loading;
    $("canvas-badge").textContent = d.domain === "mixed" ? "Dados + Leis" : (d.domain === "law" ? "Legislação" : "Dados do Território");

    const defaultTab = targetTab === "dashboard" ? "charts" : targetTab || (hasTimeline ? "timeline" : hasMap ? "map" : hasCharts ? "charts" : hasData ? "data" : "laws");
    switchCanvasTab(defaultTab, preview);

    renderDashboard(d.dashboard, d.tool_calls, d.temporal);
    if (!d.dashboard && d.charts?.length) renderCharts(d.charts);

    if (hasData) renderDataTab(d.tables, d.tool_calls);
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
    body.innerHTML = renderMarkdown(d.answer?.trim() || "A análise terminou sem uma conclusão escrita. Os resultados disponíveis aparecem abaixo.");
    aEl.append(body);

    const views = Array.isArray(d.available_views) && d.available_views.length
      ? d.available_views
      : [
          ...(d.map_spec ? [{key: "map", label: "Ver no mapa", summary: d.map_spec.title || "Mapa interativo"}] : []),
          ...(d.charts?.length ? [{key: "charts", label: `Ver gráficos (${d.charts.length})`, summary: d.charts[0]?.title || "Gráficos"}] : []),
          ...(d.tables?.length ? [{key: "data", label: `Ver tabela completa (${d.tables.length})`, summary: "Números detalhados e planilha"}] : []),
          ...(d.sources?.length ? [{key: "laws", label: `Ler trechos da lei (${d.sources.length})`, summary: "Artigos citados na resposta"}] : []),
        ];

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

    const timeData = $("canvas-pane").hidden ? null : activeTurnObj?.data?.temporal;
    const viewContext = timeData ? {
      metric: timeData.metric, uf: timeData.uf, bioma: timeData.bioma,
      start_period: timeData.frames[0].period, end_period: timeData.frames.at(-1).period,
      classes: timeData.classes,
      selected_municipality: timeData.code ? {code: timeData.code, municipio: timeData.focus?.name, uf: timeData.uf} : null,
    } : activeSpec ? {
      ...activeSpec,
      ...(activeSpec.mapbiomas_mode ? {year: mbData?.year || mbState.year, uf: mbState.uf, bioma: mbState.bioma} : {}),
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
      const turn = {id: turns.length + 1, question: q, data};
      turns.push(turn);
      appendMessageTurn(turn);
      if (document.body.dataset.productView === "studio" && matchMedia("(min-width: 1100px)").matches &&
          (data.dashboard || data.charts?.length)) {
        openCanvasForTurn(turn, "charts", true);
      }
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
    AmbianceTimeline.setEvidence(null);
    temporalRequest?.abort();
    stopMbPlay();
    mbRequest?.abort();
    mbRasterRequest?.abort();
    turns.length = 0;
    sessionHistory.length = 0;
    activeTurnId = null;
    activeTurnObj = null;
    activeSpec = null;
    selectedCode = null;
    selectedMun = null;
    currentBasemap = "light";
    destroyCharts();
    $("chat-messages").innerHTML = "";
    $("chat-messages").hidden = true;
    $("chat-welcome").hidden = false;
    $("new-chat-btn").hidden = true;
    $("mun-minicard").hidden = true;
    $("canvas-pane").hidden = true;
    document.body.classList.remove("canvas-open", "has-messages");
    showProductView("studio");
  }

  async function openStandaloneMapbiomas() {
    temporalRequest?.abort();
    activeTurnId = null;
    activeTurnObj = null;
    activeSpec = {mapbiomas_mode: true, mapbiomas_year: 2025};
    document.body.classList.add("canvas-open");
    $("canvas-pane").hidden = false;
    $("tab-btn-map").hidden = false;
    $("tab-btn-timeline").hidden = true;
    AmbianceTimeline.setEvidence(null);
    renderDashboard(null);
    $("tab-btn-charts").hidden = true;
    $("tab-btn-data").hidden = true;
    $("tab-btn-laws").hidden = true;
    $("canvas-title").textContent = "Uso e Cobertura do Solo no Brasil (1985–2025)";
    $("canvas-badge").hidden = false;
    $("canvas-badge").textContent = "MapBiomas · Coleção 11";
    switchCanvasTab("map");
    await renderMapSpec({
      mapbiomas_mode: true,
      mapbiomas_year: 2025,
      title: "Uso e Cobertura do Solo no Brasil (1985–2025)",
      view_3d: false,
    });
  }

  function exploreLandCover(temporal, period) {
    const year = Number(String(period || temporal.frames.at(-1)?.period).slice(0, 4));
    if (!Number.isInteger(year)) return;
    $("tab-btn-map").hidden = false;
    switchCanvasTab("map");
    renderMapSpec({
      mapbiomas_mode: true,
      mapbiomas_year: year,
      mapbiomas_classes: temporal.classes,
      uf: temporal.uf,
      bioma: temporal.bioma,
      highlight_codes: temporal.code ? [temporal.code] : [],
    }).catch(error => {
      $("map-scope-pill").textContent = error.message;
    });
  }

  function showProductView(view) {
    document.body.dataset.productView = view;
    $("product-title").textContent = AmbianceProduct.pages[view].label;
    updateProductScope();
    AmbianceProduct.highlight(view);
    const external = view === "explore" || view === "method";
    document.querySelector(".studio-workspace").hidden = external;
    $("product-external").hidden = !external;
    $("product-explore").hidden = view !== "explore";
    $("product-method").hidden = view !== "method";
    $("open-mapbiomas-btn").hidden = view !== "studio";
    $("new-chat-btn").hidden = view !== "studio" || !turns.length;
  }

  function updateProductScope(period) {
    const {temporal, map_spec: map} = activeTurnObj?.data || {};
    const year = period || temporal?.frames.findLast(frame => frame.value != null)?.period || map?.year;
    const territory = temporal?.scope || map?.uf || map?.bioma || "Brasil";
    $("product-scope").textContent = [territory, year || "Dados socioambientais"].join(" · ");
  }

  function openExternalView(view, href, carryContext = false) {
    const currentView = document.body.dataset.productView;
    const period = currentView === "timeline" ? AmbianceTimeline.getPeriod() : null;
    const {temporal, map_spec: map} = activeTurnObj?.data || {};
    const id = temporal?.metric || map?.metric;
    if (view === "explore" && carryContext && !href && id === "land_cover") {
      exploreLandCover(temporal, period);
      return;
    }
    const url = new URL(href || AmbianceProduct.pages[view].href, location.origin);
    if (url.origin !== location.origin || url.pathname !== AmbianceProduct.pages[view].href) return;
    url.searchParams.set("embedded", "1");
    if (view === "explore" && carryContext && !href) {
      const year = period || temporal?.frames.findLast(frame => frame.value != null)?.period || map?.year;
      for (const [key, value] of Object.entries({metric: id, uf: temporal?.uf || map?.uf, bioma: temporal?.bioma || map?.bioma,
        code: temporal?.code || map?.highlight_codes?.[0], year: year && String(year).slice(0, 4),
        flow: map?.show_flows ? map.flow_product : null})) {
        if (value) url.searchParams.set(key, value);
      }
    }
    if (view === "method" && !href && id) url.hash = id;
    temporalRequest?.abort();
    AmbianceTimeline.hide();
    stopMbPlay();
    const frame = $(`product-${view}`);
    showProductView(view);
    if (period && carryContext) updateProductScope(period);
    if (frame.dataset.route !== url.href) {
      frame.dataset.route = url.href;
      frame.src = url.href;
    }
    requestAnimationFrame(() => frame.contentWindow?.dispatchEvent(new frame.contentWindow.Event("resize")));
  }

  function navigateProduct(view, href, carryContext = false) {
    if (view === "explore" || view === "method") {
      openExternalView(view, href, carryContext);
      return;
    }
    if (view === "studio") {
      temporalRequest?.abort();
      AmbianceTimeline.hide();
      stopMbPlay();
      $("canvas-pane").hidden = true;
      document.body.classList.remove("canvas-open");
      showProductView("studio");
      return;
    }
    const tab = view === "dashboard" ? "charts" : view;
    let linkedScope;
    if ((view === "timeline" || view === "dashboard") && href) {
      const url = new URL(href, location.origin);
      if (url.origin === location.origin && url.pathname === "/" && url.searchParams.has("metric")) {
        linkedScope = Object.fromEntries(["metric", "uf", "bioma", "code", "start_year", "end_year"]
          .filter(key => url.searchParams.has(key)).map(key => [key, url.searchParams.get(key)]));
      }
    }
    const hasView = turn => {
      const data = turn?.data;
      if (tab === "timeline") return Boolean(data?.temporal);
      if (tab === "charts") return Boolean(data?.dashboard || data?.charts?.length);
      return Boolean(data?.tables?.length);
    };
    const turn = !linkedScope && [activeTurnObj, ...[...turns].reverse()].find(hasView);
    if (turn) {
      temporalRequest?.abort();
      openCanvasForTurn(turn, tab);
      return;
    }
    if (!linkedScope && temporalRequest && document.body.dataset.productView === view) return;
    activeTurnObj = null;
    activeTurnId = null;
    AmbianceTimeline.setEvidence(null);
    document.body.classList.add("canvas-open");
    $("canvas-pane").hidden = false;
    $("canvas-title").textContent = AmbianceProduct.pages[view].label;
    $("canvas-badge").dataset.loading = "true";
    $("canvas-badge").textContent = linkedScope ? "Carregando recorte do mapa" : "Carregando exemplo · Mato Grosso";
    $("canvas-badge").hidden = false;
    for (const id of ["map", "timeline", "charts", "data", "laws"]) $(`tab-btn-${id}`).hidden = id !== tab;
    renderDashboard(null);
    renderDataTab([]);
    switchCanvasTab(tab);
    requestTemporal(linkedScope || exampleScope, tab);
  }

  function setupListeners() {
    $("open-mapbiomas-btn").addEventListener("click", openStandaloneMapbiomas);
    document.addEventListener("ambiance:navigate", event =>
      navigateProduct(event.detail.view, event.detail.href, Boolean(event.detail.carryContext)));
    window.addEventListener("message", event => {
      if (event.origin !== location.origin || event.data?.type !== "ambiance:navigate") return;
      if (![$("product-explore").contentWindow, $("product-method").contentWindow].includes(event.source)) return;
      if (Object.hasOwn(AmbianceProduct.pages, event.data.view)) {
        navigateProduct(event.data.view, event.data.href, Boolean(event.data.carryContext));
      }
    });
    document.addEventListener("ambiance:period", event => {
      if (document.body.dataset.productView === "timeline") updateProductScope(event.detail);
    });
    $("timeline-evidence").addEventListener("click", () => {
      const period = $("timeline-evidence").dataset.period;
      switchCanvasTab("data");
      const row = [...$("data-container").querySelectorAll("[data-period]")].find(row => row.dataset.period === period);
      row?.click();
      row?.scrollIntoView({block: "nearest"});
    });
    $("data-to-timeline").addEventListener("click", event => {
      switchCanvasTab("timeline");
      AmbianceTimeline.goTo(event.currentTarget.dataset.period);
    });
    $("timeline-scope").addEventListener("submit", event => {
      event.preventDefault();
      const fields = Object.fromEntries(new FormData(event.target));
      const ids = fields.classes.trim().split(/[,\s]+/).filter(Boolean);
      if (ids.some(id => !/^\d+$/.test(id))) {
        $("timeline-status").textContent = "Informe os códigos de classe separados por vírgula.";
        return;
      }
      requestTemporal({...fields, classes: ids.map(Number)});
    });
    $("mb-pixels").addEventListener("change", loadMapbiomasRaster);

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
        loadMapbiomas();
      });
    });
    $("mb-year-slider").addEventListener("input", () => {
      mbState.year = Number($("mb-year-slider").value);
      $("mb-year-label").textContent = String(mbState.year);
    });
    $("mb-year-slider").addEventListener("change", () => {
      stopMbPlay();
      loadMapbiomas();
    });
    $("mb-uf").addEventListener("change", async () => {
      stopMbPlay();
      mbState.uf = $("mb-uf").value;
      selectedCode = null;
      selectedMun = null;
      $("mun-minicard").hidden = true;
      if (await loadMapbiomas()) {
        lastBbox = mbData.bbox;
        if (lastBbox) fitBbox(lastBbox, 0);
      }
    });
    $("mb-play").addEventListener("click", () => {
      if (mbPlayTimer) {
        stopMbPlay();
        return;
      }
      $("mb-play").textContent = "⏸";
      mbPlayTimer = setInterval(async () => {
        if (mbRequest) return;
        mbState.year = mbState.year >= 2025 ? 1985 : mbState.year + 1;
        await loadMapbiomas();
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
    $("canvas-close").addEventListener("click", () => navigateProduct("studio"));
    $("canvas-desc-toggle").addEventListener("click", () => {
      $("canvas-desc-bar").hidden = true;
    });

    $("map-brazil").addEventListener("click", () => drillState(""));
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
      selectedMun = null;
      $("mun-minicard").hidden = true;
      if (activeSpec?.flow_origin) {
        renderMapSpec({...activeSpec, flow_origin: null, highlight_codes: []}).catch(error => {
          $("map-scope-pill").textContent = `Erro no mapa · ${error.message}`;
        });
      } else drawMapLayers(activeSpec);
    });
    $("mun-mini-ask").addEventListener("click", () => {
      if (!selectedMun) return;
      sendQuestion(
        `Faça um resumo completo de ${selectedMun.municipio} (${selectedMun.uf}): principais números de produção, desmatamento, emissões e regras ambientais para o bioma ${selectedMun.bioma || "local"}.`
      );
    });
  }

  function init() {
    AmbianceTimeline.init();
    setupListeners();
    if (window.ResizeObserver && $("charts-container")) {
      new ResizeObserver(() => requestAnimationFrame(() => {
        if (activeTab === "charts" && !$("panel-charts").hidden) chartInstances.forEach(chart => chart.resize());
      })).observe($("charts-container"));
    }
    const view = new URLSearchParams(location.search).get("view");
    if (view && Object.hasOwn(AmbianceProduct.pages, view)) {
      navigateProduct(view, view === "timeline" || view === "dashboard" ? location.href : null);
    }
  }

  window.addEventListener("DOMContentLoaded", init);
})();

"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const format = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 1});
  const n = value => format.format(value || 0);
  const brazil = {longitude: -53, latitude: -13, zoom: 3.65, pitch: 0, bearing: 0};
  const world = {longitude: -5, latitude: 13, zoom: 1.15, pitch: 0, bearing: 0};
  const cycle = 152;
  const filterControls = {year: "year", origin: "filter-origin", exit: "filter-exit", country: "filter-country"};
  let map, request, network, view, frame;
  let scope = {}, networkCamera, selectedEdge, edgeRequest, edgePage;
  let roadRequest, domesticBuckets, dashedPaths;
  let local = [], abroad = [], markers = [];
  const estimatedRoads = new Map();
  const stageLabels = {origin: "Produção → hub", exit: "Hub → saída"};
  let recordLink = false;
  let time = 70;
  let lastFrame;
  let playing = !matchMedia("(prefers-reduced-motion: reduce)").matches;

  function showStatus(message, error = false) {
    $("status").textContent = message;
    $("status").classList.toggle("error", error);
  }

  function setView(viewport) {
    map.setProps({initialViewState: {...viewport, transitionDuration: 500,
      transitionInterpolator: new deck.FlyToInterpolator()}});
  }

  function fitRecord() {
    if (!view?.record) return;
    if (recordLink && abroad.length) {
      setView(world);
      return;
    }
    fitCoordinates(local.flatMap(edge => edge.path).concat(markers.map(point => point.position)));
  }

  function fitCoordinates(coordinates) {
    if (!coordinates.length) return;
    const xs = coordinates.map(point => point[0]);
    const ys = coordinates.map(point => point[1]);
    const container = $("network-map");
    const viewport = new deck.WebMercatorViewport({width: container.clientWidth, height: container.clientHeight})
      .fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]],
        {padding: 70, maxZoom: 9, minExtent: 0.03});
    setView({longitude: viewport.longitude, latitude: viewport.latitude, zoom: viewport.zoom, pitch: 0, bearing: 0});
  }

  function cameraState() {
    const {longitude, latitude, zoom, pitch, bearing} = map.getViewports()[0];
    return {longitude, latitude, zoom, pitch, bearing};
  }

  function prepareLayers(data) {
    local = [];
    abroad = [];
    const {places} = data;
    data.edges.forEach((rawEdge, i) => {
      const key = JSON.stringify([rawEdge.stage, rawEdge.from, rawEdge.to]);
      const edge = {...rawEdge, ...estimatedRoads.get(key)};
      const [from, start] = places[edge.from];
      const [to, end] = places[edge.to];
      const width = Math.min(4.5, 0.65 + Math.log1p(Math.max(0, edge.volume_t) / 5000) * 0.38);
      const description = edge.stage === "world" ? "Ligação comercial internacional (esquemática)" :
        `${stageLabels[edge.stage]} · ${edge.path ? "rota rodoviária estimada" : "ligação esquemática"}`;
      const item = {...edge, key, fromId: edge.from, toId: edge.to, from, to, start, end, width, description};
      if (edge.stage === "world") {
        abroad.push(item);
        return;
      }
      const path = edge.path || [start, end];
      const distances = [0];
      for (let j = 1; j < path.length; j++) {
        const latitudeScale = Math.cos((path[j][1] + path[j - 1][1]) * Math.PI / 360);
        distances.push(distances[j - 1] + Math.hypot(
          (path[j][0] - path[j - 1][0]) * latitudeScale, path[j][1] - path[j - 1][1]));
      }
      const offset = i * 13 % 40;
      const total = distances[distances.length - 1];
      const timestamps = distances.map(distance => offset + (total ? 90 * distance / total : 0));
      local.push({...item, path, timestamps, road: Boolean(edge.path)});
    });
    domesticBuckets = {};
    for (const stage of ["all", "origin", "exit"]) {
      const visible = stage === "all" ? local : local.filter(edge => edge.stage === stage);
      domesticBuckets[stage] = {
        visible, roads: visible.filter(edge => edge.road), direct: visible.filter(edge => !edge.road)
      };
    }
    markers = [...new Set(data.nodes || [])].filter(key => key.length !== 2).map(key => {
      const [name, position] = places[key];
      return {name, position, exit: key.startsWith("X:")};
    });
  }

  function domesticSelection() {
    return domesticBuckets[view?.record ? "all" : $("domestic-stage").value];
  }
  const getPath = edge => edge.path;
  const getTimestamps = edge => edge.timestamps;
  let AnimatedArcLayer;

  function draw() {
    if (!view) return;
    const layers = [];
    const detailed = Boolean(view.record);
    const selected = detailed ? null : selectedEdge?.key;
    const {visible, roads, direct} = domesticSelection();
    const showLocal = (detailed || $("domestic").checked) && visible.length > 0;
    const showInternational = (detailed ? recordLink : $("international").checked) && abroad.length > 0;
    $("road-legend").hidden = !showLocal || roads.length === 0;
    $("domestic-legend").hidden = !showLocal || direct.length === 0;
    $("international-legend").hidden = !showInternational;
    $("map-legend").hidden = !showLocal && !showInternational;
    if (showInternational) {
      layers.push(new AnimatedArcLayer({
        id: "world-arcs", data: abroad, getSourcePosition: d => d.start, getTargetPosition: d => d.end,
        getSourceColor: [25, 112, 204, 130], getTargetColor: [20, 95, 182, 160],
        getHeight: 0.25, numSegments: 48, greatCircle: true, widthUnits: "pixels",
        getWidth: d => detailed ? 3 : d.key === selected ? Math.max(4.5, d.width) : d.width,
        updateTriggers: {getWidth: [selected, detailed]},
        phase: time / cycle,
        pickable: true, autoHighlight: true, highlightColor: [32, 125, 220, 255]
      }));
    }
    if (showLocal) {
      const focused = edge => detailed || edge.key === selected;
      const width = edge => focused(edge) ? 4 : Math.max(1, edge.width * 0.65);
      const common = {getPath, widthUnits: "pixels", getWidth: width, pickable: true,
        autoHighlight: true, updateTriggers: {getColor: [selected, detailed], getWidth: [selected, detailed]}};
      if (direct.length) layers.push(new deck.PathLayer({
        ...common, id: "domestic-direct", data: direct,
        getColor: d => focused(d) ? [66, 101, 96, 225] : [93, 127, 120, 68],
        extensions: dashedPaths, getDashArray: [3, 2], dashGapPickable: true,
        highlightColor: [66, 101, 96, 255],
      }));
      if (roads.length) layers.push(new deck.PathLayer({
        ...common, id: "domestic-roads", data: roads, jointRounded: true,
        getColor: d => focused(d) ? [175, 75, 21, 245] : [191, 88, 30, 170],
        highlightColor: [230, 103, 19, 255],
      }));
      layers.push(new deck.TripsLayer({
        id: "domestic-trips", data: visible, getPath, getTimestamps,
        getColor: d => d.road ? [242, 110, 24, 245] : [50, 113, 104, focused(d) ? 160 : 36],
        widthUnits: "pixels", getWidth: d => d.road ? width(d) + 0.4 : Math.min(width(d), 2),
        updateTriggers: {getWidth: [selected, detailed], getColor: [selected, detailed]},
        currentTime: time, trailLength: 22, capRounded: true, jointRounded: true
      }));
    }
    if (markers.length) {
      layers.push(new deck.ScatterplotLayer({
        id: "record-markers", data: markers,
        getPosition: d => d.position, radiusUnits: "pixels",
        getRadius: 6, getFillColor: d => d.exit ? [23, 101, 196] : [25, 109, 74],
        stroked: true, lineWidthUnits: "pixels", getLineWidth: 1.5, getLineColor: [255, 255, 255],
        pickable: true
      }));
      layers.push(new deck.TextLayer({
        id: "record-labels", data: markers, characterSet: "auto",
        getPosition: d => d.position, getText: d => d.name,
        getSize: 13, sizeUnits: "pixels", getColor: [23, 45, 41],
        getPixelOffset: [11, 0], getTextAnchor: "start",
        background: true, getBackgroundColor: [255, 255, 255, 235],
        backgroundPadding: [5, 3],
      }));
    }
    map.setProps({layers});
  }

  function animate(now) {
    if (!playing) return;
    if (lastFrame === undefined) lastFrame = now;
    if (now - lastFrame >= 31) {
      time = (time + Math.min(now - lastFrame, 100) * 0.017 * Number($("speed").value)) % cycle;
      lastFrame = now;
      draw();
    }
    frame = requestAnimationFrame(animate);
  }

  function changePlayback(value) {
    playing = value;
    $("playback").textContent = playing ? "Pausar" : "Animar";
    cancelAnimationFrame(frame);
    lastFrame = undefined;
    if (playing) frame = requestAnimationFrame(animate);
  }

  async function readJSON(endpoint, query, signal) {
    const response = await fetch(endpoint + "?" + new URLSearchParams(query), {signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Falha ao carregar os dados.");
    return data;
  }

  function filterScope() {
    return Object.fromEntries(Object.entries(filterControls).map(([field, id]) => [field, $(id).value]));
  }

  function initialScope() {
    const params = new URLSearchParams(window.location.search);
    return Object.fromEntries(Object.keys(filterControls)
      .filter(field => params.has(field)).map(field => [field, params.get(field)]));
  }

  function syncFilters(query) {
    for (const [field, id] of Object.entries(filterControls)) {
      $(id).value = query[field] ?? "";
      if ($(id).selectedIndex < 0) $(id).value = "";
    }
    const params = new URLSearchParams(Object.entries(filterScope()).filter(([, value]) => value));
    const url = params.size ? "/mapa?" + params : "/mapa";
    if (window.location.pathname + window.location.search !== url) history.replaceState(null, "", url);
  }

  function showEdgeChoices() {
    if (!view) return;
    const visible = [
      ...($("domestic").checked ? domesticSelection().visible : []),
      ...($("international").checked ? abroad : [])
    ];
    $("edge-picker").hidden = Boolean(view?.record) || !visible.length;
    if ($("edge-picker").hidden) return;
    const top = visible.sort((a, b) => b.volume_t - a.volume_t).slice(0, 20);
    if (selectedEdge && !top.some(edge => edge.key === selectedEdge.key)) top.push(selectedEdge);
    $("edge-choice").replaceChildren(new Option("Selecionar trecho", ""),
      ...top.map(edge => new Option(`${edge.from} → ${edge.to} · ${n(edge.volume_t)} t`, edge.key)));
    $("edge-choice").value = selectedEdge?.key || "";
  }

  function renderEdgePage(data) {
    const lastPage = Math.ceil(data.total / data.page_size);
    $("edge-status").textContent = "";
    $("edge-pages").hidden = lastPage <= 1;
    $("edge-prev").disabled = data.page <= 1;
    $("edge-next").disabled = data.page >= lastPage;
    $("edge-page").textContent = `${n(data.page)} de ${n(lastPage)}`;
    $("edge-records").replaceChildren(...data.records.map(record => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      const title = document.createElement("strong");
      title.textContent = `Registro ${n(record.record)} · ${record.year} · ${n(record.volume_t)} t`;
      const label = document.createElement("span");
      label.textContent = [record.origin, record.hub, record.exit, record.country]
        .map(point => point || "Sem informação").join(" → ");
      button.append(title, label);
      button.addEventListener("click", () => load({record: record.record}));
      li.append(button);
      return li;
    }));
  }

  function roadDescription(edge) {
    if (!edge.road) return edge.road_unavailable ? "Rota indisponível · ligação esquemática" : "Ligação esquemática";
    const refs = edge.road_refs || [];
    return ["Estimativa OSRM", Number.isFinite(edge.distance_km) && `${n(edge.distance_km)} km`,
      refs.length > 0 && refs.slice(0, 4).join(", ") + (refs.length > 4 ? "…" : ""),
      edge.has_ferry && "Inclui balsa"].filter(Boolean).join(" · ");
  }

  function renderEdgeRoad() {
    const edge = selectedEdge;
    $("edge-road-panel").hidden = !edge || edge.stage === "world";
    if ($("edge-road-panel").hidden) return;
    $("edge-road-status").textContent = roadDescription(edge);
    $("edge-estimate-road").hidden = edge.road;
    $("edge-estimate-road").disabled = false;
  }

  function renderRecordRoads() {
    $("record-roads").hidden = local.length === 0;
    $("record-road").replaceChildren(...local.map(edge => {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${stageLabels[edge.stage]} · ${edge.from} → ${edge.to}`;
      item.append(title, roadDescription(edge));
      return item;
    }));
    $("estimate-road").hidden = !local.some(edge => !edge.road);
    $("estimate-road").disabled = false;
  }

  function storeRoad(edge) {
    if (!edge.path) return;
    const {path, distance_km, road_refs, has_ferry} = edge;
    estimatedRoads.set(JSON.stringify([edge.stage, edge.from, edge.to]), {path, distance_km, road_refs, has_ferry});
    if (estimatedRoads.size > 64) estimatedRoads.delete(estimatedRoads.keys().next().value);
  }

  async function estimateRecordRoad() {
    const record = view?.record;
    if (!record || !local.some(edge => !edge.road)) return;
    roadRequest?.abort();
    const current = new AbortController();
    roadRequest = current;
    $("estimate-road").disabled = true;
    $("record-road-status").textContent = "Consultando o traçado pelas rodovias…";
    try {
      const data = await readJSON("/api/map/network", {record, road: "1"}, current.signal);
      if (current.signal.aborted || view?.record !== record) return;
      for (const edge of data.edges) storeRoad(edge);
      showNetwork(data);
      $("record-road-status").textContent = local.some(edge => !edge.road)
        ? "Os trechos sem rota disponível continuam tracejados." : "";
    } catch (error) {
      if (!current.signal.aborted) $("record-road-status").textContent = error.message;
    } finally {
      if (!current.signal.aborted) $("estimate-road").disabled = false;
    }
  }

  async function estimateSelectedRoad() {
    const edge = selectedEdge;
    if (!edge || edge.stage === "world" || edge.road) return;
    roadRequest?.abort();
    const current = new AbortController();
    roadRequest = current;
    $("edge-estimate-road").disabled = true;
    $("edge-road-status").textContent = "Consultando o traçado pelas rodovias…";
    try {
      const traced = await readJSON("/api/map/edge",
        {...scope, stage: edge.stage, from: edge.fromId, to: edge.toId, road: "1"}, current.signal);
      if (current.signal.aborted || selectedEdge?.key !== edge.key || view?.record) return;
      storeRoad(traced);
      prepareLayers(view);
      selectedEdge = local.find(item => item.key === edge.key);
      renderEdgeRoad();
      $("edge-summary").textContent = `${selectedEdge.description} · ${n(edge.volume_t)} t · ${n(edge.rows)} registros`;
      fitCoordinates(selectedEdge.path);
      draw();
    } catch (error) {
      if (!current.signal.aborted) $("edge-road-status").textContent = error.message;
    } finally {
      if (!current.signal.aborted) $("edge-estimate-road").disabled = false;
    }
  }

  async function selectEdge(edge, page = 1) {
    if (view?.record || !edge?.key) return;
    if (selectedEdge?.key !== edge.key) {
      roadRequest?.abort();
      selectedEdge = edge;
      edgePage = null;
      renderEdgeRoad();
    }
    $("edge-detail").hidden = false;
    $("edge-title").textContent = `${edge.from} → ${edge.to}`;
    $("edge-summary").textContent = `${edge.description} · ${n(edge.volume_t)} t · ${n(edge.rows)} registros`;
    $("edge-international-note").hidden = edge.stage !== "world";
    showEdgeChoices();
    draw();
    edgeRequest?.abort();
    const current = new AbortController();
    edgeRequest = current;
    $("edge-records").replaceChildren();
    $("edge-status").textContent = "Carregando registros do trecho…";
    $("edge-prev").disabled = true;
    $("edge-next").disabled = true;
    try {
      const data = await readJSON("/api/map/edge",
        {...scope, stage: edge.stage, from: edge.fromId, to: edge.toId, page}, current.signal);
      if (current.signal.aborted) return;
      edgePage = data;
      renderEdgePage(data);
    } catch (error) {
      if (!current.signal.aborted) $("edge-status").textContent = error.message;
    }
  }

  function closeEdge() {
    edgeRequest?.abort();
    roadRequest?.abort();
    selectedEdge = null;
    edgePage = null;
    $("edge-detail").hidden = true;
    $("edge-pages").hidden = true;
    showEdgeChoices();
    draw();
  }

  function showNetwork(data) {
    const changedRecord = data.record !== view?.record;
    if (data.record && view && !view.record) {
      networkCamera = cameraState();
    }
    if (changedRecord) {
      recordLink = false;
      $("record-detail").closest("aside").scrollTop = 0;
      $("record-road-status").textContent = "";
    }
    view = data;
    prepareLayers(data);
    const isRecord = Boolean(data.record);
    $("edge-detail").hidden = isRecord || !selectedEdge;
    showEdgeChoices();
    $("record-detail").hidden = !isRecord;
    $("fit-record").hidden = !isRecord;
    $("overview-controls").hidden = isRecord;
    if (isRecord) {
      $("record-title").textContent = `Registro ${n(data.record)} · ${data.year}`;
      $("record-volume").textContent = `${n(data.volume_t)} t · ${data.exporter || "Exportador sem identificação"}`;
      $("record-international-note").hidden = !data.nodes.some(key => key.length === 2);
      $("record-international").hidden = abroad.length === 0;
      updateRecordLink();
      renderRecordRoads();
      const labels = ["Município produtor", "Hub logístico", "Saída", "País de destino"];
      $("record-steps").replaceChildren(...data.steps.map((step, i) => {
        const item = document.createElement("li");
        item.textContent = `${labels[i]} · ${step.label || "Sem informação"}${step.located ? "" : " (sem posição no mapa)"}`;
        return item;
      }));
      $("mapped").textContent = data.edges.length ? "1" : "0";
      $("coverage").textContent = "";
      showStatus(local.length ? "Trechos no Brasil." : "Registro sem trecho localizável no Brasil.");
      fitRecord();
    } else {
      const counts = data.counts;
      $("mapped").textContent = n(counts.mapped);
      const total = counts.total || 0;
      $("coverage").textContent = total
        ? `${n(total - (counts.mapped || 0))} de ${n(total)} registros sem trecho localizável neste recorte.`
        : "Nenhum registro corresponde aos filtros.";
      const period = data.year || `${data.years[0]}–${data.years.at(-1)}`;
      showStatus(`Soja · ${period} · ${n(data.mapped_volume_t)} t em registros com trecho`);
    }
    $("edges").textContent = n(data.edges.length);
    draw();
    $("network-map").dataset.state = "ready";
  }

  async function load(query) {
    request?.abort();
    roadRequest?.abort();
    const current = new AbortController();
    request = current;
    showStatus("Carregando fluxos da Trase…");
    try {
      const data = await readJSON("/api/map/network", query, current.signal);
      if (current.signal.aborted) return;
      if (data.years) {
        closeEdge();
        scope = query;
        network = data;
        if ($("year").options.length === 1) {
          for (const year of data.years.slice().reverse()) $("year").add(new Option(year, year));
          $("record").max = data.record_count;
        }
        for (const [key, options] of Object.entries(data.filter_options || {})) {
          const select = $("filter-" + key);
          if (select.options.length === 1) {
            for (const [id, name] of options) select.add(new Option(name, id));
          }
        }
        syncFilters(query);
        if (Object.keys(query).some(field => field !== "year" && query[field])) {
          $("network-filters").querySelector("details").open = true;
        }
      }
      showNetwork(data);
      if (data.record) estimateRecordRoad();
    } catch (e) {
      if (!current.signal.aborted) showStatus(e.message || "Falha ao carregar os fluxos.", true);
    }
  }

  function init() {
    if (!window.deck || !window.maplibregl) throw new Error("As bibliotecas do mapa não carregaram.");
    dashedPaths = [new deck.PathStyleExtension({dash: true})];
    const flowAnimation = {
      name: "flowAnimation",
      fs: `uniform flowAnimationUniforms { float phase; } flowAnimation;`,
      uniformTypes: {phase: "f32"},
      inject: {
        "fs:DECKGL_FILTER_COLOR": `
          if (picking.isActive < 0.5) {
            float pulse = smoothstep(0.65, 1.0, 1.0 - abs(fract(geometry.uv.x * 3.0 - flowAnimation.phase * 4.0) - 0.5) * 2.0);
            color.a = mix(color.a * 0.55, 0.95, pulse);
          }
        `
      }
    };
    AnimatedArcLayer = class extends deck.ArcLayer {
      static layerName = "AnimatedTraseArcLayer";
      static defaultProps = {phase: 0};
      getShaders() {
        const shaders = super.getShaders();
        return {...shaders, modules: [...shaders.modules, flowAnimation]};
      }
      draw(options) {
        this.state.model.shaderInputs.setProps({flowAnimation: {phase: this.props.phase}});
        super.draw(options);
      }
    };
    map = new deck.DeckGL({
      container: $("network-map"), map: maplibregl,
      mapStyle: {
        version: 8,
        sources: {osm: {type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256,
          attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>'}},
        layers: [{id: "osm", type: "raster", source: "osm", paint: {"raster-saturation": -0.8, "raster-opacity": 0.75}}]
      },
      initialViewState: brazil,
      controller: {dragRotate: false, touchRotate: false},
      pickingRadius: 4,
      getTooltip: ({object}) => {
        if (!object) return null;
        return {text: object.name || [
          object.description, `${object.from} → ${object.to}`,
          `${n(object.volume_t)} t · ${n(object.rows)} registros`
        ].join("\n")};
      },
      onClick: ({object}) => { if (object?.key) selectEdge(object); },
      onError: error => {
        $("map-error").textContent = "O navegador não conseguiu desenhar uma camada do mapa.";
        $("map-error").hidden = false;
        console.error(error);
      }
    });
    for (const id of ["domestic", "domestic-stage", "international"]) $(id).addEventListener("change", () => {
      if (selectedEdge?.stage !== "world" && selectedEdge &&
          (!$("domestic").checked || !domesticSelection().visible.some(edge => edge.key === selectedEdge.key))) closeEdge();
      showEdgeChoices();
      draw();
    });
    $("brazil").addEventListener("click", () => setView(brazil));
    $("world").addEventListener("click", () => setView(world));
    $("fit-record").addEventListener("click", () => fitRecord());
    $("playback").addEventListener("click", () => changePlayback(!playing));
    $("year").addEventListener("change", () => load(filterScope()));
    $("network-filters").addEventListener("submit", event => {
      event.preventDefault();
      load(filterScope());
    });
    $("network-filters").addEventListener("reset", event => {
      event.preventDefault();
      for (const id of ["year", "filter-origin", "filter-exit", "filter-country"]) $(id).value = "";
      load(filterScope());
    });
    $("edge-choice").addEventListener("change", event => {
      const edge = local.find(item => item.key === event.target.value) || abroad.find(item => item.key === event.target.value);
      if (edge) selectEdge(edge);
      else closeEdge();
    });
    $("clear-edge").addEventListener("click", closeEdge);
    $("edge-prev").addEventListener("click", () => { if (edgePage) selectEdge(selectedEdge, edgePage.page - 1); });
    $("edge-next").addEventListener("click", () => { if (edgePage) selectEdge(selectedEdge, edgePage.page + 1); });
    $("record-international").addEventListener("click", () => {
      recordLink = !recordLink;
      updateRecordLink();
      fitRecord();
      draw();
    });
    $("find-record").addEventListener("submit", event => {
      event.preventDefault();
      load({record: $("record").value});
    });
    $("estimate-road").addEventListener("click", estimateRecordRoad);
    $("edge-estimate-road").addEventListener("click", estimateSelectedRoad);
    $("clear-record").addEventListener("click", () => {
      request?.abort();
      roadRequest?.abort();
      if (network) showNetwork(network);
      else load({year: $("year").value});
      setView(networkCamera || brazil);
    });
    changePlayback(playing);
    load(initialScope());
  }

  function updateRecordLink() {
    const button = $("record-international");
    button.textContent = recordLink ? "Ocultar ligação comercial" : "Ver ligação comercial";
    button.setAttribute("aria-pressed", String(recordLink));
  }

  try {
    init();
  } catch (error) {
    showStatus(error.message, true);
    $("map-error").textContent = error.message;
    $("map-error").hidden = false;
  }
})();

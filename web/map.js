"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const format = (n, digits = 0) => new Intl.NumberFormat("pt-BR", {maximumFractionDigits: digits}).format(n);
  const state = {dataset: null, flow: null, route: null, mode: "road", sequence: 0, viewport: null};
  const routeCache = new Map();
  let mapView;

  function status(text, isError = false) {
    $("status").textContent = text;
    $("status").classList.toggle("error", isError);
  }

  async function getJSON(url, signal) {
    const response = await fetch(url, {signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível carregar os dados.");
    return data;
  }

  function currentPath() {
    if (!state.flow) return [];
    return state.mode === "road"
      ? (state.route?.geometry.coordinates || [])
      : [state.flow.origin.coordinates, state.flow.destination.coordinates];
  }

  function fit() {
    const path = currentPath();
    if (!path.length || !mapView) return;
    const lon = path.map(p => p[0]);
    const lat = path.map(p => p[1]);
    const viewport = new deck.WebMercatorViewport({width: $("map").clientWidth, height: $("map").clientHeight})
      .fitBounds([[Math.min(...lon), Math.min(...lat)], [Math.max(...lon), Math.max(...lat)]], {padding: 80, maxZoom: 10});
    const next = {longitude: viewport.longitude, latitude: viewport.latitude, zoom: viewport.zoom, pitch: 0, bearing: 0};
    state.viewport = next;
    mapView.setProps({initialViewState: {...next, transitionDuration: 700, transitionInterpolator: new deck.FlyToInterpolator()}});
  }

  function draw() {
    if (!mapView || !state.flow) return;
    const path = currentPath();
    const points = [
      {...state.flow.origin, role: "Município produtor", color: [33, 134, 93]},
      {...state.flow.destination, role: "Hub logístico", color: [36, 119, 182]}
    ];
    const layers = [];
    if (path.length) {
      layers.push(new deck.PathLayer({
        id: "selected-route-outline", data: [{path}], getPath: d => d.path,
        getColor: [255, 255, 255, 230], getWidth: 8, widthUnits: "pixels", capRounded: true, jointRounded: true
      }));
      layers.push(new deck.PathLayer({
        id: "selected-route", data: [{path, role: state.mode === "road" ? "Percurso estimado" : "Ligação esquemática"}],
        getPath: d => d.path, getColor: state.mode === "road" ? [200, 93, 33] : [103, 115, 128],
        getWidth: 4, widthUnits: "pixels", capRounded: true, jointRounded: true, pickable: true,
        autoHighlight: true, highlightColor: [255, 173, 72, 180]
      }));
    }
    layers.push(new deck.ScatterplotLayer({
      id: "municipality-points", data: points, getPosition: d => d.coordinates,
      getFillColor: d => d.color, getRadius: 8, radiusUnits: "pixels", stroked: true,
      getLineColor: [255, 255, 255], lineWidthUnits: "pixels", getLineWidth: 2, pickable: true
    }));
    mapView.setProps({layers});
    $("map").dataset.state = path.length ? "ready" : "loading";
    const isRoad = state.mode === "road";
    $("map-mode").textContent = isRoad ? "PERCURSO ESTIMADO" : "LIGAÇÃO ESQUEMÁTICA";
    $("legend-path").textContent = isRoad ? "Trajeto estimado" : "Ligação direta";
    $("legend-line").style.background = isRoad ? "#c85d21" : "#677380";
    $("distance").textContent = isRoad && state.route ? `${format(state.route.distance_km, 1)} km` : "—";
    $("distance-note").textContent = isRoad ? "Percurso pela rede viária" : "Sem cálculo rodoviário";
    $("road-info").hidden = !isRoad || !state.route;
    $("road-refs").textContent = state.route?.road_refs.join(" · ") || "O roteador não informou referências das vias.";
    $("mode-road").setAttribute("aria-pressed", String(isRoad));
    $("mode-direct").setAttribute("aria-pressed", String(!isRoad));
    if (!isRoad) status("Ligação entre os pontos; não representa o caminho por estradas.");
    else if (state.route) status(state.route.has_ferry ? "Percurso estimado inclui travessia por balsa." : "Percurso estimado entre referências municipais.");
  }

  function list(id, entries) {
    $(id).replaceChildren(...entries.slice(0, 5).map(entry => {
      const li = document.createElement("li");
      li.textContent = `${entry.name} · ${format(entry.volume_t)} t`;
      return li;
    }));
    if (entries.length > 5) {
      const li = document.createElement("li");
      li.textContent = `Mais ${entries.length - 5} nesta seleção`;
      $(id).append(li);
    }
  }

  let pending;
  async function selectFlow() {
    const sequence = ++state.sequence;
    pending?.abort();
    pending = new AbortController();
    state.flow = state.dataset.flows.find(f => f.id === $("flow").value);
    state.route = null;
    $("origin").textContent = state.flow.origin.name;
    $("destination").textContent = state.flow.destination.name;
    $("volume").textContent = `${format(state.flow.volume_t)} t`;
    $("map-title").textContent = `${state.flow.origin.name} → ${state.flow.destination.name}`;
    $("route-source").textContent = "";
    list("exporters", state.flow.exporters);
    list("countries", state.flow.countries);
    draw();
    status("Carregando percurso estimado…");
    if (state.mode === "direct") {
      draw();
      fit();
    }
    try {
      const route = routeCache.get(state.flow.id) || await getJSON(`/api/map/route?id=${encodeURIComponent(state.flow.id)}`, pending.signal);
      if (sequence !== state.sequence) return;
      routeCache.set(state.flow.id, route);
      state.route = route;
      const date = new Date(route.calculated_at).toLocaleString("pt-BR", {timeZone: "America/Sao_Paulo"});
      $("route-source").textContent = `Trajeto calculado por ${route.provider} em ${date}. Perfil: ${route.profile}.`;
      draw();
      fit();
    } catch (error) {
      if (error.name === "AbortError" || sequence !== state.sequence) return;
      $("map").dataset.state = state.mode === "road" ? "route-error" : "ready";
      status(error.message, true);
    }
  }

  async function init() {
    if (!window.deck || !window.maplibregl) throw new Error("As bibliotecas do mapa não carregaram. Confira a conexão e recarregue a página.");
    mapView = new deck.DeckGL({
      container: $("map"), map: maplibregl,
      mapStyle: {
        version: 8,
        sources: {osm: {type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256,
          attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>'}},
        layers: [{id: "osm", type: "raster", source: "osm", paint: {"raster-saturation": -0.65, "raster-opacity": 0.85}}]
      },
      initialViewState: {longitude: -53, latitude: -13, zoom: 4, pitch: 0, bearing: 0},
      controller: {dragRotate: false, touchRotate: false},
      onViewStateChange: ({viewState}) => {state.viewport = viewState;},
      getTooltip: ({object}) => object && {text: object.name ? `${object.role}\n${object.name}\nCódigo municipal: ${object.code}` : object.role},
      onError: error => {
        $("map-warning").hidden = false;
        $("map-warning").textContent = "Não foi possível renderizar uma camada do mapa. Confira se WebGL está disponível no navegador.";
        $("map").dataset.state = "render-error";
        console.error(error);
      }
    });
    state.dataset = await getJSON("/api/map/flows");
    $("dataset-year").textContent = state.dataset.year;
    $("volume-note").textContent = `Agregado no ano de ${state.dataset.year}`;
    $("flow").replaceChildren(...state.dataset.flows.map(flow => {
      const option = document.createElement("option");
      option.value = flow.id;
      option.textContent = `${flow.origin.name} → ${flow.destination.name}`;
      return option;
    }));
    // Um fluxo longo da amostra deixa o trecho rodoviário mais fácil de explorar.
    const initial = state.dataset.flows.find(f => f.origin.name === "Sapezal" && f.destination.name === "Itaituba");
    if (initial) $("flow").value = initial.id;
    $("flow").disabled = false;
    $("sample-description").textContent = `${state.dataset.flows.length} fluxos selecionados · ${state.dataset.source}`;
    $("scope").textContent = state.dataset.scope;
    $("coordinate-source").href = state.dataset.coordinate_source;
    $("flow").addEventListener("change", selectFlow);
    $("fit").addEventListener("click", fit);
    for (const mode of ["road", "direct"]) $("mode-" + mode).addEventListener("click", () => {
      state.mode = mode;
      draw();
      if (mode === "road" && !state.route) status("Trajeto indisponível. Escolha novamente o fluxo para tentar carregar.", true);
      fit();
    });
    for (const [id, delta] of [["zoom-in", 1], ["zoom-out", -1]]) $(id).addEventListener("click", () => {
      const view = state.viewport || {longitude: -53, latitude: -13, zoom: 4};
      state.viewport = {...view, zoom: Math.max(2, Math.min(17, view.zoom + delta))};
      mapView.setProps({initialViewState: {...state.viewport, transitionDuration: 250}});
    });
    let resizeTimer;
    new ResizeObserver(() => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(fit, 150);
    }).observe($("map"));
    await selectFlow();
  }

  init().catch(error => {
    status(error.message, true);
    $("map-warning").textContent = error.message;
    $("map-warning").hidden = false;
    $("map").dataset.state = "error";
    console.error(error);
  });
})();

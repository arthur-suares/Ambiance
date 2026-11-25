"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 2});
  const brazil = {longitude: -54, latitude: -14, zoom: 3.2, pitch: 0, bearing: 0};
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let evidence, current, scenes, sceneId, deckMap, shapes, shapesPromise, timer, viewToken;
  let focusOptions = new Map();
  let lastFocus;

  function periodLabel(period) {
    const [year, month] = period.split("-");
    return month ? `${month}/${year}` : year;
  }

  function describeFact(fact, unit) {
    if (!fact) return "";
    const value = `${fmt.format(fact.value)} ${unit}`;
    if (fact.change_pct == null) return `${fact.title} · ${periodLabel(fact.period)} · ${value}`;
    const sign = fact.change_pct > 0 ? "+" : "";
    return `${fact.title} · ${periodLabel(fact.baseline_period)} a ${periodLabel(fact.period)} · ${sign}${fmt.format(fact.change_pct)}% (${fmt.format(fact.baseline_value)} → ${value})`;
  }

  function halt() {
    clearTimeout(timer);
    timer = null;
    $("timeline-play").textContent = "Reproduzir";
  }

  function hide() {
    viewToken = null;
    halt();
  }

  function setCamera(focus) {
    const animated = $("timeline-camera").checked && !motion.matches;
    const key = JSON.stringify([focus || null, animated]);
    if (lastFocus === key) return;
    lastFocus = key;
    let box = focus?.bbox;
    const state = shapes?.states.features.find(f => f.properties.uf === focus?.state);
    if (state) {
      const positions = state.geometry.coordinates.flat(Infinity);
      const lon = positions.filter((_, index) => index % 2 === 0);
      const lat = positions.filter((_, index) => index % 2 === 1);
      box = [Math.min(...lon), Math.min(...lat), Math.max(...lon), Math.max(...lat)];
    }
    const target = {...brazil};
    if (box) {
      if (box[0] === box[2] && box[1] === box[3]) {
        Object.assign(target, {longitude: box[0], latitude: box[1], zoom: 8.1, pitch: animated ? 30 : 0});
      } else {
        const el = $("timeline-map");
        const viewport = new deck.WebMercatorViewport({width: el.clientWidth || 600, height: el.clientHeight || 400})
          .fitBounds([[box[0], box[1]], [box[2], box[3]]], {padding: 36, maxZoom: 8});
        Object.assign(target, {longitude: viewport.longitude, latitude: viewport.latitude, zoom: viewport.zoom});
      }
    }
    deckMap.setProps({initialViewState: animated
      ? {...target, transitionDuration: 1000, transitionInterpolator: new deck.FlyToInterpolator()}
      : target});
  }

  function mapLayers(frame) {
    const cap = evidence.max || 1;
    const mode = $("timeline-mode").value;
    if (evidence.mode === "cells" && mode === "heatmap" && deck.HeatmapLayer) {
      return [new deck.HeatmapLayer({
        id: "timeline-heat", data: frame.cells, aggregation: "SUM", radiusPixels: 42,
        colorDomain: [0, cap], getPosition: d => d.position, getWeight: d => d.value ?? 0,
      })];
    }
    if (evidence.mode === "cells") {
      return [new deck.ScatterplotLayer({
        id: "timeline-cells", data: frame.cells.filter(d => d.value != null),
        getPosition: d => d.position, radiusUnits: "pixels", getRadius: d => 3 + 12 * Math.sqrt(d.value / cap),
        getFillColor: [223, 83, 42, 200], pickable: true,
      })];
    }
    if (evidence.mode === "arcs") {
      return [new deck.ArcLayer({
        id: "timeline-flows", data: frame.arcs, getSourcePosition: d => d.source,
        getTargetPosition: d => d.target, getSourceColor: [24, 126, 83, 205],
        getTargetColor: [19, 114, 166, 200], getWidth: d => 1 + 5 * Math.sqrt(d.volume_t / cap),
        widthUnits: "pixels", pickable: true,
      })];
    }
    const geography = evidence.grain === "state" ? shapes.states
      : AmbianceMap.municipalitiesIn(shapes.municipalities, shapes.states, evidence.uf);
    const values = new Map(frame.areas.map(d => [d.code, d.value]));
    return [new deck.GeoJsonLayer({
      id: "timeline-areas", data: geography, filled: true, stroked: true,
      lineWidthMinPixels: 0.75, getLineColor: [90, 112, 98, 170],
      getFillColor: f => {
        const value = values.get(String(f.properties.uf || f.properties.codarea));
        if (value == null) return [210, 220, 216, 40];
        const intensity = Math.sqrt(Math.max(0, value / cap));
        return [Math.round(191 - 160 * intensity), Math.round(240 - 125 * intensity), 96, 215];
      },
      updateTriggers: {getFillColor: [evidence, frame]}, pickable: true,
    })];
  }

  function paint(manualScene) {
    if (!evidence) return;
    const frame = evidence.frames[current];
    const scene = manualScene || scenes.find(s => s.period === frame.period);
    sceneId = scene?.id;
    const label = periodLabel(frame.period);
    $("timeline-position").value = String(current);
    $("timeline-position").setAttribute("aria-valuetext", label);
    $("timeline-story-title").textContent = scene?.title || label;
    $("timeline-value").textContent = frame.value == null
      ? `${label} · ${evidence.scope} · Sem dados neste recorte`
      : `${label} · ${evidence.scope} · ${fmt.format(frame.value)} ${evidence.unit}`;
    const frameScenes = manualScene ? [manualScene] : scenes.filter(s => s.period === frame.period);
    const caption = frameScenes.flatMap(s => [
      describeFact(evidence.facts.find(f => f.id === s.factId), evidence.unit),
      s.text ? `Anotação: ${s.text}` : "",
    ]);
    if (frame.coverage_through) caption.push(`Último registro em ${frame.coverage_through.split("-").reverse().join("/")}.`);
    $("timeline-caption").textContent = caption.filter(Boolean).join("\n");
    $("timeline-evidence").dataset.period = frame.period;
    $("timeline-explore").textContent = frame.period.includes("-") ? "Explorar o ano no mapa" : "Explorar este período";
    document.dispatchEvent(new CustomEvent("ambiance:period", {detail: frame.period}));
    $("timeline-milestones").querySelectorAll("button").forEach(btn => {
      btn.setAttribute("aria-current", String(btn.dataset.id === sceneId));
    });
    if (deckMap && shapes && !$("panel-timeline").hidden) {
      setCamera(focusOptions.get(scene?.focus) || evidence.focus);
      deckMap.setProps({layers: frame.value == null ? [] : mapLayers(frame)});
    }
  }

  function jump(index, scene) {
    current = Math.min(Math.max(index, 0), evidence.frames.length - 1);
    paint(scene);
  }

  function renderScenes() {
    const buttons = [];
    const editors = [];
    for (const [index, scene] of scenes.entries()) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.id = scene.id;
      button.textContent = `${periodLabel(scene.period)} · ${scene.title}`;
      button.addEventListener("click", () => {
        halt();
        jump(evidence.frames.findIndex(f => f.period === scene.period), scene);
      });
      buttons.push(button);
      const card = document.createElement("article");
      const heading = document.createElement("strong");
      heading.textContent = button.textContent;
      card.append(heading);
      function field(text, el) {
        const label = document.createElement("label");
        label.textContent = text;
        label.append(el);
        card.append(label);
      }
      const title = document.createElement("input");
      title.value = scene.title;
      title.maxLength = 100;
      title.addEventListener("change", () => { scene.title = title.value.trim() || "Marco"; renderScenes(); });
      field("Título", title);
      const note = document.createElement("input");
      note.value = scene.text || "";
      note.maxLength = 400;
      note.addEventListener("change", () => { scene.text = note.value; paint(scene.id === sceneId ? scene : null); });
      field("Anotação", note);
      const focus = document.createElement("select");
      focus.add(new Option("Recorte geral", ""));
      for (const [key, option] of focusOptions) focus.add(new Option(option.name, key));
      focus.value = scene.focus || "";
      focus.addEventListener("change", () => { scene.focus = focus.value; if (scene.id === sceneId) paint(scene); });
      field("Foco da câmera", focus);
      const duration = document.createElement("input");
      duration.type = "number"; duration.min = 1; duration.max = 15; duration.value = scene.seconds || 3;
      duration.addEventListener("change", () => {
        scene.seconds = Math.min(15, Math.max(1, Number(duration.value) || 3));
        duration.value = scene.seconds;
      });
      field("Duração em segundos", duration);
      for (const [name, step] of [["Subir marco", -1], ["Descer marco", 1], ["Remover marco", 0]]) {
        const action = document.createElement("button");
        action.type = "button"; action.textContent = name;
        action.disabled = step !== 0 && !scenes[index + step];
        action.addEventListener("click", () => {
          if (!step) scenes.splice(index, 1);
          else [scenes[index], scenes[index + step]] = [scenes[index + step], scenes[index]];
          renderScenes();
        });
        card.append(action);
      }
      editors.push(card);
    }
    $("timeline-milestones").replaceChildren(...buttons);
    $("timeline-edits").replaceChildren(...editors);
    paint(scenes.find(s => s.id === sceneId && s.period === evidence.frames[current]?.period));
  }

  function setEvidence(data) {
    hide();
    evidence = data;
    current = 0;
    sceneId = null;
    lastFocus = undefined;
    $("timeline-player").hidden = !data;
    if (!data) return;
    focusOptions = new Map();
    if (data.uf) focusOptions.set(data.uf, {name: data.uf, state: data.uf});
    for (const frame of data.frames) {
      for (const item of frame.areas || []) {
        if (item.lon != null && item.lat != null && !focusOptions.has(item.code)) {
          focusOptions.set(item.code, {name: item.name, state: item.code.length === 2 ? item.code : null,
                                      bbox: [item.lon, item.lat, item.lon, item.lat]});
        }
      }
      for (const arc of frame.arcs || []) {
        const [lon, lat] = arc.source;
        if (!focusOptions.has(arc.origin_code)) focusOptions.set(arc.origin_code, {
          name: arc.origin_name, state: arc.origin_code.length === 2 ? arc.origin_code : null,
          bbox: [lon, lat, lon, lat],
        });
      }
    }
    const facts = data.facts.filter(f => !data.milestones || data.milestones.includes(f.id));
    scenes = data.editedScenes ||= facts.map(f => ({
      id: f.id, factId: f.id, period: f.period, title: f.title, seconds: 3, focus: "", text: "",
    }));
    $("timeline-position").max = String(data.frames.length - 1);
    $("timeline-play").disabled = !data.frames.some(frame => frame.value != null);
    $("timeline-method").href = data.method_url;
    const options = data.mode === "cells" ? [["heatmap", "Mapa de calor"], ["cells", "Células"]]
      : [[data.mode, data.mode === "arcs" ? "Arcos comerciais" : "Áreas coloridas"]];
    $("timeline-mode").replaceChildren(...options.map(([value, label]) => new Option(label, value)));
    $("timeline-legend").textContent = data.mode === "cells"
      ? `${data.label} · agregação em células de ${data.grid_degrees}° · escala fixa · ${data.source}`
      : `${data.label} · escala fixa em ${data.unit} no período · ${data.source}`;
    renderScenes();
  }

  async function show() {
    if (!evidence) return;
    const token = viewToken = {};
    if (!shapesPromise) {
      shapesPromise = Promise.all([
        AmbianceMap.loadStates(),
        fetch("/api/agro/geojson").then(res => {
          if (!res.ok) throw new Error("Limites municipais indisponíveis.");
          return res.json();
        }),
      ]).then(([states, municipalities]) => ({states, municipalities})).catch(error => {
        shapesPromise = null;
        throw error;
      });
    }
    try {
      shapes = await shapesPromise;
      if (token !== viewToken || $("panel-timeline").hidden) return;
      if (!deckMap) {
        deckMap = new deck.DeckGL({
          container: "timeline-map", mapLib: maplibregl,
          mapStyle: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
          initialViewState: brazil, controller: true,
          getTooltip: info => {
            const item = info.object;
            if (!item) return null;
            if (item.origin_name) return `${item.origin_name} → ${item.target_name}\n${fmt.format(item.volume_t)} t`;
            const code = String(item.properties?.uf || item.properties?.codarea || "");
            const area = evidence.frames[current].areas?.find(d => d.code === code);
            return area ? `${area.name}\n${fmt.format(area.value)} ${evidence.unit}`
              : item.value == null ? null : `${fmt.format(item.value)} ${evidence.unit} nesta célula`;
          },
        });
      }
      window.dispatchEvent(new Event("resize"));
      paint();
    } catch (error) {
      $("timeline-status").textContent = error.message;
    }
  }

  function play() {
    if (!evidence?.frames.some(frame => frame.value != null)) return;
    if (timer != null) { halt(); return; }
    const editedOrder = $("timeline-order").value === "scenes";
    const queue = editedOrder
      ? scenes.map(s => ({scene: s, index: evidence.frames.findIndex(f => f.period === s.period)}))
      : evidence.frames.map((frame, index) => ({index})).filter(({index}) => evidence.frames[index].value != null);
    if (!queue.length) return;
    let cursor = editedOrder ? 0 : Math.max(0, queue.findIndex(item => item.index >= current));
    if (cursor === queue.length - 1) cursor = 0;
    $("timeline-play").textContent = "Pausar";
    const step = () => {
      const {index, scene} = queue[cursor++];
      jump(index, scene);
      const seconds = scene?.seconds || scenes.find(s => s.id === sceneId)?.seconds || 1.2;
      timer = setTimeout(cursor === queue.length ? halt : step, seconds * 1000);
    };
    step();
  }

  function init() {
    $("timeline-play").addEventListener("click", play);
    $("timeline-prev").addEventListener("click", () => { halt(); jump(current - 1); });
    $("timeline-next").addEventListener("click", () => { halt(); jump(current + 1); });
    $("timeline-position").addEventListener("input", event => { halt(); jump(Number(event.target.value)); });
    $("timeline-mode").addEventListener("change", () => paint());
    $("timeline-camera").addEventListener("change", () => paint());
    $("timeline-order").addEventListener("change", halt);
    $("timeline-add").addEventListener("click", () => {
      const scene = {id: "custom-" + Date.now(), title: "Marco", period: evidence.frames[current].period, seconds: 3};
      scenes.push(scene);
      renderScenes();
      paint(scene);
    });
    $("timeline-camera").checked = !motion.matches;
  }

  function goTo(period) {
    if (!evidence) return;
    const index = evidence.frames.findIndex(f => f.period === period);
    if (index >= 0) { halt(); jump(index); }
  }

  const getPeriod = () => evidence?.frames[current]?.period;
  window.AmbianceTimeline = {init, setEvidence, show, hide, describeFact, goTo, getPeriod};
})();

"use strict";

(() => {
  const icons = {};
  for (const chain of ["soja", "bovinos"]) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 64;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = chain === "soja" ? "#fff5d5" : "#e4f6ee";
    ctx.strokeStyle = chain === "soja" ? "#a16207" : "#176c54";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(32, 32, 28, 0, 2 * Math.PI);
    ctx.fill();
    ctx.stroke();
    if (chain === "soja") {
      ctx.save();
      ctx.translate(32, 32);
      ctx.rotate(-0.65);
      ctx.fillStyle = "#578325";
      ctx.beginPath();
      ctx.ellipse(0, 0, 22, 12, 0, 0, 2 * Math.PI);
      ctx.fill();
      for (const x of [-12, 0, 12]) {
        ctx.fillStyle = "#e9efae";
        ctx.beginPath();
        ctx.arc(x, 0, 4.4, 0, 2 * Math.PI);
        ctx.fill();
      }
      ctx.restore();
    } else {
      ctx.font = '38px "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif';
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("🐄", 32, 32);
    }
    icons[chain] = {url: canvas.toDataURL(), width: 64, height: 64};
  }

  let statesRequest;
  const municipalityScopes = new WeakMap();
  function loadStates() {
    if (!statesRequest) {
      statesRequest = fetch("/api/agro/states").then(res => {
        if (!res.ok) throw new Error("Limites dos estados indisponíveis.");
        return res.json();
      }).catch(error => {
        statesRequest = null;
        throw error;
      });
    }
    return statesRequest;
  }

  function municipalitiesIn(geojson, states, uf) {
    const prefix = states?.features.find(f => f.properties.uf === uf)?.properties.prefix;
    if (!prefix) return geojson;
    if (!municipalityScopes.has(geojson)) municipalityScopes.set(geojson, new Map());
    const scopes = municipalityScopes.get(geojson);
    if (!scopes.has(prefix)) {
      scopes.set(prefix, {...geojson, features: geojson.features.filter(f => String(f.properties.codarea).startsWith(prefix))});
    }
    return scopes.get(prefix);
  }

  function facilityLayer(data, extensions, onHover, onStateClick) {
    const byState = data.grain === "state";
    return new deck.IconLayer({
      id: "facilities",
      data: data.points,
      pickable: true,
      getIcon: point => icons[point.cadeia] || icons.bovinos,
      getPosition: point => [point.lon, point.lat],
      getSize: byState ? 23 : 18,
      sizeUnits: "pixels",
      extensions,
      onHover,
      onClick: info => {
        if (byState && info.object?.uf) onStateClick(info.object.uf);
      },
    });
  }

  let comparisonDialog;
  let comparisonRequest;
  async function compareAlert(point) {
    if (!point?.view_date) return;
    if (!comparisonDialog) {
      comparisonDialog = document.createElement("dialog");
      comparisonDialog.className = "satellite-dialog";
      comparisonDialog.setAttribute("aria-labelledby", "satellite-title");
      comparisonDialog.innerHTML = `
        <form method="dialog"><button type="submit">Fechar</button></form>
        <h2 id="satellite-title">Antes e depois do alerta</h2>
        <p class="satellite-place"></p>
        <p class="satellite-status" role="status"></p>
        <div class="satellite-images"></div>
        <p class="satellite-method" hidden>O centro das duas imagens marca o ponto do alerta do INPE. O percentual de nuvens se refere à cena inteira. <a href="/metodologia#copernicus">Metodologia</a></p>
        <p><a class="satellite-radar" target="_blank" rel="noopener" hidden>Consultar cenas de radar Sentinel-1 no catálogo</a></p>`;
      comparisonDialog.addEventListener("close", () => comparisonRequest?.abort());
      document.body.append(comparisonDialog);
    }
    comparisonRequest?.abort();
    const request = new AbortController();
    comparisonRequest = request;
    const status = comparisonDialog.querySelector(".satellite-status");
    const images = comparisonDialog.querySelector(".satellite-images");
    const method = comparisonDialog.querySelector(".satellite-method");
    const radar = comparisonDialog.querySelector(".satellite-radar");
    const place = [point.municipio, point.uf].filter(Boolean).join(" · ") || point.bioma;
    comparisonDialog.querySelector(".satellite-place").textContent =
      `${place ? place + " · " : ""}Observação DETER em ${point.view_date.split("-").reverse().join("/")}`;
    images.replaceChildren();
    method.hidden = true;
    radar.hidden = true;
    status.textContent = "Procurando imagens Sentinel-2…";
    if (!comparisonDialog.open) comparisonDialog.showModal();
    const qs = new URLSearchParams({lon: point.lon, lat: point.lat, date: point.view_date});
    try {
      const res = await fetch(`/api/agro/satellite?${qs}`, {signal: request.signal});
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || "Não foi possível consultar o catálogo.");
      if (request.signal.aborted) return;
      status.textContent = `Sentinel-2 em cores naturais · busca de até ${result.window_days} dias em cada direção`;
      method.hidden = false;
      radar.href = result.radar_catalog;
      radar.hidden = false;
      for (const [key, label] of [["before", "Antes"], ["after", "Depois"]]) {
        const card = document.createElement("figure");
        const caption = document.createElement("figcaption");
        const scene = result.scenes[key];
        if (!scene) {
          caption.textContent = `${label} · sem imagem para este recorte no período`;
          card.append(caption);
        } else {
          const date = scene.date.split("-").reverse().join("/");
          const source = document.createElement("a");
          source.href = scene.source;
          source.target = "_blank";
          source.rel = "noopener";
          source.textContent = "Ficha da cena";
          const credit = document.createElement("small");
          credit.className = "satellite-credit";
          credit.textContent = `Contains modified Copernicus Sentinel data ${scene.date.slice(0, 4)}`;
          caption.append(`${label} · ${date} · ${scene.cloud == null ? "nuvens sem estimativa" : Math.round(scene.cloud) + "% de nuvens na cena"} · `, source, credit);
          const frame = document.createElement("div");
          frame.className = "satellite-frame";
          const image = document.createElement("img");
          image.alt = `Imagem Sentinel-2 de ${date}, centrada no ponto do alerta`;
          image.src = `/api/agro/satellite-image?${qs}&side=${key}&scene=${encodeURIComponent(scene.id)}`;
          image.addEventListener("error", () => {
            const error = document.createElement("p");
            error.textContent = "Imagem indisponível para este trecho.";
            frame.replaceWith(error);
          }, {once: true});
          frame.append(image);
          card.append(frame, caption);
        }
        images.append(card);
      }
    } catch (error) {
      if (!request.signal.aborted) status.textContent = error.message;
    }
  }

  window.AmbianceMap = {facilityLayer, loadStates, municipalitiesIn, compareAlert};
})();

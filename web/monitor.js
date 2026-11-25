"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const fmtInt = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 0});
  const fmtPct = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 1});
  const fmtSec = new Intl.NumberFormat("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const fmtUsd = new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 5});
  const fmtTime = new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  const ROLE_COLORS = {
    system: "#7c3aed",
    user: "#0f766e",
    assistant: "#2563eb",
    tool: "#d97706",
  };
  const ROLE_LABELS = {
    system: "System",
    user: "User",
    assistant: "Assistant",
    tool: "Tool",
  };

  const state = {
    payload: null,
    activeTab: "traces",
    stage: "",
    traceId: "",
    status: "all",
    loading: false,
    lastUpdated: null,
    drawer: {
      open: false,
      traceId: "",
      detail: null,
      selectedObsId: "",
      obsSubTab: "prompt",
      promptSearch: "",
      promptRole: "all",
      promptMsgIdx: 0,
      promptRaw: false,
    },
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatTimestamp(iso) {
    if (!iso) return "—";
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return iso;
    return fmtTime.format(dt);
  }

  function formatTokens(val) {
    return fmtInt.format(Number(val || 0));
  }

  function formatDurationMs(ms, secFallback = 0) {
    if (ms !== undefined && ms !== null && Number.isFinite(Number(ms))) {
      const numericMs = Number(ms);
      if (numericMs < 1000) return `${Math.round(numericMs)} ms`;
      return `${fmtSec.format(numericMs / 1000)} s`;
    }
    const s = Number(secFallback || 0);
    if (s > 0 && s < 1) return `${Math.round(s * 1000)} ms`;
    return `${fmtSec.format(s)} s`;
  }

  function formatJson(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  function copyButton(getText, label = "Copiar") {
    const btn = el("button", "monitor-btn monitor-btn-sm", label);
    btn.type = "button";
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(String(getText() || ""));
        btn.textContent = "Copiado ✓";
        setTimeout(() => { btn.textContent = label; }, 1400);
      } catch {
        btn.textContent = "Erro";
        setTimeout(() => { btn.textContent = label; }, 1400);
      }
    });
    return btn;
  }

  function langfuseTraceUrl(summary, traceId) {
    const base = (summary?.langfuse_url || "").trim().replace(/\/+$/, "");
    if (!base || !traceId || traceId === "(sem-trace)") return "";
    const project = encodeURIComponent((summary?.langfuse_project_id || "ambiance-agro").trim() || "ambiance-agro");
    return `${base}/project/${project}/traces/${encodeURIComponent(traceId)}`;
  }

  function langfuseProjectUrl(summary) {
    const base = (summary?.langfuse_url || "").trim().replace(/\/+$/, "");
    if (!base) return "";
    const project = encodeURIComponent((summary?.langfuse_project_id || "ambiance-agro").trim() || "ambiance-agro");
    return `${base}/project/${project}/traces`;
  }

  function buildTable(headers, rows, emptyText) {
    if (!rows.length) {
      return el("p", "monitor-empty", emptyText);
    }
    const table = el("table", "monitor-table");
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const h of headers) {
      headRow.append(el("th", h.num ? "num" : "", h.label));
    }
    thead.append(headRow);
    const tbody = document.createElement("tbody");
    for (const row of rows) tbody.append(row);
    table.append(thead, tbody);
    return table;
  }

  function switchTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll(".monitor-tab").forEach(btn => {
      const on = btn.dataset.monitorTab === tabName;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", String(on));
    });
    $("monitor-tab-traces").hidden = tabName !== "traces";
    $("monitor-tab-sessions").hidden = tabName !== "sessions";
    $("monitor-tab-generations").hidden = tabName !== "generations";
  }

  function renderHeader(summary, events) {
    const badge = $("monitor-lf-badge");
    const link = $("monitor-lf-link");
    const lfUrl = langfuseProjectUrl(summary);

    if (summary?.langfuse_configured && lfUrl) {
      badge.textContent = "Langfuse conectado";
      badge.className = "monitor-badge is-connected";
      link.href = lfUrl;
      link.hidden = false;
    } else {
      badge.textContent = "Log local ativo";
      badge.className = "monitor-badge is-local";
      link.hidden = true;
    }

    const updated = state.lastUpdated ? fmtTime.format(state.lastUpdated) : "—";
    $("monitor-status").textContent =
      `Atualizado às ${updated} · ${fmtInt.format(events.length)} chamada(s) · Clique em qualquer trace para auditar.`;
  }

  function renderKpis(summary) {
    const container = $("monitor-kpis");
    container.replaceChildren();
    const totals = summary?.totals || {};
    const calls = Number(totals.calls || 0);
    const errors = Number(totals.error_calls || 0);
    const inTok = Number(totals.input_tokens || 0);
    const outTok = Number(totals.output_tokens || 0);
    const cacheRead = Number(totals.cache_read_tokens || 0);
    const cacheWrite = Number(totals.cache_creation_tokens || 0);
    const totalTok = Number(totals.total_tokens || 0);
    const costUsd = Number(totals.estimated_cost_usd || 0);
    const seconds = Number(totals.seconds || 0);
    const traceCount = Object.keys(summary?.by_trace || {}).length;
    const sessionCount = Object.keys(summary?.by_session || {}).filter(k => k !== "(sem-sessão)").length;

    const promptBase = inTok + cacheRead + cacheWrite;
    const cachePct = promptBase > 0 ? (cacheRead / promptBase) * 100 : 0;
    const avgSec = calls > 0 ? seconds / calls : 0;
    const avgCalls = traceCount > 0 ? calls / traceCount : 0;

    const cards = [
      {
        label: "Chamadas LLM",
        value: formatTokens(calls),
        sub: errors > 0 ? `${formatTokens(errors)} com erro` : `${formatTokens(totals.ok_calls || 0)} com sucesso`,
      },
      {
        label: "Tokens totais",
        value: formatTokens(totalTok),
        sub: `In ${formatTokens(inTok)} · Out ${formatTokens(outTok)} · ${fmtUsd.format(costUsd)}`,
      },
      {
        label: "Leitura de cache",
        value: formatTokens(cacheRead),
        sub: `${fmtPct.format(cachePct)}% do contexto reutilizado`,
      },
      {
        label: "Latência acumulada",
        value: `${fmtSec.format(seconds)} s`,
        sub: `Média de ${fmtSec.format(avgSec)} s por chamada`,
      },
      {
        label: "Traces / Sessões",
        value: `${formatTokens(traceCount)} / ${formatTokens(sessionCount)}`,
        sub: `Média de ${fmtPct.format(avgCalls)} chamada(s) por trace`,
      },
    ];

    for (const card of cards) {
      const box = document.createElement("div");
      box.append(el("small", "", card.label), el("strong", "", card.value), el("small", "", card.sub));
      container.append(box);
    }
  }

  function renderHistogram(summary) {
    const container = $("monitor-histogram");
    const entries = Object.entries(summary?.by_trace || {})
      .sort((a, b) => String(a[1].last_timestamp || "").localeCompare(String(b[1].last_timestamp || "")))
      .slice(-24);

    if (!entries.length) {
      container.replaceChildren(el("p", "monitor-empty", "Sem traces suficientes para exibir o gráfico de atividade."));
      return;
    }

    const maxTok = entries.reduce((m, [, b]) => Math.max(m, b.total_tokens || 0), 0) || 1;
    const barsWrap = el("div", "monitor-hist-bars");
    for (const [tid, bucket] of entries) {
      const col = el("button", "monitor-hist-col");
      col.type = "button";
      const pct = Math.max(8, Math.round(((bucket.total_tokens || 0) / maxTok) * 100));
      const bar = el("span", `monitor-hist-bar${bucket.ok === false ? " is-error" : ""}`);
      bar.style.height = `${pct}%`;
      const shortLabel = formatTimestamp(bucket.last_timestamp).split(", ")[1] || tid.slice(0, 6);
      col.title = `${tid}\n${bucket.question || bucket.route || ""}\n${formatTokens(bucket.total_tokens)} tokens · ${fmtSec.format(bucket.seconds || 0)} s`;
      col.append(bar, el("small", "monitor-hist-lbl", shortLabel));
      col.addEventListener("click", () => openTraceDrawer(tid));
      barsWrap.append(col);
    }
    container.replaceChildren(barsWrap);
  }

  function renderStages(summary) {
    const container = $("monitor-stages");
    const entries = Object.entries(summary?.by_stage || {}).sort(
      (a, b) => (b[1].total_tokens || 0) - (a[1].total_tokens || 0)
    );
    const maxTokens = entries.reduce((mx, [, bucket]) => Math.max(mx, bucket.total_tokens || 0), 0) || 1;

    const rows = entries.map(([stageName, bucket]) => {
      const tr = document.createElement("tr");
      tr.className = "monitor-row-interactive";
      if (state.stage === stageName) tr.classList.add("is-selected");
      tr.title = "Clique para filtrar Generations por esta etapa";
      tr.addEventListener("click", () => {
        state.stage = stageName;
        syncFilterControls();
        renderFilteredSections();
        switchTab("generations");
      });

      const stageCell = document.createElement("td");
      stageCell.append(el("code", "monitor-code", stageName));

      const barCell = document.createElement("td", "num");
      const wrap = document.createElement("div", "monitor-token-bar");
      wrap.append(el("span", "", formatTokens(bucket.total_tokens)));
      const track = el("div", "monitor-bar");
      const fill = el("div", "monitor-bar-fill");
      fill.style.width = `${Math.max(3, Math.round(((bucket.total_tokens || 0) / maxTokens) * 100))}%`;
      track.append(fill);
      wrap.append(track);
      barCell.append(wrap);

      tr.append(
        stageCell,
        el("td", "num", formatTokens(bucket.calls)),
        el("td", "num", formatTokens(bucket.input_tokens)),
        el("td", "num", formatTokens(bucket.cache_read_tokens)),
        el("td", "num", formatTokens(bucket.output_tokens)),
        barCell,
        el("td", "num nowrap", `${fmtSec.format(bucket.seconds || 0)} s`)
      );
      return tr;
    });

    const table = buildTable(
      [
        {label: "Etapa"},
        {label: "Chamadas", num: true},
        {label: "Entrada", num: true},
        {label: "Cache Hit", num: true},
        {label: "Saída", num: true},
        {label: "Total Tokens", num: true},
        {label: "Tempo", num: true},
      ],
      rows,
      "Nenhuma chamada registrada ainda."
    );
    container.replaceChildren(table);
  }

  function renderTraces(summary) {
    const container = $("monitor-traces");
    const entries = Object.entries(summary?.by_trace || {}).sort((a, b) =>
      String(b[1].last_timestamp || "").localeCompare(String(a[1].last_timestamp || ""))
    );

    const rows = entries.map(([tid, bucket]) => {
      const tr = document.createElement("tr");
      tr.className = "monitor-row-interactive";
      if (state.drawer.open && state.drawer.traceId === tid) tr.classList.add("is-selected");
      tr.title = "Clique para abrir auditoria detalhada (Waterfall, Spans e Prompt)";
      tr.addEventListener("click", event => {
        if (event.target.closest("a, button")) return;
        openTraceDrawer(tid);
      });

      const traceCell = document.createElement("td");
      const traceWrap = el("div", "monitor-trace-cell");
      const traceCode = el("code", "monitor-code monitor-trace-id", tid);
      traceCode.title = tid;
      traceWrap.append(traceCode);
      if (bucket.question) {
        const qPreview = el("small", "monitor-q-preview", bucket.question);
        qPreview.title = bucket.question;
        traceWrap.append(qPreview);
      }
      traceCell.append(traceWrap);

      const obsCell = document.createElement("td");
      const obsChips = el("div", "monitor-chips");
      if (bucket.span_count) obsChips.append(el("span", "monitor-chip obs-chip-span", `${bucket.span_count} span`));
      obsChips.append(el("span", "monitor-chip obs-chip-gen", `${bucket.generation_count || bucket.calls} gen`));
      if (bucket.event_count) obsChips.append(el("span", "monitor-chip obs-chip-event", `${bucket.event_count} ev`));
      obsCell.append(obsChips);

      const statusCell = document.createElement("td");
      const ok = bucket.ok !== false && Number(bucket.error_calls || 0) === 0;
      statusCell.append(
        el("span", ok ? "monitor-status-ok" : "monitor-status-err", ok ? "OK" : `${bucket.error_calls} erro(s)`)
      );

      const actionCell = document.createElement("td");
      const actionWrap = el("div", "monitor-row-actions");
      const auditBtn = el("button", "monitor-btn monitor-btn-sm", "Auditar");
      auditBtn.type = "button";
      auditBtn.addEventListener("click", () => openTraceDrawer(tid));
      actionWrap.append(auditBtn);
      const traceHref = langfuseTraceUrl(summary, tid);
      if (traceHref) {
        const a = el("a", "monitor-ext-link", "LF ↗");
        a.href = traceHref;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.title = "Abrir trace no Langfuse";
        actionWrap.append(a);
      }
      actionCell.append(actionWrap);

      tr.append(
        el("td", "nowrap", formatTimestamp(bucket.last_timestamp || bucket.first_timestamp)),
        traceCell,
        el("td", "nowrap", bucket.name || bucket.route || "—"),
        obsCell,
        el("td", "num", formatTokens(bucket.input_tokens)),
        el("td", "num", formatTokens(bucket.cache_read_tokens)),
        el("td", "num", formatTokens(bucket.output_tokens)),
        el("td", "num", formatTokens(bucket.total_tokens)),
        el("td", "num nowrap", fmtUsd.format(bucket.estimated_cost_usd || 0)),
        el("td", "num nowrap", `${fmtSec.format(bucket.seconds || 0)} s`),
        statusCell,
        actionCell
      );
      return tr;
    });

    const table = buildTable(
      [
        {label: "Horário"},
        {label: "Trace / Pergunta"},
        {label: "Tipo"},
        {label: "Observations"},
        {label: "Entrada", num: true},
        {label: "Cache", num: true},
        {label: "Saída", num: true},
        {label: "Total", num: true},
        {label: "Custo est.", num: true},
        {label: "Tempo", num: true},
        {label: "Status"},
        {label: "Auditar"},
      ],
      rows,
      "Nenhuma requisição rastreada até o momento."
    );
    container.replaceChildren(table);
  }

  function renderSessions(summary) {
    const container = $("monitor-sessions");
    const sessions = Object.values(summary?.by_session || {}).sort((a, b) =>
      String(b.last_timestamp || "").localeCompare(String(a.last_timestamp || ""))
    );

    if (!sessions.length) {
      container.replaceChildren(el("p", "monitor-empty", "Nenhuma sessão agrupada encontrada."));
      return;
    }

    const cards = sessions.map(sess => {
      const card = el("article", "session-card");
      const head = el("div", "session-card-head");
      const left = el("div");
      left.append(
        el("code", "monitor-code", sess.session_id),
        el("h3", "session-question", sess.first_question || "Conversa sem texto inicial capturado")
      );
      const stats = el("div", "session-stats");
      const promptBase = (sess.input_tokens || 0) + (sess.cache_read_tokens || 0);
      const cachePct = promptBase > 0 ? ((sess.cache_read_tokens || 0) / promptBase) * 100 : 0;
      for (const pillTxt of [
        `${formatTokens(sess.trace_count)} trace(s)`,
        `${formatTokens(sess.calls)} chamada(s)`,
        `${formatTokens(sess.total_tokens)} tok`,
        `Cache ${fmtPct.format(cachePct)}%`,
        fmtUsd.format(sess.estimated_cost_usd || 0),
        `${fmtSec.format(sess.seconds || 0)} s`,
      ]) {
        stats.append(el("span", "monitor-chip", pillTxt));
      }
      head.append(left, stats);
      card.append(head);

      const list = el("div", "session-trace-list");
      const byTrace = summary?.by_trace || {};
      const orderedIds = [...(sess.trace_ids || [])].reverse();
      for (const tid of orderedIds) {
        const tb = byTrace[tid] || {};
        const item = el("button", "session-trace-item");
        item.type = "button";
        item.append(
          el("span", "nowrap", formatTimestamp(tb.last_timestamp || tb.first_timestamp)),
          el("code", "monitor-code", tid),
          el("span", "session-trace-q", tb.question || tb.name || tb.route || "—"),
          el("span", "num nowrap", `${formatTokens(tb.total_tokens)} tok · ${fmtSec.format(tb.seconds || 0)} s`)
        );
        item.addEventListener("click", () => openTraceDrawer(tid));
        list.append(item);
      }
      card.append(list);
      return card;
    });

    container.replaceChildren(...cards);
  }

  function renderEvents(summary, allEvents) {
    const filtered = [...allEvents]
      .reverse()
      .filter(ev => {
        if (state.stage && (ev.stage || "untagged") !== state.stage) return false;
        if (state.traceId && (ev.trace_id || "(sem-trace)") !== state.traceId) return false;
        if (state.status === "ok" && !ev.ok) return false;
        if (state.status === "error" && ev.ok) return false;
        return true;
      });

    $("monitor-events-count").textContent =
      `Mostrando ${fmtInt.format(filtered.length)} de ${fmtInt.format(allEvents.length)} chamada(s). Clique em uma linha para inspecionar Prompt e Completion.`;

    const rows = filtered.map(ev => {
      const tr = document.createElement("tr");
      tr.className = "monitor-row-interactive";
      const tid = ev.trace_id || "(sem-trace)";
      tr.addEventListener("click", event => {
        if (event.target.closest("a, button")) return;
        if (tid !== "(sem-trace)") openTraceDrawer(tid, ev.obs_id || "");
      });

      const traceCell = document.createElement("td");
      const traceBtn = el("button", "monitor-inline-filter monitor-trace-id", tid);
      traceBtn.type = "button";
      traceBtn.title = `Filtrar lista por ${tid}`;
      traceBtn.addEventListener("click", () => {
        state.traceId = state.traceId === tid ? "" : tid;
        syncFilterControls();
        renderFilteredSections();
      });
      traceCell.append(traceBtn);

      const stageCell = document.createElement("td");
      stageCell.append(el("code", "monitor-code", ev.stage || "untagged"));

      const toolsCell = document.createElement("td");
      const toolList = ev.tool_calls_returned || [];
      if (toolList.length) {
        const chips = el("div", "monitor-chips");
        for (const t of toolList) chips.append(el("span", "monitor-chip", t));
        toolsCell.append(chips);
      } else {
        toolsCell.textContent = "—";
      }

      const statusCell = document.createElement("td");
      if (ev.ok) {
        statusCell.append(el("span", "monitor-status-ok", ev.stop_reason || "ok"));
      } else {
        statusCell.append(el("span", "monitor-status-err", ev.error || "erro"));
      }

      const tokensSummary =
        `${formatTokens(ev.input_tokens)} / ${formatTokens(ev.cache_read_tokens)} / ${formatTokens(ev.output_tokens)} (${formatTokens(ev.total_tokens)})`;

      const traceHref = langfuseTraceUrl(summary, tid);
      const lfCell = document.createElement("td");
      const actions = el("div", "monitor-row-actions");
      if (tid !== "(sem-trace)") {
        const inspectBtn = el("button", "monitor-btn monitor-btn-sm", "Prompt");
        inspectBtn.type = "button";
        inspectBtn.addEventListener("click", () => openTraceDrawer(tid, ev.obs_id || ""));
        actions.append(inspectBtn);
      }
      if (traceHref) {
        const a = el("a", "monitor-ext-link", "↗");
        a.href = traceHref;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.title = "Abrir trace no Langfuse";
        actions.append(a);
      }
      lfCell.append(actions);

      const modelCell = el("td", "monitor-model", ev.model || "—");
      modelCell.title = ev.model || "";

      tr.append(
        el("td", "nowrap", formatTimestamp(ev.timestamp || ev.start_timestamp)),
        traceCell,
        stageCell,
        modelCell,
        toolsCell,
        el("td", "num nowrap", tokensSummary),
        el("td", "num nowrap", formatDurationMs(ev.ms, ev.seconds)),
        statusCell,
        lfCell
      );
      return tr;
    });

    const table = buildTable(
      [
        {label: "Horário"},
        {label: "Trace ID"},
        {label: "Etapa"},
        {label: "Modelo"},
        {label: "Tools"},
        {label: "In / Cache / Out (Total)", num: true},
        {label: "Tempo", num: true},
        {label: "Status"},
        {label: "Inspecionar"},
      ],
      rows,
      "Nenhuma chamada corresponde aos filtros selecionados."
    );
    $("monitor-events").replaceChildren(table);
  }

  function syncStageSelect(summary) {
    const select = $("monitor-filter-stage");
    const stages = Object.keys(summary?.by_stage || {}).sort();
    const current = state.stage;
    select.replaceChildren(el("option", "", "Todas as etapas"));
    select.firstElementChild.value = "";
    for (const st of stages) {
      const opt = el("option", "", st);
      opt.value = st;
      select.append(opt);
    }
    select.value = stages.includes(current) ? current : "";
    if (select.value !== current) state.stage = "";
  }

  function syncFilterControls() {
    $("monitor-filter-stage").value = state.stage;
    $("monitor-filter-status").value = state.status;
    const pill = $("monitor-trace-pill");
    if (state.traceId) {
      pill.textContent = `Trace: ${state.traceId}`;
      pill.hidden = false;
    } else {
      pill.hidden = true;
    }
    $("monitor-clear-filters").hidden = !state.stage && !state.traceId && state.status === "all";
  }

  function renderFilteredSections() {
    if (!state.payload) return;
    const {events = [], summary = {}} = state.payload;
    renderHistogram(summary);
    renderStages(summary);
    renderTraces(summary);
    renderSessions(summary);
    renderEvents(summary, events);
  }

  function renderAll() {
    if (!state.payload) return;
    const {events = [], summary = {}} = state.payload;
    renderHeader(summary, events);
    renderKpis(summary);
    syncStageSelect(summary);
    syncFilterControls();
    renderFilteredSections();
  }

  // ---------------- Trace Audit Drawer & Prompt Inspector ----------------

  function closeTraceDrawer() {
    state.drawer.open = false;
    $("trace-drawer").hidden = true;
    document.body.classList.remove("drawer-open");
    renderTraces(state.payload?.summary || {});
  }

  async function openTraceDrawer(traceId, focusObsId = "") {
    if (!traceId || traceId === "(sem-trace)") return;
    state.drawer.open = true;
    state.drawer.traceId = traceId;
    state.drawer.detail = null;
    state.drawer.selectedObsId = focusObsId || "";
    state.drawer.obsSubTab = "prompt";
    state.drawer.promptSearch = "";
    state.drawer.promptRole = "all";
    state.drawer.promptMsgIdx = 0;
    state.drawer.promptRaw = false;

    $("trace-drawer").hidden = false;
    document.body.classList.add("drawer-open");
    $("drawer-title").textContent = `Trace: ${traceId}`;
    $("drawer-badges").replaceChildren();
    $("drawer-io").replaceChildren();
    $("drawer-waterfall").replaceChildren(el("p", "monitor-empty", "Carregando auditoria completa do trace…"));
    $("drawer-obs-detail").replaceChildren();
    renderTraces(state.payload?.summary || {});

    try {
      const res = await fetch(`/api/llm/trace?id=${encodeURIComponent(traceId)}`, {cache: "no-store"});
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const detail = await res.json();
      if (!state.drawer.open || state.drawer.traceId !== traceId) return;
      state.drawer.detail = detail;
      const obsList = detail.observations || [];
      if (!state.drawer.selectedObsId || !obsList.some(o => o.id === state.drawer.selectedObsId)) {
        const firstGen = obsList.find(o => o.type === "generation");
        state.drawer.selectedObsId = (firstGen || obsList[0])?.id || "";
      }
      renderDrawer();
    } catch (err) {
      $("drawer-waterfall").replaceChildren(
        el("p", "monitor-empty", `Não foi possível carregar os detalhes do trace: ${err.message}`)
      );
    }
  }

  function renderDrawer() {
    const detail = state.drawer.detail;
    if (!detail) return;
    const totals = detail.totals || {};
    const obsList = detail.observations || [];

    $("drawer-title").textContent = `Trace: ${detail.name || detail.route || detail.trace_id}`;
    const ok = detail.ok !== false && Number(totals.error_calls || 0) === 0;
    const statusPill = $("drawer-status-pill");
    statusPill.textContent = ok ? "OK" : `${totals.error_calls || 1} erro(s)`;
    statusPill.className = ok ? "monitor-status-ok" : "monitor-status-err";

    const badges = $("drawer-badges");
    badges.replaceChildren();
    const promptBase = (totals.input_tokens || 0) + (totals.cache_read_tokens || 0);
    const cachePct = promptBase > 0 ? ((totals.cache_read_tokens || 0) / promptBase) * 100 : 0;
    for (const txt of [
      `id: ${detail.trace_id}`,
      detail.session_id ? `session: ${detail.session_id}` : "sem sessão",
      `${obsList.length} observation(s)`,
      `${formatDurationMs(detail.ms, detail.seconds)}`,
      `${formatTokens(totals.total_tokens)} tok (cache ${fmtPct.format(cachePct)}%)`,
      fmtUsd.format(totals.estimated_cost_usd || 0),
    ]) {
      badges.append(el("span", "monitor-chip", txt));
    }

    const lfLink = $("drawer-lf-link");
    const lfHref = langfuseTraceUrl(detail, detail.trace_id);
    if (detail.langfuse_configured && lfHref) {
      lfLink.href = lfHref;
      lfLink.hidden = false;
    } else {
      lfLink.hidden = true;
    }

    renderDrawerIO(detail);
    renderDrawerWaterfall(detail);
    renderDrawerObservation();
  }

  function renderDrawerIO(detail) {
    const container = $("drawer-io");
    container.replaceChildren();

    const makeBox = (title, value, extraMeta) => {
      const card = el("div", "drawer-io-card");
      const head = el("div", "drawer-io-head");
      head.append(el("strong", "", title), copyButton(() => formatJson(value)));
      card.append(head);
      if (extraMeta) card.append(el("small", "monitor-hint", extraMeta));
      const pre = el("pre", "code-pre code-pre-sm", formatJson(value));
      card.append(pre);
      return card;
    };

    const inp = detail.input;
    const inpText = typeof inp === "object" && inp && inp.question ? inp.question : inp;
    const inpMeta = typeof inp === "object" && inp
      ? [inp.mode && `modo=${inp.mode}`, inp.domain && `domínio=${inp.domain}`, inp.history_turns ? `histórico=${inp.history_turns} turnos` : ""].filter(Boolean).join(" · ")
      : "";

    const out = detail.output;
    const outText = typeof out === "object" && out && out.answer ? out.answer : out;
    const outMeta = typeof out === "object" && out
      ? [
          out.cached_response ? "resposta em cache HTTP" : "",
          out.views?.length ? `abas: ${out.views.join(", ")}` : "",
          out.sources_count ? `${out.sources_count} fontes` : "",
        ].filter(Boolean).join(" · ")
      : "";

    container.append(
      makeBox("Entrada do Trace", inpText || "Não registrada (trace legado)", inpMeta),
      makeBox("Saída final do Trace", outText || detail.error || "Não registrada (trace legado)", outMeta)
    );
  }

  function renderDrawerWaterfall(detail) {
    const container = $("drawer-waterfall");
    const obsList = detail.observations || [];
    const totals = detail.totals || {};
    $("drawer-wf-summary").textContent =
      `${totals.spans || 0} span(s) · ${totals.generations || 0} generation(s) · ${totals.events || 0} event(s) · total ${formatDurationMs(detail.ms, detail.seconds)}`;

    if (!obsList.length) {
      container.replaceChildren(el("p", "monitor-empty", "Nenhuma observation registrada neste trace."));
      return;
    }

    const obsById = Object.fromEntries(obsList.map(o => [o.id, o]));
    const depthOf = obs => {
      let d = 0;
      let cur = obs;
      const seen = new Set();
      while (cur?.parent_observation_id && obsById[cur.parent_observation_id] && !seen.has(cur.id)) {
        seen.add(cur.id);
        cur = obsById[cur.parent_observation_id];
        d++;
      }
      return Math.min(d, 4);
    };

    const maxTimelineMs = Math.max(
      Number(detail.ms || 0),
      ...obsList.map(o => Number(o.offset_ms || 0) + Number(o.duration_ms || 0)),
      1
    );

    const rows = obsList.map(obs => {
      const row = el("button", "waterfall-row");
      row.type = "button";
      if (obs.id === state.drawer.selectedObsId) row.classList.add("is-selected");
      const depth = depthOf(obs);

      const labelWrap = el("div", "waterfall-label");
      labelWrap.style.paddingLeft = `${depth * 18}px`;
      const otype = (obs.type || "span").toLowerCase();
      const badgeLabel = otype === "generation" ? "GEN" : otype.toUpperCase();
      const badge = el("span", `obs-type-badge is-${otype}`, badgeLabel);
      const nameSpan = el("span", "waterfall-name", obs.name || obs.stage || "observation");
      labelWrap.append(badge, nameSpan);
      if (otype === "generation" && Number(obs.cache_read_tokens || 0) > 0) {
        labelWrap.append(el("span", "monitor-chip obs-chip-cached", "Cached"));
      }
      if (obs.ok === false) {
        labelWrap.append(el("span", "monitor-status-err", "Erro"));
      }

      const track = el("div", "waterfall-track");
      const leftPct = Math.min(96, Math.max(0, (Number(obs.offset_ms || 0) / maxTimelineMs) * 100));
      const rawWidthPct = (Number(obs.duration_ms || 0) / maxTimelineMs) * 100;
      const widthPct = Math.max(otype === "event" ? 1.5 : 2.5, Math.min(100 - leftPct, rawWidthPct));
      const bar = el("span", `waterfall-bar is-${otype}${obs.ok === false ? " is-error" : ""}`);
      bar.style.left = `${leftPct.toFixed(2)}%`;
      bar.style.width = `${widthPct.toFixed(2)}%`;
      track.append(bar);

      const metrics = el("div", "waterfall-metrics");
      metrics.append(el("strong", "nowrap", formatDurationMs(obs.duration_ms, obs.seconds)));
      if (otype === "generation") {
        const speed = obs.tok_per_sec ? ` · ${fmtPct.format(obs.tok_per_sec)} tok/s` : "";
        metrics.append(el("small", "nowrap", `${formatTokens(obs.total_tokens)} tok${speed}`));
      } else {
        metrics.append(el("small", "nowrap", `+${Math.round(obs.offset_ms || 0)} ms`));
      }

      row.append(labelWrap, track, metrics);
      row.addEventListener("click", () => {
        state.drawer.selectedObsId = obs.id;
        state.drawer.obsSubTab = otype === "generation" ? "prompt" : "io";
        state.drawer.promptSearch = "";
        state.drawer.promptRole = "all";
        state.drawer.promptMsgIdx = 0;
        renderDrawerWaterfall(detail);
        renderDrawerObservation();
      });
      return row;
    });

    container.replaceChildren(...rows);
  }

  function renderDrawerObservation() {
    const container = $("drawer-obs-detail");
    const detail = state.drawer.detail;
    const obs = (detail?.observations || []).find(o => o.id === state.drawer.selectedObsId);
    if (!obs) {
      container.replaceChildren(el("p", "monitor-empty", "Selecione uma observation no Waterfall acima."));
      return;
    }

    container.replaceChildren();
    const otype = (obs.type || "span").toLowerCase();

    const head = el("div", "drawer-card-head");
    const titleBox = el("div", "drawer-obs-title");
    titleBox.append(
      el("span", `obs-type-badge is-${otype}`, otype === "generation" ? "GENERATION" : otype.toUpperCase()),
      el("h3", "", obs.name || obs.stage || "Observation")
    );
    const pills = el("div", "drawer-badges");
    if (obs.model) pills.append(el("span", "monitor-chip", obs.model));
    if (obs.stop_reason) pills.append(el("span", "monitor-chip", `stop: ${obs.stop_reason}`));
    if (Number(obs.cache_read_tokens || 0) > 0) pills.append(el("span", "monitor-chip obs-chip-cached", "Cached"));
    if (obs.tok_per_sec) pills.append(el("span", "monitor-chip", `${fmtPct.format(obs.tok_per_sec)} tok/s`));
    pills.append(el("span", "monitor-chip", formatDurationMs(obs.duration_ms, obs.seconds)));
    if (otype === "generation") pills.append(el("span", "monitor-chip", fmtUsd.format(obs.estimated_cost_usd || 0)));
    head.append(titleBox, pills);
    container.append(head);

    if (otype !== "generation") {
      renderSpanOrEventDetail(container, obs);
      return;
    }

    const tabs = el("div", "monitor-tabs drawer-subtabs");
    for (const [key, label] of [
      ["prompt", `Prompt (${obs.prompt_messages?.length || obs.messages_count || 0} msgs)`],
      ["completion", `Completion (${formatTokens(obs.output_tokens)} tok)`],
      ["usage", "Usage & Raw JSON"],
    ]) {
      const btn = el("button", `monitor-tab${state.drawer.obsSubTab === key ? " is-active" : ""}`, label);
      btn.type = "button";
      btn.addEventListener("click", () => {
        state.drawer.obsSubTab = key;
        renderDrawerObservation();
      });
      tabs.append(btn);
    }
    container.append(tabs);

    const body = el("div", "drawer-obs-body");
    container.append(body);

    if (state.drawer.obsSubTab === "completion") {
      renderGenerationCompletion(body, obs);
    } else if (state.drawer.obsSubTab === "usage") {
      renderGenerationUsageAndRaw(body, obs);
    } else {
      renderGenerationPromptInspector(body, obs);
    }
  }

  function renderSpanOrEventDetail(container, obs) {
    const grid = el("div", "drawer-io-grid");
    const mk = (title, val) => {
      const card = el("div", "drawer-io-card");
      const h = el("div", "drawer-io-head");
      h.append(el("strong", "", title), copyButton(() => formatJson(val)));
      card.append(h, el("pre", "code-pre", formatJson(val)));
      return card;
    };
    grid.append(mk("Input da operação", obs.input), mk("Output da operação", obs.error || obs.output));
    container.append(grid);

    const rawDetails = el("details", "drawer-raw-details");
    rawDetails.append(el("summary", "", "Metadata & Raw JSON"));
    rawDetails.append(el("pre", "code-pre", formatJson(obs)));
    container.append(rawDetails);
  }

  function renderGenerationPromptInspector(body, obs) {
    const msgs = obs.prompt_messages || [];
    const roleBreakdown = obs.role_breakdown || {};

    // Top OpenRouter-inspired card: Tokens per message + Usage + By role
    const summaryGrid = el("div", "prompt-summary-grid");

    // Left: Tokens per message proportional bar
    const chartCard = el("div", "prompt-chart-card");
    const chartHead = el("div", "drawer-io-head");
    chartHead.append(
      el("strong", "", "Tokens por mensagem"),
      el("small", "monitor-hint", `${formatTokens(obs.input_tokens + obs.cache_read_tokens + obs.cache_creation_tokens)} tokens de entrada`)
    );
    chartCard.append(chartHead);

    const barTrack = el("div", "prompt-msg-chart");
    if (msgs.length) {
      const totalMsgChars = msgs.reduce((s, m) => s + Number(m.chars || 0), 0) || 1;
      for (const m of msgs) {
        const share = Math.max(2, (Number(m.chars || 0) / totalMsgChars) * 100);
        const seg = el("button", `prompt-msg-seg role-${m.role}${m.cached_hint ? " is-cached" : ""}`);
        seg.type = "button";
        seg.style.width = `${share}%`;
        seg.title = `#${m.index} · ${ROLE_LABELS[m.role] || m.role} · ~${formatTokens(m.est_tokens)} tok${m.cached_hint ? " (cached)" : ""}\n${m.preview}`;
        seg.addEventListener("click", () => {
          state.drawer.promptRole = "all";
          state.drawer.promptSearch = "";
          state.drawer.promptMsgIdx = m.index - 1;
          renderDrawerObservation();
        });
        barTrack.append(seg);
      }
    } else {
      barTrack.append(el("span", "monitor-hint", "Sem breakdown de mensagens (trace legado)."));
    }
    chartCard.append(barTrack);

    const legend = el("div", "prompt-role-legend");
    for (const [role, color] of Object.entries(ROLE_COLORS)) {
      const item = el("span", "prompt-legend-item");
      const dot = el("i");
      dot.style.background = color;
      item.append(dot, ROLE_LABELS[role]);
      legend.append(item);
    }
    const cachedLegend = el("span", "prompt-legend-item");
    cachedLegend.append(el("i", "is-cached-swatch"), "Cached");
    legend.append(cachedLegend);
    chartCard.append(legend);

    // Middle: Token / Cache / Cost summary
    const statsCard = el("div", "prompt-meta-card");
    const promptTotal = Number(obs.input_tokens || 0) + Number(obs.cache_read_tokens || 0) + Number(obs.cache_creation_tokens || 0);
    const uncachedPct = promptTotal > 0 ? (Number(obs.input_tokens || 0) / promptTotal) * 100 : 0;
    const cachedPct = promptTotal > 0 ? (Number(obs.cache_read_tokens || 0) / promptTotal) * 100 : 0;
    const statsRows = [
      ["Entrada nova", `${formatTokens(obs.input_tokens)} (${fmtPct.format(uncachedPct)}%)`],
      ["Cached (read)", `${formatTokens(obs.cache_read_tokens)} (${fmtPct.format(cachedPct)}%)`],
      ["Cache write", formatTokens(obs.cache_creation_tokens)],
      ["Saída", formatTokens(obs.output_tokens)],
      ["Custo est.", fmtUsd.format(obs.estimated_cost_usd || 0)],
      ["Tools disp.", String(obs.tools_names?.length || obs.tools_count || 0)],
    ];
    const dl = el("dl", "prompt-kv-list");
    for (const [k, v] of statsRows) {
      dl.append(el("dt", "", k), el("dd", "num", v));
    }
    statsCard.append(el("strong", "prompt-subhead", "Tokens & Cache"), dl);

    // Right: By role breakdown
    const roleCard = el("div", "prompt-meta-card");
    const roleTable = el("table", "prompt-role-table");
    const rHead = document.createElement("thead");
    const rHr = document.createElement("tr");
    rHr.append(el("th", "", "By role"), el("th", "num", "%"), el("th", "num", "#"));
    rHead.append(rHr);
    const rBody = document.createElement("tbody");
    for (const role of ["system", "assistant", "tool", "user"]) {
      const rb = roleBreakdown[role] || {count: 0, pct: 0};
      const tr = document.createElement("tr");
      const tdRole = document.createElement("td");
      tdRole.append(el("span", `role-badge role-${role}`, ROLE_LABELS[role]));
      tr.append(tdRole, el("td", "num", `${fmtPct.format(rb.pct || 0)}%`), el("td", "num", String(rb.count || 0)));
      rBody.append(tr);
    }
    roleTable.append(rHead, rBody);
    roleCard.append(roleTable);

    summaryGrid.append(chartCard, statsCard, roleCard);
    body.append(summaryGrid);

    if (!msgs.length) {
      body.append(
        el(
          "p",
          "monitor-empty",
          `Trace legado sem payload completo de mensagens (system_chars=${formatTokens(obs.system_chars)}, messages_count=${obs.messages_count || 0}, tools_count=${obs.tools_count || 0}). Faça uma nova pergunta para auditar cada mensagem.`
        )
      );
      return;
    }

    // Filter & browser container (keeps searchInput mounted so typing never loses focus)
    const browser = el("div", "prompt-browser");
    const leftPane = el("div", "prompt-list-pane");
    const searchBar = el("div", "prompt-search-bar");
    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.className = "prompt-search-input";
    searchInput.placeholder = "Buscar nas mensagens…";
    searchInput.value = state.drawer.promptSearch;

    const roleSelect = el("select", "monitor-select");
    for (const [val, label] of [
      ["all", "Todos os papéis"],
      ["system", "System"],
      ["user", "User"],
      ["assistant", "Assistant"],
      ["tool", "Tool"],
    ]) {
      const opt = el("option", "", label);
      opt.value = val;
      roleSelect.append(opt);
    }
    roleSelect.value = state.drawer.promptRole;
    searchBar.append(searchInput, roleSelect);

    const listEl = el("div", "prompt-msg-list");
    leftPane.append(searchBar, listEl);
    const rightPane = el("div", "prompt-viewer-pane");
    browser.append(leftPane, rightPane);
    body.append(browser);

    function renderBrowserPanels() {
      const q = state.drawer.promptSearch.trim().toLowerCase();
      const filtered = msgs.filter(m => {
        if (state.drawer.promptRole !== "all" && m.role !== state.drawer.promptRole) return false;
        if (!q) return true;
        const hay = `${m.preview || ""} ${m.content || ""} ${formatJson(m.tool_calls || "")}`.toLowerCase();
        return hay.includes(q);
      });

      if (state.drawer.promptMsgIdx >= filtered.length) {
        state.drawer.promptMsgIdx = Math.max(0, filtered.length - 1);
      }
      const selectedMsg = filtered[state.drawer.promptMsgIdx] || null;

      listEl.replaceChildren();
      filtered.forEach((m, i) => {
        const row = el("button", `prompt-msg-item${i === state.drawer.promptMsgIdx ? " is-selected" : ""}`);
        row.type = "button";
        const top = el("div", "prompt-msg-item-top");
        top.append(
          el("span", "prompt-msg-num", `#${m.index}`),
          el("span", `role-badge role-${m.role}`, ROLE_LABELS[m.role] || m.role)
        );
        if (m.cached_hint) top.append(el("span", "monitor-chip obs-chip-cached", "cached"));
        top.append(el("small", "prompt-msg-tok", `~${formatTokens(m.est_tokens)} tok`));

        const prev = el("div", "prompt-msg-preview", m.preview);
        row.append(top, prev);
        if (m.tool_calls?.length) {
          const tcNames = m.tool_calls.map(tc => tc.name).filter(Boolean).join(", ");
          row.append(el("div", "prompt-msg-tools", `${m.tool_calls.length} tool call(s): ${tcNames}`));
        }
        row.addEventListener("click", () => {
          state.drawer.promptMsgIdx = i;
          renderBrowserPanels();
        });
        listEl.append(row);
      });
      if (!filtered.length) {
        listEl.append(el("p", "monitor-empty", "Nenhuma mensagem corresponde ao filtro."));
      }

      const viewerHead = el("div", "prompt-viewer-head");
      const navGroup = el("div", "prompt-viewer-nav");
      const prevBtn = el("button", "monitor-btn monitor-btn-sm", "‹");
      prevBtn.type = "button";
      prevBtn.disabled = state.drawer.promptMsgIdx <= 0;
      prevBtn.addEventListener("click", () => {
        state.drawer.promptMsgIdx = Math.max(0, state.drawer.promptMsgIdx - 1);
        renderBrowserPanels();
      });
      const nextBtn = el("button", "monitor-btn monitor-btn-sm", "›");
      nextBtn.type = "button";
      nextBtn.disabled = state.drawer.promptMsgIdx >= filtered.length - 1;
      nextBtn.addEventListener("click", () => {
        state.drawer.promptMsgIdx = Math.min(filtered.length - 1, state.drawer.promptMsgIdx + 1);
        renderBrowserPanels();
      });
      const counter = el(
        "span",
        "monitor-hint",
        filtered.length ? `Mensagem ${state.drawer.promptMsgIdx + 1} de ${filtered.length}` : "0 mensagens"
      );
      navGroup.append(prevBtn, counter, nextBtn);

      const viewActions = el("div", "prompt-viewer-actions");
      const rawBtn = el("button", `monitor-btn monitor-btn-sm${state.drawer.promptRaw ? " is-active" : ""}`, "</> Raw JSON");
      rawBtn.type = "button";
      rawBtn.addEventListener("click", () => {
        state.drawer.promptRaw = !state.drawer.promptRaw;
        renderBrowserPanels();
      });
      viewActions.append(
        copyButton(() => (selectedMsg ? (state.drawer.promptRaw ? formatJson(selectedMsg) : selectedMsg.content || formatJson(selectedMsg.tool_calls)) : "")),
        rawBtn
      );
      viewerHead.append(navGroup, viewActions);

      const viewerBody = el("div", "prompt-viewer-body");
      if (selectedMsg) {
        if (state.drawer.promptRaw) {
          viewerBody.append(el("pre", "code-pre", formatJson(selectedMsg)));
        } else {
          const metaLine = el("div", "prompt-viewer-meta");
          metaLine.append(el("span", `role-badge role-${selectedMsg.role}`, ROLE_LABELS[selectedMsg.role] || selectedMsg.role));
          metaLine.append(el("span", "monitor-chip", `${formatTokens(selectedMsg.chars)} chars · ~${formatTokens(selectedMsg.est_tokens)} tok`));
          if (selectedMsg.tool_use_id) metaLine.append(el("span", "monitor-chip", `tool_use_id: ${selectedMsg.tool_use_id}`));
          viewerBody.append(metaLine);
          if (selectedMsg.content) {
            viewerBody.append(el("pre", "code-pre prompt-content-pre", selectedMsg.content));
          }
          if (selectedMsg.tool_calls?.length) {
            for (const tc of selectedMsg.tool_calls) {
              const tcCard = el("div", "tool-call-card");
              tcCard.append(
                el("strong", "", `Tool call · ${tc.name} (${tc.id || "sem-id"})`),
                el("pre", "code-pre", formatJson(tc.input))
              );
              viewerBody.append(tcCard);
            }
          }
        }
      } else {
        viewerBody.append(el("p", "monitor-empty", "Selecione uma mensagem à esquerda."));
      }
      rightPane.replaceChildren(viewerHead, viewerBody);
    }

    searchInput.addEventListener("input", e => {
      state.drawer.promptSearch = e.target.value;
      state.drawer.promptMsgIdx = 0;
      renderBrowserPanels();
    });
    roleSelect.addEventListener("change", e => {
      state.drawer.promptRole = e.target.value;
      state.drawer.promptMsgIdx = 0;
      renderBrowserPanels();
    });
    renderBrowserPanels();
  }

  function renderGenerationCompletion(body, obs) {
    const blocks = obs.completion_blocks || [];
    if (!blocks.length) {
      if (obs.error) {
        body.append(el("pre", "code-pre", obs.error));
      } else if (obs.tool_calls_returned?.length) {
        body.append(el("p", "monitor-hint", `Tool calls retornadas: ${obs.tool_calls_returned.join(", ")}`));
      } else {
        body.append(el("p", "monitor-empty", "Sem blocos de completion detalhados para esta chamada."));
      }
      return;
    }

    const head = el("div", "drawer-io-head");
    head.append(
      el("strong", "", `Resposta gerada (${formatTokens(obs.output_tokens)} tokens)`),
      copyButton(() => formatJson(blocks))
    );
    body.append(head);

    for (const block of blocks) {
      if (block.type === "text") {
        body.append(el("pre", "code-pre prompt-content-pre", block.text || ""));
      } else if (block.type === "tool_use") {
        const card = el("div", "tool-call-card");
        card.append(
          el("strong", "", `Tool call solicitada · ${block.name} (${block.id || "sem-id"})`),
          el("pre", "code-pre", formatJson(block.input))
        );
        body.append(card);
      } else {
        body.append(el("pre", "code-pre", formatJson(block)));
      }
    }
  }

  function renderGenerationUsageAndRaw(body, obs) {
    const head = el("div", "drawer-io-head");
    head.append(el("strong", "", "Métricas e Payload Raw JSON"), copyButton(() => formatJson(obs)));
    body.append(head);

    const grid = el("div", "drawer-usage-grid");
    for (const [k, v] of [
      ["Stage", obs.stage || obs.name || "—"],
      ["Modelo", obs.model || "—"],
      ["Input (novo)", formatTokens(obs.input_tokens)],
      ["Cache Read", formatTokens(obs.cache_read_tokens)],
      ["Cache Write", formatTokens(obs.cache_creation_tokens)],
      ["Output", formatTokens(obs.output_tokens)],
      ["Total Tokens", formatTokens(obs.total_tokens)],
      ["Velocidade", obs.tok_per_sec ? `${fmtPct.format(obs.tok_per_sec)} tok/s` : "—"],
      ["Custo estimado", fmtUsd.format(obs.estimated_cost_usd || 0)],
      ["Tempo", formatDurationMs(obs.duration_ms, obs.seconds)],
      ["Max Tokens", obs.max_tokens ? formatTokens(obs.max_tokens) : "—"],
      ["Tools enviadas", obs.tools_names?.length ? obs.tools_names.join(", ") : String(obs.tools_count || 0)],
    ]) {
      const box = el("div", "drawer-usage-box");
      box.append(el("small", "", k), el("strong", "", v));
      grid.append(box);
    }
    body.append(grid, el("pre", "code-pre", formatJson(obs)));
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    const refreshBtn = $("monitor-refresh");
    refreshBtn.disabled = true;
    try {
      const limit = Number($("monitor-limit").value || 200);
      const res = await fetch(`/api/llm/tracker?limit=${encodeURIComponent(limit)}`, {cache: "no-store"});
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.payload = await res.json();
      state.lastUpdated = new Date();
      renderAll();
    } catch (err) {
      $("monitor-status").textContent = `Falha ao carregar métricas: ${err.message}`;
    } finally {
      state.loading = false;
      refreshBtn.disabled = false;
    }
  }

  function init() {
    document.querySelectorAll(".monitor-tab[data-monitor-tab]").forEach(btn => {
      btn.addEventListener("click", () => switchTab(btn.dataset.monitorTab));
    });
    $("monitor-refresh").addEventListener("click", refresh);
    $("monitor-limit").addEventListener("change", refresh);
    $("monitor-filter-stage").addEventListener("change", event => {
      state.stage = event.target.value;
      syncFilterControls();
      renderFilteredSections();
    });
    $("monitor-filter-status").addEventListener("change", event => {
      state.status = event.target.value;
      syncFilterControls();
      renderFilteredSections();
    });
    $("monitor-clear-filters").addEventListener("click", () => {
      state.stage = "";
      state.traceId = "";
      state.status = "all";
      syncFilterControls();
      renderFilteredSections();
    });

    $("drawer-close").addEventListener("click", closeTraceDrawer);
    $("trace-drawer-backdrop").addEventListener("click", closeTraceDrawer);
    window.addEventListener("keydown", event => {
      if (event.key === "Escape" && state.drawer.open) closeTraceDrawer();
    });

    window.addEventListener("message", event => {
      if (event.origin === location.origin && event.data?.type === "ambiance:monitor-refresh") {
        refresh();
      }
    });
    setInterval(() => {
      if ($("monitor-auto").checked && !document.hidden) refresh();
    }, 5000);
    refresh();
  }

  window.addEventListener("DOMContentLoaded", init);
})();

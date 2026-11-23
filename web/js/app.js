
/* =========================================
   AMBIANCE - INTELIGÊNCIA AMBIENTAL
   FRONT-END / INTEGRAÇÃO COM BACK-END
========================================= */

const $ = (id) => document.getElementById(id);

let queryCount = 0;


/* =========================================
   PROTEÇÃO DE CONTEÚDO
========================================= */

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
    })[char]);
}


/* =========================================
   STATUS DO SISTEMA
========================================= */

function setStatus(message, type = "") {
    const status = $("status");

    status.textContent = message;
    status.className = type;
}


function setConnectionStatus(message) {
    $("connection-status").textContent = message;
}


function showEmpty(elementId, message) {
    $(elementId).innerHTML =
        `<p class="empty-state">${escapeHtml(message)}</p>`;
}


/* =========================================
   RENDERIZAÇÃO DA RESPOSTA
========================================= */

function renderAnswer(data) {

    const answer =
        data.answer ??
        data.response ??
        data.result ??
        data.message ??
        "Nenhuma resposta foi retornada.";

    $("answer").textContent =
        typeof answer === "string"
            ? answer
            : JSON.stringify(answer, null, 2);
}


/* =========================================
   FONTES CONSULTADAS
========================================= */

function renderSources(sources) {

    const container = $("sources");

    if (!Array.isArray(sources) || sources.length === 0) {
        showEmpty("sources", "Nenhuma fonte encontrada.");
        return;
    }

    container.innerHTML = sources.map((source) => {

        const title = typeof source === "string"
            ? source
            : source.title ??
              source.name ??
              source.source ??
              "Fonte";

        const url = typeof source === "object" && source !== null
            ? source.url ?? source.link
            : null;

        let safeUrl = null;

        if (typeof url === "string") {

            try {
                const parsedUrl = new URL(url);

                if (
                    parsedUrl.protocol === "https:" ||
                    parsedUrl.protocol === "http:"
                ) {
                    safeUrl = parsedUrl.href;
                }

            } catch {
                safeUrl = null;
            }
        }

        return `
            <div class="source-item">

                <strong>${escapeHtml(title)}</strong>

                ${safeUrl
                    ? `
                        <br>
                        <a
                            href="${escapeHtml(safeUrl)}"
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            Acessar fonte →
                        </a>
                    `
                    : ""
                }

            </div>
        `;

    }).join("");
}


/* =========================================
   FERRAMENTAS UTILIZADAS
========================================= */

function renderCalls(calls) {

    if (!Array.isArray(calls) || calls.length === 0) {
        showEmpty("calls", "Nenhuma ferramenta utilizada.");
        return;
    }

    $("calls").innerHTML = calls.map((call) => {

        const name = typeof call === "string"
            ? call
            : call.name ?? call.tool ?? "Ferramenta";

        return `
            <div class="call-item">
                ${escapeHtml(name)}
            </div>
        `;

    }).join("");
}


/* =========================================
   INFORMAÇÕES DE PROCESSAMENTO
========================================= */

function renderUsage(usage) {

    if (
        !usage ||
        typeof usage !== "object" ||
        Array.isArray(usage) ||
        Object.keys(usage).length === 0
    ) {
        showEmpty("usage", "Nenhuma informação de processamento.");
        return;
    }

    $("usage").innerHTML = Object.entries(usage).map(([key, value]) => {

        const formattedValue =
            typeof value === "object" && value !== null
                ? JSON.stringify(value)
                : value;

        return `
            <div class="context-item">

                <strong>${escapeHtml(key)}:</strong>

                ${escapeHtml(formattedValue)}

            </div>
        `;

    }).join("");
}


/* =========================================
   CONTEXTO RECUPERADO
========================================= */

function renderContext(context) {

    if (
        context === null ||
        context === undefined ||
        context === ""
    ) {
        showEmpty("context", "Nenhum contexto recuperado.");
        return;
    }

    const content = typeof context === "string"
        ? context
        : JSON.stringify(context, null, 2);

    $("context").textContent = content;
}


/* =========================================
   EXIBIÇÃO DOS RESULTADOS
========================================= */

function renderResults(data) {

    renderAnswer(data);

    renderSources(
        data.sources ??
        data.references ??
        data.documents
    );

    renderCalls(
        data.tool_calls ??
        data.calls ??
        data.tools
    );

    renderUsage(
        data.usage ??
        data.metadata
    );

    renderContext(
        data.context ??
        data.retrieved_context
    );
}


/* =========================================
   COMUNICAÇÃO COM O BACK-END
========================================= */

async function askBackend(payload) {

    const response = await fetch("/api/ask", {

        method: "POST",

        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
        },

        body: JSON.stringify(payload)

    });

    const responseText = await response.text();

    let data = {};

    if (responseText.trim()) {

        try {

            data = JSON.parse(responseText);

        } catch {

            if (!response.ok) {

                throw new Error(
                    `Erro HTTP ${response.status}. ` +
                    `O servidor não retornou JSON válido.`
                );

            }

            throw new Error(
                `O servidor não retornou JSON válido. HTTP ${response.status}.`
            );

        }

    }

    if (!response.ok) {

        throw new Error(
            data.detail ??
            data.error ??
            data.message ??
            `Erro HTTP ${response.status}`
        );

    }

    if (
        !data ||
        typeof data !== "object" ||
        Array.isArray(data)
    ) {

        throw new Error(
            "O formato da resposta do servidor é inválido."
        );

    }

    return data;
}


/* =========================================
   ENVIO DA CONSULTA
========================================= */

async function handleSubmit(event) {

    event.preventDefault();

    const question = $("question").value.trim();

    if (!question) {

        setStatus(
            "Digite uma pergunta antes de enviar.",
            "error"
        );

        return;
    }


    // Dados enviados ao Back-end

    const payload = {

        question: question,

        k: Number($("k").value),

        mode: $("mode").value,

        domain: $("domain").value

    };


    const button = $("send");

    // Bloqueia o botão durante o processamento

    button.disabled = true;

    button.textContent = "Processando...";

    setStatus("Enviando consulta ao sistema...");

    setConnectionStatus("Conectando...");


    // Limpa resultados anteriores

    $("answer").textContent = "Aguardando resposta...";

    showEmpty("sources", "Buscando fontes...");

    showEmpty("calls", "Aguardando processamento...");

    showEmpty("usage", "Processando...");

    showEmpty("context", "Recuperando contexto...");


    try {

        // Solicitação ao Back-end

        const data = await askBackend(payload);


        // Exibe os resultados

        renderResults(data);


        // Atualiza indicadores

        queryCount++;

        $("query-count").textContent = queryCount;

        setConnectionStatus("Conectado");

        setStatus(
            "Consulta realizada com sucesso.",
            "success"
        );


    } catch (error) {

        console.error("Erro na consulta:", error);


        setConnectionStatus("Erro");

        $("answer").textContent = error.message;

        showEmpty(
            "sources",
            "Não foi possível carregar as fontes."
        );

        showEmpty(
            "calls",
            "Não foi possível carregar as ferramentas."
        );

        showEmpty(
            "usage",
            "Processamento não concluído."
        );

        showEmpty(
            "context",
            "Contexto indisponível."
        );

        setStatus(error.message, "error");


    } finally {

        // Reativa o botão

        button.disabled = false;

        button.innerHTML = 'Enviar <span>→</span>';

    }

}


/* =========================================
   EVENTOS
========================================= */

// Envio pelo formulário

$("form").addEventListener(
    "submit",
    handleSubmit
);


$("question").addEventListener("keydown", (event) => {
    if (
        event.key === "Enter" &&
        !event.shiftKey &&
        !event.isComposing &&
        event.keyCode !== 229 &&
        !$("send").disabled
    ) {
        event.preventDefault();
        $("form").requestSubmit();
    }
});

const viewButtons = document.querySelectorAll("[data-view]");
const questionSections = [document.querySelector(".hero"), document.querySelector(".results-area")];
const dashboardView = $("dashboard-view");

viewButtons.forEach((button) => {
    button.addEventListener("click", () => {
        const showDashboard = button.dataset.view === "dashboard";
        questionSections.forEach((section) => { section.hidden = showDashboard; });
        dashboardView.hidden = !showDashboard;
        viewButtons.forEach((tab) => {
            const active = tab === button;
            tab.classList.toggle("active", active);
            tab.setAttribute("aria-selected", String(active));
        });
        window.scrollTo({ top: 0, behavior: "smooth" });
    });
});

$("mode").addEventListener("change", () => {
    const lawsOnly = $("mode").value === "laws";
    if (lawsOnly) $("domain").value = "law";
    $("domain").disabled = lawsOnly;
});

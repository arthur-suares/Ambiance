"""Orquestrador de intenções do pipeline de chat (etapa 3 de `docs/PIPELINE_MULTIAGENTE.md`).

Classifica cada mensagem do usuário entre:
- `question`: pergunta atendida pelo Agente de Dados/RAG (`src/agent.py`);
- `dashboard`: criação de um novo painel analítico;
- `dashboard_edit`: alteração incremental da `DashboardSpec` atual da sessão;
- `map_edit`: pedido de mapa (retorna aviso amigável de indisponibilidade nesta versão);
- `mixed`: pergunta analítica/jurídica combinada com geração de dashboard (`RAG -> store -> dashboard`).

Aplica regras determinísticas primeiro (incluindo tolerância a erros comuns de digitação como
`grafiko` e `dashbord`) e só recorre a 1 chamada LLM estruturada quando as regras não decidem
e `use_llm=True`. Na dúvida, segue o caminho seguro: `question`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from src.dashboard._llm import call_structured_llm
from src.rag import resolve_domain

ALLOWED_INTENTS = ("question", "dashboard", "dashboard_edit", "map_edit", "mixed")
ALLOWED_DOMAINS = ("soy", "beef", "law", "mixed", "auto")

MAP_UNAVAILABLE_MESSAGE = (
    "A visualização em mapa interativo (Agente de Mapa) ainda não está disponível nesta versão. "
    "Posso responder com os números detalhados no chat ou montar um painel com gráficos de barras, "
    "linhas, KPIs e tabelas (por exemplo, por país de destino, estado, bioma ou município)."
)

DEFAULT_CLARIFICATION_MESSAGE = (
    "Qual recorte você gostaria de ver no painel? Escolha ou descreva uma opção:\n"
    "1. Exportações e exposição ao desmatamento da soja por país de destino (2022);\n"
    "2. Municípios líderes em exposição ao desmatamento na carne bovina (2023);\n"
    "3. Série anual de volume, FOB e exposição de um estado ou bioma específico (ex.: Mato Grosso ou Amazônia)."
)


@dataclass
class OrchestrationDecision:
    intent: str
    domain: str
    use_previous_results: bool = False
    needs_new_data: bool = True
    clarification: str | None = None
    assumption: str | None = None
    decided_by: str = "rules"
    input_tokens: int = 0
    output_tokens: int = 0


def _strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


def _normalize(text: str) -> str:
    low = _strip_accents((text or "").lower())
    return re.sub(r"\s+", " ", low).strip()


# --- Padrões determinísticos -----------------------------------------------------

_MAP_RE = re.compile(
    r"\b(?:mapas?|mapa-?mundi|choropleth|coropletic\w*|camadas?\s+geografic\w*|arcos?\s+de\s+fluxo)\b",
    re.IGNORECASE,
)
_LOGISTICS_MAP_DATA_RE = re.compile(r"\bmapa\s+logistic\w*\b", re.IGNORECASE)

# Inclui variantes e erros de digitação frequentes ("grafiko", "grfico", "dashbord", "dasboard"...)
_DASHBOARD_NOUN_RE = re.compile(
    r"\b(?:"
    r"dash(?:board|bord|boad|borad|s)?|deshboard|dasboard"
    r"|painel|paineis"
    r"|grafi[ck]os?|grfi[ck]os?|grafi[ck]uzinho"
    r"|charts?|plot(?:ar|agem|s)?"
    r"|visualizac(?:ao|oes)"
    r")\b",
    re.IGNORECASE,
)

_EDIT_VERB_RE = re.compile(
    r"\b(?:"
    r"troqu\w*|troca\w*|substitu\w*|mud\w*|alter\w*|modifiqu\w*|converta\w*|transform\w*"
    r"|adicion\w*|acrescent\w*|inclu\w*|insir\w*|coloc\w*|coloqu\w*|bota\b|bote\b"
    r"|remov\w*|tir\w*|exclu\w*|retir\w*"
    r"|reorden\w*|orden\w*"
    r")\b",
    re.IGNORECASE,
)

_ADD_VERB_RE = re.compile(
    r"\b(?:adicion\w*|acrescent\w*|inclu\w*|insir\w*|coloc\w*|coloqu\w*|bota\b|bote\b)\b",
    re.IGNORECASE,
)

_EDIT_COMPONENT_TARGET_RE = re.compile(
    r"\b(?:"
    r"grafi[ck]os?|grfi[ck]os?|barras?|linhas?|tabelas?|kpis?|cart(?:ao|oes)|cards?|componentes?"
    r"|painel|paineis|dash\w*"
    r"|titulos?|subtitulos?|cores?|eixos?|horizont\w*|vertic\w*|top\s*\d+"
    r")\b",
    re.IGNORECASE,
)

_DEICTIC_STORE_RE = re.compile(
    r"\b(?:"
    r"com\s+isso|disso|desses?\s+dados?|desses?\s+resultados?|desses?\s+numeros?"
    r"|dessa\s+resposta|dessa\s+consulta|com\s+esses?\s+dados?|com\s+esses?\s+resultados?"
    r"|acima|anterior(?:es)?"
    r")\b",
    re.IGNORECASE,
)

_LAW_TERMS_RE = re.compile(
    r"\b(?:codigo\s+florestal|reserva\s+legal|lei\s+ambiental|lei\s+\d|decreto|artigo|art\.|legislacao|crime\s+ambiental|snuc|mata\s+atlantica)\b",
    re.IGNORECASE,
)

_MIXED_QUESTION_CONJ_RE = re.compile(
    r"\b(?:quais?|qual|quanto\w*|como|explique|analise|responda|compare)\b"
    r".+\b(?:e\s+(?:monte|monta|faca|faz|crie|cria|gere|gera|mostre|exiba)|alem\s+disso|acompanhad[oa]\s+de)\b",
    re.IGNORECASE,
)

_WORLD_SCOPE_RE = re.compile(
    r"\b(?:todo\s+o\s+mundo|no\s+mundo|pelo\s+mundo|mundial|mundiais|global|globais|todos\s+os\s+paises)\b",
    re.IGNORECASE,
)

_VAGUE_FILLER_WORDS = frozenset({
    "faz", "faca", "fazer", "monta", "monte", "montar", "cria", "crie", "criar",
    "gera", "gere", "gerar", "mostra", "mostre", "mostrar", "exiba", "exibir",
    "quero", "queria", "gostaria", "pode", "poderia", "consegue", "ver", "faze",
    "me", "de", "da", "do", "dos", "das", "dê", "um", "uma", "uns", "umas",
    "o", "a", "os", "as", "no", "na", "num", "numa", "em", "por", "favor", "pfv",
    "ai", "pra", "para", "mim", "agora", "ja", "novo", "nova", "interativo",
    "interativa", "bonito", "completo", "completa", "simples", "rapido", "sobre",
    "dashboard", "dashboards", "dashbord", "dashboad", "dasboard", "deshboard", "dash",
    "painel", "paineis", "grafico", "graficos", "grafiko", "grafikos", "grfico", "grficos",
    "chart", "charts", "plot", "plotar", "visualizacao", "visualizacoes",
})

_SUBSTANTIVE_TOPIC_RE = re.compile(
    r"\b(?:"
    r"soja|soy|carne|bovin\w*|gado|beef|cattle|pecuari\w*"
    r"|desmat\w*|exposic\w*|fob|volume\w*|tonelad\w*|emiss\w*|co2\w*|area|produtividad\w*|produc\w*"
    r"|export\w*|import\w*|trading\w*|destin\w*|pais\w*|portos?|municip\w*|estad\w*|uf|bioma\w*"
    r"|compromiss\w*|zdc|rtrs|frigorific\w*|armaze\w*|instalac\w*"
    r"|brasil|mundo|mundial|global|china|europa|uniao\s+europeia|estados\s+unidos"
    r"|amazonia|cerrado|mata\s+atlantica|pantanal|pampa|caatinga"
    r"|mato\s+grosso|para|goias|bahia|parana|rio\s+grande|maranhao|tocantins|piaui|rondonia|acre"
    r"|sorriso|sao\s+felix|altamira|maraba"
    r"|20[0-2]\d"
    r")\b",
    re.IGNORECASE,
)

_CLEAR_QUESTION_RE = re.compile(
    r"(?:"
    r"\?$"
    r"|\b(?:qual|quais|quanto|quantos|quantas|como|onde|quando|quem|por\s+que|porque|o\s+que|oque"
    r"|explique|resuma|defina|definicao|conceito|significa|liste|ranking|compare|calcule)\b"
    r")",
    re.IGNORECASE,
)

_AMBIGUOUS_VISUAL_HINT_RE = re.compile(
    r"\b(?:panorama\s+visual|visao\s+executiva|apresentacao\s+visual|destaque\s+apenas|foque\s+apenas)\b",
    re.IGNORECASE,
)

_METRIC_COLUMN_HINTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\b(?:fob|receita|dolar\w*|valor\s+export\w*)\b"), ("fob", "usd")),
    (re.compile(r"\b(?:volume\w*|tonelad\w*)\b"), ("volume",)),
    (re.compile(r"\b(?:exposic\w*|desmat\w*)\b"), ("exposure", "deforestation")),
    (re.compile(r"\b(?:emiss\w*|co2\w*)\b"), ("co2", "emission")),
    (re.compile(r"\b(?:compromiss\w*|zdc)\b"), ("zdc", "commitment")),
    (re.compile(r"\b(?:produtividad\w*|yield)\b"), ("yield",)),
)


# --- Schema para fallback estruturado no LLM -------------------------------------

INTENT_TOOL_SCHEMA = {
    "type": "object",
    "required": ["intent", "domain", "use_previous_results", "needs_new_data", "clarification"],
    "properties": {
        "intent": {"type": "string", "enum": list(ALLOWED_INTENTS)},
        "domain": {"type": "string", "enum": list(ALLOWED_DOMAINS)},
        "use_previous_results": {"type": "boolean"},
        "needs_new_data": {"type": "boolean"},
        "clarification": {"type": ["string", "null"]},
        "assumption": {"type": ["string", "null"]},
    },
}

ORCHESTRATOR_INTENT_PROMPT = """\
Você é o Orquestrador de intenções do chat analítico Trase RAG (cadeias brasileiras da soja, \
carne bovina e legislação ambiental).
Classifique a mensagem do usuário em UMA intenção:
- `question`: pergunta normal sobre dados, metodologia ou legislação (caminho seguro na dúvida).
- `dashboard`: pedido para criar um painel/gráfico analítico novo. Se o pedido for vago demais \
(ex.: apenas "faz um dashboard" sem tema nem dados anteriores), preencha `clarification` com uma \
pergunta curta oferecendo 2 ou 3 opções concretas.
- `dashboard_edit`: pedido para alterar um componente do painel já existente na sessão.
- `map_edit`: pedido para exibir ou alterar um mapa geográfico.
- `mixed`: pergunta que exige resposta textual/jurídica E construção de um dashboard na mesma mensagem.
"""


def _extract_session_flags(
    session=None,
    *,
    has_spec: bool | None = None,
    has_store_data: bool | None = None,
    store_columns: set[str] | None = None,
) -> tuple[bool, bool, set[str]]:
    spec_flag = bool(has_spec) if has_spec is not None else False
    data_flag = bool(has_store_data) if has_store_data is not None else False
    cols: set[str] = {c.lower() for c in (store_columns or set())}

    if session is not None:
        if has_spec is None:
            spec_flag = getattr(session, "current_spec", None) is not None
        store = getattr(session, "result_store", None) or getattr(session, "store", None)
        sid = getattr(session, "session_id", None)
        if store is not None and sid:
            datasets = store.get_datasets(sid, non_empty_only=True)
            if has_store_data is None:
                data_flag = bool(datasets)
            if store_columns is None:
                for ds in datasets:
                    cols.update(str(c).lower() for c in ds.df.columns)

    return spec_flag, data_flag, cols


def _build_assumption(norm_msg: str, domain: str) -> str | None:
    if _WORLD_SCOPE_RE.search(norm_msg):
        chain_label = (
            "de soja" if domain == "soy"
            else "de carne bovina" if domain == "beef"
            else "agropecuárias"
        )
        return (
            f"Premissa assumida: como os dados do Trase neste sistema cobrem apenas cadeias brasileiras, "
            f"considerei as exportações brasileiras {chain_label} por país de destino no ano mais recente "
            f"disponível (não há dados de produção mundial de outros países)."
        )
    return None


# Só o nome da cadeia não é recorte: "faz um gráfico da soja" ainda precisa de métrica, lugar ou ano.
_COMMODITY_ONLY_RE = re.compile(
    r"\b(?:cadeia|soja|soy|carne|bovin[oa]s?|gado|beef|cattle|pecuaria)\b",
    re.IGNORECASE,
)


def _is_vague_dashboard_request(norm_msg: str, has_store_data: bool) -> bool:
    if _DEICTIC_STORE_RE.search(norm_msg):
        return not has_store_data
    sem_cadeia = _COMMODITY_ONLY_RE.sub(" ", norm_msg)
    if _SUBSTANTIVE_TOPIC_RE.search(sem_cadeia):
        return False
    tokens = re.findall(r"[a-z0-9]+", sem_cadeia)
    remaining = [t for t in tokens if t not in _VAGUE_FILLER_WORDS]
    return len(remaining) == 0


def _edit_needs_new_data(norm_msg: str, store_columns: set[str]) -> bool:
    if not _ADD_VERB_RE.search(norm_msg):
        return False
    if not store_columns:
        return True
    matched_any_metric = False
    for pattern, col_substrings in _METRIC_COLUMN_HINTS:
        if pattern.search(norm_msg):
            matched_any_metric = True
            if not any(any(sub in col for sub in col_substrings) for col in store_columns):
                return True
    return not matched_any_metric


def classify_intent_deterministic(
    message: str,
    *,
    domain: str | None = None,
    has_spec: bool = False,
    has_store_data: bool = False,
    store_columns: set[str] | None = None,
) -> OrchestrationDecision | None:
    """Tenta decidir a intenção apenas por regras rápidas; devolve `None` se genuinamente ambíguo."""
    norm = _normalize(message)
    resolved_domain = resolve_domain(message, domain)

    if not norm:
        return OrchestrationDecision(
            intent="question",
            domain=resolved_domain,
            use_previous_results=False,
            needs_new_data=False,
            decided_by="rules",
        )

    # 1. Pedido de mapa (exceto menção puramente tabular ao "mapa logístico" sem pedido de mapa visual)
    has_map = bool(_MAP_RE.search(norm))
    is_only_logistics_table = bool(
        _LOGISTICS_MAP_DATA_RE.search(norm)
        and not re.search(r"\b(?:num|no|em|um)\s+mapa(?!\s+logistic)\b", norm)
    )
    if has_map and not is_only_logistics_table:
        return OrchestrationDecision(
            intent="map_edit",
            domain=resolved_domain,
            use_previous_results=has_store_data,
            needs_new_data=False,
            decided_by="rules",
        )

    has_dash_noun = bool(_DASHBOARD_NOUN_RE.search(norm))
    has_edit_verb = bool(_EDIT_VERB_RE.search(norm))
    has_edit_target = bool(_EDIT_COMPONENT_TARGET_RE.search(norm))
    has_deictic = bool(_DEICTIC_STORE_RE.search(norm))

    # 2. Edição de painel: verbo de edição + alvo de componente
    is_unambiguous_visual_target = has_dash_noun or bool(
        re.search(r"\b(?:barras?|kpis?|cart(?:ao|oes)|cards?)\b", norm)
    )
    if has_edit_verb and (has_edit_target if has_spec else is_unambiguous_visual_target):
        if has_spec:
            needs_new = _edit_needs_new_data(norm, store_columns or set())
            return OrchestrationDecision(
                intent="dashboard_edit",
                domain=resolved_domain,
                use_previous_results=not needs_new and has_store_data,
                needs_new_data=needs_new or not has_store_data,
                decided_by="rules",
            )
        # R6: dashboard_edit sem spec na sessão -> tratar como dashboard
        use_prev = bool(has_store_data and (has_deictic or not _SUBSTANTIVE_TOPIC_RE.search(norm)))
        clarif = (
            DEFAULT_CLARIFICATION_MESSAGE
            if (not use_prev and not _SUBSTANTIVE_TOPIC_RE.search(norm))
            else None
        )
        return OrchestrationDecision(
            intent="dashboard",
            domain=resolved_domain,
            use_previous_results=use_prev,
            needs_new_data=not use_prev,
            clarification=clarif,
            assumption=_build_assumption(norm, resolved_domain) if not clarif else None,
            decided_by="rules",
        )

    # 3. Pedido explícito envolvendo painel/gráfico/visualização
    if has_dash_noun:
        # Misto: legislação + dashboard, ou pergunta explícita seguida de "e monte/faça ..."
        if _LAW_TERMS_RE.search(norm) or _MIXED_QUESTION_CONJ_RE.search(norm):
            return OrchestrationDecision(
                intent="mixed",
                domain="mixed" if _LAW_TERMS_RE.search(norm) else resolved_domain,
                use_previous_results=True,
                needs_new_data=False,
                assumption=_build_assumption(norm, resolved_domain),
                decided_by="rules",
            )

        if _is_vague_dashboard_request(norm, has_store_data):
            return OrchestrationDecision(
                intent="dashboard",
                domain=resolved_domain,
                use_previous_results=False,
                needs_new_data=False,
                clarification=DEFAULT_CLARIFICATION_MESSAGE,
                decided_by="rules",
            )

        use_prev = bool(has_deictic and has_store_data)
        return OrchestrationDecision(
            intent="dashboard",
            domain=resolved_domain,
            use_previous_results=use_prev,
            needs_new_data=not use_prev,
            assumption=_build_assumption(norm, resolved_domain),
            decided_by="rules",
        )

    # 4. Caso ambíguo para eventual desempate via LLM estruturado
    if _AMBIGUOUS_VISUAL_HINT_RE.search(norm):
        return None

    # 5. Perguntas comuns de dados, conceitos ou leis -> caminho seguro `question` sem chamar LLM
    if _CLEAR_QUESTION_RE.search(norm) or _SUBSTANTIVE_TOPIC_RE.search(norm) or _LAW_TERMS_RE.search(norm):
        return OrchestrationDecision(
            intent="question",
            domain=resolved_domain,
            use_previous_results=False,
            needs_new_data=False,
            decided_by="rules",
        )

    # Mensagens curtas/conversacionais sem gatilho visual também seguem para `question` sem custo extra,
    # exceto quando há spec ativa e um imperativo curto ambíguo (ex.: "filtre só Mato Grosso").
    if has_spec and re.match(r"^(?:filtr\w*|mostr\w*\s+so|deix\w*\s+so|foca|foque)\b", norm):
        return None

    return OrchestrationDecision(
        intent="question",
        domain=resolved_domain,
        use_previous_results=False,
        needs_new_data=False,
        decided_by="rules",
    )


def classify_intent_llm(
    message: str,
    *,
    domain: str | None = None,
    has_spec: bool = False,
    has_store_data: bool = False,
) -> OrchestrationDecision:
    """Executa 1 chamada LLM estruturada (JSON schema) para classificar casos ambíguos."""
    resolved_domain = resolve_domain(message, domain)
    user_msg = (
        f"Mensagem do usuário: {message}\n"
        f"Domínio sugerido pelo roteador: {resolved_domain}\n"
        f"Existe DashboardSpec ativa na sessão: {'sim' if has_spec else 'não'}\n"
        f"Existem DataFrames salvos no Result Store da sessão: {'sim' if has_store_data else 'não'}"
    )
    payload, in_tok, out_tok = call_structured_llm(
        system=ORCHESTRATOR_INTENT_PROMPT,
        user_content=user_msg,
        tool_name="emit_intent",
        tool_description="Classifica a intenção da mensagem no pipeline multiagente.",
        input_schema=INTENT_TOOL_SCHEMA,
        max_tokens=512,
    )

    intent = str(payload.get("intent") or "question").strip().lower()
    if intent not in ALLOWED_INTENTS:
        intent = "question"
    if intent == "dashboard_edit" and not has_spec:
        intent = "dashboard"

    dom = str(payload.get("domain") or resolved_domain).strip().lower()
    if dom not in ALLOWED_DOMAINS or (domain and domain != "auto"):
        dom = resolved_domain

    use_prev = bool(payload.get("use_previous_results", False))
    needs_new = bool(payload.get("needs_new_data", True))
    if intent == "mixed":
        use_prev = True
    elif use_prev and not has_store_data:
        use_prev = False
        needs_new = True

    clarif_raw = payload.get("clarification")
    clarif = str(clarif_raw).strip() if isinstance(clarif_raw, str) and clarif_raw.strip() else None

    assump_raw = payload.get("assumption")
    assump = (
        str(assump_raw).strip()
        if isinstance(assump_raw, str) and assump_raw.strip()
        else _build_assumption(_normalize(message), dom)
    )

    return OrchestrationDecision(
        intent=intent,
        domain=dom,
        use_previous_results=use_prev,
        needs_new_data=needs_new,
        clarification=clarif,
        assumption=assump if not clarif else None,
        decided_by="llm",
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def classify_intent(
    message: str,
    *,
    session=None,
    domain: str | None = None,
    has_spec: bool | None = None,
    has_store_data: bool | None = None,
    store_columns: set[str] | None = None,
    use_llm: bool = True,
) -> OrchestrationDecision:
    """Ponto de entrada do Orquestrador: regras determinísticas primeiro; LLM só se necessário."""
    spec_flag, data_flag, cols = _extract_session_flags(
        session,
        has_spec=has_spec,
        has_store_data=has_store_data,
        store_columns=store_columns,
    )

    det = classify_intent_deterministic(
        message,
        domain=domain,
        has_spec=spec_flag,
        has_store_data=data_flag,
        store_columns=cols,
    )
    if det is not None:
        return det

    if use_llm:
        try:
            return classify_intent_llm(
                message,
                domain=domain,
                has_spec=spec_flag,
                has_store_data=data_flag,
            )
        except Exception:
            pass

    # Caminho seguro: na dúvida (ou sem LLM disponível), cai no Agente de Dados/RAG atual (`question`)
    return OrchestrationDecision(
        intent="question",
        domain=resolve_domain(message, domain),
        use_previous_results=False,
        needs_new_data=False,
        decided_by="rules",
    )

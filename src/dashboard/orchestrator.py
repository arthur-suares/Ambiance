"""Planejador e coordenador interno do subsistema de dashboards (`src/dashboard/`).

Nota de arquitetura: este módulo NÃO é o orquestrador de intenções do chat
(que fica em `src/pipeline/orchestrator.py`). Aqui o papel é planejar recortes
analíticos (`create_plan`), coordenar `run_data_agent`, `propose_dashboard_spec` /
`edit_dashboard_spec` e `review_dashboard`, e renderizar o HTML final.

Fluxo:
1. `generate_dashboard`: fluxo autônomo (usado pela CLI `python -m src.cli dashboard "..."`).
2. `build_dashboard_from_store`: fluxo integrado ao pipeline de sessão (`ResultStore`),
   reaproveitando `[D1..Dn]` já salvos no chat (`use_previous_results=True`) e suportando
   edição incremental da `DashboardSpec` atual (`edit=True`).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
import re
import time
import unicodedata

from src.config import DASHBOARD_OUTPUT_DIR, DUCKDB_PATH
from src.dashboard._llm import call_structured_llm
from src.dashboard.chart_intent import CHOICE_BY_INTENT, ChartChoice, apply_share_guards, kinds_for_prompt
from src.dashboard.chart_intent import interpret as interpret_chart
from src.dashboard.dashboard_agent import (
    build_dashboard_html,
    edit_dashboard_spec,
    propose_dashboard_spec,
    revise_dashboard_spec,
)
from src.dashboard.data_agent import run_data_agent
from src.dashboard.data_base import declare_bases
from src.dashboard.law_agent import build_law_widgets, run_law_agent
from src.dashboard.dimensions import (
    DIMENSIONS,
    GLOSSARY_PROMPT,
    column_matches,
    columns_cover,
    detect_dimension,
    dimension_line,
)
from src.dashboard.reviewer_agent import review_dashboard
from src.dashboard.messages import user_message
from src.dashboard.validator import find_illegality_claim, is_law_sourced, spec_has_law_source, widget_claims
from src.dashboard.schemas import (
    ALLOWED_WIDGET_KINDS,
    DashboardRunResult,
    DashboardSpec,
    DataRequest,
    MAX_REVISIONS,
    OrchestratorPlan,
    ReviewResult,
)
from src.rag import resolve_domain
from src.soy import queries as soy_queries

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM_PROMPT = """\
Você é o Agente Orquestrador de dashboards analíticos do Trase (cadeias da carne bovina e da soja \
brasileiras). Seu papel é decompor a pergunta do usuário num plano enxuto de consultas SQL e \
componentes visuais complementares.

Diretrizes de planejamento:
- Planeje de 2 a 4 recortes de dados (`data_requests`) que juntos formem um bom painel executivo \
(ex.: indicadores de destaque para KPIs, ranking para gráfico de barras, série histórica para linha, \
ou detalhamento para tabela).
- Tipos de visual suportados nesta versão (use só estes; sem mapas):
{kinds}
- {choice_by_intent}
- Se o usuário pediu um tipo de gráfico, o recorte principal DEVE usar esse tipo em `suggested_visual`.
- Respeite a disponibilidade dos bancos informada no contexto (`trase.duckdb` para carne bovina; \
`soy.duckdb` para soja). Se a pergunta não especificar a cadeia, priorize a cadeia disponível ou \
indique claramente no objetivo.
- Registre em `methodological_notes` os cuidados essenciais do Trase aplicáveis à pergunta \
(ex.: exposição ao desmatamento tem janela de 5 anos e não pode ser somada entre anos; rankings \
municipais cobrem a origem rastreada sem 'UNKNOWN'; usar ano mais recente se nenhum foi pedido; \
na soja, o destino BRAZIL é processamento doméstico e não conta como país importador).
- Use o glossário abaixo para saber por qual coluna agrupar. Se a mensagem trouxer "DIMENSÃO PEDIDA", \
o recorte principal agrupa por essa coluna.
{glossary}
- Defina UMA base comum em `common_base` (ano, origem rastreada ou todas as origens, só exportação ou \
cadeia inteira) e descreva todos os recortes com essa mesma base: KPIs, pizza, ranking e tabela devem \
usar o mesmo filtro de ano, de origem e o mesmo denominador. Só a série histórica pode cobrir vários anos.
""".format(kinds=kinds_for_prompt(), choice_by_intent=CHOICE_BY_INTENT, glossary=GLOSSARY_PROMPT)

PLAN_TOOL_SCHEMA = {
    "type": "object",
    "required": ["dashboard_goal", "data_requests", "methodological_notes"],
    "properties": {
        "dashboard_goal": {
            "type": "string",
            "description": "Objetivo analítico do dashboard em uma frase.",
        },
        "data_requests": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["request_id", "description", "suggested_visual"],
                "properties": {
                    "request_id": {"type": "string", "description": "Ex.: Q1, Q2, Q3."},
                    "description": {"type": "string", "description": "Recorte de dados a consultar no DuckDB."},
                    "suggested_visual": {"type": "string", "enum": list(ALLOWED_WIDGET_KINDS)},
                    "database_hint": {"type": "string", "enum": ["beef", "soy", "auto"]},
                },
            },
        },
        "methodological_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "common_base": {
            "type": "object",
            "description": "Base comum a todos os recortes do painel.",
            "properties": {
                "year": {"type": "integer", "description": "Ano de referência dos recortes de um único ano."},
                "origin": {"type": "string", "enum": ["rastreada", "toda"]},
                "flow": {"type": "string", "enum": ["exportacao", "cadeia"]},
            },
        },
    },
}


def slugify_question(text: str, max_len: int = 48) -> str:
    norm = unicodedata.normalize("NFKD", text or "dashboard")
    ascii_text = norm.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return (slug[:max_len].rstrip("_")) or "dashboard"


def default_output_path(question: str, output_dir: Path | None = None) -> Path:
    base = output_dir or DASHBOARD_OUTPUT_DIR
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base / f"{stamp}_{slugify_question(question)}.html"


def create_plan(question: str, domain: str, chart: ChartChoice | None = None) -> OrchestratorPlan:
    """Usa o LLM para definir quais recortes de dados e tipos de gráficos comporão o painel."""
    beef_ok = DUCKDB_PATH.exists()
    soy_ok = soy_queries.is_available()
    user_msg = (
        f"Pergunta do usuário: {question}\n"
        f"Domínio sugerido pelo roteador: {domain}\n"
        f"Bancos disponíveis: carne bovina (trase.duckdb)={'sim' if beef_ok else 'não'}, "
        f"soja (soy.duckdb)={'sim' if soy_ok else 'não'}."
    )
    if chart is not None:
        user_msg += "\n" + chart.prompt_line()
    dim = detect_dimension(question)
    if dim is not None:
        user_msg += "\n" + dimension_line(dim)
    payload, in_tok, out_tok = call_structured_llm(
        system=ORCHESTRATOR_SYSTEM_PROMPT,
        user_content=user_msg,
        tool_name="emit_plan",
        tool_description="Define o plano de consultas e visuais do dashboard.",
        input_schema=PLAN_TOOL_SCHEMA,
        max_tokens=1500,
    )

    requests: list[DataRequest] = []
    for idx, item in enumerate(payload.get("data_requests") or [], start=1):
        if not isinstance(item, dict) or not item.get("description"):
            continue
        vis = str(item.get("suggested_visual") or "bar").lower()
        if vis not in ALLOWED_WIDGET_KINDS:
            vis = "bar"
        requests.append(DataRequest(
            request_id=str(item.get("request_id") or f"Q{idx}"),
            description=str(item["description"]).strip(),
            suggested_visual=vis,
            database_hint=str(item.get("database_hint") or "auto"),
        ))
    if not requests:
        requests.append(DataRequest("Q1", question, "table", "auto"))
    # O tipo pedido pelo usuário fica guardado no plano, não ao gosto do LLM.
    if chart is not None and chart.kind in ALLOWED_WIDGET_KINDS and not any(
        r.suggested_visual == chart.kind for r in requests
    ):
        requests[0].suggested_visual = chart.kind

    notes = [str(n).strip() for n in (payload.get("methodological_notes") or []) if str(n).strip()]
    return OrchestratorPlan(
        question=question,
        domain=domain,
        dashboard_goal=str(payload.get("dashboard_goal") or question).strip(),
        data_requests=requests,
        methodological_notes=notes,
        requested_chart=chart,
        common_base=_parse_common_base(payload.get("common_base")),
        requested_dimension=dim.key if dim is not None else None,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def _main_kind(spec: DashboardSpec | None) -> str | None:
    if spec is None:
        return None
    return next((w.kind for w in spec.widgets if w.valid and w.kind != "kpi"), None)


def _finish_chart_choice(spec: DashboardSpec, plan: OrchestratorPlan, datasets) -> None:
    """A3/A4: troca pizza enganosa pelo gráfico adequado e dá UM aviso curto quando o pedido
    não pôde ser atendido como veio."""
    apply_share_guards(spec, datasets)
    chart = plan.requested_chart
    if isinstance(chart, ChartChoice) and chart.notice and chart.notice not in spec.warnings:
        spec.warnings.insert(0, chart.notice)


def _apply_final_review_isolation(spec: DashboardSpec, final_review: ReviewResult, question: str) -> None:
    """Após esgotar as rodadas de correção, isola apenas os gráficos reprovados sem abortar o painel."""
    if not spec.title.strip():
        spec.title = f"Dashboard — {question}"

    # Só problemas bloqueantes ocultam um gráfico; observações ficam no log (já registradas pelo revisor).
    # A tela recebe uma frase simples escolhida pelo tipo do problema, nunca o texto técnico.
    codes_by_widget: dict[str, list[str]] = {}
    for issue in final_review.issues:
        if not issue.blocking or issue.code == "alegacao" and issue.widget_id:
            continue  # alegação em título de gráfico: o texto é reescrito, o gráfico fica
        if issue.widget_id:
            codes_by_widget.setdefault(issue.widget_id, []).append(issue.code)
        elif issue.code != "alegacao":  # alegação em texto: reescrita em _omit_unresolved_claims
            msg = user_message([issue.code])
            if msg not in spec.warnings:
                spec.warnings.append(msg)

    for w in spec.widgets:
        if w.id in codes_by_widget:
            w.valid = False
            w.validation_codes = codes_by_widget[w.id]
            w.validation_error = user_message(w.validation_codes)


OMITTED_CLAIM_WARNING = "Reescrevi um texto do painel para falar apenas de exposição ao desmatamento."


def _neutral_widget_title(w) -> str:
    cols = " ".join([*(w.y or []), w.column or ""]).lower()
    return "Exposição ao desmatamento" if ("expos" in cols or "defor" in cols or "desmat" in cols) else "Gráfico do painel"


def _neutral_source(w, ds) -> str:
    tag = f"[{w.dataset_id}]"
    label = (ds.source_label if ds is not None else "") or "Fonte dos dados"
    return label if tag in label else f"{label} {tag}"


def _omit_unresolved_claims(spec: DashboardSpec, question: str, datasets=None) -> None:
    """Reescreve textos com alegação indevida que sobraram após as rodadas de revisão.

    - Título/subtítulo do painel ou de um gráfico: o texto é trocado por um neutro, o gráfico continua
      (os dados estão certos) e o leitor recebe UMA frase simples avisando.
    - Textos curtos (rótulo e unidade de coluna, unidade, fonte, grupo): voltam ao padrão (nome técnico
      da coluna, sem unidade, fonte do próprio dataset, sem grupo).
    - Avisos que vieram do próprio revisor e citam o termo: descartados em silêncio (ficam no log).
    O nome oficial "Lei de Crimes Ambientais" só é liberado em componente de leis com dataset de leis.
    O monitor de saída continua com as mesmas regras e bloqueia o que escapar.
    """
    by_id = {d.dataset_id: d for d in (datasets or [])}
    rewritten = False
    law_panel = spec_has_law_source(spec, by_id)
    if find_illegality_claim(spec.title, law_source=law_panel):
        fallback = f"Dashboard — {question}" if question else ""
        spec.title = (fallback if fallback and not find_illegality_claim(fallback, law_source=law_panel)
                      else "Painel Trase")
        rewritten = True
    if find_illegality_claim(spec.subtitle, law_source=law_panel):
        spec.subtitle = ""
        rewritten = True
    for w in spec.widgets:
        ds = by_id.get(w.dataset_id)
        for _label, attr, key, _claim in widget_claims(w, is_law_sourced(w, ds)):
            rewritten = True
            if attr == "title":
                w.title = _neutral_widget_title(w)
            elif attr == "subtitle":
                w.subtitle = ""
            elif attr == "unit":
                w.unit = ""
            elif attr == "source":
                w.source = _neutral_source(w, ds)
            elif attr == "group":
                w.group = None
            elif attr == "column_labels" and key is not None:
                w.column_labels.pop(key, None)  # volta ao nome da coluna
            elif attr == "column_units" and key is not None:
                w.column_units.pop(key, None)
        if w.validation_error and find_illegality_claim(w.validation_error):
            w.validation_error = user_message(w.validation_codes)
    dropped = [msg for msg in spec.warnings if find_illegality_claim(msg, law_source=law_panel)]
    for msg in dropped:
        logger.info("Aviso descartado por conter termo proibido: %s", msg)
    kept = [msg for msg in spec.warnings if msg not in dropped]
    if rewritten and OMITTED_CLAIM_WARNING not in kept:
        kept.append(OMITTED_CLAIM_WARNING)
    spec.warnings = kept


def _finish_dimension(spec: DashboardSpec, plan: OrchestratorPlan, question: str, datasets=None) -> None:
    """A3: se o painel não agrupou pela dimensão pedida, avisa em uma frase curta; se agrupou por
    município, o subtítulo diz que é o município de ORIGEM e que cobre só a origem rastreada."""
    dim = DIMENSIONS.get(plan.requested_dimension or "")
    if dim is None:
        return
    from src.dashboard.reviewer_agent import dimension_widgets
    matched, grouped = dimension_widgets(spec, dim, datasets)
    if grouped and not matched:
        col = grouped[0].x or next(iter(grouped[0].columns), "")
        other = next((d for d in DIMENSIONS.values() if d.key != dim.key and column_matches(col, d)), None)
        if other is not None:  # sem saber a outra dimensão, não afirma nada (pode ser um apelido do SQL)
            msg = f"Não consegui montar por {dim.label}; mostrei por {other.label}."
            if msg not in spec.warnings:
                spec.warnings.append(msg)
        return
    if dim.key == "municipio" and matched:
        q = question.lower()
        cadeia = "da soja" if plan.domain == "soy" or "soja" in q else (
            "da carne bovina" if plan.domain == "beef" or "carne" in q else "do produto")
        exportada = " exportada" if re.search(r"export", q) else ""
        frase = f"Município de origem {cadeia}{exportada}; cobre só a origem rastreada."
        w = matched[0]
        if "origem rastreada" not in (w.subtitle or ""):
            w.subtitle = f"{frase} {w.subtitle}".strip() if w.subtitle else frase


LAW_PANEL_TITLE = "Legislação ambiental: o que dizem as normas"
NO_LAW_FACTS_MESSAGE = "Não encontrei nas leis do acervo um trecho com essa informação."


def _attach_law_part(spec: DashboardSpec, question: str, datasets: list, start_index: int) -> tuple[int, int]:
    """G1/G6/G8: acrescenta a parte das leis (seção "Base legal") ao painel. Os widgets são montados em
    código; sem acervo, o painel diz isso em português simples e mantém o resto."""
    usados = [int(d.dataset_id[1:]) for d in datasets if str(d.dataset_id)[1:].isdigit()]
    inicio = max([start_index - 1, *usados]) + 1
    res = run_law_agent(question, start_index=inicio)
    widgets, extra = build_law_widgets(res)
    datasets.extend([*res.datasets, *extra])
    spec.widgets.extend(widgets)
    if not res.available:
        spec.warnings.append(res.notes)
    else:
        if res.notes:
            spec.warnings.append(res.notes)
        if not widgets:
            spec.warnings.append(NO_LAW_FACTS_MESSAGE)
    return res.input_tokens, res.output_tokens


def _parse_common_base(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    try:
        if raw.get("year"):
            out["year"] = int(raw["year"])
    except (TypeError, ValueError):
        pass
    if raw.get("origin") in ("rastreada", "toda"):
        out["origin"] = raw["origin"]
    if raw.get("flow") in ("exportacao", "cadeia"):
        out["flow"] = raw["flow"]
    return out


def generate_dashboard(
    question: str,
    *,
    domain: str | None = None,
    output_path: Path | str | None = None,
    save: bool = True,
) -> DashboardRunResult:
    """Executa o fluxo completo entre Orquestrador, Dados, Dashboard e Revisor."""
    start = time.perf_counter()
    resolved_domain = resolve_domain(question, domain)

    chart, c_in, c_out = interpret_chart(question)
    law_only = resolved_domain == "law"
    if law_only:
        plan = OrchestratorPlan(question=question, domain="law", dashboard_goal=LAW_PANEL_TITLE,
                                requested_chart=chart)
        total_in, total_out = c_in, c_out
        datasets = []
        data_res = None
    else:
        plan = create_plan(question, resolved_domain, chart)
        total_in = plan.input_tokens + c_in
        total_out = plan.output_tokens + c_out
        data_res = run_data_agent(question, plan)
        total_in += data_res.input_tokens
        total_out += data_res.output_tokens
        datasets = list(data_res.datasets)

    reviews: list[ReviewResult] = []
    revisions_used = 0

    if law_only:
        spec = DashboardSpec(title=LAW_PANEL_TITLE, widgets=[], warnings=[])
    elif not datasets:
        reason = (data_res.notes if data_res else "") or "Nenhum conjunto de dados retornou linhas para esta pergunta."
        spec = DashboardSpec(
            title=f"Dashboard — {question}",
            subtitle=plan.dashboard_goal,
            widgets=[],
            warnings=[reason],
        )
    else:
        spec, d_in, d_out = propose_dashboard_spec(question, plan, datasets)
        total_in += d_in
        total_out += d_out

        for attempt in range(MAX_REVISIONS + 1):
            review = review_dashboard(question, spec, datasets, requested=plan.requested_chart,
                                      dimension=plan.requested_dimension)
            reviews.append(review)
            total_in += review.input_tokens
            total_out += review.output_tokens

            if review.approved:
                break

            if attempt < MAX_REVISIONS:
                revisions_used += 1
                spec, r_in, r_out = revise_dashboard_spec(question, plan, datasets, spec, review)
                total_in += r_in
                total_out += r_out
            else:
                _apply_final_review_isolation(spec, review, question)

    if law_only or resolved_domain == "mixed":  # G3: leis -> agente de leis; misto -> os dois
        l_in, l_out = _attach_law_part(spec, question, datasets, 1)
        total_in += l_in
        total_out += l_out
    declare_bases(spec, datasets)  # A4: bases diferentes -> cada widget diz a base que usou
    _finish_dimension(spec, plan, question, datasets)
    _finish_chart_choice(spec, plan, datasets)
    _omit_unresolved_claims(spec, question, datasets)
    html_content = build_dashboard_html(spec, datasets, question=question)

    saved_path: Path | None = None
    if save:
        saved_path = Path(output_path).resolve() if output_path else default_output_path(question)
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_text(html_content, encoding="utf-8")

    return DashboardRunResult(
        question=question,
        domain=resolved_domain,
        html=html_content,
        output_path=saved_path,
        plan=plan,
        datasets=datasets,
        spec=spec,
        reviews=reviews,
        revisions_used=revisions_used,
        input_tokens=total_in,
        output_tokens=total_out,
        seconds=round(time.perf_counter() - start, 2),
    )


def build_dashboard_from_store(
    question: str,
    session,
    *,
    domain: str | None = None,
    use_previous_results: bool = True,
    edit: bool = False,
    needs_new_data: bool = False,
    goal_hint: str | None = None,
    output_path: Path | str | None = None,
    output_dir: Path | None = None,
    save: bool = True,
    trace_hook=None,
) -> DashboardRunResult:
    """Monta ou edita um dashboard integrando-se ao `ResultStore` da sessão (R3 e R4)."""
    start = time.perf_counter()
    resolved_domain = resolve_domain(question, domain)

    sid = getattr(session, "session_id", None) or "default"
    store = getattr(session, "result_store", None) or getattr(session, "store", None)
    if store is None:
        raise ValueError("O objeto `session` precisa fornecer `result_store` (ou `store`).")

    current_spec: DashboardSpec | None = getattr(session, "current_spec", None)
    is_edit = bool(edit and current_spec is not None)

    stored_datasets = store.get_datasets(sid, non_empty_only=True)
    dim = detect_dimension(question)
    # A1: os dados guardados só servem se tiverem a dimensão pedida (ex.: município, não empresa).
    dim_missing = bool(dim is not None and stored_datasets
                       and not any(columns_cover(d.df.columns, dim) for d in stored_datasets))
    can_reuse_store = (
        bool(stored_datasets)
        and not needs_new_data
        and not dim_missing
        and (is_edit or use_previous_results)
    )

    main_kind = _main_kind(current_spec) if is_edit else None
    chart, total_in, total_out = interpret_chart(question, current_kind=main_kind)
    data_notes = ""

    law_only = resolved_domain == "law" and not is_edit
    if law_only:
        plan = OrchestratorPlan(question=question, domain="law", dashboard_goal=LAW_PANEL_TITLE,
                                data_requests=[], requested_chart=chart)
        datasets = []
    elif can_reuse_store:
        goal_txt = goal_hint or (current_spec.title if is_edit and current_spec else question)
        plan = OrchestratorPlan(
            question=question,
            domain=resolved_domain,
            dashboard_goal=goal_txt,
            data_requests=[],
            requested_chart=chart,
            requested_dimension=dim.key if dim is not None else None,
        )
        datasets = list(stored_datasets)
    else:
        t_data = time.perf_counter()
        plan = create_plan(question, resolved_domain, chart)
        plan.requested_chart = plan.requested_chart or chart
        if goal_hint:
            plan.methodological_notes.append(goal_hint)
        total_in += plan.input_tokens
        total_out += plan.output_tokens

        next_idx = store.last_index(sid) + 1
        data_res = run_data_agent(question, plan, start_index=next_idx)
        total_in += data_res.input_tokens
        total_out += data_res.output_tokens
        data_notes = data_res.notes

        for ds in data_res.datasets:
            store.put(sid, ds)

        if trace_hook is not None:
            tools_used = ",".join(c.name for c in data_res.tool_calls) or "run_data_agent"
            trace_hook("data_agent", {
                "latency_s": round(time.perf_counter() - t_data, 3),
                "input_tokens": plan.input_tokens + data_res.input_tokens,
                "output_tokens": plan.output_tokens + data_res.output_tokens,
                "tool": tools_used,
                "verdict": "ok" if data_res.datasets else "empty",
            })

        if (is_edit or use_previous_results) and not dim_missing:
            datasets = store.get_datasets(sid, non_empty_only=True)
        else:
            datasets = list(data_res.datasets)

    reviews: list[ReviewResult] = []
    revisions_used = 0

    if law_only:
        spec = DashboardSpec(title=LAW_PANEL_TITLE, widgets=[], warnings=[])
    elif not datasets:
        reason = data_notes or "Nenhum conjunto de dados retornou linhas para esta pergunta."
        spec = DashboardSpec(
            title=f"Dashboard — {question}",
            subtitle=plan.dashboard_goal,
            widgets=[],
            warnings=[reason],
        )
    else:
        t_dsh = time.perf_counter()
        if is_edit and current_spec is not None:
            spec, d_in, d_out = edit_dashboard_spec(question, current_spec, datasets, plan)
            dsh_tool = "edit_dashboard_spec"
        else:
            spec, d_in, d_out = propose_dashboard_spec(question, plan, datasets)
            dsh_tool = "propose_dashboard_spec"
        total_in += d_in
        total_out += d_out
        if trace_hook is not None:
            trace_hook("dashboard_agent", {
                "latency_s": round(time.perf_counter() - t_dsh, 3),
                "input_tokens": d_in,
                "output_tokens": d_out,
                "tool": dsh_tool,
                "verdict": "ok",
            })

        for attempt in range(MAX_REVISIONS + 1):
            t_val = time.perf_counter()
            review = review_dashboard(question, spec, datasets, requested=plan.requested_chart,
                                      dimension=plan.requested_dimension)
            reviews.append(review)
            total_in += review.input_tokens
            total_out += review.output_tokens
            if trace_hook is not None:
                trace_hook("validator", {
                    "latency_s": round(time.perf_counter() - t_val, 3),
                    "input_tokens": review.input_tokens,
                    "output_tokens": review.output_tokens,
                    "tool": "check_methodological_llm" if review.llm_called else "check_deterministic",
                    "verdict": "approved" if review.approved else "rejected",
                })

            if review.approved:
                break

            if attempt < MAX_REVISIONS:
                revisions_used += 1
                t_rev = time.perf_counter()
                spec, r_in, r_out = revise_dashboard_spec(question, plan, datasets, spec, review)
                total_in += r_in
                total_out += r_out
                if trace_hook is not None:
                    trace_hook("dashboard_agent", {
                        "latency_s": round(time.perf_counter() - t_rev, 3),
                        "input_tokens": r_in,
                        "output_tokens": r_out,
                        "tool": "revise_dashboard_spec",
                        "verdict": "revised",
                    })
            else:
                _apply_final_review_isolation(spec, review, question)

    if law_only or resolved_domain == "mixed":  # G3: leis -> agente de leis; misto -> os dois
        t_law = time.perf_counter()
        l_in, l_out = _attach_law_part(spec, question, datasets, store.last_index(sid) + 1)
        total_in += l_in
        total_out += l_out
        if trace_hook is not None:
            trace_hook("law_agent", {"latency_s": round(time.perf_counter() - t_law, 3), "input_tokens": l_in,
                                     "output_tokens": l_out, "tool": "run_law_agent", "verdict": "ok"})

    used_ids = {w.dataset_id for w in spec.widgets if w.dataset_id}
    render_datasets = [d for d in datasets if d.dataset_id in used_ids] or datasets
    declare_bases(spec, render_datasets)  # A4: bases diferentes -> cada widget diz a base que usou
    _finish_dimension(spec, plan, question, render_datasets)
    _finish_chart_choice(spec, plan, datasets)
    _omit_unresolved_claims(spec, question, datasets)
    html_content = build_dashboard_html(spec, render_datasets, question=question)

    saved_path: Path | None = None
    if save:
        saved_path = (
            Path(output_path).resolve()
            if output_path
            else default_output_path(question, output_dir=output_dir)
        )
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_text(html_content, encoding="utf-8")

    try:
        session.current_spec = spec
        if saved_path is not None:
            session.current_dashboard_path = saved_path
    except AttributeError:
        pass

    return DashboardRunResult(
        question=question,
        domain=resolved_domain,
        html=html_content,
        output_path=saved_path,
        plan=plan,
        datasets=render_datasets,
        spec=spec,
        reviews=reviews,
        revisions_used=revisions_used,
        input_tokens=total_in,
        output_tokens=total_out,
        seconds=round(time.perf_counter() - start, 2),
    )

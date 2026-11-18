"""Orquestrador (1): planeja os recortes e visuais e coordena os outros 3 agentes.

Fluxo:
1. Recebe a pergunta em linguagem natural, resolve o domínio (`resolve_domain`) e monta
   um plano analítico (`OrchestratorPlan`) com quais dados e gráficos são necessários.
2. Aciona o Agente de Dados (`run_data_agent`) para consultar os bancos DuckDB em modo
   somente-leitura e obter `pd.DataFrame`s reais ([D1], [D2]...).
3. Aciona o Agente de Dashboard (`propose_dashboard_spec`) para gerar a especificação JSON.
4. Aciona o Agente Revisor (`review_dashboard`) e, se reprovado, pede correção ao Agente de
   Dashboard por no máximo `MAX_REVISIONS` (2) rodadas.
5. Se ao final das rodadas algum gráfico ainda falhar na validação, marca apenas esse
   componente com aviso (`valid=False`) e renderiza o HTML com todos os demais gráficos.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import time
import unicodedata

from src.config import DASHBOARD_OUTPUT_DIR, DUCKDB_PATH
from src.dashboard._llm import call_structured_llm
from src.dashboard.dashboard_agent import (
    build_dashboard_html,
    propose_dashboard_spec,
    revise_dashboard_spec,
)
from src.dashboard.data_agent import run_data_agent
from src.dashboard.reviewer_agent import review_dashboard
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

ORCHESTRATOR_SYSTEM_PROMPT = """\
Você é o Agente Orquestrador de dashboards analíticos do Trase (cadeias da carne bovina e da soja \
brasileiras). Seu papel é decompor a pergunta do usuário num plano enxuto de consultas SQL e \
componentes visuais complementares.

Diretrizes de planejamento:
- Planeje de 2 a 4 recortes de dados (`data_requests`) que juntos formem um bom painel executivo \
(ex.: indicadores de destaque para KPIs, ranking para gráfico de barras, série histórica para linha, \
ou detalhamento para tabela).
- Tipos de visual suportados nesta versão: APENAS `kpi`, `bar`, `line` e `table` (sem mapas).
- Respeite a disponibilidade dos bancos informada no contexto (`trase.duckdb` para carne bovina; \
`soy.duckdb` para soja). Se a pergunta não especificar a cadeia, priorize a cadeia disponível ou \
indique claramente no objetivo.
- Registre em `methodological_notes` os cuidados essenciais do Trase aplicáveis à pergunta \
(ex.: exposição ao desmatamento tem janela de 5 anos e não pode ser somada entre anos; rankings \
municipais cobrem a origem rastreada sem 'UNKNOWN'; usar ano mais recente se nenhum foi pedido; \
na soja, o destino BRAZIL é processamento doméstico e não conta como país importador).
"""

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


def create_plan(question: str, domain: str) -> OrchestratorPlan:
    """Usa o LLM para definir quais recortes de dados e tipos de gráficos comporão o painel."""
    beef_ok = DUCKDB_PATH.exists()
    soy_ok = soy_queries.is_available()
    user_msg = (
        f"Pergunta do usuário: {question}\n"
        f"Domínio sugerido pelo roteador: {domain}\n"
        f"Bancos disponíveis: carne bovina (trase.duckdb)={'sim' if beef_ok else 'não'}, "
        f"soja (soy.duckdb)={'sim' if soy_ok else 'não'}."
    )
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

    notes = [str(n).strip() for n in (payload.get("methodological_notes") or []) if str(n).strip()]
    return OrchestratorPlan(
        question=question,
        domain=domain,
        dashboard_goal=str(payload.get("dashboard_goal") or question).strip(),
        data_requests=requests,
        methodological_notes=notes,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def _apply_final_review_isolation(spec: DashboardSpec, final_review: ReviewResult, question: str) -> None:
    """Após esgotar as rodadas de correção, isola apenas os gráficos reprovados sem abortar o painel."""
    if not spec.title.strip():
        spec.title = f"Dashboard — {question}"

    issues_by_widget: dict[str, list[str]] = {}
    for issue in final_review.issues:
        if issue.widget_id:
            issues_by_widget.setdefault(issue.widget_id, []).append(issue.message)
        else:
            spec.warnings.append(issue.message)

    for w in spec.widgets:
        if w.id in issues_by_widget:
            w.valid = False
            w.validation_error = "; ".join(issues_by_widget[w.id])


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

    plan = create_plan(question, resolved_domain)
    total_in = plan.input_tokens
    total_out = plan.output_tokens

    data_res = run_data_agent(question, plan)
    total_in += data_res.input_tokens
    total_out += data_res.output_tokens
    datasets = data_res.datasets

    reviews: list[ReviewResult] = []
    revisions_used = 0

    if not datasets:
        reason = data_res.notes or "Nenhum conjunto de dados retornou linhas para esta pergunta."
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
            review = review_dashboard(question, spec, datasets)
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

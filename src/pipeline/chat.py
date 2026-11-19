"""Fluxo central de execução do pipeline de chat (R7, R9, R10, R11).

Coordena, por mensagem:
1. `monitor_in` (quando disponível);
2. `orchestrator` (`classify_intent`);
3. Execução conforme a intenção (`question`, `dashboard`, `dashboard_edit`, `map_edit`, `mixed`);
4. `monitor_out` (quando disponível);
5. Registro de traces por etapa (quando disponível) e proteção contra exceções sem expor stack trace.
"""

from __future__ import annotations

from pathlib import Path
import time
import uuid

import src.config as config_mod
from src.agent import ToolCall, ask as agent_ask, tool_call_summary
from src.dashboard.chart_intent import suggest_other_views
from src.dashboard.messages import short_subtitle
from src.dashboard.orchestrator import build_dashboard_from_store
from src.pipeline.orchestrator import MAP_UNAVAILABLE_MESSAGE, classify_intent
from src.pipeline.session import ChatSession
from src.rag import answer as rag_laws_answer, build_context, resolve_domain


def _resolve_monitors_and_tracer(input_monitor, output_monitor, trace_writer):
    if input_monitor is None:
        try:
            from src.pipeline.monitor import default_input_monitor
            input_monitor = default_input_monitor
        except ImportError:
            input_monitor = None
    if output_monitor is None:
        try:
            from src.pipeline.monitor import default_output_monitor
            output_monitor = default_output_monitor
        except ImportError:
            output_monitor = None
    if trace_writer is None:
        try:
            from src.pipeline.traces import record_trace_step
            trace_writer = record_trace_step
        except ImportError:
            trace_writer = None
    return input_monitor, output_monitor, trace_writer


def _serialize_tool_calls(calls: list[ToolCall]) -> list[dict]:
    return [
        {
            "label": c.label,
            "name": c.name,
            "summary": tool_call_summary(c),
            "ok": c.ok,
            "rows": c.rows,
            "seconds": c.seconds,
            "output": c.output,
        }
        for c in calls
    ]


def _serialize_law_sources(sources: list[dict], *, labeled: bool = True) -> list[dict]:
    out = []
    for idx, s in enumerate(sources, 1):
        meta = s.get("metadata") or {}
        item = {
            "title": s["title"],
            "artigo": meta.get("artigo"),
            "parte": meta.get("parte"),
            "partes": meta.get("partes"),
            "url": s.get("url", ""),
            "score": float(s.get("score") or 0.0),
            "semantic_rank": s.get("semantic_rank"),
            "keyword_rank": s.get("keyword_rank"),
        }
        if labeled:
            item["label"] = f"L{idx}"
        out.append(item)
    return out


def _sanitize_error_reason(exc: BaseException) -> str:
    msg = str(exc or "").strip().splitlines()[0] if str(exc or "").strip() else type(exc).__name__
    # Nunca vazar chaves ou caminhos sensíveis
    if "sk-or-" in msg:
        msg = "erro de autenticação no provedor de LLM"
    return msg[:220]


def _friendly_error_message(intent: str, exc: BaseException) -> str:
    raw = str(exc or "")
    if "OPENROUTER_API_KEY" in raw:
        return (
            "Não foi possível consultar o modelo de linguagem: a chave OPENROUTER_API_KEY "
            "não está definida. Configure OPENROUTER_API_KEY no arquivo .env para usar o chat."
        )
    reason = _sanitize_error_reason(exc)
    if intent in ("dashboard", "dashboard_edit", "mixed"):
        return f"Não consegui montar o painel: {reason}"
    return f"Não consegui concluir a resposta: {reason}"


def _format_dashboard_summary(
    dash_res,
    *,
    edit: bool = False,
    assumption: str | None = None,
) -> str:
    valid_widgets = [w for w in dash_res.spec.widgets if w.valid]
    invalid_widgets = [w for w in dash_res.spec.widgets if not w.valid]
    ds_labels = ", ".join(f"[{d.dataset_id}]" for d in dash_res.datasets)

    parts: list[str] = []
    if assumption:
        parts.append(assumption)

    if not valid_widgets and not dash_res.spec.widgets:
        warn_txt = "; ".join(dash_res.spec.warnings) or "nenhum dado encontrado para o recorte solicitado."
        parts.append(f"Não foi possível gerar gráficos para este pedido: {warn_txt}")
        return "\n\n".join(parts)

    verb = "Painel atualizado" if edit else "Painel gerado"
    summary = (
        f"**{verb}:** {dash_res.spec.title} "
        f"({len(valid_widgets)} componente(s) válido(s)"
        + (f", {len(invalid_widgets)} com aviso" if invalid_widgets else "")
        + (f"; fontes {ds_labels}" if ds_labels else "")
        + ")."
    )
    parts.append(summary)
    if dash_res.spec.subtitle:
        parts.append(short_subtitle(dash_res.spec.subtitle))
    chart = getattr(getattr(dash_res, "plan", None), "requested_chart", None)
    if chart is not None and chart.notice:
        parts.append(chart.notice)
    suggestion = suggest_other_views(dash_res.spec)
    if suggestion:
        parts.append(suggestion)
    return "\n\n".join(parts)


def handle_message(
    session: ChatSession,
    message: str,
    *,
    domain: str = "auto",
    k: int = 6,
    mode: str = "agent",
    dashboard_output_dir: Path | None = None,
    input_monitor=None,
    output_monitor=None,
    trace_writer=None,
    use_orchestrator_llm: bool | None = None,
) -> dict:
    """Executa o pipeline completo para uma mensagem na sessão e devolve payload JSON pronto."""
    t0 = time.perf_counter()
    trace_id = uuid.uuid4().hex[:16]
    k_clamped = max(1, min(int(k or 6), 20))
    out_dir = dashboard_output_dir or config_mod.DASHBOARD_OUTPUT_DIR

    in_mon, out_mon, tracer = _resolve_monitors_and_tracer(input_monitor, output_monitor, trace_writer)

    def _emit_trace(
        stage: str,
        *,
        intent_val: str = "unknown",
        latency_s: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool: str | None = None,
        verdict: str = "ok",
        error: str | None = None,
    ) -> None:
        if tracer is None:
            return
        try:
            tracer(
                trace_id=trace_id,
                session_id=session.session_id,
                stage=stage,
                message=message,
                intent=intent_val,
                latency_s=latency_s,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool=tool,
                verdict=verdict,
                error=error,
            )
        except Exception:
            pass

    # 1. Monitor de entrada
    t_in = time.perf_counter()
    if in_mon is not None:
        verdict_in = in_mon.check(message)
        _emit_trace(
            "monitor_in",
            intent_val="blocked" if not verdict_in.allowed else "pending",
            latency_s=round(time.perf_counter() - t_in, 4),
            tool=verdict_in.rule,
            verdict="blocked" if not verdict_in.allowed else "ok",
            error=verdict_in.reason if not verdict_in.allowed else None,
        )
        if not verdict_in.allowed:
            session.last_intent = "blocked"
            return {
                "answer": verdict_in.message,
                "intent": "blocked",
                "session_id": session.session_id,
                "dashboards": [],
                "tool_calls": [],
                "sources": [],
                "warnings": [verdict_in.reason] if verdict_in.reason else [],
                "seconds": round(time.perf_counter() - t0, 2),
                "trace_id": trace_id,
                "domain": domain,
                "input_tokens": 0,
                "output_tokens": 0,
                "stop_reason": "blocked",
            }
    elif not (message or "").strip():
        return {
            "answer": "Envie uma pergunta ou pedido não vazio.",
            "intent": "blocked",
            "session_id": session.session_id,
            "dashboards": [],
            "tool_calls": [],
            "sources": [],
            "warnings": ["empty_message"],
            "seconds": round(time.perf_counter() - t0, 2),
            "trace_id": trace_id,
            "domain": domain,
            "input_tokens": 0,
            "output_tokens": 0,
            "stop_reason": "blocked",
        }

    # Modo legado explícito "só leis"
    if mode == "laws":
        resolved_dom = resolve_domain(message, domain)
        try:
            t_rag = time.perf_counter()
            res_laws = rag_laws_answer(message, k=k_clamped, domain=resolved_dom)
            _emit_trace(
                "rag",
                intent_val="question",
                latency_s=round(time.perf_counter() - t_rag, 3),
                input_tokens=res_laws.input_tokens,
                output_tokens=res_laws.output_tokens,
                tool="rag.answer",
                verdict="ok",
            )
            session.last_intent = "question"
            session.append_turn(message, res_laws.text)
            return {
                "answer": res_laws.text,
                "intent": "question",
                "session_id": session.session_id,
                "dashboards": [],
                "tool_calls": [],
                "sources": _serialize_law_sources(res_laws.sources, labeled=False),
                "warnings": [],
                "seconds": round(time.perf_counter() - t0, 2),
                "trace_id": trace_id,
                "domain": res_laws.domain,
                "input_tokens": res_laws.input_tokens,
                "output_tokens": res_laws.output_tokens,
                "stop_reason": res_laws.stop_reason,
                "context": build_context(res_laws.sources) if res_laws.sources else "",
            }
        except Exception as exc:
            err_msg = _friendly_error_message("question", exc)
            _emit_trace(
                "rag",
                intent_val="question",
                latency_s=round(time.perf_counter() - t0, 3),
                tool="rag.answer",
                verdict="error",
                error=f"{type(exc).__name__}: {_sanitize_error_reason(exc)}",
            )
            return {
                "answer": err_msg,
                "intent": "question",
                "session_id": session.session_id,
                "dashboards": [],
                "tool_calls": [],
                "sources": [],
                "warnings": [err_msg],
                "seconds": round(time.perf_counter() - t0, 2),
                "trace_id": trace_id,
                "domain": resolved_dom,
                "input_tokens": 0,
                "output_tokens": 0,
                "stop_reason": "error",
            }

    # 2. Orquestrador de intenção
    t_orch = time.perf_counter()
    allow_llm = bool(config_mod.OPENROUTER_API_KEY) if use_orchestrator_llm is None else bool(use_orchestrator_llm)
    decision = classify_intent(
        message,
        session=session,
        domain=domain,
        use_llm=allow_llm,
    )
    intent = decision.intent
    _emit_trace(
        "orchestrator",
        intent_val=intent,
        latency_s=round(time.perf_counter() - t_orch, 4),
        input_tokens=decision.input_tokens,
        output_tokens=decision.output_tokens,
        tool=f"classify_intent:{decision.decided_by}",
        verdict="clarify" if decision.clarification else "ok",
    )

    total_in = decision.input_tokens
    total_out = decision.output_tokens
    warnings: list[str] = []
    dashboards: list[str] = []
    tool_calls_out: list[dict] = []
    sources_out: list[dict] = []
    answer_text = ""
    stop_reason: str | None = "end_turn"
    dash_res = None

    try:
        # 3a. Pedido vago -> pergunta de esclarecimento
        if decision.clarification:
            answer_text = decision.clarification
            session.last_intent = intent

        # 3b. Mapa (fora do escopo atual)
        elif intent == "map_edit":
            answer_text = MAP_UNAVAILABLE_MESSAGE
            session.last_intent = "map_edit"
            session.append_turn(message, answer_text)

        # 3c. Pergunta comum -> Agente de Dados/RAG (mesmas ferramentas e mesmo prompt)
        elif intent == "question":
            t_rag = time.perf_counter()
            ans = agent_ask(
                message,
                k_laws=k_clamped,
                history=session.get_llm_history(),
                domain=decision.domain,
                session_id=session.session_id,
                result_store=session.result_store,
            )
            used_tools = ",".join(c.name for c in ans.tool_calls) or "agent.ask"
            _emit_trace(
                "rag",
                intent_val="question",
                latency_s=round(time.perf_counter() - t_rag, 3),
                input_tokens=ans.input_tokens,
                output_tokens=ans.output_tokens,
                tool=used_tools,
                verdict="ok",
            )
            total_in += ans.input_tokens
            total_out += ans.output_tokens
            answer_text = ans.text
            stop_reason = ans.stop_reason
            tool_calls_out = _serialize_tool_calls(ans.tool_calls)
            sources_out = _serialize_law_sources(ans.law_sources, labeled=True)
            session.last_intent = "question"
            session.append_turn(message, answer_text)

        # 3d. Dashboard novo ou edição de DashboardSpec existente
        elif intent in ("dashboard", "dashboard_edit"):
            is_edit = intent == "dashboard_edit"

            def _dash_trace(stage_name: str, info: dict) -> None:
                _emit_trace(
                    stage_name,
                    intent_val=intent,
                    latency_s=float(info.get("latency_s") or 0.0),
                    input_tokens=int(info.get("input_tokens") or 0),
                    output_tokens=int(info.get("output_tokens") or 0),
                    tool=info.get("tool"),
                    verdict=str(info.get("verdict") or "ok"),
                )

            dash_res = build_dashboard_from_store(
                message,
                session,
                domain=decision.domain,
                use_previous_results=decision.use_previous_results,
                edit=is_edit,
                needs_new_data=decision.needs_new_data,
                goal_hint=decision.assumption,
                output_dir=out_dir,
                save=True,
                trace_hook=_dash_trace,
            )
            total_in += dash_res.input_tokens
            total_out += dash_res.output_tokens
            warnings.extend(dash_res.spec.warnings)
            if dash_res.output_path is not None and dash_res.spec.widgets:
                dashboards.append(f"/dashboards/{dash_res.output_path.name}")
            answer_text = _format_dashboard_summary(
                dash_res,
                edit=is_edit,
                assumption=decision.assumption,
            )
            session.last_intent = intent
            session.append_turn(message, answer_text)

        # 3e. Misto: roda RAG primeiro (grava no store) e depois monta dashboard com use_previous_results=True
        elif intent == "mixed":
            t_rag = time.perf_counter()
            ans = agent_ask(
                message,
                k_laws=k_clamped,
                history=session.get_llm_history(),
                domain=decision.domain,
                session_id=session.session_id,
                result_store=session.result_store,
            )
            used_tools = ",".join(c.name for c in ans.tool_calls) or "agent.ask"
            _emit_trace(
                "rag",
                intent_val="mixed",
                latency_s=round(time.perf_counter() - t_rag, 3),
                input_tokens=ans.input_tokens,
                output_tokens=ans.output_tokens,
                tool=used_tools,
                verdict="ok",
            )
            total_in += ans.input_tokens
            total_out += ans.output_tokens
            tool_calls_out = _serialize_tool_calls(ans.tool_calls)
            sources_out = _serialize_law_sources(ans.law_sources, labeled=True)

            def _mixed_dash_trace(stage_name: str, info: dict) -> None:
                _emit_trace(
                    stage_name,
                    intent_val="mixed",
                    latency_s=float(info.get("latency_s") or 0.0),
                    input_tokens=int(info.get("input_tokens") or 0),
                    output_tokens=int(info.get("output_tokens") or 0),
                    tool=info.get("tool"),
                    verdict=str(info.get("verdict") or "ok"),
                )

            dash_res = build_dashboard_from_store(
                message,
                session,
                domain=decision.domain,
                use_previous_results=True,
                edit=False,
                needs_new_data=False,
                goal_hint=decision.assumption,
                output_dir=out_dir,
                save=True,
                trace_hook=_mixed_dash_trace,
            )
            total_in += dash_res.input_tokens
            total_out += dash_res.output_tokens
            warnings.extend(dash_res.spec.warnings)
            if dash_res.output_path is not None and dash_res.spec.widgets:
                dashboards.append(f"/dashboards/{dash_res.output_path.name}")

            dash_note = _format_dashboard_summary(dash_res, edit=False, assumption=decision.assumption)
            answer_text = f"{ans.text}\n\n{dash_note}".strip()
            stop_reason = ans.stop_reason
            session.last_intent = "mixed"
            session.append_turn(message, answer_text)

    except Exception as exc:
        err_msg = _friendly_error_message(intent, exc)
        failed_stage = "dashboard_agent" if intent in ("dashboard", "dashboard_edit") else "rag"
        _emit_trace(
            failed_stage,
            intent_val=intent,
            latency_s=round(time.perf_counter() - t0, 3),
            verdict="error",
            error=f"{type(exc).__name__}: {_sanitize_error_reason(exc)}",
        )
        return {
            "answer": err_msg,
            "intent": intent,
            "session_id": session.session_id,
            "dashboards": [],
            "tool_calls": tool_calls_out,
            "sources": sources_out,
            "warnings": [*warnings, err_msg],
            "seconds": round(time.perf_counter() - t0, 2),
            "trace_id": trace_id,
            "domain": decision.domain,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "stop_reason": "error",
        }

    # 4. Monitor de saída
    t_out = time.perf_counter()
    if out_mon is not None:
        verdict_out = out_mon.check(
            answer=answer_text,
            intent=intent,
            dashboard_result=dash_res,
        )
        _emit_trace(
            "monitor_out",
            intent_val=intent,
            latency_s=round(time.perf_counter() - t_out, 4),
            tool=verdict_out.rule,
            verdict=verdict_out.action,
            error=verdict_out.reason if verdict_out.action != "ok" else None,
        )
        if verdict_out.warnings:
            for w_msg in verdict_out.warnings:
                if w_msg not in warnings:
                    warnings.append(w_msg)
        if not verdict_out.allowed:
            dashboards = []
            answer_text = verdict_out.message
            stop_reason = "blocked_output"

    return {
        "answer": answer_text,
        "intent": intent,
        "session_id": session.session_id,
        "dashboards": dashboards,
        "tool_calls": tool_calls_out,
        "sources": sources_out,
        "warnings": warnings,
        "seconds": round(time.perf_counter() - t0, 2),
        "trace_id": trace_id,
        "domain": decision.domain,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "stop_reason": stop_reason,
    }

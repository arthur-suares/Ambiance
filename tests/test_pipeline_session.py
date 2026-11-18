"""Testes offline de sessão, isolamento entre sessões e tratamento de falhas (R7, R11)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.agent import AgentAnswer, ToolCall
import src.config as config_mod
from src.dashboard.schemas import DatasetResult
import src.pipeline.chat as chat_mod
from src.pipeline.chat import handle_message
from src.pipeline.result_store import ResultStore
from src.pipeline.session import (
    InvalidSessionIdError,
    SessionManager,
    validate_session_id,
)


def test_session_id_validation_rules():
    assert validate_session_id("sessao_valida-01") == "sessao_valida-01"
    for invalid in ("", "curto7", "../segredo", "tem espaco aqui", "a/b_123456", "x" * 65, None, 12345678):
        with pytest.raises(InvalidSessionIdError):
            validate_session_id(invalid)


def test_session_manager_enforces_ttl_and_lru_capacity(monkeypatch, tmp_path):
    clock = [1000.0]
    monkeypatch.setattr("src.pipeline.session.time.monotonic", lambda: clock[0])

    mgr = SessionManager(
        result_store=ResultStore(base_dir=tmp_path / "sessions"),
        max_sessions=2,
        ttl_seconds=30.0,
    )
    s1 = mgr.get_or_create("sessao_0001")
    s1.last_intent = "question"

    clock[0] = 1010.0
    mgr.get_or_create("sessao_0002")
    assert len(mgr) == 2

    # Terceira sessão despeja a menos recentemente usada (sessao_0001)
    clock[0] = 1015.0
    mgr.get_or_create("sessao_0003")
    assert mgr.get("sessao_0001") is None
    assert mgr.get("sessao_0002") is not None

    # Avançando além do TTL (30s), sessões expiram
    clock[0] = 1060.0
    assert len(mgr) == 0


def test_two_sessions_do_not_mix_store_or_spec(monkeypatch, tmp_path):
    store = ResultStore(base_dir=tmp_path / "sessions")
    mgr = SessionManager(result_store=store)
    dash_dir = tmp_path / "dashboards"

    sess_a = mgr.get_or_create("sessao_usuario_A")
    sess_b = mgr.get_or_create("sessao_usuario_B")

    def fake_ask(question, k_laws=6, history=None, domain=None, session_id=None, result_store=None):
        lbl = result_store.allocate_label(session_id)
        ds = DatasetResult(
            dataset_id=lbl,
            database="soy.duckdb",
            source_label="Trase — Cadeia da soja (soy.duckdb)",
            tool_name="soy_top_destinations",
            query_summary="soy_top_destinations(year=2022)",
            df=pd.DataFrame({"destination": ["CHINA", "SPAIN"], "volume_tonnes": [55000000.0, 4200000.0]}),
        )
        result_store.put(session_id, ds)
        return AgentAnswer(
            question=question,
            text=f"China liderou em 2022 [{lbl}].",
            tool_calls=[ToolCall(lbl, "soy_top_destinations", {"year": 2022}, True, "ok", 2, 0.1)],
            datasets=[ds],
        )

    monkeypatch.setattr(chat_mod, "agent_ask", fake_ask)

    # Sessão A faz pergunta de dados -> popula store de A
    r1 = handle_message(sess_a, "quais os maiores destinos da soja em 2022?", dashboard_output_dir=dash_dir)
    assert r1["intent"] == "question"
    assert store.has_data("sessao_usuario_A") is True
    assert store.has_data("sessao_usuario_B") is False

    # Sessão A pede dashboard "com isso" -> usa D1 de A sem rodar data_agent
    monkeypatch.setattr(
        "src.dashboard.orchestrator.run_data_agent",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Não deve rodar data_agent para sessão A!")),
    )
    monkeypatch.setattr(
        "src.dashboard.dashboard_agent.call_structured_llm",
        lambda **kw: ({
            "title": "Destinos da Soja (2022)",
            "subtitle": "Exportações",
            "widgets": [{
                "id": "bar_dest",
                "kind": "bar",
                "title": "Exportações por país (2022)",
                "dataset_id": "D1",
                "x": "destination",
                "y": ["volume_tonnes"],
                "unit": "t",
                "source": "Trase — Soja [D1]",
            }],
        }, 100, 60),
    )
    monkeypatch.setattr(
        "src.dashboard.reviewer_agent.call_structured_llm",
        lambda **kw: ({"approved": True, "summary": "OK", "issues": []}, 40, 20),
    )

    r2 = handle_message(sess_a, "monte um dashboard com isso", dashboard_output_dir=dash_dir)
    assert r2["intent"] == "dashboard"
    assert len(r2["dashboards"]) == 1
    assert sess_a.current_spec is not None
    assert sess_b.current_spec is None

    # Sessão B pedindo "monte um dashboard com isso" sem dados próprios pede esclarecimento (não lê dados de A!)
    r_b = handle_message(sess_b, "monte um dashboard com isso", dashboard_output_dir=dash_dir)
    assert r_b["dashboards"] == []
    assert "Qual recorte" in r_b["answer"]


def test_r11_exceptions_and_missing_key_never_expose_stack_trace(monkeypatch, tmp_path):
    mgr = SessionManager(result_store=ResultStore(base_dir=tmp_path / "sessions"))
    sess = mgr.get_or_create("sessao_falha_01")

    # 1. Exceção inesperada na montagem do painel -> resposta amigável em português, sem Traceback
    def boom_dashboard(*args, **kwargs):
        raise ValueError("falha simulada no DuckDB")

    monkeypatch.setattr(chat_mod, "build_dashboard_from_store", boom_dashboard)
    out = handle_message(sess, "monta um dashbord de exportação de soja por país em 2022")
    assert "Não consegui montar o painel" in out["answer"]
    assert "Traceback" not in out["answer"]
    assert out["dashboards"] == []

    # 2. Ausência de OPENROUTER_API_KEY -> mensagem clara orientando configurar .env
    monkeypatch.setattr(config_mod, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(
        chat_mod,
        "agent_ask",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Defina OPENROUTER_API_KEY no .env.")),
    )
    out_no_key = handle_message(sess, "qual o maior município produtor de soja em 2022?")
    assert "OPENROUTER_API_KEY" in out_no_key["answer"]
    assert "Traceback" not in out_no_key["answer"]

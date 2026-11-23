"""Testes offline de observabilidade e traces JSONL por etapa (R10)."""

from __future__ import annotations

import json

import pandas as pd

from src.dashboard.schemas import DataAgentResult, DatasetResult, OrchestratorPlan
from src.pipeline.chat import handle_message
from src.pipeline.result_store import ResultStore
from src.pipeline.session import SessionManager
import src.pipeline.traces as traces_mod
from src.pipeline.traces import MAX_PREVIEW_CHARS, build_message_fingerprint


def test_trace_fingerprint_truncates_to_120_chars_and_redacts_keys():
    fake_secret = "sk-or-v1-" + ("a" * 48)
    long_question = f"Pergunta com chave acidental {fake_secret} " + ("detalhe muito longo " * 20)

    preview, digest = build_message_fingerprint(long_question)
    assert len(preview) <= MAX_PREVIEW_CHARS
    assert fake_secret not in preview
    assert "[REDACTED]" in preview
    assert len(digest) == 64


def test_dashboard_message_writes_expected_ordered_stages_to_daily_jsonl(monkeypatch, tmp_path):
    traces_dir = tmp_path / "traces"
    monkeypatch.setattr(traces_mod, "TRACES_DIR", traces_dir)

    mgr = SessionManager(result_store=ResultStore(base_dir=tmp_path / "sessions"))
    sess = mgr.get_or_create("sessao_trace_dash")

    monkeypatch.setattr(
        "src.dashboard.orchestrator.create_plan",
        lambda q, d, chart=None: OrchestratorPlan(question=q, domain=d, dashboard_goal="Destinos 2022"),
    )
    monkeypatch.setattr(
        "src.dashboard.orchestrator.run_data_agent",
        lambda q, p, *, start_index=1: DataAgentResult(
            datasets=[
                DatasetResult(
                    dataset_id=f"D{start_index}",
                    database="soy.duckdb",
                    source_label="Trase — Soja",
                    tool_name="soy_top_destinations",
                    query_summary="soy_top_destinations(year=2022)",
                    df=pd.DataFrame({"destination": ["CHINA", "SPAIN"], "volume_tonnes": [55e6, 4e6]}),
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "src.dashboard.dashboard_agent.call_structured_llm",
        lambda **kw: ({
            "title": "Exportações de Soja em 2022",
            "subtitle": "Por país de destino",
            "widgets": [{
                "id": "bar1",
                "kind": "bar",
                "title": "Volume por destino (2022)",
                "dataset_id": "D1",
                "x": "destination",
                "y": ["volume_tonnes"],
                "unit": "t",
                "source": "Trase — Soja [D1]",
            }],
        }, 140, 75),
    )
    monkeypatch.setattr(
        "src.dashboard.reviewer_agent.call_structured_llm",
        lambda **kw: ({"approved": True, "summary": "OK", "issues": []}, 60, 25),
    )

    long_msg = (
        "monta um dashbord de exportação de soja por país em 2022 "
        + ("com detalhamento adicional para auditoria de tamanho " * 4)
    )
    assert len(long_msg) > 160

    resp = handle_message(
        sess,
        long_msg,
        dashboard_output_dir=tmp_path / "dashboards",
    )
    assert resp["intent"] == "dashboard"
    trace_id = resp["trace_id"]
    assert trace_id

    files = list(traces_dir.glob("????-??-??.jsonl"))
    assert len(files) == 1

    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) >= 6
    assert all(r["trace_id"] == trace_id for r in records)
    assert all(r["session_id"] == "sessao_trace_dash" for r in records)
    assert [r["stage"] for r in records] == [
        "monitor_in",
        "orchestrator",
        "data_agent",
        "dashboard_agent",
        "validator",
        "monitor_out",
    ]
    for r in records:
        assert len(r["message_preview"]) <= MAX_PREVIEW_CHARS
        assert r["message_preview"] != long_msg
        assert r["message_sha256"]

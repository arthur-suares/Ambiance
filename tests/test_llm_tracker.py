"""Unit tests for LLM call tracking, traces, sessions, observations, and prompt audit."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src import llm_tracker


def test_summarize_events_enriches_traces_and_langfuse_links(monkeypatch):
    monkeypatch.setenv("LLM_TRACKER_LOG", "")
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000/")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_INIT_PROJECT_ID", "ambiance-agro")

    events = [
        {
            "start_timestamp": "2026-11-25T18:00:00+00:00",
            "timestamp": "2026-11-25T18:00:02+00:00",
            "trace_id": "trace-1",
            "session_id": "sess-abc",
            "route": "POST /api/ask",
            "stage": "agro_chat.loop.turn_1",
            "model": "deepseek/deepseek-v4.1-flash",
            "ok": True,
            "seconds": 2.0,
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 400,
            "cache_creation_tokens": 0,
            "total_tokens": 550,
        },
        {
            "start_timestamp": "2026-11-25T18:00:02+00:00",
            "timestamp": "2026-11-25T18:00:05+00:00",
            "trace_id": "trace-1",
            "session_id": "sess-abc",
            "route": "POST /api/ask",
            "stage": "agro_chat.loop.turn_2",
            "model": "deepseek/deepseek-v4.1-flash",
            "ok": False,
            "seconds": 3.0,
            "input_tokens": 80,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "total_tokens": 80,
        },
    ]

    summary = llm_tracker.summarize_events(events)
    assert summary["langfuse_configured"] is True
    assert summary["langfuse_url"] == "http://127.0.0.1:3000"
    assert summary["langfuse_project_id"] == "ambiance-agro"
    assert summary["totals"]["calls"] == 2
    assert summary["totals"]["error_calls"] == 1
    assert summary["totals"]["cache_read_tokens"] == 400
    assert summary["totals"]["estimated_cost_usd"] > 0

    trace = summary["by_trace"]["trace-1"]
    assert trace["ok"] is False
    assert trace["error_calls"] == 1
    assert trace["session_id"] == "sess-abc"
    assert trace["first_timestamp"] == "2026-11-25T18:00:00+00:00"
    assert trace["last_timestamp"] == "2026-11-25T18:00:05+00:00"
    assert trace["models"] == ["deepseek/deepseek-v4.1-flash"]
    assert trace["stages"] == ["agro_chat.loop.turn_1", "agro_chat.loop.turn_2"]

    assert "sess-abc" in summary["by_session"]
    sess = summary["by_session"]["sess-abc"]
    assert sess["trace_count"] == 1
    assert sess["calls"] == 2
    assert sess["trace_ids"] == ["trace-1"]


def test_disk_hydration_and_stage_filtering(tmp_path, monkeypatch):
    log_file = tmp_path / "tracker.jsonl"
    records = [
        {
            "timestamp": "2026-11-25T18:10:00+00:00",
            "trace_id": "t-a",
            "route": "POST /api/ask",
            "stage": "rag.answer",
            "model": "m1",
            "ok": True,
            "seconds": 1.1,
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "total_tokens": 30,
        },
        {
            "timestamp": "2026-11-25T18:10:05+00:00",
            "trace_id": "t-b",
            "route": "POST /api/ask",
            "stage": "agro_chat.loop.turn_1",
            "model": "m2",
            "ok": True,
            "seconds": 2.2,
            "input_tokens": 25,
            "output_tokens": 35,
            "cache_read_tokens": 100,
            "cache_creation_tokens": 0,
            "total_tokens": 160,
        },
    ]
    log_file.write_text(
        "\n".join([json.dumps(records[0]), "not-json", json.dumps(records[1])]) + "\n",
        encoding="utf-8",
    )

    llm_tracker.reset_tracker_state()
    try:
        monkeypatch.setenv("LLM_TRACKER_LOG", str(log_file))
        all_events = llm_tracker.get_events()
        assert len(all_events) == 2

        only_rag = llm_tracker.get_events(stage="rag.answer")
        assert [ev["trace_id"] for ev in only_rag] == ["t-a"]

        only_tb = llm_tracker.get_events(trace_id="t-b")
        assert [ev["stage"] for ev in only_tb] == ["agro_chat.loop.turn_1"]

        # Legacy trace fallback synthesizes detail from _EVENTS
        legacy = llm_tracker.get_trace_detail("t-b")
        assert legacy is not None
        assert legacy["trace_id"] == "t-b"
        assert len(legacy["observations"]) == 1
        assert legacy["observations"][0]["type"] == "generation"

        llm_tracker.reset_tracker_state()
        monkeypatch.setenv("LLM_TRACKER_LOG", "off")
        assert llm_tracker.get_events() == []
    finally:
        llm_tracker.reset_tracker_state()


def test_trace_spans_events_prompt_audit_and_disk_reload(tmp_path, monkeypatch):
    log_file = tmp_path / "tracker.jsonl"
    monkeypatch.setenv("LLM_TRACKER_LOG", str(log_file))
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    llm_tracker.reset_tracker_state()

    fake_resp = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=500,
            output_tokens=120,
            cache_read_input_tokens=1500,
            cache_creation_input_tokens=0,
        ),
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="text", text="Resposta jurídica consolidada [L1]."),
        ],
    )
    fake_raw_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: fake_resp),
    )
    client = llm_tracker.TrackedClient(fake_raw_client)

    try:
        with llm_tracker.llm_trace(trace_id="trace-rich-1", route="POST /api/ask", session_id="sess-99") as tid:
            assert tid == "trace-rich-1"
            llm_tracker.set_trace_io(
                name="chatbot-request",
                input_data={"question": "O que diz o Código Florestal?", "mode": "agro"},
            )
            with llm_tracker.llm_span("retrieve-documents", input_data={"query": "Código Florestal"}) as sp:
                llm_tracker.llm_event("cache_lookup", output_data={"hit": False})
                sp.set_output({"chunks": 3})

            with llm_tracker.llm_stage("agro_chat.loop.turn_1"):
                client.messages.create(
                    model="deepseek/deepseek-v4.1-flash",
                    max_tokens=1024,
                    system=[{"type": "text", "text": "Você é um assistente jurídico.", "cache_control": {"type": "ephemeral"}}],
                    messages=[
                        {"role": "user", "content": "Pergunta inicial"},
                        {
                            "role": "assistant",
                            "content": [
                                SimpleNamespace(type="text", text="Vou buscar na base."),
                                SimpleNamespace(type="tool_use", id="tu_1", name="search_laws", input={"query": "APP"}),
                            ],
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": "tu_1", "content": "Art. 4º APP..."},
                            ],
                        },
                    ],
                    tools=[{"name": "search_laws", "description": "Busca leis"}],
                )
            llm_tracker.set_trace_io(output_data={"answer": "Resposta jurídica consolidada [L1]."})

        # Clear memory and reload strictly from persisted JSON on disk
        llm_tracker.reset_tracker_state()
        detail = llm_tracker.get_trace_detail("trace-rich-1")
        assert detail is not None
        assert detail["session_id"] == "sess-99"
        assert detail["name"] == "chatbot-request"
        assert detail["input"]["question"] == "O que diz o Código Florestal?"
        assert detail["output"]["answer"] == "Resposta jurídica consolidada [L1]."
        assert detail["totals"]["spans"] == 1
        assert detail["totals"]["events"] == 1
        assert detail["totals"]["generations"] == 1
        assert detail["totals"]["estimated_cost_usd"] > 0

        obs_by_type = {o["type"]: o for o in detail["observations"]}
        assert obs_by_type["event"]["parent_observation_id"] == obs_by_type["span"]["id"]

        gen = obs_by_type["generation"]
        roles = [m["role"] for m in gen["prompt_messages"]]
        assert roles == ["system", "user", "assistant", "tool"]
        assert gen["prompt_messages"][0]["cached_hint"] is True
        assert gen["prompt_messages"][2]["tool_calls"][0]["name"] == "search_laws"
        assert round(sum(v["pct"] for v in gen["role_breakdown"].values()), 1) == 100.0
        assert gen["completion_blocks"][0]["text"] == "Resposta jurídica consolidada [L1]."
        assert gen["tools_names"] == ["search_laws"]
    finally:
        llm_tracker.reset_tracker_state()

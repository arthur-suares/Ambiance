from types import SimpleNamespace

import pytest

from src import agro_chat


@pytest.mark.parametrize("empty_end_turn", [False, True])
@pytest.mark.parametrize("provider_available", [False, True])
def test_tool_results_always_produce_a_written_answer(monkeypatch, empty_end_turn, provider_available):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    query = SimpleNamespace(type="tool_use", name="query_agro_sql", id="sql_1", input={
        "sql": "SELECT 38277198 AS volume_t", "purpose": "Exportações de soja de Mato Grosso",
    })
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(content=[query], usage=usage, stop_reason="tool_use")
        if empty_end_turn and len(calls) == 2:
            return SimpleNamespace(content=[], usage=usage, stop_reason="end_turn")
        if not provider_available:
            raise RuntimeError("modelo indisponível")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Mato Grosso exportou 38.277.198 t [D1].")],
                               usage=usage, stop_reason="end_turn")

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.with_options = lambda **_kwargs: client
    monkeypatch.setattr("src.rag.get_client", lambda: client)
    monkeypatch.setattr(agro_chat, "MAX_TURNS", 2 if empty_end_turn else 1)
    monkeypatch.setattr(agro_chat, "run_readonly_sql", lambda *_args, **_kwargs: (["volume_t"], [{"volume_t": 38277198}]))
    monkeypatch.setattr("src.dashboard.studio.build_studio_dashboard", lambda *_args: None)

    result = agro_chat.ask_agro("Quanto Mato Grosso exportou?")
    assert len(calls) == (3 if empty_end_turn else 2)
    assert "tools" not in calls[-1]
    assert calls[-1]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert "[D1]" in result["answer"]
    assert "38.277.198" in result["answer"]
    assert result["tables"][0]["rows"] == [{"volume_t": 38277198}]

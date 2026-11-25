"""Memória do prompt do chat (cache_control no SYSTEM_PROMPT) — tudo com cliente simulado: sem rede, sem custo."""
from __future__ import annotations

from types import SimpleNamespace

import src.agro_chat as agro_chat
import src.rag as rag


def _usage(i=100, o=10, cache_read=0, cache_create=0):
    return SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=cache_read,
                           cache_creation_input_tokens=cache_create)


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(idx):
    return SimpleNamespace(type="tool_use", id=f"tu{idx}", name="set_map_view", input={"title": "Mapa de teste"})


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _resp(blocks, usage, stop="end_turn"):
    return SimpleNamespace(content=blocks, usage=usage, stop_reason=stop)


def test_system_prompt_vai_com_cache_control_efemero(monkeypatch):
    client = FakeClient([_resp([_text("Resposta final.")], _usage(120, 20, cache_read=80))])
    monkeypatch.setattr(rag, "get_client", lambda: client)
    res = agro_chat.ask_agro("Pergunta?")
    system = client.calls[0]["system"]
    assert system == [{"type": "text", "text": agro_chat.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    assert res["answer"] == "Resposta final."
    assert res["turns"] == 1 and res["input_tokens"] == 120 and res["output_tokens"] == 20
    assert res["cache_read_input_tokens"] == 80 and res["cache_creation_input_tokens"] == 0


def test_cache_em_todas_as_rodadas_inclusive_a_resposta_forcada(monkeypatch):
    monkeypatch.setattr(agro_chat, "MAX_TURNS", 2)
    # 2 rodadas pedindo ferramenta + chamada final sem ferramentas (tool_choice none)
    client = FakeClient([
        _resp([_tool(1)], _usage(100, 5), "tool_use"),
        _resp([_tool(2)], _usage(150, 5, cache_create=40), "tool_use"),
        _resp([_text("Resposta escrita no limite.")], _usage(200, 30, cache_read=90)),
    ])
    monkeypatch.setattr(rag, "get_client", lambda: client)
    res = agro_chat.ask_agro("Pergunta longa?")
    assert len(client.calls) == 3
    assert all(c["system"][0]["cache_control"] == {"type": "ephemeral"} for c in client.calls)
    assert "tool_choice" not in client.calls[0] and client.calls[2]["tool_choice"] == {"type": "none"}
    assert res["answer"] == "Resposta escrita no limite."
    assert res["turns"] == 3
    assert res["input_tokens"] == 450 and res["output_tokens"] == 40
    assert res["cache_read_input_tokens"] == 90 and res["cache_creation_input_tokens"] == 40


def test_comportamento_do_pensamento_nao_mudou(monkeypatch):
    # Sem nada no .env, nenhuma chamada manda parâmetro de "thinking" (o padrão do modelo continua).
    monkeypatch.setattr(agro_chat, "LLM_EXTRA_PARAMS", {})
    client = FakeClient([_resp([_text("ok")], _usage())])
    monkeypatch.setattr(rag, "get_client", lambda: client)
    agro_chat.ask_agro("Pergunta?")
    assert "thinking" not in client.calls[0]

"""A extração de fatos das leis mantém o "thinking" do modelo; o resto do painel continua sem (com mock, sem custo)."""
from types import SimpleNamespace

import src.dashboard._llm as llm
import src.dashboard.law_agent as law_agent


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        tool = kw["tools"][0]["name"]
        block = SimpleNamespace(type="tool_use", name=tool, input={"rows": []})
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                               stop_reason="tool_use")


CHUNK = {"content": "Art. 12. Todo imóvel rural deve manter área com cobertura de vegetação nativa.",
         "title": "Lei nº 12.651/2012", "url": "https://planalto", "metadata": {"artigo": "12"}, "score": 1.0}


def test_extracao_das_leis_vai_sem_parametro_de_thinking(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    monkeypatch.setattr("src.config.LAW_AGENT_EXTRA_PARAMS", {}, raising=False)
    law_agent.extract_facts("Reserva legal?", [CHUNK])
    assert client.calls and "thinking" not in client.calls[0]


def test_demais_chamadas_do_painel_continuam_sem_thinking(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    monkeypatch.setattr(llm, "DASHBOARD_EXTRA_PARAMS", {"thinking": {"type": "disabled"}})
    llm.call_structured_llm(system="s", user_content="u", tool_name="emit_plan", tool_description="d",
                            input_schema={"type": "object"})
    assert client.calls[0]["thinking"] == {"type": "disabled"}


def test_law_agent_thinking_pode_ser_desligado_pelo_env(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    monkeypatch.setattr("src.config.LAW_AGENT_EXTRA_PARAMS", {"thinking": {"type": "disabled"}}, raising=False)
    law_agent.extract_facts("Reserva legal?", [CHUNK])
    assert client.calls[0]["thinking"] == {"type": "disabled"}

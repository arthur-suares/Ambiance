from types import SimpleNamespace

import pandas as pd
import pytest

from src import agent
from src.soy.routing import route_question


def plan(*queries, question_type="mixed"):
    return {"question_type": question_type, "subqueries": list(queries)}


def subquery(subquery_id, domain, question, depends_on=None):
    return {
        "id": subquery_id,
        "domain": domain,
        "question": question,
        "depends_on": depends_on or [],
    }


def test_validate_plan_rejects_unknown_domains_and_forward_dependencies():
    with pytest.raises(ValueError, match="domínio desconhecido"):
        agent.validate_retrieval_plan(plan(subquery("x", "sql", "pergunta"), question_type="data"))

    with pytest.raises(ValueError, match="dependência deve apontar"):
        agent.validate_retrieval_plan(plan(
            subquery("law", "legislation", "Pergunta legal", ["data"]),
            subquery("data", "soy_data", "Pergunta soja"),
        ))


def test_validate_plan_rejects_redundant_subqueries():
    with pytest.raises(ValueError, match="redundante"):
        agent.validate_retrieval_plan(plan(
            subquery("s1", "soy_data", "Maior exposição da soja"),
            subquery("s2", "soy_data", " Maior exposição da soja "),
            subquery("law", "legislation", "Reserva Legal"),
        ))


def test_tools_are_restricted_to_the_planned_domain():
    soy = {tool["name"] for tool in agent._tools_for_domain("soy_data", soy_available=True)}
    law = {tool["name"] for tool in agent._tools_for_domain("legislation", soy_available=True)}
    beef = {tool["name"] for tool in agent._tools_for_domain("beef_data", soy_available=True)}

    assert "search_laws" not in soy
    assert "run_soy_sql" in soy
    assert soy.isdisjoint(beef)
    assert law == {"search_laws"}
    assert "run_sql" in beef
    assert "run_soy_sql" not in beef
    assert agent._tools_for_domain("soy_data", soy_available=False) == []


def test_mixed_beef_and_law_is_routed_to_planner():
    routed = route_question("Qual grupo exportador de carne bovina lidera e qual multa prevê o Decreto?")

    assert routed["domain"] == "mixed"


def test_dependent_law_context_contains_only_geographic_result_fields():
    calls = [
        agent.ToolCall(
            label="D1",
            name="soy_territorial_metric",
            input={},
            ok=True,
            output="year,region,parent_region,metric,value\n2024,MATO GROSSO,CENTRO-OESTE,soy_production_t,12345\n",
            subquery_id="data",
        )
    ]
    results = {"data": {"status": "completed"}}
    context = agent._dependency_context(
        subquery("law", "legislation", "Que regra se aplica?", ["data"]),
        results,
        calls,
    )

    assert "MATO GROSSO" in context
    assert "CENTRO-OESTE" in context
    assert "12345" not in context
    assert "soy_production_t" not in context


def test_failed_dependencies_block_only_dependent_subquery(monkeypatch):
    plan_value = plan(
        subquery("data_failed", "soy_data", "Busca de dados"),
        subquery("law_blocked", "legislation", "Regra aplicável", ["data_failed"]),
        subquery("law_independent", "legislation", "Regra independente"),
    )
    monkeypatch.setattr(agent, "_create_retrieval_plan", lambda *args: (plan_value, 2, 1))
    executed = []

    def run_subquery(query, system, tools, session, dependency_context):
        executed.append((query["id"], {tool["name"] for tool in tools}, dependency_context))
        return "resultado", "failed" if query["id"] == "data_failed" else "completed", 1, 1

    monkeypatch.setattr(agent, "_run_planned_subquery", run_subquery)
    monkeypatch.setattr(agent, "_synthesize_mixed_answer", lambda *args: ("resposta parcial", 1, 1))

    answer = agent._ask_decomposed("Pergunta original", 6, [], soy_available=True)

    assert [item["status"] for item in answer.subqueries] == ["failed", "blocked", "completed"]
    assert [item[0] for item in executed] == ["data_failed", "law_independent"]
    assert answer.text == "resposta parcial"


def test_mixed_plan_executes_scoped_queries_then_synthesizes_once(monkeypatch):
    plan_value = plan(
        subquery("data", "soy_data", "Qual município lidera em exposição da soja?"),
        subquery("law", "legislation", "Quais obrigações legais de Reserva Legal se aplicam?"),
    )
    monkeypatch.setattr(agent, "_create_retrieval_plan", lambda *args: (plan_value, 2, 1))
    executions = []

    def run_subquery(query, system, tools, session, dependency_context):
        names = {tool["name"] for tool in tools}
        executions.append((query["id"], query["question"], names, dependency_context))
        return f"resultado {query['id']}", "completed", 2, 1

    synthesis = []

    def synthesize(question, executed_plan, results, calls, system, history=None):
        synthesis.append((question, results, history))
        return "Resposta integrada.", 3, 2

    monkeypatch.setattr(agent, "_run_planned_subquery", run_subquery)
    monkeypatch.setattr(agent, "_synthesize_mixed_answer", synthesize)
    history = [{"role": "assistant", "content": "Contexto anterior."}]
    answer = agent._ask_decomposed(
        "Pergunta original", 6, [], soy_available=True, history=history
    )

    assert executions[0][2].isdisjoint({"search_laws", "run_sql"})
    assert executions[1][2] == {"search_laws"}
    assert "Reserva Legal" not in executions[0][1]
    assert "soja" not in executions[1][1]
    assert synthesis[0][0] == "Pergunta original"
    assert synthesis[0][2] == history
    assert answer.text == "Resposta integrada."
    assert [result["status"] for result in answer.subqueries] == ["completed", "completed"]


def test_planned_subquery_sends_only_focused_query_and_scoped_tools(monkeypatch):
    tool_use = SimpleNamespace(
        type="tool_use",
        id="tool-1",
        name="soy_deforestation_by_biome",
        input={"year": 2022},
    )
    final = SimpleNamespace(type="text", text="Cerrado.")
    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[tool_use],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        ),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[final],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        ),
    ]
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

    monkeypatch.setattr(agent, "get_client", lambda: SimpleNamespace(messages=Messages()))
    session = agent._Session(k_laws=6)
    executed = []

    def run(name, args):
        executed.append((name, args, session.active_subquery_id))
        return "dados", True

    monkeypatch.setattr(session, "run", run)
    query = subquery("soy1", "soy_data", "Qual município lidera em exposição da soja em 2022?")
    tools = agent._tools_for_domain("soy_data", soy_available=True)

    answer, status, _, _ = agent._run_planned_subquery(query, [], tools, session, "")

    assert status == "completed"
    assert answer == "Cerrado."
    assert calls[0]["messages"][0]["content"] == query["question"]
    assert "search_laws" not in {tool["name"] for tool in calls[0]["tools"]}
    assert executed == [("soy_deforestation_by_biome", {"year": 2022}, "soy1")]


def test_legal_subquery_receives_only_legal_question_and_search_tool(monkeypatch):
    query_text = "Quais percentuais de Reserva Legal se aplicam no Cerrado?"
    tool_use = SimpleNamespace(
        type="tool_use",
        id="tool-law",
        name="search_laws",
        input={"query": "Reserva Legal percentuais no Cerrado", "k": 6},
    )
    final = SimpleNamespace(type="text", text="A regra depende da localização.")
    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[tool_use],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        ),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[final],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        ),
    ]
    requests = []

    class Messages:
        def create(self, **kwargs):
            requests.append(kwargs)
            return responses.pop(0)

    monkeypatch.setattr(agent, "get_client", lambda: SimpleNamespace(messages=Messages()))
    session = agent._Session(k_laws=6)
    executed = []
    monkeypatch.setattr(
        session,
        "run",
        lambda name, args: (executed.append((name, args)) or ("trecho legal", True)),
    )
    query = subquery("law1", "legislation", query_text)

    answer, status, _, _ = agent._run_planned_subquery(
        query, [], agent._tools_for_domain("legislation", True), session, ""
    )

    assert status == "completed"
    assert answer == "A regra depende da localização."
    assert requests[0]["messages"][0]["content"] == query_text
    assert {tool["name"] for tool in requests[0]["tools"]} == {"search_laws"}
    assert executed == [("search_laws", {"query": "Reserva Legal percentuais no Cerrado", "k": 6})]


def test_planner_requires_and_validates_structured_tool_output(monkeypatch):
    payload = plan(
        subquery("data", "soy_data", "Qual município lidera em exposição da soja?"),
        subquery("law", "legislation", "Qual regra de Reserva Legal se aplica?"),
    )
    planner_call = SimpleNamespace(
        type="tool_use",
        name=agent.PLAN_TOOL["name"],
        input=payload,
    )
    response = SimpleNamespace(
        content=[planner_call],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    observed = {}

    class Messages:
        def create(self, **kwargs):
            observed.update(kwargs)
            return response

    monkeypatch.setattr(agent, "get_client", lambda: SimpleNamespace(messages=Messages()))
    result, input_tokens, output_tokens = agent._create_retrieval_plan("Pergunta original")

    assert result == payload
    assert observed["messages"] == [{"role": "user", "content": "Pergunta original"}]
    assert observed["tool_choice"] == {"type": "tool", "name": agent.PLAN_TOOL["name"]}
    assert (input_tokens, output_tokens) == (10, 5)


def test_focused_dependency_question_does_not_receive_full_sql_output():
    source = pd.DataFrame(
        [{"region": "MATO GROSSO", "metric": "soy_production_t", "value": 12345}]
    ).to_csv(index=False)
    call = agent.ToolCall("D1", "soy_territorial_metric", {}, True, source, subquery_id="data")
    context = agent._dependency_context(
        subquery("law", "legislation", "Qual regra se aplica?", ["data"]),
        {"data": {"status": "completed"}},
        [call],
    )

    assert "MATO GROSSO" in context
    assert "soy_production_t" not in context
    assert "12345" not in context

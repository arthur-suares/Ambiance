"""Testes offline do Agente de Dashboard integrado ao Result Store e edição de spec (R1, R3, R4)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.dashboard import (
    DatasetResult,
    OrchestratorPlan,
    build_dashboard_from_store,
    edit_dashboard_spec,
)
import src.dashboard.dashboard_agent as dashboard_agent_mod
from src.dashboard.dashboard_agent import propose_dashboard_spec
import src.dashboard.orchestrator as dash_orch_mod
from src.dashboard.schemas import DataAgentResult, parse_dashboard_spec
from src.pipeline.result_store import ResultStore


class DummySession:
    def __init__(self, session_id: str, store: ResultStore):
        self.session_id = session_id
        self.result_store = store
        self.current_spec = None
        self.current_dashboard_path = None


@pytest.fixture
def stored_soy_session(tmp_path) -> DummySession:
    store = ResultStore(base_dir=tmp_path / "sessions")
    sid = "sessao_dash_01"
    store.put(
        sid,
        DatasetResult(
            dataset_id="D1",
            database="soy.duckdb",
            source_label="Trase — Cadeia da soja (soy.duckdb)",
            tool_name="soy_yearly_trend",
            query_summary="soy_yearly_trend()",
            df=pd.DataFrame({
                "year": [2020, 2021, 2022],
                "volume_tonnes": [81234567.0, 86543210.0, 91234500.0],
                "exposure_ha": [14000.0, 12500.0, 11800.0],
            }),
        ),
    )
    return DummySession(sid, store)


# --- R1: exatamente 1 chamada estruturada por tentativa --------------------------

def test_r1_propose_and_edit_make_exactly_one_structured_llm_call_each(monkeypatch, stored_soy_session):
    calls: list[str] = []

    spec_payload = {
        "title": "Série Anual da Soja (2020–2022)",
        "subtitle": "Brasil",
        "widgets": [
            {
                "id": "kpi_vol_2022",
                "kind": "kpi",
                "title": "Volume em 2022",
                "dataset_id": "D1",
                "column": "volume_tonnes",
                "agg": "max",
                "value": 91234500.0,
                "unit": "t",
                "source": "Trase — Soja [D1]",
            },
            {
                "id": "chart_vol",
                "kind": "bar",
                "title": "Volume anual (2020–2022)",
                "dataset_id": "D1",
                "x": "year",
                "y": ["volume_tonnes"],
                "unit": "t",
                "source": "Trase — Soja [D1]",
            },
        ],
    }

    def fake_structured(**kwargs):
        calls.append(kwargs["tool_name"])
        return spec_payload, 120, 80

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_structured)

    datasets = stored_soy_session.result_store.get_datasets(stored_soy_session.session_id)
    plan = OrchestratorPlan(question="Soja", domain="soy", dashboard_goal="Série anual")

    spec1, _, _ = propose_dashboard_spec("Soja", plan, datasets)
    assert len(calls) == 1

    edited_payload = {
        **spec_payload,
        "widgets": [
            spec_payload["widgets"][0],
            {**spec_payload["widgets"][1], "kind": "line"},
        ],
    }
    monkeypatch.setattr(
        dashboard_agent_mod,
        "call_structured_llm",
        lambda **kw: (calls.append(kw["tool_name"]) or edited_payload, 130, 85),
    )

    spec2, _, _ = edit_dashboard_spec("troque o gráfico de barras por linha", spec1, datasets, plan)
    assert len(calls) == 2
    assert spec2.widgets[1].kind == "line"


# --- R3: usar resultados salvos no store sem chamar o agente de dados ------------

def test_r3_build_dashboard_from_store_skips_data_agent_and_renders_store_numbers(
    monkeypatch, stored_soy_session, tmp_path
):
    data_agent_calls = 0

    def forbid_data_agent(*args, **kwargs):
        nonlocal data_agent_calls
        data_agent_calls += 1
        raise AssertionError("run_data_agent NÃO deveria ser chamado quando use_previous_results=True e o store tem dados!")

    monkeypatch.setattr(dash_orch_mod, "run_data_agent", forbid_data_agent)

    proposed = {
        "title": "Painel Soja 2020–2022",
        "subtitle": "Dados reaproveitados do chat",
        "widgets": [
            {
                "id": "kpi1",
                "kind": "kpi",
                "title": "Pico de volume (2022)",
                "dataset_id": "D1",
                "column": "volume_tonnes",
                "agg": "max",
                "value": 91234500.0,
                "unit": "t",
                "source": "Trase — Soja [D1]",
            },
            {
                "id": "bar_vol",
                "kind": "bar",
                "title": "Volume por ano (2020–2022)",
                "dataset_id": "D1",
                "x": "year",
                "y": ["volume_tonnes"],
                "unit": "t",
                "source": "Trase — Soja [D1]",
            },
        ],
    }

    def fake_llm(**kwargs):
        if kwargs["tool_name"] == "emit_dashboard_spec":
            return proposed, 100, 60
        if kwargs["tool_name"] == "emit_review":
            return {"approved": True, "summary": "OK", "issues": []}, 80, 30
        raise AssertionError(f"Ferramenta inesperada: {kwargs['tool_name']}")

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_llm)
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm", fake_llm)

    out_html = tmp_path / "dashboards" / "painel_store.html"
    res = build_dashboard_from_store(
        "Monte um dashboard com isso",
        stored_soy_session,
        domain="soy",
        use_previous_results=True,
        output_path=out_html,
    )

    assert data_agent_calls == 0
    assert out_html.is_file()
    # KPI em formato curto, com o valor exato preservado no atributo title (vindo do store, não da IA)
    assert "91,2 mi t" in res.html
    assert 'title="91.234.500 t"' in res.html
    assert stored_soy_session.current_spec is res.spec
    assert stored_soy_session.current_dashboard_path == out_html


# --- R4: edição incremental preservando IDs e buscando novos dados se preciso ----

def test_r4_edit_swaps_bar_to_line_preserving_ids(monkeypatch, stored_soy_session, tmp_path):
    stored_soy_session.current_spec = parse_dashboard_spec({
        "title": "Painel Soja 2020–2022",
        "subtitle": "Série histórica",
        "widgets": [
            {
                "id": "kpi1",
                "kind": "kpi",
                "title": "Pico de volume (2022)",
                "dataset_id": "D1",
                "column": "volume_tonnes",
                "agg": "max",
                "value": 91234500.0,
                "unit": "t",
                "source": "Trase — Soja [D1]",
            },
            {
                "id": "chart_vol",
                "kind": "bar",
                "title": "Volume por ano (2020–2022)",
                "dataset_id": "D1",
                "x": "year",
                "y": ["volume_tonnes"],
                "unit": "t",
                "source": "Trase — Soja [D1]",
            },
        ],
    })

    monkeypatch.setattr(
        dash_orch_mod,
        "run_data_agent",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Não deve consultar dados novos")),
    )

    def fake_edit_llm(**kwargs):
        if kwargs["tool_name"] == "emit_dashboard_spec":
            assert '"id": "kpi1"' in kwargs["user_content"]
            assert '"id": "chart_vol"' in kwargs["user_content"]
            return {
                "title": "Painel Soja 2020–2022",
                "subtitle": "Série histórica",
                "widgets": [
                    {
                        "id": "kpi1",
                        "kind": "kpi",
                        "title": "Pico de volume (2022)",
                        "dataset_id": "D1",
                        "column": "volume_tonnes",
                        "agg": "max",
                        "value": 91234500.0,
                        "unit": "t",
                        "source": "Trase — Soja [D1]",
                    },
                    {
                        "id": "chart_vol",
                        "kind": "line",
                        "title": "Evolução do volume por ano (2020–2022)",
                        "dataset_id": "D1",
                        "x": "year",
                        "y": ["volume_tonnes"],
                        "unit": "t",
                        "source": "Trase — Soja [D1]",
                    },
                ],
            }, 110, 70
        if kwargs["tool_name"] == "emit_review":
            return {"approved": True, "summary": "OK", "issues": []}, 60, 20
        raise AssertionError(kwargs["tool_name"])

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_edit_llm)
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm", fake_edit_llm)

    res = build_dashboard_from_store(
        "troque o gráfico de barras por linha",
        stored_soy_session,
        domain="soy",
        edit=True,
        needs_new_data=False,
        output_dir=tmp_path / "dashboards",
    )

    assert [w.id for w in res.spec.widgets] == ["kpi1", "chart_vol"]
    assert [w.kind for w in res.spec.widgets] == ["kpi", "line"]
    assert 'data-widget-id="chart_vol" data-widget-kind="line"' in res.html


def test_r4_edit_adds_fob_kpi_fetching_new_data_when_needed(monkeypatch, stored_soy_session, tmp_path):
    stored_soy_session.current_spec = parse_dashboard_spec({
        "title": "Painel Soja 2022",
        "subtitle": "",
        "widgets": [{
            "id": "line_vol",
            "kind": "line",
            "title": "Volume por ano (2020–2022)",
            "dataset_id": "D1",
            "x": "year",
            "y": ["volume_tonnes"],
            "unit": "t",
            "source": "Trase — Soja [D1]",
        }],
    })

    def fake_create_plan(question, domain, chart=None):
        return OrchestratorPlan(
            question=question,
            domain=domain,
            dashboard_goal="Obter FOB total em 2022",
        )

    def fake_run_data_agent(question, plan, *, start_index=1):
        assert start_index == 2  # D1 já está no store; novo dataset recebe D2
        ds_fob = DatasetResult(
            dataset_id=f"D{start_index}",
            database="soy.duckdb",
            source_label="Trase — Cadeia da soja (soy.duckdb)",
            tool_name="run_soy_sql",
            query_summary="SELECT 2022 AS year, 45300000000.0 AS fob_usd",
            df=pd.DataFrame({"year": [2022], "fob_usd": [45300000000.0]}),
        )
        return DataAgentResult(datasets=[ds_fob])

    monkeypatch.setattr(dash_orch_mod, "create_plan", fake_create_plan)
    monkeypatch.setattr(dash_orch_mod, "run_data_agent", fake_run_data_agent)

    def fake_llm(**kwargs):
        if kwargs["tool_name"] == "emit_dashboard_spec":
            return {
                "title": "Painel Soja 2022",
                "subtitle": "Com FOB",
                "widgets": [
                    {
                        "id": "kpi_fob",
                        "kind": "kpi",
                        "title": "FOB da soja em 2022",
                        "dataset_id": "D2",
                        "column": "fob_usd",
                        "agg": "first",
                        "value": 45300000000.0,
                        "unit": "US$",
                        "source": "Trase — Soja [D2]",
                    },
                    {
                        "id": "line_vol",
                        "kind": "line",
                        "title": "Volume por ano (2020–2022)",
                        "dataset_id": "D1",
                        "x": "year",
                        "y": ["volume_tonnes"],
                        "unit": "t",
                        "source": "Trase — Soja [D1]",
                    },
                ],
            }, 120, 80
        if kwargs["tool_name"] == "emit_review":
            return {"approved": True, "summary": "OK", "issues": []}, 50, 20
        raise AssertionError(kwargs["tool_name"])

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_llm)
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm", fake_llm)

    res = build_dashboard_from_store(
        "adicione um KPI de FOB em 2022",
        stored_soy_session,
        domain="soy",
        edit=True,
        needs_new_data=True,
        output_dir=tmp_path / "dashboards",
    )

    assert [d.dataset_id for d in stored_soy_session.result_store.get_datasets(stored_soy_session.session_id)] == ["D1", "D2"]
    assert [w.id for w in res.spec.widgets] == ["kpi_fob", "line_vol"]
    assert 'data-widget-id="kpi_fob"' in res.html
    assert 'data-widget-id="line_vol"' in res.html

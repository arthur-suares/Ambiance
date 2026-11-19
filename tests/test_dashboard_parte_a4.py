"""Adendo à Parte A4: base comum entre widgets do painel e selo "%" em pizza e rosca."""
from __future__ import annotations

import pandas as pd

from src.dashboard.data_base import (
    DataBase,
    base_phrase,
    check_common_base,
    common_base_line,
    declare_bases,
    infer_base,
)
from src.dashboard.renderer import render_dashboard_html
from src.dashboard.reviewer_agent import review_dashboard
from src.dashboard.schemas import DatasetResult, OrchestratorPlan, parse_dashboard_spec

SQL_KPI = ("SELECT SUM(TRY_CAST(volume AS DOUBLE)) AS volume_t FROM soy_supply_chain "
           "WHERE TRY_CAST(year AS INTEGER) = 2022 AND municipality_of_production <> 'UNKNOWN' "
           "AND country_of_first_import <> 'BRAZIL'")
SQL_PIZZA = ("SELECT country_of_first_import AS pais, SUM(TRY_CAST(volume AS DOUBLE)) AS volume_t "
             "FROM soy_supply_chain WHERE TRY_CAST(year AS INTEGER) = 2022 GROUP BY 1")


def _ds(did, df, sql, tool="run_soy_sql"):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", tool, sql, df)


KPI = _ds("D1", pd.DataFrame({"volume_t": [63.1e6]}), SQL_KPI)
PIZZA = _ds("D2", pd.DataFrame({"pais": ["CHINA", "BRAZIL", "Outros"], "volume_t": [60e6, 30e6, 10e6]}), SQL_PIZZA)


def _spec():
    return parse_dashboard_spec({"title": "Painel", "widgets": [
        {"id": "k", "kind": "kpi", "title": "Volume exportado, 2022", "dataset_id": "D1", "column": "volume_t",
         "agg": "first", "unit": "t", "source": "Trase [D1]", "value": 63.1e6},
        {"id": "p", "kind": "pie", "title": "Destinos, 2022", "dataset_id": "D2", "x": "pais",
         "y": ["volume_t"], "unit": "t", "source": "Trase [D2]"},
    ]})


# --- leitura da base em código ---------------------------------------------------------------

def test_base_lida_da_consulta_e_da_tabela():
    assert infer_base(KPI) == DataBase(years=(2022,), origin="rastreada", flow="exportacao")
    assert infer_base(PIZZA) == DataBase(years=(2022,), origin="toda", flow="cadeia")
    serie = _ds("D3", pd.DataFrame({"year": [2020, 2021, 2022], "v": [1, 2, 3]}), "SELECT ...")
    assert infer_base(serie).years == (2020, 2021, 2022)


def test_consulta_pronta_le_o_ano_dos_argumentos():
    ds = _ds("D4", pd.DataFrame({"municipality": ["A"], "v": [1]}), 'top_municipalities({"year": 2021})',
             tool="top_municipalities")
    assert infer_base(ds) == DataBase(years=(2021,), origin="rastreada", flow=None)


def test_frase_da_base_em_portugues_simples():
    assert base_phrase(infer_base(KPI)) == "Base: exportações com origem rastreada de 2022."
    assert base_phrase(DataBase()) is None


# --- revisor e correção --------------------------------------------------------------------

def test_kpi_e_pizza_com_bases_diferentes_ganham_a_frase_da_base():
    spec = _spec()
    issues = check_common_base(spec, [KPI, PIZZA])
    assert [i.code for i in issues] == ["base_diferente"] and not issues[0].blocking
    assert declare_bases(spec, [KPI, PIZZA]) == ["k", "p"]
    k, p = spec.widgets
    assert k.subtitle == "Base: exportações com origem rastreada de 2022."
    assert p.subtitle.startswith("Base: toda a cadeia (com o consumo no Brasil) incluindo origem não identificada")
    assert declare_bases(spec, [KPI, PIZZA]) == []  # não repete a frase


def test_mesma_base_nao_ganha_frase_nem_aviso():
    pizza_ok = _ds("D2", PIZZA.df[PIZZA.df.pais != "BRAZIL"], SQL_KPI.replace("SUM(", "pais, SUM("))
    spec = _spec()
    assert check_common_base(spec, [KPI, pizza_ok]) == []
    assert declare_bases(spec, [KPI, pizza_ok]) == [] and spec.widgets[1].subtitle == ""


def test_serie_historica_ao_lado_do_ranking_do_ano_nao_e_base_diferente():
    serie = _ds("D3", pd.DataFrame({"year": [2021, 2022], "volume_t": [1.0, 2.0]}), SQL_KPI.replace("= 2022", "IN (2021, 2022)"))
    spec = parse_dashboard_spec({"title": "P", "widgets": [
        {"id": "k", "kind": "kpi", "title": "V", "dataset_id": "D1", "column": "volume_t", "agg": "first",
         "unit": "t", "source": "T [D1]", "value": 63.1e6},
        {"id": "l", "kind": "line", "title": "S", "dataset_id": "D3", "x": "year", "y": ["volume_t"],
         "unit": "t", "source": "T [D3]"}]})
    assert check_common_base(spec, [KPI, serie]) == []


def test_revisor_avisa_base_diferente_sem_reprovar(monkeypatch):
    from src.dashboard import reviewer_agent
    from src.dashboard.schemas import ReviewResult
    monkeypatch.setattr(reviewer_agent, "check_methodological_llm",
                        lambda *a, **k: ReviewResult(approved=True, issues=[], llm_called=True))
    review = review_dashboard("pergunta", _spec(), [KPI, PIZZA])
    assert review.approved and [i.code for i in review.issues] == ["base_diferente"]


# --- planejador e Agente de Dados ----------------------------------------------------------------

def test_planejador_exige_base_comum_e_o_agente_de_dados_recebe(monkeypatch):
    from src.dashboard import data_agent, orchestrator
    assert "common_base" in orchestrator.PLAN_TOOL_SCHEMA["properties"]
    assert "UMA base comum" in orchestrator.ORCHESTRATOR_SYSTEM_PROMPT
    payload = {"dashboard_goal": "g", "data_requests": [{"request_id": "Q1", "description": "d",
                                                         "suggested_visual": "kpi"}],
               "methodological_notes": [], "common_base": {"year": 2022, "origin": "rastreada",
                                                           "flow": "exportacao"}}
    monkeypatch.setattr(orchestrator, "call_structured_llm", lambda **k: (payload, 0, 0))
    plan = orchestrator.create_plan("pergunta", "soy")
    assert plan.common_base == {"year": 2022, "origin": "rastreada", "flow": "exportacao"}
    msg = data_agent._format_plan_message("pergunta", plan)
    assert "BASE COMUM do painel" in msg and "ano 2022" in msg and "exclua 'UNKNOWN'" in msg


def test_sem_base_comum_nao_ha_linha_extra():
    assert common_base_line({}) is None
    plan = OrchestratorPlan(question="q", domain="soy", dashboard_goal="g")
    from src.dashboard.data_agent import _format_plan_message
    assert "BASE COMUM" not in _format_plan_message("q", plan)


# --- item 5: selo da pizza -----------------------------------------------------------------------

def test_selo_de_pizza_e_rosca_e_porcentagem():
    for kind in ("pie", "donut"):
        spec = parse_dashboard_spec({"title": "P", "widgets": [
            {"id": "p", "kind": kind, "title": "Destinos", "dataset_id": "D2", "x": "pais", "y": ["volume_t"],
             "unit": "t", "source": "Trase [D2]"}]})
        page = render_dashboard_html(spec, [PIZZA])
        card = page[page.index('data-widget-id="p"'):]
        assert '<span class="badge">%</span>' in card[:1500] and '<span class="badge">t</span>' not in card[:1500]

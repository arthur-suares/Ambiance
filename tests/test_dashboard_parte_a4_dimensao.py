"""Parte A4 (itens 1 a 3): "maiores municípios exportadores" é município, não empresa."""
from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.dimensions import GLOSSARY_PROMPT, detect_dimension
from src.dashboard.reviewer_agent import check_requested_dimension
from src.dashboard.schemas import DatasetResult, OrchestratorPlan, parse_dashboard_spec
from src.pipeline.orchestrator import classify_intent_deterministic

PEDIDO = "Preciso de um grafico de pizza dos maiores municipios exportadores de soja do Brasil"


def _ds(did, df, sql="SELECT 1"):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", "run_soy_sql", sql, df)


def _spec(x):
    return parse_dashboard_spec({"title": "P", "widgets": [
        {"id": "p", "kind": "pie", "title": "Maiores", "dataset_id": "D1", "x": x, "y": ["volume"],
         "unit": "t", "source": "Trase [D1]"}]})


# --- glossário ---------------------------------------------------------------------------------

@pytest.mark.parametrize("frase,chave", [
    (PEDIDO, "municipio"),
    ("de onde vem a soja exportada", "municipio"),
    ("origem da soja em 2022", "municipio"),
    ("pizza dos maiores exportadores de soja", "empresa"),
    ("quais tradings mais exportam", "empresa"),
    ("quem exporta mais soja", "empresa"),
    ("gráfico dos portos de exportação da soja", "porto"),
    ("para onde vai a soja do Brasil", "destino"),
    ("principais destinos da soja", "destino"),
    ("maiores importadores de soja", "importador"),
    ("volume por estado", "estado"),
])
def test_glossario_de_entidades(frase, chave):
    assert detect_dimension(frase).key == chave


def test_glossario_esta_no_planejador_e_no_agente_de_dados():
    from src.dashboard import data_agent, orchestrator
    assert GLOSSARY_PROMPT in orchestrator.ORCHESTRATOR_SYSTEM_PROMPT
    assert "{glossary}" in data_agent.DATA_AGENT_PROMPT
    assert '"exportadores" descreve o município' in GLOSSARY_PROMPT


# --- (a)-(d): roteamento ---------------------------------------------------------------------------

def test_a_painel_por_empresa_aberto_e_pizza_de_municipios_vira_painel_novo():
    d = classify_intent_deterministic(PEDIDO, has_spec=True, has_store_data=True,
                                      store_columns={"exporter_group", "volume"},
                                      panel_columns={"exporter_group"})
    assert d.intent == "dashboard" and d.needs_new_data and not d.use_previous_results


def test_b_conversa_nova_pede_municipio():
    d = classify_intent_deterministic(PEDIDO)
    assert d.intent == "dashboard" and d.needs_new_data and detect_dimension(PEDIDO).key == "municipio"


def test_c_pizza_dos_maiores_exportadores_e_empresa():
    d = classify_intent_deterministic("pizza dos maiores exportadores de soja")
    assert d.intent == "dashboard" and detect_dimension("pizza dos maiores exportadores de soja").key == "empresa"


@pytest.mark.parametrize("msg", ["faz em pizza", "mostra de outro jeito", "põe como lista"])
def test_d_so_formato_com_painel_aberto_e_edicao_sem_nova_consulta(msg):
    d = classify_intent_deterministic(msg, has_spec=True, has_store_data=True,
                                      store_columns={"exporter_group", "volume"},
                                      panel_columns={"exporter_group"})
    assert d.intent == "dashboard_edit" and not d.needs_new_data and d.use_previous_results


@pytest.mark.parametrize("msg", ["faz em pizza os municípios", "faz em pizza 2020", "faz em pizza da carne"])
def test_formato_com_entidade_periodo_ou_cadeia_nao_e_so_edicao_de_formato(msg):
    d = classify_intent_deterministic(msg, has_spec=True, has_store_data=True,
                                      store_columns={"exporter_group", "volume"},
                                      panel_columns={"exporter_group"})
    assert not (d.intent == "dashboard_edit" and d.use_previous_results and not d.needs_new_data)


def test_mesma_dimensao_do_painel_em_pizza_continua_edicao():
    d = classify_intent_deterministic("faz em pizza", has_spec=True, has_store_data=True,
                                      store_columns={"municipality", "volume"}, panel_columns={"municipality"})
    assert d.intent == "dashboard_edit"


# --- Result Store: dimensão diferente nunca reaproveita ---------------------------------------------

def test_store_agrupado_por_empresa_nao_serve_para_municipio(monkeypatch, tmp_path):
    from src.dashboard import orchestrator
    from src.pipeline.result_store import ResultStore

    class Sessao:
        session_id = "s1"
        current_spec = None
        result_store = ResultStore(base_dir=tmp_path)

    Sessao.result_store.put("s1", _ds("D1", pd.DataFrame({"exporter_group": ["CARGILL"], "volume": [1.0]})))

    class Parou(Exception):
        pass

    def plano_novo(*a, **k):
        raise Parou

    monkeypatch.setattr(orchestrator, "create_plan", plano_novo)
    with pytest.raises(Parou):  # foi buscar dados novos em vez de reaproveitar os de empresa
        orchestrator.build_dashboard_from_store(PEDIDO, Sessao(), use_previous_results=True, save=False)


# --- (e) e revisor -----------------------------------------------------------------------------------

def test_revisor_devolve_quando_o_grafico_nao_usa_a_dimensao_pedida():
    issues = check_requested_dimension(_spec("exporter_group"), "municipio")
    assert [i.code for i in issues] == ["dimensao"] and "municipality_of_production" in issues[0].message
    assert check_requested_dimension(_spec("municipality"), "municipio") == []
    alias = _ds("D1", pd.DataFrame(), "SELECT municipality_of_production AS m, SUM(volume) volume FROM t")
    assert check_requested_dimension(_spec("m"), "municipio", [alias]) == []
    assert check_requested_dimension(_spec("port_of_export"), "porto") == []
    assert check_requested_dimension(_spec("country_of_first_import"), "destino") == []
    assert check_requested_dimension(_spec("port_of_export"), "destino") != []


def test_apelido_livre_no_sql_conta_como_a_dimensao_e_nao_gera_aviso_falso():
    from src.dashboard.orchestrator import _finish_dimension
    sql = ("SELECT CASE WHEN r <= 7 THEN exporter_group ELSE 'Outros' END AS grupo, SUM(volume) AS volume "
           "FROM ranked GROUP BY 1")
    ds = _ds("D1", pd.DataFrame({"grupo": ["A"], "volume": [1.0]}), sql)
    assert check_requested_dimension(_spec("grupo"), "empresa", [ds]) == []
    spec = _spec("grupo")
    plan = OrchestratorPlan(question="q", domain="soy", dashboard_goal="g", requested_dimension="empresa")
    _finish_dimension(spec, plan, "q", [ds])
    assert spec.warnings == []
    # sem o SQL não dá para saber: não afirma "mostrei por ..." à toa
    _finish_dimension(spec, plan, "q")
    assert spec.warnings == []


def test_revisor_reprova_e_pede_nova_rodada(monkeypatch):
    from src.dashboard import reviewer_agent
    called = []
    monkeypatch.setattr(reviewer_agent, "check_methodological_llm", lambda *a, **k: called.append(1))
    df = pd.DataFrame({"exporter_group": ["A", "B"], "volume": [2.0, 1.0]})
    review = reviewer_agent.review_dashboard("q", _spec("exporter_group"), [_ds("D1", df)], dimension="municipio")
    assert not review.approved and "dimensao" in [i.code for i in review.issues] and not called


def test_se_ainda_nao_bater_mensagem_curta():
    from src.dashboard.orchestrator import _finish_dimension
    spec = _spec("exporter_group")
    plan = OrchestratorPlan(question=PEDIDO, domain="soy", dashboard_goal="g", requested_dimension="municipio")
    _finish_dimension(spec, plan, PEDIDO)
    assert spec.warnings == ["Não consegui montar por município; mostrei por empresa."]


def test_por_municipio_o_subtitulo_diz_origem_rastreada():
    from src.dashboard.orchestrator import _finish_dimension
    spec = _spec("municipality")
    plan = OrchestratorPlan(question=PEDIDO, domain="soy", dashboard_goal="g", requested_dimension="municipio")
    _finish_dimension(spec, plan, PEDIDO)
    assert spec.widgets[0].subtitle == "Município de origem da soja exportada; cobre só a origem rastreada."
    assert spec.warnings == []


def test_planejador_registra_a_dimensao_e_avisa_o_agente_de_dados(monkeypatch):
    from src.dashboard import data_agent, orchestrator
    vistos = {}

    def fake(**k):
        vistos["user"] = k["user_content"]
        return {"dashboard_goal": "g", "data_requests": [{"request_id": "Q1", "description": "d",
                                                          "suggested_visual": "pie"}],
                "methodological_notes": []}, 0, 0

    monkeypatch.setattr(orchestrator, "call_structured_llm", fake)
    plan = orchestrator.create_plan(PEDIDO, "soy")
    assert plan.requested_dimension == "municipio" and "DIMENSÃO PEDIDA: município" in vistos["user"]
    assert "DIMENSÃO PEDIDA: município (coluna municipality_of_production)" in data_agent._format_plan_message(PEDIDO, plan)

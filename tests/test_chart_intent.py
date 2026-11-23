"""Parte A: entender que gráfico a pessoa quer ver, mesmo sem saber o nome do gráfico.

Nenhum teste chama o LLM de verdade (ver tests/conftest.py).
"""
from __future__ import annotations

import pandas as pd
import pytest

import src.dashboard.chart_intent as chart_intent_mod
import src.dashboard.dashboard_agent as dashboard_agent_mod
import src.dashboard.orchestrator as dash_orch_mod
from src.dashboard import build_dashboard_from_store
from src.dashboard.chart_intent import (
    apply_share_guards,
    detect,
    interpret,
    misleading_share_reason,
    suggest_other_views,
)
from src.dashboard.dashboard_agent import DASHBOARD_SYSTEM_PROMPT
from src.dashboard.reviewer_agent import check_requested_chart
from src.dashboard.schemas import ALLOWED_WIDGET_KINDS, DashboardSpec, DatasetResult, WidgetSpec
from src.pipeline.orchestrator import classify_intent
from src.pipeline.result_store import ResultStore

# --- A10: frases de leigos -> formato esperado ------------------------------------------

FRASES = [
    # pizza: nome, apelidos, erros de digitação e descrições
    ("Quais foram os maiores municípios exportadores do Brasil? Faça uma pizza", "pie"),
    ("Quais os maiores municípios exportadores do Brasil? Faça um gráfico de pizza", "pie"),
    ("uma bolinha mostrando quanto cada município representa", "pie"),
    ("faz um grafiko de piza dos destinos da soja", "pie"),
    ("quero uma pizzaa com os destinos", "pie"),
    ("gráfico de torta dos estados", "pie"),
    ("um gráfico redondo com as fatias de cada bioma", "pie"),
    ("quanto cada país representa nas exportações de carne?", "pie"),
    ("proporção de cada destino no volume de 2022", "pie"),
    ("como se divide a participação dos exportadores", "pie"),
    # rosca
    ("faz uma rosquinha com os destinos", "donut"),
    ("gráfico em anel dos biomas", "donut"),
    # barras
    ("faz em barras os maiores municípios", "bar"),
    ("gráfico de colunas por estado", "bar"),
    ("os 10 maiores municípios exportadores de soja", "bar"),
    ("quem mais exportou carne em 2023", "bar"),
    ("compara Mato Grosso com Goiás", "bar"),
    ("ranking das empresas por exposição", "bar"),
    ("top 5 destinos da soja", "bar"),
    # linha
    ("como a exposição mudou ao longo dos anos", "line"),
    ("evolução do volume de soja de 2010 a 2022", "line"),
    ("o volume subiu ou caiu desde 2015?", "line"),
    ("tendência das exportações de carne", "line"),
    ("quero ver em linha", "line"),
    ("troque as barras por linha", "line"),
    ("série histórica do FOB", "line"),
    # composição no tempo
    ("composição das exportações por bioma ao longo do tempo", "stacked_area"),
    ("gráfico empilhado do volume por estado", "stacked_area"),
    # tabela / lista
    ("põe como lista", "table"),
    ("quero uma tabela com os destinos", "table"),
    ("me dá os números exatos por município", "table"),
    ("numa planilha, por favor", "table"),
    # medidor
    ("quanto % do volume foi para a China", "gauge"),
    ("um medidor com a parte da China", "gauge"),
    # variação por item
    ("o que mais pesou na queda das exportações?", "waterfall"),
    ("contribuição de cada destino para a variação", "waterfall"),
    # barras e linha juntas
    ("quero barras e linha juntas", "bar_line"),
    # sem suporte
    ("faz um mapa dos municípios", "map"),
    ("gráfico de radar das empresas", "radar"),
    ("gráfico de bolhas por estado", "bubble"),
    # outro jeito
    ("mostra de outro jeito", "other"),
]


@pytest.mark.parametrize("frase, esperado", FRASES)
def test_frase_de_leigo_vira_o_formato_esperado(frase, esperado):
    escolha = detect(frase)
    assert escolha is not None, f"não entendeu: {frase!r}"
    assert escolha.requested == esperado


def test_ha_pelo_menos_40_frases():
    assert len(FRASES) >= 40


@pytest.mark.parametrize("frase", ["qual foi o volume em 2022?", "linha de produção da soja", "o que é exposição?"])
def test_frase_sem_formato_nao_inventa_grafico(frase):
    assert detect(frase) is None


# --- A3/A4: nunca recusar; sem suporte -> mais próximo + UM aviso simples ------------------

@pytest.mark.parametrize("frase, aviso", [
    ("faz um mapa dos municípios", "Ainda não faço mapa, então mostrei em barras."),
    ("gráfico de radar das empresas", "Ainda não faço radar, então mostrei em barras."),
])
def test_pedido_sem_suporte_vira_o_mais_proximo_com_aviso(frase, aviso):
    escolha = detect(frase)
    assert escolha.kind in ALLOWED_WIDGET_KINDS
    assert escolha.notice == aviso


def test_tipo_suportado_nao_gera_aviso():
    escolha = detect("evolução do volume")
    assert escolha.kind == "line" and escolha.notice is None


def test_pizza_vira_pizza_quando_o_tipo_existe():
    escolha = detect("faça uma pizza", allowed=(*ALLOWED_WIDGET_KINDS, "pie"))
    assert escolha.kind == "pie" and escolha.notice is None


@pytest.mark.parametrize("frase", [f for f, _e in FRASES])
def test_aviso_sem_jargao(frase):
    escolha = detect(frase)
    texto = (escolha.notice or "") + escolha.kind_label
    for termo in ("donut", "gauge", "waterfall", "combo", "kind", "pie"):
        assert termo not in texto.lower()


# --- A1 camada 2: LLM só quando o dicionário não resolve ----------------------------------

def test_llm_classifica_quando_dicionario_nao_resolve(monkeypatch):
    chamadas = []
    monkeypatch.setattr(chart_intent_mod, "call_structured_llm",
                        lambda **kw: (chamadas.append(kw) or {"chart": "line"}, 10, 2))
    escolha, tin, tout = interpret("monta um painel da soja em Goiás")
    assert len(chamadas) == 1 and escolha.requested == "line" and escolha.source == "llm"
    assert (tin, tout) == (10, 2)


def test_llm_nao_e_chamado_quando_dicionario_resolve(monkeypatch):
    monkeypatch.setattr(chart_intent_mod, "call_structured_llm",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("não deveria chamar o LLM")))
    escolha, _i, _o = interpret("faz uma pizza dos destinos")
    assert escolha.requested == "pie"


def test_falha_do_llm_segue_sem_tipo_e_sem_erro():
    # conftest faz a chamada falhar
    assert interpret("monta um painel da soja em Goiás") == (None, 0, 0)


# --- A3: pizza que enganaria vira o gráfico adequado, com UM aviso ------------------------

def _ds(df, did="D1"):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)


def _spec_pizza(x, y, unit="t"):
    w = WidgetSpec(id="p", kind="pie", title="Participação", dataset_id="D1", unit=unit,
                   source="Trase [D1]", x=x, y=[y])
    return DashboardSpec(title="Painel", subtitle="", widgets=[w])


def test_pizza_de_serie_de_anos_vira_linha_com_aviso():
    df = pd.DataFrame({"year": [2020, 2021, 2022], "volume_t": [1.0, 2.0, 3.0]})
    spec = _spec_pizza("year", "volume_t")
    apply_share_guards(spec, [_ds(df)])
    assert spec.widgets[0].kind == "line"
    assert spec.warnings == ["Pizza não serve para comparar anos, então mostrei como linha ao longo do tempo."]


def test_pizza_de_percentuais_vira_barras_com_aviso():
    df = pd.DataFrame({"state": ["MT", "GO"], "zdc_pct": [40.0, 30.0]})
    spec = _spec_pizza("state", "zdc_pct", unit="%")
    apply_share_guards(spec, [_ds(df)])
    assert spec.widgets[0].kind == "bar" and len(spec.warnings) == 1


def test_pizza_de_exposicao_somada_entre_anos_vira_barras():
    df = pd.DataFrame({"year": [2021, 2022], "state": ["MT", "GO"], "exposure_ha": [5.0, 6.0]})
    assert "janela de 5 anos" in misleading_share_reason(df, "state", "exposure_ha", "ha")


def test_pizza_com_negativos_vira_barras():
    df = pd.DataFrame({"pais": ["A", "B"], "variacao_t": [10.0, -3.0]})
    assert "negativos" in misleading_share_reason(df, "pais", "variacao_t")


def test_pizza_adequada_fica_como_pizza():
    df = pd.DataFrame({"pais": ["CHINA", "Outros"], "volume_t": [70.0, 30.0]})
    spec = _spec_pizza("pais", "volume_t")
    apply_share_guards(spec, [_ds(df)])
    assert spec.widgets[0].kind == "pie" and spec.warnings == []


# --- revisor confere o tipo pedido -----------------------------------------------------

def test_revisor_aponta_quando_o_tipo_pedido_nao_foi_atendido():
    w = WidgetSpec(id="l", kind="line", title="T", dataset_id="D1", unit="t", source="Trase [D1]")
    spec = DashboardSpec(title="P", subtitle="", widgets=[w])
    issues = check_requested_chart(spec, detect("faz em barras"))
    assert len(issues) == 1 and "gráfico de barras" in issues[0].message
    w.kind = "bar"
    assert check_requested_chart(spec, detect("faz em barras")) == []


# --- A8: sugerir outras formas de ver ----------------------------------------------------

def test_sugere_outros_formatos_em_palavras_simples():
    w = WidgetSpec(id="b", kind="bar", title="T", dataset_id="D1", unit="t", source="Trase [D1]")
    frase = suggest_other_views(DashboardSpec(title="P", subtitle="", widgets=[w]))
    assert frase == "Quer ver em pizza ou como lista? É só pedir."
    sem_pizza = tuple(k for k in ALLOWED_WIDGET_KINDS if k != "pie")
    frase = suggest_other_views(DashboardSpec(title="P", subtitle="", widgets=[w]), allowed=sem_pizza)
    assert frase == "Quer ver como lista? É só pedir."


# --- A9: prompts com os tipos realmente suportados ---------------------------------------

def test_prompts_listam_todos_os_tipos_suportados():
    for kind in ALLOWED_WIDGET_KINDS:
        assert f"`{kind}`" in DASHBOARD_SYSTEM_PROMPT
        assert f"`{kind}`" in dash_orch_mod.ORCHESTRATOR_SYSTEM_PROMPT
    assert "APENAS `kpi`, `bar`, `line` e `table`" not in dash_orch_mod.ORCHESTRATOR_SYSTEM_PROMPT


def test_plano_guarda_o_tipo_pedido_mesmo_se_o_llm_sugerir_outro(monkeypatch):
    monkeypatch.setattr(dash_orch_mod, "call_structured_llm", lambda **kw: ({
        "dashboard_goal": "g", "methodological_notes": [],
        "data_requests": [{"request_id": "Q1", "description": "ranking", "suggested_visual": "line"}],
    }, 1, 1))
    escolha = detect("faz em barras")
    plano = dash_orch_mod.create_plan("faz em barras os maiores municípios", "soy", escolha)
    assert plano.requested_chart is escolha
    assert plano.data_requests[0].suggested_visual == "bar"


# --- fluxo completo: pedido de pizza dos maiores municípios -------------------------------

class _Sessao:
    def __init__(self, store):
        self.session_id = "sessao_pizza_01"
        self.result_store = store
        self.current_spec = None
        self.current_dashboard_path = None


def test_pizza_dos_maiores_municipios_vira_pizza(monkeypatch, tmp_path):
    store = ResultStore(base_dir=tmp_path / "s")
    store.put("sessao_pizza_01", _ds(pd.DataFrame({"municipality": ["SORRISO", "SAPEZAL", "Outros"],
                                                   "volume_t": [5.0, 4.0, 91.0]})))
    mensagens = []

    def fake_llm(**kw):
        if kw["tool_name"] == "emit_review":
            return {"approved": True, "summary": "ok", "issues": []}, 1, 1
        mensagens.append(kw["user_content"])
        return {"title": "Maiores municípios exportadores de soja (2022)", "subtitle": "Origem rastreada",
                "widgets": [{"id": "w1", "kind": "pie", "title": "Participação no volume, 2022",
                             "dataset_id": "D1", "x": "municipality", "y": ["volume_t"], "unit": "t",
                             "source": "Trase — Soja [D1]"}]}, 1, 1

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_llm)
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm", fake_llm)

    res = build_dashboard_from_store(
        "Quais foram os maiores municípios exportadores do Brasil? Faça uma pizza",
        _Sessao(store), domain="soy", output_path=tmp_path / "p.html")

    assert res.plan.requested_chart.requested == "pie"
    assert "Tipo de gráfico pedido pelo usuário: gráfico de pizza" in mensagens[0]
    assert res.plan.requested_chart.kind == "pie" and res.plan.requested_chart.notice is None
    assert not any("Ainda não faço" in w for w in res.spec.warnings)
    assert res.spec.widgets[0].kind == "pie" and res.spec.widgets[0].valid
    assert '"type":"pie"' in res.html


# --- A7 e roteamento no chat -----------------------------------------------------------

@pytest.mark.parametrize("frase", ["faz em pizza", "quero ver em linha", "põe como lista", "mostra de outro jeito",
                                   "coloca em barras"])
def test_troca_de_formato_em_linguagem_leiga_edita_o_painel_aberto(frase):
    dec = classify_intent(frase, has_spec=True, has_store_data=True, store_columns={"year", "volume_t"},
                          use_llm=False)
    assert dec.intent == "dashboard_edit" and dec.use_previous_results


@pytest.mark.parametrize("frase", [
    "Quais foram os maiores municípios exportadores do Brasil? Faça uma pizza",
    "uma bolinha mostrando quanto cada município representa",
])
def test_pedido_por_formato_sem_a_palavra_grafico_vira_painel(frase):
    dec = classify_intent(frase, has_store_data=False, use_llm=False)
    assert dec.intent == "dashboard" and dec.clarification is None


def test_so_o_formato_sem_recorte_pede_esclarecimento():
    dec = classify_intent("faz uma pizza", has_store_data=False, use_llm=False)
    assert dec.intent == "dashboard" and dec.clarification is not None


@pytest.mark.parametrize("frase", ["liste os 5 maiores municípios exportadores de soja",
                                   "qual tabela tem os dados da soja?",
                                   "quais os maiores destinos da carne em 2023?"])
def test_perguntas_comuns_continuam_indo_para_o_rag(frase):
    assert classify_intent(frase, use_llm=False).intent == "question"

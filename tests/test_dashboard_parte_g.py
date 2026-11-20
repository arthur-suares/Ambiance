"""Parte G: painéis de leis, sem banco real e sem IA paga (trechos de lei de exemplo)."""
from __future__ import annotations

import re

import pandas as pd
import pytest

from src.dashboard import law_agent
from src.dashboard.law_agent import (
    LAW_FOOTER,
    UNAVAILABLE_MESSAGE,
    build_law_widgets,
    catalog_frames,
    numbers_in,
    run_law_agent,
    verify_rows,
)
from src.dashboard.renderer import render_dashboard_html
from src.dashboard.reviewer_agent import validate_law_widget, validate_widget_deterministic
from src.dashboard.schemas import LAWS_SOURCE, DashboardSpec, DatasetResult, WidgetSpec, parse_dashboard_spec
from src.dashboard.validator import find_illegality_claim, validate_widget_methodological
from src.pipeline.monitor import OutputMonitor
from src.pipeline.orchestrator import classify_intent_deterministic

URL_9605 = "https://www.planalto.gov.br/ccivil_03/leis/l9605.htm"
TRECHOS = [
    {"content": "Art. 50. Destruir ou danificar florestas nativas ou plantadas ou vegetação nativa: "
                "Multa de R$ 5.000,00 (cinco mil reais), por hectare ou fração.",
     "title": "Decreto nº 6.514/2008 — Infrações ambientais",
     "url": "https://www.planalto.gov.br/ccivil_03/_ato2007-2010/2008/decreto/d6514.htm",
     "metadata": {"artigo": "50"}},
    {"content": "Art. 75. O valor da multa de que trata este Capítulo será fixado no regulamento desta Lei e "
                "corrigido periodicamente, com base nos índices estabelecidos na legislação pertinente, sendo o "
                "mínimo de R$ 50,00 (cinqüenta reais) e o máximo de R$ 50.000.000,00 (cinqüenta milhões de reais).",
     "title": "Lei nº 9.605/1998 — Lei de Crimes Ambientais", "url": URL_9605, "metadata": {"artigo": "75"}},
    {"content": "Art. 12. Todo imóvel rural deve manter área com cobertura de vegetação nativa, a título de "
                "Reserva Legal: I - localizado na Amazônia Legal: a) 80% (oitenta por cento), no imóvel situado "
                "em área de florestas;",
     "title": "Lei nº 12.651/2012 — Código Florestal",
     "url": "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12651.htm",
     "metadata": {"artigo": "12"}},
]
BOAS = [
    {"trecho": 2, "tipo": "penalidade", "valor_min": 50, "valor_max": 50000000, "unidade": "reais",
     "citacao_literal": "sendo o mínimo de R$ 50,00 (cinqüenta reais) e o máximo de R$ 50.000.000,00"},
    {"trecho": 1, "tipo": "penalidade", "valor_min": 5000, "valor_max": 5000, "unidade": "R$ por hectare",
     "citacao_literal": "Multa de R$ 5.000,00 (cinco mil reais), por hectare ou fração"},
    {"trecho": 3, "tipo": "percentual", "valor_min": 80, "valor_max": 80, "unidade": "%",
     "citacao_literal": "80% (oitenta por cento), no imóvel situado em área de florestas"},
]
NUMERO_INVENTADO = {"trecho": 2, "tipo": "penalidade", "valor_min": 100, "valor_max": 50000000, "unidade": "R$",
                    "citacao_literal": "sendo o mínimo de R$ 50,00 (cinqüenta reais) e o máximo de R$ 50.000.000,00"}
CITACAO_ADULTERADA = {"trecho": 1, "tipo": "penalidade", "valor_min": 5000, "valor_max": 5000, "unidade": "R$",
                      "citacao_literal": "Multa de R$ 5.000,00 por hectare desmatado ilegalmente"}


def _agente(rows, **kw):
    return run_law_agent("monte um painel das multas", available=True, retriever=lambda q, k: TRECHOS,
                         extractor=lambda q, c: (rows, 0, 0), **kw)


# --- G2: o código confere o que o LLM extraiu ------------------------------------------------

def test_numeros_no_padrao_brasileiro():
    assert {50.0, 50000000.0, 75.0} <= numbers_in(TRECHOS[1]["content"])


def test_numero_fora_do_texto_e_descartado():
    df, descartadas = verify_rows([NUMERO_INVENTADO], TRECHOS)
    assert df.empty and descartadas == 1


def test_citacao_adulterada_e_descartada():
    df, descartadas = verify_rows([CITACAO_ADULTERADA], TRECHOS)
    assert df.empty and descartadas == 1


def test_lei_artigo_e_url_vem_do_trecho_nao_do_llm():
    df, descartadas = verify_rows(BOAS, TRECHOS)
    assert descartadas == 0 and len(df) == 3
    linha = df.iloc[0]
    assert linha.lei == "Lei 9.605/1998 (Lei de Crimes Ambientais)" and linha.artigo == "art. 75"
    assert linha.url_fonte == URL_9605 and linha.unidade == "R$" and linha.valor_max == 50000000


def test_trecho_inexistente_ou_unidade_desconhecida_e_descartado():
    ruins = [dict(BOAS[0], trecho=9), dict(BOAS[1], unidade="bananas")]
    df, descartadas = verify_rows(ruins, TRECHOS)
    assert df.empty and descartadas == 2


def test_painel_diz_quantas_linhas_foram_descartadas():
    res = _agente([*BOAS, NUMERO_INVENTADO, CITACAO_ADULTERADA])
    assert res.kept == 3 and res.dropped == 2
    assert res.notes == "2 informações das leis não puderam ser conferidas no texto da norma e ficaram de fora."


# --- G4 / G7: widgets montados em código e regras R5 de leis -------------------------------------

def test_faixa_so_compara_a_mesma_unidade_e_nunca_soma():
    res = _agente(BOAS)
    widgets, extra = build_law_widgets(res)
    kinds = {w.id.split("_")[1]: w for w in widgets}
    assert {"cmp", "faixa", "valor", "citacoes"} <= set(kinds)
    by_id = {d.dataset_id: d for d in [*res.datasets, *extra]}
    faixas = [w for w in widgets if w.kind == "range"]
    assert len(faixas) == 1 and faixas[0].unit == "R$"
    assert by_id[faixas[0].dataset_id].df["unidade"].unique().tolist() == ["R$"]
    for d in extra:  # cada subconjunto só tem linhas que já existiam, sem valores novos
        assert set(d.df["valor_max"]) <= set(res.datasets[0].df["valor_max"])
    for w in widgets:
        assert w.source == f"{LAWS_SOURCE} [{w.dataset_id}]"
        assert [i for i in validate_widget_deterministic(w, by_id) if i.blocking] == [], w.id


def test_validador_de_leis_exige_fonte_citacao_e_unidade_por_linha():
    df = pd.DataFrame({"lei": ["A", "B"], "artigo": ["art. 1", "art. 2"], "valor_min": [1.0, 2.0],
                       "valor_max": [3.0, 4.0], "unidade": ["R$", "%"], "citacao_literal": ["x" * 20, ""],
                       "url_fonte": [URL_9605, ""], "rotulo": ["A", "B"]})
    ds = DatasetResult("D1", "laws", LAWS_SOURCE, "search_laws", "q", df)
    w = WidgetSpec(id="r", kind="range", title="Faixa", dataset_id="D1", unit="R$", source=f"{LAWS_SOURCE} [D1]",
                   x="rotulo", y=["valor_min", "valor_max"])
    codigos = [i.code for i in validate_law_widget(w, ds)]
    assert codigos.count("lei_fonte") == 2 and "lei_unidade" in codigos
    sem_unidade = ds.df.assign(unidade=["R$", ""], citacao_literal=["x" * 20] * 2, url_fonte=[URL_9605] * 2)
    assert "lei_unidade" in [i.code for i in validate_law_widget(
        w, DatasetResult("D1", "laws", LAWS_SOURCE, "search_laws", "q", sem_unidade))]


def test_componente_de_lei_com_dados_do_trase_e_bloqueado():
    ds = DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", "q", pd.DataFrame({"a": [1]}))
    w = WidgetSpec(id="q", kind="quote", title="Artigos", dataset_id="D1", unit="citação",
                   source=f"{LAWS_SOURCE} [D1]", columns=["a"])
    assert any("acervo de leis" in i.message for i in validate_widget_deterministic(w, {"D1": ds}))


def test_acervo_vira_linha_do_tempo_e_matriz_contadas_do_banco():
    rows = [{"title": "Lei nº 12.651/2012 — Código Florestal", "url": "https://x/a", "enacted_at": "2012-05-25", "artigos": 84},
            {"title": "Lei nº 9.605/1998 — Lei de Crimes Ambientais", "url": "https://x/b", "enacted_at": "1998-02-12", "artigos": 82},
            {"title": "Decreto nº 6.514/2008 — Infrações ambientais", "url": "https://x/c", "enacted_at": "2008-07-22", "artigos": 153}]
    leis, por_ano, matriz = catalog_frames(rows)
    assert por_ano["normas"].sum() == 3 and list(por_ano["ano"]) == [1998, 2008, 2012]
    assert leis.set_index("lei").loc["Decreto 6.514/2008 (Infrações ambientais)", "tipo"] == "Decreto"
    assert matriz.set_index("lei").loc["Lei 12.651/2012 (Código Florestal)", "Florestas e vegetação"] == "●"


# --- G5: SEGURANÇA, exceção estreita para o nome oficial da norma ---------------------------------

def test_nome_da_lei_com_fonte_de_leis_passa():
    assert find_illegality_claim("Multas da Lei de Crimes Ambientais", law_source=True) is None


def test_mesmo_nome_sem_fonte_de_leis_continua_bloqueado():
    assert find_illegality_claim("Multas da Lei de Crimes Ambientais") == "crime"


def test_termo_atribuido_a_municipio_continua_bloqueado_mesmo_com_fonte_de_leis():
    assert find_illegality_claim("Sorriso cometeu crime previsto na Lei de Crimes Ambientais", law_source=True)
    assert find_illegality_claim("Exportação ilegal de soja em Sorriso", law_source=True)


def _spec_com(titulo, source):
    return DashboardSpec(title="Painel", widgets=[WidgetSpec(id="w", kind="table", title=titulo, dataset_id="D1",
                                                              unit="texto", source=source, columns=["lei"])])


def test_monitor_de_saida_dos_dois_lados():
    mon = OutputMonitor()
    leis = [DatasetResult("D1", "laws", LAWS_SOURCE, "search_laws", "q", pd.DataFrame({"lei": ["x"]}))]
    assert mon.check_dashboard_spec(_spec_com("Lei de Crimes Ambientais: multas", f"{LAWS_SOURCE} [D1]"),
                                    leis).allowed
    # Sem o dataset de leis, nada é liberado (auditoria, item 2b).
    assert not mon.check_dashboard_spec(_spec_com("Lei de Crimes Ambientais: multas", f"{LAWS_SOURCE} [D1]")).allowed
    assert not mon.check_dashboard_spec(_spec_com("Lei de Crimes Ambientais: multas", "Trase — Soja [D1]"),
                                        leis).allowed
    assert not mon.check_dashboard_spec(_spec_com("Município de Sorriso comete crime ambiental",
                                                  f"{LAWS_SOURCE} [D1]"), leis).allowed


def test_validador_metodologico_dos_dois_lados():
    w = WidgetSpec(id="w", kind="table", title="Multas da Lei de Crimes Ambientais", dataset_id="D1", unit="R$",
                   source=f"{LAWS_SOURCE} [D1]", columns=["lei"])
    leis = DatasetResult("D1", "laws", LAWS_SOURCE, "search_laws", "q", pd.DataFrame({"lei": ["x"]}))
    trase = DatasetResult("D1", "soy.duckdb", "Trase", "run_soy_sql", "q", pd.DataFrame({"lei": ["x"]}))
    assert [i for i in validate_widget_methodological(w, leis) if i.code == "alegacao"] == []
    assert [i for i in validate_widget_methodological(w, trase) if i.code == "alegacao"]


def test_g6_texto_que_liga_exposicao_a_infracao_e_bloqueado():
    assert find_illegality_claim("A exposição ao desmatamento gera multa para os municípios")
    assert find_illegality_claim("Desmatamento associado configura infração ambiental", law_source=True)
    assert find_illegality_claim("Exposição ao desmatamento por município, 2022") is None


# --- G3: roteamento --------------------------------------------------------------------------------

def test_painel_das_multas_do_codigo_florestal_vira_painel_de_leis():
    d = classify_intent_deterministic("monte um painel das multas do Código Florestal")
    assert (d.intent, d.domain) == ("dashboard", "law")


def test_pergunta_de_lei_sem_pedido_de_painel_continua_em_texto():
    d = classify_intent_deterministic("qual a multa para quem desmata sem autorização?")
    assert d.intent == "question"


def test_painel_com_dados_e_lei_e_misto():
    d = classify_intent_deterministic("painel da exposição ao desmatamento da soja e o que diz o código florestal")
    assert (d.intent, d.domain) == ("mixed", "mixed")


# --- G6 / G8: painel de leis e painel misto ----------------------------------------------------------

class _Store:
    def __init__(self, datasets=()):
        self._d = list(datasets)

    def get_datasets(self, sid, non_empty_only=True):
        return list(self._d)

    def last_index(self, sid):
        return len(self._d)

    def put(self, sid, ds):
        self._d.append(ds)


class _Sessao:
    session_id = "s"
    current_spec = None

    def __init__(self, store):
        self.result_store = store


def _orq(monkeypatch, rows=None, available=True):
    from src.dashboard import orchestrator
    monkeypatch.setattr(orchestrator, "run_law_agent", lambda q, start_index=1: run_law_agent(
        q, start_index=start_index, available=available, retriever=lambda qq, k: TRECHOS,
        extractor=lambda qq, c: (rows if rows is not None else BOAS, 0, 0)))
    return orchestrator


def test_painel_de_leis_completo(monkeypatch):
    orq = _orq(monkeypatch, rows=[*BOAS, NUMERO_INVENTADO])
    res = orq.build_dashboard_from_store("monte um painel das multas do Código Florestal", _Sessao(_Store()),
                                         domain="law", save=False)
    page = res.html
    assert 'id="base-legal"' in page and "Base legal" in page
    assert LAW_FOOTER in page and "Isto não é aconselhamento jurídico" in page
    assert "1 informação das leis não pôde ser conferida" in page
    assert page.count('ver no Planalto</a>') >= 3
    assert 'class="card card-warning' not in page and 'class="fallback-note"' not in page  # nada caiu no aviso
    assert all(LAWS_SOURCE in w.source and re.search(r"\[D\d+\]", w.source) for w in res.spec.widgets)


def test_banco_de_leis_fora_do_ar_explica_sem_quebrar(monkeypatch):
    orq = _orq(monkeypatch, available=False)
    res = orq.build_dashboard_from_store("monte um painel das multas do Código Florestal", _Sessao(_Store()),
                                         domain="law", save=False)
    assert res.spec.widgets == [] and res.spec.warnings == [UNAVAILABLE_MESSAGE]
    assert "Postgres" not in UNAVAILABLE_MESSAGE and "conexão" not in UNAVAILABLE_MESSAGE


def _misto(monkeypatch, available):
    orq = _orq(monkeypatch, available=available)
    trase = DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1",
                          pd.DataFrame({"municipality": ["A", "B"], "exposicao_ha": [2.0, 1.0]}))
    spec_trase = parse_dashboard_spec({"title": "Exposição e base legal", "widgets": [
        {"id": "b", "kind": "bar", "title": "Exposição por município", "dataset_id": "D1", "x": "municipality",
         "y": ["exposicao_ha"], "orientation": "h", "unit": "ha", "source": "Trase — Soja [D1]"}]})
    monkeypatch.setattr(orq, "propose_dashboard_spec", lambda *a, **k: (spec_trase, 0, 0))
    from src.dashboard.schemas import ReviewResult
    monkeypatch.setattr(orq, "review_dashboard", lambda *a, **k: ReviewResult(approved=True, issues=[]))
    return orq.build_dashboard_from_store("painel da exposição da soja e o que diz o código florestal",
                                          _Sessao(_Store([trase])), domain="mixed", save=False)


def test_painel_misto_separa_base_legal(monkeypatch):
    res = _misto(monkeypatch, available=True)
    page = res.html
    legal = page[page.index('id="base-legal"'):]
    rankings = page[page.index('id="rankings"'):page.index('id="base-legal"')]
    assert 'data-widget-id="b"' in rankings and 'data-widget-id="b"' not in legal
    assert "lei_citacoes_" in legal and "lei_citacoes_" not in rankings
    assert LAW_FOOTER in page


def test_painel_misto_sem_acervo_entrega_a_parte_de_dados(monkeypatch):
    res = _misto(monkeypatch, available=False)
    assert [w.id for w in res.spec.widgets] == ["b"] and UNAVAILABLE_MESSAGE in res.spec.warnings
    assert 'id="base-legal"' not in res.html


def test_render_da_faixa_e_das_citacoes():
    res = _agente(BOAS)
    widgets, extra = build_law_widgets(res)
    spec = DashboardSpec(title="Leis", widgets=widgets)
    page = render_dashboard_html(spec, [*res.datasets, *extra])
    assert 'data-widget-kind="range"' in page and 'class="quote"' in page
    assert '"50 a 50 mi"' in page  # rótulo só com números: a unidade está no selo e no eixo
    assert "“sendo o mínimo de R$ 50,00" in page


def test_mesmo_artigo_com_dois_valores_vira_dois_itens():
    dois = [BOAS[2], dict(BOAS[2], valor_min=80, valor_max=80,
                          citacao_literal="Reserva Legal: I - localizado na Amazônia Legal: a) 80%")]
    res = _agente(dois)
    _, extra = build_law_widgets(res)
    rotulos = extra[0].df["rotulo"].tolist()
    assert len(rotulos) == 2 and len(set(rotulos)) == 2

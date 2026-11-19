"""Parte F: clareza para leigos (conclusão calculada, "Como ler", rodapé, estados, acessibilidade, impressão)."""
from __future__ import annotations

import re

import pandas as pd
import pytest

from src.dashboard.messages import EMPTY_SUGGESTIONS, ERROR_MESSAGE, PROGRESS_STEPS
from src.dashboard.renderer import (
    CAVEAT_FRAGMENTS,
    PAGE_CSS,
    caveat_text,
    chart_conclusion,
    how_to_read,
    measure_limit,
    period_text,
    render_dashboard_html,
    render_status_page,
)
from src.dashboard.schemas import DatasetResult, parse_dashboard_spec
from src.dashboard.validator import find_illegality_claim
from src.data_dictionary import CAVEATS

SERIE = pd.DataFrame({"year": list(range(2011, 2023)),
                      "volume_t": [8.1e6, 8.4e6, 8.7e6, 8.8e6, 8.5e6, 10.1e6, 11.3e6, 9.9e6, 10.5e6, 12.2e6, 12.5e6, 13.9e6],
                      "exposicao_ha": [17e3, 18e3, 19e3, 18.5e3, 23.5e3, 22.4e3, 29e3, 20.8e3, 20.8e3, 19.3e3, 15.3e3, 21.7e3]})
RANK = pd.DataFrame({"municipality": ["A", "B", "C"], "volume_t": [3.0, 2.0, 1.0]})


def _w(**kw):
    raw = {"id": "w", "kind": "line", "title": "Gráfico", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
           "unit": "t", "source": "Trase [D1]"}
    raw.update(kw)
    return parse_dashboard_spec({"title": "P", "widgets": [raw]}).widgets[0]


def _ds(did, df):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)


def _page(widgets, datasets):
    return render_dashboard_html(parse_dashboard_spec({"title": "Painel", "widgets": widgets}), datasets)


# --- F1: frase-conclusão calculada ---------------------------------------------------------

def test_linha_conclui_variacao_entre_primeiro_e_ultimo_ano():
    assert chart_conclusion(_w(), SERIE) == "Volume subiu 71,6% entre 2011 e 2022: de 8,10 mi t para 13,9 mi t."


def test_linha_cita_o_pico_quando_nao_e_ponta():
    frase = chart_conclusion(_w(y=["exposicao_ha"], unit="ha"), SERIE)
    assert frase.startswith("Exposição ao desmatamento subiu 27,6% entre 2011 e 2022")
    assert frase.endswith("O pico foi em 2017 (29,0 mil ha).")


def test_queda_e_plural_concordam():
    df = pd.DataFrame({"year": [2020, 2021], "emissoes_co2": [10.0, 5.0]})
    assert chart_conclusion(_w(y=["emissoes_co2"], unit="tCO2e"), df).startswith("Emissões caíram 50,0%")


def test_zero_antes_de_2015_em_exposicao_e_sem_dado_nao_ponto_de_partida():
    df = pd.DataFrame({"year": [2013, 2014, 2015, 2016], "exposicao_ha": [0, 0, 100.0, 150.0]})
    assert "entre 2015 e 2016" in chart_conclusion(_w(y=["exposicao_ha"], unit="ha"), df)


def test_mais_de_um_valor_por_ano_nao_agrega():
    df = pd.concat([SERIE, SERIE])
    assert chart_conclusion(_w(), df) is None


def test_barras_lider_com_participacao_no_total_mostrado():
    w = _w(kind="bar", x="municipality", orientation="h", dataset_id="D2")
    assert chart_conclusion(w, RANK) == "A lidera com 3 t, 50,0% do total mostrado."


def test_pizza_com_outros_fala_do_total():
    df = pd.DataFrame({"pais": ["CHINA", "SPAIN", "Outros"], "volume_t": [60.0, 10.0, 30.0]})
    assert chart_conclusion(_w(kind="pie", x="pais"), df) == "CHINA responde por 60,0% do total."


def test_percentual_nunca_vira_participacao_somada():
    df = pd.DataFrame({"uf": ["GO", "MT"], "zdc_pct": [40.0, 70.0]})
    assert chart_conclusion(_w(kind="bar", x="uf", y=["zdc_pct"], unit="%"), df) == "MT tem o maior valor: 70,0%."


def test_varios_anos_no_ranking_nao_somam_anos():
    df = pd.DataFrame({"year": [2021, 2022, 2021, 2022], "municipality": ["A", "A", "B", "B"],
                       "exposicao_ha": [5.0, 6.0, 1.0, 2.0]})
    frase = chart_conclusion(_w(kind="bar", x="municipality", y=["exposicao_ha"], unit="ha"), df)
    assert "%" not in frase and "do total" not in frase


def test_variacao_por_item_cita_maior_alta_e_maior_queda():
    df = pd.DataFrame({"pais": ["CHINA", "THAILAND", "SPAIN"], "variacao_t": [900.0, -180.0, 90.0]})
    assert chart_conclusion(_w(kind="waterfall", x="pais", y=["variacao_t"]), df) == \
        "Maior alta: CHINA (+900 t); maior queda: THAILAND (−180 t)."


def test_conclusoes_nunca_alegam_ilegalidade_nem_autoria():
    casos = [(_w(), SERIE), (_w(y=["exposicao_ha"], unit="ha"), SERIE),
             (_w(kind="bar", x="municipality", orientation="h"), RANK)]
    for w, df in casos:
        assert find_illegality_claim(chart_conclusion(w, df)) is None


def test_conclusao_aparece_no_cartao_e_na_descricao_do_grafico():
    page = _page([{"id": "l", "kind": "line", "title": "Volume", "dataset_id": "D1", "x": "year",
                   "y": ["volume_t"], "unit": "t", "source": "Trase [D1]"}], [_ds("D1", SERIE)])
    assert '<p class="conclusion">Volume subiu 71,6% entre 2011 e 2022' in page
    assert re.search(r'role="img" aria-label="Volume\. Volume subiu 71,6%[^"]*Ver dados', page)


# --- F2: "Como ler" vindo das ressalvas do dicionário ----------------------------------------

def test_trechos_do_como_ler_existem_literalmente_nas_caveats():
    for chave, trecho in CAVEAT_FRAGMENTS.items():
        assert any(trecho in c for c in CAVEATS), chave
        assert caveat_text(chave)


def test_como_ler_da_exposicao_traz_janela_e_estimativa():
    itens = how_to_read(_w(y=["exposicao_ha"], unit="ha"), SERIE)
    assert itens[0].startswith("Cada ponto")
    assert any("janela de 5 anos: não some entre anos" in t for t in itens)
    assert any("não prova de ilegalidade" in t for t in itens)
    assert not any("2015 em diante" in t for t in itens)  # 2011-2014 têm valor aqui


def test_como_ler_avisa_sem_dado_antes_de_2015_so_quando_os_dados_mostram():
    df = pd.DataFrame({"year": [2014, 2015], "exposicao_ha": [0, 100.0]})
    itens = how_to_read(_w(y=["exposicao_ha"], unit="ha"), df)
    assert any("zero ou vazio" in t and "NULL" not in t for t in itens)


def test_como_ler_de_percentual_e_botao_acessivel():
    df = pd.DataFrame({"uf": ["GO", "MT"], "zdc_pct": [40.0, 70.0]})
    assert any("não podem ser somados" in t for t in how_to_read(_w(kind="bar", x="uf", y=["zdc_pct"], unit="%"), df))
    page = _page([{"id": "b", "kind": "bar", "title": "ZDC", "dataset_id": "D1", "x": "uf", "y": ["zdc_pct"],
                   "unit": "%", "source": "Trase [D1]"}], [_ds("D1", df)])
    assert '<summary aria-label="Como ler este gráfico" title="Como ler">?</summary>' in page


# --- F3: rodapé de publicação --------------------------------------------------------------

def test_rodape_tem_fonte_com_id_periodo_e_limite():
    page = _page([{"id": "l", "kind": "line", "title": "Exposição", "dataset_id": "D1", "x": "year",
                   "y": ["exposicao_ha"], "unit": "ha", "source": "Trase — Soja"}], [_ds("D1", SERIE)])
    rodape = page[page.index('<footer class="card-footer">'):].split("</footer>")[0]
    assert "Fonte: Trase — Soja [D1]" in rodape and "Período: 2011–2022" in rodape
    assert "exposição ao desmatamento não é prova de ilegalidade" in rodape


def test_periodo_e_limite_so_com_dados_reais():
    assert period_text(_w(kind="bar", x="municipality"), RANK) is None
    assert measure_limit(_w()) is None
    assert period_text(_w(), SERIE.tail(1)) == "2022"


def test_indicador_mostra_periodo_na_fonte():
    page = _page([{"id": "k", "kind": "kpi", "title": "Volume", "dataset_id": "D1", "column": "volume_t",
                   "agg": "max", "unit": "t", "source": "Trase [D1]", "value": 13.9e6}], [_ds("D1", SERIE)])
    assert "Fonte: Trase [D1] · 2011–2022" in page


# --- F4: estados ---------------------------------------------------------------------------

def test_estado_carregando_mostra_etapas_em_texto_simples():
    page = render_status_page("loading")
    assert 'role="status" aria-live="polite"' in page
    for etapa in PROGRESS_STEPS:
        assert etapa in page
    assert "Buscando os dados" in PROGRESS_STEPS and "Montando os gráficos" in PROGRESS_STEPS


def test_estado_sem_dados_sugere_o_que_tentar():
    page = render_status_page("empty")
    assert "O que tentar" in page and all(s in page for s in EMPTY_SUGGESTIONS)
    vazio = render_dashboard_html(parse_dashboard_spec({"title": "Nada", "widgets": []}), [])
    assert EMPTY_SUGGESTIONS[0] in vazio


def test_estado_de_erro_sem_jargao_mesmo_com_detalhe_tecnico():
    page = render_status_page("error", detail="Binder Error: column foo_bar not found")
    assert 'role="alert"' in page and "Binder" not in page and "foo_bar" not in page
    with pytest.raises(ValueError):
        render_status_page("qualquer")


def test_erro_no_chat_nao_mostra_o_nome_tecnico():
    from src.pipeline.chat import _friendly_error_message
    msg = _friendly_error_message("dashboard", RuntimeError("Binder Error: Referenced column x_y not found"))
    assert msg == ERROR_MESSAGE and "Binder" not in msg and "Error" not in msg


def test_cartao_sem_dados_sugere_outro_recorte():
    page = _page([{"id": "l", "kind": "line", "title": "Volume", "dataset_id": "D9", "x": "year",
                   "y": ["volume_t"], "unit": "t", "source": "Trase [D9]"}], [_ds("D1", SERIE)])
    assert 'class="warn-hint"' in page


# --- F5: acessibilidade ----------------------------------------------------------------------

def test_ver_dados_traz_a_mesma_informacao_do_grafico():
    page = _page([{"id": "b", "kind": "bar", "title": "Ranking", "dataset_id": "D1", "x": "municipality",
                   "y": ["volume_t"], "orientation": "h", "unit": "t", "source": "Trase [D1]"}], [_ds("D1", RANK)])
    vista = page[page.index('<details class="data-view">'):].split("</details>")[0]
    assert "<summary>Ver dados</summary>" in vista and 'aria-label="Dados do gráfico: Ranking"' in vista
    assert ">Volume (t)</th>" in vista  # a unidade aparece no cabeçalho da tabela
    assert [c for c in re.findall(r'<span class="cell-v">([^<]+)</span>', vista)] == ["3", "2", "1"]


def test_foco_visivel_e_movimento_reduzido():
    assert ":focus-visible { outline: 2px solid var(--focus)" in PAGE_CSS
    reduzido = PAGE_CSS[PAGE_CSS.index("prefers-reduced-motion"):]
    assert "animation: none !important" in reduzido.split("}\n}")[0]


# --- F6: impressão ---------------------------------------------------------------------------

def test_impressao_em_tema_claro_sem_controles():
    impressao = PAGE_CSS[PAGE_CSS.index("@media print"):]
    assert ':root[data-theme="dark"]' in impressao and "--bg: #ffffff" in impressao
    for escondido in (".sidebar", ".help", "details.data-view", ".modebar"):
        assert escondido in impressao.split("display: none")[0]
    assert "print-color-adjust: exact" in impressao and "break-inside: avoid" in impressao

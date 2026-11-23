"""Parte B: tipos novos (pizza, rosca, medidor, variação por item, barras e linha alinhadas)."""
from __future__ import annotations

import re

import pandas as pd
import pytest

from src.dashboard.chart_intent import detect
from src.dashboard.renderer import NEUTRAL, build_widget_figure, render_dashboard_html
from src.dashboard.reviewer_agent import check_deterministic
from src.dashboard.schemas import ALLOWED_WIDGET_KINDS, BASE_KIND, DatasetResult, parse_dashboard_spec

MUNICIPIOS = pd.DataFrame({
    "municipality": ["Outros", "SORRISO", "RIO VERDE", "SAPEZAL", "UNKNOWN"],
    "volume_t": [70.0, 12.0, 9.0, 4.0, 5.0],
})
SERIE = pd.DataFrame({"year": [2019, 2020, 2021, 2022], "volume_t": [80.0, 85.0, 90.0, 93.7],
                      "fob_usd": [20e9, 22e9, 31e9, 47e9]})


def _ds(did, df):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)


def _w(**kw):
    base = {"id": "w", "kind": "pie", "title": "T", "dataset_id": "D1", "unit": "t", "source": "Trase [D1]",
            "x": "municipality", "y": ["volume_t"]}
    base.update(kw)
    return parse_dashboard_spec({"title": "P", "widgets": [base]}).widgets[0]


def _bloqueios(widget_raw, df):
    spec = parse_dashboard_spec({"title": "P", "widgets": [widget_raw]})
    return [i for i in check_deterministic(spec, [_ds("D1", df)]) if i.blocking]


def test_tipos_novos_existem_e_herdam_regras():
    for kind in ("pie", "donut", "gauge", "waterfall"):
        assert kind in ALLOWED_WIDGET_KINDS
    assert BASE_KIND["pie"] == BASE_KIND["donut"] == BASE_KIND["waterfall"] == "bar"
    assert BASE_KIND["gauge"] == "kpi"


def test_pedido_de_pizza_nao_gera_mais_aviso():
    escolha = detect("Quais foram os maiores municípios exportadores do Brasil? Faça uma pizza")
    assert escolha.kind == "pie" and escolha.notice is None


# --- B1: pizza e rosca --------------------------------------------------------------------

def test_pizza_dos_maiores_municipios_ordem_cor_e_rotulos():
    fig = build_widget_figure(_w(), MUNICIPIOS)
    pie = fig.data[0]
    assert list(pie.labels) == ["Sorriso", "Rio Verde", "Sapezal", "Outros", "Não identificado"]
    cores = list(pie.marker.colors)
    assert cores[-2:] == [NEUTRAL, NEUTRAL] and NEUTRAL not in cores[:3]
    # H1: todas as fatias com rótulo externo (inclusive as pequenas), sem legenda repetida
    assert pie.text[0] == "Sorriso · 12,0%" and pie.text[2].startswith("Sapezal · ")
    assert pie.textposition == "outside" and fig.layout.showlegend is False
    assert "%{customdata[0]}" in pie.hovertemplate and "%{customdata[1]}" in pie.hovertemplate
    assert pie.hole in (None, 0)


def test_rosca_tem_furo():
    assert build_widget_figure(_w(kind="donut"), MUNICIPIOS).data[0].hole == pytest.approx(0.58)


def test_pizza_sem_outros_avisa_que_e_participacao_entre_os_mostrados():
    df = MUNICIPIOS[~MUNICIPIOS.municipality.isin(["Outros", "UNKNOWN"])]
    page = render_dashboard_html(parse_dashboard_spec({"title": "P", "widgets": [_w().to_dict()]}), [_ds("D1", df)])
    assert "Participação entre os 3 itens mostrados, não sobre o total geral." in page


def test_pizza_com_mais_de_8_partes_vira_barras_com_aviso():
    df = pd.DataFrame({"municipality": [f"M{i}" for i in range(12)], "volume_t": [float(20 - i) for i in range(12)]})
    page = render_dashboard_html(parse_dashboard_spec({"title": "P", "widgets": [_w().to_dict()]}), [_ds("D1", df)])
    assert "Com mais de 8 partes a pizza fica difícil de ler, então mostrei em barras." in page
    assert '"type":"bar"' in page and '"type":"pie"' not in page


def test_pizza_de_exposicao_somada_entre_anos_continua_bloqueada():
    df = pd.DataFrame({"year": [2021, 2022, 2021], "state": ["MT", "MT", "GO"], "exposure_ha": [5.0, 6.0, 2.0]})
    issues = _bloqueios({"id": "p", "kind": "pie", "title": "T", "dataset_id": "D1", "x": "state",
                         "y": ["exposure_ha"], "unit": "ha", "source": "Trase [D1]"}, df)
    assert any(i.code == "janela_5_anos" for i in issues)


# --- B3: medidor --------------------------------------------------------------------------

GAUGE = {"id": "g", "kind": "gauge", "title": "Parte do volume que foi para a China (2022)", "dataset_id": "D1",
         "column": "china_pct", "agg": "first", "value": 71.86, "unit": "%", "source": "Trase — Soja [D1]"}


def test_medidor_mostra_percentual_dos_dados():
    df = pd.DataFrame({"china_pct": [71.86]})
    assert _bloqueios(GAUGE, df) == []
    page = render_dashboard_html(parse_dashboard_spec({"title": "P", "widgets": [GAUGE]}), [_ds("D1", df)])
    assert 'data-widget-kind="gauge"' in page and ">71,9%<" in page and 'data-value="71.8600"' in page
    assert 'id="visao-geral"' in page


@pytest.mark.parametrize("df, raw", [
    (pd.DataFrame({"volume_t": [93.7e6]}), {**GAUGE, "column": "volume_t", "value": 93.7e6, "unit": "t"}),
    (pd.DataFrame({"china_pct": [140.0]}), {**GAUGE, "value": 140.0}),
])
def test_medidor_so_aceita_percentual_entre_0_e_100(df, raw):
    assert any(i.code == "medidor" for i in _bloqueios(raw, df))


# --- B4: variação por item ----------------------------------------------------------------

VARIACAO = pd.DataFrame({"destino": ["CHINA", "SPAIN", "Outros"], "variacao_t": [5.0e6, -1.2e6, 0.4e6]})


def test_variacao_por_item_soma_as_contribuicoes():
    w = _w(kind="waterfall", x="destino", y=["variacao_t"])
    wf = build_widget_figure(w, VARIACAO).data[0]
    assert list(wf.x) == ["China", "Espanha", "Outros", "Variação total"]  # país em português na tela
    assert list(wf.measure) == ["relative", "relative", "relative", "total"]
    assert wf.y[-1] == pytest.approx(4.2e6)


def test_variacao_por_item_de_percentual_e_bloqueada():
    df = pd.DataFrame({"destino": ["A", "B"], "variacao_pct": [3.0, -1.0]})
    issues = _bloqueios({"id": "v", "kind": "waterfall", "title": "T", "dataset_id": "D1", "x": "destino",
                         "y": ["variacao_pct"], "unit": "%", "source": "Trase [D1]"}, df)
    assert any(i.code == "soma_percentual" for i in issues)


# --- B2: barras e linha em dois gráficos alinhados -----------------------------------------

def test_barras_e_linha_ficam_juntas_alinhadas_e_sem_segundo_eixo():
    spec = parse_dashboard_spec({"title": "P", "widgets": [
        {"id": "l", "kind": "line", "title": "Volume", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
         "unit": "t", "source": "Trase [D1]", "group": "par"},
        {"id": "k", "kind": "table", "title": "Tabela", "dataset_id": "D1", "unit": "t", "source": "Trase [D1]"},
        {"id": "b", "kind": "bar", "title": "Valor FOB", "dataset_id": "D1", "x": "year", "y": ["fob_usd"],
         "unit": "US$", "source": "Trase [D1]", "group": "par"},
    ]})
    page = render_dashboard_html(spec, [_ds("D1", SERIE)])
    i_l, i_b = page.index('data-widget-id="l"'), page.index('data-widget-id="b"')
    trecho = page[i_l:i_b]
    assert 'data-widget-id="k"' not in trecho  # os dois do par ficam lado a lado na página
    assert 'id="rankings"' not in page[:i_b] or page.index('id="evolucao"') < i_l
    ranges = re.findall(r'"range":\[2018\.5,2022\.5\]', page)
    assert len(ranges) == 2  # mesmo intervalo de tempo nos dois
    assert "yaxis2" not in page  # nunca dois eixos com escalas diferentes no mesmo gráfico
    for wid in ("l", "b"):
        assert f'class="card chart-card span-2" data-widget-id="{wid}"' in page


def test_pedido_barras_e_linha_instrui_o_par_com_grupo():
    linha = detect("quero barras e linha juntas").prompt_line()
    assert "`group`" in linha and "nunca dois eixos" in linha


# --- B5: rótulo no fim da barra ------------------------------------------------------------

def test_barras_horizontais_com_percentual_no_fim():
    df = pd.DataFrame({"pais": ["CHINA", "SPAIN"], "share_pct": [71.9, 4.1]})
    fig = build_widget_figure(_w(kind="bar", x="pais", y=["share_pct"], unit="%", orientation="h"), df)
    assert list(fig.data[0].text) == ["4,1%", "71,9%"]  # horizontal: o maior fica no topo
    fig_t = build_widget_figure(_w(kind="bar", x="municipality", orientation="h"), MUNICIPIOS)
    assert list(fig_t.data[0].text)[-1] == "12"  # valor curto no fim da barra (unidade no selo)


def _contraste(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        r, g, bl = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_rotulo_da_fatia_tem_contraste_nos_dois_temas():
    pie = build_widget_figure(_w(), MUNICIPIOS).data[0]
    assert pie.textposition == "outside" and pie.outsidetextfont.size == 12  # H1: fora da fatia
    page = render_dashboard_html(parse_dashboard_spec({"title": "P", "widgets": [_w().to_dict()]}),
                                 [_ds("D1", MUNICIPIOS)])
    assert ".main-svg .slicetext { fill: var(--fg) !important; }" in page  # o texto segue o tema

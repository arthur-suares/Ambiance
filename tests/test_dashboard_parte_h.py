"""Parte H: polimento visual (pizza, nomes, base na conclusão, unidade uma vez só)."""
from __future__ import annotations

import pandas as pd

from src.dashboard.renderer import (
    NEUTRAL,
    PALETTE,
    build_widget_figure,
    chart_conclusion,
    display_label,
    pie_colors,
    render_dashboard_html,
    title_case_name,
)
from src.dashboard.data_base import infer_base
from src.dashboard.schemas import DatasetResult, parse_dashboard_spec


def _w(**kw):
    raw = {"id": "p", "kind": "pie", "title": "Maiores", "dataset_id": "D1", "x": "municipality",
           "y": ["volume_t"], "unit": "t", "source": "Trase [D1]"}
    raw.update(kw)
    return parse_dashboard_spec({"title": "P", "widgets": [raw]}).widgets[0]


def _ds(df, sql="SELECT 1"):
    return DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", sql, df)


def _lab(hexcor):
    h = hexcor.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _delta_e(a, b):
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5


MUNIS = pd.DataFrame({"municipality": ["SORRISO", "RIO VERDE", "SAPEZAL", "JATAI", "CRISTALINA", "MINEIROS",
                                       "Outros"],
                      "volume_t": [40.0, 20.0, 10.0, 8.0, 6.0, 1.0, 15.0]})


# --- H1 -----------------------------------------------------------------------------------------

def test_fatias_vizinhas_nunca_tem_tons_quase_iguais():
    assert len(PALETTE) <= 6
    for n in range(2, 7):
        cores = pie_colors([False] * n)
        vizinhas = list(zip(cores, cores[1:] + cores[:1])) if n > 2 else [(cores[0], cores[1])]
        for a, b in vizinhas:
            assert _delta_e(a, b) >= 15, (n, a, b)
    assert pie_colors([False, True]) == [PALETTE[0], NEUTRAL]


def test_fatia_pequena_tem_rotulo_externo_e_mesmo_tamanho():
    fig = build_widget_figure(_w(), MUNIS)
    pie = fig.data[0]
    assert all(t for t in pie.text)  # nenhuma fatia sem rótulo (a de 1% também)
    assert pie.textposition == "outside" and pie.outsidetextfont.size == 12
    assert fig.layout.showlegend is False


# --- H2 -----------------------------------------------------------------------------------------

def test_nomes_em_formato_de_titulo_mantendo_siglas():
    assert title_case_name("LOUIS DREYFUS COMPANY") == "Louis Dreyfus Company"
    assert title_case_name("CARGILL") == "Cargill"
    assert title_case_name("ADM") == "ADM" and title_case_name("COFCO INTERNATIONAL") == "COFCO International"
    assert title_case_name("LDC") == "LDC"
    assert title_case_name("CAMPO ALEGRE DE GOIAS") == "Campo Alegre de Goias"


def test_titulo_so_na_exibicao_e_so_para_empresas_e_municipios():
    assert display_label("RIO VERDE", "municipality") == "Rio Verde"
    assert display_label("BUNGE", "exporter_group") == "Bunge"
    assert display_label("CHINA (MAINLAND)", "country_of_first_import") == "China"  # auditoria item 7: país em português na tela
    df = MUNIS.copy()
    render_dashboard_html(parse_dashboard_spec({"title": "P", "widgets": [_w().to_dict()]}), [_ds(df)])
    assert df["municipality"].iloc[0] == "SORRISO"  # os dados não mudam


# --- H3 -----------------------------------------------------------------------------------------

def test_conclusao_diz_a_base_em_palavras_simples():
    rank = pd.DataFrame({"municipality": ["A", "B", "C"], "volume_t": [18.0, 50.0, 32.0]})
    sql = ("SELECT municipality_of_production AS municipality, SUM(volume) volume_t FROM soy_supply_chain "
           "WHERE year = 2022 AND municipality_of_production <> 'UNKNOWN' GROUP BY 1")
    frase = chart_conclusion(_w(kind="bar", orientation="h"), rank, infer_base(_ds(rank, sql)))
    assert frase == "B lidera com 50 t, 50,0% do volume dos 3 municípios mostrados com origem identificada, em 2022."


def test_com_outros_a_base_e_o_total_e_nunca_so_do_total():
    frase = chart_conclusion(_w(), MUNIS)
    assert frase == "Sorriso responde por 40,0% do volume total."
    for kind in ("pie", "bar"):
        f = chart_conclusion(_w(kind=kind), MUNIS) or ""
        assert not f.endswith(("do total.", "do total mostrado."))


def test_origem_nao_identificada_aparece_na_base():
    df = pd.DataFrame({"municipality": ["A", "UNKNOWN"], "volume_t": [10.0, 30.0]})
    assert "incluindo origem não identificada" in chart_conclusion(_w(kind="bar"), df)


# --- H4 -----------------------------------------------------------------------------------------

def _badge(page, wid):
    card = page[page.index(f'data-widget-id="{wid}"'):]
    return card[:1500]


def test_grafico_de_porcentagem_nao_tem_selo_t():
    for kind in ("pie", "donut", "progress"):
        page = render_dashboard_html(parse_dashboard_spec({"title": "P", "widgets": [_w(kind=kind).to_dict()]}),
                                     [_ds(MUNIS)])
        assert '<span class="badge">%</span>' in _badge(page, "p") and '<span class="badge">t</span>' not in _badge(page, "p")


def test_unidade_uma_vez_so_selo_sem_repetir_no_eixo():
    fig = build_widget_figure(_w(kind="bar", orientation="h"), MUNIS)
    assert fig.layout.xaxis.title.text == "Volume"
    linha = build_widget_figure(_w(kind="line", x="year", y=["volume_t"]),
                                pd.DataFrame({"year": [2021, 2022], "volume_t": [1.0, 2.0]}))
    assert "(t)" not in (linha.layout.yaxis.title.text or "")


def test_contagem_tem_marcas_inteiras():
    df = pd.DataFrame({"ano": ["1998", "2012"], "normas": [1, 1]})
    fig = build_widget_figure(_w(kind="bar", x="ano", y=["normas"], unit="normas"), df)
    assert all(float(v).is_integer() for v in fig.layout.yaxis.tickvals)

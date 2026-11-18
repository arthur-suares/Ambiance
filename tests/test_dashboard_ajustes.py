"""Ajustes do dashboard encontrados ao conferir o painel "Panorama da soja em Goiás".

Cobre: BRAZIL -> BRASIL (com ressalva em coluna de destino), unidade duplicada no eixo,
eixo Y de séries não negativas partindo de zero e a troca de "Brazil" por "Brasil" nos textos.
"""
from __future__ import annotations

import pandas as pd

from src.dashboard.dashboard_agent import DASHBOARD_SYSTEM_PROMPT
from src.dashboard.data_agent import DATA_AGENT_PROMPT
from src.dashboard.renderer import (
    _axis_title,
    build_widget_figure,
    display_label,
    format_br_value,
    pt_text,
    render_dashboard_html,
)
from src.dashboard.schemas import DatasetResult, parse_dashboard_spec

DEST = pd.DataFrame({
    "country_of_first_import": ["CHINA (MAINLAND)", "BRAZIL", "THAILAND"],
    "volume_t": [6097318.2, 3640446.7, 806971.8],
})


def _widget(**kw):
    base = {"id": "w", "kind": "bar", "title": "t", "dataset_id": "D1", "unit": "t", "source": "Trase [D1]"}
    base.update(kw)
    return parse_dashboard_spec({"title": "T", "widgets": [base]}).widgets[0]


def test_brazil_vira_brasil_com_ressalva_so_na_coluna_de_destino():
    assert display_label("BRAZIL", "country_of_first_import") == "BRASIL (processamento doméstico)"
    assert display_label("BRAZIL", "state") == "BRASIL"
    assert display_label("brazil", "") == "BRASIL"
    assert display_label("CHINA (MAINLAND)", "country_of_first_import") == "CHINA (MAINLAND)"
    assert display_label("BRAZILIAN CO", "country_of_first_import") == "BRAZILIAN CO"  # só o valor exato


def test_tabela_mostra_brasil_e_mantem_os_demais_valores():
    assert format_br_value("BRAZIL", "country_of_first_import") == "BRASIL (processamento doméstico)"
    assert format_br_value(6097318.2, "volume_t") == "6.097.318,2"
    assert format_br_value(2022, "year") == "2022"


def test_grafico_de_barras_mostra_brasil_nas_categorias():
    w = _widget(kind="bar", x="country_of_first_import", y=["volume_t"], orientation="h")
    fig = build_widget_figure(w, DEST)
    cats = list(fig.data[0].y)
    assert "BRASIL (processamento doméstico)" in cats
    assert not any(c.upper() == "BRAZIL" for c in cats)


def test_titulo_do_eixo_nao_repete_a_unidade():
    assert _axis_title("Volume (t)", "t") == "Volume (t)"
    assert _axis_title("Volume", "t") == "Volume (t)"
    assert _axis_title("Volume (toneladas)", "t") == "Volume (toneladas)"
    assert _axis_title("", "ha") == "ha"
    assert _axis_title("Exposição", "") == "Exposição"


def test_eixos_do_grafico_nao_ficam_com_unidade_duplicada():
    df = pd.DataFrame({"year": [2020, 2021, 2022], "volume_t": [12.1, 12.5, 13.9]})
    w = _widget(kind="line", x="year", y=["volume_t"], column_labels={"volume_t": "Volume (t)"})
    fig = build_widget_figure(w, df)
    assert fig.layout.yaxis.title.text == "Volume (t)"


def test_linha_nao_negativa_parte_de_zero_e_negativa_nao():
    pos = pd.DataFrame({"year": [2020, 2021, 2022], "v": [6.0, 7.0, 8.0]})
    neg = pd.DataFrame({"year": [2020, 2021, 2022], "v": [-2.0, 1.0, 3.0]})
    w = _widget(kind="line", x="year", y=["v"])
    assert build_widget_figure(w, pos).layout.yaxis.rangemode == "tozero"
    assert build_widget_figure(w, neg).layout.yaxis.rangemode is None


def test_texto_livre_troca_brazil_por_brasil_sem_mexer_em_outras_palavras():
    assert pt_text("Soja do Brazil em 2022") == "Soja do Brasil em 2022"
    assert pt_text("BRAZIL (MAINLAND)") == "Brasil (MAINLAND)"
    assert pt_text("Brazilian") == "Brazilian"
    assert pt_text(None) == ""


def test_html_final_usa_brasil_no_titulo_e_na_tabela():
    spec = parse_dashboard_spec({
        "title": "Soja do Brazil por destino",
        "subtitle": "Destinos da soja do Brazil",
        "widgets": [{
            "id": "w_t", "kind": "table", "title": "Destinos", "dataset_id": "D1",
            "columns": ["country_of_first_import", "volume_t"], "unit": "t", "source": "Trase [D1]",
        }],
    })
    html_out = render_dashboard_html(spec, [DatasetResult(dataset_id="D1", database="soy.duckdb", source_label="Trase — Soja", tool_name="run_soy_sql", query_summary="q", df=DEST)])
    assert "Soja do Brasil por destino" in html_out
    assert "BRASIL (processamento dom" in html_out  # o Plotly escreve o acento como \u00e9
    assert '"BRAZIL"' not in html_out  # nenhuma célula da tabela mostra o valor cru


def test_prompts_trazem_as_regras_novas():
    for trecho in ("Brasil", "processamento doméstico", "tradings", "(exceto Brasil)"):
        assert trecho in DASHBOARD_SYSTEM_PROMPT
    assert "country_of_first_import <> 'BRAZIL'" in DATA_AGENT_PROMPT
    assert "importer_group" in DATA_AGENT_PROMPT

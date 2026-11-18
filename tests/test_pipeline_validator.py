"""Testes offline do validador metodológico em código (R5)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.reviewer_agent import check_deterministic, review_dashboard
from src.dashboard.schemas import DatasetResult, parse_dashboard_spec
from src.dashboard.validator import (
    FIVE_YEAR_WINDOW_COLUMNS,
    NON_ADDITIVE_COLUMNS,
    PERCENTAGE_COLUMNS,
    is_five_year_window_column,
    is_non_additive_column_or_unit,
)


def _forbid_llm(monkeypatch):
    def _boom():
        raise AssertionError("O LLM NÃO pode ser chamado nas verificações determinísticas do validador!")

    monkeypatch.setattr("src.dashboard._llm.get_client", _boom)


@pytest.fixture
def multiyear_soy_ds() -> DatasetResult:
    df = pd.DataFrame({
        "year": [2020, 2021, 2022],
        "state": ["MATO GROSSO", "MATO GROSSO", "MATO GROSSO"],
        "soy_deforestation_5_year_total_exposure": [12000.0, 15000.0, 18000.0],
        "co2_gross_emissions_soy_deforestation_5_year_total_exposure": [50000.0, 60000.0, 70000.0],
        "volume": [1000000.0, 1100000.0, 1200000.0],
    })
    return DatasetResult(
        dataset_id="D1",
        database="soy.duckdb",
        source_label="Trase — Cadeia da soja (soy.duckdb)",
        tool_name="run_soy_sql",
        query_summary="SELECT year, state, ... FROM soy_supply_chain",
        df=df,
    )


@pytest.fixture
def single_year_beef_ds() -> DatasetResult:
    df = pd.DataFrame({
        "year": [2023, 2023, 2023],
        "municipality": ["SAO FELIX DO XINGU", "ALTAMIRA", "MARABA"],
        "deforestation_exposure_ha": [45000.0, 32000.0, 21000.0],
        "volume_t": [90000.0, 75000.0, 50000.0],
    })
    return DatasetResult(
        dataset_id="D1",
        database="trase.duckdb",
        source_label="Trase — Cadeia da carne bovina (trase.duckdb)",
        tool_name="top_municipalities",
        query_summary="top_municipalities(year=2023)",
        df=df,
    )


def test_dictionary_derivation_includes_beef_and_soy_catalog_columns():
    for col in (
        "deforestation_exposure_ha",
        "cattle_deforestation_5_year_total_exposure",
        "soy_deforestation_5_year_total_exposure",
        "co2_net_emissions_soy_deforestation_5_year_total_exposure",
        "co2_gross_emissions_soy_deforestation_5_year_total_exposure",
        "soy_deforestation_5y_ha",
        "soy_deforestation_gross_emissions_5y_tco2e",
    ):
        assert col in FIVE_YEAR_WINDOW_COLUMNS or is_five_year_window_column(col)
    assert is_five_year_window_column("exposure_ha")

    for col in ("zdc_exported_pct", "soy_yield_t_per_ha", "cattle_deforestation_ha_per_t"):
        assert col in NON_ADDITIVE_COLUMNS
    assert "zdc_exported_pct" in PERCENTAGE_COLUMNS

    for alias in ("desmat_ha_por_kt", "co2_t_por_t_soja", "preco_usd_t", "exposure_ha_per_t"):
        assert is_non_additive_column_or_unit(alias, "")


# --- R5-a: KPI sum/mean em coluna de janela de 5 anos com múltiplos anos --------

@pytest.mark.parametrize("agg,val", [("sum", 45000.0), ("mean", 15000.0)])
def test_r5a_blocks_kpi_sum_or_mean_on_5y_column_across_years(monkeypatch, multiyear_soy_ds, agg, val):
    _forbid_llm(monkeypatch)
    spec = parse_dashboard_spec({
        "title": "Soja em Mato Grosso",
        "subtitle": "2020–2022",
        "widgets": [{
            "id": "kpi_5y",
            "kind": "kpi",
            "title": "Exposição ao desmatamento 2020–2022",
            "dataset_id": "D1",
            "column": "soy_deforestation_5_year_total_exposure",
            "agg": agg,
            "value": val,
            "unit": "ha",
            "source": "Trase — Soja [D1]",
        }],
    })
    review = review_dashboard("Exposição da soja", spec, [multiyear_soy_ds])
    assert review.approved is False
    assert review.llm_called is False
    assert any(i.widget_id == "kpi_5y" and "5 anos" in i.message for i in review.issues)


def test_r5a_allows_kpi_sum_on_single_year_dataset(single_year_beef_ds):
    spec = parse_dashboard_spec({
        "title": "Top 3 municípios (2023)",
        "subtitle": "Origem rastreada",
        "widgets": [{
            "id": "kpi_ok",
            "kind": "kpi",
            "title": "Soma da exposição nos 3 municípios líderes (2023)",
            "dataset_id": "D1",
            "column": "deforestation_exposure_ha",
            "agg": "sum",
            "value": 98000.0,
            "unit": "ha",
            "source": "Trase — Carne bovina [D1]",
        }],
    })
    assert check_deterministic(spec, [single_year_beef_ds]) == []


# --- R5-b: bar/line com y de janela de 5 anos em vários anos sem x/color=ano ----

def test_r5b_blocks_bar_aggregating_5y_exposure_across_years(monkeypatch, multiyear_soy_ds):
    _forbid_llm(monkeypatch)
    spec = parse_dashboard_spec({
        "title": "Exposição por UF (2020–2022)",
        "subtitle": "",
        "widgets": [{
            "id": "bar_multiyear",
            "kind": "bar",
            "title": "Total 2020–2022 por estado",
            "dataset_id": "D1",
            "x": "state",
            "y": ["soy_deforestation_5_year_total_exposure"],
            "unit": "ha",
            "source": "Trase — Soja [D1]",
        }],
    })
    review = review_dashboard("Total por estado", spec, [multiyear_soy_ds])
    assert review.approved is False
    assert review.llm_called is False
    assert any(i.widget_id == "bar_multiyear" and "5 anos" in i.message for i in review.issues)


def test_r5b_allows_annual_series_and_single_year_ranking(multiyear_soy_ds, single_year_beef_ds):
    annual_spec = parse_dashboard_spec({
        "title": "Evolução anual da exposição (2020–2022)",
        "subtitle": "Comparação lado a lado por ano",
        "widgets": [
            {
                "id": "line_annual",
                "kind": "line",
                "title": "Exposição anual da soja (2020–2022)",
                "dataset_id": "D1",
                "x": "year",
                "y": ["soy_deforestation_5_year_total_exposure"],
                "unit": "ha",
                "source": "Trase — Soja [D1]",
            },
            {
                "id": "bar_by_color_year",
                "kind": "bar",
                "title": "Exposição por estado e ano",
                "dataset_id": "D1",
                "x": "state",
                "y": ["soy_deforestation_5_year_total_exposure"],
                "color": "year",
                "unit": "ha",
                "source": "Trase — Soja [D1]",
            },
        ],
    })
    assert check_deterministic(annual_spec, [multiyear_soy_ds]) == []

    ranking_spec = parse_dashboard_spec({
        "title": "Ranking municipal em 2023",
        "subtitle": "Origem rastreada",
        "widgets": [{
            "id": "bar_single_year",
            "kind": "bar",
            "title": "Exposição por município em 2023",
            "dataset_id": "D1",
            "x": "municipality",
            "y": ["deforestation_exposure_ha"],
            "unit": "ha",
            "source": "Trase — Carne bovina [D1]",
        }],
    })
    assert check_deterministic(ranking_spec, [single_year_beef_ds]) == []


# --- R5-c: KPI sum em não aditivas (%, intensidade, produtividade) e mean em % --

@pytest.mark.parametrize(
    "col,unit,vals",
    [
        ("zdc_exported_pct", "%", [40.0, 50.0]),
        ("soy_yield_t_per_ha", "t/ha", [3.2, 3.6]),
        ("desmat_ha_por_kt", "ha/kt", [1.5, 2.5]),
    ],
)
def test_r5c_blocks_kpi_sum_on_non_additive_columns(monkeypatch, col, unit, vals):
    _forbid_llm(monkeypatch)
    ds = DatasetResult(
        dataset_id="D1",
        database="soy.duckdb",
        source_label="Trase — Soja",
        tool_name="soy_territorial_metric",
        query_summary="q",
        df=pd.DataFrame({"year": [2022, 2022], "region": ["MT", "PR"], col: vals}),
    )
    spec = parse_dashboard_spec({
        "title": "Indicadores estaduais (2022)",
        "widgets": [{
            "id": "kpi_non_add",
            "kind": "kpi",
            "title": "Indicador consolidado (2022)",
            "dataset_id": "D1",
            "column": col,
            "agg": "sum",
            "value": sum(vals),
            "unit": unit,
            "source": "Trase — Soja [D1]",
        }],
    })
    review = review_dashboard("Indicadores", spec, [ds])
    assert review.approved is False
    assert review.llm_called is False
    assert any(i.widget_id == "kpi_non_add" and "não aditiva" in i.message for i in review.issues)


def test_r5c_kpi_mean_on_percentage_requires_media_in_title(monkeypatch):
    _forbid_llm(monkeypatch)
    ds = DatasetResult(
        dataset_id="D1",
        database="soy.duckdb",
        source_label="Trase — Soja",
        tool_name="soy_territorial_metric",
        query_summary="q",
        df=pd.DataFrame({"year": [2022, 2022], "region": ["MT", "PR"], "zdc_exported_pct": [40.0, 60.0]}),
    )
    bad_spec = parse_dashboard_spec({
        "title": "Compromissos ZDC (2022)",
        "widgets": [{
            "id": "kpi_pct_sem_media",
            "kind": "kpi",
            "title": "Participação ZDC nos estados (2022)",
            "dataset_id": "D1",
            "column": "zdc_exported_pct",
            "agg": "mean",
            "value": 50.0,
            "unit": "%",
            "source": "Trase — Soja [D1]",
        }],
    })
    review = review_dashboard("ZDC", bad_spec, [ds])
    assert review.approved is False
    assert review.llm_called is False
    assert any("média" in i.message for i in review.issues)

    good_spec = parse_dashboard_spec({
        "title": "Compromissos ZDC (2022)",
        "widgets": [{
            "id": "kpi_pct_com_media",
            "kind": "kpi",
            "title": "Média simples do percentual ZDC entre UFs (2022)",
            "dataset_id": "D1",
            "column": "zdc_exported_pct",
            "agg": "mean",
            "value": 50.0,
            "unit": "%",
            "source": "Trase — Soja [D1]",
        }],
    })
    assert check_deterministic(good_spec, [ds]) == []


# --- R5-d: UNKNOWN em ranking municipal da soja gera aviso, sem bloquear --------

def test_r5d_soy_municipal_ranking_with_unknown_adds_warning_without_blocking():
    ds = DatasetResult(
        dataset_id="D1",
        database="soy.duckdb",
        source_label="Trase — Cadeia da soja (soy.duckdb)",
        tool_name="soy_top_municipalities",
        query_summary='soy_top_municipalities({"year": 2022})',
        df=pd.DataFrame({
            "municipality": ["UNKNOWN", "SORRISO", "SAO DESIDERIO"],
            "state": ["UNKNOWN STATE", "MATO GROSSO", "BAHIA"],
            "volume_tonnes": [5000000.0, 2100000.0, 1400000.0],
            "exposure_ha": [18000.0, 4200.0, 3900.0],
        }),
    )
    spec = parse_dashboard_spec({
        "title": "Municípios da soja em 2022",
        "subtitle": "Cadeia da soja",
        "widgets": [{
            "id": "bar_soy_muni",
            "kind": "bar",
            "title": "Maiores volumes por município (2022)",
            "dataset_id": "D1",
            "x": "municipality",
            "y": ["volume_tonnes"],
            "unit": "t",
            "source": "Trase — Soja [D1]",
        }],
    })
    issues = check_deterministic(spec, [ds])
    assert issues == []
    assert any("UNKNOWN" in w for w in spec.warnings)


# --- R5-e: alegações de ilegalidade ou autoria recusadas sem chamar LLM ---------

@pytest.mark.parametrize(
    "bad_phrase",
    [
        "Desmatamento ilegal em 2023",
        "Empresas que cometeram crime ambiental",
        "Exportadora culpada pela supressão",
        "Municípios onde a cadeia violou a lei",
        "Ranking de empresas responsáveis pelo desmatamento",
        "Empresa responsável pelo desmatamento no Pará",
    ],
)
def test_r5e_blocks_illegality_or_authorship_claims_in_titles_subtitles_and_warnings(
    monkeypatch, single_year_beef_ds, bad_phrase
):
    _forbid_llm(monkeypatch)
    spec = parse_dashboard_spec({
        "title": "Análise Pará 2023",
        "subtitle": "",
        "widgets": [{
            "id": "bar1",
            "kind": "bar",
            "title": bad_phrase,
            "dataset_id": "D1",
            "x": "municipality",
            "y": ["deforestation_exposure_ha"],
            "unit": "ha",
            "source": "Trase — Carne bovina [D1]",
        }],
    })
    review = review_dashboard("Pergunta", spec, [single_year_beef_ds])
    assert review.approved is False
    assert review.llm_called is False
    assert any("exposição" in i.message.lower() for i in review.issues)

    # Também bloqueia se aparecer em spec.warnings
    spec_warn = parse_dashboard_spec({
        "title": "Exposição ao desmatamento em 2023",
        "subtitle": "Origem rastreada",
        "widgets": [{
            "id": "bar2",
            "kind": "bar",
            "title": "Exposição por município em 2023",
            "dataset_id": "D1",
            "x": "municipality",
            "y": ["deforestation_exposure_ha"],
            "unit": "ha",
            "source": "Trase — Carne bovina [D1]",
        }],
    })
    spec_warn.warnings.append(bad_phrase)
    rev_warn = review_dashboard("Pergunta", spec_warn, [single_year_beef_ds])
    assert rev_warn.approved is False
    assert rev_warn.llm_called is False


def test_r5e_allows_exposure_wording_and_negated_disclaimer(single_year_beef_ds):
    spec = parse_dashboard_spec({
        "title": "Exposição ao desmatamento na carne bovina (2023)",
        "subtitle": "Exposição não é prova de ilegalidade; ranking cobre a origem rastreada.",
        "widgets": [{
            "id": "bar_ok",
            "kind": "bar",
            "title": "Municípios com maior exposição ao desmatamento (2023)",
            "subtitle": "Indicador de exposição associada aos fluxos",
            "dataset_id": "D1",
            "x": "municipality",
            "y": ["deforestation_exposure_ha"],
            "unit": "ha",
            "source": "Trase — Carne bovina [D1]",
        }],
    })
    assert check_deterministic(spec, [single_year_beef_ds]) == []

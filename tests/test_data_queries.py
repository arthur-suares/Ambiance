"""Consultas prontas contra os bancos reais (pulados se os bancos não foram gerados)."""

import pytest

from src.config import DUCKDB_PATH
from src.soy.ingest import DEFAULT_DUCKDB_PATH as SOY_DUCKDB_PATH

soy = pytest.mark.skipif(not SOY_DUCKDB_PATH.exists(), reason="banco da soja não gerado (ingest-soy)")
beef = pytest.mark.skipif(not DUCKDB_PATH.exists(), reason="banco da carne bovina não gerado (build-db)")


@soy
def test_soy_exporters_by_group_and_volume_excludes_what_is_not_an_exporter():
    from src.soy import queries as q
    df = q.top_exporters(limit=5, year=2022, order_by="volume_tonnes")
    assert list(df.columns) == ["year", "exporter_group", "volume_tonnes", "exposure_ha"]
    assert not set(df["exporter_group"]) & set(q.NOT_AN_EXPORTER)
    assert df["volume_tonnes"].is_monotonic_decreasing
    meta = df.attrs["meta"]
    assert meta["cadeia"] == "soja" and meta["ano"] == 2022 and "volume_tonnes" in meta["ordenado_por"]
    assert "exporter_group" in meta["agrupado_por"] and len(meta["excluidos"]) == 2
    assert any("do volume" in n for n in meta["notas"])  # quanto o excluído representa


@soy
def test_soy_exporters_order_and_level_change_the_ranking():
    from src.soy import queries as q
    by_volume = q.top_exporters(limit=1, year=2022, order_by="volume_tonnes")
    by_exposure = q.top_exporters(limit=1, year=2022, order_by="exposure_ha")
    assert by_volume["exporter_group"][0] != by_exposure["exporter_group"][0]  # liderar em volume != em exposição
    companies = q.top_exporters(limit=3, year=2022, by_group=False, order_by="volume_tonnes", include_unidentified=True)
    assert "exporter" in companies.columns and "PROCESSED DOMESTICALLY" in set(companies["exporter"])
    with pytest.raises(ValueError):
        q.top_exporters(order_by="fob")


@soy
def test_soy_rankings_default_to_the_latest_year_and_drop_unknown_origin():
    from src.soy import queries as q
    df = q.top_municipalities(limit=3)
    assert set(df["year"]) == {q.latest_year()} and "UNKNOWN" not in set(df["municipality"])
    assert "UNKNOWN" in set(q.top_municipalities(limit=3, include_unknown=True)["municipality"])
    assert "BRAZIL" not in set(q.top_destinations(limit=50)["destination"])
    amazon = q.yearly_trend(biome="amazônia")
    assert 0 < amazon["exposure_ha"].iloc[-1] < q.yearly_trend()["exposure_ha"].iloc[-1]


@soy
def test_soy_facilities_show_both_processing_counts():
    from src.soy import queries as q
    df = q.facilities_summary(order_by="processing_capacity_t_day", limit=1)
    assert {"processing_facilities", "facilities_with_processing_capacity"} <= set(df.columns)
    assert df.attrs["meta"]["escopo"].startswith("instalações")


@beef
def test_beef_deforestation_by_region_sums_chain_flows():
    from src import queries as q
    from src import result_meta as rm
    biomes = q.deforestation_by_region(level="biome", year=2022)
    assert "UNKNOWN" in set(biomes["biome"]) and biomes["deforestation_exposure_ha"].is_monotonic_decreasing
    known = q.deforestation_by_region(level="biome", year=2022, include_unknown=False)
    assert "UNKNOWN" not in set(known["biome"]) and known["biome"].iloc[0] == "CERRADO"
    # mesma conta do gabarito: soma de flows_by_municipality
    mt = q.deforestation_by_region(level="state", year=2023, region="MT")
    expected = q._run("SELECT SUM(deforestation_exposure_ha) AS e FROM flows_by_municipality "
                      "WHERE year = 2023 AND state_of_production = 'MATO GROSSO'")["e"][0]
    assert len(mt) == 1 and mt["deforestation_exposure_ha"][0] == pytest.approx(expected)
    assert mt.attrs["meta"]["escopo"] == rm.FLOWS
    with pytest.raises(ValueError):
        q.deforestation_by_region(level="municipality")


@beef
def test_beef_region_position_ignores_unknown_and_survives_the_filter():
    from src import queries as q
    biomes = q.deforestation_by_region(level="biome", year=2022)
    unknown = biomes["biome"] == "UNKNOWN"
    assert biomes.loc[unknown, "posicao"].isna().all()  # origem não rastreada não é região
    assert biomes.set_index("biome").loc["CERRADO", "posicao"] == 1
    # com filtro, a Amazônia continua em 2º, não vira "1º de 1"
    amazon = q.deforestation_by_region(level="biome", year=2022, region="AMAZONIA")
    assert len(amazon) == 1 and amazon["posicao"][0] == 2


@soy
def test_soy_biome_position_ignores_unknown():
    from src.soy import queries as q
    df = q.deforestation_by_biome(year=2022)
    assert df.loc[df["biome"] == "UNKNOWN", "posicao"].isna().all()
    assert df.set_index("biome").loc["CERRADO", "posicao"] == 1


@beef
def test_beef_queries_carry_scope_and_units():
    from src import queries as q
    from src import result_meta as rm
    ranking = q.top_exporters(limit=3, year=2023, order_by="volume_t").attrs["meta"]
    assert ranking["escopo"] == rm.FLOWS and "volume_t" in ranking["ordenado_por"] and ranking["ano"] == 2023
    territorial = q.territorial_metric("pasture_area_ha", limit=1).attrs["meta"]
    assert territorial["escopo"] == rm.TERRITORIAL and territorial["unidades"]["value"].startswith("ha")

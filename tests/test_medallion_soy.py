"""Testes do medalhão da soja (sem LLM e sem Postgres; dados sintéticos pequenos)."""
import duckdb
import numpy as np
import pandas as pd
import pytest

from src import config
from src.medallion import agent_db, catalog, inpe, registry, soy_flows
from src.medallion.core import (Check, Lake, QualityGateError, enforce, municipality_id_from_trase, normalize_name)
from src.soy import queries as soy_queries


def bronze_df():
    rows = [  # year, biome, state, trase_id, municipality, exporter_group, exporter, dest, bloc, vol, fob, expo
        (2012, "CERRADO", "MATO GROSSO", "BR-5107925", "SORRISO", "ADM", "ADM BRASIL", "CHINA", "ASIA", 100.0, 1000.0, np.nan),
        (2020, "CERRADO", "MATO GROSSO", "BR-5107925", "SORRISO", "ADM", "ADM BRASIL", "CHINA", "ASIA", 50.0, 500.0, 10.0),
        (2020, "CERRADO", "MATO GROSSO", "BR-5107925", "SORRISO", "BUNGE", "BUNGE SA", "SPAIN", "EUROPEAN UNION", 30.0, 300.0, 6.0),
        (2020, "AMAZONIA", "PARA", "BR-1508159", "URUARA", "ADM", "ADM BRASIL", "CHINA", "ASIA", 20.0, 200.0, 8.0),
        (2020, "UNKNOWN", "UNKNOWN STATE", "BR-XXXXXXX", "UNKNOWN", "ADM", "ADM BRASIL", "CHINA", "ASIA", 40.0, 0.0, np.nan),
        (2020, "CERRADO", "MATO GROSSO", "BR-5107925", "SORRISO", "PROCESSED DOMESTICALLY", "X", "BRAZIL", "BRAZIL", 10.0, 0.0, 2.0),
        (2022, "CERRADO", "MATO GROSSO", "BR-5107925", "SORRISO", "ADM", "ADM BRASIL", "CHINA", "ASIA", 60.0, 600.0, 12.0),
        (2022, "AMAZONIA", "PARA", "BR-1508159", "URUARA", "UNKNOWN", "UNKNOWN CUSTOMER", "CHINA", "ASIA", 25.0, 250.0, 9.0),
    ]
    df = pd.DataFrame(rows, columns=["year", "biome", "state", "municipality_of_production_trase_id", "municipality_of_production",
                                      "exporter_group", "exporter", "country_of_first_import", "economic_bloc", "volume", "fob",
                                      soy_flows.EXPO])
    for c in soy_flows.RAW_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df["forest_500_soy"] = ["NOT ASSESSED"] * len(df)
    df[soy_flows.CO2N] = df[soy_flows.EXPO] * 3
    df[soy_flows.CO2G] = df[soy_flows.EXPO] * 4
    df["land_use"] = df.volume * 2
    df["port_of_export"] = [None] * len(df)
    return df.assign(_source_file="x.parquet", _source_sha256="abc", _source_version="v", _ingested_at="t")


@pytest.fixture
def silver():
    s, _ = soy_flows.to_silver(bronze_df())
    return s


# ------------------------------------------------------------------ chaves e nomes
def test_municipality_id_unica_e_nula_para_origem_desconhecida(silver):
    assert municipality_id_from_trase("BR-2100600") == "2100600"
    assert municipality_id_from_trase("BR-XXXXXXX") is None
    assert silver.municipality_id.isna().tolist() == silver.unknown_origin.tolist()


def test_normalize_name():
    assert normalize_name("São José do Rio Claro") == "SAO JOSE DO RIO CLARO"
    assert normalize_name("  Aceguá ") == "ACEGUA"


# ------------------------------------------------------------------ silver
def test_silver_marca_sem_apagar(silver):
    assert len(silver) == 8
    assert silver.is_analytic.tolist() == [False, True, True, True, False, False, True, True]
    assert silver.domestic_destination.sum() == 1 and silver.unknown_exporter.sum() == 1
    assert (silver.port_of_export == "NOT REPORTED").all()


def test_portao_bloqueia_dado_ruim(tmp_path):
    b = bronze_df()
    s, log = soy_flows.to_silver(b)
    s.loc[0, "volume"] = -1
    with pytest.raises(QualityGateError):
        enforce("silver_soy", soy_flows.silver_checks(b, s, log), tmp_path)
    assert (tmp_path / "quality_silver_soy.json").exists()


def test_portao_nao_bloqueia_por_aviso(tmp_path):
    enforce("x", [Check("aviso", "warn", False)], tmp_path)


# ------------------------------------------------------------------ gold e catálogo
def test_gold_cumpre_contrato_e_fecha_com_a_silver(silver, tmp_path):
    gold, info = soy_flows.to_gold(silver)
    checks = soy_flows.gold_checks(silver, gold, info)
    assert [c for c in checks if c.level == "blocks" and not c.passed] == []
    enforce("gold_soy", checks, tmp_path)


def test_gold_nao_soma_anos_nem_tem_coluna_de_exposicao_somada(silver):
    gold, _ = soy_flows.to_gold(silver)
    for name in ["soy_municipality_year", "soy_exporter_group_year", "soy_exporter_company_year", "soy_destination_year",
                 "soy_destination_state_year", "soy_biome_year", "soy_national_year"]:
        assert gold[name].year.notna().all()
    assert "exposto" not in catalog.GOLD["soy_inpe_crosswalk"].col_names
    n = gold["soy_national_year"].set_index("year")
    assert n.loc[2020, "volume_total_tonnes"] == 150.0 and n.loc[2020, "volume_analytic_tonnes"] == 100.0
    assert n.loc[2012, "has_environmental_data"] == False  # noqa: E712


def test_gold_idempotente(silver):
    a, _ = soy_flows.to_gold(silver)
    b, _ = soy_flows.to_gold(silver)
    for k in a:
        pd.testing.assert_frame_equal(a[k], b[k])


def test_contrato_detecta_coluna_faltando_extra_e_tipo_errado(silver):
    gold, _ = soy_flows.to_gold(silver)
    df = gold["soy_biome_year"]
    assert catalog.check_contract("soy_biome_year", df)[0]
    assert not catalog.check_contract("soy_biome_year", df.drop(columns=["exposure_ha"]))[0]
    assert not catalog.check_contract("soy_biome_year", df.assign(extra=1))[0]
    assert not catalog.check_contract("soy_biome_year", df.assign(year=df.year.astype(str)))[0]


def test_catalogo_e_a_fonte_unica_do_dicionario():
    assert set(catalog.catalog_frame().table_name) == set(catalog.GOLD)
    assert "soy_exporter_group_year" in catalog.render_markdown()


# ------------------------------------------------------------------ banco do agente e ferramentas (modo gold)
@pytest.fixture
def gold_db(silver, tmp_path, monkeypatch):
    lake = Lake(tmp_path / "lake")
    gold, _ = soy_flows.to_gold(silver)
    lake.gold.mkdir(parents=True)
    for k, v in gold.items():
        v.to_parquet(lake.gold / f"{k}.parquet", index=False)
    aux = tmp_path / "soy.duckdb"                      # banco do ingest-soy: tem a cadeia BRUTA e uma tabela de apoio
    con = duckdb.connect(str(aux))
    con.execute("CREATE TABLE soy_supply_chain AS SELECT 1 AS x")
    con.execute("CREATE TABLE soy_facilities AS SELECT 'A' AS company")
    con.close()
    run = {"run_id": "20260101T000000Z-abc1234", "built_at": "2026-01-01T00:00:00+00:00", "git_commit": "abc1234", "git_dirty": False,
           "source_name": "teste", "source_sha256": "sha", "rows_bronze": 8, "rows_silver": 8, "rows_analytic": 4, "quality_checks": 1,
           "quality_warnings_failed": 0, "inpe_sources": "{}", "gold_tables": "{}"}
    target = tmp_path / "soy_gold.duckdb"
    info = agent_db.build(lake, registry.run_frame(run), target, aux)
    monkeypatch.setattr(config, "SOY_GOLD_DUCKDB_PATH", target)
    monkeypatch.setattr(config, "SOY_USE_GOLD", True)
    return info


def test_banco_do_agente_nao_tem_a_cadeia_bruta_mas_tem_as_tabelas_de_apoio(gold_db):
    assert "soy_supply_chain" not in gold_db["tables"]
    assert "soy_facilities" in gold_db["tables"] and "gold_catalog" in gold_db["tables"] and "meta_runs" in gold_db["tables"]


def test_sql_livre_do_agente_nao_alcanca_a_tabela_bruta(gold_db):
    con = soy_queries.connect_readonly()
    try:
        with pytest.raises(Exception):
            con.execute("SELECT * FROM soy_supply_chain").fetchall()
        assert con.execute("SELECT count(*) FROM soy_biome_year").fetchone()[0] > 0
    finally:
        con.close()


def test_ferramentas_leem_a_gold(gold_db):
    assert soy_queries.using_gold() and soy_queries.is_available() and soy_queries.latest_year() == 2022
    ex = soy_queries.top_exporters(5, year=2020)
    assert list(ex.exporter)[0] in ("ADM BRASIL", "BUNGE SA") and "exporter_group" in ex.columns
    grp = soy_queries.top_exporters(5, year=2020, level="group")
    assert set(grp.exporter) == {"ADM", "BUNGE"}
    assert not any("PROCESSED DOMESTICALLY" in str(v) for v in grp.exporter)      # doméstico fica fora da base analítica
    assert soy_queries.top_destinations(5, year=2020, state="MATO GROSSO").destination.tolist()[0] == "CHINA"
    assert soy_queries.top_municipalities(5, year=2020, biome="amazonia").municipality.tolist() == ["URUARA"]
    assert soy_queries.deforestation_by_biome(2020).biome.tolist()[0] == "CERRADO"
    assert len(soy_queries.yearly_trend()) == 3


def test_prompt_vem_do_catalogo_e_traz_a_origem_dos_dados(gold_db):
    p = soy_queries.schema_prompt()
    assert "soy_municipality_year" in p and "Origem dos dados: teste; carga 20260101T000000Z-abc1234" in p
    assert "soy_facilities" in p and "janela" in p.lower()


def test_proveniencia_registrada(gold_db):
    p = registry.provenance()
    assert p["run_id"].endswith("abc1234") and p["source_sha256"] == "sha"


def test_modo_gold_desligado_nao_muda_o_comportamento(monkeypatch):
    monkeypatch.setattr(config, "SOY_USE_GOLD", False)
    assert soy_queries.using_gold() is False


# ------------------------------------------------------------------ INPE
def amz():
    return pd.DataFrame({"FID": ["a.1", "a.1"], "classname": ["DESMATAMENTO_CR"] * 2, "view_date": ["2021-08-01", "2023-09-01"],
                         "areamunkm": ["0.5", "0.2"], "municipality": ["Juara", "Sorriso"], "mun_geocod": ["5105507", "5107925"],
                         "uf": ["MT", "MT"], "_file_year": [2021, 2023]})


def cer():
    return pd.DataFrame({"FID": ["c.1", "c.2"], "classname": ["DESMATAMENTO_CR"] * 2, "view_date": ["2022-01-02"] * 2,
                         "areamunkm": ["1.0", "0.0"], "municipality": ["SORRISO", "CIDADE SEM SOJA"], "uf": ["MT", "GO"], "_file_year": [2022] * 2})


def test_inpe_fid_repetido_nao_e_duplicata_e_municipio_casa_por_nome_uf(silver):
    key = inpe.municipality_key(silver)
    s, log = inpe.to_silver_deter(amz(), cer(), key)
    assert log["exact_duplicates"] == 0 and (s.alert_id == "a.1").sum() == 2
    c = s[s.source == "DETER Cerrado"]
    assert c[c.municipality_name == "SORRISO"].municipality_id.eq("5107925").all()
    fora = c[c.municipality_name == "CIDADE SEM SOJA"].iloc[0]
    assert (not fora.municipality_matched) and fora.area_ha == 0        # mantido e marcado, não apagado


def test_inpe_gold_cruzamento_sem_exposicao_somada(silver):
    key = inpe.municipality_key(silver)
    s, _ = inpe.to_silver_deter(amz(), cer(), key)
    pam = inpe.to_silver_pampa(pd.DataFrame({"ibge": ["5107925"], "nome": ["Sorriso"], "prodes_ha_2021": ["10"], "prodes_ha_2022": ["20"],
                                             "prodes_ha_2023": ["30"], "prodes_ha_2024": ["40"], "prodes_ha_total": ["100"]}))
    g = inpe.to_gold(silver, s, pam)
    assert all(catalog.check_contract(n, df)[0] for n, df in g.items())
    assert [c for c in inpe.gold_checks(silver, s, pam, g) if c.level == "blocks" and not c.passed] == []
    assert "exposto" not in g["soy_inpe_crosswalk"].columns


def test_inpe_pampa_longo_e_total_fecha():
    sp = inpe.to_silver_pampa(pd.DataFrame({"ibge": ["4300034"], "nome": ["A"], "prodes_ha_2021": ["10"], "prodes_ha_2022": ["20"],
                                            "prodes_ha_2023": ["30"], "prodes_ha_2024": ["40"], "prodes_ha_total": ["100"]}))
    assert len(sp) == 4 and sp.prodes_ha.sum() == 100

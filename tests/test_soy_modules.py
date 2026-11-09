import json
from pathlib import Path

import pandas as pd
import pytest

from src.soy.catalog import load_manifest
from src.soy.ingest import ingest_soy_datasets, profile_file
from src.soy.routing import route_question


@pytest.fixture
def synthetic_manifest(tmp_path):
    csv_path = tmp_path / "soy_supply_chain.csv"
    parquet_path = tmp_path / "soy_deforestation.parquet"
    pd.DataFrame(
        {
            "year": [2021, 2022],
            "biome": ["AMAZONIA", "CERRADO"],
            "municipality_of_production": ["A", "B"],
            "state": ["SP", "MG"],
            "exporter": ["Alpha", "Beta"],
            "country_of_destination": ["EU", "CHINA"],
            "volume": [1000.0, 2000.0],
            "soy_deforestation_5_year_total_exposure": [5.0, 7.0],
        }
    ).to_csv(csv_path, index=False)

    pd.DataFrame(
        {
            "year": [2021, 2022],
            "country": ["BRAZIL", "BRAZIL"],
            "region": ["A", "B"],
            "soy_deforestation_hectares": [1.5, 2.5],
        }
    ).to_parquet(parquet_path, index=False)

    manifest = [
        {
            "dataset_name": "soy_supply_chain",
            "source_file": "soy_supply_chain.csv",
            "table_name": "soy_supply_chain",
            "commodity": "soy",
            "country": "Brazil",
            "dataset_type": "supply_chain",
            "version": "2.6",
            "period": {"start": 2004, "end": 2022},
            "url": "https://example.com/soy",
            "columns": [
                "year",
                "biome",
                "municipality_of_production",
                "state",
                "exporter",
                "country_of_destination",
                "volume",
                "soy_deforestation_5_year_total_exposure",
            ],
            "description": "Supply chain",
            "unit": "tonnes",
            "granularity": "municipality",
            "available_files": [str(csv_path)],
        },
        {
            "dataset_name": "soy_deforestation",
            "source_file": "soy_deforestation.parquet",
            "table_name": "soy_deforestation",
            "commodity": "soy",
            "country": "Brazil",
            "dataset_type": "environmental",
            "version": "2.6",
            "period": {"start": 2014, "end": 2024},
            "url": "https://example.com/soy-deforestation",
            "columns": [
                "year",
                "country",
                "region",
                "soy_deforestation_hectares",
            ],
            "description": "Soy deforestation",
            "unit": "hectares",
            "granularity": "municipality",
            "available_files": [str(parquet_path)],
        },
    ]
    return manifest, tmp_path


def test_manifest_present_and_loadable():
    manifest = load_manifest()
    assert manifest
    assert any(item.get("commodity") == "soy" for item in manifest)


def test_ingest_soy_dataset_supports_csv_and_parquet(synthetic_manifest):
    manifest, tmp_path = synthetic_manifest
    summary = ingest_soy_datasets(manifest=manifest, data_root=tmp_path, duckdb_path=tmp_path / "soy.duckdb")
    assert summary["ingested"] >= 2
    assert summary["missing"] == []
    assert (tmp_path / "soy.duckdb").exists()


def test_profile_file_reports_schema_and_sample(tmp_path):
    csv_path = tmp_path / "profile.csv"
    pd.DataFrame({"year": [2021], "volume": [150.5], "exporter": ["Acme"]}).to_csv(csv_path, index=False)
    profile = profile_file(csv_path)
    assert profile["row_count"] == 1
    assert "year" in profile["columns"]
    assert profile["sample"]["exporter"].tolist()[0] == "Acme"


def test_question_routing_uses_soy_domain():
    route = route_question("Quais municípios apresentam maior exposição ao desmatamento da soja?")
    assert route["domain"] == "soy"
    assert route["retrieval"] in {"structured", "hybrid"}


def test_territorial_tables_built_from_spatial_and_facilities(tmp_path):
    import duckdb

    from src.soy.territorial import build_extra_tables

    raw = tmp_path / "raw"
    raw.mkdir()
    base = "year,country,country_iso2,region,region_trase_id,parent_region,parent_region_trase_id"
    (raw / "spatial-metrics-brazil-soy-soy_tn_state.csv").write_text(
        f"{base},soy_production_tonnes\n2024,BRAZIL,BR,MATO GROSSO,BR-51,CENTRO-OESTE,BR-5,100\n"
        f"2024,BRAZIL,BR,PARANA,BR-41,SUL,BR-4,50\n", encoding="utf-8")
    # cópia "(1)" deve ser ignorada; "NaN" vira NULL
    (raw / "spatial-metrics-brazil-soy-soy_tn_state (1).csv").write_text(
        f"{base},soy_production_tonnes\n2024,BRAZIL,BR,MATO GROSSO,BR-51,CENTRO-OESTE,BR-5,100\n", encoding="utf-8")
    (raw / "spatial-metrics-brazil-soy-soy_yield_municipality.csv").write_text(
        f"{base},soy_yield_tonnes_per_hectare\n2024,BRAZIL,BR,SORRISO,BR-1,MATO GROSSO,BR-51,NaN\n", encoding="utf-8")
    (raw / "Brazil_soy_facilities_map_v1.csv").write_text(
        "facility_id,trase_id,cnpj,company_name,category,facility_type,cnae,cnae_name,start_activity_date,"
        "state_name,municipality,municipality_ibge_code,latitude,longitude,storage_capacity_tn,"
        "processing_capacity_tonnes_day,full_address,source\n"
        "1,BR-1,0,ACME (3),PROCESSING,HUB,,,NONE,MATO GROSSO,SORRISO,1,-12,-55,1000,50,X,SICARM\n",
        encoding="utf-8")

    con = duckdb.connect()
    summary = build_extra_tables(con, tmp_path)
    assert summary["spatial_metrics"] == {"files": 2, "rows": 3, "warnings": []}
    assert summary["facilities"]["rows"] == 1
    assert con.execute("SELECT value FROM soy_spatial_metrics WHERE metric = 'soy_yield_t_per_ha'").fetchone()[0] is None
    assert con.execute("SELECT company, start_activity_date FROM soy_facilities").fetchone() == ("ACME", None)

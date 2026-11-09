from __future__ import annotations

import json
from pathlib import Path

from src.config import PROJECT_ROOT

DATA_ROOT = PROJECT_ROOT / "data"
CATALOG_DIR = DATA_ROOT / "catalog"
SOY_MANIFEST_PATH = CATALOG_DIR / "soy_manifest.json"

DEFAULT_SOY_MANIFEST = [
    {
        "dataset_name": "soy_supply_chain",
        "source_file": "brazil_soy_v2_6_1_composite.csv",
        "table_name": "soy_supply_chain",
        "commodity": "soy",
        "country": "Brazil",
        "dataset_type": "supply_chain",
        "version": "2.6",
        "period": {"start": 2004, "end": 2022},
        "url": "https://trase.earth/open-data/search/soy?country=BRAZIL",
        "data_obtained_at": "2025-01-01",
        "columns": [
            "year",
            "biome",
            "country_of_production",
            "state",
            "municipality_of_production",
            "logistics_hub",
            "port_of_export",
            "exporter",
            "importer",
            "country_of_first_import",
            "soy_deforestation_5_year_total_exposure",
            "co2_net_emissions_soy_deforestation_5_year_total_exposure",
            "co2_gross_emissions_soy_deforestation_5_year_total_exposure",
            "volume",
            "fob",
            "land_use",
        ],
        "description": "Brazil soy supply chain data for 2004–2022.",
        "unit": "tonnes",
        "granularity": "municipality + exporter + importer + year",
        "observations": "The dataset is the central source for the Brazilian soy supply chain.",
    },
    {
        "dataset_name": "soy_deforestation",
        "source_file": "spatial-metrics-brazil-soy-soy_deforestation_5_year_total_municipality.csv",
        "table_name": "soy_deforestation",
        "commodity": "soy",
        "country": "Brazil",
        "dataset_type": "deforestation",
        "version": "2.6",
        "period": {"start": 2014, "end": 2024},
        "url": "https://trase.earth/open-data/search/soy?country=BRAZIL",
        "data_obtained_at": "2025-01-01",
        "columns": [
            "year",
            "country",
            "region",
            "parent_region",
            "soy_deforestation_hectares",
        ],
        "description": "Municipal deforestation exposure associated with soy supply chains.",
        "unit": "hectares",
        "granularity": "municipality and year",
        "observations": "This indicator should not be treated as direct illegal deforestation by a firm.",
    },
    {
        "dataset_name": "soy_gross_emissions",
        "source_file": "spatial-metrics-brazil-soy-co2_gross_emissions_soy_deforestation_5_year_total_municipality.csv",
        "table_name": "soy_gross_emissions",
        "commodity": "soy",
        "country": "Brazil",
        "dataset_type": "emissions",
        "version": "2.6",
        "period": {"start": 2014, "end": 2024},
        "url": "https://trase.earth/open-data/search/soy?country=BRAZIL",
        "data_obtained_at": "2025-01-01",
        "columns": [
            "year",
            "country",
            "region",
            "parent_region",
            "gross_emissions_from_soy_deforestation_tonnes_co₂-equivalent",
        ],
        "description": "Gross emissions from soy deforestation exposure.",
        "unit": "tonnes CO2e",
        "granularity": "municipality and year",
        "observations": "Gross emissions are not the same as net emissions.",
    },
]


def ensure_manifest(path: Path | str | None = None) -> Path:
    manifest_path = Path(path) if path is not None else SOY_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(DEFAULT_SOY_MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def load_manifest(path: Path | str | None = None) -> list[dict]:
    manifest_path = ensure_manifest(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Manifesto inválido em {manifest_path}: esperado uma lista de datasets.")
    return payload

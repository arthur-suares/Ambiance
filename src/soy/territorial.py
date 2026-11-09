"""Tabelas da soja além do manifesto: métricas territoriais e mapa de instalações.

Chamado ao fim de ingest_soy_datasets (python -m src.cli ingest-soy). Lê os CSV/Parquet
de data/ e data/raw/ e (re)cria no banco da soja:

- soy_spatial_metrics: todos os arquivos spatial-metrics-brazil-soy-<métrica>_<nível>.*
  numa tabela longa (metric, level, year, region, parent_region, value, unit), igual à
  spatial_metrics da carne bovina. Arquivo novo com esse padrão entra sozinho.
- soy_metric_catalog: unidade e descrição de cada métrica.
- soy_facilities: armazéns e processadoras de soja (Brazil_soy_facilities_map_*).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.config import PROJECT_ROOT

SPATIAL_PREFIX = "spatial-metrics-brazil-soy-"
LEVELS = ("country", "biome", "state", "municipality")
SPATIAL_BASE_COLUMNS = {
    "year", "country", "country_iso2", "region", "region_trase_id",
    "parent_region", "parent_region_trase_id",
}
FACILITIES_PATTERN = "*soy_facilities_map*"

# slug do arquivo -> (nome da métrica, unidade, descrição, somável entre regiões?)
SOY_METRICS = {
    "soy_area": ("soy_area_ha", "ha", "Área plantada de soja.", True),
    "soy_tn": ("soy_production_t", "t", "Produção de soja.", True),
    "soy_yield": ("soy_yield_t_per_ha", "t/ha", "Produtividade da soja.", False),
    "soy_deforestation_5_year_total": (
        "soy_deforestation_5y_ha", "ha",
        "Desmatamento associado à soja na janela de 5 anos (não somar entre anos).", True),
    "co2_gross_emissions_soy_deforestation_5_year_total": (
        "soy_deforestation_gross_emissions_5y_tco2e", "tCO2e",
        "Emissões brutas do desmatamento associado à soja, janela de 5 anos (não somar entre anos).", True),
    "rtrs_tn": ("rtrs_certified_t", "t", "Soja certificada pela Round Table on Responsible Soy (RTRS).", True),
    "zdc_traded_brazil_soy_perc": (
        "zdc_exported_pct", "%",
        "Percentual da soja exportada por empresas com compromisso de desmatamento zero (ZDC).", False),
}


def _lit(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _reader(path: Path) -> str:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return f"read_parquet({_lit(path)})"
    return f"read_csv_auto({_lit(path)}, header = true, all_varchar = true, sample_size = -1)"


def _search_dirs(data_root: Path | str | None) -> list[Path]:
    root = Path(data_root) if data_root is not None else PROJECT_ROOT / "data"
    return [d for d in (root, root / "raw", root / "processed", root / "processed" / "soy") if d.is_dir()]


def _find(data_root, pattern: str) -> list[Path]:
    """Arquivos .csv/.parquet que casam com o padrão, sem cópias "arquivo (1).csv"."""
    found: dict[str, Path] = {}
    for d in _search_dirs(data_root):
        for f in sorted(d.glob(pattern)):
            if f.suffix.lower() not in {".csv", ".parquet", ".pq"}:
                continue
            key = re.sub(r" \(\d+\)$", "", f.stem)
            # prefere o arquivo sem "(1)" e o Parquet ao CSV
            if key not in found or " (" in found[key].stem or f.suffix.lower() != ".csv":
                found[key] = f
    return sorted(found.values())


def build_spatial_metrics(conn, data_root=None) -> dict:
    files = _find(data_root, f"{SPATIAL_PREFIX}*")
    warnings, parts, used = [], [], []
    for f in files:
        stem = re.sub(r" \(\d+\)$", "", f.stem).removeprefix(SPATIAL_PREFIX)
        slug, _, level = stem.rpartition("_")
        if level not in LEVELS:
            warnings.append(f"{f.name}: nível '{level}' desconhecido, ignorado.")
            continue
        if slug not in SOY_METRICS:
            warnings.append(f"{f.name}: métrica '{slug}' fora do catálogo (unidade desconhecida).")
        metric, unit = SOY_METRICS.get(slug, (slug, "?", "", False))[:2]
        cols = [r[0] for r in conn.execute(f"DESCRIBE SELECT * FROM {_reader(f)}").fetchall()]
        value_cols = [c for c in cols if c not in SPATIAL_BASE_COLUMNS]
        if len(value_cols) != 1 or not SPATIAL_BASE_COLUMNS - {"country_iso2"} <= set(cols):
            warnings.append(f"{f.name}: formato inesperado ({cols}); ignorado.")
            continue
        value = f'TRY_CAST("{value_cols[0]}" AS DOUBLE)'
        parts.append(
            f"""SELECT {_lit(metric)} AS metric, {_lit(level)} AS level, TRY_CAST(year AS INTEGER) AS year,
                       region, region_trase_id, parent_region, parent_region_trase_id,
                       CASE WHEN isnan({value}) THEN NULL ELSE {value} END AS value, {_lit(unit)} AS unit
                FROM {_reader(f)}"""
        )
        used.append(f.name)

    if not parts:
        return {"files": 0, "rows": 0, "warnings": warnings}

    conn.execute("CREATE OR REPLACE TABLE soy_spatial_metrics AS " + "\nUNION ALL\n".join(parts))
    conn.execute("CREATE OR REPLACE TABLE soy_metric_catalog "
                 "(metric VARCHAR, unit VARCHAR, description VARCHAR, additive BOOLEAN, source_slug VARCHAR)")
    conn.executemany("INSERT INTO soy_metric_catalog VALUES (?, ?, ?, ?, ?)",
                     [(m, u, d, a, slug) for slug, (m, u, d, a) in SOY_METRICS.items()])
    rows = conn.execute("SELECT COUNT(*) FROM soy_spatial_metrics").fetchone()[0]
    return {"files": len(used), "rows": int(rows), "warnings": warnings}


def build_facilities(conn, data_root=None) -> dict:
    files = _find(data_root, FACILITIES_PATTERN)
    if not files:
        return {"files": 0, "rows": 0}
    path = files[-1]  # o mais recente em ordem alfabética, se houver mais de uma versão
    # Carrega como texto antes de converter: com TRY_CAST direto sobre o read_csv, o DuckDB
    # empurra o tipo para o leitor do CSV e falha em valores como "NONE" na data.
    conn.execute(f"CREATE OR REPLACE TEMP TABLE _soy_facilities_raw AS SELECT * FROM {_reader(path)}")
    conn.execute("""
        CREATE OR REPLACE TABLE soy_facilities AS
        SELECT facility_id, trase_id, cnpj, company_name,
               -- a fonte numera cada instalação no nome ("BUNGE ALIMENTOS S/A (78)"); company tira o número
               trim(regexp_replace(company_name, '\\s*\\(\\d+\\)\\s*$', '')) AS company,
               category,                                   -- STORAGE / PROCESSING
               facility_type,                              -- LOCAL_SILO / AGGREGATOR / HUB
               cnae, cnae_name,
               TRY_CAST(start_activity_date AS DATE) AS start_activity_date,
               state_name AS state, municipality,
               TRY_CAST(municipality_ibge_code AS BIGINT) AS municipality_ibge_code,
               TRY_CAST(latitude AS DOUBLE) AS latitude, TRY_CAST(longitude AS DOUBLE) AS longitude,
               TRY_CAST(storage_capacity_tn AS DOUBLE) AS storage_capacity_t,
               TRY_CAST(processing_capacity_tonnes_day AS DOUBLE) AS processing_capacity_t_day,
               full_address, source
        FROM _soy_facilities_raw
    """)
    conn.execute("DROP TABLE _soy_facilities_raw")
    rows = conn.execute("SELECT COUNT(*) FROM soy_facilities").fetchone()[0]
    return {"files": 1, "file": path.name, "rows": int(rows)}


def build_extra_tables(conn, data_root=None) -> dict:
    return {
        "spatial_metrics": build_spatial_metrics(conn, data_root),
        "facilities": build_facilities(conn, data_root),
    }

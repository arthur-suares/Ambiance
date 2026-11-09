"""Banco analítico: Parquet do Trase -> tabelas e views no DuckDB.

- build_database(): lê os Parquet de PARQUET_DIR e (re)cria o arquivo DuckDB com
  as tabelas supply_chain, spatial_metrics, metric_catalog, facilities e
  entity_index e as views de agregação. Roda sozinho quando algum Parquet é mais
  novo que o banco.
- get_connection(): conexão somente leitura, para as consultas prontas.
- run_readonly_sql(): executa SQL arbitrário (do LLM) numa conexão sem acesso a
  arquivos, com limite de linhas e de tempo.

Os dados são copiados para tabelas (em vez de views sobre os Parquet) para que a
conexão do LLM possa desligar o acesso a arquivos: assim um SQL gerado não lê
nem grava nada fora do banco.
"""

import re
import threading
from pathlib import Path

import duckdb
import pandas as pd

from src.config import (
    DUCKDB_PATH, FACILITIES_GLOB, PARQUET_DIR, SPATIAL_METRICS_GLOB,
    SQL_MAX_ROWS, SQL_TIMEOUT_SECONDS, SUPPLY_CHAIN_FILE,
)
from src.data_dictionary import DOMESTIC_DESTINATION, DOMESTIC_EXPORTER, LEVELS, METRICS

SPATIAL_PREFIX = "spatial-metrics-brazil-beef-"
SPATIAL_BASE_COLUMNS = {
    "year", "country", "country_iso2", "region", "region_trase_id",
    "parent_region", "parent_region_trase_id",
}
NUMERIC_SUPPLY_COLUMNS = [
    "cattle_deforestation_5_year_total_exposure",
    "co2_net_emissions_cattle_deforestation_5_year_total_exposure",
    "co2_gross_emissions_cattle_deforestation_5_year_total_exposure",
    "land_use", "fob", "volume",
]
REQUIRED_SUPPLY_COLUMNS = {
    "year", "biome", "state_of_production", "municipality_of_production",
    "municipality_of_production_trase_id", "exporter", "exporter_group",
    "country_of_destination", "zero_deforestation_brazil_beef",
    "economic_bloc", "importer", "importer_group", "port_of_export", "logistics_hub",
    *NUMERIC_SUPPLY_COLUMNS,
}


def _lit(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _norm(expr: str) -> str:
    return f"upper(strip_accents(trim({expr})))"


# --- Arquivos de origem ---------------------------------------------------------

def source_files() -> dict[str, list[Path]]:
    supply = PARQUET_DIR / SUPPLY_CHAIN_FILE
    return {
        "supply_chain": [supply] if supply.exists() else [],
        "spatial": sorted(PARQUET_DIR.glob(SPATIAL_METRICS_GLOB)),
        "facilities": sorted(PARQUET_DIR.glob(FACILITIES_GLOB)),
    }


def needs_rebuild() -> bool:
    if not DUCKDB_PATH.exists():
        return True
    built = DUCKDB_PATH.stat().st_mtime
    return any(f.stat().st_mtime > built for files in source_files().values() for f in files)


# --- Construção -------------------------------------------------------------------

def _build_supply_chain(con, path: Path) -> None:
    cols = {r[0]: r[1] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({_lit(path)})").fetchall()}
    missing = REQUIRED_SUPPLY_COLUMNS - cols.keys()
    if missing:
        raise ValueError(f"{path.name}: colunas obrigatórias ausentes: {', '.join(sorted(missing))}")

    # Aceita tanto o Parquet já tipado quanto um com tudo em texto ('' = vazio).
    select = []
    for name, dtype in cols.items():
        q = f'"{name}"'
        text = dtype == "VARCHAR"
        if name == "year":
            select.append(f"CAST({q} AS INTEGER) AS year")
        elif name in NUMERIC_SUPPLY_COLUMNS:
            select.append(f"CAST(NULLIF(TRIM({q}), '') AS DOUBLE) AS {q}" if text else f"CAST({q} AS DOUBLE) AS {q}")
        else:
            select.append(f"NULLIF(TRIM({q}), '') AS {q}" if text else q)
    con.execute(f"CREATE TABLE supply_chain AS SELECT {', '.join(select)} FROM read_parquet({_lit(path)})")


def _build_spatial(con, files: list[Path]) -> list[str]:
    """Junta os arquivos de métricas espaciais numa tabela longa. Devolve avisos."""
    warnings, parts = [], []
    for f in files:
        stem = f.stem.removeprefix(SPATIAL_PREFIX)
        slug, _, level = stem.rpartition("_")
        if level not in LEVELS:
            warnings.append(f"{f.name}: nível '{level}' desconhecido, ignorado.")
            continue
        metric, unit = METRICS.get(slug, (slug, "?", "", False))[:2]
        if slug not in METRICS:
            warnings.append(f"{f.name}: métrica '{slug}' fora do dicionário (unidade desconhecida).")
        cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({_lit(f)})").fetchall()]
        value_cols = [c for c in cols if c not in SPATIAL_BASE_COLUMNS]
        if len(value_cols) != 1:
            warnings.append(f"{f.name}: esperava 1 coluna de valor, achei {value_cols}; ignorado.")
            continue
        parts.append(
            f"""SELECT {_lit(metric)} AS metric, {_lit(level)} AS level, CAST(year AS INTEGER) AS year,
                       region, region_trase_id, parent_region, parent_region_trase_id,
                       CAST("{value_cols[0]}" AS DOUBLE) AS value, {_lit(unit)} AS unit
                FROM read_parquet({_lit(f)})"""
        )
    if not parts:
        raise ValueError("Nenhum arquivo de métricas espaciais válido.")
    con.execute("CREATE TABLE spatial_metrics AS " + "\nUNION ALL\n".join(parts))

    con.execute("CREATE TABLE metric_catalog (metric VARCHAR, unit VARCHAR, description VARCHAR, additive BOOLEAN, source_slug VARCHAR)")
    con.executemany("INSERT INTO metric_catalog VALUES (?, ?, ?, ?, ?)",
                    [(m, u, d, a, slug) for slug, (m, u, d, a) in METRICS.items()])

    metrics = [r[0] for r in con.execute("SELECT DISTINCT metric FROM spatial_metrics ORDER BY 1").fetchall()]
    pivots = ",\n".join(f'MAX(value) FILTER (WHERE metric = {_lit(m)}) AS "{m}"' for m in metrics)
    con.execute(f"""
        CREATE VIEW spatial_metrics_wide AS
        SELECT level, year, region, region_trase_id, parent_region, parent_region_trase_id,
               {pivots}
        FROM spatial_metrics
        GROUP BY ALL
    """)
    return warnings


def _build_facilities(con, path: Path) -> None:
    con.execute(f"""
        CREATE TABLE facilities AS
        SELECT unique_id, facility_id, company, cnpj, commodity,
               type_english AS type, type_detailed_english AS type_detailed,
               type_portuguese AS type_pt, type_detailed_portuguese AS type_detailed_pt,
               inspection_level, inspection_num, status,
               state, municipality,
               {_norm('state')} AS state_norm, {_norm('municipality')} AS municipality_norm,
               lat, long,
               capacity_value_num AS capacity_value, capacity_units_english AS capacity_unit,
               approved_export_countries, source
        FROM read_parquet({_lit(path)})
    """)


def _build_flow_views(con) -> None:
    dom_exp, dom_dest = _lit(DOMESTIC_EXPORTER), _lit(DOMESTIC_DESTINATION)
    con.execute(f"""
        CREATE VIEW flows_by_municipality AS
        SELECT year, biome, state_of_production, municipality_of_production,
               municipality_of_production_trase_id AS municipality_trase_id,
               SUM(volume) AS volume_t,
               SUM(volume) FILTER (WHERE exporter <> {dom_exp}) AS volume_exported_t,
               SUM(fob) AS fob_usd,
               SUM(cattle_deforestation_5_year_total_exposure) AS deforestation_exposure_ha,
               SUM(co2_net_emissions_cattle_deforestation_5_year_total_exposure) AS co2_net_tco2e,
               SUM(co2_gross_emissions_cattle_deforestation_5_year_total_exposure) AS co2_gross_tco2e,
               SUM(land_use) AS land_use_ha
        FROM supply_chain
        WHERE municipality_of_production IS NOT NULL
        GROUP BY ALL
    """)
    con.execute("""
        CREATE VIEW flows_by_exporter AS
        SELECT year, exporter_group, exporter, zero_deforestation_brazil_beef,
               SUM(volume) AS volume_t, SUM(fob) AS fob_usd,
               SUM(cattle_deforestation_5_year_total_exposure) AS deforestation_exposure_ha,
               SUM(co2_net_emissions_cattle_deforestation_5_year_total_exposure) AS co2_net_tco2e,
               COUNT(DISTINCT municipality_of_production) AS source_municipalities,
               COUNT(DISTINCT country_of_destination) AS destination_countries
        FROM supply_chain
        WHERE exporter IS NOT NULL
        GROUP BY ALL
    """)
    con.execute("""
        CREATE VIEW flows_by_destination AS
        SELECT year, country_of_destination, economic_bloc,
               SUM(volume) AS volume_t, SUM(fob) AS fob_usd,
               SUM(cattle_deforestation_5_year_total_exposure) AS deforestation_exposure_ha,
               SUM(co2_net_emissions_cattle_deforestation_5_year_total_exposure) AS co2_net_tco2e
        FROM supply_chain
        WHERE country_of_destination IS NOT NULL
        GROUP BY ALL
    """)


def _build_entity_index(con, has_facilities: bool) -> None:
    sources = [
        ("municipality", "municipality_of_production", "state_of_production", "supply_chain"),
        ("municipality", "region", "parent_region", "spatial_metrics WHERE level = 'municipality'"),
        ("state", "state_of_production", "NULL", "supply_chain"),
        ("biome", "biome", "NULL", "supply_chain"),
        ("exporter", "exporter", "exporter_group", "supply_chain"),
        ("exporter_group", "exporter_group", "NULL", "supply_chain"),
        ("importer", "importer", "importer_group", "supply_chain"),
        ("importer_group", "importer_group", "NULL", "supply_chain"),
        ("country_of_destination", "country_of_destination", "economic_bloc", "supply_chain"),
        ("economic_bloc", "economic_bloc", "NULL", "supply_chain"),
        ("port_of_export", "port_of_export", "NULL", "supply_chain"),
        ("logistics_hub", "logistics_hub", "state_of_production", "supply_chain"),
    ]
    if has_facilities:
        sources.append(("company", "company", "state", "facilities"))
    parts = [
        f"SELECT DISTINCT {_lit(kind)} AS kind, {col} AS value, CAST({ctx} AS VARCHAR) AS context FROM {src}"
        for kind, col, ctx, src in sources
    ]
    con.execute(f"""
        CREATE TABLE entity_index AS
        SELECT DISTINCT kind, value, context, {_norm('value')} AS norm
        FROM ({' UNION ALL '.join(parts)})
        WHERE value IS NOT NULL
    """)


def build_database(verbose: bool = True) -> None:
    files = source_files()
    if not files["supply_chain"]:
        raise FileNotFoundError(
            f"Parquet da cadeia não encontrado: {PARQUET_DIR / SUPPLY_CHAIN_FILE}. "
            "Converta os CSVs com scripts/csv_to_parquet.py ou ajuste SUPPLY_CHAIN_FILE no .env."
        )
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DUCKDB_PATH.with_suffix(".building.duckdb")
    tmp.unlink(missing_ok=True)

    con = duckdb.connect(str(tmp))
    con.execute("SET enable_progress_bar = false") # Apenas desliga a barra de progresso no terminal
    warnings = []
    try:
        _build_supply_chain(con, files["supply_chain"][0])
        _build_flow_views(con)
        if files["spatial"]:
            warnings += _build_spatial(con, files["spatial"])
        else:
            warnings.append("Nenhum arquivo de métricas espaciais encontrado.")
        if files["facilities"]:
            _build_facilities(con, files["facilities"][-1])
        else:
            warnings.append("Mapa logístico (facilities) não encontrado.")
        _build_entity_index(con, bool(files["facilities"]))
        con.execute("CHECKPOINT")
        counts = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for (t,) in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall()
        }
    finally:
        con.close()
    tmp.replace(DUCKDB_PATH)

    if verbose:
        print(f"Banco gerado: {DUCKDB_PATH}")
        for t, n in counts.items():
            print(f"  {t}: {n:,} linhas")
        for w in warnings:
            print(f"  aviso: {w}")


def ensure_database() -> None:
    if needs_rebuild():
        build_database()


# --- Conexões ---------------------------------------------------------------------

def get_connection():
    """Conexão somente leitura e sem acesso a arquivos.

    Não reconstrói o banco: isso fica para a inicialização (ensure_database() na CLI e
    no servidor web) ou para `python -m src.cli build-db`, para uma reconstrução nunca
    acontecer no meio de uma pergunta nem trocar o arquivo com conexões abertas.

    Todas as consultas usam a mesma configuração: o DuckDB não abre o mesmo arquivo
    com configurações diferentes no mesmo processo.
    """
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(f"Banco DuckDB não encontrado: {DUCKDB_PATH}. Rode: python -m src.cli build-db")
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True, config={"enable_external_access": False})
    con.execute("SET enable_progress_bar = false")
    con.execute("SET lock_configuration = true")
    return con


_sandbox_connection = get_connection


class SqlError(Exception):
    pass


ALLOWED_STATEMENTS = {duckdb.StatementType.SELECT}


def run_readonly_sql(sql: str, max_rows: int = SQL_MAX_ROWS,
                     timeout: float = SQL_TIMEOUT_SECONDS, connect=None) -> tuple[pd.DataFrame, bool]:
    """Executa uma única consulta SELECT. Devolve (resultado, truncado?).

    `connect` abre a conexão (padrão: banco da carne bovina). O banco da soja passa
    src.soy.queries.connect_readonly, com a mesma configuração de sandbox.
    """
    con = (connect or _sandbox_connection)()
    try:
        try:
            statements = con.extract_statements(sql)
        except duckdb.Error as e:
            raise SqlError(f"SQL inválido: {e}") from e
        if len(statements) != 1:
            raise SqlError("Envie exatamente uma consulta.")
        if statements[0].type not in ALLOWED_STATEMENTS:
            raise SqlError(f"Só consultas SELECT são permitidas (recebi {statements[0].type.name}).")

        query = re.sub(r";\s*$", "", statements[0].query.strip())
        timer = threading.Timer(timeout, con.interrupt)
        timer.start()
        try:
            # Quebras de linha: um comentário "--" no fim da consulta não engole o ")" e o LIMIT.
            df = con.execute(f"SELECT * FROM (\n{query}\n) LIMIT {max_rows + 1}").df()
        except duckdb.InterruptException as e:
            raise SqlError(f"Consulta passou de {timeout:.0f}s e foi interrompida.") from e
        except duckdb.Error as e:
            raise SqlError(f"{type(e).__name__}: {e}") from e
        finally:
            timer.cancel()
        truncated = len(df) > max_rows
        return df.head(max_rows), truncated
    finally:
        con.close()


# --- Perfil -----------------------------------------------------------------------

def get_profile() -> dict:
    con = get_connection()
    try:
        objects = con.execute("""
            SELECT table_name, 'tabela' FROM duckdb_tables()
            UNION ALL SELECT view_name, 'view' FROM duckdb_views() WHERE NOT internal
            ORDER BY 1
        """).fetchall()
        info = []
        for name, kind in objects:
            n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            cols = con.execute(f"DESCRIBE {name}").fetchall()
            info.append({"name": name, "kind": kind, "rows": n, "columns": [(c[0], c[1]) for c in cols]})
        years = con.execute("SELECT MIN(year), MAX(year) FROM supply_chain").fetchone()
        return {"objects": info, "supply_chain_years": years}
    finally:
        con.close()

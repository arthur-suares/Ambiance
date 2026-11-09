from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src.soy.ingest import DEFAULT_DUCKDB_PATH


def _table_exists(con, table_name: str) -> bool:
    row = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
        [table_name],
    ).fetchone()
    return row is not None


def _column_names(con, table_name: str) -> set[str]:
    if not _table_exists(con, table_name):
        return set()
    rows = con.execute(f"DESCRIBE {table_name}").fetchall()
    return {str(r[0]) for r in rows}


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(columns=columns)
    return df


def _attach_metadata(df: pd.DataFrame, *, source: str, unit: str, period: str, filters: dict | None = None) -> pd.DataFrame:
    df.attrs["source"] = source
    df.attrs["unit"] = unit
    df.attrs["period"] = period
    df.attrs["filters"] = filters or {}
    return df


def _connect(db_path: str | Path | None = None):
    target = Path(db_path) if db_path is not None else DEFAULT_DUCKDB_PATH
    if not target.exists():
        raise FileNotFoundError(f"Banco DuckDB da soja não encontrado: {target}")
    return duckdb.connect(str(target))


def _choose_supply_table(con) -> str | None:
    for candidate in ["soy_supply_chain", "soy_supply_chain_data", "brazil_soy_v2_6_1_composite"]:
        if _table_exists(con, candidate):
            return candidate
    return None


def _pick_columns(con, table_name: str, candidates: list[str]) -> str | None:
    cols = _column_names(con, table_name)
    for name in candidates:
        if name in cols:
            return name
    return None


def top_municipalities(limit: int = 10, year: int | None = None, state: str | None = None, biome: str | None = None) -> pd.DataFrame:
    conn = None
    try:
        conn = _connect()
        table = _choose_supply_table(conn)
        if table is None:
            return _attach_metadata(_empty_frame(["municipality", "state", "biome", "volume_tonnes", "exposure_ha"]), source="soy_supply_chain", unit="tonnes / hectares", period="2004-2022", filters={"year": year, "state": state, "biome": biome})
        cols = _column_names(conn, table)
        if "municipality_of_production" not in cols:
            return _attach_metadata(_empty_frame(["municipality", "state", "biome", "volume_tonnes", "exposure_ha"]), source=table, unit="tonnes / hectares", period="2004-2022", filters={"year": year, "state": state, "biome": biome})
        where = ["municipality_of_production IS NOT NULL"]
        params = []
        if year is not None:
            where.append("TRY_CAST(year AS INTEGER) = ?")
            params.append(year)
        if state is not None:
            where.append("LOWER(state) = LOWER(?)")
            params.append(state)
        if biome is not None:
            where.append("LOWER(biome) = LOWER(?)")
            params.append(biome)
        params.append(int(limit))
        exposure_col = "soy_deforestation_5_year_total_exposure" if "soy_deforestation_5_year_total_exposure" in cols else "soy_deforestation_hectares"
        sql = f"""
            SELECT municipality_of_production AS municipality,
                   COALESCE(state, '') AS state,
                   COALESCE(biome, '') AS biome,
                   SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes,
                   SUM(TRY_CAST({exposure_col} AS DOUBLE)) AS exposure_ha
            FROM {table}
            WHERE {' AND '.join(where)}
            GROUP BY municipality_of_production, state, biome
            ORDER BY exposure_ha DESC NULLS LAST
            LIMIT ?
        """
        df = conn.execute(sql, params).fetchdf()
        return _attach_metadata(df, source=table, unit="tonnes / hectares", period="2004-2022", filters={"year": year, "state": state, "biome": biome})
    finally:
        if conn is not None:
            conn.close()


def top_exporters(limit: int = 10, year: int | None = None) -> pd.DataFrame:
    conn = None
    try:
        conn = _connect()
        table = _choose_supply_table(conn)
        if table is None:
            return _attach_metadata(_empty_frame(["exporter", "volume_tonnes", "exposure_ha"]), source="soy_supply_chain", unit="tonnes / hectares", period="2004-2022", filters={"year": year})
        cols = _column_names(conn, table)
        if "exporter" not in cols:
            return _attach_metadata(_empty_frame(["exporter", "volume_tonnes", "exposure_ha"]), source=table, unit="tonnes / hectares", period="2004-2022", filters={"year": year})
        where = ["exporter IS NOT NULL"]
        params = []
        if year is not None:
            where.append("TRY_CAST(year AS INTEGER) = ?")
            params.append(year)
        params.append(int(limit))
        exposure_col = "soy_deforestation_5_year_total_exposure" if "soy_deforestation_5_year_total_exposure" in cols else "soy_deforestation_hectares"
        sql = f"""
            SELECT exporter,
                   SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes,
                   SUM(TRY_CAST({exposure_col} AS DOUBLE)) AS exposure_ha
            FROM {table}
            WHERE {' AND '.join(where)}
            GROUP BY exporter
            ORDER BY exposure_ha DESC NULLS LAST
            LIMIT ?
        """
        df = conn.execute(sql, params).fetchdf()
        return _attach_metadata(df, source=table, unit="tonnes / hectares", period="2004-2022", filters={"year": year})
    finally:
        if conn is not None:
            conn.close()


def top_destinations(limit: int = 10, year: int | None = None, state: str | None = None) -> pd.DataFrame:
    conn = None
    try:
        conn = _connect()
        table = _choose_supply_table(conn)
        if table is None:
            return _attach_metadata(_empty_frame(["destination", "volume_tonnes"]), source="soy_supply_chain", unit="tonnes", period="2004-2022", filters={"year": year, "state": state})
        cols = _column_names(conn, table)
        dest_col = _pick_columns(conn, table, ["country_of_first_import", "country_of_destination", "importer"])
        if dest_col is None:
            return _attach_metadata(_empty_frame(["destination", "volume_tonnes"]), source=table, unit="tonnes", period="2004-2022", filters={"year": year, "state": state})
        where = [f"{dest_col} IS NOT NULL"]
        params = []
        if year is not None:
            where.append("TRY_CAST(year AS INTEGER) = ?")
            params.append(year)
        if state is not None:
            where.append("LOWER(state) = LOWER(?)")
            params.append(state)
        params.append(int(limit))
        sql = f"""
            SELECT {dest_col} AS destination,
                   SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes
            FROM {table}
            WHERE {' AND '.join(where)}
            GROUP BY {dest_col}
            ORDER BY volume_tonnes DESC NULLS LAST
            LIMIT ?
        """
        df = conn.execute(sql, params).fetchdf()
        return _attach_metadata(df, source=table, unit="tonnes", period="2004-2022", filters={"year": year, "state": state})
    finally:
        if conn is not None:
            conn.close()


def yearly_trend() -> pd.DataFrame:
    conn = None
    try:
        conn = _connect()
        table = _choose_supply_table(conn)
        if table is None:
            return _attach_metadata(_empty_frame(["year", "volume_tonnes", "exposure_ha", "gross_emissions_tco2e"]), source="soy_supply_chain", unit="tonnes / hectares / tCO2e", period="2004-2022", filters={})
        cols = _column_names(conn, table)
        exposure_col = "soy_deforestation_5_year_total_exposure" if "soy_deforestation_5_year_total_exposure" in cols else "soy_deforestation_hectares"
        emission_col = "co2_gross_emissions_soy_deforestation_5_year_total_exposure" if "co2_gross_emissions_soy_deforestation_5_year_total_exposure" in cols else "gross_emissions_from_soy_deforestation_tonnes_co₂-equivalent"
        sql = f"""
            SELECT TRY_CAST(year AS INTEGER) AS year,
                   SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes,
                   SUM(TRY_CAST({exposure_col} AS DOUBLE)) AS exposure_ha,
                   SUM(TRY_CAST({emission_col} AS DOUBLE)) AS gross_emissions_tco2e
            FROM {table}
            WHERE year IS NOT NULL
            GROUP BY TRY_CAST(year AS INTEGER)
            ORDER BY year
        """
        df = conn.execute(sql).fetchdf()
        return _attach_metadata(df, source=table, unit="tonnes / hectares / tCO2e", period="2004-2022", filters={})
    finally:
        if conn is not None:
            conn.close()


def exposure_by_municipality(limit: int = 10, year: int | None = None) -> pd.DataFrame:
    return top_municipalities(limit=limit, year=year)


def deforestation_by_biome(year: int | None = None) -> pd.DataFrame:
    conn = None
    try:
        conn = _connect()
        table = _choose_supply_table(conn)
        if table is None:
            return _attach_metadata(_empty_frame(["biome", "exposure_ha"]), source="soy_supply_chain", unit="hectares", period="2004-2022", filters={"year": year})
        cols = _column_names(conn, table)
        if "biome" not in cols:
            return _attach_metadata(_empty_frame(["biome", "exposure_ha"]), source=table, unit="hectares", period="2004-2022", filters={"year": year})
        exposure_col = "soy_deforestation_5_year_total_exposure" if "soy_deforestation_5_year_total_exposure" in cols else "soy_deforestation_hectares"
        where = ["biome IS NOT NULL"]
        params = []
        if year is not None:
            where.append("TRY_CAST(year AS INTEGER) = ?")
            params.append(year)
        sql = f"""
            SELECT biome,
                   SUM(TRY_CAST({exposure_col} AS DOUBLE)) AS exposure_ha
            FROM {table}
            WHERE {' AND '.join(where)}
            GROUP BY biome
            ORDER BY exposure_ha DESC NULLS LAST
        """
        df = conn.execute(sql, params).fetchdf()
        return _attach_metadata(df, source=table, unit="hectares", period="2004-2022", filters={"year": year})
    finally:
        if conn is not None:
            conn.close()

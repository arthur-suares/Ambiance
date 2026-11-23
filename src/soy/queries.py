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
    """Conexão somente leitura e sem acesso a arquivos (mesma sandbox do banco da carne bovina).

    Todas as consultas usam a mesma configuração: o DuckDB não abre o mesmo arquivo com
    configurações diferentes no mesmo processo (ex.: servidor web atendendo várias perguntas).
    """
    target = Path(db_path) if db_path is not None else DEFAULT_DUCKDB_PATH
    if not target.exists():
        raise FileNotFoundError(f"Banco DuckDB da soja não encontrado: {target}. Rode: python -m src.cli ingest-soy")
    con = duckdb.connect(str(target), read_only=True, config={"enable_external_access": False})
    con.execute("SET enable_progress_bar = false")
    con.execute("SET lock_configuration = true")
    return con


def connect_readonly():
    """Usada por src.database.run_readonly_sql para o SQL livre do agente no banco da soja."""
    return _connect()


def is_available() -> bool:
    """True se o banco da soja existe e tem a tabela da cadeia (ingest-soy já rodou)."""
    if not DEFAULT_DUCKDB_PATH.exists():
        return False
    con = _connect()
    try:
        return _choose_supply_table(con) is not None
    finally:
        con.close()


def latest_year() -> int | None:
    """Ano mais recente da cadeia da soja com exposição ao desmatamento."""
    con = _connect()
    try:
        table = _choose_supply_table(con)
        if table is None:
            return None
        row = con.execute(
            f"SELECT MAX(TRY_CAST(year AS INTEGER)) FROM {table} "
            "WHERE TRY_CAST(soy_deforestation_5_year_total_exposure AS DOUBLE) > 0"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    finally:
        con.close()


def schema_prompt() -> str:
    """Descrição das tabelas do banco da soja para o prompt do agente (lida do próprio banco)."""
    from src.soy.catalog import load_manifest

    descriptions = {d.get("table_name"): d for d in load_manifest()}
    descriptions.update({
        "soy_spatial_metrics": {"description": "Indicadores territoriais da soja em formato longo: uma linha por "
                                "(metric, level, year, region). level = country, biome, state ou municipality; "
                                "para municípios, parent_region é a UF. Descreve a região inteira, não fluxos da cadeia."},
        "soy_metric_catalog": {"description": "Unidade e descrição de cada métrica de soy_spatial_metrics."},
        "soy_facilities": {"description": "Instalações de soja (armazéns e processadoras). category = STORAGE ou "
                           "PROCESSING; facility_type = LOCAL_SILO, AGGREGATOR ou HUB. Capacidades em t "
                           "(armazenagem) e t/dia (processamento). Nomes de algumas empresas são ocultados na fonte "
                           "(FACILITY NAME WITHHELD)."},
    })
    con = _connect()
    try:
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' "
            "AND table_name <> 'soy_dataset_metadata' ORDER BY table_name"
        ).fetchall()]
        out = ["# Banco DuckDB da soja (somente leitura; consulte com run_soy_sql)\n"]
        for t in tables:
            info = descriptions.get(t, {})
            period = info.get("period") or {}
            head = f"## {t}"
            if info.get("description"):
                head += f"\n{info['description']}"
            if period:
                head += f" Período: {period.get('start')}-{period.get('end')}."
            if info.get("unit"):
                head += f" Unidade: {info['unit']}."
            if info.get("granularity"):
                head += f" Granularidade: {info['granularity']}."
            out.append(head)
            for name, dtype, *_ in con.execute(f"DESCRIBE {t}").fetchall():
                out.append(f"- {name}: {dtype}")
            out.append("")
        if "soy_spatial_metrics" in tables:
            out.append("## Catálogo de métricas da soja (soy_spatial_metrics.metric)")
            for metric, unit, desc, additive, levels, y0, y1 in con.execute("""
                SELECT c.metric, c.unit, c.description, c.additive,
                       string_agg(DISTINCT m.level, ', '), MIN(m.year), MAX(m.year)
                FROM soy_metric_catalog c JOIN soy_spatial_metrics m USING (metric)
                GROUP BY ALL ORDER BY 1
            """).fetchall():
                extra = "" if additive else " (não somar entre regiões)"
                out.append(f"- {metric} [{unit}], {y0}-{y1}, níveis: {levels}{extra}: {desc}")
            out.append("")
        return "\n".join(out)
    finally:
        con.close()


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


# --- Métricas territoriais e instalações (tabelas criadas por src/soy/territorial.py) ---

SPATIAL_LEVELS = ("country", "biome", "state", "municipality")
FACILITY_GROUPS = {"state": "state", "municipality": "municipality, state", "company": "company",
                   "category": "category", "facility_type": "facility_type"}


def spatial_metric_names() -> list[str]:
    from src.soy.territorial import SOY_METRICS
    return sorted(m for m, *_ in SOY_METRICS.values())


def territorial_metric(metric: str, level: str = "state", year: int | None = None,
                       region: str | None = None, parent_region: str | None = None,
                       limit: int = 10, ascending: bool = False) -> pd.DataFrame:
    """Indicador territorial da soja (soy_spatial_metrics): ranking de regiões ou valor de uma região."""
    if metric not in spatial_metric_names():
        raise ValueError(f"metric deve ser um de: {', '.join(spatial_metric_names())}")
    if level not in SPATIAL_LEVELS:
        raise ValueError(f"level deve ser um de: {', '.join(SPATIAL_LEVELS)}")
    where, params = ["metric = ?", "level = ?"], [metric, level]
    if year:
        where.append("year = ?")
        params.append(year)
    else:
        where.append("year = (SELECT MAX(year) FROM soy_spatial_metrics WHERE metric = ? AND level = ? AND value IS NOT NULL)")
        params += [metric, level]
    if region:
        where.append("upper(strip_accents(region)) = upper(strip_accents(?))")
        params.append(region)
    if parent_region:
        where.append("upper(strip_accents(parent_region)) = upper(strip_accents(?))")
        params.append(parent_region)
    con = _connect()
    try:
        return con.execute(f"""
            SELECT year, level, region, parent_region, metric, value, unit
            FROM soy_spatial_metrics
            WHERE {' AND '.join(where)}
            ORDER BY value {'ASC' if ascending else 'DESC'} NULLS LAST
            LIMIT ?
        """, params + [int(limit)]).fetchdf()
    finally:
        con.close()


def facilities_summary(group_by: str = "state", state: str | None = None, municipality: str | None = None,
                       category: str | None = None, company: str | None = None,
                       limit: int = 10, order_by: str = "storage_capacity_t") -> pd.DataFrame:
    """Instalações de soja (armazéns/processadoras) agregadas, com capacidade de armazenagem e processamento."""
    if group_by not in FACILITY_GROUPS:
        raise ValueError(f"group_by deve ser um de: {', '.join(FACILITY_GROUPS)}")
    if order_by not in {"facilities", "storage_capacity_t", "processing_capacity_t_day"}:
        raise ValueError("order_by deve ser facilities, storage_capacity_t ou processing_capacity_t_day")
    where, params = ["TRUE"], []
    for col, val in (("state", state), ("municipality", municipality), ("category", category)):
        if val:
            where.append(f"upper(strip_accents({col})) = upper(strip_accents(?))")
            params.append(val)
    if company:
        where.append("company ILIKE ?")
        params.append(f"%{company}%")
    cols = FACILITY_GROUPS[group_by]
    con = _connect()
    try:
        return con.execute(f"""
            SELECT {cols},
                   COUNT(*) AS facilities,
                   COUNT(*) FILTER (WHERE category = 'PROCESSING') AS processing_facilities,
                   SUM(storage_capacity_t) AS storage_capacity_t,
                   SUM(processing_capacity_t_day) AS processing_capacity_t_day
            FROM soy_facilities
            WHERE {' AND '.join(where)}
            GROUP BY {cols}
            ORDER BY {order_by} DESC NULLS LAST
            LIMIT ?
        """, params + [int(limit)]).fetchdf()
    finally:
        con.close()

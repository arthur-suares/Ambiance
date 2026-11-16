from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src import config
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


GOLD_TABLE = "soy_municipality_year"       # tabela-sentinela: se existe, o banco gold está completo
GOLD_SUPPORT = {"gold_catalog", "meta_runs"}


def using_gold() -> bool:
    """True quando SOY_USE_GOLD está ligado E o banco gold existe. Nesse modo o agente só enxerga o banco gold
    (sem a tabela bruta da cadeia): as regras da gold não podem ser puladas por SQL livre."""
    return bool(config.SOY_USE_GOLD) and config.SOY_GOLD_DUCKDB_PATH.exists()


def _gold_latest_year(con) -> int | None:
    row = con.execute("SELECT MAX(year) FROM soy_national_year WHERE exposure_ha > 0").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _connect(db_path: str | Path | None = None):
    """Conexão somente leitura e sem acesso a arquivos (mesma sandbox do banco da carne bovina).

    Todas as consultas usam a mesma configuração: o DuckDB não abre o mesmo arquivo com
    configurações diferentes no mesmo processo (ex.: servidor web atendendo várias perguntas).
    """
    if db_path is not None:
        target = Path(db_path)
    elif using_gold():
        target = config.SOY_GOLD_DUCKDB_PATH
    else:
        target = DEFAULT_DUCKDB_PATH
    if not target.exists():
        raise FileNotFoundError(f"Banco DuckDB da soja não encontrado: {target}. Rode: python -m src.cli "
                                + ("build-medallion" if using_gold() else "ingest-soy"))
    con = duckdb.connect(str(target), read_only=True, config={"enable_external_access": False})
    con.execute("SET enable_progress_bar = false")
    con.execute("SET lock_configuration = true")
    return con


def connect_readonly():
    """Usada por src.database.run_readonly_sql para o SQL livre do agente no banco da soja."""
    return _connect()


def is_available() -> bool:
    """True se o banco da soja existe e tem a tabela da cadeia (ingest-soy já rodou)."""
    if using_gold():
        con = _connect()
        try:
            return _table_exists(con, GOLD_TABLE)
        finally:
            con.close()
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
        if using_gold():
            return _gold_latest_year(con)
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
        if using_gold():
            # Dicionário vem da tabela gold_catalog do próprio banco (fonte única: src/medallion/catalog.py).
            from src.medallion import catalog as gold_catalog
            from src.medallion.registry import _latest, prompt_line
            cat = con.execute("SELECT * FROM gold_catalog").fetchdf()
            out = [gold_catalog.render_prompt(cat), prompt_line(_latest(con)), ""]
            tables = [t for t in tables if t not in set(cat.table_name) | GOLD_SUPPORT]
            if tables:
                out.append("# Outras tabelas da soja\n")
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


def _gold_query(sql: str, params: list, *, source: str, unit: str, period: str, filters: dict) -> pd.DataFrame:
    conn = _connect()
    try:
        return _attach_metadata(conn.execute(sql, params).fetchdf(), source=source, unit=unit, period=period, filters=filters)
    finally:
        conn.close()


def _gold_year(year: int | None) -> int | None:
    if year is not None:
        return int(year)
    conn = _connect()
    try:
        return _gold_latest_year(conn)
    finally:
        conn.close()


def _gold_top_municipalities(limit, year, state, biome) -> pd.DataFrame:
    year = _gold_year(year)
    where, params = ["year = ?"], [year]
    for col, val in (("state", state), ("biome", biome)):
        if val is not None:
            where.append(f"LOWER({col}) = LOWER(?)")
            params.append(val)
    return _gold_query(
        f"SELECT municipality, state, biome, volume_tonnes, exposure_ha FROM soy_municipality_year WHERE {' AND '.join(where)} "
        "ORDER BY exposure_ha DESC NULLS LAST LIMIT ?", params + [int(limit)], source="soy_municipality_year",
        unit="tonnes / hectares", period=str(year), filters={"year": year, "state": state, "biome": biome})


def _gold_top_exporters(limit, year, level) -> pd.DataFrame:
    year = _gold_year(year)
    if (level or "company") == "group":
        sql = ("SELECT exporter_group AS exporter, volume_tonnes, exposure_ha FROM soy_exporter_group_year "
               "WHERE year = ? ORDER BY exposure_ha DESC NULLS LAST LIMIT ?")
        source = "soy_exporter_group_year"
    else:
        sql = ("SELECT exporter, exporter_group, volume_tonnes, exposure_ha FROM soy_exporter_company_year "
               "WHERE year = ? ORDER BY exposure_ha DESC NULLS LAST LIMIT ?")
        source = "soy_exporter_company_year"
    return _gold_query(sql, [year, int(limit)], source=source, unit="tonnes / hectares", period=str(year),
                       filters={"year": year, "level": level or "company"})


def _gold_top_destinations(limit, year, state) -> pd.DataFrame:
    year = _gold_year(year)
    if state is not None:
        sql = ("SELECT destination, SUM(volume_tonnes) AS volume_tonnes FROM soy_destination_state_year "
               "WHERE year = ? AND LOWER(state) = LOWER(?) GROUP BY destination ORDER BY volume_tonnes DESC NULLS LAST LIMIT ?")
        params, source = [year, state, int(limit)], "soy_destination_state_year"
    else:
        sql = "SELECT destination, volume_tonnes FROM soy_destination_year WHERE year = ? ORDER BY volume_tonnes DESC NULLS LAST LIMIT ?"
        params, source = [year, int(limit)], "soy_destination_year"
    return _gold_query(sql, params, source=source, unit="tonnes", period=str(year), filters={"year": year, "state": state})


def top_municipalities(limit: int = 10, year: int | None = None, state: str | None = None, biome: str | None = None) -> pd.DataFrame:
    if using_gold():
        return _gold_top_municipalities(limit, year, state, biome)
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


def top_exporters(limit: int = 10, year: int | None = None, level: str | None = None) -> pd.DataFrame:
    """level (só no banco gold): "company" (padrão) ou "group"."""
    if using_gold():
        return _gold_top_exporters(limit, year, level)
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
    if using_gold():
        return _gold_top_destinations(limit, year, state)
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
    if using_gold():
        return _gold_query(
            "SELECT year, volume_total_tonnes AS volume_tonnes, exposure_ha, co2_gross_tonnes AS gross_emissions_tco2e "
            "FROM soy_national_year ORDER BY year", [], source="soy_national_year", unit="tonnes / hectares / tCO2e",
            period="2004-2022", filters={})
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
    if using_gold():
        y = _gold_year(year)
        return _gold_query("SELECT biome, exposure_ha FROM soy_biome_year WHERE year = ? ORDER BY exposure_ha DESC NULLS LAST",
                           [y], source="soy_biome_year", unit="hectares", period=str(y), filters={"year": y})
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

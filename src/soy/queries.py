from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from src import result_meta as rm
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


SOY = "soja"
PERIOD = "2004-2022"
EXPOSURE_COL = "soy_deforestation_5_year_total_exposure"
GROSS_COL = "co2_gross_emissions_soy_deforestation_5_year_total_exposure"
VOLUME = "SUM(TRY_CAST(volume AS DOUBLE))"
EXPOSURE = f"SUM(TRY_CAST({EXPOSURE_COL} AS DOUBLE))"
YEAR = "TRY_CAST(year AS INTEGER)"

# Linhas que não são um exportador identificado: soja processada no Brasil e fluxos sem exportador conhecido.
NOT_AN_EXPORTER = ("PROCESSED DOMESTICALLY", "UNKNOWN", "UNKNOWN CUSTOMER")
UNKNOWN_ORIGIN = "UNKNOWN"
DOMESTIC_DESTINATION = "BRAZIL"
RANKING_ORDER = ("exposure_ha", "volume_tonnes")
UNITS = {
    "volume_tonnes": "t",
    "exposure_ha": "ha (exposição ao desmatamento, janela de 5 anos)",
    "gross_emissions_tco2e": "tCO2e (emissões brutas, janela de 5 anos)",
}


def _check_order(order_by: str) -> None:
    if order_by not in RANKING_ORDER:
        raise ValueError(f"order_by deve ser um de: {', '.join(RANKING_ORDER)}")


def _supply(conn) -> str:
    table = _choose_supply_table(conn)
    if table is None:
        raise FileNotFoundError("Tabela da cadeia da soja não encontrada. Rode: python -m src.cli ingest-soy")
    return table


def _text_filters(pairs) -> tuple[list[str], list]:
    """Filtros de texto sem diferenciar acento nem caixa: [(coluna, valor)] -> (condições, parâmetros)."""
    where, params = [], []
    for col, val in pairs:
        if val:
            where.append(f"upper(strip_accents({col})) = upper(strip_accents(?))")
            params.append(val)
    return where, params


def _share_note(conn, table: str, where: list[str], params: list, excluded_sql: str, label: str) -> str:
    """Quanto as linhas excluídas representam do total (para o ranking declarar a sua cobertura)."""
    row = conn.execute(f"""
        SELECT {VOLUME} FILTER (WHERE {excluded_sql}), {VOLUME},
               {EXPOSURE} FILTER (WHERE {excluded_sql}), {EXPOSURE}
        FROM {table} WHERE {' AND '.join(where)}
    """, params).fetchone()
    ev, tv, ee, te = (float(x or 0) for x in row)
    if not ev and not ee:
        return f"{label}: nenhuma neste recorte"
    share = lambda part, total: f"{part / total:.0%}" if total else "n/d"
    num = lambda x: f"{x:,.0f}".replace(",", ".")
    return (f"{label} somam {num(ev)} t ({share(ev, tv)} do volume) e {num(ee)} ha ({share(ee, te)} da exposição) "
            "neste recorte: o resultado cobre só a parte identificada")


def top_municipalities(limit: int = 10, year: int | None = None, state: str | None = None, biome: str | None = None,
                       order_by: str = "exposure_ha", include_unknown: bool = False) -> pd.DataFrame:
    """Soja: municípios de produção ordenados por exposição ou volume em um ano (padrão: o mais recente).

    Por padrão exclui a origem não rastreada (UNKNOWN), que não é um município.
    """
    _check_order(order_by)
    year = year or latest_year()
    conn = _connect()
    try:
        table = _supply(conn)
        extra, params = _text_filters((("state", state), ("biome", biome)))
        base = [f"{YEAR} = ?", "municipality_of_production IS NOT NULL"] + extra
        params = [year] + params
        unknown = f"municipality_of_production = '{UNKNOWN_ORIGIN}'"
        where = base + ([] if include_unknown else [f"NOT ({unknown})"])
        df = conn.execute(f"""
            SELECT {YEAR} AS year, municipality_of_production AS municipality,
                   COALESCE(state, '') AS state, COALESCE(biome, '') AS biome,
                   {VOLUME} AS volume_tonnes, {EXPOSURE} AS exposure_ha
            FROM {table}
            WHERE {' AND '.join(where)}
            GROUP BY ALL
            ORDER BY {order_by} DESC NULLS LAST
            LIMIT ?
        """, params + [int(limit)]).fetchdf()
        notes = [rm.RANKING_NOTE, rm.WINDOW_5Y]
        if not include_unknown:
            notes.insert(1, _share_note(conn, table, base, params, unknown, "linhas de origem não rastreada (UNKNOWN)"))
        filters = {"year": year, "state": state, "biome": biome}
        _attach_metadata(df, source=table, unit="tonnes / hectares", period=PERIOD, filters=filters)
        return rm.attach(
            df, cadeia=SOY, escopo=rm.FLOWS, ano=year, agrupado_por="município de produção",
            ordenado_por=f"{order_by} (maior primeiro), {limit} primeiras linhas",
            filtros={"state": state, "biome": biome},
            excluidos=[] if include_unknown else ["município de origem não rastreado (UNKNOWN)"],
            unidades={k: UNITS[k] for k in ("volume_tonnes", "exposure_ha")}, notas=notes)
    finally:
        conn.close()


def top_exporters(limit: int = 10, year: int | None = None, by_group: bool = True, order_by: str = "exposure_ha",
                  include_unidentified: bool = False) -> pd.DataFrame:
    """Soja: grupos exportadores (ou empresas) ordenados por exposição ou volume em um ano (padrão: o mais recente).

    Por padrão exclui o que não é um exportador identificado: soja processada no Brasil
    (PROCESSED DOMESTICALLY) e fluxos sem exportador conhecido (UNKNOWN / UNKNOWN CUSTOMER).
    """
    _check_order(order_by)
    year = year or latest_year()
    key = "exporter_group" if by_group else "exporter"
    conn = _connect()
    try:
        table = _supply(conn)
        base, params = [f"{YEAR} = ?", f"{key} IS NOT NULL"], [year]
        names = ", ".join(f"'{n}'" for n in NOT_AN_EXPORTER)
        unidentified = f"{key} IN ({names})"
        where = base + ([] if include_unidentified else [f"NOT ({unidentified})"])
        df = conn.execute(f"""
            SELECT {YEAR} AS year, {key}, {VOLUME} AS volume_tonnes, {EXPOSURE} AS exposure_ha
            FROM {table}
            WHERE {' AND '.join(where)}
            GROUP BY ALL
            ORDER BY {order_by} DESC NULLS LAST
            LIMIT ?
        """, params + [int(limit)]).fetchdf()
        notes = [rm.RANKING_NOTE, rm.WINDOW_5Y]
        if not include_unidentified:
            notes.insert(1, _share_note(conn, table, base, params, unidentified,
                                        "soja processada no Brasil e fluxos sem exportador identificado"))
        _attach_metadata(df, source=table, unit="tonnes / hectares", period=PERIOD, filters={"year": year})
        return rm.attach(
            df, cadeia=SOY, escopo=rm.FLOWS, ano=year,
            agrupado_por="grupo econômico exportador (exporter_group)" if by_group
            else "empresa exportadora (exporter; uma empresa pode pertencer a um grupo maior)",
            ordenado_por=f"{order_by} (maior primeiro), {limit} primeiras linhas",
            excluidos=[] if include_unidentified else [
                "PROCESSED DOMESTICALLY (soja processada no Brasil, não é exportador)",
                "UNKNOWN / UNKNOWN CUSTOMER (exportador não identificado)"],
            unidades={k: UNITS[k] for k in ("volume_tonnes", "exposure_ha")}, notas=notes)
    finally:
        conn.close()


def top_destinations(limit: int = 10, year: int | None = None, state: str | None = None,
                     include_domestic: bool = False) -> pd.DataFrame:
    """Soja: países de primeira importação por volume em um ano (padrão: o mais recente), sem o consumo interno."""
    year = year or latest_year()
    conn = _connect()
    try:
        table = _supply(conn)
        extra, params = _text_filters((("state", state),))
        where = [f"{YEAR} = ?", "country_of_first_import IS NOT NULL"] + extra
        if not include_domestic:
            where.append(f"country_of_first_import <> '{DOMESTIC_DESTINATION}'")
        df = conn.execute(f"""
            SELECT {YEAR} AS year, country_of_first_import AS destination,
                   {VOLUME} AS volume_tonnes, {EXPOSURE} AS exposure_ha
            FROM {table}
            WHERE {' AND '.join(where)}
            GROUP BY ALL
            ORDER BY volume_tonnes DESC NULLS LAST
            LIMIT ?
        """, [year] + params + [int(limit)]).fetchdf()
        _attach_metadata(df, source=table, unit="tonnes", period=PERIOD, filters={"year": year, "state": state})
        return rm.attach(
            df, cadeia=SOY, escopo=rm.FLOWS, ano=year, agrupado_por="país de primeira importação",
            ordenado_por=f"volume_tonnes (maior primeiro), {limit} primeiras linhas", filtros={"state": state},
            excluidos=[] if include_domestic else [f"consumo interno (destino {DOMESTIC_DESTINATION})"],
            unidades={k: UNITS[k] for k in ("volume_tonnes", "exposure_ha")}, notas=[rm.RANKING_NOTE, rm.WINDOW_5Y])
    finally:
        conn.close()


def yearly_trend(state: str | None = None, biome: str | None = None, exporter_group: str | None = None) -> pd.DataFrame:
    """Soja: série anual de volume, exposição e emissões brutas da cadeia, com filtros opcionais."""
    conn = _connect()
    try:
        table = _supply(conn)
        extra, params = _text_filters((("state", state), ("biome", biome), ("exporter_group", exporter_group)))
        df = conn.execute(f"""
            SELECT {YEAR} AS year, {VOLUME} AS volume_tonnes, {EXPOSURE} AS exposure_ha,
                   SUM(TRY_CAST({GROSS_COL} AS DOUBLE)) AS gross_emissions_tco2e
            FROM {table}
            WHERE {' AND '.join(['year IS NOT NULL'] + extra)}
            GROUP BY ALL
            ORDER BY year
        """, params).fetchdf()
        _attach_metadata(df, source=table, unit="tonnes / hectares / tCO2e", period=PERIOD, filters={})
        return rm.attach(
            df, cadeia=SOY, escopo=rm.FLOWS, agrupado_por="ano (uma linha por ano)", ordenado_por="ano",
            filtros={"state": state, "biome": biome, "exporter_group": exporter_group}, unidades=UNITS,
            notas=["inclui a origem não rastreada (UNKNOWN) e a soja processada no Brasil, salvo filtro", rm.WINDOW_5Y])
    finally:
        conn.close()


def exposure_by_municipality(limit: int = 10, year: int | None = None) -> pd.DataFrame:
    return top_municipalities(limit=limit, year=year)


def deforestation_by_biome(year: int | None = None) -> pd.DataFrame:
    """Soja: exposição ao desmatamento e volume por bioma em um ano (padrão: o mais recente)."""
    year = year or latest_year()
    conn = _connect()
    try:
        table = _supply(conn)
        df = conn.execute(f"""
            SELECT {YEAR} AS year, biome, {EXPOSURE} AS exposure_ha, {VOLUME} AS volume_tonnes
            FROM {table}
            WHERE {YEAR} = ? AND biome IS NOT NULL
            GROUP BY ALL
            ORDER BY exposure_ha DESC NULLS LAST
        """, [year]).fetchdf()
        rm.add_position(df, "biome", "exposure_ha")
        _attach_metadata(df, source=table, unit="hectares", period=PERIOD, filters={"year": year})
        return rm.attach(
            df, cadeia=SOY, escopo=rm.FLOWS, ano=year, agrupado_por="bioma de produção",
            ordenado_por="exposure_ha (maior primeiro), todos os biomas",
            unidades={k: UNITS[k] for k in ("exposure_ha", "volume_tonnes")},
            notas=["a linha UNKNOWN é a origem não rastreada: não é um bioma e não pode ser atribuída a nenhum deles",
                   rm.POSITION_NOTE.format(col="exposure_ha"), rm.WINDOW_5Y])
    finally:
        conn.close()


# --- Métricas territoriais e instalações (tabelas criadas por src/soy/territorial.py) ---

SPATIAL_LEVELS = ("country", "biome", "state", "municipality")
FACILITY_GROUPS = {"state": "state", "municipality": "municipality, state", "company": "company",
                   "category": "category", "facility_type": "facility_type"}
FACILITY_ORDER = ("facilities", "storage_capacity_t", "processing_capacity_t_day")


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
        df = con.execute(f"""
            SELECT year, level, region, parent_region, metric, value, unit
            FROM soy_spatial_metrics
            WHERE {' AND '.join(where)}
            ORDER BY value {'ASC' if ascending else 'DESC'} NULLS LAST
            LIMIT ?
        """, params + [int(limit)]).fetchdf()
        info = con.execute("SELECT unit, description, additive FROM soy_metric_catalog WHERE metric = ?",
                           [metric]).fetchone() or ("", "", True)
        return rm.attach(
            df, cadeia=SOY, escopo=rm.TERRITORIAL, ano=int(df["year"].iloc[0]) if len(df) else year,
            agrupado_por=f"região (nível {level})",
            ordenado_por=f"value ({'menor' if ascending else 'maior'} primeiro), {limit} primeiras linhas",
            filtros={"metric": metric, "region": region, "parent_region": parent_region},
            unidades={"value": f"{info[0]} ({info[1]})"},
            notas=[] if info[2] else ["esta métrica não pode ser somada nem ter média simples entre regiões"])
    finally:
        con.close()


def facilities_summary(group_by: str = "state", state: str | None = None, municipality: str | None = None,
                       category: str | None = None, company: str | None = None,
                       limit: int = 10, order_by: str = "storage_capacity_t") -> pd.DataFrame:
    """Instalações de soja (armazéns/processadoras) agregadas, com capacidade de armazenagem e processamento."""
    if group_by not in FACILITY_GROUPS:
        raise ValueError(f"group_by deve ser um de: {', '.join(FACILITY_GROUPS)}")
    if order_by not in FACILITY_ORDER:
        raise ValueError(f"order_by deve ser um de: {', '.join(FACILITY_ORDER)}")
    where, params = _text_filters((("state", state), ("municipality", municipality), ("category", category)))
    where = ["TRUE"] + where
    if company:
        where.append("company ILIKE ?")
        params.append(f"%{company}%")
    cols = FACILITY_GROUPS[group_by]
    con = _connect()
    try:
        df = con.execute(f"""
            SELECT {cols},
                   COUNT(*) AS facilities,
                   COUNT(*) FILTER (WHERE category = 'PROCESSING') AS processing_facilities,
                   COUNT(*) FILTER (WHERE processing_capacity_t_day > 0) AS facilities_with_processing_capacity,
                   SUM(storage_capacity_t) AS storage_capacity_t,
                   SUM(processing_capacity_t_day) AS processing_capacity_t_day
            FROM soy_facilities
            WHERE {' AND '.join(where)}
            GROUP BY {cols}
            ORDER BY {order_by} DESC NULLS LAST
            LIMIT ?
        """, params + [int(limit)]).fetchdf()
        return rm.attach(
            df, cadeia=SOY, escopo=rm.FACILITIES, agrupado_por=group_by,
            ordenado_por=f"{order_by} (maior primeiro), {limit} primeiras linhas",
            filtros={"state": state, "municipality": municipality, "category": category, "company": company},
            unidades={
                "facilities": "nº de instalações cadastradas (armazéns + processadoras)",
                "processing_facilities": "nº de instalações da categoria PROCESSING",
                "facilities_with_processing_capacity": "nº de instalações com capacidade de processamento informada (> 0)",
                "storage_capacity_t": "t (capacidade de armazenagem)",
                "processing_capacity_t_day": "t/dia (capacidade de processamento)"},
            notas=[rm.RANKING_NOTE,
                   "as duas contagens de processamento podem diferir: há instalação PROCESSING sem capacidade informada",
                   "cadastro sem ano de referência"])
    finally:
        con.close()

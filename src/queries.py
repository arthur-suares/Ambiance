from src.database import get_connection_with_data
from src.config import TABLE_NAME


def _run(sql: str, params: list | None = None):
    con = get_connection_with_data()
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def top_municipalities(limit: int = 10, biome: str | None = None, year: int | None = None):
    """Ranking de municípios pela exposição estimada agregada nos registros."""
    where = ["municipality_of_production IS NOT NULL"]
    params = []
    if biome:
        where.append("LOWER(biome) = LOWER(?)")
        params.append(biome)
    if year is not None:
        where.append("TRY_CAST(year AS INTEGER) = ?")
        params.append(year)
    params.append(limit)

    return _run(
        f"""
        SELECT municipality_of_production AS municipality, biome,
               SUM(TRY_CAST(cattle_deforestation_5_year_total_exposure AS DOUBLE))
                   AS estimated_exposure_ha,
               SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes
        FROM {TABLE_NAME}
        WHERE {" AND ".join(where)}
        GROUP BY municipality_of_production, biome
        ORDER BY estimated_exposure_ha DESC NULLS LAST
        LIMIT ?
        """,
        params,
    )


def top_exporters(limit: int = 10, year: int | None = None):
    where = ["exporter IS NOT NULL"]
    params = []
    if year is not None:
        where.append("TRY_CAST(year AS INTEGER) = ?")
        params.append(year)
    params.append(limit)

    return _run(
        f"""
        SELECT exporter,
               SUM(TRY_CAST(cattle_deforestation_5_year_total_exposure AS DOUBLE))
                   AS estimated_exposure_ha,
               SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes,
               COUNT(DISTINCT municipality_of_production) AS source_municipalities,
               COUNT(DISTINCT country_of_destination) AS destination_countries
        FROM {TABLE_NAME}
        WHERE {" AND ".join(where)}
        GROUP BY exporter
        ORDER BY estimated_exposure_ha DESC NULLS LAST
        LIMIT ?
        """,
        params,
    )


def top_destinations(limit: int = 10, year: int | None = None):
    where = ["country_of_destination IS NOT NULL"]
    params = []
    if year is not None:
        where.append("TRY_CAST(year AS INTEGER) = ?")
        params.append(year)
    params.append(limit)

    return _run(
        f"""
        SELECT country_of_destination AS destination,
               SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes,
               SUM(TRY_CAST(fob AS DOUBLE)) AS fob_usd,
               SUM(TRY_CAST(cattle_deforestation_5_year_total_exposure AS DOUBLE))
                   AS estimated_exposure_ha
        FROM {TABLE_NAME}
        WHERE {" AND ".join(where)}
        GROUP BY country_of_destination
        ORDER BY volume_tonnes DESC NULLS LAST
        LIMIT ?
        """,
        params,
    )


def yearly_trend():
    return _run(
        f"""
        SELECT TRY_CAST(year AS INTEGER) AS year,
               SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes,
               SUM(TRY_CAST(cattle_deforestation_5_year_total_exposure AS DOUBLE))
                   AS estimated_exposure_ha,
               SUM(TRY_CAST(co2_net_emissions_cattle_deforestation_5_year_total_exposure AS DOUBLE))
                   AS net_emissions_tco2e
        FROM {TABLE_NAME}
        GROUP BY TRY_CAST(year AS INTEGER)
        ORDER BY year
        """
    )


def exposure_intensity_by_municipality(limit: int = 10, biome: str | None = None):
    """Exposição estimada em hectares por tonelada, agregada por município."""
    where = [
        "municipality_of_production IS NOT NULL",
        "TRY_CAST(volume AS DOUBLE) > 0",
    ]
    params = []
    if biome:
        where.append("LOWER(biome) = LOWER(?)")
        params.append(biome)
    params.append(limit)

    return _run(
        f"""
        SELECT municipality_of_production AS municipality, biome,
               SUM(TRY_CAST(cattle_deforestation_5_year_total_exposure AS DOUBLE))
                   / NULLIF(SUM(TRY_CAST(volume AS DOUBLE)), 0)
                   AS exposure_ha_per_tonne,
               SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes
        FROM {TABLE_NAME}
        WHERE {" AND ".join(where)}
        GROUP BY municipality_of_production, biome
        HAVING SUM(TRY_CAST(volume AS DOUBLE)) > 0
        ORDER BY exposure_ha_per_tonne DESC NULLS LAST
        LIMIT ?
        """,
        params,
    )


def commitment_summary():
    return _run(
        f"""
        SELECT zero_deforestation_brazil_beef AS commitment_status,
               COUNT(DISTINCT exporter) AS exporters,
               SUM(TRY_CAST(volume AS DOUBLE)) AS volume_tonnes,
               SUM(TRY_CAST(cattle_deforestation_5_year_total_exposure AS DOUBLE))
                   AS estimated_exposure_ha
        FROM {TABLE_NAME}
        GROUP BY zero_deforestation_brazil_beef
        ORDER BY volume_tonnes DESC NULLS LAST
        """
    )

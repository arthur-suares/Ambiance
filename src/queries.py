"""Consultas prontas sobre o banco analítico.

Cada função devolve um DataFrame e é usada tanto pela CLI quanto pelo agente
(src/agent.py), que as expõe ao LLM como ferramentas.

Regra geral: indicadores com janela de 5 anos (exposição, emissões) não são
somados entre anos. Por isso os rankings sempre filtram um ano; sem ano, usam o
mais recente.
"""

from functools import lru_cache

from src.data_dictionary import (
    DOMESTIC_DESTINATION, DOMESTIC_EXPORTER, LEVELS, METRICS, UF_BY_ABBREV, UNKNOWN_MUNICIPALITY,
)


def _uf(value: str | None) -> str | None:
    """Aceita a sigla da UF (MT, pa) e devolve o nome usado nos dados; outros valores passam direto."""
    if not value:
        return value
    return UF_BY_ABBREV.get(value.strip().upper(), value)
from src.database import get_connection

MUNICIPALITY_ORDER = {
    "deforestation_exposure_ha", "volume_t", "volume_exported_t", "fob_usd",
    "co2_net_tco2e", "co2_gross_tco2e", "land_use_ha",
}
SPATIAL_METRIC_NAMES = {m[0] for m in METRICS.values()}


def _run(sql: str, params: list | None = None):
    con = get_connection()
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


@lru_cache(maxsize=1)
def latest_year() -> int:
    """Ano mais recente da supply_chain com exposição ao desmatamento."""
    return int(_run(
        "SELECT MAX(year) AS y FROM supply_chain WHERE cattle_deforestation_5_year_total_exposure > 0"
    )["y"][0])


def _filters(year, biome=None, state=None, prefix="", include_unknown=False):
    where, params = [f"{prefix}year = ?"], [year]
    if not include_unknown:
        # Consumo interno e parte da exportação não têm município de origem (UNKNOWN / BR-XXXXXXX)
        # e concentram ~90% da exposição; num ranking de municípios eles não são um município.
        where.append(f"{prefix}municipality_of_production <> ?")
        params.append(UNKNOWN_MUNICIPALITY)
    if biome:
        where.append(f"upper({prefix}biome) = upper(?)")
        params.append(biome)
    if state:
        where.append(f"upper({prefix}state_of_production) = upper(?)")
        params.append(_uf(state))
    return where, params


def top_municipalities(limit: int = 10, biome: str | None = None, year: int | None = None,
                       state: str | None = None, order_by: str = "deforestation_exposure_ha",
                       include_unknown: bool = False):
    """Municípios de produção ordenados por um indicador da cadeia, em um ano.

    Por padrão exclui a origem desconhecida (UNKNOWN), que não é um município.
    """
    if order_by not in MUNICIPALITY_ORDER:
        raise ValueError(f"order_by deve ser um de: {', '.join(sorted(MUNICIPALITY_ORDER))}")
    year = year or latest_year()
    where, params = _filters(year, biome, state, include_unknown=include_unknown)
    return _run(
        f"""
        SELECT year, municipality_of_production AS municipality, state_of_production AS state, biome,
               deforestation_exposure_ha, volume_t, volume_exported_t, fob_usd, co2_net_tco2e,
               deforestation_exposure_ha / NULLIF(volume_t, 0) AS exposure_ha_per_t
        FROM flows_by_municipality
        WHERE {" AND ".join(where)}
        ORDER BY {order_by} DESC NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )


EXPORTER_ORDER = {"deforestation_exposure_ha", "volume_t", "fob_usd", "exposure_ha_per_t"}


def top_exporters(limit: int = 10, year: int | None = None, include_domestic: bool = False,
                  by_group: bool = True, order_by: str = "deforestation_exposure_ha"):
    """Grupos exportadores (ou exportadores) ordenados por um indicador em um ano.

    Antes de 2015 não há exposição: o padrão passa a ser volume_t para o ranking ter sentido.
    """
    if order_by not in EXPORTER_ORDER:
        raise ValueError(f"order_by deve ser um de: {', '.join(sorted(EXPORTER_ORDER))}")
    year = year or latest_year()
    if year < 2015 and order_by in {"deforestation_exposure_ha", "exposure_ha_per_t"}:
        order_by = "volume_t"
    key = "exporter_group" if by_group else "exporter"
    where, params = ["year = ?"], [year]
    if not include_domestic:
        where.append("exporter <> ?")
        params.append(DOMESTIC_EXPORTER)
    return _run(
        f"""
        SELECT year, {key},
               SUM(cattle_deforestation_5_year_total_exposure) AS deforestation_exposure_ha,
               SUM(volume) AS volume_t,
               SUM(fob) AS fob_usd,
               SUM(cattle_deforestation_5_year_total_exposure) / NULLIF(SUM(volume), 0) AS exposure_ha_per_t,
               COUNT(DISTINCT municipality_of_production) AS source_municipalities,
               COUNT(DISTINCT country_of_destination) AS destination_countries,
               STRING_AGG(DISTINCT zero_deforestation_brazil_beef, ' | ') AS zdc_commitment
        FROM supply_chain
        WHERE {" AND ".join(where)} AND {key} IS NOT NULL
        GROUP BY year, {key}
        ORDER BY {order_by} DESC NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )


def top_destinations(limit: int = 10, year: int | None = None, include_domestic: bool = False):
    """Países de destino por volume em um ano."""
    year = year or latest_year()
    where, params = ["year = ?"], [year]
    if not include_domestic:
        where.append("country_of_destination <> ?")
        params.append(DOMESTIC_DESTINATION)
    return _run(
        f"""
        SELECT year, country_of_destination AS destination, economic_bloc,
               volume_t, fob_usd, deforestation_exposure_ha,
               deforestation_exposure_ha / NULLIF(volume_t, 0) AS exposure_ha_per_t
        FROM flows_by_destination
        WHERE {" AND ".join(where)}
        ORDER BY volume_t DESC NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )


def yearly_trend(biome: str | None = None, state: str | None = None,
                 municipality: str | None = None, exporter_group: str | None = None):
    """Série anual de volume, FOB, exposição e emissões (com filtros opcionais)."""
    where, params = ["TRUE"], []
    for col, val in (("biome", biome), ("state_of_production", _uf(state)),
                     ("municipality_of_production", municipality), ("exporter_group", exporter_group)):
        if val:
            where.append(f"upper({col}) = upper(?)")
            params.append(val)
    return _run(
        f"""
        SELECT year,
               SUM(volume) AS volume_t,
               SUM(volume) FILTER (WHERE exporter <> '{DOMESTIC_EXPORTER}') AS volume_exported_t,
               SUM(fob) AS fob_usd,
               CASE WHEN year >= 2015 THEN SUM(cattle_deforestation_5_year_total_exposure) END
                   AS deforestation_exposure_ha,
               CASE WHEN year >= 2015 THEN SUM(co2_net_emissions_cattle_deforestation_5_year_total_exposure) END
                   AS co2_net_tco2e
        FROM supply_chain
        WHERE {" AND ".join(where)}
        GROUP BY year
        ORDER BY year
        """,
        params,
    )


def exposure_intensity_by_municipality(limit: int = 10, biome: str | None = None,
                                       year: int | None = None, min_volume_t: float = 100.0):
    """Exposição por tonelada (ha/t) por município, ignorando municípios com pouco volume."""
    year = year or latest_year()
    where, params = _filters(year, biome)
    where.append("volume_t >= ?")
    params.append(min_volume_t)
    return _run(
        f"""
        SELECT year, municipality_of_production AS municipality, state_of_production AS state, biome,
               deforestation_exposure_ha / NULLIF(volume_t, 0) AS exposure_ha_per_t,
               deforestation_exposure_ha, volume_t
        FROM flows_by_municipality
        WHERE {" AND ".join(where)}
        ORDER BY exposure_ha_per_t DESC NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )


def commitment_summary(year: int | None = None, include_domestic: bool = False):
    """Volume e exposição por tipo de compromisso de desmatamento zero do exportador."""
    year = year or latest_year()
    where, params = ["year = ?"], [year]
    if not include_domestic:
        where.append("exporter <> ?")
        params.append(DOMESTIC_EXPORTER)
    return _run(
        f"""
        SELECT year, zero_deforestation_brazil_beef AS commitment_status,
               COUNT(DISTINCT exporter_group) AS exporter_groups,
               SUM(volume) AS volume_t,
               SUM(volume) / SUM(SUM(volume)) OVER () * 100 AS volume_share_pct,
               SUM(cattle_deforestation_5_year_total_exposure) AS deforestation_exposure_ha
        FROM supply_chain
        WHERE {" AND ".join(where)}
        GROUP BY year, zero_deforestation_brazil_beef
        ORDER BY volume_t DESC NULLS LAST
        """,
        params,
    )


def territorial_metric(metric: str, level: str = "state", year: int | None = None,
                       region: str | None = None, parent_region: str | None = None,
                       limit: int = 10, ascending: bool = False):
    """Indicador territorial (spatial_metrics) por região: ranking ou valor de uma região."""
    if metric not in SPATIAL_METRIC_NAMES:
        raise ValueError(f"metric deve ser um de: {', '.join(sorted(SPATIAL_METRIC_NAMES))}")
    if level not in LEVELS:
        raise ValueError(f"level deve ser um de: {', '.join(LEVELS)}")
    where, params = ["metric = ?", "level = ?"], [metric, level]
    if year:
        where.append("year = ?")
        params.append(year)
    else:
        where.append("year = (SELECT MAX(year) FROM spatial_metrics WHERE metric = ? AND level = ?)")
        params += [metric, level]
    if region:
        where.append("upper(region) = upper(?)")
        params.append(_uf(region) if level == "state" else region)
    if parent_region:
        where.append("upper(parent_region) = upper(?)")
        params.append(_uf(parent_region) if level == "municipality" else parent_region)
    return _run(
        f"""
        SELECT year, level, region, parent_region, metric, value, unit
        FROM spatial_metrics
        WHERE {" AND ".join(where)}
        ORDER BY value {"ASC" if ascending else "DESC"} NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )


ENTITY_KINDS = (
    "municipality", "state", "biome", "exporter", "exporter_group", "importer", "importer_group",
    "country_of_destination", "economic_bloc", "port_of_export", "logistics_hub", "company",
)


def find_entity(text: str, kind: str | None = None, limit: int = 8):
    """Valores reais mais parecidos com um nome digitado (tolera acento, caixa e erro de grafia)."""
    if kind and kind not in ENTITY_KINDS:
        raise ValueError(f"kind deve ser um de: {', '.join(ENTITY_KINDS)}")
    where, params = ["TRUE"], []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    return _run(
        f"""
        WITH q AS (SELECT upper(strip_accents(trim(?))) AS t)
        SELECT kind, value, context,
               -- Bônus: nome idêntico (+1) > texto como palavra inteira, ex. "CHINA (MAINLAND)" (+0,5)
               -- > texto colado em outra palavra, ex. "CHINATEX" (+0,3).
               round(jaro_winkler_similarity(norm, q.t)
                     + CASE WHEN norm = q.t THEN 1
                            WHEN regexp_matches(norm, '(^|[^A-Z0-9])' || regexp_escape(q.t) || '([^A-Z0-9]|$)') THEN 0.5
                            WHEN contains(norm, q.t) THEN 0.3
                            ELSE 0 END, 3) AS score
        FROM entity_index, q
        WHERE {" AND ".join(where)}
        ORDER BY score DESC
        LIMIT ?
        """,
        [text] + params + [limit],
    )

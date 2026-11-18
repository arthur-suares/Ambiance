"""Consultas prontas sobre o banco analítico.

Cada função devolve um DataFrame e é usada tanto pela CLI quanto pelo agente
(src/agent.py), que as expõe ao LLM como ferramentas.

Regra geral: indicadores com janela de 5 anos (exposição, emissões) não são
somados entre anos. Por isso os rankings sempre filtram um ano; sem ano, usam o
mais recente.
"""

from functools import lru_cache

from src import result_meta as rm
from src.data_dictionary import (
    DOMESTIC_DESTINATION, DOMESTIC_EXPORTER, LEVELS, METRICS, UF_BY_ABBREV, UNKNOWN_MUNICIPALITY,
)
from src.database import get_connection

BEEF = "carne bovina"
UNITS = {
    "deforestation_exposure_ha": "ha (exposição ao desmatamento, janela de 5 anos)",
    "volume_t": "t (cadeia inteira: exportação + consumo interno, salvo exclusão indicada)",
    "volume_exported_t": "t (só exportação)",
    "fob_usd": "US$ FOB",
    "co2_net_tco2e": "tCO2e (emissões líquidas, janela de 5 anos)",
    "exposure_ha_per_t": "ha por t (não somar nem tirar média entre linhas)",
}
UNKNOWN_NOTE = ("origem desconhecida (UNKNOWN) concentra ~90% da exposição de cada ano: o resultado cobre só a "
                "parte rastreada até o município")


def _units(*cols: str) -> dict:
    return {c: UNITS[c] for c in cols}


def _uf(value: str | None) -> str | None:
    """Aceita a sigla da UF (MT, pa) e devolve o nome usado nos dados; outros valores passam direto."""
    if not value:
        return value
    return UF_BY_ABBREV.get(value.strip().upper(), value)

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
    df = _run(
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
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.FLOWS, ano=year, agrupado_por="município de produção",
        ordenado_por=f"{order_by} (maior primeiro), {limit} primeiras linhas",
        filtros={"biome": biome, "state": _uf(state)},
        excluidos=[] if include_unknown else ["município de origem desconhecido (UNKNOWN)"],
        unidades=_units("deforestation_exposure_ha", "volume_t", "volume_exported_t", "fob_usd", "co2_net_tco2e",
                        "exposure_ha_per_t"),
        notas=[rm.RANKING_NOTE, UNKNOWN_NOTE, rm.WINDOW_5Y])


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
    df = _run(
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
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.FLOWS, ano=year,
        agrupado_por="grupo econômico exportador (exporter_group)" if by_group
        else "empresa exportadora (exporter; uma empresa pode pertencer a um grupo maior)",
        ordenado_por=f"{order_by} (maior primeiro), {limit} primeiras linhas",
        excluidos=[] if include_domestic else [f"consumo interno ({DOMESTIC_EXPORTER})"],
        unidades={**_units("deforestation_exposure_ha", "fob_usd", "exposure_ha_per_t"), "volume_t": "t"},
        notas=[rm.RANKING_NOTE, "a linha UNKNOWN, se aparecer, são fluxos sem exportador identificado, não uma empresa",
               rm.WINDOW_5Y])


def top_destinations(limit: int = 10, year: int | None = None, include_domestic: bool = False):
    """Países de destino por volume em um ano."""
    year = year or latest_year()
    where, params = ["year = ?"], [year]
    if not include_domestic:
        where.append("country_of_destination <> ?")
        params.append(DOMESTIC_DESTINATION)
    df = _run(
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
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.FLOWS, ano=year, agrupado_por="país de destino",
        ordenado_por=f"volume_t (maior primeiro), {limit} primeiras linhas",
        excluidos=[] if include_domestic else [f"consumo interno (destino {DOMESTIC_DESTINATION})"],
        unidades={**_units("deforestation_exposure_ha", "fob_usd", "exposure_ha_per_t"), "volume_t": "t"},
        notas=[rm.RANKING_NOTE, rm.WINDOW_5Y])


def yearly_trend(biome: str | None = None, state: str | None = None,
                 municipality: str | None = None, exporter_group: str | None = None):
    """Série anual de volume, FOB, exposição e emissões (com filtros opcionais)."""
    where, params = ["TRUE"], []
    for col, val in (("biome", biome), ("state_of_production", _uf(state)),
                     ("municipality_of_production", municipality), ("exporter_group", exporter_group)):
        if val:
            where.append(f"upper({col}) = upper(?)")
            params.append(val)
    df = _run(
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
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.FLOWS, agrupado_por="ano (uma linha por ano)", ordenado_por="ano",
        filtros={"biome": biome, "state": _uf(state), "municipality": municipality, "exporter_group": exporter_group},
        unidades=_units("volume_t", "volume_exported_t", "fob_usd", "deforestation_exposure_ha", "co2_net_tco2e"),
        notas=["inclui a origem desconhecida (UNKNOWN) e o consumo interno, salvo filtro",
               "exposição e emissões só existem de 2015 em diante; vazio = sem dado, não zero", rm.WINDOW_5Y])


REGION_LEVELS = {"biome": "biome", "state": "state_of_production"}


def deforestation_by_region(level: str = "biome", year: int | None = None, region: str | None = None,
                            include_unknown: bool = True):
    """Exposição ao desmatamento, volume e emissões dos fluxos da cadeia por bioma ou UF de produção, em um ano.

    É a soma dos fluxos (supply_chain), não o indicador territorial (territorial_metric). A linha de origem
    desconhecida (UNKNOWN / UNKNOWN STATE) vem por padrão, para mostrar quanto fica sem região.
    """
    if level not in REGION_LEVELS:
        raise ValueError(f"level deve ser um de: {', '.join(REGION_LEVELS)}")
    col = REGION_LEVELS[level]
    year = year or latest_year()
    df = _run(
        f"""
        SELECT year, {col} AS {level},
               SUM(cattle_deforestation_5_year_total_exposure) AS deforestation_exposure_ha,
               SUM(volume) AS volume_t,
               SUM(co2_net_emissions_cattle_deforestation_5_year_total_exposure) AS co2_net_tco2e
        FROM supply_chain
        WHERE year = ? AND {col} IS NOT NULL
        GROUP BY ALL
        ORDER BY deforestation_exposure_ha DESC NULLS LAST
        """,
        [year],
    )
    rm.add_position(df, level, "deforestation_exposure_ha")  # antes dos filtros: posição no ranking completo
    names = df[level].astype(str).str.upper()
    if region:
        df = df[names == str(_uf(region) if level == "state" else region).upper()].reset_index(drop=True)
    elif not include_unknown:
        df = df[~names.str.startswith("UNKNOWN")].reset_index(drop=True)
    label = {"biome": "bioma de produção", "state": "UF de produção"}[level]
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.FLOWS, ano=year, agrupado_por=label,
        ordenado_por="deforestation_exposure_ha (maior primeiro), todas as regiões",
        filtros={"region": region},
        excluidos=[] if include_unknown else ["origem desconhecida (UNKNOWN)"],
        unidades=_units("deforestation_exposure_ha", "volume_t", "co2_net_tco2e"),
        notas=["a linha UNKNOWN (ou UNKNOWN STATE) é a origem não rastreada: não é uma região e não pode ser "
               "atribuída a nenhuma delas; ela concentra a maior parte da exposição",
               "soma dos fluxos da cadeia, não o desmatamento total da região (para isso, territorial_metric)",
               rm.POSITION_NOTE.format(col="deforestation_exposure_ha"), rm.WINDOW_5Y])


def exposure_intensity_by_municipality(limit: int = 10, biome: str | None = None,
                                       year: int | None = None, min_volume_t: float = 100.0):
    """Exposição por tonelada (ha/t) por município, ignorando municípios com pouco volume."""
    year = year or latest_year()
    where, params = _filters(year, biome)
    where.append("volume_t >= ?")
    params.append(min_volume_t)
    df = _run(
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
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.FLOWS, ano=year, agrupado_por="município de produção",
        ordenado_por=f"exposure_ha_per_t (maior primeiro), {limit} primeiras linhas",
        filtros={"biome": biome, "volume mínimo (t)": min_volume_t},
        excluidos=["município de origem desconhecido (UNKNOWN)"],
        unidades=_units("exposure_ha_per_t", "deforestation_exposure_ha", "volume_t"),
        notas=[rm.RANKING_NOTE, rm.WINDOW_5Y])


def commitment_summary(year: int | None = None, include_domestic: bool = False):
    """Volume e exposição por tipo de compromisso de desmatamento zero do exportador."""
    year = year or latest_year()
    where, params = ["year = ?"], [year]
    if not include_domestic:
        where.append("exporter <> ?")
        params.append(DOMESTIC_EXPORTER)
    df = _run(
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
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.FLOWS, ano=year,
        agrupado_por="tipo de compromisso de desmatamento zero do exportador", ordenado_por="volume_t (maior primeiro)",
        excluidos=[] if include_domestic else [f"consumo interno ({DOMESTIC_EXPORTER})"],
        unidades={"volume_t": "t", "volume_share_pct": "% do volume das linhas mostradas (0-100)",
                  **_units("deforestation_exposure_ha")},
        notas=[rm.WINDOW_5Y])


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
    df = _run(
        f"""
        SELECT year, level, region, parent_region, metric, value, unit
        FROM spatial_metrics
        WHERE {" AND ".join(where)}
        ORDER BY value {"ASC" if ascending else "DESC"} NULLS LAST
        LIMIT ?
        """,
        params + [limit],
    )
    unit, desc, additive = next((u, d, a) for m, u, d, a in METRICS.values() if m == metric)
    return rm.attach(
        df, cadeia=BEEF, escopo=rm.TERRITORIAL, ano=int(df["year"].iloc[0]) if len(df) else year,
        agrupado_por=f"região (nível {level})",
        ordenado_por=f"value ({'menor' if ascending else 'maior'} primeiro), {limit} primeiras linhas",
        filtros={"metric": metric, "region": region, "parent_region": parent_region},
        unidades={"value": f"{unit} ({desc})"},
        notas=[] if additive else ["esta métrica não pode ser somada nem ter média simples entre regiões"])


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

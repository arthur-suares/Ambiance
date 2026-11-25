"""Camada de consulta ao ecossistema consolidado no PostgreSQL + PostGIS.

Todas as leituras analíticas usam transação READ ONLY com role agro_ro e
statement_timeout, garantindo isolamento total mesmo para SQL gerado pela IA.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.config import PG_CONNECT_TIMEOUT, PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER, PROJECT_ROOT

GEOJSON_PATH = PROJECT_ROOT / "data" / "raw" / "onda2" / "ibge_malha_municipios_br.geojson"
PLACES_PATH = PROJECT_ROOT / "web" / "data" / "trase_network_places.json"

CHOROPLETH_METRICS: dict[str, dict[str, str]] = {
    "trase_bovinos_exposicao_5a_ha": {
        "label": "Exposição ao desmatamento — Bovinos (Trase, 5a)",
        "unit": "ha",
        "source": "Trase Bovinos v2.2.2",
        "product": "bovinos",
        "palette": "reds",
        "caveat": "Janela de 5 anos (não somar entre anos). Exposição territorial não comprova ilegalidade.",
    },
    "trase_soja_exposicao_5a_ha": {
        "label": "Exposição ao desmatamento — Soja (Trase, 5a)",
        "unit": "ha",
        "source": "Trase Soja v2.6.1",
        "product": "soja",
        "palette": "oranges",
        "caveat": "Janela de 5 anos (não somar entre anos). Exposição territorial não comprova ilegalidade.",
    },
    "mapbiomas_desmatamento_ha": {
        "label": "Desmatamento anual (MapBiomas Col. 11)",
        "unit": "ha",
        "source": "MapBiomas Coleção 11",
        "product": "",
        "palette": "reds",
        "caveat": "Supressão anual de vegetação nativa no município; não distingue legalidade sem cruzar CAR/ASV.",
    },
    "inpe_deter_area_km2": {
        "label": "Área dos alertas por satélite (INPE)",
        "unit": "km²",
        "source": "INPE TerraBrasilis DETER",
        "product": "",
        "palette": "purples",
        "caveat": "Soma das áreas dos registros de alerta do DETER. A taxa oficial anual de desmatamento vem do PRODES.",
    },
    "ibge_bovinos_rebanho_cab": {
        "label": "Rebanho bovino (IBGE PPM)",
        "unit": "cabeças",
        "source": "IBGE PPM (SIDRA 3939)",
        "product": "",
        "palette": "greens",
        "caveat": "Efetivo anual do rebanho; não representa abate nem volume exportado.",
    },
    "ibge_soja_producao_t": {
        "label": "Produção de soja (IBGE PAM)",
        "unit": "t",
        "source": "IBGE PAM (SIDRA 5457)",
        "product": "",
        "palette": "greens",
        "caveat": "Produção municipal anual informada pelo IBGE.",
    },
    "trase_soja_volume_t": {
        "label": "Volume comercializado — Soja (Trase)",
        "unit": "t",
        "source": "Trase Soja v2.6.1",
        "product": "soja",
        "palette": "blues",
        "caveat": "Cobre apenas a parcela com município produtor rastreado.",
    },
    "trase_bovinos_volume_t": {
        "label": "Volume comercializado — Bovinos (Trase)",
        "unit": "t",
        "source": "Trase Bovinos v2.2.2",
        "product": "bovinos",
        "palette": "blues",
        "caveat": "Cobre apenas a parcela com município produtor rastreado.",
    },
    "seeg_emissao_agro_tco2e": {
        "label": "Emissões Agropecuária (SEEG Col. 14)",
        "unit": "tCO2e",
        "source": "SEEG Coleção 14 (GWP-AR5)",
        "product": "",
        "palette": "oranges",
        "caveat": "Estimativa municipal de emissões agropecuárias (fermentação entérica, solos, dejetos) em tCO2e GWP-AR5.",
    },
    "seeg_emissao_mut_tco2e": {
        "label": "Emissões Mudança de Uso da Terra (SEEG Col. 14)",
        "unit": "tCO2e",
        "source": "SEEG Coleção 14 (GWP-AR5)",
        "product": "",
        "palette": "reds",
        "caveat": "Emissões brutas de Mudança de Uso da Terra e Floresta em tCO2e GWP-AR5.",
    },
    "comex_soja_t": {
        "label": "Exportação oficial — Soja (Comex Stat)",
        "unit": "t",
        "source": "MDIC Comex Stat (SH4 1201/2304/1507)",
        "product": "",
        "palette": "blues",
        "caveat": "Município de domicílio fiscal do exportador (pode diferir do município produtor rural).",
    },
    "comex_bovinos_t": {
        "label": "Exportação oficial — Bovinos (Comex Stat)",
        "unit": "t",
        "source": "MDIC Comex Stat (SH4 0201/0202/1602/0102)",
        "product": "",
        "palette": "blues",
        "caveat": "Município de domicílio fiscal do exportador (pode diferir do município de criação).",
    },
}

MAPBIOMAS_CLASSES: dict[int, dict[str, Any]] = {
    0: {"label": "Sem observação", "group": "Sem observação", "color": "#64748b", "rgb": [100, 116, 139]},
    3: {"label": "Formação Florestal", "group": "Floresta", "color": "#1f8d49", "rgb": [31, 141, 73]},
    4: {"label": "Formação Savânica", "group": "Floresta", "color": "#7dc975", "rgb": [125, 201, 117]},
    5: {"label": "Mangue", "group": "Floresta", "color": "#04381d", "rgb": [4, 56, 29]},
    6: {"label": "Floresta Alagável", "group": "Floresta", "color": "#026975", "rgb": [2, 105, 117]},
    7: {"label": "Savana Alagada (beta)", "group": "Floresta", "color": "#228c70", "rgb": [34, 140, 112]},
    49: {"label": "Restinga Arbórea", "group": "Floresta", "color": "#02d659", "rgb": [2, 214, 89]},
    11: {"label": "Campo Alagado", "group": "Vegetação Herbácea", "color": "#519799", "rgb": [81, 151, 153]},
    12: {"label": "Formação Campestre", "group": "Vegetação Herbácea", "color": "#d6bc74", "rgb": [214, 188, 116]},
    13: {"label": "Mosaico Herbáceo-Arbustivo", "group": "Vegetação Herbácea", "color": "#d89f5c", "rgb": [216, 159, 92]},
    29: {"label": "Afloramento Rochoso", "group": "Vegetação Herbácea", "color": "#ffaa5f", "rgb": [255, 170, 95]},
    32: {"label": "Apicum", "group": "Vegetação Herbácea", "color": "#fc8114", "rgb": [252, 129, 20]},
    50: {"label": "Restinga Herbácea", "group": "Vegetação Herbácea", "color": "#ad5100", "rgb": [173, 81, 0]},
    84: {"label": "Marisma (beta)", "group": "Vegetação Herbácea", "color": "#81dbbf", "rgb": [129, 219, 191]},
    15: {"label": "Pastagem", "group": "Agropecuária", "color": "#edde8e", "rgb": [237, 222, 142]},
    39: {"label": "Soja", "group": "Agropecuária", "color": "#f5b3c8", "rgb": [245, 179, 200]},
    20: {"label": "Cana-de-açúcar", "group": "Agropecuária", "color": "#db7093", "rgb": [219, 112, 147]},
    40: {"label": "Arroz", "group": "Agropecuária", "color": "#c71585", "rgb": [199, 21, 133]},
    62: {"label": "Algodão (beta)", "group": "Agropecuária", "color": "#ff69b4", "rgb": [255, 105, 180]},
    41: {"label": "Outras Lavouras Temp.", "group": "Agropecuária", "color": "#f54ca9", "rgb": [245, 76, 169]},
    46: {"label": "Café", "group": "Agropecuária", "color": "#d68fe2", "rgb": [214, 143, 226]},
    47: {"label": "Citrus", "group": "Agropecuária", "color": "#9932cc", "rgb": [153, 50, 204]},
    35: {"label": "Dendê", "group": "Agropecuária", "color": "#9065d0", "rgb": [144, 101, 208]},
    48: {"label": "Outras Perenes", "group": "Agropecuária", "color": "#e6ccff", "rgb": [230, 204, 255]},
    9: {"label": "Silvicultura", "group": "Agropecuária", "color": "#7a5900", "rgb": [122, 89, 0]},
    21: {"label": "Mosaico de Usos", "group": "Agropecuária", "color": "#ffefc3", "rgb": [255, 239, 195]},
    23: {"label": "Praia, Duna e Areal", "group": "Não Vegetada", "color": "#ffa07a", "rgb": [255, 160, 122]},
    24: {"label": "Área Urbana", "group": "Não Vegetada", "color": "#d4271e", "rgb": [212, 39, 30]},
    25: {"label": "Outras Áreas Não Vegetadas", "group": "Não Vegetada", "color": "#db4d4f", "rgb": [219, 77, 79]},
    30: {"label": "Mineração", "group": "Não Vegetada", "color": "#9c0027", "rgb": [156, 0, 39]},
    75: {"label": "Usina Fotovoltaica", "group": "Não Vegetada", "color": "#757272", "rgb": [117, 114, 114]},
    91: {"label": "Parque Eólico", "group": "Não Vegetada", "color": "#403d3e", "rgb": [64, 61, 62]},
    31: {"label": "Aquicultura", "group": "Água", "color": "#091077", "rgb": [9, 16, 119]},
    33: {"label": "Rio, Lago e Oceano", "group": "Água", "color": "#2532e4", "rgb": [37, 50, 228]},
}


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: _to_jsonable(v) for k, v in r.items()} for r in rows]


@contextmanager
def readonly_conn(timeout_ms: int = 15000):
    con = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE,
        connect_timeout=PG_CONNECT_TIMEOUT,
        row_factory=dict_row,
    )
    try:
        with con.cursor() as cur:
            cur.execute("BEGIN TRANSACTION READ ONLY")
            cur.execute("SET LOCAL ROLE agro_ro")
            cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        yield con
    finally:
        try:
            con.rollback()
        except Exception:
            pass
        con.close()


def agro_available() -> bool:
    try:
        with readonly_conn(timeout_ms=3000) as con:
            with con.cursor() as cur:
                cur.execute("SELECT 1 FROM gold.mv_territorio_municipal_ano LIMIT 1")
                return cur.fetchone() is not None
    except Exception:
        return False


def get_meta() -> dict[str, Any]:
    with readonly_conn() as con:
        with con.cursor() as cur:
            cur.execute("SELECT DISTINCT uf FROM agro.dim_municipios ORDER BY uf")
            ufs = [r["uf"] for r in cur.fetchall()]

            cur.execute(
                "SELECT DISTINCT uf, bioma_predominante AS bioma FROM agro.dim_municipios "
                "WHERE bioma_predominante IS NOT NULL ORDER BY 2"
            )
            territorial_biomes = cur.fetchall()
            biomes = sorted({row["bioma"] for row in territorial_biomes})

            cur.execute("SELECT DISTINCT ano FROM gold.mv_territorio_municipal_ano WHERE ano >= 2000 ORDER BY ano")
            years = [int(r["ano"]) for r in cur.fetchall()]

            available = ", ".join(f'BOOL_OR("{key}" > 0) AS "{key}"' for key in CHOROPLETH_METRICS)
            cur.execute(f"SELECT ano, {available} FROM gold.mv_territorio_municipal_ano GROUP BY ano ORDER BY ano")
            metric_years = {key: [] for key in CHOROPLETH_METRICS}
            for row in cur:
                for key, periods in metric_years.items():
                    if row[key]:
                        periods.append(row["ano"])

            cur.execute(f"SELECT uf, {available} FROM gold.mv_territorio_municipal_ano GROUP BY uf ORDER BY uf")
            metric_ufs = {key: [] for key in CHOROPLETH_METRICS}
            for row in cur:
                for key, states_list in metric_ufs.items():
                    if row[key]:
                        states_list.append(row["uf"])

            cur.execute(
                f"SELECT bioma_predominante AS bioma, {available} FROM gold.mv_territorio_municipal_ano "
                "WHERE bioma_predominante IS NOT NULL GROUP BY bioma_predominante ORDER BY bioma_predominante"
            )
            metric_biomes = {key: [] for key in CHOROPLETH_METRICS}
            for row in cur:
                for key, biomes_list in metric_biomes.items():
                    if row[key]:
                        biomes_list.append(row["bioma"])

            cur.execute("SELECT produto, array_agg(DISTINCT ano ORDER BY ano) AS years FROM gold.mv_rede_fluxos GROUP BY produto")
            flow_years = {row["produto"]: row["years"] for row in cur}

            coords = _country_coords()
            cur.execute(
                """
                SELECT DISTINCT f.produto, m.uf, upper(f.pais_destino_trase_id) AS cid
                FROM gold.mv_rede_fluxos f
                JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = f.codigo_municipio_ibge
                WHERE f.pais_destino_trase_id IS NOT NULL
                  AND f.pais_destino_trase_id NOT IN ('BR', 'XX', '')
                  AND m.lon IS NOT NULL AND m.lat IS NOT NULL
                """
            )
            flow_ufs_sets: dict[str, set[str]] = {}
            flow_country_sets: dict[str, dict[str, str]] = {}
            for row in cur:
                prod = row["produto"]
                if row["uf"]:
                    flow_ufs_sets.setdefault(prod, set()).add(row["uf"])
                cid = row["cid"]
                if cid in coords:
                    flow_country_sets.setdefault(prod, {})[cid] = coords[cid][0]
            flow_ufs = {prod: sorted(vals) for prod, vals in flow_ufs_sets.items()}
            flow_countries_by_product = {
                prod: dict(sorted(cdict.items(), key=lambda kv: kv[1]))
                for prod, cdict in flow_country_sets.items()
            }
            flow_countries = dict(
                sorted(
                    {cid: cname for cdict in flow_countries_by_product.values() for cid, cname in cdict.items()}.items(),
                    key=lambda kv: kv[1],
                )
            )

            cur.execute("SELECT DISTINCT ano, uf, bioma FROM agro.fato_inpe_deter WHERE lat IS NOT NULL AND lon IS NOT NULL")
            alerts = cur.fetchall()

            cur.execute(
                "SELECT DISTINCT cadeia, uf FROM agro.dim_instalacoes "
                "WHERE lat IS NOT NULL AND lon IS NOT NULL AND uf IS NOT NULL ORDER BY uf"
            )
            facility_ufs_sets: dict[str, set[str]] = {"all": set(), "soja": set(), "bovinos": set()}
            for row in cur:
                uf_val = row["uf"]
                facility_ufs_sets["all"].add(uf_val)
                if row["cadeia"] in facility_ufs_sets:
                    facility_ufs_sets[row["cadeia"]].add(uf_val)
            facility_ufs = {k: sorted(v) for k, v in facility_ufs_sets.items()}

            cur.execute(
                "SELECT fonte_id, nome, orgao, categoria, url, versao, ano_inicio, ano_fim, limitacoes, registros "
                "FROM agro.dim_fontes WHERE registros > 0 ORDER BY registros DESC"
            )
            sources = _clean_rows(cur.fetchall())

    return {
        "metrics": CHOROPLETH_METRICS,
        "ufs": ufs,
        "biomes": biomes,
        "biomes_by_uf": {uf: [row["bioma"] for row in territorial_biomes if row["uf"] == uf] for uf in ufs},
        "alert_biomes": {
            uf: sorted({row["bioma"] for row in alerts if row["bioma"] and (not uf or row["uf"] == uf)})
            for uf in ["", *ufs]
        },
        "alert_triples": [[row["ano"], row["uf"] or "", row["bioma"] or ""] for row in alerts if row["ano"] is not None],
        "metric_years": metric_years,
        "metric_ufs": metric_ufs,
        "metric_biomes": metric_biomes,
        "flow_years": flow_years,
        "flow_ufs": flow_ufs,
        "flow_countries_by_product": flow_countries_by_product,
        "alert_years": sorted({row["ano"] for row in alerts if row["ano"] is not None}),
        "flow_countries": flow_countries,
        "facility_ufs": facility_ufs,
        "years": years,
        "default_year": 2022,
        "sources": sources,
    }


@lru_cache(maxsize=1)
def get_states_geojson() -> dict[str, Any]:
    with readonly_conn() as con, con.cursor() as cur:
        cur.execute("""
            SELECT uf, MIN(uf_nome) AS name, MIN(LEFT(codigo_municipio_ibge, 2)) AS prefix,
                   ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_Union(geom), 0.007))::json AS geometry
            FROM agro.dim_municipios
            WHERE geom IS NOT NULL
            GROUP BY uf
            ORDER BY uf
        """)
        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "geometry": row["geometry"],
                "properties": {"uf": row["uf"], "name": row["name"], "prefix": row["prefix"]},
            } for row in cur.fetchall()],
        }


def get_choropleth(
    metric: str = "trase_bovinos_exposicao_5a_ha",
    year: int = 2022,
    uf: str | None = None,
    bioma: str | None = None,
    codes: list[str] | None = None,
    grain: str = "municipality",
    strict_year: bool = False,
) -> dict[str, Any]:
    if metric not in CHOROPLETH_METRICS:
        raise ValueError(f"Métrica desconhecida: {metric}")
    meta = CHOROPLETH_METRICS[metric]
    by_state = grain == "state"
    req_year = int(year)
    base_clauses = [f'"{metric}" IS NOT NULL', f'"{metric}" > 0']
    base_params: list[Any] = []
    if uf:
        base_clauses.append("uf = %s")
        base_params.append(uf.upper()[:2])
    if bioma:
        base_clauses.append("unaccent(lower(bioma_predominante)) = unaccent(lower(%s))")
        base_params.append(bioma)
    if codes:
        base_clauses.append("codigo_municipio_ibge = ANY(%s)")
        base_params.append(list(codes))

    base_where = " AND ".join(base_clauses)

    def fetch_rows(cur, target_year: int) -> list[dict[str, Any]]:
        if by_state:
            cur.execute(
                f"""
                SELECT t.uf AS code, MIN(m.uf_nome) AS name, t.uf,
                       AVG(t.lat) AS lat, AVG(t.lon) AS lon,
                       SUM(t."{metric}")::double precision AS value
                FROM gold.mv_territorio_municipal_ano t
                JOIN (
                    SELECT uf AS state_code, MIN(uf_nome) AS uf_nome
                    FROM agro.dim_municipios GROUP BY uf
                ) m ON m.state_code = t.uf
                WHERE ano = %s AND {base_where}
                GROUP BY t.uf
                ORDER BY value DESC
                """,
                [target_year, *base_params],
            )
            return _clean_rows(cur.fetchall())
        cur.execute(
            f"""
            SELECT codigo_municipio_ibge AS code,
                   municipio AS name,
                   uf,
                   bioma_predominante AS bioma,
                   lat, lon,
                   "{metric}"::double precision AS value
            FROM gold.mv_territorio_municipal_ano
            WHERE ano = %s AND {base_where}
            ORDER BY value DESC
            """,
            [target_year, *base_params],
        )
        return _clean_rows(cur.fetchall())

    eff_year = req_year
    with readonly_conn() as con:
        with con.cursor() as cur:
            rows = fetch_rows(cur, eff_year)
            if not rows and not strict_year:
                cur.execute(
                    f"SELECT MAX(ano) AS max_ano FROM gold.mv_territorio_municipal_ano WHERE {base_where} AND ano <= %s",
                    [*base_params, req_year],
                )
                found = cur.fetchone()
                alt = found["max_ano"] if found else None
                if alt is None:
                    cur.execute(
                        f"SELECT MAX(ano) AS max_ano FROM gold.mv_territorio_municipal_ano WHERE {base_where}",
                        base_params,
                    )
                    found = cur.fetchone()
                    alt = found["max_ano"] if found else None
                if alt is not None and int(alt) != eff_year:
                    eff_year = int(alt)
                    rows = fetch_rows(cur, eff_year)

            coverage = None
            if meta["product"]:
                cur.execute(
                    """
                    SELECT
                        SUM(volume_rastreado_t) AS vol_rastreado_t,
                        SUM(volume_total_t) AS vol_total_t,
                        ROUND((100.0 * COALESCE(SUM(volume_rastreado_t), 0)
                               / NULLIF(SUM(volume_total_t), 0))::numeric, 1) AS pct_rastreado
                    FROM gold.mv_cobertura_incerteza
                    WHERE produto = %s AND ano = %s
                    """,
                    (meta["product"], eff_year),
                )
                cov = cur.fetchone()
                if cov and cov["vol_total_t"]:
                    coverage = {k: _to_jsonable(v) for k, v in cov.items()}

    values = [r["value"] for r in rows if r["value"] is not None]
    p95 = sorted(values)[int(len(values) * 0.95)] if values else 0.0
    vmax = max(values) if values else 0.0
    total = sum(values) if values else 0.0

    # Bounding box dos municípios filtrados
    lons = [r["lon"] for r in rows if r["lon"] is not None]
    lats = [r["lat"] for r in rows if r["lat"] is not None]
    bbox = [min(lons), min(lats), max(lons), max(lats)] if lons and lats else None

    return {
        "metric": metric,
        "grain": "state" if by_state else "municipality",
        "meta": meta,
        "requested_year": req_year,
        "year": eff_year,
        "year_fallback": eff_year != req_year and len(rows) > 0,
        "uf": uf,
        "bioma": bioma,
        "count": len(rows),
        "total": round(total, 2),
        "max": round(vmax, 2),
        "p95": round(p95, 2),
        "bbox": bbox,
        "coverage": coverage,
        "values": {r["code"]: r["value"] for r in rows},
        "top": rows[:15],
    }


def _country_coords() -> dict[str, tuple[str, list[float]]]:
    if not PLACES_PATH.exists():
        return {}
    cat = json.loads(PLACES_PATH.read_text(encoding="utf-8"))
    return {k: (v[0], v[1]) for k, v in cat.get("countries", {}).items()}


def get_flows(
    product: str = "bovinos",
    year: int = 2022,
    uf: str | None = None,
    origin: str | None = None,
    country: str | None = None,
    limit: int = 180,
    grain: str = "municipality",
    strict_year: bool = False,
    bioma: str | None = None,
) -> dict[str, Any]:
    if product not in ("soja", "bovinos"):
        raise ValueError("Produto deve ser 'soja' ou 'bovinos'.")
    req_year = int(year)
    by_state = grain == "state" and not origin
    origin_fields = (
        "m.uf AS origin_code, MIN(m.uf_nome) AS origin_name, m.uf AS origin_uf,"
        " s.lon AS origin_lon, s.lat AS origin_lat"
        if by_state else
        "f.codigo_municipio_ibge AS origin_code, m.municipio AS origin_name, m.uf AS origin_uf,"
        " m.lon AS origin_lon, m.lat AS origin_lat"
    )
    origin_group = "m.uf, s.lon, s.lat" if by_state else "f.codigo_municipio_ibge, m.municipio, m.uf, m.lon, m.lat"
    state_join = """
        JOIN (SELECT uf, AVG(lon) AS lon, AVG(lat) AS lat FROM agro.dim_municipios GROUP BY uf) s ON s.uf = m.uf
    """ if by_state else ""
    base_clauses = [
        "f.produto = %s",
        "f.codigo_municipio_ibge IS NOT NULL",
        "f.pais_destino_trase_id IS NOT NULL",
        "f.pais_destino_trase_id NOT IN ('BR', 'XX', '')",
    ]
    base_params: list[Any] = [product]
    if uf:
        base_clauses.append("m.uf = %s")
        base_params.append(uf.upper()[:2])
    if origin:
        base_clauses.append("f.codigo_municipio_ibge = %s")
        base_params.append(origin)
    if country:
        base_clauses.append("(upper(f.pais_destino_trase_id) = upper(%s) OR upper(f.pais_destino) = upper(%s))")
        base_params.extend([country, country])

    countries = _country_coords()
    if strict_year:
        base_clauses.append("upper(f.pais_destino_trase_id) = ANY(%s)")
        base_params.append(list(countries))
    if bioma:
        base_clauses.append("unaccent(lower(m.bioma_predominante)) = unaccent(lower(%s))")
        base_params.append(bioma)
    base_where = " AND ".join(base_clauses)

    def fetch_flows(cur, target_year: int) -> list[dict[str, Any]]:
        cur.execute(
            f"""
            SELECT
                {origin_fields},
                f.pais_destino AS country_name,
                f.pais_destino_trase_id AS country_id,
                SUM(f.registros) AS registros,
                SUM(f.volume_t) AS volume_t,
                SUM(SUM(f.volume_t)) OVER () AS scope_total,
                SUM(f.valor_usd) AS valor_usd,
                SUM(f.exposicao_desmatamento_ha) AS exposicao_ha
            FROM gold.mv_rede_fluxos f
            JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = f.codigo_municipio_ibge
            {state_join}
            WHERE f.ano = %s AND {base_where}
              AND m.lon IS NOT NULL AND m.lat IS NOT NULL
            GROUP BY {origin_group}, f.pais_destino, f.pais_destino_trase_id
            ORDER BY SUM(f.volume_t) DESC NULLS LAST
            LIMIT %s
            """,
            [target_year, *base_params, int(limit)],
        )
        return _clean_rows(cur.fetchall())

    eff_year = req_year
    with readonly_conn() as con:
        with con.cursor() as cur:
            rows = fetch_flows(cur, eff_year)
            if not rows and not strict_year:
                cur.execute(
                    f"SELECT MAX(f.ano) AS max_ano FROM gold.mv_rede_fluxos f "
                    f"JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = f.codigo_municipio_ibge "
                    f"WHERE {base_where} AND f.ano <= %s",
                    [*base_params, req_year],
                )
                found = cur.fetchone()
                alt = found["max_ano"] if found else None
                if alt is None:
                    cur.execute(
                        f"SELECT MAX(f.ano) AS max_ano FROM gold.mv_rede_fluxos f "
                        f"JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = f.codigo_municipio_ibge "
                        f"WHERE {base_where}",
                        base_params,
                    )
                    found = cur.fetchone()
                    alt = found["max_ano"] if found else None
                if alt is not None and int(alt) != eff_year:
                    eff_year = int(alt)
                    rows = fetch_flows(cur, eff_year)

    arcs = []
    for r in rows:
        cid = (r["country_id"] or "").upper()
        if cid not in countries:
            continue
        cname, coords = countries[cid]
        arcs.append({
            "origin_code": r["origin_code"],
            "origin_uf": r["origin_uf"],
            "origin_name": f"{r['origin_name']} ({r['origin_uf']})",
            "target_id": cid,
            "target_name": cname,
            "source": [r["origin_lon"], r["origin_lat"]],
            "target": coords,
            "volume_t": round(r["volume_t"] or 0.0, 2),
            "exposicao_ha": round(r["exposicao_ha"] or 0.0, 2),
            "registros": int(r["registros"] or 0),
        })

    return {
        "product": product,
        "grain": "state" if by_state else "municipality",
        "requested_year": req_year,
        "year": eff_year,
        "year_fallback": eff_year != req_year and len(arcs) > 0,
        "count": len(arcs),
        "total": rows[0]["scope_total"] if rows else None,
        "arcs": arcs,
    }


def get_deter_alerts(
    year: int = 2026,
    bioma: str | None = None,
    uf: str | None = None,
    code: str | None = None,
    limit: int = 2500,
    strict_year: bool = False,
) -> dict[str, Any]:
    req_year = int(year)
    base_clauses = ["lat IS NOT NULL", "lon IS NOT NULL"]
    base_params: list[Any] = []
    if bioma:
        base_clauses.append("unaccent(upper(bioma)) = unaccent(upper(%s))")
        base_params.append(bioma)
    if uf:
        base_clauses.append("uf = %s")
        base_params.append(uf.upper()[:2])
    if code:
        base_clauses.append("codigo_municipio_ibge = %s")
        base_params.append(code)

    base_where = " AND ".join(base_clauses)

    def fetch_deter(cur, target_year: int):
        cur.execute(
            f"SELECT COUNT(*) AS total, COALESCE(SUM(area_mun_km2), 0) AS area_total_km2 "
            f"FROM agro.fato_inpe_deter WHERE ano = %s AND {base_where}",
            [target_year, *base_params],
        )
        summary = _clean_rows([cur.fetchone()])[0]
        if not int(summary["total"] or 0):
            return summary, []
        cur.execute(
            f"""
            SELECT bioma, view_date, classname, codigo_municipio_ibge AS code,
                   municipio, uf, ROUND(area_mun_km2::numeric, 3) AS area_km2, lat, lon
            FROM agro.fato_inpe_deter
            WHERE ano = %s AND {base_where}
            ORDER BY area_mun_km2 DESC NULLS LAST
            LIMIT %s
            """,
            [target_year, *base_params, int(limit)],
        )
        return summary, _clean_rows(cur.fetchall())

    eff_year = req_year
    with readonly_conn() as con:
        with con.cursor() as cur:
            summary, points = fetch_deter(cur, eff_year)
            if not int(summary["total"] or 0) and not strict_year:
                cur.execute(
                    f"SELECT MAX(ano) AS max_ano FROM agro.fato_inpe_deter WHERE {base_where} AND ano <= %s",
                    [*base_params, req_year],
                )
                found = cur.fetchone()
                alt = found["max_ano"] if found else None
                if alt is None:
                    cur.execute(
                        f"SELECT MAX(ano) AS max_ano FROM agro.fato_inpe_deter WHERE {base_where}",
                        base_params,
                    )
                    found = cur.fetchone()
                    alt = found["max_ano"] if found else None
                if alt is not None and int(alt) != eff_year:
                    eff_year = int(alt)
                    summary, points = fetch_deter(cur, eff_year)

    return {
        "requested_year": req_year,
        "year": eff_year,
        "year_fallback": eff_year != req_year and len(points) > 0,
        "total_alerts": int(summary["total"] or 0),
        "area_total_km2": round(float(summary["area_total_km2"] or 0), 2),
        "returned": len(points),
        "points": points,
    }


def search_municipalities(
    q: str,
    limit: int = 12,
    uf: str | None = None,
    bioma: str | None = None,
) -> list[dict[str, Any]]:
    term = (q or "").strip()
    if not term:
        return []
    extra_clauses = ["lat IS NOT NULL"]
    extra_params: list[Any] = []
    if uf:
        extra_clauses.append("uf = %s")
        extra_params.append(uf.upper()[:2])
    if bioma:
        extra_clauses.append("unaccent(lower(bioma_predominante)) = unaccent(lower(%s))")
        extra_params.append(bioma)
    extra_sql = " AND ".join(extra_clauses)
    with readonly_conn() as con:
        with con.cursor() as cur:
            if term.isdigit() and len(term) <= 7:
                cur.execute(
                    f"""
                    SELECT codigo_municipio_ibge AS code, municipio, uf,
                           bioma_predominante AS bioma, lat, lon
                    FROM agro.dim_municipios
                    WHERE codigo_municipio_ibge LIKE %s AND {extra_sql}
                    ORDER BY codigo_municipio_ibge
                    LIMIT %s
                    """,
                    (f"{term}%", *extra_params, int(limit)),
                )
            else:
                cur.execute(
                    f"""
                    SELECT codigo_municipio_ibge AS code, municipio, uf,
                           bioma_predominante AS bioma, lat, lon
                    FROM agro.dim_municipios
                    WHERE unaccent(lower(municipio)) LIKE unaccent(lower(%s))
                      AND {extra_sql}
                    ORDER BY
                        CASE WHEN unaccent(lower(municipio)) LIKE unaccent(lower(%s)) THEN 0 ELSE 1 END,
                        municipio
                    LIMIT %s
                    """,
                    (f"%{term}%", *extra_params, f"{term}%", int(limit)),
                )
            return _clean_rows(cur.fetchall())


def get_municipality_profile(code: str, year: int | None = 2022, strict_year: bool = False) -> dict[str, Any]:
    with readonly_conn() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT codigo_municipio_ibge AS code, municipio, uf, uf_nome, regiao,
                       bioma_predominante AS bioma, lat, lon, area_km2
                FROM agro.dim_municipios
                WHERE codigo_municipio_ibge = %s
                """,
                (code,),
            )
            mun = cur.fetchone()
            if not mun:
                raise KeyError(f"Município {code} não encontrado.")
            if year is None:
                return {"municipality": _clean_rows([mun])[0]}

            req_year = int(year)
            eff_year = req_year
            cur.execute(
                """
                SELECT *
                FROM gold.mv_territorio_municipal_ano
                WHERE codigo_municipio_ibge = %s AND ano = %s
                """,
                (code, eff_year),
            )
            snap = cur.fetchone()
            if not snap and not strict_year:
                cur.execute(
                    """
                    SELECT *
                    FROM gold.mv_territorio_municipal_ano
                    WHERE codigo_municipio_ibge = %s AND ano <= %s
                    ORDER BY ano DESC LIMIT 1
                    """,
                    (code, req_year),
                )
                snap = cur.fetchone()
                if not snap:
                    cur.execute(
                        """
                        SELECT *
                        FROM gold.mv_territorio_municipal_ano
                        WHERE codigo_municipio_ibge = %s
                        ORDER BY ano DESC LIMIT 1
                        """,
                        (code,),
                    )
                    snap = cur.fetchone()
                if snap:
                    eff_year = int(snap["ano"])

            cur.execute(
                """
                SELECT ano,
                       ibge_soja_producao_t,
                       ibge_bovinos_rebanho_cab,
                       mapbiomas_desmatamento_ha,
                       trase_bovinos_exposicao_5a_ha,
                       trase_soja_exposicao_5a_ha,
                       inpe_deter_area_km2,
                       seeg_emissao_agro_tco2e,
                       seeg_emissao_mut_tco2e,
                       trase_soja_volume_t,
                       trase_bovinos_volume_t,
                       comex_soja_t,
                       comex_bovinos_t,
                       inst_bovinos_total,
                       inst_soja_total
                FROM gold.mv_territorio_municipal_ano
                WHERE codigo_municipio_ibge = %s AND ano >= 2015
                ORDER BY ano
                """,
                (code,),
            )
            series = _clean_rows(cur.fetchall())

            cur.execute(
                """
                SELECT ano, COUNT(*) AS alertas, ROUND(SUM(area_mun_km2)::numeric, 2) AS area_km2
                FROM agro.fato_inpe_deter
                WHERE codigo_municipio_ibge = %s AND ano >= 2023
                GROUP BY ano ORDER BY ano DESC
                """,
                (code,),
            )
            deter_recent = _clean_rows(cur.fetchall())

    return {
        "municipality": _clean_rows([mun])[0],
        "requested_year": req_year,
        "year": eff_year,
        "effective_year": eff_year,
        "snapshot": _clean_rows([snap])[0] if snap else {},
        "series": series,
        "deter_recent": deter_recent,
    }


def get_facilities(
    chain: str = "bovinos",
    uf: str | None = None,
    limit: int = 3000,
    grain: str = "municipality",
    bioma: str | None = None,
) -> dict[str, Any]:
    if chain not in ("bovinos", "soja", "all"):
        raise ValueError("Cadeia deve ser 'bovinos', 'soja' ou 'all'.")
    clauses = ["lat IS NOT NULL", "lon IS NOT NULL"]
    params: list[Any] = []
    if chain != "all":
        clauses.append("cadeia = %s")
        params.append(chain)
    if uf:
        clauses.append("uf = %s")
        params.append(uf.upper()[:2])
    if bioma:
        clauses.append(
            "codigo_municipio_ibge IN (SELECT codigo_municipio_ibge FROM agro.dim_municipios "
            "WHERE unaccent(lower(bioma_predominante)) = unaccent(lower(%s)))"
        )
        params.append(bioma)

    where_sql = " AND ".join(clauses)
    with readonly_conn() as con:
        with con.cursor() as cur:
            if grain == "state":
                cur.execute(f"""
                    WITH inventory AS (
                        SELECT uf, cadeia, COUNT(*) AS total
                        FROM agro.dim_instalacoes WHERE {where_sql} GROUP BY uf, cadeia
                    ), states AS (
                        SELECT uf, MIN(uf_nome) AS name, AVG(lon) AS lon, AVG(lat) AS lat
                        FROM agro.dim_municipios GROUP BY uf
                    )
                    SELECT inventory.*, states.name AS uf_name,
                           states.lon + CASE WHEN cadeia = 'soja' THEN 0.25 ELSE -0.25 END AS lon,
                           states.lat + 0.22 AS lat
                    FROM inventory JOIN states USING (uf)
                    WHERE states.lon IS NOT NULL AND states.lat IS NOT NULL
                    ORDER BY total DESC
                    """, params)
                points = _clean_rows(cur.fetchall())
                return {"chain": chain, "grain": "state", "total": sum(p["total"] for p in points),
                        "returned": len(points), "points": points}
            cur.execute(
                f"""
                SELECT cadeia, empresa, tipo, nivel_inspecao, numero_inspecao,
                       status, capacidade_valor, capacidade_unidade,
                       codigo_municipio_ibge AS code, municipio, uf, lat, lon
                FROM agro.dim_instalacoes
                WHERE {where_sql}
                ORDER BY capacidade_valor DESC NULLS LAST
                LIMIT %s
                """,
                [*params, int(limit)],
            )
            points = _clean_rows(cur.fetchall())
            cur.execute(f"SELECT COUNT(*) AS total FROM agro.dim_instalacoes WHERE {where_sql}", params)
            total = int(cur.fetchone()["total"] or 0)
    return {"chain": chain, "total": total, "returned": len(points), "points": points}


def run_readonly_sql(sql: str, max_rows: int = 100) -> tuple[list[str], list[dict[str, Any]]]:
    cleaned = sql.strip().rstrip(";")
    if not cleaned.lower().startswith(("select", "with")):
        raise ValueError("Apenas consultas SELECT/WITH são permitidas.")
    with readonly_conn(timeout_ms=15000) as con:
        with con.cursor() as cur:
            cur.execute(f"SELECT * FROM ({cleaned}) AS _q LIMIT {int(max_rows)}")
            rows = _clean_rows(cur.fetchall())
            cols = [d.name for d in cur.description] if cur.description else []
            return cols, rows


def get_mapbiomas_coverage(
    year: int = 2025,
    class_ids: list[int] | None = None,
    uf: str | None = None,
    bioma: str | None = None,
    mode: str = "dominant",
    include_series: bool = True,
) -> dict[str, Any]:
    """Agrega cobertura e uso da terra do MapBiomas (1985-2025) por município."""
    req_year = max(1985, min(2025, int(year)))
    if mode not in ("dominant", "share"):
        mode = "dominant"

    valid_cids = [int(c) for c in (class_ids or []) if int(c) in MAPBIOMAS_CLASSES]
    mun_clauses = ["m.lat IS NOT NULL", "m.lon IS NOT NULL"]
    mun_params: list[Any] = []
    if uf:
        mun_clauses.append("m.uf = %s")
        mun_params.append(uf.upper()[:2])
    if bioma:
        mun_clauses.append("unaccent(lower(m.bioma_predominante)) = unaccent(lower(%s))")
        mun_params.append(bioma)
    mun_where = " AND ".join(mun_clauses)

    class_clause = "AND c.classe_id = ANY(%s)" if valid_cids else ""
    year_params: list[Any] = [req_year, *mun_params]
    if valid_cids:
        year_params.append(valid_cids)

    with readonly_conn(timeout_ms=15000) as con:
        with con.cursor() as cur:
            cur.execute(
                f"""
                WITH mun_cls AS (
                    SELECT
                        c.codigo_municipio_ibge AS code,
                        m.municipio,
                        m.uf,
                        m.lon,
                        m.lat,
                        m.area_km2,
                        c.classe_id,
                        SUM(c.area_ha) AS area_ha
                    FROM agro.fato_mapbiomas_cobertura c
                    JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = c.codigo_municipio_ibge
                    WHERE c.ano = %s AND {mun_where} {class_clause}
                    GROUP BY c.codigo_municipio_ibge, m.municipio, m.uf, m.lon, m.lat, m.area_km2, c.classe_id
                ),
                ranked AS (
                    SELECT
                        code, municipio, uf, lon, lat, area_km2, classe_id, area_ha,
                        SUM(area_ha) OVER (PARTITION BY code) AS selected_ha,
                        ROW_NUMBER() OVER (PARTITION BY code ORDER BY area_ha DESC, classe_id) AS rn
                    FROM mun_cls
                )
                SELECT
                    code, municipio, uf, lon, lat,
                    classe_id AS dominant_id,
                    ROUND(area_ha::numeric, 1) AS dominant_ha,
                    ROUND(selected_ha::numeric, 1) AS selected_ha,
                    ROUND((100.0 * area_ha / NULLIF(area_km2 * 100.0, 0))::numeric, 2) AS dominant_pct,
                    ROUND((100.0 * selected_ha / NULLIF(area_km2 * 100.0, 0))::numeric, 2) AS selected_pct
                FROM ranked
                WHERE rn = 1
                """,
                year_params,
            )
            mun_rows = _clean_rows(cur.fetchall())

            # Resumo de todas as classes no recorte territorial (para toggles da legenda)
            cur.execute(
                f"""
                SELECT c.classe_id, ROUND(SUM(c.area_ha)::numeric, 1) AS area_ha
                FROM agro.fato_mapbiomas_cobertura c
                JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = c.codigo_municipio_ibge
                WHERE c.ano = %s AND {mun_where}
                GROUP BY c.classe_id
                ORDER BY area_ha DESC
                """,
                [req_year, *mun_params],
            )
            raw_summary = _clean_rows(cur.fetchall())

            series: list[dict[str, Any]] = []
            if include_series:
                cur.execute(
                    f"""
                    SELECT
                        c.ano,
                        ROUND(SUM(c.area_ha)::numeric, 1) AS area_selecionada_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (3,4,5,6,7,49)), 0)::numeric, 0) AS floresta_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id = 15), 0)::numeric, 0) AS pastagem_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (39,20,40,41,46,47,48,35,62)), 0)::numeric, 0) AS agricultura_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (9,21)), 0)::numeric, 0) AS mosaico_silv_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (11,12,13,29,32,50,84)), 0)::numeric, 0) AS herbacea_alagada_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (23,24,25,30,31,33,75,91)), 0)::numeric, 0) AS outros_agua_ha
                    FROM agro.fato_mapbiomas_cobertura c
                    JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = c.codigo_municipio_ibge
                    WHERE {mun_where} {class_clause}
                    GROUP BY c.ano
                    ORDER BY c.ano
                    """,
                    [*mun_params, *([valid_cids] if valid_cids else [])],
                )
                series = _clean_rows(cur.fetchall())

    total_area_all = sum(float(r["area_ha"] or 0) for r in raw_summary) or 1.0
    summary = []
    for r in raw_summary:
        cid = int(r["classe_id"])
        meta = MAPBIOMAS_CLASSES.get(cid)
        if not meta:
            continue
        area = float(r["area_ha"] or 0)
        summary.append({
            "classe_id": cid,
            "label": meta["label"],
            "group": meta["group"],
            "color": meta["color"],
            "rgb": meta["rgb"],
            "area_ha": area,
            "pct": round(100.0 * area / total_area_all, 2),
        })

    values: dict[str, dict[str, Any]] = {}
    pcts: list[float] = []
    lons: list[float] = []
    lats: list[float] = []
    for r in mun_rows:
        code = str(r["code"])
        sel_pct = min(100.0, float(r["selected_pct"] or 0))
        dom_pct = min(100.0, float(r["dominant_pct"] or 0))
        values[code] = {
            "name": r["municipio"],
            "uf": r["uf"],
            "dom": int(r["dominant_id"]),
            "dom_ha": float(r["dominant_ha"] or 0),
            "dom_pct": dom_pct,
            "sel_ha": float(r["selected_ha"] or 0),
            "sel_pct": sel_pct,
        }
        pcts.append(sel_pct)
        if r["lon"] is not None and r["lat"] is not None:
            lons.append(float(r["lon"]))
            lats.append(float(r["lat"]))

    max_pct = round(max(pcts), 1) if pcts else 100.0
    bbox = [min(lons), min(lats), max(lons), max(lats)] if lons and lats else None

    return {
        "year": req_year,
        "mode": mode,
        "uf": uf,
        "bioma": bioma,
        "class_ids": valid_cids,
        "classes_meta": {str(k): v for k, v in MAPBIOMAS_CLASSES.items()},
        "count": len(values),
        "max_pct": max_pct,
        "bbox": bbox,
        "values": values,
        "summary": summary,
        "series": series,
    }

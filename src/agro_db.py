"""Camada de consulta ao ecossistema consolidado no PostgreSQL + PostGIS.

Todas as leituras analíticas usam transação READ ONLY com role agro_ro e
statement_timeout, garantindo isolamento total mesmo para SQL gerado pela IA.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import json
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
        "label": "Alertas DETER — Área (INPE)",
        "unit": "km²",
        "source": "INPE TerraBrasilis DETER",
        "product": "",
        "palette": "purples",
        "caveat": "Sistema de alertas rápidos para fiscalização; não substitui a taxa oficial consolidada do PRODES.",
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
    3: {"label": "Formação Florestal", "group": "Floresta", "color": "#1f8d49", "rgb": [31, 141, 73]},
    4: {"label": "Formação Savânica", "group": "Floresta", "color": "#7dc975", "rgb": [125, 201, 117]},
    5: {"label": "Mangue", "group": "Floresta", "color": "#04381d", "rgb": [4, 56, 29]},
    6: {"label": "Floresta Alagável", "group": "Floresta", "color": "#026975", "rgb": [2, 105, 117]},
    49: {"label": "Restinga Arbórea", "group": "Floresta", "color": "#02d659", "rgb": [2, 214, 89]},
    11: {"label": "Campo Alagado", "group": "Vegetação Herbácea", "color": "#519799", "rgb": [81, 151, 153]},
    12: {"label": "Formação Campestre", "group": "Vegetação Herbácea", "color": "#d6bc74", "rgb": [214, 188, 116]},
    13: {"label": "Outras Form. Não Florestais", "group": "Vegetação Herbácea", "color": "#d89f5c", "rgb": [216, 159, 92]},
    29: {"label": "Afloramento Rochoso", "group": "Vegetação Herbácea", "color": "#ffaa5f", "rgb": [255, 170, 95]},
    50: {"label": "Restinga Herbácea", "group": "Vegetação Herbácea", "color": "#ad5100", "rgb": [173, 81, 0]},
    15: {"label": "Pastagem", "group": "Agropecuária", "color": "#edde8e", "rgb": [237, 222, 142]},
    39: {"label": "Soja", "group": "Agropecuária", "color": "#f5b3c8", "rgb": [245, 179, 200]},
    20: {"label": "Cana-de-açúcar", "group": "Agropecuária", "color": "#db7093", "rgb": [219, 112, 147]},
    40: {"label": "Arroz", "group": "Agropecuária", "color": "#c71585", "rgb": [199, 21, 133]},
    41: {"label": "Outras Lavouras Temp.", "group": "Agropecuária", "color": "#f54ca9", "rgb": [245, 76, 169]},
    46: {"label": "Café", "group": "Agropecuária", "color": "#d68fe2", "rgb": [214, 143, 226]},
    47: {"label": "Citrus", "group": "Agropecuária", "color": "#9932cc", "rgb": [153, 50, 204]},
    48: {"label": "Outras Perenes", "group": "Agropecuária", "color": "#e6ccff", "rgb": [230, 204, 255]},
    9: {"label": "Silvicultura", "group": "Agropecuária", "color": "#7a5900", "rgb": [122, 89, 0]},
    21: {"label": "Mosaico de Usos", "group": "Agropecuária", "color": "#ffefc3", "rgb": [255, 239, 195]},
    23: {"label": "Praia, Duna e Areal", "group": "Não Vegetada", "color": "#ffa07a", "rgb": [255, 160, 122]},
    24: {"label": "Área Urbana", "group": "Não Vegetada", "color": "#d4271e", "rgb": [212, 39, 30]},
    25: {"label": "Outras Áreas Não Vegetadas", "group": "Não Vegetada", "color": "#db4d4f", "rgb": [219, 77, 79]},
    30: {"label": "Mineração", "group": "Não Vegetada", "color": "#9c0027", "rgb": [156, 0, 39]},
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
                "SELECT DISTINCT bioma_predominante AS bioma FROM agro.dim_municipios "
                "WHERE bioma_predominante IS NOT NULL ORDER BY 1"
            )
            biomes = [r["bioma"] for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT ano FROM gold.mv_territorio_municipal_ano WHERE ano >= 2000 ORDER BY ano")
            years = [int(r["ano"]) for r in cur.fetchall()]

            cur.execute(
                "SELECT fonte_id, nome, orgao, categoria, url, versao, ano_inicio, ano_fim, limitacoes, registros "
                "FROM agro.dim_fontes WHERE registros > 0 ORDER BY registros DESC"
            )
            sources = _clean_rows(cur.fetchall())

    return {
        "metrics": CHOROPLETH_METRICS,
        "ufs": ufs,
        "biomes": biomes,
        "years": years,
        "default_year": 2022,
        "sources": sources,
    }


def get_choropleth(
    metric: str = "trase_bovinos_exposicao_5a_ha",
    year: int = 2022,
    uf: str | None = None,
    bioma: str | None = None,
    codes: list[str] | None = None,
) -> dict[str, Any]:
    if metric not in CHOROPLETH_METRICS:
        raise ValueError(f"Métrica desconhecida: {metric}")
    meta = CHOROPLETH_METRICS[metric]
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
            if not rows:
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
) -> dict[str, Any]:
    if product not in ("soja", "bovinos"):
        raise ValueError("Produto deve ser 'soja' ou 'bovinos'.")
    req_year = int(year)
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

    base_where = " AND ".join(base_clauses)

    def fetch_flows(cur, target_year: int) -> list[dict[str, Any]]:
        cur.execute(
            f"""
            SELECT
                f.codigo_municipio_ibge AS origin_code,
                m.municipio AS origin_name,
                m.uf AS origin_uf,
                m.lon AS origin_lon,
                m.lat AS origin_lat,
                f.pais_destino AS country_name,
                f.pais_destino_trase_id AS country_id,
                SUM(f.registros) AS registros,
                SUM(f.volume_t) AS volume_t,
                SUM(f.valor_usd) AS valor_usd,
                SUM(f.exposicao_desmatamento_ha) AS exposicao_ha
            FROM gold.mv_rede_fluxos f
            JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = f.codigo_municipio_ibge
            WHERE f.ano = %s AND {base_where}
              AND m.lon IS NOT NULL AND m.lat IS NOT NULL
            GROUP BY f.codigo_municipio_ibge, m.municipio, m.uf, m.lon, m.lat,
                     f.pais_destino, f.pais_destino_trase_id
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
            if not rows:
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

    countries = _country_coords()
    arcs = []
    for r in rows:
        cid = (r["country_id"] or "").upper()
        if cid not in countries:
            continue
        cname, coords = countries[cid]
        arcs.append({
            "origin_code": r["origin_code"],
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
        "requested_year": req_year,
        "year": eff_year,
        "year_fallback": eff_year != req_year and len(arcs) > 0,
        "count": len(arcs),
        "arcs": arcs,
    }


def get_deter_alerts(
    year: int = 2026,
    bioma: str | None = None,
    uf: str | None = None,
    code: str | None = None,
    limit: int = 2500,
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
            if not int(summary["total"] or 0):
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


def search_municipalities(q: str, limit: int = 12) -> list[dict[str, Any]]:
    term = (q or "").strip()
    if not term:
        return []
    with readonly_conn() as con:
        with con.cursor() as cur:
            if term.isdigit() and len(term) <= 7:
                cur.execute(
                    """
                    SELECT codigo_municipio_ibge AS code, municipio, uf,
                           bioma_predominante AS bioma, lat, lon
                    FROM agro.dim_municipios
                    WHERE codigo_municipio_ibge LIKE %s AND lat IS NOT NULL
                    ORDER BY codigo_municipio_ibge
                    LIMIT %s
                    """,
                    (f"{term}%", int(limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT codigo_municipio_ibge AS code, municipio, uf,
                           bioma_predominante AS bioma, lat, lon
                    FROM agro.dim_municipios
                    WHERE unaccent(lower(municipio)) LIKE unaccent(lower(%s))
                      AND lat IS NOT NULL
                    ORDER BY
                        CASE WHEN unaccent(lower(municipio)) LIKE unaccent(lower(%s)) THEN 0 ELSE 1 END,
                        municipio
                    LIMIT %s
                    """,
                    (f"%{term}%", f"{term}%", int(limit)),
                )
            return _clean_rows(cur.fetchall())


def get_municipality_profile(code: str, year: int = 2022) -> dict[str, Any]:
    req_year = int(year)
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
            if not snap:
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

    where_sql = " AND ".join(clauses)
    with readonly_conn() as con:
        with con.cursor() as cur:
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
                        ROW_NUMBER() OVER (PARTITION BY code ORDER BY area_ha DESC) AS rn
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
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (3,4,5,6,49)), 0)::numeric, 0) AS floresta_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id = 15), 0)::numeric, 0) AS pastagem_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (39,20,40,41,46,47,48)), 0)::numeric, 0) AS agricultura_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (9,21)), 0)::numeric, 0) AS mosaico_silv_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (11,12,13,29,50)), 0)::numeric, 0) AS herbacea_alagada_ha,
                        ROUND(COALESCE(SUM(c.area_ha) FILTER (WHERE c.classe_id IN (23,24,25,30,33)), 0)::numeric, 0) AS outros_agua_ha
                    FROM agro.fato_mapbiomas_cobertura c
                    JOIN agro.dim_municipios m ON m.codigo_municipio_ibge = c.codigo_municipio_ibge
                    WHERE {mun_where}
                    GROUP BY c.ano
                    ORDER BY c.ano
                    """,
                    mun_params,
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

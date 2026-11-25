"""Strict, shared evidence for Studio timelines and dashboards."""

from src.agro_db import CHOROPLETH_METRICS, MAPBIOMAS_CLASSES, get_flows, readonly_conn

EXTRA_METRICS = {
    "deter_count": {"label": "Quantidade de alertas por satélite", "unit": "registros", "source": "INPE TerraBrasilis DETER"},
    "deter_area": {"label": "Área somada dos alertas por satélite", "unit": "km²", "source": "INPE TerraBrasilis DETER"},
    "flows_soja": {"label": "Fluxos internacionais de soja rastreados", "unit": "t", "source": "Trase Soja v2.6.1"},
    "flows_bovinos": {"label": "Fluxos internacionais de bovinos rastreados", "unit": "t", "source": "Trase Bovinos v2.2.2"},
    "land_cover": {"label": "Área de uso e cobertura da terra", "unit": "ha", "source": "MapBiomas Coleção 11"},
}
METRICS = {**CHOROPLETH_METRICS, **EXTRA_METRICS}
DETER_GRID = 0.25


def _time_scope(request, metric):
    start = int(request.get("start_year") or 0)
    end = int(request.get("end_year") or 0)
    if not 1985 <= start <= end <= 2100 or end - start >= 41:
        raise ValueError("Informe um período de até 41 anos, a partir de 1985.")
    monthly = request.get("frequency") == "monthly"
    if monthly and not metric.startswith("deter_"):
        raise ValueError("A frequência mensal está disponível para alertas por satélite.")
    if not monthly:
        return [str(year) for year in range(start, end + 1)]
    first = int(request.get("start_month") or 1)
    last = int(request.get("end_month") or 12)
    if not 1 <= first <= 12 or not 1 <= last <= 12:
        raise ValueError("Informe meses de 1 a 12.")
    periods = [f"{year}-{month:02d}" for year in range(start, end + 1) for month in range(1, 13)
               if (start, first) <= (year, month) <= (end, last)]
    if not periods or len(periods) > 36:
        raise ValueError("Selecione um intervalo de até 36 meses.")
    return periods


def _territory(request):
    uf = str(request.get("uf") or "").strip().upper()
    bioma = str(request.get("bioma") or "").strip()[:40]
    code = str(request.get("code") or "").strip()
    if code and (len(code) != 7 or not code.isascii() or not code.isdecimal()):
        raise ValueError("Use o código IBGE de sete dígitos para o município.")
    if not uf and not code:
        return uf, bioma, code, None
    with readonly_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT codigo_municipio_ibge AS code, municipio AS name, uf, uf_nome, lon, lat
            FROM agro.dim_municipios WHERE (%s <> '' AND codigo_municipio_ibge = %s)
                                        OR (%s = '' AND uf = %s)
            ORDER BY codigo_municipio_ibge
        """, (code, code, code, uf))
        rows = cur.fetchall()
    if not rows or (uf and uf != rows[0]["uf"]):
        raise ValueError("O território informado não corresponde a um município ou UF da base.")
    if code:
        uf = rows[0]["uf"]
    coords = [[r["lon"], r["lat"]] for r in rows if r["lon"] is not None and r["lat"] is not None]
    bounds = ([min(p[0] for p in coords), min(p[1] for p in coords),
               max(p[0] for p in coords), max(p[1] for p in coords)] if coords else None)
    return uf, bioma, code, {"name": rows[0]["name"] if code else rows[0]["uf_nome"], "bbox": bounds}


def _deter(periods, scope, metric):
    uf, bioma, code, _ = scope
    monthly = len(periods[0]) == 7
    group = "to_char(view_date, 'YYYY-MM')" if monthly else "ano::text"
    filters = ["lat IS NOT NULL", "lon IS NOT NULL"]
    params = [periods[0], periods[-1]]
    for value, clause in ((uf, "uf = %s"), (bioma, "unaccent(lower(bioma)) = unaccent(lower(%s))"),
                          (code, "codigo_municipio_ibge = %s")):
        if value:
            filters.append(clause)
            params.append(value)
    with readonly_conn() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT MIN(view_date) AS first, MAX(view_date) AS last
            FROM agro.fato_inpe_deter WHERE {' AND '.join(filters)}
        """, params[2:])
        coverage = cur.fetchone()
        cur.execute(f"""
            SELECT {group} AS period, floor(lon / {DETER_GRID}) AS x,
                   floor(lat / {DETER_GRID}) AS y, COUNT(*) AS count,
                   SUM(area_mun_km2) AS area
            FROM agro.fato_inpe_deter
            WHERE {group} BETWEEN %s AND %s AND {' AND '.join(filters)}
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
        """, params)
        rows = cur.fetchall()
    result = {}
    weight = "count" if metric == "deter_count" else "area"
    for row in rows:
        frame = result.setdefault(row["period"], {"cells": [], "records": 0})
        frame["records"] += row["count"]
        frame["cells"].append({"position": [(row["x"] + 0.5) * DETER_GRID, (row["y"] + 0.5) * DETER_GRID],
                               "value": row[weight]})
    for frame in result.values():
        values = [cell["value"] for cell in frame["cells"] if cell["value"] is not None]
        frame["value"] = sum(values) if values else None
    freshness = {key: value.isoformat() if value else None for key, value in coverage.items()}
    return result, freshness


def _indicators(periods, scope, metric, class_ids, grain):
    uf, bioma, code, _ = scope
    coverage = metric == "land_cover"
    fact = ("agro.fato_mapbiomas_cobertura t JOIN agro.dim_municipios m USING (codigo_municipio_ibge)"
            if coverage else "gold.mv_territorio_municipal_ano t JOIN agro.dim_municipios m USING (codigo_municipio_ibge)")
    column = "t.area_ha" if coverage else f't."{metric}"'
    key = "m.uf" if grain == "state" else "m.codigo_municipio_ibge"
    name = "m.uf_nome" if grain == "state" else "m.municipio"
    filters = ["t.ano BETWEEN %s AND %s", f"{column} IS NOT NULL"]
    params = [int(periods[0]), int(periods[-1])]
    for value, clause in ((uf, "m.uf = %s"), (bioma, "unaccent(lower(m.bioma_predominante)) = unaccent(lower(%s))"),
                          (code, "m.codigo_municipio_ibge = %s")):
        if value:
            filters.append(clause)
            params.append(value)
    if coverage and class_ids:
        filters.append("t.classe_id = ANY(%s)")
        params.append(class_ids)
    with readonly_conn() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT t.ano::text AS period, {key} AS code, min({name}) AS name,
                   avg(m.lon) AS lon, avg(m.lat) AS lat, sum({column})::double precision AS value
            FROM {fact} WHERE {' AND '.join(filters)}
            GROUP BY 1, 2 ORDER BY 1, value DESC, code
        """, params)
        rows = cur.fetchall()
    result = {}
    for row in rows:
        frame = result.setdefault(row.pop("period"), {"areas": [], "value": 0})
        frame["areas"].append(row)
        frame["value"] += row["value"]
    return result


def _facts(frames):
    observed = [frame for frame in frames if frame["value"] is not None]
    if not observed:
        return []
    first, last = observed[0], observed[-1]
    peak = max(observed, key=lambda frame: frame["value"])
    facts = []
    for frame, title in ((first, "Início da série"), (peak, "Maior valor observado"), (last, "Último valor disponível")):
        if any(fact["period"] == frame["period"] for fact in facts):
            continue
        facts.append({"id": f"F{len(facts) + 1}", "period": frame["period"], "title": title, "value": frame["value"]})
    for baseline, target, title in ((first, last, "Variação no período"),):
        if baseline is not target and baseline["value"] != 0:
            facts.append({"id": f"F{len(facts) + 1}", "period": target["period"], "title": title,
                          "value": target["value"], "baseline_period": baseline["period"],
                          "baseline_value": baseline["value"],
                          "change_pct": round((target["value"] - baseline["value"]) / abs(baseline["value"]) * 100, 1)})
    pairs = [(a, b) for a, b in zip(frames, frames[1:]) if a["value"] not in (None, 0) and b["value"] is not None]
    if pairs:
        a, b = min(pairs, key=lambda pair: (pair[1]["value"] - pair[0]["value"]) / abs(pair[0]["value"]))
        if b["value"] < a["value"]:
            facts.append({"id": f"F{len(facts) + 1}", "period": b["period"], "title": "Maior queda entre períodos consecutivos",
                          "value": b["value"], "baseline_period": a["period"], "baseline_value": a["value"],
                          "change_pct": round((b["value"] - a["value"]) / abs(a["value"]) * 100, 1)})
    return sorted(facts, key=lambda fact: fact["period"])


def get_temporal(request):
    metric = request.get("metric")
    if not isinstance(metric, str) or metric not in METRICS:
        raise ValueError("Escolha uma métrica disponível para a Linha do Tempo.")
    if metric == "inpe_deter_area_km2":
        metric = "deter_area"
    meta = METRICS[metric]
    periods = _time_scope(request, metric)
    uf, bioma, code, focus = scope = _territory(request)
    grain = "municipality" if uf or code else "state"
    classes = request.get("classes") or []
    if not isinstance(classes, list) or any(type(item) is not int or item not in MAPBIOMAS_CLASSES for item in classes):
        raise ValueError("Escolha classes válidas do MapBiomas.")
    mode = "areas"
    freshness = None
    if metric.startswith("flows_"):
        mode = "arcs"
        product = metric.removeprefix("flows_")
        result = {}
        for period in periods:
            data = get_flows(product, int(period), uf=uf or None, origin=code or None,
                             grain=grain, limit=90 if grain == "state" else 180, strict_year=True, bioma=bioma or None)
            result[period] = {"arcs": data["arcs"], "value": data["total"]}
    elif metric.startswith("deter_"):
        mode = "cells"
        result, freshness = _deter(periods, scope, metric)
    else:
        result = _indicators(periods, scope, metric, classes, grain)

    frames = [{"period": period, "value": None, mode: [], **result.get(period, {})} for period in periods]
    if freshness and freshness["last"]:
        length = len(periods[0])
        cutoff = freshness["last"][:length]
        frames_by_period = {frame["period"]: frame for frame in frames}
        if cutoff in frames_by_period:
            frames_by_period[cutoff]["coverage_through"] = freshness["last"]
    scale = max((item["value"] for frame in frames for item in frame.get(mode, [])
                 if item.get("value") is not None), default=0) if mode != "arcs" else max(
                     (arc["volume_t"] for frame in frames for arc in frame["arcs"]), default=0)
    label = meta["label"]
    if metric == "land_cover" and classes:
        label += " · " + ", ".join(MAPBIOMAS_CLASSES[code]["label"] for code in classes)
    return {
        "metric": metric, "label": label, "unit": meta["unit"], "source": meta["source"],
        "scope": " · ".join(filter(None, [focus["name"] if focus else "", bioma])) or "Brasil",
        "uf": uf, "code": code, "bioma": bioma, "classes": classes, "focus": focus, "grain": grain, "mode": mode,
        "frames": frames, "facts": _facts(frames), "max": scale,
        "freshness": freshness, "grid_degrees": DETER_GRID if mode == "cells" else None,
        "method_url": "/metodologia#" + metric,
    }

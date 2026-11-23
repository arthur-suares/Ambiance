"""Rede da soja por trecho, com consulta de qualquer registro do CSV."""

from collections import Counter, defaultdict
from functools import lru_cache
import csv
import gzip
import json
import math
import os
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
PLACES = ROOT / "web/data/trase_network_places.json"
SOURCE = ROOT.parent / "dados_processados/trase_soja_fluxos.csv.gz"
EDGE_PAGE_SIZE = 20


@lru_cache(maxsize=4096)
def normalize(name):
    return "".join(c for c in unicodedata.normalize("NFKD", name.upper())
                   if not unicodedata.combining(c)).strip()


@lru_cache(maxsize=1)
def reference_data():
    catalog = json.loads(PLACES.read_text(encoding="utf-8"))
    nodes = {
        **{code: value for code, value in catalog["municipalities"].items()},
        **{"X:" + label: catalog["municipalities"][code] for label, code in catalog["exits"].items()},
        **catalog["countries"],
    }
    by_name = defaultdict(list)
    for code, (name, _) in catalog["municipalities"].items():
        by_name[normalize(name)].append(code)
    snapshot = json.loads((ROOT / "web/data/trase_map_demo.json").read_text(encoding="utf-8"))
    geometry = {}
    for flow in snapshot["flows"]:
        route = snapshot["routes"].get(flow["id"])
        if route:
            key = (flow["origin"]["code"], flow["destination"]["code"])
            geometry[key] = road_fields(route)
    return nodes, by_name, geometry


def source_path():
    return Path(os.environ.get("TRASE_SOY_MAP_SOURCE", str(SOURCE)))


def source_rows():
    with gzip.open(source_path(), "rt", encoding="utf-8", newline="") as stream:
        yield from enumerate(csv.DictReader(stream), 1)


def matches_scope(row, year=None, origin=None, exit_id=None, country=None):
    return ((year is None or int(row["ano"]) == year)
            and (origin is None or row["codigo_municipio_ibge"] == origin)
            and (exit_id is None or "X:" + normalize(row["porto_exportacao"]) == exit_id)
            and (country is None or row["pais_primeira_importacao_trase_id"] == country))


def resolve(row, nodes, by_name):
    origin = row["codigo_municipio_ibge"]
    hub_name = normalize(row["hub_logistico"])
    candidates = by_name.get(hub_name, ())
    # Em caso de homônimo, o código de origem resolve apenas quando o hub
    # tem o mesmo nome do município de origem. Os demais ficam indefinidos.
    hub = origin if origin in candidates else candidates[0] if len(candidates) == 1 else None
    exit_id = "X:" + normalize(row["porto_exportacao"])
    country = row["pais_primeira_importacao_trase_id"]
    return tuple(key if key in nodes else None for key in (origin, hub, exit_id, country))


def segments(points, nodes, country):
    origin, hub, exit_id, target = points
    for kind, start, end in (("origin", origin, hub), ("exit", hub, exit_id), ("world", exit_id, target)):
        if not start or not end or (kind == "world" and country in ("BR", "", "XX")):
            continue
        if nodes[start][1] != nodes[end][1]:
            yield kind, start, end


def payload_edges(totals, nodes, geometry):
    edges = []
    used_nodes = set()
    for (kind, start, end), (count, volume) in sorted(totals.items()):
        used_nodes.update((start, end))
        edge = {"stage": kind, "from": start, "to": end, "rows": count, "volume_t": round(volume, 3)}
        if kind == "origin" and (start, end) in geometry:
            edge.update(geometry[start, end])
        edges.append(edge)
    return edges, {key: nodes[key] for key in sorted(used_nodes)}


def scan_network(year, origin=None, exit_id=None, country=None):
    nodes, by_name, geometry = reference_data()
    totals = defaultdict(lambda: [0, 0.0])
    years = Counter()
    counts = Counter()
    origins_by_volume = defaultdict(float)
    covered_volume = 0.0
    options = {"origin": set(), "exit": set(), "country": set()}
    for _, row in source_rows():
        row_year = int(row["ano"])
        years[row_year] += 1
        row_country = row["pais_primeira_importacao_trase_id"]
        ref_points = (row["codigo_municipio_ibge"], "X:" + normalize(row["porto_exportacao"]), row_country)
        for field, point in zip(options, ref_points):
            if point in nodes:
                options[field].add(point)
        if not matches_scope(row, year, origin, exit_id, country):
            continue
        points = resolve(row, nodes, by_name)
        edges = list(segments(points, nodes, row_country))
        amount = volume_of(row)
        counts["total"] += 1
        if edges:
            counts["mapped"] += 1
            covered_volume += amount
            if points[0]:
                origins_by_volume[points[0]] += amount
        for kind, start, end in edges:
            entry = totals[kind, start, end]
            entry[0] += 1
            entry[1] += amount
            counts[kind] += 1
            if kind == "origin" and (start, end) in geometry:
                counts["road"] += 1
    edges, places = payload_edges(totals, nodes, geometry)
    return {
        "year": year, "years": sorted(years), "record_count": sum(years.values()),
        "counts": dict(counts), "mapped_volume_t": round(covered_volume, 3),
        "origin_count": len(origins_by_volume),
        "top_origins": [
            {"id": key, "name": nodes[key][0], "volume_t": round(volume, 3)}
            for key, volume in sorted(origins_by_volume.items(), key=lambda row: (-row[1], row[0]))[:10]
        ],
        "edges": edges, "places": places,
        "filter_options": {field: sorted(((key, nodes[key][0]) for key in keys), key=lambda item: item[1])
                           for field, keys in options.items()},
    }


# Um cache pequeno atende alternâncias de ano e evita reter o CSV inteiro.
@lru_cache(maxsize=4)
def network_by_year(year, origin=None, exit_id=None, country=None):
    return scan_network(year, origin, exit_id, country)


def find_edge(network, edge_key):
    edge = next((item for item in network["edges"]
                 if (item["stage"], item["from"], item["to"]) == edge_key), None)
    if edge is None:
        raise KeyError("Trecho fora do recorte da rede.")
    return edge


def edge_records(stage, start, end, page, year=None, origin=None, exit_id=None, country=None):
    network = network_by_year(year, origin, exit_id, country)
    edge_key = (stage, start, end)
    edge = find_edge(network, edge_key)
    offset = (page - 1) * EDGE_PAGE_SIZE
    if offset >= edge["rows"]:
        raise KeyError("Página fora dos registros deste trecho.")
    nodes, by_name, _ = reference_data()
    records = []
    skipped = 0
    for number, row in source_rows():
        if not matches_scope(row, year, origin, exit_id, country):
            continue
        points = resolve(row, nodes, by_name)
        if edge_key not in segments(points, nodes, row["pais_primeira_importacao_trase_id"]):
            continue
        if skipped < offset:
            skipped += 1
            continue
        records.append({
            "record": number, "year": int(row["ano"]), "volume_t": volume_of(row),
            "origin": row["municipio_producao"], "hub": row["hub_logistico"],
            "exit": row["porto_exportacao"], "country": row["pais_primeira_importacao"],
        })
        if len(records) == EDGE_PAGE_SIZE:
            break
    return {"total": edge["rows"], "page": page, "page_size": EDGE_PAGE_SIZE, "records": records}


def volume_of(row):
    amount = float(row["volume_comercializado_t"] or 0)
    return amount if math.isfinite(amount) else 0.0


@lru_cache(maxsize=24)
def record_network(record):
    nodes, by_name, geometry = reference_data()
    for number, row in source_rows():
        if number != record:
            continue
        country = row["pais_primeira_importacao_trase_id"]
        points = resolve(row, nodes, by_name)
        amount = volume_of(row)
        totals = {key: [1, amount] for key in segments(points, nodes, country)}
        edges, places = payload_edges(totals, nodes, geometry)
        steps = []
        for key, column in zip(points, ("municipio_producao", "hub_logistico",
                                       "porto_exportacao", "pais_primeira_importacao")):
            steps.append({"label": row[column], "located": key is not None})
            if key is not None:
                places[key] = nodes[key]
        return {
            "record": record, "year": int(row["ano"]), "edges": edges, "places": places,
            "steps": steps, "nodes": [key for key in points if key is not None and key != "BR"],
            "exporter": row["exportador"], "volume_t": amount,
        }
    raise KeyError("Registro fora do CSV de soja.")


def road_fields(route):
    return {
        "path": route["geometry"]["coordinates"],
        "distance_km": route["distance_km"],
        "road_refs": route["road_refs"],
        "has_ferry": route["has_ferry"],
    }


def estimate_edge(edge, places):
    from src.map_demo import fetch_road_route

    if "path" in edge:
        return edge
    start = places[edge["from"]][1]
    end = places[edge["to"]][1]
    return {**edge, **road_fields(fetch_road_route(tuple(start), tuple(end)))}


def estimate_network_road(stage, start, end, year=None, origin=None, exit_id=None, country=None):
    if stage not in ("origin", "exit"):
        raise KeyError("A estimativa rodoviária está disponível nos trechos dentro do Brasil.")
    network = network_by_year(year, origin, exit_id, country)
    edge = find_edge(network, (stage, start, end))
    return estimate_edge(edge, network["places"])


def estimate_record_road(record):
    data = record_network(record)
    edges = []
    for edge in data["edges"]:
        if edge["stage"] not in ("origin", "exit"):
            edges.append(edge)
            continue
        try:
            edges.append(estimate_edge(edge, data["places"]))
        except (OSError, ValueError, TypeError):
            # Uma falha do roteador não descarta o traçado encontrado no outro trecho.
            edges.append({**edge, "road_unavailable": True})
    return {**data, "edges": edges}

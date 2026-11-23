"""Exporta fluxos reais município→hub para o experimento deck.gl.

python3 scripts/prepare_map_demo.py --source ../dados_processados/trase_soja_fluxos.csv.gz --cache-routes
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unicodedata
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.map_demo import fetch_road_route

COORDINATE_URL = ("https://raw.githubusercontent.com/kelvins/municipios-brasileiros/"
                  "975a51d6f2e7a9ee22a734a42ebd624263812f0c/csv/municipios.csv")


def normalize(name):
    return "".join(c for c in unicodedata.normalize("NFKD", name.upper())
                   if not unicodedata.combining(c)).strip()


def aggregate_flows(rows, year):
    pairs = {}
    counts = Counter()
    for row in rows:
        if int(row["ano"]) != year:
            continue
        counts["year_rows"] += 1
        code = row["codigo_municipio_ibge"]
        hub = normalize(row["hub_logistico"])
        if len(code) != 7 or not code.isdigit():
            counts["unknown_origin_rows"] += 1
            continue
        if hub in ("", "UNKNOWN", "UNKNOWN MUNICIPALITY", "NONE"):
            counts["unknown_hub_rows"] += 1
            continue
        country = row["pais_primeira_importacao"]
        if country in ("BRAZIL", "UNKNOWN COUNTRY", "UNKNOWN", ""):
            counts["domestic_or_unknown_destination_rows"] += 1
            continue
        if hub == normalize(row["municipio_producao"]):
            counts["same_municipality_rows"] += 1
            continue
        key = (code, hub)
        pair = pairs.setdefault(key, {
            "origin_name": row["municipio_producao"], "volume_t": 0.0,
            "source_rows": 0, "countries": Counter(), "exporters": Counter(),
        })
        volume = float(row["volume_comercializado_t"] or 0)
        pair["volume_t"] += volume
        pair["source_rows"] += 1
        pair["countries"][country] += volume
        pair["exporters"][row["grupo_exportador"]] += volume
    return pairs, dict(counts)


def build_dataset(source, coordinate_text, year=2022, limit=12):
    municipalities = list(csv.DictReader(io.StringIO(coordinate_text)))
    by_code = {r["codigo_ibge"]: r for r in municipalities}
    by_name = {}
    for r in municipalities:
        by_name.setdefault(normalize(r["nome"]), []).append(r)
    with gzip.open(source, "rt", encoding="utf-8", newline="") as stream:
        pairs, counts = aggregate_flows(csv.DictReader(stream), year)
    flows = []
    for (code, hub), values in sorted(pairs.items(), key=lambda p: -p[1]["volume_t"]):
        matches = by_name.get(hub, [])
        if code not in by_code or len(matches) != 1:
            counts["unresolved_or_ambiguous_pairs"] = counts.get("unresolved_or_ambiguous_pairs", 0) + 1
            continue
        def point(row):
            return {"code": row["codigo_ibge"], "name": row["nome"],
                    "coordinates": [float(row["longitude"]), float(row["latitude"])]}
        flows.append({
            "id": f"soy-{year}-{code}-{matches[0]['codigo_ibge']}",
            "origin": point(by_code[code]), "destination": point(matches[0]),
            "volume_t": round(values["volume_t"], 3), "source_rows": values["source_rows"],
            "countries": [{"name": n, "volume_t": round(v, 3)} for n, v in values["countries"].most_common()],
            "exporters": [{"name": n, "volume_t": round(v, 3)} for n, v in values["exporters"].most_common()],
        })
        if len(flows) == limit:
            break
    if not flows:
        raise ValueError("Nenhum fluxo elegível para o recorte solicitado.")
    return {
        "year": year, "commodity": "soja", "source": "Trase Brasil soja v2.6.1",
        "source_file": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "coordinate_source": COORDINATE_URL,
        "coordinate_note": "Pontos de referência municipais; não são fazendas, silos ou locais exatos de coleta.",
        "scope": ("Maiores fluxos em toneladas entre municípios de produção e hubs distintos, "
                  "com origem identificada, hub de nome único e destino externo identificado. "
                  "Agregação de todos os exportadores e destinos elegíveis em cada par."),
        "selection_counts": counts, "flows": flows, "routes": {},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2022)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--coordinates", type=Path, help="CSV municipal local; evita novo download.")
    parser.add_argument("--output", type=Path, default=ROOT / "web/data/trase_map_demo.json")
    parser.add_argument("--cache-routes", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("--limit deve estar entre 1 e 30")
    if args.coordinates:
        text = args.coordinates.read_text(encoding="utf-8")
    else:
        request = Request(COORDINATE_URL, headers={"User-Agent": "Agro-Trase-Map-Prototype/0.1"})
        with urlopen(request, timeout=25) as response:
            text = response.read().decode("utf-8")
    data = build_dataset(args.source, text, args.year, args.limit)
    if args.cache_routes:
        for flow in data["flows"]:
            try:
                data["routes"][flow["id"]] = fetch_road_route(
                    tuple(flow["origin"]["coordinates"]), tuple(flow["destination"]["coordinates"]))
                print(f"OK {flow['origin']['name']} → {flow['destination']['name']}", flush=True)
            except (OSError, ValueError) as exc:
                print(f"Sem cache para {flow['id']}: {exc}", file=sys.stderr, flush=True)
            time.sleep(1)  # uso moderado do servidor público de demonstração
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"{len(data['flows'])} fluxos; {len(data['routes'])} trajetos salvos em {args.output}")


if __name__ == "__main__":
    main()

"""Experimento local de rotas Trase, sem dependências do chatbot.

Execute: python3 -m src.map_demo --port 8001
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
DATA_FILE = WEB_ROOT / "data" / "trase_map_demo.json"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
_ROUTING_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def load_dataset() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _valid_position(position) -> bool:
    return (isinstance(position, list) and len(position) == 2
            and all(isinstance(n, (float, int)) and not isinstance(n, bool)
                    and math.isfinite(n) for n in position)
            and -180 <= position[0] <= 180 and -90 <= position[1] <= 90)


def parse_osrm(payload: dict) -> dict:
    if (not isinstance(payload, dict) or payload.get("code") != "Ok"
            or not isinstance(payload.get("routes"), list) or not payload["routes"]):
        raise ValueError("O roteador não encontrou um percurso entre esses pontos.")
    route = payload["routes"][0]
    if not isinstance(route, dict):
        raise ValueError("O roteador retornou um trajeto inválido.")
    geometry = route.get("geometry", {})
    if not isinstance(geometry, dict):
        raise ValueError("O roteador retornou um traçado inválido.")
    coordinates = geometry.get("coordinates", [])
    if (geometry.get("type") != "LineString" or len(coordinates) < 2
            or not all(_valid_position(p) for p in coordinates)):
        raise ValueError("O roteador retornou um traçado inválido.")
    distance = route.get("distance")
    if not isinstance(distance, (float, int)) or not math.isfinite(distance) or distance <= 0:
        raise ValueError("O roteador retornou uma distância inválida.")
    references = []
    has_ferry = False
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            has_ferry |= step.get("mode") == "ferry"
            for ref in (step.get("ref") or "").split(";"):
                ref = ref.strip()
                if ref and ref not in references:
                    references.append(ref)
    return {
        "geometry": geometry,
        "distance_km": round(distance / 1000, 1),
        "road_refs": references,
        "has_ferry": has_ferry,
        "provider": "OSRM / OpenStreetMap",
        "profile": "driving (carro; sem restrições específicas de caminhões)",
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


@lru_cache(maxsize=64)
def fetch_road_route(origin: tuple, destination: tuple) -> dict:
    """Pontos vêm apenas do catálogo local; nenhuma URL vem do navegador."""
    coordinates = ";".join(",".join(str(n) for n in p) for p in (origin, destination))
    url = f"{OSRM_URL}/{coordinates}?overview=full&geometries=geojson&steps=true&alternatives=false"
    request = Request(url, headers={"User-Agent": "Agro-Trase-Map-Prototype/0.1"})
    with _ROUTING_LOCK:
        with urlopen(request, timeout=25) as response:
            payload = json.load(response)
    return parse_osrm(payload)


def route_for_flow(flow_id: str) -> dict:
    data = load_dataset()
    flow = next((f for f in data["flows"] if f["id"] == flow_id), None)
    if flow is None:
        raise KeyError("Fluxo não encontrado nesta amostra.")
    # Os trajetos já calculados mantêm o experimento utilizável quando o
    # serviço público de demonstração estiver indisponível.
    saved = data.get("routes", {}).get(flow_id)
    if saved:
        return {"flow_id": flow_id, "delivery": "saved", **saved}
    route = fetch_road_route(tuple(flow["origin"]["coordinates"]),
                             tuple(flow["destination"]["coordinates"]))
    return {"flow_id": flow_id, "delivery": "live", **route}


def _network_response(endpoint, query):
    from src.map_network import edge_records, estimate_network_road, estimate_record_road, network_by_year, record_network

    def get(key):
        return query.get(key, [""])[0]

    def number(value, digits):
        return value.isascii() and value.isdecimal() and len(value) <= digits and int(value) > 0

    record, year = get("record"), get("year")
    if ((record and not number(record, 9))
            or (year and (len(year) != 4 or not number(year, 4)))):
        return 400, {"error": "Informe um ano válido ou um número de registro positivo."}
    scope = (int(year) if year else None, get("origin") or None, get("exit") or None, get("country") or None)
    if endpoint == "/api/map/edge":
        if get("road") == "1":
            return 200, estimate_network_road(get("stage"), get("from"), get("to"), *scope)
        page = get("page") or "1"
        if not number(page, 6):
            return 400, {"error": "Informe um número de página válido."}
        return 200, edge_records(get("stage"), get("from"), get("to"), int(page), *scope)
    if record:
        data = estimate_record_road(int(record)) if get("road") == "1" else record_network(int(record))
        return 200, data
    return 200, network_by_year(*scope)


def handle_map_get(handler: BaseHTTPRequestHandler) -> bool:
    path = urlsplit(handler.path)
    assets = {
        "/mapa": ("network.html", "text/html; charset=utf-8"),
        "/mapa/": ("network.html", "text/html; charset=utf-8"),
        "/mapa/fluxo": ("map.html", "text/html; charset=utf-8"),
        "/mapa/network.css": ("network.css", "text/css; charset=utf-8"),
        "/mapa/network.js": ("network.js", "text/javascript; charset=utf-8"),
        "/mapa/map.css": ("map.css", "text/css; charset=utf-8"),
        "/mapa/map.js": ("map.js", "text/javascript; charset=utf-8"),
    }
    if path.path in assets:
        name, content_type = assets[path.path]
        handler._send(200, content_type, (WEB_ROOT / name).read_bytes())
        return True
    network_endpoints = ("/api/map/network", "/api/map/edge")
    if path.path not in ("/api/map/flows", "/api/map/route", *network_endpoints):
        return False
    try:
        if path.path in network_endpoints:
            handler._json(*_network_response(path.path, parse_qs(path.query)))
        elif path.path == "/api/map/flows":
            data = load_dataset()
            handler._json(200, {k: v for k, v in data.items() if k != "routes"})
        else:
            flow_id = parse_qs(path.query).get("id", [""])[0]
            handler._json(200, route_for_flow(flow_id))
    except KeyError as exc:
        handler._json(404, {"error": exc.args[0]})
    except FileNotFoundError:
        message = ("CSV da Trase indisponível. Confira a configuração TRASE_SOY_MAP_SOURCE."
                   if path.path in ("/api/map/network", "/api/map/edge")
                   else "Amostra indisponível. Execute scripts/prepare_map_demo.py.")
        handler._json(503, {"error": message})
    except (OSError, ValueError, TypeError) as exc:
        handler.log_error("Falha no mapa: %s", exc)
        message = ("Não foi possível carregar a rede da Trase."
                   if path.path in ("/api/map/network", "/api/map/edge") and "road" not in parse_qs(path.query)
                   else "Não foi possível obter o trajeto. Tente novamente ou veja a ligação entre municípios.")
        handler._json(503, {"error": message})
    return True


class MapHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/":
            self.send_response(302)
            self.send_header("Location", "/mapa")
            self.end_headers()
        elif not handle_map_get(self):
            self._json(404, {"error": "Página não encontrada."})

    def _json(self, status, data):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def _send(self, status, content_type, payload):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    load_dataset()
    with ThreadingHTTPServer(("127.0.0.1", args.port), MapHandler) as server:
        print(f"Mapa Trase: http://127.0.0.1:{args.port}/mapa", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor do mapa encerrado.")


if __name__ == "__main__":
    main()

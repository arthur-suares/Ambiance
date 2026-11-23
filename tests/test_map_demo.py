"""Checks do experimento geográfico, sem LLM, DuckDB ou acesso à rede."""

from copy import deepcopy
from contextlib import nullcontext
from http.server import ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from scripts.prepare_map_demo import aggregate_flows
from src import map_demo


def source_row(**changes):
    row = {"ano": "2022", "codigo_municipio_ibge": "5107875", "municipio_producao": "SAPEZAL",
           "hub_logistico": "ITAITUBA", "pais_primeira_importacao": "CHINA (MAINLAND)",
           "volume_comercializado_t": "125.5", "grupo_exportador": "EMPRESA A"}
    return {**row, **changes}


def test_aggregate_combines_actors_without_including_domestic_unknown_or_other_years():
    rows = [source_row(), source_row(grupo_exportador="EMPRESA B", volume_comercializado_t="74.5"),
            source_row(pais_primeira_importacao="BRAZIL", volume_comercializado_t="9000"),
            source_row(codigo_municipio_ibge="", volume_comercializado_t="9000"),
            source_row(hub_logistico="SAPEZAL", volume_comercializado_t="9000"),
            source_row(ano="2021", volume_comercializado_t="9000")]
    pairs, counts = aggregate_flows(rows, 2022)
    assert len(pairs) == 1
    flow = pairs[("5107875", "ITAITUBA")]
    assert flow["volume_t"] == 200
    assert flow["source_rows"] == 2
    assert sum(flow["exporters"].values()) == 200
    assert sum(flow["countries"].values()) == 200
    assert counts["unknown_origin_rows"] == 1


def osrm_payload():
    return {"code": "Ok", "routes": [{
        "geometry": {"type": "LineString", "coordinates": [[-58, -13], [-56, -12]]},
        "distance": 180000,
        "legs": [{"steps": [{"ref": "BR-163;BR-230", "mode": "driving"},
                            {"ref": "BR-163", "mode": "ferry"}]}],
    }]}


def test_route_preserves_ferry_and_road_references():
    route = map_demo.parse_osrm(osrm_payload())
    assert route["distance_km"] == 180
    assert route["road_refs"] == ["BR-163", "BR-230"]
    assert route["has_ferry"] is True


@pytest.mark.parametrize("coordinates", [[], [[-58, -13]], [[-58, -13], [181, -12]],
                                        [[-58, -13], [float("nan"), -12]]])
def test_invalid_geometry_is_rejected_instead_of_displaying_a_route(coordinates):
    payload = osrm_payload()
    payload["routes"][0]["geometry"]["coordinates"] = coordinates
    with pytest.raises(ValueError):
        map_demo.parse_osrm(payload)


def test_no_route_is_an_error():
    with pytest.raises(ValueError):
        map_demo.parse_osrm({"code": "NoRoute", "routes": []})


def test_snapshot_has_consistent_routes_and_flow_totals():
    data = map_demo.load_dataset()
    ids = [flow["id"] for flow in data["flows"]]
    assert ids and len(ids) == len(set(ids))
    assert set(data["routes"]) == set(ids)
    for flow in data["flows"]:
        assert flow["origin"]["code"] != flow["destination"]["code"]
        assert flow["volume_t"] > 0
        assert flow["volume_t"] == pytest.approx(sum(e["volume_t"] for e in flow["exporters"]), abs=0.01)
        assert flow["volume_t"] == pytest.approx(sum(e["volume_t"] for e in flow["countries"]), abs=0.01)
        route = data["routes"][flow["id"]]
        assert len(route["geometry"]["coordinates"]) > 2
        assert route["distance_km"] > 0


@pytest.fixture
def server_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), map_demo.MapHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_http_serves_catalog_and_saved_route_without_contacting_router(server_url, monkeypatch):
    def no_network(*args):
        pytest.fail("A rota salva não deve consultar o roteador")
    monkeypatch.setattr(map_demo, "fetch_road_route", no_network)
    with urlopen(f"{server_url}/api/map/flows") as response:
        catalog = json.load(response)
    assert "routes" not in catalog  # geometrias completas só são carregadas por seleção
    selected = catalog["flows"][0]
    with urlopen(f"{server_url}/api/map/route?id={selected['id']}") as response:
        route = json.load(response)
    assert route["flow_id"] == selected["id"]
    assert route["delivery"] == "saved"


def test_http_unknown_id_cannot_supply_arbitrary_coordinates_or_urls(server_url, monkeypatch):
    def no_network(*args):
        pytest.fail("Identificador inválido não deve consultar serviços externos")
    monkeypatch.setattr(map_demo, "fetch_road_route", no_network)
    with pytest.raises(HTTPError) as error:
        urlopen(f"{server_url}/api/map/route?id=https://example.com")
    assert error.value.code == 404
    assert "error" in json.load(error.value)


def test_http_upstream_failure_returns_recoverable_error(server_url, monkeypatch):
    data = deepcopy(map_demo.load_dataset())
    data["routes"] = {}
    monkeypatch.setattr(map_demo, "load_dataset", lambda: data)
    def fail(*args):
        raise OSError("offline")
    monkeypatch.setattr(map_demo, "fetch_road_route", fail)
    with pytest.raises(HTTPError) as error:
        urlopen(f"{server_url}/api/map/route?id={data['flows'][0]['id']}")
    assert error.value.code == 503
    assert "ligação" in json.load(error.value)["error"]


def test_network_aggregates_shared_segments_and_starts_arcs_at_the_exit(monkeypatch):
    from src import map_network

    nodes = {"5107875": ["Sapezal", [-58, -13]], "1503606": ["Itaituba", [-56, -4]],
             "X:SANTAREM": ["Santarém", [-54, -2]], "CN": ["China", [106, 32]]}
    by_name = {"ITAITUBA": ["1503606"]}
    monkeypatch.setattr(map_network, "reference_data", lambda: (nodes, by_name, {}))
    base = {"porto_exportacao": "SANTAREM", "pais_primeira_importacao_trase_id": "CN"}
    rows = [source_row(**base), source_row(**base, codigo_municipio_ibge=""),
            source_row(**base, ano="2021")]
    monkeypatch.setattr(map_network, "source_rows", lambda: enumerate(rows, 1))

    network = map_network.scan_network(2022)
    assert network["counts"] == {"total": 2, "mapped": 2, "origin": 1, "exit": 2, "world": 2}
    assert network["mapped_volume_t"] == 251
    edges = {edge["stage"]: edge for edge in network["edges"]}
    assert edges["world"] == {"stage": "world", "from": "X:SANTAREM", "to": "CN",
                              "rows": 2, "volume_t": 251}
    assert edges["origin"]["rows"] == 1

    monkeypatch.setattr(map_network, "network_by_year", map_network.scan_network)
    monkeypatch.setattr(map_network, "EDGE_PAGE_SIZE", 1)
    page = map_network.edge_records("world", "X:SANTAREM", "CN", 2, 2022)
    assert page["total"] == 2
    assert [row["record"] for row in page["records"]] == [2]
    filtered = map_network.edge_records("world", "X:SANTAREM", "CN", 1, 2022, "5107875")
    assert filtered["total"] == 1
    assert [row["record"] for row in filtered["records"]] == [1]
    with pytest.raises(KeyError, match="Página fora"):
        map_network.edge_records("world", "X:SANTAREM", "CN", 2, 2022, "5107875")


def test_removed_maritime_layers_are_unavailable(server_url):
    for path in ("/mapa/roteamento-baltico.geojson", "/mapa/corredores-maritimos.png",
                 "/api/map/waterways", "/api/map/sea?from=X%3ABARCARENA&to=CN"):
        with pytest.raises(HTTPError) as error:
            urlopen(f"{server_url}{path}")
        assert error.value.code == 404


def test_chat_link_and_manual_query_use_the_same_scope(monkeypatch, server_url):
    from src import map_chat, map_network

    nodes = {"5107875": ["Sapezal", [-58, -13]], "1503606": ["Itaituba", [-56, -4]],
             "X:BARCARENA": ["Barcarena", [-48, -1]], "CN": ["China", [106, 32]]}
    source = {"porto_exportacao": "BARCARENA", "pais_primeira_importacao_trase_id": "CN"}
    rows = [source_row(**source), source_row(**source, ano="2021")]
    monkeypatch.setattr(map_network, "reference_data", lambda: (nodes, {"ITAITUBA": ["1503606"]}, {}))
    monkeypatch.setattr(map_network, "source_rows", lambda: enumerate(rows, 1))
    monkeypatch.setattr(map_network, "network_by_year", map_network.scan_network)
    monkeypatch.setattr(map_chat, "network_by_year", map_network.scan_network)
    monkeypatch.setattr(map_chat, "_interpret", lambda question: (
        {"supported": True, "year": 2022, "exit": "Barcarena", "country": "China"}, 10, 20
    ))

    answer = map_chat.ask_map("Quais municípios abasteceram a China via Barcarena em 2022?")
    link = urlsplit(answer["map_context"]["url"])
    assert link.path == "/mapa"
    with urlopen(f"{server_url}/api/map/network?{link.query}") as response:
        from_chat = json.load(response)
    with urlopen(f"{server_url}/api/map/network?year=2022&country=CN&exit=X%3ABARCARENA") as response:
        from_manual = json.load(response)
    assert from_chat == from_manual
    assert parse_qs(link.query) == {"year": ["2022"], "exit": ["X:BARCARENA"], "country": ["CN"]}
    assert from_chat["counts"]["mapped"] == 1
    assert from_chat["filter_options"]["exit"] == [["X:BARCARENA", "Barcarena"]]
    assert "125,5 t" in answer["answer"]
    assert "Sapezal" in answer["answer"]


def test_invalid_model_filter_never_produces_a_broader_map(monkeypatch):
    from src import map_chat

    monkeypatch.setattr(map_chat, "_interpret", lambda question: (
        {"supported": True, "year": 2022, "exit": "Porto inventado"}, 10, 20
    ))
    monkeypatch.setattr(map_chat, "network_by_year", lambda *scope: {
        "years": [2022], "filter_options": {"exit": [("X:BARCARENA", "Barcarena")]}
    } if not any(scope) else pytest.fail("Filtro inválido não deve consultar um recorte."))
    response = map_chat.ask_map("Mostre a saída em 2022")
    assert "map_context" not in response
    assert "Porto inventado" in response["answer"]


def test_document_context_keeps_its_citations_separate_from_the_map(monkeypatch):
    from src import map_chat, rag, vector_store

    source = {"title": "Código Florestal", "metadata": {"artigo": "12"},
              "url": "https://example.invalid/lei", "score": 0.02}
    monkeypatch.setattr(vector_store, "get_connection", lambda **kwargs: nullcontext())
    monkeypatch.setattr(rag, "answer", lambda question, **kwargs: rag.RagAnswer(
        question, "O contexto recuperado cita o art. 12 [1].", [source], "end_turn", 5, 8
    ))
    result = {"answer": "918 registros.", "input_tokens": 10, "output_tokens": 20,
              "map_context": {"url": "/mapa?year=2022&country=CN"}}
    map_chat._add_legal_context(result, "O que a lei diz sobre Reserva Legal?", 6)
    assert result["map_context"]["url"] == "/mapa?year=2022&country=CN"
    assert result["domain"] == "mixed"
    assert result["sources"] == [source]
    assert "918 registros.\n\n**Contexto documental**" in result["answer"]
    assert "[1]" in result["answer"]

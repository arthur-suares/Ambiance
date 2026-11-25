"""Servidor local mínimo para testar o chatbot pelo navegador.

Uso: python -m src.cli serve   (abre em http://127.0.0.1:8000)

- GET  /          -> página web/index.html
- POST /api/ask   -> {"question": "...", "k": 6, "mode": "agent"|"laws"|"map",
                      "domain": "auto"|"law"|"beef"|"soy"|"mixed"} -> resposta + consultas + fontes
  mode=agent: agente de dados e leis; mode=laws: RAG jurídico; mode=map: recortes de soja no mapa.
Só escuta em 127.0.0.1 (acessível apenas nesta máquina).
"""

import argparse
import importlib.util
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from src.config import DUCKDB_PATH, OPENROUTER_API_KEY, PROJECT_ROOT

INDEX_HTML = PROJECT_ROOT / "web" / "index.html"
WEB_ROOT = PROJECT_ROOT / "web"


def _analytics_available() -> bool:
    return importlib.util.find_spec("duckdb") is not None and DUCKDB_PATH.is_file()


def _map_chat_available() -> bool:
    from src.map_network import source_path

    return bool(OPENROUTER_API_KEY) and source_path().is_file()


def _law_source(source, label: str | None = None):
    metadata = source["metadata"]
    out = {
        "title": source["title"], "artigo": metadata.get("artigo"),
        "parte": metadata.get("parte"), "partes": metadata.get("partes"),
        "excerpt": (source.get("content") or "")[:600],
        "url": source["url"], "score": float(source["score"]),
        "semantic_rank": source.get("semantic_rank"), "keyword_rank": source.get("keyword_rank"),
    }
    if label:
        out["label"] = label
    return out


class Handler(BaseHTTPRequestHandler):
    def _handle_agro_get(self) -> bool:
        parsed = urlsplit(self.path)
        p = parsed.path
        if p in ("/mapa", "/mapa/"):
            self.send_response(302)
            self.send_header("Location", "/explorar")
            self.end_headers()
            return True
        assets = {
            "/": ("studio.html", "text/html; charset=utf-8"),
            "/index.html": ("studio.html", "text/html; charset=utf-8"),
            "/studio.css": ("studio.css", "text/css; charset=utf-8"),
            "/studio.js": ("studio.js", "text/javascript; charset=utf-8"),
            "/product.css": ("product.css", "text/css; charset=utf-8"),
            "/product.js": ("product.js", "text/javascript; charset=utf-8"),
            "/timeline.js": ("timeline.js", "text/javascript; charset=utf-8"),
            "/methodology.js": ("methodology.js", "text/javascript; charset=utf-8"),
            "/map_layers.js": ("map_layers.js", "text/javascript; charset=utf-8"),
            "/map_layers.css": ("map_layers.css", "text/css; charset=utf-8"),
            "/metodologia": ("methodology.html", "text/html; charset=utf-8"),
            "/metodologia/": ("methodology.html", "text/html; charset=utf-8"),
            "/explorar": ("agro_map.html", "text/html; charset=utf-8"),
            "/explorar/": ("agro_map.html", "text/html; charset=utf-8"),
            "/explorar/agro_map.css": ("agro_map.css", "text/css; charset=utf-8"),
            "/explorar/agro_map.js": ("agro_map.js", "text/javascript; charset=utf-8"),
        }
        if p in assets:
            name, ctype = assets[p]
            self._send(200, ctype, (WEB_ROOT / name).read_bytes())
            return True
        if not p.startswith("/api/agro/"):
            return False
        from src import agro_db
        qs = parse_qs(parsed.query)
        g = lambda k, d="": (qs.get(k, [d])[0] or "").strip()
        try:
            if p == "/api/agro/geojson":
                payload = agro_db.GEOJSON_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/geo+json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(payload)
                return True
            if p == "/api/agro/meta":
                self._json(200, agro_db.get_meta())
                return True
            if p == "/api/agro/methodology":
                from src.methodology import get_methodology

                self._json(200, get_methodology())
                return True
            if p == "/api/agro/deter-grid":
                from src.temporal import get_temporal

                year = int(g("year", "2026"))
                metric = "deter_area" if g("weight") == "area" else "deter_count"
                self._json(200, get_temporal({"metric": metric, "start_year": year, "end_year": year,
                                             "uf": g("uf"), "bioma": g("bioma")}))
                return True
            if p == "/api/agro/states":
                self._json(200, agro_db.get_states_geojson())
                return True
            if p == "/api/agro/mapbiomas-tiles":
                from src.satellite import mapbiomas_tiles

                ids = [int(value) for value in g("classes").split(",") if value.isdecimal()]
                self._json(200, mapbiomas_tiles(int(g("year", "2025")), ids))
                return True
            if p in ("/api/agro/satellite", "/api/agro/satellite-image"):
                from src.satellite import comparison_image, get_comparison

                location = (float(g("lon")), float(g("lat")), g("date"))
                if p.endswith("-image"):
                    self._send(200, "image/png", comparison_image(*location, g("side"), g("scene")))
                else:
                    self._json(200, get_comparison(*location))
                return True
            if p == "/api/agro/choropleth":
                codes_raw = g("codes")
                codes = [c.strip() for c in codes_raw.split(",") if c.strip()] if codes_raw else None
                self._json(200, agro_db.get_choropleth(
                    metric=g("metric", "trase_bovinos_exposicao_5a_ha"),
                    year=int(g("year", "2022")),
                    uf=g("uf") or None,
                    bioma=g("bioma") or None,
                    codes=codes,
                    grain=g("grain", "municipality"),
                    strict_year=g("strict_year") == "1",
                ))
                return True
            if p == "/api/agro/flows":
                self._json(200, agro_db.get_flows(
                    product=g("product", "bovinos"),
                    year=int(g("year", "2022")),
                    uf=g("uf") or None,
                    origin=g("origin") or None,
                    country=g("country") or None,
                    limit=min(500, int(g("limit", "180"))),
                    grain=g("grain", "municipality"),
                    bioma=g("bioma") or None,
                    strict_year=g("strict_year") == "1",
                ))
                return True
            if p == "/api/agro/deter":
                self._json(200, agro_db.get_deter_alerts(
                    year=int(g("year", "2026")),
                    bioma=g("bioma") or None,
                    uf=g("uf") or None,
                    code=g("code") or None,
                    limit=min(15000, int(g("limit", "10000"))),
                    strict_year=g("strict_year") == "1",
                ))
                return True
            if p == "/api/agro/facilities":
                self._json(200, agro_db.get_facilities(
                    chain=g("chain", "bovinos"),
                    uf=g("uf") or None,
                    limit=min(15000, int(g("limit", "10000"))),
                    grain=g("grain", "municipality"),
                    bioma=g("bioma") or None,
                ))
                return True
            if p == "/api/agro/mapbiomas":
                cls_raw = g("classes")
                cls_ids = [int(c.strip()) for c in cls_raw.split(",") if c.strip().isdigit()] if cls_raw else None
                self._json(200, agro_db.get_mapbiomas_coverage(
                    year=int(g("year", "2025")),
                    class_ids=cls_ids,
                    uf=g("uf") or None,
                    bioma=g("bioma") or None,
                    mode=g("mode", "dominant"),
                    include_series=g("include_series", "1") != "0",
                ))
                return True
            if p == "/api/agro/search":
                self._json(200, {"results": agro_db.search_municipalities(
                    g("q"),
                    uf=g("uf") or None,
                    bioma=g("bioma") or None,
                )})
                return True
            if p == "/api/agro/municipality":
                self._json(200, agro_db.get_municipality_profile(
                    code=g("code"),
                    year=None if g("profile") == "territory" else int(g("year", "2022")),
                    strict_year=g("strict_year") == "1",
                ))
                return True
            self._json(404, {"error": "Endpoint /api/agro não encontrado."})
            return True
        except KeyError as exc:
            self._json(404, {"error": str(exc.args[0])})
            return True
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return True
        except (BrokenPipeError, ConnectionResetError):
            return True
        except OSError as exc:
            self._json(503, {"error": str(exc)})
            return True
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return True

    def do_GET(self):
        if self._handle_agro_get():
            return
        from src.map_demo import handle_map_get
        if handle_map_get(self):
            return
        if self.path == "/api/health":
            from src.agro_db import agro_available
            return self._json(200, {"ok": True, "analytics_available": _analytics_available(),
                                    "map_chat_available": _map_chat_available(),
                                    "agro_postgres_available": agro_available()})
        if self.path not in ("/", "/index.html"):
            return self._send(404, "text/plain", b"not found")
        self._send(200, "text/html; charset=utf-8", INDEX_HTML.read_bytes())

    def do_POST(self):
        if self.path == "/api/agro/temporal":
            return self._temporal()
        if self.path != "/api/ask":
            return self._send(404, "text/plain", b"not found")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            question = (body.get("question") or "").strip()
            if not question:
                return self._json(400, {"error": "Pergunta vazia."})
            k = max(1, min(int(body.get("k") or 6), 20))

            start = time.perf_counter()
            mode = body.get("mode", "agent")
            if mode == "agro":
                if not OPENROUTER_API_KEY:
                    return self._json(503, {"error": "Configure OPENROUTER_API_KEY no .env para usar o assistente IA."})
                from src.agro_chat import ask_agro
                result = ask_agro(
                    question,
                    k_laws=k,
                    view_context=body.get("view_context"),
                    history=body.get("history"),
                )
                result["seconds"] = round(time.perf_counter() - start, 1)
                return self._json(200, result)
            if mode == "map":
                if not _map_chat_available():
                    return self._json(503, {"error": "A consulta ao mapa requer a base da soja e o provedor de IA configurado."})
                from src.map_chat import ask_map
                result = ask_map(question, k)
                result["sources"] = [_law_source(source) for source in result["sources"]]
                result["seconds"] = round(time.perf_counter() - start, 1)
                return self._json(200, result)

            from src.rag import AGENT_DOMAINS, answer, build_context, resolve_domain
            domain = resolve_domain(question, (body.get("domain") or "auto").strip().lower())
            if mode == "agent" and domain in AGENT_DOMAINS:
                if not _analytics_available():
                    return self._json(400, {
                        "error": "O modo 'Dados + leis' requer o DuckDB e os dados em data/raw/. Selecione o modo 'Só leis' para consultar as 29 leis ambientais."
                    })
                return self._agent(question, k, start, domain)
            # No modo só-leis, consultas sobre a cadeia sem DuckDB usam o prompt jurídico quando o roteador retornar "auto" ou dados puros.
            law_domain = domain if domain in ("law", "beef", "soy", "mixed") else "law"
            result = answer(question, k=k, domain=law_domain)
            elapsed = time.perf_counter() - start

            formatted_sources = [_law_source(source, label=f"L{i}") for i, source in enumerate(result.sources, 1)]
            law_names = ", ".join(dict.fromkeys(s.get("title", "") for s in formatted_sources[:3] if s.get("title")))
            available_views = [{
                "key": "laws",
                "label": f"Ler trechos da lei ({len(formatted_sources)})",
                "summary": law_names or "Artigos das leis ambientais brasileiras",
                "what_you_see": f"{len(formatted_sources)} trecho(s) da legislação ambiental federal citados na resposta ({law_names}).",
                "what_you_receive": "Texto original dos artigos consultados e link direto para o documento oficial.",
            }] if formatted_sources else []

            self._json(200, {
                "answer": result.text,
                "stop_reason": result.stop_reason,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "seconds": round(elapsed, 1),
                "domain": result.domain,
                "context": build_context(result.sources) if result.sources else "",
                "available_views": available_views,
                "sources": formatted_sources,
            })
        except Exception as e:  # mostra o erro na página em vez de derrubar o servidor
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _temporal(self):
        from src.temporal import get_temporal
        from src.dashboard.studio import build_studio_dashboard

        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("O recorte deve ser um objeto.")
            result = get_temporal(body)
            dashboard = build_studio_dashboard(result["label"], [], result, plan_with_llm=False)
            return self._json(200, {"temporal": result, "dashboard": dashboard})
        except (ValueError, TypeError) as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _agent(self, question, k, start, domain):
        from src.agent import ask as agent_ask, tool_call_summary
        result = agent_ask(question, k_laws=k, domain=domain)
        self._json(200, {
            "answer": result.text,
            "domain": domain,
            "stop_reason": result.stop_reason,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "seconds": round(time.perf_counter() - start, 1),
            "tool_calls": [
                {"label": c.label, "name": c.name, "summary": tool_call_summary(c),
                 "ok": c.ok, "rows": c.rows, "seconds": c.seconds, "output": c.output}
                for c in result.tool_calls
            ],
            "sources": [
                {"label": f"L{i}", **_law_source(source)}
                for i, source in enumerate(result.law_sources, 1)
            ],
        })

    def _json(self, status, data):
        self._send(status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send(self, status, content_type, payload: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if content_type.startswith(("text/html", "text/css", "text/javascript")):
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[web] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


def serve(port: int = 8000, *, preload: bool = True) -> None:
    if preload:
        from src.embeddings import get_model
        if importlib.util.find_spec("duckdb") is not None:
            from src.database import ensure_database
            ensure_database()
        print("Carregando modelo de embeddings...")
        get_model()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Abra http://127.0.0.1:{port}  (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor local do chatbot e mapa.")
    parser.add_argument("--port", type=int, default=8000)
    serve(parser.parse_args().port, preload=False)

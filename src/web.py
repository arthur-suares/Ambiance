"""Servidor local mínimo para testar o chatbot e os dashboards pelo navegador.

Uso: python -m src.cli serve   (abre em http://127.0.0.1:8000)

- GET  /                        -> página web/agro_map.html (chat + mapa + gráficos)
- GET  /chat                    -> página web/index.html (chat do pipeline de dashboards)
- GET  /dashboards/<nome>.html  -> serve HTML estático apenas de DASHBOARD_OUTPUT_DIR
- POST /api/ask   -> {"question": "...", "k": 6, "mode": "agro"|"agent"|"laws"|"map", ...}
- POST /api/chat  -> pipeline com sessão ({"session_id", "message", "domain", "k"})
- POST /api/dashboard -> {"question": "..."} gera um painel com o agente de dashboard
Só escuta em 127.0.0.1 (acessível apenas nesta máquina).
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import threading
import json
import logging
from pathlib import Path
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import src.config as config_mod
from src.config import DUCKDB_PATH, OPENROUTER_API_KEY, PROJECT_ROOT
from src.dashboard.cache import dashboard_cache_key, get_cached_dashboard, save_cached_dashboard
# O agente e o pipeline de chat carregam o DuckDB: são importados só quando usados (ver /api/chat),
# para o servidor subir também no modo jurídico, sem a base analítica.
from src.pipeline.session import (
    InvalidSessionIdError,
    SessionManager,
    generate_session_id,
    validate_session_id,
)
from src.rag import AGENT_DOMAINS, answer, build_context, resolve_domain

INDEX_HTML = PROJECT_ROOT / "web" / "index.html"
WEB_ROOT = PROJECT_ROOT / "web"
DASHBOARD_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.html$")

logger = logging.getLogger(__name__)

SESSION_MANAGER = SessionManager()

# Painéis do agente de dashboard, só sob demanda (clique, abrir o canvas ou hover no cartão). Um trabalho por
# (pergunta normalizada, contexto): chamadas repetidas esperam o mesmo trabalho. Além da memória, painéis prontos
# ficam em outputs/dashboards/cache.json (src/dashboard/cache.py) e sobrevivem a reinícios do servidor.
_DASH_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dashboard")
_DASH_JOBS: dict = {}
_DASH_LOCK = threading.Lock()
_DASH_MAX_CACHED = 40


def _result_is_cacheable(result) -> bool:
    """Painel com arquivo existente e pelo menos um componente (falha ou painel vazio não vale como pronto)."""
    path = getattr(result, "output_path", None)
    spec = getattr(result, "spec", None)
    return bool(path and Path(path).is_file() and getattr(spec, "widgets", None))


def _run_and_cache_dashboard(question: str, chat_context: dict | None):
    from src.dashboard.orchestrator import generate_dashboard

    result = generate_dashboard(question, chat_context=chat_context)
    if _result_is_cacheable(result):
        title = getattr(result.spec, "title", "") or getattr(getattr(result, "plan", None), "dashboard_goal", "")
        save_cached_dashboard(question, chat_context, output_path=result.output_path, title=title,
                              domain=getattr(result, "domain", "auto"))
    else:
        logger.warning("painel sem arquivo ou sem componentes: não entra no cache persistente")
    return result


def _dashboard_job(question: str, chat_context: dict | None):
    key = dashboard_cache_key(question, chat_context)
    with _DASH_LOCK:
        fut = _DASH_JOBS.get(key)
        if fut is not None and fut.done():
            # falhou, ficou vazio ou o arquivo foi apagado: tenta de novo em vez de devolver algo inútil
            if fut.exception() is not None or not _result_is_cacheable(fut.result()):
                fut = None
        if fut is None:
            fut = _DASH_POOL.submit(_run_and_cache_dashboard, question, chat_context)
            _DASH_JOBS[key] = fut
            while len(_DASH_JOBS) > _DASH_MAX_CACHED:
                _DASH_JOBS.pop(next(iter(_DASH_JOBS)))
    return fut


def resolve_dashboard_path(raw_request_path: str, base_dir: Path | None = None) -> Path | None:
    """Resolve com segurança `/dashboards/<nome>.html` estritamente dentro de `DASHBOARD_OUTPUT_DIR`."""
    if not raw_request_path:
        return None
    clean_path, _, _ = raw_request_path.partition("?")
    # Recusa qualquer codificação percentual (%2e, %2f etc.) ou barras extras
    if "%" in clean_path or "\\" in clean_path or not clean_path.startswith("/dashboards/"):
        return None
    filename = clean_path[len("/dashboards/"):]
    if "/" in filename or ".." in filename or not DASHBOARD_FILENAME_RE.fullmatch(filename):
        return None

    root_raw = base_dir if base_dir is not None else config_mod.DASHBOARD_OUTPUT_DIR
    try:
        root = Path(root_raw).resolve()
        candidate = (root / filename).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None

    if candidate.parent != root or not candidate.is_file():
        return None
    return candidate


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
            "/explorar": ("agro_map.html", "text/html; charset=utf-8"),
            "/explorar/": ("agro_map.html", "text/html; charset=utf-8"),
            "/explorar/agro_map.css": ("agro_map.css", "text/css; charset=utf-8"),
            "/explorar/agro_map.js": ("agro_map.js", "text/javascript; charset=utf-8"),
            "/explorar/ufs.geojson": ("data/ufs.geojson", "application/geo+json; charset=utf-8"),
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
            if p == "/api/agro/choropleth":
                codes_raw = g("codes")
                codes = [c.strip() for c in codes_raw.split(",") if c.strip()] if codes_raw else None
                self._json(200, agro_db.get_choropleth(
                    metric=g("metric", "trase_bovinos_exposicao_5a_ha"),
                    year=int(g("year", "2022")),
                    uf=g("uf") or None,
                    bioma=g("bioma") or None,
                    codes=codes,
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
                ))
                return True
            if p == "/api/agro/deter":
                self._json(200, agro_db.get_deter_alerts(
                    year=int(g("year", "2026")),
                    bioma=g("bioma") or None,
                    uf=g("uf") or None,
                    code=g("code") or None,
                    limit=min(15000, int(g("limit", "10000"))),
                ))
                return True
            if p == "/api/agro/facilities":
                self._json(200, agro_db.get_facilities(
                    chain=g("chain", "bovinos"),
                    uf=g("uf") or None,
                    limit=min(15000, int(g("limit", "10000"))),
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
                self._json(200, {"results": agro_db.search_municipalities(g("q"))})
                return True
            if p == "/api/agro/municipality":
                self._json(200, agro_db.get_municipality_profile(
                    code=g("code"),
                    year=int(g("year", "2022")),
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
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return True

    def do_GET(self):
        clean_path, _, _ = self.path.partition("?")
        if self._handle_agro_get():
            return
        from src.map_demo import handle_map_get
        if handle_map_get(self):
            return
        if clean_path == "/api/health":
            from src.agro_db import agro_available
            return self._json(200, {"ok": True, "analytics_available": _analytics_available(),
                                    "map_chat_available": _map_chat_available(),
                                    "agro_postgres_available": agro_available()})
        if clean_path in ("/chat", "/chat/"):
            return self._send(200, "text/html; charset=utf-8", INDEX_HTML.read_bytes())
        if clean_path.startswith("/dashboards/"):
            dash_file = resolve_dashboard_path(self.path)
            if dash_file is None:
                return self._send(404, "text/plain", b"not found")
            return self._send(200, "text/html; charset=utf-8", dash_file.read_bytes())
        return self._send(404, "text/plain", b"not found")

    def do_POST(self):
        clean_path, _, _ = self.path.partition("?")
        if clean_path == "/api/chat":
            return self._handle_chat()
        if clean_path == "/api/dashboard":
            return self._handle_dashboard()
        if clean_path != "/api/ask":
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
                "label": f"Trechos da Lei ({len(formatted_sources)})",
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

    def _handle_chat(self):
        try:
            raw_bytes = self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
            body = json.loads(raw_bytes)
            if not isinstance(body, dict):
                return self._json(400, {"error": "Corpo JSON inválido."})
        except Exception:
            return self._json(400, {"error": "Corpo JSON inválido."})

        if "session_id" in body and body["session_id"] is not None:
            try:
                sid = validate_session_id(body["session_id"])
            except InvalidSessionIdError as exc:
                return self._json(400, {"error": str(exc)})
        else:
            sid = generate_session_id()

        raw_msg = body.get("message")
        if raw_msg is None:
            raw_msg = body.get("question")
        message = raw_msg if isinstance(raw_msg, str) else ""

        try:
            k = max(1, min(int(body.get("k") or 6), 20))
        except (TypeError, ValueError):
            k = 6
        domain = str(body.get("domain") or "auto").strip().lower() or "auto"
        mode = str(body.get("mode") or "agent").strip().lower() or "agent"

        try:
            from src.pipeline.chat import handle_message

            session = SESSION_MANAGER.get_or_create(sid)
            payload = handle_message(
                session,
                message,
                domain=domain,
                k=k,
                mode=mode,
            )
            return self._json(200, payload)
        except Exception:
            return self._json(200, {
                "answer": "Não consegui concluir o atendimento desta mensagem devido a um erro interno.",
                "intent": "question",
                "session_id": sid,
                "dashboards": [],
                "tool_calls": [],
                "sources": [],
                "warnings": ["Erro interno ao processar a mensagem."],
                "seconds": 0.0,
                "trace_id": "",
            })

    def _handle_dashboard(self):
        """Gera um painel completo com o agente de dashboard (Orquestrador → Dados → Dashboard → Revisor)."""
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            question = (body.get("question") or "").strip() if isinstance(body, dict) else ""
            if not question:
                return self._json(400, {"error": "Pergunta vazia."})
            if not _analytics_available():
                return self._json(503, {"error": "O painel completo precisa da base DuckDB (Trase) em data/processed/."})
            chat_context = body.get("context") if isinstance(body.get("context"), dict) else None
            cached = get_cached_dashboard(question, chat_context)
            if cached is not None:  # painel já gerado antes (inclusive antes de reiniciar o servidor): sem LLM
                return self._json(200, {
                    "url": f"/dashboards/{cached['filename']}",
                    "title": cached["title"] or question,
                    "domain": cached["domain"],
                    "seconds": 0.0,
                    "revisions": 0,
                    "cached": True,
                })
            result = _dashboard_job(question, chat_context).result(timeout=600)
            if not result.output_path:
                return self._json(500, {"error": "O agente não gerou o arquivo do painel."})
            return self._json(200, {
                "url": f"/dashboards/{Path(result.output_path).name}",
                "title": result.spec.title if getattr(result.spec, "title", None) else result.plan.dashboard_goal,
                "domain": result.domain,
                "seconds": round(result.seconds, 1),
                "revisions": result.revisions_used,
                "cached": False,
            })
        except Exception as exc:
            logger.exception("Erro em POST /api/dashboard")
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

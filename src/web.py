"""Servidor local mínimo para testar o chatbot e os dashboards pelo navegador.

Uso: python -m src.cli serve   (abre em http://127.0.0.1:8000)

- GET  /                        -> página web/index.html
- GET  /dashboards/<nome>.html  -> serve HTML estático apenas de DASHBOARD_OUTPUT_DIR
- POST /api/chat                -> pipeline com sessão ({"session_id", "message", "domain", "k"})
- POST /api/ask                 -> endpoint legado sem sessão (mantido para compatibilidade)
Só escuta em 127.0.0.1 (acessível apenas nesta máquina).
"""

import json
from pathlib import Path
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import src.config as config_mod
from src.config import PROJECT_ROOT
from src.agent import ask as agent_ask, tool_call_summary
from src.pipeline.chat import handle_message
from src.pipeline.session import (
    InvalidSessionIdError,
    SessionManager,
    generate_session_id,
    validate_session_id,
)
from src.rag import AGENT_DOMAINS, answer, build_context, resolve_domain

INDEX_HTML = PROJECT_ROOT / "web" / "index.html"
DASHBOARD_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.html$")

SESSION_MANAGER = SessionManager()


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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        clean_path, _, _ = self.path.partition("?")
        if clean_path in ("/", "/index.html"):
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
        if clean_path != "/api/ask":
            return self._send(404, "text/plain", b"not found")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            question = (body.get("question") or "").strip()
            if not question:
                return self._json(400, {"error": "Pergunta vazia."})
            k = max(1, min(int(body.get("k") or 6), 20))

            domain = resolve_domain(question, (body.get("domain") or "auto").strip().lower())

            start = time.perf_counter()
            if body.get("mode", "agent") == "agent" and domain in AGENT_DOMAINS:
                return self._agent(question, k, start, domain)
            result = answer(question, k=k, domain=domain)
            elapsed = time.perf_counter() - start

            self._json(200, {
                "answer": result.text,
                "stop_reason": result.stop_reason,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "seconds": round(elapsed, 1),
                "domain": result.domain,
                "context": build_context(result.sources) if result.sources else "",
                "sources": [
                    {
                        "title": s["title"],
                        "artigo": s["metadata"].get("artigo"),
                        "parte": s["metadata"].get("parte"),
                        "partes": s["metadata"].get("partes"),
                        "url": s["url"],
                        "score": float(s["score"]),
                        "semantic_rank": s.get("semantic_rank"),
                        "keyword_rank": s.get("keyword_rank"),
                    }
                    for s in result.sources
                ],
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

    def _agent(self, question, k, start, domain):
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
                {"label": f"L{i}", "title": s["title"], "artigo": s["metadata"].get("artigo"),
                 "parte": s["metadata"].get("parte"), "partes": s["metadata"].get("partes"),
                 "url": s["url"], "score": float(s["score"]),
                 "semantic_rank": s.get("semantic_rank"), "keyword_rank": s.get("keyword_rank")}
                for i, s in enumerate(result.law_sources, 1)
            ],
        })

    def _json(self, status, data):
        self._send(status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send(self, status, content_type, payload: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[web] {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


def serve(port: int = 8000) -> None:
    from src.database import ensure_database
    from src.embeddings import get_model
    ensure_database()
    print("Carregando modelo de embeddings...")
    get_model()  # carrega antes, para a primeira pergunta não demorar
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Abra http://127.0.0.1:{port}  (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")

"""Servidor local mínimo para testar o chatbot pelo navegador.

Uso: python -m src.cli serve   (abre em http://127.0.0.1:8000)

- GET  /          -> página web/index.html
- POST /api/ask   -> {"question": "...", "k": 6} -> resposta + fontes + trechos
Só escuta em 127.0.0.1 (acessível apenas nesta máquina).
"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.config import PROJECT_ROOT
from src.rag import answer, build_context

INDEX_HTML = PROJECT_ROOT / "web" / "index.html"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            return self._send(404, "text/plain", b"not found")
        self._send(200, "text/html; charset=utf-8", INDEX_HTML.read_bytes())

    def do_POST(self):
        if self.path != "/api/ask":
            return self._send(404, "text/plain", b"not found")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            question = (body.get("question") or "").strip()
            if not question:
                return self._json(400, {"error": "Pergunta vazia."})
            k = max(1, min(int(body.get("k") or 6), 20))

            domain = (body.get("domain") or "auto").strip().lower()

            start = time.perf_counter()
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
    from src.embeddings import get_model
    print("Carregando modelo de embeddings...")
    get_model()  # carrega antes, para a primeira pergunta não demorar
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Abra http://127.0.0.1:{port}  (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")

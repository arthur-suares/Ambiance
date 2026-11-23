"""Servidor local mínimo para testar o chatbot e os dashboards pelo navegador.

Uso: python -m src.cli serve   (abre em http://127.0.0.1:8000)

- GET  /                        -> página web/index.html
- GET  /dashboards/<nome>.html  -> serve HTML estático apenas de DASHBOARD_OUTPUT_DIR
- POST /api/chat                -> pipeline com sessão ({"session_id", "message", "domain", "k"})
- POST /api/ask                 -> endpoint legado sem sessão (mantido para compatibilidade)
Só escuta em 127.0.0.1 (acessível apenas nesta máquina).
"""

import importlib.util
import json
from pathlib import Path
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from urllib.parse import parse_qs, urlparse

import src.config as config_mod
from src.config import PROJECT_ROOT
# O agente e o pipeline de chat carregam o DuckDB: são importados só quando usados (ver /api/chat),
# para o servidor subir também no modo jurídico, sem a base analítica.
from src.pipeline.session import (
    InvalidSessionIdError,
    SessionManager,
    generate_session_id,
    validate_session_id,
)
from src.rag import AGENT_DOMAINS, answer, build_context, resolve_domain
from src.voice import (
    ALLOWED_WAV_MIMES,
    VoiceError,
    max_audio_bytes,
    ouvir_pergunta,
    voice_available,
)

INDEX_HTML = PROJECT_ROOT / "web" / "index.html"
QUESTIONS_JSONL = PROJECT_ROOT / "eval" / "perguntas.jsonl"
DASHBOARD_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.html$")
QUESTION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

SESSION_MANAGER = SessionManager()


def load_eval_questions(path: Path | None = None) -> list[dict]:
    """Carrega perguntas de `eval/perguntas.jsonl` para o modo de gravação de avaliação."""
    src_path = path if path is not None else QUESTIONS_JSONL
    if not src_path.is_file():
        return []
    out: list[dict] = []
    for line in src_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        qid = str(item.get("id") or "").strip()
        if qid and QUESTION_ID_RE.fullmatch(qid):
            out.append({
                "id": qid,
                "tipo": item.get("tipo", ""),
                "pergunta": item.get("pergunta", ""),
                "no_teste": bool(item.get("no_teste", False)),
            })
    return out


def _valid_question_ids(path: Path | None = None) -> set[str]:
    return {q["id"] for q in load_eval_questions(path)}


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
    return importlib.util.find_spec("duckdb") is not None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        clean_path, _, _ = self.path.partition("?")
        if clean_path == "/api/health":
            return self._json(200, {
                "ok": True,
                "analytics_available": _analytics_available(),
                "voice_available": voice_available(),
                "voice_max_seconds": config_mod.VOICE_MAX_SECONDS,
                "voice_record_mode": config_mod.VOICE_RECORD_DIR is not None,
            })
        if clean_path == "/api/voice/record/questions":
            return self._handle_voice_record_questions()
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
        if clean_path == "/api/voice":
            return self._handle_voice()
        if clean_path == "/api/voice/record" or clean_path.startswith("/api/voice/record/"):
            return self._handle_voice_record()
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
            mode = body.get("mode", "agent")
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

    def _read_wav_body(self) -> tuple[bytes | None, str]:
        """Valida Content-Type e Content-Length antes de ler o corpo WAV."""
        raw_ct = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if raw_ct not in ALLOWED_WAV_MIMES:
            self._json(415, {"error": "Formato não suportado. Envie áudio WAV (Content-Type: audio/wav)."})
            return None, raw_ct

        raw_len = self.headers.get("Content-Length")
        try:
            content_length = int(raw_len) if raw_len is not None else 0
        except (TypeError, ValueError):
            self._json(400, {"error": "Content-Length inválido."})
            return None, raw_ct

        if content_length <= 0:
            self._json(400, {"error": "Corpo de áudio vazio."})
            return None, raw_ct

        limit = max_audio_bytes()
        if content_length > limit:
            self._json(413, {
                "error": f"Áudio acima do limite de {config_mod.VOICE_MAX_SECONDS}s ({content_length} > {limit} bytes)."
            })
            return None, raw_ct

        audio = self.rfile.read(content_length)
        if not audio:
            self._json(400, {"error": "Corpo de áudio vazio."})
            return None, raw_ct
        return audio, raw_ct

    def _handle_voice(self):
        audio, content_type = self._read_wav_body()
        if audio is None:
            return
        if not voice_available():
            return self._json(503, {"error": "Entrada por voz indisponível (GEMINI_API_KEY não configurada)."})
        try:
            result = ouvir_pergunta(audio, content_type)
            print(f"[voice] {result.segundos:.2f}s | {result.transcricao}")
            return self._json(200, result.to_dict())
        except VoiceError as exc:
            return self._json(exc.http_status, {"error": str(exc)})
        except Exception as exc:
            return self._json(502, {"error": f"Falha ao processar áudio: {type(exc).__name__}: {exc}"})

    def _handle_voice_record_questions(self):
        rec_dir = config_mod.VOICE_RECORD_DIR
        if rec_dir is None:
            return self._json(404, {"error": "Modo de gravação para avaliação está desligado."})
        questions = load_eval_questions()
        for q in questions:
            q["recorded"] = (Path(rec_dir) / f"{q['id']}.wav").is_file()
        return self._json(200, {
            "record_dir": str(rec_dir),
            "questions": questions,
        })

    def _handle_voice_record(self):
        rec_dir = config_mod.VOICE_RECORD_DIR
        if rec_dir is None:
            return self._json(403, {"error": "Modo de gravação para avaliação está desligado (defina VOICE_RECORD_DIR)."})

        parsed = urlparse(self.path)
        qid = ""
        if parsed.path.startswith("/api/voice/record/"):
            qid = parsed.path[len("/api/voice/record/"):].strip()
        else:
            qs = parse_qs(parsed.query)
            qid = (qs.get("id") or [""])[0].strip()

        if not qid or not QUESTION_ID_RE.fullmatch(qid) or qid not in _valid_question_ids():
            return self._json(400, {"error": "ID de pergunta inválido ou inexistente no arquivo de avaliação."})

        audio, _ = self._read_wav_body()
        if audio is None:
            return

        root = Path(rec_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = (root / f"{qid}.wav").resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return self._json(400, {"error": "Caminho de gravação inválido."})

        target.write_bytes(audio)
        print(f"[voice-record] salvo {target.name} ({len(audio)} bytes)")
        return self._json(200, {"saved": True, "id": qid, "bytes": len(audio)})

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
    from src.embeddings import get_model
    if _analytics_available():
        from src.database import ensure_database
        ensure_database()
    else:
        print("[web] DuckDB não instalado — subindo em modo jurídico ('Só leis', 29 normas federais).")
    print("Carregando modelo de embeddings...")
    get_model()  # carrega antes, para a primeira pergunta não demorar
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Abra http://127.0.0.1:{port}  (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor parado.")


if __name__ == "__main__":
    serve()

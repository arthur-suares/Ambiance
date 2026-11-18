"""Observabilidade do pipeline multiagente em JSONL diário (etapa 9 de `docs/PIPELINE_MULTIAGENTE.md`).

- Um `trace_id` por mensagem do usuário;
- Grava um registro por etapa (`monitor_in`, `orchestrator`, `rag`, `data_agent`,
  `dashboard_agent`, `validator`, `monitor_out`) em `outputs/traces/AAAA-MM-DD.jsonl`;
- Nunca grava o texto completo da pergunta nem chaves de API: registra apenas o
  início sanitizado (até 120 caracteres) e o hash SHA-256;
- Escrita física isolada em `write_trace_record` para facilitar migração futura ao Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading

from src.config import PROJECT_ROOT

TRACES_DIR = PROJECT_ROOT / "outputs" / "traces"
MAX_PREVIEW_CHARS = 120

PIPELINE_STAGES = (
    "monitor_in",
    "orchestrator",
    "rag",
    "data_agent",
    "dashboard_agent",
    "validator",
    "monitor_out",
)

_WRITE_LOCK = threading.Lock()

_SECRET_RE = re.compile(
    r"(?:"
    r"sk-[A-Za-z0-9_\-]{12,}"
    r"|OPENROUTER_API_KEY\s*=\s*\S+"
    r"|PG_PASSWORD\s*=\s*\S+"
    r"|Bearer\s+[A-Za-z0-9._\-]{12,}"
    r")",
    re.IGNORECASE,
)


def scrub_sensitive_text(text: str | None) -> str:
    """Remove chaves de API ou credenciais acidentalmente presentes numa string."""
    if not text:
        return ""
    return _SECRET_RE.sub("[REDACTED]", text)


def build_message_fingerprint(message: str | None) -> tuple[str, str]:
    """Devolve `(preview_ate_120_chars, sha256_hex)` sem expor chaves nem o texto integral."""
    raw = message or ""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    cleaned = " ".join(scrub_sensitive_text(raw).split())
    preview = cleaned[:MAX_PREVIEW_CHARS]
    return preview, digest


def write_trace_record(record: dict, traces_dir: Path | None = None) -> Path:
    """Ponto único de persistência de traces (atualmente JSONL diário; substituível por Postgres)."""
    base = Path(traces_dir) if traces_dir is not None else TRACES_DIR
    day_file = datetime.now().strftime("%Y-%m-%d") + ".jsonl"
    out_path = base / day_file
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _WRITE_LOCK:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    return out_path


def record_trace_step(
    *,
    trace_id: str,
    session_id: str,
    stage: str,
    message: str,
    intent: str,
    latency_s: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    tool: str | None = None,
    verdict: str = "ok",
    error: str | None = None,
    traces_dir: Path | None = None,
) -> dict:
    """Monta o registro estruturado de uma etapa do pipeline e delega a `write_trace_record`."""
    preview, sha256_hex = build_message_fingerprint(message)
    lat = round(max(0.0, float(latency_s)), 4)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "session_id": session_id,
        "stage": stage,
        "intent": intent,
        "latency_s": lat,
        "latency_ms": round(lat * 1000.0, 1),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "tool": scrub_sensitive_text(tool) if tool else None,
        "verdict": verdict,
        "error": scrub_sensitive_text(error)[:240] if error else None,
        "message_preview": preview,
        "message_sha256": sha256_hex,
    }
    write_trace_record(record, traces_dir=traces_dir)
    return record

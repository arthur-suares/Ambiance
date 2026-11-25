"""Request-scoped Trace, Session, Observation (span/generation/event) & token tracker.

Wraps `anthropic.Anthropic` returned by `src.rag.get_client()` and provides
`llm_trace`, `llm_span`, `llm_event`, `llm_stage`, and `set_trace_io` so every
request across `web`, `agro_chat`, `rag`, `dashboard`, `map_chat`, and `agent`
captures full OpenRouter/Langfuse-compatible audit details, persists traces
under `outputs/llm_traces/`, appends compact summaries to `outputs/llm_tracker.jsonl`,
and forwards asynchronously to Langfuse (`/api/public/ingestion`).
"""

from __future__ import annotations

import base64
from collections import OrderedDict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.request import Request, urlopen
import uuid

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

TRACE_ID: ContextVar[str] = ContextVar("llm_trace_id", default="")
SESSION_ID: ContextVar[str] = ContextVar("llm_session_id", default="")
TRACE_ROUTE: ContextVar[str] = ContextVar("llm_trace_route", default="")
STAGE: ContextVar[str] = ContextVar("llm_stage", default="untagged")
PARENT_OBS_ID: ContextVar[str] = ContextVar("llm_parent_obs_id", default="")
_CURRENT_TRACE: ContextVar[dict[str, Any] | None] = ContextVar("llm_current_trace", default=None)

_LOCK = threading.Lock()
_EVENTS: deque[dict[str, Any]] = deque(maxlen=500)
_HYDRATED_PATH: Path | None = None
_TRACE_DETAILS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_TRACE_DETAILS_MAX = 200

# Approximate pricing per 1M tokens (USD) for audit estimation.
_MODEL_PRICING_PER_1M: list[tuple[str, tuple[float, float, float]]] = [
    ("deepseek-v4.1-flash", (0.07, 0.014, 0.28)),
    ("deepseek-chat", (0.27, 0.07, 1.10)),
    ("deepseek", (0.14, 0.03, 0.55)),
    ("claude-3-5-haiku", (0.80, 0.08, 4.00)),
    ("claude-haiku", (0.80, 0.08, 4.00)),
    ("claude-3-7-sonnet", (3.00, 0.30, 15.00)),
    ("claude-sonnet", (3.00, 0.30, 15.00)),
    ("claude-opus", (15.00, 1.50, 75.00)),
    ("gpt-4o-mini", (0.15, 0.075, 0.60)),
]


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    low = (model or "").lower()
    rates = (0.0, 0.0, 0.0)
    for substr, price in _MODEL_PRICING_PER_1M:
        if substr in low:
            rates = price
            break
    in_rate, cache_rate, out_rate = rates
    total = (
        (max(0, input_tokens) + max(0, cache_creation_tokens)) * in_rate
        + max(0, cache_read_tokens) * cache_rate
        + max(0, output_tokens) * out_rate
    ) / 1_000_000.0
    return round(total, 6)


def _log_path() -> Path | None:
    raw = os.getenv("LLM_TRACKER_LOG", "").strip()
    if raw.lower() == "off":
        return None
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else (PROJECT_ROOT / path)
    return PROJECT_ROOT / "outputs" / "llm_tracker.jsonl"


def _traces_dir() -> Path | None:
    path = _log_path()
    if path is None:
        return None
    return path.parent / "llm_traces"


def _safe_trace_filename(trace_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (trace_id or "").strip())[:96]
    return f"{cleaned or 'trace'}.json"


def _langfuse_config() -> tuple[str, str, str] | None:
    if os.getenv("LLM_TRACKER_LOG", "").strip().lower() == "off":
        return None
    if os.getenv("LANGFUSE_ENABLED", "1").strip() == "0":
        return None
    host = os.getenv("LANGFUSE_HOST", "").strip().rstrip("/")
    pub = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    sec = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if host and pub and sec:
        return host, pub, sec
    return None


def reset_tracker_state() -> None:
    """Clear in-memory tracker buffers and disk-hydration state (for tests)."""
    global _HYDRATED_PATH
    with _LOCK:
        _EVENTS.clear()
        _TRACE_DETAILS.clear()
        _HYDRATED_PATH = None


def _hydrate_from_disk_locked() -> None:
    """Load up to the latest 500 persisted events when `_LOCK` is held."""
    global _HYDRATED_PATH
    path = _log_path()
    if path is None or _HYDRATED_PATH == path:
        return
    _HYDRATED_PATH = path
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as handle:
            tail_lines = deque(handle, maxlen=500)
    except OSError:
        return
    loaded: list[dict[str, Any]] = []
    for raw in tail_lines:
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            loaded.append(item)
    if loaded:
        existing = list(_EVENTS)
        _EVENTS.clear()
        _EVENTS.extend(loaded)
        _EVENTS.extend(existing)


def _save_trace_detail_locked(trace_doc: dict[str, Any]) -> None:
    tid = trace_doc.get("trace_id")
    if not tid:
        return
    _TRACE_DETAILS[tid] = trace_doc
    _TRACE_DETAILS.move_to_end(tid)
    while len(_TRACE_DETAILS) > _TRACE_DETAILS_MAX:
        _TRACE_DETAILS.popitem(last=False)

    tdir = _traces_dir()
    if tdir is None:
        return
    try:
        tdir.mkdir(parents=True, exist_ok=True)
        target = tdir / _safe_trace_filename(tid)
        target.write_text(json.dumps(trace_doc, ensure_ascii=False, default=str), encoding="utf-8")
        files = sorted(tdir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(files) > _TRACE_DETAILS_MAX:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)
    except OSError:
        pass


def _load_trace_detail_from_disk(trace_id: str) -> dict[str, Any] | None:
    tdir = _traces_dir()
    if tdir is None or not trace_id:
        return None
    target = tdir / _safe_trace_filename(trace_id)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with _LOCK:
                _TRACE_DETAILS[trace_id] = data
                _TRACE_DETAILS.move_to_end(trace_id)
                while len(_TRACE_DETAILS) > _TRACE_DETAILS_MAX:
                    _TRACE_DETAILS.popitem(last=False)
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _iso_to_epoch_ms(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.timestamp() * 1000.0
    except ValueError:
        return None


def _clip_text(text: str, limit: int = 12000) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _safe_json_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return len(str(value))


def _clip_preview(value: Any, limit: int = 2000) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        return json.loads(raw) if len(raw) <= limit else raw[:limit] + "…"
    except Exception:
        txt = str(value)
        return txt if len(txt) <= limit else txt[:limit] + "…"


def _block_attr(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _content_to_text(value: Any, limit: int = 12000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clip_text(value, limit)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            btype = _block_attr(item, "type")
            if btype == "text":
                parts.append(str(_block_attr(item, "text", "")))
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(json.dumps(item, ensure_ascii=False, default=str))
        return _clip_text("\n".join(p for p in parts if p), limit)
    try:
        return _clip_text(json.dumps(value, ensure_ascii=False, default=str), limit)
    except Exception:
        return _clip_text(str(value), limit)


def _extract_prompt_audit(
    system: Any,
    messages: list[Any],
    tools: list[Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    prompt_messages: list[dict[str, Any]] = []

    def add_entry(
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        cached_hint: bool = False,
        tool_use_id: str = "",
    ) -> None:
        tcalls = tool_calls or []
        extra_chars = _safe_json_len(tcalls) if tcalls else 0
        chars = len(content) + extra_chars
        preview_src = content.strip() or (
            ", ".join(tc.get("name", "") for tc in tcalls if tc.get("name")) if tcalls else ""
        )
        preview_line = " ".join(preview_src.split())
        if len(preview_line) > 160:
            preview_line = preview_line[:157] + "…"
        entry: dict[str, Any] = {
            "index": len(prompt_messages) + 1,
            "role": role,
            "preview": preview_line or f"({role})",
            "content": _clip_text(content, 12000),
            "chars": chars,
            "est_tokens": max(1, round(chars / 4)) if chars else 0,
            "cached_hint": cached_hint,
        }
        if tcalls:
            entry["tool_calls"] = tcalls
        if tool_use_id:
            entry["tool_use_id"] = tool_use_id
        prompt_messages.append(entry)

    if isinstance(system, str) and system.strip():
        add_entry("system", system)
    elif isinstance(system, list) and system:
        sys_parts: list[str] = []
        sys_cached = False
        for block in system:
            if _block_attr(block, "cache_control"):
                sys_cached = True
            txt = _block_attr(block, "text")
            if txt:
                sys_parts.append(str(txt))
            elif isinstance(block, str):
                sys_parts.append(block)
        if sys_parts:
            add_entry("system", "\n\n".join(sys_parts), cached_hint=sys_cached)

    for msg in messages or []:
        role = _block_attr(msg, "role", "user") or "user"
        content = _block_attr(msg, "content", "")
        if isinstance(content, list):
            if role == "user":
                user_texts: list[str] = []
                user_cached = False
                for block in content:
                    btype = _block_attr(block, "type")
                    bcached = bool(_block_attr(block, "cache_control"))
                    if btype == "tool_result":
                        tid = str(_block_attr(block, "tool_use_id", "") or "")
                        res_txt = _content_to_text(_block_attr(block, "content", ""), 12000)
                        add_entry("tool", res_txt, cached_hint=bcached, tool_use_id=tid)
                    else:
                        if bcached:
                            user_cached = True
                        txt = _block_attr(block, "text")
                        if txt is not None:
                            user_texts.append(str(txt))
                        elif isinstance(block, str):
                            user_texts.append(block)
                        else:
                            user_texts.append(_content_to_text(block, 12000))
                joined = "\n".join(p for p in user_texts if p.strip())
                if joined:
                    add_entry("user", joined, cached_hint=user_cached)
            elif role == "assistant":
                asst_texts: list[str] = []
                tcalls: list[dict[str, Any]] = []
                asst_cached = False
                for block in content:
                    btype = _block_attr(block, "type")
                    if _block_attr(block, "cache_control"):
                        asst_cached = True
                    if btype == "tool_use":
                        tcalls.append({
                            "id": str(_block_attr(block, "id", "") or ""),
                            "name": str(_block_attr(block, "name", "") or ""),
                            "input": _clip_preview(_block_attr(block, "input"), 2000),
                        })
                    elif btype == "text":
                        txt = _block_attr(block, "text")
                        if txt:
                            asst_texts.append(str(txt))
                    elif isinstance(block, str):
                        asst_texts.append(block)
                add_entry(
                    "assistant",
                    "\n".join(asst_texts),
                    tool_calls=tcalls,
                    cached_hint=asst_cached,
                )
            else:
                add_entry(str(role), _content_to_text(content, 12000))
        else:
            add_entry(str(role), _content_to_text(content, 12000))

    breakdown: dict[str, dict[str, Any]] = {
        r: {"count": 0, "chars": 0, "est_tokens": 0, "pct": 0.0}
        for r in ("system", "user", "assistant", "tool")
    }
    total_chars = 0
    for item in prompt_messages:
        r = item["role"] if item["role"] in breakdown else "user"
        breakdown[r]["count"] += 1
        breakdown[r]["chars"] += item["chars"]
        breakdown[r]["est_tokens"] += item["est_tokens"]
        total_chars += item["chars"]
    if total_chars > 0:
        for r, bucket in breakdown.items():
            bucket["pct"] = round((bucket["chars"] / total_chars) * 100.0, 1)

    tools_names = [
        str(_block_attr(t, "name", "") or "")
        for t in (tools or [])
        if _block_attr(t, "name", "")
    ]
    return prompt_messages, breakdown, tools_names


def _emit_langfuse_batch(batch: list[dict[str, Any]]) -> None:
    cfg = _langfuse_config()
    if not cfg or not batch:
        return
    host, pub, sec = cfg
    auth = base64.b64encode(f"{pub}:{sec}".encode("utf-8")).decode("ascii")
    payload = json.dumps({"batch": batch}, ensure_ascii=False, default=str).encode("utf-8")

    def _send() -> None:
        req = Request(
            f"{host}/api/public/ingestion",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception as exc:
            logger.debug("Falha ao enviar evento ao Langfuse (%s): %s", host, exc)

    threading.Thread(target=_send, daemon=True, name="langfuse-ingest").start()


def _trace_create_item(trace_doc: dict[str, Any], fallback_ts: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": trace_doc["trace_id"],
        "timestamp": trace_doc.get("start_timestamp") or fallback_ts,
        "name": trace_doc.get("name") or trace_doc.get("route") or "ambiance-llm",
        "metadata": {
            "route": trace_doc.get("route") or "",
            **(trace_doc.get("metadata") or {}),
        },
    }
    if trace_doc.get("session_id"):
        body["sessionId"] = trace_doc["session_id"]
    if trace_doc.get("input") is not None:
        body["input"] = trace_doc["input"]
    if trace_doc.get("output") is not None:
        body["output"] = trace_doc["output"]
    return {
        "id": uuid.uuid4().hex,
        "type": "trace-create",
        "timestamp": trace_doc.get("start_timestamp") or fallback_ts,
        "body": body,
    }


def _emit_to_langfuse(event: dict[str, Any], input_preview: Any, output_preview: Any) -> None:
    cfg = _langfuse_config()
    if not cfg:
        return
    trace_id = event.get("trace_id") or uuid.uuid4().hex[:12]
    now_iso = event["timestamp"]
    start_iso = event.get("start_timestamp") or now_iso
    active = _CURRENT_TRACE.get()
    if active and active.get("trace_id") == trace_id:
        trace_item = _trace_create_item(active, start_iso)
    else:
        trace_body: dict[str, Any] = {
            "id": trace_id,
            "timestamp": start_iso,
            "name": event.get("route") or event.get("stage") or "ambiance-llm",
            "metadata": {"route": event.get("route") or ""},
        }
        if event.get("session_id"):
            trace_body["sessionId"] = event["session_id"]
        trace_item = {
            "id": uuid.uuid4().hex,
            "type": "trace-create",
            "timestamp": start_iso,
            "body": trace_body,
        }

    gen_body: dict[str, Any] = {
        "id": event.get("obs_id") or uuid.uuid4().hex,
        "traceId": trace_id,
        "name": event.get("stage") or "untagged",
        "startTime": start_iso,
        "endTime": now_iso,
        "model": event.get("model") or "",
        "modelParameters": {"maxTokens": event.get("max_tokens")},
        "input": input_preview,
        "output": output_preview,
        "usageDetails": {
            "input": event.get("input_tokens", 0),
            "output": event.get("output_tokens", 0),
            "cache_read_input_tokens": event.get("cache_read_tokens", 0),
            "cache_creation_input_tokens": event.get("cache_creation_tokens", 0),
            "total": event.get("total_tokens", 0),
        },
        "level": "DEFAULT" if event.get("ok") else "ERROR",
        "statusMessage": event.get("error") or event.get("stop_reason") or "",
        "metadata": {
            "route": event.get("route") or "",
            "seconds": event.get("seconds", 0.0),
            "tok_per_sec": event.get("tok_per_sec", 0.0),
            "estimated_cost_usd": event.get("estimated_cost_usd", 0.0),
            "system_chars": event.get("system_chars", 0),
            "messages_count": event.get("messages_count", 0),
            "messages_chars": event.get("messages_chars", 0),
            "tools_count": event.get("tools_count", 0),
            "tools_chars": event.get("tools_chars", 0),
            "tool_calls_returned": event.get("tool_calls_returned", []),
        },
    }
    if event.get("parent_observation_id"):
        gen_body["parentObservationId"] = event["parent_observation_id"]

    batch = [
        trace_item,
        {
            "id": uuid.uuid4().hex,
            "type": "generation-create",
            "timestamp": now_iso,
            "body": gen_body,
        },
    ]
    _emit_langfuse_batch(batch)


def _finalize_trace_doc(trace_doc: dict[str, Any]) -> dict[str, Any]:
    observations = list(trace_doc.get("observations") or [])
    base_ms = _iso_to_epoch_ms(trace_doc.get("start_timestamp"))
    if base_ms is None and observations:
        base_ms = _iso_to_epoch_ms(observations[0].get("start_timestamp"))

    in_tok = 0
    out_tok = 0
    cache_read = 0
    cache_write = 0
    total_tok = 0
    cost_usd = 0.0
    gen_count = 0
    span_count = 0
    event_count = 0
    err_count = 0

    for obs in observations:
        obs_start_ms = _iso_to_epoch_ms(obs.get("start_timestamp"))
        if base_ms is not None and obs_start_ms is not None:
            obs["offset_ms"] = max(0, round(obs_start_ms - base_ms))
        else:
            obs.setdefault("offset_ms", 0)
        obs.setdefault("duration_ms", round(float(obs.get("seconds", 0.0)) * 1000))
        otype = obs.get("type")
        if otype == "generation":
            gen_count += 1
            in_tok += int(obs.get("input_tokens", 0) or 0)
            out_tok += int(obs.get("output_tokens", 0) or 0)
            cache_read += int(obs.get("cache_read_tokens", 0) or 0)
            cache_write += int(obs.get("cache_creation_tokens", 0) or 0)
            total_tok += int(obs.get("total_tokens", 0) or 0)
            cost_usd = round(cost_usd + float(obs.get("estimated_cost_usd", 0.0) or 0.0), 6)
        elif otype == "span":
            span_count += 1
        elif otype == "event":
            event_count += 1
        if obs.get("ok") is False:
            err_count += 1

    trace_doc["observations"] = observations
    trace_doc["totals"] = {
        "calls": gen_count,
        "generations": gen_count,
        "spans": span_count,
        "events": event_count,
        "error_calls": err_count,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_write,
        "total_tokens": total_tok,
        "estimated_cost_usd": cost_usd,
        "seconds": trace_doc.get("seconds", 0.0),
        "ms": trace_doc.get("ms", 0),
    }
    return trace_doc


@contextmanager
def llm_trace(
    trace_id: str | None = None,
    route: str = "",
    session_id: str = "",
    name: str = "",
):
    tid = (trace_id or "").strip() or uuid.uuid4().hex[:12]
    sid = (session_id or "").strip()
    start_iso = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    trace_doc: dict[str, Any] = {
        "trace_id": tid,
        "session_id": sid,
        "route": route or "",
        "name": name or route or "ambiance-llm",
        "start_timestamp": start_iso,
        "end_timestamp": start_iso,
        "seconds": 0.0,
        "ms": 0,
        "input": None,
        "output": None,
        "metadata": {},
        "ok": True,
        "error": "",
        "observations": [],
    }
    tok_id = TRACE_ID.set(tid)
    tok_sess = SESSION_ID.set(sid)
    tok_route = TRACE_ROUTE.set(route or "")
    tok_trace = _CURRENT_TRACE.set(trace_doc)
    try:
        yield tid
    except Exception as exc:
        trace_doc["ok"] = False
        trace_doc["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        elapsed = time.perf_counter() - t0
        trace_doc["end_timestamp"] = datetime.now(timezone.utc).isoformat()
        trace_doc["seconds"] = round(elapsed, 3)
        trace_doc["ms"] = round(elapsed * 1000)
        trace_doc["session_id"] = SESSION_ID.get() or trace_doc["session_id"]
        _finalize_trace_doc(trace_doc)
        if trace_doc["observations"] or trace_doc["input"] is not None:
            with _LOCK:
                _save_trace_detail_locked(trace_doc)
            _emit_langfuse_batch([_trace_create_item(trace_doc, start_iso)])
        _CURRENT_TRACE.reset(tok_trace)
        TRACE_ROUTE.reset(tok_route)
        SESSION_ID.reset(tok_sess)
        TRACE_ID.reset(tok_id)


def set_trace_io(
    *,
    name: str | None = None,
    input_data: Any = None,
    output_data: Any = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ok: bool | None = None,
    error: str | None = None,
) -> None:
    if session_id is not None:
        SESSION_ID.set(session_id.strip())
    active = _CURRENT_TRACE.get()
    if not active:
        return
    if name is not None:
        active["name"] = name
    if session_id is not None:
        active["session_id"] = session_id.strip()
    if input_data is not None:
        active["input"] = _clip_preview(input_data, 8000)
    if output_data is not None:
        active["output"] = _clip_preview(output_data, 8000)
    if metadata:
        active["metadata"].update(metadata)
    if ok is not None:
        active["ok"] = bool(ok)
    if error is not None:
        active["error"] = str(error)


@contextmanager
def llm_stage(stage: str):
    tok = STAGE.set(stage or "untagged")
    try:
        yield
    finally:
        STAGE.reset(tok)


class _SpanHandle:
    def __init__(self, span_id: str, metadata: dict[str, Any] | None = None) -> None:
        self.id = span_id
        self.output: Any = None
        self.metadata: dict[str, Any] = dict(metadata or {})

    def set_output(self, value: Any) -> None:
        self.output = value

    def set_metadata(self, **kwargs: Any) -> None:
        self.metadata.update(kwargs)


@contextmanager
def llm_span(
    name: str,
    *,
    input_data: Any = None,
    metadata: dict[str, Any] | None = None,
):
    span_id = uuid.uuid4().hex
    parent_id = PARENT_OBS_ID.get() or None
    trace_id = TRACE_ID.get()
    session_id = SESSION_ID.get()
    start_iso = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    handle = _SpanHandle(span_id, metadata)
    tok_parent = PARENT_OBS_ID.set(span_id)
    ok = True
    err_txt = ""
    try:
        yield handle
    except Exception as exc:
        ok = False
        err_txt = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        PARENT_OBS_ID.reset(tok_parent)
        elapsed = time.perf_counter() - t0
        end_iso = datetime.now(timezone.utc).isoformat()
        obs: dict[str, Any] = {
            "id": span_id,
            "parent_observation_id": parent_id,
            "trace_id": trace_id,
            "session_id": session_id,
            "type": "span",
            "name": name,
            "start_timestamp": start_iso,
            "timestamp": end_iso,
            "seconds": round(elapsed, 3),
            "ms": round(elapsed * 1000),
            "ok": ok,
            "error": err_txt,
            "input": _clip_preview(input_data, 8000),
            "output": _clip_preview(handle.output, 8000),
            "metadata": handle.metadata,
        }
        active = _CURRENT_TRACE.get()
        if active is not None:
            active["observations"].append(obs)
        if trace_id:
            span_body: dict[str, Any] = {
                "id": span_id,
                "traceId": trace_id,
                "name": name,
                "startTime": start_iso,
                "endTime": end_iso,
                "input": obs["input"],
                "output": obs["output"],
                "level": "DEFAULT" if ok else "ERROR",
                "statusMessage": err_txt,
                "metadata": obs["metadata"],
            }
            if parent_id:
                span_body["parentObservationId"] = parent_id
            batch = []
            if active is not None:
                batch.append(_trace_create_item(active, start_iso))
            batch.append({
                "id": uuid.uuid4().hex,
                "type": "span-create",
                "timestamp": end_iso,
                "body": span_body,
            })
            _emit_langfuse_batch(batch)


def llm_event(
    name: str,
    *,
    input_data: Any = None,
    output_data: Any = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    event_id = uuid.uuid4().hex
    parent_id = PARENT_OBS_ID.get() or None
    trace_id = TRACE_ID.get()
    session_id = SESSION_ID.get()
    now_iso = datetime.now(timezone.utc).isoformat()
    obs: dict[str, Any] = {
        "id": event_id,
        "parent_observation_id": parent_id,
        "trace_id": trace_id,
        "session_id": session_id,
        "type": "event",
        "name": name,
        "start_timestamp": now_iso,
        "timestamp": now_iso,
        "seconds": 0.0,
        "ms": 0,
        "ok": True,
        "error": "",
        "input": _clip_preview(input_data, 4000),
        "output": _clip_preview(output_data, 4000),
        "metadata": dict(metadata or {}),
    }
    active = _CURRENT_TRACE.get()
    if active is not None:
        active["observations"].append(obs)
    if trace_id:
        ev_body: dict[str, Any] = {
            "id": event_id,
            "traceId": trace_id,
            "name": name,
            "startTime": now_iso,
            "input": obs["input"],
            "output": obs["output"],
            "level": "DEFAULT",
            "metadata": obs["metadata"],
        }
        if parent_id:
            ev_body["parentObservationId"] = parent_id
        batch = []
        if active is not None:
            batch.append(_trace_create_item(active, now_iso))
        batch.append({
            "id": uuid.uuid4().hex,
            "type": "event-create",
            "timestamp": now_iso,
            "body": ev_body,
        })
        _emit_langfuse_batch(batch)


def current_trace_id() -> str:
    return TRACE_ID.get()


def _record_event(
    event: dict[str, Any],
    *,
    obs_detail: dict[str, Any] | None = None,
    input_preview: Any = None,
    output_preview: Any = None,
) -> None:
    path = _log_path()
    active = _CURRENT_TRACE.get()
    if obs_detail is not None:
        if active is not None:
            active["observations"].append(obs_detail)
        elif event.get("trace_id"):
            tid = event["trace_id"]
            with _LOCK:
                existing = _TRACE_DETAILS.get(tid) or {
                    "trace_id": tid,
                    "session_id": event.get("session_id", ""),
                    "route": event.get("route", ""),
                    "name": event.get("route") or event.get("stage") or "ambiance-llm",
                    "start_timestamp": event.get("start_timestamp") or event.get("timestamp"),
                    "end_timestamp": event.get("timestamp"),
                    "seconds": event.get("seconds", 0.0),
                    "ms": event.get("ms", 0),
                    "input": None,
                    "output": None,
                    "metadata": {},
                    "ok": bool(event.get("ok", True)),
                    "error": event.get("error", ""),
                    "observations": [],
                }
                existing["observations"].append(obs_detail)
                existing["end_timestamp"] = event.get("timestamp") or existing.get("end_timestamp")
                start_ms = _iso_to_epoch_ms(existing.get("start_timestamp"))
                end_ms = _iso_to_epoch_ms(existing.get("end_timestamp"))
                if start_ms is not None and end_ms is not None:
                    total_ms = max(0, round(end_ms - start_ms))
                    existing["ms"] = total_ms
                    existing["seconds"] = round(total_ms / 1000.0, 3)
                _finalize_trace_doc(existing)
                _save_trace_detail_locked(existing)

    with _LOCK:
        _hydrate_from_disk_locked()
        _EVENTS.append(event)
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError:
                pass
    _emit_to_langfuse(event, input_preview, output_preview)


def get_events(
    trace_id: str | None = None,
    limit: int = 200,
    stage: str | None = None,
) -> list[dict[str, Any]]:
    with _LOCK:
        _hydrate_from_disk_locked()
        items = list(_EVENTS)
    if trace_id:
        items = [ev for ev in items if ev.get("trace_id") == trace_id]
    if stage:
        items = [ev for ev in items if ev.get("stage") == stage]
    if limit > 0:
        items = items[-limit:]
    return items


def _peek_trace_detail(trace_id: str) -> dict[str, Any] | None:
    if not trace_id or trace_id == "(sem-trace)":
        return None
    with _LOCK:
        cached = _TRACE_DETAILS.get(trace_id)
        if cached is not None:
            return cached
    return _load_trace_detail_from_disk(trace_id)


def get_trace_detail(trace_id: str) -> dict[str, Any] | None:
    tid = (trace_id or "").strip()
    if not tid:
        return None
    doc = _peek_trace_detail(tid)
    if doc is None:
        events = get_events(trace_id=tid, limit=500)
        if not events:
            return None
        observations: list[dict[str, Any]] = []
        for idx, ev in enumerate(events, 1):
            observations.append({
                "id": ev.get("obs_id") or f"{tid}-gen-{idx}",
                "parent_observation_id": ev.get("parent_observation_id"),
                "trace_id": tid,
                "session_id": ev.get("session_id", ""),
                "type": "generation",
                "name": ev.get("stage") or "untagged",
                "stage": ev.get("stage") or "untagged",
                "start_timestamp": ev.get("start_timestamp") or ev.get("timestamp"),
                "timestamp": ev.get("timestamp") or ev.get("start_timestamp"),
                "seconds": float(ev.get("seconds", 0.0) or 0.0),
                "ms": int(ev.get("ms") or round(float(ev.get("seconds", 0.0) or 0.0) * 1000)),
                "ok": bool(ev.get("ok", True)),
                "error": ev.get("error", ""),
                "model": ev.get("model", ""),
                "max_tokens": ev.get("max_tokens"),
                "stop_reason": ev.get("stop_reason"),
                "input_tokens": int(ev.get("input_tokens", 0) or 0),
                "output_tokens": int(ev.get("output_tokens", 0) or 0),
                "cache_read_tokens": int(ev.get("cache_read_tokens", 0) or 0),
                "cache_creation_tokens": int(ev.get("cache_creation_tokens", 0) or 0),
                "total_tokens": int(ev.get("total_tokens", 0) or 0),
                "tok_per_sec": float(ev.get("tok_per_sec", 0.0) or 0.0),
                "estimated_cost_usd": float(
                    ev.get("estimated_cost_usd")
                    if ev.get("estimated_cost_usd") is not None
                    else estimate_cost_usd(
                        ev.get("model", ""),
                        int(ev.get("input_tokens", 0) or 0),
                        int(ev.get("output_tokens", 0) or 0),
                        int(ev.get("cache_read_tokens", 0) or 0),
                        int(ev.get("cache_creation_tokens", 0) or 0),
                    )
                ),
                "tool_calls_returned": ev.get("tool_calls_returned") or [],
                "system_chars": ev.get("system_chars", 0),
                "messages_count": ev.get("messages_count", 0),
                "messages_chars": ev.get("messages_chars", 0),
                "tools_count": ev.get("tools_count", 0),
                "prompt_messages": [],
                "role_breakdown": {},
                "completion_blocks": [],
                "tools_names": [],
                "legacy": True,
            })
        start_ts = events[0].get("start_timestamp") or events[0].get("timestamp")
        end_ts = events[-1].get("timestamp") or start_ts
        s_ms = _iso_to_epoch_ms(start_ts)
        e_ms = _iso_to_epoch_ms(end_ts)
        span_ms = max(0, round(e_ms - s_ms)) if (s_ms is not None and e_ms is not None) else sum(
            o["ms"] for o in observations
        )
        doc = _finalize_trace_doc({
            "trace_id": tid,
            "session_id": events[0].get("session_id", ""),
            "route": events[0].get("route", ""),
            "name": events[0].get("route") or "ambiance-llm",
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "seconds": round(span_ms / 1000.0, 3),
            "ms": span_ms,
            "input": None,
            "output": None,
            "metadata": {"legacy_summary_only": True},
            "ok": all(o["ok"] for o in observations),
            "error": next((o["error"] for o in observations if o.get("error")), ""),
            "observations": observations,
        })
    else:
        doc = _finalize_trace_doc(dict(doc))

    cfg = _langfuse_config()
    project_id = (os.getenv("LANGFUSE_INIT_PROJECT_ID", "ambiance-agro") or "").strip() or "ambiance-agro"
    return {
        **doc,
        "langfuse_configured": cfg is not None,
        "langfuse_url": cfg[0] if cfg else "",
        "langfuse_project_id": project_id,
    }


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, dict[str, Any]] = {}
    by_trace: dict[str, dict[str, Any]] = {}
    by_session: dict[str, dict[str, Any]] = {}
    totals = {
        "calls": 0,
        "ok_calls": 0,
        "error_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "seconds": 0.0,
    }

    def ev_cost(ev: dict[str, Any]) -> float:
        if ev.get("estimated_cost_usd") is not None:
            return float(ev.get("estimated_cost_usd") or 0.0)
        return estimate_cost_usd(
            ev.get("model", ""),
            int(ev.get("input_tokens", 0) or 0),
            int(ev.get("output_tokens", 0) or 0),
            int(ev.get("cache_read_tokens", 0) or 0),
            int(ev.get("cache_creation_tokens", 0) or 0),
        )

    def add_bucket(bucket: dict[str, Any], ev: dict[str, Any], cost: float) -> None:
        bucket["calls"] += 1
        bucket["input_tokens"] += ev.get("input_tokens", 0)
        bucket["output_tokens"] += ev.get("output_tokens", 0)
        bucket["cache_read_tokens"] += ev.get("cache_read_tokens", 0)
        bucket["cache_creation_tokens"] += ev.get("cache_creation_tokens", 0)
        bucket["total_tokens"] += ev.get("total_tokens", 0)
        bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"] + cost, 6)
        bucket["seconds"] = round(bucket["seconds"] + float(ev.get("seconds", 0.0)), 3)

    def empty_bucket() -> dict[str, Any]:
        return {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "seconds": 0.0,
        }

    for ev in events:
        cost = ev_cost(ev)
        totals["calls"] += 1
        ok = bool(ev.get("ok", True))
        if ok:
            totals["ok_calls"] += 1
        else:
            totals["error_calls"] += 1
        totals["input_tokens"] += ev.get("input_tokens", 0)
        totals["output_tokens"] += ev.get("output_tokens", 0)
        totals["cache_read_tokens"] += ev.get("cache_read_tokens", 0)
        totals["cache_creation_tokens"] += ev.get("cache_creation_tokens", 0)
        totals["total_tokens"] += ev.get("total_tokens", 0)
        totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"] + cost, 6)
        totals["seconds"] = round(totals["seconds"] + float(ev.get("seconds", 0.0)), 3)

        stage = ev.get("stage") or "untagged"
        add_bucket(by_stage.setdefault(stage, empty_bucket()), ev, cost)

        tid = ev.get("trace_id") or "(sem-trace)"
        trace_bucket = by_trace.setdefault(
            tid,
            {
                **empty_bucket(),
                "route": ev.get("route", ""),
                "name": ev.get("route", "") or "ambiance-llm",
                "session_id": ev.get("session_id", ""),
                "question": "",
                "stages": [],
                "ok": True,
                "error_calls": 0,
                "first_timestamp": "",
                "last_timestamp": "",
                "models": [],
                "span_count": 0,
                "event_count": 0,
                "generation_count": 0,
            },
        )
        add_bucket(trace_bucket, ev, cost)
        trace_bucket["stages"].append(stage)
        if not trace_bucket["session_id"] and ev.get("session_id"):
            trace_bucket["session_id"] = ev["session_id"]
        if not ok:
            trace_bucket["ok"] = False
            trace_bucket["error_calls"] += 1
        start_ts = ev.get("start_timestamp") or ev.get("timestamp") or ""
        end_ts = ev.get("timestamp") or start_ts
        if start_ts and (not trace_bucket["first_timestamp"] or start_ts < trace_bucket["first_timestamp"]):
            trace_bucket["first_timestamp"] = start_ts
        if end_ts and (not trace_bucket["last_timestamp"] or end_ts > trace_bucket["last_timestamp"]):
            trace_bucket["last_timestamp"] = end_ts
        model = ev.get("model") or ""
        if model and model not in trace_bucket["models"]:
            trace_bucket["models"].append(model)

    for tid, trace_bucket in by_trace.items():
        detail = _peek_trace_detail(tid)
        if detail:
            trace_bucket["name"] = detail.get("name") or trace_bucket["name"]
            if detail.get("session_id"):
                trace_bucket["session_id"] = detail["session_id"]
            inp = detail.get("input")
            if isinstance(inp, dict) and inp.get("question"):
                trace_bucket["question"] = str(inp["question"])
            elif isinstance(inp, str):
                trace_bucket["question"] = inp
            obs = detail.get("observations") or []
            trace_bucket["span_count"] = sum(1 for o in obs if o.get("type") == "span")
            trace_bucket["event_count"] = sum(1 for o in obs if o.get("type") == "event")
            trace_bucket["generation_count"] = sum(1 for o in obs if o.get("type") == "generation")
        else:
            trace_bucket["generation_count"] = trace_bucket["calls"]

        sid = trace_bucket["session_id"] or "(sem-sessão)"
        sb = by_session.setdefault(
            sid,
            {
                **empty_bucket(),
                "session_id": sid,
                "trace_ids": [],
                "trace_count": 0,
                "first_timestamp": "",
                "last_timestamp": "",
                "first_question": "",
            },
        )
        sb["trace_ids"].append(tid)
        sb["trace_count"] += 1
        sb["calls"] += trace_bucket["calls"]
        sb["input_tokens"] += trace_bucket["input_tokens"]
        sb["output_tokens"] += trace_bucket["output_tokens"]
        sb["cache_read_tokens"] += trace_bucket["cache_read_tokens"]
        sb["cache_creation_tokens"] += trace_bucket["cache_creation_tokens"]
        sb["total_tokens"] += trace_bucket["total_tokens"]
        sb["estimated_cost_usd"] = round(sb["estimated_cost_usd"] + trace_bucket["estimated_cost_usd"], 6)
        sb["seconds"] = round(sb["seconds"] + trace_bucket["seconds"], 3)
        fts = trace_bucket["first_timestamp"]
        lts = trace_bucket["last_timestamp"]
        if fts and (not sb["first_timestamp"] or fts < sb["first_timestamp"]):
            sb["first_timestamp"] = fts
            if trace_bucket["question"]:
                sb["first_question"] = trace_bucket["question"]
        elif not sb["first_question"] and trace_bucket["question"]:
            sb["first_question"] = trace_bucket["question"]
        if lts and (not sb["last_timestamp"] or lts > sb["last_timestamp"]):
            sb["last_timestamp"] = lts

    cfg = _langfuse_config()
    project_id = (os.getenv("LANGFUSE_INIT_PROJECT_ID", "ambiance-agro") or "").strip() or "ambiance-agro"
    return {
        "totals": totals,
        "by_stage": by_stage,
        "by_trace": by_trace,
        "by_session": by_session,
        "langfuse_configured": cfg is not None,
        "langfuse_url": cfg[0] if cfg else "",
        "langfuse_project_id": project_id,
    }


class _TrackedMessages:
    def __init__(self, messages_api: Any) -> None:
        self._messages = messages_api

    def create(self, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        start_iso = datetime.now(timezone.utc).isoformat()
        obs_id = uuid.uuid4().hex
        parent_obs_id = PARENT_OBS_ID.get() or None
        session_id = SESSION_ID.get()
        tools = kwargs.get("tools") or []
        messages = kwargs.get("messages") or []
        system = kwargs.get("system")
        model = kwargs.get("model", "") or ""
        input_preview = _clip_preview(messages[-1] if messages else None)
        prompt_messages, role_breakdown, tools_names = _extract_prompt_audit(system, messages, tools)
        base = {
            "obs_id": obs_id,
            "parent_observation_id": parent_obs_id,
            "type": "generation",
            "start_timestamp": start_iso,
            "timestamp": start_iso,
            "trace_id": TRACE_ID.get(),
            "session_id": session_id,
            "route": TRACE_ROUTE.get(),
            "stage": STAGE.get(),
            "model": model,
            "max_tokens": kwargs.get("max_tokens"),
            "system_chars": _safe_json_len(system),
            "messages_count": len(messages),
            "messages_chars": _safe_json_len(messages),
            "tools_count": len(tools),
            "tools_chars": _safe_json_len(tools),
            "has_thinking": "thinking" in kwargs,
            "has_tool_choice": "tool_choice" in kwargs,
        }
        try:
            response = self._messages.create(**kwargs)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            end_iso = datetime.now(timezone.utc).isoformat()
            err_msg = f"{type(exc).__name__}: {exc}"
            compact = {
                **base,
                "timestamp": end_iso,
                "ok": False,
                "error": err_msg,
                "seconds": round(elapsed, 3),
                "ms": round(elapsed * 1000),
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "total_tokens": 0,
                "tok_per_sec": 0.0,
                "estimated_cost_usd": 0.0,
            }
            obs_detail = {
                **compact,
                "id": obs_id,
                "name": base["stage"],
                "prompt_messages": prompt_messages,
                "role_breakdown": role_breakdown,
                "completion_blocks": [],
                "tools_names": tools_names,
                "metadata": {"route": base["route"], "tools_names": tools_names},
            }
            _record_event(
                compact,
                obs_detail=obs_detail,
                input_preview=input_preview,
                output_preview=err_msg,
            )
            raise

        elapsed = time.perf_counter() - t0
        end_iso = datetime.now(timezone.utc).isoformat()
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        total_tok = in_tok + out_tok + cache_read + cache_write
        tok_per_sec = round(out_tok / elapsed, 1) if elapsed > 0 and out_tok > 0 else 0.0
        cost_usd = estimate_cost_usd(model, in_tok, out_tok, cache_read, cache_write)

        blocks = getattr(response, "content", None) or []
        tool_names = [
            getattr(b, "name", "")
            for b in blocks
            if getattr(b, "type", None) == "tool_use"
        ]
        completion_blocks: list[dict[str, Any]] = []
        for b in blocks:
            btype = getattr(b, "type", None)
            if btype == "text":
                completion_blocks.append({"type": "text", "text": _clip_text(getattr(b, "text", "") or "", 12000)})
            elif btype == "tool_use":
                completion_blocks.append({
                    "type": "tool_use",
                    "id": getattr(b, "id", "") or "",
                    "name": getattr(b, "name", "") or "",
                    "input": _clip_preview(getattr(b, "input", None), 4000),
                })
            else:
                completion_blocks.append({"type": str(btype or "unknown"), "raw": _clip_preview(b, 2000)})

        out_preview = _clip_preview(completion_blocks)
        compact = {
            **base,
            "timestamp": end_iso,
            "ok": True,
            "seconds": round(elapsed, 3),
            "ms": round(elapsed * 1000),
            "stop_reason": getattr(response, "stop_reason", None),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_write,
            "total_tokens": total_tok,
            "tok_per_sec": tok_per_sec,
            "estimated_cost_usd": cost_usd,
            "tool_calls_returned": tool_names,
        }
        obs_detail = {
            **compact,
            "id": obs_id,
            "name": base["stage"],
            "prompt_messages": prompt_messages,
            "role_breakdown": role_breakdown,
            "completion_blocks": completion_blocks,
            "tools_names": tools_names,
            "metadata": {
                "route": base["route"],
                "tools_names": tools_names,
                "has_thinking": base["has_thinking"],
                "has_tool_choice": base["has_tool_choice"],
            },
        }
        _record_event(
            compact,
            obs_detail=obs_detail,
            input_preview=input_preview,
            output_preview=out_preview,
        )
        return response

    def __getattr__(self, item: str) -> Any:
        return getattr(self._messages, item)


class TrackedClient:
    """Thin Anthropic client proxy that records every `messages.create` call."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.messages = _TrackedMessages(client.messages)

    def with_options(self, **kwargs: Any) -> "TrackedClient":
        return TrackedClient(self._client.with_options(**kwargs))

    def __getattr__(self, item: str) -> Any:
        return getattr(self._client, item)

"""Estado de sessão do pipeline de chat (etapa 1 de `docs/PIPELINE_MULTIAGENTE.md`).

Mantém por `session_id`:
- histórico recente de mensagens (usuário/assistente);
- referência ao `ResultStore` compartilhado (`D1..Dn`);
- `DashboardSpec` atual e caminho do HTML gerado;
- última intenção atendida;
- expiração por TTL e limite máximo de sessões em memória (LRU).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
import re
import threading
import time
import uuid

from src.dashboard.schemas import DashboardSpec
from src.pipeline.result_store import ResultStore

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
DEFAULT_MAX_SESSIONS = 200
DEFAULT_SESSION_TTL_SECONDS = 6 * 3600.0
DEFAULT_MAX_HISTORY_MESSAGES = 20


class InvalidSessionIdError(ValueError):
    """Lançada quando `session_id` não obedece `^[A-Za-z0-9_-]{8,64}$`."""


def is_valid_session_id(session_id: object) -> bool:
    return isinstance(session_id, str) and bool(SESSION_ID_RE.fullmatch(session_id))


def validate_session_id(session_id: object) -> str:
    if not is_valid_session_id(session_id):
        raise InvalidSessionIdError(
            "session_id inválido: use de 8 a 64 caracteres alfanuméricos, '_' ou '-'."
        )
    return str(session_id)


def generate_session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:20]}"


@dataclass
class ChatSession:
    session_id: str
    result_store: ResultStore
    history: list[dict] = field(default_factory=list)
    current_spec: DashboardSpec | None = None
    current_dashboard_path: Path | None = None
    last_intent: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES

    @property
    def store(self) -> ResultStore:
        return self.result_store

    def touch(self) -> None:
        self.updated_at = time.monotonic()

    def append_turn(self, user_msg: str, assistant_msg: str) -> None:
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": assistant_msg})
        if len(self.history) > self.max_history_messages:
            self.history = self.history[-self.max_history_messages:]
        self.touch()

    def get_llm_history(self) -> list[dict]:
        return list(self.history)


class SessionManager:
    """Gerencia sessões em memória com TTL e política LRU."""

    def __init__(
        self,
        *,
        result_store: ResultStore | None = None,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES,
    ) -> None:
        self.result_store = result_store if result_store is not None else ResultStore()
        self.max_sessions = max(1, int(max_sessions))
        self.ttl_seconds = float(ttl_seconds)
        self.max_history_messages = max(2, int(max_history_messages))
        self._lock = threading.RLock()
        self._sessions: OrderedDict[str, ChatSession] = OrderedDict()

    def _purge_expired(self, now: float) -> None:
        if self.ttl_seconds <= 0:
            self._sessions.clear()
            return
        expired = [
            sid for sid, sess in self._sessions.items()
            if (now - sess.updated_at) > self.ttl_seconds
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    def get_or_create(self, session_id: object) -> ChatSession:
        sid = validate_session_id(session_id)
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            existing = self._sessions.get(sid)
            if existing is not None:
                existing.updated_at = now
                self._sessions.move_to_end(sid)
                return existing

            while len(self._sessions) >= self.max_sessions:
                self._sessions.popitem(last=False)

            created = ChatSession(
                session_id=sid,
                result_store=self.result_store,
                created_at=now,
                updated_at=now,
                max_history_messages=self.max_history_messages,
            )
            self._sessions[sid] = created
            return created

    def get(self, session_id: str) -> ChatSession | None:
        if not is_valid_session_id(session_id):
            return None
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            sess = self._sessions.get(session_id)
            if sess is not None:
                sess.updated_at = now
                self._sessions.move_to_end(session_id)
            return sess

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(time.monotonic())
            return len(self._sessions)

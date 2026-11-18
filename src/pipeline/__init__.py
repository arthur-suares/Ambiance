"""Pipeline multiagente do chat (sessão, monitores, orquestrador, Result Store e traces).

Segue a arquitetura definida em `docs/PIPELINE_MULTIAGENTE.md`:
1. API de chat com sessão (`session.py`, `chat.py`);
2. Monitor determinístico de entrada e saída (`monitor.py`);
3. Orquestrador de intenção (`orchestrator.py`);
4. Persistência de DataFrames das ferramentas por sessão (`result_store.py`);
5. Observabilidade por etapa em JSONL (`traces.py`).
"""

from src.pipeline.chat import handle_message
from src.pipeline.monitor import InputMonitor, InputVerdict, OutputMonitor, OutputVerdict
from src.pipeline.orchestrator import OrchestrationDecision, classify_intent
from src.pipeline.result_store import ResultStore
from src.pipeline.session import ChatSession, InvalidSessionIdError, SessionManager
from src.pipeline.traces import PIPELINE_STAGES, record_trace_step, write_trace_record

__all__ = [
    "ChatSession",
    "InputMonitor",
    "InputVerdict",
    "InvalidSessionIdError",
    "OrchestrationDecision",
    "OutputMonitor",
    "OutputVerdict",
    "PIPELINE_STAGES",
    "ResultStore",
    "SessionManager",
    "classify_intent",
    "handle_message",
    "record_trace_step",
    "write_trace_record",
]

"""Pipeline multiagente do chat (sessão, monitores, orquestrador, Result Store e traces).

Segue a arquitetura definida em `docs/PIPELINE_MULTIAGENTE.md`:
1. API de chat com sessão (`session.py`, `chat.py`);
2. Monitor determinístico de entrada e saída (`monitor.py`);
3. Orquestrador de intenção (`orchestrator.py`);
4. Persistência de DataFrames das ferramentas por sessão (`result_store.py`);
5. Observabilidade por etapa em JSONL (`traces.py`).
"""

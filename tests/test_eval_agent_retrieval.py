from types import SimpleNamespace

from eval.run_eval import agent_law_retrieval_metrics
from src.agent import ToolCall


def test_agent_retrieval_metrics_use_actual_law_query_and_source_range():
    chunks = [
        {
            "title": "Lei nº 12.651/2012 – Código Florestal",
            "metadata": {"artigo": "12"},
        },
        {
            "title": "Lei nº 12.651/2012 – Código Florestal",
            "metadata": {"artigo": "3"},
        },
    ]
    answer = SimpleNamespace(
        tool_calls=[
            ToolCall(
                label="L1-L2",
                name="search_laws",
                input={"query": "Percentual de Reserva Legal por bioma"},
                ok=True,
                output="trechos legais",
                subquery_id="law_1",
                law_source_start=1,
                law_source_end=2,
            )
        ],
        law_sources=chunks,
    )
    item = {
        "artigos": [
            {"lei": "Lei 12.651/2012 (Código Florestal)", "artigo": "12", "nivel": "essencial"},
            {"lei": "Lei 12.651/2012 (Código Florestal)", "artigo": "3", "nivel": "complementar"},
        ]
    }

    [metrics] = agent_law_retrieval_metrics(answer, item)

    assert metrics["pergunta_enviada"] == "Percentual de Reserva Legal por bioma"
    assert metrics["subconsulta_id"] == "law_1"
    assert metrics["metricas"]["hit@1"] == 1.0
    assert metrics["metricas"]["recall@1"] == 0.5
    assert metrics["metricas"]["recall@3"] == 1.0


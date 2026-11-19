"""Testes de regressão das correções do Agente de Dashboards.

Cada teste reproduz um erro encontrado no uso real. Nenhum chama o LLM de verdade.
"""
from __future__ import annotations

import pandas as pd
import pytest

import src.dashboard.dashboard_agent as dashboard_agent_mod
from src.dashboard import build_dashboard_from_store
from src.dashboard.dashboard_agent import DASHBOARD_SYSTEM_PROMPT
from src.dashboard.orchestrator import OMITTED_CLAIM_WARNING
from src.dashboard.schemas import MAX_REVISIONS, DatasetResult
from src.dashboard.validator import find_illegality_claim
from src.pipeline.monitor import OutputMonitor
from src.pipeline.result_store import ResultStore


class _Sessao:
    def __init__(self, session_id: str, store: ResultStore):
        self.session_id = session_id
        self.result_store = store
        self.current_spec = None
        self.current_dashboard_path = None


@pytest.fixture
def sessao_ranking(tmp_path) -> _Sessao:
    store = ResultStore(base_dir=tmp_path / "sessions")
    sid = "sessao_correcoes_01"
    store.put(sid, DatasetResult(
        dataset_id="D1", database="soy.duckdb", source_label="Trase — Soja",
        tool_name="soy_top_municipalities", query_summary="soy_top_municipalities()",
        df=pd.DataFrame({"municipality": ["SORRISO", "SAPEZAL", "NOVA MUTUM"],
                         "exposure_ha": [5200.0, 4100.0, 3900.0]}),
    ))
    return _Sessao(sid, store)


def _spec(title: str, subtitle: str = "Origem rastreada (excluindo UNKNOWN), 2022") -> dict:
    return {
        "title": title,
        "subtitle": subtitle,
        "widgets": [{
            "id": "w1", "kind": "bar", "title": "Exposição ao desmatamento por município (2022)",
            "dataset_id": "D1", "x": "municipality", "y": ["exposure_ha"], "unit": "ha",
            "orientation": "h", "source": "Trase — Soja [D1]",
        }],
    }


# --- Erro 2: alegação de ilegalidade bloqueava o painel inteiro --------------------

@pytest.mark.parametrize("termo", [
    "ilegal", "ilegalidade", "crime", "criminoso", "culpado", "violou a lei", "responsável pelo desmatamento",
])
def test_prompt_proibe_termos_do_monitor_mesmo_negados(termo):
    assert termo in DASHBOARD_SYSTEM_PROMPT
    assert "NEM MESMO para negá-las" in DASHBOARD_SYSTEM_PROMPT
    assert "exposição ao desmatamento" in DASHBOARD_SYSTEM_PROMPT


def test_revisao_devolve_alegacao_ao_agente_e_painel_corrigido_passa_no_monitor(monkeypatch, sessao_ranking, tmp_path):
    chamadas: list[str] = []
    problemas_recebidos: list[str] = []

    def fake_llm(**kw):
        chamadas.append(kw["tool_name"])
        if kw["tool_name"] == "emit_review":
            return {"approved": True, "summary": "OK", "issues": []}, 1, 1
        if "Problemas apontados pelo Agente Revisor" in kw["user_content"]:
            problemas_recebidos.append(kw["user_content"])
            return _spec("Municípios com maior exposição ao desmatamento (2022)"), 1, 1
        return _spec("Municípios responsáveis pelo desmatamento ilegal (2022)"), 1, 1

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_llm)
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm", fake_llm)

    res = build_dashboard_from_store("ranking de exposição", sessao_ranking, domain="soy",
                                     output_path=tmp_path / "p.html")

    assert res.revisions_used == 1 and problemas_recebidos
    assert "alegação indevida" in problemas_recebidos[0]
    assert res.spec.title == "Municípios com maior exposição ao desmatamento (2022)"
    assert OutputMonitor().check_dashboard_spec(res.spec).allowed


def test_alegacao_nao_corrigida_nao_bloqueia_painel_pelo_texto_do_revisor(monkeypatch, sessao_ranking, tmp_path):
    """Se a IA insiste no termo, o texto sai; antes, a mensagem do revisor virava aviso e o monitor bloqueava."""
    revisoes = 0

    def fake_llm(**kw):
        nonlocal revisoes
        if kw["tool_name"] == "emit_review":
            return {"approved": True, "summary": "OK", "issues": []}, 1, 1
        if "Problemas apontados" in kw["user_content"]:
            revisoes += 1
        return _spec("Municípios responsáveis pelo desmatamento (2022)",
                     subtitle="Ranking de municípios culpados, 2022"), 1, 1

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_llm)
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm", fake_llm)

    res = build_dashboard_from_store("ranking de exposição", sessao_ranking, domain="soy",
                                     output_path=tmp_path / "p.html")

    assert revisoes == MAX_REVISIONS
    veredito = OutputMonitor().check_dashboard_spec(res.spec)
    assert veredito.allowed, veredito.reason
    assert OMITTED_CLAIM_WARNING in res.spec.warnings
    assert not any(find_illegality_claim(t) for t in [res.spec.title, res.spec.subtitle, *res.spec.warnings])
    assert res.spec.widgets[0].valid  # o gráfico, que estava correto, continua no painel

"""Testes de regressão das correções do Agente de Dashboards.

Cada teste reproduz um erro encontrado no uso real. Nenhum chama o LLM de verdade.
"""
from __future__ import annotations

import re

import duckdb
import pandas as pd
import pytest

import src.dashboard.dashboard_agent as dashboard_agent_mod
from src.dashboard import build_dashboard_from_store
from src.dashboard.dashboard_agent import DASHBOARD_SYSTEM_PROMPT
from src.dashboard.data_agent import DATA_AGENT_PROMPT
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


# --- Erro 1 (dados): evolução dos N maiores municípios ------------------------------

def _sql_de_exemplo_da_serie() -> str:
    trecho = DATA_AGENT_PROMPT[DATA_AGENT_PROMPT.index("Evolução anual dos N maiores"):]
    return re.search(r"Ex\.: `(WITH top AS .+?)`", trecho, flags=re.S).group(1)


def test_prompt_do_agente_de_dados_fixa_ranking_em_um_ano():
    trecho = DATA_AGENT_PROMPT[DATA_AGENT_PROMPT.index("Evolução anual dos N maiores"):][:900]
    assert "ÚNICO ano de referência" in trecho
    assert "Não reclassifique a cada ano" in trecho
    assert "BRAZIL" in trecho and "UNKNOWN" in trecho


def test_sql_de_exemplo_traz_os_10_de_2022_em_todos_os_anos_sem_brasil():
    """Base sintética com colunas VARCHAR (como no soy.duckdb). Armadilhas montadas de propósito:
    - M10 só fica no top 10 de 2022 se contar o destino BRAZIL;
    - M11 é o maior somando todos os anos, mas pequeno em 2022;
    - em 2004 o maior é M12, que não está no top de 2022."""
    linhas = []
    for ano in range(2004, 2023):
        for i in range(10):
            linhas.append((str(ano), f"M{i}", "CHINA", str(1000 - i * 10)))
        linhas.append((str(ano), "M10", "BRAZIL", "50000"))
        linhas.append((str(ano), "M10", "CHINA", "1"))
        linhas.append((str(ano), "M11", "CHINA", "1" if ano == 2022 else "90000"))
        linhas.append((str(ano), "M12", "CHINA", "80000" if ano == 2004 else "2"))
        linhas.append((str(ano), "UNKNOWN", "CHINA", "999999"))
    con = duckdb.connect()
    con.execute("CREATE TABLE soy_supply_chain (year VARCHAR, municipality_of_production VARCHAR, "
                "country_of_first_import VARCHAR, volume VARCHAR)")
    con.executemany("INSERT INTO soy_supply_chain VALUES (?, ?, ?, ?)", linhas)

    df = con.execute(_sql_de_exemplo_da_serie()).df()

    assert sorted(df["municipality"].unique()) == sorted(f"M{i}" for i in range(10))
    assert df.groupby("municipality")["year"].nunique().eq(19).all()
    assert df.loc[df.municipality == "M0", "volume_tonnes"].eq(1000).all()  # BRAZIL fora da série

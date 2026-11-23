from types import SimpleNamespace

import pandas as pd

from src.agent import (
    _Session,
    ask,
    build_fallback_plan,
    validate_retrieval_plan,
)
from src.fts_query import clean_legal_query, extract_legal_subqueries, split_mixed_question
from src.soy.routing import route_question
from src.vector_store import fuse_chunk_lists


def test_routing_identifies_all_mixed_patterns():
    assert route_question(
        "Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022 e qual meta de redução de emissões a Política Nacional sobre Mudança do Clima estabeleceu?"
    )["domain"] == "mixed"
    assert route_question(
        "Qual estado tem a maior área de pastagem e quanto de reserva legal um imóvel em área de floresta na Amazônia Legal precisa manter?"
    )["domain"] == "mixed"
    assert route_question(
        "Que percentual da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero em 2022, e o que é o CAR?"
    )["domain"] == "mixed"
    assert route_question(
        "Qual município teve a maior exposição ao desmatamento na carne bovina em 2023, e qual a pena para quem destrói floresta de preservação permanente?"
    )["domain"] == "mixed"
    # "obrigado" não deve disparar "gado"
    assert route_question(
        "O que é o Cadastro Ambiental Rural (CAR) e quem é obrigado a se inscrever nele?"
    )["domain"] == "law"


def test_split_mixed_question_separates_data_and_legal_clauses_and_resolves_anaphora():
    m04 = "Qual foi a exposição ao desmatamento da soja na Mata Atlântica em 2022 e em que casos a lei proíbe cortar vegetação primária nesse bioma?"
    split = split_mixed_question(m04)
    assert split["is_mixed"] is True
    assert len(split["data_clauses"]) == 1
    assert len(split["legal_clauses"]) == 1
    assert "Mata Atlântica" in split["legal_clauses"][0]
    assert "soja" not in split["legal_clauses"][0].lower()

    m11 = "Qual estado tem a maior capacidade de processamento de soja, e que atividades dependem de licenciamento ambiental prévio?"
    split_11 = split_mixed_question(m11)
    assert split_11["is_mixed"] is True
    assert "soja" not in split_11["legal_clauses"][0].lower()
    assert "licenciamento" in split_11["legal_clauses"][0].lower()


def test_clean_legal_query_strips_supply_chain_noise():
    q = clean_legal_query("licenciamento ambiental prévio atividades de processamento de soja esmagamento de oleaginosas")
    assert "soja" not in q.lower()
    assert "oleaginosas" not in q.lower()
    assert "licenciamento ambiental" in q.lower()


def test_extract_legal_subqueries_expands_canonical_statutes():
    sqs_m05 = extract_legal_subqueries(
        "Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022 e qual meta de redução de emissões a Política Nacional sobre Mudança do Clima estabeleceu?"
    )
    assert len(sqs_m05) >= 2
    assert any("36,1%" in s and "38,9%" in s for s in sqs_m05)

    sqs_m03 = extract_legal_subqueries(
        "Qual grupo exportador de carne bovina teve maior exposição ao desmatamento em 2023 e ele tem compromisso de desmatamento zero? Que multa o Decreto 6.514/2008 prevê para desmatar dentro da reserva legal sem autorização?"
    )
    assert any("art. 51" in s and "em área de reserva legal" in s for s in sqs_m03)


def test_fuse_chunk_lists_deduplicates_and_boosts_consensus_and_diversifies_articles():
    c_12_p1 = {"chunk_id": 1, "title": "Código Florestal", "score": 0.03, "semantic_rank": 1, "keyword_rank": 2,
               "metadata": {"artigo": "12", "parte": 1, "partes": 5}, "content": "Art. 12 p1"}
    c_12_p2 = {"chunk_id": 2, "title": "Código Florestal", "score": 0.028, "semantic_rank": 2, "keyword_rank": 3,
               "metadata": {"artigo": "12", "parte": 2, "partes": 5}, "content": "Art. 12 p2"}
    c_12_p3 = {"chunk_id": 3, "title": "Código Florestal", "score": 0.027, "semantic_rank": 3, "keyword_rank": 4,
               "metadata": {"artigo": "12", "parte": 3, "partes": 5}, "content": "Art. 12 p3"}
    c_3_p1 = {"chunk_id": 4, "title": "Código Florestal", "score": 0.025, "semantic_rank": 4, "keyword_rank": 1,
              "metadata": {"artigo": "3", "parte": 1, "partes": 17}, "content": "Art. 3 p1"}

    list_a = [c_12_p1, c_12_p2, c_12_p3]
    list_b = [c_3_p1, c_12_p1]

    fused = fuse_chunk_lists([list_a, list_b], limit=3, max_per_article=2)
    ids = [c["chunk_id"] for c in fused]
    # c_12_p1 aparece nas duas sub-buscas (1º lugar), e max_per_article=2 impede que a 3ª parte do art. 12 expulse o art. 3º
    assert ids[0] == 1
    assert 4 in ids
    assert 3 not in ids
    assert len(ids) == len(set(ids))


def test_validate_retrieval_plan_never_raises_on_data_to_data_dependencies():
    # Reproduz exatamente o caso que derrubou M03 e M10 na v6
    raw_v6_m03 = {
        "question_type": "mixed",
        "subqueries": [
            {"id": "sq1", "domain": "beef_data", "question": "Qual grupo exportador teve maior exposição em 2023?", "depends_on": []},
            {"id": "sq2", "domain": "beef_data", "question": "Esse grupo tem compromisso de desmatamento zero?", "depends_on": ["sq1"]},
            {"id": "sq3", "domain": "legislation", "question": "Que multa o Decreto 6.514/2008 prevê para desmatar dentro da reserva legal?", "depends_on": []},
        ],
    }
    plan = validate_retrieval_plan(raw_v6_m03)
    assert plan["question_type"] == "mixed"
    assert len(plan["subqueries"]) == 3
    assert plan["subqueries"][1]["depends_on"] == ["sq1"]


def test_validate_retrieval_plan_complements_missing_domain_with_fallback():
    q = "Que percentual da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero em 2022, e o que é o CAR?"
    partial = {
        "question_type": "data",
        "subqueries": [
            {"id": "sq1", "domain": "soy_data", "question": "Percentual de soja ZDC no Mato Grosso em 2022", "depends_on": []},
        ],
    }
    plan = validate_retrieval_plan(partial, fallback_question=q)
    assert plan["question_type"] == "mixed"
    domains = {sq["domain"] for sq in plan["subqueries"]}
    assert "soy_data" in domains and "legislation" in domains


def test_session_deduplicates_law_chunks_and_records_regions(monkeypatch):
    fake_chunks = [
        {"chunk_id": 10, "title": "Lei 12.651/2012", "url": "http://planalto", "content": "Art. 12...",
         "metadata": {"artigo": "12", "parte": 1, "partes": 1}},
        {"chunk_id": 20, "title": "Lei 12.651/2012", "url": "http://planalto", "content": "Art. 3...",
         "metadata": {"artigo": "3", "parte": 1, "partes": 1}},
    ]
    monkeypatch.setattr("src.agent.retrieve_multi", lambda queries, k=6: fake_chunks)
    monkeypatch.setitem(
        __import__("src.agent", fromlist=["QUERY_FUNCS"]).QUERY_FUNCS,
        "soy_deforestation_by_biome",
        lambda year=None: pd.DataFrame({"biome": ["CERRADO", "AMAZONIA"], "exposure_ha": [100.0, 50.0]}),
    )

    session = _Session(k_laws=6, planned_law_queries=["O que o Código Florestal exige de reserva legal?"])
    _, ok_d = session.run("soy_deforestation_by_biome", {"year": 2022})
    assert ok_d
    assert session.discovered_regions == ["CERRADO", "AMAZONIA"]

    out1, ok1 = session.run("search_laws", {"query": "reserva legal por bioma"})
    assert ok1
    assert session.calls[-1].label == "L1-L2"
    assert len(session.law_sources) == 2

    # Segunda chamada retornando os mesmos chunks não duplica law_sources
    out2, ok2 = session.run("search_laws", {"query": "reserva legal Amazônia"})
    assert ok2
    assert len(session.law_sources) == 2
    assert 'rotulo="L1"' in out2 and 'rotulo="L2"' in out2


def test_ask_completeness_guardrail_injects_search_laws_when_skipped(monkeypatch):
    q = "Que percentual da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero em 2022, e o que é o CAR?"
    monkeypatch.setattr("src.agent.soy_queries.is_available", lambda: True)
    monkeypatch.setattr("src.agent.soy_queries.latest_year", lambda: 2022)
    monkeypatch.setattr("src.agent.soy_queries.schema_prompt", lambda: "soy schema")
    monkeypatch.setattr("src.agent.queries.latest_year", lambda: 2023)
    monkeypatch.setattr("src.agent.render_prompt", lambda: "beef dict")
    monkeypatch.setattr(
        "src.agent.decompose_question",
        lambda question, history=None: (build_fallback_plan(question), 10, 10),
    )
    monkeypatch.setitem(
        __import__("src.agent", fromlist=["QUERY_FUNCS"]).QUERY_FUNCS,
        "soy_territorial_metric",
        lambda **kwargs: pd.DataFrame({"year": [2022], "region": ["MATO GROSSO"], "value": [53.1]}),
    )
    monkeypatch.setattr(
        "src.agent.retrieve_multi",
        lambda queries, k=6: [{
            "chunk_id": 29, "title": "Lei nº 12.651/2012 – Código Florestal", "url": "http://planalto",
            "content": "Art. 29. É criado o Cadastro Ambiental Rural - CAR...",
            "metadata": {"artigo": "29", "parte": 1, "partes": 1},
        }],
    )

    responses = [
        # Turno 1: modelo chama apenas a ferramenta de dados (esquecendo search_laws)
        SimpleNamespace(
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            content=[SimpleNamespace(type="tool_use", id="t1", name="soy_territorial_metric",
                                     input={"metric": "zdc_exported_pct", "region": "MATO GROSSO", "year": 2022})],
        ),
        # Turno 2: modelo tenta encerrar sem consultar leis -> guardrail intercepta e injeta search_laws
        SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=120, output_tokens=30),
            content=[SimpleNamespace(type="text", text="Rascunho parcial apenas com [D1].")],
        ),
        # Turno 3: modelo reescreve resposta completa com [D1] e [L1]
        SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=150, output_tokens=50),
            content=[SimpleNamespace(type="text", text="Em 2022 foi 53,1% [D1] e o CAR está no art. 29 [L1].")],
        ),
    ]

    class FakeMessages:
        def create(self, **kwargs):
            return responses.pop(0)

    monkeypatch.setattr("src.agent.get_client", lambda: SimpleNamespace(messages=FakeMessages()))

    ans = ask(q, k_laws=4)
    assert "[D1]" in ans.text and "[L1]" in ans.text
    assert [c.name for c in ans.tool_calls] == ["soy_territorial_metric", "search_laws"]
    assert len(ans.law_sources) == 1

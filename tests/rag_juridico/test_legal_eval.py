import json
from pathlib import Path

import numpy as np
import pytest

from eval.legal_corpus import ROOT, digest, freeze, load_frozen, local_inventory, reconcile
from eval.legal_eval import assemble_context, context_xml, legal_scores, validate_questions
from eval.metrics import chunk_key


def chunk(article="3", part=1, parts=1, text="conteúdo", path="lei.htm"):
    return {"chunk_id": f"{path}:{article}:{part}", "source_path": path,
            "title": "Lei 12.651/2012", "url": 'https://fonte/?a=1&b="2"', "content": text,
            "metadata": {"artigo": article, "parte": part, "partes": parts}}


def question(evidence="definição correta"):
    return {"id": "Q1", "tipo": "lei", "deve_abster": False,
            "artigos": [{"lei": "Lei 12.651/2012", "artigo": "3", "nivel": "essencial"}],
            "evidencias": [{"lei": "Lei 12.651/2012", "artigo": "3", "trecho": evidence}]}


def test_wrong_part_hits_article_but_does_not_satisfy_evidence():
    q = question()
    wrong, correct = chunk(part=1, parts=2), chunk(part=2, parts=2, text="Definição   correta")
    scores = legal_scores(q, [wrong, correct])
    assert scores["hit@1"] == 1
    assert scores["evidence_recall@1"] == 0
    assert scores["evidence_complete@3"] == 1
    assert legal_scores(q, [chunk(text="definição correta", path="outra.htm")])["hit@1"] == 1
    another_law = chunk(text="definição correta")
    another_law["title"] = "Lei 9.605/1998"
    assert legal_scores(q, [another_law])["evidence_recall@1"] == 0


def test_negative_questions_not_in_ranking_denominator():
    assert legal_scores({"deve_abster": True}, [chunk()]) == {
        "ranking_applicable": False, "abstention_review": "pending_generation"}


def test_sibling_context_expansion_respects_whole_chunk_budget_and_xml():
    first = chunk(part=1, parts=2, text="primeiro <trecho>")
    second = chunk(part=2, parts=2, text="segundo")
    context = assemble_context([second, first], [first, second], len, mode="siblings", k=3, budget=10000)
    assert context == [first, second]
    assert "&lt;trecho&gt;" in context_xml(context)
    from xml.etree.ElementTree import fromstring
    assert len(fromstring(context_xml(context))) == 2
    budget = len(context_xml([first]))
    context = assemble_context([second], [first, second], len, mode="siblings", k=3, budget=budget)
    assert context == [first]
    assert assemble_context([first], [first], len, budget=1) == []


def test_snapshot_detects_content_change_and_refuses_empty(tmp_path):
    row = chunk()
    frozen = freeze([row], "database", "manifest-hash", {})
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(frozen))
    assert load_frozen(path) == frozen
    frozen["chunks"][0]["content"] = "modificado"
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match="Fingerprint"):
        load_frozen(path)
    with pytest.raises(ValueError):
        freeze([], "database", "x", {})


def test_audit_detects_missing_extra_stale_and_incomplete_parts():
    local = {"documents": [{"file": "lei.htm", "sha256": "novo", "actual_sha256": "novo",
                             "article_numbers": ["3", "4"]},
                            {"file": "faltando.htm", "article_numbers": ["1"]}]}
    def row(path, part):
        return {**chunk(part=part, parts=2, path=path), "sha256": "antigo", "embedding_model": "e5",
                "document_metadata": {}, "embedding_dim": 384}
    audited = reconcile(local, [row("lei.htm", 1), row("extra.htm", 1)])
    assert audited["missing_documents"] == ["faltando.htm"]
    assert audited["extra_documents"] == ["extra.htm"]
    doc = audited["documents"][0]
    assert not doc["hash_matches_file"]
    assert doc["missing_articles"] == ["4"]
    assert doc["invalid_article_parts"] == ["3"]


def test_all_gold_evidence_exists_in_actual_parser_output():
    from src.law_parser import parse_law_file
    inventory = local_inventory()
    assert len(inventory["documents"]) == 29
    assert all(d["hash_matches"] for d in inventory["documents"])
    assert all(not d["duplicate_articles"] for d in inventory["documents"])
    chunks = []
    for d in inventory["documents"]:
        for article in parse_law_file(ROOT / d["file"])[1]:
            chunks.append({"title": d["title"], "metadata": {"artigo": article.number},
                           "content": "\n".join(article.paragraphs)})
    items = [json.loads(line) for line in (ROOT / "eval/perguntas_juridicas.jsonl").read_text().splitlines()]
    validate_questions(items, chunks)
    assert len(items) == 48
    assert sum(i["deve_abster"] for i in items) == 6
    assert len({chunk_key(c)[0] for c in chunks}) == 29


def test_similarity_does_not_load_retrieval_model(monkeypatch):
    from eval import text_metrics
    loaded = []
    class FakeModel:
        def __init__(self, model_id, **kwargs):
            loaded.append((model_id, kwargs))
        def encode(self, texts, **kwargs):
            return np.ones((len(texts), 2))
    import sentence_transformers
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", FakeModel)
    monkeypatch.setenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    text_metrics.get_similarity_model.cache_clear()
    try:
        text_metrics._embed_pair_texts(["resposta", "referência"])
        assert loaded == [(text_metrics.SIMILARITY_MODEL, {"revision": text_metrics.SIMILARITY_REVISION})]
        assert text_metrics.SIMILARITY_MODEL == "BAAI/bge-m3"
        assert text_metrics.HISTORICAL_SIMILARITY_MODEL == "intfloat/multilingual-e5-small"
    finally:
        text_metrics.get_similarity_model.cache_clear()


def test_window_context_preserves_top_ranking_and_expands_neighbors():
    art3_parts = [chunk(article="3", part=i, parts=5, text=f"parte {i}") for i in range(1, 6)]
    art12 = chunk(article="12", part=1, parts=1, text="reserva legal 80%")
    art15 = chunk(article="15", part=1, parts=1, text="computo de APP")
    art26 = chunk(article="26", part=1, parts=1, text="autorizacao CAR")
    art29 = chunk(article="29", part=1, parts=1, text="cadastro ambiental")
    ranked = [art3_parts[2], art3_parts[4], art12, art15, art26, art29]
    context = assemble_context(ranked, art3_parts + [art12, art15, art26, art29], len, mode="window", k=6, budget=10000)
    assert [c["chunk_id"] for c in context[:5]] == [c["chunk_id"] for c in ranked[:5]]
    assert context[5]["metadata"]["artigo"] == "3"
    assert context[5]["metadata"]["parte"] == 1


def test_ingest_laws_reindexes_on_model_or_chunking_change_and_keeps_default_chunk_limit(monkeypatch, tmp_path):
    from src import ingest_laws
    from src.law_parser import Article

    manifest = tmp_path / "manifest.json"
    entry = {
        "file": "docs/leis/fake.htm",
        "title": "Lei Fake",
        "doc_type": "law",
        "url": "https://example.com/fake",
        "retrieved_at": "2026-11-06",
        "sha256": "abc",
    }
    manifest.write_text(json.dumps([entry]), encoding="utf-8")
    monkeypatch.setattr(ingest_laws, "MANIFEST", manifest)
    monkeypatch.setattr(ingest_laws, "max_model_tokens", lambda: 8192)
    monkeypatch.setattr(ingest_laws, "count_chunk_tokens", lambda text: len(text.split()))
    monkeypatch.setattr(ingest_laws, "embed_passages", lambda texts: np.ones((len(texts), 2)))
    monkeypatch.setattr(ingest_laws, "parse_law_file", lambda _: (None, [Article("1", [], ["Art. 1º Texto."])]))

    upserts = []
    monkeypatch.setattr(ingest_laws.vector_store, "upsert_document", lambda *a, **kw: upserts.append(kw["metadata"]))

    # Mesmo sha256, mas modelo diferente no índice -> deve reindexar e manter limite padrão de 480 tokens.
    monkeypatch.setattr(ingest_laws, "EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setattr(
        ingest_laws.vector_store,
        "get_document_index_info",
        lambda _: {"sha256": "abc", "embedding_model": "intfloat/multilingual-e5-small",
                   "metadata": {"chunking": "por artigo, max 480 tokens; artigos longos em partes de 256"}},
    )
    ingest_laws.ingest_laws()
    assert len(upserts) == 1
    assert "max 480 tokens" in upserts[0]["chunking"]

    # Mesmo sha256, mesmo modelo e mesmo chunking -> deve pular.
    upserts.clear()
    monkeypatch.setattr(
        ingest_laws.vector_store,
        "get_document_index_info",
        lambda _: {"sha256": "abc", "embedding_model": "BAAI/bge-m3",
                   "metadata": {"chunking": "por artigo, max 480 tokens; artigos longos em partes de 256"}},
    )
    ingest_laws.ingest_laws()
    assert upserts == []


def test_hybrid_rrf_candidates_merges_semantic_and_keyword_ranks(monkeypatch):
    from eval import legal_eval

    corpus = [chunk(article=str(i), text=f"artigo {i}") for i in range(1, 5)]
    scores = np.array([0.9, 0.2, 0.8, 0.1])
    lookup = {(c["source_path"], str(c["metadata"]["artigo"]), int(c["metadata"]["parte"])): i for i, c in enumerate(corpus)}
    monkeypatch.setattr(legal_eval, "_lexical_idf_ranks", lambda q, limit, lk: {1: 1, 2: 2})
    cands = legal_eval._hybrid_rrf_candidates(scores, corpus, "consulta", 4, lookup)
    # Chunk 1 (sem=3, kw=1) -> 1/63 + 1/61 = 0.032266; Chunk 2 (sem=2, kw=2) -> 2/62 = 0.032258
    assert cands[0]["chunk_id"] == corpus[1]["chunk_id"]
    assert cands[1]["chunk_id"] == corpus[2]["chunk_id"]
    assert cands[0]["semantic_rank"] == 3 and cands[0]["keyword_rank"] == 1
    assert cands[1]["semantic_rank"] == 2 and cands[1]["keyword_rank"] == 2


def test_check_abstention_response_detects_missing_scope():
    from eval.legal_eval import _check_abstention_response

    assert _check_abstention_response("O acervo recuperado não contém o Anexo VIII da Lei 6.938/1981.")["abstained"] is True
    assert _check_abstention_response("Os trechos recuperados não incluem a Lei nº 14.119/2021, então não tenho base.")["abstained"] is True
    assert _check_abstention_response("A multa prevista no art. 52 é de R$ 1.000,00 por hectare.")["abstained"] is False


def test_diverse_law_context_reserves_slots_across_norms():
    cf1 = chunk(article="26", path="cf.htm", text="supressão")
    cf2 = chunk(article="27", path="cf.htm", text="outra regra")
    cf3 = chunk(article="28", path="cf.htm", text="mais uma")
    pnma = chunk(article="10", path="pnma.htm", text="licenciamento")
    ranked = [cf1, cf2, cf3, pnma]
    context = assemble_context(ranked, ranked, len, mode="diverse_law", k=4, budget=10000)
    assert [c["source_path"] for c in context[:2]] == ["cf.htm", "pnma.htm"]


def test_decompose_legal_query_handles_comparative_and_simple_questions():
    from eval.legal_eval import decompose_legal_query

    q_rel = "Como se relacionam a exigência geral de licenciamento e a supressão de vegetação?"
    assert decompose_legal_query(q_rel) == [q_rel, "a exigência geral de licenciamento", "a supressão de vegetação"]
    q_simple = "Qual é a função da reserva legal no Código Florestal?"
    assert decompose_legal_query(q_simple) == [q_simple]


def test_count_chunk_tokens_keeps_passage_headroom_for_bge_m3(monkeypatch):
    from src import embeddings

    seen_inputs = []

    class FakeTokenizer:
        def encode(self, text, add_special_tokens=True):
            seen_inputs.append(text)
            return list(text)

    class FakeModel:
        tokenizer = FakeTokenizer()

    monkeypatch.setattr(embeddings, "EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setattr(embeddings, "get_model", lambda: FakeModel())
    assert embeddings.count_tokens("artigo") == len("artigo")
    assert embeddings.count_chunk_tokens("artigo") == len("passage: artigo")
    assert seen_inputs == ["artigo", "passage: artigo"]


def test_hybrid_rrf_candidates_respects_calibrated_lexical_weight(monkeypatch):
    from eval import legal_eval

    corpus = [chunk(article=str(i), text=f"artigo {i}") for i in range(1, 5)]
    scores = np.array([0.9, 0.2, 0.8, 0.1])
    lookup = {(c["source_path"], str(c["metadata"]["artigo"]), int(c["metadata"]["parte"])): i for i, c in enumerate(corpus)}
    monkeypatch.setattr(legal_eval, "_lexical_idf_ranks", lambda q, limit, lk: {1: 1, 2: 30})
    # Com RRF 50/50 (1.0), um acerto lexical forte distante no ranking semântico ultrapassa o top-1 semântico.
    cands_50_50 = legal_eval._hybrid_rrf_candidates(scores, corpus, "consulta", 4, lookup, lexical_weight=1.0)
    assert cands_50_50[0]["chunk_id"] == corpus[1]["chunk_id"]
    # Com peso fino (0.02), o top-1 semântico (chunk 0) mantém a 1ª posição.
    cands_cal = legal_eval._hybrid_rrf_candidates(scores, corpus, "consulta", 4, lookup, lexical_weight=0.02)
    assert cands_cal[0]["chunk_id"] == corpus[0]["chunk_id"]


def test_rag_retrieve_decomposes_and_expands_siblings(monkeypatch):
    from src import rag, vector_store

    assert vector_store.LEXICAL_RRF_WEIGHT == 0.02
    c_art2_p1 = {**chunk(article="2", part=1, parts=2, path="pnmc.htm", text="mitigação"), "score": 0.015}
    c_art2_p2 = {**chunk(article="2", part=2, parts=2, path="pnmc.htm", text="adaptação"), "score": 0.016}
    c_art38 = {**chunk(article="38", part=1, parts=1, path="crimes.htm", text="pena"), "score": 0.017}

    queries_seen = []

    monkeypatch.setattr(rag, "embed_query", lambda q: np.zeros(4, dtype=np.float32))

    def fake_hybrid_search(query_text, emb, limit=5, candidates=40, doc_type=None):
        queries_seen.append(query_text)
        if "pena" in query_text:
            return [c_art38, c_art2_p2]
        return [c_art2_p2, c_art38]

    monkeypatch.setattr(rag.vector_store, "hybrid_search", fake_hybrid_search)
    monkeypatch.setattr(rag.vector_store, "get_article_siblings", lambda path, art: [c_art2_p1, c_art2_p2])

    q = "Qual a diferença entre pena por APP e adaptação e mitigação?"
    res = rag.retrieve(q, k=3)
    assert len(queries_seen) == 3
    assert [c["chunk_id"] for c in res] == [
        c_art38["chunk_id"],
        c_art2_p1["chunk_id"],
        c_art2_p2["chunk_id"],
    ]

    ranked_only = rag.retrieve("O que é área consolidada?", k=2, context_mode="ranked")
    assert [c["chunk_id"] for c in ranked_only] == [c_art2_p2["chunk_id"], c_art38["chunk_id"]]


def test_decompose_v2_and_tail_sibling_prioritization(monkeypatch):
    from src import rag
    from src.law_parser import parse_law

    # 1. Múltiplas interrogações, conectivo interrogativo e "tanto ... quanto ..."
    q_multi = "Quando depende de CAR? E quais atividades precisam de licenciamento?"
    assert rag.decompose_legal_query(q_multi) == [
        q_multi,
        "Quando depende de CAR",
        "quais atividades precisam de licenciamento",
    ]
    q_conn = "Qual a pena criminal por destruir APP e qual a multa por desmatar reserva legal?"
    assert rag.decompose_legal_query(q_conn) == [
        q_conn,
        "Qual a pena criminal por destruir APP",
        "qual a multa por desmatar reserva legal",
    ]
    q_both = "O que muda tanto na esfera penal quanto na esfera administrativa?"
    assert rag.decompose_legal_query(q_both) == [
        q_both,
        "O que muda na esfera penal",
        "O que muda na esfera administrativa",
    ]

    # 2. Parte final (ex.: parte 16/17) não é descartada quando k=6
    parts = [{**chunk(article="3", part=i, parts=17, text=f"parte {i}"), "score": 0.01} for i in range(1, 18)]
    ranked = [{**parts[15], "score": 0.02}]  # parte 16 em 1º
    monkeypatch.setattr(rag, "embed_query", lambda q: np.zeros(4, dtype=np.float32))
    monkeypatch.setattr(rag.vector_store, "hybrid_search", lambda q, emb, limit=5, doc_type=None: ranked)
    monkeypatch.setattr(rag.vector_store, "get_article_siblings", lambda path, art: parts)

    res = rag.retrieve("Como define crédito de carbono?", k=6)
    got_parts = [c["metadata"]["parte"] for c in res]
    assert got_parts[0] == 1
    assert 16 in got_parts
    assert len(res) == 6

    # 3. Parser junta dígito de artigo partido em tag HTML ("Art. 1 8.") e extrai ementa começando com "Fixa"
    html = "<p>Fixa normas gerais.</p><p>Art. 1 8. Texto do artigo 18.</p>"
    ementa, articles = parse_law(html)
    assert ementa == "Fixa normas gerais."
    assert [a.number for a in articles] == ["18"]

    # 4. _diversify_subquery_laws promove a primeira ocorrência de cada norma distinta em subconsultas inter-normas
    l1_a = chunk(article="58", path="l15190.htm", text="a")
    l1_b = chunk(article="13", path="l15190.htm", text="b")
    l2_a = chunk(article="10", path="pnma.htm", text="c")
    assert [c["chunk_id"] for c in rag._diversify_subquery_laws([l1_a, l1_b, l2_a])] == [
        l1_a["chunk_id"],
        l2_a["chunk_id"],
        l1_b["chunk_id"],
    ]

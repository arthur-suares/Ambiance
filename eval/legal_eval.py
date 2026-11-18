"""Avaliação jurídica isolada sobre chunks congelados; não altera o Postgres.

python -m eval.legal_eval --corpus /tmp/leis.json --model e5-small --saida /tmp/baseline
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import time
from importlib.metadata import version

import numpy as np

from eval.legal_corpus import ROOT, digest, load_frozen, write_json
from eval.metrics import article_key, chunk_key, first_positions, gold_sets, ranking_scores
from eval.text_metrics import (
    HISTORICAL_SIMILARITY_MODEL,
    HISTORICAL_SIMILARITY_REVISION,
    SIMILARITY_MODEL,
    SIMILARITY_REVISION,
)
from src.rag import _interleave_candidates, decompose_legal_query

QUESTIONS = ROOT / "eval/perguntas_juridicas.jsonl"
MODELS = {"e5-small": "intfloat/multilingual-e5-small",
          "e5-large": "intfloat/multilingual-e5-large", "bge-m3": "BAAI/bge-m3"}


def plain(text):
    return re.sub(r"\s+", " ", text).strip().casefold()


def evidence_found(evidence: dict, chunks: list[dict]) -> bool:
    key = article_key(evidence["lei"], evidence["artigo"])
    return any(chunk_key(c) == key and plain(evidence["trecho"]) in plain(c["content"]) for c in chunks)


def validate_questions(items: list[dict], chunks: list[dict]):
    if not items or len({i["id"] for i in items}) != len(items):
        raise ValueError("Perguntas vazias ou IDs duplicados.")
    for item in items:
        if item["tipo"] != "lei":
            raise ValueError("Esta suíte aceita apenas leis.")
        if item["deve_abster"]:
            if item["evidencias"] or item["artigos"]:
                raise ValueError(f"{item['id']}: abstenção não recebe qrels positivos.")
        elif not item["evidencias"]:
            raise ValueError(f"{item['id']}: sem evidências.")
        for e in item["evidencias"]:
            if not evidence_found(e, chunks):
                raise ValueError(f"{item['id']}: evidência ausente dos chunks: {e}")


def legal_scores(item: dict, chunks: list[dict], ks=(1, 3, 5, 10)) -> dict:
    # Negativos não são erros de retrieval: precisam de avaliação da resposta.
    if item["deve_abster"]:
        return {"ranking_applicable": False, "abstention_review": "pending_generation"}
    essential, all_articles = gold_sets(item)
    result = ranking_scores(first_positions(chunks), essential, all_articles, ks)
    result["ranking_applicable"] = True
    for k in ks:
        flags = [evidence_found(e, chunks[:k]) for e in item["evidencias"]]
        result[f"evidence_recall@{k}"] = sum(flags) / len(flags)
        result[f"evidence_complete@{k}"] = float(all(flags))
    return result


def _expand_window_group(seed: dict, corpus: list[dict]) -> list[dict]:
    """Para artigo multi-parte, traz o próprio trecho, parte 1 (caput) e vizinhos imediatos."""
    siblings = sorted(
        [c for c in corpus if c["source_path"] == seed["source_path"] and chunk_key(c) == chunk_key(seed)],
        key=lambda c: c["metadata"].get("parte", 1),
    )
    if len(siblings) <= 1:
        return [seed]
    seed_part = seed["metadata"].get("parte", 1)
    by_part = {c["metadata"].get("parte", 1): c for c in siblings}
    ordered = [seed]
    for candidate_part in (1, seed_part - 1, seed_part + 1):
        c = by_part.get(candidate_part)
        if c and c["chunk_id"] != seed["chunk_id"] and c not in ordered:
            ordered.append(c)
    return ordered


def assemble_context(ranked: list[dict], corpus: list[dict], count, *, mode="ranked", k=6, budget=2400):
    """Inclui apenas chunks inteiros com limite de k e orçamento XML fixo.

    Modos:
    - "ranked": ordem do ranking;
    - "siblings": expande todas as partes do mesmo artigo, em ordem;
    - "window": preserva o top (k - 1) e usa a vaga restante para trazer caput/vizinho de artigos multi-parte;
    - "diverse_law": reserva vagas iniciais para diplomas distintos (até min(3, k // 2)) e completa pelo ranking.
    """
    if mode not in {"ranked", "siblings", "window", "diverse_law"} or min(k, budget) < 1:
        raise ValueError("Modo, k ou orçamento de contexto inválido.")
    selected, seen = [], set()

    def try_add(c: dict) -> bool:
        if c["chunk_id"] in seen or len(selected) >= k:
            return False
        if count(context_xml(selected + [c])) <= budget:
            seen.add(c["chunk_id"])
            selected.append(c)
            return True
        return False

    if mode == "diverse_law":
        seen_laws = set()
        diverse_limit = max(1, min(3, k // 2))
        for c in ranked:
            if c["source_path"] not in seen_laws and try_add(c):
                seen_laws.add(c["source_path"])
                if len(seen_laws) >= diverse_limit:
                    break
        for c in ranked:
            try_add(c)
            if len(selected) >= k:
                return selected
        return selected

    if mode == "window":
        preserved = []
        for c in ranked[:max(1, k - 1)]:
            if try_add(c):
                preserved.append(c)
        for seed in preserved:
            if seed["metadata"].get("partes", 1) > 1:
                for c in _expand_window_group(seed, corpus):
                    if try_add(c):
                        break
            if len(selected) >= k:
                return selected
        for c in ranked:
            try_add(c)
            if len(selected) >= k:
                return selected
        return selected

    for seed in ranked:
        group = [seed]
        if mode == "siblings":
            group = sorted([c for c in corpus if c["source_path"] == seed["source_path"]
                            and chunk_key(c) == chunk_key(seed)],
                           key=lambda c: c["metadata"].get("parte", 1))
        for c in group:
            try_add(c)
            if len(selected) >= k:
                return selected
    return selected


def context_xml(chunks: list[dict]) -> str:
    from xml.sax.saxutils import escape, quoteattr
    docs = []
    for i, c in enumerate(chunks, 1):
        m = c["metadata"]
        attrs = {"indice": i, "lei": c["title"], "artigo": m["artigo"],
                 "parte": f"{m.get('parte', 1)}/{m.get('partes', 1)}", "fonte": c["url"]}
        tag = " ".join(f"{key}={quoteattr(str(value))}" for key, value in attrs.items())
        docs.append(f"<documento {tag}>\n{escape(c['content'])}\n</documento>")
    return "<documentos>\n" + "\n".join(docs) + "\n</documentos>"


def mean_scores(records: list[dict], field="metrics") -> dict:
    positive = [r[field] for r in records if not r["deve_abster"]]
    keys = {key for r in positive for key in r if key != "ranking_applicable"}
    return {key: sum(r[key] for r in positive if r.get(key) is not None) /
            sum(r.get(key) is not None for r in positive)
            for key in sorted(keys) if any(r.get(key) is not None for r in positive)}


def _configure_reranker(reranker):
    """Evita truncamento quando o modelo suporta mais que o default de 512 tokens."""
    model_max = getattr(getattr(getattr(reranker, "model", None), "config", None), "max_position_embeddings", None)
    if isinstance(model_max, int) and model_max >= 1026:
        limit = min(1024, model_max - 2)
        if hasattr(reranker, "max_seq_length"):
            reranker.max_seq_length = limit
        else:
            reranker.max_length = limit
    return reranker


def _resolve_reranker_revision(model_id: str, reranker) -> str | None:
    cfg = getattr(getattr(reranker, "model", None), "config", None)
    commit_hash = getattr(cfg, "_commit_hash", None) if cfg is not None else None
    if commit_hash:
        return commit_hash
    from huggingface_hub import try_to_load_from_cache
    config_path = try_to_load_from_cache(model_id, "config.json")
    if isinstance(config_path, str):
        return Path(config_path).parent.name
    return None


def _lexical_idf_ranks(query_text: str, limit: int, chunk_lookup: dict[tuple[str, str, int], int]) -> dict[int, int]:
    """Ranking lexical IDF do Postgres (src/vector_store + src/fts_query) mapeado aos índices do corpus."""
    from src.config import FTS_CONFIG
    from src.fts_query import extract_terms, weight_terms
    from src.vector_store import _term_doc_freq, get_connection

    pool = extract_terms(query_text)
    if not pool:
        return {}
    with get_connection(register=False) as con:
        con.execute("SET TRANSACTION READ ONLY")
        n_docs, doc_freq = _term_doc_freq(con, pool, "law")
        weighted = weight_terms(pool, doc_freq, n_docs)
        terms, weights = [t for t, _ in weighted], [w for _, w in weighted]
        if not terms:
            return {}
        fts_text = " or ".join(terms)
        rows = con.execute(
            f"""
            SELECT d.source_path, c.metadata,
                   ts_rank_cd(c.tsv, q) AS text_rank,
                   (SELECT COALESCE(SUM(t.w), 0)
                      FROM unnest(%(terms)s::text[], %(weights)s::float8[]) AS t(term, w)
                     WHERE c.tsv @@ websearch_to_tsquery('{FTS_CONFIG}', t.term)) AS idf_score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id,
                 websearch_to_tsquery('{FTS_CONFIG}', %(query)s) q
            WHERE c.tsv @@ q
              AND d.doc_type = 'law'
            ORDER BY idf_score DESC, text_rank DESC
            LIMIT %(limit)s
            """,
            {"terms": terms, "weights": weights, "query": fts_text, "limit": limit},
        ).fetchall()
    kw_ranks: dict[int, int] = {}
    for rank, row in enumerate(rows, start=1):
        meta = row["metadata"] or {}
        key = (row["source_path"], str(meta.get("artigo")), int(meta.get("parte", 1)))
        idx = chunk_lookup.get(key)
        if idx is not None:
            kw_ranks[idx] = rank
    return kw_ranks


def _hybrid_rrf_candidates(
    scores: np.ndarray,
    corpus: list[dict],
    query_text: str,
    candidates: int,
    chunk_lookup: dict[tuple[str, str, int], int],
    rrf_k: int = 60,
    lexical_weight: float = 1.0,
) -> list[dict]:
    sem_positions = np.argsort(-scores, kind="stable")[:candidates]
    sem_ranks = {int(pos): rank for rank, pos in enumerate(sem_positions, start=1)}
    kw_ranks = _lexical_idf_ranks(query_text, candidates, chunk_lookup)
    fused_ids = set(sem_ranks) | set(kw_ranks)
    scored = []
    for idx in fused_ids:
        sr = sem_ranks.get(idx)
        kr = kw_ranks.get(idx)
        rrf_score = (1.0 / (rrf_k + sr) if sr else 0.0) + (lexical_weight / (rrf_k + kr) if kr else 0.0)
        scored.append((rrf_score, float(scores[idx]), idx, sr, kr))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    out = []
    for rrf_score, cos_score, idx, sr, kr in scored[:candidates]:
        out.append({
            **corpus[idx],
            "score": rrf_score,
            "semantic_score": cos_score,
            "semantic_rank": sr,
            "keyword_rank": kr,
        })
    return out


def _load_generation_dependencies():
    """Carrega cliente Anthropic/OpenRouter e LAW_SYSTEM_PROMPT mesmo sem duckdb instalado."""
    try:
        from src.rag import LAW_SYSTEM_PROMPT, get_client
    except ModuleNotFoundError as exc:
        if exc.name != "duckdb":
            raise
        import sys
        import types
        sys.modules.setdefault("duckdb", types.SimpleNamespace())
        from src.rag import LAW_SYSTEM_PROMPT, get_client
    return get_client, LAW_SYSTEM_PROMPT


_ABSTENTION_RE = re.compile(
    r"(não (?:há|consta|constam|está|estão|foi|foram|contém|possui|inclu[ei]|incluem|permite|é possível|tenho (?:base|como)|encontr|identific|dispon|abrang|cobr)|"
    r"aus[êe]ncia|fora do|indispon[ií]vel|insuficiente|sem base|não bastam|não traz|limita-se|apenas .* snapshot|"
    r"anexo.*(?:não|exclu|fora|ausente)|não atest|exige dados|necess[áa]rios? (?:dados|documentos|an[áa]lise|consultar))",
    re.I,
)


def _check_abstention_response(text: str) -> dict:
    match = _ABSTENTION_RE.search(text or "")
    return {"abstained": bool(match), "matched_cue": match.group(0) if match else None}


def _summarize_generation(records: list[dict]) -> dict:
    def avg_group(rows: list[dict]) -> dict:
        if not rows:
            return {}
        return {
            "n": len(rows),
            "cosine": sum(r["text_metrics"]["cosine"]["cosseno"] for r in rows) / len(rows),
            "rouge_l_f1": sum(r["text_metrics"]["rouge_l"]["f1"] for r in rows) / len(rows),
            "bleu": sum(r["text_metrics"]["bleu"]["bleu"] for r in rows) / len(rows),
            "truncated_responses": sum(bool(r["text_metrics"]["cosine"]["truncada_resposta"]) for r in rows),
            "input_tokens_mean": sum(r["input_tokens"] for r in rows) / len(rows),
            "output_tokens_mean": sum(r["output_tokens"] for r in rows) / len(rows),
        }

    positive = [r for r in records if not r["deve_abster"]]
    abstention = [r for r in records if r["deve_abster"]]
    return {
        "positive": avg_group(positive),
        "abstention": {
            **avg_group(abstention),
            "abstention_rate": sum(bool(r["abstention_check"]["abstained"]) for r in abstention) / len(abstention)
            if abstention else None,
            "per_question": {r["id"]: r["abstention_check"] for r in abstention},
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--model", choices=MODELS, default="e5-small")
    ap.add_argument("--revision", help="revisão Hugging Face do candidato; registrada na configuração")
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--candidates", type=int, default=40)
    ap.add_argument("--context-k", type=int, default=6)
    ap.add_argument("--context-budget", type=int, default=2400)
    ap.add_argument("--context-mode", choices=("ranked", "siblings", "window", "diverse_law"), default="ranked")
    ap.add_argument("--retrieval", choices=("exact_dense_cosine", "hybrid_rrf"), default="exact_dense_cosine")
    ap.add_argument("--lexical-weight", type=float, default=1.0,
                    help="peso do canal lexical no RRF quando --retrieval=hybrid_rrf")
    ap.add_argument("--decompose", action="store_true",
                    help="decompõe perguntas comparativas/multinorma em subconsultas determinísticas")
    ap.add_argument("--reranker", help="CrossEncoder, por exemplo BAAI/bge-reranker-v2-m3")
    ap.add_argument("--reuse-embeddings", type=Path,
                    help="reutiliza embeddings.npy de outra rodada do mesmo modelo e corpus")
    ap.add_argument("--generate", action="store_true", help="gera respostas via LLM configurado e calcula métricas de texto")
    ap.add_argument("--local-files-only", action="store_true")
    args = ap.parse_args()
    if args.candidates < 10 or min(args.context_k, args.context_budget) < 1:
        ap.error("Use candidates >= 10 e contexto/orçamento positivos.")
    if args.saida.exists() and any(args.saida.iterdir()):
        ap.error("Pasta de saída não está vazia; preserve as rodadas anteriores.")
    frozen = load_frozen(args.corpus)
    corpus = frozen["chunks"]
    items = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    validate_questions(items, corpus)
    from sentence_transformers import SentenceTransformer, CrossEncoder
    from transformers import AutoTokenizer
    model_id = MODELS[args.model]
    revision = args.revision or (HISTORICAL_SIMILARITY_REVISION if args.model == "e5-small" else None)
    model = SentenceTransformer(model_id, revision=revision, local_files_only=args.local_files_only)
    from huggingface_hub import try_to_load_from_cache
    config_path = try_to_load_from_cache(model_id, "config.json", revision=revision)
    if isinstance(config_path, str):
        revision = Path(config_path).parent.name
    e5 = args.model.startswith("e5-")
    passage_prefix, query_prefix = ("passage: ", "query: ") if e5 else ("", "")
    passages = [passage_prefix + c["content"] for c in corpus]
    queries = [query_prefix + item["pergunta"] for item in items]
    limit = model.max_seq_length
    # Recusa truncamento: jamais adapta os chunks ao candidato.
    lengths = [len(model.tokenizer.encode(text, truncation=False)) for text in passages + queries]
    if max(lengths) > limit:
        raise ValueError(f"{model_id}: {max(lengths)} tokens excedem {limit}; recrie um único corpus comum a todos.")
    tokenizer = AutoTokenizer.from_pretrained(HISTORICAL_SIMILARITY_MODEL, revision=HISTORICAL_SIMILARITY_REVISION,
                                            local_files_only=args.local_files_only)
    def count(text):
        return len(tokenizer.encode(text, truncation=False))
    if args.reuse_embeddings:
        embeddings = np.load(args.reuse_embeddings)
        dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        if embeddings.shape != (len(corpus), dim()):
            raise ValueError(f"Embeddings reutilizados incompatíveis: {embeddings.shape} != {(len(corpus), dim())}.")
        index_seconds = 0.0
    else:
        start = time.perf_counter()
        embeddings = model.encode(passages, normalize_embeddings=True, batch_size=16, show_progress_bar=True)
        index_seconds = time.perf_counter() - start
    # Vetores isolados por rodada, sem reset ou escrita no banco compartilhado.
    args.saida.mkdir(parents=True, exist_ok=True)
    if not args.reuse_embeddings:
        np.save(args.saida / "embeddings.npy", embeddings)
    reranker = _configure_reranker(CrossEncoder(args.reranker, local_files_only=args.local_files_only)) if args.reranker else None
    reranker_max_length = (getattr(reranker, "max_seq_length", None) or getattr(reranker, "max_length", None)) if reranker else None
    config = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "model": model_id, "model_revision": revision,
              "dimension": embeddings.shape[1], "corpus_sha256": frozen["corpus_sha256"],
              "corpus_origin": frozen["origin"], "questions_sha256": digest(items),
              "similarity_model": SIMILARITY_MODEL, "similarity_revision": SIMILARITY_REVISION,
              "context_tokenizer": HISTORICAL_SIMILARITY_MODEL,
              "passage_prefix": passage_prefix, "query_prefix": query_prefix,
              "retrieval": args.retrieval, "lexical_weight": args.lexical_weight, "decompose": args.decompose, "candidates": args.candidates,
              "reranker": args.reranker,
              "reranker_max_length": reranker_max_length,
              "reranker_revision": _resolve_reranker_revision(args.reranker, reranker) if reranker else None,
              "reused_embeddings": str(args.reuse_embeddings) if args.reuse_embeddings else None,
              "context_mode": args.context_mode, "context_k": args.context_k,
              "context_budget": args.context_budget, "index_seconds": index_seconds,
              "generation": args.generate, "python": platform.python_version(),
              "versions": {p: version(p) for p in ("sentence-transformers", "transformers", "numpy")}}
    if args.generate:
        from src.config import LLM_MODEL
        get_client, LAW_SYSTEM_PROMPT = _load_generation_dependencies()
        config.update(generation_model=LLM_MODEL, prompt_sha256=digest(LAW_SYSTEM_PROMPT))
    write_json(args.saida / "config.json", config)
    chunk_lookup = {
        (c["source_path"], str(c["metadata"].get("artigo")), int(c["metadata"].get("parte", 1))): i
        for i, c in enumerate(corpus)
    }
    records = []
    with (args.saida / "details.jsonl").open("w", encoding="utf-8") as out:
        for item, query in zip(items, queries):
            start = time.perf_counter()
            subqueries = decompose_legal_query(item["pergunta"]) if args.decompose else [item["pergunta"]]
            if len(subqueries) > 1:
                lists = []
                for sq in subqueries:
                    v = model.encode(query_prefix + sq, normalize_embeddings=True)
                    sc = embeddings @ v
                    if args.retrieval == "hybrid_rrf":
                        lists.append(_hybrid_rrf_candidates(
                            sc, corpus, sq, args.candidates, chunk_lookup, lexical_weight=args.lexical_weight,
                        ))
                    else:
                        pos = np.argsort(-sc, kind="stable")[:args.candidates]
                        lists.append([{**corpus[p], "score": float(sc[p])} for p in pos])
                candidates = _interleave_candidates(lists, args.candidates)
            else:
                vector = model.encode(query, normalize_embeddings=True)
                scores = embeddings @ vector
                if args.retrieval == "hybrid_rrf":
                    candidates = _hybrid_rrf_candidates(
                        scores, corpus, item["pergunta"], args.candidates, chunk_lookup,
                        lexical_weight=args.lexical_weight,
                    )
                else:
                    positions = np.argsort(-scores, kind="stable")[:args.candidates]
                    candidates = [{**corpus[p], "score": float(scores[p])} for p in positions]
            base_metrics = legal_scores(item, candidates)
            retrieval_seconds = time.perf_counter() - start
            rerank_seconds = 0.0
            if reranker:
                start = time.perf_counter()
                pairs = [[item["pergunta"], c["content"]] for c in candidates]
                # Recusa cortes também no reranker (inclui pergunta e tokens especiais).
                pair_lengths = [len(reranker.tokenizer(q, t, truncation=False)["input_ids"]) for q, t in pairs]
                pair_limit = reranker_max_length or reranker.tokenizer.model_max_length
                if max(pair_lengths) > pair_limit:
                    raise ValueError(f"Reranker truncaria um par pergunta/chunk ({max(pair_lengths)} > {pair_limit}).")
                predictions = np.asarray(reranker.predict(pairs)).reshape(-1)
                if len(predictions) != len(candidates):
                    raise ValueError("Reranker deve produzir um score por par.")
                for c, score in zip(candidates, predictions):
                    c["rerank_score"] = float(score)
                candidates.sort(key=lambda c: -c["rerank_score"])
                rerank_seconds = time.perf_counter() - start
            context = assemble_context(candidates, corpus, count, mode=args.context_mode,
                                       k=args.context_k, budget=args.context_budget)
            rec = {"id": item["id"], "categoria": item["categoria"], "deve_abster": item["deve_abster"],
                   "pergunta": item["pergunta"], "subqueries": subqueries, "reference": item["resposta_esperada"],
                   "base_metrics": base_metrics, "metrics": legal_scores(item, candidates),
                   "context_metrics": legal_scores(item, context, ks=(args.context_k,)),
                   "context_tokens": count(context_xml(context)), "retrieval_seconds": retrieval_seconds,
                   "rerank_seconds": rerank_seconds, "candidates": candidates, "context": context}
            if args.generate:
                from src.config import LLM_MODEL
                from eval.text_metrics import cosine, normalize, rouge_l, bleu_sentence
                get_client, LAW_SYSTEM_PROMPT = _load_generation_dependencies()
                generated = get_client().messages.create(
                    model=LLM_MODEL, max_tokens=4096, system=LAW_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": context_xml(context) + "\n\nPergunta: " + item["pergunta"]}])
                response = "".join(b.text for b in generated.content if b.type == "text")
                rec.update(response=response, stop_reason=generated.stop_reason,
                           input_tokens=generated.usage.input_tokens, output_tokens=generated.usage.output_tokens,
                           text_metrics={"cosine": cosine(response, item["resposta_esperada"]),
                                         "rouge_l": rouge_l(normalize(response), normalize(item["resposta_esperada"])),
                                         "bleu": bleu_sentence(normalize(response), normalize(item["resposta_esperada"]))},
                           abstention_check=_check_abstention_response(response) if item["deve_abster"] else None,
                           qualitative_review="pending: correção, ressalvas, suporte das citações e abstenção")
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            records.append(rec)
            print(f"{item['id']}: mrr={rec['metrics'].get('mrr')}", flush=True)
    summary = {"questions": len(items), "positive": sum(not i["deve_abster"] for i in items),
               "abstention": sum(i["deve_abster"] for i in items),
               "base_metrics": mean_scores(records, "base_metrics"), "metrics": mean_scores(records),
               "context_metrics": mean_scores(records, "context_metrics"),
               "by_category": {category: mean_scores([r for r in records if r["categoria"] == category])
                               for category in Counter(i["categoria"] for i in items)},
               "abstention_review": "auto_checked_manual_review_optional" if args.generate else "manual_pending",
               "corpus_sha256": frozen["corpus_sha256"]}
    if args.generate:
        summary["text_metrics_summary"] = _summarize_generation(records)
    write_json(args.saida / "summary.json", summary)


if __name__ == "__main__":
    main()

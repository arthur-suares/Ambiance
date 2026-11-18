"""Acesso à camada documental do RAG (PostgreSQL + pgvector).

Este módulo não gera embeddings: recebe vetores prontos. Assim a escolha do
modelo (sentence-transformers, API etc.) fica desacoplada do armazenamento.
"""

from dataclasses import dataclass, field

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    FTS_CONFIG,
    PG_CONNECT_TIMEOUT,
    PG_DATABASE,
    PG_HOST,
    PG_PASSWORD,
    PG_PORT,
    PG_USER,
    PROJECT_ROOT,
)
from src.fts_query import build_relaxed_fts_query, extract_terms, weight_terms

SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
RRF_K = 60  # constante padrão do Reciprocal Rank Fusion
# Peso lexical fino no RRF: atua como desempate sem rebaixar o topo semântico do bge-m3.
LEXICAL_RRF_WEIGHT = 0.02


@dataclass
class Chunk:
    content: str
    embedding: list[float] | np.ndarray
    page_start: int | None = None
    page_end: int | None = None
    token_count: int | None = None
    metadata: dict = field(default_factory=dict)


def get_connection(register: bool = True) -> psycopg.Connection:
    con = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE,
        row_factory=dict_row,
        # Sem isso, com o Postgres desligado a conexão pode esperar indefinidamente (Windows).
        connect_timeout=PG_CONNECT_TIMEOUT,
    )
    if register:
        register_vector(con)
    return con


def init_schema() -> None:
    """Cria extensão, tabelas e índices. Seguro para rodar mais de uma vez."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8").format(
        embedding_dim=EMBEDDING_DIM, fts_config=FTS_CONFIG
    )
    # O tipo vector só existe depois do CREATE EXTENSION, então não registra antes.
    with get_connection(register=False) as con:
        con.execute(sql)
        _check_embedding_dim(con)


def reset_schema() -> None:
    """Apaga tabelas e índices. Necessário ao trocar EMBEDDING_DIM ou FTS_CONFIG."""
    with get_connection(register=False) as con:
        con.execute("DROP TABLE IF EXISTS chunks, documents CASCADE")


def _check_embedding_dim(con: psycopg.Connection) -> None:
    """Falha cedo se o banco foi criado com outra dimensão de embedding."""
    row = con.execute(
        """
        SELECT atttypmod AS dim FROM pg_attribute
        WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'
        """
    ).fetchone()
    if row and row["dim"] != EMBEDDING_DIM:
        raise ValueError(
            f"A coluna chunks.embedding tem dimensão {row['dim']}, mas EMBEDDING_DIM={EMBEDDING_DIM}. "
            "Ajuste o .env ou recrie as tabelas (os embeddings precisarão ser regerados)."
        )


def get_document_hash(source_path: str) -> str | None:
    """Retorna o sha256 já indexado, para pular arquivos que não mudaram."""
    info = get_document_index_info(source_path)
    return info["sha256"] if info else None


def get_document_index_info(source_path: str) -> dict | None:
    """Retorna sha256, embedding_model e metadata já indexados para o documento."""
    with get_connection() as con:
        return con.execute(
            "SELECT sha256, embedding_model, metadata FROM documents WHERE source_path = %s",
            [source_path],
        ).fetchone()


def upsert_document(
    source_path: str,
    sha256: str,
    chunks: list[Chunk],
    *,
    title: str | None = None,
    doc_type: str | None = None,
    url: str | None = None,
    version: str | None = None,
    retrieved_at: str | None = None,
    metadata: dict | None = None,
) -> int:
    """Insere ou substitui um documento e todos os seus chunks numa única transação."""
    for i, chunk in enumerate(chunks):
        if len(chunk.embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"Chunk {i}: embedding com {len(chunk.embedding)} dimensões, esperado {EMBEDDING_DIM}."
            )

    with get_connection() as con, con.transaction():
        document_id = con.execute(
            """
            INSERT INTO documents (source_path, title, doc_type, url, version,
                                   retrieved_at, sha256, embedding_model, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_path) DO UPDATE SET
                title = EXCLUDED.title,
                doc_type = EXCLUDED.doc_type,
                url = EXCLUDED.url,
                version = EXCLUDED.version,
                retrieved_at = EXCLUDED.retrieved_at,
                sha256 = EXCLUDED.sha256,
                embedding_model = EXCLUDED.embedding_model,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING id
            """,
            [source_path, title, doc_type, url, version, retrieved_at,
             sha256, EMBEDDING_MODEL, Jsonb(metadata or {})],
        ).fetchone()["id"]

        con.execute("DELETE FROM chunks WHERE document_id = %s", [document_id])
        with con.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (document_id, chunk_index, content, page_start,
                                    page_end, token_count, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (document_id, i, c.content, c.page_start, c.page_end,
                     c.token_count, Jsonb(c.metadata), np.asarray(c.embedding, dtype=np.float32))
                    for i, c in enumerate(chunks)
                ],
            )
    return document_id


def delete_document(source_path: str) -> bool:
    with get_connection() as con:
        cur = con.execute("DELETE FROM documents WHERE source_path = %s", [source_path])
        return cur.rowcount > 0


_SELECT_RESULT = """
    SELECT c.id AS chunk_id, c.content, c.page_start, c.page_end, c.metadata,
           d.source_path, d.title, d.url, d.doc_type, d.version
"""


def semantic_search(
    query_embedding, limit: int = 5, doc_type: str | None = None
) -> list[dict]:
    """Busca só por similaridade de cosseno. score = 1 - distância."""
    with get_connection() as con:
        if doc_type:
            # Com filtro, o HNSW continua varrendo até achar `limit` resultados (pgvector >= 0.8).
            con.execute("SET hnsw.iterative_scan = relaxed_order")
        return con.execute(
            _SELECT_RESULT
            + """
                 , 1 - (c.embedding <=> %(emb)s) AS score
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)
            ORDER BY c.embedding <=> %(emb)s
            LIMIT %(limit)s
            """,
            {"emb": np.asarray(query_embedding, dtype=np.float32),
             "doc_type": doc_type, "limit": limit},
        ).fetchall()


LEXICAL_MODES = ("strict", "relaxed", "idf")


def _term_doc_freq(con: psycopg.Connection, terms: list[str], doc_type: str | None) -> tuple[int, dict[str, int]]:
    """Número de chunks do índice (com o filtro de doc_type) e, para cada termo, em quantos chunks ele aparece."""
    params = {"terms": terms, "doc_type": doc_type}
    n_docs = con.execute(
        "SELECT count(*) AS n FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)", params).fetchone()["n"]
    rows = con.execute(
        f"""
        SELECT t.term,
               (SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id
                 WHERE c.tsv @@ websearch_to_tsquery('{FTS_CONFIG}', t.term)
                   AND (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)) AS df
        FROM unnest(%(terms)s::text[]) AS t(term)
        """, params).fetchall()
    return n_docs, {r["term"]: r["df"] for r in rows}


def hybrid_search(
    query_text: str,
    query_embedding,
    limit: int = 5,
    candidates: int = 40,
    doc_type: str | None = None,
    lexical_mode: str = "idf",
    lexical_weight: float = LEXICAL_RRF_WEIGHT,
) -> list[dict]:
    """Combina busca vetorial e full-text com Reciprocal Rank Fusion.

    Cada busca devolve até `candidates` resultados; a posição de cada chunk em
    cada lista entra no RRF como 1/(RRF_K + posição_semântica) + lexical_weight/(RRF_K + posição_lexical).
    Os scores do canal lexical só ordenam esse canal: o RRF recebe posições.

    `lexical_mode` escolhe a consulta do canal lexical (src/fts_query.py):
    - "strict": a pergunta inteira no `websearch_to_tsquery` (todas as palavras, AND). Modo antigo, só para comparar.
    - "relaxed": termos informativos ligados por OR; ordem do canal por `ts_rank_cd`.
    - "idf" (padrão): os mesmos termos com OR, mas cada chunk é ordenado pela soma do IDF dos termos que ele
      contém (IDF do BM25 sobre os chunks do índice), com `ts_rank_cd` só para desempatar. Termo comum
      ("reserva", "legal") pesa pouco; termo raro pesa muito.
    Em todos, o filtro `c.tsv @@ q` continua: chunk sem nenhum termo da consulta não entra pelo canal lexical.
    Sem termo válido, o canal lexical fica vazio e a busca é só semântica.
    """
    if lexical_mode not in LEXICAL_MODES:
        raise ValueError(f"lexical_mode deve ser um de: {', '.join(LEXICAL_MODES)}")
    terms: list[str] = []
    weights: list[float] = []
    if lexical_mode == "strict":
        fts_text = query_text
    elif lexical_mode == "relaxed":
        fts_text = build_relaxed_fts_query(query_text)
    else:
        fts_text = ""
    with get_connection() as con:
        if lexical_mode == "idf":
            pool = extract_terms(query_text)
            if pool:
                n_docs, doc_freq = _term_doc_freq(con, pool, doc_type)
                weighted = weight_terms(pool, doc_freq, n_docs)
                terms, weights = [t for t, _ in weighted], [w for _, w in weighted]
                fts_text = " or ".join(terms)
        if doc_type:
            con.execute("SET hnsw.iterative_scan = relaxed_order")
        return con.execute(
            f"""
            WITH semantic AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY distance) AS rank
                FROM (
                    SELECT c.id, c.embedding <=> %(emb)s AS distance
                    FROM chunks c JOIN documents d ON d.id = c.document_id
                    WHERE (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)
                    ORDER BY distance
                    LIMIT %(candidates)s
                ) s
            ),
            keyword AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY idf_score DESC, text_rank DESC) AS rank
                FROM (
                    SELECT c.id, ts_rank_cd(c.tsv, q) AS text_rank,
                           (SELECT COALESCE(SUM(t.w), 0)
                              FROM unnest(%(terms)s::text[], %(weights)s::float8[]) AS t(term, w)
                             WHERE c.tsv @@ websearch_to_tsquery('{FTS_CONFIG}', t.term)) AS idf_score
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id,
                         websearch_to_tsquery('{FTS_CONFIG}', %(query)s) q
                    WHERE c.tsv @@ q
                      AND (%(doc_type)s::text IS NULL OR d.doc_type = %(doc_type)s)
                    ORDER BY idf_score DESC, text_rank DESC
                    LIMIT %(candidates)s
                ) k
            ),
            fused AS (
                SELECT COALESCE(s.id, k.id) AS id,
                       COALESCE(1.0 / ({RRF_K} + s.rank), 0)
                     + COALESCE(%(lexical_weight)s::float8 / ({RRF_K} + k.rank), 0) AS score,
                       s.rank AS semantic_rank,
                       k.rank AS keyword_rank
                FROM semantic s FULL OUTER JOIN keyword k ON s.id = k.id
            )
            {_SELECT_RESULT}
                 , f.score, f.semantic_rank, f.keyword_rank
            FROM fused f
            JOIN chunks c ON c.id = f.id
            JOIN documents d ON d.id = c.document_id
            ORDER BY f.score DESC, f.semantic_rank ASC NULLS LAST, f.keyword_rank ASC NULLS LAST
            LIMIT %(limit)s
            """,
            {"emb": np.asarray(query_embedding, dtype=np.float32),
             "query": fts_text, "doc_type": doc_type, "terms": terms, "weights": weights,
             "candidates": candidates, "limit": limit, "lexical_weight": float(lexical_weight)},
        ).fetchall()


def get_article_siblings(source_path: str, artigo: str) -> list[dict]:
    """Retorna todas as partes de um mesmo artigo de um documento, ordenadas por parte."""
    with get_connection(register=False) as con:
        return con.execute(
            _SELECT_RESULT
            + """
                 , NULL::float8 AS score, NULL::bigint AS semantic_rank, NULL::bigint AS keyword_rank
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.source_path = %(source_path)s
              AND c.metadata->>'artigo' = %(artigo)s
            ORDER BY COALESCE((c.metadata->>'parte')::int, 1), c.chunk_index
            """,
            {"source_path": source_path, "artigo": str(artigo)},
        ).fetchall()


def stats() -> dict:
    with get_connection() as con:
        return con.execute(
            """
            SELECT (SELECT COUNT(*) FROM documents) AS documents,
                   (SELECT COUNT(*) FROM chunks) AS chunks,
                   (SELECT array_agg(DISTINCT embedding_model) FROM documents) AS models
            """
        ).fetchone()


def _chunk_identity(chunk: dict) -> tuple:
    cid = chunk.get("chunk_id")
    if cid is not None:
        return ("id", cid)
    meta = chunk.get("metadata") or {}
    return ("meta", chunk.get("title"), meta.get("artigo"), meta.get("parte"))


def _article_identity(chunk: dict) -> tuple:
    meta = chunk.get("metadata") or {}
    return (chunk.get("title"), meta.get("artigo"))


def fuse_chunk_lists(
    chunk_lists: list[list[dict]],
    limit: int = 6,
    rrf_k: int = RRF_K,
    max_per_article: int | None = 2,
) -> list[dict]:
    """Funde e desduplica resultados de múltiplas sub-buscas usando Reciprocal Rank Fusion (RRF).

    - Cada sub-busca `m` contribui com `w_m * (1 / (rrf_k + pos_m) + score_hibrido_m)` para cada chunk,
      onde `w_m` dá leve prioridade de desempate à primeira sub-consulta (a pergunta limpa do usuário)
      e `score_hibrido_m` preserva a força conjunta dos canais semântico + lexical daquela sub-busca.
    - Chunks repetidos entre sub-buscas têm seus scores somados (subindo no ranking) e aparecem uma única vez.
    - `max_per_article` limita quantas partes de um mesmo artigo longo (ex.: art. 12 com 5 partes) podem entrar
      na passagem principal do top-`limit`, abrindo espaço para artigos complementares (ex.: art. 3º); se sobrarem
      vagas até `limit`, as partes excedentes entram no final na ordem de score.
    """
    non_empty = [lst for lst in chunk_lists if lst]
    if not non_empty:
        return []

    by_key: dict[tuple, dict] = {}
    scores: dict[tuple, float] = {}
    first_seen_order: dict[tuple, tuple[int, int]] = {}
    best_sem_rank: dict[tuple, int | None] = {}
    best_kw_rank: dict[tuple, int | None] = {}

    for m, chunks in enumerate(non_empty):
        # Leve decaimento por sub-consulta apenas para desempatar a favor da consulta original limpa
        query_weight = max(0.85, 1.0 - 0.02 * m)
        for pos, chunk in enumerate(chunks, start=1):
            key = _chunk_identity(chunk)
            raw_score = float(chunk.get("score") or 0.0)
            rrf_part = 1.0 / (rrf_k + pos)
            contrib = query_weight * (rrf_part + raw_score)
            scores[key] = scores.get(key, 0.0) + contrib

            if key not in by_key:
                by_key[key] = dict(chunk)
                first_seen_order[key] = (m, pos)

            s_rank = chunk.get("semantic_rank")
            if s_rank is not None:
                prev_s = best_sem_rank.get(key)
                best_sem_rank[key] = s_rank if prev_s is None else min(prev_s, s_rank)

            k_rank = chunk.get("keyword_rank")
            if k_rank is not None:
                prev_k = best_kw_rank.get(key)
                best_kw_rank[key] = k_rank if prev_k is None else min(prev_k, k_rank)

    ranked_keys = sorted(
        by_key.keys(),
        key=lambda k: (-scores[k], first_seen_order[k]),
    )

    merged_all: list[dict] = []
    for key in ranked_keys:
        item = dict(by_key[key])
        item["score"] = scores[key]
        if key in best_sem_rank:
            item["semantic_rank"] = best_sem_rank[key]
        if key in best_kw_rank:
            item["keyword_rank"] = best_kw_rank[key]
        merged_all.append(item)

    if max_per_article is None or max_per_article <= 0:
        return merged_all[:limit]

    primary: list[dict] = []
    overflow: list[dict] = []
    article_counts: dict[tuple, int] = {}

    for item in merged_all:
        art_key = _article_identity(item)
        count = article_counts.get(art_key, 0)
        if art_key[1] is not None and count >= max_per_article:
            overflow.append(item)
        else:
            primary.append(item)
            article_counts[art_key] = count + 1
            if len(primary) >= limit:
                break

    if len(primary) < limit and overflow:
        primary.extend(overflow[: limit - len(primary)])

    return primary[:limit]

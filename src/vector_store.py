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
    with get_connection() as con:
        row = con.execute(
            "SELECT sha256 FROM documents WHERE source_path = %s", [source_path]
        ).fetchone()
    return row["sha256"] if row else None


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
) -> list[dict]:
    """Combina busca vetorial e full-text com Reciprocal Rank Fusion.

    Cada busca devolve até `candidates` resultados; a posição de cada chunk em
    cada lista vira score 1/(RRF_K + posição) e os scores são somados. Os scores do
    canal lexical só ordenam esse canal: o RRF recebe posições.

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
                     + COALESCE(1.0 / ({RRF_K} + k.rank), 0) AS score,
                       s.rank AS semantic_rank,
                       k.rank AS keyword_rank
                FROM semantic s FULL OUTER JOIN keyword k ON s.id = k.id
            )
            {_SELECT_RESULT}
                 , f.score, f.semantic_rank, f.keyword_rank
            FROM fused f
            JOIN chunks c ON c.id = f.id
            JOIN documents d ON d.id = c.document_id
            ORDER BY f.score DESC
            LIMIT %(limit)s
            """,
            {"emb": np.asarray(query_embedding, dtype=np.float32),
             "query": fts_text, "doc_type": doc_type, "terms": terms, "weights": weights,
             "candidates": candidates, "limit": limit},
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

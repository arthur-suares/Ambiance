-- Esquema da camada documental do RAG.
-- Os placeholders {embedding_dim} e {fts_config} são preenchidos por
-- src/vector_store.py a partir do .env (EMBEDDING_DIM, FTS_CONFIG).
-- Idempotente: pode ser executado várias vezes.

CREATE EXTENSION IF NOT EXISTS vector;

-- Um registro por arquivo de origem (PDF, metodologia, relatório...).
CREATE TABLE IF NOT EXISTS documents (
    id              BIGSERIAL PRIMARY KEY,
    source_path     TEXT NOT NULL UNIQUE,      -- caminho relativo em docs/
    title           TEXT,
    doc_type        TEXT,                      -- ex.: methodology, dictionary, report
    url             TEXT,
    version         TEXT,
    retrieved_at    DATE,                      -- data de obtenção do documento
    sha256          TEXT NOT NULL,             -- detecta mudança e evita reindexar
    embedding_model TEXT NOT NULL,             -- não misturar embeddings de modelos diferentes
    metadata        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trechos indexados. Cada chunk guarda o embedding e um tsvector para busca híbrida.
CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    page_start  INTEGER,
    page_end    INTEGER,
    token_count INTEGER,
    metadata    JSONB NOT NULL DEFAULT '{{}}'::jsonb,   -- ex.: seção, título do capítulo
    embedding   vector({embedding_dim}) NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('{fts_config}', content)) STORED,
    UNIQUE (document_id, chunk_index)
);

-- Busca semântica (distância de cosseno).
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Busca por palavra-chave.
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);

CREATE INDEX IF NOT EXISTS chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS documents_doc_type ON documents (doc_type);

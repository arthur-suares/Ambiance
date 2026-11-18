"""Pipeline de ingestão das leis: HTML limpo -> artigos -> embeddings -> Postgres.

Lê docs/leis/manifest.json, e para cada lei:
1. pula se o sha256 já indexado for igual (a lei não mudou);
2. divide em artigos (src/law_parser.py);
3. gera os embeddings (src/embeddings.py);
4. grava documento + chunks numa transação (src/vector_store.py).
"""

import json
from pathlib import Path

from src import vector_store
from src.config import EMBEDDING_MODEL, PROJECT_ROOT
from src.embeddings import count_chunk_tokens, embed_passages, max_model_tokens
from src.law_parser import build_chunks, parse_law_file

MANIFEST = PROJECT_ROOT / "docs" / "leis" / "manifest.json"
# Folga abaixo do limite do modelo para nenhum chunk chegar perto do corte.
TOKEN_SAFETY_MARGIN = 32
# Limite padrão dos chunks: fixado em 480 para trocar modelo de embeddings sem alterar o chunking.
DEFAULT_CHUNK_MAX_TOKENS = 480
# Tamanho das partes quando um artigo precisa ser dividido (ver build_chunks).
CHUNK_SPLIT_TOKENS = 256


def _chunking_spec(chunk_max_tokens: int, split_tokens: int) -> str:
    return f"por artigo, max {chunk_max_tokens} tokens; artigos longos em partes de {split_tokens}"


def _should_skip_document(indexed: dict | None, expected_sha256: str, expected_chunking: str) -> bool:
    if not indexed:
        return False
    return (
        indexed.get("sha256") == expected_sha256
        and indexed.get("embedding_model") == EMBEDDING_MODEL
        and (indexed.get("metadata") or {}).get("chunking") == expected_chunking
    )


def ingest_laws(force: bool = False, chunk_max_tokens: int | None = None) -> None:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    model_limit = max_model_tokens() - TOKEN_SAFETY_MARGIN
    target_max = DEFAULT_CHUNK_MAX_TOKENS if chunk_max_tokens is None else chunk_max_tokens
    effective_max = min(target_max, model_limit)
    split_tokens = min(CHUNK_SPLIT_TOKENS, effective_max)
    chunking_label = _chunking_spec(effective_max, split_tokens)
    for entry in entries:
        source_path = entry["file"]
        indexed = None if force else vector_store.get_document_index_info(source_path)
        if not force and _should_skip_document(indexed, entry["sha256"], chunking_label):
            print(f"= {entry['title']}: sem mudanças, pulando")
            continue

        ementa, articles = parse_law_file(PROJECT_ROOT / source_path)
        law_chunks = build_chunks(entry["title"], ementa, articles, count_chunk_tokens,
                                   effective_max, split_tokens)
        vectors = embed_passages([c.text for c in law_chunks])

        chunks = [
            vector_store.Chunk(
                content=c.text,
                embedding=v,
                token_count=c.token_count,
                metadata={
                    "artigo": c.article,
                    "parte": c.part,
                    "partes": c.parts,
                    "hierarquia": c.hierarchy,
                },
            )
            for c, v in zip(law_chunks, vectors)
        ]
        vector_store.upsert_document(
            source_path,
            entry["sha256"],
            chunks,
            title=entry["title"],
            doc_type=entry["doc_type"],
            url=entry["url"],
            retrieved_at=entry["retrieved_at"],
            metadata={
                "jurisdiction": entry.get("jurisdiction"),
                "enacted_at": entry.get("enacted_at"),
                "original_sha256": entry.get("original_sha256"),
                "chunking": chunking_label,
            },
        )
        split = sum(1 for c in law_chunks if c.parts > 1)
        print(f"+ {entry['title']}: {len(articles)} artigos -> {len(chunks)} chunks "
              f"({split} chunks vêm de artigos divididos)")

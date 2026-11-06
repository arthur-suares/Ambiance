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
from src.config import PROJECT_ROOT
from src.embeddings import count_tokens, embed_passages, max_model_tokens
from src.law_parser import build_chunks, parse_law_file

MANIFEST = PROJECT_ROOT / "docs" / "leis" / "manifest.json"
# Folga abaixo do limite do modelo para nenhum chunk chegar perto do corte.
TOKEN_SAFETY_MARGIN = 32
# Tamanho das partes quando um artigo precisa ser dividido (ver build_chunks).
CHUNK_SPLIT_TOKENS = 256


def ingest_laws(force: bool = False) -> None:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    chunk_max_tokens = max_model_tokens() - TOKEN_SAFETY_MARGIN
    split_tokens = min(CHUNK_SPLIT_TOKENS, chunk_max_tokens)
    for entry in entries:
        source_path = entry["file"]
        if not force and vector_store.get_document_hash(source_path) == entry["sha256"]:
            print(f"= {entry['title']}: sem mudanças, pulando")
            continue

        ementa, articles = parse_law_file(PROJECT_ROOT / source_path)
        law_chunks = build_chunks(entry["title"], ementa, articles, count_tokens,
                                   chunk_max_tokens, split_tokens)
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
                "chunking": f"por artigo, max {chunk_max_tokens} tokens; artigos longos em partes de {split_tokens}",
            },
        )
        split = sum(1 for c in law_chunks if c.parts > 1)
        print(f"+ {entry['title']}: {len(articles)} artigos -> {len(chunks)} chunks "
              f"({split} chunks vêm de artigos divididos)")

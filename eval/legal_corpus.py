"""Auditoria somente leitura; exportação dos chunks persistidos ou reconstrução explícita.

python -m eval.legal_corpus --saida eval/resultados/rag_juridico/auditoria
python -m eval.legal_corpus --freeze /tmp/leis-indexadas.json
python -m eval.legal_corpus --rebuild /tmp/leis-e5-small.json
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from src.law_parser import build_chunks, extract_paragraphs, parse_law_file

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/leis/manifest.json"
CHUNK_MODEL = "intfloat/multilingual-e5-small"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def local_inventory(root: Path = ROOT) -> dict:
    manifest = root / "docs/leis/manifest.json"
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    docs = []
    for entry in entries:
        path = root / entry["file"]
        row = dict(entry)
        row["exists"] = path.is_file()
        if path.is_file():
            raw = path.read_bytes()
            ementa, articles = parse_law_file(path)
            numbers = [a.number for a in articles]
            row.update(actual_sha256=hashlib.sha256(raw).hexdigest(),
                       articles=len(articles), article_numbers=numbers,
                       duplicate_articles=[n for n, count in Counter(numbers).items() if count > 1],
                       ementa=bool(ementa),
                       annex_headings=[p for p in extract_paragraphs(raw.decode(entry.get("encoding", "utf-8")))
                                       if re.match(r"^ANEXO(?:\s|$)", p, re.I)])
            row["hash_matches"] = row["actual_sha256"] == entry["sha256"]
        docs.append(row)
    listed = {e["file"] for e in entries}
    unlisted = sorted(str(p.relative_to(root)) for p in (root / "docs/leis").iterdir()
                      if p.suffix.lower() in {".htm", ".html"} and str(p.relative_to(root)) not in listed)
    return {"manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "documents": docs, "unlisted_html": unlisted,
            "parser_scope": "ementa e artigos; termina em Brasília, descarta assinaturas e anexos"}


def read_index() -> list[dict]:
    from src.vector_store import get_connection
    with get_connection(register=False) as con:
        con.execute("SET TRANSACTION READ ONLY")
        return con.execute("""
            SELECT d.source_path, d.title, d.doc_type, d.url, d.sha256,
                   d.embedding_model, d.metadata AS document_metadata,
                   c.chunk_index, c.content, c.token_count, c.metadata,
                   vector_dims(c.embedding) AS embedding_dim
            FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
            ORDER BY d.source_path, c.chunk_index
        """).fetchall()


def reconcile(local: dict, rows: list[dict]) -> dict:
    expected = {d["file"]: d for d in local["documents"]}
    indexed: dict[str, list[dict]] = {}
    for row in rows:
        indexed.setdefault(row["source_path"], []).append(row)
    docs = []
    for path, group in indexed.items():
        first, source = group[0], expected.get(path)
        chunks = [r for r in group if r["content"] is not None]
        keys = [(r["metadata"].get("artigo"), r["metadata"].get("parte")) for r in chunks]
        numbers = {str(r["metadata"].get("artigo")) for r in chunks} - {"ementa"}
        invalid_parts = []
        for article in {key[0] for key in keys}:
            parts = [r["metadata"] for r in chunks if r["metadata"].get("artigo") == article]
            totals = {m.get("partes") for m in parts}
            total = next(iter(totals))
            if (len(totals) != 1 or not isinstance(total, int) or total < 1
                    or {m.get("parte") for m in parts} != set(range(1, total + 1))):
                invalid_parts.append(article)
        docs.append({"file": path, "title": first["title"], "in_manifest": source is not None,
                     "hash_matches_manifest": first["sha256"] == source["sha256"] if source else None,
                     "hash_matches_file": first["sha256"] == source.get("actual_sha256") if source else None,
                     "embedding_model": first["embedding_model"], "chunks": len(chunks),
                     "chunks_sha256": _chunks_sha256(chunks),
                     "dimensions": sorted({r["embedding_dim"] for r in chunks}),
                     "duplicate_article_parts": len(keys) - len(set(keys)),
                     "invalid_article_parts": invalid_parts,
                     "missing_articles": sorted(set(source.get("article_numbers", [])) - numbers) if source else [],
                     "unexpected_articles": sorted(numbers - set(source.get("article_numbers", []))) if source else [],
                     "document_metadata": first["document_metadata"]})
    manifest_rows = [r for r in rows if r["source_path"] in expected and r.get("content") is not None]
    return {"status": "read", "documents": docs, "chunks": sum(d["chunks"] for d in docs),
            "manifest_chunks_sha256": _chunks_sha256(manifest_rows) if manifest_rows else None,
            "missing_documents": sorted(set(expected) - set(indexed)),
            "extra_documents": sorted(set(indexed) - set(expected))}


def _chunk_payload(row: dict) -> dict:
    return {k: row[k] for k in ("source_path", "title", "url", "content", "metadata")}


def _chunks_sha256(rows: list[dict]) -> str:
    payloads = [_chunk_payload(r) for r in rows if r.get("content") is not None]
    payloads.sort(key=lambda c: (c["source_path"], str(c["metadata"].get("artigo", "")), int(c["metadata"].get("parte", 1))))
    return digest(payloads)


def freeze(rows: list[dict], origin: str, manifest_hash: str, chunking: dict) -> dict:
    chunks = []
    for row in rows:
        if row.get("content") is None:
            continue
        # ID independente do banco e da dimensão dos vetores.
        c = _chunk_payload(row)
        c["chunk_id"] = digest(c)
        chunks.append(c)
    if not chunks or len({c["chunk_id"] for c in chunks}) != len(chunks):
        raise ValueError("Corpus vazio ou chunks duplicados.")
    payload = {"schema": 1, "origin": origin, "manifest_sha256": manifest_hash,
               "chunking": chunking, "chunks": chunks}
    return {**payload, "corpus_sha256": digest(payload)}


def load_frozen(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    payload = {k: v for k, v in data.items() if k != "corpus_sha256"}
    if data.get("corpus_sha256") != digest(payload):
        raise ValueError("Fingerprint do corpus inválido; não altere os chunks entre rodadas.")
    return data


def rebuild(local: dict) -> dict:
    from transformers import AutoTokenizer
    from eval.text_metrics import HISTORICAL_SIMILARITY_REVISION
    tokenizer = AutoTokenizer.from_pretrained(CHUNK_MODEL, revision=HISTORICAL_SIMILARITY_REVISION)
    def count(text):
        return len(tokenizer.encode("passage: " + text, add_special_tokens=True, truncation=False))
    rows = []
    for entry in local["documents"]:
        if not entry.get("hash_matches"):
            raise ValueError(f"Arquivo ausente ou divergente do manifesto: {entry['file']}")
        ementa, articles = parse_law_file(ROOT / entry["file"])
        for c in build_chunks(entry["title"], ementa, articles, count, 480, 256):
            if c.token_count > 480:
                raise ValueError(f"Chunk excede limite E5-small: {entry['file']}, art. {c.article}")
            rows.append({"source_path": entry["file"], "title": entry["title"], "url": entry["url"],
                         "content": c.text, "metadata": {"artigo": c.article, "parte": c.part,
                         "partes": c.parts, "hierarquia": c.hierarchy}})
    return freeze(rows, "rebuilt_not_verified_against_database", local["manifest_sha256"],
                  {"model": CHUNK_MODEL, "max_tokens": 480, "split_tokens": 256,
                   "tokenizer_revision": HISTORICAL_SIMILARITY_REVISION,
                   "parser_sha256": hashlib.sha256((ROOT / "src/law_parser.py").read_bytes()).hexdigest()})


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--saida", type=Path, default=ROOT / "eval/resultados/rag_juridico/auditoria")
    ap.add_argument("--corpus-ref", type=Path, default=ROOT / "data/processed/juridico/corpus_e5_small.json",
                    help="corpus congelado de referência para comparar chunks_sha256")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--freeze", type=Path, help="exporta exatamente os chunks das leis do índice, sem vetores")
    group.add_argument("--rebuild", type=Path, help="reconstrói os chunks E5-small, sem afirmar que estão indexados")
    args = ap.parse_args()
    local = local_inventory()
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "local": local}
    if args.corpus_ref.is_file():
        frozen_ref = load_frozen(args.corpus_ref)
        report["frozen_reference"] = {
            "path": str(args.corpus_ref.relative_to(ROOT)) if args.corpus_ref.is_relative_to(ROOT) else str(args.corpus_ref),
            "origin": frozen_ref.get("origin"),
            "corpus_sha256": frozen_ref.get("corpus_sha256"),
            "chunks": len(frozen_ref["chunks"]),
            "chunks_sha256": _chunks_sha256(frozen_ref["chunks"]),
            "chunking": frozen_ref.get("chunking"),
        }
    rows = None
    try:
        rows = read_index()
        report["index"] = reconcile(local, rows)
        if "frozen_reference" in report and report["index"].get("manifest_chunks_sha256"):
            report["index"]["matches_frozen_reference"] = (
                report["index"]["manifest_chunks_sha256"] == report["frozen_reference"]["chunks_sha256"]
            )
        # Fingerprint permite comparar conteúdo/chunking em auditorias futuras.
        for doc in report["index"]["documents"]:
            source = next((d for d in local["documents"] if d["file"] == doc["file"]), None)
            if source:
                doc["indexed_content_sha256"] = digest([
                    {"content": r["content"], "metadata": r["metadata"]}
                    for r in rows if r["source_path"] == doc["file"]])
    except Exception as exc:
        # Não imprime DSN/credenciais nem transforma falha em um índice vazio.
        report["index"] = {"status": "unavailable", "error_type": type(exc).__name__,
                           "message": "Não foi possível ler o Postgres; acervo persistido não confirmado."}
    write_json(args.saida / "audit.json", report)
    lines = ["# Auditoria do acervo jurídico", "",
             f"Manifesto: {len(local['documents'])} normas; parser: {sum(d.get('articles', 0) for d in local['documents'])} artigos.",
             f"Índice persistido: {report['index']['status']}.", "",
             "| Norma | Artigos extraídos | SHA256 confere | Anexos detectados (excluídos pelo parser) |",
             "|---|---:|---|---:|"]
    for d in local["documents"]:
        lines.append(f"| {d['title']} | {d.get('articles', 'ausente')} | {d.get('hash_matches', False)} | {len(d.get('annex_headings', []))} |")
    lines += ["", "HTMLs fora do manifesto (não ingeridos por ingest-laws):", ""]
    lines += [f"- `{p}`" for p in local["unlisted_html"]]
    if "frozen_reference" in report:
        ref = report["frozen_reference"]
        lines += ["", "## Snapshot congelado de referência", "",
                  f"- Arquivo: `{ref['path']}` (`{ref['chunks']}` chunks, origem `{ref['origin']}`)",
                  f"- `corpus_sha256`: `{ref['corpus_sha256']}`",
                  f"- `chunks_sha256`: `{ref['chunks_sha256']}`"]
    if report["index"]["status"] == "read":
        idx = report["index"]
        lines += ["", "## Índice persistido (PostgreSQL)", "",
                  f"- Chunks totais no banco: {idx['chunks']} | Documentos ausentes: {len(idx['missing_documents'])} | Documentos extras: {len(idx['extra_documents'])}"]
        if "matches_frozen_reference" in idx:
            lines.append(f"- Chunks das {len(local['documents'])} normas idênticos ao snapshot congelado: `{idx['matches_frozen_reference']}`")
        lines += ["", "| Norma | No manifesto | Modelo | Dimensão | Chunks | Hash confere | Divergências de artigo |",
                  "|---|---|---|---:|---:|---|---|"]
        for doc in idx["documents"]:
            issues = (len(doc["missing_articles"]) + len(doc["unexpected_articles"])
                      + doc["duplicate_article_parts"] + len(doc["invalid_article_parts"]))
            lines.append(
                f"| {doc['title']} | {doc['in_manifest']} | {doc['embedding_model']} | "
                f"{','.join(map(str, doc['dimensions']))} | {doc['chunks']} | "
                f"{bool(doc['hash_matches_file'] and doc['hash_matches_manifest'])} | {issues} |"
            )
    else:
        lines += ["", "## Índice persistido (PostgreSQL)", "",
                  f"- Status: `{report['index']['status']}` ({report['index'].get('error_type')}): {report['index'].get('message')}"]
    lines += ["", "A contagem local não comprova indexação. Detalhes e divergências do banco estão em audit.json.",
              "Os gabaritos se referem ao snapshot local, sem certificação de vigência jurídica atual."]
    args.saida.mkdir(parents=True, exist_ok=True)
    (args.saida / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.freeze:
        if rows is None:
            raise SystemExit("Auditoria salva; exportação recusada: índice persistido indisponível.")
        paths = {d["file"] for d in local["documents"]}
        selected = [r for r in rows if r["source_path"] in paths]
        problems = report["index"]["missing_documents"] or any(
            not d["hash_matches_file"] or not d["hash_matches_manifest"] or d["missing_articles"]
            or d["unexpected_articles"] or d["duplicate_article_parts"] or d["invalid_article_parts"]
            for d in report["index"]["documents"] if d["in_manifest"])
        if problems:
            raise SystemExit("Auditoria salva; resolva divergências do índice antes de congelar.")
        write_json(args.freeze, freeze(selected, "database", local["manifest_sha256"],
                                      {"preserved_from_database": True}))
    if args.rebuild:
        write_json(args.rebuild, rebuild(local))
    print(f"Auditoria: {args.saida / 'audit.md'}; índice={report['index']['status']}")


if __name__ == "__main__":
    main()

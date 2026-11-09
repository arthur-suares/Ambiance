from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb

from src.config import PROJECT_ROOT
from src.soy.catalog import DEFAULT_SOY_MANIFEST, ensure_manifest, load_manifest

DEFAULT_DUCKDB_PATH = PROJECT_ROOT / "data" / "processed" / "soy" / "soy.duckdb"


def _safe_table_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(name))
    cleaned = cleaned.strip("_")
    return cleaned or "soy_dataset"


def _resolve_file_path(source_file: str, data_root: Path | str | None = None) -> Path | None:
    root = Path(data_root) if data_root is not None else PROJECT_ROOT / "data"
    candidates = [
        root / source_file,
        root / "raw" / source_file,
        root / "processed" / source_file,
        root / "processed" / "soy" / source_file,
        PROJECT_ROOT / source_file,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def profile_file(path: Path | str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")

    conn = duckdb.connect(":memory:")
    try:
        if p.suffix.lower() == ".csv":
            table = conn.execute(
                "SELECT * FROM read_csv_auto(?, header = true, sample_size = -1, all_varchar = true, ignore_errors = true)",
                [str(p)],
            )
        else:
            table = conn.execute("SELECT * FROM read_parquet(?)", [str(p)])
        columns = table.description
        row_count = conn.execute("SELECT COUNT(*) FROM (SELECT * FROM read_csv_auto(?, header = true, sample_size = -1, all_varchar = true, ignore_errors = true))", [str(p)]).fetchone()[0] if p.suffix.lower() == ".csv" else conn.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(p)]).fetchone()[0]
        sample = conn.execute("SELECT * FROM read_csv_auto(?, header = true, sample_size = -1, all_varchar = true, ignore_errors = true) LIMIT 5", [str(p)]).fetchdf() if p.suffix.lower() == ".csv" else conn.execute("SELECT * FROM read_parquet(?) LIMIT 5", [str(p)]).fetchdf()
        return {
            "path": str(p),
            "row_count": int(row_count),
            "columns": [col[0] for col in columns],
            "dtypes": {col[0]: str(col[1]) for col in columns},
            "sample": sample,
            "sha256": sha256_file(p),
        }
    finally:
        conn.close()


def detect_missing_datasets(manifest: list[dict] | None = None, data_root: Path | str | None = None) -> list[str]:
    records = manifest or load_manifest()
    missing = []
    for dataset in records:
        source = dataset.get("source_file")
        if source and _resolve_file_path(source, data_root) is None:
            missing.append(dataset.get("dataset_name") or source)
    return missing


def ingest_soy_datasets(
    manifest: list[dict] | None = None,
    data_root: Path | str | None = None,
    duckdb_path: Path | str | None = None,
    force: bool = False,
) -> dict:
    records = manifest or load_manifest()
    db_path = Path(duckdb_path) if duckdb_path is not None else DEFAULT_DUCKDB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS soy_dataset_metadata (
                dataset_name VARCHAR PRIMARY KEY,
                table_name VARCHAR,
                source_file VARCHAR,
                sha256 VARCHAR,
                ingested_at TIMESTAMP,
                row_count BIGINT,
                version VARCHAR,
                period_start INTEGER,
                period_end INTEGER,
                status VARCHAR
            )
            """
        )
        ingested = 0
        missing = []
        for dataset in records:
            source_file = dataset.get("source_file")
            table_name = dataset.get("table_name") or _safe_table_name(dataset.get("dataset_name", "soy_dataset"))
            file_path = _resolve_file_path(source_file, data_root) if source_file else None
            if file_path is None:
                missing.append(dataset.get("dataset_name") or source_file)
                continue

            sha = sha256_file(file_path)
            previous = conn.execute(
                "SELECT sha256, row_count FROM soy_dataset_metadata WHERE dataset_name = ?",
                [dataset.get("dataset_name")],
            ).fetchone()
            if previous and previous[0] == sha and not force:
                continue

            required = dataset.get("columns") or []
            if file_path.suffix.lower() == ".csv":
                stage_name = f"{table_name}_staging"
                conn.execute(f"DROP TABLE IF EXISTS {stage_name}")
                conn.execute(
                    f"CREATE TABLE {stage_name} AS SELECT * FROM read_csv_auto(?, header = true, sample_size = -1, all_varchar = true, ignore_errors = true)",
                    [str(file_path)],
                )
            elif file_path.suffix.lower() in {".parquet", ".pq"}:
                stage_name = f"{table_name}_staging"
                conn.execute(f"DROP TABLE IF EXISTS {stage_name}")
                conn.execute(f"CREATE TABLE {stage_name} AS SELECT * FROM read_parquet(?)", [str(file_path)])
            else:
                raise ValueError(f"Formato não suportado para {file_path}: {file_path.suffix}")

            available = [row[0] for row in conn.execute(f"DESCRIBE {stage_name}").fetchall()]
            missing_cols = [col for col in required if col not in available]
            if missing_cols:
                conn.execute(f"DROP TABLE IF EXISTS {stage_name}")
                raise ValueError(f"Dataset {dataset.get('dataset_name')} faltando colunas: {missing_cols}")

            conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM {stage_name}")
            conn.execute(f"DROP TABLE IF EXISTS {stage_name}")

            row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            period = dataset.get("period") or {}
            conn.execute(
                """
                INSERT INTO soy_dataset_metadata (dataset_name, table_name, source_file, sha256, ingested_at, row_count, version, period_start, period_end, status)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, 'ok')
                ON CONFLICT (dataset_name) DO UPDATE SET
                    table_name = excluded.table_name,
                    source_file = excluded.source_file,
                    sha256 = excluded.sha256,
                    ingested_at = excluded.ingested_at,
                    row_count = excluded.row_count,
                    version = excluded.version,
                    period_start = excluded.period_start,
                    period_end = excluded.period_end,
                    status = excluded.status
                """,
                [
                    dataset.get("dataset_name"),
                    table_name,
                    str(file_path),
                    sha,
                    int(row_count),
                    dataset.get("version"),
                    period.get("start"),
                    period.get("end"),
                ],
            )
            ingested += 1

        from src.soy.territorial import build_extra_tables

        extra = build_extra_tables(conn, data_root)
        return {"database": str(db_path), "ingested": ingested, "missing": missing, "available": [d.get("dataset_name") for d in records if _resolve_file_path(d.get("source_file"), data_root) is not None], "extra": extra}
    finally:
        conn.close()


def get_soy_profile(duckdb_path: Path | str | None = None) -> dict:
    db_path = Path(duckdb_path) if duckdb_path is not None else DEFAULT_DUCKDB_PATH
    if not db_path.exists():
        return {"tables": [], "metadata": []}

    conn = duckdb.connect(str(db_path))
    try:
        tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name").fetchall()
        metadata = conn.execute("SELECT dataset_name, table_name, sha256, row_count, ingested_at, version FROM soy_dataset_metadata ORDER BY dataset_name").fetchall()
        return {"tables": [row[0] for row in tables], "metadata": [dict(zip(["dataset_name", "table_name", "sha256", "row_count", "ingested_at", "version"], row)) for row in metadata]}
    finally:
        conn.close()


if __name__ == "__main__":
    ensure_manifest()
    print(json.dumps(ingest_soy_datasets(), ensure_ascii=False, indent=2))

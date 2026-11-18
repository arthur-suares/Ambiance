"""Result Store por sessão: guarda os DataFrames das ferramentas (D1..Dn) em memória e Parquet.

Implementa a etapa 4a de `docs/PIPELINE_MULTIAGENTE.md`:
- Limite em memória por sessão (`max_datasets`, padrão 20) e por DataFrame (`max_rows`, padrão 5.000);
- Numeração contínua de `D1`, `D2`... ao longo de várias mensagens na mesma sessão;
- Persistência em `outputs/sessions/<session_id>/` (um `<Dn>.parquet` por resultado + `meta.json`).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import threading

import pandas as pd

from src.config import PROJECT_ROOT
from src.dashboard.schemas import DatasetResult

DEFAULT_SESSIONS_DIR = PROJECT_ROOT / "outputs" / "sessions"
DEFAULT_MAX_DATASETS = 20
DEFAULT_MAX_ROWS = 5000

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LABEL_NUM_RE = re.compile(r"^D(\d+)$", re.IGNORECASE)


def _validate_safe_id(value: str, kind: str = "session_id") -> str:
    cleaned = (value or "").strip()
    if not _SAFE_ID_RE.match(cleaned):
        raise ValueError(f"{kind} inválido: {value!r}.")
    return cleaned


def _safe_write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Grava DataFrame em Parquet convertendo colunas object mistas para string quando necessário."""
    try:
        df.to_parquet(path, index=False)
    except Exception:
        fixed = df.copy()
        for col in fixed.columns:
            if fixed[col].dtype == "object":
                fixed[col] = fixed[col].map(lambda v: None if pd.isna(v) else str(v))
        fixed.to_parquet(path, index=False)


@dataclass
class _SessionBucket:
    last_index: int = 0
    items: OrderedDict[str, DatasetResult] = field(default_factory=OrderedDict)


class ResultStore:
    """Armazena `DatasetResult` indexados por `session_id` e `dataset_id` (D1..Dn)."""

    def __init__(
        self,
        base_dir: Path | str | None = None,
        *,
        max_datasets: int = DEFAULT_MAX_DATASETS,
        max_rows: int = DEFAULT_MAX_ROWS,
        persist: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir).resolve() if base_dir is not None else DEFAULT_SESSIONS_DIR.resolve()
        self.max_datasets = max(1, int(max_datasets))
        self.max_rows = max(1, int(max_rows))
        self.persist = bool(persist)
        self._lock = threading.RLock()
        self._buckets: dict[str, _SessionBucket] = {}

    def _session_dir(self, session_id: str) -> Path:
        sid = _validate_safe_id(session_id, "session_id")
        target = (self.base_dir / sid).resolve()
        try:
            target.relative_to(self.base_dir)
        except ValueError as exc:
            raise ValueError(f"Caminho fora do diretório de sessões para {session_id!r}.") from exc
        return target

    def _ensure_loaded(self, session_id: str) -> _SessionBucket:
        sid = _validate_safe_id(session_id, "session_id")
        bucket = self._buckets.get(sid)
        if bucket is not None:
            return bucket

        bucket = _SessionBucket()
        if self.persist:
            sdir = self._session_dir(sid)
            meta_path = sdir / "meta.json"
            if meta_path.is_file():
                try:
                    raw = json.loads(meta_path.read_text(encoding="utf-8"))
                    bucket.last_index = max(0, int(raw.get("last_index") or 0))
                    for entry in raw.get("datasets") or []:
                        did = _validate_safe_id(str(entry.get("dataset_id") or ""), "dataset_id")
                        pq_file = _validate_safe_id(
                            str(entry.get("parquet_file") or f"{did}.parquet").removesuffix(".parquet"),
                            "parquet_file",
                        ) + ".parquet"
                        pq_path = (sdir / pq_file).resolve()
                        pq_path.relative_to(sdir)
                        if not pq_path.is_file():
                            continue
                        df = pd.read_parquet(pq_path)
                        if len(df) > self.max_rows:
                            df = df.head(self.max_rows).copy()
                        ds = DatasetResult(
                            dataset_id=did,
                            database=str(entry.get("database") or "trase.duckdb"),
                            source_label=str(entry.get("source_label") or "Trase"),
                            tool_name=str(entry.get("tool_name") or ""),
                            query_summary=str(entry.get("query_summary") or ""),
                            df=df,
                            purpose=str(entry.get("purpose") or ""),
                            truncated=bool(entry.get("truncated", False)),
                            seconds=float(entry.get("seconds") or 0.0),
                        )
                        bucket.items[did] = ds
                        m = _LABEL_NUM_RE.match(did)
                        if m:
                            bucket.last_index = max(bucket.last_index, int(m.group(1)))
                    while len(bucket.items) > self.max_datasets:
                        bucket.items.popitem(last=False)
                except Exception:
                    bucket = _SessionBucket()

        self._buckets[sid] = bucket
        return bucket

    def _write_meta(self, session_id: str, bucket: _SessionBucket) -> None:
        if not self.persist:
            return
        sdir = self._session_dir(session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        meta = {
            "session_id": session_id,
            "last_index": bucket.last_index,
            "datasets": [
                {
                    "dataset_id": ds.dataset_id,
                    "database": ds.database,
                    "source_label": ds.source_label,
                    "tool_name": ds.tool_name,
                    "query_summary": ds.query_summary,
                    "purpose": ds.purpose,
                    "truncated": ds.truncated,
                    "seconds": ds.seconds,
                    "rows": len(ds.df),
                    "columns": [str(c) for c in ds.df.columns],
                    "parquet_file": f"{ds.dataset_id}.parquet",
                }
                for ds in bucket.items.values()
            ],
        }
        meta_path = sdir / "meta.json"
        tmp_path = sdir / "meta.json.tmp"
        tmp_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(meta_path)

    def last_index(self, session_id: str) -> int:
        with self._lock:
            return self._ensure_loaded(session_id).last_index

    def allocate_label(self, session_id: str) -> str:
        """Reserva o próximo rótulo sequencial (`D1`, `D2`...) na sessão."""
        with self._lock:
            sid = _validate_safe_id(session_id, "session_id")
            bucket = self._ensure_loaded(sid)
            bucket.last_index += 1
            self._write_meta(sid, bucket)
            return f"D{bucket.last_index}"

    def put(self, session_id: str, dataset: DatasetResult) -> DatasetResult:
        """Grava um `DatasetResult` na sessão (aplicando limites e persistência Parquet)."""
        with self._lock:
            sid = _validate_safe_id(session_id, "session_id")
            did = _validate_safe_id(dataset.dataset_id, "dataset_id")
            bucket = self._ensure_loaded(sid)

            m = _LABEL_NUM_RE.match(did)
            if m:
                bucket.last_index = max(bucket.last_index, int(m.group(1)))

            over_limit = len(dataset.df) > self.max_rows
            df_trimmed = dataset.df.head(self.max_rows).copy()
            stored = DatasetResult(
                dataset_id=did,
                database=dataset.database,
                source_label=dataset.source_label,
                tool_name=dataset.tool_name,
                query_summary=dataset.query_summary,
                df=df_trimmed,
                purpose=dataset.purpose,
                truncated=bool(dataset.truncated or over_limit),
                seconds=dataset.seconds,
            )

            if did in bucket.items:
                bucket.items.move_to_end(did)
            bucket.items[did] = stored

            evicted_ids: list[str] = []
            while len(bucket.items) > self.max_datasets:
                old_id, _ = bucket.items.popitem(last=False)
                evicted_ids.append(old_id)

            if self.persist:
                sdir = self._session_dir(sid)
                sdir.mkdir(parents=True, exist_ok=True)
                _safe_write_parquet(stored.df, sdir / f"{did}.parquet")
                for old_id in evicted_ids:
                    (sdir / f"{old_id}.parquet").unlink(missing_ok=True)
                self._write_meta(sid, bucket)

            return stored

    def get(self, session_id: str, dataset_id: str) -> DatasetResult | None:
        with self._lock:
            bucket = self._ensure_loaded(session_id)
            return bucket.items.get(dataset_id)

    def get_datasets(self, session_id: str, *, non_empty_only: bool = False) -> list[DatasetResult]:
        with self._lock:
            bucket = self._ensure_loaded(session_id)
            items = list(bucket.items.values())
            if non_empty_only:
                return [d for d in items if not d.df.empty]
            return items

    def has_data(self, session_id: str) -> bool:
        return bool(self.get_datasets(session_id, non_empty_only=True))

    def clear(self, session_id: str) -> None:
        with self._lock:
            sid = _validate_safe_id(session_id, "session_id")
            self._buckets.pop(sid, None)
            if self.persist:
                sdir = self._session_dir(sid)
                if sdir.is_dir():
                    for f in sdir.glob("*.parquet"):
                        f.unlink(missing_ok=True)
                    (sdir / "meta.json").unlink(missing_ok=True)

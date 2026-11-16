"""Registro de cada carga (quem gerou os dados): vai para data/lake/_runs/<run_id>.json e para a tabela meta_runs do banco do agente.

Serve para rastrear qualquer resposta ou rodada de avaliação até o código (commit) e a fonte (SHA-256) que geraram os dados.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from src import config
from src.medallion.core import Lake, git_info


def collect_quality(lake: Lake) -> dict:
    total = warn_failed = 0
    for f in sorted(lake.logs.glob("quality_*.json")):
        for c in json.loads(f.read_text(encoding="utf-8")):
            total += 1
            warn_failed += int((not c["passed"]) and c["level"] == "warn")
    return {"quality_checks": total, "quality_warnings_failed": warn_failed}


def new_run(lake: Lake, *, soy_manifest: dict, inpe_manifest: dict | None, rows: dict, gold_tables: dict[str, int]) -> dict:
    now = datetime.now(timezone.utc)
    git = git_info()
    run = {
        "run_id": now.strftime("%Y%m%dT%H%M%SZ") + "-" + git["git_commit"][:7],
        "built_at": now.isoformat(timespec="seconds"), **git,
        "source_name": soy_manifest.get("source"), "source_sha256": soy_manifest.get("sha256"),
        "rows_bronze": rows["bronze"], "rows_silver": rows["silver"], "rows_analytic": rows["analytic"],
        **collect_quality(lake),
        "inpe_sources": json.dumps((inpe_manifest or {}).get("shas", {}), ensure_ascii=False),
        "gold_tables": json.dumps(gold_tables, ensure_ascii=False),
    }
    lake.runs.mkdir(parents=True, exist_ok=True)
    (lake.runs / f"{run['run_id']}.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    return run


def run_frame(run: dict) -> pd.DataFrame:
    return pd.DataFrame([run])


def _latest(con) -> dict | None:
    df = con.execute("SELECT * FROM meta_runs ORDER BY built_at DESC LIMIT 1").fetchdf()
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in df.iloc[0].to_dict().items()} if len(df) else None


def provenance(db_path: Path | None = None) -> dict | None:
    """Última carga registrada no banco do agente; None se não houver banco gold. Nunca levanta erro.

    Sem db_path usa a MESMA conexão sandbox do agente (src.soy.queries._connect): o DuckDB não abre o mesmo arquivo com
    configurações diferentes no mesmo processo (ex.: servidor web), e uma falha aqui apagaria a origem dos dados em silêncio.
    """
    try:
        if db_path is None:
            from src.soy import queries as soy_queries
            if not soy_queries.using_gold():
                return None
            con = soy_queries._connect()
        else:
            con = duckdb.connect(str(db_path), read_only=True)
        try:
            return _latest(con)
        finally:
            con.close()
    except Exception:
        return None


def prompt_line(run: dict | None) -> str:
    if not run:
        return ""
    return f"Origem dos dados: {run['source_name']}; carga {run['run_id']} em {str(run['built_at'])[:10]}."

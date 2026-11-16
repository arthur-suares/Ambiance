"""Banco do agente (SOY_GOLD_DUCKDB_PATH): só a camada gold + catálogo + registro + tabelas de apoio.

NÃO contém a tabela bruta da cadeia (soy_supply_chain). Com SOY_USE_GOLD=1 o agente (inclusive o run_soy_sql) só enxerga
este arquivo, então não há como pular as regras da gold consultando o dado cru.
As demais tabelas da soja (métricas territoriais, instalações...) vêm do banco do ingest-soy, se ele existir.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

from src import config
from src.medallion import catalog
from src.medallion.core import Lake

EXCLUDED_AUX = {"soy_supply_chain", "soy_dataset_metadata"}     # cadeia bruta: de propósito fora do banco do agente


def build(lake: Lake, run_frame, target: Path | None = None, aux_db: Path | None = None) -> dict:
    target = Path(target) if target is not None else config.SOY_GOLD_DUCKDB_PATH
    aux = Path(aux_db) if aux_db is not None else config.SOY_DUCKDB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".duckdb.tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    copied = []
    try:
        for f in sorted(lake.gold.glob("*.parquet")):
            con.execute(f"CREATE TABLE {f.stem} AS SELECT * FROM read_parquet('{f.as_posix()}')")
        con.register("catalog_df", catalog.catalog_frame())
        con.execute("CREATE TABLE gold_catalog AS SELECT * FROM catalog_df")
        con.register("run_df", run_frame)
        con.execute("CREATE TABLE meta_runs AS SELECT * FROM run_df")
        if aux.exists():
            con.execute(f"ATTACH '{aux.as_posix()}' AS aux (READ_ONLY)")
            for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'aux' AND table_schema = 'main'").fetchall():
                if t not in EXCLUDED_AUX:
                    con.execute(f'CREATE TABLE main."{t}" AS SELECT * FROM aux.main."{t}"')
                    copied.append(t)
            con.execute("DETACH aux")
        con.unregister("catalog_df")
        con.unregister("run_df")
        tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_type = 'BASE TABLE' ORDER BY 1").fetchall()]
    finally:
        con.close()
    os.replace(tmp, target)                      # troca atômica: um agente que está lendo o arquivo antigo não quebra
    return {"path": str(target), "tables": tables, "aux_copied": copied, "aux_found": aux.exists()}

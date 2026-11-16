"""Orquestra o medalhão da soja: bronze -> silver -> gold (soja + INPE) -> banco do agente -> registro -> dicionário.

    python -m src.cli build-medallion [--raw ARQUIVO.parquet] [--force] [--no-inpe]

Cada camada só é gerada se o portão de qualidade da anterior passou; se um portão bloqueia, o banco do agente NÃO é trocado.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from src import config
from src.medallion import agent_db, catalog, inpe, registry, soy_flows
from src.medallion.core import Lake, QualityGateError

DOC_PATH = config.PROJECT_ROOT / "docs" / "dicionario_gold.md"


def build(raw: Path | None = None, force: bool = False, with_inpe: bool = True, lake: Lake | None = None,
          target: Path | None = None, aux_db: Path | None = None, write_docs: bool = True) -> dict:
    lake = lake or Lake()
    raw = Path(raw) if raw is not None else config.SOY_RAW_PARQUET
    if not raw.exists():
        raise FileNotFoundError(f"Fonte da soja não encontrada: {raw}. Defina SOY_RAW_PARQUET ou passe --raw.")
    t0 = time.perf_counter()
    manifest = soy_flows.build_bronze(lake, raw, force)
    silver, log = soy_flows.build_silver(lake)
    gold = soy_flows.build_gold(lake, silver)
    inpe_manifest = None
    if with_inpe and inpe.available(config.INPE_RAW_DIR):
        inpe_manifest = inpe.build_bronze(lake, config.INPE_RAW_DIR, force)
        gold.update(inpe.build_gold(lake, silver, inpe.build_silver(lake, silver)))
    elif with_inpe:
        print(f"[inpe] fontes não encontradas em {config.INPE_RAW_DIR}: etapa do INPE ignorada.")
    run = registry.new_run(lake, soy_manifest=manifest, inpe_manifest=inpe_manifest,
                           rows={"bronze": log["rows_bronze"], "silver": log["rows_silver"], "analytic": log["is_analytic"]},
                           gold_tables={k: len(v) for k, v in gold.items()})
    info = agent_db.build(lake, registry.run_frame(run), target, aux_db)
    if write_docs:
        DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOC_PATH.write_text(catalog.render_markdown(), encoding="utf-8")
    print(f"[ok] carga {run['run_id']} em {time.perf_counter() - t0:.0f}s -> {info['path']} ({len(info['tables'])} tabelas)")
    return {"run": run, "agent_db": info}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, help="parquet do Trase soja (padrão: SOY_RAW_PARQUET)")
    ap.add_argument("--force", action="store_true", help="refaz a bronze mesmo com a mesma fonte")
    ap.add_argument("--no-inpe", action="store_true", help="pula as camadas do INPE")
    a = ap.parse_args(argv)
    try:
        build(a.raw, a.force, not a.no_inpe)
    except QualityGateError as e:
        print("PORTÃO DE QUALIDADE BLOQUEOU A CARGA (o banco do agente não foi alterado):", e)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

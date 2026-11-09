"""Converte os CSVs do Trase para Parquet usando DuckDB.

Uso:
    python scripts/csv_to_parquet.py                      # data/raw/*.csv -> data/processed/parquet/
    python scripts/csv_to_parquet.py arquivo.csv outro.csv
    python scripts/csv_to_parquet.py --out data/processed/parquet --force

- Tipos inferidos lendo o arquivo inteiro (sample_size=-1), para não errar coluna numérica.
- Compressão ZSTD.
- Pula arquivos cujo Parquet já é mais novo que o CSV (use --force para refazer).
- Ao final confere se o número de linhas do Parquet bate com o do CSV.
"""

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "data" / "raw"
DEFAULT_OUT = ROOT / "data" / "processed" / "parquet"


def sql_str(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def convert(con, csv: Path, out_dir: Path, force: bool) -> None:
    target = out_dir / (csv.stem + ".parquet")
    if target.exists() and not force and target.stat().st_mtime >= csv.stat().st_mtime:
        print(f"= {csv.name}: já convertido ({target.name})")
        return

    src = f"read_csv_auto({sql_str(csv)}, header = true, sample_size = -1)"
    tmp = target.with_suffix(".parquet.tmp")
    con.execute(f"COPY (SELECT * FROM {src}) TO {sql_str(tmp)} (FORMAT parquet, COMPRESSION zstd)")

    csv_rows = con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]
    pq_rows = con.execute(f"SELECT COUNT(*) FROM read_parquet({sql_str(tmp)})").fetchone()[0]
    if csv_rows != pq_rows:
        tmp.unlink()
        raise RuntimeError(f"{csv.name}: CSV tem {csv_rows} linhas, Parquet ficou com {pq_rows}.")
    tmp.replace(target)

    mb = lambda p: p.stat().st_size / 1_048_576
    cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_str(target)})").fetchall()
    print(f"+ {csv.name} -> {target.name}: {pq_rows:,} linhas, "
          f"{mb(csv):.1f} MB -> {mb(target):.1f} MB")
    for name, dtype, *_ in cols:
        print(f"    {name}: {dtype}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="CSVs a converter (padrão: data/raw/*.csv)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Pasta de saída")
    ap.add_argument("--force", action="store_true", help="Reconverte mesmo se já existir")
    args = ap.parse_args()

    files = args.files or sorted(DEFAULT_IN.glob("*.csv"))
    if not files:
        print(f"Nenhum CSV encontrado em {DEFAULT_IN}.")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    failed = 0
    for csv in files:
        try:
            convert(con, csv.resolve(), args.out, args.force)
        except Exception as e:
            failed += 1
            print(f"! {csv.name}: {type(e).__name__}: {e}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

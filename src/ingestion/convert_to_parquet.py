
from pathlib import Path
import duckdb

# Diretórios do projeto
PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def convert_csv_to_parquet(csv_path: Path) -> Path:
    """
    Converte um CSV para Parquet utilizando DuckDB.
    """

    if not csv_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {csv_path}")

    parquet_path = PROCESSED_DIR / f"{csv_path.stem}.parquet"

    con = duckdb.connect()

    try:
        # Lê o CSV e converte diretamente para Parquet
        con.execute(
            """
            COPY (
                SELECT *
                FROM read_csv_auto(?, sample_size=-1)
            )
            TO ?
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """,
            [str(csv_path), str(parquet_path)]
        )

        print(f"Conversão concluída: {parquet_path}")

    finally:
        con.close()

    return parquet_path


if __name__ == "__main__":
    for csv_file in RAW_DIR.glob("*.csv"):
        convert_csv_to_parquet(csv_file)

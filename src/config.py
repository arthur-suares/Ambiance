from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


CSV_PATH = resolve_project_path(
    os.getenv("TRASE_CSV_PATH", "data/raw/brazil_beef.csv")
)
DUCKDB_PATH = resolve_project_path(
    os.getenv("DUCKDB_PATH", "data/processed/trase.duckdb")
)
TABLE_NAME = os.getenv("TRASE_TABLE_NAME", "supply_chain")

if not TABLE_NAME.replace("_", "").isalnum():
    raise ValueError("TRASE_TABLE_NAME deve conter apenas letras, números e underscore.")

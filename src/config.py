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


# --- Camada tabular (Parquet -> DuckDB) ---
# Os Parquet são a fonte; o arquivo DuckDB é gerado a partir deles (python -m src.cli build-db).
PARQUET_DIR = resolve_project_path(os.getenv("PARQUET_DIR", "data/processed/parquet"))
SUPPLY_CHAIN_FILE = os.getenv("SUPPLY_CHAIN_FILE", "brazil_beef_v2_2_2.parquet")
SPATIAL_METRICS_GLOB = os.getenv("SPATIAL_METRICS_GLOB", "spatial-metrics-brazil-beef-*.parquet")
FACILITIES_GLOB = os.getenv("FACILITIES_GLOB", "*br_beef_logistics_map*.parquet")
DUCKDB_PATH = resolve_project_path(
    os.getenv("DUCKDB_PATH", "data/processed/trase.duckdb")
)
TABLE_NAME = "supply_chain"
# Limites do SQL gerado pelo LLM.
SQL_TIMEOUT_SECONDS = float(os.getenv("SQL_TIMEOUT_SECONDS", "20"))
SQL_MAX_ROWS = int(os.getenv("SQL_MAX_ROWS", "200"))

# --- Camada documental (PostgreSQL + pgvector) ---
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5433"))
PG_USER = os.getenv("PG_USER", "rag")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DATABASE = os.getenv("PG_DATABASE", "trase_rag")
PG_CONNECT_TIMEOUT = int(os.getenv("PG_CONNECT_TIMEOUT", "5"))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
FTS_CONFIG = os.getenv("FTS_CONFIG", "portuguese")

if not FTS_CONFIG.isalpha():
    raise ValueError("FTS_CONFIG deve ser o nome de uma configuração de texto do Postgres (ex.: english, portuguese).")

# --- LLM (geração) via OpenRouter, endpoint compatível com a API da Anthropic ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api")
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-haiku-5.5")

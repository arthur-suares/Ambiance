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

# --- Camada documental (PostgreSQL + pgvector) ---
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5433"))
PG_USER = os.getenv("PG_USER", "rag")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DATABASE = os.getenv("PG_DATABASE", "trase_rag")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
FTS_CONFIG = os.getenv("FTS_CONFIG", "portuguese")

if not FTS_CONFIG.isalpha():
    raise ValueError("FTS_CONFIG deve ser o nome de uma configuração de texto do Postgres (ex.: english, portuguese).")

# --- LLM (geração) via OpenRouter, endpoint compatível com a API da Anthropic ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api")
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-haiku-5.5")

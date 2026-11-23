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

# --- Camada tabular da soja (banco DuckDB separado, gerado por python -m src.cli ingest-soy) ---
SOY_DUCKDB_PATH = resolve_project_path(
    os.getenv("SOY_DUCKDB_PATH", "data/processed/soy/soy.duckdb")
)
SOY_DATA_ROOT = resolve_project_path(
    os.getenv("SOY_DATA_ROOT", "data")
)

# --- Camada documental (PostgreSQL + pgvector) ---
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5433"))
PG_USER = os.getenv("PG_USER", "rag")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DATABASE = os.getenv("PG_DATABASE", "trase_rag")
PG_CONNECT_TIMEOUT = int(os.getenv("PG_CONNECT_TIMEOUT", "5"))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
FTS_CONFIG = os.getenv("FTS_CONFIG", "portuguese")

if not FTS_CONFIG.isalpha():
    raise ValueError("FTS_CONFIG deve ser o nome de uma configuração de texto do Postgres (ex.: english, portuguese).")

# --- LLM (geração) via OpenRouter, endpoint compatível com a API da Anthropic ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api")
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-haiku-5.5")
# LLM_THINKING=disabled manda thinking={"type": "disabled"} em todas as chamadas (ex.: modelos que raciocinam
# por padrão, como o DeepSeek, e gastariam o max_tokens só pensando). Vazio = padrão do modelo.
LLM_THINKING = os.getenv("LLM_THINKING", "").strip().lower()
LLM_EXTRA_PARAMS: dict = {"thinking": {"type": "disabled"}} if LLM_THINKING == "disabled" else {}
# Limite de tokens de saída de cada chamada do agente. Com thinking ligado o raciocínio sai desse mesmo
# limite, então ele precisa ser maior (senão a resposta volta cortada, stop_reason = max_tokens).
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8000"))

# --- LLM-as-a-judge (eval/judge.py) ---
# JUDGE_MODEL vazio = mesmo modelo do agente (e o mesmo LLM_THINKING). Com outro modelo, o thinking do juiz
# vem só de JUDGE_THINKING, para a configuração do agente (ex.: DeepSeek sem thinking) não vazar para o juiz.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "").strip() or LLM_MODEL
JUDGE_THINKING = os.getenv("JUDGE_THINKING", LLM_THINKING if JUDGE_MODEL == LLM_MODEL else "").strip().lower()
JUDGE_EXTRA_PARAMS: dict = {"thinking": {"type": "disabled"}} if JUDGE_THINKING == "disabled" else {}

# --- Dashboards gerados dinamicamente ---
DASHBOARD_OUTPUT_DIR = resolve_project_path(
    os.getenv("DASHBOARD_OUTPUT_DIR", "outputs/dashboards")
)

# --- Entrada e saída por voz (multimodal via Gemini) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "gemini").strip().lower() or "gemini"
VOICE_MODEL = os.getenv("VOICE_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
VOICE_TTS_MODEL = os.getenv("VOICE_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip() or "gemini-2.5-flash-preview-tts"
VOICE_TTS_VOICE = os.getenv("VOICE_TTS_VOICE", "Kore").strip() or "Kore"
VOICE_TTS_MAX_CHARS = int(os.getenv("VOICE_TTS_MAX_CHARS", "4000"))
VOICE_MAX_SECONDS = int(os.getenv("VOICE_MAX_SECONDS", "60"))
_VOICE_RECORD_DIR_RAW = os.getenv("VOICE_RECORD_DIR", "").strip()
VOICE_RECORD_DIR: Path | None = (
    resolve_project_path(_VOICE_RECORD_DIR_RAW) if _VOICE_RECORD_DIR_RAW else None
)

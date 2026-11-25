"""Cache persistente de painéis gerados: `outputs/dashboards/cache.json` (hash da pergunta + contexto -> arquivo HTML).

- A pergunta é normalizada (minúsculas, sem acento, espaços colapsados) antes do hash; o contexto da aba Dados
  (`{"charts": [...], "tables": [...]}`) entra na chave: contexto diferente = outra entrada.
- Só vale se o HTML ainda existir em `DASHBOARD_OUTPUT_DIR` e se a entrada não passou de `DASHBOARD_CACHE_DAYS`.
- Escrita do JSON com lock + arquivo temporário + `os.replace` (nunca deixa um cache.json pela metade).
- Nada é lido nem gravado fora da pasta de painéis; nomes de arquivo só aceitam `[A-Za-z0-9_-]+.html`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import unicodedata

import src.config as config_mod

logger = logging.getLogger(__name__)

CACHE_FILENAME = "cache.json"
SAFE_HTML_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.html$")
_CACHE_LOCK = threading.Lock()


def normalize_question(question: str | None) -> str:
    """Minúsculas, sem acentos e com espaços colapsados: 'Pará  ?' e 'para ?' dão o mesmo texto."""
    text = unicodedata.normalize("NFKD", str(question or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _canonicalize_context(chat_context: dict | None):
    """None, {} e {"charts": [], "tables": []} são o mesmo contexto (vazio)."""
    if not isinstance(chat_context, dict):
        return None
    filtered = {k: v for k, v in chat_context.items() if v not in (None, [], {}, "")}
    return filtered or None


def _render_version() -> str:
    """Impressão digital do código que desenha o painel (o visual vai dentro do HTML guardado).
    Mudou o renderer/tema/animações → chave nova → o painel é gerado de novo com o visual atual,
    em vez de servir por 7 dias uma página com o visual antigo."""
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in ("renderer.py", "embed_theme.py", "interaction.py"):
        try:
            h.update((here / name).read_bytes())
        except OSError:
            h.update(name.encode())
    return h.hexdigest()[:12]


RENDER_VERSION = _render_version()


def dashboard_cache_key(question: str, chat_context: dict | None) -> str:
    payload = json.dumps([normalize_question(question), _canonicalize_context(chat_context), RENDER_VERSION],
                         sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _root(base_dir: Path | str | None) -> Path:
    return Path(base_dir) if base_dir is not None else Path(config_mod.DASHBOARD_OUTPUT_DIR)


def _safe_html_path(root: Path, filename) -> Path | None:
    """Caminho do HTML dentro de `root`, ou None se o nome for suspeito ou o arquivo não existir."""
    if not isinstance(filename, str) or not SAFE_HTML_NAME_RE.fullmatch(filename):
        return None
    try:
        base = root.resolve()
        candidate = (base / filename).resolve()
    except (OSError, RuntimeError):
        return None
    if candidate.parent != base or not candidate.is_file():
        return None
    return candidate


def _read_cache_unlocked(cache_path: Path) -> dict[str, dict]:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("cache de painéis ilegível (%s); começando vazio: %s", cache_path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("cache de painéis com formato inesperado em %s; começando vazio", cache_path)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _write_cache_atomic_unlocked(cache_path: Path, data: dict[str, dict]) -> bool:
    tmp_name = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, prefix=".cache_",
                                         suffix=".tmp", delete=False) as tmp:
            tmp_name = tmp.name
            json.dump(data, tmp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, cache_path)
        return True
    except OSError as exc:
        logger.warning("não consegui gravar o cache de painéis em %s: %s", cache_path, exc)
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                logger.warning("arquivo temporário do cache não removido: %s", tmp_name)
        return False


def get_cached_dashboard(question: str, chat_context: dict | None, *, base_dir: Path | str | None = None,
                         max_age_days: float | None = None, now: float | None = None) -> dict | None:
    """Painel já gerado para (pergunta, contexto), ou None (sem entrada, expirado, arquivo apagado ou inválido)."""
    root = _root(base_dir)
    ttl_days = config_mod.DASHBOARD_CACHE_DAYS if max_age_days is None else max_age_days
    if ttl_days <= 0:
        return None
    key = dashboard_cache_key(question, chat_context)
    ts_now = time.time() if now is None else now
    cache_path = root / CACHE_FILENAME
    with _CACHE_LOCK:
        data = _read_cache_unlocked(cache_path)
        entry = data.get(key)
        if entry is None:
            return None
        created = entry.get("created_at")
        fresh = isinstance(created, (int, float)) and not isinstance(created, bool) \
            and 0 <= ts_now - created <= ttl_days * 86400
        if not fresh or _safe_html_path(root, entry.get("filename")) is None:
            data.pop(key, None)  # expirada, arquivo apagado ou nome inválido: some do cache
            _write_cache_atomic_unlocked(cache_path, data)
            return None
        return {
            "filename": entry["filename"],
            "title": str(entry.get("title") or ""),
            "domain": str(entry.get("domain") or "auto"),
            "created_at": created,
        }


def save_cached_dashboard(question: str, chat_context: dict | None, *, output_path: Path | str,
                          title: str = "", domain: str = "auto", base_dir: Path | str | None = None,
                          now: float | None = None) -> bool:
    """Registra o painel gerado. Recusa (False) qualquer arquivo fora da pasta de painéis ou que não exista."""
    root = _root(base_dir)
    candidate = _safe_html_path(root, Path(output_path).name)
    try:
        inside = candidate is not None and candidate == Path(output_path).resolve()
    except (OSError, RuntimeError):
        inside = False
    if not inside:
        logger.warning("painel fora de %s ou inexistente não entra no cache: %s", root, output_path)
        return False
    key = dashboard_cache_key(question, chat_context)
    ts_now = time.time() if now is None else now
    cache_path = root / CACHE_FILENAME
    with _CACHE_LOCK:
        data = _read_cache_unlocked(cache_path)
        data[key] = {
            "filename": candidate.name,
            "title": str(title or ""),
            "domain": str(domain or "auto"),
            "created_at": ts_now,
            "question": normalize_question(question),
        }
        return _write_cache_atomic_unlocked(cache_path, data)

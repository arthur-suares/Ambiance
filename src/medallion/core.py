"""Peças comuns do medalhão: caminhos, portões de qualidade, hash e leitura/escrita segura.

Este módulo não conhece nenhuma fonte de dados (soja, INPE...). Outra fonte pode reaproveitá-lo.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from src import config


# ----------------------------------------------------------------------------- caminhos

class Lake:
    """Pastas do medalhão (tudo derivado de config.MEDALLION_DIR)."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else config.MEDALLION_DIR
        self.bronze, self.silver, self.gold = (self.root / n for n in ("bronze", "silver", "gold"))
        self.logs, self.runs = self.root / "_logs", self.root / "_runs"


def reset_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_info() -> dict:
    """Commit e estado do código que gerou a carga (para rastrear cada resposta até a versão do código)."""
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=config.PROJECT_ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    commit = run("rev-parse", "HEAD")
    return {"git_commit": commit or "desconhecido", "git_dirty": bool(run("status", "--porcelain")) if commit else None}


# ----------------------------------------------------------------------------- nomes e chaves

def normalize_name(value) -> str:
    """'São José do Rio Claro' -> 'SAO JOSE DO RIO CLARO' (mesma regra para todas as fontes)."""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9 ]", "", text).strip()


MUNICIPALITY_ID_RE = re.compile(r"^\d{7}$")


def municipality_id_from_trase(trase_id) -> str | None:
    """'BR-2100600' -> '2100600': chave única de município (IBGE, 7 dígitos) em todas as tabelas.
    O município fictício do Trase ('BR-XXXXXXX', origem desconhecida) não é um município: vira None."""
    code = str(trase_id).split("-", 1)[-1]
    return code if MUNICIPALITY_ID_RE.match(code) else None

UF_BY_IBGE_PREFIX = {'11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA', '16': 'AP', '17': 'TO', '21': 'MA',
                     '22': 'PI', '23': 'CE', '24': 'RN', '25': 'PB', '26': 'PE', '27': 'AL', '28': 'SE', '29': 'BA',
                     '31': 'MG', '32': 'ES', '33': 'RJ', '35': 'SP', '41': 'PR', '42': 'SC', '43': 'RS', '50': 'MS',
                     '51': 'MT', '52': 'GO', '53': 'DF'}


# ----------------------------------------------------------------------------- qualidade

@dataclass
class Check:
    name: str
    level: str          # "blocks": se falhar, a próxima camada NÃO é gerada | "warn": só registra
    passed: bool
    detail: str = ""

    def __post_init__(self):
        self.passed = bool(self.passed)


class QualityGateError(RuntimeError):
    pass


def close(a: float, b: float, rel: float = 1e-9) -> bool:
    return abs(a - b) <= max(abs(a), abs(b), 1.0) * rel


def enforce(layer: str, checks: list[Check], log_dir: Path) -> list[Check]:
    """Grava o resultado da camada e bloqueia se alguma checagem 'blocks' falhou."""
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"quality_{layer}.json").write_text(
        json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=1), encoding="utf-8")
    failed = [c for c in checks if not c.passed and c.level == "blocks"]
    if failed:
        raise QualityGateError(f"[{layer}] {len(failed)} checagem(ns) bloqueante(s) falharam: "
                               + "; ".join(f"{c.name} ({c.detail})" for c in failed))
    return checks

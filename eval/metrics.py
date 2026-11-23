"""Métricas sem LLM: ranking das leis (Hit Rate@k, Recall@k, MRR), precisão média
(fórmula do Context Precision) e checagem de valores numéricos.

Funções puras, testadas em tests/test_eval_metrics.py.
"""

from __future__ import annotations

import math
import re
import unicodedata

KS = (1, 3, 5, 10)

# ----------------------------------------------------------------------------- leis

_LAW_NUMBER = re.compile(r"\d{1,2}\.\d{3}")


def law_key(title: str) -> str:
    """Identifica a lei pelo número: 'Lei nº 12.651/2012 – Código Florestal' -> '12.651'."""
    m = _LAW_NUMBER.search(title or "")
    return m.group(0) if m else (title or "").strip()


def article_key(lei: str, artigo) -> tuple[str, str]:
    return law_key(lei), str(artigo).strip()


def chunk_key(chunk: dict) -> tuple[str, str]:
    return article_key(chunk["title"], (chunk.get("metadata") or {}).get("artigo"))


def gold_sets(item: dict) -> tuple[set, set]:
    """(essenciais, essenciais + complementares) do gabarito, como chaves (lei, artigo)."""
    essenciais = {article_key(a["lei"], a["artigo"]) for a in item["artigos"] if a.get("nivel", "essencial") == "essencial"}
    todos = {article_key(a["lei"], a["artigo"]) for a in item["artigos"]}
    return essenciais, todos


def first_positions(chunks: list[dict]) -> dict[tuple[str, str], int]:
    """Posição (1 = primeiro chunk) em que cada artigo aparece pela primeira vez.
    Um artigo dividido em partes conta uma vez, na posição da primeira parte."""
    pos: dict[tuple[str, str], int] = {}
    for i, c in enumerate(chunks, start=1):
        pos.setdefault(chunk_key(c), i)
    return pos


def ranking_scores(first_pos: dict, essenciais: set, todos: set, ks=KS) -> dict:
    """Hit@k e MRR sobre os essenciais; Recall@k sobre essenciais + complementares."""
    inf = math.inf
    out = {}
    for k in ks:
        out[f"hit@{k}"] = 1.0 if any(first_pos.get(a, inf) <= k for a in essenciais) else 0.0
        out[f"recall@{k}"] = sum(first_pos.get(a, inf) <= k for a in todos) / len(todos) if todos else 0.0
    first = min((first_pos.get(a, inf) for a in essenciais), default=inf)
    out["primeiro_essencial"] = None if first == inf or first > max(ks) else int(first)
    out["mrr"] = 1.0 / first if out["primeiro_essencial"] else 0.0
    return out


def average_precision(flags: list[bool]) -> float:
    """Média da precisão@i nas posições úteis (Context Precision do RAGAS).
    Ex.: [útil, inútil, útil, inútil] -> (1/1 + 2/3) / 2 = 0,83. Sem item útil -> 0."""
    hits, total = 0, 0.0
    for i, useful in enumerate(flags, start=1):
        if useful:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0


# ----------------------------------------------------------------------------- números

SCALES = {"mil": 1e3, "milhao": 1e6, "milhoes": 1e6, "mi": 1e6, "bilhao": 1e9, "bilhoes": 1e9, "bi": 1e9}
NUMBER_RE = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)*)(?:\s*(milhoes|milhao|bilhoes|bilhao|mil|mi|bi)\b)?", re.IGNORECASE
)
_BR_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")


def strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _to_float(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def br_value(token: str) -> float | None:
    """Leitura no formato brasileiro: '277.582,68' -> 277582.68; '1.000' -> 1000; '4.7' -> 4.7."""
    if "," in token:
        return _to_float(token.replace(".", "").replace(",", "."))
    if _BR_THOUSANDS.fullmatch(token):
        return _to_float(token.replace(".", ""))
    return _to_float(token)


def number_candidates(token: str, scale: str | None = None) -> set[float]:
    """Leituras possíveis de um número (formato BR e formato CSV/inglês), já com a escala."""
    mult = SCALES.get((scale or "").lower(), 1.0)
    cands = {br_value(token), _to_float(token.replace(",", ""))}
    return {c * mult for c in cands if c is not None}


def extract_numbers(text: str) -> list[tuple[str, set[float]]]:
    """[(trecho original, leituras possíveis)] para cada número do texto."""
    plain = strip_accents(text or "").lower()
    return [(m.group(0), number_candidates(m.group(1), m.group(2))) for m in NUMBER_RE.finditer(plain)]


def parse_br_number(text: str) -> float | None:
    """Primeiro número do texto, lido no formato brasileiro: '260,2 mil ha' -> 260200."""
    m = NUMBER_RE.search(strip_accents(text).lower())
    if not m:
        return None
    v = br_value(m.group(1))
    return None if v is None else v * SCALES.get((m.group(2) or "").lower(), 1.0)


def find_value(valor: float, tol_rel: float, text: str, csv: bool = False) -> dict | None:
    """Procura no texto um número igual ao esperado (dentro da tolerância relativa).
    csv=True também lê o texto com vírgulas como separador de colunas (saída das ferramentas
    de dados, ex. "JBS,277582.68"); use só no contexto, não na resposta em português.
    Devolve {trecho, lido, erro_rel} do mais próximo ou None."""
    best = None
    limit = max(abs(valor) * tol_rel, 1e-9)
    numbers = extract_numbers(text)
    if csv:
        numbers += extract_numbers((text or "").replace(",", " "))
    for raw, cands in numbers:
        for c in cands:
            diff = abs(c - valor)
            if diff <= limit and (best is None or diff < best[2]):
                best = (raw, c, diff)
    if best is None:
        return None
    return {"trecho": best[0].strip(), "lido": best[1], "erro_rel": best[2] / abs(valor) if valor else 0.0}


def mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None

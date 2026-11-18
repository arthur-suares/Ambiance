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


# ----------------------------------------------------------------------------- checagem estruturada
# A busca acima (find_value) aceita qualquer número próximo em qualquer lugar do texto: um valor de emissões da
# carne bovina já foi aceito como "produção de soja" só por estar dentro da tolerância. Aqui o número só conta
# se estiver no lugar certo: mesma cadeia, mesmo escopo, coluna da métrica, linha/filtro da entidade, ano e,
# em texto corrido (resposta e leis), acompanhado da unidade.

# Família da métrica -> trechos que identificam a coluna ("sim") e trechos de colunas de outra métrica ("nao").
METRIC_FAMILIES = {
    "exposicao": {"sim": ("exposure", "exposicao", "deforestation", "desmatamento"),
                  "nao": ("co2", "emission", "emiss", "per_t", "por_t")},
    "volume": {"sim": ("volume",), "nao": ("exposure", "exposicao")},
    "emissoes_brutas": {"sim": ("gross", "bruta"), "nao": ()},
    "participacao": {"sim": ("share", "pct", "particip", "percent"), "nao": ()},
    "producao": {"sim": ("production", "producao"), "nao": ()},
    "produtividade": {"sim": ("yield", "produtividade"), "nao": ()},
    "pastagem": {"sim": ("pasture", "pastagem"), "nao": ()},
    "zdc_pct": {"sim": ("zdc",), "nao": ()},
    "capacidade_processamento": {"sim": ("processing_capacity", "capacidade_process"), "nao": ()},
    "capacidade_armazenagem": {"sim": ("storage_capacity", "armazenagem"), "nao": ()},
    "instalacoes": {"sim": ("facilities", "instalac"), "nao": ("processing", "capacity")},
}
_TERRITORIAL_TOOLS = {"territorial_metric", "soy_territorial_metric"}
_FREE_SQL_TOOLS = {"run_sql", "run_soy_sql"}
_YEAR_COLUMNS = {"year", "ano"}
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_TOOL_IN_DESCRIPTION = re.compile(r"[–-] (\w+):")


def _norm(text) -> str:
    return strip_accents(str(text or "")).lower()


def parse_tool_table(text: str) -> tuple[list[str], list[list[str]], str]:
    """Saída de uma ferramenta de dados -> (colunas, linhas, legenda). Ignora a legenda '# ...' e o rodapé '(N linhas)'."""
    import csv
    legend, data = [], []
    for line in (text or "").splitlines():
        if line.startswith("#"):
            legend.append(line)
        elif line.strip() and not line.startswith(("(", "Resultado [")):
            data.append(line)
    rows = list(csv.reader(data))
    return (rows[0], rows[1:], "\n".join(legend)) if rows else ([], [], "\n".join(legend))


def item_tool(item: dict) -> str:
    """Nome da ferramenta que gerou um item do contexto (rodadas antigas só têm a descrição)."""
    if item.get("ferramenta"):
        return item["ferramenta"]
    m = _TOOL_IN_DESCRIPTION.search(item.get("descricao") or "")
    return m.group(1) if m else ""


def item_chain(item: dict) -> str:
    if item.get("cadeia"):
        return item["cadeia"]
    tool = item_tool(item)
    return "soja" if tool.startswith("soy_") or tool == "run_soy_sql" else "carne"


def item_scope(item: dict) -> str:
    """fluxos | territorial | instalacoes, pela ferramenta (ou, no SQL livre, pela tabela consultada)."""
    tool, call = item_tool(item), _norm(item.get("chamada"))
    if tool in _TERRITORIAL_TOOLS or (tool in _FREE_SQL_TOOLS and "spatial_metrics" in call):
        return "territorial"
    if "facilities" in tool or (tool in _FREE_SQL_TOOLS and "facilities" in call):
        return "instalacoes"
    return "fluxos"


def _has_term(term: str, haystack: str) -> bool:
    """term aceita alternativas separadas por '|' (ex.: 'MATO GROSSO|MT'); casa palavra inteira, sem acento/caixa."""
    return any(re.search(rf"(?<![a-z0-9]){re.escape(_norm(alt))}(?![a-z0-9])", haystack) for alt in term.split("|"))


def _why_not(v: dict, item: dict, col: str, row: list[str], header: list[str], legend: str) -> str | None:
    """Motivo para NÃO aceitar a célula (col, row) como o valor v do gabarito; None = aceita."""
    if v["cadeia"] != item_chain(item):
        return f"cadeia {item_chain(item)}, esperada {v['cadeia']}"
    if v.get("escopo") and v["escopo"] != item_scope(item):
        return f"escopo {item_scope(item)}, esperado {v['escopo']}"
    tool, call = item_tool(item), _norm(item.get("chamada"))
    family = METRIC_FAMILIES.get(v.get("metrica") or "")
    if family:
        name = _norm(col)
        labels = _norm(" ".join(c for c in row if _to_float(c) is None))  # formato longo: a métrica vem na linha
        if any(x in name for x in family["nao"]):
            return f"coluna '{col}' é de outra métrica"
        if not (any(x in name for x in family["sim"]) or any(x in labels for x in family["sim"])
                or (tool in _FREE_SQL_TOOLS and any(x in call for x in family["sim"]))):
            return f"coluna '{col}' não é da métrica {v['metrica']}"
    legend_facts = _norm("\n".join(l for l in legend.splitlines() if l.startswith(("# ano:", "# filtros:"))))
    haystack = " ".join([_norm(" ".join(row)), call, legend_facts])
    for term in v.get("termos") or []:
        if not _has_term(term, haystack):
            return f"sem '{term}' na linha nem nos filtros"
    year = v.get("ano")
    if year:
        year_cells = [c for h, c in zip(header, row) if _norm(h) in _YEAR_COLUMNS]
        if year_cells:
            if _to_float(year_cells[0]) != float(year):
                return f"linha do ano {year_cells[0]}, esperado {year}"
        else:
            mentioned = {int(y) for y in _YEAR_RE.findall(call + " " + legend_facts)}
            if mentioned and int(year) not in mentioned:
                return f"consulta de {sorted(mentioned)}, esperado {year}"
    return None


def find_in_table(v: dict, item: dict) -> tuple[dict | None, list[str]]:
    """Procura o valor v do gabarito num resultado de ferramenta de dados, exigindo cadeia, escopo, coluna da
    métrica, entidade e ano. Devolve (achado ou None, motivos das células numericamente próximas que foram rejeitadas)."""
    if item.get("tipo") != "dados" or item.get("ok") is False:
        return None, []
    header, rows, legend = parse_tool_table(item.get("texto") or "")
    limit = max(abs(v["valor"]) * v["tolerancia_rel"], 1e-9)
    best, rejected = None, []
    for row in rows:
        for col, cell in zip(header, row):
            x = _to_float(cell)
            if x is None or abs(x - v["valor"]) > limit:
                continue
            reason = _why_not(v, item, col, row, header, legend)
            if reason:
                rejected.append(f"{item['id']}: {cell} ({reason})")
            elif best is None or abs(x - v["valor"]) < best[0]:
                best = (abs(x - v["valor"]), {"trecho": cell, "lido": x, "coluna": col,
                                              "erro_rel": abs(x - v["valor"]) / abs(v["valor"]) if v["valor"] else 0.0})
    return (best[1] if best else None), rejected


# Unidade em texto corrido. "depois": o que deve vir logo após o número; "antes": logo antes (moeda).
_UNITS = {
    "%": {"depois": r"%|por cento"},
    "ha": {"depois": r"ha\b|hectares?"},
    "t": {"depois": r"(?:t\b|toneladas?|ton\b)(?!\s*/)(?!\s*(?:de\s+)?co2)"},
    "tco2e": {"depois": r"t\s*(?:de\s+)?co2|toneladas?\s+(?:de\s+)?co2|mtco2|tco2"},
    "t/dia": {"depois": r"(?:t|toneladas?)\s*(?:/|por)\s*dia"},
    "t/ha": {"depois": r"(?:t|toneladas?)\s*(?:/|por)\s*(?:ha\b|hectare)"},
    "m": {"depois": r"m\b|metros?"},
    "r$/ha": {"antes": r"r\$"},
}
# entre o número e a unidade: negrito/parênteses, "de" e o valor por extenso das leis ("30 (trinta) metros")
_AFTER_GAP = r"^[\s*_)]*(?:\([^)\d]{1,40}\)\s*)?(?:de\s+)?[\s*_(]*"
_BEFORE_GAP = r"[\s*_(]*$"


def _unit_ok(unit: str, text: str, start: int, end: int, loose: bool) -> bool:
    """O número em text[start:end] está acompanhado da unidade? loose=True (resposta do agente) também aceita a
    unidade no cabeçalho de uma tabela markdown ou antes do número, na mesma linha."""
    spec = _UNITS.get(_norm(unit))
    if spec is None:
        return True
    if "antes" in spec:
        if re.search(rf"(?:{spec['antes']}){_BEFORE_GAP}", text[max(0, start - 8):start]):
            return True
        pattern = spec["antes"]
    else:
        if re.match(rf"{_AFTER_GAP}(?:{spec['depois']})", text[end:end + 40]):
            return True
        pattern = spec["depois"]
    if not loose:
        return False
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    if "|" in text[line_start:line_end]:
        block_start = line_start  # sobe até o início da tabela markdown e lê o cabeçalho
        while block_start > 0:
            prev = text.rfind("\n", 0, block_start - 1) + 1
            if "|" not in text[prev:block_start]:
                break
            block_start = prev
        header_end = text.find("\n", block_start)
        return bool(re.search(pattern, text[block_start:len(text) if header_end == -1 else header_end]))
    return bool(re.search(pattern, text[max(line_start, start - 60):start]))


def find_value_with_unit(valor: float, tol_rel: float, text: str, unit: str, loose: bool = False) -> dict | None:
    """Como find_value, mas o número só conta se vier com a unidade esperada (ex.: '277,6 mil ha', 'R$ 5.000,00').
    Devolve {trecho, lido, erro_rel} do mais próximo ou None."""
    plain = strip_accents(text or "").lower()
    limit = max(abs(valor) * tol_rel, 1e-9)
    best = None
    for m in NUMBER_RE.finditer(plain):
        for c in number_candidates(m.group(1), m.group(2)):
            diff = abs(c - valor)
            if diff <= limit and (best is None or diff < best[2]) and _unit_ok(unit, plain, m.start(), m.end(), loose):
                best = (m.group(0), c, diff)
    if best is None:
        return None
    return {"trecho": best[0].strip(), "lido": best[1], "erro_rel": best[2] / abs(valor) if valor else 0.0}

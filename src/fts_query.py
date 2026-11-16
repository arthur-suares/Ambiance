"""Consulta lexical relaxada para o canal de palavras-chave da busca híbrida.

O `websearch_to_tsquery` do Postgres liga todas as palavras com AND: numa pergunta inteira nenhum chunk
contém todas elas, e o canal lexical devolve zero candidatos. Aqui a pergunta vira uma consulta com OR,
mantendo só termos informativos. É determinístico: sem LLM, sem IDF.

O texto devolvido usa a sintaxe do `websearch_to_tsquery` (a mesma função do SQL):
`termo or termo or "expressão com várias palavras"`. Os termos só têm letras, dígitos, hífen interno, `.`, `/`,
`%` e aspas que o próprio construtor coloca, então o texto do usuário não consegue injetar operadores. Mesmo
assim ele segue como parâmetro do driver, nunca concatenado no SQL, e o `websearch_to_tsquery` não dá erro
de sintaxe com nenhuma entrada.

Consulta sem termo válido devolve "" (o `@@` com consulta vazia não casa com nenhum chunk): o canal lexical fica
vazio e a busca vira só semântica, sem ranking lexical artificial.

Os acentos ficam como o usuário digitou: o índice não remove acentos (config `portuguese`), então "Amazonia" sem
acento não casa com "Amazônia" no texto. Limitação conhecida.
"""

from __future__ import annotations

import math
import re
import unicodedata

MAX_TERMS = 12  # limite de termos (âncoras e expressões primeiro, depois palavras na ordem da pergunta)
MIN_WORD_LEN = 2

# Palavras funcionais: interrogativos, artigos, preposições, conjunções e verbos auxiliares frequentes.
# Termos do domínio (multa, reserva, legal, autorização, desmatamento, licenciamento...) ficam de fora de propósito.
STOPWORDS = frozenset("""
    qual quais como quando onde quanto quanta quantos quantas que quem
    um uma uns umas o a os as
    de da do das dos em na no nas nos ao aos à às
    para por com e ou se
    é foi ser ter tem há
    deve devem pode podem
    or and
""".split())

# Expressões jurídicas e do domínio que valem mais juntas do que separadas.
PHRASES = tuple(tuple(p.split()) for p in (
    "reserva legal",
    "amazônia legal",
    "corte raso",
    "área de preservação permanente",
    "preservação permanente",
    "unidade de conservação",
    "unidades de conservação",
    "proteção integral",
    "mata atlântica",
    "cadastro ambiental rural",
    "licenciamento ambiental",
    "mudança do clima",
    "uso sustentável",
))

_TOKEN = re.compile(
    r"""
    (?P<art>\b[Aa]rt(?:igos?|s?\.)?\s*(?P<artn>\d+)(?:\s*[ºo°])?(?:-[A-Za-z])?)   # Art. 12, artigo 12, Art. 61-A
  | (?P<norma>\d{1,3}(?:\.\d{3})+/\d{4})                                           # 12.651/2012, 6.514/2008
  | (?P<pct>\d+(?:[.,]\d+)?\s?%)                                                   # 80%, 36,1%
  | (?P<num>\d+(?:[.,/]\d+)*)                                                      # número solto (descartado)
  | (?P<word>[^\W\d_]+(?:-[^\W\d_]+)*)                                             # palavra, com hífen interno
    """,
    re.VERBOSE,
)


def _fold(text: str) -> str:
    """Minúsculas e sem acentos, só para comparar (a consulta mantém o texto original)."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


_STOPWORDS_FOLDED = frozenset(_fold(w) for w in STOPWORDS)
_PHRASES_FOLDED = tuple((tuple(_fold(w) for w in p), p) for p in PHRASES)


def _find_phrases(words: list[str]) -> list[str]:
    """Expressões de PHRASES presentes em sequência na lista de palavras (como o usuário escreveu)."""
    folded = [_fold(w) for w in words]
    found = []
    for pattern, _ in _PHRASES_FOLDED:
        n = len(pattern)
        for i in range(len(folded) - n + 1):
            if tuple(folded[i:i + n]) == pattern:
                found.append(" ".join(words[i:i + n]))
                break
    return found


def extract_terms(query_text: str) -> list[str]:
    """Termos da consulta (sem limite), já sem stopwords, números soltos e duplicatas.

    Ordem: âncoras (artigo, número de norma, percentual), expressões jurídicas e palavras informativas na ordem
    em que aparecem. Cada termo já está na sintaxe do `websearch_to_tsquery` (expressões entre aspas).
    """
    text = unicodedata.normalize("NFC", query_text or "")
    anchors: list[str] = []
    words: list[str] = []
    for m in _TOKEN.finditer(text):
        if m.group("art"):
            anchors.append(f'"art {m.group("artn")}"')
        elif m.group("norma"):
            anchors.append(m.group("norma"))
        elif m.group("pct"):
            anchors.append(re.sub(r"\s", "", m.group("pct")))
        elif m.group("word"):
            words.append(m.group("word"))

    terms: list[tuple[str, str]] = [(a, a) for a in anchors]                 # (chave de dedup, termo emitido)
    terms += [(_fold(p), f'"{p}"') for p in _find_phrases(words)]
    for w in words:
        key = _fold(w)
        if key not in _STOPWORDS_FOLDED and len(key) >= MIN_WORD_LEN:
            terms.append((key, w))

    seen, out = set(), []
    for key, term in terms:
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def build_relaxed_fts_query(query_text: str, max_terms: int = MAX_TERMS) -> str:
    """Pergunta -> consulta lexical com OR ("" se não houver termo válido).

    Os primeiros `max_terms` termos de `extract_terms` (âncoras e expressões antes das palavras) ligados
    por OR. Números soltos (anos, quantidades) são descartados: só contam dentro de uma âncora.
    """
    return " or ".join(extract_terms(query_text)[:max_terms])


# ----------------------------------------------------------------------------- IDF

def bm25_idf(df: int, n_docs: int) -> float:
    """IDF do BM25: sempre positivo; vai de ~ln(n_docs) (termo raro) a ~0 (termo em quase todos os chunks)."""
    return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))


def weight_terms(terms: list[str], doc_freq: dict[str, int], n_docs: int,
                 max_terms: int = MAX_TERMS) -> list[tuple[str, float]]:
    """Termos com o IDF de cada um, do mais raro ao mais comum, no máximo `max_terms`.

    `doc_freq[termo]` é o número de chunks do índice que casam com o termo. Termo que não casa com nenhum
    chunk (df = 0) sai: não muda o resultado. Se houver mais termos que o limite, ficam os de maior IDF.
    Empates mantêm a ordem original (âncoras e expressões primeiro).
    """
    scored = [(t, bm25_idf(doc_freq[t], n_docs)) for t in terms if doc_freq.get(t, 0) > 0]
    scored.sort(key=lambda x: -x[1])  # sort estável
    return scored[:max_terms]


# ----------------------------------------------------------------------------- Decomposição de perguntas mistas

_CLAUSE_SPLIT_RE = re.compile(
    r"""
    [?;]+
  | \.\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])
  | \s*,?\s+\be\s+(?=(?:
        o\s+que
      | em\s+que
      | por\s+que
      | de\s+que
      | a\s+que
      | qual
      | quais
      | quanto
      | quanta
      | quantos
      | quantas
      | como
      | onde
      | quando
      | quem
      | que\s+(?:multa|pena|san[cç][aã]o|regra|percentual|limite|obriga[cç][aã]o|atividades?|casos?|área|area|biomas?|lei|decreto)
    )\b)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Ruído exclusivo das tabelas de fluxo/território da soja e carne bovina que polui embeddings e IDF jurídico
_SUPPLY_CHAIN_NOISE_PATTERNS = (
    r"\bcadeia\s+da\s+(?:soja|carne\s+bovina|pecu[aá]ria)\b",
    r"\b(?:na|da|de)\s+(?:soja|carne\s+bovina)\b",
    r"\bprocessamento\s+de\s+soja\b",
    r"\besmagamento\s+de\s+oleaginosas\b",
    r"\bcapacidade\s+de\s+(?:processamento|armazenagem)\b",
    r"\bgrupos?\s+exportador(?:es)?\b",
    r"\bexposi[cç][aã]o\s+ao\s+desmatamento\b",
    r"\bcompromisso\s+de\s+desmatamento\s+zero\b",
    r"\b(?:soja|carne\s+bovina|bovinos?|bovina|exportador(?:es|a|as)?|importador(?:es|a|as)?|fob|trase|toneladas?)\b",
)
_SUPPLY_CHAIN_NOISE_RE = re.compile("|".join(_SUPPLY_CHAIN_NOISE_PATTERNS), re.IGNORECASE)

_BIOMES = (
    ("mata atlantica", "Mata Atlântica"),
    ("amazonia legal", "Amazônia Legal"),
    ("amazonia", "Amazônia"),
    ("cerrado", "Cerrado"),
    ("caatinga", "Caatinga"),
    ("pampa", "Pampa"),
    ("pantanal", "Pantanal"),
)

_ANAPHORIC_BIOME_RE = re.compile(r"\b(?:ness[ea]s?|nest[ea]s?)\s+biomas?\b", re.IGNORECASE)


def _extract_mentioned_biomes(text: str) -> list[str]:
    folded = _fold(text)
    found: list[str] = []
    for key, label in _BIOMES:
        if key in folded and label not in found:
            found.append(label)
    return found


def clean_legal_query(query: str) -> str:
    """Remove termos exclusivos da cadeia produtiva (soja/carne/exportador) de uma sub-consulta jurídica."""
    cleaned = _SUPPLY_CHAIN_NOISE_RE.sub(" ", query or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:-")
    return cleaned if len(cleaned) >= 5 else (query or "").strip()


def split_mixed_question(question: str) -> dict:
    """Divide uma pergunta em cláusulas de dados (`data_clauses`) e de legislação (`legal_clauses`).

    Determinístico e sem LLM, servindo tanto para a etapa de pré-recuperação (`retrieve`) quanto como
    fallback imediato para o Agente Decompositor.
    """
    from src.soy.routing import route_question

    raw = (question or "").strip()
    if not raw:
        return {"is_mixed": False, "data_clauses": [], "legal_clauses": []}

    parts = [p.strip(" ,;.") for p in _CLAUSE_SPLIT_RE.split(raw) if p and p.strip(" ,;.")]
    if not parts:
        parts = [raw]

    data_clauses: list[str] = []
    legal_clauses: list[str] = []
    mixed_clauses: list[str] = []
    for part in parts:
        part_q = part if part.endswith("?") else part + "?"
        route = route_question(part_q)
        domain = route["domain"]
        if domain == "law":
            legal_clauses.append(part_q)
        elif domain in ("soy", "beef"):
            data_clauses.append(part_q)
        elif domain == "mixed":
            data_clauses.append(part_q)
            if route.get("retrieval") != "structured":
                mixed_clauses.append(part_q)
        else:
            # Cláusula neutra/ambígua: se a pergunta geral tem lei, pode ser a cláusula legal (ex.: "que atividades...")
            overall = route_question(raw)["domain"]
            if overall in ("law", "mixed"):
                legal_clauses.append(part_q)
            else:
                data_clauses.append(part_q)

    if not legal_clauses and mixed_clauses:
        legal_clauses.extend(clean_legal_query(c) for c in mixed_clauses)

    # Resolução de anáfora territorial (ex.: "nesse bioma" referindo-se à Mata Atlântica citada na cláusula de dados)
    data_biomes = _extract_mentioned_biomes(" ".join(data_clauses))
    resolved_legal: list[str] = []
    for clause in legal_clauses:
        if _ANAPHORIC_BIOME_RE.search(clause):
            if data_biomes:
                replacement = "no bioma " + " e ".join(data_biomes)
                clause = _ANAPHORIC_BIOME_RE.sub(replacement, clause)
            elif "reserva legal" in _fold(clause):
                clause = _ANAPHORIC_BIOME_RE.sub(
                    "na Amazônia Legal (floresta e cerrado) e nas demais regiões do país",
                    clause,
                )
        resolved_legal.append(clean_legal_query(clause))

    is_mixed = bool(data_clauses and resolved_legal)
    if not resolved_legal and route_question(raw)["domain"] in ("law", "mixed"):
        resolved_legal = [clean_legal_query(raw)]

    return {
        "is_mixed": is_mixed,
        "data_clauses": data_clauses,
        "legal_clauses": resolved_legal,
    }


def extract_legal_subqueries(question: str, extra_regions: list[str] | None = None) -> list[str]:
    """Gera de 1 a 3 sub-consultas jurídicas limpas e complementares para busca híbrida + fusão RRF.

    1. Separa a parte jurídica da parte de dados (evitando que termos como 'soja', 'bovina', 'exportador'
       poluam o embedding e5-small e o peso IDF).
    2. Resolve referências anafóricas a biomas/regiões (`nesse bioma`, `nesses biomas`), incluindo regiões
       descobertas dinamicamente em `extra_regions`.
    3. Acrescenta sub-consulta canônica complementar quando a pergunta envolve conceitos multi-artigo ou
       vocabulário estatutário específico dos 7 diplomas indexados.
    """
    split = split_mixed_question(question)
    base_queries = list(split["legal_clauses"]) if split["legal_clauses"] else [clean_legal_query(question)]

    if extra_regions:
        region_str = ", ".join(dict.fromkeys(r for r in extra_regions if r))
        if region_str:
            base_queries = [
                _ANAPHORIC_BIOME_RE.sub(f"nos biomas {region_str}", q) if _ANAPHORIC_BIOME_RE.search(q)
                else f"{q} ({region_str})"
                for q in base_queries
            ]

    combined_folded = _fold(" ".join(base_queries))
    expansions: list[str] = []

    # 1. Reserva Legal + percentuais por bioma / Amazônia Legal (Código Florestal art. 12 + art. 3º)
    if "reserva legal" in combined_folded and any(
        k in combined_folded for k in ("bioma", "amazonia", "floresta", "cerrado", "percentual", "exige", "manter")
    ) and "multa" not in combined_folded and "decreto" not in combined_folded:
        expansions.append(
            "Código Florestal Lei 12.651/2012 art. 12 percentual mínimo de Reserva Legal imóvel rural "
            "Amazônia Legal 80% área de floresta 35% cerrado 20% campos gerais e demais regiões do país"
        )
        expansions.append(
            "Código Florestal Lei 12.651/2012 art. 3º inciso I definição de Amazônia Legal estados e Reserva Legal"
        )

    # 2. APP / Faixa marginal de cursos d'água (Código Florestal art. 4º + art. 3º)
    if ("preservacao permanente" in combined_folded or re.search(r"\bapp\b", combined_folded)) and any(
        k in combined_folded for k in ("largura", "faixa", "rio", "rios", "curso", "margem", "margens", "metros")
    ):
        expansions.append(
            "Código Florestal Lei 12.651/2012 art. 4º art. 3º Área de Preservação Permanente APP "
            "faixas marginais de qualquer curso d'água natural largura mínima de 30 metros"
        )

    # 3. Multa por desmatar dentro / em área de reserva legal (Decreto 6.514/2008 art. 51)
    if "multa" in combined_folded and "reserva legal" in combined_folded and "fora da reserva legal" not in combined_folded:
        expansions.append(
            "Decreto 6.514/2008 art. 51 destruir desmatar danificar ou explorar floresta ou vegetação nativa "
            "em área de reserva legal ou servidão florestal sem autorização prévia multa de R$ 5.000,00 por hectare"
        )

    # 4. Multa por desmatar a corte raso fora da reserva legal (Decreto 6.514/2008 art. 52)
    if "multa" in combined_folded and ("fora da reserva legal" in combined_folded or "corte raso" in combined_folded):
        expansions.append(
            "Decreto 6.514/2008 art. 52 desmatar a corte raso florestas ou demais formações nativas "
            "fora da reserva legal sem autorização da autoridade competente multa de R$ 1.000,00 por hectare"
        )

    # 5. Meta de redução de emissões / Política Nacional sobre Mudança do Clima (Lei 12.187/2009 art. 12)
    if ("mudanca do clima" in combined_folded or "pnmc" in combined_folded or "emissoes" in combined_folded) and any(
        k in combined_folded for k in ("meta", "reducao", "reduzir", "compromisso", "2020")
    ):
        expansions.append(
            "Lei 12.187/2009 art. 12 Política Nacional sobre Mudança do Clima PNMC compromisso nacional voluntário "
            "ações de mitigação das emissões de gases de efeito estufa reduzir entre 36,1% e 38,9% emissões projetadas até 2020"
        )

    # 6. Licenciamento ambiental prévio de atividades poluidoras (Lei 6.938/1981 art. 10)
    if "licenciamento" in combined_folded and any(
        k in combined_folded for k in ("atividade", "atividades", "previo", "dependem", "estabelecimentos", "poluidor")
    ):
        expansions.append(
            "Lei 6.938/1981 art. 10 Política Nacional do Meio Ambiente construção instalação ampliação e funcionamento "
            "de estabelecimentos e atividades utilizadores de recursos ambientais efetiva ou potencialmente poluidores "
            "dependerão de prévio licenciamento ambiental"
        )

    # 7. Mata Atlântica: corte de vegetação primária (Lei 11.428/2006 art. 11 e art. 14)
    if "mata atlantica" in combined_folded and any(
        k in combined_folded for k in ("primaria", "corte", "cortar", "proib", "vedad", "supressao")
    ):
        expansions.append(
            "Lei 11.428/2006 art. 11 art. 14 Mata Atlântica é vedado o corte e a supressão de vegetação primária "
            "ou nos estágios avançado e médio de regeneração utilidade pública interesse social"
        )

    # 8. Pena por destruir/danificar floresta de preservação permanente (Lei 9.605/1998 art. 38 e art. 39)
    if "pena" in combined_folded and "preservacao permanente" in combined_folded:
        expansions.append(
            "Lei 9.605/1998 art. 38 art. 39 crimes contra a flora destruir ou danificar floresta considerada de "
            "preservação permanente cortar árvores em floresta considerada de preservação permanente sem permissão "
            "pena detenção de um a três anos ou multa"
        )

    # 9. Cadastro Ambiental Rural - CAR (Código Florestal Lei 12.651/2012 art. 29)
    if re.search(r"\bcar\b", combined_folded) or "cadastro ambiental rural" in combined_folded:
        expansions.append(
            "Código Florestal Lei 12.651/2012 art. 29 Cadastro Ambiental Rural CAR SINIMA registro público "
            "eletrônico de âmbito nacional obrigatório para todos os imóveis rurais"
        )

    # Desduplicação preservando a ordem (sub-consulta limpa do usuário primeiro, expansões depois)
    out: list[str] = []
    seen: set[str] = set()
    for q in base_queries + expansions:
        q_clean = q.strip()
        key = _fold(q_clean)
        if q_clean and key not in seen:
            seen.add(key)
            out.append(q_clean)
    return out

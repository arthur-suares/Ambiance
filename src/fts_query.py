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

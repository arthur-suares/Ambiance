"""ROUGE-L, BLEU e similaridade de cosseno entre a resposta do agente e as referências.

- Cosseno: embeddings do e5-small (o modelo do projeto) do texto limpo (sem tabelas, rótulos e markdown, mas
  com acentos e números originais); mede se os dois textos dizem a mesma coisa, mesmo com outras palavras.

Antes de comparar, o texto é normalizado (decisão do plano): sem rótulos [D1]/[L1], sem markdown
e tabelas, minúsculas, sem acentos e com números padronizados (valor completo arredondado a
3 algarismos significativos, então "36.100" e "36,1 mil" viram o mesmo token).

- ROUGE-L: implementação própria por LCS (o pacote rouge-score usa tokenizador/stemmer de inglês).
- BLEU: sacrebleu sobre os tokens já normalizados (tokenize="none"), N = 4, pesos iguais.
  Por pergunta: suavização "exp" (padrão do sacrebleu). Corpus: sem suavização.
"""

from __future__ import annotations

import math
import re

from sacrebleu.metrics import BLEU

from eval.metrics import NUMBER_RE, SCALES, br_value, strip_accents

_LABELS = re.compile(r"\[\s*[DL]\d+(?:\s*[-–,;]\s*[DL]?\d+)*\s*\]")
_LABEL_WITH_TEXT = re.compile(r"\[\s*[DL]\d+\s*,\s*([^\]]*[^\]\s])\s*\]")  # "[L1, Decreto 6.514/2008, art. 52]"
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_TOKEN = re.compile(r"r\$|\d+(?:\.\d+)?|[a-z]+|%")

_SENTENCE_BLEU = BLEU(tokenize="none", smooth_method="exp", effective_order=True)
_CORPUS_BLEU = BLEU(tokenize="none", smooth_method="none")


def canonical_number(x: float) -> str:
    """Arredonda a 3 algarismos significativos: 277582.68 -> '278000'; 36.1 -> '36.1'."""
    if x == 0:
        return "0"
    digits = 2 - int(math.floor(math.log10(abs(x))))
    r = round(x, digits)
    return str(int(r)) if r == int(r) else f"{r:g}"


def _number_token(m: re.Match) -> str:
    token, scale = m.group(1), m.group(2)
    if not scale and token.isdigit() and 1900 <= int(token) <= 2100:
        return f" {token} "  # anos ficam como estão
    v = br_value(token)
    if v is None:
        return f" {token} "
    return f" {canonical_number(v * SCALES.get((scale or '').lower(), 1.0))} "


def _strip_markup(text: str) -> str:
    """Tira tabelas markdown, rótulos [D1]/[L1], links, marcadores de lista/título e ênfase."""
    lines = [ln for ln in (text or "").splitlines() if not ln.strip().startswith("|")]  # tabelas markdown
    t = "\n".join(lines)
    t = _LABELS.sub(" ", t)
    t = _LABEL_WITH_TEXT.sub(r" \1 ", t)  # tira só o rótulo e mantém a lei e o artigo citados
    t = _LINK.sub(r"\1", t)
    t = re.sub(r"(?m)^\s*(?:#+|>|[-*+]|\d+[.)])\s+", " ", t)  # títulos, citações, listas
    return re.sub(r"[*_`]+", " ", t)


def normalize(text: str) -> list[str]:
    """Texto -> lista de tokens normalizados (ROUGE-L e BLEU)."""
    t = strip_accents(_strip_markup(text)).lower()
    t = NUMBER_RE.sub(_number_token, t)
    return _TOKEN.findall(t)


def clean_text(text: str) -> str:
    """Texto limpo para o cosseno: sem tabelas, rótulos e markdown, mas com acentos, maiúsculas e números originais."""
    return " ".join(_strip_markup(text).split())


# ----------------------------------------------------------------------------- cosseno

def _embed_pair_texts(texts: list[str]):
    """Vetores unitários do e5-small com o prefixo "query: " (tarefa simétrica de similaridade, como o e5 recomenda)."""
    from src.embeddings import get_model
    return get_model().encode(["query: " + t for t in texts], normalize_embeddings=True, batch_size=16)


def _n_tokens(text: str) -> int:
    from src.embeddings import get_model
    return len(get_model().tokenizer.encode("query: " + text, add_special_tokens=True))


def cosine(hyp_text: str, ref_text: str) -> dict:
    """Similaridade de cosseno entre os embeddings da resposta e da referência (já limpos de markup).

    O e5-small lê no máximo `limite_tokens` (512): o que passa disso é cortado sem aviso, então o resultado
    informa quando a resposta ou a referência foi truncada.
    """
    from src.embeddings import get_model
    hyp, ref = clean_text(hyp_text), clean_text(ref_text)
    a, b = _embed_pair_texts([hyp, ref])
    limit = get_model().max_seq_length
    n_hyp, n_ref = _n_tokens(hyp), _n_tokens(ref)
    return {"cosseno": float(a @ b), "tokens_resposta": n_hyp, "tokens_referencia": n_ref, "limite_tokens": limit,
            "truncada_resposta": n_hyp > limit, "truncada_referencia": n_ref > limit}


def cosine_baseline(hyp_texts: list[str], ref_texts: list[str]) -> dict | None:
    """Linha de base: cosseno médio de cada resposta com as referências das OUTRAS perguntas.

    O e5 dá notas altas mesmo para textos sem relação (a faixa útil é estreita). Comparar o cosseno da
    resposta com a referência da própria pergunta contra esta média mostra quanto da nota é só "mesmo assunto".
    """
    n = len(hyp_texts)
    if n < 2:
        return None
    hv = _embed_pair_texts([clean_text(t) for t in hyp_texts])
    rv = _embed_pair_texts([clean_text(t) for t in ref_texts])
    sims = hv @ rv.T
    own = [float(sims[i, i]) for i in range(n)]
    other = [float(sims[i, j]) for i in range(n) for j in range(n) if i != j]
    return {"proprio_media": sum(own) / n, "outras_media": sum(other) / len(other),
            "outras_max": max(other), "perguntas": n}


def lcs_length(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, start=1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def rouge_l(hyp: list[str], ref: list[str]) -> dict:
    """Precisão = LCS / palavras da resposta; recall = LCS / palavras da referência; F1."""
    lcs = lcs_length(hyp, ref)
    p = lcs / len(hyp) if hyp else 0.0
    r = lcs / len(ref) if ref else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precisao": p, "recall": r, "f1": f, "lcs": lcs, "palavras_resposta": len(hyp), "palavras_referencia": len(ref)}


def _bleu_dict(score) -> dict:
    return {
        "bleu": score.score / 100,
        "p1": score.precisions[0] / 100, "p2": score.precisions[1] / 100,
        "p3": score.precisions[2] / 100, "p4": score.precisions[3] / 100,
        "acertos": list(score.counts), "totais": list(score.totals),
        "bp": score.bp, "tamanho_resposta": score.sys_len, "tamanho_referencia": score.ref_len,
    }


def bleu_sentence(hyp: list[str], ref: list[str]) -> dict:
    """BLEU de uma resposta, com suavização exp (só para achar piores casos)."""
    if not hyp or not ref:
        return {"bleu": 0.0, "p1": 0.0, "p2": 0.0, "p3": 0.0, "p4": 0.0, "acertos": [0] * 4, "totais": [0] * 4,
                "bp": 0.0, "tamanho_resposta": len(hyp), "tamanho_referencia": len(ref)}
    return _bleu_dict(_SENTENCE_BLEU.sentence_score(" ".join(hyp), [" ".join(ref)]))


def bleu_corpus(hyps: list[list[str]], refs: list[list[str]]) -> dict | None:
    """BLEU de corpus: soma acertos, totais e tamanhos de todas as respostas antes da fórmula."""
    if not hyps:
        return None
    return _bleu_dict(_CORPUS_BLEU.corpus_score([" ".join(h) for h in hyps], [[" ".join(r) for r in refs]]))

import pytest

from eval.metrics import (
    average_precision,
    find_value,
    first_positions,
    gold_sets,
    law_key,
    parse_br_number,
    ranking_scores,
)
from eval.text_metrics import (
    bleu_corpus,
    bleu_sentence,
    canonical_number,
    clean_text,
    cosine,
    cosine_baseline,
    normalize,
    rouge_l,
)

CF = "Lei nº 12.651/2012 – Código Florestal"


def chunk(artigo, title=CF, parte=None):
    return {"title": title, "metadata": {"artigo": artigo, "parte": parte}}


ITEM_L01 = {"artigos": [
    {"lei": "Lei 12.651/2012 (Código Florestal)", "artigo": "12", "nivel": "essencial"},
    {"lei": "Lei 12.651/2012 (Código Florestal)", "artigo": "3", "nivel": "complementar"},
]}


def test_law_key():
    assert law_key(CF) == "12.651"
    assert law_key("Decreto nº 6.514/2008 – Infrações") == "6.514"


def test_ranking_example_from_plan():
    # 1º art. 13, 2º art. 12, 3º art. 68, 4º art. 59, 5º art. 3
    pos = first_positions([chunk("13"), chunk("12"), chunk("68"), chunk("59"), chunk("3")])
    ess, todos = gold_sets(ITEM_L01)
    s = ranking_scores(pos, ess, todos)
    assert s["hit@1"] == 0 and s["hit@3"] == 1
    assert s["mrr"] == 0.5 and s["primeiro_essencial"] == 2
    assert s["recall@3"] == 0.5 and s["recall@5"] == 1


def test_complementar_does_not_count_for_hit_or_mrr():
    pos = first_positions([chunk("3"), chunk("13")])
    ess, todos = gold_sets(ITEM_L01)
    s = ranking_scores(pos, ess, todos)
    assert s["hit@10"] == 0 and s["mrr"] == 0 and s["recall@1"] == 0.5


def test_article_in_parts_counts_once_at_first_position():
    pos = first_positions([chunk("13"), chunk("12", parte=1), chunk("12", parte=2)])
    assert pos[("12.651", "12")] == 2
    assert len(pos) == 2


def test_other_law_with_same_article_is_not_relevant():
    pos = first_positions([chunk("12", title="Lei nº 12.187/2009 – PNMC")])
    ess, todos = gold_sets(ITEM_L01)
    assert ranking_scores(pos, ess, todos)["hit@10"] == 0


def test_average_precision():
    assert average_precision([True, False, True, False]) == pytest.approx((1 + 2 / 3) / 2)
    assert average_precision([False, False]) == 0


def test_numbers():
    assert parse_br_number("260,2 mil ha") == pytest.approx(260200)
    assert parse_br_number("7,49 milhões") == pytest.approx(7.49e6)
    assert parse_br_number("R$ 1.000,00") == pytest.approx(1000)
    assert find_value(277582.68, 0.01, "JBS, com cerca de 277,6 mil ha") is not None
    assert find_value(277582.68, 0.01, "exporter_group,exposure\nJBS,277582.68", csv=True) is not None  # CSV das ferramentas
    assert find_value(277582.68, 0.01, "cerca de 290 mil ha") is None
    assert find_value(80, 0, "80% (oitenta por cento)") is not None


def test_normalize():
    toks = normalize("**São Félix** do Xingu [D1] tem 36.100 ha\n| a | b |\n|---|---|")
    assert toks == ["sao", "felix", "do", "xingu", "tem", "36100", "ha"]
    assert normalize("36,1 mil ha") == ["36100", "ha"]
    assert normalize("277.582,68") == normalize("277,6 mil") == ["278000"]
    assert normalize("em 2022") == ["em", "2022"]
    assert canonical_number(3.484) == "3.48"


def test_rouge_and_bleu_example_from_plan():
    ref = normalize("A multa é de R$ 1000 por hectare")
    hyp = normalize("A multa prevista é de R$ 1000 por hectare ou fração")
    assert len(ref) == 8 and len(hyp) == 11
    r = rouge_l(hyp, ref)
    assert r["lcs"] == 8
    assert r["precisao"] == pytest.approx(8 / 11) and r["recall"] == 1
    assert r["f1"] == pytest.approx(0.842, abs=1e-3)
    b = bleu_sentence(hyp, ref)
    assert [b["p1"], b["p2"], b["p3"], b["p4"]] == pytest.approx([8 / 11, 6 / 10, 4 / 9, 3 / 8])
    assert b["bp"] == 1 and b["bleu"] == pytest.approx(0.519, abs=1e-3)


def test_bleu_corpus_pools_counts():
    a_ref, a_hyp = normalize("a multa e de r$ 1000 por hectare"), normalize("a multa prevista e de r$ 1000 por hectare ou fracao")
    b_ref, b_hyp = normalize("um dois tres quatro cinco"), normalize("cinco quatro tres dois um")
    c = bleu_corpus([a_hyp, b_hyp], [a_ref, b_ref])
    assert c["acertos"][3] == 3 and c["totais"][3] == 8 + 2
    b = bleu_sentence(b_hyp, b_ref)
    assert b["acertos"][3] == 0 and b["p4"] > 0  # sem acerto de 4 palavras, a suavização evita o zero


def test_clean_text_keeps_words_but_drops_markup():
    txt = ("**Resposta curta:** a multa é de R$ 1.000,00 [L1, Decreto 6.514/2008, art. 52].\n"
           "| a | b |\n|---|---|\n- item [D1]")
    out = clean_text(txt)
    assert "[L1" not in out and "[D1]" not in out and "|" not in out and "*" not in out
    assert "R$ 1.000,00" in out and "multa" in out and "item" in out
    assert "Decreto 6.514/2008, art. 52" in out  # a lei e o artigo citados continuam; só o rótulo [L1, ...] sai
    assert "l1" not in normalize(txt)


def test_cosine_identical_text_is_one_and_unrelated_is_lower():
    ref = "A multa por desmatar a corte raso fora da reserva legal é de R$ 1.000,00 por hectare ou fração."
    same = cosine(ref + " [L1]", ref)
    assert same["cosseno"] == pytest.approx(1.0, abs=1e-4)
    assert not same["truncada_resposta"] and not same["truncada_referencia"]
    other = cosine("O Brasil exportou soja para a China em 2022.", ref)
    assert other["cosseno"] < same["cosseno"]


def test_cosine_flags_truncation():
    long = "desmatamento na cadeia da soja " * 400
    assert cosine(long, "multa por hectare")["truncada_resposta"] is True


def test_cosine_baseline_compares_own_reference_with_others():
    hyps = ["A multa é de R$ 1.000,00 por hectare.", "A China foi o maior destino da soja em 2022."]
    refs = ["Multa de R$ 1.000,00 por hectare ou fração.", "O principal destino da soja brasileira em 2022 foi a China."]
    b = cosine_baseline(hyps, refs)
    assert b["proprio_media"] > b["outras_media"]
    assert cosine_baseline(hyps[:1], refs[:1]) is None

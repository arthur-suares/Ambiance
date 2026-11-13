from src.fts_query import MAX_TERMS, build_relaxed_fts_query


def terms(query: str) -> list[str]:
    """Termos emitidos (a consulta é 'a or b or "c d"')."""
    q = build_relaxed_fts_query(query)
    return q.split(" or ") if q else []


def lower_terms(query: str) -> set[str]:
    return {t.lower() for t in terms(query)}


def test_removes_stopwords_but_keeps_domain_terms():
    t = lower_terms("Qual a multa para quem desmata sem autorização em uma área de reserva?")
    assert not t & {"qual", "a", "para", "em", "uma", "de", "quem"}
    assert {"multa", "desmata", "autorização", "área", "reserva"} <= t


def test_keeps_article_anchor():
    assert '"art 12"' in terms("O que diz o Art. 12 do Código Florestal?")
    assert '"art 52"' in terms("conforme o artigo 52 do decreto")
    assert '"art 61"' in terms("Art. 61-A")


def test_keeps_law_number():
    assert "12.651/2012" in terms("Segundo a Lei 12.651/2012, qual o percentual?")
    assert "6.514/2008" in terms("multa do Decreto 6.514/2008")


def test_keeps_percentage():
    assert "80%" in terms("reserva de 80% na floresta")
    assert "36,1%" in terms("meta de 36,1% de redução")


def test_keeps_reserva_legal_phrase_and_its_words():
    t = terms("Qual percentual de reserva legal um imóvel rural precisa manter?")
    assert '"reserva legal"' in t
    assert {"reserva", "legal", "percentual", "imóvel", "rural"} <= set(t)


def test_keeps_amazonia_legal_phrase():
    t = terms("imóvel na Amazônia Legal")
    assert '"Amazônia Legal"' in t


def test_joins_with_or_and_never_with_and():
    q = build_relaxed_fts_query("percentual reserva legal imóvel rural Amazônia Legal")
    assert " or " in q
    assert " and " not in q.lower() and "&" not in q


def test_removes_duplicates_ignoring_case_and_accents():
    t = terms("Reserva reserva RESERVA legal Legal; área Área")
    assert [x.lower() for x in t].count("reserva") == 1
    assert [x.lower() for x in t].count("legal") == 1
    assert len([x for x in t if x.lower() in {"área", "area"}]) == 1


def test_limits_number_of_terms():
    q = " ".join(f"palavra{chr(97 + i)}{chr(97 + j)}" for i in range(6) for j in range(6))
    assert len(terms(q)) == MAX_TERMS
    assert len(terms("alfa beta gama delta epsilon")) == 5
    assert len(build_relaxed_fts_query("alfa beta gama delta", max_terms=2).split(" or ")) == 2


def test_query_without_valid_terms_is_empty():
    assert build_relaxed_fts_query("") == ""
    assert build_relaxed_fts_query("   ") == ""
    assert build_relaxed_fts_query("qual é o que de em para?") == ""
    assert build_relaxed_fts_query("2022 ... 10 ?!") == ""      # só números soltos e pontuação
    assert build_relaxed_fts_query(None) == ""


def test_hyphenated_terms_and_accents_are_preserved():
    t = terms("zona de uso-restrito e preservação, conforme a Lei da Mata Atlântica")
    assert "uso-restrito" in t
    assert "preservação" in t
    assert '"Mata Atlântica"' in t


def test_user_text_cannot_inject_operators():
    q = build_relaxed_fts_query('multa & !desmatamento | (reserva) "aspas" -excluir <-> x:*')
    assert not set(q) & set("&!|()<>:*'")
    assert q.count('"') % 2 == 0
    assert all(" " not in t or t.startswith('"') for t in q.split(" or "))


# ----------------------------------------------------------------------------- IDF

def test_bm25_idf_is_positive_and_decreases_with_document_frequency():
    from src.fts_query import bm25_idf
    n = 100
    assert bm25_idf(1, n) > bm25_idf(10, n) > bm25_idf(50, n) > bm25_idf(100, n) > 0


def test_weight_terms_orders_rare_terms_first_and_drops_unmatched():
    from src.fts_query import bm25_idf, weight_terms
    df = {"reserva": 80, '"corte raso"': 3, "multa": 20, "inexistente": 0}
    out = weight_terms(list(df), df, n_docs=100)
    assert [t for t, _ in out] == ['"corte raso"', "multa", "reserva"]   # df = 0 sai
    assert out[0][1] == bm25_idf(3, 100)
    assert out[0][1] > out[1][1] > out[2][1]


def test_weight_terms_keeps_highest_idf_when_over_the_limit():
    from src.fts_query import weight_terms
    df = {f"t{i}": 5 + i for i in range(10)}   # t0 é o mais raro
    out = weight_terms(list(df), df, n_docs=100, max_terms=3)
    assert [t for t, _ in out] == ["t0", "t1", "t2"]


def test_weight_terms_ties_keep_original_order():
    from src.fts_query import weight_terms
    out = weight_terms(["b", "a", "c"], {"a": 4, "b": 4, "c": 4}, n_docs=50)
    assert [t for t, _ in out] == ["b", "a", "c"]


def test_weight_terms_empty_when_nothing_matches():
    from src.fts_query import weight_terms
    assert weight_terms(["x", "y"], {"x": 0, "y": 0}, n_docs=10) == []
    assert weight_terms([], {}, n_docs=10) == []


def test_extract_terms_has_no_limit_and_matches_relaxed_query_head():
    from src.fts_query import extract_terms
    q = " ".join(f"palavra{chr(97 + i)}{chr(97 + j)}" for i in range(6) for j in range(6))
    assert len(extract_terms(q)) == 36
    assert build_relaxed_fts_query(q).split(" or ") == extract_terms(q)[:MAX_TERMS]

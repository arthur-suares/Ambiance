"""Diagnóstico da recuperação nas leis: onde cai o artigo essencial em cada busca (sem LLM).

Uso: python -m eval.diagnostico_busca <pasta-da-rodada> <saida.json>

Para cada pergunta com artigo no gabarito, mede a busca direta com a pergunta inteira, a busca só com a metade de
lei da pergunta mista (texto em LAW_HALF) e as buscas que o agente fez na rodada (lidas do detalhes.jsonl).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from eval.metrics import chunk_key, first_positions, gold_sets  # noqa: E402
from eval.run_eval import load_tests  # noqa: E402
from src.embeddings import embed_query  # noqa: E402
from src.vector_store import get_connection, hybrid_search  # noqa: E402

RUN = Path(sys.argv[1]) / "detalhes.jsonl"
OUT = Path(sys.argv[2])

# metade de lei de cada pergunta mista (o texto da própria pergunta, sem a parte de dados)
LAW_HALF = {
    "M01": "O que o Código Florestal exige de reserva legal nesses biomas?",
    "M02": "Quanto de reserva legal um imóvel em área de floresta na Amazônia Legal deve manter?",
    "M03": "Que multa o Decreto 6.514/2008 prevê para desmatar dentro da reserva legal sem autorização?",
    "M04": "Em que casos a lei proíbe cortar vegetação primária na Mata Atlântica?",
    "M05": "Qual meta de redução de emissões a Política Nacional sobre Mudança do Clima estabeleceu?",
    "M06": "Quanto de reserva legal um imóvel em área de floresta na Amazônia Legal precisa manter?",
    "M07": "O que é o CAR?",
    "M08": "Qual a pena para quem destrói floresta de preservação permanente?",
    "M09": "Qual a multa por desmatar a corte raso fora da reserva legal?",
    "M10": "Que multa se aplica a quem desmata dentro da reserva legal?",
    "M11": "Que atividades dependem de licenciamento ambiental prévio?",
}

recs = {json.loads(l)["id"]: json.loads(l) for l in open(RUN, encoding="utf-8")}
items = [i for i in load_tests() if i["artigos"]]


def n_keyword_matches(query: str) -> int:
    with get_connection() as con:
        row = con.execute("SELECT count(*) AS n FROM chunks c, websearch_to_tsquery('portuguese', %s) q WHERE c.tsv @@ q",
                          [query]).fetchone()
        return list(row.values())[0] if isinstance(row, dict) else row[0]


def search(query: str, k: int = 10, candidates: int = 40):
    return hybrid_search(query, embed_query(query), limit=k, candidates=candidates)


def first_essential(chunks, ess):
    pos = first_positions(chunks)
    ps = [p for key, p in pos.items() if key in ess]
    return min(ps) if ps else None


def arts(chunks, n=5):
    seen, out = set(), []
    for c in chunks:
        a = (c["metadata"] or {}).get("artigo")
        key = (c["title"].split("–")[0].strip().replace("Lei nº ", "L").replace("Decreto nº ", "D"), a)
        if key not in seen:
            seen.add(key)
            out.append(f"{key[0]} art.{key[1]}")
        if len(out) >= n:
            break
    return out


rows = []
for it in items:
    ess, todos = gold_sets(it)
    q = it["pergunta"]
    row = {"id": it["id"], "tipo": it["tipo"], "essenciais": sorted(ess), "complementares": sorted(todos - ess)}
    # busca direta com a pergunta original (produção: 40 candidatos por lista)
    top = search(q, k=40)
    row["direta_kw_matches"] = n_keyword_matches(q)
    row["direta_primeiro_essencial"] = first_essential(top[:10], ess)
    row["direta_primeiro_essencial_top40"] = first_essential(top, ess)
    row["direta_top5"] = arts(top, 5)
    # onde estão os chunks essenciais, com TODOS os candidatos (672)
    full = search(q, k=700, candidates=700)
    ess_rows = []
    for pos, c in enumerate(full, start=1):
        if chunk_key(c) in ess:
            ess_rows.append({"pos_rrf_completo": pos, "rank_semantico": c["semantic_rank"], "rank_kw": c["keyword_rank"],
                             "parte": (c["metadata"] or {}).get("parte")})
    row["essencial_com_todos_candidatos"] = ess_rows[:4]
    # artigos complementares
    comp_pos = first_positions(top[:10])
    row["posicao_gabarito_top10"] = {f"{k[0]} art.{k[1]}": comp_pos.get(k) for k in sorted(todos)}
    # metade de lei
    if it["id"] in LAW_HALF:
        h = LAW_HALF[it["id"]]
        t2 = search(h, k=10)
        row["metade_lei_kw_matches"] = n_keyword_matches(h)
        row["metade_lei_primeiro_essencial"] = first_essential(t2, ess)
        row["metade_lei_top5"] = arts(t2, 5)
    # buscas do agente
    ag = []
    for call in recs[it["id"]]["agente"]["chamadas"]:
        if call["ferramenta"] == "search_laws":
            a = call["argumentos"]
            qq, kk = a.get("query", ""), int(a.get("k", 6))
            res = search(qq, k=kk)
            ag.append({"query": qq, "k": kk, "kw_matches": n_keyword_matches(qq),
                       "primeiro_essencial": first_essential(res, ess), "top": arts(res, 4)})
    row["agente"] = ag
    row["agente_achou_essencial"] = any(x["primeiro_essencial"] for x in ag)
    rows.append(row)

OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok", len(rows))

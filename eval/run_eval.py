"""Roda a avaliação do RAG nas 20 perguntas marcadas com no_teste (eval/PLANO_AVALIACAO.md).

Uso:
    python -m eval.run_eval                     # as 20 perguntas
    python -m eval.run_eval --ids L01,M01       # só algumas
    python -m eval.run_eval --limit 2           # as 2 primeiras
    python -m eval.run_eval --sem-juiz          # pula o LLM-as-a-judge (mais rápido/barato)

Cada pergunta passa por: (1) busca direta nas leis -> Hit/Recall/MRR; (2) agente completo ->
resposta + contexto; (3) checagem dos valores; (4) juiz -> Faithfulness, Context Precision,
Context Recall; (5) ROUGE-L e BLEU contra as duas referências. Tudo é gravado em
eval/resultados/<data-hora>/ (config.json, detalhes.jsonl, perguntas/<ID>.md, relatorio.md).
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import time
from datetime import datetime
from importlib import metadata
from pathlib import Path

from eval import judge
from eval.metrics import KS, chunk_key, find_value, first_positions, gold_sets, mean, ranking_scores
from eval.report import write_question_trail, write_report
from eval.text_metrics import bleu_sentence, clean_text, cosine, normalize, rouge_l
from src.config import EMBEDDING_MODEL, LLM_MODEL, PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / "eval"
RETRIEVAL_K = 10   # top-10 da busca direta (Hit/Recall@1,3,5,10 e MRR)
K_LAWS = 6         # trechos de lei por busca do agente (mesmo padrão do chat)


def load_tests(ids: list[str] | None = None, limit: int | None = None) -> list[dict]:
    items = [json.loads(line) for line in open(EVAL_DIR / "perguntas.jsonl", encoding="utf-8")]
    items = [i for i in items if i.get("no_teste")]
    if ids:
        wanted = {x.strip().upper() for x in ids}
        items = [i for i in items if i["id"] in wanted]
    return items[:limit] if limit else items


def relevance(key, essenciais: set, todos: set) -> str:
    return "essencial" if key in essenciais else "complementar" if key in todos else "não"


def chunk_row(pos: int, c: dict, essenciais: set, todos: set) -> dict:
    m = c.get("metadata") or {}
    return {
        "posicao": pos, "lei": c["title"], "artigo": m.get("artigo"), "parte": m.get("parte"),
        "partes": m.get("partes"), "score_rrf": float(c["score"]) if c.get("score") is not None else None,
        "rank_semantico": c.get("semantic_rank"), "rank_palavras_chave": c.get("keyword_rank"),
        "relevancia": relevance(chunk_key(c), essenciais, todos), "url": c.get("url"), "texto": c["content"],
    }


# ----------------------------------------------------------------------------- etapa 1

def retrieval_metrics(item: dict) -> dict | None:
    """Busca híbrida direta com a pergunta original (só perguntas com artigo no gabarito)."""
    if not item["artigos"]:
        return None
    from src.rag import retrieve
    essenciais, todos = gold_sets(item)
    start = time.perf_counter()
    chunks = retrieve(item["pergunta"], k=RETRIEVAL_K)
    rows = [chunk_row(i, c, essenciais, todos) for i, c in enumerate(chunks, start=1)]
    pos = first_positions(chunks)
    scores = ranking_scores(pos, essenciais, todos)
    found = {f"{lei}, art. {art}": pos.get((lei, art)) for lei, art in sorted(todos)}
    return {"segundos": round(time.perf_counter() - start, 2), "chunks": rows, "metricas": scores,
            "posicao_dos_artigos_do_gabarito": found}


# ----------------------------------------------------------------------------- etapa 2

_LAW_RANGE = re.compile(r"L(\d+)-L(\d+)")


def context_items(answer, essenciais: set, todos: set) -> list[dict]:
    """Contexto que o agente recebeu, na ordem: cada trecho de lei [Ln] e cada resultado de dados [Dn]."""
    from src.agent import tool_call_summary
    items, used = [], set()
    for call in answer.tool_calls:
        m = _LAW_RANGE.fullmatch(call.label or "")
        if call.name == "search_laws" and call.ok and m:
            for n in range(int(m.group(1)), int(m.group(2)) + 1):
                c = answer.law_sources[n - 1]
                meta = c.get("metadata") or {}
                parte = f" (parte {meta['parte']}/{meta['partes']})" if (meta.get("partes") or 1) > 1 else ""
                items.append({"id": f"L{n}", "tipo": "lei", "descricao": f"{c['title']}, art. {meta.get('artigo')}{parte}",
                              "texto": c["content"], "chamada": tool_call_summary(call),
                              "relevancia": relevance(chunk_key(c), essenciais, todos),
                              "score_rrf": float(c["score"]) if c.get("score") is not None else None})
                used.add(f"L{n}")
            continue
        cid = call.label if call.label and call.label not in used else call.name
        k = 2
        while cid in used:
            cid, k = f"{call.label or call.name}#{k}", k + 1
        used.add(cid)
        # o juiz precisa saber de qual cadeia é cada resultado (o SQL sozinho não diz isso a ele)
        cadeia = "soja" if call.name.startswith("soy_") or call.name == "run_soy_sql" else "carne bovina"
        items.append({"id": cid, "tipo": "dados" if call.label.startswith("D") else "outro",
                      "descricao": f"dados da cadeia da {cadeia} – {call.name}: {tool_call_summary(call)}"[:400],
                      "texto": call.output, "chamada": tool_call_summary(call), "ok": call.ok})
    return items


def agent_law_retrieval_metrics(answer, item: dict) -> list[dict]:
    """Calcula métricas por consulta real enviada a search_laws durante a execução do agente."""
    essenciais, todos = gold_sets(item) if item["artigos"] else (set(), set())
    searches = []
    for call in answer.tool_calls:
        if call.name != "search_laws":
            continue
        chunks = (
            answer.law_sources[call.law_source_start - 1:call.law_source_end]
            if call.law_source_start is not None and call.law_source_end is not None
            else []
        )
        positions = first_positions(chunks)
        searches.append({
            "subconsulta_id": call.subquery_id,
            "pergunta_enviada": call.input.get("query", ""),
            "fontes_recuperadas": [
                {"lei": chunk.get("title"), "artigo": (chunk.get("metadata") or {}).get("artigo")}
                for chunk in chunks
            ],
            "posicao_dos_artigos_do_gabarito": {
                f"{law}, art. {article}": positions.get((law, article))
                for law, article in sorted(todos)
            },
            "metricas": ranking_scores(positions, essenciais, todos),
        })
    return searches


def run_agent(item: dict) -> tuple[dict, list[dict]]:
    from src.agent import ask
    from src.rag import resolve_domain
    domain = resolve_domain(item["pergunta"], "auto")
    start = time.perf_counter()
    answer = ask(item["pergunta"], k_laws=K_LAWS, domain=domain)
    seconds = round(time.perf_counter() - start, 2)
    essenciais, todos = gold_sets(item) if item["artigos"] else (set(), set())
    calls = [{"rotulo": c.label, "ferramenta": c.name, "argumentos": c.input, "ok": c.ok, "linhas": c.rows,
              "segundos": c.seconds, "saida": c.output, "subconsulta_id": c.subquery_id,
              "dominio": c.domain, "pergunta_da_subconsulta": c.question,
              "faixa_fontes_juridicas": [c.law_source_start, c.law_source_end]
              if c.law_source_start is not None else None} for c in answer.tool_calls]
    agent = {"dominio": domain, "resposta": answer.text, "stop_reason": answer.stop_reason,
             "tokens_entrada": answer.input_tokens, "tokens_saida": answer.output_tokens,
             "segundos": seconds, "chamadas": calls,
             "tipo_pergunta": answer.question_type,
             "subconsultas": answer.subqueries,
             "buscas_juridicas": agent_law_retrieval_metrics(answer, item)}
    return agent, context_items(answer, essenciais, todos)


# ----------------------------------------------------------------------------- etapa 3

def check_values(item: dict, resposta: str, itens: list[dict]) -> dict:
    rows = []
    for v in item["valores"]:
        where = [it["id"] for it in itens if find_value(v["valor"], v["tolerancia_rel"], it["texto"], csv=True)]
        in_answer = find_value(v["valor"], v["tolerancia_rel"], resposta)
        rows.append({**v, "no_contexto": where, "na_resposta": in_answer})
    n = len(rows)
    return {
        "valores": rows,
        "valor_recuperado": sum(bool(r["no_contexto"]) for r in rows) / n if n else None,
        "acerto_valores": sum(r["na_resposta"] is not None for r in rows) / n if n else None,
    }


# ----------------------------------------------------------------------------- etapa 5

def text_scores(item: dict, resposta: str) -> dict:
    hyp = normalize(resposta)
    out = {"resposta_normalizada": " ".join(hyp), "resposta_limpa": clean_text(resposta)}
    for name, field in (("curta", "resposta_esperada"), ("longa", "resposta_referencia")):
        text = item.get(field) or ""
        ref = normalize(text)
        out[name] = {"referencia_normalizada": " ".join(ref), "referencia_limpa": clean_text(text),
                     "rouge_l": rouge_l(hyp, ref), "bleu": bleu_sentence(hyp, ref), "cosseno": cosine(resposta, text)}
    return out


# ----------------------------------------------------------------------------- orquestração

def flat_metrics(rec: dict) -> dict:
    m = {}
    if rec["retrieval"]:
        m.update(rec["retrieval"]["metricas"])
    for key in ("faithfulness", "context_precision", "context_recall"):
        m[key] = (rec["juiz"] or {}).get(key, {}).get("score")
    m["valor_recuperado"] = rec["checagem"]["valor_recuperado"] if rec["checagem"] else None
    m["acerto_valores"] = rec["checagem"]["acerto_valores"] if rec["checagem"] else None
    if rec["texto"]:
        for ref in ("curta", "longa"):
            r = rec["texto"][ref]
            m[f"rouge_l_p_{ref}"] = r["rouge_l"]["precisao"]
            m[f"rouge_l_r_{ref}"] = r["rouge_l"]["recall"]
            m[f"rouge_l_f1_{ref}"] = r["rouge_l"]["f1"]
            m[f"bleu_{ref}"] = r["bleu"]["bleu"]
            m[f"cosseno_{ref}"] = r["cosseno"]["cosseno"]
    if rec["agente"]:
        m["segundos"] = rec["agente"]["segundos"]
        m["tokens_entrada"] = rec["agente"]["tokens_entrada"]
        m["tokens_saida"] = rec["agente"]["tokens_saida"]
        m["tokens"] = m["tokens_entrada"] + m["tokens_saida"]
    return m


def evaluate(item: dict, use_judge: bool = True) -> dict:
    rec = {"id": item["id"], "tipo": item["tipo"], "pergunta": item["pergunta"], "gabarito": {
        k: item.get(k) for k in ("resposta_esperada", "resposta_referencia", "valores", "entidades", "artigos",
                                 "ferramentas", "sql_gabarito")},
        "retrieval": None, "agente": None, "contexto": [], "checagem": None, "juiz": None, "texto": None, "erros": []}
    try:
        rec["retrieval"] = retrieval_metrics(item)
    except Exception as e:
        rec["erros"].append(f"busca direta: {type(e).__name__}: {e}")
    try:
        rec["agente"], rec["contexto"] = run_agent(item)
    except Exception as e:
        rec["erros"].append(f"agente: {type(e).__name__}: {e}")
    if rec["agente"]:
        resposta = rec["agente"]["resposta"]
        rec["checagem"] = check_values(item, resposta, rec["contexto"])
        if use_judge:
            rec["juiz"] = judge.judge_all(item["pergunta"], resposta, item["resposta_esperada"], rec["contexto"])
            for key, res in rec["juiz"].items():
                if res.get("erro"):
                    rec["erros"].append(f"juiz ({key}): {res['erro']}")
        rec["texto"] = text_scores(item, resposta)
    rec["metricas"] = flat_metrics(rec)
    return rec


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def run_config(items: list[dict], use_judge: bool) -> dict:
    from src.agent import MAX_TURNS
    from src.vector_store import RRF_K
    return {
        "data": datetime.now().isoformat(timespec="seconds"),
        "perguntas": [i["id"] for i in items],
        "modelo_agente": LLM_MODEL,
        "modelo_juiz": LLM_MODEL if use_judge else None,
        "temperatura": "padrão da API (o Claude Haiku 5.5 não aceita temperatura 0)",
        "modelo_embeddings": EMBEDDING_MODEL,
        "busca": {"tipo": "híbrida (pgvector + full-text) com RRF", "rrf_k": RRF_K, "k_busca_direta": RETRIEVAL_K,
                  "ks_avaliados": list(KS), "k_leis_agente": K_LAWS, "max_turnos_agente": MAX_TURNS},
        "juiz": {"max_caracteres_por_item": judge.MAX_ITEM_CHARS, "prompts": judge.PROMPTS} if use_judge else None,
        "bleu": {"n": 4, "pesos": "iguais (1/4)", "por_pergunta": "sacrebleu, smooth_method=exp",
                 "corpus": "sacrebleu, sem suavização", "tokenizacao": "normalização própria (eval/text_metrics.py)"},
        "cosseno": {"modelo": EMBEDDING_MODEL, "prefixo": "query: ", "texto": "limpo (sem tabelas, rótulos e markdown)",
                    "limite_tokens": "512 (o que passar é cortado; cada pergunta registra se houve corte)"},
        "referencias": {"curta": "resposta_esperada (fatos-chave; usada no Context Recall)",
                        "longa": "resposta_referencia (estrutura do prompt do agente; ROUGE-L, BLEU e cosseno)"},
        "versoes": {"python": platform.python_version(), **{p: _version(p) for p in
                    ("anthropic", "sacrebleu", "duckdb", "psycopg", "sentence-transformers", "pgvector")}},
    }


def rescore_text(old_dir: Path, out: Path) -> None:
    """Refaz só as métricas de texto (ROUGE-L, BLEU, cosseno) de uma rodada já feita, com o gabarito atual.

    Reaproveita as respostas do agente, o contexto, a busca direta e as notas do juiz da rodada antiga: não chama
    o agente, o juiz nem o Postgres. Vale enquanto a `resposta_esperada` (usada pelo juiz no Context Recall)
    não mudar; o que muda é a `resposta_referencia`.
    """
    items = {i["id"]: i for i in load_tests()}
    old = [json.loads(line) for line in open(old_dir / "detalhes.jsonl", encoding="utf-8")]
    config = json.loads((old_dir / "config.json").read_text(encoding="utf-8"))
    new_cfg = run_config([items[r["id"]] for r in old], use_judge=bool(config.get("modelo_juiz")))
    for key in ("data", "modelo_agente", "modelo_juiz", "temperatura", "juiz"):  # o que veio da rodada antiga
        new_cfg[key] = config.get(key)
    new_cfg["reaproveitado_de"] = {"pasta": old_dir.name, "data_original": config["data"],
                                   "o_que_foi_refeito": "ROUGE-L, BLEU e cosseno, com as referências atuais do gabarito"}
    (out / "perguntas").mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(new_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    records = []
    with open(out / "detalhes.jsonl", "w", encoding="utf-8") as f:
        for rec in old:
            item = items[rec["id"]]
            rec["gabarito"].update({k: item.get(k) for k in ("resposta_esperada", "resposta_referencia")})
            if rec["agente"]:
                rec["texto"] = text_scores(item, rec["agente"]["resposta"])
            rec["metricas"] = flat_metrics(rec)
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            write_question_trail(rec, out / "perguntas" / f"{rec['id']}.md")
    write_report(records, new_cfg, out / "relatorio.md")
    print(f"Pronto: {out / 'relatorio.md'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Avaliação do RAG (20 perguntas do teste).")
    ap.add_argument("--ids", help="IDs separados por vírgula (ex.: L01,M01)")
    ap.add_argument("--limit", type=int, help="roda só as N primeiras perguntas")
    ap.add_argument("--sem-juiz", action="store_true", help="não chama o LLM-as-a-judge")
    ap.add_argument("--saida", help="pasta de saída (padrão: eval/resultados/<data-hora>)")
    ap.add_argument("--refazer-texto", metavar="PASTA",
                    help="reaproveita uma rodada pronta e refaz só ROUGE-L, BLEU e cosseno (não chama agente, juiz nem banco)")
    args = ap.parse_args()

    if args.refazer_texto:
        out = Path(args.saida) if args.saida else EVAL_DIR / "resultados" / datetime.now().strftime("%Y-%m-%d_%H%M")
        rescore_text(Path(args.refazer_texto), out)
        return

    from src.database import ensure_database
    ensure_database()

    items = load_tests(args.ids.split(",") if args.ids else None, args.limit)
    if not items:
        raise SystemExit("Nenhuma pergunta selecionada.")
    out = Path(args.saida) if args.saida else EVAL_DIR / "resultados" / datetime.now().strftime("%Y-%m-%d_%H%M")
    (out / "perguntas").mkdir(parents=True, exist_ok=True)
    use_judge = not args.sem_juiz
    config = run_config(items, use_judge)
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    records = []
    with open(out / "detalhes.jsonl", "w", encoding="utf-8") as f:
        for n, item in enumerate(items, start=1):
            print(f"[{n}/{len(items)}] {item['id']} ...", flush=True)
            rec = evaluate(item, use_judge)
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            f.flush()
            write_question_trail(rec, out / "perguntas" / f"{rec['id']}.md")
            m = rec["metricas"]
            print(f"    mrr={m.get('mrr')} faith={m.get('faithfulness')} cr={m.get('context_recall')} "
                  f"valores={m.get('acerto_valores')} rougeL={m.get('rouge_l_f1_longa')} "
                  f"{'ERROS: ' + '; '.join(rec['erros']) if rec['erros'] else ''}", flush=True)

    write_report(records, config, out / "relatorio.md")
    print(f"\nPronto: {out / 'relatorio.md'}")
    faith = mean(r["metricas"].get("faithfulness") for r in records)
    print(f"Faithfulness média: {faith:.2f}" if faith is not None else "")


if __name__ == "__main__":
    main()

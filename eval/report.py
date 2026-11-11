"""Escrita da trilha por pergunta (perguntas/<ID>.md) e do relatório (relatorio.md).

Médias sempre simples (por pergunta); a única exceção é o BLEU de corpus, que soma as
contagens de n-gramas das respostas do grupo antes de aplicar a fórmula.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.metrics import KS, mean
from eval.text_metrics import bleu_corpus

TYPES = [("lei", "Lei"), ("carne", "Carne bovina"), ("soja", "Soja"), ("mista", "Mista")]
TRECHO = 220        # caracteres de cada chunk mostrados na trilha
SAIDA_MAX = 2500    # caracteres de cada saída de ferramenta mostrados na trilha (íntegra no detalhes.jsonl)


def fmt(x, casas: int = 2) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "sim" if x else "não"
    if isinstance(x, (int, float)):
        return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(x)


def pct(x) -> str:
    return "—" if x is None else f"{fmt(100 * x, 0)}%"


def cell(text) -> str:
    return " ".join(str(text if text is not None else "—").split()).replace("|", "\\|")


def cut(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + f"\n[... {len(text) - n} caracteres a mais no detalhes.jsonl ...]"


def body_text(chunk_text: str) -> str:
    """Texto do chunk sem o cabeçalho (título da lei e caminho de capítulos/seções)."""
    lines = (chunk_text or "").splitlines()[1:]
    return " ".join(" ".join(ln for ln in lines if " > " not in ln).split())


def table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return out + [""]


# ----------------------------------------------------------------------------- trilha

def write_question_trail(rec: dict, path: Path) -> None:
    g, m = rec["gabarito"], rec["metricas"]
    L = [f"# {rec['id']} ({rec['tipo']})", "", f"**Pergunta:** {rec['pergunta']}", ""]
    if rec["erros"]:
        L += ["> **Erros nesta pergunta:** " + "; ".join(rec["erros"]), ""]

    # 1 ----------------------------------------------------------------------
    L += ["## 1. Pergunta e gabarito", "", f"**Resposta esperada (referência curta):** {g['resposta_esperada']}", "",
          f"**Referência longa:** {g.get('resposta_referencia') or '—'}", ""]
    if g["valores"]:
        L += ["**Valores esperados:**", ""] + table(
            ["Descrição", "Valor", "Unidade", "Tolerância"],
            [[v["descricao"], fmt(v["valor"]), v["unidade"], pct(v["tolerancia_rel"])] for v in g["valores"]])
    if g["entidades"]:
        L += ["**Entidades esperadas:** " + ", ".join(g["entidades"]), ""]
    if g["artigos"]:
        L += ["**Artigos do gabarito:**", ""] + table(["Lei", "Artigo", "Nível"],
                                                       [[a["lei"], a["artigo"], a.get("nivel")] for a in g["artigos"]])
    if g["ferramentas"]:
        L += ["**Ferramentas esperadas:** " + ", ".join(f"`{f}`" for f in g["ferramentas"]), ""]
    if g["sql_gabarito"]:
        L += ["**SQL que gerou o gabarito:**", "", "```sql", g["sql_gabarito"], "```", ""]

    # 2 ----------------------------------------------------------------------
    L += ["## 2. Retrieval direto (busca híbrida com a pergunta original, top-10)", ""]
    r = rec["retrieval"]
    if r is None:
        L += ["Sem artigo de lei no gabarito: a etapa não se aplica a esta pergunta.", ""]
    else:
        L += table(["Pos.", "Lei", "Art.", "Parte", "Score RRF", "Rank semântico", "Rank palavras-chave", "Relevância", "Trecho"],
                   [[c["posicao"], c["lei"], c["artigo"], f"{c['parte']}/{c['partes']}" if (c.get("partes") or 1) > 1 else "—",
                     fmt(c["score_rrf"], 4), c["rank_semantico"] or "—", c["rank_palavras_chave"] or "—",
                     c["relevancia"], cut(body_text(c["texto"]), TRECHO)] for c in r["chunks"]])
        sc = r["metricas"]
        L += ["Posição em que cada artigo do gabarito apareceu pela primeira vez: " + "; ".join(
            f"{k} → {v if v else 'não apareceu'}" for k, v in r["posicao_dos_artigos_do_gabarito"].items()), ""]
        L += table(["k", "Hit@k (essenciais)", "Recall@k (essenciais + complementares)"],
                   [[k, fmt(sc[f"hit@{k}"]), fmt(sc[f"recall@{k}"])] for k in KS])
        pe = sc["primeiro_essencial"]
        L += [f"**MRR:** " + (f"primeiro artigo essencial na posição {pe} → 1/{pe} = {fmt(sc['mrr'])}" if pe
                               else "nenhum artigo essencial no top-10 → 0"), ""]

    # 3 ----------------------------------------------------------------------
    L += ["## 3. Execução do agente", ""]
    a = rec["agente"]
    if a is None:
        L += ["O agente não rodou (ver erros acima).", ""]
    else:
        L += [f"Domínio roteado: `{a['dominio']}` · {len(a['chamadas'])} chamada(s) de ferramenta", ""]
        for n, c in enumerate(a["chamadas"], start=1):
            L += [f"### Chamada {n}: `{c['ferramenta']}` → {c['rotulo'] or '—'}", "",
                  f"ok: {fmt(c['ok'])} · linhas: {c['linhas'] if c['linhas'] is not None else '—'} · {fmt(c['segundos'])} s", "",
                  "Argumentos escolhidos pelo LLM:", "", "```json",
                  json.dumps(c["argumentos"], ensure_ascii=False, indent=2), "```", "",
                  "Resultado devolvido ao LLM:", "", "```text", cut(c["saida"], SAIDA_MAX), "```", ""]
        L += ["### Contexto recebido pelo LLM (itens avaliados pelo juiz)", ""]
        L += table(["Item", "Descrição", "Relevância (gabarito)"],
                   [[it["id"], it["descricao"], it.get("relevancia", "—")] for it in rec["contexto"]])

    # 4 ----------------------------------------------------------------------
    L += ["## 4. Resposta do LLM", ""]
    if a:
        L += [f"{fmt(a['segundos'])} s · {a['tokens_entrada']} tokens de entrada · {a['tokens_saida']} de saída · "
              f"stop_reason = `{a['stop_reason']}`", "", "---", "", a["resposta"], "", "---", ""]

    # 5 ----------------------------------------------------------------------
    L += ["## 5. Checagem dos valores (sem juiz)", ""]
    ch = rec["checagem"]
    if not ch or not ch["valores"]:
        L += ["Sem valores numéricos no gabarito.", ""]
    else:
        L += table(["Valor esperado", "Esperado", "No contexto (itens)", "Na resposta (trecho lido)", "Erro relativo"],
                   [[v["descricao"], f"{fmt(v['valor'])} {v['unidade']}", ", ".join(v["no_contexto"]) or "não",
                     v["na_resposta"]["trecho"] if v["na_resposta"] else "não encontrado",
                     pct(v["na_resposta"]["erro_rel"]) if v["na_resposta"] else "—"] for v in ch["valores"]])
        L += [f"**Valor recuperado:** {pct(ch['valor_recuperado'])} · **Acerto de valores:** {pct(ch['acerto_valores'])}", ""]

    # 6 ----------------------------------------------------------------------
    L += ["## 6. Juiz (LLM-as-a-judge)", ""]
    j = rec["juiz"]
    if not j:
        L += ["Juiz não executado nesta rodada.", ""]
    else:
        for key, title, field in (("faithfulness", "Faithfulness (afirmações da resposta sustentadas pelo contexto)", "sustentada"),
                                  ("context_recall", "Context Recall (afirmações da referência curta presentes no contexto)", "no_contexto")):
            res = j[key]
            L += [f"### {title}: {fmt(res.get('score'))}", ""]
            if res.get("erro"):
                L += [f"Erro do juiz: {res['erro']}", ""]
                continue
            L += [f"Conta: {res['conta']}", ""]
            L += table(["#", "Afirmação", "Veredito", "Evidência", "Justificativa"],
                       [[i, c.get("afirmacao"), "✓" if c[field] else "✗", c.get("evidencia") or "—", c.get("justificativa")]
                        for i, c in enumerate(res["afirmacoes"], start=1)])
        res = j["context_precision"]
        L += [f"### Context Precision (utilidade de cada item do contexto, na ordem): {fmt(res.get('score'))}", ""]
        if res.get("erro"):
            L += [f"Erro do juiz: {res['erro']}", ""]
        else:
            L += [f"Conta: {res['conta']}", ""]
            L += table(["Item", "Útil?", "Justificativa"],
                       [[it["id"], "✓" if it["util"] else "✗", it["justificativa"]] for it in res["itens"]])

    # 7 ----------------------------------------------------------------------
    L += ["## 7. ROUGE-L e BLEU", ""]
    t = rec["texto"]
    if not t:
        L += ["Sem resposta para comparar.", ""]
    else:
        rows = []
        for ref in ("curta", "longa"):
            rl, bl = t[ref]["rouge_l"], t[ref]["bleu"]
            rows.append([ref, rl["lcs"], rl["palavras_resposta"], rl["palavras_referencia"], fmt(rl["precisao"]),
                         fmt(rl["recall"]), fmt(rl["f1"]), " / ".join(fmt(bl[f"p{n}"]) for n in range(1, 5)),
                         " / ".join(f"{x}/{y}" for x, y in zip(bl["acertos"], bl["totais"])), fmt(bl["bp"]), fmt(bl["bleu"])])
        L += table(["Referência", "LCS", "Palavras resposta", "Palavras referência", "ROUGE-L P", "ROUGE-L R",
                    "ROUGE-L F1", "BLEU p1/p2/p3/p4", "Acertos/totais (n=1..4)", "BP", "BLEU (suavizado)"], rows)
        L += ["Textos normalizados usados na comparação:", "", "```text", "RESPOSTA: " + cut(t["resposta_normalizada"], 3000),
              "", "REFERÊNCIA CURTA: " + t["curta"]["referencia_normalizada"], "",
              "REFERÊNCIA LONGA: " + t["longa"]["referencia_normalizada"], "```", ""]

    L += ["## Resumo das métricas desta pergunta", ""]
    L += table(["Métrica", "Valor"], [[k, fmt(v) if isinstance(v, float) else v] for k, v in m.items()])
    path.write_text("\n".join(L), encoding="utf-8")


# ----------------------------------------------------------------------------- relatório

def _avg(records, key):
    vals = [r["metricas"].get(key) for r in records if r["metricas"].get(key) is not None]
    return (sum(vals) / len(vals) if vals else None), len(vals)


def _corpus(records, ref):
    hyps, refs = [], []
    for r in records:
        if r["texto"]:
            hyps.append(r["texto"]["resposta_normalizada"].split())
            refs.append(r["texto"][ref]["referencia_normalizada"].split())
    res = bleu_corpus(hyps, refs)
    return (res["bleu"] if res else None), len(hyps)


def write_report(records: list[dict], config: dict, path: Path) -> None:
    by_type = {t: [r for r in records if r["tipo"] == t] for t, _ in TYPES}
    L = [f"# Avaliação do RAG ({config['data'][:10]})", "",
         f"{len(records)} perguntas · agente: `{config['modelo_agente']}` · juiz: `{config['modelo_juiz'] or 'não executado'}` · "
         f"temperatura: {config['temperatura']} · embeddings: `{config['modelo_embeddings']}`", "",
         "Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de "
         "todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.", ""]

    def row(label, key, desc, kind="avg", casas=2):
        v, n = _avg(records, key) if kind == "avg" else _corpus(records, key)
        return [label, fmt(v, casas), n, desc]

    L += ["## Painel", "", "### Recuperação: o sistema buscou o que precisava?", ""]
    L += table(["Métrica", "Valor", "n", "O que mede"], [
        row("Hit@5", "hit@5", "o artigo essencial está entre os 5 primeiros da busca direta?"),
        row("MRR", "mrr", "1/posição do primeiro artigo essencial (busca direta)"),
        row("Recall@5", "recall@5", "fração dos artigos do gabarito (essenciais + complementares) no top-5"),
        row("Context Recall", "context_recall", "fração das afirmações da referência presentes no contexto do agente (juiz)"),
        row("Context Precision", "context_precision", "itens úteis do contexto e se vieram primeiro (juiz)"),
        row("Valor recuperado", "valor_recuperado", "fração dos números do gabarito presentes no contexto"),
    ])
    L += ["### Geração: a resposta está certa e apoiada no que foi buscado?", ""]
    L += table(["Métrica", "Valor", "n", "O que mede"], [
        row("Faithfulness", "faithfulness", "fração das afirmações da resposta sustentadas pelo contexto (juiz)"),
        row("Acerto de valores", "acerto_valores", "fração dos números do gabarito presentes na resposta"),
        row("ROUGE-L F1 (ref. curta)", "rouge_l_f1_curta", "sobreposição de palavras em ordem com a referência curta"),
        row("ROUGE-L F1 (ref. longa)", "rouge_l_f1_longa", "sobreposição de palavras em ordem com a referência longa"),
        row("BLEU de corpus (ref. curta)", "curta", "n-gramas (1 a 4) em comum, somados no grupo", kind="corpus"),
        row("BLEU de corpus (ref. longa)", "longa", "n-gramas (1 a 4) em comum, somados no grupo", kind="corpus"),
    ])
    L += ["### Custo: quanto custa responder?", ""]
    L += table(["Métrica", "Valor", "n", "O que mede"], [
        row("Latência média (s)", "segundos", "tempo do agente da pergunta à resposta final", casas=1),
        row("Tokens médios por pergunta", "tokens", "entrada + saída do agente (soma de todos os turnos)", casas=0),
        row("Tokens de entrada (média)", "tokens_entrada", "", casas=0),
        row("Tokens de saída (média)", "tokens_saida", "", casas=0),
    ])

    # por tipo
    cols = [("Hit@5", "hit@5"), ("MRR", "mrr"), ("Recall@5", "recall@5"), ("Context Recall", "context_recall"),
            ("Context Precision", "context_precision"), ("Faithfulness", "faithfulness"),
            ("Acerto de valores", "acerto_valores"), ("ROUGE-L F1 (longa)", "rouge_l_f1_longa")]
    rows = []
    for label, group in [(name, by_type[t]) for t, name in TYPES] + [("**Geral**", records)]:
        if not group:
            continue
        rows.append([label, len(group)] + [fmt(_avg(group, k)[0]) for _, k in cols]
                    + [fmt(_corpus(group, "longa")[0]), fmt(_avg(group, "segundos")[0], 1)])
    L += ["## Resultados por tipo de pergunta", ""]
    L += table(["Tipo", "n"] + [c for c, _ in cols] + ["BLEU corpus (longa)", "Latência (s)"], rows)

    # ranking por k
    groups = [("Geral", records), ("Lei", by_type["lei"]), ("Mista", by_type["mista"])]
    rk = [[f"Hit@{k}"] + [fmt(_avg(g, f"hit@{k}")[0]) for _, g in groups] for k in KS]
    rk += [[f"Recall@{k}"] + [fmt(_avg(g, f"recall@{k}")[0]) for _, g in groups] for k in KS]
    rk += [["MRR"] + [fmt(_avg(g, "mrr")[0]) for _, g in groups]]
    L += ["## Busca nas leis por k (busca direta com a pergunta original)", ""]
    L += table(["Métrica"] + [f"{n} (n={_avg(g, 'mrr')[1]})" for n, g in groups], rk)

    # ROUGE/BLEU em detalhe
    L += ["## ROUGE-L e BLEU em detalhe", ""]
    L += table(["Referência", "ROUGE-L P", "ROUGE-L R", "ROUGE-L F1", "BLEU de corpus", "BLEU médio por pergunta (suavizado)"],
               [[ref, fmt(_avg(records, f"rouge_l_p_{ref}")[0]), fmt(_avg(records, f"rouge_l_r_{ref}")[0]),
                 fmt(_avg(records, f"rouge_l_f1_{ref}")[0]), fmt(_corpus(records, ref)[0]),
                 fmt(_avg(records, f"bleu_{ref}")[0])] for ref in ("curta", "longa")])

    # por pergunta
    L += ["## Resultados por pergunta", "", "Clique no ID para ver a trilha completa (cada etapa da pergunta).", ""]
    L += table(["ID", "Tipo", "Hit@5", "MRR", "Recall@5", "Ctx Recall", "Ctx Precision", "Faithfulness", "Valores",
                "ROUGE-L F1 (longa)", "BLEU (longa)", "Tempo (s)", "Tokens", "Erros"],
               [[f"[{r['id']}](perguntas/{r['id']}.md)", r["tipo"]] +
                [fmt(r["metricas"].get(k)) for k in ("hit@5", "mrr", "recall@5", "context_recall", "context_precision",
                                                     "faithfulness", "acerto_valores", "rouge_l_f1_longa", "bleu_longa")] +
                [fmt(r["metricas"].get("segundos"), 1), fmt(r["metricas"].get("tokens"), 0), len(r["erros"]) or ""]
                for r in records])

    # piores casos
    def worst(key, label, n=5):
        vals = sorted((r["metricas"][key], r["id"]) for r in records if r["metricas"].get(key) is not None)
        return [f"- **{label}:** " + (", ".join(f"[{i}](perguntas/{i}.md) ({fmt(v)})" for v, i in vals[:n]) or "—")]

    L += ["## Piores casos", ""]
    misses = [r["id"] for r in records if r["metricas"].get("hit@10") == 0]
    L += [f"- **Artigo essencial fora do top-10 da busca direta:** " +
          (", ".join(f"[{i}](perguntas/{i}.md)" for i in misses) or "nenhum")]
    L += worst("faithfulness", "Menor Faithfulness") + worst("context_recall", "Menor Context Recall")
    L += worst("acerto_valores", "Menor acerto de valores") + worst("rouge_l_f1_longa", "Menor ROUGE-L F1 (ref. longa)")
    errs = [r for r in records if r["erros"]]
    if errs:
        L += ["", "**Erros durante a rodada:**", ""] + [f"- {r['id']}: {'; '.join(r['erros'])}" for r in errs]

    judge_in = sum((res.get("uso") or {}).get("input_tokens", 0) for r in records if r["juiz"] for res in r["juiz"].values())
    judge_out = sum((res.get("uso") or {}).get("output_tokens", 0) for r in records if r["juiz"] for res in r["juiz"].values())
    L += ["", "## Limitações", "",
          "- **Uma rodada só e sem controle de temperatura:** o Claude Haiku 5.5 não aceita temperatura 0, então o agente "
          "e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta "
          "(Hit/Recall/MRR) não usa LLM e é reprodutível.",
          "- **Viés de autoavaliação:** o juiz é o mesmo modelo do sistema.",
          "- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.",
          "- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.",
          "- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio "
          "texto de busca e escolhe o k (ver seção 3 de cada trilha).",
          "- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; "
          "por isso são complemento do juiz, não substituto.",
          f"- **Custo do juiz nesta rodada:** {judge_in} tokens de entrada e {judge_out} de saída (fora do bloco Custo, "
          "que mede só o sistema).", ""]
    path.write_text("\n".join(L), encoding="utf-8")

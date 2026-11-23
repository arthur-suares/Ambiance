"""LLM-as-a-judge: Faithfulness, Context Precision e Context Recall (definições do RAGAS).

O juiz só faz julgamentos sim/não, com justificativa; a nota é calculada por fórmula aqui.
Usa o mesmo cliente e o mesmo modelo do sistema (src/rag.py:get_client, LLM_MODEL).
O Claude Haiku 5.5 não aceita temperatura 0, então as notas podem variar um pouco entre rodadas.
"""

from __future__ import annotations

import json

from eval.metrics import average_precision
from src.config import LLM_MODEL
from src.rag import get_client

MAX_ITEM_CHARS = 6000  # cada item de contexto (tabela ou trecho de lei) é cortado aqui, se for maior

FAITHFULNESS_PROMPT = """\
Você avalia se a RESPOSTA de um sistema de RAG é fiel ao CONTEXTO que o sistema recuperou.

Passo 1: divida a RESPOSTA em afirmações factuais atômicas (números, nomes, percentuais, artigos de lei, \
conclusões). Ignore cortesias, frases sobre o próprio sistema e ressalvas genéricas sem conteúdo factual.
Passo 2: para cada afirmação, decida se ela pode ser inferida diretamente do CONTEXTO. Arredondamentos \
razoáveis de números do contexto e cálculos simples sobre eles (soma, diferença, percentual) contam como \
sustentados. Conhecimento externo ao contexto NÃO conta, mesmo que seja verdadeiro.

Responda apenas com JSON, sem texto fora dele:
{"afirmacoes": [{"afirmacao": "...", "sustentada": true, "evidencia": "id do item (ex.: D1, L3) ou null", \
"justificativa": "uma frase"}]}"""

CONTEXT_RECALL_PROMPT = """\
Você avalia se o CONTEXTO recuperado por um sistema de RAG contém as informações da RESPOSTA DE REFERÊNCIA.

Passo 1: divida a RESPOSTA DE REFERÊNCIA em afirmações factuais atômicas.
Passo 2: para cada afirmação, decida se ela pode ser atribuída ao CONTEXTO (a informação está lá, \
mesmo que com outras palavras, outro formato de número ou arredondamento razoável). Cálculos simples sobre \
números do contexto (soma, diferença, percentual de variação) contam como presentes, como na avaliação de \
fidelidade.

Responda apenas com JSON, sem texto fora dele:
{"afirmacoes": [{"afirmacao": "...", "no_contexto": true, "evidencia": "id do item (ex.: D1, L3) ou null", \
"justificativa": "uma frase"}]}"""

CONTEXT_PRECISION_PROMPT = """\
Você avalia a utilidade de cada item do CONTEXTO recuperado por um sistema de RAG.

Para cada item, na ordem, decida se ele foi útil para chegar à RESPOSTA DE REFERÊNCIA da PERGUNTA \
(contém pelo menos uma informação que aparece na resposta de referência ou que é necessária para obtê-la). \
Avalie todos os itens, um por um, usando exatamente os ids fornecidos.

Responda apenas com JSON, sem texto fora dele:
{"itens": [{"id": "D1", "util": true, "justificativa": "uma frase"}]}"""

PROMPTS = {
    "faithfulness": FAITHFULNESS_PROMPT,
    "context_recall": CONTEXT_RECALL_PROMPT,
    "context_precision": CONTEXT_PRECISION_PROMPT,
}


def format_context(items: list[dict]) -> str:
    parts = []
    for it in items:
        text = it["texto"]
        if len(text) > MAX_ITEM_CHARS:
            text = text[:MAX_ITEM_CHARS] + "\n[... item cortado para o juiz ...]"
        parts.append(f'<item id="{it["id"]}" descricao="{it["descricao"]}">\n{text}\n</item>')
    return "<contexto>\n" + "\n".join(parts) + "\n</contexto>" if parts else "<contexto>(vazio)</contexto>"


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("sem JSON na resposta do juiz")
    return json.loads(text[start:end + 1])


def _ask(system: str, user: str) -> tuple[dict, str, dict]:
    """Chama o juiz; tenta de novo uma vez se o JSON vier inválido. Devolve (json, texto bruto, uso)."""
    messages = [{"role": "user", "content": user}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    raw = ""
    for attempt in range(2):
        response = get_client().messages.create(model=LLM_MODEL, max_tokens=8000, system=system, messages=messages)
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        raw = "".join(b.text for b in response.content if b.type == "text").strip()
        try:
            return _parse_json(raw), raw, usage
        except (ValueError, json.JSONDecodeError):
            if attempt == 0:
                messages += [{"role": "assistant", "content": raw or "(vazio)"},
                             {"role": "user", "content": "Responda novamente apenas com o JSON válido pedido."}]
    raise ValueError(f"JSON inválido do juiz: {raw[:300]}")


def _bool(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in {"true", "sim", "yes"})


def faithfulness(pergunta: str, resposta: str, itens: list[dict]) -> dict:
    user = f"PERGUNTA:\n{pergunta}\n\n{format_context(itens)}\n\nRESPOSTA:\n{resposta}"
    data, raw, usage = _ask(FAITHFULNESS_PROMPT, user)
    claims = [{**c, "sustentada": _bool(c.get("sustentada"))} for c in data.get("afirmacoes", [])]
    ok = sum(c["sustentada"] for c in claims)
    score = ok / len(claims) if claims else None
    return {"score": score, "afirmacoes": claims, "conta": f"{ok} de {len(claims)} afirmações sustentadas",
            "bruto": raw, "uso": usage}


def context_recall(pergunta: str, referencia: str, itens: list[dict]) -> dict:
    user = f"PERGUNTA:\n{pergunta}\n\n{format_context(itens)}\n\nRESPOSTA DE REFERÊNCIA:\n{referencia}"
    data, raw, usage = _ask(CONTEXT_RECALL_PROMPT, user)
    claims = [{**c, "no_contexto": _bool(c.get("no_contexto"))} for c in data.get("afirmacoes", [])]
    ok = sum(c["no_contexto"] for c in claims)
    score = ok / len(claims) if claims else None
    return {"score": score, "afirmacoes": claims, "conta": f"{ok} de {len(claims)} afirmações da referência no contexto",
            "bruto": raw, "uso": usage}


def context_precision(pergunta: str, referencia: str, itens: list[dict]) -> dict:
    if not itens:
        return {"score": 0.0, "itens": [], "conta": "nenhum item de contexto", "bruto": "", "uso": {}}
    user = f"PERGUNTA:\n{pergunta}\n\nRESPOSTA DE REFERÊNCIA:\n{referencia}\n\n{format_context(itens)}"
    data, raw, usage = _ask(CONTEXT_PRECISION_PROMPT, user)
    verdicts = {str(v.get("id")): v for v in data.get("itens", [])}
    out = []
    for it in itens:  # mantém a ordem real do contexto; item sem veredito conta como não útil
        v = verdicts.get(it["id"], {})
        out.append({"id": it["id"], "util": _bool(v.get("util")),
                    "justificativa": v.get("justificativa", "(sem veredito do juiz)")})
    flags = [o["util"] for o in out]
    score = average_precision(flags)
    marks = ", ".join(f"{o['id']}={'útil' if o['util'] else 'inútil'}" for o in out)
    hits, terms = 0, []
    for i, f in enumerate(flags, start=1):
        if f:
            hits += 1
            terms.append(f"{hits}/{i}")
    conta = f"[{marks}] -> ({' + '.join(terms)}) / {hits} = {score:.2f}" if hits else f"[{marks}] -> nenhum útil = 0"
    return {"score": score, "itens": out, "conta": conta, "bruto": raw, "uso": usage}


def _safe(fn, *args) -> dict:
    try:
        return fn(*args)
    except Exception as e:  # erro do juiz não derruba a rodada: a nota fica vazia e o erro vai para a trilha
        return {"score": None, "erro": f"{type(e).__name__}: {e}", "uso": {}}


def judge_all(pergunta: str, resposta: str, referencia: str, itens: list[dict]) -> dict:
    return {
        "faithfulness": _safe(faithfulness, pergunta, resposta, itens),
        "context_precision": _safe(context_precision, pergunta, referencia, itens),
        "context_recall": _safe(context_recall, pergunta, referencia, itens),
    }

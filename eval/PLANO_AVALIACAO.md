# Plano: avaliação do RAG com 20 testes

## Contexto
O sistema de RAG (soja, carne bovina e leis ambientais) precisa de uma avaliação quantitativa para a entrega. Já existe um conjunto de 30 perguntas com gabarito (`eval/perguntas.jsonl`, gerado por `eval/build_gold.py`). O objetivo é rodar **20 testes** — 5 de lei, 5 de carne bovina, 5 de soja e 5 mistas — e medir **Hit Rate@k, Recall@k, MRR, Faithfulness, Context Precision e Context Recall**, gerando um relatório com resultados por tipo de pergunta.

## Decisões (alinhadas com o usuário)
- **Hit Rate@k, Recall@k, MRR: só nas leis** (perguntas de lei + parte de lei das mistas → 10 perguntas). Em soja/carne bovina a recuperação é SQL, sem lista ranqueada; lá a recuperação é medida por Context Precision/Recall e por um indicador auxiliar "valor recuperado" (o número do gabarito apareceu no resultado de alguma ferramenta?).
- **Onde medir as métricas de ranking:** chamando a busca híbrida direto (`src/rag.py:retrieve`) com a **pergunta original** e k = 1, 3, 5, 10. Determinístico e reprodutível.
- **Faithfulness, Context Precision, Context Recall:** no fluxo completo do agente (`src/agent.py:ask`), nas 20 perguntas.
- **Juiz:** implementação própria seguindo as definições do RAGAS, usando o cliente já existente (`src/rag.py:get_client`) e **o mesmo modelo do sistema (claude-haiku-5.5)**. O viés de autoavaliação entra como limitação no relatório.
- **Fora do escopo (F01–F03) ficam de fora** dos 20 (não têm contexto de referência para Context Recall).

## Seleção das 20 perguntas (de `eval/perguntas.jsonl`)
- **Lei (5):** L01 reserva legal, L02 APP de rio, L04 multa corte raso, L06 pena APP (Lei 9.605), L07 categorias SNUC → cobre 4 normas.
- **Soja (5):** S01 município, S02 grupos exportadores, S03 destino, S05 maior produtor (territorial), S07 armazenagem (instalações).
- **Carne bovina (5):** C01 grupo exportador, C02 destino, C03 município, C04 tendência 2015→2023, C07 pastagem (territorial).
- **Mistas (5):** M01–M05 (todas).
Campo novo `no_teste: true` nessas 20 em `build_gold.py` (o JSONL continua com as 30).

## Definição das métricas
**Unidade de relevância nas leis = artigo** (lei + nº do artigo; qualquer parte/chunk dele conta). Um artigo recuperado em várias partes conta uma vez, na posição da primeira parte.
- **Hit Rate@k:** 1 se pelo menos um artigo do gabarito está entre os k primeiros; média nas perguntas.
- **Recall@k:** artigos do gabarito encontrados no top-k ÷ artigos do gabarito. Com 1 artigo por pergunta coincide com Hit Rate — o relatório deixa isso explícito (só diverge se o gabarito tiver mais de um artigo). Para ganhar sentido, revisar o gabarito de lei com artigos relacionados legítimos (ex.: L02 art. 4; L04 art. 52; M01 arts. 12 e 3 — Amazônia Legal) onde fizer sentido.
- **MRR:** 1/posição do primeiro artigo relevante (0 se não aparecer no top-10); média.
- **Faithfulness (juiz):** juiz quebra a resposta em afirmações; fração sustentada pelo contexto recuperado (resultados das ferramentas: tabelas `[D]` + trechos `[L]`).
- **Context Precision (juiz):** juiz marca cada item de contexto (cada chamada de ferramenta / cada chunk de lei, na ordem) como útil ou não para chegar ao gabarito; média da precisão@i nas posições úteis (fórmula do RAGAS).
- **Context Recall (juiz):** juiz quebra o `resposta_esperada` do gabarito em afirmações; fração que pode ser atribuída ao contexto recuperado.
- **Auxiliares (sem juiz, baratos):** acerto de valores (números do gabarito na resposta, tolerância do JSONL, normalizando formato BR), "valor recuperado" (número no contexto), latência e tokens.

## Implementação
Novo arquivo **`eval/run_eval.py`** (`python -m eval.run_eval`), com:
1. `load_tests()` — lê `eval/perguntas.jsonl`, filtra `no_teste`.
2. `retrieval_metrics(item)` — para itens com `artigos`: `src.rag.retrieve(pergunta, k=10)`, mapeia cada chunk para (lei, artigo) via `title`/`metadata["artigo"]` (casar lei pelo número, ex. "12.651"), deduplica e calcula Hit/Recall@{1,3,5,10} e MRR.
3. `run_agent(item)` — `src.agent.ask(pergunta)`; guarda resposta, `tool_calls` (label, nome, `output`), `law_sources`, tokens e tempo. Contexto para o juiz = lista ordenada dos `output` das chamadas (como o agente recebeu).
4. `judge.py` (em `eval/`) — três funções (`faithfulness`, `context_precision`, `context_recall`) com prompts em português que pedem JSON (afirmações + veredito + justificativa); usa `get_client()` e `LLM_MODEL`; `temperature=0`; trunca contextos longos para caber.
5. Agregação por tipo (lei/soja/carne/mista) e geral; grava `eval/resultados/<data>/detalhes.jsonl` (tudo por pergunta, incluindo justificativas do juiz) e `eval/resultados/<data>/relatorio.md` (tabelas por tipo + piores casos + limitações).

Reutilizar: `src/rag.py` (`retrieve`, `get_client`), `src/agent.py` (`ask`, `ToolCall`, `tool_call_summary`), `src/database.py:ensure_database`, constantes de `src/config.py`.

## Verificação
1. `python -m eval.build_gold` → 30 perguntas, 20 com `no_teste`.
2. Teste unitário em `tests/test_eval_metrics.py` das funções puras (Hit/Recall/MRR com listas sintéticas; normalização de números "260,2 mil ha" → 260200).
3. Rodar `python -m eval.run_eval --limit 2` (1 lei + 1 mista) para conferir o formato e as justificativas do juiz; depois as 20.
4. Revisar manualmente ~5 notas do juiz contra a resposta para validar o juiz (registrar a concordância no relatório).
5. `pytest -q tests` continua passando.

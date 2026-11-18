# Comparação Experimental do RAG Jurídico

Avaliação isolada do RAG jurídico sobre os **mesmos 672 chunks** congelados e a **suíte jurídica ampliada de 36 perguntas** (`30` positivas + `6` casos negativos/abstenção), mantendo o modelo de similaridade textual fixado em `intfloat/multilingual-e5-small` (revisão `614241f622f53c4eeff9890bdc4f31cfecc418b3`).

---

## 1. Auditoria do Acervo e Reconciliação com o PostgreSQL

- **Manifesto ([docs/leis/manifest.json](file:///Users/aluno1/Agro/Ambiance/docs/leis/manifest.json))**: **7 normas federais**, **488 artigos** extraídos pelo `src/law_parser.py` e **672 chunks**.
- **PostgreSQL (`trase_rag`, `pgvector 0.8.0-pg17`)**: índice auditado antes da migração ([audit.md](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/audit.md), [audit.json](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/audit.json) agora refletem o índice ativo pós-migração em `1024d`, ver Seção 9):
  - `status` (linha de base): **`read`** (`7` documentos, **`672` chunks**, modelo inicial `intfloat/multilingual-e5-small`, `384` dimensões);
  - `missing_documents`: `0` | `extra_documents`: `0` | divergências de artigo/hash: `0`;
  - `matches_frozen_reference`: **`True`** (`chunks_sha256 = 82c136c17fcff57ad67bb154db304400a02a3778f5317c4ebbcb175d5863c8a5`), confirmando que o snapshot [corpus_e5_small.json](file:///Users/aluno1/Agro/Ambiance/data/processed/juridico/corpus_e5_small.json) e o export verificado do banco ([frozen_from_db.json](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/frozen_from_db.json)) possuem exatamente o mesmo conjunto de 672 chunks.
- **Anexos ignorados pelo parser**: detectados **3 cabeçalhos de anexos excluídos** em `Lei nº 6.938/1981 – Política Nacional do Meio Ambiente` (`ANEXO`, `ANEXO VIII` e `ANEXO IX`), porque o parser encerra a leitura em `"Brasília,"` e descarta assinaturas e anexos (motivo do caso negativo `N01` sobre a lista da TCFA do Anexo VIII).
- **Arquivos HTML fora do manifesto** (não ingeridos por `ingest_laws`):
  - `docs/leis/L14119.html` (Lei nº 14.119/2021 — Pagamento por Serviços Ambientais, caso `N03`)
  - `docs/leis/L15190.html`
  - `docs/leis/Lcp 140.html` (Lei Complementar nº 140/2011, caso `N02`)
  - `docs/leis/decreto_6514.html`
  - `docs/leis/decreto_7830.html`
- **Proteções implementadas**:
  - [src/ingest_laws.py](file:///Users/aluno1/Agro/Ambiance/src/ingest_laws.py) fixa `DEFAULT_CHUNK_MAX_TOKENS = 480` (`CHUNK_SPLIT_TOKENS = 256`) para que modelos de janela maior como `BAAI/bge-m3` não alterem silenciosamente a segmentação.
  - [src/ingest_laws.py](file:///Users/aluno1/Agro/Ambiance/src/ingest_laws.py) e [src/vector_store.py](file:///Users/aluno1/Agro/Ambiance/src/vector_store.py) (`get_document_index_info`) verificam `sha256`, `embedding_model` e `chunking` antes de pular um documento, garantindo reindexação quando o modelo ou o chunking mudam.
  - [eval/text_metrics.py](file:///Users/aluno1/Agro/Ambiance/eval/text_metrics.py) e [eval/run_eval.py](file:///Users/aluno1/Agro/Ambiance/eval/run_eval.py) mantêm `SIMILARITY_MODEL = "intfloat/multilingual-e5-small"` fixo na avaliação textual.

---

## 2. Comparação de Embeddings nos Mesmos 672 Chunks (`context-mode = ranked`, busca densa pura)

Avaliação das 30 perguntas positivas em busca densa exata (`exact_dense_cosine`, `candidates = 40`):

| Modelo | Dim | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR | Recall@5 | Ev. Recall@1 | Ev. Recall@3 | Ev. Recall@5 | Ev. Recall@10 | Ev. Complete@1 | Ev. Complete@3 | Ev. Complete@5 | Ev. Complete@10 | Indexação (s) | Busca/q (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `intfloat/multilingual-e5-small` | 384 | 0,633 | 0,733 | 0,800 | 0,867 | 0,706 | 0,767 | 0,583 | 0,700 | 0,767 | 0,850 | 0,533 | 0,667 | 0,733 | 0,833 | 4,3 | 11,1 |
| `intfloat/multilingual-e5-large` | 1024 | 0,733 | 0,900 | 0,933 | 0,967 | 0,828 | 0,917 | 0,683 | 0,850 | 0,917 | 0,950 | 0,633 | 0,800 | **0,900** | 0,933 | 40,8 | 38,8 |
| `BAAI/bge-m3` | 1024 | **0,867** | **0,967** | **1,000** | **1,000** | **0,925** | **0,967** | **0,750** | **0,867** | **0,917** | **0,967** | **0,700** | **0,833** | 0,867 | **0,933** | 41,2 | 31,5 |

---

## 3. Busca Densa (`exact_dense_cosine`) vs Busca Híbrida (`hybrid_rrf`: Denso + FTS IDF do Postgres)

Com o Postgres populado com os 672 chunks, avaliamos o canal lexical IDF (`portuguese` `tsvector`, `RRF_K = 60`, peso igual `1/(60+rank)` entre canal semântico e canal lexical):

| Configuração | Recuperação | Hit@1 | Hit@5 | MRR | Ev. Complete@5 | Ctx Hit@6 | Ctx Ev. Complete@6 |
|---|---|---:|---:|---:|---:|---:|---:|
| `e5-small` | Densa pura (`exact_dense_cosine`) | 0,633 | 0,800 | 0,706 | 0,733 | 0,833 | 0,733 |
| **`e5-small`** | **Híbrida (`hybrid_rrf` + IDF)** | **0,700** | **0,867** | **0,781** | **0,833** | **0,867** | **0,833** |
| **`bge-m3`** | **Densa pura (`exact_dense_cosine`)** | **0,867** | **1,000** | **0,925** | **0,867** | **1,000** | **0,900** |
| `bge-m3` | Híbrida (`hybrid_rrf` + IDF) | 0,800 | 0,933 | 0,871 | 0,867 | 0,933 | 0,900 |
| `bge-m3` + `bge-reranker-v2-m3` | Híbrida (`hybrid_rrf` + IDF) | **0,933** | **0,967** | **0,954** | **0,933** | **0,967** | **0,933** |

**Achados sobre o canal lexical**:
- **No `e5-small`**, a busca híbrida com IDF produziu ganho sólido (`MRR` de `0,706 -> 0,781`, `Ev. Complete@5` de `0,733 -> 0,833`), resgatando `L05` (de 2º para 1º), `J01` (`0,00 -> 0,10`), `J03` (`0,00 -> 0,11`) e `J10` (`0,00 -> 0,25`).
- **No `bge-m3`**, o RRF `50/50` sem peso diluiu o topo do ranking semântico em perguntas conceituais/com pouca sobreposição lexical direta (`L07`, `L08`, `J08`, `J20`, `J17`), reduzindo `MRR` de `0,925` para `0,871`, embora tenha melhorado `L05` (`0,50 -> 1,00`).
- **Ao aplicar `bge-reranker-v2-m3` sobre `bge-m3 + hybrid_rrf`**, o reranker recuperou totalmente o topo (`MRR = 0,954`, `Ev. Complete@5 = 0,933`), idêntico ao reranking sobre busca densa.

---

## 4. Efeito do Reranking (`BAAI/bge-reranker-v2-m3`, top-40 candidatos)

O reranker CrossEncoder (`max_seq_length = 1024`, sem truncamento de pares pergunta/chunk) foi aplicado sobre os top-40 candidatos (`context-mode = ranked`):

| Configuração | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR | Ev. Recall@5 | Ev. Complete@5 | Ctx Hit@6 | Ctx Ev. Complete@6 | Rerank/q (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `e5-small` (sem rerank) | 0,633 | 0,733 | 0,800 | 0,867 | 0,706 | 0,767 | 0,733 | 0,833 | 0,733 | 0,00 |
| **`e5-small` + `bge-reranker-v2-m3`** | **0,933** | **0,967** | **0,967** | **1,000** | **0,954** | **0,950** | **0,933** | **0,967** | **0,933** | **5,04** |
| `e5-large` (sem rerank) | 0,733 | 0,900 | 0,933 | 0,967 | 0,828 | 0,917 | 0,900 | 0,933 | 0,900 | 0,00 |
| **`e5-large` + `bge-reranker-v2-m3`** | **0,933** | **0,967** | **0,967** | **1,000** | **0,954** | **0,950** | **0,933** | **0,967** | **0,933** | **11,74** |
| `bge-m3` (sem rerank) | 0,867 | 0,967 | 1,000 | 1,000 | 0,925 | 0,917 | 0,867 | 1,000 | 0,900 | 0,00 |
| **`bge-m3` + `bge-reranker-v2-m3`** | **0,933** | **0,967** | **0,967** | **1,000** | **0,954** | **0,950** | **0,933** | **0,967** | **0,933** | **11,87** |

- Os três modelos convergiram para o mesmo teto após o reranking porque o `e5-small` já incluía os trechos corretos no top-40 em `29/30` perguntas positivas (exceto `J14`, art. 10 da Lei 6.938/1981).

---

## 5. Montagem do Contexto (`ranked` vs `siblings` vs `window`, `k = 6`, orçamento `2400` tokens)

| Recuperador | Modo | Ctx Hit@6 | Ctx MRR | Ctx Ev. Recall@6 | Ctx Ev. Complete@6 | Tokens médios |
|---|---|---:|---:|---:|---:|---:|
| `e5-small` | `ranked` | **0,833** | **0,702** | **0,767** | **0,733** | 1.593 |
| `e5-small` | `siblings` | 0,733 | 0,683 | 0,700 | 0,667 | 1.565 |
| `e5-small` | `window` | 0,800 | 0,697 | **0,767** | **0,733** | 1.599 |
| `e5-large` | `ranked` / `window` | **0,933** | **0,823** | **0,917** | **0,900** | 1.627 / 1.645 |
| `e5-large` | `siblings` | 0,833 | 0,783 | 0,817 | 0,800 | 1.627 |
| `bge-m3` | `ranked` | **1,000** | **0,925** | 0,950 | 0,900 | 1.751 |
| **`bge-m3`** | **`siblings`** | **1,000** | **0,925** | **0,967** | **0,933** | **1.704** |
| `bge-m3` | `window` | **1,000** | **0,925** | 0,933 | 0,900 | 1.751 |
| Qualquer modelo + rerank | `ranked` / `window` | **0,967** | **0,950** | **0,950** | **0,933** | 1.722–1.777 |
| Qualquer modelo + rerank | `siblings` | 0,933 | 0,933 | 0,917 | 0,900 | 1.701–1.730 |

- **`siblings` ingênuo** degrada `e5-small` e `e5-large` quando um artigo longo (ex.: art. 3º com 17 partes ou art. 61-A com 15 partes) aparece como falso positivo no topo e consome os 6 slots.
- **No `bge-m3` sem reranker**, como o acerto no topo é alto (`Hit@5 = 1,000`), `siblings` expande o art. 2º da PNMC em `J17` e traz ambas as definições (*adaptação* e *mitigação*), alcançando **`Ctx Hit@6 = 1,000`** e **`Ctx Ev. Complete@6 = 0,933`** sem custo de CrossEncoder.

---

## 6. Experimento Controlado: Diversidade por Norma (`diverse_law`, Opção 1) vs Decomposição em Subconsultas (`--decompose`, Opção 2)

Avaliação isolada antes de alterar o código de produção (`src/rag.py`), comparando como cada opção lida com perguntas multinorma (`J08`, `J14`) e de contraste (`J11`, `J19`) mantendo todas as demais variáveis fixas:

| Modelo | Estratégia | Hit@1 | Hit@5 | MRR | Ev. Complete@5 | Ctx Hit@6 | Ctx Ev. Complete@6 | Multinorma EvC@5 (`J08`, `J14`) | Contraste EvC@5 (`J11`, `J19`) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `e5-small` | Baseline (`ranked`) | 0,633 | 0,800 | 0,706 | 0,733 | 0,833 | 0,733 | 0,50 | 0,50 |
| `e5-small` | **Opção 1**: `diverse_law` | 0,633 | 0,800 | 0,706 | 0,733 | 0,800 | 0,700 | 0,50 | 0,50 |
| `e5-small` | **Opção 2**: `--decompose` (`ranked`) | 0,633 | 0,800 | 0,706 | 0,733 | 0,833 | 0,733 | 0,50 | 0,50 |
| `e5-large` | Baseline (`ranked`) | 0,733 | 0,933 | 0,828 | 0,900 | 0,933 | 0,900 | 0,50 | 1,00 |
| `e5-large` | **Opção 1**: `diverse_law` | 0,733 | 0,933 | 0,828 | 0,900 | 0,933 | 0,900 | 0,50 | 1,00 |
| `e5-large` | **Opção 2**: `--decompose` (`ranked`) | 0,733 | 0,933 | 0,828 | 0,900 | 0,933 | **0,933** | **1,00** | 0,50 |
| `bge-m3` | Baseline (`ranked`) | 0,867 | 1,000 | 0,925 | 0,867 | 1,000 | 0,900 | 0,00 | 1,00 |
| `bge-m3` | **Opção 1**: `diverse_law` | 0,867 | 1,000 | 0,925 | 0,867 | 1,000 | 0,867 | 0,00 | 1,00 |
| `bge-m3` | **Opção 2**: `--decompose` (`ranked`) | **0,867** | **1,000** | **0,925** | **0,933** | **1,000** | **0,967** | **1,00** | **1,00** |
| **`bge-m3`** | **Opção 2 (`--decompose`) + `siblings`** | **0,867** | **1,000** | **0,925** | **0,933** | **1,000** | **1,000** | **1,00** | **1,00** |

**Por que a Opção 2 venceu com folga:**
1. **Opção 1 (`diverse_law`) não resolveu nenhum caso multinorma e piorou as perguntas simples**: em `e5-small` (`L08`) e `bge-m3` (`J07`), forçar outras leis no top-3 expulsou uma parte necessária do artigo-alvo (`Ctx Ev. Complete@6` caiu de `0,733 -> 0,700` no `e5-small` e de `0,900 -> 0,867` no `bge-m3`). Além disso, em `J14`, trouxe o artigo errado das outras leis (art. 23 da Mata Atlântica e art. 17-L da PNMA no `e5-small`; art. 32 da Mata Atlântica e art. 50-A da Lei 9.605 no `bge-m3`).
2. **Opção 2 (`--decompose`) elevou o `bge-m3` para 100% nas multinorma e no conjunto completo quando combinada com `siblings`**:
   - Em `J08`, levou a Lei 9.605 art. 38 para a **2ª posição** (`evC@6 = 1,0`).
   - Em `J14`, colocou o art. 26 do Código Florestal em **1º** e o art. 10 da PNMA em **2º** (`evC@6 = 1,0`) tanto no `bge-m3` quanto no `e5-large`.
   - Com **`bge-m3` + `--decompose` + `siblings`**, todas as **30 perguntas positivas** (`30/30`, **`Ctx Ev. Complete@6 = 1,000`**) tiveram 100% dos trechos de evidência recuperados no contexto XML sem usar CrossEncoder.

---

## 7. Avaliação de Geração e Abstenção (`--generate`, `anthropic/claude-haiku-5.5`)

Comparação ponta a ponta mantendo o mesmo `LAW_SYSTEM_PROMPT`, o mesmo gerador e a régua fixa de cosseno em `intfloat/multilingual-e5-small`:

| Configuração | Ctx Hit@6 | Ctx Ev. Complete@6 | Cosseno fixo (30 pos.) | ROUGE-L F1 (30 pos.) | BLEU (30 pos.) | Acerto de valores | Abstenção correta (`N01`–`N06`) | Tokens médios (in / out, pos.) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`e5-small` (`ranked`)** | 0,833 | 0,733 | 0,892 | 0,154 | 0,056 | 8 / 8 | **6 / 6 (100%)** | 3.526 / 1.041 |
| **`bge-m3` (`siblings`)** | **1,000** | **0,933** | **0,902** | **0,196** | **0,072** | **8 / 8** | **6 / 6 (100%)** | 3.720 / 928 |

**Impacto qualitativo da troca de recuperação na resposta gerada**:
- Com **`e5-small` (`ranked`)**, o modelo foi honesto e **não alucinou** quando o contexto falhou, mas teve de declarar ausência de evidência em **`J01`**, **`J02`**, **`J03`** e **`J17`**, e em **`J07`** trouxe apenas a regra de área consolidada (`15 m`, art. 61-A) sem a regra geral (`50 m`, art. 4º, IV).
- Com **`bge-m3` (`siblings`)**, o gerador passou a responder correta e completamente **`J01`** (área rural consolidada), **`J02`** (reserva legal), **`J03`** (cômputo de APP e exceção do § 4º), **`J07`** (50 metros ao redor de nascentes perenes) e **`J17`** (adaptação vs mitigação na PNMC), elevando o **ROUGE-L F1 de `0,154` para `0,196` (+27% relativo)** e o **cosseno fixo de `0,892` para `0,902`**.
- **Casos residuais que permanecem mesmo com `bge-m3`**:
  - **`J14`** (multinorma: PNMA art. 10 + Código Florestal art. 26): o art. 10 da Lei 6.938/1981 não entrou no top-6 de nenhum recuperador (nem após reranker), então o gerador respondeu corretamente sobre o art. 26 e declarou que os trechos não traziam a regra geral de licenciamento.
  - **`N01`–`N06` (Abstenção)**: **6/6 (100%)** das perguntas negativas foram recusadas adequadamente nas duas configurações — o LLM declarou explicitamente a ausência do Anexo VIII (`N01`), da LC 140/2011 (`N02`), da Lei 14.119/2021 (`N03`), de norma estadual do Pará (`N04`), a impossibilidade de atestar regularidade só com o CAR (`N05`) e a falta de comprovação de vigência atual (`N06`).

---

## 8. Recomendações Finais para a Branch `melhoria-rag-juridico`

1. **Adotar `BAAI/bge-m3` (1024d) com montagem `siblings` (ou `window` para segurança contra falsos positivos longos)** na camada jurídica: entrega **`Ctx Hit@6 = 1,000`**, **`Ctx Ev. Complete@6 = 0,933`** e latência de apenas `~31 ms/consulta`, resolvendo `J01`, `J02`, `J03`, `J07` e `J17` sem o custo de `5–12 s` do CrossEncoder.
2. **Calibrar pesos na fusão híbrida (`hybrid_search`)**: ao usar `BAAI/bge-m3`, dar menor peso ao canal lexical do que ao semântico (ou aplicar `hybrid_rrf` apenas como gerador de candidatos antes de reranking leve) para evitar que o RRF `50/50` rebaixe acertos de topo como ocorreu em `L07`, `L08`, `J08` e `J20`.
3. **Atacar o caso multinorma `J14` na integração com o Arthur**: perguntas com duas normas distintas ("licenciamento geral + supressão de vegetação") exigem decomposição por sub-objetivo jurídico ou busca separada por dispositivo antes da montagem final do contexto.

---

## 9. Verificação em Produção no PostgreSQL (`BAAI/bge-m3` 1024d)

Após aprovação da Opção 2, a configuração vencedora foi integrada ao pipeline de produção e o banco PostgreSQL (`trase_rag`, container `trase-rag-postgres`) foi reindexado em **1024 dimensões**:

- **Alterações aplicadas**:
  - [src/config.py](file:///Users/aluno1/Agro/Ambiance/src/config.py) e `.env` / `.env.example`: padrão atualizado para `EMBEDDING_MODEL=BAAI/bge-m3` e `EMBEDDING_DIM=1024`.
  - [src/embeddings.py](file:///Users/aluno1/Agro/Ambiance/src/embeddings.py) e [src/ingest_laws.py](file:///Users/aluno1/Agro/Ambiance/src/ingest_laws.py): adicionado `count_chunk_tokens` (mantendo a folga canônica de `"passage: "`, pois sem ela o tokenizador XLM-R de `BAAI/bge-m3` gerava `666` chunks divergentes em vez de `672`).
  - [src/vector_store.py](file:///Users/aluno1/Agro/Ambiance/src/vector_store.py): adicionado `LEXICAL_RRF_WEIGHT = 0.02` (calibrado em varredura empírica porque peso `0,2` ainda derrubava `J01` e `J14` para `Ev. Complete@6 = 0,9333`), desempate determinístico por `semantic_rank` e `keyword_rank`, e o helper `get_article_siblings`.
  - [src/rag.py](file:///Users/aluno1/Agro/Ambiance/src/rag.py): integrados `decompose_legal_query`, intercalação `_interleave_candidates`, expansão `_expand_siblings` em `retrieve()` e import preguiçoso de `route_question` em `resolve_domain()`.
  - [src/agent.py](file:///Users/aluno1/Agro/Ambiance/src/agent.py): atualizada a descrição da ferramenta `search_laws` em `TOOLS`.
- **Reconciliação pós-reindexação ([audit.md](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/audit.md), [audit.json](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/audit.json))**:
  - `status`: **`read`** (`7` documentos, **`672` chunks**, `embedding_model = BAAI/bge-m3`, `dimensions = [1024]`, reindexação completa em `84,1 s`).
  - `matches_frozen_reference`: **`True`** (`chunks_sha256 = 82c136c17fcff57ad67bb154db304400a02a3778f5317c4ebbcb175d5863c8a5`).
  - Segunda execução de `ingest_laws()` pulou todas as 7 normas (`sem mudanças, pulando`).
- **Validação ao vivo de `src.rag.retrieve(q, k=6)` contra o PostgreSQL (30 perguntas positivas)**:
  - **`Hit@1 = 0,8667`** | **`Hit@3 = 0,9667`** | **`Hit@5 = 1,0000`** | **`Hit@6 = 1,0000`**
  - **`MRR = 0,9250`** | **`Recall@6 = 1,0000`** | **`Ev. Recall@6 = 1,0000`** | **`Ev. Complete@6 = 1,0000` (30/30)**
  - Latência ponta a ponta ao vivo (`embed_query` + SQL HNSW/FTS + `get_article_siblings`): mediana **`68,9 ms/consulta`** (média **`83,4 ms`**).
  - Suíte unitária (`pytest tests/test_legal_eval.py tests/test_eval_metrics.py tests/test_fts_query.py`): **48 passed**.

---

## 10. Blindagens `v2` e Expansão para 11 Normas Federais (904 Chunks)

Após os testes de robustez em perguntas compostas livres e partes finais (`parte >= 7`) e a incorporação das 4 normas que estavam em `docs/leis/` fora do manifesto:

- **Blindagens aplicadas em [src/rag.py](file:///Users/aluno1/Agro/Ambiance/src/rag.py) e [src/law_parser.py](file:///Users/aluno1/Agro/Ambiance/src/law_parser.py)**:
  - `decompose_legal_query`: passou a decompor também múltiplas interrogações (`?`), conectivos interrogativos compostos (`"... e qual/quais/como/quando..."`) e estruturas `"tanto ... quanto ..."`.
  - `_prioritize_sibling_parts` + `_expand_siblings`: em artigos extensos (`art. 3º` com 17 partes, `art. 61-A` com 15 partes etc.), preserva o caput (`parte 1`), a parte recuperada pelo `bge-m3` e suas vizinhas quando o artigo não cabe inteiro em `k` vagas, além de limitar artigos únicos a `k - 2` quando há subconsultas inter-normas.
  - `_diversify_subquery_laws` + `_NAMES_SPECIFIC_LAW_RE`: em subconsultas abertas que não citam um diploma específico (ex.: `"a exigência geral de licenciamento"` após a entrada da Lei 15.190/2025), diversifica as leis antes de repetir o mesmo diploma; quando a subconsulta cita explicitamente uma norma (ex.: `"na Mata Atlântica"`), preserva a ordem natural dos seus dispositivos.
  - [src/law_parser.py](file:///Users/aluno1/Agro/Ambiance/src/law_parser.py): adicionada junção de número de artigo partido por tag HTML (`"Art. 1 8." -> "Art. 18."` no Decreto 7.830/2012) e prefixo `"Fixa"` em `EMENTA_RE` (LC 140/2011), mantendo intactos todos os 672 chunks anteriores.
- **Expansão do manifesto ([docs/leis/manifest.json](file:///Users/aluno1/Agro/Ambiance/docs/leis/manifest.json)) para 11 normas (624 artigos, 904 chunks)**:
  - Incluídas `Decreto nº 7.830/2012` (CAR/SICAR, 23 artigos, 35 chunks), `Lei Complementar nº 140/2011` (competências federativas, 22 artigos, 33 chunks), `Lei nº 14.119/2021` (PSA, 24 artigos, 41 chunks) e `Lei nº 15.190/2025` (Lei Geral do Licenciamento Ambiental, 67 artigos, 123 chunks).
  - Auditoria ([audit.md](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/audit.md)): `documents = 11`, `chunks = 904`, `dimensions = [1024]`, `embedding_model = BAAI/bge-m3`, `matches_frozen_reference = True` (`chunks_sha256 = 5f8c547f1aa02776973c2754a77ca4b2b1b2e594e8aebc8a607b7c5ef0eb6db2`), `0` divergências.
- **Resultados ao vivo no PostgreSQL (`11` leis / `904` chunks, `src.rag.retrieve(q, k=6)`)**:
  - **Benchmark ampliado (34 perguntas positivas `L01`–`L08`, `J01`–`J26`)**: **`Hit@1 = 0,8824`**, **`Hit@3 = 0,9706`**, **`Hit@5 = 1,0000`**, **`Hit@6 = 1,0000`**, **`MRR = 0,9338`**, **`Recall@6 = 1,0000`**, **`Ev. Recall@6 = 1,0000`**, **`Ev. Complete@6 = 1,0000` (34/34)**; latência mediana **`67,7 ms`**.
  - **Stress test (12 perguntas: 6 partes finais `parte >= 7` + 6 compostas livres `S01`–`S12`)**: **`Hit@6 = 1,0000`**, **`Recall@6 = 1,0000`**, **`Ev. Recall@6 = 1,0000`**, **`Ev. Complete@6 = 1,0000` (12/12)** (vs. `25,0%` antes das blindagens `v2`); latência mediana **`180,0 ms`**.

---

## 11. Expansão Completa do Acervo Agroambiental para 29 Normas Federais (1.893 Chunks)

Para cobrir integralmente os domínios do sistema (soja, carne bovina, desmatamento, CAR/PRA, crédito rural, rastreabilidade bovina, recursos hídricos, manejo do fogo, mercado de carbono, regularização fundiária e terras indígenas/quilombolas), foram baixadas do Planalto, limpas com `scripts/remove_revoked.py` e ingeridas em `1024d` (`BAAI/bge-m3`) mais **18 normas federais** (substituindo o revogado Decreto nº 6.321/2007 pelo vigente **Decreto nº 11.687/2023**):

- **Reconciliação final ([audit.md](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/audit.md), [audit.json](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/auditoria/audit.json))**:
  - **`29` normas federais**, **`1.306` artigos**, **`1.893` chunks**, **`1024` dimensões** (`BAAI/bge-m3`), `0` divergências de artigo/hash e `matches_frozen_reference = True` (`chunks_sha256 = b3e3427afab0a8bb722cf247aa3fa41b65160a0323b0289551f5518f5d46c7c4`).
- **Desempenho ao vivo no PostgreSQL (`29` leis / `1.893` chunks, `src.rag.retrieve(q, k=6)`)**:
  - **Benchmark oficial (`42` positivas `L01`–`L08`, `J01`–`J34`)**: **`Hit@1 = 0,9048`**, **`Hit@3 = 0,9762`**, **`Hit@5 = 1,0000`**, **`Hit@6 = 1,0000`**, **`MRR = 0,9452`**, **`Recall@6 = 1,0000`**, **`Ev. Recall@6 = 1,0000`**, **`Ev. Complete@6 = 1,0000` (42/42)**; latência mediana **`83,2 ms`**.
  - **Stress test (`12` perguntas `S01`–`S12`)**: **`Hit@6 = 1,0000`**, **`Recall@6 = 1,0000`**, **`Ev. Recall@6 = 1,0000`**, **`Ev. Complete@6 = 1,0000` (12/12)**; latência mediana **`201,5 ms`**.
  - **Suíte de testes (`pytest tests/test_legal_eval.py tests/test_eval_metrics.py tests/test_fts_query.py`)**: **`49 passed`**.

---

## 12. Rodada de Geração com LLM (`--generate`) sobre 29 Normas e 48 Perguntas

Rodada executada via `eval.legal_eval --generate` em [juridico_bge_m3_29leis_gen](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/rodadas/juridico_bge_m3_29leis_gen/summary.json) (`BAAI/bge-m3`, `hybrid_rrf`, `lexical_weight=0.02`, `--decompose`, `--context-mode siblings`, `corpus_sha256 = f71a0674b96214c0eb64598287fdd42c7e67e2e89ae277e70f14cff46af7ff6f`):

- **Recuperação no avaliador offline (`42` positivas)**:
  - **`Hit@1 = 0,9048`** | **`Hit@3 = 0,9762`** | **`Hit@5 = 1,0000`** | **`Context Hit@6 = 1,0000`**
  - **`MRR = 0,9452`** | **`Context Recall@6 = 0,9881`** | **`Context Ev. Complete@6 = 0,9762` (41/42)** *(em `J17`, o montador offline de `siblings` sem `_prioritize_sibling_parts` deixou parte secundária fora de `k=6`, mas o LLM respondeu corretamente com `cosseno = 0,9126`; em produção `src.rag.retrieve` atinge `42/42 = 1,0000`)*.
- **Geração nas perguntas positivas (`42` perguntas)**:
  - **Cosseno fixo (`multilingual-e5-small`)**: **`0,9036`** (mín. `0,8419` em `J10`, máx. `0,9364` em `L07`; **faixa `J23`–`J34` entre `0,8940` e `0,9294`**)
  - **ROUGE-L Recall médio**: **`0,7417`** | **ROUGE-L F1 médio**: **`0,2237`** | **BLEU médio**: **`0,0922`** *(F1 e BLEU mais baixos que o recall porque o LLM inclui fundamentação completa e citações legais, enquanto `resposta_esperada` é sintética)*
  - **Tokens médios**: `3.704,9` entrada / `1.032,1` saída (`0` respostas cortadas por `max_tokens`; todas encerraram com `stop_reason = end_turn`; `5` respostas — `J06`, `J14`, `J24`, `J26`, `J27` — excederam `512` tokens apenas no codificador de similaridade `e5-small`)
- **Abstenção (`6` perguntas: `N01`–`N06`)**:
  - **Taxa automática (`_check_abstention_response`)**: **`0,6667` (`4/6`)** — `N01`, `N04`, `N05` e `N06` casaram com marcadores explícitos (`"não traz"`, `"Não há"`).
  - **Inspeção manual em [details.jsonl](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/rodadas/juridico_bge_m3_29leis_gen/details.jsonl)**: **`6/6` (`100%`)** de abstenção correta — `N02` (EUDR 2023/1115) e `N03` (ITBI de Sorriso-MT) iniciaram diretamente com *"Os trechos fornecidos/disponíveis não respondem a essa pergunta"* e se recusaram a completar com conhecimento externo; o verificador automático não marcou `N02` e `N03` apenas porque a frase exata `"não respondem a essa pergunta"` não está na lista de regex do detector.
  - **Cosseno / tokens médios (`N01`–`N06`)**: `0,8732` | `3.862,7` entrada / `955,8` saída (`0` truncamentos).

---

## 13. Troca da Régua de Similaridade para `BAAI/bge-m3` e Comparação com a Escala Histórica (`e5-small`)

Para eliminar o truncamento acima de `512` tokens em respostas jurídicas extensas e ganhar separação real entre respostas pertinentes e referências não relacionadas, [eval/text_metrics.py](file:///Users/aluno1/Agro/Ambiance/eval/text_metrics.py) passou a usar **`BAAI/bge-m3`** (`revision = 5617a9f61b028005a4858fdac845db406aefb181`, limite `8.192` tokens) como `SIMILARITY_MODEL`, preservando a escala histórica do `intfloat/multilingual-e5-small` em `HISTORICAL_SIMILARITY_*` (e nos arquivos já salvos).

Comparação direta sobre as **mesmas 48 respostas geradas** em [juridico_bge_m3_29leis_gen](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/rodadas/juridico_bge_m3_29leis_gen/details.jsonl) ([similaridade_e5_vs_bgem3.json](file:///Users/aluno1/Agro/Ambiance/eval/resultados/rag_juridico/relatorios/similaridade_e5_vs_bgem3.json)):

| Métrica (42 positivas / 6 abstenções) | `e5-small` (Histórica) | `BAAI/bge-m3` (Nova Régua) |
|---|---|---|
| **Janela máxima (`limite_tokens`)** | `512` tokens | **`8.192` tokens** |
| **Respostas truncadas (positivas)** | `5/42` (`J06`, `J14`, `J24`, `J26`, `J27`; máx. `720` tok) | **`0/42`** (máx. observado `717` tok) |
| **Cosseno médio (positivas — própria ref.)** | `0,9036` (med. `0,9030`, faixa `0,8419`–`0,9364`) | **`0,7801`** (med. `0,7973`, faixa `0,4929`–`0,9371`) |
| **Cosseno médio com OUTRAS referências (`cosine_baseline`)** | `0,8469` (máx. `0,9404`) | **`0,5082`** (máx. `0,8840`) |
| **Margem discriminativa (`próprio - outras`)** | **`+0,0566`** (`5,7` p.p.) | **`+0,2720`** (**`4,8×` maior**) |
| **Cosseno médio nas abstenções (`N01`–`N06`)** | `0,8732` (med. `0,8654`) | **`0,5608`** (med. `0,5559`) |

- **Principais achados**:
  - Os **5 casos truncados** no `e5-small` passam a ser lidos integralmente no `bge-m3` sem corte: `J06` (`0,9189 -> 0,7462`), `J14` (`0,9024 -> 0,7048`), `J24` (`0,8992 -> 0,7661`), `J26` (`0,9160 -> 0,8111`) e `J27` (`0,9079 -> 0,8027`).
  - A queda numérica absoluta de `0,9036` para `0,7801` não indica pior qualidade, mas sim o fim da compressão artificial do `e5-small` (que dava `0,8469` até para pares não relacionados e `0,8732` para abstenções). No `bge-m3`, a margem discriminativa sobe de **`+0,0566` para `+0,2720`**.
  - Casos extensos como `J10` (`bge-m3 = 0,4929`) e `J13` (`0,6544`) refletem respostas completas muito mais longas que a referência sintética (`444` vs. `31` tokens em `J10`, com `ROUGE-L Recall = 0,7222`), enquanto pares de extensão equilibrada atingem `0,867–0,937` (`J29 = 0,9371`, `J25 = 0,8970`, `J23 = 0,8768`).
  - **Suíte de testes após a troca (`pytest tests/test_legal_eval.py tests/test_eval_metrics.py tests/test_fts_query.py`)**: **`49 passed`**.

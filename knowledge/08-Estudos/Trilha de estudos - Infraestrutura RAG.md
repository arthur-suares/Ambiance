---
tags: [estudos, infraestrutura, rag, dados]
status: rascunho
data: 2026-11-11
---

# Trilha de estudos - Infraestrutura RAG

Esta trilha acompanha o [[Plano de implementação da infraestrutura RAG]]. A ordem prioriza o que será implementado primeiro.

## 1. Fundamentos de RAG e recuperação

### Leitura essencial

- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401) — artigo fundador para entender memória paramétrica e não paramétrica.
- [Text Embeddings by Weakly-Supervised Contrastive Pre-training](https://arxiv.org/abs/2212.03533) — artigo do E5; explica o modelo usado atualmente.
- [Reciprocal Rank Fusion](https://doi.org/10.1145/1571941.1572114) — método que combina os rankings semântico e textual.
- [HNSW](https://arxiv.org/abs/1603.09320) — algoritmo do índice aproximado usado pelo pgvector.

### Objetivo prático

Conseguir explicar por que os dados tabulares usam SQL, as leis usam busca híbrida e o que muda entre similaridade exata e HNSW.

## 2. DuckDB, Parquet e modelagem analítica

### Documentação

- [DuckDB: leitura e escrita de Parquet](https://duckdb.org/docs/data/parquet)
- [DuckDB: concorrência](https://duckdb.org/docs/stable/connect/concurrency.html)
- [DuckDB: dicas de Parquet](https://duckdb.org/docs/stable/data/parquet/tips)
- [Apache Arrow e Parquet em Python](https://arrow.apache.org/docs/python/parquet/)

### Objetivo prático

Construir um pipeline pequeno que converta CSV/XLSX para Parquet, preserve tipos, valide contagem de linhas e gere um DuckDB somente leitura.

## 3. dbt Core e qualidade de dados

### Documentação

- [dbt: projetos e modelos](https://docs.getdbt.com/docs/build/projects)
- [dbt: testes de dados](https://docs.getdbt.com/docs/build/data-tests)
- [dbt: documentação dos modelos](https://docs.getdbt.com/docs/collaborate/documentation)
- [dbt-duckdb](https://github.com/duckdb/dbt-duckdb)

### Objetivo prático

Modelar uma tabela Silver e uma Gold, com testes de chave, valores aceitos, relacionamento e uma regra de negócio do projeto.

## 4. Orquestração com Dagster

### Documentação

- [Dagster: conceitos](https://docs.dagster.io/concepts)
- [Dagster: assets](https://docs.dagster.io/guides/build/assets)
- [Dagster: schedules](https://docs.dagster.io/guides/automate/schedules)
- [Dagster: sensors](https://docs.dagster.io/guides/automate/sensors)
- [Dagster: partitions e backfills](https://docs.dagster.io/guides/build/partitions-and-backfills)

### Objetivo prático

Transformar uma CLI idempotente em um asset, particionar por ano e executar um backfill controlado.

## 5. PostgreSQL, pgvector e busca híbrida

### Documentação

- [PostgreSQL: full-text search](https://www.postgresql.org/docs/17/textsearch.html)
- [PostgreSQL: tabelas e índices de texto](https://www.postgresql.org/docs/17/textsearch-tables.html)
- [pgvector: README oficial](https://github.com/pgvector/pgvector)
- [pgvector: busca híbrida, HNSW e filtros](https://github.com/pgvector/pgvector#hybrid-search)

### Objetivo prático

Criar uma tabela com `tsvector` e `vector`, medir busca exata, HNSW e full-text e combinar os rankings com RRF.

## 6. Dados geoespaciais e tiles

### Documentação

- [PostGIS: documentação](https://postgis.net/documentation/)
- [PostGIS: ST_AsMVT](https://postgis.net/docs/ST_AsMVT.html)
- [PostGIS: ST_AsMVTGeom](https://postgis.net/docs/ST_AsMVTGeom.html)
- [Martin tile server](https://maplibre.org/martin/)
- [Martin com PostgreSQL](https://maplibre.org/martin/run/)
- [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/)
- [Política de uso dos tiles do OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/)

### Objetivo prático

Publicar uma camada municipal simplificada como MVT e visualizá-la no MapLibre com estilo dirigido por um indicador.

## 7. API e contratos

### Documentação

- [FastAPI: primeiros passos](https://fastapi.tiangolo.com/tutorial/first-steps/)
- [FastAPI em containers](https://fastapi.tiangolo.com/deployment/docker/)
- [Pydantic: modelos](https://docs.pydantic.dev/latest/concepts/models/)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)

### Objetivo prático

Implementar `/health/ready` e `/api/v1/ask` com entrada e saída validadas, documentação OpenAPI e teste de contrato.

## 8. Modelos locais e serving

### Documentação

- [Ollama API](https://docs.ollama.com/api/introduction)
- [vLLM: servidor compatível com OpenAI](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/)
- [vLLM com Docker](https://docs.vllm.ai/en/stable/deployment/docker/)

### Objetivo prático

Executar a mesma ferramenta de agente contra dois provedores, mantendo o contrato e comparando acerto, latência e uso de memória.

## 9. Avaliação do RAG

### Artigos e documentação

- [RAGAS: Automated Evaluation of Retrieval Augmented Generation](https://arxiv.org/abs/2309.15217)
- [ARES: Automated RAG Evaluation System](https://arxiv.org/abs/2311.09476)
- [pytest: primeiros passos](https://docs.pytest.org/en/stable/getting-started.html)
- Plano interno: `eval/PLANO_AVALIACAO.md`

### Objetivo prático

Medir retrieval e geração separadamente. O juiz LLM complementa, mas não substitui, gabaritos determinísticos e revisão humana.

## 10. Containers, observabilidade e segurança

### Documentação

- [Docker Compose: quickstart](https://docs.docker.com/compose/gettingstarted/)
- [Docker Compose: secrets](https://docs.docker.com/compose/how-tos/use-secrets/)
- [OpenTelemetry](https://opentelemetry.io/docs/)
- [Prometheus: visão geral](https://prometheus.io/docs/introduction/overview/)
- [Grafana OSS](https://grafana.com/docs/grafana/latest/)
- [OWASP: prompt injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP API Security Top 10](https://api-security.owasp.org/editions/2023/en/0x00-header/)

### Objetivo prático

Subir API e dependências com health checks, secrets fora do Git, traces de ponta a ponta e um dashboard de latência/erro.

## Ordem sugerida de estudo

| Ciclo | Conteúdo | Exercício no Ambiance |
|---:|---|---|
| 1 | DuckDB, Parquet e contratos | inventariar e converter um dataset pequeno |
| 2 | dbt e qualidade | criar Silver/Gold do IBGE soja |
| 3 | PostgreSQL, pgvector e RRF | reproduzir a busca das leis |
| 4 | avaliação | executar baseline de perguntas |
| 5 | FastAPI e contratos | expor `/ask` e health checks |
| 6 | PostGIS, Martin e MapLibre | publicar um indicador municipal |
| 7 | Ollama/vLLM | comparar modelos no benchmark |
| 8 | Dagster e observabilidade | automatizar e monitorar o fluxo completo |

## Regra de estudo

Cada ciclo deve produzir um artefato no repositório: código, teste, ADR, benchmark ou documento. O aprendizado só é considerado concluído quando a equipe consegue reproduzir o exemplo no Ambiance.

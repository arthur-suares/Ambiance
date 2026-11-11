---
tags: [adr, arquitetura, open-source]
status: decisão
data: 2026-11-11
---

# ADR-001 - Arquitetura aberta e medalhão

## Contexto

O projeto precisa processar dados tabulares, geoespaciais e jurídicos com rastreabilidade e baixo custo de entrada.

## Decisão

Adotar componentes de código aberto e a [[Arquitetura medalhão]], começando com Parquet, DuckDB, PostgreSQL, PostGIS, pgvector, FastAPI e MapLibre.

## Consequências

- O MVP pode operar em Docker Compose.
- Tecnologias distribuídas só serão introduzidas quando volume ou concorrência justificarem.
- A equipe precisa manter manifestos, testes e versionamento das publicações.

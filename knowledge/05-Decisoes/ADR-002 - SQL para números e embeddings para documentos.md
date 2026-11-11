---
tags: [adr, rag, dados]
status: decisão
data: 2026-11-11
---

# ADR-002 - SQL para números e embeddings para documentos

## Contexto

Rankings, somas, percentuais e séries temporais exigem cálculo exato. Similaridade vetorial é apropriada para recuperar texto, não para agregar medidas.

## Decisão

- Recuperar dados numéricos com SQL.
- Usar embeddings e full-text search para [[Legislação ambiental]] e metodologias.
- Permitir que o agente combine os dois tipos de evidência.

## Consequências

O [[Arquitetura do RAG|RAG]] precisa manter ferramentas, citações e guardrails distintos para dados e documentos.

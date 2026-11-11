---
tags: [arquitetura, rag, ia]
status: rascunho
---

# Arquitetura do RAG

O sistema combina recuperação estruturada e documental.

## Dados numéricos

- Consultados por SQL em snapshots DuckDB somente leitura.
- Consultas prontas são preferidas ao SQL livre.
- O SQL livre deve aceitar apenas um `SELECT`, com timeout e limite de linhas.

## Documentos

- [[Legislação ambiental]] dividida por artigo.
- Embeddings multilíngues no pgvector.
- Full-text search em português.
- Fusão das buscas por Reciprocal Rank Fusion.

## Agente

O roteador identifica perguntas sobre [[Carne bovina]], [[Soja]], leis ou domínio misto. O agente usa as ferramentas adequadas e retorna o [[Contrato de resposta da IA]].

## Proveniência

Cada afirmação quantitativa recebe uma citação de dados; cada afirmação jurídica recebe uma citação com diploma e artigo.

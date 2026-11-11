---
tags: [fonte, legislacao, rag]
status: rascunho
---

# Legislação ambiental

O acervo jurídico é recuperado pelo [[Arquitetura do RAG]] por busca híbrida: embeddings e busca textual.

## Metadados necessários

- diploma, artigo e hierarquia;
- jurisdição e abrangência territorial;
- data de publicação;
- início e fim de vigência;
- situação do dispositivo;
- URL oficial, data de obtenção e SHA-256;
- texto original e texto consolidado.

## Regra

Trechos revogados podem ser excluídos do índice de legislação vigente, mas as versões históricas devem ser preservadas para perguntas referentes a períodos anteriores.

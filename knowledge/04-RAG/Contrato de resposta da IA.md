---
tags: [rag, api, contrato]
status: rascunho
---

# Contrato de resposta da IA

A IA deve devolver uma estrutura que possa controlar o produto, e não somente texto.

```json
{
  "answer": "Resposta em português",
  "domain": "beef | soy | law | mixed",
  "data_citations": [],
  "legal_citations": [],
  "map": {
    "layer": "nome_da_camada",
    "territorial_level": "municipality | state | biome",
    "year": 2022,
    "metric": "nome_da_metrica"
  },
  "charts": [],
  "warnings": [],
  "coverage": {
    "start_year": 2004,
    "end_year": 2022
  }
}
```

Os campos serão refinados junto com [[Visão do produto]], [[Arquitetura de dados]] e [[Arquitetura do RAG]].

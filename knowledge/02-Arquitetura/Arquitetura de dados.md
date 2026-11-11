---
tags: [arquitetura, dados, medalhao]
status: rascunho
---

# Arquitetura de dados

O projeto adota a [[Arquitetura medalhão]] para separar preservação, padronização e consumo.

## Bronze

Arquivos originais, imutáveis, acompanhados por manifesto com fonte, versão, data de obtenção, licença e SHA-256.

## Silver

Dados limpos e padronizados em Parquet, mantendo granularidade, fonte, unidade, metodologia e código territorial. Veja [[Modelo conceitual]].

## Gold

Tabelas e views de consumo para o mapa, os gráficos e as ferramentas SQL do [[Arquitetura do RAG|RAG]].

## Regra contra contradições

Métricas de fontes diferentes não são tratadas como equivalentes. Por exemplo, desmatamento observado pelo [[MapBiomas]] e exposição ao desmatamento estimada pelo [[Trase]] devem manter nomes, metodologias e campos distintos.

## Cobertura temporal

Ausência de dado é `NULL`, nunca zero. Combinações entre fontes devem informar a interseção temporal efetivamente utilizada.

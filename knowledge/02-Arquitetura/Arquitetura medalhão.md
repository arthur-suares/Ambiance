---
tags: [dados, medalhao]
status: rascunho
---

# Arquitetura medalhão

## Bronze

Preserva exatamente o que foi obtido de [[Fontes de dados]], sem correção destrutiva.

## Silver

Padroniza tipos, nomes, unidades, chaves territoriais e metadados. As transformações devem ser reproduzíveis e testadas.

## Gold

Materializa indicadores e agregados aprovados para [[Visão do produto|o produto]] e para consultas do [[Arquitetura do RAG|agente]].

## Publicação

Cada publicação deve ter um `release_id`, manifesto de arquivos, resultado dos testes e matriz de cobertura temporal.

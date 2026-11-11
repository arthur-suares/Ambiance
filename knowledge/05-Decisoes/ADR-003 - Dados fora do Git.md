---
tags: [adr, dados, git]
status: decisão
data: 2026-11-11
---

# ADR-003 - Dados fora do Git

## Contexto

Os datasets locais ocupam aproximadamente 1,5 GB e podem conter arquivos derivados e substituíveis.

## Decisão

Manter dados brutos e processados fora do controle de versão Git. Versionar apenas código, esquemas, catálogos, manifestos e relatórios de qualidade.

## Consequências

- Evita repositório excessivamente grande.
- Cada ambiente deve configurar os caminhos dos dados.
- SHA-256 e metadados permitem verificar a reprodução das cargas.

Veja [[Inventário de datasets]] e [[Histórico de implementação]].

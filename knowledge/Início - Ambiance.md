---
tags: [ambiance, moc]
status: rascunho
---

# Início - Ambiance

O Ambiance é um produto para analisar as cadeias brasileiras de [[Carne bovina]] e [[Soja]], relacionando produção, fluxos comerciais, [[Desmatamento]], [[Emissões de CO2]] e [[Legislação ambiental]].

## Navegação principal

- [[Visão do produto]]
- [[Arquitetura geral]]
- [[Arquitetura de dados]]
- [[Arquitetura do RAG]]
- [[Plano de implementação da infraestrutura RAG]]
- [[Trilha de estudos - Infraestrutura RAG]]
- [[Fontes de dados]]
- [[Modelo conceitual]]
- [[Glossário]]
- [[Roadmap]]
- [[Histórico de implementação]]

## Princípios

1. Números são recuperados por SQL, não por similaridade vetorial.
2. Embeddings são usados para documentos, especialmente [[Legislação ambiental]].
3. Toda resposta deve apresentar proveniência, período, unidade e limitações.
4. As fontes não devem ser fundidas quando representam conceitos metodologicamente diferentes.
5. A infraestrutura deve priorizar componentes de código aberto.

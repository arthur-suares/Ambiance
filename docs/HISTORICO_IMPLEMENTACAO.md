# Histórico de implementação

Este documento registra as alterações realizadas no projeto, as decisões técnicas, as validações executadas e os próximos passos.

## 2026-11-11 — Preparação do repositório

### Objetivo

Clonar o projeto Ambiance sem sobrescrever ou mover os dados que já estavam no diretório de trabalho.

### Ações realizadas

1. Verificada a pasta `/Users/aluno1/Agro` antes do clone.
2. Confirmado que ela não era um repositório Git e continha aproximadamente 1,5 GB de arquivos.
3. Identificada a branch padrão `main` no repositório remoto.
4. Clonado `https://github.com/arthur-suares/Ambiance.git` em `/Users/aluno1/Agro/Ambiance`.
5. Criada a branch local `integracao-dados`, evitando alterações diretas na `main`.
6. Verificado o `.gitignore`: os conteúdos de `data/raw/` e `data/processed/` não são versionados.

### Estado dos dados

- Os arquivos brutos continuam em `/Users/aluno1/Agro`.
- Os dados tratados continuam em `/Users/aluno1/Agro/dados_processados`.
- Nenhum dado foi movido, apagado, duplicado ou enviado ao GitHub.
- Nenhuma alteração foi enviada ao repositório remoto.

### Decisão técnica

Os dados permanecerão fora do repositório Git. A integração será feita por configuração e catálogos de datasets, preservando rastreabilidade e evitando versionar arquivos grandes.

### Observação

O `README.md` presente no repositório parece anterior ao documento técnico fornecido pela equipe do RAG. A atualização da documentação deverá preservar os requisitos mais recentes de soja, roteamento misto e citações.

### Próximo passo sugerido

Criar um inventário dos arquivos existentes e definir o mapeamento de cada dataset para as camadas Bronze, Silver e Gold.

## 2026-11-11 — Base de conhecimento no Obsidian

### Objetivo

Criar um grafo de conhecimento versionado para centralizar conceitos, fontes, arquitetura, decisões e andamento do projeto.

### Ações realizadas

1. Configurada a raiz do repositório como vault do Obsidian.
2. Criadas configurações compartilháveis em `.obsidian/app.json` e `.obsidian/graph.json`.
3. Excluídos do Git os arquivos pessoais de workspace do Obsidian.
4. Criada a pasta `knowledge/` com notas conectadas por links internos.
5. Criadas notas iniciais sobre produto, arquitetura, fontes, RAG, domínio, decisões e roadmap.
6. Criados templates para novas notas e registros de decisão arquitetural.

### Decisões

- O vault é a raiz do repositório para incluir no grafo o README e os demais documentos Markdown.
- Dados brutos, arquivos processados, credenciais e preferências pessoais não pertencem ao grafo versionado.
- Decisões arquiteturais serão registradas como ADRs.

### Validação prevista

Verificar links internos, sintaxe dos arquivos e estado do Git antes do primeiro commit.

### Nota de ambiente

Neste ambiente, o interpretador está disponível como `python3`, e não como `python`. Os comandos de documentação e automação devem considerar essa diferença.

### Verificação do aplicativo Obsidian

Foi tentada a abertura do vault com o aplicativo Obsidian, mas o macOS não encontrou um aplicativo registrado com esse nome. Também foram verificadas as pastas padrão de aplicativos, o identificador `md.obsidian`, o Homebrew, comandos instalados e a pasta Downloads, sem localizar o aplicativo ou instalador. O vault permanece pronto e pode ser aberto assim que o Obsidian estiver instalado ou seu caminho for informado.

Após a instalação, o aplicativo foi localizado em `/Applications/Obsidian.app` e o vault `/Users/aluno1/Agro/Ambiance` foi aberto com sucesso.

## 2026-11-11 — Plano de implementação da infraestrutura do RAG

### Objetivo

Transformar a arquitetura conceitual em uma sequência executável de implementação, com gates, entregáveis, critérios de aceite e material de estudo.

### Diagnóstico realizado

- Revisados `docker-compose.yml`, `requirements.txt`, `src/config.py`, pipelines de conversão, testes e plano de avaliação.
- Confirmado que o repositório já possui DuckDB, pgvector, parser jurídico, busca híbrida, consultas SQL e guardrails.
- Identificadas lacunas em contratos de dados, publicação medalhão, API de produção, PostGIS, tiles, modelo local, orquestração, observabilidade, CI/CD e backups.

### Documentos criados

- `docs/PLANO_IMPLEMENTACAO_INFRA_RAG.md`: plano completo em fases e gates.
- `knowledge/02-Arquitetura/Plano de implementação da infraestrutura RAG.md`: nó do plano no grafo.
- `knowledge/08-Estudos/Trilha de estudos - Infraestrutura RAG.md`: documentação oficial, artigos e exercícios.

### Decisões propostas

- Evoluir o sistema existente incrementalmente, sem reescrita total.
- Manter DuckDB como artefato analítico somente leitura e PostgreSQL como banco online.
- Introduzir dbt depois dos contratos e Dagster depois das CLIs idempotentes.
- Usar Ollama no desenvolvimento e avaliar vLLM para produção com GPU.
- Selecionar modelo e reranker por benchmark do Ambiance.
- Começar por um fluxo vertical pequeno do IBGE soja antes de generalizar.

### Fontes consultadas

Foram priorizadas documentações oficiais de DuckDB, Apache Arrow, dbt, Dagster, PostgreSQL, pgvector, PostGIS, Martin, MapLibre, FastAPI, Pydantic, Docker, Ollama, vLLM, OpenTelemetry, Prometheus, Grafana e OWASP, além dos artigos originais de RAG, E5, HNSW, RRF, RAGAS e ARES.

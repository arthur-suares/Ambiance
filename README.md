# Trase RAG

Chatbot que responde perguntas sobre a cadeia da carne bovina brasileira e sobre a legislação ambiental, com citação de cada número e de cada artigo de lei.

Duas fontes, duas formas de recuperação:

| Fonte | Armazenamento | Recuperação |
|---|---|---|
| Dados do Trase (fluxos da cadeia, indicadores territoriais, estabelecimentos) | Parquet → DuckDB | SQL: consultas prontas e SELECT gerado pelo LLM |
| Leis ambientais | PostgreSQL + pgvector | Busca híbrida (vetor + full-text) |

Linhas de tabela não viram embeddings: rankings, somas e tendências são calculados por SQL. Um agente (LLM com ferramentas) decide o que consultar em cada pergunta e pode combinar as duas fontes.

## Estrutura

```text
├── data/
│   ├── raw/                  # CSVs baixados do Trase
│   └── processed/
│       ├── parquet/          # Parquet convertidos (fonte do banco)
│       └── trase.duckdb      # banco analítico gerado (build-db)
├── docs/
│   ├── dicionario_dados.md   # gerado a partir de src/data_dictionary.py
│   └── leis/                 # leis ambientais (HTML do Planalto)
├── scripts/
│   ├── csv_to_parquet.py     # CSV -> Parquet
│   └── remove_revoked.py     # remove trechos revogados das leis
├── sql/                      # esquema do Postgres/pgvector
├── src/
│   ├── agent.py              # agente: LLM + ferramentas (dados e leis)
│   ├── data_dictionary.py    # dicionário de dados (prompt do LLM e docs)
│   ├── database.py           # Parquet -> DuckDB, conexão e SQL isolado
│   ├── queries.py            # consultas prontas
│   ├── rag.py                # RAG só de leis
│   ├── vector_store.py, embeddings.py, law_parser.py, ingest_laws.py
│   ├── cli.py
│   └── web.py                # página local de teste
└── web/index.html
```

## Instalação

Requer Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

Copie `.env.example` para `.env` e preencha `OPENROUTER_API_KEY` e `PG_PASSWORD`.

## Dados do Trase

1. Baixe os CSVs para `data/raw/` e converta para Parquet (tipos inferidos lendo o arquivo inteiro, ZSTD, contagem de linhas conferida):

   ```bash
   python scripts/csv_to_parquet.py
   ```

   O Parquet da cadeia (`SUPPLY_CHAIN_FILE`, padrão `brazil_beef_v2_2_2.parquet`) também fica em `data/processed/parquet/`.

2. Gere o banco DuckDB. Isso também acontece sozinho na primeira consulta e sempre que um Parquet for mais novo que o banco:

   ```bash
   python -m src.cli build-db
   python -m src.cli profile
   ```

### O que o banco contém

| Objeto | Tipo | Conteúdo |
|---|---|---|
| `supply_chain` | tabela | Fluxos da cadeia (4,5 mi linhas, 2011–2023, sem 2018), com tipos corrigidos |
| `flows_by_municipality`, `flows_by_exporter`, `flows_by_destination` | views | Somas por ano e município / exportador / destino |
| `spatial_metrics` | tabela | 13 indicadores territoriais × 4 níveis (país, bioma, UF, município) em formato longo |
| `spatial_metrics_wide` | view | Os mesmos indicadores, uma coluna por métrica |
| `metric_catalog` | tabela | Métrica, unidade, descrição e se pode ser somada entre regiões |
| `facilities` | tabela | Mapa logístico (frigoríficos e outros estabelecimentos com inspeção) |
| `entity_index` | tabela | Nomes distintos, para resolver grafias ("sao felix" → "SAO FELIX DO XINGU") |

As colunas, unidades e regras de interpretação estão em [docs/dicionario_dados.md](docs/dicionario_dados.md). Para mudar o dicionário, edite `src/data_dictionary.py` e rode `python -m src.cli dictionary`. O mesmo conteúdo vai para o prompt do LLM.

Os Parquet são copiados para tabelas, e não lidos por views, para que a conexão do LLM rode sem acesso a arquivos.

### Consultas pela CLI

```bash
python -m src.cli top-municipalities --biome CERRADO --year 2022
python -m src.cli top-exporters --limit 10                  # por grupo; --by-company por empresa
python -m src.cli top-destinations --year 2020
python -m src.cli trend --state PARA
python -m src.cli intensity --biome AMAZONIA
python -m src.cli commitments
python -m src.cli territorial zdc_exported_pct --level state
python -m src.cli find "sao felix" --kind municipality
python -m src.cli sql "SELECT year, SUM(volume_t) FROM flows_by_destination GROUP BY 1 ORDER BY 1"
```

Sem `--year`, os rankings usam o ano mais recente (2023).

## Chatbot

```bash
python -m src.cli ask "Quais grupos exportadores tiveram maior exposição ao desmatamento em 2023?"
python -m src.cli ask "..." --show-context     # mostra cada ferramenta chamada e o resultado
python -m src.cli ask "..." --laws-only        # fluxo antigo, só leis
python -m src.cli serve                        # página em http://127.0.0.1:8000
```

O agente (`src/agent.py`) tem estas ferramentas:

- **Consultas prontas** de `queries.py`: rankings de municípios, exportadores e destinos, série anual, intensidade, compromissos de desmatamento zero e indicadores territoriais.
- **`find_entity`**: confirma a grafia de um nome antes de filtrar.
- **`run_sql`**: um único SELECT no DuckDB, para o que as consultas prontas não cobrem. A conexão é somente leitura e sem acesso a arquivos, com limite de 200 linhas e de 20 segundos (`SQL_MAX_ROWS`, `SQL_TIMEOUT_SECONDS`). Outros comandos (DDL, `COPY`, `ATTACH`, `SET`) e mais de uma consulta por chamada são recusados.
- **`search_laws`**: busca híbrida nas leis.

Cada resultado recebe um rótulo, como `[D1]` para dados e `[L1]` para leis, e a resposta cita esses rótulos. Se o Postgres estiver fora do ar, o agente responde a parte de dados e avisa que não conseguiu consultar as leis.

## Cuidados metodológicos

Estão em `CAVEATS` em `src/data_dictionary.py` e vão no prompt do agente. Os principais:

- **Exposição e emissões usam janela de 5 anos: não some entre anos.** A partir de 2015, a soma da exposição dos fluxos de um ano é igual ao desmatamento nacional atribuído à pecuária naquele ano. Somar anos conta o mesmo desmatamento várias vezes.
- **Cerca de 90% da exposição de cada ano não tem município de origem.** O consumo interno aparece como uma única linha por ano com município `UNKNOWN` (`BR-XXXXXXX`), e parte da exportação também. Os rankings de municípios excluem essa linha e cobrem só a parte rastreada (~8% da exposição em 2023). Para o desmatamento total de uma região, use `spatial_metrics`.
- Na `supply_chain`, a exposição só existe de 2015 em diante. Os zeros de 2011–2014 significam "sem dado".
- O consumo interno aparece como exportador `DOMESTIC PROCESSING AND CONSUMPTION` e destino `BRAZIL`. As consultas de exportação excluem esses registros por padrão.
- Métricas por tonelada e percentuais não se somam: recalcule a partir dos totais.
- `facilities` tem uma linha por estabelecimento e commodity. Para contar estabelecimentos, use `COUNT(DISTINCT facility_id)`.
- Exposição é uma estimativa de associação da cadeia, não prova de ilegalidade nem de responsabilidade direta.

Interpretações marcadas "(confirmar na metodologia)" no dicionário ainda precisam ser verificadas na documentação oficial do Trase.

## Banco vetorial (PostgreSQL + pgvector)

Os documentos de `docs/` ficam no Postgres com pgvector, que oferece índice HNSW persistente, filtros por metadados e busca híbrida (vetor + full-text).

```bash
docker compose up -d --wait          # sobe o Postgres na porta 5433 (PG_PORT)
python -m src.cli init-vector-db     # cria tabelas e índices (idempotente)
python -m src.cli vector-stats
```

Defina `PG_PASSWORD` no `.env` antes de subir o container. `EMBEDDING_DIM` precisa bater com o modelo de embedding. Para trocar de modelo com outra dimensão, recrie as tabelas e regere os embeddings.

- `sql/schema.sql`: tabelas `documents` (um registro por arquivo, com sha256 e modelo de embedding) e `chunks` (texto, páginas, embedding e `tsvector` gerado).
- `src/vector_store.py`: `upsert_document` (substitui o documento e seus chunks numa transação), `semantic_search`, `hybrid_search` (Reciprocal Rank Fusion) e `delete_document`. Recebe vetores prontos e não depende do modelo de embedding.

### Leis ambientais

```bash
python scripts/remove_revoked.py      # remove trechos revogados (docs/leis/original -> docs/leis)
python -m src.cli ingest-laws         # divide por artigo, gera embeddings e indexa (pula leis sem mudança)
python -m src.cli search "multa por desmatar sem autorização" --limit 5
python -m src.cli search "reserva legal" --mode semantic --doc-type law
```

- `src/law_parser.py`: divide cada lei em artigos e guarda a hierarquia (Capítulo/Seção). Artigos acima de 480 tokens viram partes de até 256 tokens, e cada parte repete o caput.
- `src/embeddings.py`: modelo `intfloat/multilingual-e5-small`, com os prefixos `passage:` e `query:`.
- `src/ingest_laws.py`: lê `docs/leis/manifest.json` e grava no Postgres.

Limitação conhecida: perguntas de definição ("o que é área rural consolidada?") podem não trazer o art. 3º no topo quando outros artigos repetem o termo muitas vezes. O próximo passo recomendado é um reranker (cross-encoder) sobre os candidatos.

## Próximos passos

- Indexar a metodologia do Trase no pgvector e dar ao agente uma ferramenta para consultá-la, para confirmar as interpretações marcadas no dicionário.
- Montar um conjunto de avaliação (cerca de 30 perguntas com a resposta numérica conferida no DuckDB) para medir se o agente escolhe a consulta e os filtros certos.
- Reranker para a busca nas leis.

Nunca coloque tokens ou credenciais no Git. O `.env` está ignorado.

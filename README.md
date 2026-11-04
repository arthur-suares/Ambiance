# Trase RAG — projeto inicial

Este protótipo consulta o dataset tabular do Trase usando DuckDB e SQL. Ele é a primeira camada de recuperação para perguntas quantitativas. Não transforma cada linha do CSV em embedding: rankings, somas e tendências devem ser calculados por SQL.

A camada de RAG documental (PDFs, metodologia, relatórios) pode ser adicionada depois com embeddings e um índice vetorial.

## Estrutura

```text
trase-rag/
├── data/
│   ├── raw/                 # CSV original/tratado recebido
│   └── processed/           # banco DuckDB local
├── docs/                    # metodologia, dicionário e relatórios (futuro RAG)
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── queries.py
│   └── cli.py
├── .env.example
├── .gitignore
└── requirements.txt
```

## Instalação

Requer Python 3.10+.

```bash
python -m venv .venv
```

Linux/macOS:
```bash
source .venv/bin/activate
```

Windows PowerShell:
```powershell
.venv\Scripts\Activate.ps1
```

```bash
pip install -r requirements.txt
```

Copie `.env.example` para `.env`. Coloque o CSV em `data/raw/brazil_beef.csv` ou ajuste `TRASE_CSV_PATH`.

## Executar

```bash
python -m src.cli profile
python -m src.cli top-municipalities --limit 10
python -m src.cli top-municipalities --biome "Amazonia" --limit 10
python -m src.cli top-exporters --limit 10
python -m src.cli top-destinations --limit 10
python -m src.cli trend
python -m src.cli intensity --limit 10
python -m src.cli commitments
```

Para forçar a leitura de um CSV atualizado:

```bash
python -m src.cli reload
```

## Trocar o CSV sem reescrever a recuperação

Mantenha o contrato de dados combinado com a equipe: nomes das colunas, tipos, codificação e separador. Substitua o arquivo configurado em `TRASE_CSV_PATH` e execute `reload` e `profile`. As funções de `queries.py` permanecem iguais desde que o esquema continue compatível.

## Consultas incluídas

- Perfil da base, colunas e amostra.
- Municípios por exposição estimada ao desmatamento.
- Exportadores por exposição estimada.
- Países de destino por volume.
- Evolução anual de volume, exposição e emissões líquidas.
- Exposição estimada por tonelada.
- Resumo por indicador de compromisso de desmatamento zero.

## Cuidados metodológicos

As métricas do Trase são estimativas de exposição associada às cadeias, não prova de ilegalidade, responsabilidade direta ou causalidade. A soma por município/exportador depende da granularidade e das regras de alocação dos registros. Valide a interpretação com a metodologia oficial. A razão exposição/volume só deve ser comparada entre registros com escopo e unidades compatíveis.

## Próxima etapa: RAG documental

1. Adicionar documentos em `docs/` (metodologia, dicionário, relatórios).
2. Extrair texto e dividir em chunks.
3. Preservar metadados: arquivo, página, URL, versão.
4. Gerar embeddings e indexar os chunks em um mecanismo vetorial.
5. Criar roteamento: perguntas quantitativas para SQL; perguntas conceituais para busca documental; perguntas mistas para ambos.
6. Conectar um LLM para redigir respostas com evidências e fontes.

A estrutura separa acesso aos dados (`database.py`) das consultas (`queries.py`) para facilitar uma futura migração para tabelas Delta e Databricks SQL.

Nunca coloque tokens ou credenciais no Git. O `.env` está ignorado.

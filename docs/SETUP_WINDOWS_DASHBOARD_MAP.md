# Setup no Windows — branch `feat/dashboard-map`

Roteiro para um assistente (ou pessoa) reproduzir no Windows tudo o que foi feito nesta branch:
chat primeiro → resposta → cartões **Mapa / Gráficos / Painel completo**.

## 0. Pré-requisitos
- Git, Python 3.11+, Docker Desktop (rodando), PowerShell.
- Arquivo `.env` com a chave do OpenRouter (pedir ao grupo; **nunca** commitar).

## 1. Pegar o código
```powershell
git clone https://github.com/arthur-suares/Ambiance.git
cd Ambiance
git fetch origin
git switch feat/dashboard-map
```

## 2. Ambiente Python
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. `.env`
Copie `.env.example` para `.env` e preencha. Pontos obrigatórios:
```
PG_PORT=5433
PG_USER=rag
PG_PASSWORD=<senha escolhida>
PG_DATABASE=trase_rag
EMBEDDING_MODEL=BAAI/bge-m3      # o banco da Release usa 1024 dimensões
EMBEDDING_DIM=1024
OPENROUTER_API_KEY=<chave>
```
Salve o `.env` com quebras de linha **LF** (no VS Code: canto inferior direito, CRLF → LF),
senão o `restore_db.sh` falha.

## 4. Banco (Docker + dados da Release)
O script é bash: rode pelo **Git Bash** (vem com o Git para Windows):
```bash
./scripts/restore_db.sh
```
Ele sobe Postgres+PostGIS (porta 5433) e pgAdmin (http://127.0.0.1:5050), baixa
`agro_full.dump` da Release `data-v1` e restaura: leis (29 docs / 1.893 chunks), municípios,
fluxos Trase, DETER, SEEG e `gold.*`. Conferir no fim a tabela de contagens.

## 5. Arquivos que NÃO vão pelo Git
```powershell
# malha municipal do IBGE (contorno dos municípios no mapa)
mkdir data\raw\onda2 -Force
curl.exe -L "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?intrarregiao=municipio&qualidade=minima&formato=application/vnd.geo+json" -o data\raw\onda2\ibge_malha_municipios_br.geojson

# bases DuckDB (necessárias para "Painel completo" e para o chat /chat)
python -m src.cli build-db
python -m src.cli ingest-soy
```
`web/data/ufs.geojson` (limites dos estados) já vem no Git.

## 6. Modelo de embeddings (baixa ~2 GB uma vez)
```powershell
python -c "from src.embeddings import embed_query; print(len(embed_query('teste')))"   # deve imprimir 1024
```

## 7. Rodar
```powershell
python -m src.web
```
- http://127.0.0.1:8000/ → chat com cartões Mapa / Gráficos / Painel completo
- http://127.0.0.1:8000/chat → chat do pipeline de dashboards (versão anterior)

## 8. Testes
```powershell
python -m pytest -q tests/test_dashboard*.py tests/test_pipeline_*.py tests/test_map_demo.py
```
Esperado: 421 passed, 3 skipped.

## 9. Teste manual
1. "Quais municípios de Goiás tiveram mais desmatamento em 2022?" → aparecem os cartões; Mapa abre em GO.
2. Modo "Só leis": "O que o Código Florestal exige de Reserva Legal na Amazônia Legal?" → sem cartões.
3. Pergunta de soja/carne → "Painel completo" gera o dashboard (~1 min) e embute na tela.

## Pendências conhecidas
- "Painel completo" ainda não foi testado ponta a ponta no navegador (endpoint `/api/dashboard` e testes ok).
- O agente de dashboard usa DuckDB (Trase); números podem diferir da resposta (Postgres/MapBiomas/IBGE/SEEG).
- O texto da IA às vezes diz "o mapa foi ajustado" — ajustar o prompt em `src/agro_chat.py`.

## Arquivos principais
`web/agro_map.html|css|js` (interface), `src/web.py` (rotas, `/api/dashboard`), `src/agro_chat.py`,
`src/dashboard/` (agente de dashboard), `scripts/restore_db.sh`.

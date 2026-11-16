# Arquitetura da soja: medalhão (bronze → silver → gold)

Cobre só os dados da **soja** (Trase v2.6.1) e os alertas do **INPE** ligados a ela. Carne bovina e leis têm outros fluxos.
Dicionário das tabelas gold: [dicionario_gold.md](dicionario_gold.md) (gerado; não duplique colunas aqui).

## 1. Fluxo

```
 FONTES (data/raw/)                    MEDALHÃO (data/lake/)                          AGENTE
 ──────────────────                    ─────────────────────────────────────────      ──────────────────────────
 soy/*.parquet  (Trase)  ──►  BRONZE ──► SILVER ──► GOLD ──┐
 inpe/y*.csv   (DETER AM)        cru      limpo +     tabelas │
 inpe/c*.csv   (DETER CE)     + origem    etiquetado  do       ├─► soy_gold.duckdb ──► ferramentas soy_* e run_soy_sql
 inpe/prodes_pampa*.csv                               catálogo │   (só gold + catálogo     (SOY_USE_GOLD=1)
 soy.duckdb (ingest-soy: métricas territoriais,                 │    + meta_runs + apoio)
             instalações) ── copiadas, SEM a cadeia bruta ──────┘
                 ▲
   portão de qualidade entre cada camada: falhou algo que bloqueia → a próxima camada NÃO é gerada
   e o banco do agente NÃO é trocado
```

Comando único: `python -m src.cli build-medallion [--raw ARQUIVO] [--force] [--no-inpe]` (≈20 s).
Ordem interna: bronze soja → silver soja → gold soja → bronze/silver/gold INPE → registro da carga → banco do agente → dicionário.

## 2. As camadas

| Camada | Onde | O que é | Regra |
|---|---|---|---|
| **Bronze** | `data/lake/bronze/` | Cópia fiel da fonte (soja: 492.629 linhas; DETER Amazônia 150.589; DETER Cerrado 90.199; PRODES Pampa 190), particionada por ano, mais origem: arquivo, SHA-256, versão, data da coleta e da carga | **Imutável.** Se o SHA-256 não mudou, não é refeita. |
| **Silver** | `data/lake/silver/` | Tipos corrigidos e **etiquetas** (`unknown_origin`, `domestic_destination`, `unknown_exporter`, `fob_zero`, `environmental_data_available`, `is_analytic`...), colunas derivadas, `municipality_id` | **Nada é apagado sem justificativa**; problema vira coluna. Mesmas linhas da bronze (exceto duplicata exata). |
| **Gold** | `data/lake/gold/` | 11 tabelas do catálogo (`src/medallion/catalog.py`), sempre **por ano** e só com a base analítica (origem conhecida, destino fora do Brasil, 2013 em diante) | Soma de volume, FOB e exposição **fecha com a silver**. Sem total que junte anos. |

## 3. O que cada problema anterior virou

| Problema | Solução |
|---|---|
| Medalhão fora do projeto, dois jeitos de carregar a soja | Pacote `src/medallion/`, caminhos em `src/config.py` (`MEDALLION_DIR`, `SOY_RAW_PARQUET`, `INPE_RAW_DIR`, `SOY_GOLD_DUCKDB_PATH`). A cadeia (fluxos) é carregada **só** pelo medalhão. O `ingest-soy` continua carregando os demais datasets (métricas territoriais, instalações). |
| Agente via tudo | Banco do agente (`soy_gold.duckdb`) **sem `soy_supply_chain`**. Com `SOY_USE_GOLD=1`, ferramentas e `run_soy_sql` só alcançam esse arquivo. |
| Nomes inconsistentes | Gold em inglês e com os mesmos nomes que as ferramentas já devolvem (`volume_tonnes`, `exposure_ha`). |
| Chaves de município diferentes | `municipality_id` = IBGE de 7 dígitos em **todas** as tabelas; o código do Trase fica em `trase_municipality_id`. O município fictício do Trase (`BR-XXXXXXX`, origem desconhecida) vira nulo. |
| Dicionário duplicado | `catalog.py` é a fonte única: gera contrato, `gold_catalog` (no banco), prompt do agente e `dicionario_gold.md`. |
| Sem rastreabilidade | Cada carga grava `run_id`, commit, SHA-256, contagens e nº de checagens em `data/lake/_runs/` e na tabela `meta_runs`. A resposta da web (`soy_data`) e o `config.json` de cada rodada de avaliação (`codigo`, `dados_soja`) trazem isso. |

## 4. Portões de qualidade (107 checagens na última carga, 0 falhas bloqueantes)

Bronze (19) · Silver (24) · Gold (64). Exemplos que **bloqueiam**: linhas e volume da silver = bronze; FOB, volume e exposição de cada gold = base analítica da silver; chave (ano, município) única; participações somam 100% por ano; `municipality_id` com 7 dígitos (e nulo só onde a origem é desconhecida); colunas e tipos de cada tabela gold = catálogo (contrato); alertas INPE com área ≥ 0 e ano coerente com o arquivo. Exemplos que **só avisam**: nulos de exposição antes de 2013 (estruturais), % de alertas do Cerrado ligados ao Trase, `FID` repetido do INPE, alertas de área 0.
Resultados em `data/lake/_logs/quality_<camada>.json`.

## 5. Regras que o desenho garante

1. **Exposição e CO₂ são janela de 5 anos: nunca somam entre anos.** Toda gold tem `year`; não há coluna de exposição acumulada (o cruzamento INPE traz `exposure_2022_ha` e `exposed_pct_of_land`, que é razão ponderada).
2. O que ficou fora da base analítica **continua visível** em `soy_national_year` (hoje: 26,4% doméstico e 11,2% origem desconhecida do volume total 2004–2022).
3. A gold é **determinística**: mesma silver → mesma gold (inclui as anomalias, semente fixa).
4. Falha de um portão **nunca** troca o banco do agente (troca atômica só no fim).

## 6. Como o agente usa

- `soy_top_municipalities`, `soy_top_exporters` (novo parâmetro `level`: `company` padrão ou `group`), `soy_top_destinations`, `soy_yearly_trend` e `soy_deforestation_by_biome` leem a gold (`SELECT` direto, sem `SUM`/`TRY_CAST` sobre dado bruto).
- O prompt das tabelas vem de `gold_catalog` no próprio banco, mais `SOY_RULES_GOLD` (`src/agent.py`) e a linha "Origem dos dados: … carga …".
- Sem `SOY_USE_GOLD` (padrão) o comportamento é o de antes, lendo `soy.duckdb`.

## 7. Variáveis de ambiente

| Variável | Padrão | Para quê |
|---|---|---|
| `SOY_RAW_PARQUET` | `data/raw/soy/brazil_soy_v2_6_1_composite.parquet` | fonte da soja |
| `INPE_RAW_DIR` | `data/raw/inpe` | CSVs do INPE (`y20*.csv`, `c20*.csv`, `prodes_pampa_municipios.csv`) |
| `MEDALLION_DIR` | `data/lake` | bronze, silver, gold e logs |
| `SOY_GOLD_DUCKDB_PATH` | `data/processed/soy/soy_gold.duckdb` | banco do agente |
| `SOY_USE_GOLD` | `0` | liga o agente na gold |

## 8. Mudanças de comportamento (importante para o time)

- **Rankings e totais mudam** com `SOY_USE_GOLD=1`: a gold exclui doméstico, origem desconhecida e anos antes de 2013, e a ferramenta antiga incluía tudo. **O gabarito de avaliação foi gerado sobre a base bruta e precisa ser reconciliado** (decidir a definição correta e regerar o que mudar) antes de comparar métricas.
- `soy_top_exporters` agora tem `level`; o padrão (`company`) preserva a granularidade antiga (empresa).
- `soy_yearly_trend` passa a trazer a exposição da base analítica (nula antes de 2013).

## 9. Limites conhecidos

- A **coleta do INPE é manual** (os CSVs foram baixados do TerraBrasilis e ficam em `data/raw/inpe`); não há script de coleta no repositório.
- O **Cerrado casa com o Trase por nome + UF** (82,0% dos alertas, 87,3% da área); o resto são municípios sem soja no Trase e ficam marcados (`municipality_matched = false`).
- O PRODES Pampa cobre 2021–2024 e o DETER 2021–2026 (2026 parcial); são sinais diferentes e não se somam.
- `scikit-learn` é necessário para `is_anomaly` (sem ele a coluna fica falsa e a carga avisa).
- A carga refaz tudo em ≈20 s; não há carga incremental (suficiente para 188 MB).
- O prompt do agente em modo gold tem ≈3,6 mil tokens para a soja (o dicionário completo); pode ser enxugado se o custo importar.
- Ainda **não foi medido** se a gold melhora as respostas do agente; falta rodar a avaliação nos dois modos (`SOY_USE_GOLD=0` e `1`).

## 10. Checklist antes de enviar para a branch

1. Rodar `python -m pytest tests/test_medallion_soy.py` (19 testes) e a suíte completa.
2. Decidir o gabarito (item 8) e a granularidade do exportador (`company` × `group`).
3. Combinar com quem cuida de carne e leis o uso de `src/medallion/core.py` (portões, registro) para as outras fontes.
4. Confirmar que `data/raw/` e `data/lake/` não vão para o Git (já estão no `.gitignore`).

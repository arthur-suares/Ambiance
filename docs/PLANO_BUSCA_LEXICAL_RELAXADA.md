# Plano de implementacao: busca lexical relaxada

## Objetivo

Fazer com que a busca por palavras-chave participe efetivamente da busca
hibrida, sem aceitar chunks que nao contenham nenhum termo da consulta.

A primeira versao deve ser deterministica, sem LLM e sem IDF.

## Escopo

Implementar:

1. Extracao deterministica de termos em Python.
2. Remocao de stopwords genericas.
3. Preservacao de ancoras juridicas.
4. Consulta lexical com `OR`.
5. Manutencao do filtro `WHERE c.tsv @@ q`.
6. Validacao com testes unitarios e o diagnostico existente.

Nao implementar nesta etapa:

- IDF;
- reranker;
- reescrita de consulta por LLM;
- troca do modelo de embeddings;
- alteracao do indice HNSW;
- alteracao da formula RRF.

## Comportamento desejado

Para a pergunta:

```text
Qual percentual de reserva legal um imovel rural na Amazonia Legal deve manter?
```

A consulta lexical deve preservar termos informativos e gerar algo equivalente
a:

```text
percentual OR reserva OR legal OR imovel OR rural OR "Amazonia Legal"
```

O formato exato pode variar conforme a implementacao e o parser do PostgreSQL,
mas a consulta nao deve exigir que todos os termos aparecam no mesmo chunk.

## Arquivos provaveis

- `src/vector_store.py`: integrar a consulta relaxada na funcao `hybrid_search`.
- `src/fts_query.py`: modulo opcional recomendado para o construtor de consulta.
- `tests/test_fts_query.py`: testes unitarios do construtor.
- `eval/diagnostico_busca.py`: somente se for necessario tornar a avaliacao
  consistente com a nova consulta.

## Requisitos funcionais

### 1. Criar um construtor de consulta

Criar uma funcao com responsabilidade clara, por exemplo:

```python
def build_relaxed_fts_query(query_text: str) -> str:
    ...
```

Ela deve:

- normalizar espacos;
- remover pontuacao irrelevante;
- separar palavras e expressoes;
- remover stopwords genericas;
- preservar termos juridicos;
- limitar a consulta a uma quantidade razoavel de termos;
- retornar uma consulta lexical com `OR`.

### 2. Stopwords iniciais

Comecar com uma lista pequena e explicita de palavras funcionais, por exemplo:

```text
qual, quais, como, quando, onde,
um, uma, uns, umas,
de, da, do, das, dos,
em, na, no, nas, nos,
para, por, e, ou,
deve, devem, pode, podem
```

Nao remover inicialmente termos juridicos ou do dominio, como:

```text
multa, reserva, legal, autorizacao,
desmatamento, licenciamento, infracao
```

### 3. Ancoras juridicas

Preservar, quando presentes:

- `Art. 12` e `artigo 12`;
- `Lei 12.651/2012`;
- `Decreto 6.514/2008`;
- percentuais como `80%`;
- siglas como `APP` e `CAR`;
- expressoes juridicas relevantes, como `reserva legal`,
  `corte raso` e `Amazônia Legal`.

Expressoes de varias palavras devem ser tratadas como frases quando o formato
do parser permitir.

### 4. Integracao com o PostgreSQL

Manter a estrutura essencial da busca lexical:

```sql
WHERE c.tsv @@ q
ORDER BY text_rank DESC
```

Nao remover `c.tsv @@ q`.

O `q` deve ser gerado a partir da consulta relaxada. `ts_rank_cd` continua
responsavel por ordenar os candidatos:

```sql
ts_rank_cd(c.tsv, q) AS text_rank
```

A implementacao deve continuar usando parametros do driver para valores
externos. Nao concatenar texto de usuario diretamente em SQL sem sanitizacao.

### 5. RRF

Manter a fusao atual:

```text
1 / (RRF_K + semantic_rank)
+ 1 / (RRF_K + keyword_rank)
```

Nao misturar diretamente `ts_rank_cd` com distancia vetorial. O canal lexical
continua contribuindo pela posicao (`keyword_rank`).

## Casos de borda

Tratar explicitamente:

1. Consulta vazia apos a remocao de stopwords.
2. Consulta composta apenas por numeros ou pontuacao.
3. Termos repetidos.
4. Percentuais e numeros de artigos.
5. Acentos e cedilha.
6. Siglas em maiusculas.
7. Termos com hifen.
8. Consulta muito longa.

Se nao houver termos validos, a busca deve falhar de forma explicita ou usar o
comportamento padrao documentado pelo projeto. Nao retornar um ranking lexical
artificial com score zero.

## Testes unitarios

Adicionar testes para:

1. Remocao de stopwords.
2. Preservacao de `Art. 12`.
3. Preservacao de `Lei 12.651/2012`.
4. Preservacao de `80%`.
5. Preservacao de `reserva legal`.
6. Preservacao de `Amazônia Legal`.
7. Geracao de consulta com `OR`.
8. Remocao de duplicatas.
9. Limite de termos.
10. Consulta sem termos validos.

Os testes devem verificar o comportamento do construtor, nao detalhes
irrelevantes de formatacao.

## Validacao da recuperacao

Executar o diagnostico existente antes e depois da mudanca:

```bash
python -m eval.diagnostico_busca ^
  eval/resultados/rodada_20_perguntas_v3 ^
  eval/resultados/rodada_20_perguntas_v3/diagnostico_busca_relaxada.json
```

No PowerShell, pode ser necessario usar uma unica linha ou substituir `^` por
acento grave conforme o shell.

Comparar:

- quantidade de consultas com `keyword_rank` diferente de `null`;
- `direta_kw_matches`;
- posicao do primeiro artigo essencial;
- Hit@5;
- MRR;
- tempo de consulta;
- quantidade de candidatos retornados pelo canal lexical.

## Criterios de aceitacao

A implementacao sera considerada correta se:

- a busca lexical produzir candidatos em mais consultas relevantes;
- nenhum chunk sem correspondencia lexical entrar pelo canal de palavras-chave;
- a busca semantica permanecer inalterada;
- o `WHERE c.tsv @@ q` permanecer ativo;
- o RRF continuar recebendo ranks, e nao scores de escalas diferentes;
- os testes unitarios passarem;
- o diagnostico mostrar melhora ou nenhuma regressao relevante em Hit@5 e MRR;
- nao houver dependencia de LLM.

## Observacao para a implementacao

A mudanca deve ser cirurgica. Primeiro implementar a consulta relaxada com
stopwords e ancoras. Nao adicionar IDF, reranking ou reescrita por LLM na mesma
alteracao. Essas tecnicas devem ser avaliadas em uma etapa posterior, com uma
comparacao isolada.

## Resultado da implementacao (2026-11-13)

Implementado: `src/fts_query.py` (construtor), integracao em `hybrid_search`
(`relaxed_lexical=True` por padrao; `False` volta ao modo AND), `tests/test_fts_query.py`
(12 testes; suite com 31 testes passando) e contagem de candidatos lexicais e tempo em
`eval/diagnostico_busca.py` (terceiro argumento `estrito` roda o modo antigo).

Decisoes: stopwords do plano mais artigos, `que`, `com`, `se` e auxiliares; numeros soltos (anos,
quantidades) sao descartados e so contam dentro de ancoras (`art. N`, `12.651/2012`, `80%`); expressoes
entram como frase e tambem como palavras; no maximo 12 termos; acentos ficam como digitados (o indice nao
remove acentos). Consulta sem termo valido gera `""`, o `@@` nao casa com nada e a busca fica so
semantica. O SQL nao mudou: `WHERE c.tsv @@ q`, `ts_rank_cd` e RRF por posicao.

Diagnostico (16 perguntas com artigo; arquivos `diagnostico_busca_estrito.json` e
`diagnostico_busca_relaxada.json` em `eval/resultados/rodada_20_perguntas_v3/`):

| Medida | Estrito (antes) | Relaxado (depois) |
|---|---|---|
| Consultas diretas com chunks que casam (`direta_kw_matches` > 0) | 1 de 16 | 16 de 16 |
| Candidatos lexicais no top-40 da busca direta (media) | 0,06 | 28,7 |
| Hit@5, busca direta, geral (mista) | 0,62 (0,45) | 0,69 (0,55) |
| MRR, busca direta, geral (lei / mista) | 0,543 (1,00 / 0,336) | 0,512 (0,85 / 0,359) |
| MRR, so a metade de lei das mistas | 0,604 | 0,495 |
| Artigo essencial achado em alguma busca do agente (consultas reexecutadas) | 15 de 16 | 11 de 16 |
| Tempo mediano da consulta (ms) | 41 | 45 |

Criterios de aceitacao: cumpridos (canal lexical com candidatos, `WHERE c.tsv @@ q` ativo, semantica
inalterada, RRF por posicao, testes passando, sem LLM). **Nao cumprido: "nenhuma regressao relevante em
Hit@5 e MRR".** O Hit@5 subiu, mas o MRR caiu (L07 foi de 1o para 4o) e, nas consultas que o agente fez, o
artigo essencial deixou de aparecer em L04, M03, M08 e M10.

Causa: com OR sobre termos comuns (`reserva`, `legal`, `multa`), o `ts_rank_cd` favorece chunks que repetem
essas palavras (arts. 14, 15 e 18 do Codigo Florestal). Eles ocupam o topo do canal lexical, que agora tem
40 candidatos com o mesmo peso do canal semantico no RRF, e passam na frente do artigo certo, que cita o
termo uma vez (ex.: L04, art. 52: 1o no semantico, fora dos 40 lexicais). E o problema que o IDF resolveria,
mas o plano o deixa para uma etapa posterior com comparacao isolada.

## Etapa seguinte: IDF (2026-11-13)

O parametro `relaxed_lexical` virou `lexical_mode` em `hybrid_search`: `"strict"` (modo antigo, AND),
`"relaxed"` (OR, ordem por `ts_rank_cd`) e `"idf"` (**novo padrao**).

Como o IDF funciona (`src/fts_query.py` e `src/vector_store.py`):

1. `extract_terms` gera os termos da pergunta (ancoras, expressoes e palavras, sem limite).
2. Para cada termo, uma consulta ao proprio indice conta em quantos chunks ele aparece (`df`). O total de
   chunks respeita o filtro `doc_type`. O peso e o IDF do BM25: `ln(1 + (N - df + 0.5) / (df + 0.5))`.
   Termo com `df = 0` sai. Se passar de 12 termos, ficam os de maior IDF.
3. O canal lexical continua com `WHERE c.tsv @@ q` (OR dos termos). Os candidatos sao ordenados pela **soma
   do IDF dos termos que cada chunk contem**, e o `ts_rank_cd` so desempata. Assim "reserva" e "legal",
   que aparecem em muitos chunks, pesam pouco, e "corte raso" ou "art 52" pesam muito.
4. A semantica, o HNSW e o RRF (que recebe posicoes) nao mudaram. Sem LLM.

Decisao de desenho: o IDF pondera a ordem do canal lexical, em vez de apenas descartar termos comuns. Foi
escolhido antes de medir e avaliado uma vez, sem ajustar parametros a este conjunto de perguntas.

Diagnostico (mesmas 16 perguntas e mesmas consultas do agente; arquivos `diagnostico_busca_estrito.json`,
`diagnostico_busca_relaxada.json` e `diagnostico_busca_idf.json` em `eval/resultados/rodada_20_perguntas_v3/`):

| Medida | Estrito (antigo) | Relaxado (OR) | **IDF** |
|---|---|---|---|
| Consultas diretas com chunks que casam | 1 de 16 | 16 de 16 | 16 de 16 |
| Candidatos lexicais no top-40 da busca direta (media) | 0,1 | 28,7 | 28,2 |
| Hit@5, busca direta: geral (mista) | 0,62 (0,45) | 0,69 (0,55) | **0,75 (0,64)** |
| Hit@10, busca direta: geral | 0,69 | 0,69 | 0,75 |
| MRR, busca direta: geral | 0,543 | 0,512 | **0,611** |
| MRR, busca direta: lei / mista | 1,00 / 0,336 | 0,85 / 0,359 | **1,00 / 0,435** |
| Metade de lei das mistas: Hit@5 / Hit@10 / MRR | 0,73 / 0,82 / 0,604 | 0,73 / 0,82 / 0,495 | **0,82 / 1,00 / 0,613** |
| Artigo essencial achado em alguma busca do agente | 15 de 16 | 11 de 16 | **16 de 16** |
| Artigo essencial na 1a busca do agente | 14 de 16 | 11 de 16 | 15 de 16 |
| Tempo mediano da consulta (ms) | 43 | 40 | 58 |

Criterios de aceitacao: todos cumpridos, incluindo "nenhuma regressao relevante em Hit@5 e MRR". Hit@5 e MRR
sobem em relacao ao modo antigo e a lei fica em 1,00/1,00. Nenhuma pergunta perdeu o artigo essencial
(L04, M03, M08 e M10, que o modo relaxado perdera nas buscas do agente, voltam).

Mudancas de posicao que merecem atencao (busca do agente, 1a busca): L07 do 1o para o 2o, M08 do 1o para o 3o
e M11 do 1o para o 2o (o artigo continua no top-6 em todas). Na busca direta, o M10 passa de "fora do top-40"
para o 5o lugar e o M03 de "fora do top-40" para o 20o.

Custos e limites: +15 ms por consulta (uma consulta extra ao indice para contar o `df` e a soma de IDF por
chunk candidato); o IDF e recalculado a cada busca, entao acompanha o indice sem cache. M01, M03 e M05 seguem
fora do top-10 na busca direta (a pergunta mista inteira ainda dilui o canal semantico); o IDF melhora
o canal lexical, nao o semantico. Nao foi rodada a avaliacao completa com o agente (so a busca).

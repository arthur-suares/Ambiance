# Plano: avaliação do RAG com 20 testes

## Contexto
O sistema de RAG (soja, carne bovina e leis ambientais) precisa de uma avaliação quantitativa para a entrega. Já existe um conjunto de 36 perguntas com gabarito (`eval/perguntas.jsonl`, gerado por `eval/build_gold.py`). O objetivo é rodar **20 testes** — 5 de lei, 2 de carne bovina, 2 de soja e 11 mistas — e medir **Hit Rate@k, Recall@k, MRR, Faithfulness, Context Precision, Context Recall, ROUGE-L e BLEU**, gerando um relatório com resultados por tipo de pergunta.

## Decisões (alinhadas com o usuário)
- **Hit Rate@k, Recall@k, MRR: só nas leis** (perguntas de lei + parte de lei das mistas → 16 perguntas). Em soja/carne bovina a recuperação é SQL, sem lista ranqueada; lá a recuperação é medida por Context Precision/Recall e por um indicador auxiliar "valor recuperado" (o número do gabarito apareceu no resultado de alguma ferramenta?).
- **Onde medir as métricas de ranking:** chamando a busca híbrida direto (`src/rag.py:retrieve`) com a **pergunta original** e k = 1, 3, 5, 10. Determinístico e reprodutível.
- **Faithfulness, Context Precision, Context Recall:** no fluxo completo do agente (`src/agent.py:ask`), nas 20 perguntas.
- **Juiz:** implementação própria seguindo as definições do RAGAS, usando o cliente já existente (`src/rag.py:get_client`) e **o mesmo modelo do sistema (claude-haiku-5.5)**. O viés de autoavaliação entra como limitação no relatório.
- **ROUGE-L e BLEU** (semelhança de texto entre a resposta do agente e uma referência), nas 20 perguntas:
  - **Duas referências, com papéis separados (decidido em 2026-11-13):**
    - `resposta_esperada` (curta): lista de fatos-chave. Só o Context Recall (juiz) a usa como referência principal, para a nota não cair por causa de ressalvas que não dependem da busca. ROUGE-L, BLEU e cosseno também são calculados contra ela, só para comparação.
    - `resposta_referencia` (longa): escrita **na estrutura do prompt do agente** (`src/agent.py`, "Como responder"): resposta curta primeiro; depois os dados `[D]` e as leis `[L]` com ano, filtros e unidade, citando a lei e o artigo na primeira citação; no fim "Limites da resposta" (exposição não prova ilegalidade, o que seria necessário para verificar um caso). É a referência principal de ROUGE-L, BLEU e cosseno. Tem de 50 a 253 palavras (as respostas do agente têm de 81 a 417).
    - As duas são escritas só com o gabarito (SQL e texto dos artigos), **sem copiar as respostas do agente**. Devem ser revisadas pela equipe. O relatório mostra as duas.
  - **Cosseno** (decidido em 2026-11-13): similaridade de cosseno entre os embeddings do e5-small (o modelo do projeto, com o prefixo `query: `) da resposta e da referência, sobre o texto limpo (sem tabelas, rótulos e markdown; com acentos e números originais). Limites: o modelo lê só 512 tokens (o relatório diz quantas respostas foram cortadas) e dá notas altas até para textos sem relação. Por isso o relatório traz uma **linha de base**: o cosseno médio de cada resposta com as referências das outras perguntas. A nota só vale pela diferença para essa linha.
  - **ROUGE-L:** precisão, recall e F1 (F1 como número principal).
  - **BLEU:** os dois cálculos. **BLEU de corpus** por tipo e geral como número principal (soma as contagens de n-gramas de todas as respostas do grupo; não precisa de suavização; é a definição original) e **BLEU por pergunta** com suavização (padrão do sacrebleu, `exp`), só para achar os piores casos. N = 4, pesos iguais (wₙ = 1/4), com penalidade de tamanho (BP).
  - **Normalização antes de comparar** (resposta e referências): remover rótulos `[D1]`/`[L1]`, markdown e tabelas; minúsculas; tirar acentos ("São Félix" = "Sao Felix"); padronizar números ("36.100" e "36,1 mil" viram o mesmo token; o número é convertido para o valor completo e arredondado a 3 algarismos significativos, para que "277.582,68" e "277,6 mil" também coincidam).
  - Limitação a registrar: são métricas de sobreposição de palavras; uma resposta correta com outra redação recebe nota baixa. Por isso servem de complemento ao juiz, não de substituto.
- **Fora do escopo (F01–F03) ficam de fora** dos 20. São as perguntas que testam recusa (café em MG, projeção para 2030, "a JBS cometeu crime?") e não têm contexto de referência para Context Recall. Podem ser rodadas à parte só para medir recusa.

## Apresentação dos resultados (alinhado com o usuário)
- **Agregação: só média simples** nas 20 perguntas (e nas perguntas de cada tipo). Sem números globais somados, sem margem de erro e sem taxa de acerto de ponta a ponta. A exceção é o BLEU de corpus, que já foi decidido.
- **Painel no topo do relatório**, com um número por métrica e três blocos por etapa do pipeline:

| Etapa | Pergunta que responde | Métricas |
|---|---|---|
| **Recuperação** | O sistema buscou o que precisava? | Hit@5, MRR, Recall@5, Context Recall, Context Precision |
| **Geração** | A resposta está certa e apoiada no que foi buscado? | Faithfulness, acerto de valores, ROUGE-L F1, BLEU de corpus, cosseno |
| **Custo** | Quanto custa responder? | Latência média, tokens médios por pergunta |

  Abaixo do painel: a mesma tabela por tipo (lei / carne / soja / mista), a tabela com todas as métricas de cada pergunta e os piores casos.

## Rastreabilidade (alinhado com o usuário)
Cada teste deve deixar visível o resultado de **cada etapa**, para que qualquer nota possa ser conferida até a origem. Por pergunta, a trilha registra:

1. **Pergunta e gabarito:** tipo; resposta esperada (curta); referência longa; valores esperados com tolerância; artigos com nível (essencial/complementar); SQL do gabarito.
2. **Retrieval direto (busca híbrida com a pergunta original, top-10):** para cada posição, lei, artigo, parte, score RRF, posição na busca semântica e na busca por palavras-chave, e se é relevante (essencial / complementar / não), com um trecho do texto. Em seguida Hit@1/3/5/10, Recall@1/3/5/10 e MRR, com a conta explicada (ex.: "primeiro essencial na posição 2 → MRR = 1/2 = 0,5").
3. **Execução do agente, na ordem das chamadas:** rótulo (`[D1]`, `[L1]`…), ferramenta, argumentos que o LLM escolheu (texto de busca e k em `search_laws`; SQL em `run_sql`/`run_soy_sql`; ano/filtros nas demais), resultado devolvido (tabela ou trechos de lei com lei/artigo/parte/score), nº de linhas, tempo e se deu erro.
4. **Resposta do LLM:** texto final completo, tokens de entrada e saída, tempo total.
5. **Checagens sem juiz:** para cada valor esperado, se aparece no contexto (em qual `[D]`/`[L]`) e na resposta (número lido e erro relativo).
6. **Juiz:** para cada métrica, a lista de afirmações (ou itens de contexto), o veredito sim/não e a justificativa de cada uma, e a fórmula com os números (ex.: "4 de 5 afirmações sustentadas → 0,8").
7. **Texto (ROUGE-L / BLEU):** resposta e referências já normalizadas, tamanho da LCS, P/R/F1, p1–p4, BP e BLEU, para cada uma das duas referências.

**Arquivos de cada rodada** (`eval/resultados/<data-hora>/`):
- `config.json`: data, modelo do agente e do juiz, modelo de embeddings, k, RRF_K, prompts do juiz, versões das bibliotecas, lista de perguntas.
- `detalhes.jsonl`: tudo acima, uma linha por pergunta, **sem truncar** (inclui as saídas completas das ferramentas e as respostas brutas do juiz).
- `perguntas/<ID>.md`: a trilha da pergunta em formato legível, seção por seção (1 a 7). Trechos longos aparecem resumidos, com a íntegra no `detalhes.jsonl`.
- `relatorio.md`: painel, tabela por tipo, tabela por pergunta com link para cada `perguntas/<ID>.md`, piores casos e limitações.

## Seleção das 20 perguntas
- **Lei (5):** L01 reserva legal, L02 APP de rio, L04 multa corte raso, L06 pena APP (Lei 9.605), L07 categorias SNUC.
- **Carne bovina (2):** C01 grupo exportador com maior exposição (2023), C04 tendência 2015→2023.
- **Soja (2):** S01 município com maior exposição (2022), S05 maior estado produtor (territorial).
- **Mistas (11):** M01–M05 (já existem) + 6 novas, já criadas em `build_gold.py` (gabarito por SQL e pelo texto do artigo; ver `eval/gabarito.md`):

| Nº | Pergunta | Dados | Artigo esperado |
|---|---|---|---|
| M06 | Qual estado tem a maior área de pastagem e quanto de reserva legal um imóvel em área de floresta na Amazônia Legal precisa manter? | `spatial_metrics` (pasture_area_ha) | Código Florestal, art. 12 |
| M07 | Que percentual da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero em 2022, e o que é o CAR? | `soy_spatial_metrics` (zdc_exported_pct) | Código Florestal, art. 29 |
| M08 | Qual município teve a maior exposição ao desmatamento na carne bovina em 2023, e qual a pena para quem destrói floresta de preservação permanente? | `flows_by_municipality` | Lei 9.605, art. 38 |
| M09 | Compare a exposição ao desmatamento da soja e da carne bovina na Amazônia em 2022, e qual a multa por desmatar a corte raso fora da reserva legal? | soja + carne por bioma | Decreto 6.514, art. 52 |
| M10 | Qual o maior grupo exportador de soja em 2022 e sua exposição ao desmatamento? Que multa se aplica a quem desmata dentro da reserva legal? | `soy_supply_chain` (exporter_group) | Decreto 6.514, art. 51 |
| M11 | Qual estado tem a maior capacidade de processamento de soja, e que atividades dependem de licenciamento ambiental prévio? | `soy_facilities` | Lei 6.938 (PNMA), art. 10 |

Campo `no_teste: true` nessas 20 (já aplicado: o JSONL tem 36 perguntas, 20 marcadas para o teste).

## Definição das métricas
**Unidade de relevância nas leis = artigo** (lei + nº do artigo; qualquer parte/chunk dele conta). Um artigo recuperado em várias partes conta uma vez, na posição da primeira parte.

**Quem define o que é relevante:** anotação manual no campo `artigos` do gabarito, feita lendo o texto dos artigos indexados (ex.: L04 → Decreto 6.514, art. 52, que diz "Multa de R$ 1.000,00 por hectare"). Deve ser revisada pela equipe antes da rodada final. A comparação é automática: cada chunk recuperado já tem lei e artigo nos metadados; é relevante se ambos batem com o gabarito. Nas mistas, a busca direta usa a pergunta completa e só a parte de lei entra nessas métricas.

**Dois níveis de relevância** (campo `nivel` em cada item de `artigos`):
- **Essencial:** sem ele não dá para responder à pergunta. É o conjunto usado por **Hit Rate@k e MRR**.
- **Complementar:** ajuda ou dá contexto (ex.: uma definição), mas não responde sozinho. É usado só no **Recall@k**, junto com os essenciais.

Motivo: se houvesse um nível só, o Recall daria o mesmo valor que o Hit (com 1 artigo por pergunta). E se os complementares contassem no Hit/MRR, uma busca que trouxesse só a definição (art. 3) sem os percentuais (art. 12) teria nota máxima mesmo falhando no que importa. Nas perguntas sem complementar, Recall = Hit.

Anotação **conferida no texto indexado em 2026-11-11** (todos os artigos abaixo existem nos chunks e dizem o que o motivo afirma). Regras: fechar o gabarito **antes** de olhar os resultados da busca, para não inflar as notas; não marcar todo artigo que só menciona o tema. Fica de fora de propósito: Dec. 6.514 art. 43 no L06 (é multa administrativa por dano em APP, e a pergunta pede a pena criminal).

| Nº | Essencial | Complementar | Motivo |
|---|---|---|---|
| L01 | CF art. 12 | CF art. 3 | O art. 3 define Amazônia Legal e reserva legal |
| L02 | CF art. 4 | CF art. 3 | O art. 3 define APP |
| L04 | Dec. 6.514 art. 52 | — | O art. 51 (dentro da RL) seria a resposta errada |
| L06 | Lei 9.605 art. 38 | Lei 9.605 art. 39 | O art. 39 trata de cortar árvores em APP (mesma pena) |
| L07 | SNUC art. 8 | SNUC art. 7 | O art. 7 divide as UCs nos dois grupos |
| M01, M02, M06 | CF art. 12 | CF art. 3 | Mesma lógica do L01 |
| M03, M10 | Dec. 6.514 art. 51 | — | |
| M04 | Lei 11.428 art. 11 | Lei 11.428 art. 14 | O art. 14 trata das exceções (utilidade pública e interesse social) |
| M05 | PNMC art. 12 | — | |
| M07 | CF art. 29 | — | |
| M08 | Lei 9.605 art. 38 | Lei 9.605 art. 39 | |
| M09 | Dec. 6.514 art. 52 | — | |
| M11 | PNMA art. 10 | — | |

**Exemplo (L01).** Essencial = {art. 12}, complementar = {art. 3}. A busca devolve: 1º art. 13, 2º art. 12, 3º art. 68, 4º art. 59, 5º art. 3.

| Métrica | Conjunto | Cálculo | Nota |
|---|---|---|---|
| Hit@3 | {12} | art. 12 no top-3? sim | 1 |
| MRR | {12} | 1ª posição relevante = 2 → 1/2 | 0,5 |
| Recall@3 | {12, 3} | só o 12 no top-3 → 1/2 | 0,5 |
| Recall@5 | {12, 3} | os dois no top-5 → 2/2 | 1 |

Contraexemplo: se a busca devolvesse 1º art. 3, 2º art. 13… sem o art. 12, então Hit = 0 e MRR = 0 (correto: os percentuais não vieram). Com um nível só, daria Hit = 1 e MRR = 1.

Exemplo (L04, só essencial): a busca devolve art. 51 (1º), art. 52 (2º), art. 53 (3º) → Hit@1 = 0, Hit@3 = 1, Recall@3 = 1, MRR = 0,5.
- **Hit Rate@k:** 1 se pelo menos um artigo **essencial** está entre os k primeiros; média nas perguntas.
- **Recall@k:** artigos (essenciais + complementares) encontrados no top-k ÷ total desses artigos; média.
- **MRR:** 1/posição do primeiro artigo **essencial** (0 se não aparecer no top-10); média.
- **Faithfulness (juiz):** juiz quebra a resposta em afirmações; fração sustentada pelo contexto recuperado (resultados das ferramentas: tabelas `[D]` + trechos `[L]`).
- **Context Precision (juiz):** juiz marca cada item de contexto (cada chamada de ferramenta / cada chunk de lei, na ordem) como útil ou não para chegar ao gabarito; média da precisão@i nas posições úteis (fórmula do RAGAS).
- **Context Recall (juiz):** juiz quebra o `resposta_esperada` (a referência curta, que contém só os fatos que a resposta precisa ter) em afirmações; fração que pode ser atribuída ao contexto recuperado.
- **ROUGE-L:** com LCS = maior subsequência comum de palavras (em ordem, não precisa ser contígua) entre resposta e referência: precisão = LCS ÷ nº de palavras da resposta; recall = LCS ÷ nº de palavras da referência; F1 = 2PR/(P+R). Ex.: referência "a multa e de r$ 1000 por hectare" (8), resposta "a multa prevista e de r$ 1000 por hectare ou fracao" (11), LCS = 8 → P = 0,73, R = 1, F1 = 0,84.
- **BLEU:** BLEU = BP · exp(Σ wₙ·log pₙ) = BP · (p1·p2·p3·p4)^(1/4), onde pₙ = sequências de n palavras da resposta presentes na referência (com recorte: cada sequência conta no máximo quantas vezes aparece na referência) ÷ total de sequências de n palavras da resposta; BP = 1 se a resposta é maior que a referência, senão e^(1 − r/c). Mesmo exemplo: p = 0,73 / 0,60 / 0,44 / 0,375, BP = 1 → BLEU = 0,52. No corpus, somam-se acertos, totais e tamanhos de todas as respostas do grupo antes de aplicar a fórmula.
- **Auxiliares (sem juiz, baratos):** acerto de valores (números do gabarito na resposta, tolerância do JSONL, normalizando formato BR), "valor recuperado" (número no contexto), latência e tokens.
  - **Valor recuperado:** o número do gabarito apareceu em algum resultado de ferramenta? Separa erro de recuperação de erro de redação. Ex. C01: a tabela de `top_exporters(2023)` tem "JBS, 277582.68" → recuperado; se a resposta disser "280 mil ha", o erro foi na redação, não na consulta.

### Pipeline do juiz
O juiz é uma chamada extra ao LLM depois que o sistema respondeu. Entradas: (a) pergunta, (b) contexto = saídas das ferramentas na ordem (tabelas `[D]` e trechos `[L]`), (c) resposta do sistema, (d) resposta esperada do gabarito. O juiz faz julgamentos sim/não; a nota é calculada por fórmula.
- **Faithfulness:** afirmações da resposta sustentadas pelo contexto ÷ total. Ex.: 4 de 5 → 0,8.
- **Context Recall:** afirmações do gabarito encontradas no contexto ÷ total. Ex. M01 sem o art. 12 recuperado → 2/3 = 0,67.
- **Context Precision:** para cada item do contexto, na ordem, "ajuda a chegar ao gabarito?"; média da precisão nas posições úteis. Ex. [útil, inútil, útil, inútil] → (1/1 + 2/3) / 2 = 0,83.

### Pipeline de cada teste
1. Busca direta (só perguntas com artigo no gabarito) → Hit Rate@k, Recall@k, MRR.
2. Sistema completo (agente) responde → resposta, contexto, tempo, tokens.
3. Checagens sem juiz → valor recuperado, acerto do número.
4. Juiz → Faithfulness, Context Precision, Context Recall.
5. Texto → ROUGE-L (P/R/F1) e BLEU por pergunta, contra as duas referências (BLEU de corpus é calculado na agregação).
6. Grava tudo e agrega por tipo (lei / carne / soja / mista) → relatório.

## Implementação (feita em 2026-11-11)
- **Temperatura:** o pedido era temperatura 0, mas o Claude Haiku 5.5 recusa qualquer valor diferente do padrão (e o SDK `anthropic` 2.6 nem tem mais o parâmetro). Decisão do usuário: **rodar cada pergunta uma vez** e registrar a variação como limitação. O mesmo vale para o juiz.
- `eval/build_gold.py`: campos `nivel` nos artigos, `no_teste`, `resposta_referencia` (referência longa, escrita antes de rodar o agente) e as mistas M06–M11.
- `eval/metrics.py`: Hit@k, Recall@k, MRR, precisão média (Context Precision) e leitura de números no formato BR e CSV.
- `eval/text_metrics.py`: normalização do texto, ROUGE-L (LCS próprio), BLEU (sacrebleu: por pergunta com `exp`, corpus sem suavização) e cosseno (e5-small, com aviso de truncamento e linha de base).
  - Correção feita em 2026-11-13: a limpeza só tirava rótulos puros (`[L1]`). O agente cita `[L1, Decreto 6.514/2008, art. 52]`, e o rótulo sobrava como token "l1". Agora só o rótulo sai e a lei e o artigo ficam.
- `python -m eval.run_eval --refazer-texto <pasta-da-rodada>`: refaz só ROUGE-L, BLEU e cosseno de uma rodada pronta com o gabarito atual (reaproveita respostas, contexto, busca direta e notas do juiz; não chama agente, juiz nem Postgres). Só vale enquanto a `resposta_esperada` não mudar, porque o juiz a usa. A rodada `rodada_20_perguntas_v3` é a v2 reavaliada assim.
- `eval/judge.py`: Faithfulness, Context Precision e Context Recall com prompts em português; o juiz devolve JSON com veredito e justificativa por item; a nota é calculada no código. Itens de contexto com mais de 6.000 caracteres são cortados para o juiz (marcado no texto). Erro do juiz deixa a nota vazia e vai para a trilha.
- `eval/run_eval.py`: `python -m eval.run_eval [--ids L01,M01] [--limit N] [--sem-juiz] [--saida pasta]`. Executa as etapas 1–5 por pergunta e grava os arquivos descritos em **Rastreabilidade**.
- `eval/report.py`: trilha `perguntas/<ID>.md` e `relatorio.md` (painel, por tipo, busca por k, ROUGE/BLEU em detalhe, por pergunta, piores casos, limitações).
- `tests/test_eval_metrics.py`: testes das funções puras (exemplos do plano: MRR 0,5 / Recall@3 0,5 do L01; ROUGE-L F1 0,84 e BLEU 0,52 da multa; números "260,2 mil" e CSV).
- `requirements.txt`: `sacrebleu`.

## Verificação
1. `python -m eval.build_gold` → 36 perguntas (30 atuais + M06–M11), 20 com `no_teste`, artigos com `nivel` (essencial/complementar).
2. Teste unitário em `tests/test_eval_metrics.py` das funções puras (Hit/Recall/MRR com listas sintéticas; normalização de números "260,2 mil ha" → 260200; ROUGE-L e BLEU no exemplo da multa: F1 = 0,84 e BLEU = 0,52).
3. Rodar `python -m eval.run_eval --limit 2` (1 lei + 1 mista) para conferir o formato e as justificativas do juiz; depois as 20.
4. Revisar manualmente ~5 notas do juiz contra a resposta para validar o juiz (registrar a concordância no relatório).
5. Conferir a rastreabilidade em 2 perguntas: refazer à mão, a partir de `perguntas/<ID>.md`, o MRR, uma nota do juiz e o ROUGE-L, e confirmar que batem com o `relatorio.md`.
6. `pytest -q tests` continua passando.

# Avaliação do RAG (2026-11-18)

20 perguntas · agente: `deepseek/deepseek-v4.1-flash` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o código não envia temperatura) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 1,00 | 16 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,97 | 16 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,94 | 16 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,98 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,90 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 1,00 | 18 | fração dos números do gabarito presentes no contexto, no lugar certo (cadeia, escopo, métrica, entidade e ano) |
| Valor recuperado (critério solto) | 1,00 | 18 | número próximo em qualquer lugar do contexto (critério das rodadas anteriores) |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,90 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 1,00 | 18 | fração dos números do gabarito presentes na resposta, com a unidade |
| Acerto de valores (critério solto) | 1,00 | 18 | número próximo em qualquer lugar da resposta (critério das rodadas anteriores) |
| ROUGE-L F1 (ref. curta) | 0,14 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,29 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,04 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,16 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,906 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,959 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 7,7 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 27.507 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 26.617 | 20 |  |
| Tokens de saída (média) | 890 | 20 |  |
| Tokens de entrada lidos do cache (média) | 11.283 | 20 | parte da entrada servida pelo cache de prompt (já incluída na entrada) |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 1,00 | 0,80 | 1,00 | 0,83 | 0,84 | 1,00 | 0,28 | 0,95 | 0,16 | 6,9 |
| Carne bovina | 2 | — | — | — | 1,00 | 1,00 | 0,93 | 1,00 | 0,30 | 0,96 | 0,11 | 5,0 |
| Soja | 2 | — | — | — | 1,00 | 0,75 | 0,95 | 1,00 | 0,28 | 0,96 | 0,16 | 7,2 |
| Mista | 11 | 1,00 | 0,95 | 1,00 | 0,96 | 0,94 | 0,92 | 1,00 | 0,29 | 0,96 | 0,16 | 8,7 |
| **Geral** | 20 | 1,00 | 0,97 | 0,94 | 0,98 | 0,90 | 0,90 | 1,00 | 0,29 | 0,96 | 0,16 | 7,7 |

## Busca nas leis por k (busca direta com a pergunta original)

| Métrica | Geral (n=16) | Lei (n=5) | Mista (n=11) |
|---|---|---|---|
| Hit@1 | 0,94 | 1,00 | 0,91 |
| Hit@3 | 1,00 | 1,00 | 1,00 |
| Hit@5 | 1,00 | 1,00 | 1,00 |
| Hit@10 | 1,00 | 1,00 | 1,00 |
| Recall@1 | 0,66 | 0,60 | 0,68 |
| Recall@3 | 0,94 | 0,80 | 1,00 |
| Recall@5 | 0,94 | 0,80 | 1,00 |
| Recall@10 | 1,00 | 1,00 | 1,00 |
| MRR | 0,97 | 1,00 | 0,95 |

## ROUGE-L, BLEU e cosseno em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) | Cosseno |
|---|---|---|---|---|---|---|
| curta | 0,08 | 0,75 | 0,14 | 0,04 | 0,04 | 0,906 |
| longa | 0,22 | 0,46 | 0,29 | 0,16 | 0,15 | 0,959 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,906 | 0,859 | 0,931 | 0,048 |
| longa | 0,959 | 0,896 | 0,950 | 0,063 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 11 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 0,75 | 0,88 | 1,00 | 0,27 | 0,15 | 0,95 | 7,8 | 28.734 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,85 | 1,00 | 0,30 | 0,20 | 0,95 | 6,3 | 25.459 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,79 | 1,00 | 0,28 | 0,14 | 0,95 | 7,4 | 26.132 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,79 | — | 0,31 | 0,18 | 0,94 | 7,1 | 26.614 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,39 | 0,92 | — | 0,27 | 0,16 | 0,96 | 5,6 | 25.429 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 1,00 | 0,50 | 1,00 | 1,00 | 0,30 | 0,18 | 0,96 | 9,1 | 36.040 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,90 | 1,00 | 0,25 | 0,13 | 0,95 | 5,2 | 23.543 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,94 | 1,00 | 0,27 | 0,10 | 0,97 | 5,4 | 24.298 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 1,00 | 1,00 | 0,91 | 1,00 | 0,33 | 0,13 | 0,95 | 4,6 | 23.953 |  |
| [M01](perguntas/M01.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,90 | 1,00 | 0,31 | 0,15 | 0,97 | 9,8 | 29.660 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,95 | 1,00 | 0,24 | 0,08 | 0,96 | 8,4 | 28.466 |  |
| [M03](perguntas/M03.md) | mista | 1,00 | 1,00 | 1,00 | 0,86 | 0,83 | 0,95 | 1,00 | 0,27 | 0,15 | 0,94 | 9,3 | 29.351 |  |
| [M04](perguntas/M04.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,36 | 0,22 | 0,97 | 9,4 | 27.916 |  |
| [M05](perguntas/M05.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,64 | 1,00 | 1,00 | 0,35 | 0,24 | 0,98 | 5,8 | 27.318 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,94 | 1,00 | 0,24 | 0,09 | 0,96 | 8,7 | 27.899 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,82 | 1,00 | 0,33 | 0,18 | 0,97 | 6,9 | 27.649 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 1,00 | 0,83 | 1,00 | 0,94 | 1,00 | 0,33 | 0,19 | 0,97 | 8,0 | 26.870 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,85 | 1,00 | 0,26 | 0,14 | 0,95 | 11,6 | 28.655 |  |
| [M10](perguntas/M10.md) | mista | 1,00 | 0,50 | 1,00 | 0,83 | 0,83 | 0,91 | 1,00 | 0,28 | 0,13 | 0,97 | 8,3 | 27.598 |  |
| [M11](perguntas/M11.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,86 | 1,00 | 0,25 | 0,14 | 0,96 | 9,5 | 28.563 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** nenhum
- **Menor Faithfulness:** [L04](perguntas/L04.md) (0,79), [L06](perguntas/L06.md) (0,79), [M07](perguntas/M07.md) (0,82), [L02](perguntas/L02.md) (0,85), [M09](perguntas/M09.md) (0,85)
- **Menor Context Recall:** [M08](perguntas/M08.md) (0,83), [M10](perguntas/M10.md) (0,83), [M03](perguntas/M03.md) (0,86), [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00)
- **Menor acerto de valores:** [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00), [L02](perguntas/L02.md) (1,00), [L04](perguntas/L04.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M06](perguntas/M06.md) (0,24), [M02](perguntas/M02.md) (0,24), [M11](perguntas/M11.md) (0,25), [S05](perguntas/S05.md) (0,25), [M09](perguntas/M09.md) (0,26)
- **Menor cosseno (ref. longa):** [L06](perguntas/L06.md) (0,94), [M03](perguntas/M03.md) (0,94), [S05](perguntas/S05.md) (0,95), [L01](perguntas/L01.md) (0,95), [L02](perguntas/L02.md) (0,95)

## Limitações

- **Uma rodada só e sem controle de temperatura:** temperatura padrão da API (o código não envia temperatura), então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Juiz diferente do agente:** juiz `anthropic/claude-haiku-5.5`, agente `deepseek/deepseek-v4.1-flash`. Isso reduz o viés de autoavaliação, mas as notas de rodadas com juízes diferentes não são diretamente comparáveis.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 244220 tokens de entrada e 101469 de saída (fora do bloco Custo, que mede só o sistema).

---

## Análise Consolidada das Perguntas Mistas (`M01` a `M11`)

### 1. Evolução das Métricas nas Perguntas Mistas (`n=11`) entre Rodadas

Comparação direta das 11 perguntas mistas (`M01` a `M11`) entre:
- **v5 (`rodada_20_perguntas_v5`):** baseline original (Haiku 5.5 sem decomposição);
- **v6 (`rodada_20_perguntas_v6`):** tentativa anterior de segmentação em subagentes isolados;
- **v8 (`rodada_20_perguntas_v8_deepseek_juiz_haiku`):** mesmo par de modelos desta rodada (`deepseek/deepseek-v4.1-flash` + juiz `anthropic/claude-haiku-5.5`), porém **antes** da decomposição + Multi-Query RRF;
- **v10 (`rodada_20_perguntas_v10_mistas_deepseek_juiz_haiku`):** esta rodada, com Roteador corrigido, Agente Decompositor, despoluição de embeddings/IDF e fusão Multi-Query RRF.

| Métrica (Perguntas Mistas, n=11) | v5 (Baseline) | v6 (Subagentes antigos) | v8 (DeepSeek s/ decomposição) | **v10 (Nova Decomposição + RRF)** | Ganho (v10 vs v8) | Ganho (v10 vs v5) |
|---|---|---|---|---|---|---|
| **Hit@1** | 0,36 | 0,36 | 0,36 | **0,91** | **+0,55** | **+0,55** |
| **Hit@3** | 0,45 | 0,45 | 0,45 | **1,00** | **+0,55** | **+0,55** |
| **Hit@5** | 0,64 | 0,64 | 0,64 | **1,00** | **+0,36** | **+0,36** |
| **MRR** | 0,43 | 0,43 | 0,43 | **0,95** | **+0,52** | **+0,52** |
| **Recall@5** | 0,55 | 0,55 | 0,55 | **1,00** | **+0,45** | **+0,45** |
| **Context Recall (Juiz)** | 0,89 | 0,58 | 0,92 | **0,96** | **+0,04** | **+0,07** |
| **Context Precision (Juiz)** | 0,72 | 0,70 | 0,92 | **0,94** | **+0,02** | **+0,22** |
| **Faithfulness (Juiz)** | 0,79 | 0,79 | 0,88 | **0,92** | **+0,04** | **+0,13** |
| **Acerto de valores** | 0,97 | 0,77 | 0,94 | **1,00** | **+0,06** | **+0,03** |
| **ROUGE-L F1 (ref. longa)** | 0,31 | 0,22 | 0,28 | **0,29** | **+0,01** | -0,02 |
| **Cosseno (ref. longa)** | 0,97 | 0,94 | 0,96 | **0,96** | **0,00** | -0,01 |
| **Latência média (s)** | 10,2 | 18,5 | 8,5 | **8,7** | +0,2 s | **-1,5 s** |

### 2. Comparação Pergunta a Pergunta (`M01` a `M11`: v8 Antes vs v10 Depois)

| ID | Hit@5 (v8 → v10) | MRR (v8 → v10) | Recall@5 (v8 → v10) | Ctx Recall (v8 → v10) | Ctx Precision (v8 → v10) | Faithfulness (v8 → v10) | Valores (v8 → v10) | Posição dos Artigos do Gabarito na v10 |
|---|---|---|---|---|---|---|---|---|
| **[M01](perguntas/M01.md)** | 0,00 → **1,00** | 0,00 → **1,00** | 0,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 0,91 → **0,90** | 1,00 → **1,00** | `12.651, art. 12` → **1º**; `art. 3` → **2º** |
| **[M02](perguntas/M02.md)** | 1,00 → **1,00** | 0,33 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 0,92 → **1,00** | 0,90 → **0,95** | 1,00 → **1,00** | `12.651, art. 12` → **1º**; `art. 3` → **3º** |
| **[M03](perguntas/M03.md)** | 0,00 → **1,00** | 0,00 → **1,00** | 0,00 → **1,00** | 0,83 → **0,86** | 0,83 → **0,83** | 0,89 → **0,95** | 1,00 → **1,00** | `6.514, art. 51` → **1º** |
| **[M04](perguntas/M04.md)** | 1,00 → **1,00** | 0,25 → **1,00** | 0,50 → **1,00** | 1,00 → **1,00** | 0,83 → **1,00** | 0,95 → **1,00** | 1,00 → **1,00** | `11.428, art. 11` → **1º**; `art. 14` → **3º** |
| **[M05](perguntas/M05.md)** | 0,00 → **1,00** | 0,00 → **1,00** | 0,00 → **1,00** | 0,67 → **1,00** | 1,00 → 0,64 | 0,71 → **1,00** | 0,33 → **1,00** | `12.187, art. 12` → **1º** |
| **[M06](perguntas/M06.md)** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 0,79 → **0,94** | 1,00 → **1,00** | `12.651, art. 12` → **1º**; `art. 3` → **3º** |
| **[M07](perguntas/M07.md)** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 0,92 → **1,00** | 1,00 → 0,82 | 1,00 → **1,00** | `12.651, art. 29` → **1º** |
| **[M08](perguntas/M08.md)** | 1,00 → **1,00** | 1,00 → **1,00** | 0,50 → **1,00** | 0,80 → **0,83** | 1,00 → **1,00** | 0,94 → **0,94** | 1,00 → **1,00** | `9.605, art. 38` → **1º**; `art. 39` → **2º** |
| **[M09](perguntas/M09.md)** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 1,00 → **1,00** | 0,94 → 0,85 | 1,00 → **1,00** | `6.514, art. 52` → **1º** |
| **[M10](perguntas/M10.md)** | 1,00 → **1,00** | 0,20 → **0,50** | 1,00 → **1,00** | 0,83 → **0,83** | 0,83 → **0,83** | 0,84 → **0,91** | 1,00 → **1,00** | `6.514, art. 51` → **2º** |
| **[M11](perguntas/M11.md)** | 0,00 → **1,00** | 0,00 → **1,00** | 0,00 → **1,00** | 1,00 → **1,00** | 0,83 → **1,00** | 0,83 → **0,86** | 1,00 → **1,00** | `6.938, art. 10` → **1º** |

### 3. Como cada Pergunta Mista foi Decomposta e Fundida nesta Rodada

| ID | Plano gerado pelo Agente Decompositor (`subconsultas`) | Ferramentas Acionadas | Destaques da Resolução |
|---|---|---|---|
| **M01** | `q1 (soy_data)`: Exposição ao desmatamento na cadeia da soja por bioma (2022)<br>`q2 (beef_data)`: Exposição na cadeia da carne bovina por bioma (2022)<br>`q3 (legislation)`: Reserva Legal exigida pelo Código Florestal nos biomas (depende de `q1, q2`) | `soy_deforestation_by_biome` (`D1`), `deforestation_by_region` (`D2`), `search_laws` (`L1-L8`) | O `Art. 12` (essencial) e o `Art. 3º` (complementar) saíram de fora do top-10 (`Hit@10=0` na v8) direto para **1º e 2º lugares**. |
| **M02** | `q1 (soy_data)`: Produção de soja no MT no ano mais recente<br>`q2 (beef_data)`: Exposição da carne bovina em 2023 no MT<br>`q3 (legislation)`: Percentual de Reserva Legal em área de floresta na Amazônia Legal | `soy_territorial_metric` (`D1`), `deforestation_by_region` (`D2`), `search_laws` (`L1-L6`) | `MRR` subiu de `0,33` para **`1,00`**, `Context Precision` subiu para **`1,00`** e `Faithfulness` subiu de `0,90` para **`0,95`**. |
| **M03** | `q1 (beef_data)`: Grupo exportador de carne bovina com maior exposição (2023)<br>`q2 (beef_data)`: Compromissos de desmatamento zero dos grupos<br>`q3 (legislation)`: Multa do Decreto 6.514/2008 para desmatamento dentro da Reserva Legal | `top_exporters` (`D1`), `commitment_summary` (`D2`), `search_laws` (`L1-L8`) | Na v6 havia abortado com `planning_error` (nota `0,00`); na v8 tinha `Hit@10=0`. Agora teve `Hit@1=1,00`, `Faithfulness=0,95` e `Valores=1,00`. |
| **M04** | `q1 (soy_data)`: Exposição da soja na Mata Atlântica em 2022<br>`q2 (legislation)`: Casos em que a lei proíbe corte de vegetação primária na Mata Atlântica | `soy_deforestation_by_biome` (`D1`), `search_laws` (`L1-L6`) | Resolveu a anáfora *"nesse bioma"* → *"Mata Atlântica"* e trouxe `Art. 11` (1º) e `Art. 14` (3º), subindo `Recall@5` de `0,50` → **`1,00`** e `Faithfulness` para **`1,00`**. |
| **M05** | `q1 (soy_data)`: Emissões de CO2 associadas ao desmatamento na soja (2022)<br>`q2 (legislation)`: Meta de redução de emissões na PNMC | `soy_yearly_trend` (`D1`), `search_laws` (`L1-L6`) | **Maior salto da rodada:** na v8 o `Art. 12` da PNMC não era recuperado (`Valores=0,33`, `Ctx Recall=0,67`, `Faithfulness=0,71`). Na v10, o `Art. 12` ficou em **1º lugar** e `Hit@5`, `MRR`, `Ctx Recall`, `Faithfulness` e `Valores` cravaram **`1,00`**. |
| **M06** | `q1 (beef_data)`: Estado com maior área de pastagem<br>`q2 (legislation)`: Percentual mínimo de Reserva Legal em área de floresta na Amazônia Legal | `territorial_metric` (`D1`), `search_laws` (`L1-L6`) | Roteada como `mixed` (na v5/v6 era confundida com `law`), elevando `Faithfulness` de `0,79` para **`0,94`** com `1,00` em todas as métricas de recuperação e valores. |
| **M07** | `q1 (soy_data)`: % da soja exportada pelo MT sob compromisso ZDC (2022)<br>`q2 (legislation)`: O que é o CAR e sua função no Código Florestal | `soy_territorial_metric` (`D1`), `search_laws` (`L1-L6`) | Roteada como `mixed` (na v5/v6 perdia `search_laws`), mantendo `Hit@1=1,00`, `Ctx Recall=1,00`, `Ctx Precision=1,00` e `Valores=1,00`. |
| **M08** | `q1 (beef_data)`: Município com maior exposição na carne bovina (2023)<br>`q2 (legislation)`: Pena para quem destrói floresta de preservação permanente | `top_municipalities` (`D1`), `search_laws` (`L1-L6`) | A fusão RRF + diversidade por artigo colocou `Art. 38` em **1º** e `Art. 39` (complementar) em **2º**, subindo `Recall@5` de `0,50` para **`1,00`**. |
| **M09** | `q1 (soy_data)`: Exposição da soja na Amazônia (2022)<br>`q2 (beef_data)`: Exposição da carne bovina na Amazônia (2022)<br>`q3 (legislation)`: Multa por desmatamento a corte raso fora da Reserva Legal | `soy_deforestation_by_biome` (`D1`), `deforestation_by_region` (`D2`), `search_laws` (`L1-L6`) | `Hit@1=1,00`, `Ctx Recall=1,00`, `Ctx Precision=1,00` e `Valores=1,00`. |
| **M10** | `q1 (soy_data)`: Maior grupo exportador de soja em 2022 e sua exposição<br>`q2 (legislation)`: Multa para quem desmata dentro da Reserva Legal | `soy_top_exporters` (`D1`), `search_laws` (`L1-L6`) | Na v6 havia zerado com `planning_error`. Agora subiu `MRR` de `0,20` → **`0,50`** (`Art. 51` na 2ª posição), `Faithfulness` de `0,84` → **`0,91`** e `Valores = 1,00`. |
| **M11** | `q1 (soy_data)`: Estado com maior capacidade de processamento de soja<br>`q2 (legislation)`: Atividades que dependem de licenciamento ambiental prévio | `soy_facilities_summary` (`D1`), `search_laws` (`L1-L6`) | A despoluição dos termos de soja na sub-busca jurídica tirou o `Art. 10` da Lei 6.938/1981 de fora do top-10 (`Hit@10=0` na v8) para o **1º lugar** (`MRR=1,00`, `Ctx Recall=1,00`, `Ctx Precision=1,00`). |

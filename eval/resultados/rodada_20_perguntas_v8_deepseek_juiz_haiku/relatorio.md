# Avaliação do RAG (2026-11-18)

20 perguntas · agente: `deepseek/deepseek-v4.1-flash` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o código não envia temperatura) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,75 | 16 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,58 | 16 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,62 | 16 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,96 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,88 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 0,96 | 18 | fração dos números do gabarito presentes no contexto, no lugar certo (cadeia, escopo, métrica, entidade e ano) |
| Valor recuperado (critério solto) | 0,96 | 18 | número próximo em qualquer lugar do contexto (critério das rodadas anteriores) |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,89 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 0,96 | 18 | fração dos números do gabarito presentes na resposta, com a unidade |
| Acerto de valores (critério solto) | 0,96 | 18 | número próximo em qualquer lugar da resposta (critério das rodadas anteriores) |
| ROUGE-L F1 (ref. curta) | 0,14 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,29 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,04 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,16 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,905 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,959 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 7,2 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 26.167 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 25.411 | 20 |  |
| Tokens de saída (média) | 756 | 20 |  |
| Tokens de entrada lidos do cache (média) | 8.128 | 20 | parte da entrada servida pelo cache de prompt (já incluída na entrada) |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 0,90 | 0,80 | 1,00 | 0,68 | 0,88 | 1,00 | 0,30 | 0,95 | 0,17 | 5,9 |
| Carne bovina | 2 | — | — | — | 1,00 | 1,00 | 0,91 | 1,00 | 0,30 | 0,96 | 0,13 | 5,9 |
| Soja | 2 | — | — | — | 1,00 | 1,00 | 0,97 | 1,00 | 0,27 | 0,95 | 0,12 | 4,3 |
| Mista | 11 | 0,64 | 0,43 | 0,55 | 0,92 | 0,92 | 0,88 | 0,94 | 0,28 | 0,96 | 0,16 | 8,5 |
| **Geral** | 20 | 0,75 | 0,58 | 0,62 | 0,96 | 0,88 | 0,89 | 0,96 | 0,29 | 0,96 | 0,16 | 7,2 |

## Busca nas leis por k (busca direta com a pergunta original)

| Métrica | Geral (n=16) | Lei (n=5) | Mista (n=11) |
|---|---|---|---|
| Hit@1 | 0,50 | 0,80 | 0,36 |
| Hit@3 | 0,62 | 1,00 | 0,45 |
| Hit@5 | 0,75 | 1,00 | 0,64 |
| Hit@10 | 0,75 | 1,00 | 0,64 |
| Recall@1 | 0,41 | 0,60 | 0,32 |
| Recall@3 | 0,50 | 0,80 | 0,36 |
| Recall@5 | 0,62 | 0,80 | 0,55 |
| Recall@10 | 0,69 | 0,90 | 0,59 |
| MRR | 0,58 | 0,90 | 0,43 |

## ROUGE-L, BLEU e cosseno em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) | Cosseno |
|---|---|---|---|---|---|---|
| curta | 0,08 | 0,71 | 0,14 | 0,04 | 0,04 | 0,905 |
| longa | 0,22 | 0,44 | 0,29 | 0,16 | 0,16 | 0,959 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,905 | 0,858 | 0,927 | 0,047 |
| longa | 0,959 | 0,896 | 0,953 | 0,063 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 8 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 0,61 | 1,00 | 1,00 | 0,30 | 0,18 | 0,95 | 5,7 | 30.488 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,83 | 1,00 | 0,27 | 0,18 | 0,95 | 4,5 | 25.132 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,62 | 0,87 | 1,00 | 0,28 | 0,12 | 0,95 | 7,5 | 27.770 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,64 | 0,91 | — | 0,32 | 0,18 | 0,95 | 6,0 | 26.540 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 0,50 | 1,00 | 1,00 | 0,50 | 0,78 | — | 0,32 | 0,21 | 0,95 | 5,7 | 25.057 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 1,00 | 1,00 | 0,94 | 1,00 | 0,22 | 0,10 | 0,95 | 4,8 | 23.969 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 1,00 | 1,00 | 0,33 | 0,17 | 0,95 | 3,8 | 23.633 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 1,00 | 1,00 | 0,32 | 0,15 | 0,95 | 5,2 | 24.136 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 1,00 | 1,00 | 0,81 | 1,00 | 0,28 | 0,12 | 0,96 | 6,5 | 24.033 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 1,00 | 0,91 | 1,00 | 0,29 | 0,15 | 0,97 | 9,7 | 27.957 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,33 | 1,00 | 1,00 | 0,92 | 0,90 | 1,00 | 0,22 | 0,07 | 0,96 | 15,4 | 27.056 |  |
| [M03](perguntas/M03.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 0,83 | 0,89 | 1,00 | 0,30 | 0,19 | 0,96 | 6,6 | 26.569 |  |
| [M04](perguntas/M04.md) | mista | 1,00 | 0,25 | 0,50 | 1,00 | 0,83 | 0,95 | 1,00 | 0,33 | 0,20 | 0,97 | 10,0 | 26.510 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 0,67 | 1,00 | 0,71 | 0,33 | 0,22 | 0,11 | 0,96 | 5,5 | 26.167 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,79 | 1,00 | 0,22 | 0,11 | 0,95 | 6,7 | 26.656 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,92 | 1,00 | 1,00 | 0,37 | 0,22 | 0,97 | 5,6 | 25.893 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 0,50 | 0,80 | 1,00 | 0,94 | 1,00 | 0,33 | 0,26 | 0,97 | 5,8 | 25.961 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,94 | 1,00 | 0,29 | 0,18 | 0,97 | 5,5 | 26.891 |  |
| [M10](perguntas/M10.md) | mista | 1,00 | 0,20 | 1,00 | 0,83 | 0,83 | 0,84 | 1,00 | 0,28 | 0,16 | 0,96 | 8,4 | 25.950 |  |
| [M11](perguntas/M11.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,83 | 0,83 | 1,00 | 0,23 | 0,12 | 0,96 | 14,4 | 26.970 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md), [M03](perguntas/M03.md), [M05](perguntas/M05.md), [M11](perguntas/M11.md)
- **Menor Faithfulness:** [M05](perguntas/M05.md) (0,71), [L07](perguntas/L07.md) (0,78), [M06](perguntas/M06.md) (0,79), [C04](perguntas/C04.md) (0,81), [L02](perguntas/L02.md) (0,83)
- **Menor Context Recall:** [M05](perguntas/M05.md) (0,67), [M08](perguntas/M08.md) (0,80), [M03](perguntas/M03.md) (0,83), [M10](perguntas/M10.md) (0,83), [C01](perguntas/C01.md) (1,00)
- **Menor acerto de valores:** [M05](perguntas/M05.md) (0,33), [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00), [L02](perguntas/L02.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [S01](perguntas/S01.md) (0,22), [M06](perguntas/M06.md) (0,22), [M02](perguntas/M02.md) (0,22), [M05](perguntas/M05.md) (0,22), [M11](perguntas/M11.md) (0,23)
- **Menor cosseno (ref. longa):** [L06](perguntas/L06.md) (0,95), [S01](perguntas/S01.md) (0,95), [M06](perguntas/M06.md) (0,95), [L07](perguntas/L07.md) (0,95), [L01](perguntas/L01.md) (0,95)

## Limitações

- **Uma rodada só e sem controle de temperatura:** temperatura padrão da API (o código não envia temperatura), então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Juiz diferente do agente:** juiz `anthropic/claude-haiku-5.5`, agente `deepseek/deepseek-v4.1-flash`. Isso reduz o viés de autoavaliação, mas as notas de rodadas com juízes diferentes não são diretamente comparáveis.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 257468 tokens de entrada e 102657 de saída (fora do bloco Custo, que mede só o sistema).

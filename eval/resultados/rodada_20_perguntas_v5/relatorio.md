# Avaliação do RAG (2026-11-13)

20 perguntas · agente: `anthropic/claude-haiku-5.5` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o Claude Haiku 5.5 não aceita temperatura 0) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,75 | 16 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,58 | 16 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,62 | 16 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,93 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,82 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 1,00 | 18 | fração dos números do gabarito presentes no contexto |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,84 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 0,98 | 18 | fração dos números do gabarito presentes na resposta |
| ROUGE-L F1 (ref. curta) | 0,17 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,33 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,05 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,17 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,913 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,963 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 8,5 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 5.514 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 4.139 | 20 |  |
| Tokens de saída (média) | 1.375 | 20 |  |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 0,90 | 0,80 | 1,00 | 0,92 | 0,93 | 1,00 | 0,32 | 0,96 | 0,17 | 6,6 |
| Carne bovina | 2 | — | — | — | 0,88 | 1,00 | 0,78 | 1,00 | 0,36 | 0,96 | 0,16 | 7,4 |
| Soja | 2 | — | — | — | 1,00 | 1,00 | 0,94 | 1,00 | 0,44 | 0,97 | 0,25 | 4,8 |
| Mista | 11 | 0,64 | 0,43 | 0,55 | 0,89 | 0,72 | 0,79 | 0,97 | 0,31 | 0,97 | 0,17 | 10,2 |
| **Geral** | 20 | 0,75 | 0,58 | 0,62 | 0,93 | 0,82 | 0,84 | 0,98 | 0,33 | 0,96 | 0,17 | 8,5 |

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
| curta | 0,10 | 0,75 | 0,17 | 0,05 | 0,06 | 0,913 |
| longa | 0,26 | 0,45 | 0,33 | 0,17 | 0,18 | 0,963 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,913 | 0,865 | 0,934 | 0,048 |
| longa | 0,963 | 0,900 | 0,963 | 0,063 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 3 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 1,00 | 1,00 | 0,30 | 0,15 | 0,95 | 7,3 | 5.053 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,86 | 1,00 | 0,30 | 0,16 | 0,96 | 7,4 | 3.888 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,35 | 0,16 | 0,96 | 6,2 | 5.075 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,89 | — | 0,29 | 0,13 | 0,94 | 6,2 | 3.333 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 0,50 | 1,00 | 1,00 | 0,58 | 0,93 | — | 0,34 | 0,25 | 0,97 | 5,9 | 3.984 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 1,00 | 1,00 | 1,00 | 1,00 | 0,42 | 0,22 | 0,96 | 5,9 | 1.508 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,89 | 1,00 | 0,47 | 0,30 | 0,97 | 3,7 | 1.091 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,73 | 1,00 | 0,39 | 0,24 | 0,95 | 4,6 | 1.420 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 0,75 | 1,00 | 0,83 | 1,00 | 0,32 | 0,13 | 0,96 | 10,1 | 3.319 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,89 | 0,90 | 1,00 | 0,28 | 0,16 | 0,97 | 12,0 | 8.781 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,33 | 1,00 | 0,67 | 0,45 | 0,80 | 0,67 | 0,26 | 0,12 | 0,97 | 9,9 | 7.231 |  |
| [M03](perguntas/M03.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 0,83 | 0,76 | 1,00 | 0,32 | 0,20 | 0,97 | 10,7 | 5.766 |  |
| [M04](perguntas/M04.md) | mista | 1,00 | 0,25 | 0,50 | 1,00 | 0,75 | 0,68 | 1,00 | 0,37 | 0,18 | 0,98 | 9,8 | 5.548 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 0,80 | 0,35 | 0,50 | 1,00 | 0,34 | 0,19 | 0,96 | 11,1 | 14.075 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,94 | 1,00 | 0,26 | 0,09 | 0,95 | 7,9 | 6.198 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,87 | 1,00 | 1,00 | 0,41 | 0,28 | 0,97 | 5,4 | 3.551 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 0,50 | 0,83 | 1,00 | 0,50 | 1,00 | 0,29 | 0,21 | 0,97 | 8,1 | 4.308 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,48 | 0,86 | 1,00 | 0,28 | 0,14 | 0,97 | 16,1 | 8.581 |  |
| [M10](perguntas/M10.md) | mista | 1,00 | 0,20 | 1,00 | 0,83 | 0,29 | 0,95 | 1,00 | 0,25 | 0,14 | 0,96 | 13,2 | 11.373 |  |
| [M11](perguntas/M11.md) | mista | 0,00 | 0,00 | 0,00 | 0,80 | 1,00 | 0,85 | 1,00 | 0,31 | 0,19 | 0,96 | 8,5 | 6.202 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md), [M03](perguntas/M03.md), [M05](perguntas/M05.md), [M11](perguntas/M11.md)
- **Menor Faithfulness:** [M05](perguntas/M05.md) (0,50), [M08](perguntas/M08.md) (0,50), [M04](perguntas/M04.md) (0,68), [C01](perguntas/C01.md) (0,73), [M03](perguntas/M03.md) (0,76)
- **Menor Context Recall:** [M02](perguntas/M02.md) (0,67), [C04](perguntas/C04.md) (0,75), [M05](perguntas/M05.md) (0,80), [M11](perguntas/M11.md) (0,80), [M03](perguntas/M03.md) (0,83)
- **Menor acerto de valores:** [M02](perguntas/M02.md) (0,67), [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00), [L02](perguntas/L02.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M10](perguntas/M10.md) (0,25), [M06](perguntas/M06.md) (0,26), [M02](perguntas/M02.md) (0,26), [M09](perguntas/M09.md) (0,28), [M01](perguntas/M01.md) (0,28)
- **Menor cosseno (ref. longa):** [L06](perguntas/L06.md) (0,94), [M06](perguntas/M06.md) (0,95), [C01](perguntas/C01.md) (0,95), [L01](perguntas/L01.md) (0,95), [L02](perguntas/L02.md) (0,96)

## Limitações

- **Uma rodada só e sem controle de temperatura:** o Claude Haiku 5.5 não aceita temperatura 0, então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz é o mesmo modelo do sistema.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 207788 tokens de entrada e 96523 de saída (fora do bloco Custo, que mede só o sistema).

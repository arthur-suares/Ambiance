# Avaliação do RAG (2026-11-11)

20 perguntas · agente: `anthropic/claude-haiku-5.5` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o Claude Haiku 5.5 não aceita temperatura 0) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,62 | 16 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,54 | 16 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,53 | 16 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,89 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,79 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 0,89 | 18 | fração dos números do gabarito presentes no contexto |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,83 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 0,89 | 18 | fração dos números do gabarito presentes na resposta |
| ROUGE-L F1 (ref. curta) | 0,17 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,33 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,06 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,19 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,912 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,965 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 7,7 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 5.888 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 4.568 | 20 |  |
| Tokens de saída (média) | 1.319 | 20 |  |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 1,00 | 0,80 | 1,00 | 0,90 | 0,87 | 1,00 | 0,32 | 0,96 | 0,21 | 5,3 |
| Carne bovina | 2 | — | — | — | 0,88 | 1,00 | 0,77 | 1,00 | 0,36 | 0,96 | 0,16 | 7,3 |
| Soja | 2 | — | — | — | 1,00 | 1,00 | 0,79 | 1,00 | 0,31 | 0,96 | 0,14 | 4,4 |
| Mista | 11 | 0,45 | 0,34 | 0,41 | 0,82 | 0,66 | 0,83 | 0,82 | 0,34 | 0,97 | 0,20 | 9,5 |
| **Geral** | 20 | 0,62 | 0,54 | 0,53 | 0,89 | 0,79 | 0,83 | 0,89 | 0,33 | 0,97 | 0,19 | 7,7 |

## Busca nas leis por k (busca direta com a pergunta original)

| Métrica | Geral (n=16) | Lei (n=5) | Mista (n=11) |
|---|---|---|---|
| Hit@1 | 0,50 | 1,00 | 0,27 |
| Hit@3 | 0,56 | 1,00 | 0,36 |
| Hit@5 | 0,62 | 1,00 | 0,45 |
| Hit@10 | 0,69 | 1,00 | 0,55 |
| Recall@1 | 0,34 | 0,60 | 0,23 |
| Recall@3 | 0,47 | 0,80 | 0,32 |
| Recall@5 | 0,53 | 0,80 | 0,41 |
| Recall@10 | 0,59 | 0,90 | 0,45 |
| MRR | 0,54 | 1,00 | 0,34 |

## ROUGE-L, BLEU e cosseno em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) | Cosseno |
|---|---|---|---|---|---|---|
| curta | 0,10 | 0,73 | 0,17 | 0,06 | 0,06 | 0,912 |
| longa | 0,27 | 0,44 | 0,33 | 0,19 | 0,19 | 0,965 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,912 | 0,864 | 0,935 | 0,048 |
| longa | 0,965 | 0,900 | 0,959 | 0,065 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 2 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 0,83 | 1,00 | 1,00 | 0,33 | 0,20 | 0,96 | 4,8 | 4.464 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 1,00 | 1,00 | 0,23 | 0,16 | 0,95 | 4,2 | 3.752 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,80 | 1,00 | 0,35 | 0,16 | 0,96 | 6,7 | 4.616 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,67 | 0,56 | — | 0,32 | 0,28 | 0,97 | 6,7 | 3.001 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | — | 0,37 | 0,28 | 0,97 | 4,0 | 3.553 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 1,00 | 1,00 | 0,80 | 1,00 | 0,30 | 0,13 | 0,96 | 5,2 | 1.572 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,78 | 1,00 | 0,32 | 0,14 | 0,96 | 3,6 | 1.202 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,91 | 1,00 | 0,38 | 0,24 | 0,96 | 4,6 | 1.508 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 0,75 | 1,00 | 0,63 | 1,00 | 0,35 | 0,12 | 0,96 | 10,0 | 3.246 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,49 | 0,87 | 1,00 | 0,45 | 0,27 | 0,98 | 16,3 | 19.093 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,25 | 1,00 | 1,00 | 0,64 | 0,74 | 1,00 | 0,24 | 0,08 | 0,96 | 11,9 | 12.665 |  |
| [M03](perguntas/M03.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 0,83 | 0,85 | 1,00 | 0,34 | 0,22 | 0,97 | 8,3 | 5.706 |  |
| [M04](perguntas/M04.md) | mista | 0,00 | 0,11 | 0,00 | 0,89 | 0,17 | 0,83 | 0,00 | 0,33 | 0,17 | 0,97 | 9,4 | 5.478 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,62 | 0,00 | 0,25 | 0,14 | 0,96 | 9,1 | 12.066 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,85 | 1,00 | 0,27 | 0,11 | 0,95 | 7,2 | 5.729 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,38 | 0,21 | 0,97 | 6,0 | 3.782 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 0,50 | 0,83 | 1,00 | 0,87 | 1,00 | 0,38 | 0,22 | 0,98 | 6,7 | 4.051 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 0,33 | 1,00 | 1,00 | 0,81 | 0,86 | 1,00 | 0,43 | 0,24 | 0,98 | 11,4 | 6.753 |  |
| [M10](perguntas/M10.md) | mista | 0,00 | 0,00 | 0,00 | 0,67 | 0,29 | 0,84 | 1,00 | 0,31 | 0,17 | 0,97 | 11,1 | 9.928 |  |
| [M11](perguntas/M11.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 1,00 | 0,81 | 1,00 | 0,33 | 0,23 | 0,97 | 7,1 | 5.585 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md), [M03](perguntas/M03.md), [M05](perguntas/M05.md), [M10](perguntas/M10.md), [M11](perguntas/M11.md)
- **Menor Faithfulness:** [L06](perguntas/L06.md) (0,56), [M05](perguntas/M05.md) (0,62), [C04](perguntas/C04.md) (0,63), [M02](perguntas/M02.md) (0,74), [S05](perguntas/S05.md) (0,78)
- **Menor Context Recall:** [M05](perguntas/M05.md) (0,00), [M10](perguntas/M10.md) (0,67), [C04](perguntas/C04.md) (0,75), [M03](perguntas/M03.md) (0,83), [M08](perguntas/M08.md) (0,83)
- **Menor acerto de valores:** [M04](perguntas/M04.md) (0,00), [M05](perguntas/M05.md) (0,00), [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [L02](perguntas/L02.md) (0,23), [M02](perguntas/M02.md) (0,24), [M05](perguntas/M05.md) (0,25), [M06](perguntas/M06.md) (0,27), [S01](perguntas/S01.md) (0,30)
- **Menor cosseno (ref. longa):** [L02](perguntas/L02.md) (0,95), [M06](perguntas/M06.md) (0,95), [C01](perguntas/C01.md) (0,96), [S05](perguntas/S05.md) (0,96), [L04](perguntas/L04.md) (0,96)

## Limitações

- **Uma rodada só e sem controle de temperatura:** o Claude Haiku 5.5 não aceita temperatura 0, então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz é o mesmo modelo do sistema.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 202799 tokens de entrada e 94923 de saída (fora do bloco Custo, que mede só o sistema).

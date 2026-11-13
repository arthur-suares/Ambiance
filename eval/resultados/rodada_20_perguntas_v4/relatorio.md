# Avaliação do RAG (2026-11-13)

20 perguntas · agente: `anthropic/claude-haiku-5.5` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o Claude Haiku 5.5 não aceita temperatura 0) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,62 | 16 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,54 | 16 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,53 | 16 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,88 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,88 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 0,96 | 18 | fração dos números do gabarito presentes no contexto |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,84 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 0,94 | 18 | fração dos números do gabarito presentes na resposta |
| ROUGE-L F1 (ref. curta) | 0,17 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,32 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,05 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,17 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,911 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,963 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 8,2 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 6.077 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 4.742 | 20 |  |
| Tokens de saída (média) | 1.335 | 20 |  |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 1,00 | 0,80 | 1,00 | 0,92 | 0,90 | 1,00 | 0,33 | 0,96 | 0,17 | 6,1 |
| Carne bovina | 2 | — | — | — | 0,88 | 1,00 | 0,87 | 1,00 | 0,32 | 0,96 | 0,16 | 7,8 |
| Soja | 2 | — | — | — | 0,90 | 1,00 | 0,76 | 1,00 | 0,40 | 0,96 | 0,21 | 5,1 |
| Mista | 11 | 0,45 | 0,34 | 0,41 | 0,81 | 0,81 | 0,82 | 0,91 | 0,31 | 0,97 | 0,17 | 9,7 |
| **Geral** | 20 | 0,62 | 0,54 | 0,53 | 0,88 | 0,88 | 0,84 | 0,94 | 0,32 | 0,96 | 0,17 | 8,2 |

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
| curta | 0,10 | 0,73 | 0,17 | 0,05 | 0,06 | 0,911 |
| longa | 0,27 | 0,43 | 0,32 | 0,17 | 0,18 | 0,963 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,911 | 0,864 | 0,934 | 0,047 |
| longa | 0,963 | 0,898 | 0,961 | 0,065 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 4 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 1,00 | 1,00 | 0,32 | 0,20 | 0,97 | 6,7 | 4.353 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,83 | 1,00 | 0,32 | 0,21 | 0,95 | 3,7 | 3.767 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,28 | 0,10 | 0,95 | 8,6 | 7.576 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,61 | 0,67 | — | 0,27 | 0,14 | 0,95 | 7,8 | 4.828 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | — | 0,44 | 0,34 | 0,98 | 3,8 | 3.882 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 0,80 | 1,00 | 0,92 | 1,00 | 0,42 | 0,21 | 0,97 | 5,7 | 1.477 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,60 | 1,00 | 0,39 | 0,20 | 0,96 | 4,5 | 1.259 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,85 | 1,00 | 0,39 | 0,27 | 0,96 | 4,5 | 1.385 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 0,75 | 1,00 | 0,90 | 1,00 | 0,24 | 0,10 | 0,96 | 11,1 | 2.868 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,47 | 0,86 | 1,00 | 0,35 | 0,19 | 0,97 | 15,3 | 19.900 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,25 | 1,00 | 1,00 | 1,00 | 0,68 | 1,00 | 0,34 | 0,18 | 0,98 | 10,2 | 7.290 |  |
| [M03](perguntas/M03.md) | mista | 0,00 | 0,00 | 0,00 | 0,88 | 0,83 | 0,84 | 1,00 | 0,27 | 0,17 | 0,96 | 8,0 | 5.529 |  |
| [M04](perguntas/M04.md) | mista | 0,00 | 0,11 | 0,00 | 0,12 | 1,00 | 0,95 | 1,00 | 0,26 | 0,14 | 0,96 | 13,8 | 11.782 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 0,12 | 0,75 | 0,67 | 0,35 | 0,27 | 0,97 | 7,2 | 12.080 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,84 | 1,00 | 0,22 | 0,06 | 0,94 | 7,4 | 6.190 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,83 | 1,00 | 0,37 | 0,22 | 0,96 | 7,0 | 3.853 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 0,50 | 0,83 | 1,00 | 0,88 | 1,00 | 0,40 | 0,26 | 0,98 | 7,7 | 4.119 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 0,33 | 1,00 | 1,00 | 1,00 | 0,71 | 1,00 | 0,35 | 0,20 | 0,98 | 12,7 | 6.798 |  |
| [M10](perguntas/M10.md) | mista | 0,00 | 0,00 | 0,00 | 0,57 | 0,83 | 0,75 | 0,33 | 0,26 | 0,15 | 0,96 | 9,1 | 5.468 |  |
| [M11](perguntas/M11.md) | mista | 0,00 | 0,00 | 0,00 | 0,71 | 0,63 | 0,93 | 1,00 | 0,22 | 0,07 | 0,96 | 8,3 | 7.142 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md), [M03](perguntas/M03.md), [M05](perguntas/M05.md), [M10](perguntas/M10.md), [M11](perguntas/M11.md)
- **Menor Faithfulness:** [S05](perguntas/S05.md) (0,60), [L06](perguntas/L06.md) (0,67), [M02](perguntas/M02.md) (0,68), [M09](perguntas/M09.md) (0,71), [M05](perguntas/M05.md) (0,75)
- **Menor Context Recall:** [M04](perguntas/M04.md) (0,12), [M10](perguntas/M10.md) (0,57), [M11](perguntas/M11.md) (0,71), [C04](perguntas/C04.md) (0,75), [S01](perguntas/S01.md) (0,80)
- **Menor acerto de valores:** [M10](perguntas/M10.md) (0,33), [M05](perguntas/M05.md) (0,67), [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M11](perguntas/M11.md) (0,22), [M06](perguntas/M06.md) (0,22), [C04](perguntas/C04.md) (0,24), [M10](perguntas/M10.md) (0,26), [M04](perguntas/M04.md) (0,26)
- **Menor cosseno (ref. longa):** [M06](perguntas/M06.md) (0,94), [L04](perguntas/L04.md) (0,95), [L02](perguntas/L02.md) (0,95), [L06](perguntas/L06.md) (0,95), [S05](perguntas/S05.md) (0,96)

## Limitações

- **Uma rodada só e sem controle de temperatura:** o Claude Haiku 5.5 não aceita temperatura 0, então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz é o mesmo modelo do sistema.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 227421 tokens de entrada e 100458 de saída (fora do bloco Custo, que mede só o sistema).

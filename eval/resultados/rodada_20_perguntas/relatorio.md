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
| Context Recall | 0,91 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,86 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 0,98 | 18 | fração dos números do gabarito presentes no contexto |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,83 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 0,98 | 18 | fração dos números do gabarito presentes na resposta |
| ROUGE-L F1 (ref. curta) | 0,17 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,28 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,06 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,12 | 20 | n-gramas (1 a 4) em comum, somados no grupo |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 8,1 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 5.668 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 4.348 | 20 |  |
| Tokens de saída (média) | 1.320 | 20 |  |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 1,00 | 0,80 | 1,00 | 0,93 | 0,82 | 1,00 | 0,36 | 0,21 | 5,4 |
| Carne bovina | 2 | — | — | — | 0,67 | 1,00 | 0,75 | 1,00 | 0,26 | 0,10 | 7,4 |
| Soja | 2 | — | — | — | 0,90 | 1,00 | 0,83 | 1,00 | 0,27 | 0,13 | 5,5 |
| Mista | 11 | 0,45 | 0,34 | 0,41 | 0,91 | 0,77 | 0,85 | 0,97 | 0,25 | 0,10 | 9,9 |
| **Geral** | 20 | 0,62 | 0,54 | 0,53 | 0,91 | 0,86 | 0,83 | 0,98 | 0,28 | 0,12 | 8,1 |

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

## ROUGE-L e BLEU em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) |
|---|---|---|---|---|---|
| curta | 0,10 | 0,75 | 0,17 | 0,06 | 0,06 |
| longa | 0,19 | 0,59 | 0,28 | 0,12 | 0,14 |

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 1,00 | 1,00 | 0,36 | 0,22 | 5,2 | 4.894 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,78 | 1,00 | 0,23 | 0,14 | 6,2 | 4.108 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,60 | 1,00 | 0,39 | 0,19 | 5,3 | 5.136 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,64 | 0,70 | — | 0,36 | 0,19 | 6,0 | 5.089 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | — | 0,48 | 0,31 | 4,5 | 3.960 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 0,80 | 1,00 | 0,76 | 1,00 | 0,32 | 0,13 | 6,1 | 1.638 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,90 | 1,00 | 0,22 | 0,13 | 4,9 | 1.276 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,69 | 1,00 | 0,32 | 0,15 | 5,3 | 1.397 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 0,33 | 1,00 | 0,81 | 1,00 | 0,20 | 0,07 | 9,5 | 2.798 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,89 | 0,94 | 1,00 | 0,20 | 0,06 | 13,6 | 8.464 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,25 | 1,00 | 1,00 | 0,92 | 0,67 | 1,00 | 0,18 | 0,06 | 14,1 | 7.851 |  |
| [M03](perguntas/M03.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 0,83 | 0,86 | 1,00 | 0,29 | 0,13 | 7,7 | 5.337 |  |
| [M04](perguntas/M04.md) | mista | 0,00 | 0,11 | 0,00 | 1,00 | 0,67 | 0,82 | 1,00 | 0,26 | 0,11 | 13,3 | 13.334 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 0,67 | 0,12 | 1,00 | 0,67 | 0,31 | 0,13 | 8,5 | 11.994 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,83 | 0,85 | 1,00 | 0,17 | 0,08 | 7,1 | 5.110 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,80 | 1,00 | 0,31 | 0,18 | 5,8 | 3.660 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 0,50 | 0,83 | 1,00 | 0,79 | 1,00 | 0,27 | 0,12 | 6,5 | 4.150 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 0,33 | 1,00 | 1,00 | 0,92 | 0,83 | 1,00 | 0,22 | 0,11 | 11,8 | 6.918 |  |
| [M10](perguntas/M10.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 0,29 | 0,95 | 1,00 | 0,21 | 0,08 | 12,7 | 10.503 |  |
| [M11](perguntas/M11.md) | mista | 0,00 | 0,00 | 0,00 | 0,83 | 1,00 | 0,87 | 1,00 | 0,29 | 0,13 | 8,1 | 5.748 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md), [M03](perguntas/M03.md), [M05](perguntas/M05.md), [M10](perguntas/M10.md), [M11](perguntas/M11.md)
- **Menor Faithfulness:** [L04](perguntas/L04.md) (0,60), [M02](perguntas/M02.md) (0,67), [C01](perguntas/C01.md) (0,69), [L06](perguntas/L06.md) (0,70), [S01](perguntas/S01.md) (0,76)
- **Menor Context Recall:** [C04](perguntas/C04.md) (0,33), [M05](perguntas/M05.md) (0,67), [S01](perguntas/S01.md) (0,80), [M03](perguntas/M03.md) (0,83), [M08](perguntas/M08.md) (0,83)
- **Menor acerto de valores:** [M05](perguntas/M05.md) (0,67), [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00), [L02](perguntas/L02.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M06](perguntas/M06.md) (0,17), [M02](perguntas/M02.md) (0,18), [M01](perguntas/M01.md) (0,20), [C04](perguntas/C04.md) (0,20), [M10](perguntas/M10.md) (0,21)

## Limitações

- **Uma rodada só e sem controle de temperatura:** o Claude Haiku 5.5 não aceita temperatura 0, então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz é o mesmo modelo do sistema.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Custo do juiz nesta rodada:** 207630 tokens de entrada e 92963 de saída (fora do bloco Custo, que mede só o sistema).

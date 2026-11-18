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
| Context Recall | 0,97 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,82 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 1,00 | 18 | fração dos números do gabarito presentes no contexto, no lugar certo (cadeia, escopo, métrica, entidade e ano) |
| Valor recuperado (critério solto) | 1,00 | 18 | número próximo em qualquer lugar do contexto (critério das rodadas anteriores) |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,89 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 1,00 | 18 | fração dos números do gabarito presentes na resposta, com a unidade |
| Acerto de valores (critério solto) | 1,00 | 18 | número próximo em qualquer lugar da resposta (critério das rodadas anteriores) |
| ROUGE-L F1 (ref. curta) | 0,14 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,29 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,04 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,16 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,905 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,960 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 9,6 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 31.340 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 30.227 | 20 |  |
| Tokens de saída (média) | 1.113 | 20 |  |
| Tokens de entrada lidos do cache (média) | 13.483 | 20 | parte da entrada servida pelo cache de prompt (já incluída na entrada) |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 0,90 | 0,80 | 1,00 | 0,74 | 0,91 | 1,00 | 0,30 | 0,95 | 0,17 | 7,8 |
| Carne bovina | 2 | — | — | — | 1,00 | 0,75 | 0,84 | 1,00 | 0,32 | 0,96 | 0,11 | 9,1 |
| Soja | 2 | — | — | — | 0,90 | 1,00 | 0,81 | 1,00 | 0,28 | 0,96 | 0,11 | 6,3 |
| Mista | 11 | 0,64 | 0,43 | 0,55 | 0,96 | 0,84 | 0,90 | 1,00 | 0,29 | 0,96 | 0,16 | 11,2 |
| **Geral** | 20 | 0,75 | 0,58 | 0,62 | 0,97 | 0,82 | 0,89 | 1,00 | 0,29 | 0,96 | 0,16 | 9,6 |

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
| curta | 0,08 | 0,75 | 0,14 | 0,04 | 0,04 | 0,905 |
| longa | 0,22 | 0,47 | 0,29 | 0,16 | 0,15 | 0,960 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,905 | 0,861 | 0,922 | 0,044 |
| longa | 0,960 | 0,899 | 0,956 | 0,061 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 10 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 0,67 | 1,00 | 1,00 | 0,31 | 0,16 | 0,97 | 5,2 | 26.001 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,93 | 1,00 | 0,28 | 0,17 | 0,95 | 5,7 | 25.439 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,61 | 0,94 | 1,00 | 0,26 | 0,11 | 0,95 | 14,9 | 49.023 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,73 | — | 0,41 | 0,31 | 0,95 | 3,5 | 24.692 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 0,50 | 1,00 | 1,00 | 0,44 | 0,94 | — | 0,26 | 0,15 | 0,95 | 9,9 | 28.444 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 0,80 | 1,00 | 0,85 | 1,00 | 0,24 | 0,12 | 0,96 | 5,8 | 23.970 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,77 | 1,00 | 0,31 | 0,11 | 0,96 | 6,8 | 35.844 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,93 | 1,00 | 0,31 | 0,12 | 0,97 | 6,1 | 24.186 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 1,00 | 0,50 | 0,75 | 1,00 | 0,32 | 0,11 | 0,96 | 12,0 | 37.240 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 1,00 | 0,79 | 1,00 | 0,30 | 0,15 | 0,97 | 13,2 | 29.668 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,33 | 1,00 | 1,00 | 1,00 | 0,94 | 1,00 | 0,24 | 0,11 | 0,95 | 11,2 | 27.470 |  |
| [M03](perguntas/M03.md) | mista | 0,00 | 0,00 | 0,00 | 0,86 | 0,83 | 0,90 | 1,00 | 0,28 | 0,18 | 0,95 | 9,8 | 26.746 |  |
| [M04](perguntas/M04.md) | mista | 1,00 | 0,25 | 0,50 | 1,00 | 0,70 | 1,00 | 1,00 | 0,34 | 0,22 | 0,97 | 7,8 | 26.427 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,62 | 1,00 | 1,00 | 0,35 | 0,17 | 0,97 | 11,8 | 43.823 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,83 | 0,84 | 1,00 | 0,25 | 0,10 | 0,95 | 3,7 | 26.879 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,92 | 0,94 | 1,00 | 0,34 | 0,20 | 0,97 | 8,4 | 26.588 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 0,50 | 0,83 | 1,00 | 0,93 | 1,00 | 0,35 | 0,23 | 0,97 | 6,9 | 26.321 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,84 | 0,85 | 1,00 | 0,26 | 0,15 | 0,97 | 16,4 | 44.991 |  |
| [M10](perguntas/M10.md) | mista | 1,00 | 0,20 | 1,00 | 0,83 | 0,75 | 0,95 | 1,00 | 0,25 | 0,13 | 0,97 | 13,2 | 44.097 |  |
| [M11](perguntas/M11.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,75 | 0,80 | 1,00 | 0,19 | 0,11 | 0,95 | 20,4 | 28.959 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md), [M03](perguntas/M03.md), [M05](perguntas/M05.md), [M11](perguntas/M11.md)
- **Menor Faithfulness:** [L06](perguntas/L06.md) (0,73), [C04](perguntas/C04.md) (0,75), [S05](perguntas/S05.md) (0,77), [M01](perguntas/M01.md) (0,79), [M11](perguntas/M11.md) (0,80)
- **Menor Context Recall:** [S01](perguntas/S01.md) (0,80), [M08](perguntas/M08.md) (0,83), [M10](perguntas/M10.md) (0,83), [M03](perguntas/M03.md) (0,86), [C01](perguntas/C01.md) (1,00)
- **Menor acerto de valores:** [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00), [L02](perguntas/L02.md) (1,00), [L04](perguntas/L04.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M11](perguntas/M11.md) (0,19), [S01](perguntas/S01.md) (0,24), [M02](perguntas/M02.md) (0,24), [M10](perguntas/M10.md) (0,25), [M06](perguntas/M06.md) (0,25)
- **Menor cosseno (ref. longa):** [L07](perguntas/L07.md) (0,95), [M06](perguntas/M06.md) (0,95), [L02](perguntas/L02.md) (0,95), [M03](perguntas/M03.md) (0,95), [L06](perguntas/L06.md) (0,95)

## Limitações

- **Uma rodada só e sem controle de temperatura:** temperatura padrão da API (o código não envia temperatura), então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Juiz diferente do agente:** juiz `anthropic/claude-haiku-5.5`, agente `deepseek/deepseek-v4.1-flash`. Isso reduz o viés de autoavaliação, mas as notas de rodadas com juízes diferentes não são diretamente comparáveis.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 292256 tokens de entrada e 108932 de saída (fora do bloco Custo, que mede só o sistema).

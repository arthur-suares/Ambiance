# Avaliação do RAG (2026-11-18)

20 perguntas · agente: `deepseek/deepseek-v4.1-flash` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o código não envia temperatura) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 1,00 | 16 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,90 | 16 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,94 | 16 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,97 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,87 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 1,00 | 18 | fração dos números do gabarito presentes no contexto, no lugar certo (cadeia, escopo, métrica, entidade e ano) |
| Valor recuperado (critério solto) | 1,00 | 18 | número próximo em qualquer lugar do contexto (critério das rodadas anteriores) |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,89 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 1,00 | 18 | fração dos números do gabarito presentes na resposta, com a unidade |
| Acerto de valores (critério solto) | 1,00 | 18 | número próximo em qualquer lugar da resposta (critério das rodadas anteriores) |
| ROUGE-L F1 (ref. curta) | 0,14 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,30 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,04 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,17 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,738 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,895 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 10,7 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 31.273 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 29.954 | 20 |  |
| Tokens de saída (média) | 1.318 | 20 |  |
| Tokens de entrada lidos do cache (média) | 12.224 | 20 | parte da entrada servida pelo cache de prompt (já incluída na entrada) |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 1,00 | 0,80 | 1,00 | 0,78 | 0,90 | 1,00 | 0,34 | 0,91 | 0,21 | 7,9 |
| Carne bovina | 2 | — | — | — | 1,00 | 1,00 | 0,88 | 1,00 | 0,27 | 0,85 | 0,10 | 5,4 |
| Soja | 2 | — | — | — | 1,00 | 1,00 | 0,89 | 1,00 | 0,30 | 0,89 | 0,12 | 6,2 |
| Mista | 11 | 1,00 | 0,85 | 1,00 | 0,95 | 0,86 | 0,89 | 1,00 | 0,29 | 0,90 | 0,16 | 13,8 |
| **Geral** | 20 | 1,00 | 0,90 | 0,94 | 0,97 | 0,87 | 0,89 | 1,00 | 0,30 | 0,89 | 0,17 | 10,7 |

## Busca nas leis por k (busca direta com a pergunta original)

| Métrica | Geral (n=16) | Lei (n=5) | Mista (n=11) |
|---|---|---|---|
| Hit@1 | 0,81 | 1,00 | 0,73 |
| Hit@3 | 1,00 | 1,00 | 1,00 |
| Hit@5 | 1,00 | 1,00 | 1,00 |
| Hit@10 | 1,00 | 1,00 | 1,00 |
| Recall@1 | 0,62 | 0,60 | 0,64 |
| Recall@3 | 0,91 | 0,80 | 0,95 |
| Recall@5 | 0,94 | 0,80 | 1,00 |
| Recall@10 | 0,97 | 0,90 | 1,00 |
| MRR | 0,90 | 1,00 | 0,85 |

## ROUGE-L, BLEU e cosseno em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) | Cosseno |
|---|---|---|---|---|---|---|
| curta | 0,08 | 0,76 | 0,14 | 0,04 | 0,04 | 0,738 |
| longa | 0,23 | 0,48 | 0,30 | 0,17 | 0,17 | 0,895 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,738 | 0,507 | 0,735 | 0,231 |
| longa | 0,895 | 0,567 | 0,812 | 0,327 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 0 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 0,70 | 1,00 | 1,00 | 0,33 | 0,25 | 0,89 | 5,3 | 26.783 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,86 | 1,00 | 0,34 | 0,27 | 0,88 | 6,1 | 25.934 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,57 | 0,81 | 1,00 | 0,27 | 0,12 | 0,92 | 17,6 | 51.613 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,64 | 0,82 | — | 0,35 | 0,20 | 0,94 | 6,5 | 26.585 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | — | 0,41 | 0,28 | 0,94 | 4,1 | 25.512 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 1,00 | 1,00 | 1,00 | 1,00 | 0,34 | 0,17 | 0,87 | 5,0 | 24.395 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,78 | 1,00 | 0,25 | 0,08 | 0,90 | 7,3 | 24.415 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,92 | 1,00 | 0,24 | 0,10 | 0,78 | 4,7 | 25.013 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 1,00 | 1,00 | 0,85 | 1,00 | 0,29 | 0,09 | 0,92 | 6,0 | 24.856 |  |
| [M01](perguntas/M01.md) | mista | 1,00 | 0,50 | 1,00 | 1,00 | 0,87 | 0,94 | 1,00 | 0,28 | 0,15 | 0,88 | 19,7 | 32.644 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,87 | 1,00 | 0,29 | 0,15 | 0,90 | 16,5 | 29.366 |  |
| [M03](perguntas/M03.md) | mista | 1,00 | 1,00 | 1,00 | 0,83 | 0,83 | 0,76 | 1,00 | 0,26 | 0,15 | 0,82 | 13,0 | 29.518 |  |
| [M04](perguntas/M04.md) | mista | 1,00 | 0,50 | 1,00 | 1,00 | 0,75 | 1,00 | 1,00 | 0,34 | 0,20 | 0,91 | 10,3 | 28.821 |  |
| [M05](perguntas/M05.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,62 | 0,85 | 1,00 | 0,28 | 0,16 | 0,89 | 9,3 | 45.364 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,92 | 1,00 | 0,30 | 0,14 | 0,91 | 9,3 | 27.906 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,62 | 1,00 | 0,38 | 0,20 | 0,96 | 9,3 | 28.812 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 1,00 | 0,83 | 1,00 | 1,00 | 1,00 | 0,30 | 0,21 | 0,88 | 11,8 | 27.779 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,88 | 1,00 | 0,30 | 0,14 | 0,94 | 21,1 | 30.265 |  |
| [M10](perguntas/M10.md) | mista | 1,00 | 0,33 | 1,00 | 0,83 | 0,60 | 1,00 | 1,00 | 0,26 | 0,13 | 0,89 | 15,5 | 45.952 |  |
| [M11](perguntas/M11.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,83 | 0,92 | 1,00 | 0,25 | 0,16 | 0,88 | 15,9 | 43.920 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** nenhum
- **Menor Faithfulness:** [M07](perguntas/M07.md) (0,62), [M03](perguntas/M03.md) (0,76), [S05](perguntas/S05.md) (0,78), [L04](perguntas/L04.md) (0,81), [L06](perguntas/L06.md) (0,82)
- **Menor Context Recall:** [M03](perguntas/M03.md) (0,83), [M08](perguntas/M08.md) (0,83), [M10](perguntas/M10.md) (0,83), [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00)
- **Menor acerto de valores:** [C01](perguntas/C01.md) (1,00), [C04](perguntas/C04.md) (1,00), [L01](perguntas/L01.md) (1,00), [L02](perguntas/L02.md) (1,00), [L04](perguntas/L04.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [C01](perguntas/C01.md) (0,24), [S05](perguntas/S05.md) (0,25), [M11](perguntas/M11.md) (0,25), [M10](perguntas/M10.md) (0,26), [M03](perguntas/M03.md) (0,26)
- **Menor cosseno (ref. longa):** [C01](perguntas/C01.md) (0,78), [M03](perguntas/M03.md) (0,82), [S01](perguntas/S01.md) (0,87), [M08](perguntas/M08.md) (0,88), [M01](perguntas/M01.md) (0,88)

## Limitações

- **Uma rodada só e sem controle de temperatura:** temperatura padrão da API (o código não envia temperatura), então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Juiz diferente do agente:** juiz `anthropic/claude-haiku-5.5`, agente `deepseek/deepseek-v4.1-flash`. Isso reduz o viés de autoavaliação, mas as notas de rodadas com juízes diferentes não são diretamente comparáveis.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 257512 tokens de entrada e 105612 de saída (fora do bloco Custo, que mede só o sistema).

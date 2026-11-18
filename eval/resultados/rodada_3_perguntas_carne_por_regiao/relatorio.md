# Avaliação do RAG (2026-11-18)

3 perguntas · agente: `anthropic/claude-haiku-5.5` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o código não envia temperatura) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,67 | 3 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,44 | 3 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,67 | 3 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 1,00 | 3 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,96 | 3 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 1,00 | 3 | fração dos números do gabarito presentes no contexto, no lugar certo (cadeia, escopo, métrica, entidade e ano) |
| Valor recuperado (critério solto) | 1,00 | 3 | número próximo em qualquer lugar do contexto (critério das rodadas anteriores) |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,85 | 3 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 1,00 | 3 | fração dos números do gabarito presentes na resposta, com a unidade |
| Acerto de valores (critério solto) | 1,00 | 3 | número próximo em qualquer lugar da resposta (critério das rodadas anteriores) |
| ROUGE-L F1 (ref. curta) | 0,13 | 3 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,30 | 3 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,04 | 3 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,14 | 3 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,933 | 3 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,973 | 3 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 10,2 | 3 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 7.687 | 3 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 5.766 | 3 |  |
| Tokens de saída (média) | 1.921 | 3 |  |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Mista | 3 | 0,67 | 0,44 | 0,67 | 1,00 | 0,96 | 0,85 | 1,00 | 0,30 | 0,97 | 0,14 | 10,2 |
| **Geral** | 3 | 0,67 | 0,44 | 0,67 | 1,00 | 0,96 | 0,85 | 1,00 | 0,30 | 0,97 | 0,14 | 10,2 |

## Busca nas leis por k (busca direta com a pergunta original)

| Métrica | Geral (n=3) | Lei (n=0) | Mista (n=3) |
|---|---|---|---|
| Hit@1 | 0,33 | — | 0,33 |
| Hit@3 | 0,67 | — | 0,67 |
| Hit@5 | 0,67 | — | 0,67 |
| Hit@10 | 0,67 | — | 0,67 |
| Recall@1 | 0,50 | — | 0,50 |
| Recall@3 | 0,67 | — | 0,67 |
| Recall@5 | 0,67 | — | 0,67 |
| Recall@10 | 0,67 | — | 0,67 |
| MRR | 0,44 | — | 0,44 |

## ROUGE-L, BLEU e cosseno em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) | Cosseno |
|---|---|---|---|---|---|---|
| curta | 0,07 | 0,67 | 0,13 | 0,04 | 0,03 | 0,933 |
| longa | 0,23 | 0,43 | 0,30 | 0,14 | 0,14 | 0,973 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,933 | 0,912 | 0,926 | 0,021 |
| longa | 0,973 | 0,943 | 0,952 | 0,030 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 2 de 3; referências longas cortadas: 0 de 3. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,89 | 0,88 | 1,00 | 0,27 | 0,13 | 0,97 | 9,8 | 8.578 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,33 | 1,00 | 1,00 | 1,00 | 0,81 | 1,00 | 0,28 | 0,11 | 0,97 | 9,8 | 7.500 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,87 | 1,00 | 0,34 | 0,19 | 0,98 | 11,1 | 6.984 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md)
- **Menor Faithfulness:** [M02](perguntas/M02.md) (0,81), [M09](perguntas/M09.md) (0,87), [M01](perguntas/M01.md) (0,88)
- **Menor Context Recall:** [M01](perguntas/M01.md) (1,00), [M02](perguntas/M02.md) (1,00), [M09](perguntas/M09.md) (1,00)
- **Menor acerto de valores:** [M01](perguntas/M01.md) (1,00), [M02](perguntas/M02.md) (1,00), [M09](perguntas/M09.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M01](perguntas/M01.md) (0,27), [M02](perguntas/M02.md) (0,28), [M09](perguntas/M09.md) (0,34)
- **Menor cosseno (ref. longa):** [M01](perguntas/M01.md) (0,97), [M02](perguntas/M02.md) (0,97), [M09](perguntas/M09.md) (0,98)

## Limitações

- **Uma rodada só e sem controle de temperatura:** temperatura padrão da API (o código não envia temperatura), então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz (`anthropic/claude-haiku-5.5`) é o mesmo modelo do agente.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 49269 tokens de entrada e 19215 de saída (fora do bloco Custo, que mede só o sistema).

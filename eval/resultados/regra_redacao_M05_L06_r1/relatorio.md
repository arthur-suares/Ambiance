# Avaliação do RAG (2026-11-18)

2 perguntas · agente: `anthropic/claude-haiku-5.5` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o código não envia temperatura) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,50 | 2 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,50 | 2 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,50 | 2 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,90 | 2 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,37 | 2 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 0,67 | 1 | fração dos números do gabarito presentes no contexto, no lugar certo (cadeia, escopo, métrica, entidade e ano) |
| Valor recuperado (critério solto) | 0,67 | 1 | número próximo em qualquer lugar do contexto (critério das rodadas anteriores) |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,83 | 2 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 0,67 | 1 | fração dos números do gabarito presentes na resposta, com a unidade |
| Acerto de valores (critério solto) | 0,67 | 1 | número próximo em qualquer lugar da resposta (critério das rodadas anteriores) |
| ROUGE-L F1 (ref. curta) | 0,23 | 2 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,35 | 2 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,07 | 2 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,21 | 2 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,908 | 2 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,963 | 2 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 7,9 | 2 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 49.488 | 2 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 48.288 | 2 |  |
| Tokens de saída (média) | 1.200 | 2 |  |
| Tokens de entrada lidos do cache (média) | 24.718 | 2 | parte da entrada servida pelo cache de prompt (já incluída na entrada) |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 1 | 1,00 | 1,00 | 1,00 | 1,00 | 0,63 | 0,82 | — | 0,36 | 0,97 | 0,21 | 7,0 |
| Mista | 1 | 0,00 | 0,00 | 0,00 | 0,80 | 0,10 | 0,83 | 0,67 | 0,34 | 0,96 | 0,20 | 8,8 |
| **Geral** | 2 | 0,50 | 0,50 | 0,50 | 0,90 | 0,37 | 0,83 | 0,67 | 0,35 | 0,96 | 0,21 | 7,9 |

## Busca nas leis por k (busca direta com a pergunta original)

| Métrica | Geral (n=2) | Lei (n=1) | Mista (n=1) |
|---|---|---|---|
| Hit@1 | 0,50 | 1,00 | 0,00 |
| Hit@3 | 0,50 | 1,00 | 0,00 |
| Hit@5 | 0,50 | 1,00 | 0,00 |
| Hit@10 | 0,50 | 1,00 | 0,00 |
| Recall@1 | 0,25 | 0,50 | 0,00 |
| Recall@3 | 0,50 | 1,00 | 0,00 |
| Recall@5 | 0,50 | 1,00 | 0,00 |
| Recall@10 | 0,50 | 1,00 | 0,00 |
| MRR | 0,50 | 1,00 | 0,00 |

## ROUGE-L, BLEU e cosseno em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) | Cosseno |
|---|---|---|---|---|---|---|
| curta | 0,14 | 0,77 | 0,23 | 0,07 | 0,08 | 0,908 |
| longa | 0,30 | 0,42 | 0,35 | 0,21 | 0,20 | 0,963 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,908 | 0,852 | 0,869 | 0,056 |
| longa | 0,963 | 0,884 | 0,890 | 0,079 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 0 de 2; referências longas cortadas: 0 de 2. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,63 | 0,82 | — | 0,36 | 0,21 | 0,97 | 7,0 | 36.505 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 0,80 | 0,10 | 0,83 | 0,67 | 0,34 | 0,20 | 0,96 | 8,8 | 62.470 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M05](perguntas/M05.md)
- **Menor Faithfulness:** [L06](perguntas/L06.md) (0,82), [M05](perguntas/M05.md) (0,83)
- **Menor Context Recall:** [M05](perguntas/M05.md) (0,80), [L06](perguntas/L06.md) (1,00)
- **Menor acerto de valores:** [M05](perguntas/M05.md) (0,67)
- **Menor ROUGE-L F1 (ref. longa):** [M05](perguntas/M05.md) (0,34), [L06](perguntas/L06.md) (0,36)
- **Menor cosseno (ref. longa):** [M05](perguntas/M05.md) (0,96), [L06](perguntas/L06.md) (0,97)

## Limitações

- **Uma rodada só e sem controle de temperatura:** temperatura padrão da API (o código não envia temperatura), então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz (`anthropic/claude-haiku-5.5`) é o mesmo modelo do agente.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 26703 tokens de entrada e 8955 de saída (fora do bloco Custo, que mede só o sistema).

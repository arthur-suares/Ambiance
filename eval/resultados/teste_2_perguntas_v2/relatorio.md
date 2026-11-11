# Avaliação do RAG (2026-11-11)

2 perguntas · agente: `anthropic/claude-haiku-5.5` · juiz: `anthropic/claude-haiku-5.5` · temperatura: padrão da API (o Claude Haiku 5.5 não aceita temperatura 0) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,50 | 2 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,50 | 2 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,25 | 2 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 1,00 | 2 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,75 | 2 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 1,00 | 2 | fração dos números do gabarito presentes no contexto |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,84 | 2 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 1,00 | 2 | fração dos números do gabarito presentes na resposta |
| ROUGE-L F1 (ref. curta) | 0,15 | 2 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,23 | 2 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,03 | 2 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,07 | 2 | n-gramas (1 a 4) em comum, somados no grupo |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 11,5 | 2 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 6.732 | 2 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 4.835 | 2 |  |
| Tokens de saída (média) | 1.897 | 2 |  |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 1 | 1,00 | 1,00 | 0,50 | 1,00 | 0,83 | 0,91 | 1,00 | 0,28 | 0,11 | 8,7 |
| Mista | 1 | 0,00 | 0,00 | 0,00 | 1,00 | 0,67 | 0,77 | 1,00 | 0,18 | 0,04 | 14,3 |
| **Geral** | 2 | 0,50 | 0,50 | 0,25 | 1,00 | 0,75 | 0,84 | 1,00 | 0,23 | 0,07 | 11,5 |

## Busca nas leis por k (busca direta com a pergunta original)

| Métrica | Geral (n=2) | Lei (n=1) | Mista (n=1) |
|---|---|---|---|
| Hit@1 | 0,50 | 1,00 | 0,00 |
| Hit@3 | 0,50 | 1,00 | 0,00 |
| Hit@5 | 0,50 | 1,00 | 0,00 |
| Hit@10 | 0,50 | 1,00 | 0,00 |
| Recall@1 | 0,25 | 0,50 | 0,00 |
| Recall@3 | 0,25 | 0,50 | 0,00 |
| Recall@5 | 0,25 | 0,50 | 0,00 |
| Recall@10 | 0,50 | 1,00 | 0,00 |
| MRR | 0,50 | 1,00 | 0,00 |

## ROUGE-L e BLEU em detalhe

| Referência | ROUGE-L P | ROUGE-L R | ROUGE-L F1 | BLEU de corpus | BLEU médio por pergunta (suavizado) |
|---|---|---|---|---|---|
| curta | 0,08 | 0,77 | 0,15 | 0,03 | 0,03 |
| longa | 0,15 | 0,53 | 0,23 | 0,07 | 0,07 |

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 0,83 | 0,91 | 1,00 | 0,28 | 0,11 | 8,7 | 6.091 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,67 | 0,77 | 1,00 | 0,18 | 0,04 | 14,3 | 7.373 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md)
- **Menor Faithfulness:** [M01](perguntas/M01.md) (0,77), [L01](perguntas/L01.md) (0,91)
- **Menor Context Recall:** [L01](perguntas/L01.md) (1,00), [M01](perguntas/M01.md) (1,00)
- **Menor acerto de valores:** [L01](perguntas/L01.md) (1,00), [M01](perguntas/M01.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M01](perguntas/M01.md) (0,18), [L01](perguntas/L01.md) (0,28)

## Limitações

- **Uma rodada só e sem controle de temperatura:** o Claude Haiku 5.5 não aceita temperatura 0, então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz é o mesmo modelo do sistema.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Custo do juiz nesta rodada:** 26689 tokens de entrada e 12048 de saída (fora do bloco Custo, que mede só o sistema).

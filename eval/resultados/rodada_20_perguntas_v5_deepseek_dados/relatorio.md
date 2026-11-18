# Avaliação do RAG (2026-11-16)

20 perguntas · agente: `deepseek/deepseek-v4.1-flash` · juiz: `deepseek/deepseek-v4.1-flash` · temperatura: padrão da API (o Claude Haiku 5.5 não aceita temperatura 0) · embeddings: `intfloat/multilingual-e5-small`

Todas as médias são simples (média das perguntas). O BLEU de corpus é a exceção: soma as contagens de todas as respostas do grupo antes de aplicar a fórmula. `n` = número de perguntas em que a métrica se aplica.

## Painel

### Recuperação: o sistema buscou o que precisava?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Hit@5 | 0,75 | 16 | o artigo essencial está entre os 5 primeiros da busca direta? |
| MRR | 0,58 | 16 | 1/posição do primeiro artigo essencial (busca direta) |
| Recall@5 | 0,62 | 16 | fração dos artigos do gabarito (essenciais + complementares) no top-5 |
| Context Recall | 0,93 | 20 | fração das afirmações da referência presentes no contexto do agente (juiz) |
| Context Precision | 0,92 | 20 | itens úteis do contexto e se vieram primeiro (juiz) |
| Valor recuperado | 0,91 | 18 | fração dos números do gabarito presentes no contexto, no lugar certo (cadeia, escopo, métrica, entidade e ano) |
| Valor recuperado (critério solto) | 0,91 | 18 | número próximo em qualquer lugar do contexto (critério das rodadas anteriores) |

### Geração: a resposta está certa e apoiada no que foi buscado?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Faithfulness | 0,95 | 20 | fração das afirmações da resposta sustentadas pelo contexto (juiz) |
| Acerto de valores | 0,91 | 18 | fração dos números do gabarito presentes na resposta, com a unidade |
| Acerto de valores (critério solto) | 0,91 | 18 | número próximo em qualquer lugar da resposta (critério das rodadas anteriores) |
| ROUGE-L F1 (ref. curta) | 0,14 | 20 | sobreposição de palavras em ordem com a referência curta |
| ROUGE-L F1 (ref. longa) | 0,30 | 20 | sobreposição de palavras em ordem com a referência longa |
| BLEU de corpus (ref. curta) | 0,04 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| BLEU de corpus (ref. longa) | 0,15 | 20 | n-gramas (1 a 4) em comum, somados no grupo |
| Cosseno (ref. curta) | 0,903 | 20 | semelhança de significado (embeddings) com a referência curta |
| Cosseno (ref. longa) | 0,957 | 20 | semelhança de significado (embeddings) com a referência longa |

### Custo: quanto custa responder?

| Métrica | Valor | n | O que mede |
|---|---|---|---|
| Latência média (s) | 6,6 | 20 | tempo do agente da pergunta à resposta final |
| Tokens médios por pergunta | 15.930 | 20 | entrada + saída do agente (soma de todos os turnos) |
| Tokens de entrada (média) | 15.121 | 20 |  |
| Tokens de saída (média) | 809 | 20 |  |

## Resultados por tipo de pergunta

| Tipo | n | Hit@5 | MRR | Recall@5 | Context Recall | Context Precision | Faithfulness | Acerto de valores | ROUGE-L F1 (longa) | Cosseno (longa) | BLEU corpus (longa) | Latência (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lei | 5 | 1,00 | 0,90 | 0,80 | 1,00 | 0,92 | 0,96 | 1,00 | 0,34 | 0,96 | 0,19 | 6,7 |
| Carne bovina | 2 | — | — | — | 1,00 | 1,00 | 0,89 | 1,00 | 0,30 | 0,95 | 0,10 | 5,5 |
| Soja | 2 | — | — | — | 1,00 | 1,00 | 0,94 | 1,00 | 0,34 | 0,96 | 0,20 | 4,6 |
| Mista | 11 | 0,64 | 0,43 | 0,55 | 0,87 | 0,89 | 0,96 | 0,86 | 0,28 | 0,96 | 0,14 | 7,0 |
| **Geral** | 20 | 0,75 | 0,58 | 0,62 | 0,93 | 0,92 | 0,95 | 0,91 | 0,30 | 0,96 | 0,15 | 6,6 |

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
| curta | 0,08 | 0,72 | 0,14 | 0,04 | 0,04 | 0,903 |
| longa | 0,23 | 0,45 | 0,30 | 0,15 | 0,16 | 0,957 |

**Como ler o cosseno.** O e5-small dá notas altas até para textos sem relação, então o número só diz algo quando comparado com uma linha de base: o cosseno médio de cada resposta com as referências das outras perguntas.

| Referência | Cosseno com a referência da própria pergunta (média) | Cosseno com referências de outras perguntas (média) | Maior cosseno com outra pergunta | Diferença |
|---|---|---|---|---|
| curta | 0,902 | 0,857 | 0,928 | 0,046 |
| longa | 0,957 | 0,895 | 0,957 | 0,061 |

Respostas do agente cortadas no limite de 512 tokens do modelo: 7 de 20; referências longas cortadas: 0 de 20. O que passa do limite não entra no cosseno.

## Resultados por pergunta

Clique no ID para ver a trilha completa (cada etapa da pergunta).

| ID | Tipo | Hit@5 | MRR | Recall@5 | Ctx Recall | Ctx Precision | Faithfulness | Valores | ROUGE-L F1 (longa) | BLEU (longa) | Cosseno (longa) | Tempo (s) | Tokens | Erros |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [L01](perguntas/L01.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 0,93 | 1,00 | 0,31 | 0,16 | 0,95 | 6,8 | 25.821 |  |
| [L02](perguntas/L02.md) | lei | 1,00 | 1,00 | 0,50 | 1,00 | 1,00 | 1,00 | 1,00 | 0,38 | 0,25 | 0,95 | 4,3 | 24.112 |  |
| [L04](perguntas/L04.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 0,61 | 1,00 | 1,00 | 0,27 | 0,13 | 0,96 | 8,6 | 22.652 |  |
| [L06](perguntas/L06.md) | lei | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,86 | — | 0,34 | 0,20 | 0,96 | 5,9 | 7.354 |  |
| [L07](perguntas/L07.md) | lei | 1,00 | 0,50 | 1,00 | 1,00 | 1,00 | 1,00 | — | 0,42 | 0,32 | 0,97 | 7,8 | 19.152 |  |
| [S01](perguntas/S01.md) | soja | — | — | — | 1,00 | 1,00 | 1,00 | 1,00 | 0,34 | 0,22 | 0,97 | 5,8 | 11.681 |  |
| [S05](perguntas/S05.md) | soja | — | — | — | 1,00 | 1,00 | 0,89 | 1,00 | 0,33 | 0,16 | 0,95 | 3,3 | 6.263 |  |
| [C01](perguntas/C01.md) | carne | — | — | — | 1,00 | 1,00 | 0,94 | 1,00 | 0,34 | 0,13 | 0,96 | 5,8 | 17.720 |  |
| [C04](perguntas/C04.md) | carne | — | — | — | 1,00 | 1,00 | 0,84 | 1,00 | 0,26 | 0,08 | 0,95 | 5,2 | 12.321 |  |
| [M01](perguntas/M01.md) | mista | 0,00 | 0,00 | 0,00 | 0,67 | 1,00 | 0,88 | 0,75 | 0,24 | 0,10 | 0,95 | 10,7 | 22.397 |  |
| [M02](perguntas/M02.md) | mista | 1,00 | 0,33 | 1,00 | 1,00 | 1,00 | 1,00 | 0,67 | 0,27 | 0,09 | 0,96 | 6,8 | 9.719 |  |
| [M03](perguntas/M03.md) | mista | 0,00 | 0,00 | 0,00 | 0,75 | 0,83 | 0,91 | 1,00 | 0,30 | 0,19 | 0,95 | 6,3 | 25.430 |  |
| [M04](perguntas/M04.md) | mista | 1,00 | 0,25 | 0,50 | 1,00 | 0,75 | 1,00 | 1,00 | 0,30 | 0,16 | 0,96 | 6,8 | 9.129 |  |
| [M05](perguntas/M05.md) | mista | 0,00 | 0,00 | 0,00 | 0,50 | 1,00 | 1,00 | 0,33 | 0,22 | 0,09 | 0,95 | 6,7 | 9.051 |  |
| [M06](perguntas/M06.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,83 | 1,00 | 1,00 | 0,22 | 0,08 | 0,94 | 5,4 | 20.609 |  |
| [M07](perguntas/M07.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 0,92 | 1,00 | 0,40 | 0,23 | 0,96 | 6,5 | 8.659 |  |
| [M08](perguntas/M08.md) | mista | 1,00 | 1,00 | 0,50 | 0,80 | 1,00 | 1,00 | 1,00 | 0,33 | 0,19 | 0,96 | 10,4 | 26.207 |  |
| [M09](perguntas/M09.md) | mista | 1,00 | 1,00 | 1,00 | 1,00 | 0,83 | 1,00 | 0,67 | 0,25 | 0,16 | 0,96 | 7,2 | 9.769 |  |
| [M10](perguntas/M10.md) | mista | 1,00 | 0,20 | 1,00 | 0,80 | 0,75 | 1,00 | 1,00 | 0,29 | 0,15 | 0,97 | 6,7 | 19.929 |  |
| [M11](perguntas/M11.md) | mista | 0,00 | 0,00 | 0,00 | 1,00 | 0,83 | 0,88 | 1,00 | 0,23 | 0,12 | 0,96 | 4,1 | 10.634 |  |

## Piores casos

- **Artigo essencial fora do top-10 da busca direta:** [M01](perguntas/M01.md), [M03](perguntas/M03.md), [M05](perguntas/M05.md), [M11](perguntas/M11.md)
- **Menor Faithfulness:** [C04](perguntas/C04.md) (0,84), [L06](perguntas/L06.md) (0,86), [M11](perguntas/M11.md) (0,88), [M01](perguntas/M01.md) (0,88), [S05](perguntas/S05.md) (0,89)
- **Menor Context Recall:** [M05](perguntas/M05.md) (0,50), [M01](perguntas/M01.md) (0,67), [M03](perguntas/M03.md) (0,75), [M08](perguntas/M08.md) (0,80), [M10](perguntas/M10.md) (0,80)
- **Menor acerto de valores:** [M05](perguntas/M05.md) (0,33), [M02](perguntas/M02.md) (0,67), [M09](perguntas/M09.md) (0,67), [M01](perguntas/M01.md) (0,75), [C01](perguntas/C01.md) (1,00)
- **Menor ROUGE-L F1 (ref. longa):** [M05](perguntas/M05.md) (0,22), [M06](perguntas/M06.md) (0,22), [M11](perguntas/M11.md) (0,23), [M01](perguntas/M01.md) (0,24), [M09](perguntas/M09.md) (0,25)
- **Menor cosseno (ref. longa):** [M06](perguntas/M06.md) (0,94), [S05](perguntas/S05.md) (0,95), [L01](perguntas/L01.md) (0,95), [M05](perguntas/M05.md) (0,95), [L02](perguntas/L02.md) (0,95)

## Limitações

- **Uma rodada só e sem controle de temperatura:** o Claude Haiku 5.5 não aceita temperatura 0, então o agente e o juiz podem dar respostas e notas um pouco diferentes se a avaliação for repetida. A busca direta (Hit/Recall/MRR) não usa LLM e é reprodutível.
- **Viés de autoavaliação:** o juiz é o mesmo modelo do sistema.
- **Poucas perguntas por tipo:** carne bovina e soja têm 2 perguntas cada; as médias desses tipos são instáveis.
- **Relevância anotada à mão:** os artigos essenciais/complementares do gabarito definem Hit, Recall e MRR.
- **Busca direta ≠ busca do agente:** Hit/Recall/MRR usam a pergunta original; o agente escreve o próprio texto de busca e escolhe o k (ver seção 3 de cada trilha).
- **ROUGE-L e BLEU medem palavras, não significado:** uma resposta correta com outra redação recebe nota baixa; por isso são complemento do juiz, não substituto.
- **Cosseno do e5-small tem faixa estreita e limite de 512 tokens:** textos sem relação também recebem notas altas (ver a linha de base) e respostas mais longas que o limite são cortadas. Serve para comparar perguntas e rodadas, não como nota absoluta. Números errados mudam pouco o cosseno: quem confere os valores é o acerto de valores.
- **Custo do juiz nesta rodada:** 175028 tokens de entrada e 56475 de saída (fora do bloco Custo, que mede só o sistema).

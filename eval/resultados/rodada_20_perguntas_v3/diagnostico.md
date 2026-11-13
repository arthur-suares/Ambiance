# Diagnóstico da rodada: por que as perguntas mistas vão pior e por que Hit, Recall e MRR estão baixos

Base: as respostas e o contexto da `rodada_20_perguntas_v2` (as mesmas da v3; a v3 só refez ROUGE-L, BLEU e cosseno) e o experimento de busca `diagnostico_busca.json`, gerado por `python -m eval.diagnostico_busca eval/resultados/rodada_20_perguntas_v2 eval/resultados/rodada_20_perguntas_v3/diagnostico_busca.json` (não usa LLM). Nada no sistema foi alterado.

## 1. Resumo

1. **Hit, Recall e MRR só ficam baixos nas perguntas mistas.** Nas 5 de lei, a busca acerta o artigo essencial em 1º lugar todas as vezes (Hit@5 = 1,00, MRR = 1,00). As 11 mistas puxam a média geral para baixo (Hit@5 = 0,45, MRR = 0,34).
2. **A causa principal é a pergunta mista inteira ser usada como texto de busca.** A parte de dados dilui a busca, e a parte de palavras-chave do "híbrido" quase nunca encontra nada. Se a busca usar só a metade de lei da pergunta, Hit@5 vai de 0,45 para 0,73 e o MRR de 0,34 para 0,60.
3. **O agente compensa em boa parte.** Ele escreve a própria busca, e a primeira busca dele já trouxe o artigo essencial em 14 das 16 perguntas; com uma segunda tentativa, em 15. A exceção é o M05, onde nenhuma das duas buscas trouxe o art. 12.
4. **Nas mistas, o que mais prejudica as notas finais é outra coisa:** a escolha da métrica de dados (M04 e M05), o excesso de itens no contexto (Context Precision) e alegações que o juiz não consegue conferir porque vêm do prompt do sistema (Faithfulness).

## 2. Por que Hit, Recall e MRR parecem baixos

| Grupo | Busca | Hit@5 | Hit@10 | MRR |
|---|---|---|---|---|
| Lei (5) | pergunta inteira | 1,00 | 1,00 | 1,00 |
| Mista (11) | pergunta inteira (é o que a avaliação mede) | 0,45 | 0,55 | 0,34 |
| Mista (11) | só a metade de lei da pergunta | 0,73 | 0,82 | 0,60 |
| Geral (16) | pergunta inteira | 0,62 | 0,69 | 0,54 |

O geral é só a média ponderada: (5 × 1,00 + 11 × 0,34) / 16 = 0,54 de MRR.

**Recall@5 = 0,80 nas perguntas de lei** não é falha de busca. O artigo essencial veio em 1º lugar em todas. O Recall perde porque o artigo complementar fica fora do top-5: o art. 3 do Código Florestal veio em 6º no L01 e nem entrou no top-10 no L02. Isso é o efeito, esperado, de contar os complementares no Recall.

**Causas nas mistas** (posição do artigo essencial, busca direta → só com a metade de lei → primeira busca do agente):

| ID | Busca direta (pergunta inteira) | Só a metade de lei | 1ª busca do agente |
|---|---|---|---|
| M01 | 17º (fora do top-10) | não aparece | não aparece (achou na 2ª) |
| M02 | 4º | 1º | 1º |
| M03 | 53º (fora dos 40 candidatos) | 5º | 2º |
| M04 | 9º | 9º | 5º |
| M05 | 23º (fora do top-10) | 3º | não aparece (nem na 2ª) |
| M06 | 1º | 1º | 2º |
| M07 | 1º | 1º | 1º |
| M08 | 1º | 1º | 1º |
| M09 | 3º | 1º | 1º |
| M10 | 39º (fora do top-10) | não aparece | 2º |
| M11 | 49º (fora dos 40 candidatos) | 1º | 1º |

1. **A parte de dados dilui a busca por significado.** Em M02, M03, M05, M09 e M11 o artigo sobe muito quando a parte de dados sai da consulta (M11: do 49º para o 1º; M03: do 53º para o 5º).
2. **A busca por palavras-chave quase não participa.** Ela usa `websearch_to_tsquery`, que só devolve trechos que contenham todas as palavras da consulta. Com a pergunta inteira, 15 das 16 consultas não casaram com nenhum trecho (só a L04 casou com 1). Mesmo com a metade de lei, 7 das 11 não casaram com nenhum. Na prática, a busca "híbrida" funciona só por significado, e a fusão (RRF) quase não acrescenta nada.
3. **Artigos quase iguais se confundem.** O art. 51 do Decreto 6.514 (multa dentro da reserva legal) e o art. 52 (fora dela) têm texto parecido. No M10, mesmo com a pergunta só de lei, o art. 52 vem na frente e o 51 não aparece. No M03, o art. 52 e o 55 vêm antes do 51.
4. **A parte de lei às vezes depende da parte de dados.** O M01 pergunta "o que o Código Florestal exige de reserva legal nesses biomas?". Sem a primeira metade, "nesses biomas" não diz nada, e a busca só com a metade de lei também falha.
5. **O M04 é fraqueza de significado, não de diluição.** O art. 11 da Lei da Mata Atlântica fica em 9º com a pergunta inteira e com a metade de lei. A lei tem vários artigos sobre vegetação que competem com ele.

**Limite do que a avaliação mede.** Hit, Recall e MRR usam a pergunta original como texto de busca, e o agente não busca assim: ele reescreve a consulta e pode buscar de novo. Por isso essas três métricas mostram a qualidade da busca bruta, não do sistema. Quem mede o que o agente de fato recuperou é o Context Recall (0,89).

## 3. Por que as mistas vão pior (todas as métricas)

Médias por tipo (v3): Context Recall 0,82 (lei 1,00), Context Precision 0,66 (lei 0,90), acerto de valores 0,82 (lei 1,00), Faithfulness 0,83 (lei 0,87), tokens por pergunta 8.258 (lei 3.877) e 2,8 chamadas de ferramenta (lei 1,0).

1. **Busca de lei com a pergunta inteira** (seção 2). Afeta Hit, Recall e MRR.
2. **Escolha errada da métrica de dados (M04 e M05).** Os dois perdem todos os valores de dados. O agente usou `soy_territorial_metric` (indicador da região inteira) em vez de `soy_deforestation_by_biome` / `soy_yearly_trend` (exposição da cadeia, que é o que a descrição das ferramentas e a pergunta sugerem). No M04 trouxe 46.677,7 ha em vez de 49.590,25 ha; no M05, 140,1 Mt em vez de 121,1 Mt. É o único motivo da queda do acerto de valores de 1,00 para 0,82 nas mistas (os demais valores estão certos), e o M05 também perde os 2 valores da lei por causa da busca.
3. **Contexto com muito item inútil (Context Precision).** A busca de lei do agente sempre devolve 6 trechos e, em média, só 1 ou 2 são úteis. Nas mistas, ainda há chamadas de dados extras que o juiz considera inúteis (`territorial_metric` no M01, M02 e M09). Mistas têm em média 8,5 itens de contexto contra 6 nas de lei e 1 a 1,5 nas de dados.
4. **Alegações do prompt que o juiz não confere (Faithfulness).** Das 48 afirmações marcadas como sem apoio nas 20 perguntas, cerca de 27 são ressalvas de metodologia ou conhecimento do prompt do sistema (janela de 5 anos, "exposição não prova ilegalidade", "não somar anos", quais documentos seriam necessários, "6,87 de 7,49 mi ha de origem desconhecida"). Esse número vem do dicionário de dados que está no prompt, mas o juiz só enxerga os resultados das ferramentas. Se essas afirmações contassem como sustentadas, a Faithfulness média iria de 0,83 para cerca de 0,92 (contagem por palavras-chave, aproximada). As afirmações realmente soltas são menos: o caso mais claro é o L06 (0,56), em que o agente acrescentou culpa, pessoa jurídica e esfera administrativa sem apoio nos trechos.
5. **Mais passos, mais custo.** O M01 fez 5 chamadas (2 buscas de lei, porque a primeira errou) e gastou 19.093 tokens e 16,3 s, o maior da rodada.

## 4. Revisão das 20 perguntas

Legenda de "de quem é": **busca** (retrieval), **agente** (escolha de ferramenta ou redação), **gabarito**, **avaliação** (como a métrica ou o juiz mede).

| ID | O que as notas mostram | Causa | De quem é |
|---|---|---|---|
| L01 | Hit 1,00, MRR 1,00, Recall@5 0,50, Precision 0,83 | Art. 12 em 1º. O complementar (art. 3) ficou em 6º. Dos 6 trechos, 2 úteis. | avaliação (complementar fora do top-5) |
| L02 | Recall@5 0,50, resto 1,00 | Art. 4 em 1º. O art. 3 (complementar) não entrou no top-10. | avaliação |
| L04 | Faithfulness 0,80 | Busca perfeita. Duas afirmações dos "limites da resposta" erradas sobre o contexto: disse que os trechos eram "do decreto federal" (havia também Código Florestal e Lei 9.605) e que não tratavam da definição de reserva legal (o art. 30 trata). | agente (redação) |
| L06 | Faithfulness 0,56, Precision 0,67 | Busca perfeita (art. 38 em 1º, art. 39 em 2º). O agente acrescentou 4 afirmações sem apoio (culpa, pessoas físicas, pessoas jurídicas, esfera administrativa). O próximo trecho útil só aparece em 6º. | agente (conhecimento externo) |
| L07 | Tudo 1,00 | Nada a corrigir. | — |
| S01 | Faithfulness 0,80 | Valor e município certos. Sem apoio: a comparação do UNKNOWN com a soma da tabela (veio com limit 10) e as ressalvas do prompt. | avaliação |
| S05 | Faithfulness 0,78 | Valor certo. As duas afirmações sem apoio (série até 2024, fluxos da soja até 2022) vêm do prompt, não da ferramenta. | avaliação |
| C01 | Faithfulness 0,91 | Uma afirmação (janela de 5 anos) vem do prompt. | avaliação |
| C04 | Context Recall 0,75, Faithfulness 0,63 | Valores certos. A referência diz "não somar anos", regra do prompt que não está nos dados. 7 afirmações de metodologia sem apoio nos resultados. | avaliação |
| M01 | Hit/MRR 0, Precision 0,49, Faithfulness 0,87, 19.093 tokens | Art. 12 em 17º na busca direta. O agente errou a 1ª busca e acertou a 2ª; por isso Context Recall e valores ficam em 1,00. 17 itens de contexto, 5 úteis. Trouxe dados territoriais (D2) e disse que o Pampa fica fora da Amazônia Legal sem apoio. | busca + agente |
| M02 | Hit@5 1,00, MRR 0,25, Precision 0,64, Faithfulness 0,74 | Art. 12 em 4º (art. 3 e 13 antes); com só a metade de lei, 1º. Chamada de dados extra (D2) inútil. Cinco afirmações sem apoio (ano mais recente, ressalvas, diferença entre exposição e desmatamento total). | busca + agente |
| M03 | Hit/MRR 0, Context Recall 0,83 | Art. 51 em 53º (fora dos 40 candidatos); o agente trouxe o art. 52 em 1º e o 51 em 2º. A única afirmação da referência que falta é a ressalva de interpretação ("não prova que descumpriu a lei"), que não é fato do contexto. | busca (art. 51 x 52); avaliação |
| M04 | Hit@5 0, MRR 0,11, valores 0, Precision 0,17 | Art. 11 em 9º. O agente usou a métrica territorial (46.677,7 ha) em vez da exposição da cadeia (49.590,25 ha), então o valor está errado e só 1 dos 6 trechos de lei foi útil (em 5º). | agente (ferramenta) + busca |
| M05 | Context Recall 0, Precision 0, valores 0, Faithfulness 0,62 | Pior caso. Duas falhas independentes: (1) as duas buscas do agente trouxeram os arts. 6, 5 e 4 da PNMC e nunca o art. 12, então faltam os 36,1% e 38,9%; (2) usou a emissão territorial (140,1 Mt) em vez da da cadeia (121,1 Mt). | busca + agente |
| M06 | Tudo bom. Faithfulness 0,85 | Art. 12 em 1º. Afirmações sem apoio: "2023 é o ano mais recente" e uma condição sobre APP e CAR que o trecho diz de outro jeito. | agente (redação) |
| M07 | Tudo 1,00 (exceto métricas de texto) | Nada a corrigir. | — |
| M08 | Recall@5 0,50, Context Recall 0,83, Faithfulness 0,87 | Art. 38 em 1º; o art. 39 (complementar) fora do top-10. Falta só a ressalva "não prova crime". Os números do UNKNOWN (6,87 de 7,49 mi ha) vêm do dicionário do prompt, não dos resultados. | avaliação |
| M09 | MRR 0,33, Precision 0,81, Faithfulness 0,86 | Art. 52 em 3º (arts. 98 e 29 antes); só com a metade de lei, 1º. Chamada de dados extra (D2) inútil. Duas afirmações sobre "comparáveis" e "metodologias diferentes" sem apoio. | busca + agente |
| M10 | Hit/MRR 0, Context Recall 0,67, Precision 0,29 | Art. 51 em 39º; o art. 52 vem na frente, até com só a metade de lei. O agente achou o art. 51 em 2º. `soy_top_exporters` (D1) ordena por exposição (não por volume), agrupa por exportador (não por grupo) e não exclui PROCESSED DOMESTICALLY nem UNKNOWN CUSTOMER, que apareceram no topo. Isso obrigou o agente a refazer por SQL (D2), e o juiz considerou "CARGILL é o maior" não confirmável no contexto, porque PROCESSED DOMESTICALLY aparece acima dela em D2. Só 2 de 8 itens úteis. | busca (art. 51 x 52); ferramenta (`soy_top_exporters`) |
| M11 | Hit/MRR 0, Context Recall 0,83, Faithfulness 0,81 | Art. 10 em 49º na busca direta; só com a metade de lei, 1º, e o agente também achou em 1º. A ferramenta mostra 25 instalações em Mato Grosso, e o gabarito diz 24 (conta só as com capacidade de processamento maior que 0). | busca (diluição); **gabarito x ferramenta** |

## 5. O que eu mudaria (propostas, nada foi aplicado)

1. **Busca:** trocar o full-text de "todas as palavras" (AND) por "qualquer palavra" (OR) ou fazer um segundo passo quando não houver resultado. Assim a parte de palavras-chave do híbrido passa a contribuir (hoje quase nunca contribui) e, por exemplo, "art. 51", "licenciamento" e "CAR" pesariam mais.
2. **Avaliação da busca nas mistas:** guardar no gabarito a metade de lei da pergunta (`pergunta_lei`) e medir Hit, Recall e MRR com ela e com a busca que o agente de fato fez, mantendo a medida com a pergunta inteira. Hoje a métrica sub-representa o sistema.
3. **Juiz da Faithfulness:** incluir o dicionário e as regras do prompt como parte do contexto, ou separar essas alegações das "soltas". Hoje ele pune o agente por seguir o próprio prompt.
4. **Gabarito:** (a) M11, alinhar 24 x 25 instalações com a ferramenta ou citar os dois critérios; (b) M04 e M05, as perguntas dizem "exposição ao desmatamento da soja", que também pode ser lida como a métrica territorial. Vale deixar a pergunta explícita ("da cadeia") ou aceitar os dois valores; (c) M10, a referência deveria dizer que PROCESSED DOMESTICALLY e UNKNOWN não contam como exportador.
5. **Agente:** reforçar nas descrições das ferramentas a diferença entre exposição da cadeia e indicador territorial (M04, M05) e dar ao `soy_top_exporters` o que a versão da carne bovina (`top_exporters`) já tem: `by_group`, `order_by` e `include_domestic=False` (M10).

Posso aplicar qualquer um deles. As mudanças 1 e 5 alteram o sistema, e a 3 muda a definição da Faithfulness, então prefiro que você decida antes.

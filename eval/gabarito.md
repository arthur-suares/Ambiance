# Conjunto de teste do RAG — gabarito

Gerado por `python -m eval.build_gold`. Os números vêm de SQL direto nos bancos; tolerância padrão de 1% nos valores numéricos. *(no teste)* marca as 20 perguntas da avaliação; artigos essenciais contam em Hit Rate e MRR, complementares só no Recall.

## Leis

**L01. Qual percentual de reserva legal um imóvel rural precisa manter na Amazônia Legal e no resto do país?** *(no teste)*  
Gabarito: Pelo art. 12 do Código Florestal: na Amazônia Legal, 80% em área de florestas, 35% em área de cerrado e 20% em campos gerais; nas demais regiões do país, 20%.  
Referência longa: De acordo com o art. 12 do Código Florestal (Lei 12.651/2012), todo imóvel rural deve manter uma área com cobertura de vegetação nativa a título de reserva legal. Na Amazônia Legal, o percentual mínimo é de 80% do imóvel situado em área de florestas, 35% do imóvel situado em área de cerrado e 20% do imóvel situado em área de campos gerais. Nas demais regiões do país, o percentual mínimo é de 20% da área do imóvel. A Amazônia Legal é definida no art. 3º e abrange os estados do Acre, Pará, Amazonas, Roraima, Rondônia, Amapá e Mato Grosso, além de partes de Tocantins, Goiás e Maranhão.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 12 (essencial); Lei 12.651/2012 (Código Florestal), art. 3 (complementar)  
Ferramentas esperadas: `search_laws`  

**L02. Qual a largura mínima da faixa de preservação permanente às margens de um rio com menos de 10 metros de largura?** *(no teste)*  
Gabarito: 30 metros, contados da borda da calha do leito regular (art. 4º, I, a, do Código Florestal).  
Referência longa: Segundo o art. 4º, inciso I, alínea a, do Código Florestal (Lei 12.651/2012), as faixas marginais de qualquer curso d'água natural perene e intermitente são áreas de preservação permanente. Para cursos d'água com menos de 10 metros de largura, a faixa mínima é de 30 metros, medida a partir da borda da calha do leito regular. A APP é definida no art. 3º como área protegida, coberta ou não por vegetação nativa, com a função ambiental de preservar os recursos hídricos, a paisagem, a estabilidade geológica e a biodiversidade.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 4 (essencial); Lei 12.651/2012 (Código Florestal), art. 3 (complementar)  
Ferramentas esperadas: `search_laws`  

**L03. O que é o Cadastro Ambiental Rural (CAR) e quem é obrigado a se inscrever nele?**  
Gabarito: Registro público eletrônico de âmbito nacional, no âmbito do SINIMA, obrigatório para todos os imóveis rurais, que integra as informações ambientais das propriedades e posses para controle, monitoramento, planejamento e combate ao desmatamento (art. 29 do Código Florestal).  
Artigos: Lei 12.651/2012 (Código Florestal), art. 29 (essencial)  
Ferramentas esperadas: `search_laws`  

**L04. Qual a multa para quem desmata a corte raso, fora da reserva legal, sem autorização?** *(no teste)*  
Gabarito: Multa de R$ 1.000,00 por hectare ou fração (art. 52 do Decreto 6.514/2008).  
Referência longa: O art. 52 do Decreto 6.514/2008 estabelece que desmatar, a corte raso, florestas ou demais formações nativas, fora da reserva legal, sem autorização da autoridade competente, sujeita o infrator a multa de R$ 1.000,00 por hectare ou fração. Se o desmatamento ocorrer dentro da reserva legal, a infração é outra (art. 51), com multa de R$ 5.000,00 por hectare ou fração.  
Artigos: Decreto 6.514/2008, art. 52 (essencial)  
Ferramentas esperadas: `search_laws`  

**L05. Qual a multa por desmatar vegetação nativa dentro da reserva legal sem autorização do órgão ambiental?**  
Gabarito: Multa de R$ 5.000,00 por hectare ou fração (art. 51 do Decreto 6.514/2008).  
Artigos: Decreto 6.514/2008, art. 51 (essencial)  
Ferramentas esperadas: `search_laws`  

**L06. Qual a pena prevista para quem destrói floresta de preservação permanente?** *(no teste)*  
Gabarito: Detenção de um a três anos, ou multa, ou ambas cumulativamente; se o crime for culposo, a pena é reduzida à metade (art. 38 da Lei 9.605/1998).  
Referência longa: Pelo art. 38 da Lei 9.605/1998 (Lei de Crimes Ambientais), destruir ou danificar floresta considerada de preservação permanente, mesmo que em formação, ou utilizá-la com infringência das normas de proteção é crime punido com detenção de um a três anos, ou multa, ou ambas as penas cumulativamente. Se o crime for culposo, a pena é reduzida à metade. O art. 39 prevê a mesma pena para quem corta árvores em floresta de preservação permanente sem permissão da autoridade competente.  
Artigos: Lei 9.605/1998 (Lei de Crimes Ambientais), art. 38 (essencial); Lei 9.605/1998 (Lei de Crimes Ambientais), art. 39 (complementar)  
Ferramentas esperadas: `search_laws`  

**L07. Quais são as categorias de unidades de conservação de proteção integral?** *(no teste)*  
Gabarito: Estação Ecológica, Reserva Biológica, Parque Nacional, Monumento Natural e Refúgio de Vida Silvestre (art. 8º da Lei 9.985/2000 – SNUC).  
Referência longa: O art. 8º da Lei 9.985/2000, que institui o Sistema Nacional de Unidades de Conservação (SNUC), define que o grupo das Unidades de Proteção Integral é composto por cinco categorias: Estação Ecológica, Reserva Biológica, Parque Nacional, Monumento Natural e Refúgio de Vida Silvestre. Segundo o art. 7º, o objetivo básico das unidades de proteção integral é preservar a natureza, sendo admitido apenas o uso indireto dos seus recursos naturais.  
Artigos: Lei 9.985/2000 (SNUC), art. 8 (essencial); Lei 9.985/2000 (SNUC), art. 7 (complementar)  
Ferramentas esperadas: `search_laws`  

**L08. Qual foi a meta de redução de emissões assumida pelo Brasil na Política Nacional sobre Mudança do Clima?**  
Gabarito: Compromisso nacional voluntário de reduzir entre 36,1% e 38,9% as emissões projetadas até 2020 (art. 12 da Lei 12.187/2009).  
Artigos: Lei 12.187/2009 (PNMC), art. 12 (essencial)  
Ferramentas esperadas: `search_laws`  

## Soja

**S01. Qual município teve a maior exposição ao desmatamento ligada à soja em 2022?** *(no teste)*  
Gabarito: Sao Gabriel (Rio Grande do Sul), com cerca de 18,8 mil ha de exposição. A origem não rastreada (UNKNOWN) não é um município e deve ficar de fora ou ser explicada.  
Referência longa: Em 2022, o município com a maior exposição ao desmatamento ligada à soja foi Sao Gabriel (Rio Grande do Sul), com cerca de 18,8 mil ha de exposição (janela de 5 anos). A origem não rastreada (UNKNOWN) não é um município e fica fora do ranking. A exposição ao desmatamento não prova, por si só, ilegalidade.  
Ferramentas esperadas: `soy_top_municipalities`  

**S02. Quais foram os três maiores grupos exportadores de soja em volume em 2022?**  
Gabarito: Por volume exportado: CARGILL (13,53 milhões t); BUNGE (10,16 milhões t); ADM (9,74 milhões t). A soja processada no Brasil (PROCESSED DOMESTICALLY) não é um exportador.  
Ferramentas esperadas: `run_soy_sql`  

**S03. Qual foi o principal país de destino da soja brasileira em 2022?**  
Gabarito: China (CHINA (MAINLAND) nos dados), com cerca de 40,38 milhões t. O consumo interno (BRAZIL) não é destino de exportação.  
Ferramentas esperadas: `soy_top_destinations`  

**S04. Qual foi a exposição total ao desmatamento da cadeia da soja em 2022?**  
Gabarito: Cerca de 793,7 mil ha (janela de 5 anos), incluindo a origem não rastreada.  
Ferramentas esperadas: `soy_yearly_trend`  

**S05. Qual estado é o maior produtor de soja do Brasil, segundo o dado mais recente?** *(no teste)*  
Gabarito: Mato Grosso, com cerca de 38,40 milhões t em 2024.  
Referência longa: Segundo o dado mais recente (2024), o maior produtor de soja do Brasil é o Mato Grosso, com cerca de 38,40 milhões t produzidas no ano.  
Ferramentas esperadas: `soy_territorial_metric`  

**S06. Qual a produtividade da soja em Sorriso (MT) no ano mais recente disponível?**  
Gabarito: Cerca de 3,48 t/ha em 2024.  
Ferramentas esperadas: `soy_territorial_metric`  

**S07. Qual estado tem a maior capacidade de armazenagem de soja e quantas instalações ele tem?**  
Gabarito: Mato Grosso, com cerca de 62,97 milhões t de capacidade de armazenagem em 2.334 instalações.  
Ferramentas esperadas: `soy_facilities_summary`  

## Carne bovina

**C01. Qual grupo exportador de carne bovina teve a maior exposição ao desmatamento em 2023?** *(no teste)*  
Gabarito: JBS, com cerca de 277,6 mil ha.  
Referência longa: Em 2023, o grupo exportador de carne bovina com a maior exposição ao desmatamento foi a JBS, com cerca de 277,6 mil ha. A exposição ao desmatamento não prova, por si só, ilegalidade.  
Ferramentas esperadas: `top_exporters`  

**C02. Para qual país o Brasil mais exportou carne bovina em 2023?**  
Gabarito: China (CHINA (MAINLAND) nos dados), com cerca de 1,80 milhões t.  
Ferramentas esperadas: `top_destinations`  

**C03. Qual município teve a maior exposição ao desmatamento na cadeia da carne bovina em 2023?**  
Gabarito: Sao Felix do Xingu (Para), com cerca de 36,1 mil ha.  
Ferramentas esperadas: `top_municipalities`  

**C04. Como a exposição total ao desmatamento da carne bovina mudou entre 2015 e 2023?** *(no teste)*  
Gabarito: Subiu de cerca de 4,70 milhões ha em 2015 para 7,49 milhões ha em 2023, alta de cerca de 59%. Os valores de cada ano não devem ser somados.  
Referência longa: A exposição ao desmatamento da cadeia da carne bovina subiu de cerca de 4,70 milhões ha em 2015 para cerca de 7,49 milhões ha em 2023, um aumento de cerca de 59%. Cada valor anual já considera uma janela de 5 anos de desmatamento, por isso os valores de anos diferentes não devem ser somados.  
Ferramentas esperadas: `yearly_trend`  

**C05. Quantas toneladas de carne bovina o Brasil exportou em 2023?**  
Gabarito: Cerca de 3,57 milhões t exportadas.  
Ferramentas esperadas: `yearly_trend`  

**C06. Em 2023, que parcela do volume exportado de carne bovina saiu de exportadores sem compromisso de desmatamento zero?**  
Gabarito: Cerca de 36,8% do volume exportado veio de exportadores sem compromisso (NO COMMITMENT).  
Ferramentas esperadas: `commitment_summary`  

**C07. Qual estado tem a maior área de pastagem, segundo o dado mais recente?**  
Gabarito: Para, com cerca de 21,29 milhões ha em 2023.  
Ferramentas esperadas: `territorial_metric`  

## Mistas (dados + leis)

**M01. Em 2022, qual bioma teve maior exposição ao desmatamento na cadeia da soja e na da carne bovina? O que o Código Florestal exige de reserva legal nesses biomas?** *(no teste)*  
Gabarito: Cerrado nas duas cadeias: 260,2 mil ha na soja e 298,8 mil ha na carne bovina (sem a origem não rastreada). Reserva legal (art. 12): 35% para imóveis em área de cerrado na Amazônia Legal e 20% fora dela.  
Referência longa: Em 2022, o bioma com maior exposição ao desmatamento foi o Cerrado nas duas cadeias: cerca de 260,2 mil ha na soja e 298,8 mil ha na carne bovina, sem contar a origem não rastreada. Pelo art. 12 do Código Florestal, a reserva legal de imóveis em área de cerrado é de 35% quando estão na Amazônia Legal e de 20% nas demais regiões do país; em área de florestas na Amazônia Legal, o percentual é de 80%.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 12 (essencial); Lei 12.651/2012 (Código Florestal), art. 3 (complementar)  
Ferramentas esperadas: `soy_deforestation_by_biome`, `run_sql`, `search_laws`  

**M02. No Mato Grosso, quanto se produziu de soja no ano mais recente e qual foi a exposição ao desmatamento da carne bovina em 2023? Quanto de reserva legal um imóvel em área de floresta na Amazônia Legal deve manter?** *(no teste)*  
Gabarito: Soja: cerca de 38,40 milhões t. Carne bovina: cerca de 179,6 mil ha de exposição em 2023. Reserva legal em área de florestas na Amazônia Legal: 80% (art. 12 do Código Florestal).  
Referência longa: No Mato Grosso, a produção de soja no ano mais recente disponível foi de cerca de 38,40 milhões t. Na cadeia da carne bovina, a exposição ao desmatamento do estado em 2023 foi de cerca de 179,6 mil ha. Como o Mato Grosso faz parte da Amazônia Legal (art. 3º do Código Florestal), um imóvel situado em área de florestas deve manter 80% de reserva legal, conforme o art. 12.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 12 (essencial); Lei 12.651/2012 (Código Florestal), art. 3 (complementar)  
Ferramentas esperadas: `soy_territorial_metric`, `yearly_trend`, `search_laws`  

**M03. Qual grupo exportador de carne bovina teve maior exposição ao desmatamento em 2023 e ele tem compromisso de desmatamento zero? Que multa o Decreto 6.514/2008 prevê para desmatar dentro da reserva legal sem autorização?** *(no teste)*  
Gabarito: JBS, com cerca de 277,6 mil ha; tem compromisso de desmatamento zero (de empresa, e também G4/TAC em parte dos fluxos). A multa é de R$ 5.000,00 por hectare ou fração (art. 51). A exposição não prova que o grupo descumpriu a lei.  
Referência longa: Em 2023, o grupo exportador de carne bovina com maior exposição ao desmatamento foi a JBS, com cerca de 277,6 mil ha. O grupo tem compromisso de desmatamento zero (compromisso próprio e, em parte dos fluxos, acordos G4/TAC). A exposição ao desmatamento não prova que o grupo descumpriu a lei. Pelo art. 51 do Decreto 6.514/2008, destruir, desmatar, danificar ou explorar vegetação nativa em área de reserva legal sem autorização prévia do órgão ambiental sujeita o infrator a multa de R$ 5.000,00 por hectare ou fração.  
Artigos: Decreto 6.514/2008, art. 51 (essencial)  
Ferramentas esperadas: `top_exporters`, `search_laws`  

**M04. Qual foi a exposição ao desmatamento da soja na Mata Atlântica em 2022 e em que casos a lei proíbe cortar vegetação primária nesse bioma?** *(no teste)*  
Gabarito: Cerca de 49,6 mil ha em 2022. A Lei da Mata Atlântica (art. 11) veda o corte de vegetação primária ou em estágio médio/avançado quando ela abriga espécies ameaçadas, protege mananciais ou previne erosão, forma corredores entre remanescentes, protege o entorno de unidades de conservação ou tem excepcional valor paisagístico, ou quando o proprietário não cumpre a legislação ambiental.  
Referência longa: Em 2022, a exposição ao desmatamento da cadeia da soja no bioma Mata Atlântica foi de cerca de 49,6 mil ha. A Lei da Mata Atlântica (Lei 11.428/2006), em seu art. 11, veda o corte e a supressão de vegetação primária ou nos estágios avançado e médio de regeneração quando a vegetação abrigar espécies da flora e da fauna ameaçadas de extinção, exercer a função de proteção de mananciais ou de prevenção e controle de erosão, formar corredores entre remanescentes de vegetação primária ou secundária em estágio avançado de regeneração, proteger o entorno das unidades de conservação ou possuir excepcional valor paisagístico; também é vedado quando o proprietário ou posseiro não cumprir a legislação ambiental. Fora desses casos, o art. 14 só admite a supressão de vegetação primária e secundária em estágio avançado em caso de utilidade pública.  
Artigos: Lei 11.428/2006 (Lei da Mata Atlântica), art. 11 (essencial); Lei 11.428/2006 (Lei da Mata Atlântica), art. 14 (complementar)  
Ferramentas esperadas: `soy_deforestation_by_biome`, `search_laws`  

**M05. Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022 e qual meta de redução de emissões a Política Nacional sobre Mudança do Clima estabeleceu?** *(no teste)*  
Gabarito: Cerca de 121,12 milhões tCO2e de emissões brutas (janela de 5 anos) em 2022. A PNMC (art. 12) fixou o compromisso voluntário de reduzir entre 36,1% e 38,9% as emissões projetadas até 2020.  
Referência longa: Em 2022, as emissões brutas de CO2 associadas ao desmatamento na cadeia da soja foram de cerca de 121,12 milhões tCO2e (janela de 5 anos). A Política Nacional sobre Mudança do Clima (Lei 12.187/2009), no art. 12, estabeleceu como compromisso nacional voluntário reduzir entre 36,1% e 38,9% as emissões de gases de efeito estufa projetadas até 2020.  
Artigos: Lei 12.187/2009 (PNMC), art. 12 (essencial)  
Ferramentas esperadas: `soy_yearly_trend`, `search_laws`  

**M06. Qual estado tem a maior área de pastagem e quanto de reserva legal um imóvel em área de floresta na Amazônia Legal precisa manter?** *(no teste)*  
Gabarito: Para, com cerca de 21,29 milhões ha de pastagem em 2023. Em área de florestas na Amazônia Legal, a reserva legal é de 80% do imóvel (art. 12 do Código Florestal).  
Referência longa: Segundo o dado mais recente (2023), o estado com a maior área de pastagem é o Para, com cerca de 21,29 milhões ha. Pelo art. 12 do Código Florestal, um imóvel rural localizado na Amazônia Legal em área de florestas deve manter 80% da sua área como reserva legal.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 12 (essencial); Lei 12.651/2012 (Código Florestal), art. 3 (complementar)  
Ferramentas esperadas: `territorial_metric`, `search_laws`  

**M07. Que percentual da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero em 2022, e o que é o CAR?** *(no teste)*  
Gabarito: Cerca de 53,1% em 2022. O CAR (art. 29 do Código Florestal) é o registro público eletrônico nacional, obrigatório para todos os imóveis rurais, que integra as informações ambientais das propriedades para controle, monitoramento, planejamento e combate ao desmatamento.  
Referência longa: Em 2022, cerca de 53,1% da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero. O Cadastro Ambiental Rural (CAR), criado pelo art. 29 do Código Florestal, é um registro público eletrônico de âmbito nacional, no Sistema Nacional de Informação sobre Meio Ambiente (SINIMA), obrigatório para todos os imóveis rurais, com a finalidade de integrar as informações ambientais das propriedades e posses rurais para controle, monitoramento, planejamento ambiental e econômico e combate ao desmatamento.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 29 (essencial)  
Ferramentas esperadas: `soy_territorial_metric`, `search_laws`  

**M08. Qual município teve a maior exposição ao desmatamento na carne bovina em 2023, e qual a pena para quem destrói floresta de preservação permanente?** *(no teste)*  
Gabarito: Sao Felix do Xingu (Para), com cerca de 36,1 mil ha. A pena é detenção de um a três anos, ou multa, ou ambas (art. 38 da Lei 9.605/1998), reduzida à metade se o crime for culposo. A exposição não prova que houve crime.  
Referência longa: Em 2023, o município com a maior exposição ao desmatamento na cadeia da carne bovina foi Sao Felix do Xingu (Para), com cerca de 36,1 mil ha. Pelo art. 38 da Lei 9.605/1998, destruir ou danificar floresta considerada de preservação permanente é crime punido com detenção de um a três anos, ou multa, ou ambas as penas cumulativamente, com redução da pena à metade se o crime for culposo. A exposição ao desmatamento não prova que houve crime.  
Artigos: Lei 9.605/1998 (Lei de Crimes Ambientais), art. 38 (essencial); Lei 9.605/1998 (Lei de Crimes Ambientais), art. 39 (complementar)  
Ferramentas esperadas: `top_municipalities`, `search_laws`  

**M09. Compare a exposição ao desmatamento da soja e da carne bovina na Amazônia em 2022, e qual a multa por desmatar a corte raso fora da reserva legal?** *(no teste)*  
Gabarito: Na Amazônia, em 2022: soja com cerca de 48,7 mil ha e carne bovina com cerca de 293,9 mil ha (a carne tem cerca de 6 vezes mais). A multa é de R$ 1.000,00 por hectare ou fração (art. 52 do Decreto 6.514/2008).  
Referência longa: Na Amazônia, em 2022, a exposição ao desmatamento foi de cerca de 48,7 mil ha na cadeia da soja e 293,9 mil ha na cadeia da carne bovina, ou seja, a carne bovina teve cerca de 6 vezes mais exposição que a soja no bioma. Pelo art. 52 do Decreto 6.514/2008, desmatar a corte raso florestas ou demais formações nativas fora da reserva legal, sem autorização da autoridade competente, sujeita o infrator a multa de R$ 1.000,00 por hectare ou fração.  
Artigos: Decreto 6.514/2008, art. 52 (essencial)  
Ferramentas esperadas: `soy_deforestation_by_biome`, `run_sql`, `search_laws`  

**M10. Qual o maior grupo exportador de soja em 2022 e sua exposição ao desmatamento? Que multa se aplica a quem desmata dentro da reserva legal?** *(no teste)*  
Gabarito: CARGILL, com cerca de 13,53 milhões t exportadas e 55,1 mil ha de exposição ao desmatamento em 2022. A multa é de R$ 5.000,00 por hectare ou fração (art. 51 do Decreto 6.514/2008). A exposição não prova ilegalidade.  
Referência longa: Em 2022, o maior grupo exportador de soja em volume foi a CARGILL, com cerca de 13,53 milhões t exportadas e cerca de 55,1 mil ha de exposição ao desmatamento. A exposição não prova ilegalidade. Pelo art. 51 do Decreto 6.514/2008, quem destrói, desmata, danifica ou explora vegetação nativa em área de reserva legal sem autorização prévia do órgão ambiental está sujeito a multa de R$ 5.000,00 por hectare ou fração.  
Artigos: Decreto 6.514/2008, art. 51 (essencial)  
Ferramentas esperadas: `soy_top_exporters`, `search_laws`  

**M11. Qual estado tem a maior capacidade de processamento de soja, e que atividades dependem de licenciamento ambiental prévio?** *(no teste)*  
Gabarito: Mato Grosso, com cerca de 56.700 t/dia de capacidade de processamento (24 instalações com processamento). Pelo art. 10 da Lei 6.938/1981, dependem de licenciamento prévio a construção, instalação, ampliação e funcionamento de estabelecimentos e atividades que usam recursos ambientais e são efetiva ou potencialmente poluidores ou capazes de causar degradação ambiental.  
Referência longa: O estado com a maior capacidade de processamento de soja é o Mato Grosso, com cerca de 56.700 t/dia somadas em 24 instalações com processamento. Pelo art. 10 da Lei 6.938/1981 (Política Nacional do Meio Ambiente), a construção, instalação, ampliação e funcionamento de estabelecimentos e atividades utilizadores de recursos ambientais, efetiva ou potencialmente poluidores ou capazes, sob qualquer forma, de causar degradação ambiental dependem de prévio licenciamento ambiental.  
Artigos: Lei 6.938/1981 (PNMA), art. 10 (essencial)  
Ferramentas esperadas: `soy_facilities_summary`, `search_laws`  

## Fora do escopo (deve recusar)

**F01. Qual foi a produção de café em Minas Gerais em 2022?**  
Gabarito: O sistema não tem dados de café; deve dizer que a informação não está na base (cobre soja, carne bovina e leis ambientais).  

**F02. Qual será a exposição ao desmatamento da soja em 2030?**  
Gabarito: Não há projeções na base; os dados da cadeia da soja vão até 2022. Deve dizer que não é possível responder.  

**F03. A JBS cometeu crime ambiental em 2023?**  
Gabarito: Não é possível concluir: os dados mostram exposição ao desmatamento, que não prova ilegalidade nem responsabilidade direta. Pode explicar o que a lei tipifica e que dados seriam necessários (autos de infração, embargos, CAR).  

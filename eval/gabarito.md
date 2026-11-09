# Conjunto de teste do RAG — gabarito

Gerado por `python -m eval.build_gold`. Os números vêm de SQL direto nos bancos; tolerância padrão de 1% nos valores numéricos.

## Leis

**L01. Qual percentual de reserva legal um imóvel rural precisa manter na Amazônia Legal e no resto do país?**  
Gabarito: Pelo art. 12 do Código Florestal: na Amazônia Legal, 80% em área de florestas, 35% em área de cerrado e 20% em campos gerais; nas demais regiões do país, 20%.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 12  
Ferramentas esperadas: `search_laws`  

**L02. Qual a largura mínima da faixa de preservação permanente às margens de um rio com menos de 10 metros de largura?**  
Gabarito: 30 metros, contados da borda da calha do leito regular (art. 4º, I, a, do Código Florestal).  
Artigos: Lei 12.651/2012 (Código Florestal), art. 4  
Ferramentas esperadas: `search_laws`  

**L03. O que é o Cadastro Ambiental Rural (CAR) e quem é obrigado a se inscrever nele?**  
Gabarito: Registro público eletrônico de âmbito nacional, no âmbito do SINIMA, obrigatório para todos os imóveis rurais, que integra as informações ambientais das propriedades e posses para controle, monitoramento, planejamento e combate ao desmatamento (art. 29 do Código Florestal).  
Artigos: Lei 12.651/2012 (Código Florestal), art. 29  
Ferramentas esperadas: `search_laws`  

**L04. Qual a multa para quem desmata a corte raso, fora da reserva legal, sem autorização?**  
Gabarito: Multa de R$ 1.000,00 por hectare ou fração (art. 52 do Decreto 6.514/2008).  
Artigos: Decreto 6.514/2008, art. 52  
Ferramentas esperadas: `search_laws`  

**L05. Qual a multa por desmatar vegetação nativa dentro da reserva legal sem autorização do órgão ambiental?**  
Gabarito: Multa de R$ 5.000,00 por hectare ou fração (art. 51 do Decreto 6.514/2008).  
Artigos: Decreto 6.514/2008, art. 51  
Ferramentas esperadas: `search_laws`  

**L06. Qual a pena prevista para quem destrói floresta de preservação permanente?**  
Gabarito: Detenção de um a três anos, ou multa, ou ambas cumulativamente; se o crime for culposo, a pena é reduzida à metade (art. 38 da Lei 9.605/1998).  
Artigos: Lei 9.605/1998 (Lei de Crimes Ambientais), art. 38  
Ferramentas esperadas: `search_laws`  

**L07. Quais são as categorias de unidades de conservação de proteção integral?**  
Gabarito: Estação Ecológica, Reserva Biológica, Parque Nacional, Monumento Natural e Refúgio de Vida Silvestre (art. 8º da Lei 9.985/2000 – SNUC).  
Artigos: Lei 9.985/2000 (SNUC), art. 8  
Ferramentas esperadas: `search_laws`  

**L08. Qual foi a meta de redução de emissões assumida pelo Brasil na Política Nacional sobre Mudança do Clima?**  
Gabarito: Compromisso nacional voluntário de reduzir entre 36,1% e 38,9% as emissões projetadas até 2020 (art. 12 da Lei 12.187/2009).  
Artigos: Lei 12.187/2009 (PNMC), art. 12  
Ferramentas esperadas: `search_laws`  

## Soja

**S01. Qual município teve a maior exposição ao desmatamento ligada à soja em 2022?**  
Gabarito: Sao Gabriel (Rio Grande do Sul), com cerca de 18,8 mil ha de exposição. A origem não rastreada (UNKNOWN) não é um município e deve ficar de fora ou ser explicada.  
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

**S05. Qual estado é o maior produtor de soja do Brasil, segundo o dado mais recente?**  
Gabarito: Mato Grosso, com cerca de 38,40 milhões t em 2024.  
Ferramentas esperadas: `soy_territorial_metric`  

**S06. Qual a produtividade da soja em Sorriso (MT) no ano mais recente disponível?**  
Gabarito: Cerca de 3,48 t/ha em 2024.  
Ferramentas esperadas: `soy_territorial_metric`  

**S07. Qual estado tem a maior capacidade de armazenagem de soja e quantas instalações ele tem?**  
Gabarito: Mato Grosso, com cerca de 62,97 milhões t de capacidade de armazenagem em 2.334 instalações.  
Ferramentas esperadas: `soy_facilities_summary`  

## Carne bovina

**C01. Qual grupo exportador de carne bovina teve a maior exposição ao desmatamento em 2023?**  
Gabarito: JBS, com cerca de 277,6 mil ha.  
Ferramentas esperadas: `top_exporters`  

**C02. Para qual país o Brasil mais exportou carne bovina em 2023?**  
Gabarito: China (CHINA (MAINLAND) nos dados), com cerca de 1,80 milhões t.  
Ferramentas esperadas: `top_destinations`  

**C03. Qual município teve a maior exposição ao desmatamento na cadeia da carne bovina em 2023?**  
Gabarito: Sao Felix do Xingu (Para), com cerca de 36,1 mil ha.  
Ferramentas esperadas: `top_municipalities`  

**C04. Como a exposição total ao desmatamento da carne bovina mudou entre 2015 e 2023?**  
Gabarito: Subiu de cerca de 4,70 milhões ha em 2015 para 7,49 milhões ha em 2023, alta de cerca de 59%. Os valores de cada ano não devem ser somados.  
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

**M01. Em 2022, qual bioma teve maior exposição ao desmatamento na cadeia da soja e na da carne bovina? O que o Código Florestal exige de reserva legal nesses biomas?**  
Gabarito: Cerrado nas duas cadeias: 260,2 mil ha na soja e 298,8 mil ha na carne bovina (sem a origem não rastreada). Reserva legal (art. 12): 35% para imóveis em área de cerrado na Amazônia Legal e 20% fora dela.  
Artigos: Lei 12.651/2012 (Código Florestal), art. 12  
Ferramentas esperadas: `soy_deforestation_by_biome`, `run_sql`, `search_laws`  

**M02. No Mato Grosso, quanto se produziu de soja no ano mais recente e qual foi a exposição ao desmatamento da carne bovina em 2023? Quanto de reserva legal um imóvel em área de floresta na Amazônia Legal deve manter?**  
Gabarito: Soja: cerca de 38,40 milhões t. Carne bovina: cerca de 179,6 mil ha de exposição em 2023. Reserva legal em área de florestas na Amazônia Legal: 80% (art. 12 do Código Florestal).  
Artigos: Lei 12.651/2012 (Código Florestal), art. 12  
Ferramentas esperadas: `soy_territorial_metric`, `yearly_trend`, `search_laws`  

**M03. Qual grupo exportador de carne bovina teve maior exposição ao desmatamento em 2023 e ele tem compromisso de desmatamento zero? Que multa o Decreto 6.514/2008 prevê para desmatar dentro da reserva legal sem autorização?**  
Gabarito: JBS, com cerca de 277,6 mil ha; tem compromisso de desmatamento zero (de empresa, e também G4/TAC em parte dos fluxos). A multa é de R$ 5.000,00 por hectare ou fração (art. 51). A exposição não prova que o grupo descumpriu a lei.  
Artigos: Decreto 6.514/2008, art. 51  
Ferramentas esperadas: `top_exporters`, `search_laws`  

**M04. Qual foi a exposição ao desmatamento da soja na Mata Atlântica em 2022 e em que casos a lei proíbe cortar vegetação primária nesse bioma?**  
Gabarito: Cerca de 49,6 mil ha em 2022. A Lei da Mata Atlântica (art. 11) veda o corte de vegetação primária ou em estágio médio/avançado quando ela abriga espécies ameaçadas, protege mananciais ou previne erosão, forma corredores entre remanescentes, protege o entorno de unidades de conservação ou tem excepcional valor paisagístico, ou quando o proprietário não cumpre a legislação ambiental.  
Artigos: Lei 11.428/2006 (Lei da Mata Atlântica), art. 11  
Ferramentas esperadas: `soy_deforestation_by_biome`, `search_laws`  

**M05. Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022 e qual meta de redução de emissões a Política Nacional sobre Mudança do Clima estabeleceu?**  
Gabarito: Cerca de 121,12 milhões tCO2e de emissões brutas (janela de 5 anos) em 2022. A PNMC (art. 12) fixou o compromisso voluntário de reduzir entre 36,1% e 38,9% as emissões projetadas até 2020.  
Artigos: Lei 12.187/2009 (PNMC), art. 12  
Ferramentas esperadas: `soy_yearly_trend`, `search_laws`  

## Fora do escopo (deve recusar)

**F01. Qual foi a produção de café em Minas Gerais em 2022?**  
Gabarito: O sistema não tem dados de café; deve dizer que a informação não está na base (cobre soja, carne bovina e leis ambientais).  

**F02. Qual será a exposição ao desmatamento da soja em 2030?**  
Gabarito: Não há projeções na base; os dados da cadeia da soja vão até 2022. Deve dizer que não é possível responder.  

**F03. A JBS cometeu crime ambiental em 2023?**  
Gabarito: Não é possível concluir: os dados mostram exposição ao desmatamento, que não prova ilegalidade nem responsabilidade direta. Pode explicar o que a lei tipifica e que dados seriam necessários (autos de infração, embargos, CAR).  

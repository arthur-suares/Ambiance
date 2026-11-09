# Dicionário de dados — banco analítico (DuckDB)

Gerado por `python -m src.cli dictionary` a partir de `src/data_dictionary.py`. Edite o arquivo Python, não este.

## `supply_chain` (tabela)

Fluxos da cadeia da carne bovina do Trase (v2.2.2): um registro por combinação de ano, município de produção, exportador, importador, destino e produto. 4,5 milhões de linhas, 2011-2023 (sem 2018). Volume, FOB e indicadores estão alocados por fluxo: somar fluxos dentro de um ano é válido.

| Coluna | Descrição |
|---|---|
| `year` | INTEGER. Ano do fluxo. |
| `biome` | Bioma do município de produção: AMAZONIA, CERRADO, MATA ATLANTICA, PAMPA, PANTANAL, CAATINGA, UNKNOWN. |
| `state_of_production` | UF de produção, nome por extenso em maiúsculas sem acento (ex.: PARA, MATO GROSSO). |
| `municipality_of_production` | Município de produção, maiúsculas sem acento (ex.: SAO FELIX DO XINGU). 'UNKNOWN' (trase_id BR-XXXXXXX, UF 'UNKNOWN STATE', bioma 'UNKNOWN') = origem não rastreada. |
| `municipality_of_production_trase_id` | Código do município (ex.: BR-1507300 = prefixo BR- + código IBGE). Use para juntar com spatial_metrics.region_trase_id. |
| `state_of_production_trase_id` | Código da UF (ex.: BR-15). |
| `logistics_hub` | Município do frigorífico/centro logístico por onde o gado passou. |
| `product_type` | BEEF BONELESS, BEEF OFFALS, MEAT PREPARATIONS, CATTLE (gado vivo), BEEF, BEEF DRIED SALTED SMOKED. |
| `port_of_export` | Porto de exportação. |
| `exporter` | Empresa exportadora. 'DOMESTIC PROCESSING AND CONSUMPTION' = consumo interno; 'UNKNOWN' = não identificado. |
| `exporter_group` | Grupo econômico do exportador (ex.: JBS, MARFRIG, MINERVA). Prefira este para ranking de empresas. |
| `exporter_id` | Identificador do exportador (CNPJ parcial). |
| `importer` | Empresa importadora. |
| `importer_group` | Grupo econômico do importador. |
| `country_of_destination` | País de destino. 'BRAZIL' = consumo interno; 'UNKNOWN COUNTRY' = não identificado. |
| `economic_bloc` | Bloco econômico do destino (ex.: EUROPEAN UNION, CHINA (MAINLAND)). |
| `zero_deforestation_brazil_beef` | Compromisso de desmatamento zero do exportador: NO COMMITMENT, COMPANY COMMITMENT (compromisso próprio), G4 (Compromisso Público da Pecuária com o Greenpeace, 2009), TAC (Termo de Ajustamento de Conduta com o MPF) e combinações. |
| `forest_500_beef` | Nota Forest 500 (Global Canopy) do exportador, texto: '0'..'6' ou 'NOT ASSESSED'. |
| `volume` | DOUBLE, toneladas de carne (equivalente-carcaça; confirmar na metodologia). |
| `fob` | DOUBLE, valor FOB em US$. |
| `land_use` | DOUBLE, hectares de pastagem associados ao fluxo (confirmar na metodologia). NULL em ~247 mil linhas. |
| `cattle_deforestation_5_year_total_exposure` | DOUBLE, hectares. Exposição ao desmatamento: desmatamento atribuído à pecuária nos 5 anos até o ano, alocado ao fluxo. Só existe a partir de 2015 (2011-2014 = 0/NULL = sem dado). |
| `co2_net_emissions_cattle_deforestation_5_year_total_exposure` | DOUBLE, tCO2e. Emissões líquidas da exposição. Mesmas regras da exposição. |
| `co2_gross_emissions_cattle_deforestation_5_year_total_exposure` | DOUBLE, tCO2e. Emissões brutas da exposição. Mesmas regras da exposição. |

## `flows_by_municipality` (view)

supply_chain agregada por ano e município de produção (inclui consumo interno). Somas já prontas.

| Coluna | Descrição |
|---|---|
| `year, biome, state_of_production, municipality_of_production, municipality_trase_id` | Chaves. |
| `volume_t` | Volume total (t), interno + exportado. |
| `volume_exported_t` | Volume exportado (t), sem consumo interno. |
| `fob_usd` | Valor FOB (US$). |
| `deforestation_exposure_ha` | Exposição ao desmatamento (ha). |
| `co2_net_tco2e, co2_gross_tco2e` | Emissões líquidas e brutas da exposição (tCO2e). |
| `land_use_ha` | Área de pastagem associada (ha). |

## `flows_by_exporter` (view)

supply_chain agregada por ano, grupo exportador e exportador (inclui a linha de consumo interno; filtre se quiser só exportação).

| Coluna | Descrição |
|---|---|
| `year, exporter_group, exporter, zero_deforestation_brazil_beef` | Chaves. |
| `volume_t, fob_usd, deforestation_exposure_ha, co2_net_tco2e` | Somas. |
| `source_municipalities, destination_countries` | Número de municípios de origem e países de destino distintos. |

## `flows_by_destination` (view)

supply_chain agregada por ano e país de destino (inclui BRAZIL = consumo interno).

| Coluna | Descrição |
|---|---|
| `year, country_of_destination, economic_bloc` | Chaves. |
| `volume_t, fob_usd, deforestation_exposure_ha, co2_net_tco2e` | Somas. |

## `spatial_metrics` (tabela)

Indicadores territoriais do Trase por região (formato longo: uma linha por métrica, nível, ano e região). Descrevem a região inteira, não fluxos. 2010-2023. No nível municipal, 2010-2011 só têm cattle_production_t, pasture_area_ha, pasture_deforestation_ha, co2_net_pasture_deforestation_tco2e, zdc_exported_pct e zdc_produced_pct; as demais métricas municipais começam em 2012.

| Coluna | Descrição |
|---|---|
| `metric` | Nome da métrica (ver catálogo abaixo). |
| `level` | 'country' (Brasil), 'biome', 'state' ou 'municipality'. |
| `year` | INTEGER. |
| `region` | Nome da região em maiúsculas sem acento (BRAZIL, AMAZONIA, PARA, ALTAMIRA...). |
| `region_trase_id` | Código da região (BR-1500602 para município, BR-15 para UF, BR-BIO-1 para bioma). |
| `parent_region` | Região-mãe: UF para município, macrorregião (NORTE, CENTRO-OESTE...) para UF, BRAZIL para bioma. |
| `parent_region_trase_id` | Código da região-mãe. |
| `value` | DOUBLE, valor na unidade da métrica. |
| `unit` | Unidade da métrica. |

## `spatial_metrics_wide` (view)

spatial_metrics em formato largo: uma linha por nível, ano e região, uma coluna por métrica (nomes do catálogo).

| Coluna | Descrição |
|---|---|
| `level, year, region, region_trase_id, parent_region, parent_region_trase_id, <métricas>` |  |

## `metric_catalog` (tabela)

Catálogo das métricas de spatial_metrics: metric, unit, description, additive (pode somar entre regiões).

## `facilities` (tabela)

Mapa logístico do Trase (2026-05-07, v6): estabelecimentos com inspeção sanitária (frigoríficos, laticínios etc.). Inclui várias commodities, não só carne bovina. 18 mil linhas. ATENÇÃO: uma linha por estabelecimento E commodity; o mesmo abatedouro aparece em várias linhas (Beef, Pork, Chicken...). Para contar estabelecimentos use COUNT(DISTINCT facility_id) ou filtre commodity = 'Beef'. É um retrato atual (2026), não histórico.

| Coluna | Descrição |
|---|---|
| `unique_id` | Identificador da linha (facility_id + commodity). |
| `facility_id` | Identificador do estabelecimento. |
| `company, cnpj` | Empresa e CNPJ. |
| `commodity` | Beef, Meat, Dairy, Chicken, Fish, Egg... |
| `type, type_detailed` | Tipo do estabelecimento em inglês (Slaughterhouse, Meat processing unit...) e detalhe. |
| `type_pt, type_detailed_pt` | Os mesmos em português. |
| `inspection_level` | SIF (federal, pode exportar), SIE (estadual), SIM (municipal), CONSORCIO (consórcio/SISBI). |
| `inspection_num` | Número de registro no serviço de inspeção. |
| `status` | Active, Inactive, Cancelado, Suspenso, Reserva ou NULL. |
| `state, municipality` | UF e município como na fonte (maiúsculas/minúsculas e acentos). |
| `state_norm, municipality_norm` | UF e município em MAIÚSCULAS SEM ACENTO, para juntar com as outras tabelas. |
| `lat, long` | Coordenadas. |
| `capacity_value, capacity_unit` | Capacidade numérica e unidade (Kg/day, Liter/day, Animal, Animal/hour...). |
| `approved_export_countries` | Países para os quais está habilitado a exportar ('Can not export' = não exporta). |
| `source` | SISBI, SIE database ou SIF database. |

## `entity_index` (tabela)

Valores distintos de nomes (municípios, exportadores, países...) para resolver grafias. Use a ferramenta find_entity.

| Coluna | Descrição |
|---|---|
| `kind, value, context, norm` |  |

## Catálogo de métricas espaciais

| Arquivo Trase | Métrica | Unidade | Soma entre regiões | Descrição |
|---|---|---|---|---|
| `cattle_deforestation_5_year_total` | `cattle_deforestation_ha` | ha | sim | Desmatamento atribuído à pecuária na região, janela de 5 anos até o ano. |
| `cattle_deforestation_per_tn_5_year_total` | `cattle_deforestation_ha_per_t` | ha/t | não | Desmatamento atribuído à pecuária por tonelada produzida (janela de 5 anos). |
| `cattle_tn` | `cattle_production_t` | t | sim | Produção bovina da região no ano. |
| `co2_gross_emissions_cattle_deforestation_5_year_total_exposure` | `co2_gross_cattle_deforestation_tco2e` | tCO2e | sim | Emissões brutas do desmatamento atribuído à pecuária (janela de 5 anos). |
| `co2_gross_emissions_cattle_deforestation_per_tn_5_year_total` | `co2_gross_cattle_deforestation_tco2e_per_t` | tCO2e/t | não | Emissões brutas do desmatamento atribuído à pecuária por tonelada. |
| `co2_gross_emissions_pasture_deforestation_5_year_total` | `co2_gross_pasture_deforestation_tco2e` | tCO2e | sim | Emissões brutas do desmatamento para pastagem (janela de 5 anos). |
| `co2_net_emissions_cattle_deforestation_5_year_total_exposure` | `co2_net_cattle_deforestation_tco2e` | tCO2e | sim | Emissões líquidas do desmatamento atribuído à pecuária (janela de 5 anos). |
| `co2_net_emissions_cattle_deforestation_per_tn_5_year_total` | `co2_net_cattle_deforestation_tco2e_per_t` | tCO2e/t | não | Emissões líquidas do desmatamento atribuído à pecuária por tonelada. |
| `co2_net_emissions_pasture_deforestation_5_year_total` | `co2_net_pasture_deforestation_tco2e` | tCO2e | sim | Emissões líquidas do desmatamento para pastagem (janela de 5 anos). |
| `pasture_deforestation_5_year_total` | `pasture_deforestation_ha` | ha | sim | Desmatamento para pastagem na região (janela de 5 anos). |
| `pasture_ha` | `pasture_area_ha` | ha | sim | Área de pastagem da região no ano. |
| `zdc_exported_brazil_beef_perc` | `zdc_exported_pct` | % (0-100) | não | Percentual da carne exportada da região por empresas com compromisso de desmatamento zero (ZDC). |
| `zdc_traded_brazil_beef_perc` | `zdc_produced_pct` | % (0-100) | não | Percentual da carne produzida na região comercializada sob compromisso de desmatamento zero (ZDC). |

## Regras de interpretação

- Exposição e emissões com janela de 5 anos: NÃO some entre anos (as janelas se sobrepõem e contam o mesmo desmatamento várias vezes). Responda por ano; para períodos, mostre a série ou a média anual e diga isso.
- Na supply_chain, exposição e emissões só existem de 2015 em diante; 2011-2014 aparecem como 0/NULL e significam 'sem dado', não 'zero desmatamento'. O ano de 2018 não existe na supply_chain (existe em spatial_metrics).
- A partir de 2015, a soma da exposição de todos os fluxos de um ano é igual ao desmatamento atribuído à pecuária no Brasil naquele ano (spatial_metrics, metric='cattle_deforestation_ha', level='country').
- Consumo interno: exporter = 'DOMESTIC PROCESSING AND CONSUMPTION' e country_of_destination = 'BRAZIL'. Para falar de exportação, exclua esses registros; para a cadeia inteira, mantenha.
- Origem desconhecida: o consumo interno não é rastreado até o município e aparece como UMA linha por ano com municipality_of_production = 'UNKNOWN' (UF 'UNKNOWN STATE', bioma 'UNKNOWN'); parte da exportação também (em 2023, 26% do volume exportado). Essa origem concentra ~90% da exposição de cada ano (2023: 6,87 de 7,49 mi ha), então os municípios identificados cobrem só ~8%. Em rankings de municípios, UFs ou biomas a partir da supply_chain, exclua 'UNKNOWN' (as consultas prontas já excluem) e avise que o ranking cobre apenas a parte rastreada. Para o desmatamento total de uma região, use spatial_metrics.
- Métricas por tonelada e percentuais não podem ser somados nem tirada média simples entre regiões: recalcule a partir dos totais (ex.: SUM(exposição)/SUM(volume)) ou use o valor da região agregada.
- Percentuais de spatial_metrics estão na escala 0-100.
- Nomes em supply_chain e spatial_metrics estão em MAIÚSCULAS SEM ACENTO. Em facilities use state_norm/municipality_norm. Antes de filtrar por um nome dito pelo usuário, confirme a grafia com find_entity.
- Exposição ao desmatamento é uma estimativa de associação da cadeia, não prova de ilegalidade nem de responsabilidade direta de uma empresa.
- Valores 'UNKNOWN' / 'UNKNOWN COUNTRY' são fluxos não identificados; mencione quando forem relevantes no ranking.
- facilities tem uma linha por estabelecimento e commodity: conte estabelecimentos com COUNT(DISTINCT facility_id).

# Dicionário da camada gold da soja

> Gerado de `src/medallion/catalog.py` (fonte única). Não edite à mão: mude o catálogo e rode `python -m src.cli build-medallion`.

## `soy_municipality_year`
**Granularidade:** município × ano. Fluxos da soja por município de produção, com sinal de anomalia.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `year` | int |  | Ano do fluxo. |
| `municipality_id` | str |  | Código IBGE do município (7 dígitos). Chave única em todas as tabelas. |
| `trase_municipality_id` | str |  | Código do município no Trase (BR-<IBGE>). |
| `municipality` | str |  | Nome do município (grafia do Trase, sem acento). |
| `state` | str |  | UF por extenso (grafia do Trase). |
| `biome` | str |  | Bioma do município. |
| `volume_tonnes` | float | t | Volume de soja exportado. |
| `fob_usd` | float | US$ | Valor FOB. |
| `land_use_ha` | float | ha | Área de soja associada ao fluxo. |
| `exposure_ha` | float | ha | Exposição ao desmatamento (janela de 5 anos; não somar entre anos). |
| `co2_net_tonnes` | float | tCO2e | Emissões líquidas de CO2 do desmatamento (janela de 5 anos). |
| `co2_gross_tonnes` | float | tCO2e | Emissões brutas de CO2 do desmatamento (janela de 5 anos). |
| `n_exporters` | int |  | Nº de grupos exportadores distintos. |
| `n_destinations` | int |  | Nº de países de destino distintos. |
| `exposure_ha_per_kt` | float | ha/kt | Exposição por mil toneladas de soja. |
| `co2_t_per_t` | float | tCO2e/t | CO2 líquido por tonelada de soja. |
| `volume_share_in_year` | float | fração | Participação no volume analítico do mesmo ano (soma 1 por ano). |
| `is_anomaly` | bool |  | Município marcado como atípico no ano (~2%). |
| `anomaly_score` | float |  | Pontuação de anomalia (maior = mais atípico; comparável só dentro do ano). |

**Cuidados:**
- exposure_ha é exposição ao desmatamento em JANELA DE 5 ANOS: não some entre anos (a mesma área aparece em até 5 anos); compare anos lado a lado. Existe só de 2013 em diante.
- Base analítica: só fluxos de origem conhecida, destino fora do Brasil e ano >= 2013. O volume doméstico e o de origem desconhecida ficam fora e aparecem em soy_national_year.
- is_anomaly marca ~2% dos municípios de cada ano (Isolation Forest sobre volume, exposição, CO2 e intensidades); é um sinal para investigar, não prova de irregularidade.

## `soy_exporter_group_year`
**Granularidade:** grupo exportador × ano. Fluxos da soja por grupo econômico exportador.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `year` | int |  | Ano do fluxo. |
| `exporter_group` | str |  | Grupo exportador (UNKNOWN = não identificado na fonte; não é uma empresa). |
| `volume_tonnes` | float | t | Volume de soja exportado. |
| `fob_usd` | float | US$ | Valor FOB. |
| `land_use_ha` | float | ha | Área de soja associada ao fluxo. |
| `exposure_ha` | float | ha | Exposição ao desmatamento (janela de 5 anos; não somar entre anos). |
| `co2_net_tonnes` | float | tCO2e | Emissões líquidas de CO2 do desmatamento (janela de 5 anos). |
| `co2_gross_tonnes` | float | tCO2e | Emissões brutas de CO2 do desmatamento (janela de 5 anos). |
| `n_municipalities` | int |  | Nº de municípios de origem distintos. |
| `n_destinations` | int |  | Nº de países de destino distintos. |
| `exposure_ha_per_kt` | float | ha/kt | Exposição por mil toneladas de soja. |
| `co2_t_per_t` | float | tCO2e/t | CO2 líquido por tonelada de soja. |
| `volume_share_in_year` | float | fração | Participação no volume analítico do mesmo ano (soma 1 por ano). |

**Cuidados:**
- exposure_ha é exposição ao desmatamento em JANELA DE 5 ANOS: não some entre anos (a mesma área aparece em até 5 anos); compare anos lado a lado. Existe só de 2013 em diante.
- Base analítica: só fluxos de origem conhecida, destino fora do Brasil e ano >= 2013. O volume doméstico e o de origem desconhecida ficam fora e aparecem em soy_national_year.

## `soy_exporter_company_year`
**Granularidade:** empresa exportadora × ano. Fluxos da soja por empresa exportadora (com o grupo).

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `year` | int |  | Ano do fluxo. |
| `exporter` | str |  | Empresa exportadora. |
| `exporter_group` | str |  | Grupo da empresa. |
| `volume_tonnes` | float | t | Volume de soja exportado. |
| `fob_usd` | float | US$ | Valor FOB. |
| `land_use_ha` | float | ha | Área de soja associada ao fluxo. |
| `exposure_ha` | float | ha | Exposição ao desmatamento (janela de 5 anos; não somar entre anos). |
| `co2_net_tonnes` | float | tCO2e | Emissões líquidas de CO2 do desmatamento (janela de 5 anos). |
| `co2_gross_tonnes` | float | tCO2e | Emissões brutas de CO2 do desmatamento (janela de 5 anos). |
| `n_municipalities` | int |  | Nº de municípios de origem distintos. |
| `n_destinations` | int |  | Nº de países de destino distintos. |
| `exposure_ha_per_kt` | float | ha/kt | Exposição por mil toneladas de soja. |
| `co2_t_per_t` | float | tCO2e/t | CO2 líquido por tonelada de soja. |
| `volume_share_in_year` | float | fração | Participação no volume analítico do mesmo ano (soma 1 por ano). |

**Cuidados:**
- exposure_ha é exposição ao desmatamento em JANELA DE 5 ANOS: não some entre anos (a mesma área aparece em até 5 anos); compare anos lado a lado. Existe só de 2013 em diante.
- Base analítica: só fluxos de origem conhecida, destino fora do Brasil e ano >= 2013. O volume doméstico e o de origem desconhecida ficam fora e aparecem em soy_national_year.

## `soy_destination_year`
**Granularidade:** país de destino × ano. Fluxos da soja por país de primeira importação.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `year` | int |  | Ano do fluxo. |
| `destination` | str |  | País de primeira importação (em inglês, como no Trase: CHINA, EUROPEAN UNION...). |
| `economic_bloc` | str |  | Bloco econômico do destino. |
| `volume_tonnes` | float | t | Volume de soja exportado. |
| `fob_usd` | float | US$ | Valor FOB. |
| `land_use_ha` | float | ha | Área de soja associada ao fluxo. |
| `exposure_ha` | float | ha | Exposição ao desmatamento (janela de 5 anos; não somar entre anos). |
| `co2_net_tonnes` | float | tCO2e | Emissões líquidas de CO2 do desmatamento (janela de 5 anos). |
| `co2_gross_tonnes` | float | tCO2e | Emissões brutas de CO2 do desmatamento (janela de 5 anos). |
| `n_exporters` | int |  | Nº de grupos exportadores distintos. |
| `n_municipalities` | int |  | Nº de municípios de origem distintos. |
| `exposure_ha_per_kt` | float | ha/kt | Exposição por mil toneladas de soja. |
| `co2_t_per_t` | float | tCO2e/t | CO2 líquido por tonelada de soja. |
| `volume_share_in_year` | float | fração | Participação no volume analítico do mesmo ano (soma 1 por ano). |

**Cuidados:**
- Base analítica: só fluxos de origem conhecida, destino fora do Brasil e ano >= 2013. O volume doméstico e o de origem desconhecida ficam fora e aparecem em soy_national_year.

## `soy_destination_state_year`
**Granularidade:** UF de origem × país de destino × ano. Como soy_destination_year, aberto por UF de origem.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `year` | int |  | Ano do fluxo. |
| `state` | str |  | UF de origem por extenso. |
| `destination` | str |  | País de primeira importação. |
| `economic_bloc` | str |  | Bloco econômico do destino. |
| `volume_tonnes` | float | t | Volume de soja exportado. |
| `fob_usd` | float | US$ | Valor FOB. |
| `land_use_ha` | float | ha | Área de soja associada ao fluxo. |
| `exposure_ha` | float | ha | Exposição ao desmatamento (janela de 5 anos; não somar entre anos). |
| `co2_net_tonnes` | float | tCO2e | Emissões líquidas de CO2 do desmatamento (janela de 5 anos). |
| `co2_gross_tonnes` | float | tCO2e | Emissões brutas de CO2 do desmatamento (janela de 5 anos). |
| `n_exporters` | int |  | Nº de grupos exportadores distintos. |
| `n_municipalities` | int |  | Nº de municípios de origem distintos. |
| `exposure_ha_per_kt` | float | ha/kt | Exposição por mil toneladas de soja. |
| `co2_t_per_t` | float | tCO2e/t | CO2 líquido por tonelada de soja. |
| `volume_share_in_year` | float | fração | Participação no volume analítico do mesmo ano (soma 1 por ano). |

**Cuidados:**
- Base analítica: só fluxos de origem conhecida, destino fora do Brasil e ano >= 2013. O volume doméstico e o de origem desconhecida ficam fora e aparecem em soy_national_year.
- Somar UFs dentro do MESMO ano é válido; somar anos não.

## `soy_biome_year`
**Granularidade:** bioma × ano. Fluxos da soja por bioma de origem.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `year` | int |  | Ano do fluxo. |
| `biome` | str |  | Bioma. |
| `volume_tonnes` | float | t | Volume de soja exportado. |
| `fob_usd` | float | US$ | Valor FOB. |
| `land_use_ha` | float | ha | Área de soja associada ao fluxo. |
| `exposure_ha` | float | ha | Exposição ao desmatamento (janela de 5 anos; não somar entre anos). |
| `co2_net_tonnes` | float | tCO2e | Emissões líquidas de CO2 do desmatamento (janela de 5 anos). |
| `co2_gross_tonnes` | float | tCO2e | Emissões brutas de CO2 do desmatamento (janela de 5 anos). |
| `n_exporters` | int |  | Nº de grupos exportadores distintos. |
| `n_destinations` | int |  | Nº de países de destino distintos. |
| `n_municipalities` | int |  | Nº de municípios de origem distintos. |
| `exposure_ha_per_kt` | float | ha/kt | Exposição por mil toneladas de soja. |
| `co2_t_per_t` | float | tCO2e/t | CO2 líquido por tonelada de soja. |
| `volume_share_in_year` | float | fração | Participação no volume analítico do mesmo ano (soma 1 por ano). |

**Cuidados:**
- exposure_ha é exposição ao desmatamento em JANELA DE 5 ANOS: não some entre anos (a mesma área aparece em até 5 anos); compare anos lado a lado. Existe só de 2013 em diante.
- Base analítica: só fluxos de origem conhecida, destino fora do Brasil e ano >= 2013. O volume doméstico e o de origem desconhecida ficam fora e aparecem em soy_national_year.

## `soy_national_year`
**Granularidade:** ano. Série nacional e reconciliação: quanto do volume entra e quanto fica fora da base analítica.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `year` | int |  | Ano do fluxo. |
| `volume_total_tonnes` | float | t | Volume total da fonte no ano (todas as linhas). |
| `volume_domestic_tonnes` | float | t | Volume processado no Brasil (destino doméstico). |
| `volume_unknown_origin_tonnes` | float | t | Volume de origem desconhecida (UNKNOWN STATE/BIOME). |
| `volume_analytic_tonnes` | float | t | Volume da base analítica (as outras tabelas somam isto). |
| `pct_domestic` | float | fração | Fração doméstica do volume total. |
| `pct_unknown_origin` | float | fração | Fração de origem desconhecida do volume total. |
| `pct_analytic` | float | fração | Fração do volume na base analítica. |
| `rows_total` | int |  | Linhas da fonte no ano. |
| `rows_analytic` | int |  | Linhas na base analítica. |
| `has_environmental_data` | bool |  | False antes de 2013 (exposição e CO2 não existem). |
| `fob_usd` | float | US$ | FOB da base analítica. |
| `exposure_ha` | float | ha | Exposição ao desmatamento da base analítica (nulo antes de 2013). |
| `co2_net_tonnes` | float | tCO2e | CO2 líquido da base analítica. |
| `co2_gross_tonnes` | float | tCO2e | CO2 bruto da base analítica. |

**Cuidados:**
- exposure_ha é exposição ao desmatamento em JANELA DE 5 ANOS: não some entre anos (a mesma área aparece em até 5 anos); compare anos lado a lado. Existe só de 2013 em diante.

## `inpe_deter_municipality_year`
**Granularidade:** município × ano × fonte × classe. Alertas de desmatamento do INPE DETER (Amazônia e Cerrado) por município.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `municipality_id` | str |  | Código IBGE do município. |
| `year` | int |  | Ano do alerta. |
| `source` | str |  | DETER Amazônia ou DETER Cerrado. |
| `alert_class` | str |  | Classe do alerta. |
| `area_ha` | float | ha | Área alertada. |
| `n_alerts` | int |  | Nº de alertas. |

**Cuidados:**
- Só alertas ligados a municípios presentes no Trase (Cerrado casa por nome+UF: ~82% dos alertas). DETER cobre 2021–2026 (2026 parcial); é alerta rápido, não desmatamento consolidado.

## `inpe_prodes_pampa_municipality_year`
**Granularidade:** município × ano. Desmatamento anual do INPE PRODES Pampa por município.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `municipality_id` | str |  | Código IBGE do município. |
| `year` | int |  | Ano (2021–2024). |
| `prodes_ha` | float | ha | Área desmatada. |

**Cuidados:**
- PRODES é corte raso anual consolidado; não se soma com o DETER.

## `soy_inpe_crosswalk`
**Granularidade:** município. Cruzamento por município: Trase (2013–2022) x INPE DETER x PRODES Pampa.

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `municipality_id` | str |  | Código IBGE do município. |
| `trase_municipality_id` | str |  | Código no Trase. |
| `municipality` | str |  | Município. |
| `state` | str |  | UF por extenso. |
| `biome` | str |  | Bioma dominante (maior volume). |
| `volume_tonnes` | float | t | Volume 2013–2022 (fluxos anuais: somar anos é válido para volume). |
| `land_use_ha` | float | ha | Área de soja, somada nos anos (usada só na razão abaixo). |
| `exposed_pct_of_land` | float | % | Exposição ÷ área de soja ×100: média ponderada pela área (NÃO é soma de exposição). |
| `co2_t_per_t` | float | tCO2e/t | CO2 líquido por tonelada de soja. |
| `exposure_2022_ha` | float | ha | Exposição ao desmatamento só de 2022. |
| `volume_eu_tonnes` | float | t | Volume com destino à União Europeia. |
| `deter_ha_2021_22` | float | ha | Alertas DETER em 2021–2022. |
| `deter_ha_2023_26` | float | ha | Alertas DETER em 2023–2026 (2026 parcial). |
| `deter_ha_total` | float | ha | Alertas DETER 2021–2026. |
| `deter_source` | str |  | Fonte(s) DETER do município (nulo = sem alerta). |
| `prodes_pampa_ha_2021` | float | ha | PRODES Pampa 2021. |
| `prodes_pampa_ha_2022` | float | ha | PRODES Pampa 2022. |
| `prodes_pampa_ha_2021_24` | float | ha | PRODES Pampa 2021–2024. |
| `has_inpe_coverage` | bool |  | Tem alerta DETER ou está no Pampa (cobertura PRODES). |

**Cuidados:**
- Não existe coluna de exposição somada entre anos; use exposure_2022_ha ou exposed_pct_of_land.
- Correlações com DETER são moderadas; trate como sinal complementar.

## `dim_entity`
**Granularidade:** entidade. Nomes normalizados para confirmar grafias antes de filtrar (município, exportador, grupo, destino, UF, bioma).

| coluna | tipo | unidade | descrição |
|---|---|---|---|
| `entity_type` | str |  | municipality | exporter | exporter_group | destination | state | biome. |
| `entity_id` | str |  | IBGE (município) ou o próprio nome. |
| `name` | str |  | Nome como aparece nas tabelas gold. |
| `name_normalized` | str |  | Nome sem acento, maiúsculo (para comparar com o texto do usuário). |
| `state` | str |  | UF (só município). |

**Cuidados:**
- Use name_normalized para achar a grafia exata antes de filtrar.

-- =============================================================================
-- Camada Gold — Materialized Views para o Mapa Interativo e o Agente de IA
-- =============================================================================
-- Regras metodológicas respeitadas:
--   1. Nunca somar métricas de fontes distintas (MapBiomas, INPE DETER e Trase
--      permanecem em colunas separadas e claramente prefixadas).
--   2. Exposição ao desmatamento da Trase (janela de 5 anos) NÃO deve ser somada
--      entre anos — cada linha aqui representa um único ano.
--   3. Origens desconhecidas (codigo_municipio_ibge IS NULL) são quantificadas
--      explicitamente em gold.mv_cobertura_incerteza para o selo de transparência.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Painel territorial por município e ano (coroplético + consultas do agente)
-- -----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS gold.mv_territorio_municipal_ano;

CREATE MATERIALIZED VIEW gold.mv_territorio_municipal_ano AS
WITH anos AS (
    SELECT DISTINCT ano, codigo_municipio_ibge FROM agro.fato_ibge_pam_soja
    UNION
    SELECT DISTINCT ano, codigo_municipio_ibge FROM agro.fato_ibge_ppm_bovinos
    UNION
    SELECT DISTINCT ano, codigo_municipio_ibge FROM agro.fato_mapbiomas_desmatamento
    UNION
    SELECT DISTINCT ano, codigo_municipio_ibge FROM agro.fato_trase_fluxos
     WHERE codigo_municipio_ibge IS NOT NULL
    UNION
    SELECT DISTINCT ano, codigo_municipio_ibge FROM agro.fato_inpe_deter
     WHERE codigo_municipio_ibge IS NOT NULL AND ano IS NOT NULL
    UNION
    SELECT DISTINCT ano, codigo_municipio_ibge FROM agro.fato_seeg_emissoes
     WHERE codigo_municipio_ibge IS NOT NULL
    UNION
    SELECT DISTINCT ano, codigo_municipio_ibge FROM agro.fato_comex_exportacoes
     WHERE codigo_municipio_ibge IS NOT NULL
),
mb_cob AS (
    SELECT
        ano,
        codigo_municipio_ibge,
        SUM(area_ha) FILTER (WHERE classe_nivel_1 = '1. Forest') AS mapbiomas_floresta_ha,
        SUM(area_ha) FILTER (WHERE classe_nivel_2 ILIKE '%Pasture%' OR classe_nivel_3 ILIKE '%Pasture%') AS mapbiomas_pastagem_ha,
        SUM(area_ha) FILTER (WHERE classe_nivel_3 ILIKE '%Soy%' OR classe_nivel_4 ILIKE '%Soy%') AS mapbiomas_soja_ha,
        SUM(area_ha) FILTER (WHERE classe_nivel_1 = '3. Farming') AS mapbiomas_agropecuaria_ha
    FROM agro.fato_mapbiomas_cobertura
    GROUP BY ano, codigo_municipio_ibge
),
mb_desm AS (
    SELECT
        ano,
        codigo_municipio_ibge,
        SUM(area_ha) FILTER (
            WHERE classe_transicao_nome ILIKE '%Suppression%'
               OR classe_transicao_nome ILIKE '%Desmatamento%'
               OR classe_transicao_id IN (4, 6)
        ) AS mapbiomas_desmatamento_ha
    FROM agro.fato_mapbiomas_desmatamento
    GROUP BY ano, codigo_municipio_ibge
),
trase_agg AS (
    SELECT
        ano,
        codigo_municipio_ibge,
        SUM(volume_comercializado_t) FILTER (WHERE produto = 'soja') AS trase_soja_volume_t,
        SUM(valor_comercializado_usd) FILTER (WHERE produto = 'soja') AS trase_soja_fob_usd,
        SUM(desmatamento_exposicao_5_anos_ha) FILTER (WHERE produto = 'soja') AS trase_soja_exposicao_5a_ha,
        SUM(emissoes_liquidas_5_anos_tco2e) FILTER (WHERE produto = 'soja') AS trase_soja_emissoes_liq_tco2e,
        SUM(volume_comercializado_t) FILTER (WHERE produto = 'bovinos') AS trase_bovinos_volume_t,
        SUM(valor_comercializado_usd) FILTER (WHERE produto = 'bovinos') AS trase_bovinos_fob_usd,
        SUM(desmatamento_exposicao_5_anos_ha) FILTER (WHERE produto = 'bovinos') AS trase_bovinos_exposicao_5a_ha,
        SUM(emissoes_liquidas_5_anos_tco2e) FILTER (WHERE produto = 'bovinos') AS trase_bovinos_emissoes_liq_tco2e
    FROM agro.fato_trase_fluxos
    WHERE codigo_municipio_ibge IS NOT NULL
    GROUP BY ano, codigo_municipio_ibge
),
deter_agg AS (
    SELECT
        ano,
        codigo_municipio_ibge,
        COUNT(*) AS inpe_deter_alertas,
        SUM(area_mun_km2) AS inpe_deter_area_km2
    FROM agro.fato_inpe_deter
    WHERE codigo_municipio_ibge IS NOT NULL AND ano IS NOT NULL
    GROUP BY ano, codigo_municipio_ibge
),
sif_agg AS (
    SELECT
        codigo_municipio_ibge,
        COUNT(*) FILTER (WHERE cadeia = 'bovinos') AS inst_bovinos_total,
        COUNT(*) FILTER (WHERE cadeia = 'soja') AS inst_soja_total
    FROM agro.dim_instalacoes
    WHERE codigo_municipio_ibge IS NOT NULL
    GROUP BY codigo_municipio_ibge
),
seeg_agg AS (
    SELECT
        ano,
        codigo_municipio_ibge,
        SUM(emissao_tco2e) FILTER (WHERE tipo_fluxo = 'Emissão') AS seeg_emissao_total_tco2e,
        SUM(emissao_tco2e) FILTER (WHERE tipo_fluxo = 'Emissão' AND setor ILIKE 'Agropecu%') AS seeg_emissao_agro_tco2e,
        SUM(emissao_tco2e) FILTER (WHERE tipo_fluxo = 'Emissão' AND setor ILIKE 'Mudança de Uso%') AS seeg_emissao_mut_tco2e
    FROM agro.fato_seeg_emissoes
    WHERE codigo_municipio_ibge IS NOT NULL
    GROUP BY ano, codigo_municipio_ibge
),
comex_agg AS (
    SELECT
        ano,
        codigo_municipio_ibge,
        SUM(kg_liquido) FILTER (WHERE produto = 'soja') / 1000.0 AS comex_soja_t,
        SUM(valor_fob_usd) FILTER (WHERE produto = 'soja') AS comex_soja_fob_usd,
        SUM(kg_liquido) FILTER (WHERE produto = 'bovinos') / 1000.0 AS comex_bovinos_t,
        SUM(valor_fob_usd) FILTER (WHERE produto = 'bovinos') AS comex_bovinos_fob_usd
    FROM agro.fato_comex_exportacoes
    WHERE codigo_municipio_ibge IS NOT NULL
    GROUP BY ano, codigo_municipio_ibge
)
SELECT
    a.ano,
    m.codigo_municipio_ibge,
    m.municipio,
    m.uf,
    m.regiao,
    m.bioma_predominante,
    m.lat,
    m.lon,
    -- IBGE PAM / PPM
    pam.area_plantada_ha             AS ibge_soja_area_plantada_ha,
    pam.quantidade_produzida_t       AS ibge_soja_producao_t,
    pam.rendimento_medio_kg_ha       AS ibge_soja_rendimento_kg_ha,
    ppm.rebanho_bovino_cabecas       AS ibge_bovinos_rebanho_cab,
    -- MapBiomas Col. 11
    mbc.mapbiomas_floresta_ha,
    mbc.mapbiomas_pastagem_ha,
    mbc.mapbiomas_soja_ha,
    mbc.mapbiomas_agropecuaria_ha,
    mbd.mapbiomas_desmatamento_ha,
    -- INPE DETER
    det.inpe_deter_alertas,
    det.inpe_deter_area_km2,
    -- SEEG Coleção 14 (tCO2e GWP-AR5)
    sg.seeg_emissao_total_tco2e,
    sg.seeg_emissao_agro_tco2e,
    sg.seeg_emissao_mut_tco2e,
    -- Comex Stat (MDIC)
    cx.comex_soja_t,
    cx.comex_soja_fob_usd,
    cx.comex_bovinos_t,
    cx.comex_bovinos_fob_usd,
    -- Trase Cadeias
    tr.trase_soja_volume_t,
    tr.trase_soja_fob_usd,
    tr.trase_soja_exposicao_5a_ha,
    tr.trase_soja_emissoes_liq_tco2e,
    tr.trase_bovinos_volume_t,
    tr.trase_bovinos_fob_usd,
    tr.trase_bovinos_exposicao_5a_ha,
    tr.trase_bovinos_emissoes_liq_tco2e,
    -- Infraestrutura (Frigoríficos e Silos)
    COALESCE(sif.inst_bovinos_total, 0) AS inst_bovinos_total,
    COALESCE(sif.inst_soja_total, 0)    AS inst_soja_total
FROM anos a
JOIN agro.dim_municipios m
  ON m.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN agro.fato_ibge_pam_soja pam
  ON pam.ano = a.ano AND pam.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN agro.fato_ibge_ppm_bovinos ppm
  ON ppm.ano = a.ano AND ppm.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN mb_cob mbc
  ON mbc.ano = a.ano AND mbc.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN mb_desm mbd
  ON mbd.ano = a.ano AND mbd.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN trase_agg tr
  ON tr.ano = a.ano AND tr.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN deter_agg det
  ON det.ano = a.ano AND det.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN seeg_agg sg
  ON sg.ano = a.ano AND sg.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN comex_agg cx
  ON cx.ano = a.ano AND cx.codigo_municipio_ibge = a.codigo_municipio_ibge
LEFT JOIN sif_agg sif
  ON sif.codigo_municipio_ibge = a.codigo_municipio_ibge;

CREATE UNIQUE INDEX idx_mv_terr_pk
    ON gold.mv_territorio_municipal_ano (ano, codigo_municipio_ibge);
CREATE INDEX idx_mv_terr_uf_ano
    ON gold.mv_territorio_municipal_ano (uf, ano);
CREATE INDEX idx_mv_terr_bioma_ano
    ON gold.mv_territorio_municipal_ano (bioma_predominante, ano);

-- -----------------------------------------------------------------------------
-- 2. Rede agregada de fluxos (substitui o scan de CSV em map_network.py)
-- -----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS gold.mv_rede_fluxos;

CREATE MATERIALIZED VIEW gold.mv_rede_fluxos AS
SELECT
    produto,
    ano,
    codigo_municipio_ibge,
    municipio_producao,
    estado_producao,
    bioma,
    hub_logistico,
    porto_exportacao,
    pais_destino,
    pais_destino_trase_id,
    COUNT(*)                                AS registros,
    SUM(volume_comercializado_t)            AS volume_t,
    SUM(valor_comercializado_usd)           AS valor_usd,
    SUM(desmatamento_exposicao_5_anos_ha)   AS exposicao_desmatamento_ha,
    SUM(emissoes_liquidas_5_anos_tco2e)     AS emissoes_liquidas_tco2e
FROM agro.fato_trase_fluxos
GROUP BY
    produto, ano, codigo_municipio_ibge, municipio_producao,
    estado_producao, bioma, hub_logistico, porto_exportacao,
    pais_destino, pais_destino_trase_id;

CREATE INDEX idx_mv_rede_prod_ano
    ON gold.mv_rede_fluxos (produto, ano);
CREATE INDEX idx_mv_rede_mun
    ON gold.mv_rede_fluxos (codigo_municipio_ibge, produto, ano);
CREATE INDEX idx_mv_rede_pais
    ON gold.mv_rede_fluxos (pais_destino_trase_id, produto, ano);

-- -----------------------------------------------------------------------------
-- 3. Cobertura e incerteza (% rastreado vs UNKNOWN por produto/ano/UF)
-- -----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS gold.mv_cobertura_incerteza;

CREATE MATERIALIZED VIEW gold.mv_cobertura_incerteza AS
SELECT
    produto,
    ano,
    COALESCE(estado_producao, 'UNKNOWN') AS estado_producao,
    COUNT(*) AS total_registros,
    COUNT(*) FILTER (WHERE codigo_municipio_ibge IS NOT NULL) AS registros_rastreados,
    SUM(volume_comercializado_t) AS volume_total_t,
    SUM(volume_comercializado_t) FILTER (WHERE codigo_municipio_ibge IS NOT NULL) AS volume_rastreado_t,
    CASE
        WHEN SUM(volume_comercializado_t) > 0
        THEN ROUND(
            (100.0 * COALESCE(SUM(volume_comercializado_t) FILTER (WHERE codigo_municipio_ibge IS NOT NULL), 0)
             / SUM(volume_comercializado_t))::numeric, 2
        )
        ELSE NULL
    END AS pct_volume_rastreado,
    SUM(desmatamento_exposicao_5_anos_ha) AS exposicao_total_ha,
    SUM(desmatamento_exposicao_5_anos_ha) FILTER (WHERE codigo_municipio_ibge IS NOT NULL) AS exposicao_rastreada_ha
FROM agro.fato_trase_fluxos
GROUP BY produto, ano, COALESCE(estado_producao, 'UNKNOWN');

CREATE INDEX idx_mv_cob_prod_ano
    ON gold.mv_cobertura_incerteza (produto, ano);

-- Garantir leitura para a role agro_ro nas materialized views
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO agro_ro;

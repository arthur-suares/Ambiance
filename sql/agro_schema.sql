-- =============================================================================
-- Ecossistema Agroambiental Unificado (PostgreSQL 17 + pgvector + PostGIS)
-- =============================================================================
-- Schemas:
--   public -> Camada documental/RAG existente (documents, chunks) [intocada]
--   agro   -> Dimensões canônicas + Fatos padronizados (chave: codigo_municipio_ibge + ano)
--   gold   -> Materialized Views otimizadas para o Mapa Interativo e o Agente de IA
--
-- Idempotente: pode ser executado várias vezes sem perder dados existentes.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE SCHEMA IF NOT EXISTS agro;
CREATE SCHEMA IF NOT EXISTS gold;

-- -----------------------------------------------------------------------------
-- 1. DIMENSÕES CANÔNICAS
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agro.dim_fontes (
    fonte_id          TEXT PRIMARY KEY,
    nome              TEXT NOT NULL,
    orgao             TEXT NOT NULL,
    categoria         TEXT NOT NULL, -- producao, uso_terra, desmatamento, emissoes, cadeia, infraestrutura, governanca
    url               TEXT,
    versao            TEXT,
    ano_inicio        SMALLINT,
    ano_fim           SMALLINT,
    grao              TEXT NOT NULL, -- municipio_ano, fluxo_ano, alerta_data, estabelecimento
    limitacoes        TEXT NOT NULL,
    registros         BIGINT DEFAULT 0,
    atualizado_em     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agro.dim_municipios (
    codigo_municipio_ibge CHAR(7) PRIMARY KEY,
    municipio             TEXT NOT NULL,
    municipio_norm        TEXT NOT NULL,
    uf                    CHAR(2) NOT NULL,
    uf_nome               TEXT NOT NULL,
    regiao                TEXT NOT NULL,
    bioma_predominante    TEXT,
    lat                   DOUBLE PRECISION,
    lon                   DOUBLE PRECISION,
    area_km2              DOUBLE PRECISION,
    geom                  GEOMETRY(MultiPolygon, 4326)
);

CREATE INDEX IF NOT EXISTS idx_dim_municipios_uf_norm
    ON agro.dim_municipios (uf, municipio_norm);
CREATE INDEX IF NOT EXISTS idx_dim_municipios_norm
    ON agro.dim_municipios (municipio_norm);
CREATE INDEX IF NOT EXISTS idx_dim_municipios_geom
    ON agro.dim_municipios USING GIST (geom);

CREATE TABLE IF NOT EXISTS agro.dim_instalacoes_sif (
    id                    BIGSERIAL PRIMARY KEY,
    sif                   TEXT NOT NULL,
    cnpj                  TEXT,
    razao_social          TEXT,
    municipio             TEXT,
    municipio_norm        TEXT,
    uf                    CHAR(2),
    codigo_municipio_ibge CHAR(7) REFERENCES agro.dim_municipios(codigo_municipio_ibge),
    categoria             TEXT,
    classe                TEXT,
    situacao              TEXT,
    area_atuacao          TEXT,
    fonte                 TEXT NOT NULL DEFAULT 'MAPA SIGSIF'
);

CREATE INDEX IF NOT EXISTS idx_dim_sif_mun ON agro.dim_instalacoes_sif (codigo_municipio_ibge);
CREATE INDEX IF NOT EXISTS idx_dim_sif_uf ON agro.dim_instalacoes_sif (uf);
CREATE INDEX IF NOT EXISTS idx_dim_sif_num ON agro.dim_instalacoes_sif (sif);

-- -----------------------------------------------------------------------------
-- 2. FATOS — PRODUÇÃO AGROPECUÁRIA (IBGE PAM & PPM)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agro.fato_ibge_pam_soja (
    ano                              SMALLINT NOT NULL,
    codigo_municipio_ibge            CHAR(7) NOT NULL REFERENCES agro.dim_municipios(codigo_municipio_ibge),
    area_plantada_ha                 DOUBLE PRECISION,
    status_area_plantada             TEXT,
    area_colhida_ha                  DOUBLE PRECISION,
    status_area_colhida              TEXT,
    quantidade_produzida_t           DOUBLE PRECISION,
    status_quantidade_produzida      TEXT,
    rendimento_medio_kg_ha           DOUBLE PRECISION,
    status_rendimento_medio          TEXT,
    valor_producao_mil_reais_nominal DOUBLE PRECISION,
    status_valor_producao            TEXT,
    fonte                            TEXT NOT NULL DEFAULT 'IBGE PAM',
    tabela_sidra                     TEXT,
    PRIMARY KEY (ano, codigo_municipio_ibge)
);

CREATE INDEX IF NOT EXISTS idx_pam_soja_mun_ano
    ON agro.fato_ibge_pam_soja (codigo_municipio_ibge, ano);

CREATE TABLE IF NOT EXISTS agro.fato_ibge_ppm_bovinos (
    ano                    SMALLINT NOT NULL,
    codigo_municipio_ibge  CHAR(7) NOT NULL REFERENCES agro.dim_municipios(codigo_municipio_ibge),
    rebanho_bovino_cabecas BIGINT,
    status_rebanho_bovino  TEXT,
    unidade                TEXT DEFAULT 'cabecas',
    fonte                  TEXT NOT NULL DEFAULT 'IBGE PPM',
    tabela_sidra           TEXT,
    PRIMARY KEY (ano, codigo_municipio_ibge)
);

CREATE INDEX IF NOT EXISTS idx_ppm_bovinos_mun_ano
    ON agro.fato_ibge_ppm_bovinos (codigo_municipio_ibge, ano);

-- -----------------------------------------------------------------------------
-- 3. FATOS — USO DA TERRA E DESMATAMENTO (MAPBIOMAS COL. 11 & INPE DETER)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agro.fato_mapbiomas_cobertura (
    ano                   SMALLINT NOT NULL,
    codigo_municipio_ibge CHAR(7) NOT NULL REFERENCES agro.dim_municipios(codigo_municipio_ibge),
    bioma                 TEXT NOT NULL,
    classe_id             SMALLINT NOT NULL,
    classe_nivel_0        TEXT,
    classe_nivel_1        TEXT,
    classe_nivel_2        TEXT,
    classe_nivel_3        TEXT,
    classe_nivel_4        TEXT,
    area_ha               DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mb_cob_mun_ano
    ON agro.fato_mapbiomas_cobertura (codigo_municipio_ibge, ano);
CREATE INDEX IF NOT EXISTS idx_mb_cob_ano_n1
    ON agro.fato_mapbiomas_cobertura (ano, classe_nivel_1);

CREATE TABLE IF NOT EXISTS agro.fato_mapbiomas_desmatamento (
    ano                   SMALLINT NOT NULL,
    codigo_municipio_ibge CHAR(7) NOT NULL REFERENCES agro.dim_municipios(codigo_municipio_ibge),
    bioma                 TEXT NOT NULL,
    colecao               TEXT,
    classe_transicao_id   SMALLINT,
    classe_transicao_nome TEXT,
    classe_id             SMALLINT,
    classe_nivel_0        TEXT,
    classe_nivel_1        TEXT,
    classe_nivel_2        TEXT,
    classe_nivel_3        TEXT,
    classe_nivel_4        TEXT,
    area_ha               DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mb_desm_mun_ano
    ON agro.fato_mapbiomas_desmatamento (codigo_municipio_ibge, ano);
CREATE INDEX IF NOT EXISTS idx_mb_desm_ano_trans
    ON agro.fato_mapbiomas_desmatamento (ano, classe_transicao_nome);

CREATE TABLE IF NOT EXISTS agro.fato_inpe_deter (
    id                    BIGSERIAL PRIMARY KEY,
    bioma                 TEXT NOT NULL, -- AMAZONIA | CERRADO | PANTANAL
    view_date             DATE,
    ano                   SMALLINT,
    mes                   SMALLINT,
    classname             TEXT,
    codigo_municipio_ibge CHAR(7),
    municipio             TEXT,
    uf                    CHAR(2),
    uc                    TEXT,
    area_mun_km2          DOUBLE PRECISION,
    area_uc_km2           DOUBLE PRECISION,
    sensor                TEXT,
    satellite             TEXT,
    lat                   DOUBLE PRECISION,
    lon                   DOUBLE PRECISION
);

ALTER TABLE agro.fato_inpe_deter ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE agro.fato_inpe_deter ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_deter_mun_ano
    ON agro.fato_inpe_deter (codigo_municipio_ibge, ano, mes);
CREATE INDEX IF NOT EXISTS idx_deter_bioma_date
    ON agro.fato_inpe_deter (bioma, view_date);

-- -----------------------------------------------------------------------------
-- 4. FATOS — CADEIAS DE ABASTECIMENTO (TRASE SOJA + BOVINOS UNIFICADOS)
-- -----------------------------------------------------------------------------
-- Preserva codigo_municipio_ibge NULL quando a origem for BR-XXXXXXX / UNKNOWN.

CREATE TABLE IF NOT EXISTS agro.fato_trase_fluxos (
    id                               BIGSERIAL PRIMARY KEY,
    produto                          TEXT NOT NULL, -- 'soja' | 'bovinos'
    ano                              SMALLINT NOT NULL,
    codigo_municipio_ibge            CHAR(7),       -- NULL quando origem UNKNOWN
    municipio_producao               TEXT,
    estado_producao                  TEXT,
    bioma                            TEXT,
    hub_logistico                    TEXT,          -- hub_logistico (soja) ou municipio_abate (bovinos)
    porto_exportacao                 TEXT,
    tipo_produto                     TEXT,
    exportador                       TEXT,
    grupo_exportador                 TEXT,
    importador                       TEXT,
    grupo_importador                 TEXT,
    pais_destino                     TEXT,
    pais_destino_trase_id            TEXT,
    bloco_economico                  TEXT,
    volume_comercializado_t          DOUBLE PRECISION,
    valor_comercializado_usd         DOUBLE PRECISION,
    area_uso_ha                      DOUBLE PRECISION, -- area_soja_ha ou area_pastagem_ha
    desmatamento_exposicao_5_anos_ha DOUBLE PRECISION,
    emissoes_liquidas_5_anos_tco2e   DOUBLE PRECISION,
    emissoes_brutas_5_anos_tco2e     DOUBLE PRECISION,
    compromisso_desmatamento_zero    TEXT,
    forest_500_score                 DOUBLE PRECISION,
    municipio_producao_trase_id      TEXT,
    fonte                            TEXT,
    versao_fonte                     TEXT
);

CREATE INDEX IF NOT EXISTS idx_trase_prod_ano_mun
    ON agro.fato_trase_fluxos (produto, ano, codigo_municipio_ibge);
CREATE INDEX IF NOT EXISTS idx_trase_prod_ano_uf
    ON agro.fato_trase_fluxos (produto, ano, estado_producao);
CREATE INDEX IF NOT EXISTS idx_trase_prod_ano_pais
    ON agro.fato_trase_fluxos (produto, ano, pais_destino_trase_id);
CREATE INDEX IF NOT EXISTS idx_trase_prod_ano_exp
    ON agro.fato_trase_fluxos (produto, ano, grupo_exportador);

-- -----------------------------------------------------------------------------
-- 5. EMISSÕES (SEEG), INFRAESTRUTURA (FRIGORÍFICOS/SILOS) E COMÉRCIO (COMEX)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agro.dim_instalacoes (
    id                    BIGSERIAL PRIMARY KEY,
    cadeia                TEXT NOT NULL, -- 'bovinos' | 'soja'
    facility_id           TEXT,
    cnpj                  TEXT,
    empresa               TEXT,
    tipo                  TEXT,
    tipo_detalhado        TEXT,
    nivel_inspecao        TEXT,          -- SIF | SIE | SIM | SISBI | SICARM
    numero_inspecao       TEXT,
    status                TEXT,
    capacidade_valor      DOUBLE PRECISION,
    capacidade_unidade    TEXT,
    codigo_municipio_ibge CHAR(7) REFERENCES agro.dim_municipios(codigo_municipio_ibge),
    municipio             TEXT,
    uf                    CHAR(2),
    lat                   DOUBLE PRECISION,
    lon                   DOUBLE PRECISION,
    geom                  GEOMETRY(Point, 4326),
    fonte                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dim_inst_cadeia_uf ON agro.dim_instalacoes (cadeia, uf);
CREATE INDEX IF NOT EXISTS idx_dim_inst_mun ON agro.dim_instalacoes (codigo_municipio_ibge);
CREATE INDEX IF NOT EXISTS idx_dim_inst_geom ON agro.dim_instalacoes USING GIST (geom);

CREATE TABLE IF NOT EXISTS agro.fato_comex_exportacoes (
    id                    BIGSERIAL PRIMARY KEY,
    ano                   SMALLINT NOT NULL,
    mes                   SMALLINT NOT NULL,
    produto               TEXT NOT NULL, -- 'soja' | 'bovinos'
    sh4                   CHAR(4) NOT NULL,
    sh4_desc              TEXT,
    codigo_municipio_ibge CHAR(7),
    uf                    CHAR(2),
    co_pais               TEXT,
    pais                  TEXT,
    kg_liquido            DOUBLE PRECISION,
    valor_fob_usd         DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_comex_prod_ano_mun ON agro.fato_comex_exportacoes (produto, ano, codigo_municipio_ibge);
CREATE INDEX IF NOT EXISTS idx_comex_ano_uf ON agro.fato_comex_exportacoes (ano, uf);

CREATE TABLE IF NOT EXISTS agro.fato_seeg_emissoes (
    id                    BIGSERIAL PRIMARY KEY,
    ano                   SMALLINT NOT NULL,
    codigo_municipio_ibge CHAR(7),
    uf                    CHAR(2),
    tipo_fluxo            TEXT,          -- Emissão | Remoção | Bunker
    setor                 TEXT NOT NULL,
    subsetor              TEXT,
    atividade             TEXT,
    gas                   TEXT NOT NULL,
    emissao_tco2e         DOUBLE PRECISION,
    versao_seeg           TEXT
);

ALTER TABLE agro.fato_seeg_emissoes ADD COLUMN IF NOT EXISTS tipo_fluxo TEXT;

CREATE INDEX IF NOT EXISTS idx_seeg_mun_ano
    ON agro.fato_seeg_emissoes (codigo_municipio_ibge, ano, setor);

-- -----------------------------------------------------------------------------
-- 6. ROLE SOMENTE-LEITURA PARA O AGENTE SQL
-- -----------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agro_ro') THEN
        CREATE ROLE agro_ro NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA agro, gold TO agro_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA agro, gold TO agro_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA agro GRANT SELECT ON TABLES TO agro_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO agro_ro;

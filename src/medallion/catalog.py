"""Catálogo da camada gold da soja: FONTE ÚNICA do dicionário.

Daqui saem (1) o contrato de cada tabela (colunas e tipos conferidos a cada carga), (2) a tabela `gold_catalog`
dentro do banco do agente, (3) o trecho de prompt do agente (src/soy/queries.py:schema_prompt) e (4) o
docs/dicionario_gold.md. Para mudar uma descrição ou regra, mude aqui e rode `python -m src.cli build-medallion`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

WINDOW_NOTE = ("exposure_ha é exposição ao desmatamento em JANELA DE 5 ANOS: não some entre anos "
               "(a mesma área aparece em até 5 anos); compare anos lado a lado. Existe só de 2013 em diante.")
BASE_NOTE = ("Base analítica: só fluxos de origem conhecida, destino fora do Brasil e ano >= 2013. O volume doméstico e o de "
             "origem desconhecida ficam fora e aparecem em soy_national_year.")


@dataclass(frozen=True)
class Col:
    name: str
    kind: str                    # int | float | str | bool
    desc: str
    unit: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    grain: str
    desc: str
    cols: tuple[Col, ...]
    caveats: tuple[str, ...] = ()
    municipality_key: bool = False
    extra: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def col_names(self) -> list[str]:
        return [c.name for c in self.cols]


YEAR = Col("year", "int", "Ano do fluxo.")
MEASURES = (
    Col("volume_tonnes", "float", "Volume de soja exportado.", "t"),
    Col("fob_usd", "float", "Valor FOB.", "US$"),
    Col("land_use_ha", "float", "Área de soja associada ao fluxo.", "ha"),
    Col("exposure_ha", "float", "Exposição ao desmatamento (janela de 5 anos; não somar entre anos).", "ha"),
    Col("co2_net_tonnes", "float", "Emissões líquidas de CO2 do desmatamento (janela de 5 anos).", "tCO2e"),
    Col("co2_gross_tonnes", "float", "Emissões brutas de CO2 do desmatamento (janela de 5 anos).", "tCO2e"),
)
RATIOS = (
    Col("exposure_ha_per_kt", "float", "Exposição por mil toneladas de soja.", "ha/kt"),
    Col("co2_t_per_t", "float", "CO2 líquido por tonelada de soja.", "tCO2e/t"),
    Col("volume_share_in_year", "float", "Participação no volume analítico do mesmo ano (soma 1 por ano).", "fração"),
)
N_EXP = Col("n_exporters", "int", "Nº de grupos exportadores distintos.")
N_DEST = Col("n_destinations", "int", "Nº de países de destino distintos.")
N_MUN = Col("n_municipalities", "int", "Nº de municípios de origem distintos.")


def _t(name, grain, desc, keys, counts, tail=(), **kw) -> Table:
    return Table(name, grain, desc, (YEAR, *keys, *MEASURES, *counts, *RATIOS, *tail), **kw)


GOLD: dict[str, Table] = {t.name: t for t in [
    _t("soy_municipality_year", "município × ano", "Fluxos da soja por município de produção, com sinal de anomalia.",
       (Col("municipality_id", "str", "Código IBGE do município (7 dígitos). Chave única em todas as tabelas."),
        Col("trase_municipality_id", "str", "Código do município no Trase (BR-<IBGE>)."),
        Col("municipality", "str", "Nome do município (grafia do Trase, sem acento)."),
        Col("state", "str", "UF por extenso (grafia do Trase)."),
        Col("biome", "str", "Bioma do município.")),
       (N_EXP, N_DEST), municipality_key=True,
       tail=(Col("is_anomaly", "bool", "Município marcado como atípico no ano (~2%)."),
             Col("anomaly_score", "float", "Pontuação de anomalia (maior = mais atípico; comparável só dentro do ano).")),
       caveats=(WINDOW_NOTE, BASE_NOTE, "is_anomaly marca ~2% dos municípios de cada ano (Isolation Forest sobre volume, "
                "exposição, CO2 e intensidades); é um sinal para investigar, não prova de irregularidade.")),
    _t("soy_exporter_group_year", "grupo exportador × ano", "Fluxos da soja por grupo econômico exportador.",
       (Col("exporter_group", "str", "Grupo exportador (UNKNOWN = não identificado na fonte; não é uma empresa)."),),
       (N_MUN, N_DEST), caveats=(WINDOW_NOTE, BASE_NOTE)),
    _t("soy_exporter_company_year", "empresa exportadora × ano", "Fluxos da soja por empresa exportadora (com o grupo).",
       (Col("exporter", "str", "Empresa exportadora (UNKNOWN CUSTOMER = exportador não identificado na fonte; não é uma empresa)."), Col("exporter_group", "str", "Grupo da empresa.")),
       (N_MUN, N_DEST), caveats=(WINDOW_NOTE, BASE_NOTE)),
    _t("soy_destination_year", "país de destino × ano", "Fluxos da soja por país de primeira importação.",
       (Col("destination", "str", "País de primeira importação (em inglês, como no Trase: CHINA, EUROPEAN UNION...)."),
        Col("economic_bloc", "str", "Bloco econômico do destino.")),
       (N_EXP, N_MUN), caveats=(BASE_NOTE,)),
    _t("soy_destination_state_year", "UF de origem × país de destino × ano", "Como soy_destination_year, aberto por UF de origem.",
       (Col("state", "str", "UF de origem por extenso."), Col("destination", "str", "País de primeira importação."),
        Col("economic_bloc", "str", "Bloco econômico do destino.")),
       (N_EXP, N_MUN), caveats=(BASE_NOTE, "Somar UFs dentro do MESMO ano é válido; somar anos não.")),
    _t("soy_biome_year", "bioma × ano", "Fluxos da soja por bioma de origem.",
       (Col("biome", "str", "Bioma."),), (N_EXP, N_DEST, N_MUN), caveats=(WINDOW_NOTE, BASE_NOTE)),
    Table("soy_national_year", "ano", "Série nacional e reconciliação: quanto do volume entra e quanto fica fora da base analítica.",
          (YEAR,
           Col("volume_total_tonnes", "float", "Volume total da fonte no ano (todas as linhas).", "t"),
           Col("volume_domestic_tonnes", "float", "Volume processado no Brasil (destino doméstico).", "t"),
           Col("volume_unknown_origin_tonnes", "float", "Volume de origem desconhecida (UNKNOWN STATE/BIOME).", "t"),
           Col("volume_analytic_tonnes", "float", "Volume da base analítica (as outras tabelas somam isto).", "t"),
           Col("pct_domestic", "float", "Fração doméstica do volume total.", "fração"),
           Col("pct_unknown_origin", "float", "Fração de origem desconhecida do volume total.", "fração"),
           Col("pct_analytic", "float", "Fração do volume na base analítica.", "fração"),
           Col("rows_total", "int", "Linhas da fonte no ano."),
           Col("rows_analytic", "int", "Linhas na base analítica."),
           Col("has_environmental_data", "bool", "False antes de 2013 (exposição e CO2 não existem)."),
           Col("fob_usd", "float", "FOB da base analítica.", "US$"),
           Col("exposure_ha", "float", "Exposição ao desmatamento da base analítica (nulo antes de 2013).", "ha"),
           Col("co2_net_tonnes", "float", "CO2 líquido da base analítica.", "tCO2e"),
           Col("co2_gross_tonnes", "float", "CO2 bruto da base analítica.", "tCO2e")),
          caveats=(WINDOW_NOTE,)),
    Table("inpe_deter_municipality_year", "município × ano × fonte × classe", "Alertas de desmatamento do INPE DETER (Amazônia e Cerrado) por município.",
          (Col("municipality_id", "str", "Código IBGE do município."), Col("year", "int", "Ano do alerta."),
           Col("source", "str", "DETER Amazônia ou DETER Cerrado."), Col("alert_class", "str", "Classe do alerta."),
           Col("area_ha", "float", "Área alertada.", "ha"), Col("n_alerts", "int", "Nº de alertas.")),
          municipality_key=True,
          caveats=("Só alertas ligados a municípios presentes no Trase (Cerrado casa por nome+UF: ~82% dos alertas). "
                   "DETER cobre 2021–2026 (2026 parcial); é alerta rápido, não desmatamento consolidado.",)),
    Table("inpe_prodes_pampa_municipality_year", "município × ano", "Desmatamento anual do INPE PRODES Pampa por município.",
          (Col("municipality_id", "str", "Código IBGE do município."), Col("year", "int", "Ano (2021–2024)."),
           Col("prodes_ha", "float", "Área desmatada.", "ha")),
          municipality_key=True, caveats=("PRODES é corte raso anual consolidado; não se soma com o DETER.",)),
    Table("soy_inpe_crosswalk", "município", "Cruzamento por município: Trase (2013–2022) x INPE DETER x PRODES Pampa.",
          (Col("municipality_id", "str", "Código IBGE do município."),
           Col("trase_municipality_id", "str", "Código no Trase."), Col("municipality", "str", "Município."),
           Col("state", "str", "UF por extenso."), Col("biome", "str", "Bioma dominante (maior volume)."),
           Col("volume_tonnes", "float", "Volume 2013–2022 (fluxos anuais: somar anos é válido para volume).", "t"),
           Col("land_use_ha", "float", "Área de soja, somada nos anos (usada só na razão abaixo).", "ha"),
           Col("exposed_pct_of_land", "float", "Exposição ÷ área de soja ×100: média ponderada pela área (NÃO é soma de exposição).", "%"),
           Col("co2_t_per_t", "float", "CO2 líquido por tonelada de soja.", "tCO2e/t"),
           Col("exposure_2022_ha", "float", "Exposição ao desmatamento só de 2022.", "ha"),
           Col("volume_eu_tonnes", "float", "Volume com destino à União Europeia.", "t"),
           Col("deter_ha_2021_22", "float", "Alertas DETER em 2021–2022.", "ha"),
           Col("deter_ha_2023_26", "float", "Alertas DETER em 2023–2026 (2026 parcial).", "ha"),
           Col("deter_ha_total", "float", "Alertas DETER 2021–2026.", "ha"),
           Col("deter_source", "str", "Fonte(s) DETER do município (nulo = sem alerta)."),
           Col("prodes_pampa_ha_2021", "float", "PRODES Pampa 2021.", "ha"),
           Col("prodes_pampa_ha_2022", "float", "PRODES Pampa 2022.", "ha"),
           Col("prodes_pampa_ha_2021_24", "float", "PRODES Pampa 2021–2024.", "ha"),
           Col("has_inpe_coverage", "bool", "Tem alerta DETER ou está no Pampa (cobertura PRODES).")),
          municipality_key=True,
          caveats=("Não existe coluna de exposição somada entre anos; use exposure_2022_ha ou exposed_pct_of_land.",
                   "Correlações com DETER são moderadas; trate como sinal complementar.")),
    Table("dim_entity", "entidade", "Nomes normalizados para confirmar grafias antes de filtrar (município, exportador, grupo, destino, UF, bioma).",
          (Col("entity_type", "str", "municipality | exporter | exporter_group | destination | state | biome."),
           Col("entity_id", "str", "IBGE (município) ou o próprio nome."), Col("name", "str", "Nome como aparece nas tabelas gold."),
           Col("name_normalized", "str", "Nome sem acento, maiúsculo (para comparar com o texto do usuário)."),
           Col("state", "str", "UF (só município).")),
          caveats=("Use name_normalized para achar a grafia exata antes de filtrar.",)),
]}

# tabelas de apoio (geradas pelo pipeline, fora do contrato de colunas)
SUPPORT_TABLES = ("gold_catalog", "meta_runs")


def catalog_frame() -> pd.DataFrame:
    rows = []
    for t in GOLD.values():
        for c in t.cols:
            rows.append({"table_name": t.name, "grain": t.grain, "table_description": t.desc, "column_name": c.name,
                         "kind": c.kind, "unit": c.unit, "column_description": c.desc, "caveats": " | ".join(t.caveats)})
    return pd.DataFrame(rows)


def check_contract(name: str, df: pd.DataFrame) -> tuple[bool, str]:
    """Colunas exatamente as do catálogo e tipos compatíveis."""
    spec = GOLD[name]
    missing = [c for c in spec.col_names if c not in df.columns]
    extra = [c for c in df.columns if c not in spec.col_names]
    bad = []
    for c in spec.cols:
        if c.name in df.columns:
            s = df[c.name]
            ok = {"int": pd.api.types.is_integer_dtype(s) or (pd.api.types.is_float_dtype(s) and s.dropna().mod(1).eq(0).all()),
                  "float": pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s),
                  "str": pd.api.types.is_string_dtype(s) or s.dtype == object,
                  "bool": pd.api.types.is_bool_dtype(s)}[c.kind]
            if not ok:
                bad.append(f"{c.name}:{s.dtype}!={c.kind}")
    return (not missing and not extra and not bad), f"faltam={missing} extras={extra} tipos={bad}"


def render_markdown() -> str:
    out = ["# Dicionário da camada gold da soja", "",
           "> Gerado de `src/medallion/catalog.py` (fonte única). Não edite à mão: mude o catálogo e rode `python -m src.cli build-medallion`.", ""]
    for t in GOLD.values():
        out += [f"## `{t.name}`", f"**Granularidade:** {t.grain}. {t.desc}", "", "| coluna | tipo | unidade | descrição |", "|---|---|---|---|"]
        out += [f"| `{c.name}` | {c.kind} | {c.unit} | {c.desc} |" for c in t.cols]
        if t.caveats:
            out += ["", "**Cuidados:**"] + [f"- {c}" for c in t.caveats]
        out.append("")
    return "\n".join(out)


def render_prompt(catalog: pd.DataFrame) -> str:
    """Prompt do agente a partir da tabela gold_catalog lida do próprio banco (não do Python)."""
    out = ["# Tabelas gold da soja (já limpas e conferidas; somente leitura via run_soy_sql)\n"]
    for name, g in catalog.groupby("table_name", sort=False):
        first = g.iloc[0]
        out.append(f"## {name}\n{first.table_description} Granularidade: {first.grain}.")
        for r in g.itertuples():
            unit = f" [{r.unit}]" if r.unit else ""
            out.append(f"- {r.column_name}: {r.kind}{unit}. {r.column_description}")
        if first.caveats:
            out.append(f"Cuidados: {first.caveats}")
        out.append("")
    return "\n".join(out)

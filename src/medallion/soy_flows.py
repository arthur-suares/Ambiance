"""Fluxos da cadeia da soja (Trase Brazil Soy v2.6.1, composite): bronze -> silver -> gold.

- bronze: cópia fiel do parquet original + origem (arquivo, SHA-256, versão, data da carga), particionada por ano.
- silver: limpo e etiquetado. NADA é apagado sem justificativa: cada problema vira uma coluna de marcação.
- gold:   tabelas do catálogo (src/medallion/catalog.py), todas por ano, só com a base analítica.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.medallion import catalog
from src.medallion.core import (Check, Lake, close, enforce, municipality_id_from_trase, normalize_name, reset_dir,
                                sha256_file, MUNICIPALITY_ID_RE)

SOURCE_NAME = "Trase Brazil Soy v2.6.1 (composite)"
RAW_COLUMNS = [
    "year", "biome", "country_of_production", "forest_500_soy", "zero_deforestation_brazil_soy", "state",
    "municipality_of_production", "logistics_hub", "port_of_export", "exporter", "exporter_group", "importer",
    "importer_group", "country_of_first_import", "economic_bloc", "state_trase_id",
    "municipality_of_production_trase_id", "country_of_production_trase_id", "country_of_first_import_trase_id",
    "soy_deforestation_5_year_total_exposure", "co2_net_emissions_soy_deforestation_5_year_total_exposure",
    "co2_gross_emissions_soy_deforestation_5_year_total_exposure", "volume", "fob", "land_use"]
EXPO, CO2N, CO2G = RAW_COLUMNS[19], RAW_COLUMNS[20], RAW_COLUMNS[21]
FIRST_YEAR_WITH_ENV_DATA = 2013      # antes disso exposição e emissões não existem na fonte (nulo estrutural)
META_COLS = ["_source_file", "_source_sha256", "_source_version", "_ingested_at"]


# ============================================================================ BRONZE

def bronze_checks(raw: pd.DataFrame, written_rows: int) -> list[Check]:
    missing = [c for c in RAW_COLUMNS if c not in raw.columns]
    extra = [c for c in raw.columns if c not in RAW_COLUMNS]
    return [
        Check("esquema: as 25 colunas esperadas existem", "blocks", not missing, f"faltam: {missing}"),
        Check("esquema: nenhuma coluna nova inesperada (schema drift)", "warn", not extra, f"novas: {extra}"),
        Check("contagem: linhas gravadas == linhas do arquivo original", "blocks", written_rows == len(raw), f"{written_rows} vs {len(raw)}"),
        Check("ano sem nulos", "blocks", int(raw["year"].isna().sum()) == 0, ""),
    ]


def build_bronze(lake: Lake, raw_path: Path, force: bool = False) -> dict:
    sha = sha256_file(raw_path)
    manifest_path = lake.bronze / "soy_flows" / "_manifest.json"
    if manifest_path.exists() and not force and json.loads(manifest_path.read_text()).get("sha256") == sha:
        print(f"[bronze/soja] mesma fonte (sha256 {sha[:12]}…): nada a fazer (--force refaz).")
        return json.loads(manifest_path.read_text())
    raw = pd.read_parquet(raw_path)
    meta = dict(zip(META_COLS, [raw_path.name, sha, SOURCE_NAME, datetime.now(timezone.utc).isoformat(timespec="seconds")]))
    out = reset_dir(lake.bronze / "soy_flows")
    raw.assign(**meta).to_parquet(out / "data", partition_cols=["year"], index=False)
    n = int(duckdb.sql(f"SELECT count(*) FROM read_parquet('{out}/data/*/*.parquet', hive_partitioning=true)").fetchall()[0][0])
    checks = bronze_checks(raw, n)
    manifest = {"sha256": sha, "rows": len(raw), "columns": len(RAW_COLUMNS), "source": SOURCE_NAME, **meta,
                "years": [int(raw.year.min()), int(raw.year.max())]}
    (out / "_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    enforce("bronze_soy", checks, lake.logs)
    print(f"[bronze/soja] {len(raw):,} linhas")
    return manifest


def read_bronze(lake: Lake) -> pd.DataFrame:
    return duckdb.sql(f"SELECT * FROM read_parquet('{lake.bronze}/soy_flows/data/*/*.parquet', hive_partitioning=true)").df()


# ============================================================================ SILVER

def to_silver(bronze: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Limpeza e marcações. Função pura (DataFrame entra, DataFrame sai) para poder ser testada."""
    df = bronze.copy()
    log = {"rows_bronze": len(df)}
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object:
            df[c] = df[c].str.strip()
    data_cols = [c for c in df.columns if not c.startswith("_")]
    log["exact_duplicates"] = int(df.duplicated(subset=data_cols).sum())
    df = df.drop_duplicates(subset=data_cols).reset_index(drop=True)
    df["municipality_id"] = df.municipality_of_production_trase_id.map(municipality_id_from_trase)
    df["unknown_origin"] = df.state.eq("UNKNOWN STATE") | df.biome.eq("UNKNOWN")
    df["domestic_destination"] = df.country_of_first_import.eq("BRAZIL")
    df["unknown_exporter"] = df.exporter_group.eq("UNKNOWN")
    df["fob_zero"] = df.fob.eq(0)
    df["environmental_data_available"] = df.year >= FIRST_YEAR_WITH_ENV_DATA
    df["forest_500_soy"] = pd.to_numeric(df.forest_500_soy, errors="coerce")
    df["forest500_not_assessed"] = df.forest_500_soy.isna()
    df["port_of_export"] = df.port_of_export.fillna("NOT REPORTED")
    df["is_analytic"] = (~df.unknown_origin) & (~df.domestic_destination) & df.environmental_data_available
    df["price_usd_per_t"] = np.where(df.volume > 0, df.fob / df.volume, np.nan)
    df["co2_t_per_t"] = df[CO2N] / df.volume
    df["exposure_ha_per_kt"] = df[EXPO] / df.volume * 1000
    for k in ["unknown_origin", "domestic_destination", "unknown_exporter", "fob_zero", "forest500_not_assessed", "is_analytic"]:
        log[k] = int(df[k].sum())
    log["rows_silver"] = len(df)
    return df, log


def silver_checks(bronze: pd.DataFrame, silver: pd.DataFrame, log: dict) -> list[Check]:
    pre, post = silver[silver.year < FIRST_YEAR_WITH_ENV_DATA], silver[silver.year >= FIRST_YEAR_WITH_ENV_DATA]
    data_cols = [c for c in bronze.columns if not c.startswith("_")]
    dedup = bronze.drop_duplicates(subset=data_cols)
    key = ["year", "volume", "fob", "country_of_first_import", "state", "biome", "exporter_group"]
    return [
        Check("linhas: silver == bronze - duplicatas exatas", "blocks", len(silver) == len(bronze) - log["exact_duplicates"], ""),
        Check("volume total da silver == da bronze", "blocks", close(silver.volume.sum(), dedup.volume.sum()), f"{silver.volume.sum():.2f}"),
        Check("FOB total da silver == da bronze", "blocks", close(silver.fob.sum(), dedup.fob.sum()), ""),
        Check("chaves sem nulos", "blocks", int(silver[key].isna().sum().sum()) == 0, str(silver[key].isna().sum().to_dict())),
        Check("municipality_id: nulo exatamente nas linhas de origem desconhecida; 7 dígitos nas demais", "blocks",
              bool((silver.municipality_id.isna() == silver.unknown_origin).all()
                   and silver.municipality_id.dropna().map(lambda v: bool(MUNICIPALITY_ID_RE.match(v))).all()),
              f"nulos={int(silver.municipality_id.isna().sum())} origem_desconhecida={int(silver.unknown_origin.sum())}"),
        Check("anos entre 2004 e 2022", "blocks", bool(silver.year.between(2004, 2022).all()), ""),
        Check("volume e FOB nunca negativos", "blocks", bool((silver.volume >= 0).all() and (silver.fob >= 0).all()), ""),
        Check("exposição e CO2 sem nulos de 2013 em diante", "blocks", int(post[[EXPO, CO2N, CO2G]].isna().sum().sum()) == 0, ""),
        Check("nulos de exposição antes de 2013 são todos estruturais (esperado)", "warn", bool(pre[EXPO].isna().all()), f"{int(pre[EXPO].isna().sum())} de {len(pre)}"),
        Check("duplicatas exatas na bronze", "warn", log["exact_duplicates"] == 0, str(log["exact_duplicates"])),
    ]


def build_silver(lake: Lake) -> tuple[pd.DataFrame, dict]:
    bronze = read_bronze(lake)
    silver, log = to_silver(bronze)
    enforce("silver_soy", silver_checks(bronze, silver, log), lake.logs)      # portão: só grava se passou
    out = reset_dir(lake.silver / "soy_flows")
    silver.drop(columns=META_COLS).assign(_bronze_sha256=bronze["_source_sha256"].iloc[0]).to_parquet(out / "soy_flows.parquet", index=False)
    (lake.logs / "silver_soy_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(f"[silver/soja] {len(silver):,} linhas; analíticas: {log['is_analytic']:,}")
    return silver, log


# ============================================================================ GOLD

def _agg(ana: pd.DataFrame, keys: list[str], counts: tuple[str, ...]) -> pd.DataFrame:
    named = dict(volume_tonnes=("volume", "sum"), fob_usd=("fob", "sum"), land_use_ha=("land_use", "sum"),
                 exposure_ha=(EXPO, "sum"), co2_net_tonnes=(CO2N, "sum"), co2_gross_tonnes=(CO2G, "sum"))
    src = {"n_exporters": "exporter_group", "n_destinations": "country_of_first_import", "n_municipalities": "municipality_id"}
    named.update({c: (src[c], "nunique") for c in counts})
    g = ana.groupby(keys, as_index=False, dropna=False).agg(**named)
    g["exposure_ha_per_kt"] = g.exposure_ha / g.volume_tonnes * 1000
    g["co2_t_per_t"] = g.co2_net_tonnes / g.volume_tonnes
    g["volume_share_in_year"] = g.volume_tonnes / g.groupby("year").volume_tonnes.transform("sum")
    return g


def _anomalies(mun: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    mun = mun.reset_index(drop=True)
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return mun.assign(is_anomaly=False, anomaly_score=np.nan), False
    feats = ["volume_tonnes", "land_use_ha", "exposure_ha", "co2_net_tonnes", "exposure_ha_per_kt", "co2_t_per_t", "n_exporters", "n_destinations"]
    X = np.log1p(mun[feats].clip(lower=0))
    mun["anomaly_score"] = 0.0
    for _, g in mun.groupby("year"):
        Xs = (X.loc[g.index] - X.loc[g.index].median()) / (X.loc[g.index].std() + 1e-9)
        m = IsolationForest(n_estimators=300, contamination=0.02, random_state=42).fit(Xs)
        mun.loc[g.index, "anomaly_score"] = -m.score_samples(Xs)
    mun["is_anomaly"] = mun.groupby("year").anomaly_score.transform(lambda s: s >= s.quantile(0.98))
    return mun, True


def _national(silver: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, g in silver.groupby("year"):
        a = g[g.is_analytic]
        vt = g.volume.sum()
        rows.append({"year": int(year), "volume_total_tonnes": vt,
                     "volume_domestic_tonnes": g.loc[g.domestic_destination, "volume"].sum(),
                     "volume_unknown_origin_tonnes": g.loc[g.unknown_origin, "volume"].sum(),
                     "volume_analytic_tonnes": a.volume.sum(), "rows_total": len(g), "rows_analytic": len(a),
                     "has_environmental_data": bool(year >= FIRST_YEAR_WITH_ENV_DATA),
                     "fob_usd": a.fob.sum() if len(a) else np.nan,
                     "exposure_ha": a[EXPO].sum() if len(a) else np.nan,
                     "co2_net_tonnes": a[CO2N].sum() if len(a) else np.nan, "co2_gross_tonnes": a[CO2G].sum() if len(a) else np.nan})
    n = pd.DataFrame(rows)
    for new, col in [("pct_domestic", "volume_domestic_tonnes"), ("pct_unknown_origin", "volume_unknown_origin_tonnes"), ("pct_analytic", "volume_analytic_tonnes")]:
        n[new] = n[col] / n.volume_total_tonnes
    return n


def _dim_entity(silver: pd.DataFrame) -> pd.DataFrame:
    parts = []
    mun = silver.groupby(["municipality_id", "municipality_of_production", "state"], as_index=False).volume.sum() \
        .sort_values("volume", ascending=False).drop_duplicates("municipality_id")
    parts.append(pd.DataFrame({"entity_type": "municipality", "entity_id": mun.municipality_id, "name": mun.municipality_of_production, "state": mun.state}))
    for etype, col in [("exporter", "exporter"), ("exporter_group", "exporter_group"), ("destination", "country_of_first_import"),
                       ("state", "state"), ("biome", "biome")]:
        v = silver[col].dropna().drop_duplicates().sort_values()
        parts.append(pd.DataFrame({"entity_type": etype, "entity_id": v.values, "name": v.values, "state": None}))
    d = pd.concat(parts, ignore_index=True)
    d["name_normalized"] = d.name.map(normalize_name)
    d["state"] = d.state.astype("object")
    return d[["entity_type", "entity_id", "name", "name_normalized", "state"]]


def to_gold(silver: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict]:
    ana = silver[silver.is_analytic]
    mun, anomaly_ok = _anomalies(_agg(ana.rename(columns={"municipality_of_production": "municipality", "municipality_of_production_trase_id": "trase_municipality_id"}),
                                      ["year", "municipality_id", "trase_municipality_id", "municipality", "state", "biome"], ("n_exporters", "n_destinations")))
    ana2 = ana.rename(columns={"country_of_first_import": "destination"}).assign(country_of_first_import=ana.country_of_first_import)
    out = {
        "soy_municipality_year": mun,
        "soy_exporter_group_year": _agg(ana, ["year", "exporter_group"], ("n_municipalities", "n_destinations")),
        "soy_exporter_company_year": _agg(ana, ["year", "exporter", "exporter_group"], ("n_municipalities", "n_destinations")),
        "soy_destination_year": _agg(ana2, ["year", "destination", "economic_bloc"], ("n_exporters", "n_municipalities")),
        "soy_destination_state_year": _agg(ana2, ["year", "state", "destination", "economic_bloc"], ("n_exporters", "n_municipalities")),
        "soy_biome_year": _agg(ana, ["year", "biome"], ("n_exporters", "n_destinations", "n_municipalities")),
        "soy_national_year": _national(silver),
        "dim_entity": _dim_entity(silver),
    }
    return out, {"anomaly_computed": anomaly_ok}


def gold_checks(silver: pd.DataFrame, gold: dict[str, pd.DataFrame], info: dict) -> list[Check]:
    a = silver[silver.is_analytic]
    vol, fob, exp = a.volume.sum(), a.fob.sum(), a[EXPO].sum()
    checks = []
    for name, df in gold.items():
        ok, detail = catalog.check_contract(name, df)
        checks.append(Check(f"{name}: contrato (colunas e tipos do catálogo)", "blocks", ok, detail))
    for name in ["soy_municipality_year", "soy_exporter_group_year", "soy_exporter_company_year", "soy_destination_year",
                 "soy_destination_state_year", "soy_biome_year"]:
        g = gold[name]
        checks += [
            Check(f"{name}: volume == volume analítico da silver", "blocks", close(g.volume_tonnes.sum(), vol), f"{g.volume_tonnes.sum():.2f}"),
            Check(f"{name}: FOB == FOB analítico da silver", "blocks", close(g.fob_usd.sum(), fob), ""),
            Check(f"{name}: exposição == exposição analítica da silver", "blocks", close(g.exposure_ha.sum(), exp), ""),
            Check(f"{name}: todas as linhas têm ano (nada agregado entre anos)", "blocks", int(g.year.isna().sum()) == 0, ""),
            Check(f"{name}: participações somam 100% em cada ano", "blocks", bool(np.allclose(g.groupby("year").volume_share_in_year.sum(), 1.0)), ""),
            Check(f"{name}: sem volume ou exposição negativos", "blocks", bool((g.volume_tonnes >= 0).all() and (g.exposure_ha >= 0).all()), ""),
        ]
    m = gold["soy_municipality_year"]
    checks += [
        Check("soy_municipality_year: chave (ano, município) única", "blocks", not m.duplicated(["year", "municipality_id"]).any(), ""),
        Check("soy_municipality_year: municipality_id com 7 dígitos", "blocks", bool(m.municipality_id.map(lambda v: bool(MUNICIPALITY_ID_RE.match(v))).all()), ""),
        Check("anomalias: ~2% por ano (entre 1% e 4%)", "warn", (not info["anomaly_computed"]) or 0.01 <= float(m.is_anomaly.mean()) <= 0.04, f"{m.is_anomaly.mean():.3%}"),
        Check("anomalias calculadas (scikit-learn instalado)", "warn", info["anomaly_computed"], "instale scikit-learn"),
    ]
    n = gold["soy_national_year"]
    checks += [
        Check("soy_national_year: volume total == volume da silver", "blocks", close(n.volume_total_tonnes.sum(), silver.volume.sum()), ""),
        Check("soy_national_year: volume analítico == volume analítico da silver", "blocks", close(n.volume_analytic_tonnes.sum(), vol), ""),
        Check("soy_national_year: linhas == linhas da silver", "blocks", int(n.rows_total.sum()) == len(silver), ""),
        Check("dim_entity: (tipo, id) único", "blocks", not gold["dim_entity"].duplicated(["entity_type", "entity_id"]).any(), ""),
    ]
    return checks


def build_gold(lake: Lake, silver: pd.DataFrame) -> dict[str, pd.DataFrame]:
    gold, info = to_gold(silver)
    enforce("gold_soy", gold_checks(silver, gold, info), lake.logs)
    reset_dir(lake.gold)
    for name, df in gold.items():
        df.to_parquet(lake.gold / f"{name}.parquet", index=False)
        print(f"[gold/soja] {name}: {len(df):,} linhas")
    return gold

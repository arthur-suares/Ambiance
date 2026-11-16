"""Camadas do INPE (DETER Amazônia, DETER Cerrado, PRODES Pampa) e o cruzamento com o Trase.

Entradas em config.INPE_RAW_DIR: y20*.csv (DETER Amazônia), c20*.csv (DETER Cerrado) e prodes_pampa_municipios.csv.
Chave única de município: municipality_id (IBGE, 7 dígitos). A Amazônia já traz o código; o Cerrado é ligado ao Trase
por nome normalizado + UF (alertas de municípios sem soja no Trase ficam marcados, sem apagar).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.medallion.core import (Check, Lake, close, enforce, normalize_name, reset_dir, sha256_file, MUNICIPALITY_ID_RE,
                                UF_BY_IBGE_PREFIX)
from src.medallion.soy_flows import EXPO, CO2N

AMZ_COLS = ["FID", "classname", "view_date", "areamunkm", "municipality", "mun_geocod", "uf"]
CER_COLS = ["FID", "classname", "view_date", "areamunkm", "municipality", "uf"]
PAMPA_COLS = ["ibge", "nome", "prodes_ha_2021", "prodes_ha_2022", "prodes_ha_2023", "prodes_ha_2024", "prodes_ha_total"]
CLASSES = {"DESMATAMENTO_CR", "DESMATAMENTO_VEG"}
PAMPA_NAME = "prodes_pampa_municipios.csv"


def _meta(path: Path, name: str) -> dict:
    return {"_source_name": name, "_source_file": path.name, "_source_sha256": sha256_file(path),
            "_collected_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "_ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def raw_files(raw_dir: Path) -> list[Path]:
    return sorted(raw_dir.glob("y20*.csv")) + sorted(raw_dir.glob("c20*.csv")) + [raw_dir / PAMPA_NAME]


def available(raw_dir: Path) -> bool:
    return (raw_dir / PAMPA_NAME).exists() and any(raw_dir.glob("y20*.csv")) and any(raw_dir.glob("c20*.csv"))


# ============================================================================ BRONZE

def build_bronze(lake: Lake, raw_dir: Path, force: bool = False) -> dict:
    shas = {f.name: sha256_file(f) for f in raw_files(raw_dir)}
    mp = lake.bronze / "inpe" / "_manifest.json"
    if mp.exists() and not force and json.loads(mp.read_text()).get("shas") == shas:
        print("[bronze/inpe] mesmas fontes: nada a fazer.")
        return json.loads(mp.read_text())
    base, checks, rows = reset_dir(lake.bronze / "inpe"), [], {}
    for key, pattern, cols, name in [("deter_amazonia", "y20*.csv", AMZ_COLS, "INPE TerraBrasilis - DETER Amazônia (alertas)"),
                                     ("deter_cerrado", "c20*.csv", CER_COLS, "INPE TerraBrasilis - DETER Cerrado (alertas)")]:
        parts, n_src = [], 0
        for f in sorted(raw_dir.glob(pattern)):
            d = pd.read_csv(f, dtype=str, keep_default_na=False)
            n_src += len(d)
            checks.append(Check(f"{f.name}: colunas esperadas", "blocks", list(d.columns) == cols, str(list(d.columns))))
            d = d.assign(**_meta(f, name), _file_year=int(f.stem[1:]))
            parts.append(d)
        pd.concat(parts, ignore_index=True).to_parquet(base / key, partition_cols=["_file_year"], index=False)
        n_out = int(duckdb.sql(f"SELECT count(*) FROM read_parquet('{base / key}/*/*.parquet', hive_partitioning=true)").fetchall()[0][0])
        checks.append(Check(f"{key}: linhas gravadas == linhas dos CSVs", "blocks", n_out == n_src, f"{n_out} vs {n_src}"))
        rows[key] = n_out
    pam = pd.read_csv(raw_dir / PAMPA_NAME, dtype=str, keep_default_na=False)
    checks.append(Check("prodes_pampa: colunas esperadas", "blocks", list(pam.columns) == PAMPA_COLS, str(list(pam.columns))))
    (base / "prodes_pampa").mkdir()
    pam.assign(**_meta(raw_dir / PAMPA_NAME, "INPE TerraBrasilis - PRODES Pampa (por município)")).to_parquet(base / "prodes_pampa" / "data.parquet", index=False)
    rows["prodes_pampa"] = len(pam)
    enforce("bronze_inpe", checks, lake.logs)
    (base / "_manifest.json").write_text(json.dumps({"shas": shas, "rows": rows}, indent=1), encoding="utf-8")
    print(f"[bronze/inpe] linhas: {rows}")
    return {"shas": shas, "rows": rows}


def _read(lake: Lake, key: str) -> pd.DataFrame:
    return duckdb.sql(f"SELECT * FROM read_parquet('{lake.bronze}/inpe/{key}/**/*.parquet', hive_partitioning=true)").df()


# ============================================================================ SILVER

def municipality_key(soy_silver: pd.DataFrame) -> pd.DataFrame:
    k = soy_silver[["municipality_id", "municipality_of_production"]].drop_duplicates("municipality_id").copy()
    k["uf"] = k.municipality_id.str[:2].map(UF_BY_IBGE_PREFIX)
    k["name_norm"] = k.municipality_of_production.map(normalize_name)
    return k[["municipality_id", "uf", "name_norm"]]


def to_silver_deter(amz: pd.DataFrame, cer: pd.DataFrame, key: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    a = amz.rename(columns={"mun_geocod": "municipality_id"})
    a["id_origin"] = np.where(a.municipality_id.str.len() == 7, "mun_geocod", None)
    a["source"] = "DETER Amazônia"
    c = cer.copy()
    c["name_norm"] = c.municipality.map(normalize_name)
    c = c.merge(key, on=["name_norm", "uf"], how="left")
    c["id_origin"] = np.where(c.municipality_id.notna(), "nome+uf (Trase)", None)
    c["source"] = "DETER Cerrado"
    cols = ["source", "FID", "classname", "view_date", "areamunkm", "municipality", "uf", "municipality_id", "id_origin"]
    s = pd.concat([a[cols], c[cols]], ignore_index=True)
    log = {"rows_bronze": len(s), "exact_duplicates": int(s.duplicated().sum())}
    s = s.drop_duplicates().reset_index(drop=True).rename(columns={"FID": "alert_id", "classname": "alert_class", "municipality": "municipality_name", "uf": "state_uf"})
    s["alert_date"] = pd.to_datetime(s.view_date)
    s["year"] = s.alert_date.dt.year
    s["area_km2"] = pd.to_numeric(s.areamunkm)
    s["area_ha"] = s.area_km2 * 100
    s["municipality_matched"] = s.municipality_id.notna()
    s = s.drop(columns=["view_date", "areamunkm"])
    log["rows_silver"] = len(s)
    return s, log


def to_silver_pampa(pam: pd.DataFrame) -> pd.DataFrame:
    w = pam[PAMPA_COLS].rename(columns={"ibge": "municipality_id", "nome": "municipality_name"}).copy()
    num = [c for c in w.columns if c.startswith("prodes_ha")]
    w[num] = w[num].apply(pd.to_numeric)
    long = w.melt(id_vars=["municipality_id", "municipality_name", "prodes_ha_total"], value_vars=[f"prodes_ha_{y}" for y in (2021, 2022, 2023, 2024)],
                  var_name="year", value_name="prodes_ha")
    long["year"] = long.year.str[-4:].astype(int)
    return long.sort_values(["municipality_id", "year"]).reset_index(drop=True)


def silver_checks(amz, cer, pam, key, s, log, sp) -> list[Check]:
    raw_km2 = pd.to_numeric(amz.areamunkm).sum() + pd.to_numeric(cer.areamunkm).sum()
    cs, az = s[s.source == "DETER Cerrado"], s[s.source == "DETER Amazônia"]
    return [
        Check("chave Trase: (nome normalizado, UF) única (senão o casamento duplicaria alertas)", "blocks", not key.duplicated(["name_norm", "uf"]).any(),
              f"{int(key.duplicated(['name_norm', 'uf']).sum())} repetidas"),
        Check("alertas: linhas silver == bronze - duplicatas exatas", "blocks", len(s) == log["rows_bronze"] - log["exact_duplicates"], ""),
        Check("alertas: área total (ha) == área da bronze x 100", "blocks", close(s.area_ha.sum(), raw_km2 * 100), f"{s.area_ha.sum():.1f} ha"),
        Check("alertas: datas válidas e ano 2021–2026", "blocks", bool(s.alert_date.notna().all() and s.year.between(2021, 2026).all()), ""),
        Check("alertas: ano da data == ano do arquivo", "blocks",
              bool(pd.concat([amz.view_date.str[:4].astype(int) == amz._file_year.astype(int), cer.view_date.str[:4].astype(int) == cer._file_year.astype(int)]).all()), ""),
        Check("alertas: áreas nunca negativas", "blocks", bool((s.area_ha >= 0).all()), ""),
        Check("alertas: áreas iguais a zero (lasca de polígono; mantidas, somam 0 ha)", "warn", True, f"{int((s.area_ha == 0).sum())} alertas"),
        Check("alertas Amazônia: IBGE com 7 dígitos e UF coerente", "blocks",
              bool(az.municipality_id.str.len().eq(7).all() and (az.municipality_id.str[:2].map(UF_BY_IBGE_PREFIX) == az.state_uf).all()), ""),
        Check("alertas: só as classes conhecidas", "warn", set(s.alert_class) <= CLASSES, str(set(s.alert_class) - CLASSES)),
        Check("alertas Cerrado: % ligada a município do Trase", "warn", True,
              f"{cs.municipality_matched.mean():.1%} dos alertas, {cs[cs.municipality_matched].area_ha.sum() / cs.area_ha.sum():.1%} da área"),
        Check("alertas: FID repetido NÃO é duplicata (o INPE reaproveita o ID)", "warn", True, f"{int(s.alert_id.duplicated().sum())} FIDs repetidos"),
        Check("pampa: soma dos 4 anos == total informado", "blocks", bool(np.allclose(sp.groupby("municipality_id").prodes_ha.sum().values, sp.groupby("municipality_id").prodes_ha_total.first().values)), ""),
        Check("pampa: município único e IBGE com 7 dígitos", "blocks", bool(sp.municipality_id.map(lambda v: bool(MUNICIPALITY_ID_RE.match(v))).all() and sp.municipality_id.nunique() == len(pam)), ""),
        Check("pampa: áreas não negativas", "blocks", bool((sp.prodes_ha >= 0).all()), ""),
    ]


def build_silver(lake: Lake, soy_silver: pd.DataFrame) -> dict:
    amz, cer, pam = _read(lake, "deter_amazonia"), _read(lake, "deter_cerrado"), _read(lake, "prodes_pampa")
    key = municipality_key(soy_silver)
    s, log = to_silver_deter(amz, cer, key)
    sp = to_silver_pampa(pam)
    enforce("silver_inpe", silver_checks(amz, cer, pam, key, s, log, sp), lake.logs)
    out = reset_dir(lake.silver / "inpe")
    s.to_parquet(out / "deter_alerts.parquet", index=False)
    sp.to_parquet(out / "prodes_pampa.parquet", index=False)
    (lake.logs / "silver_inpe_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(f"[silver/inpe] alertas: {len(s):,} ({int(s.municipality_matched.sum()):,} com município); pampa: {len(sp):,}")
    return {"alerts": s, "pampa": sp}


# ============================================================================ GOLD

def to_gold(soy_silver: pd.DataFrame, alerts: pd.DataFrame, pampa: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ok = alerts[alerts.municipality_matched]
    det = ok.groupby(["municipality_id", "year", "source", "alert_class"], as_index=False).agg(area_ha=("area_ha", "sum"), n_alerts=("area_ha", "size"))
    pam = pampa[["municipality_id", "year", "prodes_ha"]].copy()
    e = soy_silver[soy_silver.is_analytic]
    t = e.groupby(["municipality_id", "municipality_of_production_trase_id", "municipality_of_production", "state", "biome"]).agg(
        volume_tonnes=("volume", "sum"), land_use_ha=("land_use", "sum"), _expo=(EXPO, "sum"), _co2=(CO2N, "sum")).reset_index()
    t = t.sort_values("volume_tonnes", ascending=False).drop_duplicates("municipality_id")
    t["exposed_pct_of_land"] = t._expo / t.land_use_ha * 100     # razão de somas = média ponderada pela área; NÃO é soma de exposição
    t["co2_t_per_t"] = t._co2 / t.volume_tonnes
    t = t.rename(columns={"municipality_of_production_trase_id": "trase_municipality_id", "municipality_of_production": "municipality"})
    e22 = e[e.year == 2022].groupby("municipality_id")[EXPO].sum().rename("exposure_2022_ha")
    eu = e[e.economic_bloc == "EUROPEAN UNION"].groupby("municipality_id").volume.sum().rename("volume_eu_tonnes")
    w = ok.groupby("municipality_id").apply(lambda x: pd.Series({
        "deter_ha_2021_22": x[x.year <= 2022].area_ha.sum(), "deter_ha_2023_26": x[x.year >= 2023].area_ha.sum(),
        "deter_ha_total": x.area_ha.sum(), "deter_source": "+".join(sorted(x.source.unique()))}), include_groups=False).reset_index()
    pw = pampa.pivot(index="municipality_id", columns="year", values="prodes_ha")
    pw = pd.DataFrame({"prodes_pampa_ha_2021": pw[2021], "prodes_pampa_ha_2022": pw[2022], "prodes_pampa_ha_2021_24": pw.sum(axis=1)}).reset_index()
    m = t.merge(w, on="municipality_id", how="left").merge(e22, on="municipality_id", how="left") \
        .merge(eu, on="municipality_id", how="left").merge(pw, on="municipality_id", how="left").drop(columns=["_expo", "_co2"])
    zero = ["deter_ha_2021_22", "deter_ha_2023_26", "deter_ha_total", "volume_eu_tonnes", "exposure_2022_ha"]
    m[zero] = m[zero].fillna(0)
    m["has_inpe_coverage"] = m.deter_source.notna() | m.biome.eq("PAMPA")
    return {"inpe_deter_municipality_year": det, "inpe_prodes_pampa_municipality_year": pam, "soy_inpe_crosswalk": m}


def gold_checks(soy_silver, alerts, pampa, g) -> list[Check]:
    from src.medallion import catalog
    ok = alerts[alerts.municipality_matched]
    det, pam, m = g["inpe_deter_municipality_year"], g["inpe_prodes_pampa_municipality_year"], g["soy_inpe_crosswalk"]
    checks = [Check(f"{n}: contrato (colunas e tipos do catálogo)", "blocks", *catalog.check_contract(n, df)) for n, df in g.items()]
    return checks + [
        Check("deter: área == área dos alertas com município (silver)", "blocks", close(det.area_ha.sum(), ok.area_ha.sum()), ""),
        Check("deter: nº de alertas == alertas com município (silver)", "blocks", int(det.n_alerts.sum()) == len(ok), ""),
        Check("deter: chave (município, ano, fonte, classe) única", "blocks", not det.duplicated(["municipality_id", "year", "source", "alert_class"]).any(), ""),
        Check("deter e pampa: municipality_id com 7 dígitos", "blocks", bool(det.municipality_id.str.len().eq(7).all() and pam.municipality_id.str.len().eq(7).all()), ""),
        Check("pampa: área == área da silver", "blocks", close(pam.prodes_ha.sum(), pampa.prodes_ha.sum()), ""),
        Check("cruzamento: um município por linha", "blocks", m.municipality_id.is_unique, ""),
        Check("cruzamento: volume == volume analítico da silver da soja", "blocks", close(m.volume_tonnes.sum(), soy_silver.loc[soy_silver.is_analytic, "volume"].sum()), ""),
        Check("cruzamento: DETER por município == DETER da gold (municípios do Trase)", "blocks", close(m.deter_ha_total.sum(), det[det.municipality_id.isin(m.municipality_id)].area_ha.sum()), ""),
        Check("cruzamento: deter_ha_total == soma dos dois períodos", "blocks", bool(np.allclose(m.deter_ha_total, m.deter_ha_2021_22 + m.deter_ha_2023_26)), ""),
    ]


def build_gold(lake: Lake, soy_silver: pd.DataFrame, silver_inpe: dict) -> dict[str, pd.DataFrame]:
    g = to_gold(soy_silver, silver_inpe["alerts"], silver_inpe["pampa"])
    enforce("gold_inpe", gold_checks(soy_silver, silver_inpe["alerts"], silver_inpe["pampa"], g), lake.logs)
    for name, df in g.items():
        df.to_parquet(lake.gold / f"{name}.parquet", index=False)
        print(f"[gold/inpe] {name}: {len(df):,} linhas")
    return g

"""Ingestão das bases Onda 2B + Onda 3 no PostgreSQL + PostGIS:
  - agro.dim_instalacoes (Frigoríficos/Pecuária + Silos/Instalações de Soja)
  - agro.fato_comex_exportacoes (MDIC Comex Stat 2022-2025 — Soja e Bovinos)
  - agro.fato_seeg_emissoes (SEEG Coleção 14 — CO2e GWP-AR5 por município, 2000+)

Uso:
    .venv/bin/python scripts/ingest_onda2_3.py
"""

from __future__ import annotations

from collections import defaultdict
import csv
from pathlib import Path
import sys
import time
import unicodedata

import openpyxl
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER  # noqa: E402

ONDA2_DIR = ROOT / "data" / "raw" / "onda2"
ONDA3_DIR = ROOT / "data" / "raw" / "onda3"
SCHEMA_SQL = ROOT / "sql" / "agro_schema.sql"
GOLD_SQL = ROOT / "sql" / "gold_views.sql"

COMEX_SH4 = {
    "1201": "soja",
    "2304": "soja",
    "1507": "soja",
    "0201": "bovinos",
    "0202": "bovinos",
    "1602": "bovinos",
    "0102": "bovinos",
}


def norm(text: str | None) -> str:
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(text).upper())
        if not unicodedata.combining(c)
    ).strip()


def clean(val: object) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def fnum(val: object) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s.upper() in ("NA", "NAN", "NULL", "NONE", "-"):
        return None
    try:
        return float(s.replace(",", ".")) if ("," in s and "." not in s) else float(s)
    except ValueError:
        return None


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DATABASE, autocommit=False
    )


def load_instalacoes(con: psycopg.Connection) -> int:
    beef_csv = ONDA3_DIR / "trase" / "2026-05-07-br_beef_logistics_map_v6.csv"
    soy_csv = ONDA3_DIR / "trase" / "Brazil_soy_facilities_map_v2_2_2026.csv"
    t0 = time.perf_counter()

    with con.cursor() as cur:
        cur.execute("SELECT codigo_municipio_ibge, uf, uf_nome, municipio_norm FROM agro.dim_municipios")
        valid_muns = set()
        uf_by_name = {}
        mun_lookup = {}
        for cod, uf, uf_nome, mnorm in cur.fetchall():
            valid_muns.add(cod)
            uf_by_name[norm(uf_nome)] = uf
            uf_by_name[uf] = uf
            mun_lookup[(uf, mnorm)] = cod

        cur.execute("TRUNCATE TABLE agro.dim_instalacoes RESTART IDENTITY")
        total = 0
        with cur.copy(
            """COPY agro.dim_instalacoes (
                cadeia, facility_id, cnpj, empresa, tipo, tipo_detalhado,
                nivel_inspecao, numero_inspecao, status, capacidade_valor, capacidade_unidade,
                codigo_municipio_ibge, municipio, uf, lat, lon, fonte
            ) FROM STDIN"""
        ) as cp:
            # 1. Frigoríficos / Pecuária
            if beef_csv.exists():
                print(f"[INST] Carregando {beef_csv.name} ...", flush=True)
                with beef_csv.open("r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        uf = uf_by_name.get(norm(row.get("state")))
                        mun = clean(row.get("municipality"))
                        cod = mun_lookup.get((uf, norm(mun))) if uf and mun else None
                        lat = fnum(row.get("lat"))
                        lon = fnum(row.get("long"))
                        if lat is not None and not (-35 <= lat <= 6):
                            lat = lon = None
                        cp.write_row((
                            "bovinos", clean(row.get("facility_id")), clean(row.get("cnpj")),
                            clean(row.get("company")), clean(row.get("type_portuguese")) or clean(row.get("type_english")),
                            clean(row.get("type_detailed_portuguese")),
                            clean(row.get("inspection_level")), clean(row.get("inspection_num")),
                            clean(row.get("status")), fnum(row.get("capacity_value_num")),
                            clean(row.get("capacity_units_portuguese")),
                            cod, mun, uf, lat, lon, "Trase Beef Logistics v6",
                        ))
                        total += 1

            # 2. Silos / Instalações de Soja
            if soy_csv.exists():
                print(f"[INST] Carregando {soy_csv.name} ...", flush=True)
                with soy_csv.open("r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        cod_raw = clean(row.get("municipality_ibge_code"))
                        cod = cod_raw if cod_raw in valid_muns else None
                        uf = uf_by_name.get(norm(row.get("state_name")))
                        mun = clean(row.get("municipality"))
                        if not cod and uf and mun:
                            cod = mun_lookup.get((uf, norm(mun)))
                        lat = fnum(row.get("latitude"))
                        lon = fnum(row.get("longitude"))
                        if lat is not None and not (-35 <= lat <= 6):
                            lat = lon = None
                        cap_s = fnum(row.get("storage_capacity_tn"))
                        cap_p = fnum(row.get("processing_capacity_tonnes_day"))
                        cap_val = cap_s if (cap_s and cap_s > 0) else (cap_p if (cap_p and cap_p > 0) else None)
                        cap_unit = "t (armazenagem)" if (cap_s and cap_s > 0) else ("t/dia (processamento)" if (cap_p and cap_p > 0) else None)
                        cp.write_row((
                            "soja", clean(row.get("facility_id")), clean(row.get("cnpj")),
                            clean(row.get("company_name")), clean(row.get("category")),
                            clean(row.get("facility_type")),
                            clean(row.get("source")) or "SICARM", clean(row.get("cda")),
                            "Ativo", cap_val, cap_unit,
                            cod, mun, uf, lat, lon, "Trase Soy Facilities v2.2",
                        ))
                        total += 1

        # Popula geometria Point e resolve municípios faltantes via PostGIS
        cur.execute(
            """
            UPDATE agro.dim_instalacoes
            SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326)
            WHERE lat IS NOT NULL AND lon IS NOT NULL
            """
        )
        cur.execute(
            """
            UPDATE agro.dim_instalacoes i
            SET codigo_municipio_ibge = m.codigo_municipio_ibge,
                uf = COALESCE(i.uf, m.uf),
                municipio = COALESCE(i.municipio, m.municipio)
            FROM agro.dim_municipios m
            WHERE i.codigo_municipio_ibge IS NULL AND i.geom IS NOT NULL AND m.geom IS NOT NULL
              AND ST_Intersects(m.geom, i.geom)
            """
        )
    con.commit()
    print(f"[OK  ] dim_instalacoes: {total:,} instalações em {time.perf_counter() - t0:.1f}s")
    return total


def load_comex(con: psycopg.Connection) -> int:
    comex_dir = ONDA3_DIR / "comex"
    exp_files = sorted(comex_dir.glob("EXP_*_MUN.csv"))
    if not exp_files:
        print("[SKIP] Comex Stat não encontrado.")
        return 0
    t0 = time.perf_counter()

    # Dicionários auxiliares
    paises = {}
    if (comex_dir / "PAIS.csv").exists():
        with (comex_dir / "PAIS.csv").open("r", encoding="latin-1", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                paises[r["CO_PAIS"].strip()] = r["NO_PAIS"].strip()

    sh4_names = {}
    if (comex_dir / "NCM_SH.csv").exists():
        with (comex_dir / "NCM_SH.csv").open("r", encoding="latin-1", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                code = r.get("CO_SH4", "").strip()
                if code in COMEX_SH4 and code not in sh4_names:
                    sh4_names[code] = r.get("NO_SH4_POR", "").strip()

    total = 0
    with con.cursor() as cur:
        cur.execute("SELECT codigo_municipio_ibge FROM agro.dim_municipios")
        valid_muns = {r[0] for r in cur.fetchall()}

        cur.execute("TRUNCATE TABLE agro.fato_comex_exportacoes RESTART IDENTITY")
        with cur.copy(
            """COPY agro.fato_comex_exportacoes (
                ano, mes, produto, sh4, sh4_desc, codigo_municipio_ibge, uf,
                co_pais, pais, kg_liquido, valor_fob_usd
            ) FROM STDIN"""
        ) as cp:
            for path in exp_files:
                print(f"[COMX] Lendo {path.name} ...", flush=True)
                with path.open("r", encoding="latin-1", newline="") as f:
                    for row in csv.DictReader(f, delimiter=";"):
                        sh4 = (row.get("SH4") or "").strip().zfill(4)
                        produto = COMEX_SH4.get(sh4)
                        if not produto:
                            continue
                        cod_raw = (row.get("CO_MUN") or "").strip()
                        cod = cod_raw if cod_raw in valid_muns else None
                        co_pais = (row.get("CO_PAIS") or "").strip()
                        cp.write_row((
                            int(row["CO_ANO"]), int(row["CO_MES"]), produto, sh4,
                            sh4_names.get(sh4, sh4), cod,
                            clean(row.get("SG_UF_MUN")),
                            co_pais, paises.get(co_pais, co_pais),
                            fnum(row.get("KG_LIQUIDO")), fnum(row.get("VL_FOB")),
                        ))
                        total += 1
    con.commit()
    print(f"[OK  ] fato_comex_exportacoes: {total:,} registros (soja+bovinos) em {time.perf_counter() - t0:.1f}s")
    return total


def load_seeg(con: psycopg.Connection) -> int:
    xlsx_path = ONDA2_DIR / "seeg_municipios_col14.xlsx"
    if not xlsx_path.exists():
        print("[SKIP] SEEG xlsx não encontrado.")
        return 0
    t0 = time.perf_counter()
    print(f"[SEEG] Lendo {xlsx_path.name} (aba Dados, anos >= 2000) ...", flush=True)

    with con.cursor() as cur:
        cur.execute("SELECT codigo_municipio_ibge, uf FROM agro.dim_municipios")
        mun_uf = {r[0]: r[1] for r in cur.fetchall()}

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Dados"]
    rows_iter = ws.iter_rows(values_only=True)
    header = list(next(rows_iter))
    year_cols = [(i, int(h)) for i, h in enumerate(header) if isinstance(h, (int, float)) and int(h) >= 2000]
    print(f"       Colunas de ano detectadas: {year_cols[0][1]}–{year_cols[-1][1]} ({len(year_cols)} anos)", flush=True)

    agg: dict[tuple, float] = defaultdict(float)
    raw_count = 0
    for row in rows_iter:
        raw_count += 1
        if raw_count % 50_000 == 0:
            print(f"       SEEG lidas: {raw_count:,} linhas wide ...", flush=True)
        id_terr = row[8]
        if id_terr is None:
            continue
        id_str = str(int(id_terr)) if isinstance(id_terr, (int, float)) else str(id_terr).strip()
        cod = id_str[-7:] if len(id_str) >= 7 else None
        if cod not in mun_uf:
            continue
        uf = mun_uf[cod]
        tipo_fluxo = clean(row[0]) or "Emissão"
        setor = clean(row[1]) or "Outros"
        categoria = clean(row[2])
        atividade = clean(row[5])
        for idx, ano in year_cols:
            val = row[idx]
            if val is not None and val != 0:
                fv = float(val)
                if fv != 0.0:
                    agg[(ano, cod, uf, tipo_fluxo, setor, categoria, atividade)] += fv
    wb.close()

    print(f"       Unpivot concluído: {len(agg):,} linhas agregadas de {raw_count:,} linhas wide. Gravando via COPY ...", flush=True)
    with con.cursor() as cur:
        cur.execute("TRUNCATE TABLE agro.fato_seeg_emissoes RESTART IDENTITY")
        with cur.copy(
            """COPY agro.fato_seeg_emissoes (
                ano, codigo_municipio_ibge, uf, tipo_fluxo, setor, subsetor,
                atividade, gas, emissao_tco2e, versao_seeg
            ) FROM STDIN"""
        ) as cp:
            for (ano, cod, uf, tipo_fluxo, setor, categoria, atividade), val in agg.items():
                cp.write_row((
                    ano, cod, uf, tipo_fluxo, setor, categoria, atividade,
                    "CO2e (t) GWP-AR5", round(val, 4), "SEEG Coleção 14",
                ))
    con.commit()
    print(f"[OK  ] fato_seeg_emissoes: {len(agg):,} linhas em {time.perf_counter() - t0:.1f}s")
    return len(agg)


def update_catalog_and_gold(con: psycopg.Connection) -> None:
    entries = [
        ("seeg_emissoes", "SEEG Brasil — Emissões Municipais", "Observatório do Clima", "emissoes",
         "https://seeg.eco.br/dados/", "Coleção 14 (GWP-AR5)", "municipio_ano",
         "Estimativas municipais em tCO2e (GWP-AR5) por setor (Agropecuária, MUT, Energia, Resíduos, Processos Industriais).",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_seeg_emissoes"),
        ("comex_exportacoes", "Comex Stat — Exportações Municipais (Soja e Bovinos)", "MDIC", "comercio",
         "https://comexstat.mdic.gov.br/", "SH4 Agro 2022–2025", "municipio_mes",
         "Exportações oficiais por município de domicílio fiscal do exportador (pode diferir do município produtor rural).",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_comex_exportacoes"),
        ("trase_instalacoes", "Trase — Frigoríficos e Silos/Instalações de Soja", "Trase / SICARM / MAPA", "infraestrutura",
         "https://trase.earth/open-data", "Beef v6 + Soy v2.2 (2026)", "estabelecimento",
         "Instalações georreferenciadas (frigoríficos SIF/SIE/SIM e silos/esmagadoras de soja) com capacidade declarada ou estimada.",
         "SELECT COUNT(*), NULL, NULL FROM agro.dim_instalacoes"),
    ]
    with con.cursor() as cur:
        for fid, nome, orgao, cat, url, ver, grao, lim, q in entries:
            cur.execute(q)
            cnt, y0, y1 = cur.fetchone()
            cur.execute(
                """
                INSERT INTO agro.dim_fontes
                    (fonte_id, nome, orgao, categoria, url, versao, ano_inicio, ano_fim, grao, limitacoes, registros, atualizado_em)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (fonte_id) DO UPDATE SET
                    versao = EXCLUDED.versao, ano_inicio = EXCLUDED.ano_inicio,
                    ano_fim = EXCLUDED.ano_fim, registros = EXCLUDED.registros,
                    limitacoes = EXCLUDED.limitacoes, atualizado_em = now()
                """,
                (fid, nome, orgao, cat, url, ver, y0, y1, grao, lim, cnt or 0),
            )
        print("[SQL ] Reconstruindo Materialized Views da camada Gold ...", flush=True)
        cur.execute(GOLD_SQL.read_text(encoding="utf-8"))
        cur.execute("ANALYZE;")
    con.commit()
    print("[OK  ] dim_fontes e gold.* atualizados.")


def main() -> int:
    t0 = time.perf_counter()
    with connect() as con:
        with con.cursor() as cur:
            cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        con.commit()
        load_instalacoes(con)
        load_comex(con)
        load_seeg(con)
        update_catalog_and_gold(con)
    print(f"\nIngestão Onda 2B + 3 concluída em {time.perf_counter() - t0:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

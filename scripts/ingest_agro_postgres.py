"""Ingestão consolidada das bases agroambientais no PostgreSQL + PostGIS.

Usa COPY FROM STDIN (psycopg v3) para carregar ~10 milhões de linhas com alta
performance e idempotência por módulo.

Uso:
    .venv/bin/python scripts/ingest_agro_postgres.py
    .venv/bin/python scripts/ingest_agro_postgres.py --only dim,sif,deter,gold
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
import sys
import time
import unicodedata

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER  # noqa: E402

PROCESSED_DIR = ROOT.parent / "dados_processados"
ONDA2_DIR = ROOT / "data" / "raw" / "onda2"
SCHEMA_SQL = ROOT / "sql" / "agro_schema.sql"
GOLD_SQL = ROOT / "sql" / "gold_views.sql"


def norm(text: str | None) -> str:
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(text).upper())
        if not unicodedata.combining(c)
    ).strip()


def valid_ibge(code: str | None) -> str | None:
    if not code:
        return None
    s = str(code).strip()
    if len(s) == 7 and s.isascii() and s.isdigit():
        return s
    return None


def num(val: str | None) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() in ("NA", "NAN", "NULL", "NONE", "-", "..", "...", "X"):
        return None
    try:
        return float(s.replace(",", ".")) if ("," in s and "." not in s) else float(s)
    except ValueError:
        return None


def integer(val: str | None) -> int | None:
    v = num(val)
    return int(round(v)) if v is not None else None


def clean_str(val: str | None) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE,
        autocommit=False,
    )


def apply_sql(con: psycopg.Connection, path: Path) -> None:
    print(f"[SQL ] Aplicando {path.name} ...", flush=True)
    with con.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))
    con.commit()


def load_dim_municipios(con: psycopg.Connection) -> int:
    mun_path = ONDA2_DIR / "ibge_municipios.json"
    geo_path = ONDA2_DIR / "ibge_malha_municipios_br.geojson"
    if not mun_path.exists():
        raise FileNotFoundError(f"Arquivo ausente: {mun_path}. Rode scripts/download_onda2.py primeiro.")

    t0 = time.perf_counter()
    mun_list = json.loads(mun_path.read_text(encoding="utf-8"))
    geoms: dict[str, str] = {}
    if geo_path.exists():
        gj = json.loads(geo_path.read_text(encoding="utf-8"))
        for feat in gj.get("features", []):
            cod = str(feat.get("properties", {}).get("codarea", "")).strip()
            if cod and feat.get("geometry"):
                geoms[cod] = json.dumps(feat["geometry"])

    print(f"[DIM ] Carregando {len(mun_list)} municípios ({len(geoms)} geometrias PostGIS) ...", flush=True)
    rows = []
    for m in mun_list:
        cod = str(m["id"]).zfill(7)
        nome = m["nome"]
        micro = m.get("microrregiao")
        if micro and micro.get("mesorregiao"):
            uf_obj = micro["mesorregiao"]["UF"]
        else:
            uf_obj = m["regiao-imediata"]["regiao-intermediaria"]["UF"]
        uf = uf_obj["sigla"]
        uf_nome = uf_obj["nome"]
        regiao = uf_obj["regiao"]["nome"]
        rows.append((cod, nome, norm(nome), uf, uf_nome, regiao, geoms.get(cod)))

    # Áreas especiais de corpos d'água usadas pelo IBGE/MapBiomas no RS
    for cod, nome in (("4300001", "Lagoa Mirim"), ("4300002", "Lagoa dos Patos")):
        if not any(r[0] == cod for r in rows):
            rows.append((cod, nome, norm(nome), "RS", "Rio Grande do Sul", "Sul", geoms.get(cod)))

    with con.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO agro.dim_municipios (
                codigo_municipio_ibge, municipio, municipio_norm, uf, uf_nome, regiao, geom
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                CASE WHEN %s::text IS NOT NULL THEN ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)), 3)) END
            )
            ON CONFLICT (codigo_municipio_ibge) DO UPDATE SET
                municipio = EXCLUDED.municipio,
                municipio_norm = EXCLUDED.municipio_norm,
                uf = EXCLUDED.uf,
                uf_nome = EXCLUDED.uf_nome,
                regiao = EXCLUDED.regiao,
                geom = COALESCE(EXCLUDED.geom, agro.dim_municipios.geom)
            """,
            [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[6]) for r in rows],
        )
        cur.execute(
            """
            UPDATE agro.dim_municipios
            SET lat = ST_Y(ST_PointOnSurface(geom)),
                lon = ST_X(ST_PointOnSurface(geom)),
                area_km2 = ROUND((ST_Area(geom::geography) / 1000000.0)::numeric, 2)::double precision
            WHERE geom IS NOT NULL
            """
        )
    con.commit()
    print(f"[OK  ] dim_municipios: {len(rows)} linhas em {time.perf_counter() - t0:.1f}s")
    return len(rows)


def load_ibge_pam(con: psycopg.Connection) -> int:
    path = PROCESSED_DIR / "ibge_pam_soja_municipios.csv.gz"
    t0 = time.perf_counter()
    print(f"[IBGE] Carregando {path.name} ...", flush=True)
    count = 0
    with con.cursor() as cur:
        cur.execute("TRUNCATE TABLE agro.fato_ibge_pam_soja")
        with cur.copy(
            """COPY agro.fato_ibge_pam_soja (
                ano, codigo_municipio_ibge, area_plantada_ha, status_area_plantada,
                area_colhida_ha, status_area_colhida, quantidade_produzida_t,
                status_quantidade_produzida, rendimento_medio_kg_ha, status_rendimento_medio,
                valor_producao_mil_reais_nominal, status_valor_producao, fonte, tabela_sidra
            ) FROM STDIN"""
        ) as cp:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    cod = valid_ibge(row.get("codigo_municipio_ibge"))
                    if not cod:
                        continue
                    cp.write_row((
                        integer(row["ano"]), cod,
                        num(row.get("area_plantada_ha")), clean_str(row.get("status_area_plantada")),
                        num(row.get("area_colhida_ha")), clean_str(row.get("status_area_colhida")),
                        num(row.get("quantidade_produzida_t")), clean_str(row.get("status_quantidade_produzida")),
                        num(row.get("rendimento_medio_kg_ha")), clean_str(row.get("status_rendimento_medio")),
                        num(row.get("valor_producao_mil_reais_nominal")), clean_str(row.get("status_valor_producao")),
                        clean_str(row.get("fonte")) or "IBGE PAM", clean_str(row.get("tabela_sidra")),
                    ))
                    count += 1
    con.commit()
    print(f"[OK  ] fato_ibge_pam_soja: {count:,} linhas em {time.perf_counter() - t0:.1f}s")
    return count


def load_ibge_ppm(con: psycopg.Connection) -> int:
    path = PROCESSED_DIR / "ibge_ppm_bovinos_municipios.csv.gz"
    t0 = time.perf_counter()
    print(f"[IBGE] Carregando {path.name} ...", flush=True)
    count = 0
    with con.cursor() as cur:
        cur.execute("TRUNCATE TABLE agro.fato_ibge_ppm_bovinos")
        with cur.copy(
            """COPY agro.fato_ibge_ppm_bovinos (
                ano, codigo_municipio_ibge, rebanho_bovino_cabecas,
                status_rebanho_bovino, unidade, fonte, tabela_sidra
            ) FROM STDIN"""
        ) as cp:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    cod = valid_ibge(row.get("codigo_municipio_ibge"))
                    if not cod:
                        continue
                    cp.write_row((
                        integer(row["ano"]), cod,
                        integer(row.get("rebanho_bovino_cabecas")),
                        clean_str(row.get("status_rebanho_bovino")),
                        clean_str(row.get("unidade")) or "cabecas",
                        clean_str(row.get("fonte")) or "IBGE PPM",
                        clean_str(row.get("tabela_sidra")),
                    ))
                    count += 1
    con.commit()
    print(f"[OK  ] fato_ibge_ppm_bovinos: {count:,} linhas em {time.perf_counter() - t0:.1f}s")
    return count


def load_mapbiomas(con: psycopg.Connection) -> tuple[int, int]:
    cob_path = PROCESSED_DIR / "mapbiomas_cobertura_municipios.csv.gz"
    desm_path = PROCESSED_DIR / "mapbiomas_desmatamento_municipios.csv.gz"

    t0 = time.perf_counter()
    print(f"[MB  ] Carregando {cob_path.name} ...", flush=True)
    c_cob = 0
    with con.cursor() as cur:
        cur.execute("SELECT codigo_municipio_ibge FROM agro.dim_municipios")
        valid_muns = {r[0] for r in cur.fetchall()}

        cur.execute("TRUNCATE TABLE agro.fato_mapbiomas_cobertura")
        with cur.copy(
            """COPY agro.fato_mapbiomas_cobertura (
                ano, codigo_municipio_ibge, bioma, classe_id,
                classe_nivel_0, classe_nivel_1, classe_nivel_2, classe_nivel_3, classe_nivel_4,
                area_ha
            ) FROM STDIN"""
        ) as cp:
            with gzip.open(cob_path, "rt", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    cod = valid_ibge(row.get("codigo_municipio_ibge"))
                    area = num(row.get("area_ha"))
                    if not cod or cod not in valid_muns or area is None:
                        continue
                    cp.write_row((
                        integer(row["ano"]), cod, clean_str(row.get("bioma")) or "Desconhecido",
                        integer(row.get("classe_id")) or 0,
                        clean_str(row.get("classe_nivel_0")), clean_str(row.get("classe_nivel_1")),
                        clean_str(row.get("classe_nivel_2")), clean_str(row.get("classe_nivel_3")),
                        clean_str(row.get("classe_nivel_4")), area,
                    ))
                    c_cob += 1
                    if c_cob % 500_000 == 0:
                        print(f"       cobertura: {c_cob:,} linhas ...", flush=True)
        # Atualiza bioma predominante em dim_municipios com base no ano mais recente do MapBiomas
        cur.execute(
            """
            WITH latest AS (SELECT MAX(ano) AS max_ano FROM agro.fato_mapbiomas_cobertura),
            ranked AS (
                SELECT codigo_municipio_ibge, bioma,
                       ROW_NUMBER() OVER (PARTITION BY codigo_municipio_ibge ORDER BY SUM(area_ha) DESC) AS rn
                FROM agro.fato_mapbiomas_cobertura, latest
                WHERE ano = latest.max_ano
                GROUP BY codigo_municipio_ibge, bioma
            )
            UPDATE agro.dim_municipios m
            SET bioma_predominante = r.bioma
            FROM ranked r
            WHERE m.codigo_municipio_ibge = r.codigo_municipio_ibge AND r.rn = 1
            """
        )
    con.commit()
    print(f"[OK  ] fato_mapbiomas_cobertura: {c_cob:,} linhas em {time.perf_counter() - t0:.1f}s")

    t1 = time.perf_counter()
    print(f"[MB  ] Carregando {desm_path.name} ...", flush=True)
    c_desm = 0
    with con.cursor() as cur:
        cur.execute("TRUNCATE TABLE agro.fato_mapbiomas_desmatamento")
        with cur.copy(
            """COPY agro.fato_mapbiomas_desmatamento (
                ano, codigo_municipio_ibge, bioma, colecao,
                classe_transicao_id, classe_transicao_nome, classe_id,
                classe_nivel_0, classe_nivel_1, classe_nivel_2, classe_nivel_3, classe_nivel_4,
                area_ha
            ) FROM STDIN"""
        ) as cp:
            with gzip.open(desm_path, "rt", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    cod = valid_ibge(row.get("codigo_municipio_ibge"))
                    area = num(row.get("area_ha"))
                    if not cod or cod not in valid_muns or area is None:
                        continue
                    cp.write_row((
                        integer(row["ano"]), cod, clean_str(row.get("bioma")) or "Desconhecido",
                        clean_str(row.get("colecao")),
                        integer(row.get("classe_transicao_id")), clean_str(row.get("classe_transicao_nome")),
                        integer(row.get("classe_id")),
                        clean_str(row.get("classe_nivel_0")), clean_str(row.get("classe_nivel_1")),
                        clean_str(row.get("classe_nivel_2")), clean_str(row.get("classe_nivel_3")),
                        clean_str(row.get("classe_nivel_4")), area,
                    ))
                    c_desm += 1
                    if c_desm % 500_000 == 0:
                        print(f"       desmatamento: {c_desm:,} linhas ...", flush=True)
    con.commit()
    print(f"[OK  ] fato_mapbiomas_desmatamento: {c_desm:,} linhas em {time.perf_counter() - t1:.1f}s")
    return c_cob, c_desm


def load_trase(con: psycopg.Connection) -> int:
    files = [
        ("soja", PROCESSED_DIR / "trase_soja_fluxos.csv.gz"),
        ("bovinos", PROCESSED_DIR / "trase_bovinos_fluxos.csv.gz"),
    ]
    t0 = time.perf_counter()
    total = 0
    with con.cursor() as cur:
        cur.execute("TRUNCATE TABLE agro.fato_trase_fluxos RESTART IDENTITY")
        with cur.copy(
            """COPY agro.fato_trase_fluxos (
                produto, ano, codigo_municipio_ibge, municipio_producao, estado_producao,
                bioma, hub_logistico, porto_exportacao, tipo_produto,
                exportador, grupo_exportador, importador, grupo_importador,
                pais_destino, pais_destino_trase_id, bloco_economico,
                volume_comercializado_t, valor_comercializado_usd, area_uso_ha,
                desmatamento_exposicao_5_anos_ha, emissoes_liquidas_5_anos_tco2e,
                emissoes_brutas_5_anos_tco2e, compromisso_desmatamento_zero,
                forest_500_score, municipio_producao_trase_id, fonte, versao_fonte
            ) FROM STDIN"""
        ) as cp:
            for produto, path in files:
                print(f"[TRAS] Carregando {path.name} ({produto}) ...", flush=True)
                sub = 0
                with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
                    for row in csv.DictReader(f):
                        if produto == "soja":
                            hub = clean_str(row.get("hub_logistico"))
                            pais = clean_str(row.get("pais_primeira_importacao"))
                            pais_id = clean_str(row.get("pais_primeira_importacao_trase_id"))
                            area = num(row.get("area_soja_ha"))
                            exp5 = num(row.get("desmatamento_soja_exposicao_5_anos_ha"))
                            em_liq = num(row.get("emissoes_liquidas_desmatamento_soja_5_anos_tco2e"))
                            em_bru = num(row.get("emissoes_brutas_desmatamento_soja_5_anos_tco2e"))
                            tipo = "SOY"
                        else:
                            hub = clean_str(row.get("municipio_abate"))
                            pais = clean_str(row.get("pais_destino"))
                            pais_id = clean_str(row.get("pais_destino_trase_id"))
                            area = num(row.get("area_pastagem_ha"))
                            exp5 = num(row.get("desmatamento_bovinos_exposicao_5_anos_ha"))
                            em_liq = num(row.get("emissoes_liquidas_desmatamento_bovinos_5_anos_tco2e"))
                            em_bru = num(row.get("emissoes_brutas_desmatamento_bovinos_5_anos_tco2e"))
                            tipo = clean_str(row.get("tipo_produto"))

                        cp.write_row((
                            produto, integer(row["ano"]), valid_ibge(row.get("codigo_municipio_ibge")),
                            clean_str(row.get("municipio_producao")), clean_str(row.get("estado_producao")),
                            clean_str(row.get("bioma")), hub, clean_str(row.get("porto_exportacao")), tipo,
                            clean_str(row.get("exportador")), clean_str(row.get("grupo_exportador")),
                            clean_str(row.get("importador")), clean_str(row.get("grupo_importador")),
                            pais, pais_id, clean_str(row.get("bloco_economico")),
                            num(row.get("volume_comercializado_t")), num(row.get("valor_comercializado_usd")),
                            area, exp5, em_liq, em_bru,
                            clean_str(row.get("compromisso_desmatamento_zero")),
                            num(row.get("forest_500_score")),
                            clean_str(row.get("municipio_producao_trase_id")),
                            clean_str(row.get("fonte")), clean_str(row.get("versao_fonte")),
                        ))
                        sub += 1
                        total += 1
                        if sub % 500_000 == 0:
                            print(f"       {produto}: {sub:,} linhas ...", flush=True)
                print(f"       {produto}: {sub:,} linhas carregadas.")
    con.commit()
    print(f"[OK  ] fato_trase_fluxos: {total:,} linhas em {time.perf_counter() - t0:.1f}s")
    return total


def load_sigsif(con: psycopg.Connection) -> int:
    path = ONDA2_DIR / "mapa_sigsif_estabelecimentos.csv"
    if not path.exists() or path.stat().st_size < 100:
        print("[SKIP] MAPA SIGSIF não encontrado.")
        return 0
    t0 = time.perf_counter()
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return 0
    lines = text.splitlines()
    delim = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delim)

    def pick(row: dict, *candidates: str) -> str | None:
        norm_map = {norm(k): v for k, v in row.items() if k}
        for c in candidates:
            for k, v in norm_map.items():
                if c in k and v and str(v).strip():
                    return str(v).strip()
        return None

    # Mapa (uf, municipio_norm) -> codigo_municipio_ibge
    with con.cursor() as cur:
        cur.execute("SELECT uf, municipio_norm, codigo_municipio_ibge FROM agro.dim_municipios")
        mun_lookup = {(uf, mnorm): cod for uf, mnorm, cod in cur.fetchall()}

        cur.execute("TRUNCATE TABLE agro.dim_instalacoes_sif RESTART IDENTITY")
        count = 0
        with cur.copy(
            """COPY agro.dim_instalacoes_sif (
                sif, cnpj, razao_social, municipio, municipio_norm, uf,
                codigo_municipio_ibge, categoria, classe, situacao, area_atuacao, fonte
            ) FROM STDIN"""
        ) as cp:
            for row in reader:
                sif = pick(row, "NR_SIF", "SIF", "NUMERO")
                if not sif:
                    continue
                mun = pick(row, "MUNICIPIO", "CIDADE")
                uf = pick(row, "UF", "ESTADO")
                uf_clean = norm(uf)[:2] if uf else None
                mun_n = norm(mun)
                cod = mun_lookup.get((uf_clean, mun_n)) if uf_clean and mun_n else None
                cp.write_row((
                    sif, pick(row, "CNPJ", "CPF"), pick(row, "RAZAO", "NOME", "EMPRESARIAL"),
                    mun, mun_n or None, uf_clean, cod,
                    pick(row, "CATEGORIA"), pick(row, "CLASSE"),
                    pick(row, "SITUACAO", "STATUS"), pick(row, "AREA", "ATUACAO"),
                    "MAPA SIGSIF",
                ))
                count += 1
    con.commit()
    print(f"[OK  ] dim_instalacoes_sif: {count:,} estabelecimentos em {time.perf_counter() - t0:.1f}s")
    return count


def load_inpe_deter(con: psycopg.Connection) -> int:
    zips = sorted(ONDA2_DIR.glob("deter-*.zip"))
    if not zips:
        print("[SKIP] Arquivos ZIP INPE DETER não encontrados em data/raw/onda2/.")
        return 0

    import shapefile  # pyshp

    t0 = time.perf_counter()
    total = 0
    with con.cursor() as cur:
        cur.execute("SELECT uf, municipio_norm, codigo_municipio_ibge FROM agro.dim_municipios")
        mun_lookup = {(uf, mnorm): cod for uf, mnorm, cod in cur.fetchall()}

        cur.execute("TRUNCATE TABLE agro.fato_inpe_deter RESTART IDENTITY")
        with cur.copy(
            """COPY agro.fato_inpe_deter (
                bioma, view_date, ano, mes, classname, codigo_municipio_ibge,
                municipio, uf, uc, area_mun_km2, area_uc_km2, sensor, satellite, lat, lon
            ) FROM STDIN"""
        ) as cp:
            for path in zips:
                name_l = path.name.lower()
                if "amz" in name_l:
                    bioma = "AMAZONIA"
                elif "cerrado" in name_l:
                    bioma = "CERRADO"
                elif "pantanal" in name_l:
                    bioma = "PANTANAL"
                else:
                    bioma = "OUTRO"
                print(f"[INPE] Lendo {path.name} ({bioma}) ...", flush=True)
                sf = shapefile.Reader(str(path))
                fields = [f[0] for f in sf.fields[1:]]
                idx = {name: i for i, name in enumerate(fields)}
                sub = 0
                for sr in sf.iterShapeRecords():
                    rec = sr.record
                    def get(*names):
                        for nm in names:
                            i = idx.get(nm)
                            if i is not None:
                                v = rec[i]
                                if v is not None and str(v).strip() != "":
                                    return v
                        return None

                    vdate_raw = get("VIEW_DATE", "view_date")
                    vdate = vdate_raw.isoformat()[:10] if hasattr(vdate_raw, "isoformat") else clean_str(vdate_raw)
                    if vdate and "T" in vdate:
                        vdate = vdate.split("T", 1)[0]
                    ano = int(vdate[:4]) if vdate and len(vdate) >= 4 and vdate[:4].isdigit() else None
                    mes = int(vdate[5:7]) if vdate and len(vdate) >= 7 and vdate[5:7].isdigit() else None

                    classname = clean_str(get("CLASSNAME", "CLASS_NAME", "classname"))
                    uf_val = norm(get("UF", "uf"))[:2] or None
                    mun_val = clean_str(get("MUNICIPALI", "MUNICIPALITY", "municipality"))
                    cod = valid_ibge(get("GEOCODIBGE", "GEOCOD_IBGE", "geocod_ibge"))
                    if not cod and uf_val and mun_val:
                        cod = mun_lookup.get((uf_val, norm(mun_val)))

                    area_mun = num(get("AREAMUNKM", "AREA_KM", "areamunkm"))
                    area_uc = num(get("AREAUCKM", "areauckm"))
                    uc_val = clean_str(get("UC", "uc"))
                    sensor = clean_str(get("SENSOR", "sensor"))
                    sat = clean_str(get("SATELLITE", "satellite"))

                    lat = lon = None
                    try:
                        bbox = sr.shape.bbox
                        if bbox and len(bbox) == 4:
                            lon = round((bbox[0] + bbox[2]) / 2.0, 6)
                            lat = round((bbox[1] + bbox[3]) / 2.0, 6)
                    except Exception:
                        pass

                    cp.write_row((
                        bioma, vdate, ano, mes, classname, cod, mun_val, uf_val,
                        uc_val, area_mun, area_uc, sensor, sat, lat, lon,
                    ))
                    sub += 1
                    total += 1
                    if sub % 100_000 == 0:
                        print(f"       {bioma}: {sub:,} alertas ...", flush=True)
                print(f"       {bioma}: {sub:,} alertas carregados.")

        # Spatial join PostGIS para alertas sem código IBGE (ex.: DETER Pantanal)
        print("[GIS ] Resolvendo municípios via PostGIS ST_Intersects para alertas sem GEOCODIBGE ...", flush=True)
        cur.execute(
            """
            UPDATE agro.fato_inpe_deter d
            SET codigo_municipio_ibge = m.codigo_municipio_ibge,
                municipio = COALESCE(d.municipio, m.municipio),
                uf = COALESCE(d.uf, m.uf)
            FROM agro.dim_municipios m
            WHERE d.codigo_municipio_ibge IS NULL
              AND d.lat IS NOT NULL AND d.lon IS NOT NULL
              AND m.geom IS NOT NULL
              AND ST_Intersects(m.geom, ST_SetSRID(ST_MakePoint(d.lon, d.lat), 4326))
            """
        )
        print(f"       PostGIS atribuiu município a {cur.rowcount:,} alertas.")
    con.commit()
    print(f"[OK  ] fato_inpe_deter: {total:,} alertas em {time.perf_counter() - t0:.1f}s")
    return total


def update_catalog(con: psycopg.Connection) -> None:
    entries = [
        ("ibge_pam_soja", "IBGE PAM — Soja", "IBGE / SIDRA", "producao",
         "https://sidra.ibge.gov.br/pesquisa/pam/tabelas", "2000-2025", "municipio_ano",
         "Valores de produção são nominais (mil R$) sem correção monetária; células sigilosas/indisponíveis preservadas como nulas com status explícito.",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_ibge_pam_soja"),
        ("ibge_ppm_bovinos", "IBGE PPM — Efetivo Bovino", "IBGE / SIDRA", "producao",
         "https://sidra.ibge.gov.br/pesquisa/ppm/tabelas", "2000-2025", "municipio_ano",
         "Efetivo anual em cabeças; não representa abate nem fluxo comercial.",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_ibge_ppm_bovinos"),
        ("mapbiomas_cobertura", "MapBiomas Cobertura da Terra", "MapBiomas", "uso_terra",
         "https://brasil.mapbiomas.org/", "Coleção 11", "municipio_ano",
         "Área por classe de cobertura (ha). Não deve ser somada com métricas da Trase.",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_mapbiomas_cobertura"),
        ("mapbiomas_desmatamento", "MapBiomas Desmatamento Anual", "MapBiomas", "desmatamento",
         "https://brasil.mapbiomas.org/", "Coleção 11", "municipio_ano",
         "Transições de supressão de vegetação nativa por município/ano. Não comprova ilegalidade individual.",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_mapbiomas_desmatamento"),
        ("trase_fluxos", "Trase — Cadeias de Soja e Carne Bovina", "Trase", "cadeia",
         "https://trase.earth/open-data", "Soja v2.6.1 / Bovinos v2.2.2", "fluxo_ano",
         "Exposição ao desmatamento usa janela de 5 anos (NÃO somar entre anos). Origens UNKNOWN (BR-XXXXXXX) mantidas com codigo_municipio_ibge NULL. Exposição ≠ ilegalidade.",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_trase_fluxos"),
        ("mapa_sigsif", "MAPA SIGSIF — Estabelecimentos SIF", "MAPA", "infraestrutura",
         "https://dados.agricultura.gov.br/", "Oficial CSV", "estabelecimento",
         "Cadastro administrativo de estabelecimentos com Serviço de Inspeção Federal; ligação municipal feita por UF + nome normalizado.",
         "SELECT COUNT(*), NULL, NULL FROM agro.dim_instalacoes_sif"),
        ("inpe_deter", "INPE TerraBrasilis — Alertas DETER", "INPE", "desmatamento",
         "https://terrabrasilis.dpi.inpe.br/", "TerraBrasilis · Amazônia, Cerrado e Pantanal", "alerta_data",
         "Sistema de alertas rápidos para fiscalização; não substitui a taxa oficial consolidada do PRODES.",
         "SELECT COUNT(*), MIN(ano), MAX(ano) FROM agro.fato_inpe_deter"),
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
    con.commit()
    print("[OK  ] dim_fontes atualizado.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        default="all",
        help="Módulos separados por vírgula: dim,ibge,mapbiomas,trase,sif,deter,gold (padrão: all)",
    )
    args = parser.parse_args()
    steps = {"dim", "ibge", "mapbiomas", "trase", "sif", "deter", "gold"} if args.only == "all" else {
        s.strip().lower() for s in args.only.split(",") if s.strip()
    }

    t_all = time.perf_counter()
    with connect() as con:
        apply_sql(con, SCHEMA_SQL)
        if "dim" in steps:
            load_dim_municipios(con)
        if "ibge" in steps:
            load_ibge_pam(con)
            load_ibge_ppm(con)
        if "mapbiomas" in steps:
            load_mapbiomas(con)
        if "trase" in steps:
            load_trase(con)
        if "sif" in steps:
            load_sigsif(con)
        if "deter" in steps:
            load_inpe_deter(con)
        update_catalog(con)
        if "gold" in steps:
            apply_sql(con, GOLD_SQL)
        with con.cursor() as cur:
            cur.execute("ANALYZE;")
        con.commit()

    print(f"\nEcossistema consolidado no PostgreSQL em {time.perf_counter() - t_all:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

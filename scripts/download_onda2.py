"""Baixa bases oficiais abertas da Onda 2 + malha municipal IBGE para data/raw/onda2/.

Uso:
    .venv/bin/python scripts/download_onda2.py
"""

from __future__ import annotations

from pathlib import Path
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "raw" / "onda2"

SOURCES = [
    (
        "ibge_municipios.json",
        "https://servicodados.ibge.gov.br/api/v1/localidades/municipios",
        "IBGE Localidades — 5.570 municípios",
    ),
    (
        "ibge_malha_municipios_br.geojson",
        "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
        "?intrarregiao=municipio&qualidade=minima&formato=application/vnd.geo+json",
        "IBGE Malha Municipal (GeoJSON simplificado)",
    ),
    (
        "mapa_sigsif_estabelecimentos.csv",
        "https://dados.agricultura.gov.br/dataset/062166e3-b515-4274-8e7d-68aadd64b820"
        "/resource/97277e92-264a-4dc0-9aea-f87b8ea93798/download/"
        "sigsifestabelecimentosregistradosnosif.csv",
        "MAPA SIGSIF — Estabelecimentos registrados no SIF",
    ),
    (
        "inpe_deter_amazonia.csv",
        "https://terrabrasilis.dpi.inpe.br/geoserver/deter-amz/ows"
        "?service=WFS&version=1.0.0&request=GetFeature"
        "&typeName=deter-amz:deter_amz"
        "&propertyName=classname,quadrant,path_row,view_date,sensor,satellite,areauckm,uc,areamunkm,municipality,geocod_ibge,uf"
        "&outputFormat=csv",
        "INPE TerraBrasilis — DETER Amazônia (CSV via WFS)",
    ),
    (
        "inpe_deter_cerrado.csv",
        "https://terrabrasilis.dpi.inpe.br/geoserver/deter-cerrado-nb/ows"
        "?service=WFS&version=1.0.0&request=GetFeature"
        "&typeName=deter-cerrado-nb:deter_cerrado"
        "&propertyName=classname,quadrant,path_row,view_date,sensor,satellite,areauckm,uc,areamunkm,municipality,geocod_ibge,uf"
        "&outputFormat=csv",
        "INPE TerraBrasilis — DETER Cerrado (CSV via WFS)",
    ),
]


def download(filename: str, url: str, label: str) -> bool:
    dest = OUT_DIR / filename
    if dest.exists() and dest.stat().st_size > 1000:
        print(f"[SKIP] {label} já existe ({dest.stat().st_size / 1_048_576:.2f} MB)")
        return True
    print(f"[GET ] {label} ...", flush=True)
    try:
        with requests.get(url, stream=True, timeout=180, headers={"User-Agent": "Agro-Data-Pipeline/1.0"}) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            size = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=131_072):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
            tmp.replace(dest)
        print(f"[OK  ] {filename} ({size / 1_048_576:.2f} MB)")
        return True
    except Exception as exc:
        print(f"[ERR ] {label}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for filename, url, label in SOURCES:
        if download(filename, url, label):
            ok += 1
    print(f"\nConcluído: {ok}/{len(SOURCES)} fontes baixadas em {OUT_DIR}")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

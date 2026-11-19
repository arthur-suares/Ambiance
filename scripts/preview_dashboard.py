"""Pré-visualização do visual dos dashboards, sem chave, sem rede e sem banco.

Monta um painel com DADOS DE EXEMPLO (sintéticos) usando todos os tipos de componente e grava:
    outputs/dashboards/_preview_claro.html
    outputs/dashboards/_preview_escuro.html

Uso:
    python scripts/preview_dashboard.py            # Plotly embutido (funciona offline)
    python scripts/preview_dashboard.py --cdn      # Plotly pelo CDN (arquivo menor)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dashboard.renderer import render_dashboard_html  # noqa: E402
from src.dashboard.schemas import DatasetResult, parse_dashboard_spec  # noqa: E402

SRC = "Trase — Soja, dados de exemplo"


def _ds(did: str, df: pd.DataFrame, purpose: str) -> DatasetResult:
    return DatasetResult(dataset_id=did, database="exemplo", source_label=SRC, tool_name="exemplo",
                         query_summary=f"-- {purpose} (dados sintéticos para pré-visualização)", df=df)


def build_example() -> tuple:
    anos = list(range(2013, 2023))
    serie = pd.DataFrame({
        "year": anos,
        "volume_t": [8.7e6, 8.8e6, 8.5e6, 10.1e6, 11.3e6, 9.9e6, 10.5e6, 12.2e6, 12.5e6, 13.9e6],
        "exposicao_ha": [18871, 18558, 23554, 22425, 28956, 20856, 20838, 19356, 15304, 21671],
        "fob_usd": [3.1e9, 2.6e9, 2.4e9, 2.9e9, 3.3e9, 3.0e9, 2.8e9, 3.6e9, 4.9e9, 6.1e9],
    }).sort_values("year", ascending=False, ignore_index=True)  # como o SQL faria: ano mais recente primeiro
    biomas = pd.DataFrame([
        {"year": a, "biome": b, "volume_t": v}
        for a, base in zip(serie["year"], serie["volume_t"])
        for b, v in (("CERRADO", base * 0.82), ("MATA ATLANTICA", base * 0.18))
    ])
    municipios = pd.DataFrame({
        "municipality": ["RIO VERDE", "JATAI", "CRISTALINA", "PARAUNA", "MONTIVIDIU", "CATALAO",
                         "IPAMERI", "MINEIROS", "SILVANIA", "CAMPO ALEGRE DE GOIAS"],
        "volume_t": [1633200, 1149600, 1004700, 574000, 553800, 468900, 402900, 384800, 309300, 288600],
        "exposicao_ha": [261, 430, 4973, 331, 210, 500, 1160, 383, 365, 438],
    })
    destinos = pd.DataFrame({
        "country_of_first_import": ["CHINA (MAINLAND)", "BRAZIL", "THAILAND", "INDONESIA", "VIETNAM", "SPAIN"],
        "volume_t": [6097318, 3640447, 806972, 679894, 305391, 241930],
    })
    # Participação com "Outros" calculado na consulta (total menos os maiores), como o Agente de Dados faz.
    partes = pd.DataFrame({
        "country_of_first_import": ["CHINA (MAINLAND)", "THAILAND", "INDONESIA", "VIETNAM", "SPAIN", "Outros"],
        "volume_t": [6097318, 806972, 679894, 305391, 241930, 412180],
    })
    china = pd.DataFrame({"china_pct": [71.86]})
    variacao = pd.DataFrame({
        "country_of_first_import": ["CHINA (MAINLAND)", "THAILAND", "SPAIN", "VIETNAM", "Outros"],
        "variacao_t": [912400, -184300, 96100, -42800, 21500],
    })
    datasets = [_ds("D1", serie, "série anual"), _ds("D2", biomas, "volume por bioma e ano"),
                _ds("D3", municipios, "ranking municipal 2022"), _ds("D4", destinos, "destinos 2022"),
                _ds("D5", partes, "participação por destino com Outros, 2022"),
                _ds("D6", china, "parte do volume exportado para a China, 2022"),
                _ds("D7", variacao, "variação do volume por destino, 2021 a 2022")]
    spec = parse_dashboard_spec({
        "title": "Panorama da soja em Goiás (dados de exemplo)",
        "subtitle": "Pré-visualização do visual dos painéis. Os números são sintéticos e servem só para conferir o layout.",
        "warnings": ["Exposição ao desmatamento usa janela de 5 anos: compare anos lado a lado, sem somar."],
        "widgets": [
            {"id": "k1", "kind": "kpi", "title": "Volume originado, 2022", "dataset_id": "D1",
             "column": "volume_t", "agg": "first", "unit": "t", "source": f"{SRC} [D1]",
             "trend_x": "year", "trend_y": "volume_t"},
            {"id": "k2", "kind": "kpi", "title": "Exposição ao desmatamento, 2022", "dataset_id": "D1",
             "column": "exposicao_ha", "agg": "first", "unit": "ha", "source": f"{SRC} [D1]",
             "subtitle": "Janela de 5 anos; não somar entre anos.", "trend_x": "year", "trend_y": "exposicao_ha"},
            {"id": "k3", "kind": "kpi", "title": "Municípios de origem", "dataset_id": "D3",
             "column": "municipality", "agg": "count", "unit": "municípios", "source": f"{SRC} [D3]"},
            {"id": "k4", "kind": "kpi", "title": "Países de destino (exceto Brasil)", "dataset_id": "D4",
             "column": "volume_t", "agg": "count", "unit": "países", "source": f"{SRC} [D4]"},
            {"id": "g1", "kind": "gauge", "title": "Parte do volume exportado que foi para a China, 2022",
             "dataset_id": "D6", "column": "china_pct", "agg": "first", "unit": "%", "source": f"{SRC} [D6]"},
            {"id": "l1", "kind": "line", "title": "Exposição ao desmatamento por ano", "dataset_id": "D1",
             "x": "year", "y": ["exposicao_ha"], "column_labels": {"exposicao_ha": "Exposição"},
             "unit": "ha", "source": f"{SRC} [D1]", "subtitle": "Cada ponto é a janela de 5 anos daquele ano."},
            {"id": "a1", "kind": "area", "title": "Volume por bioma de origem", "dataset_id": "D2",
             "x": "year", "y": ["volume_t"], "color": "biome", "stacked": True,
             "column_labels": {"volume_t": "Volume"}, "unit": "t", "source": f"{SRC} [D2]"},
            {"id": "b1", "kind": "bar", "title": "Maiores municípios de origem, 2022", "dataset_id": "D3",
             "x": "municipality", "y": ["volume_t"], "orientation": "h", "column_labels": {"volume_t": "Volume"},
             "unit": "t", "source": f"{SRC} [D3]", "subtitle": "Origem rastreada, sem UNKNOWN."},
            {"id": "pz", "kind": "pie", "title": "Para onde vai a soja exportada, 2022", "dataset_id": "D5",
             "x": "country_of_first_import", "y": ["volume_t"], "unit": "t", "source": f"{SRC} [D5]",
             "subtitle": "Exportações, sem o consumo no Brasil."},
            {"id": "rz", "kind": "donut", "title": "Os mesmos destinos, em rosca", "dataset_id": "D5",
             "x": "country_of_first_import", "y": ["volume_t"], "unit": "t", "source": f"{SRC} [D5]"},
            {"id": "wf", "kind": "waterfall", "title": "O que mais pesou na variação do volume, 2021 a 2022",
             "dataset_id": "D7", "x": "country_of_first_import", "y": ["variacao_t"], "unit": "t",
             "source": f"{SRC} [D7]", "span": 2},
            {"id": "pl", "kind": "line", "title": "Volume exportado por ano", "dataset_id": "D1", "x": "year",
             "y": ["volume_t"], "unit": "t", "source": f"{SRC} [D1]", "group": "volume_e_valor"},
            {"id": "pb", "kind": "bar", "title": "Valor exportado por ano", "dataset_id": "D1", "x": "year",
             "y": ["fob_usd"], "unit": "US$", "source": f"{SRC} [D1]", "group": "volume_e_valor"},
            {"id": "p1", "kind": "progress", "title": "Participação por destino, 2022", "dataset_id": "D4",
             "x": "country_of_first_import", "y": ["volume_t"], "unit": "t", "source": f"{SRC} [D4]",
             "subtitle": "Brasil = processamento doméstico, não é exportação."},
            {"id": "t1", "kind": "table", "title": "Detalhamento por município, 2022", "dataset_id": "D3",
             "span": 2, "columns": ["municipality", "volume_t", "exposicao_ha"],
             "column_labels": {"municipality": "Município", "volume_t": "Volume (t)", "exposicao_ha": "Exposição (ha)"},
             "unit": "t / ha", "source": f"{SRC} [D3]"},
            {"id": "x1", "kind": "bar", "title": "Exemplo de componente com erro", "dataset_id": "D3",
             "x": "municipality", "y": ["coluna_inexistente"], "unit": "t", "source": f"{SRC} [D3]"},
        ],
    })
    # Como a IA faria: cada KPI informa o valor, que o validador confere contra o DataFrame.
    from src.dashboard.schemas import compute_kpi_value
    by_id = {d.dataset_id: d.df for d in datasets}
    for w in spec.widgets:
        if w.kind in ("kpi", "gauge"):
            w.value = compute_kpi_value(by_id[w.dataset_id], w.column, w.agg)
    return spec, datasets


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cdn", action="store_true", help="carrega o Plotly pelo CDN em vez de embutir")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "dashboards"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    spec, datasets = build_example()
    for theme, name in (("light", "_preview_claro.html"), ("dark", "_preview_escuro.html")):
        page = render_dashboard_html(spec, datasets, question="Panorama da soja em Goiás",
                                     plotlyjs="cdn" if args.cdn else "inline", theme=theme)
        (out / name).write_text(page, encoding="utf-8")
        print(f"gravado: {out / name}")


if __name__ == "__main__":
    main()

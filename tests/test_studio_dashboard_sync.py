"""Testes da unificação da aba Dados no studio e do tema embed do Painel completo."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.agro_chat import _evaluate_views
from src.dashboard.renderer import (
    PAGE_CSS,
    load_studio_chart_colors,
    load_studio_tokens,
    render_dashboard_html,
)
from src.dashboard.schemas import DatasetResult, parse_dashboard_spec

ROOT = Path(__file__).resolve().parents[1]


def test_studio_html_unifica_graficos_e_tabela_em_dados():
    html = (ROOT / "web" / "studio.html").read_text(encoding="utf-8")
    assert 'id="tab-btn-charts"' not in html
    assert 'id="panel-charts"' not in html
    assert 'id="tab-btn-data">Dados</button>' in html
    panel_data = html[html.index('id="panel-data"'):html.index('id="panel-dash"')]
    assert 'id="charts-container"' in panel_data
    assert 'id="data-container"' in panel_data
    assert panel_data.index('id="charts-container"') < panel_data.index('id="data-container"')


def test_evaluate_views_unifica_graficos_e_tabelas_em_data():
    tables = [{"purpose": "Top 10 municípios MT", "columns": ["municipio", "ha"], "rows": [{"municipio": "Sorriso", "ha": 10}]}]
    charts = [{"title": "Top 10 municípios de MT"}]
    map_spec = {"title": "Desmatamento em MT", "uf": "MT", "year": 2022}

    _, _, views = _evaluate_views("agro", tables, charts, map_spec, [])
    keys = [v["key"] for v in views]
    assert keys == ["map", "data"]
    data_view = views[1]
    assert data_view["label"] == "Dados"
    assert "gráfico" in data_view["what_you_see"].lower()
    assert "tabela" in data_view["what_you_see"].lower()
    assert "csv" in data_view["what_you_receive"].lower()


def test_evaluate_views_somente_lei_retorna_apenas_trechos():
    tables = [{"purpose": "Ignorar"}]
    charts = [{"title": "Ignorar"}]
    map_spec = {"title": "Ignorar"}
    sources = [{"title": "Código Florestal", "artigo": "12"}]

    final_map, final_charts, views = _evaluate_views("law", tables, charts, map_spec, sources)
    assert final_map is None
    assert final_charts == []
    assert [v["key"] for v in views] == ["laws"]


def test_embed_reaproveita_tokens_e_cores_do_studio_sem_alterar_standalone():
    tokens = load_studio_tokens()
    chart_colors = load_studio_chart_colors()
    assert tokens["bg"] == "#f6f7f4"
    assert tokens["accent"] == "#15803d"
    assert "Plus Jakarta Sans" in tokens["font"]
    assert chart_colors[:3] == ("#10b981", "#38bdf8", "#f59e0b")

    # Standalone (PAGE_CSS) continua intacto
    assert "--bg: #f6f5f0;" in PAGE_CSS
    assert "--accent: #b5832a;" in PAGE_CSS

    df = pd.DataFrame({"municipality": ["SORRISO", "SINOP"], "exposicao_ha": [1200.0, 900.0]})
    ds = DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)
    spec = parse_dashboard_spec({
        "title": "Exposição ao desmatamento em MT",
        "widgets": [{
            "id": "b1",
            "kind": "bar",
            "title": "Ranking municipal",
            "dataset_id": "D1",
            "x": "municipality",
            "y": ["exposicao_ha"],
            "orientation": "h",
            "unit": "ha",
            "source": "Trase [D1]",
        }],
    })
    rendered = render_dashboard_html(spec, [ds], plotlyjs="cdn")
    assert '<style id="studio-embed-theme">' in rendered
    assert ":root.is-embed" in rendered
    assert "--studio-accent: #15803d;" in rendered
    assert "--studio-bg: #f6f7f4;" in rendered
    assert '"#10b981"' in rendered
    assert "fonts.googleapis" not in rendered

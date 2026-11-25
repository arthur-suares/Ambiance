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
    assert ':root.is-embed[data-theme="dark"]' in rendered
    assert "color-scheme: light;" in rendered
    assert '"#10b981"' in rendered
    assert "fonts.googleapis" not in rendered


def test_revisor_reprova_painel_sem_kpis_poucos_graficos_ou_dominado_por_tabelas():
    from src.dashboard.reviewer_agent import check_dashboard_structure

    df_muni = pd.DataFrame({
        "municipality": ["SORRISO", "SINOP", "LUCAS", "NOVA MUTUM"],
        "exposicao_ha": [4200.0, 3100.0, 2200.0, 1800.0],
        "volume_t": [2.1e6, 1.5e6, 1.1e6, 0.9e6],
    })
    df_dest = pd.DataFrame({
        "country_of_first_import": ["CHINA", "SPAIN", "NETHERLANDS", "OUTROS"],
        "volume_t": [3.0e6, 1.0e6, 0.8e6, 0.8e6],
    })
    datasets = [
        DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df_muni),
        DatasetResult("D2", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 2", df_dest),
    ]
    bad_spec = parse_dashboard_spec({
        "title": "Painel só com tabelas",
        "widgets": [
            {"id": "b1", "kind": "bar", "title": "Ranking", "dataset_id": "D1", "x": "municipality", "y": ["exposicao_ha"], "unit": "ha", "source": "Trase [D1]"},
            {"id": "t1", "kind": "table", "title": "Tab 1", "dataset_id": "D1", "unit": "ha", "source": "Trase [D1]"},
            {"id": "t2", "kind": "table", "title": "Tab 2", "dataset_id": "D2", "unit": "t", "source": "Trase [D2]"},
        ],
    })
    issues = check_dashboard_structure(bad_spec, datasets)
    joined = " | ".join(i.message for i in issues)
    assert "0 KPIs" in joined
    assert "apenas 1 gráfico" in joined
    assert "mais tabelas" in joined

    good_spec = parse_dashboard_spec({
        "title": "Painel executivo completo",
        "widgets": [
            {"id": "k1", "kind": "kpi", "title": "Exposição total", "dataset_id": "D1", "column": "exposicao_ha", "agg": "sum", "value": 11300.0, "unit": "ha", "source": "Trase [D1]"},
            {"id": "k2", "kind": "kpi", "title": "Volume total", "dataset_id": "D1", "column": "volume_t", "agg": "sum", "value": 5.6e6, "unit": "t", "source": "Trase [D1]"},
            {"id": "k3", "kind": "kpi", "title": "Municípios", "dataset_id": "D1", "column": "municipality", "agg": "count", "value": 4.0, "unit": "municípios", "source": "Trase [D1]"},
            {"id": "b1", "kind": "bar", "title": "Ranking exposição", "dataset_id": "D1", "x": "municipality", "y": ["exposicao_ha"], "orientation": "h", "unit": "ha", "source": "Trase [D1]"},
            {"id": "d1", "kind": "donut", "title": "Participação por destino", "dataset_id": "D2", "x": "country_of_first_import", "y": ["volume_t"], "unit": "t", "source": "Trase [D2]"},
            {"id": "p1", "kind": "progress", "title": "Top destinos", "dataset_id": "D2", "x": "country_of_first_import", "y": ["volume_t"], "unit": "t", "source": "Trase [D2]"},
        ],
    })
    assert check_dashboard_structure(good_spec, datasets) == []


def test_chat_context_garante_grafico_da_aba_dados_no_painel_completo():
    from src.dashboard.chat_context import ensure_dados_charts_included

    df_dest = pd.DataFrame({"pais": ["CHINA", "ESPANHA"], "volume_t": [100.0, 50.0]})
    datasets = [DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df_dest)]
    spec = parse_dashboard_spec({
        "title": "Soja em MT",
        "widgets": [
            {"id": "d1", "kind": "donut", "title": "Destinos da soja", "dataset_id": "D1", "x": "pais", "y": ["volume_t"], "unit": "t", "source": "Trase [D1]"},
        ],
    })
    chat_ctx = {
        "charts": [{
            "title": "Top 10 municípios de MT por exposição ao desmatamento (2022)",
            "chart_type": "horizontal_bar",
            "x_label": "Município",
            "y_label": "Exposição",
            "unit": "ha",
            "labels": ["Sorriso", "Nova Ubiratã", "Querência"],
            "series": [{"name": "Exposição ao desmatamento", "values": [4200, 3800, 3100]}],
        }],
        "tables": [],
    }

    added = ensure_dados_charts_included(spec, datasets, chat_ctx, domain="soy")
    assert added == 1
    assert any(w.id == "dados_chart_1" and w.kind == "bar" and w.orientation == "h" for w in spec.widgets)
    # Segunda chamada é idempotente (já existe gráfico equivalente)
    assert ensure_dados_charts_included(spec, datasets, chat_ctx, domain="soy") == 0


def test_renderer_recolhe_tabelas_e_aplica_spans_2_colunas_no_embed():
    df_muni = pd.DataFrame({"municipality": ["A", "B", "C"], "exposicao_ha": [300.0, 200.0, 100.0]})
    df_dest = pd.DataFrame({"pais": ["CHINA", "ESPANHA", "OUTROS"], "volume_t": [60.0, 25.0, 15.0]})
    datasets = [
        DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df_muni),
        DatasetResult("D2", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 2", df_dest),
    ]
    spec = parse_dashboard_spec({
        "title": "Painel MT",
        "widgets": [
            {"id": "k1", "kind": "kpi", "title": "Total", "dataset_id": "D1", "column": "exposicao_ha", "agg": "sum", "value": 600.0, "unit": "ha", "source": "Trase [D1]"},
            {"id": "b1", "kind": "bar", "title": "Ranking", "dataset_id": "D1", "x": "municipality", "y": ["exposicao_ha"], "orientation": "h", "unit": "ha", "source": "Trase [D1]"},
            {"id": "d1", "kind": "donut", "title": "Destinos", "dataset_id": "D2", "x": "pais", "y": ["volume_t"], "unit": "t", "source": "Trase [D2]"},
            {"id": "t1", "kind": "table", "title": "Tabela completa", "dataset_id": "D1", "unit": "ha", "source": "Trase [D1]"},
        ],
    })
    rendered = render_dashboard_html(spec, datasets, plotlyjs="cdn")
    assert 'data-embed-span="7"' in rendered
    assert 'data-embed-span="5"' in rendered
    assert '<details class="full-data-collapse"><summary>Dados completos (1 tabela)</summary>' in rendered
    assert 'class="hero-stats"' in rendered


def test_plan_groups_nao_descarta_kpis_com_mesmo_group_de_graficos():
    df = pd.DataFrame({"year": [2021, 2022], "volume_t": [100.0, 140.0], "fob_usd": [50.0, 80.0]})
    ds = DatasetResult("D1", "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)
    spec = parse_dashboard_spec({
        "title": "Evolução MT",
        "widgets": [
            {"id": "kpi1", "kind": "kpi", "title": "Volume 2022", "dataset_id": "D1", "column": "volume_t",
             "agg": "last", "value": 140.0, "unit": "t", "source": "Trase [D1]", "group": "ev",
             "trend_x": "year", "trend_y": "volume_t"},
            {"id": "w1", "kind": "line", "title": "Volume", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
             "unit": "t", "source": "Trase [D1]", "group": "ev"},
            {"id": "w2", "kind": "bar", "title": "FOB", "dataset_id": "D1", "x": "year", "y": ["fob_usd"],
             "unit": "US$", "source": "Trase [D1]", "group": "ev"},
        ],
    })
    rendered = render_dashboard_html(spec, [ds], plotlyjs="cdn")
    assert 'data-widget-id="kpi1"' in rendered
    assert 'data-widget-id="w1"' in rendered
    assert 'data-widget-id="w2"' in rendered
    assert "+40,0%" in rendered

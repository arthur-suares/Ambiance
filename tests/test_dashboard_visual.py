"""Visual dos dashboards: formato dos números, KPIs com tendência, tipos area/progress, página e segurança.

Todos os números conferidos aqui saem dos DataFrames; nenhum vem da IA.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

from src.dashboard.renderer import (
    build_widget_figure,
    format_compact_br,
    kpi_trend,
    render_dashboard_html,
)
from src.dashboard.reviewer_agent import validate_widget_deterministic
from src.dashboard.schemas import DatasetResult, compute_kpi_value, parse_dashboard_spec

SERIE = pd.DataFrame({"year": [2022, 2021, 2020], "volume_t": [13.9e6, 12.5e6, 12.2e6]})
RANK = pd.DataFrame({"municipality": ["JATAI", "RIO VERDE", "CRISTALINA"], "volume_t": [1149600, 1633200, 1004700]})
DEST = pd.DataFrame({"country_of_first_import": ["CHINA (MAINLAND)", "BRAZIL", "THAILAND"],
                     "volume_t": [6000.0, 3000.0, 1000.0]})


def _ds(did, df):
    return DatasetResult(dataset_id=did, database="soy.duckdb", source_label="Trase — Soja",
                         tool_name="run_soy_sql", query_summary="SELECT 1", df=df)


def _w(**kw):
    base = {"id": "w", "kind": "bar", "title": "T", "dataset_id": "D1", "unit": "t", "source": "Trase [D1]"}
    base.update(kw)
    return parse_dashboard_spec({"title": "P", "widgets": [base]}).widgets[0]


def _page(widgets, datasets, **kw):
    for w in widgets:  # como a IA faria: KPI informa o valor, que o validador confere
        if w.get("kind") == "kpi" and "value" not in w:
            df = {d.dataset_id: d.df for d in datasets}[w["dataset_id"]]
            w["value"] = compute_kpi_value(df, w["column"], w.get("agg", "first"))
    spec = parse_dashboard_spec({"title": kw.pop("title", "Painel"), "widgets": widgets})
    return render_dashboard_html(spec, datasets, **kw)


@pytest.mark.parametrize("valor, unidade, esperado", [
    (13855914.9, "t", "13,9 mi t"),
    (6.069e9, "US$", "US$ 6,07 bi"),
    (21671, "ha", "21,7 mil ha"),
    (1004700, "t", "1,00 mi t"),
    (44.01, "%", "44,0%"),
    (181, "municípios", "181 municípios"),
    (9689, "registros", "9.689 registros"),
    (0.4527, "ha/t", "0,45 ha/t"),
    (float("nan"), "t", "—"),
    ("abc", "t", "—"),
])
def test_formato_compacto_brasileiro(valor, unidade, esperado):
    assert format_compact_br(valor, unidade) == esperado


def test_formato_compacto_sem_unidade_para_rotulos():
    assert format_compact_br(1633200, "t", with_unit=False) == "1,63 mi"


def test_tendencia_do_kpi_calcula_variacao_exata_do_dataframe():
    t = kpi_trend(SERIE, _w(kind="kpi", column="volume_t", trend_x="year", trend_y="volume_t"))
    assert t["xs"] == [2020, 2021, 2022]
    assert t["prev_x"] == 2021
    assert t["delta_pct"] == pytest.approx((13.9e6 - 12.5e6) / 12.5e6 * 100)


def test_tendencia_nao_agrega_periodos_repetidos_nem_inventa_variacao():
    repetido = pd.DataFrame({"year": [2022, 2022, 2021], "v": [1.0, 2.0, 3.0]})
    assert kpi_trend(repetido, _w(kind="kpi", column="v", trend_x="year", trend_y="v")) is None
    um_ponto = pd.DataFrame({"year": [2022], "v": [5.0]})
    assert kpi_trend(um_ponto, _w(kind="kpi", column="v", trend_x="year", trend_y="v"))["delta_pct"] is None
    zero_antes = pd.DataFrame({"year": [2021, 2022], "v": [0.0, 5.0]})
    assert kpi_trend(zero_antes, _w(kind="kpi", column="v", trend_x="year", trend_y="v"))["delta_pct"] is None


def test_validador_aponta_coluna_de_tendencia_inexistente():
    w = _w(kind="kpi", column="volume_t", agg="first", value=13.9e6, trend_x="ano_errado", trend_y="volume_t")
    issues = validate_widget_deterministic(w, {"D1": _ds("D1", SERIE)})
    assert any("trend_x='ano_errado'" in i.message for i in issues)


def test_kpi_mostra_numero_compacto_variacao_e_minisserie():
    html_out = _page([{"id": "k", "kind": "kpi", "title": "Volume, 2022", "dataset_id": "D1", "column": "volume_t",
                       "agg": "first", "unit": "t", "source": "Trase [D1]", "trend_x": "year", "trend_y": "volume_t"}],
                     [_ds("D1", SERIE)])
    assert "13,9 mi t" in html_out
    assert "11,2% <span class=\"delta-ref\">vs 2021" in html_out
    assert '<svg class="spark"' in html_out
    assert 'title="13.900.000 t"' in html_out  # valor exato preservado para leitura


def test_area_herda_as_checagens_de_line_e_progress_as_de_bar():
    area = _w(kind="area", x="year", y=["nao_existe"])
    prog = _w(kind="progress", x="municipality", y=["nao_existe"])
    assert validate_widget_deterministic(area, {"D1": _ds("D1", SERIE)})
    assert validate_widget_deterministic(prog, {"D1": _ds("D1", RANK)})


def test_area_empilhada_usa_stackgroup_e_parte_de_zero():
    df = pd.DataFrame({"year": [2021, 2021, 2022, 2022], "biome": ["A", "B", "A", "B"], "v": [1.0, 2.0, 3.0, 4.0]})
    fig = build_widget_figure(_w(kind="area", x="year", y=["v"], color="biome", stacked=True), df)
    assert {tr.stackgroup for tr in fig.data} == {"s"}
    assert fig.layout.yaxis.rangemode == "tozero"


def test_ranking_de_barras_ordena_do_maior_para_o_menor():
    fig = build_widget_figure(_w(kind="bar", x="municipality", y=["volume_t"], orientation="h"), RANK)
    assert list(fig.data[0].y)[-1] == "Rio Verde"  # horizontal: o maior fica no topo (H2: título)
    assert list(fig.data[0].text)[-1] == "1,63 mi"


def test_progress_calcula_participacao_e_explica_a_base():
    html_out = _page([{"id": "p", "kind": "progress", "title": "Destinos", "dataset_id": "D1",
                       "x": "country_of_first_import", "y": ["volume_t"], "unit": "t", "source": "Trase [D1]"}],
                     [_ds("D1", DEST)])
    assert "60,0%" in html_out and "30,0%" in html_out and "10,0%" in html_out
    assert "BRASIL (processamento doméstico)" in html_out
    assert "nas 3 linhas de [D1], não sobre o total geral" in html_out


def test_progress_usa_coluna_de_fracao_como_percentual():
    df = pd.DataFrame({"pais": ["A", "B"], "participacao": [0.75, 0.25]})
    html_out = _page([{"id": "p", "kind": "progress", "title": "P", "dataset_id": "D1", "x": "pais",
                       "y": ["participacao"], "unit": "%", "source": "Trase [D1]"}], [_ds("D1", df)])
    assert "75,0%" in html_out and "25,0%" in html_out and "não sobre o total geral" not in html_out


def test_tabela_html_com_barra_de_dados_e_rotulo_brasil():
    html_out = _page([{"id": "t", "kind": "table", "title": "Tabela", "dataset_id": "D1",
                       "columns": ["country_of_first_import", "volume_t"], "unit": "t", "source": "Trase [D1]"}],
                     [_ds("D1", DEST)])
    assert "<table>" in html_out and 'style="width:100.0%"' in html_out
    assert "BRASIL (processamento doméstico)" in html_out


def test_secoes_na_ordem_com_ancoras_e_sem_secao_vazia():
    html_out = _page([
        {"id": "t", "kind": "table", "title": "T", "dataset_id": "D1", "unit": "t", "source": "Trase [D1]"},
        {"id": "k", "kind": "kpi", "title": "K", "dataset_id": "D1", "column": "volume_t", "unit": "t",
         "source": "Trase [D1]"},
    ], [_ds("D1", SERIE)])
    assert html_out.index('id="visao-geral"') < html_out.index('id="detalhamento"')
    assert 'id="evolucao"' not in html_out and 'id="rankings"' not in html_out
    for alvo in re.findall(r'href="#([a-z-]+)"', html_out):
        assert f'id="{alvo}"' in html_out


def test_nenhum_recurso_externo_alem_do_plotly():
    widgets = [{"id": "l", "kind": "line", "title": "L", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
                "unit": "t", "source": "Trase [D1]"}]
    cdn = _page([dict(w) for w in widgets], [_ds("D1", SERIE)], plotlyjs="cdn")
    externos = re.findall(r'(?:src|href)="(https?://[^"]+)"', cdn)
    assert externos and all("cdn.plot.ly" in u for u in externos)
    inline = _page(widgets, [_ds("D1", SERIE)])  # padrão: Plotly embutido
    # O código-fonte do Plotly embutido contém textos com URLs; o que importa é a marcação da página.
    marcacao = re.sub(r"<script\b[^>]*>.*?</script>", "", inline, flags=re.S)
    assert "<script" not in marcacao and not re.findall(r'(?:src|href)="https?://', marcacao)
    assert '<script src="http' not in inline


@pytest.mark.parametrize("modo", ["inline", "cdn"])
def test_plotly_carrega_antes_de_todo_grafico_mesmo_com_barra_antes_da_linha(modo):
    """Regressão: com a barra antes da linha no JSON, o Plotly ia para a seção Rankings, que fica
    depois da Evolução na página; a linha era desenhada antes de o Plotly existir e ficava em branco."""
    widgets = [
        {"id": "b", "kind": "bar", "title": "B", "dataset_id": "D2", "x": "municipality", "y": ["volume_t"],
         "unit": "t", "source": "Trase [D2]"},
        {"id": "l", "kind": "line", "title": "L", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
         "unit": "t", "source": "Trase [D1]"},
    ]
    page = _page(widgets, [_ds("D1", SERIE), _ds("D2", RANK)], plotlyjs=modo)
    carga = [m.start() for m in re.finditer(r"cdn\.plot\.ly/|plotly\.js v\d", page)]
    desenhos = [m.start() for m in re.finditer(r"Plotly\.newPlot\(", page)]
    assert len(desenhos) == 2 and page.index('id="evolucao"') < page.index('id="rankings"')
    assert len(carga) >= 1 and page.index("</head>") > carga[0]
    assert all(pos > carga[0] for pos in desenhos)


def _serie_municipios(n_munis=5, anos=range(2020, 2023)):
    linhas = [{"year": a, "municipality": f"M{i}", "volume_t": float((i + 1) * 100 + (a - 2020))}
              for i in range(n_munis) for a in anos]
    # Ordem embaralhada por volume, como sai de um ORDER BY volume DESC.
    return pd.DataFrame(linhas).sort_values("volume_t", ascending=False)


def test_top_n_em_linha_com_color_limita_series_e_nao_linhas():
    """Regressão: top_n=3 cortava as 3 primeiras linhas da tabela (um único ano), e cada
    município ficava com um ponto só, deixando o gráfico praticamente vazio."""
    df = _serie_municipios()
    df.loc[(df.municipality == "M0") & (df.year == 2022), "volume_t"] = 9999.0  # maior só no último ano
    w = _w(kind="line", x="year", y=["volume_t"], color="municipality", top_n=3)
    fig = build_widget_figure(w, df)
    assert sorted(t.name for t in fig.data) == ["M0", "M3", "M4"]  # ranking pelo ano mais recente
    assert all(len(t.x) == 3 for t in fig.data)  # todos os anos de cada município


def test_top_n_em_linha_sem_color_mantem_periodos_mais_recentes():
    w = _w(kind="line", x="year", y=["volume_t"], top_n=2)
    fig = build_widget_figure(w, SERIE)
    assert sorted(fig.data[0].x) == [2021, 2022]


def test_pagina_sem_grafico_plotly_nao_carrega_plotly():
    page = _page([{"id": "t", "kind": "table", "title": "T", "dataset_id": "D1", "unit": "t",
                   "source": "Trase [D1]"}], [_ds("D1", SERIE)])
    assert "Plotly" not in page and "cdn.plot.ly" not in page


def test_texto_da_ia_e_escapado():
    html_out = _page([{"id": "t", "kind": "table", "title": "<script>alert(1)</script>", "dataset_id": "D1",
                       "unit": "t", "source": "Trase [D1]"}], [_ds("D1", SERIE)],
                     title="<img src=x onerror=alert(1)>")
    assert "<script>alert(1)</script>" not in html_out
    assert "<img src=x" not in html_out


def test_pagina_acessivel_e_com_tema():
    html_out = _page([{"id": "t", "kind": "table", "title": "T", "dataset_id": "D1", "unit": "t",
                       "source": "Trase [D1]"}], [_ds("D1", SERIE)], theme="dark")
    assert '<html lang="pt-BR" data-theme="dark">' in html_out
    assert 'name="viewport"' in html_out and 'aria-label="Seções do painel"' in html_out
    assert 'id="theme-toggle"' in html_out and "localStorage" in html_out
    assert "Dados: Trase (CC BY 4.0)" in html_out

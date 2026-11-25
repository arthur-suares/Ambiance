from src.dashboard import studio
from src.dashboard.schemas import DashboardSpec, WidgetSpec


def test_ranking_draws_from_sql_when_planner_returns_only_a_table(monkeypatch):
    monkeypatch.setattr(studio, "propose_dashboard_spec", lambda *args, **kwargs: (
        DashboardSpec("Painel", widgets=[WidgetSpec("table", "table", "Dados", "D1", "km²", "INPE")]),
        0, 0,
    ))
    rows = [
        {"municipio": "Altamira", "codigo_municipio_ibge": "1500602", "area_km2": 10.0},
        {"municipio": "São Félix do Xingu", "codigo_municipio_ibge": "1507300", "area_km2": 5.0},
    ]
    result = studio.build_studio_dashboard("Ranking de alertas", [
        {"label": "D1", "purpose": "Área de alertas", "columns": list(rows[0]), "rows": rows},
    ], plan_with_llm=True)
    chart = next(w for w in result["widgets"] if w["kind"] == "bar")
    assert (chart["x"], chart["y"], chart["unit"]) == ("municipio", ["area_km2"], "km²")
    assert result["tables"][0]["rows"] == rows


def test_chronological_chart_survives_provider_failure_and_retains_gaps(monkeypatch):
    def provider_error(*args, **kwargs):
        raise RuntimeError("indisponível")

    monkeypatch.setattr(studio, "propose_dashboard_spec", provider_error)
    rows = [{"ano": 2017, "volume_t": 10}, {"ano": 2018, "volume_t": None}, {"ano": 2019, "volume_t": 12}]
    result = studio.build_studio_dashboard("Série", [
        {"label": "D1", "purpose": "Volume", "columns": list(rows[0]), "rows": rows},
    ], plan_with_llm=True)
    chart = result["widgets"][0]
    assert (chart["kind"], chart["x"], chart["sort_by"], chart["ascending"]) == ("line", "ano", "ano", True)
    assert result["tables"][0]["rows"][1]["volume_t"] is None


def test_codes_are_not_used_as_chart_measures():
    rows = [{"municipio": "Altamira", "codigo_municipio_ibge": 1500602}]
    result = studio.build_studio_dashboard("Municípios", [
        {"label": "D1", "purpose": "Identificação", "columns": list(rows[0]), "rows": rows},
    ], plan_with_llm=False)
    assert result["widgets"] == []


def test_grouped_color_widget_is_preserved_and_long_series_fallback_works():
    rows = [
        {"ano": 2022, "produto": "Soja", "exportacao_t": 100.0},
        {"ano": 2023, "produto": "Soja", "exportacao_t": 120.0},
        {"ano": 2022, "produto": "Bovinos", "exportacao_t": 30.0},
        {"ano": 2023, "produto": "Bovinos", "exportacao_t": 40.0},
    ]
    result = studio.build_studio_dashboard("Exportações por produto", [
        {"label": "D1", "purpose": "Exportações", "columns": list(rows[0]), "rows": rows},
    ], plan_with_llm=False)
    chart = result["widgets"][0]
    assert (chart["kind"], chart["x"], chart["y"], chart["color"]) == ("line", "ano", ["exportacao_t"], "produto")


def test_wide_multi_column_fallback_includes_all_matching_series():
    rows = [
        {"ano": 2022, "soja_t": 25000000, "bovinos_t": 500000},
        {"ano": 2023, "soja_t": 28000000, "bovinos_t": 550000},
    ]
    result = studio.build_studio_dashboard("Exportações MT", [
        {"label": "D1", "purpose": "Exportações", "columns": list(rows[0]), "rows": rows},
    ], plan_with_llm=False)
    chart = result["widgets"][0]
    assert (chart["kind"], chart["x"], chart["y"], chart["unit"]) == ("line", "ano", ["soja_t", "bovinos_t"], "t")


def test_temporal_tables_omit_empty_coverage_and_single_territory_ranking():
    evidence = {
        "label": "Produção de soja",
        "unit": "t",
        "source": "IBGE PAM",
        "scope": "Sorriso",
        "method_url": "/metodologia#ibge_soja_producao_t",
        "frames": [
            {"period": "2024", "value": 2100000, "areas": [{"code": "5107925", "name": "Sorriso", "value": 2100000}]},
            {"period": "2025", "value": 2343000, "areas": [{"code": "5107925", "name": "Sorriso", "value": 2343000}]},
        ],
        "facts": [],
    }
    result = studio.build_studio_dashboard("Sorriso", [], evidence, plan_with_llm=False)
    assert [t["label"] for t in result["tables"]] == ["T1"]
    assert result["tables"][0]["columns"] == ["periodo", "valor"]


def test_studio_dashboard_skips_llm_by_default_and_for_temporal_evidence(monkeypatch):
    calls = []
    monkeypatch.setattr(studio, "propose_dashboard_spec", lambda *args, **kwargs: calls.append(args))

    rows = [{"ano": 2024, "area_km2": 10.0}, {"ano": 2025, "area_km2": 12.0}]
    res_default = studio.build_studio_dashboard("SQL", [
        {"label": "D1", "purpose": "Alertas", "columns": ["ano", "area_km2"], "rows": rows},
    ])
    assert res_default["widgets"]
    assert calls == []

    evidence = {
        "label": "Produção de soja",
        "unit": "t",
        "source": "IBGE PAM",
        "scope": "MT",
        "method_url": "/metodologia#ibge_soja_producao_t",
        "frames": [
            {"period": "2024", "value": 100, "areas": []},
            {"period": "2025", "value": 120, "areas": []},
        ],
        "facts": [],
    }
    res_temporal = studio.build_studio_dashboard("Evolução", [], evidence, plan_with_llm=True)
    assert res_temporal["widgets"]
    assert calls == []

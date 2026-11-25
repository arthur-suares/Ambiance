import pytest

from src import temporal
from src.dashboard.studio import build_studio_dashboard


def test_flow_timeline_keeps_a_missing_year_in_map_and_dashboard(monkeypatch):
    calls = []

    def read_flow(product, year, **kwargs):
        calls.append((product, year, kwargs["strict_year"]))
        return {"arcs": [], "total": {2017: 200, 2019: 250}.get(year)}

    monkeypatch.setattr(temporal, "get_flows", read_flow)
    evidence = temporal.get_temporal({"metric": "flows_bovinos", "start_year": 2017, "end_year": 2019})
    dashboard = build_studio_dashboard("Fluxos", [], evidence, plan_with_llm=False)

    assert calls == [("bovinos", year, True) for year in (2017, 2018, 2019)]
    assert [f["value"] for f in evidence["frames"]] == [200, None, 250]
    assert [r["valor"] for r in dashboard["tables"][0]["rows"]] == [200, None, 250]
    assert dashboard["widgets"][0]["dataset_id"] == "T1"


def test_milestones_compute_changes_from_observed_frames():
    facts = temporal._facts([
        {"period": "2022", "value": 90},
        {"period": "2023", "value": 100},
        {"period": "2024", "value": 86},
        {"period": "2025", "value": 120},
    ])
    decline = next(f for f in facts if f.get("change_pct", 0) < 0)
    assert (decline["baseline_period"], decline["period"], decline["change_pct"]) == ("2023", "2024", -14)


def test_monthly_scope_is_only_supported_for_alerts():
    with pytest.raises(ValueError, match="Frequência|frequência"):
        temporal.get_temporal({"metric": "ibge_soja_producao_t", "frequency": "monthly",
                               "start_year": 2025, "end_year": 2025})

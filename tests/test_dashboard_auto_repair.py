"""Consertos automáticos do painel: o que é mecânico é corrigido em vez de esconder o componente."""

import pandas as pd

from src.dashboard.renderer import _promote_single_value
from src.dashboard.reviewer_agent import auto_repair_spec, validate_widget_deterministic
from src.dashboard.schemas import DashboardSpec, DatasetResult, WidgetSpec


def _ds(did, df):
    return DatasetResult(dataset_id=did, database="trase.duckdb", source_label="Trase", tool_name="run_sql",
                         query_summary="SELECT ...", df=df)


def test_fonte_citando_outro_dataset_e_corrigida_e_grafico_fica_valido():
    d6 = _ds("D6", pd.DataFrame({"year": [2020, 2021, 2022], "value": [1.0, 2.0, 3.0]}))
    w = WidgetSpec(id="w6", kind="bar", title="Evolução", dataset_id="D6", unit="t",
                   source="Trase — Cadeia da carne bovina [D7]", x="year", y=["value"])
    spec = DashboardSpec(title="t", widgets=[w])
    fixes = auto_repair_spec(spec, [d6])
    assert w.source == "Trase — Cadeia da carne bovina [D6]"
    assert fixes
    assert not [i for i in validate_widget_deterministic(w, {"D6": d6}) if "identificador" in i.message]


def test_fonte_sem_trase_recebe_prefixo():
    d1 = _ds("D1", pd.DataFrame({"uf": ["GO", "MT"], "v": [1.0, 2.0]}))
    w = WidgetSpec(id="w1", kind="bar", title="x", dataset_id="D1", unit="t", source="Cadeia da soja [D1]",
                   x="uf", y=["v"])
    auto_repair_spec(DashboardSpec(title="t", widgets=[w]), [d1])
    assert "trase" in w.source.lower() and "[D1]" in w.source


def test_kpi_com_agg_errada_troca_para_a_que_bate_com_o_valor_escrito():
    # série até 2023, mas o KPI é o valor de 2022 (o maior da série)
    df = pd.DataFrame({"year": [2021, 2022, 2023], "cattle_production_t": [1.0e6, 1.5e6, 1.3e6]})
    d7 = _ds("D7", df)
    w = WidgetSpec(id="kpi1", kind="kpi", title="Produção 2022", dataset_id="D7", unit="t",
                   source="Trase [D7]", column="cattle_production_t", agg="last", value=1.5e6)
    auto_repair_spec(DashboardSpec(title="t", widgets=[w]), [d7])
    assert w.agg == "max"
    assert not [i for i in validate_widget_deterministic(w, {"D7": d7}) if i.code == "kpi_valor"]


def test_kpi_que_nao_bate_com_nenhuma_agg_continua_bloqueado():
    d1 = _ds("D1", pd.DataFrame({"v": [10.0, 20.0, 30.0]}))
    w = WidgetSpec(id="k", kind="kpi", title="x", dataset_id="D1", unit="%", source="Trase [D1]",
                   column="v", agg="max", value=9.57)
    auto_repair_spec(DashboardSpec(title="t", widgets=[w]), [d1])
    assert w.agg == "max"
    assert [i for i in validate_widget_deterministic(w, {"D1": d1}) if i.code == "kpi_valor"]


def test_grafico_de_valor_unico_vira_kpi():
    d4 = _ds("D4", pd.DataFrame({"state_total_t": [1117424.3]}))
    w = WidgetSpec(id="w", kind="bar", title="Total", dataset_id="D4", unit="t", source="Trase [D4]",
                   x="uf", y=["state_total_t"])
    out = _promote_single_value(w, {"D4": d4})
    assert out.kind == "kpi" and out.column == "state_total_t" and out.valid


def test_kpi_de_uma_entidade_numa_tabela_de_varios_estados_le_a_linha_certa():
    from src.dashboard.renderer import _render_kpi_card

    df = pd.DataFrame({"region": ["MT", "GO", "PA"], "value": [3.2e6, 1117424.3, 0.5e6]})
    d2 = _ds("D2", df)
    w = WidgetSpec(id="kpi1", kind="kpi", title="Produção de Goiás", dataset_id="D2", unit="t",
                   source="Trase [D2]", column="value", agg="max", value=1117420.0)
    auto_repair_spec(DashboardSpec(title="t", widgets=[w]), [d2])
    assert w.match == {"region": "GO"} and w.agg == "first"
    assert not [i for i in validate_widget_deterministic(w, {"D2": d2}) if i.code == "kpi_valor"]
    assert "1,12" in _render_kpi_card(w, df)  # mostra o número de Goiás, não o máximo


def test_kpi_de_entidade_e_ano_filtra_os_dois_e_mantem_a_serie():
    df = pd.DataFrame({"state": ["GO", "GO", "MT", "MT"], "year": [2021, 2022, 2021, 2022],
                       "v": [10.0, 12.0, 30.0, 33.0]})
    d1 = _ds("D1", df)
    w = WidgetSpec(id="k", kind="kpi", title="GO 2022", dataset_id="D1", unit="t", source="Trase [D1]",
                   column="v", agg="max", value=12.0, trend_x="year", trend_y="v")
    auto_repair_spec(DashboardSpec(title="t", widgets=[w]), [d1])
    assert w.match == {"state": "GO", "year": "2022"}
    from src.dashboard.renderer import kpi_trend
    from src.dashboard.schemas import kpi_frame
    trend = kpi_trend(kpi_frame(df, w, keep_time=True), w)
    assert trend and trend["ys"] == [10.0, 12.0]


def test_kpi_com_serie_sem_coluna_de_tempo_ganha_o_ano_do_dataset():
    d1 = _ds("D1", pd.DataFrame({"year": [2021, 2022], "v": [1.0, 2.0]}))
    w = WidgetSpec(id="k", kind="kpi", title="x", dataset_id="D1", unit="t", source="Trase [D1]",
                   column="v", agg="last", value=2.0, trend_y="v")
    auto_repair_spec(DashboardSpec(title="t", widgets=[w]), [d1])
    assert w.trend_x == "year"
    assert not [i for i in validate_widget_deterministic(w, {"D1": d1}) if i.blocking]


def test_kpi_com_serie_impossivel_perde_a_serie_e_nao_bloqueia():
    d1 = _ds("D1", pd.DataFrame({"uf": ["GO"], "v": [2.0]}))
    w = WidgetSpec(id="k", kind="kpi", title="x", dataset_id="D1", unit="t", source="Trase [D1]",
                   column="v", agg="first", value=2.0, trend_y="v")
    auto_repair_spec(DashboardSpec(title="t", widgets=[w]), [d1])
    assert w.trend_x is None and w.trend_y is None
    assert not [i for i in validate_widget_deterministic(w, {"D1": d1}) if i.blocking]


def test_mudar_o_visual_invalida_o_cache_do_painel(monkeypatch):
    import src.dashboard.cache as cache
    k1 = cache.dashboard_cache_key("Pergunta X", None)
    monkeypatch.setattr(cache, "RENDER_VERSION", "outra-versao")
    assert cache.dashboard_cache_key("Pergunta X", None) != k1


def test_minisserie_com_dois_pontos_nao_e_desenhada():
    from src.dashboard.renderer import _sparkline_svg
    assert _sparkline_svg([1.0, 2.0], "u", "x") == ""
    assert _sparkline_svg([1.0, 2.0, 3.0], "u", "x").startswith('<svg class="spark"')

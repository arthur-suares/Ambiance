"""Checagem estruturada dos valores (eval/metrics.py) e legenda dos resultados (src/result_meta.py)."""

import pandas as pd
import pytest

from eval.metrics import find_in_table, find_value, find_value_with_unit, item_scope, parse_tool_table
from eval.run_eval import check_values
from src import result_meta as rm

LEGEND = "# cadeia: {cadeia} | escopo: fluxos da cadeia\n# filtros: {filtros}\n"


def data_item(cid, tool, call, text, cadeia):
    return {"id": cid, "tipo": "dados", "ok": True, "ferramenta": tool, "cadeia": cadeia, "chamada": call, "texto": text}


def gold(valor, cadeia, escopo, metrica, termos=(), ano=None, unidade="ha", tol=0.01):
    return {"descricao": "x", "valor": valor, "unidade": unidade, "tolerancia_rel": tol, "cadeia": cadeia,
            "escopo": escopo, "metrica": metrica, "termos": list(termos), "ano": ano}


SOY_PRODUCTION = data_item(
    "D1", "soy_territorial_metric", 'soy_territorial_metric({"metric": "soy_production_t", "region": "MATO GROSSO"})',
    "# cadeia: soja | escopo: indicador territorial\n# ano: 2024\n"
    "year,level,region,parent_region,metric,value,unit\n2024,state,MATO GROSSO,CENTRO-OESTE,soy_production_t,38396400.0,t\n(1 linhas)",
    "soja")
BEEF_TREND = data_item(
    "D2", "yearly_trend", 'yearly_trend({"state": "MATO GROSSO"})',
    LEGEND.format(cadeia="carne bovina", filtros="state = MATO GROSSO")
    + "year,volume_t,volume_exported_t,fob_usd,deforestation_exposure_ha,co2_net_tco2e\n"
      "2022,627862.0,627862.0,2652190000.0,196154.0,38418300.0\n"
      "2023,575760.0,575760.0,2283850000.0,179559.0,35265900.0\n(2 linhas)",
    "carne")
PRODUCTION_MT = gold(38396410.0, "soja", "territorial", "producao", ["MATO GROSSO|MT"], unidade="t")
EXPOSURE_MT_2023 = gold(179559.4804, "carne", "fluxos", "exposicao", ["MATO GROSSO|MT"], 2023)


def test_parse_tool_table_skips_legend_and_footer():
    header, rows, legend = parse_tool_table(BEEF_TREND["texto"])
    assert header[0] == "year" and len(rows) == 2 and rows[1][0] == "2023"
    assert legend.startswith("# cadeia: carne bovina")


def test_number_from_another_chain_and_metric_is_rejected():
    """Caso M02: emissões da carne (38.418.300 tCO2e) ficam a 0,06% da produção de soja do MT (38.396.410 t)."""
    assert find_value(38396410.0, 0.01, BEEF_TREND["texto"], csv=True)  # o critério solto aceita
    found, rejected = find_in_table(PRODUCTION_MT, BEEF_TREND)
    assert found is None
    assert rejected and "cadeia carne, esperada soja" in rejected[0]
    found, rejected = find_in_table(PRODUCTION_MT, SOY_PRODUCTION)
    assert found["coluna"] == "value" and not rejected


def test_value_needs_the_right_column_row_and_year():
    found, _ = find_in_table(EXPOSURE_MT_2023, BEEF_TREND)
    assert found["coluna"] == "deforestation_exposure_ha" and found["lido"] == 179559.0
    # mesmo número, mas pedido para 2022: a linha é de 2023
    found, rejected = find_in_table({**EXPOSURE_MT_2023, "ano": 2022}, BEEF_TREND)
    assert found is None and "linha do ano 2023" in rejected[0]
    # mesmo número numa coluna de volume não é exposição
    wrong_column = {**BEEF_TREND, "texto": "year,volume_t\n2023,179559.0\n(1 linhas)"}
    found, rejected = find_in_table(EXPOSURE_MT_2023, wrong_column)
    assert found is None and "não é da métrica exposicao" in rejected[0]
    # outra UF no filtro
    other_state = {**BEEF_TREND, "chamada": 'yearly_trend({"state": "PARA"})',
                   "texto": BEEF_TREND["texto"].replace("MATO GROSSO", "PARA")}
    found, rejected = find_in_table(EXPOSURE_MT_2023, other_state)
    assert found is None and "sem 'MATO GROSSO|MT'" in rejected[0]


def test_emissions_column_is_not_exposure_even_with_exposure_in_its_name():
    item = data_item("D1", "run_sql", "SELECT year, SUM(co2_net_emissions_cattle_deforestation_5_year_total_exposure) "
                     "FROM supply_chain WHERE year = 2023 GROUP BY 1",
                     "year,sum(co2_net_emissions_cattle_deforestation_5_year_total_exposure)\n2023,179559.0\n(1 linhas)", "carne")
    found, rejected = find_in_table({**EXPOSURE_MT_2023, "termos": []}, item)
    assert found is None and "outra métrica" in rejected[0]


def test_free_sql_with_any_alias_is_accepted_when_the_query_reads_the_metric():
    item = data_item("D1", "run_sql", "SELECT SUM(deforestation_exposure_ha) AS total FROM flows_by_municipality "
                     "WHERE year = 2023 AND state_of_production = 'MATO GROSSO'", "total\n179559.0\n(1 linhas)", "carne")
    found, _ = find_in_table(EXPOSURE_MT_2023, item)
    assert found["coluna"] == "total"


def test_scope_territorial_is_not_flows():
    territorial = data_item("D1", "territorial_metric", 'territorial_metric({"metric": "cattle_deforestation_ha"})',
                            "year,level,region,parent_region,metric,value,unit\n"
                            "2023,state,MATO GROSSO,CENTRO-OESTE,cattle_deforestation_ha,179559.0,ha\n(1 linhas)", "carne")
    assert item_scope(territorial) == "territorial" and item_scope(BEEF_TREND) == "fluxos"
    found, rejected = find_in_table(EXPOSURE_MT_2023, territorial)
    assert found is None and "escopo territorial, esperado fluxos" in rejected[0]


def test_old_runs_without_tool_fields_are_read_from_the_description():
    old = {"id": "D2", "tipo": "dados", "ok": True, "chamada": BEEF_TREND["chamada"],
           "descricao": "dados da cadeia da carne bovina – yearly_trend: " + BEEF_TREND["chamada"],
           "texto": BEEF_TREND["texto"].split("\n", 2)[2]}  # sem legenda, como nas rodadas antigas
    assert find_in_table(EXPOSURE_MT_2023, old)[0]
    assert find_in_table(PRODUCTION_MT, old)[0] is None


@pytest.mark.parametrize("text, unit, expected", [
    ("a exposição foi de **277,6 mil ha** em 2023", "ha", True),
    ("cerca de 277.583 hectares", "ha", True),
    ("exportou 277,6 mil toneladas", "ha", False),
    ("| Grupo | Exposição (ha) |\n|---|---|\n| JBS | 277.582,68 |", "ha", True),
    ("| Grupo | Volume (t) |\n|---|---|\n| JBS | 277.582,68 |", "ha", False),
    ("Exposição ao desmatamento (ha): 277.582,68", "ha", True),
])
def test_answer_number_needs_its_unit(text, unit, expected):
    assert bool(find_value_with_unit(277582.6811, 0.01, text, unit, loose=True)) is expected


def test_units_in_running_text():
    assert find_value_with_unit(5000, 0, "multa de R$ 5.000,00 por hectare ou fração", "R$/ha")
    assert find_value_with_unit(5000, 0, "foram 5.000 hectares", "R$/ha") is None
    assert find_value_with_unit(20, 0, "o art. 20 trata de outro assunto", "%") is None
    assert find_value_with_unit(20, 0, "20% (vinte por cento) nas demais regiões", "%")
    assert find_value_with_unit(121118342.12, 0.01, "emitiu 121,1 milhões de tCO₂e", "tCO2e")
    assert find_value_with_unit(121118342.12, 0.01, "emitiu 121,1 milhões de tCO₂e", "t") is None  # toneladas de soja
    assert find_value_with_unit(56700, 0.01, "capacidade de 56.700 t/dia", "t/dia")
    assert find_value_with_unit(56700, 0.01, "capacidade de 56.700 t/dia", "t") is None
    assert find_value_with_unit(13527267.5, 0.01, "exportou 13,53 milhões de toneladas", "t")


def test_check_values_reports_both_criteria():
    item = {"valores": [PRODUCTION_MT, EXPOSURE_MT_2023,
                        {"descricao": "RL", "valor": 80.0, "unidade": "%", "tolerancia_rel": 0, "cadeia": "lei",
                         "escopo": None, "metrica": None, "termos": [], "ano": None}]}
    law = {"id": "L1", "tipo": "lei", "texto": "I - 80% (oitenta por cento), no imóvel situado em área de florestas"}
    answer = "A exposição foi de 179,6 mil ha [D2] e a reserva legal é de 80% [L1]. Produção: sem dado."
    out = check_values(item, answer, [BEEF_TREND, law])  # a consulta da produção de soja não foi feita
    by = {v["valor"]: v for v in out["valores"]}
    assert by[38396410.0]["no_contexto"] == [] and by[38396410.0]["no_contexto_solto"] == ["D2"]
    assert by[38396410.0]["rejeitados_no_contexto"]
    assert by[179559.4804]["no_contexto"] == ["D2"] and by[80.0]["no_contexto"] == ["L1"]
    assert out["valor_recuperado"] == pytest.approx(2 / 3) and out["valor_recuperado_solto"] == 1.0
    assert out["acerto_valores"] == pytest.approx(2 / 3)


# ----------------------------------------------------------------------------- legenda dos resultados

def test_legend_is_rendered_before_the_csv_and_can_be_stripped():
    from src.agent import df_to_text
    df = rm.attach(pd.DataFrame({"exporter_group": ["CARGILL"], "volume_tonnes": [13527267.5]}), cadeia="soja",
                   escopo=rm.FLOWS, ano=2022, agrupado_por="grupo econômico exportador (exporter_group)",
                   ordenado_por="volume_tonnes (maior primeiro), 1 primeiras linhas", excluidos=["PROCESSED DOMESTICALLY"],
                   unidades={"volume_tonnes": "t"}, notas=[rm.RANKING_NOTE])
    text = df_to_text(df)
    assert text.splitlines()[0].startswith("# cadeia: soja | escopo: fluxos da cadeia")
    for expected in ("# ano: 2022", "# agrupado por: grupo econômico", "# ordenado por: volume_tonnes",
                     "# excluídos do resultado: PROCESSED DOMESTICALLY", "# unidades: volume_tonnes = t"):
        assert expected in text
    assert rm.strip_meta(text).splitlines()[0] == "exporter_group,volume_tonnes"
    assert parse_tool_table(text)[0] == ["exporter_group", "volume_tonnes"]


def test_ranking_tools_require_an_explicit_order():
    from src.agent import REQUIRED_ARGS, _check_required
    for name in ("top_exporters", "top_municipalities", "soy_top_exporters", "soy_top_municipalities",
                 "soy_facilities_summary"):
        assert "order_by" in REQUIRED_ARGS[name]
    with pytest.raises(ValueError, match="informe order_by"):
        _check_required("soy_top_exporters", {"year": 2022})
    _check_required("soy_top_exporters", {"year": 2022, "order_by": "volume_tonnes"})
    _check_required("soy_yearly_trend", {})

from __future__ import annotations

from types import SimpleNamespace
import sys

import duckdb
import pandas as pd
import pytest

import src.config as config_mod
from src.dashboard import (
    ALLOWED_WIDGET_KINDS,
    MAX_REVISIONS,
    MAX_ROWS_TO_LLM,
    DatasetResult,
    generate_dashboard,
)
import src.dashboard.data_agent as data_agent_mod
import src.dashboard.orchestrator as orchestrator_mod
from src.dashboard.renderer import render_dashboard_html
from src.dashboard.reviewer_agent import review_dashboard
from src.dashboard.schemas import format_dataset_for_llm, parse_dashboard_spec
import src.database as database_mod


# --- Helpers para simular a API Messages da Anthropic sem rede -------------------

def _usage(inp: int = 100, out: int = 50):
    return SimpleNamespace(input_tokens=inp, output_tokens=out)


def _tool_response(name: str, payload: dict, tool_id: str = "toolu_1"):
    return SimpleNamespace(
        stop_reason="tool_use",
        usage=_usage(),
        content=[SimpleNamespace(type="tool_use", id=tool_id, name=name, input=payload)],
    )


def _multi_tool_response(calls: list[tuple[str, dict]]):
    return SimpleNamespace(
        stop_reason="tool_use",
        usage=_usage(),
        content=[
            SimpleNamespace(type="tool_use", id=f"toolu_{i}", name=n, input=inp)
            for i, (n, inp) in enumerate(calls, 1)
        ],
    )


def _text_response(text: str):
    return SimpleNamespace(
        stop_reason="end_turn",
        usage=_usage(),
        content=[SimpleNamespace(type="text", text=text)],
    )


class FakeAnthropicClient:
    """Cliente simulado com fila determinística de respostas."""

    def __init__(self, responses: list):
        self._queue = list(responses)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._queue:
            raise AssertionError("Fila de respostas simuladas do LLM esgotou inesperadamente.")
        nxt = self._queue.pop(0)
        if callable(nxt):
            return nxt(kwargs)
        return nxt


@pytest.fixture
def sample_datasets() -> list[DatasetResult]:
    df_rank = pd.DataFrame({
        "year": [2023, 2023, 2023],
        "municipality": ["SAO FELIX DO XINGU", "ALTAMIRA", "NOVO REPARTIMENTO"],
        "deforestation_exposure_ha": [45000.0, 32000.0, 21000.0],
        "volume_t": [90000.0, 75000.0, 50000.0],
    })
    df_trend = pd.DataFrame({
        "year": [2021, 2022, 2023],
        "volume_t": [200000.0, 220000.0, 250000.0],
        "deforestation_exposure_ha": [95000.0, 102000.0, 98000.0],
    })
    return [
        DatasetResult(
            dataset_id="D1",
            database="trase.duckdb",
            source_label="Trase — Cadeia da carne bovina (trase.duckdb)",
            tool_name="top_municipalities",
            query_summary='top_municipalities({"state": "PARA", "year": 2023})',
            df=df_rank,
            purpose="Ranking municipal no Pará em 2023",
        ),
        DatasetResult(
            dataset_id="D2",
            database="trase.duckdb",
            source_label="Trase — Cadeia da carne bovina (trase.duckdb)",
            tool_name="yearly_trend",
            query_summary='yearly_trend({"state": "PARA"})',
            df=df_trend,
            purpose="Série anual no Pará",
        ),
    ]


@pytest.fixture
def temp_beef_duckdb(tmp_path, monkeypatch):
    db_path = tmp_path / "trase.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        rows = [
            (2023, "AMAZONIA", "PARA", f"MUNI_{i:03d}", "JBS", "CHINA", 1000.0 + i, 5000.0 + i, 100.0 + i)
            for i in range(1, 86)
        ]
        con.execute("""
            CREATE TABLE supply_chain (
                year INTEGER,
                biome VARCHAR,
                state_of_production VARCHAR,
                municipality_of_production VARCHAR,
                exporter_group VARCHAR,
                country_of_destination VARCHAR,
                volume DOUBLE,
                fob DOUBLE,
                cattle_deforestation_5_year_total_exposure DOUBLE
            )
        """)
        con.executemany("INSERT INTO supply_chain VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    finally:
        con.close()

    monkeypatch.setattr(config_mod, "DUCKDB_PATH", db_path)
    monkeypatch.setattr(database_mod, "DUCKDB_PATH", db_path)
    monkeypatch.setattr(data_agent_mod, "DUCKDB_PATH", db_path)
    monkeypatch.setattr(orchestrator_mod, "DUCKDB_PATH", db_path)
    return db_path


# --- Testes de contratos, truncamento e isolamento de erros ----------------------

def test_supported_widget_kinds_exclude_map():
    assert ALLOWED_WIDGET_KINDS == ("kpi", "bar", "line", "table")
    spec = parse_dashboard_spec({
        "title": "Painel Teste",
        "subtitle": "Subtítulo",
        "widgets": [
            {
                "id": "w_map",
                "kind": "map",
                "title": "Mapa ainda não suportado",
                "dataset_id": "D1",
                "unit": "ha",
                "source": "Trase [D1]",
            },
            {
                "id": "w_bar",
                "kind": "bar",
                "title": "Ranking válido",
                "dataset_id": "D1",
                "x": "municipality",
                "y": ["deforestation_exposure_ha"],
                "unit": "ha",
                "source": "Trase [D1]",
            },
        ],
    })
    assert len(spec.widgets) == 2
    assert spec.widgets[0].valid is False
    assert "map" in (spec.widgets[0].validation_error or "")
    assert spec.widgets[1].valid is True


def test_dataset_prompt_truncates_at_60_rows():
    assert MAX_ROWS_TO_LLM == 60
    big_df = pd.DataFrame({"idx": list(range(100)), "val": [float(i) for i in range(100)]})
    ds = DatasetResult(
        dataset_id="D1",
        database="trase.duckdb",
        source_label="Trase — Carne bovina",
        tool_name="run_sql",
        query_summary="SELECT idx, val FROM t",
        df=big_df,
    )
    prompt_text = format_dataset_for_llm(ds)
    assert f"truncado em {MAX_ROWS_TO_LLM} de 100 linhas" in prompt_text
    assert "59,59.0" in prompt_text
    assert "60,60.0" not in prompt_text
    assert len(ds.df) == 100


# --- Testes do Agente Revisor (determinístico primeiro, LLM só metodológico) -----

def test_reviewer_catches_deterministic_errors_without_calling_llm(monkeypatch, sample_datasets):
    def _forbid_llm():
        raise AssertionError("O LLM NÃO deveria ser chamado quando há erros determinísticos!")

    monkeypatch.setattr("src.dashboard._llm.get_client", _forbid_llm)

    bad_spec = parse_dashboard_spec({
        "title": "Painel com erros determinísticos",
        "subtitle": "",
        "widgets": [
            {
                "id": "kpi_errado",
                "kind": "kpi",
                "title": "Maior exposição municipal (2023)",
                "dataset_id": "D1",
                "column": "deforestation_exposure_ha",
                "agg": "first",
                "value": 999999.0,  # não bate com 45000.0
                "unit": "ha",
                "source": "Trase [D1]",
            },
            {
                "id": "bar_sem_fonte_e_coluna",
                "kind": "bar",
                "title": "",
                "dataset_id": "D1",
                "x": "municipality",
                "y": ["coluna_inexistente"],
                "unit": "",
                "source": " IBGE ",  # sem Trase e sem [D1]
            },
        ],
    })

    review = review_dashboard("Pergunta teste", bad_spec, sample_datasets)
    assert review.approved is False
    assert review.llm_called is False
    messages = " | ".join(i.message for i in review.issues)
    assert "diverge do resultado SQL" in messages
    assert "Título ausente" in messages
    assert "Unidade ausente" in messages
    assert "Trase" in messages
    assert "coluna_inexistente" in messages


def test_reviewer_calls_llm_only_after_deterministic_passes(monkeypatch, sample_datasets):
    fake_client = FakeAnthropicClient([
        _tool_response("emit_review", {
            "approved": False,
            "summary": "Incoerência semântica entre título e coluna.",
            "issues": [{
                "widget_id": "kpi_semantica",
                "message": "O título fala em receita financeira, mas a coluna plotada é volume_t.",
            }],
        })
    ])
    monkeypatch.setattr("src.dashboard._llm.get_client", lambda: fake_client)

    # Estruturalmente, aritmeticamente e nas regras determinísticas válido (soma de volume = 670000),
    # mas semanticamente incoerente (título fala em dólares, coluna é volume_t).
    spec = parse_dashboard_spec({
        "title": "Comércio no Pará",
        "subtitle": "2021-2023",
        "widgets": [{
            "id": "kpi_semantica",
            "kind": "kpi",
            "title": "Faturamento em dólares acumulado 2021-2023",
            "dataset_id": "D2",
            "column": "volume_t",
            "agg": "sum",
            "value": 670000.0,
            "unit": "t",
            "source": "Trase — Carne bovina [D2]",
        }],
    })

    review = review_dashboard("Evolução no Pará", spec, sample_datasets)
    assert review.llm_called is True
    assert review.approved is False
    assert len(fake_client.calls) == 1
    assert review.issues[0].widget_id == "kpi_semantica"
    assert review.issues[0].check_type == "methodological"


# --- Teste do Agente de Dados + Guardrails read-only no DuckDB -------------------

def test_data_agent_enforces_readonly_guardrails_and_returns_full_df(monkeypatch, temp_beef_duckdb):
    fake_client = FakeAnthropicClient([
        # Rodada 1: tenta DDL proibido e uma consulta SELECT válida com 85 linhas
        _multi_tool_response([
            ("run_sql", {"sql": "DROP TABLE supply_chain", "purpose": "tentativa inválida"}),
            ("run_sql", {
                "sql": "SELECT municipality_of_production, volume FROM supply_chain WHERE year = 2023 ORDER BY volume DESC",
                "purpose": "Todos os 85 municípios",
            }),
        ]),
        # Rodada 2: encerra após receber resultados
        _text_response("Dados coletados em [D1]."),
    ])
    monkeypatch.setattr("src.dashboard.data_agent.get_client", lambda: fake_client)
    monkeypatch.setattr("src.soy.queries.is_available", lambda: False)
    monkeypatch.setattr("src.queries.latest_year", lambda: 2023)

    plan = orchestrator_mod.OrchestratorPlan(
        question="Municípios do Pará em 2023",
        domain="beef",
        dashboard_goal="Listar volume por município",
    )
    res = data_agent_mod.run_data_agent("Municípios do Pará em 2023", plan)

    assert len(res.tool_calls) == 2
    assert res.tool_calls[0].ok is False
    assert "SELECT" in res.tool_calls[0].output
    assert res.tool_calls[1].ok is True
    assert f"truncado em {MAX_ROWS_TO_LLM} de 85 linhas" in res.tool_calls[1].output

    # O DataFrame retornado em memória preserva todas as 85 linhas (não truncado em 60)
    assert len(res.datasets) == 1
    assert res.datasets[0].dataset_id == "D1"
    assert len(res.datasets[0].df) == 85


# --- Teste do Renderizador Plotly (kpi, bar, line, table + aviso parcial) --------

def test_renderer_renders_all_4_types_and_shows_warning_for_invalid_chart(sample_datasets):
    spec = parse_dashboard_spec({
        "title": "Carne Bovina no Pará (2021–2023)",
        "subtitle": "Fluxos rastreados da cadeia",
        "widgets": [
            {
                "id": "w_kpi",
                "kind": "kpi",
                "title": "Líder municipal em exposição (2023)",
                "subtitle": "São Félix do Xingu — origem rastreada",
                "dataset_id": "D1",
                "column": "deforestation_exposure_ha",
                "agg": "first",
                "value": 45000.0,
                "unit": "ha",
                "source": "Trase — Carne bovina [D1]",
            },
            {
                "id": "w_bar",
                "kind": "bar",
                "title": "Top municípios em exposição (2023)",
                "dataset_id": "D1",
                "x": "municipality",
                "y": ["deforestation_exposure_ha"],
                "orientation": "h",
                "unit": "ha",
                "source": "Trase — Carne bovina [D1]",
            },
            {
                "id": "w_line",
                "kind": "line",
                "title": "Evolução anual do volume (2021–2023)",
                "dataset_id": "D2",
                "x": "year",
                "y": ["volume_t"],
                "unit": "t",
                "source": "Trase — Carne bovina [D2]",
            },
            {
                "id": "w_table",
                "kind": "table",
                "title": "Detalhamento por município (2023)",
                "dataset_id": "D1",
                "columns": ["municipality", "volume_t", "deforestation_exposure_ha"],
                "column_labels": {"municipality": "Município", "volume_t": "Volume (t)"},
                "unit": "t / ha",
                "source": "Trase — Carne bovina [D1]",
            },
            {
                "id": "w_quebrado",
                "kind": "bar",
                "title": "Gráfico com coluna errada",
                "dataset_id": "D1",
                "x": "municipality",
                "y": ["nao_existe"],
                "unit": "ha",
                "source": "Trase — Carne bovina [D1]",
            },
        ],
    })

    html_out = render_dashboard_html(spec, sample_datasets, question="Como está o Pará?")
    assert "<!doctype html>" in html_out.lower()
    for wid, kind in (("w_kpi", "kpi"), ("w_bar", "bar"), ("w_line", "line"), ("w_table", "table")):
        assert f'data-widget-id="{wid}"' in html_out
        assert f'data-widget-kind="{kind}"' in html_out
    assert 'class="card card-warning"' in html_out
    assert "Este gráfico não pôde ser exibido" in html_out
    assert "nao_existe" in html_out
    assert "Trase — Carne bovina [D1]" in html_out
    assert "Trase — Carne bovina [D2]" in html_out


# --- Testes do Orquestrador (ciclo de revisão até 2 rodadas + degradação) --------

def test_orchestrator_fixes_spec_in_one_revision(monkeypatch, temp_beef_duckdb, tmp_path):
    monkeypatch.setattr("src.soy.queries.is_available", lambda: False)
    monkeypatch.setattr("src.queries.latest_year", lambda: 2023)

    bad_spec = {
        "title": "Painel Pará 2023",
        "subtitle": "Carne bovina",
        "widgets": [{
            "id": "kpi1",
            "kind": "kpi",
            "title": "Maior volume municipal (2023)",
            "dataset_id": "D1",
            "column": "volume",
            "agg": "first",
            "value": 123.0,  # incorreto (o real no banco sintético é 1085.0)
            "unit": "t",
            "source": "Trase — Carne bovina [D1]",
        }],
    }
    fixed_spec = {
        "title": "Painel Pará 2023",
        "subtitle": "Carne bovina",
        "widgets": [
            {
                "id": "kpi1",
                "kind": "kpi",
                "title": "Maior volume municipal (2023)",
                "dataset_id": "D1",
                "column": "volume",
                "agg": "first",
                "value": 1085.0,
                "unit": "t",
                "source": "Trase — Carne bovina [D1]",
            },
            {
                "id": "bar1",
                "kind": "bar",
                "title": "Top 5 municípios por volume (2023)",
                "subtitle": "Origem rastreada",
                "dataset_id": "D1",
                "x": "muni",
                "y": ["volume"],
                "top_n": 5,
                "unit": "t",
                "source": "Trase — Carne bovina [D1]",
            },
        ],
    }

    fake_client = FakeAnthropicClient([
        # 1. Orquestrador: plano
        _tool_response("emit_plan", {
            "dashboard_goal": "Analisar municípios do Pará em 2023",
            "data_requests": [{"request_id": "Q1", "description": "Top municípios", "suggested_visual": "bar"}],
            "methodological_notes": ["Usar 2023"],
        }),
        # 2. Agente de Dados: executa SQL + finaliza
        _tool_response("run_sql", {
            "sql": "SELECT municipality_of_production AS muni, volume FROM supply_chain WHERE year = 2023 ORDER BY volume DESC LIMIT 10",
            "purpose": "Top 10 municípios por volume",
        }),
        _text_response("Concluído em [D1]."),
        # 3. Agente de Dashboard (proposta inicial com KPI errado -> falha determinística sem chamar LLM revisor)
        _tool_response("emit_dashboard_spec", bad_spec),
        # 4. Agente de Dashboard (correção #1 com valor 1085.0 correto)
        _tool_response("emit_dashboard_spec", fixed_spec),
        # 5. Agente Revisor (LLM metodológico aprova)
        _tool_response("emit_review", {"approved": True, "summary": "Tudo correto.", "issues": []}),
    ])
    monkeypatch.setattr("src.dashboard._llm.get_client", lambda: fake_client)
    monkeypatch.setattr("src.dashboard.data_agent.get_client", lambda: fake_client)

    out_path = tmp_path / "painel_corrigido.html"
    res = generate_dashboard("Maiores municípios de carne no Pará", output_path=out_path)

    assert res.revisions_used == 1
    assert len(res.reviews) == 2
    assert res.reviews[0].llm_called is False  # falhou no determinístico
    assert res.reviews[1].llm_called is True and res.reviews[1].approved is True
    assert out_path.exists()
    assert 'data-widget-id="kpi1"' in res.html
    assert 'data-widget-id="bar1"' in res.html
    assert 'class="card card-warning' not in res.html
    assert "Este gráfico não pôde ser exibido" not in res.html


def test_orchestrator_caps_at_2_revisions_and_keeps_valid_charts(monkeypatch, temp_beef_duckdb, tmp_path):
    assert MAX_REVISIONS == 2
    monkeypatch.setattr("src.soy.queries.is_available", lambda: False)
    monkeypatch.setattr("src.queries.latest_year", lambda: 2023)

    # Um gráfico válido (bar_ok) e um teimosamente inválido (kpi_bad) durante todas as tentativas
    partially_bad_spec = {
        "title": "Painel Parcial Pará",
        "subtitle": "2023",
        "widgets": [
            {
                "id": "bar_ok",
                "kind": "bar",
                "title": "Volume por município (2023)",
                "dataset_id": "D1",
                "x": "muni",
                "y": ["volume"],
                "unit": "t",
                "source": "Trase — Carne bovina [D1]",
            },
            {
                "id": "kpi_bad",
                "kind": "kpi",
                "title": "KPI com coluna inexistente",
                "dataset_id": "D1",
                "column": "coluna_fantasma",
                "agg": "sum",
                "value": 10.0,
                "unit": "t",
                "source": "Trase — Carne bovina [D1]",
            },
        ],
    }

    fake_client = FakeAnthropicClient([
        _tool_response("emit_plan", {
            "dashboard_goal": "Teste limite de 2 revisões",
            "data_requests": [{"request_id": "Q1", "description": "Volume", "suggested_visual": "bar"}],
            "methodological_notes": [],
        }),
        _tool_response("run_sql", {
            "sql": "SELECT municipality_of_production AS muni, volume FROM supply_chain WHERE year = 2023 ORDER BY volume DESC LIMIT 5",
            "purpose": "Top 5",
        }),
        _text_response("Pronto."),
        # Proposta inicial + 2 correções (total 3 chamadas ao Dashboard Agent)
        _tool_response("emit_dashboard_spec", partially_bad_spec),
        _tool_response("emit_dashboard_spec", partially_bad_spec),
        _tool_response("emit_dashboard_spec", partially_bad_spec),
    ])
    monkeypatch.setattr("src.dashboard._llm.get_client", lambda: fake_client)
    monkeypatch.setattr("src.dashboard.data_agent.get_client", lambda: fake_client)

    res = generate_dashboard("Pergunta com gráfico teimoso", save=False)

    assert res.revisions_used == 2
    assert len(res.reviews) == 3
    by_id = {w.id: w for w in res.spec.widgets}
    assert by_id["bar_ok"].valid is True
    assert by_id["kpi_bad"].valid is False
    assert 'data-widget-id="bar_ok"' in res.html
    assert 'data-widget-kind="bar"' in res.html
    assert 'data-widget-id="kpi_bad"' in res.html
    assert "Este gráfico não pôde ser exibido" in res.html


# --- Teste da CLI (`python -m src.cli dashboard "..."`) --------------------------

def test_cli_dashboard_saves_html_and_opens_browser(monkeypatch, temp_beef_duckdb, tmp_path):
    from src import cli

    monkeypatch.setattr("src.soy.queries.is_available", lambda: False)
    monkeypatch.setattr("src.queries.latest_year", lambda: 2023)

    valid_spec = {
        "title": "Dashboard CLI 2023",
        "subtitle": "Gerado via CLI",
        "widgets": [{
            "id": "t1",
            "kind": "table",
            "title": "Tabela de municípios (2023)",
            "dataset_id": "D1",
            "columns": ["muni", "volume"],
            "unit": "t",
            "source": "Trase — Carne bovina [D1]",
        }],
    }

    fake_client = FakeAnthropicClient([
        _tool_response("emit_plan", {
            "dashboard_goal": "Tabela CLI",
            "data_requests": [{"request_id": "Q1", "description": "Tabela", "suggested_visual": "table"}],
            "methodological_notes": [],
        }),
        _tool_response("run_sql", {
            "sql": "SELECT municipality_of_production AS muni, volume FROM supply_chain WHERE year = 2023 LIMIT 3",
            "purpose": "Amostra",
        }),
        _text_response("Dados prontos."),
        _tool_response("emit_dashboard_spec", valid_spec),
        _tool_response("emit_review", {"approved": True, "summary": "OK", "issues": []}),
    ])
    monkeypatch.setattr("src.dashboard._llm.get_client", lambda: fake_client)
    monkeypatch.setattr("src.dashboard.data_agent.get_client", lambda: fake_client)

    opened_urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url) or True)

    out_html = tmp_path / "saida_cli.html"
    monkeypatch.setattr(sys, "argv", ["cli", "dashboard", "Resumo da carne bovina", "-o", str(out_html)])
    cli.main()

    assert out_html.exists()
    assert "Dashboard CLI 2023" in out_html.read_text(encoding="utf-8")
    assert len(opened_urls) == 1
    assert opened_urls[0].endswith("saida_cli.html")

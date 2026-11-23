"""Testes offline do Result Store e integração retrocompatível em src/agent.py (R2)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

import src.agent as agent_mod
import src.config as config_mod
from src.dashboard.schemas import DatasetResult
import src.database as database_mod
from src.pipeline.result_store import ResultStore


def _usage(inp: int = 80, out: int = 40):
    return SimpleNamespace(input_tokens=inp, output_tokens=out)


def _tool_turn(calls: list[tuple[str, dict]]):
    return SimpleNamespace(
        stop_reason="tool_use",
        usage=_usage(),
        content=[
            SimpleNamespace(type="tool_use", id=f"tu_{i}", name=name, input=inp)
            for i, (name, inp) in enumerate(calls, 1)
        ],
    )


def _text_turn(text: str):
    return SimpleNamespace(
        stop_reason="end_turn",
        usage=_usage(),
        content=[SimpleNamespace(type="text", text=text)],
    )


class FakeClient:
    def __init__(self, turns: list):
        self._turns = list(turns)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._turns.pop(0)


@pytest.fixture
def temp_beef_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trase.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("""
            CREATE TABLE supply_chain (
                year INTEGER,
                country_of_destination VARCHAR,
                economic_bloc VARCHAR,
                volume DOUBLE,
                fob DOUBLE,
                cattle_deforestation_5_year_total_exposure DOUBLE
            )
        """)
        con.executemany(
            "INSERT INTO supply_chain VALUES (?, ?, ?, ?, ?, ?)",
            [
                (2023, "CHINA", "CHINA (MAINLAND)", 50000.0, 250000000.0, 12000.0),
                (2023, "UNITED STATES", "NAFTA", 20000.0, 110000000.0, 3500.0),
            ],
        )
        con.execute("""
            CREATE VIEW flows_by_destination AS
            SELECT year, country_of_destination, economic_bloc,
                   SUM(volume) AS volume_t,
                   SUM(fob) AS fob_usd,
                   SUM(cattle_deforestation_5_year_total_exposure) AS deforestation_exposure_ha
            FROM supply_chain
            GROUP BY ALL
        """)
        con.execute("CREATE TABLE entity_index (kind VARCHAR, value VARCHAR, context VARCHAR, norm VARCHAR)")
        con.execute("INSERT INTO entity_index VALUES ('country_of_destination', 'CHINA', 'CHINA (MAINLAND)', 'CHINA')")
    finally:
        con.close()

    monkeypatch.setattr(config_mod, "DUCKDB_PATH", db_path)
    monkeypatch.setattr(database_mod, "DUCKDB_PATH", db_path)
    monkeypatch.setattr("src.soy.queries.is_available", lambda: False)
    monkeypatch.setattr("src.queries.latest_year", lambda: 2023)
    return db_path


def test_result_store_persists_parquet_meta_and_enforces_limits(tmp_path):
    store = ResultStore(base_dir=tmp_path / "sessions", max_datasets=3, max_rows=5, persist=True)
    sid = "sessao_teste_01"

    for idx in range(1, 5):
        lbl = store.allocate_label(sid)
        assert lbl == f"D{idx}"
        df = pd.DataFrame({"x": list(range(10)), "val": [float(i * idx) for i in range(10)]})
        store.put(
            sid,
            DatasetResult(
                dataset_id=lbl,
                database="trase.duckdb",
                source_label="Trase — Carne bovina",
                tool_name="run_sql",
                query_summary=f"SELECT {idx}",
                df=df,
            ),
        )

    # Limite de 3 conjuntos por sessão (D1 foi despejado; restam D2, D3, D4) e 5 linhas cada
    kept = store.get_datasets(sid)
    assert [d.dataset_id for d in kept] == ["D2", "D3", "D4"]
    assert all(len(d.df) == 5 and d.truncated is True for d in kept)

    sdir = tmp_path / "sessions" / sid
    assert not (sdir / "D1.parquet").exists()
    assert (sdir / "D2.parquet").exists()
    assert (sdir / "D4.parquet").exists()
    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["last_index"] == 4

    # Nova instância recarrega do disco e continua em D5
    reloaded = ResultStore(base_dir=tmp_path / "sessions", max_datasets=3, max_rows=5, persist=True)
    assert [d.dataset_id for d in reloaded.get_datasets(sid)] == ["D2", "D3", "D4"]
    assert reloaded.allocate_label(sid) == "D5"


def test_result_store_rejects_invalid_session_ids(tmp_path):
    store = ResultStore(base_dir=tmp_path / "sessions")
    for bad in ("../env", "a/b", "", "id com espaco", "a" * 80):
        with pytest.raises(ValueError):
            store.allocate_label(bad)


def test_agent_ask_saves_datasets_with_continuous_dn_labels_across_turns(monkeypatch, temp_beef_db, tmp_path):
    store = ResultStore(base_dir=tmp_path / "sessions")
    sid = "sessao_chat_1234"

    # Mensagem 1: find_entity (sem Dn) + top_destinations (D1) + run_sql (D2)
    client1 = FakeClient([
        _tool_turn([
            ("find_entity", {"text": "CHINA", "kind": "country_of_destination"}),
            ("top_destinations", {"year": 2023, "limit": 5}),
            ("run_sql", {"sql": "SELECT SUM(volume) AS total_t FROM supply_chain WHERE year = 2023", "purpose": "Total"}),
        ]),
        _text_turn("A China liderou com 50 mil t [D1] de um total de 70 mil t [D2]."),
    ])
    monkeypatch.setattr(agent_mod, "get_client", lambda: client1)

    ans1 = agent_mod.ask("Destinos da carne em 2023", session_id=sid, result_store=store)
    assert [c.label for c in ans1.tool_calls] == ["find_entity", "D1", "D2"]
    assert [d.dataset_id for d in ans1.datasets] == ["D1", "D2"]

    saved = store.get_datasets(sid)
    assert [d.dataset_id for d in saved] == ["D1", "D2"]
    assert float(saved[0].df.iloc[0]["volume_t"]) == 50000.0
    assert float(saved[1].df.iloc[0]["total_t"]) == 70000.0
    assert (tmp_path / "sessions" / sid / "D1.parquet").is_file()
    assert (tmp_path / "sessions" / sid / "D2.parquet").is_file()

    # Mensagem 2 na mesma sessão: numeração continua em D3
    client2 = FakeClient([
        _tool_turn([("run_sql", {"sql": "SELECT SUM(fob) AS total_fob FROM supply_chain WHERE year = 2023"})]),
        _text_turn("O FOB total foi US$ 360 milhões [D3]."),
    ])
    monkeypatch.setattr(agent_mod, "get_client", lambda: client2)

    ans2 = agent_mod.ask("Qual foi o FOB total em 2023?", session_id=sid, result_store=store)
    assert [c.label for c in ans2.tool_calls] == ["D3"]
    assert [d.dataset_id for d in store.get_datasets(sid)] == ["D1", "D2", "D3"]


def test_agent_ask_without_result_store_keeps_exact_legacy_behavior(monkeypatch, temp_beef_db):
    client = FakeClient([
        _tool_turn([("top_destinations", {"year": 2023, "limit": 2})]),
        _text_turn("China liderou em 2023 [D1]."),
    ])
    monkeypatch.setattr(agent_mod, "get_client", lambda: client)

    ans = agent_mod.ask("Destinos em 2023")
    assert ans.datasets == []
    assert [c.label for c in ans.tool_calls] == ["D1"]
    assert "[D1]" in ans.text
    # Chamada seguinte sem store reinicia em D1, exatamente como antes
    client_next = FakeClient([
        _tool_turn([("top_destinations", {"year": 2023, "limit": 2})]),
        _text_turn("China liderou [D1]."),
    ])
    monkeypatch.setattr(agent_mod, "get_client", lambda: client_next)
    ans_next = agent_mod.ask("Destinos em 2023 novamente")
    assert [c.label for c in ans_next.tool_calls] == ["D1"]
    assert ans_next.datasets == []

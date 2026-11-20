"""Testes offline do Orquestrador de intenções (R6) e da suíte eval/pipeline_intents.py."""

from __future__ import annotations

import pytest

import eval.pipeline_intents as eval_intents_mod
import src.pipeline.orchestrator as pipe_orch_mod
from src.pipeline.orchestrator import MAP_UNAVAILABLE_MESSAGE, classify_intent


def test_eval_suite_achieves_100_percent_without_llm(monkeypatch):
    monkeypatch.setattr(
        pipe_orch_mod,
        "call_structured_llm",
        lambda **kw: (_ for _ in ()).throw(AssertionError("O LLM não pode ser chamado nos 20 casos determinísticos!")),
    )
    hits, total, rows = eval_intents_mod.run_suite(use_llm=False)
    failures = [r for r in rows if r["acertou"] != "SIM"]
    assert total == 20
    assert hits == 20, f"Falhas inesperadas: {failures}"


def test_question_path_adds_zero_llm_calls(monkeypatch):
    monkeypatch.setattr(
        pipe_orch_mod,
        "call_structured_llm",
        lambda **kw: (_ for _ in ()).throw(AssertionError("Caminho question não deve chamar LLM no orquestrador!")),
    )
    for q in (
        "qual o maior município produtor de soja em 2022?",
        "o que diz o Código Florestal sobre reserva legal?",
        "o que é exposição ao desmatamento?",
        "quantos frigoríficos existem no mapa logístico?",
    ):
        dec = classify_intent(q)
        assert dec.intent == "question"
        assert dec.decided_by == "rules"
        assert dec.clarification is None


def test_vague_requests_return_concrete_clarification():
    for msg in ("faz um dashboard", "um gráfico", "quero montar um painel"):
        dec = classify_intent(msg, has_store_data=False)
        assert dec.intent == "dashboard"
        assert dec.clarification is not None
        assert "1." in dec.clarification and "2." in dec.clarification


@pytest.mark.parametrize("msg, dominio", [
    ("faz um gráfico da soja", "soy"),
    ("monta um painel da carne bovina", "beef"),
    ("quero um dashboard da cadeia da soja", "soy"),
])
def test_so_o_nome_da_cadeia_nao_e_recorte_e_pede_esclarecimento(msg, dominio):
    """Regressão: 'soja' contava como recorte e o painel era montado sem métrica, lugar ou ano."""
    dec = classify_intent(msg, has_store_data=False, use_llm=False)
    assert dec.intent == "dashboard"
    assert dec.domain == dominio
    assert dec.clarification is not None


@pytest.mark.parametrize("msg", [
    "Monte um painel da soja em Goiás de 2015 a 2022",
    "Faça um dashboard dos 10 maiores municípios exportadores de soja por exposição ao desmatamento",
    "Gráfico das exportações de carne bovina por destino em 2023",
])
def test_pedido_com_recorte_monta_direto(msg):
    dec = classify_intent(msg, has_store_data=False, use_llm=False)
    assert dec.intent == "dashboard" and dec.clarification is None


COLUNAS = {"year", "municipality", "volume_tonnes", "exposure_ha"}


@pytest.mark.parametrize("msg", [
    "mostre só os 5 maiores",
    "agora só os 5 maiores",
    "só os 5 maiores municípios",
    "deixa só o top 3",
])
def test_so_os_n_maiores_com_painel_aberto_e_edicao_com_dados_salvos(msg):
    """Regressão: sem verbo de edição, essas frases viravam pergunta comum (ou iam para o LLM)."""
    dec = classify_intent(msg, has_spec=True, has_store_data=True, store_columns=COLUNAS, use_llm=False)
    assert dec.intent == "dashboard_edit"
    assert dec.use_previous_results and not dec.needs_new_data


def test_filtro_com_painel_aberto_e_edicao_que_busca_dados_novos():
    dec = classify_intent("filtre só Mato Grosso", has_spec=True, has_store_data=True,
                          store_columns=COLUNAS, use_llm=False)
    assert dec.intent == "dashboard_edit" and dec.needs_new_data


@pytest.mark.parametrize("msg, tem_painel", [
    ("quais os 5 maiores municípios em 2022?", True),
    ("mostre só os 5 maiores", False),
])
def test_pergunta_ou_sem_painel_nao_vira_edicao(msg, tem_painel):
    dec = classify_intent(msg, has_spec=tem_painel, has_store_data=tem_painel, use_llm=False)
    assert dec.intent != "dashboard_edit"


def test_assumable_world_request_declares_premise():
    dec = classify_intent("faz um grafiko da soja para todo o mundo?")
    assert dec.intent == "dashboard"
    assert dec.domain == "soy"
    assert dec.clarification is None
    assert dec.assumption is not None
    assert "destino" in dec.assumption.lower()
    assert "produção mundial" in dec.assumption.lower()


def test_dashboard_edit_with_and_without_spec_and_needs_new_data():
    # Com spec ativa: troca visual não precisa de novos dados
    dec_swap = classify_intent(
        "troque o gráfico de barras por linha",
        has_spec=True,
        has_store_data=True,
        store_columns={"year", "volume_tonnes"},
    )
    assert dec_swap.intent == "dashboard_edit"
    assert dec_swap.needs_new_data is False
    assert dec_swap.use_previous_results is True

    # Com spec ativa: adição de FOB quando FOB não está nas colunas do store -> needs_new_data=True
    dec_fob = classify_intent(
        "adicione um KPI de FOB",
        has_spec=True,
        has_store_data=True,
        store_columns={"year", "volume_tonnes"},
    )
    assert dec_fob.intent == "dashboard_edit"
    assert dec_fob.needs_new_data is True

    # Sem spec ativa: verbo de edição cai em dashboard
    dec_no_spec = classify_intent(
        "troque o gráfico de barras por linha",
        has_spec=False,
        has_store_data=True,
    )
    assert dec_no_spec.intent == "dashboard"


def test_mixed_and_map_edit_behaviors():
    dec_mixed = classify_intent(
        "explique o que diz o Código Florestal sobre reserva legal e monte um painel de exposição no Pará"
    )
    assert dec_mixed.intent == "mixed"
    assert dec_mixed.use_previous_results is True

    dec_map = classify_intent("mostra isso num mapa", has_store_data=True)
    assert dec_map.intent == "map_edit"
    assert "ainda não está disponível" in MAP_UNAVAILABLE_MESSAGE


def test_ambiguous_message_uses_one_structured_llm_call_and_falls_back_to_question_on_error(monkeypatch):
    calls: list[str] = []

    def fake_llm(**kwargs):
        calls.append(kwargs["tool_name"])
        return {
            "intent": "dashboard_edit",
            "domain": "soy",
            "use_previous_results": True,
            "needs_new_data": False,
            "clarification": None,
        }, 90, 40

    monkeypatch.setattr(pipe_orch_mod, "call_structured_llm", fake_llm)

    # Sem spec na sessão, mesmo que o LLM devolva dashboard_edit, o orquestrador converte para dashboard
    dec = classify_intent("apresente uma visão executiva disso", has_spec=False, has_store_data=True, use_llm=True)
    assert len(calls) == 1
    assert dec.decided_by == "llm"
    assert dec.intent == "dashboard"

    # Se o LLM falhar, caminho seguro = question
    monkeypatch.setattr(
        pipe_orch_mod,
        "call_structured_llm",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("falha simulada")),
    )
    dec_safe = classify_intent("apresente uma visão executiva disso", use_llm=True)
    assert dec_safe.intent == "question"


def test_eval_cli_exits_with_clear_message_when_key_missing(monkeypatch, capsys):
    monkeypatch.setattr(eval_intents_mod, "OPENROUTER_API_KEY", "")
    rc = eval_intents_mod.main(["--llm"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "OPENROUTER_API_KEY" in err

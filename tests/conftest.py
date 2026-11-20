"""Configuração comum dos testes."""
from __future__ import annotations

import pytest

import src.dashboard.chart_intent as chart_intent_mod


@pytest.fixture(autouse=True)
def _sem_llm_na_classificacao_de_grafico(monkeypatch):
    """A classificação do tipo de gráfico pode chamar o LLM quando o dicionário não resolve.
    Nos testes, essa chamada nunca vai à rede: falha e o fluxo segue sem tipo pedido.
    Testes que precisam simular o LLM trocam `chart_intent_mod.call_structured_llm` de novo."""
    def _bloqueado(**_kwargs):
        raise RuntimeError("LLM desativado nos testes")

    monkeypatch.setattr(chart_intent_mod, "call_structured_llm", _bloqueado)

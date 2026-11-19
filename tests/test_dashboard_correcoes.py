"""Testes de regressão das correções do Agente de Dashboards.

Cada teste reproduz um erro encontrado no uso real. Nenhum chama o LLM de verdade.
"""
from __future__ import annotations

import pytest

from src.dashboard.dashboard_agent import DASHBOARD_SYSTEM_PROMPT


# --- Erro 2: alegação de ilegalidade bloqueava o painel inteiro --------------------

@pytest.mark.parametrize("termo", [
    "ilegal", "ilegalidade", "crime", "criminoso", "culpado", "violou a lei", "responsável pelo desmatamento",
])
def test_prompt_proibe_termos_do_monitor_mesmo_negados(termo):
    assert termo in DASHBOARD_SYSTEM_PROMPT
    assert "NEM MESMO para negá-las" in DASHBOARD_SYSTEM_PROMPT
    assert "exposição ao desmatamento" in DASHBOARD_SYSTEM_PROMPT

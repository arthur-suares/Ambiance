"""Parte A2: painel quase vazio por defeitos no revisor e no validador.

Reproduz "Preciso de um grafico de pizza dos maiores exportadores de soja do Brasil" com dados de
exemplo e um revisor LLM simulado que devolve as mesmas instruções internas vistas no uso real.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

import src.dashboard.dashboard_agent as dashboard_agent_mod
from src.dashboard import build_dashboard_from_store
from src.dashboard.messages import plain_labels, short_subtitle
from src.dashboard.orchestrator import OMITTED_CLAIM_WARNING
from src.dashboard.renderer import render_dashboard_html
from src.dashboard.reviewer_agent import check_deterministic
from src.dashboard.schemas import DatasetResult, parse_dashboard_spec
from src.pipeline.monitor import OutputMonitor
from src.pipeline.result_store import ResultStore

PERGUNTA = "Preciso de um grafico de pizza dos maiores exportadores de soja do Brasil"

GRUPOS = pd.DataFrame({
    "exporter_group": ["Outros", "CARGILL", "BUNGE", "ADM", "UNKNOWN", "COFCO"],
    "volume_t": [38.9e6, 13.5e6, 10.2e6, 9.7e6, 6.1e6, 5.3e6],
    "share_pct": [41.5, 14.4, 10.8, 10.4, 6.5, 5.7],
})
TOTAIS = pd.DataFrame({"volume_total_t": [93.7e6], "n_grupos": [196]})

SUBTITULO_TECNICO = (
    "Recorte: 2022, excluindo destino BRAZIL e exportadores UNKNOWN, UNKNOWN CUSTOMER e PROCESSED "
    "DOMESTICALLY. Percentuais calculados na base de % do identificado, com o total do recorte como "
    "denominador. Os demais grupos ficam em Outros, somando 100%. Dados do Trase."
)

SPEC_GERADA = {
    "title": "Maiores exportadores de soja do Brasil em 2022",
    "subtitle": SUBTITULO_TECNICO,
    "widgets": [
        {"id": "kpi1", "kind": "kpi", "title": "Volume exportado (2022)", "dataset_id": "D2",
         "column": "volume_total_t", "agg": "first", "value": 93.7e6, "unit": "t", "source": "Trase — Soja [D2]"},
        {"id": "kpi2", "kind": "kpi", "title": "Grupos exportadores (2022)", "dataset_id": "D2",
         "column": "n_grupos", "agg": "first", "value": 196, "unit": "grupos", "source": "Trase — Soja [D2]"},
        {"id": "w_part", "kind": "progress", "title": "Participação de cada grupo no volume (2022)",
         "dataset_id": "D1", "x": "exporter_group", "y": ["share_pct"], "unit": "%",
         "source": "Trase — Soja [D1]"},
        {"id": "w_bar", "kind": "bar", "title": "Volume exportado pelos 15 maiores grupos (2022)",
         "dataset_id": "D1", "x": "exporter_group", "y": ["volume_t"], "unit": "t", "orientation": "h",
         "source": "Trase — Soja [D1]"},
        {"id": "w_tab", "kind": "table", "title": "Detalhe por grupo (2022)", "dataset_id": "D1",
         "columns": ["exporter_group", "volume_t", "share_pct"], "unit": "t",
         "column_labels": {"exporter_group": "Grupo", "volume_t": "Volume", "share_pct": "Participação"},
         "column_units": {"volume_t": "t", "share_pct": "%"}, "source": "Trase — Soja [D1]"},
    ],
}

# Texto interno do revisor LLM, como apareceu nos cartões no uso real.
REVISAO_LLM = {
    "approved": False,
    "summary": "Ajustes recomendados.",
    "issues": [
        {"widget_id": "w_part", "message": "Substitua por um widget kind='pie' com x='grupo' e y=['volume_t'] "
                                           "a partir de supply_chain; pct_identificado mistura bases."},
        {"widget_id": "w_bar", "message": "Gráfico metodologicamente correto. Mantido como válido, mas o "
                                          "subtítulo deve esclarecer a origem rastreada."},
        {"widget_id": "w_tab", "message": "A tabela declara unidade 't' mas tem colunas em %."},
        {"widget_id": None, "message": "Evite qualquer sugestão de desmatamento ilegal no texto."},
    ],
}

_PROIBIDO_NA_TELA = ("kind=", "widget", "supply_chain", "pct_identificado", "Substitua", "exporter_group",
                     "share_pct", "volume_t", "desmatamento ilegal")


def _texto_visivel(page: str) -> str:
    """Só o que o leitor vê: sem scripts, estilos, atributos nem o bloco técnico de Rastreabilidade."""
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)
    page = re.sub(r'<details class="provenance".*?</details>', " ", page, flags=re.S)
    return re.sub(r"<[^>]+>", " ", page)


def _ds(did, df):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)


class _Sessao:
    def __init__(self, store):
        self.session_id = "sessao_a2_01"
        self.result_store = store
        self.current_spec = None
        self.current_dashboard_path = None


@pytest.fixture
def painel(monkeypatch, tmp_path):
    store = ResultStore(base_dir=tmp_path / "s")
    store.put("sessao_a2_01", _ds("D1", GRUPOS))
    store.put("sessao_a2_01", _ds("D2", TOTAIS))

    def fake_llm(**kw):
        if kw["tool_name"] == "emit_review":
            return REVISAO_LLM, 1, 1
        return SPEC_GERADA, 1, 1  # o gerador "insiste" na mesma spec em todas as tentativas

    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", fake_llm)
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm", fake_llm)
    return build_dashboard_from_store(PERGUNTA, _Sessao(store), domain="soy", output_path=tmp_path / "p.html")


def test_a_painel_mostra_graficos_validos(painel):
    assert all(w.valid for w in painel.spec.widgets)
    assert painel.html.count("Plotly.newPlot(") >= 1  # barras desenhadas
    assert "Mostrei os mesmos dados como lista" not in painel.html
    assert OutputMonitor().check_dashboard_spec(painel.spec).action == "ok"


def test_b_nenhum_texto_interno_aparece_na_tela(painel):
    visivel = _texto_visivel(painel.html)
    for termo in _PROIBIDO_NA_TELA:
        assert termo not in visivel, termo
    for aviso in painel.spec.warnings:
        for termo in _PROIBIDO_NA_TELA:
            assert termo not in aviso


def test_c_observacao_do_revisor_nao_omite_o_grafico(painel):
    barras = next(w for w in painel.spec.widgets if w.id == "w_bar")
    assert barras.valid and barras.validation_error is None


def test_d_tabela_com_unidades_mistas_e_aceita_com_unidade_por_coluna(painel):
    tabela = next(w for w in painel.spec.widgets if w.id == "w_tab")
    assert tabela.valid
    assert "Volume (t)" in painel.html and "Participação (%)" in painel.html
    assert ">t / %</span>" in painel.html


def test_texto_do_revisor_com_termo_proibido_nao_vira_aviso(painel):
    assert OMITTED_CLAIM_WARNING not in painel.spec.warnings


def test_subtitulo_tecnico_vira_portugues_simples_e_curto(painel):
    visivel = _texto_visivel(painel.html)
    for termo in ("UNKNOWN", "PROCESSED DOMESTICALLY", "BRAZIL"):
        assert termo not in visivel
    hero = re.search(r'<p class="hero-subtitle">(.*?)</p>', painel.html, flags=re.S).group(1)
    assert len(hero) <= 200
    assert "Notas do recorte" in painel.html  # texto completo fica na Rastreabilidade


def test_rotulos_tecnicos_em_portugues():
    assert plain_labels("exportadores UNKNOWN CUSTOMER e PROCESSED DOMESTICALLY") == \
        "exportadores cliente não identificado e consumo no Brasil"
    assert plain_labels("origem 'UNKNOWN'") == "origem não identificada"
    assert len(short_subtitle(SUBTITULO_TECNICO)) <= 200


# --- (e) somar percentuais entre grupos continua bloqueado --------------------------------

@pytest.mark.parametrize("widget", [
    {"id": "k", "kind": "kpi", "title": "Soma das participações", "dataset_id": "D1", "column": "share_pct",
     "agg": "sum", "value": 89.3, "unit": "%", "source": "Trase [D1]"},
    {"id": "b", "kind": "bar", "title": "Participação empilhada", "dataset_id": "D1", "x": "ano",
     "y": ["share_pct", "outra_pct"], "barmode": "stack", "unit": "%", "source": "Trase [D1]"},
])
def test_e_somar_percentuais_entre_grupos_continua_bloqueado(widget):
    df = pd.DataFrame({"ano": [2021, 2022], "exporter_group": ["A", "B"], "share_pct": [40.0, 49.3],
                       "outra_pct": [10.0, 20.0]})
    spec = parse_dashboard_spec({"title": "P", "widgets": [widget]})
    issues = [i for i in check_deterministic(spec, [_ds("D1", df)]) if i.blocking]
    assert any(i.code == "soma_percentual" for i in issues)


def test_e_mostrar_o_percentual_de_cada_grupo_nao_e_bloqueado():
    spec = parse_dashboard_spec({"title": "P", "widgets": [SPEC_GERADA["widgets"][2]]})
    assert [i for i in check_deterministic(spec, [_ds("D1", GRUPOS)]) if i.blocking] == []


# --- (f) "Outros" e "não identificado" no fim, em cor neutra ------------------------------

def test_f_outros_e_nao_identificado_ficam_no_fim(painel):
    html_out = painel.html
    tabela = html_out[html_out.index('data-widget-id="w_tab"'):]
    linhas = re.findall(r"<tr><td[^>]*>([^<]+)</td>", tabela)
    assert linhas[-2:] == ["Outros", "Não identificado"]
    lista = html_out[html_out.index('data-widget-id="w_part"'):]
    rotulos = re.findall(r'<span class="prog-label">([^<]+)</span>', lista)
    assert rotulos[-2:] == ["Outros", "Não identificado"]
    from src.dashboard.renderer import NEUTRAL
    assert NEUTRAL in lista  # cor neutra


def test_f_barras_poem_outros_por_ultimo_em_cor_neutra():
    from src.dashboard.renderer import build_widget_figure
    spec = parse_dashboard_spec({"title": "P", "widgets": [SPEC_GERADA["widgets"][3]]})
    fig = build_widget_figure(spec.widgets[0], GRUPOS)
    nomes = list(fig.data[0].y)  # barras horizontais: o primeiro do eixo fica embaixo
    assert set(nomes[:2]) == {"Outros", "Não identificado"}
    cores = list(fig.data[0].marker.color)
    from src.dashboard.renderer import NEUTRAL
    assert cores[0] == cores[1] == NEUTRAL and cores[-1] != NEUTRAL


# --- 8: pior caso, gráfico reprovado com dados vira lista --------------------------------

def test_grafico_reprovado_com_dados_vira_lista_e_sem_dados_vira_aviso():
    spec = parse_dashboard_spec({"title": "P", "widgets": [
        {"id": "x", "kind": "bar", "title": "Barras com coluna errada", "dataset_id": "D1",
         "x": "exporter_group", "y": ["coluna_que_nao_existe"], "unit": "t", "source": "Trase [D1]"},
        {"id": "z", "kind": "bar", "title": "Sem dados", "dataset_id": "D9", "x": "a", "y": ["b"],
         "unit": "t", "source": "Trase [D9]"},
    ]})
    page = render_dashboard_html(spec, [_ds("D1", GRUPOS)])
    visivel = _texto_visivel(page)
    assert "Mostrei os mesmos dados como lista." in visivel and "CARGILL" in visivel
    assert "Sem dados para este gráfico" in visivel and "Não há dados para este recorte." in visivel
    assert "coluna_que_nao_existe" not in visivel and "D9" not in visivel.replace("[D9]", "")


def test_titulo_de_grafico_com_termo_proibido_e_reescrito_e_o_grafico_fica(monkeypatch, tmp_path):
    store = ResultStore(base_dir=tmp_path / "s")
    store.put("sessao_a2_01", _ds("D1", GRUPOS))
    spec = {"title": "Exportadores de soja (2022)", "subtitle": "", "widgets": [
        {**SPEC_GERADA["widgets"][3], "title": "Grupos responsáveis pelo desmatamento (2022)"}]}
    monkeypatch.setattr(dashboard_agent_mod, "call_structured_llm", lambda **kw: (spec, 1, 1))
    monkeypatch.setattr("src.dashboard.reviewer_agent.call_structured_llm",
                        lambda **kw: ({"approved": True, "summary": "", "issues": []}, 1, 1))
    res = build_dashboard_from_store(PERGUNTA, _Sessao(store), domain="soy", output_path=tmp_path / "p.html")
    w = res.spec.widgets[0]
    assert w.valid and "responsáveis" not in w.title
    assert res.spec.warnings.count(OMITTED_CLAIM_WARNING) == 1
    assert OMITTED_CLAIM_WARNING == "Reescrevi um texto do painel para falar apenas de exposição ao desmatamento."


def test_nome_de_campo_escrito_pela_ia_nao_aparece_na_tela():
    texto = "Ranking dos 7 maiores grupos exportadores (exporter_group) em 2022, base share_pct."
    assert plain_labels(texto) == "Ranking dos 7 maiores grupos exportadores em 2022, base share pct."
    assert plain_labels("Exportações de soja do Brasil, 2022") == "Exportações de soja do Brasil, 2022"


def test_eixos_e_legendas_nao_mostram_nome_de_campo():
    from src.dashboard.renderer import build_widget_figure
    for w_raw in (SPEC_GERADA["widgets"][3], {**SPEC_GERADA["widgets"][3], "y": ["share_pct"], "unit": "%"}):
        w = parse_dashboard_spec({"title": "P", "widgets": [w_raw]}).widgets[0]
        fig = build_widget_figure(w, GRUPOS)
        textos = [fig.layout.xaxis.title.text or "", fig.layout.yaxis.title.text or "",
                  *[t.name or "" for t in fig.data]]
        assert not any("_" in t for t in textos), textos
    assert build_widget_figure(parse_dashboard_spec({"title": "P", "widgets": [SPEC_GERADA["widgets"][3]]})
                               .widgets[0], GRUPOS).layout.xaxis.title.text == "Volume (t)"

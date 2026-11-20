"""Partes C e E: composição visual e identidade (sem cara de painel feito por IA)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.dashboard.renderer import (
    ACCENT,
    NEUTRAL,
    PAGE_CSS,
    PALETTE,
    _short_num,
    build_widget_figure,
    render_dashboard_html,
)
from src.dashboard.schemas import DatasetResult, compute_kpi_value, parse_dashboard_spec

SERIE = pd.DataFrame({"year": list(range(2011, 2023)),
                      "volume_t": [8.1e6, 8.4e6, 8.7e6, 8.8e6, 8.5e6, 10.1e6, 11.3e6, 9.9e6, 10.5e6, 12.2e6, 12.5e6, 13.9e6],
                      "exposicao_ha": [17e3, 18e3, 19e3, 18.5e3, 23.5e3, 22.4e3, 29e3, 20.8e3, 20.8e3, 19.3e3, 15.3e3, 21.7e3]})
CURTA = SERIE.tail(4).reset_index(drop=True)


def _ds(did, df):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)


def _lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _cr(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tokens(theme: str) -> dict[str, str]:
    bloco = PAGE_CSS.split(':root[data-theme="dark"]')[0 if theme == "light" else 1].split("}")[0]
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", bloco))


def _page(widgets, datasets, **kw):
    by_id = {d.dataset_id: d.df for d in datasets}
    for w in widgets:
        if w.get("kind") in ("kpi", "gauge") and "value" not in w:
            w["value"] = compute_kpi_value(by_id[w["dataset_id"]], w["column"], w.get("agg", "first"))
    return render_dashboard_html(parse_dashboard_spec({"title": "Painel", "widgets": widgets}), datasets, **kw)


# --- E3: paleta e contraste ---------------------------------------------------------------

def test_no_maximo_6_cores_de_categoria_um_acento_e_um_neutro():
    assert len(PALETTE) <= 6 and len(set(PALETTE)) == len(PALETTE)
    assert ACCENT not in PALETTE and NEUTRAL not in PALETTE


@pytest.mark.parametrize("fundo", ["#ffffff", "#1b1f1b"])
def test_series_tem_contraste_de_3_para_1_nos_dois_temas(fundo):
    for cor in [*PALETTE, NEUTRAL, ACCENT]:
        assert _cr(cor, fundo) >= 3.0, (cor, fundo)


@pytest.mark.parametrize("tema", ["light", "dark"])
def test_textos_passam_aa_nos_dois_temas(tema):
    t = _tokens(tema)
    for texto in ("fg", "muted", "chart-text"):
        for fundo in ("bg", "panel", "panel-2"):
            assert _cr(t[texto], t[fundo]) >= 4.5, (tema, texto, fundo)
    assert _cr(t["warn-fg"], t["warn-bg"]) >= 4.5


# --- E1/E2: o que não pode e o sistema de design -------------------------------------------

def test_sem_degrade_vidro_brilho_nem_cantos_exagerados():
    css = PAGE_CSS.lower()
    for proibido in ("gradient", "backdrop-filter", "text-shadow", "box-shadow", "glass", "inter,"):
        assert proibido not in css, proibido
    raios = [int(r) for r in re.findall(r"border-radius:\s*(\d+)px", css)]
    assert raios and max(raios) <= 8
    assert "radius: 999px" not in css and "border-left: 3px" not in css and "border-left: 4px" not in css


def test_sistema_de_design_documentado_no_css():
    for token in ("--s1: 4px", "--s2: 8px", "--r-sm: 6px", "--r-md: 8px", "--t-md: 14px", "--t-3xl: 36px"):
        assert token in PAGE_CSS
    assert "font-variant-numeric: tabular-nums" in PAGE_CSS
    assert "fonts.googleapis" not in PAGE_CSS and "@import" not in PAGE_CSS


def test_sem_emoji_na_pagina():
    page = _page([{"id": "k", "kind": "kpi", "title": "Volume", "dataset_id": "D1", "column": "volume_t",
                   "agg": "max", "unit": "t", "source": "Trase [D1]"}], [_ds("D1", SERIE)])
    assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", re.sub(r"<script\b.*?</script>", "", page, flags=re.S))


# --- C1: fileira de indicadores ----------------------------------------------------------

def test_indicador_tem_icone_numero_e_variacao_calculada():
    serie = SERIE.sort_values("year", ascending=False)
    page = _page([{"id": "k", "kind": "kpi", "title": "Volume originado, 2022", "dataset_id": "D1",
                   "column": "volume_t", "agg": "max", "unit": "t", "source": "Trase [D1]",
                   "trend_x": "year", "trend_y": "volume_t"}], [_ds("D1", serie)])
    item = page[page.index('data-widget-id="k"'):]
    assert 'class="kpi-icon"' in item[:600]
    assert ">13,9 mi t<" in item
    assert "+11,2% <span class=\"delta-ref\">vs 2021" in item
    assert 'class="kpi-strip"' in page and "kpi-card" not in page  # fileira, não grade de cartões


def test_indicador_sem_periodo_anterior_nao_mostra_variacao():
    page = _page([{"id": "k", "kind": "kpi", "title": "Municípios", "dataset_id": "D1", "column": "year",
                   "agg": "count", "unit": "municípios", "source": "Trase [D1]"}], [_ds("D1", SERIE)])
    assert 'class="kpi-delta"' not in page


# --- C2/E4: linhas ------------------------------------------------------------------------

def _linha(df, **kw):
    raw = {"id": "l", "kind": "line", "title": "Volume", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
           "unit": "t", "source": "Trase [D1]"}
    raw.update(kw)
    return build_widget_figure(parse_dashboard_spec({"title": "P", "widgets": [raw]}).widgets[0], df)


def test_linha_com_marcadores_vazados_reta_e_rotulo_no_fim():
    fig = _linha(SERIE)
    tr = fig.data[0]
    assert tr.marker.symbol == "circle-open" and tr.line.shape in (None, "linear")
    textos = [a.text for a in fig.layout.annotations]
    assert "13,9 mi" in textos  # último valor no fim da linha
    assert any(t.startswith("máx.") for t in textos) is False  # máximo é o último ponto: sem anotação extra


def test_linha_anota_o_maximo_quando_nao_e_o_ultimo():
    fig = _linha(SERIE, y=["exposicao_ha"], unit="ha")
    assert "máx. 2017: 29,0 mil" in [a.text for a in fig.layout.annotations]


def test_poucos_pontos_tem_valor_escrito_em_cada_ponto():
    tr = _linha(CURTA).data[0]
    assert "text" in tr.mode and list(tr.text)[-1] == "13,9 mi"


def test_duas_series_com_rotulo_direto_tracos_diferentes_e_sem_legenda():
    df = pd.concat([CURTA.assign(cadeia="Soja"), CURTA.assign(cadeia="Carne", volume_t=CURTA.volume_t / 3)])
    fig = _linha(df, color="cadeia")
    assert fig.layout.showlegend is False
    assert {t.line.dash for t in fig.data} == {"solid", "dash"}  # forma, além da cor
    assert any(a.text.startswith("Carne · ") for a in fig.layout.annotations)


def test_marcas_do_eixo_em_portugues():
    fig = _linha(SERIE)
    assert all(re.fullmatch(r"\d+(,\d)?( mil| mi| bi)?", t) for t in fig.layout.yaxis.ticktext)
    assert "15 mi" in fig.layout.yaxis.ticktext
    assert _short_num(1.5e9) == "1,5 bi" and _short_num(2500) == "2,5 mil" and _short_num(0) == "0"


# --- C3/E5: hierarquia ---------------------------------------------------------------------

def test_um_grafico_principal_por_secao_e_menores_compactos():
    rank = pd.DataFrame({"municipality": ["A", "B", "C"], "volume_t": [3.0, 2.0, 1.0]})
    page = _page([
        {"id": "b1", "kind": "bar", "title": "Ranking principal", "dataset_id": "D2", "x": "municipality",
         "y": ["volume_t"], "orientation": "h", "unit": "t", "source": "Trase [D2]"},
        {"id": "p1", "kind": "pie", "title": "Participação", "dataset_id": "D2", "x": "municipality",
         "y": ["volume_t"], "unit": "t", "source": "Trase [D2]"},
        {"id": "b2", "kind": "bar", "title": "Outro ranking", "dataset_id": "D2", "x": "municipality",
         "y": ["volume_t"], "orientation": "h", "unit": "t", "source": "Trase [D2]"},
    ], [_ds("D2", rank)])
    assert 'class="card chart-card span-2" data-widget-id="b1"' in page
    assert 'class="card chart-card is-compact" data-widget-id="p1"' in page
    assert 'class="card chart-card is-compact" data-widget-id="b2"' in page


# --- E6: dados de exemplo sempre rotulados --------------------------------------------------

def test_preview_rotula_os_dados_como_exemplo():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from preview_dashboard import build_example
    spec, datasets = build_example()
    assert "exemplo" in spec.title.lower()
    assert all("exemplo" in w.source.lower() for w in spec.widgets)
    assert "lorem" not in str(spec.to_dict()).lower()


def test_cartao_de_meia_largura_nao_fica_sozinho_na_linha():
    serie = SERIE.assign(bioma="CERRADO")
    page = _page([
        {"id": "l1", "kind": "line", "title": "Principal", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
         "unit": "t", "source": "Trase [D1]"},
        {"id": "a1", "kind": "area", "title": "Sozinho", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
         "color": "bioma", "stacked": True, "unit": "t", "source": "Trase [D1]"},
    ], [_ds("D1", serie)])
    assert 'class="card chart-card span-2" data-widget-id="a1"' in page


def test_celular_nao_estoura_a_largura_da_tela():
    movel = PAGE_CSS[PAGE_CSS.index("@media (max-width: 900px)"):]
    assert ".shell { grid-template-columns: minmax(0, 1fr); }" in movel
    assert "repeat(2, minmax(0, 1fr))" in movel and ".chart-grid { grid-template-columns: minmax(0, 1fr); }" in movel


def test_eixo_de_tempo_so_mostra_anos_dos_dados():
    assert list(_linha(SERIE).layout.xaxis.range) == [2010.6, 2022.4]

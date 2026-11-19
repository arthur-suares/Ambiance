"""Parte D: movimento e interação (sem exagero), com o valor final sempre no HTML."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.dashboard.interaction import MOTION_CSS, MOTION_JS
from src.dashboard.renderer import render_dashboard_html
from src.dashboard.schemas import DatasetResult, compute_kpi_value, parse_dashboard_spec

ROOT = Path(__file__).resolve().parents[1]
SERIE = pd.DataFrame({"year": list(range(2016, 2023)),
                      "volume_t": [8.5e6, 10.1e6, 11.3e6, 9.9e6, 10.5e6, 12.2e6, 13.9e6]})
RANK = pd.DataFrame({"municipality": ["SORRISO", "RIO VERDE", "JATAI", "Outros"],
                     "volume_t": [40.0, 30.0, 10.0, 20.0]})
PCT = pd.DataFrame({"uf": ["GO", "MT"], "zdc_pct": [40.0, 70.0]})


def _ds(did, df):
    return DatasetResult(did, "soy.duckdb", "Trase — Soja", "run_soy_sql", "SELECT 1", df)


def _page(widgets, datasets, **kw):
    by_id = {d.dataset_id: d.df for d in datasets}
    for w in widgets:
        if w.get("kind") in ("kpi", "gauge") and "value" not in w:
            w["value"] = compute_kpi_value(by_id[w["dataset_id"]], w["column"], w.get("agg", "first"))
    return render_dashboard_html(parse_dashboard_spec({"title": "Painel", "widgets": widgets}), datasets, **kw)


BAR = {"id": "b", "kind": "bar", "title": "Ranking", "dataset_id": "D2", "x": "municipality",
       "y": ["volume_t"], "orientation": "h", "unit": "t", "source": "Trase [D2]"}
LINE = {"id": "l", "kind": "line", "title": "Série", "dataset_id": "D1", "x": "year", "y": ["volume_t"],
        "unit": "t", "source": "Trase [D1]"}
KPI = {"id": "k", "kind": "kpi", "title": "Volume, 2022", "dataset_id": "D1", "column": "volume_t", "agg": "max",
       "unit": "t", "source": "Trase [D1]"}


# --- D5: regras técnicas (sem navegador) --------------------------------------------------------

def test_valor_final_fica_no_html_e_o_movimento_so_existe_com_js():
    page = _page([KPI], [_ds("D1", SERIE)])
    assert '>13,9 mi t<' in page and 'data-value="13900000.0"' in page
    assert ".js-motion .card" in MOTION_CSS and "d.classList.add(\"js-motion\")" in MOTION_JS
    assert "prefers-reduced-motion: reduce" in MOTION_JS and "prefers-reduced-motion: reduce" in MOTION_CSS
    assert "beforeprint" in MOTION_JS and "@media print" in MOTION_CSS


def test_duracoes_entre_250_e_900_ms():
    # durações das animações (não os temporizadores de limpeza, que esperam a animação acabar)
    ms = [int(m) for m in re.findall(r"animateTo\([^;]*?,\s*(\d+)\)", MOTION_JS)]
    ms += [int(float(s) * 1000) for s in re.findall(r"transition:[^;]*?(\.\d+)s", MOTION_CSS)]
    ms += [int(m) for m in re.findall(r"dur = (\d+)", MOTION_JS)]
    ms += [int(m) for m in re.findall(r"(\d+)ms", MOTION_JS)]
    assert ms and all(200 <= v <= 900 for v in ms), ms


def test_sem_biblioteca_nova():
    page = _page([BAR, LINE], [_ds("D1", SERIE), _ds("D2", RANK)], plotlyjs="cdn")
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', page)
    assert srcs and all("cdn.plot.ly" in s for s in srcs)


# --- D3: ver como, tela cheia, baixar -------------------------------------------------------------

def test_ver_como_barras_pizza_lista_com_os_mesmos_dados():
    page = _page([BAR], [_ds("D2", RANK)])
    card = page[page.index('data-widget-id="b"'):]
    assert 'aria-label="Ver como"' in card
    for v in ("bar", "pie", "list"):
        assert f'data-view="{v}"' in card
    assert '<div class="view" data-view="pie" hidden>' in card
    # a pizza usa exatamente os mesmos números do ranking
    pie_json = card[card.index('data-view="pie" hidden'):card.index('<div class="view" data-view="list"')]
    assert re.search(r'"values":\[40\.0,30\.0,10\.0,20\.0\]', pie_json.replace(" ", ""))


def test_sem_pizza_quando_ela_enganaria():
    page = _page([{**BAR, "x": "uf", "y": ["zdc_pct"], "unit": "%"}], [_ds("D2", PCT)])
    assert 'data-view="pie"' not in page and 'data-view="list"' in page


def test_botoes_e_csv_com_os_dados_do_cartao():
    page = _page([BAR], [_ds("D2", RANK)])
    for acao in ("fullscreen", "image", "csv"):
        assert f'data-action="{acao}"' in page
    csv = re.search(r'<script type="text/csv" class="csv-data">(.*?)</script>', page, re.S).group(1)
    linhas = csv.strip().splitlines()
    assert linhas[0] == "Município;Volume (t)"  # cabeçalho como na tela, sem nome de campo
    assert linhas[1] == "Sorriso;40,0" and linhas[-1] == "Outros;20,0"


# --- D4: período ------------------------------------------------------------------------------------

def test_filtro_de_periodo_so_com_anos_dos_dados():
    page = _page([LINE], [_ds("D1", SERIE)])
    filtro = page[page.index('class="period-filter"'):page.index("</div>", page.index('class="period-filter"'))]
    anos = [int(a) for a in re.findall(r'<option value="(\d{4})"', filtro)]
    assert anos == list(range(2016, 2023)) * 2
    assert '<tr data-year="2016">' in page  # a tabela de "Ver dados" pode ser filtrada


def test_sem_filtro_de_periodo_quando_nao_ha_ano():
    assert 'class="period-filter"' not in _page([BAR], [_ds("D2", RANK)])


# --- D6: navegador real (Edge via Playwright) ---------------------------------------------------------

def _edge_ok() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe").exists() or \
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe").exists()


navegador = pytest.mark.skipif(not _edge_ok(), reason="Playwright ou Edge indisponível")
CAPTURAS = ROOT / "outputs" / "capturas_parte_d"


@pytest.fixture(scope="module")
def preview_html(tmp_path_factory):
    sys.path.insert(0, str(ROOT / "scripts"))
    from preview_dashboard import build_example
    spec, datasets = build_example()
    out = tmp_path_factory.mktemp("d")
    paginas = {}
    for theme in ("light", "dark"):
        p = out / f"preview_{theme}.html"
        p.write_text(render_dashboard_html(spec, datasets, question="Panorama", theme=theme), encoding="utf-8")
        paginas[theme] = p
    return paginas


def _abrir(pw, path, *, width=1300, height=900, reduced=False):
    browser = pw.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              reduced_motion="reduce" if reduced else "no-preference")
    page = ctx.new_page()
    erros = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erros.append(str(e)))
    page.goto(path.as_uri())
    page.wait_for_load_state("load")
    return browser, page, erros


def _rolar_ate_o_fim(page):
    altura = page.evaluate("document.body.scrollHeight")
    y = 0
    while y < altura:
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(120)
        y += 500
    page.wait_for_timeout(1300)  # a animação mais longa tem 900 ms + atraso escalonado


@navegador
def test_animacoes_terminam_com_os_numeros_dos_dados_e_sem_erro(preview_html):
    from playwright.sync_api import sync_playwright
    html_txt = preview_html["light"].read_text(encoding="utf-8")
    esperados = re.findall(r'<p class="kpi-value"[^>]*>([^<]+)</p>', html_txt)
    with sync_playwright() as pw:
        browser, page, erros = _abrir(pw, preview_html["light"])
        assert page.evaluate("document.documentElement.classList.contains('js-motion')")
        _rolar_ate_o_fim(page)
        finais = page.eval_on_selector_all(".kpi-value", "els => els.map(e => e.textContent.trim())")
        assert [f for f in finais if f] [:len(esperados)] == [e.strip() for e in esperados] or \
            all(e.strip() in finais for e in esperados)
        assert "13,9 mi t" in finais  # o mesmo número do DataFrame (volume de 2022)
        assert page.evaluate("[...document.querySelectorAll('.card, .kpi')].every(c => c.classList.contains('is-in'))")
        assert erros == [], erros
        CAPTURAS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(CAPTURAS / "claro_desktop.png"), full_page=True)
        browser.close()


@navegador
def test_movimento_reduzido_mostra_tudo_pronto(preview_html):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page, erros = _abrir(pw, preview_html["light"], reduced=True)
        assert not page.evaluate("document.documentElement.classList.contains('js-motion')")
        assert page.eval_on_selector(".kpi-value", "e => e.textContent.trim()") == "13,9 mi t"
        assert page.eval_on_selector(".card", "e => getComputedStyle(e).opacity") == "1"
        assert erros == [], erros
        browser.close()


@navegador
def test_ver_como_periodo_e_tema_escuro_e_celular(preview_html):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page, erros = _abrir(pw, preview_html["dark"])
        _rolar_ate_o_fim(page)
        card = page.locator('[data-widget-id="pz"]')
        card.locator('.view-switch button[data-view="bar"]').click()
        page.wait_for_timeout(900)
        assert card.locator('.view[data-view="bar"]').is_visible()
        assert not card.locator('.view[data-view="pie"]').is_visible()
        card.locator('.view-switch button[data-view="list"]').click()
        assert card.locator('.view[data-view="list"] table').is_visible()
        linha = page.locator('[data-widget-id="l1"]')
        linha.locator("select[data-from]").select_option("2018")
        assert linha.get_attribute("data-period") == "2018-2022"
        ocultas = linha.locator("tr[data-year][hidden]").count()
        assert ocultas == 5  # 2013 a 2017 escondidos; nenhum valor novo
        xs = linha.evaluate("el => el.querySelector('.js-plotly-plot').data[0].x")
        ys = linha.evaluate("el => el.querySelector('.js-plotly-plot').data[0].y")
        assert [int(x) for x in xs] == [2018, 2019, 2020, 2021, 2022]
        assert ys == [20856, 20838, 19356, 15304, 21671]  # os mesmos valores do DataFrame
        assert erros == [], erros
        CAPTURAS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(CAPTURAS / "escuro_desktop.png"), full_page=True)
        browser.close()
        for theme, nome in (("light", "claro_celular.png"), ("dark", "escuro_celular.png")):
            browser, page, erros = _abrir(pw, preview_html[theme], width=390, height=844)
            _rolar_ate_o_fim(page)
            largura = page.evaluate("document.documentElement.scrollWidth")
            assert largura <= 392, largura  # nada passa da largura da tela
            assert erros == [], erros
            page.screenshot(path=str(CAPTURAS / nome), full_page=True)
            browser.close()

"""Cache persistente de painéis, normalização da pergunta e não-duplicação da geração (sem rede, sem LLM)."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import urllib.request

import pytest

import src.config as config_mod
import src.web as web
from src.dashboard import cache as dash_cache

PERGUNTA = "Quais os 10 municípios do Pará com maior exposição ao desmatamento?"
CTX_A = {"charts": [{"title": "Ranking A", "labels": ["X", "Y"], "series": [{"name": "ha", "values": [2, 1]}]}], "tables": []}
CTX_B = {"charts": [{"title": "Ranking B", "labels": ["X", "Y"], "series": [{"name": "ha", "values": [9, 1]}]}], "tables": []}


def _html(base: Path, name: str = "painel_1.html") -> Path:
    path = base / name
    path.write_text("<html></html>", encoding="utf-8")
    return path


# --- normalização e chave --------------------------------------------------------------------------

def test_normaliza_maiusculas_acentos_e_espacos():
    a = dash_cache.normalize_question("  Quais os 10  municípios do PARÁ?  ")
    b = dash_cache.normalize_question("quais os 10 municipios do para?")
    assert a == b == "quais os 10 municipios do para?"
    assert dash_cache.dashboard_cache_key("Pará", None) == dash_cache.dashboard_cache_key(" para ", None)


def test_contexto_diferente_gera_outra_chave_e_vazio_equivale_a_none():
    k_none = dash_cache.dashboard_cache_key(PERGUNTA, None)
    assert dash_cache.dashboard_cache_key(PERGUNTA, {}) == k_none
    assert dash_cache.dashboard_cache_key(PERGUNTA, {"charts": [], "tables": []}) == k_none
    k_a = dash_cache.dashboard_cache_key(PERGUNTA, CTX_A)
    k_b = dash_cache.dashboard_cache_key(PERGUNTA, CTX_B)
    assert len({k_none, k_a, k_b}) == 3


# --- acerto, expiração, arquivo apagado ------------------------------------------------------------

def test_acerto_com_variacao_de_acento_e_caixa(tmp_path):
    out = _html(tmp_path)
    assert dash_cache.save_cached_dashboard(PERGUNTA, CTX_A, output_path=out, title="Painel PA", domain="beef",
                                            base_dir=tmp_path, now=1000.0)
    hit = dash_cache.get_cached_dashboard(PERGUNTA.upper().replace("Á", "A"), CTX_A, base_dir=tmp_path,
                                          max_age_days=7, now=1000.0 + 3600)
    assert hit == {"filename": "painel_1.html", "title": "Painel PA", "domain": "beef", "created_at": 1000.0}
    # contexto diferente = outra entrada
    assert dash_cache.get_cached_dashboard(PERGUNTA, CTX_B, base_dir=tmp_path, max_age_days=7, now=1001.0) is None
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=tmp_path, max_age_days=7, now=1001.0) is None


def test_expiracao_remove_a_entrada(tmp_path):
    out = _html(tmp_path)
    dash_cache.save_cached_dashboard(PERGUNTA, None, output_path=out, base_dir=tmp_path, now=0.0)
    dia = 86400.0
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=tmp_path, max_age_days=7, now=6 * dia) is not None
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=tmp_path, max_age_days=7, now=8 * dia) is None
    assert json.loads((tmp_path / "cache.json").read_text(encoding="utf-8")) == {}
    # TTL <= 0 desliga o cache
    dash_cache.save_cached_dashboard(PERGUNTA, None, output_path=out, base_dir=tmp_path, now=0.0)
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=tmp_path, max_age_days=0, now=1.0) is None


def test_arquivo_apagado_vira_miss(tmp_path):
    out = _html(tmp_path)
    dash_cache.save_cached_dashboard(PERGUNTA, None, output_path=out, base_dir=tmp_path, now=10.0)
    out.unlink()
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=tmp_path, max_age_days=7, now=11.0) is None


def test_cache_json_corrompido_nao_derruba(tmp_path):
    (tmp_path / "cache.json").write_text("{nao é json", encoding="utf-8")
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=tmp_path, max_age_days=7) is None
    out = _html(tmp_path)
    assert dash_cache.save_cached_dashboard(PERGUNTA, None, output_path=out, base_dir=tmp_path)
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=tmp_path, max_age_days=7) is not None


# --- segurança de caminho --------------------------------------------------------------------------

def test_recusa_arquivo_fora_da_pasta_e_nomes_suspeitos(tmp_path):
    pasta = tmp_path / "dashboards"
    pasta.mkdir()
    fora = _html(tmp_path, "fora.html")
    assert dash_cache.save_cached_dashboard(PERGUNTA, None, output_path=fora, base_dir=pasta) is False
    assert dash_cache.save_cached_dashboard(PERGUNTA, None, output_path=pasta / "inexistente.html", base_dir=pasta) is False
    assert not (pasta / "cache.json").exists()

    # entrada manipulada no cache.json com ../ nunca vira resposta
    key = dash_cache.dashboard_cache_key(PERGUNTA, None)
    (pasta / "cache.json").write_text(json.dumps({key: {"filename": "../fora.html", "created_at": time.time()}}),
                                      encoding="utf-8")
    assert dash_cache.get_cached_dashboard(PERGUNTA, None, base_dir=pasta, max_age_days=7) is None


def test_escrita_concorrente_nao_corrompe_nem_deixa_temporarios(tmp_path):
    arquivos = [_html(tmp_path, f"p_{i}.html") for i in range(12)]
    erros: list[Exception] = []

    def gravar(i):
        try:
            assert dash_cache.save_cached_dashboard(f"pergunta {i}", None, output_path=arquivos[i], base_dir=tmp_path)
        except Exception as exc:  # pragma: no cover - só para reportar na asserção
            erros.append(exc)

    threads = [threading.Thread(target=gravar, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not erros
    data = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert len(data) == 12
    assert not list(tmp_path.glob(".cache_*.tmp"))


# --- servidor: não-duplicação, falha não cacheada, cache após "reiniciar" ----------------------------

@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "DASHBOARD_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "DASHBOARD_CACHE_DAYS", 7.0)
    monkeypatch.setattr(web, "_analytics_available", lambda: True)
    web._DASH_JOBS.clear()
    estado = SimpleNamespace(calls=0, modo="ok", lock=threading.Lock(), atraso=0.0)

    def fake_generate(question, *, chat_context=None, **kw):
        with estado.lock:
            estado.calls += 1
            n = estado.calls
        time.sleep(estado.atraso)
        if estado.modo == "erro":
            raise RuntimeError("falha simulada do agente")
        out = tmp_path / f"painel_{n}.html"
        out.write_text("<html>painel</html>", encoding="utf-8")
        widgets = [] if estado.modo == "vazio" else [object()]
        return SimpleNamespace(output_path=out, spec=SimpleNamespace(title="Painel teste", widgets=widgets),
                               plan=SimpleNamespace(dashboard_goal="meta"), domain="beef", seconds=1.2,
                               revisions_used=0)

    monkeypatch.setattr("src.dashboard.orchestrator.generate_dashboard", fake_generate)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    estado.base = f"http://127.0.0.1:{httpd.server_address[1]}"
    estado.dir = tmp_path
    yield estado
    httpd.shutdown()
    httpd.server_close()
    web._DASH_JOBS.clear()


def _post(base, path, payload):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_duas_chamadas_concorrentes_geram_o_painel_uma_vez(servidor):
    servidor.atraso = 0.3
    resultados: list = []

    def pedir(pergunta):
        resultados.append(_post(servidor.base, "/api/dashboard", {"question": pergunta, "context": CTX_A}))

    threads = [threading.Thread(target=pedir, args=(p,)) for p in (PERGUNTA, PERGUNTA.upper(), "  " + PERGUNTA)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert servidor.calls == 1
    assert {r[0] for r in resultados} == {200}
    assert len({r[1]["url"] for r in resultados}) == 1


def test_cache_persistente_responde_sem_gerar_apos_reiniciar(servidor):
    st, primeiro = _post(servidor.base, "/api/dashboard", {"question": PERGUNTA, "context": CTX_A})
    assert st == 200 and primeiro["cached"] is False and servidor.calls == 1
    assert (servidor.dir / "cache.json").exists()

    web._DASH_JOBS.clear()  # equivale a reiniciar o servidor: a memória some, o disco permanece
    st, segundo = _post(servidor.base, "/api/dashboard", {"question": PERGUNTA.lower(), "context": CTX_A})
    assert st == 200 and segundo["cached"] is True and segundo["seconds"] == 0.0
    assert segundo["url"] == primeiro["url"]
    assert servidor.calls == 1  # nenhuma chamada ao agente (nenhum custo de LLM)

    # contexto diferente = outro painel
    st, terceiro = _post(servidor.base, "/api/dashboard", {"question": PERGUNTA, "context": CTX_B})
    assert st == 200 and terceiro["cached"] is False and servidor.calls == 2


def test_arquivo_apagado_regera_o_painel(servidor):
    _post(servidor.base, "/api/dashboard", {"question": PERGUNTA, "context": CTX_A})
    for html in servidor.dir.glob("painel_*.html"):
        html.unlink()
    web._DASH_JOBS.clear()
    st, resp = _post(servidor.base, "/api/dashboard", {"question": PERGUNTA, "context": CTX_A})
    assert st == 200 and resp["cached"] is False and servidor.calls == 2


def test_falha_e_painel_vazio_nao_sao_cacheados_e_tentam_de_novo(servidor):
    servidor.modo = "erro"
    st, resp = _post(servidor.base, "/api/dashboard", {"question": PERGUNTA})
    assert st == 500 and "falha simulada" in resp["error"]
    assert not (servidor.dir / "cache.json").exists()

    servidor.modo = "vazio"
    st, _ = _post(servidor.base, "/api/dashboard", {"question": PERGUNTA})
    assert st == 200
    assert not (servidor.dir / "cache.json").exists() or json.loads(
        (servidor.dir / "cache.json").read_text(encoding="utf-8")) == {}

    servidor.modo = "ok"
    st, resp = _post(servidor.base, "/api/dashboard", {"question": PERGUNTA})
    assert st == 200 and resp["cached"] is False
    assert servidor.calls == 3  # as duas falhas anteriores não ficaram presas na memória


def test_pergunta_de_lei_nao_oferece_painel_nem_chama_o_dashboard(servidor, monkeypatch):
    import src.rag as rag

    fonte = {"title": "Código Florestal", "content": "Art. 12 ...", "url": "https://planalto.gov.br/x",
             "score": 0.9, "metadata": {"artigo": "12", "parte": 1, "partes": 1}}
    fake = SimpleNamespace(text="Resposta jurídica [1].", sources=[fonte], stop_reason="end_turn",
                           input_tokens=10, output_tokens=5, domain="law")
    monkeypatch.setattr(rag, "answer", lambda *a, **k: fake)
    st, resp = _post(servidor.base, "/api/ask",
                     {"question": "O que o Código Florestal exige?", "mode": "laws", "domain": "law"})
    assert st == 200
    assert [v["key"] for v in resp["available_views"]] == ["laws"]
    assert servidor.calls == 0

"""Testes offline de HTTP em src/web.py e segurança de /dashboards/<nome>.html (R7, R8)."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from src.agent import AgentAnswer
import src.config as config_mod
import src.pipeline.chat as chat_mod
from src.pipeline.result_store import ResultStore
from src.pipeline.session import SessionManager
import src.web as web_mod


class _FakeSocket:
    def __init__(self, raw_request: bytes):
        self._rfile = io.BytesIO(raw_request)
        self._wfile = io.BytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        return self._rfile if "r" in mode else self._wfile

    def sendall(self, data: bytes):
        self._wfile.write(data)


def _http_call(method: str, path: str, body: dict | bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    if isinstance(body, dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = f"Host: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n"
    elif isinstance(body, bytes):
        payload = body
        headers = f"Host: 127.0.0.1\r\nContent-Length: {len(payload)}\r\n"
    else:
        payload = b""
        headers = "Host: 127.0.0.1\r\n"

    raw_req = f"{method} {path} HTTP/1.1\r\n{headers}\r\n".encode("utf-8") + payload
    sock = _FakeSocket(raw_req)
    web_mod.Handler(sock, ("127.0.0.1", 54321), SimpleNamespace())

    raw_resp = sock._wfile.getvalue()
    head_bytes, _, resp_body = raw_req_split = raw_resp.partition(b"\r\n\r\n")
    lines = head_bytes.decode("iso-8859-1").split("\r\n")
    status = int(lines[0].split()[1])
    resp_headers: dict[str, str] = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()
    return status, resp_headers, resp_body


@pytest.mark.parametrize(
    "malicious_path",
    [
        "/dashboards/../.env",
        "/dashboards/..%2F.env",
        "/dashboards/%2e%2e/.env",
        "/dashboards/%2e%2e%2f.env",
        "/dashboards/a/b.html",
        "/dashboards/nao_existe.html",
        "/dashboards/dados.parquet",
        "/dashboards/script.js",
        "/dashboards/.html",
    ],
)
def test_r8_dashboard_route_blocks_traversal_wrong_ext_and_missing(monkeypatch, tmp_path, malicious_path):
    dash_dir = tmp_path / "dashboards"
    dash_dir.mkdir()
    (tmp_path / ".env").write_text("SEGREDO_NAO_SERVIR=1", encoding="utf-8")
    (dash_dir / "dados.parquet").write_bytes(b"PAR1")

    monkeypatch.setattr(config_mod, "DASHBOARD_OUTPUT_DIR", dash_dir)

    status, _, body = _http_call("GET", malicious_path)
    assert status == 404
    assert b"SEGREDO" not in body


def test_r8_dashboard_route_blocks_symlink_outside_dir_and_serves_valid_html(monkeypatch, tmp_path):
    dash_dir = tmp_path / "dashboards"
    dash_dir.mkdir()
    outside_file = tmp_path / "fora.html"
    outside_file.write_text("<html>fora</html>", encoding="utf-8")

    # Link simbólico dentro de DASHBOARD_OUTPUT_DIR apontando para fora -> 404
    symlink_path = dash_dir / "link_externo.html"
    symlink_path.symlink_to(outside_file)

    valid_html = dash_dir / "20261118_soja_destinos.html"
    valid_html.write_text("<!doctype html><html><body>Painel OK</body></html>", encoding="utf-8")

    monkeypatch.setattr(config_mod, "DASHBOARD_OUTPUT_DIR", dash_dir)

    st_sym, _, body_sym = _http_call("GET", "/dashboards/link_externo.html")
    assert st_sym == 404
    assert b"fora" not in body_sym

    st_ok, headers_ok, body_ok = _http_call("GET", "/dashboards/20261118_soja_destinos.html")
    assert st_ok == 200
    assert "text/html" in headers_ok.get("content-type", "")
    assert "Painel OK" in body_ok.decode("utf-8")


def test_r7_api_chat_validates_session_id_and_preserves_legacy_api_ask(monkeypatch, tmp_path):
    mgr = SessionManager(result_store=ResultStore(base_dir=tmp_path / "sessions"))
    monkeypatch.setattr(web_mod, "SESSION_MANAGER", mgr)

    monkeypatch.setattr(
        chat_mod,
        "agent_ask",
        lambda q, **kw: AgentAnswer(question=q, text="Resposta simulada [D1]."),
    )
    monkeypatch.setattr(
        web_mod,
        "agent_ask",
        lambda q, **kw: AgentAnswer(question=q, text="Resposta legada /api/ask."),
    )

    # session_id inválido -> 400
    for bad_sid in ("curto", "../invalido", "", "a" * 70):
        st, _, _ = _http_call("POST", "/api/chat", {"session_id": bad_sid, "message": "oi"})
        assert st == 400

    # /api/chat válido -> 200 com todos os campos exigidos em R7
    st_chat, _, raw_chat = _http_call(
        "POST",
        "/api/chat",
        {"session_id": "sessao_web_12345", "message": "qual o maior município produtor de soja em 2022?"},
    )
    assert st_chat == 200
    data = json.loads(raw_chat.decode("utf-8"))
    for required_key in (
        "answer", "intent", "session_id", "dashboards",
        "tool_calls", "sources", "warnings", "seconds", "trace_id",
    ):
        assert required_key in data
    assert data["session_id"] == "sessao_web_12345"
    assert data["intent"] == "question"
    assert "Resposta simulada" in data["answer"]

    # POST /api/ask continua funcionando exatamente como antes
    st_ask, _, raw_ask = _http_call(
        "POST",
        "/api/ask",
        {"question": "qual o maior município produtor de soja em 2022?", "mode": "agent"},
    )
    assert st_ask == 200
    ask_data = json.loads(raw_ask.decode("utf-8"))
    assert ask_data["answer"] == "Resposta legada /api/ask."


def test_index_html_uses_api_chat_session_storage_and_dashboard_iframe():
    st, headers, body = _http_call("GET", "/")
    assert st == 200
    assert "text/html" in headers.get("content-type", "")
    html_txt = body.decode("utf-8")
    assert '"/api/chat"' in html_txt
    assert "sessionStorage" in html_txt
    assert "Abrir painel" in html_txt
    assert "<iframe" in html_txt

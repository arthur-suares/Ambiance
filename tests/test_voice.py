"""Testes offline do módulo de entrada multimodal por voz (src/voice.py, src/web.py e eval/voice_compare.py)."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from eval.voice_compare import entity_hit_rate, field_matches, word_error_rate
import src.config as config_mod
from src.voice import (
    ResultadoVoz,
    VoiceProviderError,
    max_audio_bytes,
    ouvir_pergunta,
    seletores_para_resultado,
    validar_payload_voz,
)
import src.web as web_mod


class _FakeSocket:
    def __init__(self, raw_request: bytes):
        self._rfile = io.BytesIO(raw_request)
        self._wfile = io.BytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        return self._rfile if "r" in mode else self._wfile

    def sendall(self, data: bytes):
        self._wfile.write(data)


def _http_call(
    method: str,
    path: str,
    body: bytes = b"",
    *,
    content_type: str | None = None,
    content_length_override: int | None = None,
) -> tuple[int, dict[str, str], bytes]:
    header_lines = ["Host: 127.0.0.1"]
    if content_type is not None:
        header_lines.append(f"Content-Type: {content_type}")
    clen = content_length_override if content_length_override is not None else len(body)
    if method == "POST":
        header_lines.append(f"Content-Length: {clen}")
    raw_req = f"{method} {path} HTTP/1.1\r\n" + "\r\n".join(header_lines) + "\r\n\r\n"
    sock = _FakeSocket(raw_req.encode("utf-8") + body)
    web_mod.Handler(sock, ("127.0.0.1", 54321), SimpleNamespace())

    raw_resp = sock._wfile.getvalue()
    head_bytes, _, resp_body = raw_resp.partition(b"\r\n\r\n")
    lines = head_bytes.decode("iso-8859-1").split("\r\n")
    status = int(lines[0].split()[1])
    resp_headers: dict[str, str] = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()
    return status, resp_headers, resp_body


class _FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[int, str, str]] = []

    def transcribe_and_extract(self, audio: bytes, mime: str, model: str):
        self.calls.append((len(audio), mime, model))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _fake_wav(size: int = 128) -> bytes:
    return b"RIFF" + b"\x00" * max(0, size - 4)


def test_ouvir_pergunta_valid_audio_extracts_fields(monkeypatch):
    monkeypatch.setattr(config_mod, "GEMINI_API_KEY", "fake-key")
    fake = _FakeProvider(
        json.dumps({
            "transcricao": "quanto Sorriso exportou de soja em 2020?",
            "local": "Sorriso (MT)",
            "commodity": "soja",
            "ano": 2020,
            "tipo": "dados",
        })
    )
    res = ouvir_pergunta(_fake_wav(), "audio/wav", provider=fake)
    assert res.transcricao == "quanto Sorriso exportou de soja em 2020?"
    assert res.local == "Sorriso (MT)"
    assert res.commodity == "soja"
    assert res.ano == 2020
    assert res.tipo == "dados"
    assert len(fake.calls) == 1


def test_validar_payload_voz_sanitizes_out_of_schema_and_rejects_invalid_json():
    res = validar_payload_voz({
        "transcricao": "  Qual a   produção de café?  ",
        "local": "não identificado",
        "commodity": "cafe",       # fora do esquema -> None
        "ano": "ano-passado",      # fora do esquema -> None
        "tipo": "desconhecido",    # fora do esquema -> None
    })
    assert res.transcricao == "Qual a produção de café?"
    assert res.local is None
    assert res.commodity is None
    assert res.ano is None
    assert res.tipo is None

    with pytest.raises(VoiceProviderError):
        validar_payload_voz("{json quebrado")

    with pytest.raises(VoiceProviderError):
        validar_payload_voz({"transcricao": "   ", "tipo": "leis"})


@pytest.mark.parametrize(
    "tipo,commodity,expected_mode,expected_domain",
    [
        ("leis", None, "laws", "law"),
        ("leis", "soja", "laws", "law"),
        ("dados", "soja", "agent", "soy"),
        ("dados", "carne", "agent", "beef"),
        ("misto", "soja", "agent", "mixed"),
        ("dados", "ambas", "agent", "mixed"),
        ("fora_escopo", None, None, "auto"),
        (None, None, None, "auto"),
    ],
)
def test_seletores_mapping_table(tipo, commodity, expected_mode, expected_domain):
    res = ResultadoVoz(transcricao="teste", tipo=tipo, commodity=commodity)
    assert seletores_para_resultado(res) == {"mode": expected_mode, "domain": expected_domain}


def test_api_voice_http_errors_and_health_without_key(monkeypatch):
    monkeypatch.setattr(config_mod, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config_mod, "VOICE_PROVIDER", "gemini")
    monkeypatch.setattr(config_mod, "VOICE_RECORD_DIR", None)

    st, _, body = _http_call("GET", "/api/health")
    assert st == 200
    health = json.loads(body)
    assert health["voice_available"] is False
    assert health["voice_record_mode"] is False

    # Sem chave -> 503
    st503, _, _ = _http_call("POST", "/api/voice", _fake_wav(), content_type="audio/wav")
    assert st503 == 503

    # Com chave, testa 400 (vazio), 415 (formato errado) e 413 (acima do limite sem precisar enviar corpo inteiro)
    monkeypatch.setattr(config_mod, "GEMINI_API_KEY", "fake-key")

    st400, _, _ = _http_call("POST", "/api/voice", b"", content_type="audio/wav")
    assert st400 == 400

    st415, _, _ = _http_call("POST", "/api/voice", _fake_wav(), content_type="audio/webm")
    assert st415 == 415

    st413, _, _ = _http_call(
        "POST", "/api/voice", b"", content_type="audio/wav",
        content_length_override=max_audio_bytes() + 100,
    )
    assert st413 == 413


def test_api_voice_success_and_provider_error_502(monkeypatch):
    monkeypatch.setattr(config_mod, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(config_mod, "VOICE_PROVIDER", "gemini")

    fake_ok = ResultadoVoz(
        transcricao="Qual o percentual de reserva legal na Amazônia Legal?",
        local="Amazônia Legal",
        commodity=None,
        ano=None,
        tipo="leis",
        modelo="gemini-3.5-flash-lite",
        segundos=0.42,
    )
    monkeypatch.setattr(web_mod, "ouvir_pergunta", lambda audio, ct: fake_ok)
    st, _, body = _http_call("POST", "/api/voice", _fake_wav(), content_type="audio/wav")
    assert st == 200
    payload = json.loads(body)
    assert payload["transcricao"] == fake_ok.transcricao
    assert payload["seletores"] == {"mode": "laws", "domain": "law"}

    def _boom(audio, ct):
        raise VoiceProviderError("JSON inválido vindo do Gemini")

    monkeypatch.setattr(web_mod, "ouvir_pergunta", _boom)
    st502, _, _ = _http_call("POST", "/api/voice", _fake_wav(), content_type="audio/wav")
    assert st502 == 502


def test_voice_record_mode_validates_question_ids_only(monkeypatch, tmp_path):
    rec_dir = tmp_path / "audios"
    monkeypatch.setattr(config_mod, "VOICE_RECORD_DIR", rec_dir)

    st_q, _, body_q = _http_call("GET", "/api/voice/record/questions")
    assert st_q == 200
    questions = json.loads(body_q)["questions"]
    assert any(q["id"] == "L01" for q in questions)

    # Recusa IDs inexistentes ou path traversal
    for bad_id in ("../.env", "NAO_EXISTE", "L01.wav", "a/b", ""):
        st_bad, _, _ = _http_call("POST", f"/api/voice/record?id={bad_id}", _fake_wav(), content_type="audio/wav")
        assert st_bad == 400

    # Aceita ID real de eval/perguntas.jsonl
    st_ok, _, body_ok = _http_call("POST", "/api/voice/record?id=L01", _fake_wav(256), content_type="audio/wav")
    assert st_ok == 200
    assert json.loads(body_ok)["id"] == "L01"
    assert (rec_dir / "L01.wav").is_file()
    assert (rec_dir / "L01.wav").stat().st_size == 256


def test_voice_compare_metrics():
    assert word_error_rate("Quanto Sorriso exportou de soja em 2020?", "quanto sorriso exportou de soja em 2020") == 0.0
    assert word_error_rate("a b c d", "a x c d") == pytest.approx(0.25)
    assert entity_hit_rate(["JBS"], "A JBS cometeu crime ambiental em 2023?", "a jbs cometeu crime ambiental em 2023") == 1.0
    assert entity_hit_rate(["JBS"], "A JBS cometeu crime ambiental em 2023?", "a gbs cometeu crime ambiental em 2023") == 0.0
    assert field_matches(
        {"local": "Sorriso (MT)", "commodity": "soja", "ano": 2020, "tipo": "dados"},
        {"local": "Sorriso", "commodity": "soja", "ano": 2020, "tipo": "dados"},
    ) == {"local": True, "commodity": True, "ano": True, "tipo": True}

"""Painel completo sob demanda no studio.js (sem rede, sem LLM): análise estática + simulação em JavaScriptCore."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDIO_JS = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")
JSC = shutil.which("jsc") or (
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
    if Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc").exists() else None
)
needs_jsc = pytest.mark.skipif(JSC is None, reason="jsc (JavaScriptCore) não disponível")


def _function_source(name: str, *, is_async: bool = False) -> str:
    """Extrai o código de `function name(...) { ... }` por balanceamento de chaves."""
    prefix = "async function " if is_async else "function "
    start = STUDIO_JS.index(f"{prefix}{name}(")
    brace = STUDIO_JS.index("{", STUDIO_JS.index(")", start))
    depth, i = 0, brace
    while i < len(STUDIO_JS):
        ch = STUDIO_JS[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return STUDIO_JS[start:i + 1]
        i += 1
    raise AssertionError(f"função {name} sem fechamento")


def _run_jsc(script: str, tmp_path: Path) -> str:
    path = tmp_path / "case.js"
    path.write_text(script, encoding="utf-8")
    out = subprocess.run([JSC, str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr + out.stdout
    return out.stdout.strip()


@needs_jsc
def test_studio_js_tem_sintaxe_valida(tmp_path):
    (tmp_path / "studio_src.js").write_text(STUDIO_JS, encoding="utf-8")
    script = f'new Function(readFile("{tmp_path / "studio_src.js"}")); print("OK");'
    assert _run_jsc(script, tmp_path) == "OK"


def test_append_message_turn_nao_pre_gera_o_painel():
    corpo = _function_source("appendMessageTurn")
    # a única referência a requestDashboard em appendMessageTurn está no aquecimento por hover/foco
    chamadas = [m.start() for m in re.finditer(r"requestDashboard\(", corpo)]
    assert len(chamadas) == 1
    assert "startWarmup" in corpo[max(0, chamadas[0] - 400):chamadas[0]]
    assert 'views.some(v => v.key === "dash")) requestDashboard' not in corpo


def test_hover_e_foco_no_cartao_do_painel_usam_atraso_de_cerca_de_400ms():
    corpo = _function_source("appendMessageTurn")
    assert 'if (v.key === "dash")' in corpo
    assert re.search(r"\}, 4[0-5]\d\);", corpo), "atraso de ~420 ms esperado"
    for evento in ("mouseenter", "mouseleave", "focus", "blur", "click"):
        assert f'btn.addEventListener("{evento}"' in corpo
    assert "turns.includes(turn)" in corpo
    assert "clearTimeout(hoverTimer)" in corpo
    # cada listener de aquecimento é registrado uma vez, no botão recém-criado (sem duplicar)
    assert corpo.count('btn.addEventListener("mouseenter"') == 1


def test_abrir_o_canvas_aquece_o_painel_quando_ele_existe():
    corpo = _function_source("openCanvasForTurn", is_async=True)
    assert re.search(r'if \(hasDash && defaultTab !== "dash"\) requestDashboard\(turn\)', corpo)


def test_aba_painel_continua_chamando_loadDashboard_e_texto_de_carregamento():
    assert 'if (resolved === "dash") loadDashboard(activeTurnObj);' in STUDIO_JS
    assert "O agente de dashboard está montando o painel" in _function_source("loadDashboard", is_async=True)


@needs_jsc
def test_request_dashboard_nao_duplica_e_tenta_de_novo_apos_erro(tmp_path):
    request_src = _function_source("requestDashboard")
    script = f"""
var calls = 0, log = [];
var behavior = "ok";
function fetchDashboard(turn) {{
  calls += 1;
  if (behavior === "erro") return Promise.reject(new Error("falhou"));
  return Promise.resolve("/dashboards/x.html").then(function (u) {{ turn.dashUrl = u; return u; }});
}}
{request_src}
var turn = {{id: 1}};
// duas chamadas simultâneas -> 1 requisição
var p1 = requestDashboard(turn), p2 = requestDashboard(turn);
log.push("mesma promessa: " + (p1 === p2));
p1.then(function () {{
  log.push("calls apos 1a rodada: " + calls);
  // com dashUrl pronto, nenhuma nova requisição
  return requestDashboard(turn);
}}).then(function (u) {{
  log.push("url pronta: " + u + " calls=" + calls);
  // erro limpa a promessa e permite nova tentativa
  var t2 = {{id: 2}};
  behavior = "erro";
  return requestDashboard(t2).catch(function () {{
    log.push("erro tratado, dashPromise=" + t2.dashPromise);
    behavior = "ok";
    return requestDashboard(t2);
  }}).then(function (u2) {{
    log.push("retry ok: " + u2 + " calls=" + calls);
  }});
}}).then(function () {{
  return requestDashboard(null).catch(function (e) {{ log.push("null: " + e.message); }});
}}).then(function () {{
  print(log.join("\\n"));
}});
drainMicrotasks();
"""
    out = _run_jsc(script, tmp_path).splitlines()
    assert out[0] == "mesma promessa: true"
    assert out[1] == "calls apos 1a rodada: 1"
    assert out[2] == "url pronta: /dashboards/x.html calls=1"
    assert out[3] == "erro tratado, dashPromise=null"
    assert out[4] == "retry ok: /dashboards/x.html calls=3"
    assert out[5] == "null: Turno inválido."

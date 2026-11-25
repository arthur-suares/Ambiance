"""Cliente compartilhado para chamadas estruturadas (JSON via tool_use) ao LLM.

Segue o mesmo padrão de `src/rag.py` e `src/agent.py`: usa `get_client()`
(Anthropic Messages API via OpenRouter) e `LLM_MODEL`.
"""

from __future__ import annotations

from src.config import LLM_EXTRA_PARAMS, LLM_MODEL
from src.dashboard.schemas import extract_json_dict
from src.rag import get_client


def call_structured_llm(
    *,
    system: str | list[dict],
    user_content: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    max_tokens: int = 4096,
) -> tuple[dict, int, int]:
    """Solicita ao LLM uma saída JSON estruturada via ferramenta dedicada.

    Devolve `(payload_dict, input_tokens, output_tokens)`. Aceita tanto resposta
    `tool_use` (padrão Anthropic) quanto JSON em bloco de texto (fallback para
    modelos no OpenRouter que ignorem `tool_choice`).
    """
    response = get_client().messages.create(
        model=LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        tools=[{
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
        }],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user_content}],
        **LLM_EXTRA_PARAMS,
    )
    in_tok = getattr(response.usage, "input_tokens", 0) or 0
    out_tok = getattr(response.usage, "output_tokens", 0) or 0

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return dict(block.input or {}), in_tok, out_tok

    text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text").strip()
    if text:
        return extract_json_dict(text), in_tok, out_tok

    raise ValueError(f"O LLM não devolveu saída estruturada para '{tool_name}' (stop_reason={response.stop_reason}).")

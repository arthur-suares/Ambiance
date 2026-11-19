"""Textos que o leitor do painel vê: frases simples, sem nomes de campo, tabela ou tipo técnico.

O texto técnico dos agentes (revisor, validador) vai só para o log. A tela recebe uma frase escolhida
pelo TIPO do problema (`WidgetIssue.code`).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

USER_MESSAGES = {
    "janela_5_anos": "Esta medida usa uma janela de 5 anos e não pode ser somada entre anos.",
    "soma_percentual": "Percentuais e médias não podem ser somados entre grupos.",
    "media_percentual": "Este número seria uma média de percentuais sem dizer isso no título.",
    "alegacao": "Um texto deste gráfico usava termos incompatíveis com dados de exposição ao desmatamento.",
    "kpi_valor": "O número deste indicador não bateu com os dados.",
    "sem_dados": "Não há dados para este recorte.",
    "medidor": "O medidor só mostra um percentual calculado dos dados.",
    "estrutura": "Os dados encontrados não têm todas as informações que este gráfico precisa.",
}
DEFAULT_MESSAGE = "Não consegui mostrar este gráfico como planejado."
SHOWN_AS_LIST = "Mostrei os mesmos dados como lista."
NO_DATA_TITLE = "Sem dados para este gráfico"


def user_message(codes) -> str:
    """Uma frase simples para o primeiro tipo de problema conhecido."""
    for code in codes:
        if code in USER_MESSAGES:
            return USER_MESSAGES[code]
    return DEFAULT_MESSAGE


def log_issues(context: str, issues) -> None:
    """Texto bruto dos agentes: só para o log."""
    for issue in issues:
        logger.info("[%s] %s (%s/%s): %s", context, issue.widget_id or "painel", issue.code,
                    "bloqueante" if issue.blocking else "observação", issue.message)


# --- Rótulos técnicos dos dados em português simples ---------------------------------

_LABEL_SUBS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), r) for p, r in (
        (r"['\"]?\bUNKNOWN CUSTOMER\b['\"]?", "cliente não identificado"),
        (r"['\"]?\bUNKNOWN COUNTRY\b['\"]?", "país não identificado"),
        (r"['\"]?\bPROCESSED DOMESTICALLY\b['\"]?", "consumo no Brasil"),
        (r"\borigem\s+['\"]?UNKNOWN\b['\"]?", "origem não identificada"),
        (r"['\"]?\bUNKNOWN\b['\"]?", "não identificado"),
        (r"\bBRAZIL\b", "Brasil"),
        (r"\bBrazil\b", "Brasil"),
    )
)


_FIELD_IN_PARENS_RE = re.compile(r"\s*\(\s*`?[a-z][a-z0-9]*(?:_[a-z0-9]+)+`?\s*\)")
_FIELD_RE = re.compile(r"`?(?<![\w])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w])`?")


def plain_labels(text: str | None) -> str:
    """Troca rótulos técnicos dos dados (UNKNOWN, PROCESSED DOMESTICALLY...) por português simples e
    tira nomes de campo que a IA escreva no texto ("(exporter_group)" some; "share_pct" vira "share pct")."""
    out = text or ""
    for pattern, repl in _LABEL_SUBS:
        out = pattern.sub(repl, out)
    out = _FIELD_IN_PARENS_RE.sub("", out)
    return _FIELD_RE.sub(lambda m: m.group(0).strip("`").replace("_", " "), out)


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def short_subtitle(text: str | None, max_chars: int = 200) -> str:
    """Subtítulo do painel em até ~2 linhas: frases inteiras até `max_chars`; o resto vai para a
    Rastreabilidade."""
    clean = plain_labels(text).strip()
    if len(clean) <= max_chars:
        return clean
    out = ""
    for sentence in _SENTENCE_RE.split(clean):
        candidate = f"{out} {sentence}".strip()
        if len(candidate) > max_chars:
            break
        out = candidate
    if not out:
        out = clean[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out


_RESIDUAL_RE = re.compile(
    r"\b(?:outros|outras|demais|resto|unknown|nao\s+identificad\w*|nao\s+rastread\w*|não\s+identificad\w*"
    r"|não\s+rastread\w*|others?)\b",
    re.IGNORECASE,
)


def is_residual_label(value) -> bool:
    """"Outros", "demais", "não identificado/UNKNOWN": linhas que vão sempre no fim, em cor neutra."""
    return bool(_RESIDUAL_RE.search(str(value or "")))

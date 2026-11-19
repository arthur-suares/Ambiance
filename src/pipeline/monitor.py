"""Monitores determinísticos de entrada e saída (etapas 2 e 7 de `docs/PIPELINE_MULTIAGENTE.md`).

- `InputMonitor`: lista extensível de verificações rápidas (vazio, tamanho máximo, injeção de prompt,
  alteração/exclusão de dados, pedido para acusar empresa de crime e PII — CPF/CNPJ/e-mail).
  Ponto de extensão claro (`add_check` / `checks`) para plugar classificador externo futuro.
- `OutputMonitor`: audita deterministicamente a saída do dashboard (spec válida, ausência de alegações
  de ilegalidade/autoria conforme R5-e e presença obrigatória de `source` e `[Dn]` nos componentes).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import re
import unicodedata

from src.dashboard.schemas import DashboardSpec
from src.dashboard.validator import find_illegality_claim, is_law_sourced, spec_has_law_source

logger = logging.getLogger("ambiance.monitor")

DEFAULT_MAX_INPUT_CHARS = 2000


def _strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


@dataclass
class InputVerdict:
    allowed: bool
    rule: str = "ok"
    reason: str = ""
    message: str = ""


@dataclass
class OutputVerdict:
    allowed: bool
    action: str = "ok"       # "ok" | "warn" | "blocked"
    rule: str = "ok"
    reason: str = ""
    message: str = ""
    warnings: list[str] = field(default_factory=list)


InputCheckFn = Callable[[str], InputVerdict | None]


# --- Verificações determinísticas de entrada -------------------------------------

_PROMPT_INJECTION_RE = re.compile(
    r"(?:"
    r"ignore\s+(?:todas\s+|as\s+|os\s+|suas\s+)?instruc\w*"
    r"|ignore\s+(?:all\s+|previous\s+)?instructions"
    r"|desconsidere\s+(?:todas\s+|as\s+)?(?:regras|instruc\w*)"
    r"|esqueca\s+(?:todas\s+|as\s+)?(?:regras|instruc\w*)"
    r"|(?:revele|mostre|exiba|imprima|repita)\s+(?:o\s+|seu\s+)?(?:system\s+)?prompt"
    r"|\bsystem\s+prompt\b|\bprompt\s+de\s+sistema\b"
    r"|\bjailbreak\b|\bdan\s+mode\b|\bmodo\s+desenvolvedor\b"
    r")",
    re.IGNORECASE,
)

_DATA_MUTATION_RE = re.compile(
    r"(?:"
    r"\b(?:drop|truncate|alter)\s+table\b|\bdelete\s+from\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b"
    r"|\b(?:apague|delete|drope?|destrua|zere|limpe|corrompa|sobrescreva)\s+"
    r"(?:a\s+|as\s+|os\s+|o\s+|todos\s+os\s+)?"
    r"(?:banco|base|dados|registros|arquivos|duckdb|postgres|supply_chain|soy_supply_chain)"
    r"|\b(?:altere|modifique|edite|atualize)\s+(?:a\s+|as\s+|os\s+|o\s+)?"
    r"(?:banco\s+de\s+dados|base\s+de\s+dados|dados\s+do\s+banco|registros\s+do\s+banco|supply_chain|soy_supply_chain)"
    r"|\b(?:apague|delete|drope?|destrua|altere|modifique)\s+(?:a\s+|as\s+)?tabelas?"
    r"(?!\s+(?:do|da|deste|desse|no|na)\s+(?:dash\w*|painel|grafi\w*))"
    r")",
    re.IGNORECASE,
)

# Bloqueia pedidos para acusar/condenar/incriminar empresa ou município, sem bloquear perguntas sobre a lei
_CRIME_ACCUSATION_RE = re.compile(
    r"(?:"
    r"\b(?:acuse\w*|incrimine\w*|condene\w*|culpe\w*)\s+.{1,60}?\b(?:crime\w*|criminos\w*|ilegal\w*|desmat\w*|lei)\b"
    r"|\b(?:acusar|incriminar|condenar)\s+(?:uma?\s+|as?\s+)?(?:empresa\w*|exportad\w*|trading\w*|frigorific\w*|produtor\w*)"
    r"|\b(?:diga|afirme|declare|escreva|prove|conclua)\s+que\s+(?:a\s+|o\s+|essa\s+)?(?:empresa\w*|exportad\w*|trading\w*|[a-z0-9_]{2,30})\s+"
    r"(?:cometeu\s+crime|[eé]\s+criminos\w*|[eé]\s+culpad\w*|violou\s+a\s+lei|desmatou\s+ilegalmente)"
    r")",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CPF_FORMATTED_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_CNPJ_FORMATTED_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_CPF_LABELED_OR_RAW_RE = re.compile(r"(?:\bcpf\s*[:#-]?\s*\d{11}\b|\b\d{11}\b)", re.IGNORECASE)
_CNPJ_LABELED_OR_RAW_RE = re.compile(r"(?:\bcnpj\s*[:#-]?\s*\d{14}\b|\b\d{14}\b)", re.IGNORECASE)


def check_empty_input(message: str) -> InputVerdict | None:
    if not (message or "").strip():
        return InputVerdict(
            allowed=False,
            rule="empty_message",
            reason="Mensagem vazia.",
            message="Envie uma pergunta ou pedido não vazio.",
        )
    return None


def make_max_length_check(max_chars: int = DEFAULT_MAX_INPUT_CHARS) -> InputCheckFn:
    def _check(message: str) -> InputVerdict | None:
        if len(message or "") > max_chars:
            return InputVerdict(
                allowed=False,
                rule="max_length",
                reason=f"Mensagem excedeu o limite de {max_chars} caracteres ({len(message)}).",
                message=f"Sua mensagem ultrapassa o limite de {max_chars} caracteres. Envie um pedido mais curto.",
            )
        return None

    return _check


def check_prompt_injection(message: str) -> InputVerdict | None:
    norm = _strip_accents(message.lower())
    if _PROMPT_INJECTION_RE.search(norm):
        return InputVerdict(
            allowed=False,
            rule="prompt_injection",
            reason="Tentativa de injeção de prompt ou extração de instruções internas.",
            message="Não posso atender pedidos para ignorar regras do sistema ou exibir instruções internas.",
        )
    return None


def check_data_mutation(message: str) -> InputVerdict | None:
    norm = _strip_accents(message.lower())
    if _DATA_MUTATION_RE.search(norm):
        return InputVerdict(
            allowed=False,
            rule="data_mutation",
            reason="Pedido de alteração ou exclusão de tabelas/dados.",
            message="Este sistema opera somente em modo de leitura; não é permitido alterar ou apagar dados.",
        )
    return None


def check_crime_accusation(message: str) -> InputVerdict | None:
    norm = _strip_accents(message.lower())
    if _CRIME_ACCUSATION_RE.search(norm):
        return InputVerdict(
            allowed=False,
            rule="crime_accusation",
            reason="Pedido para acusar empresa/agente de crime ou ilegalidade.",
            message=(
                "Não posso acusar empresas ou municípios de crime ou ilegalidade: os dados do Trase "
                "medem exposição associada à cadeia produtiva, não conformidade jurídica individual."
            ),
        )
    return None


def check_pii(message: str) -> InputVerdict | None:
    text = message or ""
    if (
        _EMAIL_RE.search(text)
        or _CPF_FORMATTED_RE.search(text)
        or _CNPJ_FORMATTED_RE.search(text)
        or _CPF_LABELED_OR_RAW_RE.search(text)
        or _CNPJ_LABELED_OR_RAW_RE.search(text)
    ):
        return InputVerdict(
            allowed=False,
            rule="pii_detected",
            reason="Presença de dado pessoal/identificador (CPF, CNPJ ou e-mail) na mensagem.",
            message="Por privacidade e segurança, remova CPF, CNPJ ou e-mail antes de enviar a pergunta.",
        )
    return None


class InputMonitor:
    """Monitor de entrada determinístico com lista extensível de verificações (`checks`)."""

    def __init__(
        self,
        *,
        max_chars: int = DEFAULT_MAX_INPUT_CHARS,
        checks: list[InputCheckFn] | None = None,
    ) -> None:
        self.max_chars = max(1, int(max_chars))
        if checks is not None:
            self.checks: list[InputCheckFn] = list(checks)
        else:
            self.checks = [
                check_empty_input,
                make_max_length_check(self.max_chars),
                check_prompt_injection,
                check_data_mutation,
                check_crime_accusation,
                check_pii,
            ]

    def add_check(self, check_fn: InputCheckFn) -> None:
        """Ponto de extensão para registrar classificadores adicionais no futuro."""
        self.checks.append(check_fn)

    def check(self, message: str) -> InputVerdict:
        for fn in self.checks:
            verdict = fn(message)
            if verdict is not None and not verdict.allowed:
                logger.warning("Entrada recusada pelo monitor (regra=%s): %s", verdict.rule, verdict.reason)
                return verdict
        return InputVerdict(allowed=True, rule="ok")


# --- Monitor de saída determinístico ---------------------------------------------

_DATASET_TAG_RE = re.compile(r"\[?\bD\d+\b\]?", re.IGNORECASE)


class OutputMonitor:
    """Valida a saída dos agentes antes da entrega ao front-end (etapa 7)."""

    def check_dashboard_spec(self, spec: DashboardSpec | None) -> OutputVerdict:
        if spec is None:
            return OutputVerdict(
                allowed=False,
                action="blocked",
                rule="missing_spec",
                reason="Especificação do dashboard ausente.",
                message="Não consegui montar o painel: especificação vazia.",
            )

        if not spec.title.strip():
            return OutputVerdict(
                allowed=False,
                action="blocked",
                rule="invalid_spec_title",
                reason="DashboardSpec sem título principal.",
                message="Não consegui validar o painel gerado (título ausente).",
            )

        # R5-e na saída: nenhuma alegação de ilegalidade/autoria em títulos, subtítulos ou avisos
        law_panel = spec_has_law_source(spec)  # G5: só o nome oficial da norma, só com fonte de leis
        for label, txt in (("título", spec.title), ("subtítulo", spec.subtitle)):
            claim = find_illegality_claim(txt, law_source=law_panel)
            if claim:
                logger.warning("Saída de dashboard bloqueada por alegação indevida (%s) no %s.", claim, label)
                return OutputVerdict(
                    allowed=False,
                    action="blocked",
                    rule="illegality_claim",
                    reason=f"Alegação indevida ('{claim}') no {label} do painel.",
                    message=(
                        "O painel foi bloqueado pelo monitor de saída por conter alegação de ilegalidade "
                        "ou autoria direta incompatível com os dados de exposição do Trase."
                    ),
                )

        for warn_msg in spec.warnings:
            claim = find_illegality_claim(warn_msg, law_source=law_panel)
            if claim:
                logger.warning("Saída de dashboard bloqueada por alegação indevida (%s) em warnings.", claim)
                return OutputVerdict(
                    allowed=False,
                    action="blocked",
                    rule="illegality_claim",
                    reason=f"Alegação indevida ('{claim}') nos avisos do painel.",
                    message=(
                        "O painel foi bloqueado pelo monitor de saída por conter alegação de ilegalidade "
                        "ou autoria direta incompatível com os dados de exposição do Trase."
                    ),
                )

        if not spec.widgets:
            return OutputVerdict(
                allowed=True,
                action="warn",
                rule="empty_widgets",
                reason="Painel sem componentes visuais.",
                warnings=["Nenhum componente visual pôde ser gerado para este recorte."],
            )

        valid_widgets = [w for w in spec.widgets if w.valid]
        degraded_widgets = [w for w in spec.widgets if not w.valid]

        for w in valid_widgets:
            for field_name, txt in (("título", w.title), ("subtítulo", w.subtitle)):
                claim = find_illegality_claim(txt, law_source=is_law_sourced(w))
                if claim:
                    logger.warning("Componente %s bloqueado na saída por alegação '%s'.", w.id, claim)
                    return OutputVerdict(
                        allowed=False,
                        action="blocked",
                        rule="illegality_claim",
                        reason=f"Componente '{w.id}' contém alegação indevida ('{claim}') no {field_name}.",
                        message=(
                            "O painel foi bloqueado pelo monitor de saída por conter alegação de ilegalidade "
                            "ou autoria direta."
                        ),
                    )

            if not w.source.strip() or not _DATASET_TAG_RE.search(w.source):
                logger.warning("Componente %s sem source/[Dn] válido na saída: %r", w.id, w.source)
                return OutputVerdict(
                    allowed=False,
                    action="blocked",
                    rule="missing_source_citation",
                    reason=f"Componente '{w.id}' não possui 'source' com rótulo [Dn].",
                    message=(
                        "O painel foi bloqueado pelo monitor de saída porque um ou mais gráficos não "
                        "citaram a fonte de dados [Dn]."
                    ),
                )

        if not valid_widgets:
            return OutputVerdict(
                allowed=True,
                action="warn",
                rule="all_widgets_degraded",
                reason="Todos os componentes do painel falharam na validação.",
                warnings=["Os componentes solicitados apresentaram inconsistências e foram ocultados com aviso."],
            )

        if degraded_widgets:
            return OutputVerdict(
                allowed=True,
                action="warn",
                rule="partial_degradation",
                reason=f"{len(degraded_widgets)} componente(s) degradado(s) com aviso.",
                warnings=[
                    f"“{w.title or 'Gráfico do painel'}”: {w.validation_error or 'não pôde ser mostrado como planejado.'}"
                    for w in degraded_widgets
                ],
            )

        return OutputVerdict(allowed=True, action="ok", rule="ok")

    def check(
        self,
        *,
        answer: str,
        intent: str,
        dashboard_result=None,
    ) -> OutputVerdict:
        if intent in ("dashboard", "dashboard_edit", "mixed") and dashboard_result is not None:
            return self.check_dashboard_spec(dashboard_result.spec)
        return OutputVerdict(allowed=True, action="ok", rule="ok")


default_input_monitor = InputMonitor()
default_output_monitor = OutputMonitor()

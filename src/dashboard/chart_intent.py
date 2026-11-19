"""Entende que gráfico o usuário quer ver, mesmo quando ele não sabe o nome.

Duas camadas:
1. Dicionário determinístico de expressões em português leigo ("pizza", "uma bolinha mostrando
   quanto cada um representa", "como mudou ao longo dos anos", "os maiores"...), tolerante a
   acentos e a erros de digitação ("piza", "grafiko").
2. Se o dicionário não resolver, 1 chamada curta ao LLM só para classificar a intenção visual.
   Se essa chamada falhar, o gerador escolhe pela intenção (regras no prompt).

O resultado (`ChartChoice`) é guardado no plano e repassado ao planejador, ao Agente de Dados,
ao gerador e ao revisor. Nunca se responde "não entendi o tipo de gráfico": pedido sem suporte
vira o gráfico mais próximo, com um aviso curto em português simples.

Nomes técnicos (pie, donut, gauge, waterfall...) ficam só no código; o que aparece na tela usa
`LABELS`, em palavras do dia a dia.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from src.dashboard._llm import call_structured_llm
from src.dashboard.schemas import ALLOWED_WIDGET_KINDS

# Código interno -> (nome na tela, tipo de componente, empilhado)
_CHARTS: dict[str, tuple[str, str, bool]] = {
    "pie": ("gráfico de pizza", "pie", False),
    "donut": ("gráfico de rosca", "donut", False),
    "bar": ("gráfico de barras", "bar", False),
    "line": ("gráfico de linha", "line", False),
    "area": ("gráfico de área", "area", False),
    "stacked_area": ("gráfico de composição ao longo do tempo", "area", True),
    "table": ("lista com os números", "table", False),
    "gauge": ("medidor", "gauge", False),
    "waterfall": ("gráfico de variação por item", "waterfall", False),
    "bar_line": ("barras e linha em dois gráficos alinhados", "bar_line", False),
    "map": ("mapa", "map", False),
    "radar": ("gráfico de radar", "radar", False),
    "bubble": ("gráfico de bolhas", "bubble", False),
    "scatter": ("gráfico de dispersão", "scatter", False),
    "other": ("outro formato", "other", False),
}
LABELS = {code: label for code, (label, _k, _s) in _CHARTS.items()}

# Quando o tipo ainda não existe, usa o mais próximo (e avisa).
_FALLBACK = {
    "pie": "bar", "donut": "bar", "gauge": "kpi", "waterfall": "bar",
    "map": "bar", "radar": "bar", "bubble": "bar", "scatter": "bar",
}
_FALLBACK_LABEL = {"bar": "em barras", "kpi": "como um número de destaque", "line": "em linha",
                   "table": "como lista"}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    low = _strip_accents((text or "").lower())
    low = re.sub(r"\bgrafi[ck]o?s?\b|\bgrfi[ck]os?\b|\bgrafiko?s?\b", "grafico", low)
    return re.sub(r"\s+", " ", low).strip()


# (código, padrão, explícito). Explícito = nomeia um formato ("pizza", "barras", "tabela").
# Descritivo = descreve a intenção ("os maiores", "ao longo do tempo") e só vale sem nome explícito.
_PATTERNS: tuple[tuple[str, str, bool], ...] = (
    ("bar_line", r"\bbarr?as?\s+(?:e|com)\s+(?:uma\s+|a\s+)?linhas?\b|\blinhas?\s+(?:e|com)\s+(?:as\s+)?barr?as?\b"
                 r"|\bbarr?as?\s+e\s+linhas?\s+juntas\b", True),
    ("stacked_area", r"\bempilhad[oa]s?\b|\barea\s+empilhad\w*", True),
    ("stacked_area", r"\bcomposic\w*\b.*\b(?:ao\s+longo|no\s+tempo|por\s+ano|ano\s+a\s+ano|com\s+o\s+tempo)\b", False),
    ("area", r"\bgrafico\s+de\s+area\b|\bem\s+area\b", True),
    ("donut", r"\b(?:rosca|rosquinha|donut|anel|argola)\b", True),
    ("gauge", r"\b(?:medidor|ponteiro|velocimetro|gauge|relogio)\b", True),
    ("gauge", r"\bquant[oa]s?\s*(?:%|por\s*cento|porcento)\s+(?:d[oa]s?\s+\w+\s+)?(?:foi|foram|vai|vao|vem|veio)"
              r"\s+(?:para|pra|pro|de)\b", False),
    ("waterfall", r"\b(?:cascata|waterfall)\b", True),
    ("waterfall", r"\bo\s+que\s+mais\s+(?:pesou|puxou|contribuiu|explica)\b"
                  r"|\bquem\s+mais\s+(?:puxou|pesou|contribuiu)\s+(?:a|na|para\s+a)\s+(?:queda|alta|subida|variacao)\b"
                  r"|\bcontribuic\w*\s+de\s+cada\b", False),
    ("pie", r"\b(?:pi[sz]{1,2}a|pitza|pitsa|torta|setores|fatias?|bolinha|circulo|redondo|redonda)\b", True),
    ("pie", r"\bquanto\s+cada\s+(?:um|uma|\w+)\s+(?:representa|pesa|tem\s+do\s+total)\b"
            r"|\bproporc\w*|\bdivisao\b|\bparticipac\w*|\bfatia\b|\bpercentual\s+de\s+cada\b|\bparte\s+de\s+cada\b", False),
    ("table", r"\b(?:tabelas?|tabelinha|planilhas?)\b|\b(?:em|como|numa|uma|na)\s+lista\b|\blistinha\b", True),
    ("table", r"\bnumeros?\s+exatos?\b|\bvalores?\s+exatos?\b|\bnumero\s+por\s+numero\b", False),
    ("line", r"\bgrafico\s+de\s+linhas?\b|\b(?:em|como|numa|uma|por|pra|para|de)\s+linhas?\b|\blinha\s+do\s+tempo\b", True),
    ("line", r"\bevoluc\w*|\bevoluiu\b|\bao\s+longo\s+d[oa]s?\s+(?:tempo|anos)\b|\bcom\s+o\s+tempo\b"
             r"|\bcomo\s+(?:isso\s+|ele\s+|ela\s+)?(?:mudou|variou|evoluiu|cresceu)\b|\btendencia\b"
             r"|\bsubiu\s+ou\s+caiu\b|\bcaiu\s+ou\s+subiu\b|\bano\s+a\s+ano\b|\bserie\s+(?:historica|temporal|anual)\b"
             r"|\bhistorico\b|\bpor\s+ano\b", False),
    ("bar", r"\bbarr?as?\b|\bbarrinhas?\b|\bcolunas?\b|\bgrafico\s+de\s+barr?as?\b", True),
    ("bar", r"\branking\b|\b(?:os|as)\s+(?:\d+\s+)?maiores\b|\b(?:os|as)\s+(?:\d+\s+)?principais\b|\bquem\s+mais\b"
            r"|\bcompar\w*|\btop\s*\d+\b|\bmais\s+export\w*|\blideres\b|\blidera\w*", False),
    ("map", r"\bmapas?\b", True),
    ("radar", r"\b(?:radar|teia|aranha)\b", True),
    ("bubble", r"\bbolhas?\b", True),
    ("scatter", r"\bdispers(?:ao|oes)\b|\bpontinhos\s+espalhados\b", True),
    ("other", r"\b(?:de|em|num|noutro|com)\s+(?:um\s+)?outr[oa]\s+(?:jeito|forma|formato|modo|tipo|grafico)\b"
              r"|\boutro\s+(?:tipo\s+de\s+)?grafico\b", True),
)
_COMPILED = tuple((code, re.compile(pat), explicit) for code, pat, explicit in _PATTERNS)

# Formatos que, nomeados, deixam claro que a pessoa quer um gráfico (usado pelo orquestrador do chat).
# "tabela"/"lista" ficam de fora: sozinhas, continuam indo para a resposta em texto.
ROUTING_CODES = frozenset({"pie", "donut", "bar", "line", "area", "stacked_area", "gauge", "waterfall", "bar_line"})

# Erros de digitação de nomes de formato (palavra a palavra).
_FUZZY_WORDS = {
    "pizza": "pie", "torta": "pie", "rosca": "donut", "rosquinha": "donut", "barras": "bar",
    "tabela": "table", "planilha": "table", "medidor": "gauge", "ponteiro": "gauge",
}
_FUZZY_SKIP = frozenset({"liste", "lista", "linha", "linhas", "barra", "terra", "tabelas", "medidas", "medida",
                         "rosa", "porta", "ponte", "praca", "prazo", "parte", "partes", "costa"})


@dataclass
class ChartChoice:
    """Tipo de gráfico entendido a partir do pedido."""

    requested: str           # código interno (pie, bar, line...)
    kind: str                # tipo de componente que será gerado
    stacked: bool = False
    source: str = "dicionario"   # dicionario | llm
    explicit: bool = True
    notice: str | None = None    # aviso curto em português simples (ou None)

    @property
    def label(self) -> str:
        return LABELS.get(self.requested, self.requested)

    @property
    def kind_label(self) -> str:
        if self.kind == "area" and self.stacked:
            return LABELS["stacked_area"]
        return LABELS.get(self.kind, {"kpi": "um número de destaque"}.get(self.kind, self.kind))

    def prompt_line(self) -> str:
        """Instrução para os prompts (planejador, dados, gerador, revisor)."""
        if self.requested == "other":
            return ("O usuário pediu para ver o mesmo dado de outro jeito: troque o formato do gráfico principal "
                    f"por outro tipo adequado (kind='{self.kind}'), sem mudar os números.")
        extra = ""
        if self.kind == "bar_line":
            extra = (" Faça DOIS componentes separados, um `bar` e um `line`, com o mesmo `x` de tempo e cada um "
                     "com a sua unidade; nunca dois eixos com escalas diferentes no mesmo gráfico.")
        elif self.kind == "area" and self.stacked:
            extra = " Use `stacked=true` (só para métricas aditivas)."
        elif self.kind in ("pie", "donut"):
            extra = " No máximo 8 fatias; o resto vira 'Outros' calculado na consulta SQL."
        return (f"Tipo de gráfico pedido pelo usuário: {self.label}. O componente principal DEVE ter "
                f"kind='{self.kind}'.{extra}")


def _supported(kind: str, allowed: tuple[str, ...]) -> bool:
    if kind == "bar_line":
        return "bar" in allowed and "line" in allowed
    return kind in allowed


def resolve(requested: str, *, allowed: tuple[str, ...] = ALLOWED_WIDGET_KINDS, source: str = "dicionario",
            explicit: bool = True, current_kind: str | None = None) -> ChartChoice:
    """Transforma o código pedido no tipo de componente possível hoje, com aviso se precisar trocar."""
    if requested == "other":
        kind = alternative_kind(current_kind, allowed)
        return ChartChoice("other", kind, source=source, explicit=explicit)
    _label, kind, stacked = _CHARTS[requested]
    if _supported(kind, allowed):
        return ChartChoice(requested, kind, stacked=stacked, source=source, explicit=explicit)
    fallback = _FALLBACK.get(requested, "bar")
    nome = LABELS[requested].removeprefix("gráfico de ")
    notice = f"Ainda não faço {nome}, então mostrei {_FALLBACK_LABEL.get(fallback, fallback)}."
    return ChartChoice(requested, fallback, source=source, explicit=explicit, notice=notice)


_ALTERNATIVES = {
    "bar": ("pie", "table"), "progress": ("pie", "bar"), "line": ("bar", "table"), "area": ("line", "bar"),
    "pie": ("bar", "table"), "donut": ("bar", "table"), "table": ("bar", "pie"), "kpi": ("bar", "table"),
    "gauge": ("bar", "table"), "waterfall": ("bar", "table"),
}


def alternative_kind(current_kind: str | None, allowed: tuple[str, ...] = ALLOWED_WIDGET_KINDS) -> str:
    """Outro formato possível para o mesmo dado ("mostra de outro jeito")."""
    for kind in _ALTERNATIVES.get(current_kind or "", ("bar", "table")):
        if kind in allowed and kind != current_kind:
            return kind
    return "table" if current_kind != "table" else "bar"


def detect(text: str, *, allowed: tuple[str, ...] = ALLOWED_WIDGET_KINDS,
           current_kind: str | None = None) -> ChartChoice | None:
    """Camada 1: dicionário. Nome explícito vence descrição; entre nomes, vale o último citado
    ("troque as barras por linha" -> linha)."""
    norm = normalize(text)
    if not norm:
        return None
    explicit_hits: list[tuple[int, str]] = []
    descriptive_hits: list[str] = []
    for code, pattern, explicit in _COMPILED:
        for m in pattern.finditer(norm):
            if explicit:
                explicit_hits.append((m.start(), code))
            elif code not in descriptive_hits:
                descriptive_hits.append(code)
    for word in re.findall(r"[a-z]{4,}", norm):
        if word in _FUZZY_SKIP or word in _FUZZY_WORDS:
            continue
        close = difflib.get_close_matches(word, list(_FUZZY_WORDS), n=1, cutoff=0.8)
        if close:
            explicit_hits.append((norm.index(word), _FUZZY_WORDS[close[0]]))
    if any(code == "bar_line" for _p, code in explicit_hits):
        return resolve("bar_line", allowed=allowed)
    if explicit_hits:
        code = max(explicit_hits)[1]
        return resolve(code, allowed=allowed, current_kind=current_kind)
    if descriptive_hits:
        return resolve(descriptive_hits[0], allowed=allowed, explicit=False)
    return None


def names_chart_format(text: str) -> bool:
    """True se a frase nomeia um formato de gráfico (pizza, barras, linha, medidor...)."""
    choice = detect(text)
    return bool(choice and choice.explicit and choice.requested in ROUTING_CODES)


CHART_INTENT_SCHEMA = {
    "type": "object",
    "required": ["chart"],
    "properties": {
        "chart": {
            "type": "string",
            "enum": ["pie", "donut", "bar", "line", "stacked_area", "table", "gauge", "waterfall", "none"],
            "description": "Formato que melhor atende o pedido; 'none' se o pedido não indicar formato.",
        },
    },
}

CHART_INTENT_PROMPT = """\
Classifique que formato de gráfico a pessoa quer ver. Ela pode não saber o nome dos gráficos.
- pie: quanto cada parte representa do total (participação, proporção).
- donut: como pie, em forma de anel.
- bar: comparar itens, os maiores, ranking.
- line: como algo mudou ao longo do tempo.
- stacked_area: composição de um total ao longo do tempo.
- table: lista, números exatos.
- gauge: um único percentual (ex.: quanto % foi para um país).
- waterfall: o que mais contribuiu para uma alta ou queda entre dois períodos.
- none: o pedido não indica formato.
Responda só com a ferramenta."""


def classify_with_llm(text: str) -> tuple[ChartChoice | None, int, int]:
    """Camada 2: 1 chamada curta ao LLM. Falha ou 'none' -> None (o gerador escolhe pela intenção)."""
    try:
        payload, in_tok, out_tok = call_structured_llm(
            system=CHART_INTENT_PROMPT,
            user_content=f"Pedido: {text}",
            tool_name="emit_chart_intent",
            tool_description="Registra o formato de gráfico pedido.",
            input_schema=CHART_INTENT_SCHEMA,
            max_tokens=100,
        )
    except Exception:
        return None, 0, 0
    code = str((payload or {}).get("chart") or "none")
    if code not in _CHARTS or code == "none":
        return None, in_tok, out_tok
    return resolve(code, source="llm", explicit=False), in_tok, out_tok


def interpret(text: str, *, use_llm: bool = True, current_kind: str | None = None) -> tuple[ChartChoice | None, int, int]:
    """Dicionário primeiro; LLM só se o dicionário não resolver. Devolve (escolha, tokens_in, tokens_out)."""
    choice = detect(text, current_kind=current_kind)
    if choice is not None or not use_llm:
        return choice, 0, 0
    return classify_with_llm(text)


# --- A9: tipos realmente suportados, para os prompts -------------------------------------

_KIND_HELP = {
    "kpi": "número de destaque",
    "bar": "comparar itens e rankings (os maiores); barras horizontais ordenadas para nomes longos",
    "line": "evolução ao longo do tempo",
    "area": "evolução com preenchimento; `stacked=true` para composição de um total ao longo do tempo",
    "progress": "participações em lista com barrinha (até 10 itens)",
    "table": "lista com os números exatos",
    "pie": "participação de cada parte no total (até 8 fatias, resto em 'Outros' calculado no SQL)",
    "donut": "como pizza, em forma de anel",
    "gauge": "um único percentual calculado dos dados (sem meta)",
    "waterfall": "contribuição de cada item para a variação entre dois períodos",
}


def kinds_for_prompt(allowed: tuple[str, ...] = ALLOWED_WIDGET_KINDS) -> str:
    """Lista dos tipos de componente suportados agora, com quando usar cada um."""
    return "\n".join(f"- `{k}`: {_KIND_HELP.get(k, k)}" for k in allowed)


CHOICE_BY_INTENT = """\
Sem tipo pedido pelo usuário, escolha pela intenção: participação -> pizza (se existir; senão barras \
horizontais); "maiores/principais" -> barras horizontais ordenadas; evolução -> linha; composição ao \
longo do tempo -> área empilhada; detalhe/lista -> tabela."""


# --- A3: gráfico que enganaria vira o adequado, com um aviso ---------------------------

_YEAR_NAMES = frozenset({"year", "ano"})


def misleading_share_reason(df: pd.DataFrame, x: str | None, y: str | None, unit: str = "") -> str | None:
    """Por que uma pizza/rosca enganaria com esses dados (frase simples), ou None se estiver ok."""
    from src.dashboard.validator import is_five_year_window_column, is_non_additive_column_or_unit

    if not x or not y or x not in df.columns or y not in df.columns:
        return None
    if x.strip().lower() in _YEAR_NAMES:
        return "Pizza não serve para comparar anos, então mostrei como linha ao longo do tempo."
    if "year" in df.columns and df["year"].nunique() > 1 and is_five_year_window_column(y, df):
        return ("Os anos não podem ser somados nesta medida (janela de 5 anos), então mostrei em barras "
                "em vez de pizza.")
    if is_non_additive_column_or_unit(y, unit, df):
        return ("Percentuais e médias não somam um total, então mostrei em barras em vez de pizza.")
    valores = pd.to_numeric(df[y], errors="coerce")
    if (valores < 0).any():
        return "Há valores negativos, que não cabem numa pizza, então mostrei em barras."
    return None


def apply_share_guards(spec, datasets) -> None:
    """Troca pizza/rosca enganosa pelo gráfico adequado e acrescenta UM aviso por troca."""
    by_id = {d.dataset_id: d for d in datasets}
    for w in spec.widgets:
        if w.kind not in ("pie", "donut") or w.dataset_id not in by_id:
            continue
        y = w.y[0] if w.y else None
        reason = misleading_share_reason(by_id[w.dataset_id].df, w.x, y, w.unit)
        if reason is None:
            continue
        w.kind = "line" if (w.x or "").strip().lower() in _YEAR_NAMES else "bar"
        if w.kind == "bar":
            w.orientation = "h"
        if reason not in spec.warnings:
            spec.warnings.append(reason)


# --- A8: sugerir outras formas de ver o mesmo dado -------------------------------------

_SUGGEST_LABEL = {"pie": "em pizza", "bar": "em barras", "table": "como lista", "line": "em linha",
                  "donut": "em rosca"}


def suggest_other_views(spec, allowed: tuple[str, ...] = ALLOWED_WIDGET_KINDS) -> str | None:
    """Frase curta oferecendo outros formatos possíveis para o gráfico principal."""
    main = next((w for w in spec.widgets if w.valid and w.kind != "kpi"), None)
    if main is None:
        return None
    options = [k for k in _ALTERNATIVES.get(main.kind, ("bar", "table")) if k in allowed and k != main.kind]
    labels = [_SUGGEST_LABEL[k] for k in options if k in _SUGGEST_LABEL][:2]
    if not labels:
        return None
    return f"Quer ver {' ou '.join(labels)}? É só pedir."

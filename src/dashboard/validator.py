"""Validador metodológico determinístico (em código) para especificações de dashboard.

Implementa a etapa 5 de `docs/PIPELINE_MULTIAGENTE.md` antes de qualquer chamada
ao LLM revisor, derivando as colunas de janela de 5 anos e as métricas não aditivas
diretamente dos catálogos (`src/data_dictionary.py`, `src/soy/territorial.py` e
`src/soy/catalog.py`).
"""

from __future__ import annotations

import re

import pandas as pd

from src.dashboard.schemas import DashboardSpec, DatasetResult, WidgetIssue, WidgetSpec
from src.data_dictionary import METRICS, TABLES
from src.soy.catalog import DEFAULT_SOY_MANIFEST
from src.soy.territorial import SOY_METRICS


def _derive_five_year_columns() -> frozenset[str]:
    """Deriva nomes de métricas e colunas com janela de 5 anos a partir dos dicionários."""
    cols: set[str] = set()

    for slug, (metric, _unit, desc, _additive) in METRICS.items():
        if "5_year" in slug.lower() or "5 anos" in desc.lower():
            cols.add(slug.lower())
            cols.add(metric.lower())

    for _table_name, _kind, _table_desc, table_cols in TABLES:
        for col_expr, col_desc in table_cols:
            if col_expr.strip().startswith("<"):
                continue
            desc_low = col_desc.lower()
            for raw_col in col_expr.split(","):
                cn = raw_col.strip().lower()
                if not cn:
                    continue
                if "5_year" in cn or "5 anos" in desc_low or (
                    "exposição" in desc_low and "zero_deforestation" not in cn
                ):
                    cols.add(cn)

    for slug, (metric, _unit, desc, _additive) in SOY_METRICS.items():
        if "5_year" in slug.lower() or "5y" in metric.lower() or "5 anos" in desc.lower():
            cols.add(slug.lower())
            cols.add(metric.lower())

    for entry in DEFAULT_SOY_MANIFEST:
        src_file = str(entry.get("source_file") or "").lower()
        for col in entry.get("columns") or ():
            cl = str(col).strip().lower()
            if "5_year" in cl or (
                "5_year" in src_file and cl not in {"year", "country", "region", "parent_region"}
            ):
                cols.add(cl)

    return frozenset(cols)


def _derive_non_additive_sets() -> tuple[frozenset[str], frozenset[str]]:
    """Deriva métricas não aditivas e percentuais a partir da flag `additive` dos catálogos."""
    non_additive: set[str] = set()
    percent_cols: set[str] = set()

    for _slug, (metric, unit, _desc, additive) in [*METRICS.items(), *SOY_METRICS.items()]:
        if not additive:
            m_low = metric.lower()
            non_additive.add(m_low)
            if "%" in unit:
                percent_cols.add(m_low)

    return frozenset(non_additive), frozenset(percent_cols)


FIVE_YEAR_WINDOW_COLUMNS: frozenset[str] = _derive_five_year_columns()
NON_ADDITIVE_COLUMNS, PERCENTAGE_COLUMNS = _derive_non_additive_sets()

_FIVE_YEAR_ALIAS_RE = re.compile(
    r"(?:5_year|_5y(?:_|$)|(?:^|_)exposure(?:_ha|_tco2e|_per_t)?$|gross_emissions_tco2e|deforestation_exposure)",
    re.IGNORECASE,
)
_PERCENT_COL_RE = re.compile(
    r"(?:^|_)(?:pct|perc|percent|percentual|porcentagem|share_pct)(?:$|_)",
    re.IGNORECASE,
)
_NON_ADDITIVE_ALIAS_RE = re.compile(
    r"(?:_per_|_por_|(?:^|_)(?:yield|produtividade|intensidade|intensity)(?:$|_)"
    r"|(?:^|_)pre[cç]o(?:_|$)|(?:^|_)price(?:_|$)"
    r"|(?:usd|brl|us\$|r\$)_(?:por_|per_)?(?:t|kt|ha|kg|ton)(?:$|_))",
    re.IGNORECASE,
)
_RATIO_UNIT_RE = re.compile(
    r"^\s*(?:ha|t|kt|kg|tco2e|co2e?|us\$|usd|r\$|brl)\s*/\s*(?:ha|t|kt|kg|ton|tonelada|ano|dia)s?\s*$",
    re.IGNORECASE,
)
_YEAR_COLUMNS = frozenset({"year", "ano"})
_MUNICIPALITY_COLUMNS = frozenset({"municipality", "municipality_of_production", "municipio", "município"})

# Isenta apenas ressalvas explícitas de negação (ex.: "exposição não é prova de ilegalidade").
_NEGATED_DISCLAIMER_RE = re.compile(
    r"\bn[aã]o\s+(?:[ée]\s+|constitui\s+|representa\s+)?"
    r"(?:prova|ind[ií]cio|evid[eê]ncia|atestado|sin[oô]nimo|confirma[cç][aã]o)?\s*(?:de\s+)?"
    r"(?:indica\s+|implica\s+|configura\s+|significa\s+|comprova\s+|demonstra\s+)?"
    r"(?:desmatamento\s+)?(?:ilegal\w*|crime\w*|culpa\w*|responsabil\w*)",
    re.IGNORECASE,
)

_ILLEGALITY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bilega(?:l|is|lidade|lmente)\b", re.IGNORECASE), "ilegal/ilegalidade"),
    (re.compile(r"\bcrimes?\b|\bcriminos[oa]s?\b", re.IGNORECASE), "crime"),
    (re.compile(r"\bculpad[oa]s?\b", re.IGNORECASE), "culpada/culpado"),
    (
        re.compile(
            r"\b(?:viol(?:ou|aram|a|am|a[cç][aã]o)|infring(?:iu|iram)|descumpri(?:u|ram))\s+"
            r"(?:a\s+|as\s+|da\s+|das\s+)?lei\b",
            re.IGNORECASE,
        ),
        "violou a lei",
    ),
    (
        re.compile(
            r"\b(?:respons[aá]ve(?:l|is)|autora?s?)\s+pelo\s+desmatamento\b"
            r"|\bautora?s?\s+do\s+desmatamento\b",
            re.IGNORECASE,
        ),
        "responsável pelo desmatamento",
    ),
)


def is_five_year_window_column(col: str | None, df: pd.DataFrame | None = None) -> bool:
    """True se a coluna (ou métrica em formato longo) representa exposição/emissões em janela de 5 anos."""
    if not col:
        return False
    cl = col.strip().lower()
    if cl in FIVE_YEAR_WINDOW_COLUMNS or bool(_FIVE_YEAR_ALIAS_RE.search(cl)):
        return True
    if cl == "value" and df is not None and "metric" in df.columns:
        metrics = {str(m).strip().lower() for m in df["metric"].dropna().unique()}
        return bool(metrics & FIVE_YEAR_WINDOW_COLUMNS) or any(
            bool(_FIVE_YEAR_ALIAS_RE.search(m)) for m in metrics
        )
    return False


def is_percentage_column_or_unit(
    col: str | None,
    unit: str | None = None,
    df: pd.DataFrame | None = None,
) -> bool:
    """True se a coluna ou unidade representa percentual (%)."""
    u = (unit or "").strip().lower()
    if "%" in u or u in {"pct", "perc", "percent", "percentual", "porcentagem"}:
        return True
    if not col:
        return False
    cl = col.strip().lower()
    if cl in PERCENTAGE_COLUMNS or bool(_PERCENT_COL_RE.search(cl)):
        return True
    if cl == "value" and df is not None:
        if "metric" in df.columns:
            metrics = {str(m).strip().lower() for m in df["metric"].dropna().unique()}
            if metrics & PERCENTAGE_COLUMNS:
                return True
        if "unit" in df.columns:
            units = {str(x).strip().lower() for x in df["unit"].dropna().unique()}
            if any("%" in x for x in units):
                return True
    return False


def is_non_additive_column_or_unit(
    col: str | None,
    unit: str | None = None,
    df: pd.DataFrame | None = None,
) -> bool:
    """True se a coluna ou unidade não pode ser somada entre regiões/entidades (%, intensidade, produtividade, preço/t)."""
    if is_percentage_column_or_unit(col, unit, df):
        return True
    if unit and _RATIO_UNIT_RE.match(unit):
        return True
    if not col:
        return False
    cl = col.strip().lower()
    if cl in NON_ADDITIVE_COLUMNS or bool(_NON_ADDITIVE_ALIAS_RE.search(cl)):
        return True
    if cl == "value" and df is not None and "metric" in df.columns:
        metrics = {str(m).strip().lower() for m in df["metric"].dropna().unique()}
        if metrics & NON_ADDITIVE_COLUMNS or any(bool(_NON_ADDITIVE_ALIAS_RE.search(m)) for m in metrics):
            return True
    return False


def distinct_year_count(df: pd.DataFrame) -> tuple[str | None, int]:
    """Devolve `(nome_da_coluna_de_ano, qtd_anos_distintos)` no DataFrame."""
    year_col = next((c for c in df.columns if c.strip().lower() in _YEAR_COLUMNS), None)
    if year_col is None or df.empty:
        return None, 0
    numeric = pd.to_numeric(df[year_col], errors="coerce").dropna()
    if not numeric.empty:
        return year_col, int(numeric.astype(int).nunique())
    cleaned = df[year_col].dropna().astype(str).str.strip()
    cleaned = cleaned[cleaned != ""]
    return year_col, int(cleaned.nunique())


def find_illegality_claim(text: str | None) -> str | None:
    """Se `text` contiver alegação de ilegalidade/crime/autoria de desmatamento, devolve o termo detectado."""
    if not text or not text.strip():
        return None
    sanitized = _NEGATED_DISCLAIMER_RE.sub(" ", text)
    for pattern, label in _ILLEGALITY_PATTERNS:
        if pattern.search(sanitized):
            return label
    return None


def _title_mentions_average(title: str | None) -> bool:
    if not title:
        return False
    return bool(re.search(r"\bm[eé]di[ao]s?\b", title, flags=re.IGNORECASE))


def validate_widget_methodological(
    w: WidgetSpec,
    ds: DatasetResult | None,
) -> list[WidgetIssue]:
    """Aplica as regras metodológicas bloqueantes (R5-a, R5-b, R5-c, R5-e por widget) em código."""
    issues: list[WidgetIssue] = []

    for field_label, text_val in (("título", w.title), ("subtítulo", w.subtitle)):
        claim = find_illegality_claim(text_val)
        if claim:
            issues.append(WidgetIssue(
                w.id,
                "methodological",
                f"O {field_label} do componente contém alegação indevida ('{claim}'). "
                "Os dados do Trase medem apenas exposição associada à cadeia, não ilegalidade ou autoria direta; "
                "reescreva usando 'exposição ao desmatamento'.",
                code="alegacao",
            ))

    if ds is None or ds.df.empty:
        return issues

    df = ds.df
    year_col, n_years = distinct_year_count(df)

    # R5-a e R5-c: regras para KPI
    if w.kind == "kpi" and w.column and w.column in df.columns:
        if w.agg in ("sum", "mean") and n_years > 1 and is_five_year_window_column(w.column, df):
            issues.append(WidgetIssue(
                w.id,
                "methodological",
                f"KPI não pode usar agg='{w.agg}' sobre '{w.column}' em {w.dataset_id} porque o dataset "
                f"contém {n_years} anos distintos ({year_col}) e o indicador usa janela móvel de 5 anos "
                "(janelas sobrepostas contariam o mesmo desmatamento várias vezes). Filtre um único ano.",
                code="janela_5_anos",
            ))

        if w.agg == "sum" and is_non_additive_column_or_unit(w.column, w.unit, df):
            issues.append(WidgetIssue(
                w.id,
                "methodological",
                f"KPI não pode somar (agg='sum') a coluna não aditiva '{w.column}' (unidade '{w.unit}'). "
                "Percentuais, intensidades e produtividade não se somam entre regiões ou entidades.",
                code="soma_percentual",
            ))
        elif (
            w.agg == "mean"
            and is_percentage_column_or_unit(w.column, w.unit, df)
            and not _title_mentions_average(w.title)
        ):
            issues.append(WidgetIssue(
                w.id,
                "methodological",
                f"KPI com agg='mean' sobre percentual ('{w.column}') só é permitido quando o título "
                "indica explicitamente tratar-se de 'média' simples.",
                code="media_percentual",
            ))

    # R5-b: gráficos bar/line com coluna y de janela de 5 anos em dataset multianual
    elif w.kind in ("bar", "line") and w.y and n_years > 1:
        five_year_ys = [col for col in w.y if col in df.columns and is_five_year_window_column(col, df)]
        if five_year_ys:
            x_is_year = bool(w.x and w.x.strip().lower() in _YEAR_COLUMNS)
            color_is_year = bool(w.color and w.color.strip().lower() in _YEAR_COLUMNS)
            if not x_is_year and not color_is_year:
                cols_str = ", ".join(five_year_ys)
                issues.append(WidgetIssue(
                    w.id,
                    "methodological",
                    f"Gráfico '{w.kind}' não pode agregar indicador de janela de 5 anos ({cols_str}) "
                    f"num dataset com {n_years} anos distintos sem separar por ano em 'x' ou 'color' "
                    "nem filtrar um único ano (série anual é permitida; total multianual é bloqueado).",
                    code="janela_5_anos",
                ))

    # R5-b: exibir o percentual de cada grupo é permitido; SOMAR (empilhar) percentuais ou
    # intensidades entre grupos não é.
    stacks = (w.kind == "bar" and w.barmode == "stack" and bool(w.color or len(w.y) > 1)) or (
        w.kind == "line" and w.stacked
    )
    if stacks and any(c in df.columns and is_non_additive_column_or_unit(c, w.unit, df) for c in w.y):
        issues.append(WidgetIssue(
            w.id,
            "methodological",
            f"Gráfico empilhado soma percentuais/intensidades entre grupos ({', '.join(w.y)}).",
            code="soma_percentual",
        ))

    return issues


def _is_soy_context(w: WidgetSpec, ds: DatasetResult) -> bool:
    if ds.database == "soy.duckdb" or ds.tool_name.startswith("soy_") or ds.tool_name == "run_soy_sql":
        return True
    haystack = f"{ds.source_label} {ds.query_summary} {w.source} {w.title}".lower()
    if "soja" in haystack or "soy" in haystack:
        return True
    return any(str(c).lower().startswith("soy_") for c in ds.df.columns)


def _widget_slice(df: pd.DataFrame, w: WidgetSpec) -> pd.DataFrame:
    out = df
    if w.sort_by and w.sort_by in out.columns:
        out = out.sort_values(by=w.sort_by, ascending=w.ascending, na_position="last")
    if w.top_n:
        out = out.head(w.top_n)
    elif w.kind == "table":
        out = out.head(50)
    return out


def validate_spec_methodological(
    spec: DashboardSpec,
    datasets_by_id: dict[str, DatasetResult],
) -> list[WidgetIssue]:
    """Valida metadados gerais do `DashboardSpec` (R5-e) e acrescenta avisos não bloqueantes (R5-d)."""
    issues: list[WidgetIssue] = []

    for field_label, text_val in (("título do painel", spec.title), ("subtítulo do painel", spec.subtitle)):
        claim = find_illegality_claim(text_val)
        if claim:
            issues.append(WidgetIssue(
                None,
                "methodological",
                f"O {field_label} contém alegação indevida ('{claim}'). "
                "Substitua por linguagem neutra baseada em 'exposição ao desmatamento'.",
                code="alegacao",
            ))

    for warn_msg in list(spec.warnings):
        claim = find_illegality_claim(warn_msg)
        if claim:
            issues.append(WidgetIssue(
                None,
                "methodological",
                f"Um aviso do painel contém alegação indevida ('{claim}'). "
                "Substitua por linguagem neutra baseada em 'exposição ao desmatamento'.",
                code="alegacao",
            ))

    # R5-d: rankings municipais da cadeia da soja com linhas UNKNOWN -> aviso em spec.warnings (não bloqueia)
    for w in spec.widgets:
        if w.kind not in ("bar", "table", "line"):
            continue
        ds = datasets_by_id.get(w.dataset_id)
        if ds is None or ds.df.empty or not _is_soy_context(w, ds):
            continue
        muni_col = next((c for c in ds.df.columns if c.strip().lower() in _MUNICIPALITY_COLUMNS), None)
        if muni_col is None:
            continue
        # Se for bar/line, confirma que a dimensão municipal participa ou que o dataset é um ranking municipal
        if w.kind in ("bar", "line") and w.x and w.x != muni_col:
            continue
        sliced = _widget_slice(ds.df, w)
        values = sliced[muni_col].dropna().astype(str).str.strip().str.upper()
        if (values == "UNKNOWN").any() or values.str.startswith("UNKNOWN ").any():
            msg = (
                f"“{w.title or 'Ranking de municípios'}” inclui volume de origem não identificada "
                "(município não rastreado); essa linha aparece no fim."
            )
            if msg not in spec.warnings:
                spec.warnings.append(msg)

    return issues

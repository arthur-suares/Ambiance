"""Base de cada conjunto de dados do painel (ano, origem rastreada, fluxo) e coerência entre widgets.

A base é lida em código: dos anos presentes no DataFrame e dos filtros escritos na consulta
(`year = 2022`, `<> 'UNKNOWN'`, `<> 'BRAZIL'`...). A IA não escreve nem a base nem a frase.
Quando os widgets de um painel usam bases diferentes (ex.: KPI só com origem rastreada e pizza com
todas as origens), cada widget recebe no subtítulo a frase da base usada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from src.dashboard.schemas import DashboardSpec, DatasetResult, WidgetIssue

BASE_PREFIX = "Base:"

_YEAR_COLS = ("year", "ano")
_YEAR_EQ_RE = re.compile(r"\byear\b\s*(?:AS\s+\w+\s*\))?\s*=\s*'?(\d{4})", re.IGNORECASE)
_YEAR_IN_RE = re.compile(r"\byear\b\s*(?:AS\s+\w+\s*\))?\s*IN\s*\(([^)]*)\)", re.IGNORECASE)
_YEAR_BETWEEN_RE = re.compile(r"\byear\b\s*(?:AS\s+\w+\s*\))?\s*BETWEEN\s*'?(\d{4})'?\s*AND\s*'?(\d{4})",
                              re.IGNORECASE)
_NOT_UNKNOWN_RE = re.compile(r"(?:<>|!=)\s*'UNKNOWN[^']*'|NOT\s+IN\s*\([^)]*'UNKNOWN", re.IGNORECASE)
_NOT_DOMESTIC_RE = re.compile(
    r"(?:<>|!=)\s*'(?:BRAZIL|DOMESTIC PROCESSING AND CONSUMPTION)'|NOT\s+IN\s*\([^)]*'(?:BRAZIL|DOMESTIC)",
    re.IGNORECASE)
_SUPPLY_TABLE_RE = re.compile(r"\b(?:soy_)?supply_chain\b", re.IGNORECASE)
# Consultas prontas que já excluem a origem não identificada (ver CAVEATS: top_municipalities).
_TRACKED_QUERIES = ("top_municipalities",)


@dataclass(frozen=True)
class DataBase:
    years: tuple[int, ...] | None = None   # anos presentes ou filtrados
    origin: str | None = None              # "rastreada" | "toda"
    flow: str | None = None                # "exportacao" | "cadeia"

    def is_empty(self) -> bool:
        return self.years is None and self.origin is None and self.flow is None


def _years_from_df(df: pd.DataFrame) -> tuple[int, ...] | None:
    col = next((c for c in df.columns if str(c).lower() in _YEAR_COLS), None)
    if col is None:
        return None
    anos = sorted({int(v) for v in pd.to_numeric(df[col], errors="coerce").dropna()})
    return tuple(anos) or None


def _years_from_query(q: str) -> tuple[int, ...] | None:
    m = _YEAR_BETWEEN_RE.search(q)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return tuple(range(min(a, b), max(a, b) + 1))
    m = _YEAR_IN_RE.search(q)
    if m:
        anos = sorted({int(v) for v in re.findall(r"\d{4}", m.group(1))})
        return tuple(anos) or None
    anos = sorted({int(v) for v in _YEAR_EQ_RE.findall(q)})
    if len(anos) == 1:
        return tuple(anos)
    m = re.search(r'"year"\s*:\s*(\d{4})', q)  # consulta pronta: nome({"year": 2022, ...})
    return (int(m.group(1)),) if m else None


def _has_unknown_rows(df: pd.DataFrame) -> bool:
    for c in df.columns:
        if df[c].dtype == object and df[c].astype(str).str.upper().str.startswith("UNKNOWN").any():
            return True
    return False


def infer_base(ds: DatasetResult) -> DataBase:
    """Base do conjunto de dados, lida da tabela e da consulta. Campo desconhecido fica None."""
    q = ds.query_summary or ""
    years = _years_from_df(ds.df) or _years_from_query(q)
    is_sql = ds.tool_name in ("run_sql", "run_soy_sql")
    origin = flow = None
    if _has_unknown_rows(ds.df):
        origin = "toda"
    elif _NOT_UNKNOWN_RE.search(q) or ds.tool_name in _TRACKED_QUERIES:
        origin = "rastreada"
    elif is_sql and _SUPPLY_TABLE_RE.search(q):
        origin = "toda"
    if _NOT_DOMESTIC_RE.search(q):
        flow = "exportacao"
    elif is_sql and _SUPPLY_TABLE_RE.search(q):
        flow = "cadeia"
    return DataBase(years=years, origin=origin, flow=flow)


def base_phrase(base: DataBase) -> str | None:
    """Frase simples da base: "Base: exportações com origem rastreada de 2022." """
    if base.is_empty():
        return None
    sujeito = {"exportacao": "exportações", "cadeia": "toda a cadeia (com o consumo no Brasil)"}.get(
        base.flow or "", "dados")
    partes = []
    if base.origin == "rastreada":
        partes.append("com origem rastreada")
    elif base.origin == "toda":
        partes.append("incluindo origem não identificada")
    if base.years:
        a, b = base.years[0], base.years[-1]
        partes.append(f"de {a}" if a == b else f"de {a} a {b}")
    if sujeito == "dados" and not partes:
        return None
    return f"{BASE_PREFIX} {' '.join([sujeito, *partes])}."


def _widget_bases(spec: DashboardSpec, datasets: list[DatasetResult]) -> dict[str, DataBase]:
    by_id = {d.dataset_id: d for d in datasets}
    return {w.id: infer_base(by_id[w.dataset_id]) for w in spec.widgets
            if w.valid and w.dataset_id in by_id}


def differing_fields(bases: dict[str, DataBase]) -> list[str]:
    """Campos em que os widgets do painel discordam. Ano só se compara entre recortes de um único ano
    (uma série histórica ao lado de um ranking do último ano não é base diferente)."""
    campos = []
    origens = {b.origin for b in bases.values() if b.origin}
    fluxos = {b.flow for b in bases.values() if b.flow}
    anos = {b.years[0] for b in bases.values() if b.years and len(b.years) == 1}
    if len(anos) > 1:
        campos.append("ano")
    if len(origens) > 1:
        campos.append("origem")
    if len(fluxos) > 1:
        campos.append("fluxo")
    return campos


def check_common_base(spec: DashboardSpec, datasets: list[DatasetResult]) -> list[WidgetIssue]:
    """Revisor: avisa (sem bloquear) quando os widgets do painel usam bases diferentes."""
    bases = _widget_bases(spec, datasets)
    campos = differing_fields(bases)
    if not campos:
        return []
    detalhe = "; ".join(f"{wid}: {base_phrase(b) or 'base desconhecida'}" for wid, b in bases.items())
    return [WidgetIssue(None, "deterministic",
                        f"Widgets com bases diferentes ({', '.join(campos)}): {detalhe}",
                        code="base_diferente", blocking=False)]


def declare_bases(spec: DashboardSpec, datasets: list[DatasetResult]) -> list[str]:
    """Se as bases diferem, escreve no subtítulo de cada widget a frase da base usada.

    Devolve os ids dos widgets que receberam a frase."""
    bases = _widget_bases(spec, datasets)
    if not differing_fields(bases):
        return []
    marcados = []
    for w in spec.widgets:
        frase = base_phrase(bases[w.id]) if w.id in bases else None
        if not frase or BASE_PREFIX in (w.subtitle or ""):
            continue
        w.subtitle = f"{w.subtitle.rstrip()} {frase}".strip() if w.subtitle else frase
        marcados.append(w.id)
    return marcados


def common_base_line(common: dict | None) -> str | None:
    """Linha para o Agente de Dados com a base comum definida pelo planejador."""
    if not common:
        return None
    partes = []
    if common.get("year"):
        partes.append(f"ano {int(common['year'])} em TODAS as consultas de um único ano")
    if common.get("origin") == "rastreada":
        partes.append("só origem rastreada (exclua 'UNKNOWN' da origem) em todas as consultas")
    elif common.get("origin") == "toda":
        partes.append("todas as origens, incluindo 'UNKNOWN', em todas as consultas")
    if common.get("flow") == "exportacao":
        partes.append("só exportação (exclua BRAZIL / consumo doméstico) em todas as consultas")
    elif common.get("flow") == "cadeia":
        partes.append("cadeia inteira, incluindo o consumo no Brasil, em todas as consultas")
    if not partes:
        return None
    return ("BASE COMUM do painel (KPIs, pizza, ranking e tabela usam o mesmo filtro e o mesmo denominador): "
            + "; ".join(partes) + ". Se uma consulta não puder seguir essa base, diga qual base usou no resumo.")


__all__ = ["DataBase", "base_phrase", "check_common_base", "common_base_line", "declare_bases",
           "differing_fields", "infer_base"]

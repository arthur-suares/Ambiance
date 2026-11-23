"""Glossário de entidades: a palavra que o usuário usa -> a coluna de agrupamento dos dados.

"municípios exportadores" é município (o adjetivo "exportadores" descreve o município); "exportadores",
"empresas", "tradings" e "quem exporta" são grupos exportadores; "para onde vai" é o país de destino.
Usado pelo roteador (edição x painel novo), pelo planejador, pelo Agente de Dados e pelo revisor.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str                      # para a tela: "município", "empresa"...
    columns: tuple[str, ...]        # colunas nos bancos (soja e carne)
    tokens: tuple[str, ...]         # começos de palavra que identificam a coluna num nome qualquer


DIMENSIONS: dict[str, Dimension] = {
    "municipio": Dimension("municipio", "município", ("municipality_of_production",),
                           ("muni", "cidade")),
    "porto": Dimension("porto", "porto", ("port_of_export",), ("port", "porto")),
    "destino": Dimension("destino", "país de destino", ("country_of_first_import", "country_of_destination"),
                         ("country", "destin", "pais")),
    "importador": Dimension("importador", "importador", ("importer_group", "importer"),
                            ("importer", "importador")),
    "empresa": Dimension("empresa", "empresa", ("exporter_group", "exporter"),
                         ("exporter", "exportador", "empresa", "trading")),
    "estado": Dimension("estado", "estado", ("state", "state_of_production"), ("state", "estado", "uf")),
    "bioma": Dimension("bioma", "bioma", ("biome",), ("biome", "bioma")),
}

# Ordem importa: município antes de empresa ("municípios exportadores" é município).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((k, re.compile(p)) for k, p in (
    ("municipio", r"\bmunicip\w*|\bcidades?\b|\bde onde vem\b"),
    ("porto", r"\bportos?\b"),
    ("destino", r"\bdestinos?\b|\bpara onde vai\b|\bpara onde vao\b|\bpais(?:es)?\b"),
    ("importador", r"\bimportador\w*|\bcomprador\w*"),
    ("empresa", r"\bexportador\w*|\bempresas?\b|\btradings?\b|\bgrupos?\b|\bquem exporta\w*"),
    ("estado", r"\bestados?\b|\bufs?\b"),
    ("bioma", r"\bbiomas?\b"),
))
_ORIGIN_RE = re.compile(r"\borigem\b")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def detect_dimension(text: str) -> Dimension | None:
    """Dimensão de agrupamento pedida no texto, ou None. "origem" sozinha vale como município."""
    norm = _norm(text)
    for key, pattern in _PATTERNS:
        if pattern.search(norm):
            return DIMENSIONS[key]
    if _ORIGIN_RE.search(norm):
        return DIMENSIONS["municipio"]
    return None


def column_matches(col: str | None, dim: Dimension) -> bool:
    """A coluna (com qualquer apelido do SQL) é da dimensão? "municipality" e "municipio" valem."""
    if not col:
        return False
    low = col.lower()
    if low in dim.columns:
        return True
    partes = re.split(r"[^a-z0-9]+", _norm(low))
    return any(p.startswith(t) for p in partes if p for t in dim.tokens)


def aliased_from(col: str | None, dim: Dimension, query: str) -> bool:
    """O SQL renomeou a coluna da dimensão para `col` ("municipality_of_production AS m")?"""
    if not col or not query:
        return False
    origem = "|".join(re.escape(c) for c in dim.columns)
    return bool(re.search(rf"\b(?:{origem})\b\s+AS\s+\"?{re.escape(col)}\"?(?![\w])", query, re.IGNORECASE))


def columns_cover(columns, dim: Dimension) -> bool:
    return any(column_matches(str(c), dim) for c in columns)


GLOSSARY_PROMPT = """\
Glossário de entidades (palavra do usuário -> coluna de agrupamento):
- "município", "municípios exportadores", "maiores municípios", "de onde vem a soja", "origem" -> \
municipality_of_production (só origem rastreada: exclua 'UNKNOWN'). Em "municípios exportadores", \
"exportadores" descreve o município: NÃO troque para empresa.
- "exportador", "empresa", "trading", "grupo", "quem exporta" -> exporter_group.
- "porto" -> port_of_export.
- "destino", "país", "para onde vai" -> country_of_first_import (soja) ou country_of_destination (carne).
- "importador", "comprador" -> importer_group.
- "estado"/"UF" -> state (soja) ou state_of_production (carne); "bioma" -> biome."""


def dimension_line(dim: Dimension | None) -> str | None:
    """Linha para o planejador e o Agente de Dados com a dimensão pedida."""
    if dim is None:
        return None
    cols = " ou ".join(dim.columns)
    extra = " Só a origem rastreada (exclua 'UNKNOWN')." if dim.key == "municipio" else ""
    return (f"DIMENSÃO PEDIDA: {dim.label} (coluna {cols}). O gráfico principal DEVE agrupar por essa "
            f"coluna.{extra}")


__all__ = ["DIMENSIONS", "Dimension", "GLOSSARY_PROMPT", "column_matches", "columns_cover",
           "detect_dimension", "dimension_line"]

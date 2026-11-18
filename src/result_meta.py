"""Legenda dos resultados das consultas prontas.

Cada consulta anexa ao DataFrame (em df.attrs["meta"]) o que o CSV sozinho não diz: cadeia, escopo
(fluxos da cadeia x indicador territorial), ano, agrupamento, ordenação, filtros, exclusões e unidades.
O agente escreve essa legenda antes do CSV (linhas iniciadas por "# "), para que o LLM e o juiz da
avaliação leiam o resultado com o mesmo significado que o SQL lhe deu.
"""

from __future__ import annotations

import pandas as pd

META_PREFIX = "# "

FLOWS = "fluxos da cadeia (soma dos fluxos rastreados pelo Trase; não é o indicador territorial da região)"
TERRITORIAL = "indicador territorial (descreve a região inteira; não são fluxos da cadeia)"
FACILITIES = "instalações (cadastro de estabelecimentos; não são fluxos da cadeia)"
FREE_SQL = "consulta SQL livre (unidade e significado dependem das colunas escolhidas na consulta)"

WINDOW_5Y = "exposição/emissões usam janela de 5 anos: compare anos lado a lado, não some entre anos"
RANKING_NOTE = ("ranking limitado às primeiras linhas pela ordenação indicada: ele só mostra quem lidera NESSA "
                "métrica; para outra métrica, refaça a consulta com outro order_by")


POSITION_NOTE = ("posicao = lugar da região no ranking por {col}, entre as regiões identificadas (1 = maior), calculado "
                 "sobre todas as regiões do ano, mesmo com filtro; a origem não rastreada (UNKNOWN) fica sem posição")


def add_position(df: pd.DataFrame, label_col: str, value_col: str) -> pd.DataFrame:
    """Põe na frente a coluna posicao (1 = maior value_col), sem contar as linhas UNKNOWN, que ficam vazias.

    Assim o LLM lê quem lidera em vez de comparar números parecidos (ex.: 298.765 x 293.949 ha).
    Chame antes de filtrar uma região, para a posição continuar sendo a do ranking completo.
    """
    known = ~df[label_col].astype(str).str.upper().str.startswith("UNKNOWN")
    pos = df[value_col].where(known).rank(ascending=False, method="min")
    df.insert(0, "posicao", pos.astype("Int64"))
    return df


def attach(df: pd.DataFrame, *, cadeia: str, escopo: str, ano=None, agrupado_por: str | None = None,
           ordenado_por: str | None = None, filtros: dict | None = None, excluidos: list[str] | None = None,
           unidades: dict | None = None, notas: list[str] | None = None) -> pd.DataFrame:
    df.attrs["meta"] = {
        "cadeia": cadeia, "escopo": escopo, "ano": ano, "agrupado_por": agrupado_por, "ordenado_por": ordenado_por,
        "filtros": {k: v for k, v in (filtros or {}).items() if v not in (None, "")},
        "excluidos": list(excluidos or []), "unidades": dict(unidades or {}), "notas": list(notas or []),
    }
    return df


def render(meta: dict | None) -> str:
    """Legenda em texto, uma informação por linha, cada linha iniciada por '# '. Vazio se não houver meta."""
    if not meta:
        return ""
    lines = [f"cadeia: {meta['cadeia']} | escopo: {meta['escopo']}"]
    if meta.get("ano") is not None:
        lines.append(f"ano: {meta['ano']}")
    if meta.get("agrupado_por"):
        lines.append(f"agrupado por: {meta['agrupado_por']}")
    if meta.get("ordenado_por"):
        lines.append(f"ordenado por: {meta['ordenado_por']}")
    if "filtros" in meta:
        filtros = "; ".join(f"{k} = {v}" for k, v in meta["filtros"].items())
        lines.append(f"filtros: {filtros or 'nenhum'}")
    if meta.get("excluidos"):
        lines.append("excluídos do resultado: " + "; ".join(meta["excluidos"]))
    if meta.get("unidades"):
        lines.append("unidades: " + "; ".join(f"{k} = {v}" for k, v in meta["unidades"].items()))
    lines += [f"nota: {n}" for n in meta.get("notas") or []]
    return "\n".join(META_PREFIX + line for line in lines)


def strip_meta(text: str) -> str:
    """Tira as linhas de legenda de uma saída de ferramenta (para ler só os dados)."""
    return "\n".join(line for line in (text or "").splitlines() if not line.startswith(META_PREFIX.strip()))

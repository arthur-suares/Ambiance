"""Integração do contexto da aba Dados (gráficos e tabelas da resposta) com o Painel completo.

Garante que o Painel completo seja sempre um superconjunto da aba Dados:
1. Envia um resumo dos gráficos e tabelas da resposta nos prompts do Orquestrador e do Agente de Dashboard.
2. Antes da renderização, verifica deterministicamente se cada gráfico da aba Dados tem equivalente no
   DashboardSpec (mesma métrica e ordenação); caso algum tenha faltado, anexa o dataset e o componente
   equivalente sem alterar os demais gráficos gerados pelo agente.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

from src.dashboard.schemas import DashboardSpec, DatasetResult, WidgetSpec

_STOPWORDS = frozenset({
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "por", "para", "com", "sem",
    "os", "as", "um", "uma", "ao", "aos", "entre", "sobre", "mais", "maior", "maiores", "top",
    "grafico", "gráfico", "evolucao", "evolução", "ranking", "comparacao", "comparação",
})


def _norm_text(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _norm_text(text).split() if len(t) >= 3 and t not in _STOPWORDS}


def normalize_chat_context(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """Normaliza o payload opcional `context` enviado pelo studio (`charts` e `tables`)."""
    if not isinstance(raw, dict):
        return {"charts": [], "tables": []}

    charts_out: list[dict[str, Any]] = []
    for item in (raw.get("charts") or [])[:6]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:140]
        labels = [str(x).strip() for x in (item.get("labels") or [])[:40]]
        series_out: list[dict[str, Any]] = []
        for s in (item.get("series") or [])[:6]:
            if not isinstance(s, dict):
                continue
            vals = s.get("values")
            if not isinstance(vals, list):
                continue
            nums: list[float | None] = []
            for v in vals[:len(labels) or 40]:
                try:
                    nums.append(None if v is None else float(v))
                except (TypeError, ValueError):
                    nums.append(None)
            if any(v is not None for v in nums):
                series_out.append({
                    "name": str(s.get("name") or "Valor").strip()[:80],
                    "values": nums,
                })
        if title or (labels and series_out):
            charts_out.append({
                "title": title or "Gráfico da resposta",
                "subtitle": str(item.get("subtitle") or "").strip()[:180],
                "chart_type": str(item.get("chart_type") or "bar").strip().lower(),
                "x_label": str(item.get("x_label") or "").strip()[:60],
                "y_label": str(item.get("y_label") or "").strip()[:60],
                "unit": str(item.get("unit") or "").strip()[:30],
                "labels": labels,
                "series": series_out,
            })

    tables_out: list[dict[str, Any]] = []
    for item in (raw.get("tables") or [])[:8]:
        if not isinstance(item, dict):
            continue
        purpose = str(item.get("purpose") or "").strip()[:160]
        cols = [str(c).strip() for c in (item.get("columns") or [])[:20] if str(c).strip()]
        rows = item.get("rows") if isinstance(item.get("rows"), list) else []
        if purpose or cols:
            tables_out.append({
                "label": str(item.get("label") or "").strip()[:24],
                "purpose": purpose,
                "columns": cols,
                "row_count": len(rows),
            })

    return {"charts": charts_out, "tables": tables_out}


def format_chat_context_prompt(raw_context: Any) -> str:
    """Formata o contexto da aba Dados para os prompts do Orquestrador e do Agente de Dashboard."""
    ctx = normalize_chat_context(raw_context)
    charts, tables = ctx["charts"], ctx["tables"]
    if not charts and not tables:
        return ""

    lines = [
        "Contexto da aba Dados já exibida na resposta do chat (o Painel completo DEVE ser um "
        "SUPERCONJUNTO da aba Dados — inclua um gráfico equivalente a cada gráfico abaixo, com a "
        "mesma métrica e ordenação, e complemente com KPIs e gráficos adicionais de outros tipos):"
    ]
    for idx, ch in enumerate(charts, start=1):
        series_names = ", ".join(s["name"] for s in ch["series"]) or ch["y_label"] or "valor"
        unit = f" ({ch['unit']})" if ch["unit"] else ""
        sample = ", ".join(ch["labels"][:5])
        sample_txt = f"; primeiros rótulos na ordem: {sample}" if sample else ""
        lines.append(
            f"- Gráfico Dados #{idx}: título='{ch['title']}', tipo={ch['chart_type']}, "
            f"métrica={series_names}{unit}{sample_txt}."
        )
    for idx, tb in enumerate(tables, start=1):
        cols_txt = ", ".join(tb["columns"][:8])
        lines.append(
            f"- Tabela Dados #{idx}: '{tb['purpose'] or tb['label']}' "
            f"({tb['row_count']} linhas; colunas: {cols_txt})."
        )
    return "\n".join(lines)


def _kind_family(chart_type: str) -> set[str]:
    ct = (chart_type or "").lower()
    if ct in ("line", "area"):
        return {"line", "area"}
    if ct in ("doughnut", "donut", "pie"):
        return {"donut", "pie", "progress"}
    return {"bar", "progress"}


def _has_equivalent_widget(
    chat_chart: dict[str, Any],
    spec: DashboardSpec,
    by_id: dict[str, DatasetResult],
) -> bool:
    """Verifica se `spec` já contém um gráfico válido equivalente ao gráfico da aba Dados."""
    target_labels = [_norm_text(x) for x in chat_chart.get("labels") or [] if _norm_text(x)]
    target_tokens = _tokens(
        " ".join([
            chat_chart.get("title", ""),
            chat_chart.get("y_label", ""),
            *(s.get("name", "") for s in chat_chart.get("series") or []),
        ])
    )
    wanted_kinds = _kind_family(chat_chart.get("chart_type", "bar"))

    for w in spec.widgets:
        if not w.valid or w.kind not in wanted_kinds:
            continue
        ds = by_id.get(w.dataset_id)
        if ds is None or ds.df.empty:
            continue

        # 1) Sobreposição de rótulos no eixo x + coerência de métrica/unidade
        label_match = False
        if target_labels and w.x and w.x in ds.df.columns:
            w_labels = {_norm_text(v) for v in ds.df[w.x].dropna().tolist()}
            overlap = sum(1 for lbl in target_labels if any(lbl in wl or wl in lbl for wl in w_labels if wl))
            if overlap >= max(2, int(len(target_labels) * 0.5)):
                label_match = True

        w_tokens = _tokens(" ".join([w.title, w.subtitle, *w.y, *w.column_labels.values()]))
        token_overlap = len(target_tokens & w_tokens)
        unit_chat = _norm_text(chat_chart.get("unit", ""))
        unit_w = _norm_text(w.unit)
        unit_compatible = (not unit_chat) or (not unit_w) or (unit_chat == unit_w) or (unit_chat in unit_w) or (unit_w in unit_chat)

        if label_match and unit_compatible and (token_overlap >= 1 or not target_tokens):
            return True
        if target_tokens and token_overlap >= max(2, int(len(target_tokens) * 0.6)) and unit_compatible:
            return True
    return False


def _next_dataset_id(datasets: list[DatasetResult]) -> str:
    nums = [int(d.dataset_id[1:]) for d in datasets if str(d.dataset_id).startswith("D") and str(d.dataset_id)[1:].isdigit()]
    return f"D{(max(nums) if nums else 0) + 1}"


def _map_chart_kind(chart_type: str) -> tuple[str, str]:
    ct = (chart_type or "bar").lower()
    if ct == "horizontal_bar":
        return "bar", "h"
    if ct == "line":
        return "line", "v"
    if ct == "area":
        return "area", "v"
    if ct in ("doughnut", "donut"):
        return "donut", "v"
    if ct == "pie":
        return "pie", "v"
    return "bar", "v"


def ensure_dados_charts_included(
    spec: DashboardSpec,
    datasets: list[DatasetResult],
    raw_context: Any,
    *,
    domain: str = "agro",
) -> int:
    """Garante deterministicamente que cada gráfico da aba Dados tenha um equivalente no Painel completo.

    Retorna a quantidade de gráficos da aba Dados anexados automaticamente.
    """
    ctx = normalize_chat_context(raw_context)
    if not ctx["charts"]:
        return 0

    by_id = {d.dataset_id: d for d in datasets}
    existing_ids = {w.id for w in spec.widgets}
    db_name = "soy.duckdb" if domain == "soy" else "trase.duckdb"
    if datasets:
        db_name = datasets[0].database

    added = 0
    insert_pos = sum(1 for w in spec.widgets if w.kind in ("kpi", "gauge"))

    for idx, ch in enumerate(ctx["charts"], start=1):
        labels = ch["labels"]
        series = ch["series"]
        if not labels or not series:
            continue
        if _has_equivalent_widget(ch, spec, by_id):
            continue

        # Monta DataFrame exatamente na ordem e com os números do gráfico da aba Dados.
        n_rows = min(len(labels), *(len(s["values"]) for s in series))
        if n_rows < 2:
            continue
        x_col = "categoria"
        data_dict: dict[str, list[Any]] = {x_col: labels[:n_rows]}
        y_cols: list[str] = []
        col_labels: dict[str, str] = {}
        if ch["x_label"]:
            col_labels[x_col] = ch["x_label"]
        for s_i, s in enumerate(series, start=1):
            col_name = f"serie_{s_i}"
            data_dict[col_name] = s["values"][:n_rows]
            y_cols.append(col_name)
            col_labels[col_name] = s["name"] or ch["y_label"] or "Valor"

        df = pd.DataFrame(data_dict)
        ds_id = _next_dataset_id(datasets)
        ds = DatasetResult(
            dataset_id=ds_id,
            database=db_name,
            source_label="Trase — Dados da resposta (aba Dados)",
            tool_name="chat_context_chart",
            query_summary=f"Série da aba Dados: {ch['title']}",
            df=df,
            purpose=ch["title"],
        )
        datasets.append(ds)
        by_id[ds_id] = ds

        kind, orient = _map_chart_kind(ch["chart_type"])
        wid = f"dados_chart_{idx}"
        while wid in existing_ids:
            wid = f"{wid}_x"
        existing_ids.add(wid)

        unit = ch["unit"] or "unid."
        widget = WidgetSpec(
            id=wid,
            kind=kind,
            title=ch["title"],
            subtitle=ch["subtitle"] or "Mesma métrica e ordenação exibidas na aba Dados.",
            dataset_id=ds_id,
            unit=unit,
            source=f"Trase — Dados da resposta [{ds_id}]",
            span=2 if kind in ("line", "area") else 1,
            x=x_col,
            y=y_cols,
            orientation=orient,
            column_labels=col_labels,
            sort_by=None,
            ascending=False,
        )
        spec.widgets.insert(insert_pos, widget)
        insert_pos += 1
        added += 1

    return added

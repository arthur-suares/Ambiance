"""Dashboard widgets grounded in the same evidence returned to the Studio."""

import re
import unicodedata

import pandas as pd

from src.agro_db import CHOROPLETH_METRICS
from src.dashboard.dashboard_agent import propose_dashboard_spec
from src.dashboard.reviewer_agent import validate_widget_deterministic
from src.dashboard.schemas import DatasetResult, OrchestratorPlan, WidgetSpec, compute_kpi_value


PERIOD_COLUMNS = ("periodo", "ano", "year", "ano_mes", "mes", "month", "data", "date")
CATEGORY_COLUMNS = ("municipio", "nome_municipio", "territorio", "estado", "uf", "pais", "destino",
                    "bioma", "classe", "categoria", "produto", "setor", "empresa", "nome", "name")
NON_METRIC_COLUMNS = {"ibge", "lat", "lon", "latitude", "longitude", "rank", "ranking", "posicao",
                      "sh4", "hs4", "ncm", "cnpj", "cpf", "dia", "day", "trimestre", "quarter"}


def _column_key(column):
    normalized = unicodedata.normalize("NFKD", str(column).lower())
    return re.sub(r"[^a-z0-9]+", "_", normalized.encode("ascii", "ignore").decode()).strip("_")


def _measure_unit(key):
    if key in CHOROPLETH_METRICS:
        return CHOROPLETH_METRICS[key]["unit"]
    suffixes = {"_km2": "km²", "_ha": "ha", "_t": "t", "_kg": "kg", "_cab": "cabeças",
                "_usd": "US$", "_tco2e": "tCO₂e", "_pct": "%", "_percentual": "%"}
    for suffix, unit in suffixes.items():
        if key.endswith(suffix):
            return unit
    if key in {"alertas", "registros", "total_alertas", "contagem", "count"}:
        return "registros"
    return "Unidade conforme coluna"


def _fallback_charts(datasets, metadata):
    """Draw up to three charts from result tables when the plan supplies no usable graph."""
    charts = []
    for dataset in datasets.values():
        frame = dataset.df
        columns = {_column_key(col): col for col in frame}
        metrics = [
            (key, col) for key, col in columns.items()
            if key not in (*PERIOD_COLUMNS, *CATEGORY_COLUMNS, *NON_METRIC_COLUMNS)
            and not re.search(r"(^|_)(codigo|code|id|ibge)(_|$)", key)
            and not pd.api.types.is_bool_dtype(frame[col])
            and pd.to_numeric(frame[col], errors="coerce").replace([float("inf"), -float("inf")], None).notna().any()
        ]
        if not metrics:
            continue
        period_key = next((key for key in PERIOD_COLUMNS if key in columns), None)
        category_key = next((key for key in CATEGORY_COLUMNS if key in columns), None)
        table = metadata[dataset.dataset_id]
        y_key, y = next(((key, col) for key, col in metrics if _measure_unit(key) != "Unidade conforme coluna"),
                        metrics[0])
        unit = table.get("unit") or _measure_unit(y_key)

        if period_key and len(frame) > 1:
            period_col = columns[period_key]
            if frame[period_col].is_unique:
                y_cols = [col for key, col in metrics if _measure_unit(key) == _measure_unit(y_key)][:4] or [y]
                widget = WidgetSpec(
                    f"result-chart-{dataset.dataset_id}", "line",
                    table["purpose"], dataset.dataset_id, unit,
                    f"{dataset.source_label} [{dataset.dataset_id}]", x=period_col, y=y_cols, span=2,
                    orientation="v", sort_by=period_col, ascending=True, top_n=None,
                )
            elif category_key and 2 <= frame[columns[category_key]].nunique(dropna=True) <= 8:
                widget = WidgetSpec(
                    f"result-chart-{dataset.dataset_id}", "line",
                    table["purpose"], dataset.dataset_id, unit,
                    f"{dataset.source_label} [{dataset.dataset_id}]", x=period_col, y=[y],
                    color=columns[category_key], span=2,
                    orientation="v", sort_by=period_col, ascending=True, top_n=None,
                )
            else:
                continue
        elif category_key:
            widget = WidgetSpec(
                f"result-chart-{dataset.dataset_id}", "bar",
                table["purpose"], dataset.dataset_id, unit,
                f"{dataset.source_label} [{dataset.dataset_id}]", x=columns[category_key], y=[y], span=2,
                orientation="h", sort_by=y, ascending=False, top_n=15,
            )
        else:
            continue

        if validate_widget_deterministic(widget, datasets):
            continue
        charts.append(widget)
        if len(charts) == 3:
            break
    return charts


def _temporal_tables(evidence):
    frames = evidence["frames"]
    has_coverage = any(frame.get("coverage_through") for frame in frames)
    columns = ["periodo", "valor", *(["cobertura_ate"] if has_coverage else [])]
    series = [{
        "periodo": frame["period"],
        "valor": frame["value"],
        **({"cobertura_ate": frame.get("coverage_through")} if has_coverage else {}),
    } for frame in frames]
    final = next((frame for frame in reversed(frames) if frame["value"] is not None), None)
    source = evidence["source"]
    tables = [{
        "label": "T1", "purpose": "Série temporal do mapa", "source": source,
        "unit": evidence["unit"], "method_url": evidence["method_url"],
        "columns": columns, "rows": series,
    }]
    if final:
        ranking = (final.get("areas") or [])[:15]
        if len(ranking) > 1:
            tables.append({
                "label": "T2", "purpose": f"Maiores valores territoriais · {final['period']}",
                "source": source, "unit": evidence["unit"], "method_url": evidence["method_url"],
                "columns": ["territorio", "valor"], "rows": [
                    {"territorio": row["name"], "valor": row["value"]} for row in ranking
                ],
            })
    return tables


def build_studio_dashboard(question, tables, evidence=None, *, plan_with_llm=False):
    datasets = {}
    browser_tables = [*_temporal_tables(evidence), *tables] if evidence else tables
    for table in browser_tables:
        if not table["rows"]:
            continue
        label = table["label"]
        source = table.get("source") or "PostgreSQL · base consultada no Ambiance"
        datasets[label] = DatasetResult(
            dataset_id=label, database="postgresql", source_label=source,
            tool_name="temporal" if evidence else "query_agro_sql",
            query_summary=table["purpose"], df=pd.DataFrame(table["rows"], columns=table["columns"]),
        )
    if not datasets:
        return None
    headline = evidence["label"] if evidence else question[:140]
    proposed = []
    if plan_with_llm and not evidence:
        from src.llm_tracker import llm_stage

        plan = OrchestratorPlan(question=question, domain="agro", dashboard_goal=headline)
        try:
            with llm_stage("dashboard.studio.propose_spec"):
                spec, _, _ = propose_dashboard_spec(question, plan, list(datasets.values()), studio=True)
            proposed = spec.widgets[:8]
        except Exception:
            # Provider failure leaves the evidence and deterministic widgets available.
            pass

    defaults = []
    summary = []
    if evidence:
        if any(frame["value"] is not None for frame in evidence["frames"]):
            first_period = evidence["frames"][0]["period"]
            last_period = evidence["frames"][-1]["period"]
            series_title = (
                f"Evolução no período ({first_period}–{last_period})"
                if first_period != last_period else f"Valor observado · {first_period}"
            )
            defaults.append(WidgetSpec("series", "line", series_title, "T1", evidence["unit"],
                                       evidence["source"], x="periodo", y=["valor"], span=2))
        if "T2" in datasets:
            defaults.append(WidgetSpec("territories", "bar", browser_tables[1]["purpose"], "T2",
                                       evidence["unit"], evidence["source"], x="territorio", y=["valor"],
                                       orientation="h", top_n=12, span=2))
        summary = [fact for fact in evidence["facts"] if "change_pct" in fact][:2]
    metadata = {table["label"]: table for table in browser_tables}
    widgets = []
    signatures = set()
    for item in [*defaults, *proposed]:
        dataset = datasets.get(item.dataset_id)
        if not dataset:
            continue
        if item.color and (
            item.color not in dataset.df
            or len(item.y) != 1
            or not 1 <= dataset.df[item.color].nunique(dropna=True) <= 8
        ):
            continue
        # A time-series component always keeps the canonical chronological rows and their gaps.
        if evidence and item.dataset_id == "T1" and item.kind != "table" and item not in defaults:
            continue
        if item.kind == "kpi":
            if item.agg not in {"first", "min", "max", "count"} or item.column not in dataset.df:
                continue
            item.value = compute_kpi_value(dataset.df, item.column, item.agg)
        item.source = f"{dataset.source_label} [{dataset.dataset_id}]"
        item.unit = metadata[item.dataset_id].get("unit") or item.unit or "Unidade conforme coluna"
        signature = (item.kind, item.dataset_id, item.x, tuple(item.y), item.color, item.column, item.agg)
        if signature in signatures or validate_widget_deterministic(item, datasets):
            continue
        signatures.add(signature)
        widgets.append(item.to_dict())

    if not any(widget["kind"] in {"line", "bar"} for widget in widgets):
        widgets.extend(widget.to_dict() for widget in _fallback_charts(datasets, metadata))

    return {
        "title": headline, "scope": evidence["scope"] if evidence else "",
        "widgets": widgets, "tables": browser_tables, "summary": summary,
        "method_url": evidence["method_url"] if evidence else "/metodologia#indicadores",
    }

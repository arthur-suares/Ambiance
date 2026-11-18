"""Agente de dados (2): executa consultas somente-leitura nos bancos DuckDB e devolve DataFrames.

Reaproveita integralmente:
- as consultas prontas de `src/queries.py` (carne bovina), `src/soy/queries.py` (soja) e `find_entity`;
- `run_readonly_sql` de `src/database.py` (conexão `read_only=True`, `enable_external_access=False`,
  `lock_configuration=True`, parser restrito a um único `SELECT`, timeout e `LIMIT`);
- o dicionário de dados (`render_prompt`) e o esquema da soja (`schema_prompt`), com `cache_control`.

Os previews enviados ao LLM no loop de ferramentas são truncados em `MAX_ROWS_TO_LLM` (60) linhas,
enquanto os `pd.DataFrame` completos (até `SQL_MAX_ROWS`) são preservados em memória como `D1`, `D2`...
"""

from __future__ import annotations

import json
import time

import pandas as pd

from src import queries
from src.agent import QUERY_FUNCS, SOY_RULES, SOY_TOOLS, SOY_UNAVAILABLE, TOOLS, ToolCall, tool_call_summary
from src.config import DUCKDB_PATH, LLM_MODEL
from src.dashboard.schemas import DataAgentResult, DatasetResult, MAX_ROWS_TO_LLM, OrchestratorPlan, round_sig
from src.data_dictionary import render_prompt
from src.database import SqlError, run_readonly_sql
from src.rag import get_client
from src.soy import queries as soy_queries

MAX_DATA_TURNS = 8

BEEF_UNAVAILABLE = """\
# Banco da carne bovina
Indisponível nesta instalação (rode `python -m src.cli build-db`). Consulte apenas o banco da soja se disponível."""

DATA_AGENT_PROMPT = """\
Você é o Agente de Dados do sistema de dashboards do Trase. Seu papel é coletar os conjuntos \
de dados tabulares necessários para construir um painel analítico que responda à pergunta do usuário, \
seguindo o plano do Orquestrador.

Regras de coleta:
- Use apenas as ferramentas disponíveis (consultas prontas e SELECT somente-leitura via run_sql / run_soy_sql).
- Prefira as consultas prontas quando cobrirem o recorte; use run_sql (carne bovina) ou run_soy_sql (soja) \
quando precisar cruzar dimensões, filtrar por estado/bioma/empresa específicos ou agregar para KPIs.
- Nunca use run_sql para soja nem run_soy_sql para carne bovina.
- Antes de filtrar por nome de município, empresa ou país informado pelo usuário, confirme a grafia com \
find_entity (países/blocos estão em inglês: CHINA, EUROPEAN UNION, UNITED STATES; municípios/UFs sem acento).
- Se nenhum ano for pedido, use o ano mais recente com dados ({latest_year} para carne bovina; \
{soy_latest_year} para soja).
- Respeite rigorosamente as regras metodológicas do Trase: NÃO some exposição ao desmatamento nem emissões \
de janela de 5 anos entre anos diferentes; exclua 'UNKNOWN' em rankings municipais e avise quando relevante.
- Agregue no SQL (GROUP BY, SUM, AVG, ORDER BY, LIMIT) para devolver tabelas enxutas e prontas para gráficos.
- Na soja, `country_of_first_import = 'BRAZIL'` é soja processada no próprio Brasil (consumo doméstico), \
não é exportação. Ao contar países de destino, exclua BRAZIL (`country_of_first_import <> 'BRAZIL'`). \
Em rankings de destino, mantenha BRAZIL só se a pergunta pedir o consumo doméstico.
- Para contar compradores use `importer_group` (grupos importadores); para vendedores, `exporter_group`.
- Se uma consulta falhar ou voltar vazia, ajuste e tente novamente (no máximo 2 tentativas por recorte).
- Quando todos os datasets necessários já tiverem sido obtidos ([D1], [D2]...), encerre com um resumo curto \
dizendo o que cada [Dn] representa.

{dictionary}

{soy}
"""


def _df_preview(df: pd.DataFrame, truncated: bool = False) -> str:
    if df.empty:
        return "(nenhuma linha — ajuste os filtros ou confira a grafia com find_entity)"
    shown = df.head(MAX_ROWS_TO_LLM).map(round_sig)
    text = shown.to_csv(index=False).strip()
    extra = len(df) > MAX_ROWS_TO_LLM or truncated
    suffix = (
        f"\n(... truncado em {len(shown)} de {len(df)} linhas)"
        if extra else f"\n({len(df)} linhas)"
    )
    return text + suffix


def _source_metadata(tool_name: str) -> tuple[str, str]:
    if tool_name == "run_soy_sql" or tool_name.startswith("soy_"):
        return "soy.duckdb", "Trase — Cadeia da soja (soy.duckdb)"
    return "trase.duckdb", "Trase — Cadeia da carne bovina (trase.duckdb)"


class _DataSession:
    def __init__(self) -> None:
        self.datasets: list[DatasetResult] = []
        self.calls: list[ToolCall] = []

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        start = time.perf_counter()
        label, rows = "", None
        try:
            if name in ("run_sql", "run_soy_sql"):
                connect = soy_queries.connect_readonly if name == "run_soy_sql" else None
                df, truncated = run_readonly_sql(args["sql"], connect=connect)
                rows = len(df)
                purpose = str(args.get("purpose") or "").strip()
                text = _df_preview(df, truncated)
                if not df.empty:
                    label = f"D{len(self.datasets) + 1}"
                    db_name, src_label = _source_metadata(name)
                    self.datasets.append(DatasetResult(
                        dataset_id=label,
                        database=db_name,
                        source_label=src_label,
                        tool_name=name,
                        query_summary=args["sql"].strip(),
                        df=df.copy(),
                        purpose=purpose,
                        truncated=truncated,
                        seconds=round(time.perf_counter() - start, 2),
                    ))
            elif name in QUERY_FUNCS:
                call_args = {k: v for k, v in args.items() if v is not None}
                df = QUERY_FUNCS[name](**call_args)
                rows = len(df)
                text = _df_preview(df)
                if name != "find_entity" and not df.empty:
                    label = f"D{len(self.datasets) + 1}"
                    db_name, src_label = _source_metadata(name)
                    summary = f"{name}({json.dumps(call_args, ensure_ascii=False)})"
                    self.datasets.append(DatasetResult(
                        dataset_id=label,
                        database=db_name,
                        source_label=src_label,
                        tool_name=name,
                        query_summary=summary,
                        df=df.copy(),
                        purpose=f"Consulta pronta {name}",
                        truncated=False,
                        seconds=round(time.perf_counter() - start, 2),
                    ))
            else:
                raise ValueError(f"Ferramenta desconhecida: {name}")
            ok = True
        except (SqlError, ValueError, TypeError, FileNotFoundError) as e:
            text, ok = f"Erro: {e}", False
        except Exception as e:
            text, ok = f"Erro: {type(e).__name__}: {e}", False

        elapsed = round(time.perf_counter() - start, 2)
        self.calls.append(ToolCall(label or name, name, args, ok, text, rows, elapsed))
        if label and ok:
            text = f"Resultado [{label}]\n{text}"
        return text, ok


def _format_plan_message(question: str, plan: OrchestratorPlan) -> str:
    reqs = "\n".join(
        f"- [{r.request_id}] ({r.suggested_visual}, base={r.database_hint}): {r.description}"
        for r in plan.data_requests
    ) or "- Obtenha os dados necessários para responder à pergunta."
    notes = "\n".join(f"- {n}" for n in plan.methodological_notes)
    msg = (
        f"Pergunta do usuário: {question}\n"
        f"Domínio identificado: {plan.domain}\n"
        f"Objetivo do dashboard: {plan.dashboard_goal}\n\n"
        f"Consultas planejadas pelo Orquestrador:\n{reqs}"
    )
    if notes:
        msg += f"\n\nCuidados metodológicos:\n{notes}"
    return msg


def run_data_agent(question: str, plan: OrchestratorPlan) -> DataAgentResult:
    """Executa o loop de tool-use no DuckDB e devolve DataFrames rotulados [D1, D2...]."""
    beef_ok = DUCKDB_PATH.exists()
    soy_ok = soy_queries.is_available()

    beef_tools = [t for t in TOOLS if t["name"] != "search_laws"] if beef_ok else []
    tools = beef_tools + (SOY_TOOLS if soy_ok else [])
    if not tools:
        return DataAgentResult(
            notes="Nenhum banco DuckDB encontrado (rode `build-db` ou `ingest-soy`)."
        )

    latest_beef = queries.latest_year() if beef_ok else "indisponível"
    latest_soy = (soy_queries.latest_year() if soy_ok else None) or "indisponível"
    system = [{
        "type": "text",
        "text": DATA_AGENT_PROMPT.format(
            latest_year=latest_beef,
            soy_latest_year=latest_soy,
            dictionary=render_prompt() if beef_ok else BEEF_UNAVAILABLE,
            soy=(soy_queries.schema_prompt() + "\n" + SOY_RULES) if soy_ok else SOY_UNAVAILABLE,
        ),
        "cache_control": {"type": "ephemeral"},
    }]

    messages: list[dict] = [{"role": "user", "content": _format_plan_message(question, plan)}]
    session = _DataSession()
    result = DataAgentResult()

    for _ in range(MAX_DATA_TURNS):
        response = get_client().messages.create(
            model=LLM_MODEL,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )
        result.input_tokens += getattr(response.usage, "input_tokens", 0) or 0
        result.output_tokens += getattr(response.usage, "output_tokens", 0) or 0

        if response.stop_reason != "tool_use":
            result.notes = "".join(
                getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text"
            ).strip()
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            text, ok = session.run(block.name, dict(block.input or {}))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": text,
                "is_error": not ok,
            })
        messages.append({"role": "user", "content": tool_results})

    result.datasets = session.datasets
    result.tool_calls = session.calls
    return result


__all__ = ["run_data_agent", "tool_call_summary"]

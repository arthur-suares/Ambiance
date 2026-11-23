"""Agente híbrido (PostgreSQL+PostGIS + RAG Jurídico) com emissão de MapSpec declarativo."""

from __future__ import annotations

import json
import time
from typing import Any

from src.agro_db import CHOROPLETH_METRICS, run_readonly_sql
from src.config import LLM_EXTRA_PARAMS, LLM_MAX_TOKENS, LLM_MODEL

MAX_TURNS = 6

SYSTEM_PROMPT = """\
Você é o assistente analítico e socioambiental da plataforma Agro/Ambiance.
Você responde perguntas em português combinando:
1. Banco consolidado PostgreSQL + PostGIS (schemas `agro` e `gold`), via ferramenta `query_agro_sql`.
2. Legislação ambiental federal (29 leis, busca híbrida pgvector + FTS), via ferramenta `search_laws`.
3. Mapa interativo sincronizado, controlado pela ferramenta `set_map_view`.

## Esquema disponível (somente leitura)
- `gold.mv_territorio_municipal_ano` (chave: `ano`, `codigo_municipio_ibge`):
  Colunas: `ano`, `codigo_municipio_ibge`, `municipio`, `uf`, `regiao`, `bioma_predominante`, `lat`, `lon`,
  `ibge_soja_area_plantada_ha`, `ibge_soja_producao_t`, `ibge_soja_rendimento_kg_ha`, `ibge_bovinos_rebanho_cab`,
  `mapbiomas_floresta_ha`, `mapbiomas_pastagem_ha`, `mapbiomas_soja_ha`, `mapbiomas_agropecuaria_ha`,
  `mapbiomas_desmatamento_ha`, `inpe_deter_alertas`, `inpe_deter_area_km2`,
  `seeg_emissao_total_tco2e`, `seeg_emissao_agro_tco2e`, `seeg_emissao_mut_tco2e`,
  `comex_soja_t`, `comex_soja_fob_usd`, `comex_bovinos_t`, `comex_bovinos_fob_usd`,
  `trase_soja_volume_t`, `trase_soja_fob_usd`, `trase_soja_exposicao_5a_ha`, `trase_soja_emissoes_liq_tco2e`,
  `trase_bovinos_volume_t`, `trase_bovinos_fob_usd`, `trase_bovinos_exposicao_5a_ha`, `trase_bovinos_emissoes_liq_tco2e`,
  `inst_bovinos_total`, `inst_soja_total`.
- `agro.fato_seeg_emissoes` (`ano`, `codigo_municipio_ibge`, `uf`, `tipo_fluxo`, `setor`, `subsetor`, `atividade`, `emissao_tco2e` em GWP-AR5).
- `agro.fato_comex_exportacoes` (`ano`, `mes`, `produto`, `sh4`, `sh4_desc`, `codigo_municipio_ibge`, `uf`, `pais`, `kg_liquido`, `valor_fob_usd`).
- `agro.dim_instalacoes` (`cadeia` IN ('bovinos','soja'), `empresa`, `cnpj`, `tipo`, `nivel_inspecao`, `numero_inspecao`, `capacidade_valor`, `codigo_municipio_ibge`, `uf`, `lat`, `lon`).
- `gold.mv_rede_fluxos` (`produto` IN ('soja','bovinos'), `ano`, `codigo_municipio_ibge`, `municipio_producao`,
  `estado_producao`, `bioma`, `hub_logistico`, `porto_exportacao`, `pais_destino`, `pais_destino_trase_id`,
  `registros`, `volume_t`, `valor_usd`, `exposicao_desmatamento_ha`, `emissoes_liquidas_tco2e`).
- `gold.mv_cobertura_incerteza` (`produto`, `ano`, `estado_producao`, `volume_total_t`, `volume_rastreado_t`, `pct_volume_rastreado`, `exposicao_total_ha`, `exposicao_rastreada_ha`).
- `agro.fato_inpe_deter` (`bioma` IN ('AMAZONIA','CERRADO','PANTANAL'), `view_date`, `ano`, `mes`, `classname`,
  `codigo_municipio_ibge`, `municipio`, `uf`, `uc`, `area_mun_km2`, `lat`, `lon`). Atualizado até 23/11/2026.
- `agro.dim_municipios` (`codigo_municipio_ibge`, `municipio`, `municipio_norm`, `uf`, `uf_nome`, `regiao`, `bioma_predominante`, `area_km2`).
- `agro.dim_fontes` (catálogo de fontes, cobertura temporal e limitações).

## Regras obrigatórias
- Sempre use `query_agro_sql` para números; nunca invente valores.
- Inclua `codigo_municipio_ibge` nos SELECTs municipais para que o mapa destaque os municípios encontrados.
- Sempre chame `set_map_view` quando a pergunta envolver território, municípios, biomas, estados, fluxos ou alertas DETER.
- Para perguntas sobre leis, obrigações, Código Florestal, CAR, PRA, crimes ambientais ou licenciamento, chame `search_laws`.
- Regras metodológicas:
  - NUNCA some `trase_*_exposicao_5a_ha` entre anos (janela móvel de 5 anos).
  - NUNCA trate exposição ao desmatamento ou alerta territorial como prova de ilegalidade individual.
  - Sempre informe o ano, a unidade, a fonte e cite `[D1]`, `[D2]` para dados e `[L1]`, `[L2]` para leis.
  - Quando falar de fluxos da Trase, mencione que há parcela `UNKNOWN` (sem município rastreado) e cite a cobertura se relevante.
  - Valores de `bioma_predominante` em `mv_territorio_municipal_ano` usam acento ('Amazônia', 'Cerrado', 'Mata Atlântica', 'Caatinga', 'Pampa', 'Pantanal'); em `fato_inpe_deter` usam maiúsculas sem acento ('AMAZONIA', 'CERRADO', 'PANTANAL'). Use `unaccent(lower(...))` ao filtrar nomes/biomas.
"""

TOOLS = [
    {
        "name": "query_agro_sql",
        "description": "Executa consulta SQL SELECT somente-leitura nos schemas agro e gold do PostgreSQL.",
        "input_schema": {
            "type": "object",
            "required": ["sql", "purpose"],
            "properties": {
                "sql": {"type": "string", "description": "Consulta SELECT ou WITH válida em PostgreSQL."},
                "purpose": {"type": "string", "description": "Resumo curto do que a consulta mede."},
            },
        },
    },
    {
        "name": "search_laws",
        "description": "Busca híbrida (vetorial + palavra-chave) nas 29 leis ambientais federais.",
        "input_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Termos jurídicos ou pergunta legal."},
            },
        },
    },
    {
        "name": "set_map_view",
        "description": "Define o estado visual do mapa interativo sincronizado com a resposta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": sorted(CHOROPLETH_METRICS.keys()),
                    "description": "Métrica do mapa coroplético municipal.",
                },
                "year": {"type": "integer", "description": "Ano principal do recorte (ex.: 2022 ou 2025)."},
                "uf": {"type": "string", "description": "Sigla de UF (2 letras, ex.: PA, MT), opcional."},
                "bioma": {"type": "string", "description": "Bioma (ex.: Amazônia, Cerrado, Pantanal), opcional."},
                "show_flows": {"type": "boolean", "description": "Exibir camada de fluxos comerciais Trase."},
                "flow_product": {"type": "string", "enum": ["soja", "bovinos"]},
                "show_deter": {"type": "boolean", "description": "Exibir camada de pontos de alertas INPE DETER."},
                "deter_year": {"type": "integer", "description": "Ano dos alertas DETER (ex.: 2025 ou 2026)."},
                "highlight_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Códigos IBGE de 7 dígitos dos municípios principais citados na resposta.",
                },
            },
        },
    },
]


def _format_table_for_llm(cols: list[str], rows: list[dict[str, Any]], label: str, purpose: str) -> str:
    if not rows:
        return f"[{label}] {purpose}\n(0 linhas retornadas)"
    header = " | ".join(cols)
    sep = " | ".join("---" for _ in cols)
    body = []
    for r in rows[:40]:
        body.append(" | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols))
    note = f"\n(mostrando 40 de {len(rows)} linhas)" if len(rows) > 40 else ""
    return f"[{label}] {purpose} ({len(rows)} linhas)\n{header}\n{sep}\n" + "\n".join(body) + note


def _run_law_search(query: str, k: int) -> list[dict[str, Any]]:
    from src.embeddings import embed_query
    from src.vector_store import get_connection, hybrid_search

    q_emb = embed_query(query)
    with get_connection() as con:
        return hybrid_search(con, query, q_emb, k=k)


def ask_agro(question: str, k_laws: int = 6) -> dict[str, Any]:
    from src.rag import get_client

    client = get_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    tool_calls_log: list[dict[str, Any]] = []
    law_sources: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    map_spec: dict[str, Any] = {}
    discovered_codes: list[str] = []

    in_tokens = 0
    out_tokens = 0
    d_idx = 0
    final_text = ""
    stop_reason = ""

    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=LLM_MODEL,
            max_tokens=min(LLM_MAX_TOKENS, 4096),
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
            **LLM_EXTRA_PARAMS,
        )
        in_tokens += resp.usage.input_tokens
        out_tokens += resp.usage.output_tokens
        stop_reason = resp.stop_reason or ""

        assistant_blocks = resp.content
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_uses = [b for b in assistant_blocks if b.type == "tool_use"]
        if not tool_uses:
            final_text = "\n".join(b.text for b in assistant_blocks if b.type == "text").strip()
            break

        tool_results = []
        for tu in tool_uses:
            t0 = time.perf_counter()
            name = tu.name
            inp = tu.input or {}
            if name == "query_agro_sql":
                d_idx += 1
                label = f"D{d_idx}"
                sql = str(inp.get("sql", ""))
                purpose = str(inp.get("purpose", "Consulta SQL"))
                try:
                    cols, rows = run_readonly_sql(sql, max_rows=100)
                    for r in rows[:20]:
                        code = r.get("codigo_municipio_ibge") or r.get("code")
                        if isinstance(code, str) and len(code) == 7 and code.isdigit() and code not in discovered_codes:
                            discovered_codes.append(code)
                    tables.append({"label": label, "purpose": purpose, "columns": cols, "rows": rows[:30]})
                    out_txt = _format_table_for_llm(cols, rows, label, purpose)
                    tool_calls_log.append({
                        "label": label, "name": name, "summary": purpose,
                        "ok": True, "rows": len(rows), "seconds": round(time.perf_counter() - t0, 2),
                        "output": sql,
                    })
                except Exception as exc:
                    out_txt = f"[{label}] ERRO SQL: {exc}"
                    tool_calls_log.append({
                        "label": label, "name": name, "summary": purpose,
                        "ok": False, "rows": 0, "seconds": round(time.perf_counter() - t0, 2),
                        "output": f"{sql}\nErro: {exc}",
                    })
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out_txt})

            elif name == "search_laws":
                q = str(inp.get("query", question))
                try:
                    hits = _run_law_search(q, k=k_laws)
                    chunks_txt = []
                    for h in hits:
                        law_sources.append(h)
                        idx_l = len(law_sources)
                        art = h["metadata"].get("artigo", "")
                        chunks_txt.append(f"[L{idx_l}] {h['title']} (art. {art})\n{h['content']}")
                    out_txt = "\n\n".join(chunks_txt) if chunks_txt else "Nenhum trecho jurídico encontrado."
                    tool_calls_log.append({
                        "label": f"L1..L{len(law_sources)}", "name": name, "summary": q,
                        "ok": True, "rows": len(hits), "seconds": round(time.perf_counter() - t0, 2),
                        "output": q,
                    })
                except Exception as exc:
                    out_txt = f"Busca jurídica indisponível: {exc}"
                    tool_calls_log.append({
                        "label": "L", "name": name, "summary": q,
                        "ok": False, "rows": 0, "seconds": round(time.perf_counter() - t0, 2),
                        "output": str(exc),
                    })
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out_txt})

            elif name == "set_map_view":
                spec: dict[str, Any] = {}
                if inp.get("metric") in CHOROPLETH_METRICS:
                    spec["metric"] = inp["metric"]
                if isinstance(inp.get("year"), int):
                    spec["year"] = inp["year"]
                if isinstance(inp.get("uf"), str) and inp["uf"].strip():
                    spec["uf"] = inp["uf"].strip().upper()[:2]
                if isinstance(inp.get("bioma"), str) and inp["bioma"].strip():
                    spec["bioma"] = inp["bioma"].strip()
                if isinstance(inp.get("show_flows"), bool):
                    spec["show_flows"] = inp["show_flows"]
                if inp.get("flow_product") in ("soja", "bovinos"):
                    spec["flow_product"] = inp["flow_product"]
                if isinstance(inp.get("show_deter"), bool):
                    spec["show_deter"] = inp["show_deter"]
                if isinstance(inp.get("deter_year"), int):
                    spec["deter_year"] = inp["deter_year"]
                if isinstance(inp.get("highlight_codes"), list):
                    spec["highlight_codes"] = [
                        str(c).strip() for c in inp["highlight_codes"]
                        if str(c).strip().isdigit() and len(str(c).strip()) == 7
                    ][:25]
                map_spec.update(spec)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "MapSpec atualizado."})

        messages.append({"role": "user", "content": tool_results})

    if discovered_codes and "highlight_codes" not in map_spec:
        map_spec["highlight_codes"] = discovered_codes[:15]

    return {
        "answer": final_text,
        "domain": "mixed" if (tables and law_sources) else ("law" if law_sources else "agro"),
        "stop_reason": stop_reason,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "tool_calls": tool_calls_log,
        "tables": tables,
        "map_spec": map_spec if map_spec else None,
        "sources": [
            {
                "label": f"L{i}",
                "title": s["title"],
                "artigo": s["metadata"].get("artigo"),
                "parte": s["metadata"].get("parte"),
                "partes": s["metadata"].get("partes"),
                "url": s["url"],
                "score": float(s["score"]),
                "semantic_rank": s.get("semantic_rank"),
                "keyword_rank": s.get("keyword_rank"),
            }
            for i, s in enumerate(law_sources, 1)
        ],
    }

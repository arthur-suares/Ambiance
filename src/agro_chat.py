"""Agente híbrido (PostgreSQL+PostGIS + RAG Jurídico) com emissão de MapSpec declarativo."""

from __future__ import annotations

import json
import logging
import re
import time
from math import isfinite
from numbers import Real
from typing import Any

from src.agro_db import CHOROPLETH_METRICS, run_readonly_sql
from src.config import LLM_EXTRA_PARAMS, LLM_MAX_TOKENS, LLM_MODEL
from src.temporal import METRICS, get_temporal

MAX_TURNS = 4
logger = logging.getLogger(__name__)
_LAW_HINT_RE = re.compile(
    r"\b(lei|leis|c[oó]digo|florestal|reserva\s+legal|app|car|pra|embargo|crime|licenciamento|"
    r"obriga[cç][aã]o|obriga[cç][oõ]es|art\.?|artigo|norma|decreto|resolu[cç][aã]o)\b",
    re.I,
)

SYSTEM_PROMPT = """\
Você é o assistente analítico e socioambiental da plataforma Agro/Ambiance.
Você responde perguntas em português e constrói em tempo real um **Canvas Interativo** ao lado do chat combinando:
1. Banco consolidado PostgreSQL + PostGIS (schemas `agro` e `gold`), via ferramenta `query_agro_sql`.
2. Legislação ambiental federal (29 leis, busca híbrida pgvector + FTS), via ferramenta `search_laws`.
3. Mapa interativo sob demanda (`deck.gl`), controlado pela ferramenta `set_map_view`.
4. Linha do Tempo e Dashboard, abastecidos pela ferramenta `set_temporal_view` e pelas consultas SQL.

Comece a resposta final com uma conclusão em texto, mesmo que o usuário peça só uma visualização. Para exportações sem produto especificado, identifique as cadeias cobertas pelas consultas e informe que elas são um recorte. No Comex Stat, a UF corresponde ao domicílio fiscal do exportador. Para carne bovina fresca, refrigerada ou congelada, filtre os códigos 0201 e 0202. Para a cadeia bovina mais ampla, explicite os códigos e o conjunto de produtos consultado.

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
- Use `query_agro_sql` ou `set_temporal_view` para números; nunca invente valores.
- Inclua `codigo_municipio_ibge` nos SELECTs municipais para que o mapa destaque os municípios encontrados.
- **Mapa sob demanda (`set_map_view`):** sempre chame quando a pergunta envolver território, municípios, biomas, estados, fluxos, instalações, cobertura MapBiomas ou alertas DETER. Ative apenas as camadas relevantes para a pergunta, defina um `title` descritivo e escolha o recorte (`uf`/`bioma`/`year`/`metric`/`deter_mode`/`show_facilities`/`mapbiomas_mode`).
- Quando o usuário pedir **cobertura e uso da terra (MapBiomas, floresta vs pastagem vs soja, 1985–2025)**, use `mapbiomas_mode: true`, `mapbiomas_year` (1985–2025) e `mapbiomas_classes` (opcional, IDs como 3=Floresta, 4=Savânica, 15=Pastagem, 39=Soja, 21=Mosaico, 24=Urbana, 33=Água).
- **Evolução territorial:** quando a pergunta pedir intervalo, evolução, série, play, marcos ou animação de uma métrica territorial, use `set_temporal_view` uma única vez. Os marcos, o mapa animado e o Dashboard são gerados automaticamente a partir da série [T1] — não chame `set_map_view` nem repita consultas SQL sobre o mesmo indicador. Só chame `search_laws` se a pergunta pedir legislação. Para datas não informadas, use o intervalo pertinente à pergunta e explique o recorte. Use meses apenas para DETER.
- **Dashboard:** os resultados das ferramentas alimentam o Dashboard interativo automaticamente. Prefira resultados com colunas claras e unidades no nome ou no propósito da consulta.
- Para perguntas sobre leis, obrigações, Código Florestal, CAR, PRA, crimes ambientais ou licenciamento, chame `search_laws`.
- Em pedidos de refinamento conversacional ("filtre só 2025", "troque para hexágonos 3D", "mostre os frigoríficos", "compare com Altamira"), preserve ou adapte o recorte do Canvas atual.
- Regras de clareza e linguagem acessível:
  - Escreva para qualquer pessoa (cidadãos, pesquisadores, gestores e empresas), em português natural e claro.
  - NUNCA use siglas técnicas sem explicá-las em palavras comuns primeiro (evite siglas soltas como DETER, SEEG, APP, CAR, PRA, SIF, IBGE, MUT, UNKNOWN ou SQL; escreva "alertas de satélite do INPE", "emissões de carbono e uso da terra", "área de preservação permanente", "cadastro ambiental rural", "frigoríficos e abatedouros", "parcela sem origem identificada").
  - Nos títulos dos mapas (`title`), também use linguagem humana sem siglas técnicas.
- Regras metodológicas:
  - NUNCA some `trase_*_exposicao_5a_ha` entre anos (janela móvel de 5 anos).
  - NUNCA trate exposição ao desmatamento ou alerta territorial como prova de ilegalidade individual.
  - Sempre informe o ano, a unidade, a fonte e cite `[D1]`, `[D2]` para dados e `[L1]`, `[L2]` para leis.
  - Quando falar de fluxos da Trase, mencione que há parcela `UNKNOWN` (sem município rastreado) e cite a cobertura se relevante.
  - Valores de `bioma_predominante` em `mv_territorio_municipal_ano` usam acento ('Amazônia', 'Cerrado', 'Mata Atlântica', 'Caatinga', 'Pampa', 'Pantanal'); em `fato_inpe_deter` usam maiúsculas sem acento ('AMAZONIA', 'CERRADO', 'PANTANAL'). Use `unaccent(lower(...))` ao filtrar nomes/biomas.
"""

CHART_TYPES = ("bar", "horizontal_bar", "line", "area", "doughnut")

TOOLS = [
    {
        "name": "set_temporal_view",
        "description": "Carrega dados do recorte para Linha do Tempo, mapa animado e Dashboard, sem substituir períodos ausentes.",
        "input_schema": {
            "type": "object",
            "required": ["metric", "start_year", "end_year"],
            "properties": {
                "metric": {"type": "string", "enum": list(METRICS),
                           "description": "Escolha flows_soja/flows_bovinos para arcos internacionais, land_cover para cobertura MapBiomas e deter_count/deter_area para alertas."},
                "start_year": {"type": "integer"},
                "end_year": {"type": "integer"},
                "frequency": {"type": "string", "enum": ["annual", "monthly"]},
                "start_month": {"type": "integer"},
                "end_month": {"type": "integer"},
                "uf": {"type": "string"},
                "bioma": {"type": "string"},
                "code": {"type": "string", "description": "Código IBGE de sete dígitos para restringir a série a um município."},
                "classes": {"type": "array", "items": {"type": "integer"},
                            "description": "Para land_cover: 3 floresta, 15 pastagem, 39 soja, entre outras classes."},
            },
        },
    },
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
        "description": "Constrói e configura o mapa interativo (deck.gl) no Canvas ao lado do chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título curto para a visualização do mapa."},
                "metric": {
                    "type": "string",
                    "enum": sorted(CHOROPLETH_METRICS.keys()),
                    "description": "Métrica do mapa coroplético municipal.",
                },
                "year": {"type": "integer", "description": "Ano principal do recorte (ex.: 2022, 2025 ou 2026)."},
                "uf": {"type": "string", "description": "Sigla de UF (2 letras, ex.: PA, MT), opcional."},
                "bioma": {"type": "string", "description": "Bioma (ex.: Amazônia, Cerrado, Pantanal), opcional."},
                "show_flows": {"type": "boolean", "description": "Exibir camada de arcos de fluxos comerciais Trase."},
                "flow_product": {"type": "string", "enum": ["soja", "bovinos"]},
                "show_deter": {"type": "boolean", "description": "Exibir camada de alertas INPE DETER."},
                "deter_year": {"type": "integer", "description": "Ano dos alertas DETER (ex.: 2025 ou 2026)."},
                "deter_mode": {
                    "type": "string",
                    "enum": ["hex", "points"],
                    "description": "Modo de renderização dos alertas DETER: 'hex' (hexágonos 3D) ou 'points'.",
                },
                "show_facilities": {"type": "boolean", "description": "Exibir camada de frigoríficos ou armazéns/silos."},
                "facilities_chain": {"type": "string", "enum": ["bovinos", "soja"]},
                "view_3d": {"type": "boolean", "description": "Inclinar câmera para visualização 3D."},
                "basemap": {"type": "string", "enum": ["dark", "terrain", "light"]},
                "mapbiomas_mode": {"type": "boolean", "description": "Ativar visualização oficial de Cobertura e Uso da Terra MapBiomas (1985-2025)."},
                "mapbiomas_year": {"type": "integer", "description": "Ano do MapBiomas entre 1985 e 2025."},
                "mapbiomas_classes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "IDs de classes MapBiomas para filtrar (ex.: [3,4,15,39]).",
                },
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
    for r in rows[:20]:
        body.append(" | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols))
    note = f"\n(mostrando 20 de {len(rows)} linhas)" if len(rows) > 20 else ""
    return f"[{label}] {purpose} ({len(rows)} linhas)\n{header}\n{sep}\n" + "\n".join(body) + note


def _run_law_search(query: str, k: int) -> list[dict[str, Any]]:
    from src.embeddings import embed_query
    from src.vector_store import hybrid_search

    q_emb = embed_query(query)
    return hybrid_search(query, q_emb, limit=k)


def _format_view_context(view_context: dict[str, Any] | None) -> str:
    if not isinstance(view_context, dict):
        return ""
    parts = []
    if view_context.get("preset"):
        parts.append(f"visão={view_context['preset']}")
    if view_context.get("chain") and view_context["chain"] != "all":
        parts.append(f"cadeia={view_context['chain']}")
    if view_context.get("uf"):
        parts.append(f"UF={view_context['uf']}")
    if view_context.get("bioma"):
        parts.append(f"bioma={view_context['bioma']}")
    if view_context.get("year"):
        parts.append(f"ano={view_context['year']}")
    if view_context.get("start_period") and view_context.get("end_period"):
        parts.append(f"período={view_context['start_period']} a {view_context['end_period']}")
    if view_context.get("classes"):
        parts.append(f"classes MapBiomas={view_context['classes']}")
    if view_context.get("metric"):
        parts.append(f"métrica={view_context['metric']}")
    if view_context.get("show_flows"):
        parts.append(f"fluxos={view_context.get('flow_product') or 'ativos'}")
    if view_context.get("show_deter"):
        parts.append(f"DETER={view_context.get('deter_mode') or 'points'}({view_context.get('deter_year') or view_context.get('year') or 'recente'})")
    if view_context.get("show_facilities"):
        parts.append(f"instalações={view_context.get('facilities_chain') or 'bovinos'}")
    if isinstance(view_context.get("view_3d"), bool):
        parts.append("3D" if view_context["view_3d"] else "2D")
    if view_context.get("basemap"):
        parts.append(f"basemap={view_context['basemap']}")
    sel = view_context.get("selected_municipality")
    if isinstance(sel, dict) and sel.get("code"):
        parts.append(f"município_selecionado={sel.get('municipio', '')} ({sel.get('uf', '')}, IBGE {sel['code']})")
    if not parts:
        return ""
    return "[Contexto atual do Canvas/mapa: " + "; ".join(parts) + "]\n\n"


def _sanitize_history(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        text = content.strip()[:1500]
        if not text:
            continue
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] = (cleaned[-1]["content"] + "\n\n" + text)[:1500]
        else:
            cleaned.append({"role": role, "content": text})
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    while cleaned and cleaned[-1]["role"] != "assistant":
        cleaned.pop()
    return cleaned


def _sanitize_chart(inp: dict[str, Any]) -> dict[str, Any] | None:
    raw_labels = inp.get("labels")
    raw_series = inp.get("series")
    if not isinstance(raw_labels, list) or not raw_labels or not isinstance(raw_series, list) or not raw_series:
        return None
    labels = [str(x)[:60] for x in raw_labels[:30]]
    n = len(labels)
    chart_type = inp.get("chart_type")
    if chart_type not in CHART_TYPES:
        chart_type = "bar"
    series: list[dict[str, Any]] = []
    for s in raw_series[:8]:
        if not isinstance(s, dict):
            continue
        vals = s.get("values")
        if not isinstance(vals, list):
            continue
        nums: list[float] = []
        for i in range(n):
            v = vals[i] if i < len(vals) else 0
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                nums.append(0.0)
        entry: dict[str, Any] = {
            "name": str(s.get("name") or f"Série {len(series) + 1}")[:60],
            "values": nums,
        }
        if isinstance(s.get("color"), str) and s["color"].strip():
            entry["color"] = s["color"].strip()[:32]
        series.append(entry)
    if not series:
        return None
    return {
        "title": str(inp.get("title") or "Gráfico")[:120],
        "subtitle": str(inp.get("subtitle") or "")[:180],
        "chart_type": chart_type,
        "x_label": str(inp.get("x_label") or "")[:60],
        "y_label": str(inp.get("y_label") or "")[:60],
        "unit": str(inp.get("unit") or "")[:30],
        "labels": labels,
        "series": series,
    }


def _evaluate_views(
    domain: str,
    tables: list[dict[str, Any]],
    charts: list[dict[str, Any]],
    map_spec: dict[str, Any] | None,
    sources: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, str]]]:
    """Avalia a resposta gerada e define apenas as visualizações pertinentes, com descrição do que o usuário verá e receberá."""
    if domain == "law":
        map_spec = None
        charts = []

    views: list[dict[str, str]] = []

    if map_spec:
        scope = map_spec.get("uf") or map_spec.get("bioma") or "Brasil"
        if map_spec.get("mapbiomas_mode"):
            yr = map_spec.get("mapbiomas_year") or map_spec.get("year") or 2025
            what_see = f"Mapa dos municípios mostrando a cobertura do solo (florestas, pastagens, lavouras e água) em {scope} no ano de {yr}."
            what_rec = "Filtro por tipo de vegetação ou uso rural, comparação ano a ano (1985 a 2025) e resumo ao clicar em cada município."
        else:
            layers = ["municípios coloridos pelo indicador escolhido"]
            if map_spec.get("show_deter"):
                layers.append(f"alertas recentes de desmatamento por satélite ({'colunas em 3D' if map_spec.get('deter_mode') == 'hex' else 'pontos no mapa'})")
            if map_spec.get("show_flows"):
                layers.append(f"rotas de exportação de {map_spec.get('flow_product') or 'produção rural'} para outros países")
            if map_spec.get("show_facilities"):
                layers.append("localização de frigoríficos e armazéns")
            hl = len(map_spec.get("highlight_codes") or [])
            yr = map_spec.get("year") or map_spec.get("deter_year") or "ano mais recente"
            what_see = f"Mapa interativo de {scope} ({yr}) com {', '.join(layers)}" + (f" e {hl} município(s) em destaque." if hl else ".")
            what_rec = "Visão em 2D ou 3D, imagem de satélite, nota explicando os limites dos dados e resumo completo ao clicar em qualquer município."
        views.append({
            "key": "map",
            "label": "Ver no mapa",
            "summary": map_spec.get("title") or f"Visualização geográfica de {scope}",
            "what_you_see": what_see,
            "what_you_receive": what_rec,
        })

    if charts:
        titles = ", ".join(c.get("title", "Gráfico") for c in charts[:2])
        views.append({
            "key": "charts",
            "label": f"Ver gráficos ({len(charts)})",
            "summary": titles,
            "what_you_see": f"{len(charts)} gráfico(s) interativo(s) montado(s) com os números desta resposta: {titles}.",
            "what_you_receive": "Valores detalhados ao passar o mouse e opção para baixar o gráfico como imagem.",
        })

    if tables:
        purposes = "; ".join(t.get("purpose", "Tabela") for t in tables[:2])
        views.append({
            "key": "data",
            "label": f"Ver resultados ({len(tables)})",
            "summary": purposes,
            "what_you_see": f"{len(tables)} tabela(s) com os números exatos usados na resposta: {purposes}.",
            "what_you_receive": "Dados completos para conferência e botão para baixar a planilha pronta para Excel.",
        })

    if sources:
        law_names = ", ".join(dict.fromkeys(s.get("title", "") for s in sources[:3] if s.get("title")))
        views.append({
            "key": "laws",
            "label": f"Ler trechos da lei ({len(sources)})",
            "summary": law_names or "Artigos das leis ambientais brasileiras",
            "what_you_see": f"{len(sources)} trecho(s) da legislação ambiental federal citados na resposta ({law_names}).",
            "what_you_receive": "Texto original dos artigos consultados e link direto para o documento oficial.",
        })

    return map_spec, charts, views


def _answer_value(value: Any) -> str:
    if value is None:
        return "sem dados"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, Real) and not isinstance(value, bool):
        if not isfinite(value):
            return "sem dados"
        fmt = ",.0f" if value == int(value) else ",.2f"
        return format(value, fmt).translate(str.maketrans(",.", ".,"))
    return str(value)


def _answer_from_evidence(temporal, tables, law_sources, tool_log, has_map, charts) -> str:
    paragraphs = []
    if temporal:
        observed = [frame for frame in temporal["frames"] if frame["value"] is not None]
        heading = f'{temporal["label"]} em {temporal["scope"]}'
        if observed:
            values = [
                f'{frame["period"]}: {_answer_value(frame["value"])} {temporal["unit"]}'
                + (f' (dados até {frame["coverage_through"]})' if frame.get("coverage_through") else "")
                for frame in observed
            ]
            values = values if len(values) <= 6 else [values[0], values[-1]]
            paragraphs.append(f'{heading}. {" · ".join(values)}. Fonte: {temporal["source"]} [T1].')
            if len(observed) < len(temporal["frames"]):
                paragraphs.append("A série tem períodos sem dados.")
        else:
            paragraphs.append(f"{heading}. A série consultada não contém valores para o período [T1].")
    for table in [item for item in tables if item["rows"]][:2]:
        lines = [
            " · ".join(f'{col.replace("_", " ")}: {_answer_value(row.get(col))}' for col in table["columns"][:8])
            for row in table["rows"][:6]
        ]
        paragraphs.append(f'{table["purpose"]} [{table["label"]}].\n\n' + "\n".join(f"- {line}" for line in lines))
        if len(table["rows"]) > len(lines):
            paragraphs.append("Veja as demais linhas na aba Dados.")
    if law_sources:
        paragraphs.append(f'A busca jurídica encontrou {len(law_sources)} trechos. A aba de legislação abre os textos consultados, incluindo {law_sources[0]["title"]} [L1].')
    if paragraphs:
        return "\n\n".join(paragraphs)
    if tables:
        return "A consulta não encontrou registros para esse recorte. Você pode ajustar o período ou o território."
    if any(not call["ok"] for call in tool_log):
        return "A consulta à fonte falhou. Vale tentar novamente para recuperar os dados do recorte."
    if has_map or charts:
        return "A visualização foi preparada. Abra o painel para conferir o recorte e os dados exibidos."
    return "Não consegui concluir a análise. Reformule a pergunta indicando o território, o tema e o período de interesse."


def ask_agro(
    question: str,
    k_laws: int = 6,
    view_context: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from src.llm_tracker import current_trace_id, llm_span, llm_stage
    from src.rag import get_client

    client = get_client()
    user_content = _format_view_context(view_context) + question
    system_blocks = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    messages: list[dict[str, Any]] = [*_sanitize_history(history), {"role": "user", "content": user_content}]
    tool_calls_log: list[dict[str, Any]] = []
    law_sources: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    map_spec: dict[str, Any] = {}
    discovered_codes: list[str] = []
    temporal = None
    used_law_search = False

    in_tokens = 0
    out_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0
    llm_calls = 0
    d_idx = 0
    final_text = ""
    stop_reason = ""

    def _with_tool_cache(tools_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not tools_list:
            return []
        return [
            {**tool, "cache_control": {"type": "ephemeral"}} if idx == len(tools_list) - 1 else tool
            for idx, tool in enumerate(tools_list)
        ]

    for turn_idx in range(1, MAX_TURNS + 1):
        if temporal is not None:
            turn_tools = (
                [t for t in TOOLS if t["name"] == "search_laws"]
                if (not used_law_search and _LAW_HINT_RE.search(question))
                else []
            )
        else:
            turn_tools = TOOLS

        req_kwargs: dict[str, Any] = {
            "model": LLM_MODEL,
            "max_tokens": min(LLM_MAX_TOKENS, 4096),
            "system": system_blocks,
            "messages": messages,
            **LLM_EXTRA_PARAMS,
        }
        if turn_tools:
            req_kwargs["tools"] = _with_tool_cache(turn_tools)

        try:
            with llm_stage(f"agro_chat.loop.turn_{turn_idx}"):
                resp = client.messages.create(**req_kwargs)
        except Exception:
            if not (tables or temporal or law_sources or map_spec or charts):
                raise
            logger.warning("Resposta interrompida após recuperar evidências.", exc_info=True)
            break
        llm_calls += 1
        in_tokens += int(getattr(resp.usage, "input_tokens", 0) or 0)
        out_tokens += int(getattr(resp.usage, "output_tokens", 0) or 0)
        cache_read_tokens += int(getattr(resp.usage, "cache_read_input_tokens", 0) or 0)
        cache_creation_tokens += int(getattr(resp.usage, "cache_creation_input_tokens", 0) or 0)
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
            if name == "set_temporal_view":
                with llm_span("tool:set_temporal_view", input_data=inp) as sp:
                    try:
                        temporal = get_temporal(inp)
                        out_txt = json.dumps({
                            "source": temporal["source"], "scope": temporal["scope"], "unit": temporal["unit"],
                            "series_T1": [(f["period"], f["value"], f.get("coverage_through")) for f in temporal["frames"]],
                            "facts": temporal["facts"],
                        }, ensure_ascii=False)
                        sp.set_output({"source": temporal["source"], "scope": temporal["scope"], "frames": len(temporal["frames"])})
                    except (ValueError, TypeError) as exc:
                        out_txt = f"Recorte temporal inválido: {exc}"
                        sp.set_output({"error": str(exc)})
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out_txt})

            elif name == "query_agro_sql":
                d_idx += 1
                label = f"D{d_idx}"
                sql = str(inp.get("sql", ""))
                purpose = str(inp.get("purpose", "Consulta SQL"))
                with llm_span("tool:query_agro_sql", input_data={"purpose": purpose, "sql": sql}) as sp:
                    try:
                        cols, rows = run_readonly_sql(sql, max_rows=100)
                        for r in rows[:20]:
                            code = r.get("codigo_municipio_ibge") or r.get("code")
                            if isinstance(code, str) and len(code) == 7 and code.isdigit() and code not in discovered_codes:
                                discovered_codes.append(code)
                        tables.append({"label": label, "purpose": purpose, "columns": cols, "rows": rows,
                                       "row_limit": 100, "at_limit": len(rows) == 100})
                        out_txt = _format_table_for_llm(cols, rows, label, purpose)
                        tool_calls_log.append({
                            "label": label, "name": name, "summary": purpose,
                            "ok": True, "rows": len(rows), "seconds": round(time.perf_counter() - t0, 2),
                            "output": sql,
                        })
                        sp.set_output({"label": label, "rows": len(rows), "columns": cols, "sample": rows[:5]})
                    except Exception as exc:
                        out_txt = f"[{label}] ERRO SQL: {exc}"
                        tool_calls_log.append({
                            "label": label, "name": name, "summary": purpose,
                            "ok": False, "rows": 0, "seconds": round(time.perf_counter() - t0, 2),
                            "output": f"{sql}\nErro: {exc}",
                        })
                        sp.set_output({"label": label, "error": str(exc)})
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out_txt})

            elif name == "search_laws":
                used_law_search = True
                q = str(inp.get("query", question))
                with llm_span("retrieve-documents", input_data={"query": q, "k": k_laws}) as sp:
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
                        sp.set_output({"hits": len(hits), "laws": [h["title"] for h in hits[:6]]})
                    except Exception as exc:
                        out_txt = f"Busca jurídica indisponível: {exc}"
                        tool_calls_log.append({
                            "label": "L", "name": name, "summary": q,
                            "ok": False, "rows": 0, "seconds": round(time.perf_counter() - t0, 2),
                            "output": str(exc),
                        })
                        sp.set_output({"error": str(exc)})
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out_txt})

            elif name == "set_map_view":
                with llm_span("tool:set_map_view", input_data=inp) as sp:
                    spec: dict[str, Any] = {}
                    if isinstance(inp.get("title"), str) and inp["title"].strip():
                        spec["title"] = inp["title"].strip()[:120]
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
                    if inp.get("deter_mode") in ("hex", "points"):
                        spec["deter_mode"] = inp["deter_mode"]
                    if isinstance(inp.get("show_facilities"), bool):
                        spec["show_facilities"] = inp["show_facilities"]
                    if inp.get("facilities_chain") in ("bovinos", "soja"):
                        spec["facilities_chain"] = inp["facilities_chain"]
                    if isinstance(inp.get("view_3d"), bool):
                        spec["view_3d"] = inp["view_3d"]
                    if inp.get("basemap") in ("dark", "terrain", "light"):
                        spec["basemap"] = inp["basemap"]
                    if isinstance(inp.get("mapbiomas_mode"), bool):
                        spec["mapbiomas_mode"] = inp["mapbiomas_mode"]
                    if isinstance(inp.get("mapbiomas_year"), int):
                        spec["mapbiomas_year"] = max(1985, min(2025, inp["mapbiomas_year"]))
                    if isinstance(inp.get("mapbiomas_classes"), list):
                        spec["mapbiomas_classes"] = [int(c) for c in inp["mapbiomas_classes"] if isinstance(c, int)][:25]
                    if isinstance(inp.get("highlight_codes"), list):
                        spec["highlight_codes"] = [
                            str(c).strip() for c in inp["highlight_codes"]
                            if str(c).strip().isdigit() and len(str(c).strip()) == 7
                        ][:25]
                    map_spec.update(spec)
                    sp.set_output(spec)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "MapSpec atualizado no Canvas."})

        messages.append({"role": "user", "content": tool_results})

    if not final_text and (tables or temporal or law_sources or map_spec or charts):
        note = {
            "type": "text",
            "text": "Agora responda em português à pergunta original, em texto. Resuma os achados das ferramentas com dados e referências, informe os limites do recorte e encerre sem pedir novas ferramentas.",
        }
        if messages[-1]["role"] == "assistant" and not messages[-1]["content"]:
            messages.pop()
        if messages[-1]["role"] == "user":
            previous = messages[-1]["content"]
            blocks = previous if isinstance(previous, list) else [{"type": "text", "text": previous}]
            messages[-1]["content"] = [*blocks, note]
        else:
            messages.append({"role": "user", "content": [note]})
        try:
            with llm_stage("agro_chat.synthesis_fallback"):
                response = client.with_options(timeout=12, max_retries=0).messages.create(
                    model=LLM_MODEL,
                    max_tokens=2048,
                    system=system_blocks,
                    messages=messages,
                    **LLM_EXTRA_PARAMS,
                )
            llm_calls += 1
            in_tokens += int(getattr(response.usage, "input_tokens", 0) or 0)
            out_tokens += int(getattr(response.usage, "output_tokens", 0) or 0)
            cache_read_tokens += int(getattr(response.usage, "cache_read_input_tokens", 0) or 0)
            cache_creation_tokens += int(getattr(response.usage, "cache_creation_input_tokens", 0) or 0)
            stop_reason = response.stop_reason or stop_reason
            final_text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        except Exception:
            logger.warning("Síntese indisponível. Usando resumo calculado a partir das evidências.", exc_info=True)

    if not final_text:
        final_text = _answer_from_evidence(temporal, tables, law_sources, tool_calls_log, bool(map_spec), charts)

    if discovered_codes and map_spec and "highlight_codes" not in map_spec:
        map_spec["highlight_codes"] = discovered_codes[:15]

    domain = "mixed" if ((tables or temporal) and law_sources) else ("law" if law_sources else "agro")
    formatted_sources = [
        {
            "label": f"L{i}",
            "title": s["title"],
            "artigo": s["metadata"].get("artigo"),
            "parte": s["metadata"].get("parte"),
            "partes": s["metadata"].get("partes"),
            "excerpt": (s.get("content") or "")[:600],
            "url": s["url"],
            "score": float(s["score"]),
            "semantic_rank": s.get("semantic_rank"),
            "keyword_rank": s.get("keyword_rank"),
        }
        for i, s in enumerate(law_sources, 1)
    ]
    final_map, final_charts, available_views = _evaluate_views(
        domain=domain,
        tables=tables,
        charts=charts,
        map_spec=map_spec if map_spec else None,
        sources=formatted_sources,
    )

    dashboard = None
    if tables or temporal:
        from src.dashboard.studio import build_studio_dashboard

        with llm_span("build_studio_dashboard", input_data={"tables": len(tables), "has_temporal": bool(temporal)}) as sp:
            dashboard = build_studio_dashboard(question, tables, temporal)
            if dashboard:
                sp.set_output({"title": dashboard.get("title"), "widgets": len(dashboard.get("widgets") or [])})
        if dashboard:
            if temporal:
                temporal["milestones"] = [f["id"] for f in temporal["facts"][:6]]
                final_map = None
                available_views = [v for v in available_views if v["key"] not in {"map", "data", "charts"}]
                available_views.insert(0, {"key": "timeline", "label": "Reproduzir evolução", "summary": temporal["label"]})
                tables = dashboard["tables"]
            else:
                available_views = [v for v in available_views if v["key"] != "charts"]
            available_views.append({"key": "dashboard", "label": "Abrir dashboard", "summary": dashboard["title"]})
            if temporal:
                available_views.append({"key": "data", "label": "Conferir dados", "summary": "Série temporal e recorte"})
            final_charts = []

    return {
        "answer": final_text,
        "temporal": temporal,
        "dashboard": dashboard,
        "domain": domain,
        "stop_reason": stop_reason,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "total_tokens": in_tokens + out_tokens + cache_read_tokens + cache_creation_tokens,
        "llm_calls": llm_calls,
        "llm_trace_id": current_trace_id() or None,
        "tool_calls": tool_calls_log,
        "tables": tables,
        "charts": final_charts,
        "map_spec": final_map,
        "available_views": available_views,
        "sources": formatted_sources,
    }

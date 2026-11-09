import argparse
import sys

import pandas as pd

from src import queries

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 60)

LEVELS = ["country", "biome", "state", "municipality"]


def print_df(df):
    print("Nenhum resultado encontrado." if df.empty else df.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="RAG do Trase: dados da cadeia da carne bovina (DuckDB) e leis ambientais (pgvector)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- Banco analítico ---
    sub.add_parser("profile", help="Tabelas e views do banco, com linhas e colunas.")
    sub.add_parser("build-db", help="Recria o banco DuckDB a partir dos Parquet.")
    sub.add_parser("reload", help="Alias de build-db.")
    dic = sub.add_parser("dictionary", help="Gera docs/dicionario_dados.md.")
    dic.add_argument("--print", action="store_true", help="Mostra o texto enviado ao LLM em vez de gravar.")

    sql = sub.add_parser("sql", help="Executa um SELECT no banco (somente leitura).")
    sql.add_argument("query")

    find = sub.add_parser("find", help="Procura a grafia de um nome nos dados.")
    find.add_argument("text")
    find.add_argument("--kind", choices=queries.ENTITY_KINDS)

    # --- Consultas prontas ---
    muni = sub.add_parser("top-municipalities", help="Municípios por indicador da cadeia, num ano.")
    muni.add_argument("--limit", type=int, default=10)
    muni.add_argument("--biome")
    muni.add_argument("--state")
    muni.add_argument("--year", type=int)
    muni.add_argument("--order-by", default="deforestation_exposure_ha", choices=sorted(queries.MUNICIPALITY_ORDER))

    exporters = sub.add_parser("top-exporters", help="Grupos exportadores por exposição, num ano.")
    exporters.add_argument("--limit", type=int, default=10)
    exporters.add_argument("--year", type=int)
    exporters.add_argument("--include-domestic", action="store_true")
    exporters.add_argument("--by-company", action="store_true", help="Por empresa em vez de grupo.")

    destinations = sub.add_parser("top-destinations", help="Destinos por volume, num ano.")
    destinations.add_argument("--limit", type=int, default=10)
    destinations.add_argument("--year", type=int)
    destinations.add_argument("--include-domestic", action="store_true")

    trend = sub.add_parser("trend", help="Série anual dos indicadores.")
    trend.add_argument("--biome")
    trend.add_argument("--state")
    trend.add_argument("--municipality")
    trend.add_argument("--exporter-group")

    intensity = sub.add_parser("intensity", help="Exposição por tonelada, por município.")
    intensity.add_argument("--limit", type=int, default=10)
    intensity.add_argument("--biome")
    intensity.add_argument("--year", type=int)
    intensity.add_argument("--min-volume", type=float, default=100.0)

    commitments = sub.add_parser("commitments", help="Resumo por compromisso de desmatamento zero.")
    commitments.add_argument("--year", type=int)
    commitments.add_argument("--include-domestic", action="store_true")

    terr = sub.add_parser("territorial", help="Indicador territorial (spatial_metrics) por região.")
    terr.add_argument("metric", choices=sorted(queries.SPATIAL_METRIC_NAMES))
    terr.add_argument("--level", default="state", choices=LEVELS)
    terr.add_argument("--year", type=int)
    terr.add_argument("--region")
    terr.add_argument("--parent-region")
    terr.add_argument("--limit", type=int, default=10)

    # --- Camada documental ---
    init_db = sub.add_parser("init-vector-db", help="Cria tabelas e índices no Postgres/pgvector.")
    init_db.add_argument("--reset", action="store_true",
                         help="Apaga e recria as tabelas (perde os dados indexados).")
    sub.add_parser("vector-stats", help="Contagem de documentos e chunks indexados.")

    ingest = sub.add_parser("ingest-laws", help="Divide as leis por artigo e indexa no Postgres.")
    ingest.add_argument("--force", action="store_true", help="Reindexa mesmo sem mudança no arquivo.")

    search = sub.add_parser("search", help="Busca nos documentos indexados.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--doc-type")
    search.add_argument("--mode", choices=["hybrid", "semantic"], default="hybrid")

    # --- Chatbot ---
    ask = sub.add_parser("ask", help="Pergunta ao chatbot (dados do Trase + leis, com citações).")
    ask.add_argument("question")
    ask.add_argument("--k", type=int, default=6, help="Quantos trechos de lei por busca.")
    ask.add_argument("--laws-only", action="store_true", help="Só a busca nas leis (fluxo antigo, sem dados).")
    ask.add_argument("--doc-type", help="Com --laws-only: filtra o tipo de documento.")
    ask.add_argument("--show-context", action="store_true", help="Mostra os resultados enviados ao LLM.")

    serve = sub.add_parser("serve", help="Abre uma página web local para testar o chatbot.")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    # Comandos que leem o DuckDB: confere uma vez, aqui, se o banco precisa ser (re)gerado.
    # O "serve" faz o mesmo em src/web.py. Durante as consultas o banco nunca é reconstruído.
    no_duckdb = {"build-db", "reload", "dictionary", "init-vector-db", "vector-stats", "ingest-laws", "search"}
    if args.command not in no_duckdb and not getattr(args, "laws_only", False):
        from src.database import ensure_database
        ensure_database()

    if args.command == "profile":
        from src.database import get_profile
        p = get_profile()
        print(f"Anos na supply_chain: {p['supply_chain_years']}")
        for o in p["objects"]:
            print(f"\n{o['name']} ({o['kind']}, {o['rows']:,} linhas)")
            for name, dtype in o["columns"]:
                print(f"  - {name}: {dtype}")
    elif args.command in ("build-db", "reload"):
        from src.database import build_database
        build_database()
    elif args.command == "dictionary":
        from src.data_dictionary import render_markdown, render_prompt
        if args.print:
            print(render_prompt())
        else:
            from src.config import PROJECT_ROOT
            out = PROJECT_ROOT / "docs" / "dicionario_dados.md"
            out.write_text(render_markdown(), encoding="utf-8")
            print(f"Gravado: {out}")
    elif args.command == "sql":
        from src.database import SqlError, run_readonly_sql
        try:
            df, truncated = run_readonly_sql(args.query)
        except SqlError as e:
            sys.exit(f"Erro: {e}")
        print_df(df)
        if truncated:
            print("(resultado truncado)")
    elif args.command == "find":
        print_df(queries.find_entity(args.text, args.kind))
    elif args.command == "top-municipalities":
        print_df(queries.top_municipalities(args.limit, args.biome, args.year, args.state, args.order_by))
    elif args.command == "top-exporters":
        print_df(queries.top_exporters(args.limit, args.year, args.include_domestic, not args.by_company))
    elif args.command == "top-destinations":
        print_df(queries.top_destinations(args.limit, args.year, args.include_domestic))
    elif args.command == "trend":
        print_df(queries.yearly_trend(args.biome, args.state, args.municipality, args.exporter_group))
    elif args.command == "intensity":
        print_df(queries.exposure_intensity_by_municipality(args.limit, args.biome, args.year, args.min_volume))
    elif args.command == "commitments":
        print_df(queries.commitment_summary(args.year, args.include_domestic))
    elif args.command == "territorial":
        print_df(queries.territorial_metric(args.metric, args.level, args.year, args.region,
                                            args.parent_region, args.limit))
    elif args.command == "init-vector-db":
        from src import vector_store
        if args.reset:
            vector_store.reset_schema()
            print("Tabelas apagadas.")
        vector_store.init_schema()
        print("Esquema vetorial criado/verificado.")
    elif args.command == "vector-stats":
        from src import vector_store
        s = vector_store.stats()
        print(f"Documentos: {s['documents']}  Chunks: {s['chunks']}  Modelos: {s['models']}")
    elif args.command == "ingest-laws":
        from src.ingest_laws import ingest_laws
        ingest_laws(force=args.force)
    elif args.command == "search":
        from src import vector_store
        from src.embeddings import embed_query
        q = embed_query(args.query)
        if args.mode == "hybrid":
            rows = vector_store.hybrid_search(args.query, q, args.limit, doc_type=args.doc_type)
        else:
            rows = vector_store.semantic_search(q, args.limit, doc_type=args.doc_type)
        for i, r in enumerate(rows, 1):
            m = r["metadata"]
            parte = f" (parte {m['parte']}/{m['partes']})" if m.get("partes", 1) > 1 else ""
            ranks = (f"  [semântica #{r['semantic_rank']}, palavra-chave #{r['keyword_rank']}]"
                     if args.mode == "hybrid" else "")
            print(f"\n{i}. {r['title']} - Art. {m.get('artigo')}{parte}  score={float(r['score']):.4f}{ranks}")
            body = r["content"].split("\n")
            print("   " + " ".join(body[1:])[:400] + "...")
    elif args.command == "ask" and not args.laws_only:
        from src.agent import ask as agent_ask, tool_call_summary
        result = agent_ask(args.question, k_laws=args.k)
        if args.show_context:
            print("=== Ferramentas chamadas ===")
            for c in result.tool_calls:
                print(f"\n[{c.label}] {tool_call_summary(c)}  ({c.seconds}s{'' if c.ok else ', ERRO'})")
                print(c.output)
            print()
        print(result.text)
        data_calls = [c for c in result.tool_calls if c.label.startswith("D") and c.ok]
        if data_calls:
            print("\nConsultas:")
            for c in data_calls:
                print(f"  [{c.label}] {tool_call_summary(c)}")
        if result.law_sources:
            print("\nLeis:")
            for i, s in enumerate(result.law_sources, 1):
                m = s["metadata"]
                print(f"  [L{i}] {s['title']}, art. {m.get('artigo')} - {s['url']}")
        print(f"\n(tokens: {result.input_tokens} entrada, {result.output_tokens} saída; "
              f"{len(result.tool_calls)} chamadas de ferramenta)")
    elif args.command == "ask":
        from src.rag import answer, build_context
        result = answer(args.question, k=args.k, doc_type=args.doc_type)
        if args.show_context:
            print("=== Trechos enviados ao LLM ===")
            print(build_context(result.sources))
            print()
        print(result.text)
        print("\nFontes:")
        for i, s in enumerate(result.sources, 1):
            m = s["metadata"]
            parte = f" (parte {m['parte']}/{m['partes']})" if m.get("partes", 1) > 1 else ""
            print(f"  [{i}] {s['title']}, art. {m.get('artigo')}{parte} - {s['url']}")
        print(f"\n(tokens: {result.input_tokens} entrada, {result.output_tokens} saída)")
    elif args.command == "serve":
        from src.web import serve
        serve(args.port)


if __name__ == "__main__":
    main()

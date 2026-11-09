import argparse

from src import queries
from src.database import get_profile, load_csv
from src.soy.catalog import load_manifest
from src.soy.ingest import detect_missing_datasets, get_soy_profile, ingest_soy_datasets
from src.soy.queries import (
    deforestation_by_biome,
    exposure_by_municipality,
    top_destinations,
    top_exporters,
    top_municipalities,
    yearly_trend,
)
from src.soy.routing import route_question


def print_df(df):
    print("Nenhum resultado encontrado." if df.empty else df.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="Consultas iniciais ao dataset Trase de carne bovina e extensões da soja."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profile", help="Mostra perfil, colunas e amostra.")
    sub.add_parser("reload", help="Força a recarga do CSV.")

    muni = sub.add_parser("top-municipalities", help="Municípios por exposição.")
    muni.add_argument("--limit", type=int, default=10)
    muni.add_argument("--biome")
    muni.add_argument("--year", type=int)

    exporters = sub.add_parser("top-exporters", help="Exportadores por exposição.")
    exporters.add_argument("--limit", type=int, default=10)
    exporters.add_argument("--year", type=int)

    destinations = sub.add_parser("top-destinations", help="Destinos por volume.")
    destinations.add_argument("--limit", type=int, default=10)
    destinations.add_argument("--year", type=int)

    sub.add_parser("trend", help="Evolução anual dos indicadores.")

    intensity = sub.add_parser("intensity", help="Exposição por tonelada.")
    intensity.add_argument("--limit", type=int, default=10)
    intensity.add_argument("--biome")

    sub.add_parser("commitments", help="Resumo por compromisso ambiental.")

    init_db = sub.add_parser("init-vector-db", help="Cria tabelas e índices no Postgres/pgvector.")
    init_db.add_argument("--reset", action="store_true", help="Apaga e recria as tabelas (perde os dados indexados).")
    sub.add_parser("vector-stats", help="Contagem de documentos e chunks indexados.")

    ingest = sub.add_parser("ingest-laws", help="Divide as leis por artigo e indexa no Postgres.")
    ingest.add_argument("--force", action="store_true", help="Reindexa mesmo sem mudança no arquivo.")

    soy_profile = sub.add_parser("soy-profile", help="Mostra o perfil dos datasets da soja.")
    soy_profile.add_argument("--full", action="store_true", help="Mostra também a lista de datasets ausentes.")

    ingest_soy = sub.add_parser("ingest-soy", help="Ingesta datasets estruturados da soja em DuckDB.")
    ingest_soy.add_argument("--force", action="store_true", help="Reprocessa mesmo sem mudança no arquivo.")

    soy_muni = sub.add_parser("soy-top-municipalities", help="Ranking de municípios da soja.")
    soy_muni.add_argument("--limit", type=int, default=10)
    soy_muni.add_argument("--year", type=int)
    soy_muni.add_argument("--state")
    soy_muni.add_argument("--biome")

    soy_exporters = sub.add_parser("soy-top-exporters", help="Ranking de exportadores da soja.")
    soy_exporters.add_argument("--limit", type=int, default=10)
    soy_exporters.add_argument("--year", type=int)

    soy_destinations = sub.add_parser("soy-top-destinations", help="Ranking de destinos da soja.")
    soy_destinations.add_argument("--limit", type=int, default=10)
    soy_destinations.add_argument("--year", type=int)

    soy_trend = sub.add_parser("soy-trend", help="Tendências anuais dos indicadores da soja.")

    soy_exposure = sub.add_parser("soy-exposure", help="Exposição por município e bioma para soja.")
    soy_exposure.add_argument("--limit", type=int, default=10)
    soy_exposure.add_argument("--year", type=int)

    search = sub.add_parser("search", help="Busca nos documentos indexados.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--doc-type")
    search.add_argument("--mode", choices=["hybrid", "semantic"], default="hybrid")

    ask = sub.add_parser("ask", help="Pergunta ao chatbot (busca + resposta do LLM com citações).")
    ask.add_argument("question")
    ask.add_argument("--k", type=int, default=6, help="Quantos trechos enviar ao LLM.")
    ask.add_argument("--doc-type")
    ask.add_argument("--domain", choices=["auto", "law", "beef", "soy", "mixed"], default="auto")
    ask.add_argument("--show-context", action="store_true", help="Mostra os trechos enviados ao LLM.")

    serve = sub.add_parser("serve", help="Abre uma página web local para testar o chatbot.")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.command == "profile":
        p = get_profile()
        print(f"Linhas: {p['row_count']}")
        print(f"Intervalo de anos: {p['year_range']}")
        print("\nColunas:")
        for name, dtype in p["columns"]:
            print(f"- {name}: {dtype}")
        print("\nAmostra:")
        print(p["sample"].to_string(index=False))
    elif args.command == "reload":
        load_csv(force_reload=True)
        print("CSV recarregado.")
    elif args.command == "top-municipalities":
        print_df(queries.top_municipalities(args.limit, args.biome, args.year))
    elif args.command == "top-exporters":
        print_df(queries.top_exporters(args.limit, args.year))
    elif args.command == "top-destinations":
        print_df(queries.top_destinations(args.limit, args.year))
    elif args.command == "trend":
        print_df(queries.yearly_trend())
    elif args.command == "intensity":
        print_df(queries.exposure_intensity_by_municipality(args.limit, args.biome))
    elif args.command == "commitments":
        print_df(queries.commitment_summary())
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
    elif args.command == "soy-profile":
        manifest = load_manifest()
        print(f"Datasets esperados: {len(manifest)}")
        print(f"Ausentes: {detect_missing_datasets(manifest)}")
        print(get_soy_profile())
    elif args.command == "ingest-soy":
        summary = ingest_soy_datasets(force=args.force)
        print(summary)
    elif args.command == "soy-top-municipalities":
        print_df(top_municipalities(limit=args.limit, year=args.year, state=args.state, biome=args.biome))
    elif args.command == "soy-top-exporters":
        print_df(top_exporters(limit=args.limit, year=args.year))
    elif args.command == "soy-top-destinations":
        print_df(top_destinations(limit=args.limit, year=args.year))
    elif args.command == "soy-trend":
        print_df(yearly_trend())
    elif args.command == "soy-exposure":
        print_df(exposure_by_municipality(limit=args.limit, year=args.year))
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
            ranks = (f"  [semântica #{r['semantic_rank']}, palavra-chave #{r['keyword_rank']}]" if args.mode == "hybrid" else "")
            print(f"\n{i}. {r['title']} - Art. {m.get('artigo')}{parte}  score={float(r['score']):.4f}{ranks}")
            body = r["content"].split("\n")
            print("   " + " ".join(body[1:])[:400] + "...")
    elif args.command == "ask":
        from src.rag import answer, build_context
        route = route_question(args.question) if args.domain == "auto" else {"domain": args.domain, "retrieval": "hybrid"}
        result = answer(args.question, k=args.k, doc_type=args.doc_type, domain=route["domain"])
        if args.show_context:
            print("=== Trechos enviados ao LLM ===")
            print(build_context(result.sources))
            print()
        print(f"Domínio: {result.domain}")
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

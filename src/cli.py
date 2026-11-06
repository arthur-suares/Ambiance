import argparse
from src.database import get_profile, load_csv
from src import queries


def print_df(df):
    print("Nenhum resultado encontrado." if df.empty else df.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="Consultas iniciais ao dataset Trase de carne bovina."
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

    ask = sub.add_parser("ask", help="Pergunta ao chatbot (busca + resposta do LLM com citações).")
    ask.add_argument("question")
    ask.add_argument("--k", type=int, default=6, help="Quantos trechos enviar ao LLM.")
    ask.add_argument("--doc-type")
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

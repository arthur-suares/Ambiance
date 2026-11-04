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


if __name__ == "__main__":
    main()

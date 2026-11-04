import duckdb
from src.config import CSV_PATH, DUCKDB_PATH, TABLE_NAME

REQUIRED_COLUMNS = {
    "year",
    "biome",
    "municipality_of_production",
    "exporter",
    "country_of_destination",
    "volume",
    "cattle_deforestation_5_year_total_exposure",
    "co2_net_emissions_cattle_deforestation_5_year_total_exposure",
    "land_use",
    "fob",
}


def get_connection():
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DUCKDB_PATH))


def table_exists(con) -> bool:
    result = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [TABLE_NAME],
    ).fetchone()[0]
    return result > 0


def load_csv(force_reload: bool = False) -> None:
    """Carrega o CSV em uma tabela DuckDB."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"CSV não encontrado: {CSV_PATH}. "
            "Coloque-o em data/raw/ ou configure TRASE_CSV_PATH no .env."
        )

    con = get_connection()
    try:
        if table_exists(con) and not force_reload:
            return

        csv_literal = str(CSV_PATH).replace("'", "''")
        con.execute(
            f"""
            CREATE OR REPLACE TABLE {TABLE_NAME} AS
            SELECT * FROM read_csv_auto(
                '{csv_literal}',
                header = true,
                sample_size = -1,
                ignore_errors = false
            )
            """
        )

        columns = {
            row[0] for row in con.execute(f"DESCRIBE {TABLE_NAME}").fetchall()
        }
        missing = REQUIRED_COLUMNS - columns
        if missing:
            con.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
            raise ValueError(
                "Colunas obrigatórias ausentes: " + ", ".join(sorted(missing))
            )
    finally:
        con.close()


def get_connection_with_data():
    load_csv()
    return get_connection()


def get_profile() -> dict:
    con = get_connection_with_data()
    try:
        count = con.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
        columns = con.execute(f"DESCRIBE {TABLE_NAME}").fetchall()
        sample = con.execute(f"SELECT * FROM {TABLE_NAME} LIMIT 5").df()
        years = con.execute(
            f"SELECT MIN(TRY_CAST(year AS INTEGER)), MAX(TRY_CAST(year AS INTEGER)) "
            f"FROM {TABLE_NAME}"
        ).fetchone()
        return {
            "row_count": count,
            "columns": [(row[0], row[1]) for row in columns],
            "year_range": years,
            "sample": sample,
        }
    finally:
        con.close()

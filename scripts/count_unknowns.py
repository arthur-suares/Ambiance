"""Conta valores UNKNOWN, células vazias e IDs placeholder em todos os CSVs de data/raw.

As três contagens são feitas separadamente e depois combinadas ("faltante" =
UNKNOWN, vazio ou ID com X). Para cada arquivo mostra:
  - por coluna: quantas linhas têm UNKNOWN, vazio, ID com X e o total
  - por linha: quantas têm pelo menos uma / todas as colunas em cada categoria

Um valor é considerado "unknown" se contém a palavra UNKNOWN (sem diferenciar
maiúsculas), o que cobre variações como "UNKNOWN CUSTOMER", "UNKNOWN STATE",
"UNKNOWN PORT BRAZIL", etc. Uma célula é "vazia" se não tem conteúdo ou só
espaços em branco. Um "ID com X" é um valor placeholder em colunas de ID
(nome terminando em _id), como "BR-XX", "BR-XXXXXXX" ou "XX". Códigos reais
que só contêm a letra X, como "MX" ou "XU", não entram.

Uso:
    python scripts/count_unknowns.py                 # todos os CSVs de data/raw
    python scripts/count_unknowns.py arquivo.csv ... # arquivos específicos
    python scripts/count_unknowns.py --out resumo.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PATTERN = r"\bUNKNOWN\b"
ID_X_PATTERN = r"(?:[A-Z]{2}-)?X+"


def pct(n, total) -> str:
    return f"{100 * n / total:.2f}%" if total else "0.00%"


def analyze(path: Path) -> list[dict]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    total = len(df)

    unknown = pd.DataFrame(
        {c: df[c].str.contains(PATTERN, case=False, regex=True) for c in df.columns}
    )
    empty = pd.DataFrame({c: df[c].str.strip() == "" for c in df.columns})
    id_x = pd.DataFrame(
        {
            c: df[c].str.strip().str.fullmatch(ID_X_PATTERN)
            if c.lower().endswith("_id")
            else pd.Series(False, index=df.index)
            for c in df.columns
        }
    )
    missing = unknown | empty | id_x

    def row_stats(mask: pd.DataFrame) -> tuple[int, int]:
        if not total:
            return 0, 0
        return int(mask.any(axis=1).sum()), int(mask.all(axis=1).sum())

    stats = {
        "UNKNOWN": row_stats(unknown),
        "Vazio": row_stats(empty),
        "ID com X": row_stats(id_x),
        "Faltante (qualquer um)": row_stats(missing),
    }

    print(f"\n=== {path.name} ===")
    print(f"Linhas: {total:,} | Colunas: {len(df.columns)}")
    label_w = max(len(k) for k in stats)
    print(f"  {'Linhas com...':<{label_w}}  {'>=1 coluna':>20}  {'todas as colunas':>20}")
    for label, (any_n, all_n) in stats.items():
        print(
            f"  {label:<{label_w}}  {f'{any_n:,} ({pct(any_n, total)})':>20}"
            f"  {f'{all_n:,} ({pct(all_n, total)})':>20}"
        )

    n_unknown = unknown.sum()
    n_empty = empty.sum()
    n_id_x = id_x.sum()
    n_missing = missing.sum()
    order = n_missing.sort_values(ascending=False).index

    rows = []
    affected = [c for c in order if n_missing[c] > 0]
    if not affected:
        print("Nenhuma coluna com UNKNOWN, vazia ou ID com X.")
    else:
        col_w = max(len(c) for c in affected)
        print(f"  {'Coluna':<{col_w}}  {'UNKNOWN':>18}  {'Vazio':>18}  {'ID com X':>18}  {'Total':>18}  Exemplos UNKNOWN")
        for c in affected:
            variants = df.loc[unknown[c], c].value_counts().head(3)
            examples = ", ".join(f"{v} ({n:,})" for v, n in variants.items())
            print(
                f"  {c:<{col_w}}"
                f"  {f'{n_unknown[c]:,} ({pct(n_unknown[c], total)})':>18}"
                f"  {f'{n_empty[c]:,} ({pct(n_empty[c], total)})':>18}"
                f"  {f'{n_id_x[c]:,} ({pct(n_id_x[c], total)})':>18}"
                f"  {f'{n_missing[c]:,} ({pct(n_missing[c], total)})':>18}"
                f"  {examples}"
            )

    for c in order:
        rows.append(
            {
                "arquivo": path.name,
                "coluna": c,
                "total_linhas": total,
                "linhas_unknown": int(n_unknown[c]),
                "linhas_vazias": int(n_empty[c]),
                "linhas_id_x": int(n_id_x[c]),
                "linhas_faltantes": int(n_missing[c]),
                "pct_unknown": round(100 * n_unknown[c] / total, 4) if total else 0.0,
                "pct_vazias": round(100 * n_empty[c] / total, 4) if total else 0.0,
                "pct_id_x": round(100 * n_id_x[c] / total, 4) if total else 0.0,
                "pct_faltantes": round(100 * n_missing[c] / total, 4) if total else 0.0,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="CSVs a analisar (padrão: data/raw/*.csv)")
    parser.add_argument("--out", type=Path, help="salva o resumo por coluna neste CSV")
    args = parser.parse_args()

    files = args.files or sorted(RAW_DIR.glob("*.csv"))
    if not files:
        sys.exit(f"Nenhum CSV encontrado em {RAW_DIR}")

    all_rows = []
    for f in files:
        try:
            all_rows.extend(analyze(f))
        except Exception as e:  # noqa: BLE001 - segue para os demais arquivos
            print(f"\n=== {f.name} ===\nERRO ao ler: {e}")

    if args.out:
        pd.DataFrame(all_rows).to_csv(args.out, index=False)
        print(f"\nResumo salvo em {args.out}")


if __name__ == "__main__":
    main()

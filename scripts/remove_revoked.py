"""Remove trechos revogados (texto riscado) das leis baixadas do Planalto.

Entrada:  docs/leis/original/*.{htm,html}  (HTML original, Windows-1252, não modificado)
Saída:    docs/leis/*.{htm,html}           (HTML limpo, UTF-8)

Regras:
- remove todo conteúdo riscado (redação revogada ou alterada). O Planalto
  marca isso de duas formas: tags <strike>/<s>/<del> e estilo inline
  "text-decoration: line-through";
- se o parágrafo que continha o <strike> ficar só com notas órfãs, como
  "(Revogado pelo Decreto nº ...)", "(Vigência)", "(Vide ADI ...)",
  "Prejudicada" ou um rótulo solto como "Art. 61-A.", remove o parágrafo;
- trechos vigentes no mesmo parágrafo são preservados.

Uso: python scripts/remove_revoked.py
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

from bs4 import BeautifulSoup

LAWS_DIR = Path(__file__).resolve().parents[1] / "docs" / "leis"
ORIGINAL_DIR = LAWS_DIR / "original"
MANIFEST = LAWS_DIR / "manifest.json"
SOURCE_ENCODING = "cp1252"
HTML_EXTENSIONS = {".htm", ".html"}

BLOCK_TAGS = ["p", "td", "li", "blockquote"]
STRUCK_TAGS = ["strike", "s", "del"]
LINE_THROUGH = re.compile(r"text-decoration\s*:[^;]*line-through", re.I)
PARENTHETICAL = re.compile(r"\([^)]*\)")
ORPHAN_WORDS = re.compile(r"\b(Vigência( encerrada)?|Prejudicad[oa]|Revogad[oa])\b", re.I)
BARE_LABEL = re.compile(
    r"^(Art\.?\s*\d+[\wº°]*(-[A-Z])?\.?|§\s*\d+\s*[º°o]?\.?|[IVXLC]+\s*[-–]|[a-z]\))$"
)


def is_orphan(text: str) -> bool:
    rest = PARENTHETICAL.sub(" ", text)
    rest = ORPHAN_WORDS.sub(" ", rest)
    rest = re.sub(r"[\s.,;:\-–]+", " ", rest).strip()
    return not rest or bool(BARE_LABEL.match(rest))


def is_struck(tag) -> bool:
    return tag.name in STRUCK_TAGS or bool(LINE_THROUGH.search(tag.get("style") or ""))


def clean(html: str) -> tuple[str, int, int]:
    soup = BeautifulSoup(html, "lxml")
    strikes = soup.find_all(is_struck)

    parents = []
    for s in strikes:
        if s.name in BLOCK_TAGS:
            continue  # o próprio parágrafo está riscado: sai inteiro
        parent = s.find_parent(BLOCK_TAGS) or s.parent
        if parent is not None and parent not in parents:
            parents.append(parent)

    for s in strikes:
        if not s.decomposed:  # pode já ter saído junto com um ancestral riscado
            s.decompose()

    dropped = 0
    for parent in parents:
        if parent.decomposed:
            continue
        text = re.sub(r"\s+", " ", parent.get_text(" ")).strip()
        if is_orphan(text):
            parent.decompose()
            dropped += 1

    # Declara UTF-8 no arquivo de saída.
    for meta in soup.find_all("meta"):
        if meta.get("charset") or "charset" in (meta.get("content") or "").lower():
            meta.decompose()
    if soup.head is None:
        soup.html.insert(0, soup.new_tag("head"))
    soup.head.insert(0, soup.new_tag("meta", charset="utf-8"))

    return str(soup), len(strikes), dropped


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def law_files(directory: Path):
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in HTML_EXTENSIONS
    )


def main() -> None:
    ORIGINAL_DIR.mkdir(exist_ok=True)
    # Primeira execução: move os originais para original/.
    for f in law_files(LAWS_DIR):
        target = ORIGINAL_DIR / f.name
        if not target.exists():
            shutil.move(str(f), target)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_name = {Path(e["file"]).name: e for e in manifest}

    for src in law_files(ORIGINAL_DIR):
        html = src.read_text(encoding=SOURCE_ENCODING)
        cleaned, n_strikes, n_dropped = clean(html)
        out = LAWS_DIR / src.name
        out.write_text(cleaned, encoding="utf-8")
        print(f"{src.name}: {n_strikes} trechos revogados removidos, "
              f"{n_dropped} parágrafos órfãos removidos")

        entry = by_name.get(src.name)
        if entry:
            entry["file"] = f"docs/leis/{src.name}"
            entry["original_file"] = f"docs/leis/original/{src.name}"
            entry["original_encoding"] = SOURCE_ENCODING
            entry["original_sha256"] = sha256(src)
            entry["encoding"] = "utf-8"
            entry["sha256"] = sha256(out)
            entry["processing"] = "trechos revogados (<strike> e line-through) removidos por scripts/remove_revoked.py"
            entry.pop("encoding_original", None)

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

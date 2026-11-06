"""Divide o HTML limpo de uma lei em artigos (unidade de chunk do RAG jurídico).

Cada artigo vira um chunk com:
- o caput e todos os seus parágrafos (§), incisos e alíneas;
- um cabeçalho de contexto: nome da lei + Título/Capítulo/Seção onde o artigo está.

Artigos maiores que o limite de tokens do modelo de embedding são divididos em
partes, e cada parte repete o cabeçalho e o caput para não perder o contexto.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup

# "Art. 1º", "Art 2º -", "Art.16", "Art. 61-A.", "Art. 1º-A." (o Planalto varia o formato).
# Sufixo "-A": colado ao número ("61-A") ou com espaço mas seguido de ponto ("9o -A.").
# Em "Art 2º - A Política" o "A" é texto, não sufixo.
ARTICLE_RE = re.compile(
    r"^Art\.?\s*(\d+)\s*(?:º|°|o(?=\W))?(?:-([A-Z])(?![a-zà-ú])|\s-\s?([A-Z])(?=\.))?\s*[.\-–]?\s*"
)
# Artigo sem conteúdo: só "(VETADO)", "(Revogado)" etc. depois do rótulo.
EMPTY_BODY_RE = re.compile(r"^[\s.\-–]*(\([^)]*\)[\s.\-–]*)*$")
# Hierarquia de uma lei, do nível mais alto ao mais baixo.
HEADING_LEVELS = ["LIVRO", "TÍTULO", "CAPÍTULO", "SEÇÃO", "SUBSEÇÃO"]
HEADING_RE = re.compile(
    r"^(LIVRO|T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\s+([IVXLCDM]+|[ÚU]NIC[OA])\b",
    re.I,
)
END_RE = re.compile(r"^Bras[íi]lia\s*,")
EMENTA_RE = re.compile(r"^(Disp[õo]e|Regulamenta|Institui|Altera|Estabelece)\b")
NOISE_RE = re.compile(r"^(Texto compilado|Mensagem de veto|Vig[êe]ncia|\(Vide|Regulamento)", re.I)


@dataclass
class Article:
    number: str                      # "12", "61-A" ou "ementa"
    hierarchy: list[str]             # ["CAPÍTULO IV – DA ÁREA DE RESERVA LEGAL", ...]
    paragraphs: list[str]            # caput primeiro, depois §, incisos, alíneas


@dataclass
class LawChunk:
    text: str                        # texto completo que será embedado e mostrado ao LLM
    article: str
    part: int
    parts: int
    hierarchy: list[str] = field(default_factory=list)
    token_count: int | None = None

def _split_oversized(paragraph, prefix, count_tokens, max_tokens) -> list[str]:
    """Quebra um único parágrafo maior que o limite em pedaços por frase/palavra."""
    if count_tokens(prefix + "\n" + paragraph) <= max_tokens:
        return [paragraph]
    words, pieces, buf = paragraph.split(" "), [], []
    for w in words:
        if buf and count_tokens(prefix + "\n" + " ".join(buf + [w])) > max_tokens:
            pieces.append(" ".join(buf))
            buf = []
        buf.append(w)
    if buf:
        pieces.append(" ".join(buf))
    return pieces

def build_chunks(
    law_title: str,
    ementa: str | None,
    articles: list[Article],
    count_tokens: Callable[[str], int],
    max_tokens: int = 480,
    split_tokens: int = 256,
) -> list[LawChunk]:
    """Transforma artigos em chunks.

    - Artigo que cabe em max_tokens vira um chunk inteiro.
    - Artigo maior é dividido em partes de até split_tokens. As partes são
      menores de propósito: um chunk com muitos incisos sobre assuntos
      diferentes (ex.: as definições do art. 3º do Código Florestal) gera um
      embedding "diluído", que não fica próximo de nenhuma pergunta específica.
    """
    chunks: list[LawChunk] = []

    if ementa:
        text = f"{law_title}\nEmenta: {ementa}"
        chunks.append(LawChunk(text, "ementa", 1, 1, [], count_tokens(text)))

    for art in articles:
        header = law_title + ("\n" + " > ".join(art.hierarchy) if art.hierarchy else "")
        full = header + "\n" + "\n".join(art.paragraphs)
        if count_tokens(full) <= max_tokens:
            chunks.append(LawChunk(full, art.number, 1, 1, art.hierarchy, count_tokens(full)))
            continue

        # Artigo longo: agrupa parágrafos até o limite; cada parte repete header + caput.
        caput, rest = art.paragraphs[0], art.paragraphs[1:]
        prefix = header + "\n" + caput
        if count_tokens(prefix) > split_tokens // 2:
            # Caput enorme: não repete inteiro, só o rótulo do artigo.
            prefix = header + f"\nArt. {art.number} (continuação)"
            rest = art.paragraphs
        groups: list[list[str]] = [[]]
        for p in rest:
            for piece in _split_oversized(p, prefix, count_tokens, split_tokens):
                candidate = prefix + "\n" + "\n".join(groups[-1] + [piece])
                if groups[-1] and count_tokens(candidate) > split_tokens:
                    groups.append([])
                groups[-1].append(piece)
        for i, group in enumerate(groups, start=1):
            text = prefix + "\n" + "\n".join(group)
            chunks.append(LawChunk(text, art.number, i, len(groups), art.hierarchy, count_tokens(text)))

    return chunks

def _normalize_heading(word: str) -> str:
    w = word.upper()
    for level in HEADING_LEVELS:
        if w.replace("Í", "I").replace("Ç", "C").replace("Ã", "A") == \
           level.replace("Í", "I").replace("Ç", "C").replace("Ã", "A"):
            return level
    return w


def extract_paragraphs(html: str) -> list[str]:
    """Texto de cada bloco (<p> ou célula de tabela sem <p>), com espaços normalizados."""
    soup = BeautifulSoup(html, "lxml")
    blocks = []
    for el in soup.find_all(["p", "td"]):
        if el.name == "td" and el.find("p"):
            continue
        text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
        # get_text(" ") separa "1" e "º" em <sup>; junta de volta.
        text = re.sub(r"(\d)\s+([º°o])(?=\W)", r"\1\2", text)
        text = re.sub(r"\s+([.,;:)])", r"\1", text)
        if text:
            blocks.append(text)
    return blocks

def parse_law(html: str) -> tuple[str | None, list[Article]]:
    """Retorna (ementa, artigos). Ignora preâmbulo, assinaturas e anexos."""
    paragraphs = extract_paragraphs(html)
    ementa = None
    hierarchy: dict[str, str] = {}
    pending_heading: str | None = None  # nível cujo nome ainda vai aparecer na linha seguinte
    articles: list[Article] = []
    current: Article | None = None

    for text in paragraphs:
        if END_RE.match(text):
            break

        heading = HEADING_RE.match(text)
        if heading:
            level = _normalize_heading(heading.group(1))
            # Zera os níveis abaixo deste (novo capítulo apaga a seção anterior).
            for lower in HEADING_LEVELS[HEADING_LEVELS.index(level):]:
                hierarchy.pop(lower, None)
            hierarchy[level] = text.upper()
            pending_heading = level if len(text) <= len(heading.group(0)) + 2 else None
            current = None
            continue

        if pending_heading and not ARTICLE_RE.match(text) and len(text) < 200:
            hierarchy[pending_heading] += " – " + text.upper()
            pending_heading = None
            continue
        pending_heading = None

        art = ARTICLE_RE.match(text)
        if art:
            suffix = art.group(2) or art.group(3)
            number = art.group(1) + (f"-{suffix}" if suffix else "")
            if EMPTY_BODY_RE.match(text[art.end():]):
                current = None  # vetado/revogado sem texto: não vira chunk
                continue
            current = Article(
                number=number,
                hierarchy=[hierarchy[l] for l in HEADING_LEVELS if l in hierarchy],
                paragraphs=[text],
            )
            articles.append(current)
            continue

        if current is not None:
            current.paragraphs.append(text)
        elif ementa is None and EMENTA_RE.match(text):
            ementa = text
        # Demais linhas antes do primeiro artigo (título, notas) são descartadas.

    return ementa, articles

def parse_law_file(path: Path) -> tuple[str | None, list[Article]]:
    return parse_law(path.read_text(encoding="utf-8"))

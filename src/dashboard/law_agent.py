"""Agente de leis (G): datasets sobre a legislação ambiental para painéis, sem inventar números.

Dois tipos de dataset, ambos `DatasetResult` com `database="laws"` e fonte "Legislação — Planalto":
- (a) metadados do acervo, por SQL somente-leitura determinístico no Postgres (leis por tipo, ano, tema
  e número de artigos);
- (b) fatos extraídos dos trechos recuperados pela busca já existente (`src.rag.retrieve`, só importada):
  lei, artigo, tipo, valor_min, valor_max, unidade (por linha), prazo, citacao_literal, url_fonte.

O LLM só EXTRAI; o código CONFERE (G2): cada número e cada citação literal precisam existir no texto do
trecho de onde vieram. Linha que não passa é descartada e o painel diz quantas foram. Lei, artigo e URL
vêm dos metadados do trecho, nunca do LLM. Nada é somado entre leis e nenhuma multa total é calculada.
Os widgets dos painéis de lei são montados aqui, em código (`build_law_widgets`).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from src.dashboard.schemas import LAWS_DATABASE, LAWS_SOURCE, DatasetResult, WidgetSpec

logger = logging.getLogger(__name__)

LAW_FOOTER = ("Texto das normas conforme o acervo consolidado; confirme a vigência. "
              "Isto não é aconselhamento jurídico.")
UNAVAILABLE_MESSAGE = ("O acervo de leis não está disponível agora, então não consegui montar a parte "
                       "das leis. Tente de novo mais tarde.")
FACT_TYPES = {"penalidade": "Penalidade", "obrigacao": "Obrigação", "prazo": "Prazo", "percentual": "Percentual"}

# Unidade de cada linha: só formas conhecidas (o resto é descartado na conferência).
_UNIT_ALIASES = {
    "r$": "R$", "reais": "R$", "real": "R$", "brl": "R$",
    "r$ por hectare": "R$ por hectare", "r$/ha": "R$ por hectare", "reais por hectare": "R$ por hectare",
    "r$ por hectare ou fracao": "R$ por hectare", "r$ por unidade": "R$ por unidade",
    "r$ por metro cubico": "R$ por m³", "r$/m3": "R$ por m³", "r$ por m³": "R$ por m³",
    "%": "%", "por cento": "%", "percentual": "%",
    "dias": "dias", "dia": "dias", "meses": "meses", "mes": "meses", "anos": "anos", "ano": "anos",
    "hectares": "hectares", "ha": "hectares", "modulos fiscais": "módulos fiscais",
}

_THEMES = (
    ("Florestas e vegetação", r"florest|mata atl|vegeta"),
    ("Crimes e infrações", r"crime|infra[cç]"),
    ("Clima e carbono", r"clima|carbono"),
    ("Povos indígenas e quilombolas", r"indi[gö]en|indio|quilomb"),
    ("Terra e reforma agrária", r"fundi[aá]r|agr[aá]ria|fun[cç][aã]o social"),
    ("Rastreabilidade", r"rastreab"),
    ("Água", r"h[ií]dric"),
    ("Agrotóxicos", r"agrot[oó]x"),
    ("Fogo", r"fogo"),
    ("Crédito e política agrícola", r"cr[eé]dito|agr[ií]cola|fomento"),
    ("Unidades de conservação", r"snuc|conserva[cç]"),
    ("Meio ambiente (geral)", r"meio ambiente"),
    ("Regularização ambiental", r"\bpra\b|regulariza"),
)

EXTRACT_SCHEMA = {
    "type": "object",
    "required": ["rows"],
    "properties": {
        "rows": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "required": ["trecho", "tipo", "citacao_literal"],
                "properties": {
                    "trecho": {"type": "integer", "description": "Índice do <documento> de onde veio (1, 2...)."},
                    "tipo": {"type": "string", "enum": list(FACT_TYPES)},
                    "valor_min": {"type": ["number", "null"]},
                    "valor_max": {"type": ["number", "null"]},
                    "unidade": {"type": ["string", "null"]},
                    "prazo": {"type": ["string", "null"]},
                    "citacao_literal": {"type": "string", "description": "Cópia exata de um trecho do documento."},
                },
            },
        },
    },
}

EXTRACT_PROMPT = """\
Você extrai fatos de trechos de leis brasileiras para uma tabela. Regras:
- Use SÓ o que está escrito nos <documento>. Não estime, não calcule, não some, não converta.
- Cada linha: o índice do documento (`trecho`), o tipo (penalidade, obrigacao, prazo, percentual), os \
números exatamente como estão no texto (valor_min e valor_max; um só valor: os dois iguais), a unidade \
desta linha (R$, R$ por hectare, %, dias, meses, anos, hectares) e uma `citacao_literal` copiada \
EXATAMENTE do documento (uma frase, sem reticências), que contenha os números da linha.
- Sem número no texto, deixe valor_min/valor_max nulos. Não junte faixas de leis diferentes.
- Não escreva opinião nem interpretação."""


@dataclass
class LawAgentResult:
    datasets: list[DatasetResult] = field(default_factory=list)
    available: bool = True
    kept: int = 0
    dropped: int = 0
    notes: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


# --- Normalização e conferência (G2) ---------------------------------------------------

def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = re.sub(r"[‐-―−]", "-", t)
    return re.sub(r"\s+", " ", t).strip()


_NUM_RE = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")


def numbers_in(text: str) -> set[float]:
    """Números escritos no texto, no padrão brasileiro ("50.000.000,00" -> 50000000.0; "20%" -> 20.0)."""
    out = set()
    for m in _NUM_RE.findall(text or ""):
        try:
            out.add(float(m.replace(".", "").replace(",", ".")))
        except ValueError:
            continue
    return out


def _unit(raw) -> str | None:
    if raw is None:
        return None
    key = _norm(str(raw)).replace(" ou fracao", "").strip()
    if key in _UNIT_ALIASES:
        return _UNIT_ALIASES[key]
    return _UNIT_ALIASES.get(_norm(str(raw)))


def verify_row(row: dict, chunks: list[dict]) -> dict | None:
    """Confere uma linha extraída contra o trecho de origem. Devolve a linha final ou None (descartada)."""
    try:
        idx = int(row.get("trecho"))
    except (TypeError, ValueError):
        return None
    if not 1 <= idx <= len(chunks):
        return None
    chunk = chunks[idx - 1]
    texto = chunk.get("content") or ""
    ntexto = _norm(texto)
    citacao = str(row.get("citacao_literal") or "").strip()
    if len(citacao) < 15 or "..." in citacao or "…" in citacao or _norm(citacao) not in ntexto:
        return None
    tipo = str(row.get("tipo") or "")
    if tipo not in FACT_TYPES:
        return None
    nums = numbers_in(texto)
    valores = []
    for campo in ("valor_min", "valor_max"):
        v = row.get(campo)
        if v is None:
            valores.append(None)
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if v not in nums:
            return None  # número que não está no texto do trecho
        valores.append(v)
    vmin, vmax = valores
    if vmin is not None and vmax is not None and vmin > vmax:
        return None
    unidade = _unit(row.get("unidade"))
    if (vmin is not None or vmax is not None) and unidade is None:
        return None
    if unidade and unidade.startswith("R$") and "r$" not in ntexto and "reais" not in ntexto:
        return None
    prazo = str(row.get("prazo") or "").strip() or None
    if prazo and (not numbers_in(prazo) <= nums):
        return None
    meta = chunk.get("metadata") or {}
    url = str(chunk.get("url") or "").strip()
    if not url:
        return None
    return {
        "lei": short_law_name(chunk.get("title") or ""),
        "artigo": f"art. {meta.get('artigo')}" if meta.get("artigo") else "",
        "tipo": FACT_TYPES[tipo],
        "valor_min": vmin,
        "valor_max": vmax,
        "unidade": unidade or "",
        "prazo": prazo or "",
        "citacao_literal": citacao,
        "url_fonte": url,
    }


def verify_rows(rows: list[dict], chunks: list[dict]) -> tuple[pd.DataFrame, int]:
    kept = []
    seen = set()
    for r in rows or []:
        out = verify_row(r if isinstance(r, dict) else {}, chunks)
        if out is None:
            continue
        key = (out["lei"], out["artigo"], out["citacao_literal"])
        if key not in seen:
            seen.add(key)
            kept.append(out)
    dropped = len(rows or []) - len(kept)
    cols = ["lei", "artigo", "tipo", "valor_min", "valor_max", "unidade", "prazo", "citacao_literal", "url_fonte"]
    return pd.DataFrame(kept, columns=cols), dropped


def short_law_name(title: str) -> str:
    """"Lei nº 9.605/1998 — Lei de Crimes Ambientais" -> "Lei 9.605/1998 (Lei de Crimes Ambientais)"."""
    t = re.sub(r"\s+", " ", title or "").strip()
    t = re.sub(r"\bn\s*[º°o.]\s*", "", t, flags=re.IGNORECASE)
    partes = re.split(r"\s+[—–-]\s+", t, maxsplit=1)
    return f"{partes[0]} ({partes[1]})" if len(partes) == 2 else t


def law_type(title: str) -> str:
    low = _norm(title)
    if low.startswith("lei complementar"):
        return "Lei complementar"
    if low.startswith("decreto"):
        return "Decreto"
    if low.startswith("lei"):
        return "Lei"
    return "Outra norma"


def law_themes(title: str) -> list[str]:
    low = _norm(title)
    temas = [nome for nome, pad in _THEMES if re.search(pad, low)]
    return temas or ["Outros"]


# --- Acesso ao acervo (somente leitura) ------------------------------------------------

def laws_available() -> bool:
    try:
        from src import vector_store

        with vector_store.get_connection(register=False) as con:
            con.execute("SELECT 1")
        return True
    except Exception:  # Postgres desligado, sem driver, sem permissão...
        logger.info("Acervo de leis indisponível.", exc_info=True)
        return False


_CATALOG_SQL = """
    SELECT d.title, d.url, d.metadata->>'enacted_at' AS enacted_at,
           COUNT(DISTINCT c.metadata->>'artigo') AS artigos
    FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
    WHERE d.doc_type = 'law'
    GROUP BY d.id, d.title, d.url, d.metadata->>'enacted_at'
    ORDER BY 3
"""


def fetch_catalog() -> list[dict]:
    from src import vector_store

    with vector_store.get_connection(register=False) as con:
        con.read_only = True  # transação somente-leitura
        return list(con.execute(_CATALOG_SQL).fetchall())


def catalog_frames(rows: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(leis, normas por ano, matriz lei × tema), tudo contado das linhas do acervo."""
    leis = []
    for r in rows:
        ano = str(r.get("enacted_at") or "")[:4]
        leis.append({
            "lei": short_law_name(r.get("title") or ""),
            "tipo": law_type(r.get("title") or ""),
            "ano": int(ano) if ano.isdigit() else None,
            "artigos": int(r.get("artigos") or 0),
            "temas": " · ".join(law_themes(r.get("title") or "")),
            "url_fonte": str(r.get("url") or ""),
        })
    df = pd.DataFrame(leis, columns=["lei", "tipo", "ano", "artigos", "temas", "url_fonte"])
    por_ano = (df.dropna(subset=["ano"]).groupby("ano").agg(normas=("lei", "count"), url_fonte=("url_fonte", "first"))
               .reset_index().astype({"ano": int}))
    # Anos esparsos (1965, 1981...): o eixo usa o ano como rótulo, sem preencher anos sem norma.
    por_ano.insert(1, "publicacao", por_ano["ano"].astype(str))
    todos = sorted({t for ts in df["temas"] for t in ts.split(" · ")}) if not df.empty else []
    matriz = pd.DataFrame([
        {"lei": r.lei, **{t: ("●" if t in r.temas.split(" · ") else "") for t in todos}, "url_fonte": r.url_fonte}
        for r in df.itertuples()
    ], columns=["lei", *todos, "url_fonte"])
    return df, por_ano, matriz


# --- Agente ------------------------------------------------------------------------

_CATALOG_HINT_RE = re.compile(r"acervo|quantas (?:leis|normas)|(?:leis|normas) por|linha do tempo|por ano|por tema"
                              r"|artigos|tipos? de norma|matriz")
_FACTS_HINT_RE = re.compile(r"multa|penalidad|san[cç]|prazo|percentu|obriga|exig|valor|reserva legal|app\b")


def _dataset(did: str, df: pd.DataFrame, query: str, purpose: str) -> DatasetResult:
    return DatasetResult(dataset_id=did, database=LAWS_DATABASE, source_label=LAWS_SOURCE, tool_name="search_laws",
                         query_summary=query, df=df, purpose=purpose)


def run_law_agent(
    question: str,
    *,
    start_index: int = 1,
    available: bool | None = None,
    retriever=None,
    extractor=None,
    catalog_fetch=None,
    k: int = 8,
) -> LawAgentResult:
    """Monta os datasets de leis para o painel. Sem acervo, devolve `available=False` e uma frase simples."""
    res = LawAgentResult()
    if available is None:
        available = laws_available()
    if not available:
        res.available = False
        res.notes = UNAVAILABLE_MESSAGE
        return res

    nxt = start_index
    norm_q = _norm(question)
    want_catalog = bool(_CATALOG_HINT_RE.search(norm_q))
    want_facts = bool(_FACTS_HINT_RE.search(norm_q)) or not want_catalog
    try:
        if want_catalog:
            leis, por_ano, matriz = catalog_frames((catalog_fetch or fetch_catalog)())
            for df, q, p in ((leis, "SELECT documentos do acervo (somente leitura)", "Leis do acervo"),
                             (por_ano, "Contagem das leis do acervo por ano de publicação", "Normas por ano"),
                             (matriz, "Temas pelo título de cada lei (regra fixa em código)", "Leis × tema")):
                if not df.empty:
                    res.datasets.append(_dataset(f"D{nxt}", df, q, p))
                    nxt += 1
        if want_facts:
            if retriever is None:
                from src.rag import retrieve as retriever  # só leitura: a busca existente, sem alteração
            chunks = list(retriever(question, k) or [])
            rows, in_tok, out_tok = (extractor or extract_facts)(question, chunks)
            res.input_tokens += in_tok
            res.output_tokens += out_tok
            facts, dropped = verify_rows(rows, chunks)
            res.kept, res.dropped = len(facts), dropped
            if not facts.empty:
                res.datasets.append(_dataset(
                    f"D{nxt}", facts, f"busca nas leis: {question!r} (k={k}); extração conferida em código",
                    "Fatos das leis conferidos no texto"))
    except Exception:
        logger.exception("Falha ao montar os dados de leis.")
        res.available = False
        res.notes = UNAVAILABLE_MESSAGE
        res.datasets = []
        return res
    if res.dropped:
        res.notes = dropped_message(res.dropped)
    return res


def dropped_message(n: int) -> str:
    """Frase simples sobre as linhas descartadas na conferência."""
    if n == 1:
        return "1 informação das leis não pôde ser conferida no texto da norma e ficou de fora."
    return f"{n} informações das leis não puderam ser conferidas no texto da norma e ficaram de fora."


def extract_facts(question: str, chunks: list[dict]) -> tuple[list[dict], int, int]:
    """O LLM extrai linhas dos trechos (o código confere depois em `verify_rows`)."""
    if not chunks:
        return [], 0, 0
    from src.dashboard._llm import call_structured_llm
    from src.rag import build_context  # só leitura

    payload, in_tok, out_tok = call_structured_llm(
        system=EXTRACT_PROMPT,
        user_content=f"Pedido: {question}\n\n{build_context(chunks)}",
        tool_name="emit_law_facts",
        tool_description="Linhas de fatos copiados dos trechos de lei.",
        input_schema=EXTRACT_SCHEMA,
        max_tokens=3000,
    )
    return list(payload.get("rows") or []), in_tok, out_tok


# --- Widgets dos painéis de lei (montados em código) -------------------------------------

def _w(**kw) -> WidgetSpec:
    did = kw["dataset_id"]
    kw.setdefault("source", f"{LAWS_SOURCE} [{did}]")
    return WidgetSpec(**kw)


def build_law_widgets(result: LawAgentResult) -> tuple[list[WidgetSpec], list[DatasetResult]]:
    """Widgets fixos para os datasets de leis. Faixa de multa: um gráfico por unidade (sem misturar)."""
    widgets: list[WidgetSpec] = []
    extra: list[DatasetResult] = []
    ids = [int(d.dataset_id[1:]) for d in result.datasets if d.dataset_id[1:].isdigit()]
    nxt = (max(ids) + 1) if ids else 1
    for ds in result.datasets:
        df, did = ds.df, ds.dataset_id
        if "citacao_literal" in df.columns:
            widgets.append(_w(id=f"lei_cmp_{did}", kind="table", title="Comparativo das normas encontradas",
                              dataset_id=did, unit="texto", span=2,
                              columns=["lei", "artigo", "tipo", "valor_min", "valor_max", "unidade", "prazo",
                                       "url_fonte"],
                              column_labels={"lei": "Norma", "artigo": "Artigo", "tipo": "Tipo",
                                             "valor_min": "Mínimo", "valor_max": "Máximo", "unidade": "Unidade",
                                             "prazo": "Prazo", "url_fonte": "Fonte"}))
            valores = df.dropna(subset=["valor_min", "valor_max"], how="all")
            for unidade, parte in valores.groupby("unidade", sort=False):
                rotulo = parte["lei"].str.replace(r"\s*\(.*\)$", "", regex=True) + ", " + parte["artigo"]
                # Mesmo artigo com dois valores (ex.: 80% e 35%): cada linha é um item, nunca somada.
                ordem = rotulo.groupby(rotulo).cumcount()
                repetido = rotulo.map(rotulo.value_counts()) > 1
                rotulo = rotulo.where(~repetido, rotulo + " (" + ordem.map(lambda i: "abcdefgh"[i % 8]) + ")")
                parte = parte.assign(rotulo=rotulo).reset_index(drop=True)
                sub_id = f"D{nxt}"
                nxt += 1
                extra.append(_dataset(sub_id, parte, f"{ds.query_summary} — linhas em {unidade} de [{did}]",
                                      f"Valores em {unidade}"))
                faixa = (parte["valor_min"].notna() & parte["valor_max"].notna()
                         & (parte["valor_min"] != parte["valor_max"])).any()
                if faixa:
                    widgets.append(_w(id=f"lei_faixa_{sub_id}", kind="range", dataset_id=sub_id, unit=unidade,
                                      title=f"Faixa de valores por artigo ({unidade})", x="rotulo",
                                      y=["valor_min", "valor_max"], orientation="h", span=2,
                                      column_labels={"rotulo": "Artigo", "valor_min": "Mínimo", "valor_max": "Máximo"}))
                else:
                    widgets.append(_w(id=f"lei_valor_{sub_id}", kind="bar", dataset_id=sub_id, unit=unidade,
                                      title=f"Valores previstos por artigo ({unidade})", x="rotulo",
                                      y=["valor_max"], orientation="h",
                                      column_labels={"rotulo": "Artigo", "valor_max": "Valor"}))
            widgets.append(_w(id=f"lei_citacoes_{did}", kind="quote", title="Artigos-chave", dataset_id=did,
                              unit="citação", span=2, columns=["lei", "artigo", "citacao_literal", "url_fonte"]))
        elif "normas" in df.columns:
            widgets.append(_w(id=f"lei_tempo_{did}", kind="bar", title="Normas do acervo por ano de publicação",
                              dataset_id=did, unit="normas", x="publicacao", y=["normas"],
                              column_labels={"publicacao": "Ano", "normas": "Normas"}))
        elif "temas" in df.columns:
            widgets.append(_w(id=f"lei_lista_{did}", kind="table", title="Normas do acervo", dataset_id=did,
                              unit="normas", columns=["lei", "tipo", "ano", "artigos", "url_fonte"],
                              column_labels={"lei": "Norma", "tipo": "Tipo", "ano": "Ano", "artigos": "Artigos",
                                             "url_fonte": "Fonte"}))
        elif "lei" in df.columns:
            temas = [c for c in df.columns if c not in ("lei", "url_fonte")]
            widgets.append(_w(id=f"lei_matriz_{did}", kind="table", title="Leis × tema", dataset_id=did,
                              unit="tema", span=2, columns=["lei", *temas, "url_fonte"],
                              column_labels={"lei": "Norma", "url_fonte": "Fonte"}))
    return widgets, extra


__all__ = ["LAW_FOOTER", "LawAgentResult", "UNAVAILABLE_MESSAGE", "build_law_widgets", "catalog_frames",
           "dropped_message", "extract_facts", "laws_available", "numbers_in", "run_law_agent", "short_law_name",
           "verify_row", "verify_rows"]

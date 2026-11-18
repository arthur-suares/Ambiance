from __future__ import annotations

import re
import unicodedata


def _fold(text: str) -> str:
    nfd = unicodedata.normalize("NFD", (text or "").lower().strip())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def route_question(question: str) -> dict:
    text = _fold(question)
    if not text:
        return {"domain": "auto", "retrieval": "hybrid", "reason": "Pergunta vazia."}

    legal_keywords = [
        "codigo florestal",
        "reserva legal",
        "lei ambiental",
        "artigo",
        "art. ",
        "lei ",
        "decreto",
        "licenciamento",
        "licenca ambiental",
        "desmatamento ilegal",
        "vegetacao nativa",
        "vegetacao primaria",
        "lei da mata atlantica",
        "cadastro ambiental rural",
        "mudanca do clima",
        "politica nacional",
        "preservacao permanente",
        "unidade de conservacao",
        "unidades de conservacao",
        "protecao integral",
        "uso sustentavel",
        "crimes ambientais",
        "crime ambiental",
        "infracao",
        "infracoes",
        "multa",
        "pena",
        "corte raso",
        "supressao",
        "embargo",
    ]
    legal_acronym_re = re.compile(r"\b(car|app|snuc|pnma|pnmc|pra|sinima|ibama|conama)\b")

    soy_keywords = [
        "soja",
        "soy",
        "desmatamento da soja",
        "exposicao ao desmatamento",
        "producao de soja",
        "municipio com maior exposicao",
        "empresa exportadora",
        "exportador",
        "importador",
        "bioma da soja",
        "cadeia da soja",
        "volume de soja",
        "emissoes da soja",
        "producao da soja",
        "processamento de soja",
        "esmagamento",
        "armazenagem",
        "rtrs",
    ]
    beef_keywords = [
        "bovino",
        "bovina",
        "carne bovina",
        "beef",
        "cattle",
        "pecuaria",
        "pastagem",
        "rebanho",
        "frigorifico",
    ]
    beef_word_re = re.compile(r"\b(gado|pasto|abate)\b")

    has_legal = any(k in text for k in legal_keywords) or bool(legal_acronym_re.search(text))
    has_soy = any(k in text for k in soy_keywords)
    has_beef = any(k in text for k in beef_keywords) or bool(beef_word_re.search(text))
    # Termos genéricos ("exportador", "importador", "exposicao ao desmatamento"...) também valem para a carne bovina:
    # se a pergunta cita a carne bovina e não cita soja explicitamente, ela não é de soja.
    if has_beef and not re.search(r"\b(soja|soy)\b", text):
        has_soy = False

    if has_legal and (has_soy or has_beef):
        return {"domain": "mixed", "retrieval": "hybrid", "reason": "Pergunta mistura legislação e dados estruturados."}
    if has_legal and not (has_soy or has_beef):
        return {"domain": "law", "retrieval": "document", "reason": "Pergunta documental sobre legislação."}
    if has_soy and has_beef:
        return {"domain": "mixed", "retrieval": "structured", "reason": "Pergunta combina dados de soja e carne bovina."}
    if has_soy:
        if re.search(r"(como|metodologia|definicao|explicar|calcula|indicador|dicionario)", text):
            return {"domain": "soy", "retrieval": "document", "reason": "Pergunta conceitual sobre a metodologia da soja."}
        if re.search(r"(quais|qual|ranking|compar|evolucao|ano|municipio|estado|bioma|empresa|pais|exportad|importad)", text):
            return {"domain": "soy", "retrieval": "structured", "reason": "Pergunta quantitativa sobre dados da soja."}
        return {"domain": "soy", "retrieval": "hybrid", "reason": "Pergunta mista sobre soja."}
    if has_beef:
        return {"domain": "beef", "retrieval": "structured", "reason": "Pergunta quantitativa sobre cadeia bovina."}

    return {"domain": "auto", "retrieval": "hybrid", "reason": "Roteamento genérico."}

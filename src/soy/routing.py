from __future__ import annotations

import re


def route_question(question: str) -> dict:
    text = (question or "").lower().strip()
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
        "desmatamento ilegal",
        "vegetacao nativa",
    ]
    soy_keywords = [
        "soja",
        "soy",
        "desmatamento da soja",
        "exposição ao desmatamento",
        "produção de soja",
        "municipio com maior exposição",
        "empresa exportadora",
        "exportador",
        "importador",
        "bioma da soja",
        "cadeia da soja",
        "volume de soja",
        "emissões da soja",
        "produção da soja",
    ]
    beef_keywords = [
        "bovino",
        "carne bovina",
        "gado",
        "beef",
        "cattle",
        "pecuária",
    ]

    has_legal = any(k in text for k in legal_keywords)
    has_soy = any(k in text for k in soy_keywords)
    has_beef = any(k in text for k in beef_keywords)
    # Termos genéricos ("exportador", "importador"...) também valem para a carne bovina:
    # se a pergunta cita a carne bovina e não cita soja explicitamente, ela é de carne bovina.
    if has_beef and not re.search(r"\b(soja|soy)\b", text):
        has_soy = False

    if has_legal and (has_soy or has_beef):
        return {"domain": "mixed", "retrieval": "hybrid", "reason": "Pergunta mistura legislação e dados estruturados."}
    if has_legal and not (has_soy or has_beef):
        return {"domain": "law", "retrieval": "document", "reason": "Pergunta documental sobre legislação."}
    if has_soy:
        if re.search(r"(como|metodologia|definição|explicar|calcula|indicador|dicionário)", text):
            return {"domain": "soy", "retrieval": "document", "reason": "Pergunta conceitual sobre a metodologia da soja."}
        if re.search(r"(quais|qual|ranking|compar|evolução|ano|municipio|estado|bioma|empresa|país|exportad|importad)", text):
            return {"domain": "soy", "retrieval": "structured", "reason": "Pergunta quantitativa sobre dados da soja."}
        return {"domain": "soy", "retrieval": "hybrid", "reason": "Pergunta mista sobre soja."}
    if has_beef:
        return {"domain": "beef", "retrieval": "structured", "reason": "Pergunta quantitativa sobre cadeia bovina."}

    return {"domain": "auto", "retrieval": "hybrid", "reason": "Roteamento genérico."}

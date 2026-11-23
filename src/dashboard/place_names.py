"""Nomes de países e biomas em português, só para a tela (item 7 da auditoria).

Os dados do Trase trazem nomes em inglês e MAIÚSCULAS ("CHINA (MAINLAND)", "THAILAND", "MATA ATLANTICA").
Na tela eles viram "China", "Tailândia", "Mata Atlântica". Os dados e o CSV baixado continuam como vieram.
"BRAZIL" tem tratamento próprio em `renderer.display_label` (processamento doméstico) e não está aqui.
"""

from __future__ import annotations

COUNTRY_NAMES_PT: dict[str, str] = {
    # Principais destinos da soja e da carne bovina do Brasil
    "CHINA (MAINLAND)": "China", "CHINA": "China", "MAINLAND CHINA": "China",
    "CHINA (HONG KONG)": "Hong Kong", "HONG KONG": "Hong Kong", "CHINA (TAIWAN)": "Taiwan", "TAIWAN": "Taiwan",
    "THAILAND": "Tailândia", "SPAIN": "Espanha", "INDONESIA": "Indonésia",
    "VIET NAM": "Vietnã", "VIETNAM": "Vietnã", "NETHERLANDS": "Países Baixos", "THE NETHERLANDS": "Países Baixos",
    "IRAN": "Irã", "IRAN (ISLAMIC REPUBLIC OF)": "Irã", "TURKEY": "Turquia", "TURKIYE": "Turquia", "TÜRKIYE": "Turquia",
    "SOUTH KOREA": "Coreia do Sul", "KOREA (REPUBLIC OF)": "Coreia do Sul", "REPUBLIC OF KOREA": "Coreia do Sul",
    "KOREA, REPUBLIC OF": "Coreia do Sul", "JAPAN": "Japão",
    "UNITED STATES": "Estados Unidos", "UNITED STATES OF AMERICA": "Estados Unidos", "USA": "Estados Unidos",
    "GERMANY": "Alemanha", "FRANCE": "França", "ITALY": "Itália", "UNITED KINGDOM": "Reino Unido",
    "RUSSIA": "Rússia", "RUSSIAN FEDERATION": "Rússia", "EGYPT": "Egito", "SAUDI ARABIA": "Arábia Saudita",
    "UNITED ARAB EMIRATES": "Emirados Árabes Unidos", "CHILE": "Chile", "ARGENTINA": "Argentina",
    "PAKISTAN": "Paquistão", "BANGLADESH": "Bangladesh", "INDIA": "Índia", "MALAYSIA": "Malásia",
    "PHILIPPINES": "Filipinas", "MEXICO": "México", "PORTUGAL": "Portugal", "BELGIUM": "Bélgica",
    "NORWAY": "Noruega", "DENMARK": "Dinamarca", "POLAND": "Polônia", "ALGERIA": "Argélia",
    "MOROCCO": "Marrocos", "ISRAEL": "Israel", "IRAQ": "Iraque", "LEBANON": "Líbano", "JORDAN": "Jordânia",
    "URUGUAY": "Uruguai", "PARAGUAY": "Paraguai", "PERU": "Peru", "VENEZUELA": "Venezuela",
    "COLOMBIA": "Colômbia", "CANADA": "Canadá", "SINGAPORE": "Singapura", "SOUTH AFRICA": "África do Sul",
    "ANGOLA": "Angola", "LIBYA": "Líbia", "GREECE": "Grécia", "IRELAND": "Irlanda", "SWITZERLAND": "Suíça",
    "OMAN": "Omã", "KUWAIT": "Kuwait", "QATAR": "Catar", "YEMEN": "Iêmen", "TUNISIA": "Tunísia",
    "SRI LANKA": "Sri Lanka", "NEW ZEALAND": "Nova Zelândia", "AUSTRALIA": "Austrália", "CUBA": "Cuba",
    "ROMANIA": "Romênia", "BULGARIA": "Bulgária", "UKRAINE": "Ucrânia", "GEORGIA": "Geórgia",
    "SLOVENIA": "Eslovênia", "MYANMAR": "Mianmar", "CAMBODIA": "Camboja", "NIGERIA": "Nigéria",
    "GHANA": "Gana", "SENEGAL": "Senegal", "HONDURAS": "Honduras", "DOMINICAN REPUBLIC": "República Dominicana",
    "EUROPEAN UNION": "União Europeia", "SWEDEN": "Suécia", "FINLAND": "Finlândia", "AUSTRIA": "Áustria",
}

BIOME_NAMES_PT: dict[str, str] = {
    "AMAZONIA": "Amazônia", "AMAZON": "Amazônia", "AMAZÔNIA": "Amazônia",
    "MATA ATLANTICA": "Mata Atlântica", "MATA ATLÂNTICA": "Mata Atlântica", "ATLANTIC FOREST": "Mata Atlântica",
    "CERRADO": "Cerrado", "CAATINGA": "Caatinga", "PANTANAL": "Pantanal", "PAMPA": "Pampa",
}

_PLACE_NAMES = {**COUNTRY_NAMES_PT, **BIOME_NAMES_PT}


def place_name_pt(value) -> str | None:
    """Nome em português de um país ou bioma escrito em inglês/maiúsculas; None se não for conhecido."""
    key = " ".join(str(value).split()).upper()
    return _PLACE_NAMES.get(key)

"""Gera o conjunto de teste do RAG (eval/perguntas.jsonl e eval/gabarito.md).

Uso: python -m eval.build_gold

Os gabaritos numéricos são calculados aqui, por SQL direto nos bancos DuckDB (independente
das ferramentas do agente), e os gabaritos de lei vêm do texto dos artigos indexados.
Rodar de novo atualiza os valores se os dados mudarem.

Cada linha do JSONL tem:
- id, tipo (lei | soja | carne | mista | fora_escopo), pergunta
- resposta_esperada: resposta de referência em texto
- valores: números que a resposta deve conter (valor, unidade, tolerância relativa)
- entidades: nomes que a resposta deve citar (município, empresa, país...)
- artigos: dispositivos legais que devem ser recuperados/citados, cada um com `nivel`:
  essencial (sem ele não dá para responder; usado em Hit Rate@k e MRR) ou complementar
  (ajuda/dá contexto; entra só no Recall@k, junto com os essenciais)
- ferramentas: ferramentas que o agente deveria usar (para medir escolha de ferramenta)
- deve_recusar: true se o correto é dizer que não há dados/base para responder
- sql_gabarito: consulta que gerou os valores (rastreabilidade)
- no_teste: true para as 20 perguntas da avaliação (eval/PLANO_AVALIACAO.md)
- resposta_referencia: referência longa, na estrutura do prompt do agente (resposta curta, dados [D] e leis [L]
  com ano/filtros/unidade, limites da resposta). Só nas 20 do teste; é a referência de ROUGE-L, BLEU e cosseno.
  A resposta_esperada (curta) fica como lista de fatos-chave, usada no Context Recall. As duas são escritas só
  com o gabarito (SQL e texto dos artigos), sem olhar as respostas do agente.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from src.config import DUCKDB_PATH, PROJECT_ROOT
from src.soy.ingest import DEFAULT_DUCKDB_PATH as SOY_DUCKDB_PATH

OUT_DIR = PROJECT_ROOT / "eval"
TOL = 0.01  # 1% de tolerância para números (arredondamento na resposta)

# Expressões numéricas da soja (o banco da soja guarda tudo como texto)
SV = "TRY_CAST(volume AS DOUBLE)"
SE = "TRY_CAST(soy_deforestation_5_year_total_exposure AS DOUBLE)"
SG = "TRY_CAST(co2_gross_emissions_soy_deforestation_5_year_total_exposure AS DOUBLE)"
SF = "TRY_CAST(fob AS DOUBLE)"

LAWS = {
    "cf": "Lei 12.651/2012 (Código Florestal)",
    "lca": "Lei 9.605/1998 (Lei de Crimes Ambientais)",
    "dec": "Decreto 6.514/2008",
    "ma": "Lei 11.428/2006 (Lei da Mata Atlântica)",
    "pnma": "Lei 6.938/1981 (PNMA)",
    "pnmc": "Lei 12.187/2009 (PNMC)",
    "snuc": "Lei 9.985/2000 (SNUC)",
}


# As 20 perguntas da avaliação: 5 lei, 2 carne, 2 soja, 11 mistas
NO_TESTE = {"L01", "L02", "L04", "L06", "L07", "C01", "C04", "S01", "S05"} | {f"M{i:02d}" for i in range(1, 12)}


def art(law: str, number: str, nivel: str = "essencial") -> dict:
    return {"lei": LAWS[law], "artigo": number, "nivel": nivel}


def comp(law: str, number: str) -> dict:
    """Artigo complementar: dá contexto, mas não responde sozinho."""
    return art(law, number, "complementar")


def val(descricao: str, valor: float, unidade: str, tol: float = TOL) -> dict:
    return {"descricao": descricao, "valor": round(float(valor), 4), "unidade": unidade, "tolerancia_rel": tol}


def br(x: float, casas: int = 0) -> str:
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def nome(s: str) -> str:
    """'SAO GABRIEL' -> 'Sao Gabriel'; 'RIO GRANDE DO SUL' -> 'Rio Grande do Sul' (os dados vêm sem acento)."""
    small = {"de", "do", "da", "dos", "das", "e"}
    return " ".join(w.lower() if i and w.lower() in small else w.capitalize() for i, w in enumerate(s.lower().split()))


def mil(x: float) -> str:
    return f"{br(x / 1e3, 1)} mil"


def mi(x: float) -> str:
    return f"{br(x / 1e6, 2)} milhões"


LIM_EXPOSICAO = ("a exposição ao desmatamento é uma estimativa de associação entre a cadeia e o desmatamento, não prova "
                 "ilegalidade nem responsabilidade direta de uma empresa, município ou produtor.")
LIM_CASO = ("para verificar uma situação concreta, seriam necessários o Cadastro Ambiental Rural (CAR) do imóvel, a área e a "
            "data do desmatamento e a autorização (ou a ausência dela) do órgão ambiental.")


def limites(*frases: str) -> str:
    """Junta as frases da seção 'Limites da resposta' (a primeira em minúscula, as demais com inicial maiúscula)."""
    return " ".join(f if i == 0 else f[0].upper() + f[1:] for i, f in enumerate(frases))


def resposta(curta: str, *blocos: str, limites: str | None = None) -> str:
    """Referência longa na estrutura do prompt do agente: resposta curta primeiro, depois o contexto
    (dados [D] e leis [L], com ano, filtros e unidade) e, no fim, os limites da resposta."""
    partes = [f"**Resposta curta:** {curta}", *blocos]
    if limites:
        partes.append(f"**Limites da resposta:** {limites}")
    return "\n\n".join(partes)


class Db:
    def __init__(self):
        self.beef = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        self.soy = duckdb.connect(str(SOY_DUCKDB_PATH), read_only=True)

    def q(self, db: str, sql: str) -> list[tuple]:
        return getattr(self, db).execute(sql).fetchall()


def build(db: Db) -> list[dict]:
    items: list[dict] = []

    def add(tipo, pergunta, resposta, *, valores=(), entidades=(), artigos=(), ferramentas=(),
            deve_recusar=False, sql=None):
        items.append({
            "id": f"{tipo[:1].upper() if tipo != 'fora_escopo' else 'F'}{sum(i['tipo'] == tipo for i in items) + 1:02d}",
            "tipo": tipo, "pergunta": pergunta, "resposta_esperada": resposta,
            "valores": list(valores), "entidades": list(entidades), "artigos": list(artigos),
            "ferramentas": list(ferramentas), "deve_recusar": deve_recusar, "sql_gabarito": sql,
        })
        items[-1]["no_teste"] = items[-1]["id"] in NO_TESTE
        items[-1]["resposta_referencia"] = None

    def ref(texto):
        """Referência longa da última pergunta adicionada."""
        items[-1]["resposta_referencia"] = texto

    # ------------------------------------------------------------------ LEIS
    add("lei", "Qual percentual de reserva legal um imóvel rural precisa manter na Amazônia Legal e no resto do país?",
        "Pelo art. 12 do Código Florestal: na Amazônia Legal, 80% em área de florestas, 35% em área de cerrado e "
        "20% em campos gerais; nas demais regiões do país, 20%.",
        valores=[val("Amazônia Legal, florestas", 80, "%", 0), val("Amazônia Legal, cerrado", 35, "%", 0),
                 val("demais regiões", 20, "%", 0)],
        artigos=[art("cf", "12"), comp("cf", "3")], ferramentas=["search_laws"])
    ref(resposta(
        "o percentual mínimo de reserva legal depende da localização do imóvel. Na Amazônia Legal é de 80% em área de "
        "florestas, 35% em área de cerrado e 20% em área de campos gerais; nas demais regiões do país é de 20%.",
        "O art. 12 do Código Florestal (Lei 12.651/2012) determina que todo imóvel rural mantenha uma área com cobertura "
        "de vegetação nativa a título de reserva legal [L1]. O percentual mínimo é calculado sobre a área do imóvel e varia "
        "conforme a região e o tipo de vegetação [L1]. A Amazônia Legal é definida no art. 3º e abrange os estados do Acre, "
        "Pará, Amazonas, Roraima, Rondônia, Amapá e Mato Grosso, além de partes de Tocantins, Goiás e Maranhão [L2].",
        limites="para saber quanto de reserva legal um imóvel específico deve manter, é preciso conhecer a sua "
                "localização e o tipo de vegetação."))
    add("lei", "Qual a largura mínima da faixa de preservação permanente às margens de um rio com menos de 10 metros de largura?",
        "30 metros, contados da borda da calha do leito regular (art. 4º, I, a, do Código Florestal).",
        valores=[val("largura mínima da APP", 30, "m", 0)], artigos=[art("cf", "4"), comp("cf", "3")], ferramentas=["search_laws"])
    ref(resposta(
        "30 metros, contados da borda da calha do leito regular.",
        "Segundo o art. 4º, inciso I, alínea a, do Código Florestal (Lei 12.651/2012), as faixas marginais de qualquer "
        "curso d'água natural perene e intermitente são áreas de preservação permanente [L1]. Para cursos d'água com menos "
        "de 10 metros de largura, a faixa mínima é de 30 metros, medida a partir da borda da calha do leito regular [L1]. "
        "Pelo art. 3º, a área de preservação permanente é uma área protegida, coberta ou não por vegetação nativa, com a "
        "função ambiental de preservar os recursos hídricos, a paisagem, a estabilidade geológica e a biodiversidade [L2].",
        limites="a largura da faixa muda conforme a largura do rio; esta resposta vale só para rios com menos de 10 "
                "metros."))
    add("lei", "O que é o Cadastro Ambiental Rural (CAR) e quem é obrigado a se inscrever nele?",
        "Registro público eletrônico de âmbito nacional, no âmbito do SINIMA, obrigatório para todos os imóveis "
        "rurais, que integra as informações ambientais das propriedades e posses para controle, monitoramento, "
        "planejamento e combate ao desmatamento (art. 29 do Código Florestal).",
        artigos=[art("cf", "29")], ferramentas=["search_laws"])
    add("lei", "Qual a multa para quem desmata a corte raso, fora da reserva legal, sem autorização?",
        "Multa de R$ 1.000,00 por hectare ou fração (art. 52 do Decreto 6.514/2008).",
        valores=[val("multa por hectare", 1000, "R$/ha", 0)], artigos=[art("dec", "52")], ferramentas=["search_laws"])
    ref(resposta(
        "multa de R$ 1.000,00 por hectare ou fração.",
        "O art. 52 do Decreto 6.514/2008 estabelece que desmatar, a corte raso, florestas ou demais formações nativas, "
        "fora da reserva legal, sem autorização da autoridade competente, sujeita o infrator a multa de R$ 1.000,00 por "
        "hectare ou fração [L1]. Se o desmatamento ocorrer dentro da reserva legal, a infração é outra (art. 51), com multa "
        "de R$ 5.000,00 por hectare ou fração [L2].",
        limites=LIM_CASO))
    add("lei", "Qual a multa por desmatar vegetação nativa dentro da reserva legal sem autorização do órgão ambiental?",
        "Multa de R$ 5.000,00 por hectare ou fração (art. 51 do Decreto 6.514/2008).",
        valores=[val("multa por hectare", 5000, "R$/ha", 0)], artigos=[art("dec", "51")], ferramentas=["search_laws"])
    add("lei", "Qual a pena prevista para quem destrói floresta de preservação permanente?",
        "Detenção de um a três anos, ou multa, ou ambas cumulativamente; se o crime for culposo, a pena é reduzida "
        "à metade (art. 38 da Lei 9.605/1998).",
        artigos=[art("lca", "38"), comp("lca", "39")], ferramentas=["search_laws"])
    ref(resposta(
        "detenção de um a três anos, ou multa, ou ambas as penas cumulativamente; se o crime for culposo, a pena é "
        "reduzida à metade.",
        "Pelo art. 38 da Lei 9.605/1998 (Lei de Crimes Ambientais), destruir ou danificar floresta considerada de "
        "preservação permanente, mesmo que em formação, ou utilizá-la com infringência das normas de proteção é crime "
        "punido com detenção de um a três anos, ou multa, ou ambas as penas cumulativamente [L1]. Se o crime for culposo, "
        "a pena é reduzida à metade [L1]. O art. 39 prevê a mesma pena para quem corta árvores em floresta de preservação "
        "permanente sem permissão da autoridade competente [L2].",
        limites="para saber se houve crime em um caso concreto, seriam necessários os fatos apurados e a decisão da "
                "autoridade competente; esta resposta apenas explica o que a lei prevê."))
    add("lei", "Quais são as categorias de unidades de conservação de proteção integral?",
        "Estação Ecológica, Reserva Biológica, Parque Nacional, Monumento Natural e Refúgio de Vida Silvestre "
        "(art. 8º da Lei 9.985/2000 – SNUC).",
        entidades=["Estação Ecológica", "Reserva Biológica", "Parque Nacional", "Monumento Natural",
                   "Refúgio de Vida Silvestre"],
        artigos=[art("snuc", "8"), comp("snuc", "7")], ferramentas=["search_laws"])
    ref(resposta(
        "as unidades de proteção integral são cinco: Estação Ecológica, Reserva Biológica, Parque Nacional, Monumento "
        "Natural e Refúgio de Vida Silvestre.",
        "O art. 8º da Lei 9.985/2000, que institui o Sistema Nacional de Unidades de Conservação (SNUC), define que o "
        "grupo das Unidades de Proteção Integral é composto por essas cinco categorias [L1]. Segundo o art. 7º, o "
        "objetivo básico das unidades de proteção integral é preservar a natureza, sendo admitido apenas o uso indireto "
        "dos seus recursos naturais [L2]."))
    add("lei", "Qual foi a meta de redução de emissões assumida pelo Brasil na Política Nacional sobre Mudança do Clima?",
        "Compromisso nacional voluntário de reduzir entre 36,1% e 38,9% as emissões projetadas até 2020 "
        "(art. 12 da Lei 12.187/2009).",
        valores=[val("redução mínima", 36.1, "%", 0), val("redução máxima", 38.9, "%", 0)],
        artigos=[art("pnmc", "12")], ferramentas=["search_laws"])

    # ------------------------------------------------------------------ SOJA
    sql = (f"SELECT municipality_of_production, state, SUM({SE}) FROM soy_supply_chain "
           f"WHERE year = '2022' AND municipality_of_production <> 'UNKNOWN' GROUP BY ALL ORDER BY 3 DESC LIMIT 1")
    m, uf, e = db.q("soy", sql)[0]
    add("soja", "Qual município teve a maior exposição ao desmatamento ligada à soja em 2022?",
        f"{nome(m)} ({nome(uf)}), com cerca de {mil(e)} ha de exposição. A origem não rastreada (UNKNOWN) "
        f"não é um município e deve ficar de fora ou ser explicada.",
        valores=[val("exposição", e, "ha")], entidades=[m], ferramentas=["soy_top_municipalities"], sql=sql)
    ref(resposta(
        f"em 2022, o município com a maior exposição ao desmatamento ligada à soja foi {nome(m)} ({nome(uf)}), com cerca "
        f"de {mil(e)} ha.",
        "**Dados (2022, soja)**\n"
        f"- {nome(m)} ({nome(uf)}): cerca de {mil(e)} ha de exposição ao desmatamento, em janela de 5 anos [D1].\n"
        "- A origem não rastreada (UNKNOWN) não é um município e fica fora do ranking [D1].",
        limites=LIM_EXPOSICAO))

    sql = (f"SELECT exporter_group, SUM({SV}) FROM soy_supply_chain WHERE year = '2022' "
           f"AND exporter_group NOT IN ('PROCESSED DOMESTICALLY', 'UNKNOWN') GROUP BY 1 ORDER BY 2 DESC LIMIT 3")
    rows = db.q("soy", sql)
    add("soja", "Quais foram os três maiores grupos exportadores de soja em volume em 2022?",
        "Por volume exportado: " + "; ".join(f"{g} ({mi(v)} t)" for g, v in rows) +
        ". A soja processada no Brasil (PROCESSED DOMESTICALLY) não é um exportador.",
        valores=[val(f"volume {g}", v, "t") for g, v in rows], entidades=[g for g, _ in rows],
        ferramentas=["run_soy_sql"], sql=sql)

    sql = (f"SELECT country_of_first_import, SUM({SV}) FROM soy_supply_chain WHERE year = '2022' "
           f"AND country_of_first_import <> 'BRAZIL' GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    c, v = db.q("soy", sql)[0]
    add("soja", "Qual foi o principal país de destino da soja brasileira em 2022?",
        f"China (CHINA (MAINLAND) nos dados), com cerca de {mi(v)} t. O consumo interno (BRAZIL) não é destino de exportação.",
        valores=[val("volume", v, "t")], entidades=["CHINA"], ferramentas=["soy_top_destinations"], sql=sql)

    sql = f"SELECT SUM({SE}) FROM soy_supply_chain WHERE year = '2022'"
    e = db.q("soy", sql)[0][0]
    add("soja", "Qual foi a exposição total ao desmatamento da cadeia da soja em 2022?",
        f"Cerca de {mil(e)} ha (janela de 5 anos), incluindo a origem não rastreada.",
        valores=[val("exposição total", e, "ha")], ferramentas=["soy_yearly_trend"], sql=sql)

    sql = ("SELECT year, region, value FROM soy_spatial_metrics WHERE metric = 'soy_production_t' AND level = 'state' "
           "AND year = (SELECT MAX(year) FROM soy_spatial_metrics WHERE metric = 'soy_production_t') "
           "ORDER BY value DESC LIMIT 1")
    y, r, v = db.q("soy", sql)[0]
    add("soja", "Qual estado é o maior produtor de soja do Brasil, segundo o dado mais recente?",
        f"{nome(r)}, com cerca de {mi(v)} t em {y}.",
        valores=[val("produção", v, "t")], entidades=[r], ferramentas=["soy_territorial_metric"], sql=sql)
    ref(resposta(
        f"o maior produtor de soja do Brasil é o {nome(r)}, com cerca de {mi(v)} t produzidas em {y}, o dado mais "
        "recente disponível.",
        f"**Dados ({y}, soja)**\n"
        f"- {nome(r)}: cerca de {mi(v)} t de soja produzidas no ano, o maior valor entre os estados [D1]."))

    sql = ("SELECT year, value FROM soy_spatial_metrics WHERE metric = 'soy_yield_t_per_ha' AND level = 'municipality' "
           "AND region = 'SORRISO' AND parent_region = 'MATO GROSSO' ORDER BY year DESC LIMIT 1")
    y, v = db.q("soy", sql)[0]
    add("soja", "Qual a produtividade da soja em Sorriso (MT) no ano mais recente disponível?",
        f"Cerca de {br(v, 2)} t/ha em {y}.",
        valores=[val("produtividade", v, "t/ha")], ferramentas=["soy_territorial_metric"], sql=sql)

    sql = ("SELECT state, SUM(storage_capacity_t), COUNT(*) FROM soy_facilities GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    s, cap, n = db.q("soy", sql)[0]
    add("soja", "Qual estado tem a maior capacidade de armazenagem de soja e quantas instalações ele tem?",
        f"{nome(s)}, com cerca de {mi(cap)} t de capacidade de armazenagem em {br(n)} instalações.",
        valores=[val("capacidade de armazenagem", cap, "t"), val("instalações", n, "un")], entidades=[s],
        ferramentas=["soy_facilities_summary"], sql=sql)

    # ------------------------------------------------------------------ CARNE BOVINA
    sql = ("SELECT exporter_group, SUM(deforestation_exposure_ha) FROM flows_by_exporter WHERE year = 2023 "
           "AND exporter_group NOT IN ('DOMESTIC PROCESSING AND CONSUMPTION', 'UNKNOWN') GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    g, e = db.q("beef", sql)[0]
    add("carne", "Qual grupo exportador de carne bovina teve a maior exposição ao desmatamento em 2023?",
        f"{g}, com cerca de {mil(e)} ha.", valores=[val("exposição", e, "ha")], entidades=[g],
        ferramentas=["top_exporters"], sql=sql)
    ref(resposta(
        f"em 2023, o grupo exportador de carne bovina com a maior exposição ao desmatamento foi a {g}, com cerca de "
        f"{mil(e)} ha.",
        "**Dados (2023, carne bovina)**\n"
        f"- {g}: cerca de {mil(e)} ha de exposição ao desmatamento, o maior entre os grupos exportadores [D1].\n"
        "- Linhas sem exportador identificado (UNKNOWN) e o processamento e consumo domésticos não são grupos "
        "exportadores e ficam fora do ranking [D1].",
        limites=LIM_EXPOSICAO))

    sql = ("SELECT country_of_destination, SUM(volume_t) FROM flows_by_destination WHERE year = 2023 "
           "AND country_of_destination NOT IN ('BRAZIL', 'UNKNOWN COUNTRY') GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    c, v = db.q("beef", sql)[0]
    add("carne", "Para qual país o Brasil mais exportou carne bovina em 2023?",
        f"China (CHINA (MAINLAND) nos dados), com cerca de {mi(v)} t.",
        valores=[val("volume", v, "t")], entidades=["CHINA"], ferramentas=["top_destinations"], sql=sql)

    sql = ("SELECT municipality_of_production, state_of_production, deforestation_exposure_ha FROM flows_by_municipality "
           "WHERE year = 2023 AND municipality_of_production <> 'UNKNOWN' ORDER BY 3 DESC LIMIT 1")
    m, uf, e = db.q("beef", sql)[0]
    add("carne", "Qual município teve a maior exposição ao desmatamento na cadeia da carne bovina em 2023?",
        f"{nome(m)} ({nome(uf)}), com cerca de {mil(e)} ha.",
        valores=[val("exposição", e, "ha")], entidades=[m], ferramentas=["top_municipalities"], sql=sql)

    sql = ("SELECT year, SUM(deforestation_exposure_ha) FROM flows_by_municipality WHERE year IN (2015, 2023) "
           "GROUP BY 1 ORDER BY 1")
    (y0, e0), (y1, e1) = db.q("beef", sql)
    add("carne", "Como a exposição total ao desmatamento da carne bovina mudou entre 2015 e 2023?",
        f"Subiu de cerca de {mi(e0)} ha em {y0} para {mi(e1)} ha em {y1}, alta de cerca de {br((e1 / e0 - 1) * 100)}%. "
        "Os valores de cada ano não devem ser somados.",
        valores=[val(f"exposição {y0}", e0, "ha"), val(f"exposição {y1}", e1, "ha")],
        ferramentas=["yearly_trend"], sql=sql)
    ref(resposta(
        f"a exposição ao desmatamento da cadeia da carne bovina subiu de cerca de {mi(e0)} ha em {y0} para cerca de "
        f"{mi(e1)} ha em {y1}, uma alta de cerca de {br((e1 / e0 - 1) * 100)}%.",
        "**Dados (carne bovina)**\n"
        f"- {y0}: cerca de {mi(e0)} ha de exposição [D1].\n"
        f"- {y1}: cerca de {mi(e1)} ha de exposição [D1].\n"
        "Cada valor anual é uma exposição em janela de 5 anos, por isso os valores de anos diferentes são comparados "
        "lado a lado e não devem ser somados.",
        limites=LIM_EXPOSICAO))

    sql = "SELECT SUM(volume_exported_t) FROM flows_by_municipality WHERE year = 2023"
    v = db.q("beef", sql)[0][0]
    add("carne", "Quantas toneladas de carne bovina o Brasil exportou em 2023?",
        f"Cerca de {mi(v)} t exportadas.", valores=[val("volume exportado", v, "t")],
        ferramentas=["yearly_trend"], sql=sql)

    sql = ("SELECT zero_deforestation_brazil_beef, SUM(volume_t) * 100.0 / SUM(SUM(volume_t)) OVER () FROM flows_by_exporter "
           "WHERE year = 2023 AND exporter_group <> 'DOMESTIC PROCESSING AND CONSUMPTION' GROUP BY 1 "
           "ORDER BY 2 DESC")
    rows = db.q("beef", sql)
    no = next((p for k, p in rows if k == "NO COMMITMENT"), None)
    add("carne", "Em 2023, que parcela do volume exportado de carne bovina saiu de exportadores sem compromisso de desmatamento zero?",
        f"Cerca de {br(no, 1)}% do volume exportado veio de exportadores sem compromisso (NO COMMITMENT).",
        valores=[val("participação sem compromisso", no, "%", 0.02)], ferramentas=["commitment_summary"], sql=sql)

    sql = ("SELECT year, region, value FROM spatial_metrics WHERE metric = 'pasture_area_ha' AND level = 'state' "
           "AND year = (SELECT MAX(year) FROM spatial_metrics WHERE metric = 'pasture_area_ha') ORDER BY value DESC LIMIT 1")
    y, r, v = db.q("beef", sql)[0]
    add("carne", "Qual estado tem a maior área de pastagem, segundo o dado mais recente?",
        f"{nome(r)}, com cerca de {mi(v)} ha em {y}.",
        valores=[val("área de pastagem", v, "ha")], entidades=[r], ferramentas=["territorial_metric"], sql=sql)

    # ------------------------------------------------------------------ MISTAS
    s1 = f"SELECT biome, SUM({SE}) FROM soy_supply_chain WHERE year = '2022' AND biome <> 'UNKNOWN' GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
    s2 = ("SELECT biome, SUM(deforestation_exposure_ha) FROM flows_by_municipality WHERE year = 2022 AND biome <> 'UNKNOWN' "
          "GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    (bs, es), (bb, eb) = db.q("soy", s1)[0], db.q("beef", s2)[0]
    add("mista", "Em 2022, qual bioma teve maior exposição ao desmatamento na cadeia da soja e na da carne bovina? "
                 "O que o Código Florestal exige de reserva legal nesses biomas?",
        f"{nome(bs)} nas duas cadeias: {mil(es)} ha na soja e {mil(eb)} ha na carne bovina (sem a origem não rastreada). "
        "Reserva legal (art. 12): 35% para imóveis em área de cerrado na Amazônia Legal e 20% fora dela.",
        valores=[val("exposição soja", es, "ha"), val("exposição carne", eb, "ha"), val("RL cerrado Amazônia Legal", 35, "%", 0),
                 val("RL demais regiões", 20, "%", 0)],
        entidades=[bs], artigos=[art("cf", "12"), comp("cf", "3")],
        ferramentas=["soy_deforestation_by_biome", "run_sql", "search_laws"], sql=f"{s1};\n{s2}")
    ref(resposta(
        f"em 2022, o bioma com maior exposição ao desmatamento foi o {nome(bs)} nas duas cadeias. Pelo Código Florestal, "
        "a reserva legal em imóveis em área de cerrado é de 35% na Amazônia Legal e de 20% nas demais regiões do país.",
        "**Dados (2022)**\n"
        f"- Soja: {nome(bs)}, com cerca de {mil(es)} ha de exposição, sem contar a origem não rastreada (UNKNOWN) [D1].\n"
        f"- Carne bovina: {nome(bs)}, com cerca de {mil(eb)} ha de exposição, sem contar a origem não rastreada (UNKNOWN) [D2].",
        "**O que o Código Florestal exige de reserva legal**\n"
        "O art. 12 da Lei 12.651/2012 define os percentuais mínimos de vegetação nativa que todo imóvel rural deve manter "
        "como reserva legal [L1]. Na Amazônia Legal, o percentual é de 80% em área de florestas, 35% em área de cerrado e "
        "20% em campos gerais; nas demais regiões do país, é de 20% [L1]. O percentual depende da localização do imóvel e "
        "do tipo de vegetação, não do nome do bioma.",
        limites=limites(LIM_EXPOSICAO, "o percentual de reserva legal de um imóvel específico depende da sua "
                                       "localização e do tipo de vegetação.")))

    s1 = ("SELECT value FROM soy_spatial_metrics WHERE metric = 'soy_production_t' AND level = 'state' AND region = 'MATO GROSSO' "
          "ORDER BY year DESC LIMIT 1")
    s2 = ("SELECT SUM(deforestation_exposure_ha) FROM flows_by_municipality WHERE year = 2023 AND state_of_production = 'MATO GROSSO'")
    ps, eb = db.q("soy", s1)[0][0], db.q("beef", s2)[0][0]
    add("mista", "No Mato Grosso, quanto se produziu de soja no ano mais recente e qual foi a exposição ao desmatamento da "
                 "carne bovina em 2023? Quanto de reserva legal um imóvel em área de floresta na Amazônia Legal deve manter?",
        f"Soja: cerca de {mi(ps)} t. Carne bovina: cerca de {mil(eb)} ha de exposição em 2023. "
        "Reserva legal em área de florestas na Amazônia Legal: 80% (art. 12 do Código Florestal).",
        valores=[val("produção de soja MT", ps, "t"), val("exposição carne MT 2023", eb, "ha"), val("RL floresta", 80, "%", 0)],
        artigos=[art("cf", "12"), comp("cf", "3")], ferramentas=["soy_territorial_metric", "yearly_trend", "search_laws"], sql=f"{s1};\n{s2}")
    ref(resposta(
        f"no Mato Grosso, a produção de soja no ano mais recente disponível foi de cerca de {mi(ps)} t e a exposição ao "
        f"desmatamento da carne bovina em 2023 foi de cerca de {mil(eb)} ha. Um imóvel em área de florestas na Amazônia "
        "Legal deve manter 80% de reserva legal.",
        "**Dados (Mato Grosso)**\n"
        f"- Soja, ano mais recente: cerca de {mi(ps)} t produzidas [D1].\n"
        f"- Carne bovina, 2023: cerca de {mil(eb)} ha de exposição ao desmatamento [D2].",
        "**O que o Código Florestal exige de reserva legal**\n"
        "O Mato Grosso faz parte da Amazônia Legal, definida no art. 3º [L2]. Pelo art. 12, um imóvel situado em área de "
        "florestas na Amazônia Legal deve manter 80% da sua área como reserva legal [L1].",
        limites=limites(LIM_EXPOSICAO, "o percentual de reserva legal de um imóvel específico depende da sua "
                                       "localização e do tipo de vegetação.")))

    sql = ("SELECT exporter_group, SUM(deforestation_exposure_ha), string_agg(DISTINCT zero_deforestation_brazil_beef, ' | ') "
           "FROM flows_by_exporter WHERE year = 2023 AND exporter_group NOT IN ('DOMESTIC PROCESSING AND CONSUMPTION', 'UNKNOWN') "
           "GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    g, e, z = db.q("beef", sql)[0]
    add("mista", "Qual grupo exportador de carne bovina teve maior exposição ao desmatamento em 2023 e ele tem compromisso de "
                 "desmatamento zero? Que multa o Decreto 6.514/2008 prevê para desmatar dentro da reserva legal sem autorização?",
        f"{g}, com cerca de {mil(e)} ha; tem compromisso de desmatamento zero"
        f"{' (de empresa, e também G4/TAC em parte dos fluxos)' if 'G4' in z or 'TAC' in z else ''}. A multa é de R$ 5.000,00 por hectare ou fração (art. 51). "
        "A exposição não prova que o grupo descumpriu a lei.",
        valores=[val("exposição", e, "ha"), val("multa por hectare", 5000, "R$/ha", 0)], entidades=[g],
        artigos=[art("dec", "51")], ferramentas=["top_exporters", "search_laws"], sql=sql)
    ref(resposta(
        f"em 2023, o grupo exportador de carne bovina com maior exposição ao desmatamento foi a {g}, com cerca de "
        f"{mil(e)} ha. O grupo tem compromisso de desmatamento zero"
        f"{' (próprio e, em parte dos fluxos, acordos G4/TAC)' if 'G4' in z or 'TAC' in z else ''}. Pelo Decreto "
        "6.514/2008, a multa por desmatar dentro da reserva legal sem autorização é de R$ 5.000,00 por hectare ou fração.",
        "**Dados (2023, carne bovina)**\n"
        f"- {g}: cerca de {mil(e)} ha de exposição ao desmatamento, o maior entre os grupos exportadores identificados [D1].",
        "**O que a lei exige**\n"
        "O art. 51 do Decreto 6.514/2008 estabelece que destruir, desmatar, danificar ou explorar vegetação nativa em área "
        "de reserva legal, sem autorização prévia do órgão ambiental, sujeita o infrator a multa de R$ 5.000,00 por "
        "hectare ou fração [L1].",
        limites=limites(LIM_EXPOSICAO, LIM_CASO)))

    sql = f"SELECT SUM({SE}) FROM soy_supply_chain WHERE year = '2022' AND biome = 'MATA ATLANTICA'"
    e = db.q("soy", sql)[0][0]
    add("mista", "Qual foi a exposição ao desmatamento da soja na Mata Atlântica em 2022 e em que casos a lei proíbe cortar "
                 "vegetação primária nesse bioma?",
        f"Cerca de {mil(e)} ha em 2022. A Lei da Mata Atlântica (art. 11) veda o corte de vegetação primária ou em estágio "
        "médio/avançado quando ela abriga espécies ameaçadas, protege mananciais ou previne erosão, forma corredores entre "
        "remanescentes, protege o entorno de unidades de conservação ou tem excepcional valor paisagístico, ou quando o "
        "proprietário não cumpre a legislação ambiental.",
        valores=[val("exposição soja Mata Atlântica", e, "ha")], artigos=[art("ma", "11"), comp("ma", "14")],
        ferramentas=["soy_deforestation_by_biome", "search_laws"], sql=sql)
    ref(resposta(
        f"em 2022, a exposição ao desmatamento da cadeia da soja na Mata Atlântica foi de cerca de {mil(e)} ha. A Lei da "
        "Mata Atlântica veda o corte de vegetação primária, e da secundária em estágio avançado e médio de regeneração, "
        "em casos como abrigar espécies ameaçadas, proteger mananciais ou prevenir erosão.",
        "**Dados (2022, soja)**\n"
        f"- Mata Atlântica: cerca de {mil(e)} ha de exposição ao desmatamento, em janela de 5 anos [D1].",
        "**O que a lei exige**\n"
        "O art. 11 da Lei 11.428/2006 (Lei da Mata Atlântica) veda o corte e a supressão de vegetação primária ou nos "
        "estágios avançado e médio de regeneração quando a vegetação abrigar espécies da flora e da fauna ameaçadas de "
        "extinção, exercer a função de proteção de mananciais ou de prevenção e controle de erosão, formar corredores entre "
        "remanescentes de vegetação primária ou secundária em estágio avançado de regeneração, proteger o entorno das "
        "unidades de conservação ou possuir excepcional valor paisagístico [L1]. O corte também é vedado quando o "
        "proprietário ou posseiro não cumprir a legislação ambiental [L1]. Fora desses casos, o art. 14 só admite a "
        "supressão de vegetação primária e secundária em estágio avançado em caso de utilidade pública [L2].",
        limites=limites(LIM_EXPOSICAO, "para saber se um corte específico é proibido, seriam necessários o estágio da "
                                       "vegetação, a localização e a autorização do órgão ambiental.")))

    sql = f"SELECT SUM({SG}) FROM soy_supply_chain WHERE year = '2022'"
    g = db.q("soy", sql)[0][0]
    add("mista", "Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022 e qual meta de redução de emissões "
                 "a Política Nacional sobre Mudança do Clima estabeleceu?",
        f"Cerca de {mi(g)} tCO2e de emissões brutas (janela de 5 anos) em 2022. A PNMC (art. 12) fixou o compromisso "
        "voluntário de reduzir entre 36,1% e 38,9% as emissões projetadas até 2020.",
        valores=[val("emissões brutas soja 2022", g, "tCO2e"), val("redução mínima", 36.1, "%", 0), val("redução máxima", 38.9, "%", 0)],
        artigos=[art("pnmc", "12")], ferramentas=["soy_yearly_trend", "search_laws"], sql=sql)
    ref(resposta(
        f"em 2022, a cadeia da soja teve cerca de {mi(g)} tCO2e de emissões brutas associadas ao desmatamento. A Política "
        "Nacional sobre Mudança do Clima fixou o compromisso voluntário de reduzir entre 36,1% e 38,9% as emissões "
        "projetadas até 2020.",
        "**Dados (2022, soja)**\n"
        f"- Emissões brutas de CO2 associadas ao desmatamento: cerca de {mi(g)} tCO2e, em janela de 5 anos [D1].",
        "**O que a lei estabelece**\n"
        "O art. 12 da Lei 12.187/2009 (Política Nacional sobre Mudança do Clima) estabelece como compromisso nacional "
        "voluntário reduzir entre 36,1% e 38,9% as emissões de gases de efeito estufa projetadas até 2020 [L1].",
        limites="as emissões usam janela de 5 anos e não devem ser somadas entre anos; são uma estimativa de associação "
                "entre a cadeia e o desmatamento."))

    # M06: pastagem + reserva legal
    sql = ("SELECT year, region, value FROM spatial_metrics WHERE metric = 'pasture_area_ha' AND level = 'state' "
           "AND year = (SELECT MAX(year) FROM spatial_metrics WHERE metric = 'pasture_area_ha') ORDER BY value DESC LIMIT 1")
    y, r, v = db.q("beef", sql)[0]
    add("mista", "Qual estado tem a maior área de pastagem e quanto de reserva legal um imóvel em área de floresta na "
                 "Amazônia Legal precisa manter?",
        f"{nome(r)}, com cerca de {mi(v)} ha de pastagem em {y}. Em área de florestas na Amazônia Legal, a reserva "
        "legal é de 80% do imóvel (art. 12 do Código Florestal).",
        valores=[val("área de pastagem", v, "ha"), val("RL floresta", 80, "%", 0)], entidades=[r],
        artigos=[art("cf", "12"), comp("cf", "3")], ferramentas=["territorial_metric", "search_laws"], sql=sql)
    ref(resposta(
        f"o estado com a maior área de pastagem é o {nome(r)}, com cerca de {mi(v)} ha em {y}. Um imóvel em área de "
        "florestas na Amazônia Legal deve manter 80% de reserva legal.",
        f"**Dados ({y})**\n"
        f"- {nome(r)}: cerca de {mi(v)} ha de pastagem, o maior valor entre os estados [D1].",
        "**O que o Código Florestal exige de reserva legal**\n"
        "Pelo art. 12 do Código Florestal (Lei 12.651/2012), um imóvel rural localizado na Amazônia Legal, definida no "
        "art. 3º, deve manter como reserva legal 80% da sua área quando está em área de florestas [L1].",
        limites="o percentual de reserva legal de um imóvel específico depende da sua localização e do tipo de vegetação."))

    # M07: soja exportada sob compromisso de desmatamento zero (MT) + CAR
    sql = ("SELECT value FROM soy_spatial_metrics WHERE metric = 'zdc_exported_pct' AND level = 'state' "
           "AND region = 'MATO GROSSO' AND year = 2022")
    p = db.q("soy", sql)[0][0]
    add("mista", "Que percentual da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero em 2022, "
                 "e o que é o CAR?",
        f"Cerca de {br(p, 1)}% em 2022. O CAR (art. 29 do Código Florestal) é o registro público eletrônico nacional, "
        "obrigatório para todos os imóveis rurais, que integra as informações ambientais das propriedades para "
        "controle, monitoramento, planejamento e combate ao desmatamento.",
        valores=[val("soja exportada com compromisso ZDC (MT)", p, "%", 0.02)],
        artigos=[art("cf", "29")], ferramentas=["soy_territorial_metric", "search_laws"], sql=sql)
    ref(resposta(
        f"em 2022, cerca de {br(p, 1)}% da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero. O "
        "CAR é o Cadastro Ambiental Rural, um registro público eletrônico nacional obrigatório para todos os imóveis rurais.",
        "**Dados (Mato Grosso, 2022)**\n"
        f"- Cerca de {br(p, 1)}% da soja exportada saiu sob compromisso de desmatamento zero [D1].",
        "**O que é o CAR**\n"
        "O Cadastro Ambiental Rural (CAR), criado pelo art. 29 do Código Florestal (Lei 12.651/2012), é um registro "
        "público eletrônico de âmbito nacional, no Sistema Nacional de Informação sobre Meio Ambiente (SINIMA), obrigatório "
        "para todos os imóveis rurais, com a finalidade de integrar as informações ambientais das propriedades e posses "
        "rurais para controle, monitoramento, planejamento ambiental e econômico e combate ao desmatamento [L1].",
        limites="o compromisso de desmatamento zero não prova, por si só, que a soja exportada esteja livre de "
                "desmatamento ilegal."))

    # M08: município da carne bovina + pena por destruir APP
    sql = ("SELECT municipality_of_production, state_of_production, deforestation_exposure_ha FROM flows_by_municipality "
           "WHERE year = 2023 AND municipality_of_production <> 'UNKNOWN' ORDER BY 3 DESC LIMIT 1")
    m, uf, e = db.q("beef", sql)[0]
    add("mista", "Qual município teve a maior exposição ao desmatamento na carne bovina em 2023, e qual a pena para quem "
                 "destrói floresta de preservação permanente?",
        f"{nome(m)} ({nome(uf)}), com cerca de {mil(e)} ha. A pena é detenção de um a três anos, ou multa, ou ambas "
        "(art. 38 da Lei 9.605/1998), reduzida à metade se o crime for culposo. A exposição não prova que houve crime.",
        valores=[val("exposição", e, "ha")], entidades=[m],
        artigos=[art("lca", "38"), comp("lca", "39")], ferramentas=["top_municipalities", "search_laws"], sql=sql)
    ref(resposta(
        f"em 2023, o município com a maior exposição ao desmatamento na carne bovina foi {nome(m)} ({nome(uf)}), com "
        "cerca de "
        f"{mil(e)} ha. A pena para quem destrói floresta de preservação permanente é detenção de um a três anos, ou multa, "
        "ou ambas, reduzida à metade se o crime for culposo.",
        "**Dados (2023, carne bovina)**\n"
        f"- {nome(m)} ({nome(uf)}): cerca de {mil(e)} ha de exposição ao desmatamento [D1].",
        "**O que a lei prevê**\n"
        "Pelo art. 38 da Lei 9.605/1998 (Lei de Crimes Ambientais), destruir ou danificar floresta considerada de "
        "preservação permanente é crime punido com detenção de um a três anos, ou multa, ou ambas as penas cumulativamente, "
        "com redução da pena à metade se o crime for culposo [L1]. O art. 39 prevê a mesma pena para quem corta árvores em "
        "floresta de preservação permanente sem permissão da autoridade competente [L2].",
        limites=limites(LIM_EXPOSICAO, "a exposição não prova que houve crime.", LIM_CASO)))

    # M09: soja x carne na Amazônia + multa por corte raso fora da RL
    s1 = f"SELECT SUM({SE}) FROM soy_supply_chain WHERE year = '2022' AND biome = 'AMAZONIA'"
    s2 = "SELECT SUM(deforestation_exposure_ha) FROM flows_by_municipality WHERE year = 2022 AND biome = 'AMAZONIA'"
    es, eb = db.q("soy", s1)[0][0], db.q("beef", s2)[0][0]
    add("mista", "Compare a exposição ao desmatamento da soja e da carne bovina na Amazônia em 2022, e qual a multa por "
                 "desmatar a corte raso fora da reserva legal?",
        f"Na Amazônia, em 2022: soja com cerca de {mil(es)} ha e carne bovina com cerca de {mil(eb)} ha "
        f"(a carne tem cerca de {br(eb / es)} vezes mais). A multa é de R$ 1.000,00 por hectare ou fração "
        "(art. 52 do Decreto 6.514/2008).",
        valores=[val("exposição soja Amazônia", es, "ha"), val("exposição carne Amazônia", eb, "ha"),
                 val("multa por hectare", 1000, "R$/ha", 0)], entidades=["AMAZONIA"],
        artigos=[art("dec", "52")], ferramentas=["soy_deforestation_by_biome", "run_sql", "search_laws"],
        sql=f"{s1};\n{s2}")
    ref(resposta(
        f"na Amazônia, em 2022, a exposição ao desmatamento foi de cerca de {mil(es)} ha na soja e {mil(eb)} ha na carne "
        f"bovina, ou seja, a carne bovina teve cerca de {br(eb / es)} vezes mais. A multa por desmatar a corte raso fora "
        "da reserva legal é de R$ 1.000,00 por hectare ou fração.",
        "**Comparação (Amazônia, 2022)**\n"
        f"- Soja: cerca de {mil(es)} ha de exposição ao desmatamento [D1].\n"
        f"- Carne bovina: cerca de {mil(eb)} ha de exposição ao desmatamento [D2].",
        "**O que a lei prevê**\n"
        "O art. 52 do Decreto 6.514/2008 estabelece que desmatar, a corte raso, florestas ou demais formações nativas fora "
        "da reserva legal, sem autorização da autoridade competente, sujeita o infrator a multa de R$ 1.000,00 por hectare "
        "ou fração [L1].",
        limites=limites(LIM_EXPOSICAO, LIM_CASO)))

    # M10: maior exportador de soja + exposição + multa dentro da RL
    sql = (f"SELECT exporter_group, SUM({SV}), SUM({SE}) FROM soy_supply_chain WHERE year = '2022' "
           f"AND exporter_group NOT IN ('PROCESSED DOMESTICALLY', 'UNKNOWN') GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    g, v, e = db.q("soy", sql)[0]
    add("mista", "Qual o maior grupo exportador de soja em 2022 e sua exposição ao desmatamento? Que multa se aplica a quem "
                 "desmata dentro da reserva legal?",
        f"{g}, com cerca de {mi(v)} t exportadas e {mil(e)} ha de exposição ao desmatamento em 2022. A multa é de "
        "R$ 5.000,00 por hectare ou fração (art. 51 do Decreto 6.514/2008). A exposição não prova ilegalidade.",
        valores=[val("volume", v, "t"), val("exposição", e, "ha"), val("multa por hectare", 5000, "R$/ha", 0)],
        entidades=[g], artigos=[art("dec", "51")], ferramentas=["soy_top_exporters", "search_laws"], sql=sql)
    ref(resposta(
        f"em 2022, o maior grupo exportador de soja foi a {g}, com cerca de {mi(v)} t exportadas e {mil(e)} ha de "
        "exposição ao desmatamento. A multa para quem desmata dentro da reserva legal sem autorização é de R$ 5.000,00 "
        "por hectare ou fração.",
        "**Dados (2022, soja)**\n"
        f"- {g}: cerca de {mi(v)} t exportadas, o maior volume entre os grupos exportadores [D1].\n"
        f"- Exposição ao desmatamento do grupo: cerca de {mil(e)} ha [D1].",
        "**O que a lei prevê**\n"
        "Pelo art. 51 do Decreto 6.514/2008, quem destrói, desmata, danifica ou explora vegetação nativa em área de "
        "reserva legal, sem autorização prévia do órgão ambiental, está sujeito a multa de R$ 5.000,00 por hectare ou "
        "fração [L1].",
        limites=limites(LIM_EXPOSICAO, LIM_CASO)))

    # M11: capacidade de processamento de soja + licenciamento
    sql = ("SELECT state, SUM(processing_capacity_t_day), COUNT(*) FILTER (WHERE processing_capacity_t_day > 0) "
           "FROM soy_facilities GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 1")
    s, cap, n = db.q("soy", sql)[0]
    add("mista", "Qual estado tem a maior capacidade de processamento de soja, e que atividades dependem de licenciamento "
                 "ambiental prévio?",
        f"{nome(s)}, com cerca de {br(cap)} t/dia de capacidade de processamento ({br(n)} instalações com processamento). "
        "Pelo art. 10 da Lei 6.938/1981, dependem de licenciamento prévio a construção, instalação, ampliação e "
        "funcionamento de estabelecimentos e atividades que usam recursos ambientais e são efetiva ou potencialmente "
        "poluidores ou capazes de causar degradação ambiental.",
        valores=[val("capacidade de processamento", cap, "t/dia")], entidades=[s],
        artigos=[art("pnma", "10")], ferramentas=["soy_facilities_summary", "search_laws"], sql=sql)
    ref(resposta(
        f"o estado com a maior capacidade de processamento de soja é o {nome(s)}, com cerca de {br(cap)} t/dia. "
        "Dependem de licenciamento ambiental prévio a construção, instalação, ampliação e funcionamento de "
        "estabelecimentos e atividades que usam recursos ambientais e são poluidores ou capazes de causar degradação "
        "ambiental.",
        "**Dados (soja)**\n"
        f"- {nome(s)}: cerca de {br(cap)} t/dia de capacidade de processamento somadas em {br(n)} instalações com "
        "processamento, o maior valor entre os estados [D1].",
        "**O que a lei exige**\n"
        "Pelo art. 10 da Lei 6.938/1981 (Política Nacional do Meio Ambiente), a construção, instalação, ampliação e "
        "funcionamento de estabelecimentos e atividades utilizadores de recursos ambientais, efetiva ou potencialmente "
        "poluidores ou capazes, sob qualquer forma, de causar degradação ambiental dependem de prévio licenciamento "
        "ambiental [L1].",
        limites="para saber se uma instalação específica precisa de licença, seriam necessários o tipo de atividade, o "
                "porte e a norma do órgão ambiental competente."))

    # ------------------------------------------------------------------ FORA DO ESCOPO
    add("fora_escopo", "Qual foi a produção de café em Minas Gerais em 2022?",
        "O sistema não tem dados de café; deve dizer que a informação não está na base (cobre soja, carne bovina e leis ambientais).",
        deve_recusar=True)
    add("fora_escopo", "Qual será a exposição ao desmatamento da soja em 2030?",
        "Não há projeções na base; os dados da cadeia da soja vão até 2022. Deve dizer que não é possível responder.",
        deve_recusar=True)
    add("fora_escopo", "A JBS cometeu crime ambiental em 2023?",
        "Não é possível concluir: os dados mostram exposição ao desmatamento, que não prova ilegalidade nem responsabilidade "
        "direta. Pode explicar o que a lei tipifica e que dados seriam necessários (autos de infração, embargos, CAR).",
        entidades=["JBS"], deve_recusar=True)
    return items


def write_markdown(items: list[dict], path: Path) -> None:
    names = {"lei": "Leis", "soja": "Soja", "carne": "Carne bovina", "mista": "Mistas (dados + leis)",
             "fora_escopo": "Fora do escopo (deve recusar)"}
    out = ["# Conjunto de teste do RAG — gabarito", "",
           "Gerado por `python -m eval.build_gold`. Os números vêm de SQL direto nos bancos; "
           f"tolerância padrão de {TOL:.0%} nos valores numéricos. *(no teste)* marca as 20 perguntas da avaliação; "
           "artigos essenciais contam em Hit Rate e MRR, complementares só no Recall.", ""]
    for tipo, title in names.items():
        out += [f"## {title}", ""]
        for i in (x for x in items if x["tipo"] == tipo):
            out.append(f"**{i['id']}. {i['pergunta']}**{' *(no teste)*' if i['no_teste'] else ''}  ")
            out.append(f"Gabarito: {i['resposta_esperada']}  ")
            if i.get("resposta_referencia"):
                out.append(f"Referência longa: {i['resposta_referencia']}  ")
            if i["artigos"]:
                out.append("Artigos: " + "; ".join(f"{a['lei']}, art. {a['artigo']} ({a['nivel']})" for a in i["artigos"]) + "  ")
            if i["ferramentas"]:
                out.append("Ferramentas esperadas: " + ", ".join(f"`{f}`" for f in i["ferramentas"]) + "  ")
            out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def main() -> None:
    items = build(Db())
    OUT_DIR.mkdir(exist_ok=True)
    with open(OUT_DIR / "perguntas.jsonl", "w", encoding="utf-8") as f:
        for i in items:
            f.write(json.dumps(i, ensure_ascii=False) + "\n")
    write_markdown(items, OUT_DIR / "gabarito.md")
    counts = {t: sum(i["tipo"] == t for i in items) for t in dict.fromkeys(i["tipo"] for i in items)}
    print(f"{len(items)} perguntas -> eval/perguntas.jsonl e eval/gabarito.md {counts}; "
          f"no_teste={sum(i['no_teste'] for i in items)}")


if __name__ == "__main__":
    main()

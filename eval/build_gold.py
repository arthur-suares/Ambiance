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
- artigos: dispositivos legais que devem ser recuperados/citados
- ferramentas: ferramentas que o agente deveria usar (para medir escolha de ferramenta)
- deve_recusar: true se o correto é dizer que não há dados/base para responder
- sql_gabarito: consulta que gerou os valores (rastreabilidade)
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


def art(law: str, number: str) -> dict:
    return {"lei": LAWS[law], "artigo": number}


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

    # ------------------------------------------------------------------ LEIS
    add("lei", "Qual percentual de reserva legal um imóvel rural precisa manter na Amazônia Legal e no resto do país?",
        "Pelo art. 12 do Código Florestal: na Amazônia Legal, 80% em área de florestas, 35% em área de cerrado e "
        "20% em campos gerais; nas demais regiões do país, 20%.",
        valores=[val("Amazônia Legal, florestas", 80, "%", 0), val("Amazônia Legal, cerrado", 35, "%", 0),
                 val("demais regiões", 20, "%", 0)],
        artigos=[art("cf", "12")], ferramentas=["search_laws"])
    add("lei", "Qual a largura mínima da faixa de preservação permanente às margens de um rio com menos de 10 metros de largura?",
        "30 metros, contados da borda da calha do leito regular (art. 4º, I, a, do Código Florestal).",
        valores=[val("largura mínima da APP", 30, "m", 0)], artigos=[art("cf", "4")], ferramentas=["search_laws"])
    add("lei", "O que é o Cadastro Ambiental Rural (CAR) e quem é obrigado a se inscrever nele?",
        "Registro público eletrônico de âmbito nacional, no âmbito do SINIMA, obrigatório para todos os imóveis "
        "rurais, que integra as informações ambientais das propriedades e posses para controle, monitoramento, "
        "planejamento e combate ao desmatamento (art. 29 do Código Florestal).",
        artigos=[art("cf", "29")], ferramentas=["search_laws"])
    add("lei", "Qual a multa para quem desmata a corte raso, fora da reserva legal, sem autorização?",
        "Multa de R$ 1.000,00 por hectare ou fração (art. 52 do Decreto 6.514/2008).",
        valores=[val("multa por hectare", 1000, "R$/ha", 0)], artigos=[art("dec", "52")], ferramentas=["search_laws"])
    add("lei", "Qual a multa por desmatar vegetação nativa dentro da reserva legal sem autorização do órgão ambiental?",
        "Multa de R$ 5.000,00 por hectare ou fração (art. 51 do Decreto 6.514/2008).",
        valores=[val("multa por hectare", 5000, "R$/ha", 0)], artigos=[art("dec", "51")], ferramentas=["search_laws"])
    add("lei", "Qual a pena prevista para quem destrói floresta de preservação permanente?",
        "Detenção de um a três anos, ou multa, ou ambas cumulativamente; se o crime for culposo, a pena é reduzida "
        "à metade (art. 38 da Lei 9.605/1998).",
        artigos=[art("lca", "38")], ferramentas=["search_laws"])
    add("lei", "Quais são as categorias de unidades de conservação de proteção integral?",
        "Estação Ecológica, Reserva Biológica, Parque Nacional, Monumento Natural e Refúgio de Vida Silvestre "
        "(art. 8º da Lei 9.985/2000 – SNUC).",
        entidades=["Estação Ecológica", "Reserva Biológica", "Parque Nacional", "Monumento Natural",
                   "Refúgio de Vida Silvestre"],
        artigos=[art("snuc", "8")], ferramentas=["search_laws"])
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
        entidades=[bs], artigos=[art("cf", "12")],
        ferramentas=["soy_deforestation_by_biome", "run_sql", "search_laws"], sql=f"{s1};\n{s2}")

    s1 = ("SELECT value FROM soy_spatial_metrics WHERE metric = 'soy_production_t' AND level = 'state' AND region = 'MATO GROSSO' "
          "ORDER BY year DESC LIMIT 1")
    s2 = ("SELECT SUM(deforestation_exposure_ha) FROM flows_by_municipality WHERE year = 2023 AND state_of_production = 'MATO GROSSO'")
    ps, eb = db.q("soy", s1)[0][0], db.q("beef", s2)[0][0]
    add("mista", "No Mato Grosso, quanto se produziu de soja no ano mais recente e qual foi a exposição ao desmatamento da "
                 "carne bovina em 2023? Quanto de reserva legal um imóvel em área de floresta na Amazônia Legal deve manter?",
        f"Soja: cerca de {mi(ps)} t. Carne bovina: cerca de {mil(eb)} ha de exposição em 2023. "
        "Reserva legal em área de florestas na Amazônia Legal: 80% (art. 12 do Código Florestal).",
        valores=[val("produção de soja MT", ps, "t"), val("exposição carne MT 2023", eb, "ha"), val("RL floresta", 80, "%", 0)],
        artigos=[art("cf", "12")], ferramentas=["soy_territorial_metric", "yearly_trend", "search_laws"], sql=f"{s1};\n{s2}")

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

    sql = f"SELECT SUM({SE}) FROM soy_supply_chain WHERE year = '2022' AND biome = 'MATA ATLANTICA'"
    e = db.q("soy", sql)[0][0]
    add("mista", "Qual foi a exposição ao desmatamento da soja na Mata Atlântica em 2022 e em que casos a lei proíbe cortar "
                 "vegetação primária nesse bioma?",
        f"Cerca de {mil(e)} ha em 2022. A Lei da Mata Atlântica (art. 11) veda o corte de vegetação primária ou em estágio "
        "médio/avançado quando ela abriga espécies ameaçadas, protege mananciais ou previne erosão, forma corredores entre "
        "remanescentes, protege o entorno de unidades de conservação ou tem excepcional valor paisagístico, ou quando o "
        "proprietário não cumpre a legislação ambiental.",
        valores=[val("exposição soja Mata Atlântica", e, "ha")], artigos=[art("ma", "11")],
        ferramentas=["soy_deforestation_by_biome", "search_laws"], sql=sql)

    sql = f"SELECT SUM({SG}) FROM soy_supply_chain WHERE year = '2022'"
    g = db.q("soy", sql)[0][0]
    add("mista", "Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022 e qual meta de redução de emissões "
                 "a Política Nacional sobre Mudança do Clima estabeleceu?",
        f"Cerca de {mi(g)} tCO2e de emissões brutas (janela de 5 anos) em 2022. A PNMC (art. 12) fixou o compromisso "
        "voluntário de reduzir entre 36,1% e 38,9% as emissões projetadas até 2020.",
        valores=[val("emissões brutas soja 2022", g, "tCO2e"), val("redução mínima", 36.1, "%", 0), val("redução máxima", 38.9, "%", 0)],
        artigos=[art("pnmc", "12")], ferramentas=["soy_yearly_trend", "search_laws"], sql=sql)

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
           f"tolerância padrão de {TOL:.0%} nos valores numéricos.", ""]
    for tipo, title in names.items():
        out += [f"## {title}", ""]
        for i in (x for x in items if x["tipo"] == tipo):
            out.append(f"**{i['id']}. {i['pergunta']}**  ")
            out.append(f"Gabarito: {i['resposta_esperada']}  ")
            if i["artigos"]:
                out.append("Artigos: " + "; ".join(f"{a['lei']}, art. {a['artigo']}" for a in i["artigos"]) + "  ")
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
    print(f"{len(items)} perguntas -> eval/perguntas.jsonl e eval/gabarito.md {counts}")


if __name__ == "__main__":
    main()

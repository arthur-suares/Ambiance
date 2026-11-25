"""Indicator definitions and provenance for map, timeline and dashboard."""

from datetime import date

from src.agro_db import readonly_conn
from src.temporal import METRICS


IBGE_PERIOD = "Agregação por código IBGE e ano. A visão estadual soma os municípios com registros."
FIVE_YEARS = "Some a exposição atribuída aos fluxos com origem municipal identificada dentro de um mesmo ano. As janelas de cinco anos se sobrepõem entre anos."
FLOW_METHOD = "Some os volumes por origem produtora identificada e país. Os arcos no mapa destacam as maiores ligações e o total inclui todos os pares elegíveis."
DETER_METHOD = "Agrupe todos os registros com coordenadas do recorte em células de 0,25° e por período. Use a data de observação do INPE. Na exploração por pontos é aplicado um limite de exibição."

DEFINITIONS = {
    "ibge_soja_producao_t": ("ibge_pam_soja", "Quantidade de soja produzida na unidade territorial no ano, em toneladas.", IBGE_PERIOD, "A estimativa mede produção agrícola."),
    "ibge_bovinos_rebanho_cab": ("ibge_ppm_bovinos", "Efetivo de bovinos no município no ano pesquisado, em cabeças.", IBGE_PERIOD, "Abate, exportação e rebanho têm unidades e conceitos próprios."),
    "seeg_emissao_agro_tco2e": ("seeg_emissoes", "Emissões estimadas da agropecuária em toneladas de CO₂ equivalente.", "Some as estimativas municipais do setor Agropecuária classificadas como emissão.", "Estimativas em GWP-AR5. As remoções têm tratamento separado."),
    "seeg_emissao_mut_tco2e": ("seeg_emissoes", "Emissões brutas estimadas por mudanças no uso da terra e florestas.", "Some as estimativas municipais do setor Mudança de Uso da Terra classificadas como emissão.", "Estimativas em GWP-AR5. As remoções têm tratamento separado."),
    "mapbiomas_desmatamento_ha": ("mapbiomas_desmatamento", "Área de supressão de vegetação identificada a partir das transições anuais de cobertura.", "Some as classes de supressão selecionadas da Coleção 11 por município e ano.", "O mapeamento de supressão e a avaliação da situação legal usam informações diferentes."),
    "land_cover": ("mapbiomas_cobertura", "Área em hectares das classes anuais de cobertura e uso da terra.", "Some a área por classe e município. Os pixels oficiais de 30 m e as estatísticas municipais são os dois modos de visualização da coleção.", "O recorte estatístico por bioma usa o bioma predominante do município."),
    "inpe_deter_area_km2": ("inpe_deter", "Área somada dos registros de alerta do INPE, em km².", "O indicador territorial soma áreas por município e ano. A Linha do Tempo de alertas usa a série georreferenciada e o método descrito na ficha de área somada.", "O PRODES fornece a taxa anual oficial. As áreas somadas podem incluir sobreposição entre registros."),
    "deter_count": ("inpe_deter", "Número de registros georreferenciados de alerta por satélite.", DETER_METHOD, "As séries dos biomas começam em datas diferentes. As classes podem incluir degradação e cicatrizes de queimada."),
    "deter_area": ("inpe_deter", "Área somada dos registros de alerta que informam área, em km².", DETER_METHOD, "A soma pode incluir sobreposições entre registros. O PRODES fornece a taxa anual oficial."),
    "flows_soja": ("trase_fluxos", "Volume de fluxos internacionais de soja com município produtor rastreado.", FLOW_METHOD, "O arco representa uma ligação comercial. O país informado pela Trase muda de conceito em 2019 para primeira importação."),
    "flows_bovinos": ("trase_fluxos", "Volume de fluxos internacionais da cadeia bovina com município produtor rastreado.", FLOW_METHOD, "O arco representa uma ligação comercial. A cobertura de origem depende do ano e da cadeia."),
}

for product in ("soja", "bovinos"):
    DEFINITIONS[f"trase_{product}_volume_t"] = (
        "trase_fluxos", f"Volume comercializado na cadeia de {product} com origem municipal identificada.",
        IBGE_PERIOD, "O volume representa os registros Trase com origem identificada.",
    )
    DEFINITIONS[f"trase_{product}_exposicao_5a_ha"] = (
        "trase_fluxos", f"Exposição estimada ao desmatamento associada à cadeia de {product}.",
        FIVE_YEARS, "A exposição territorial é uma estimativa. A situação legal depende de evidência adicional.",
    )
    DEFINITIONS[f"comex_{product}_t"] = (
        "comex_exportacoes", f"Peso líquido exportado dos códigos de produtos selecionados para {product}.",
        "Some quilogramas líquidos e divida por 1.000 para obter toneladas.",
        "O município é o domicílio fiscal do exportador. A origem produtora da Trase tem outro conceito.",
    )


def get_methodology():
    with readonly_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT fonte_id, nome, url, versao, ano_inicio, ano_fim, registros
            FROM agro.dim_fontes WHERE registros > 0
        """)
        sources = {row["fonte_id"]: row for row in cur.fetchall()}
        cur.execute("""
            SELECT bioma, MIN(view_date) AS first, MAX(view_date) AS last
            FROM agro.fato_inpe_deter GROUP BY bioma ORDER BY bioma
        """)
        deter = [{k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()} for row in cur.fetchall()]
        cur.execute("SELECT produto, array_agg(DISTINCT ano ORDER BY ano) AS years FROM agro.fato_trase_fluxos GROUP BY 1")
        trase_years = {row["produto"]: row["years"] for row in cur.fetchall()}
    biome_names = {"AMAZONIA": "Amazônia", "CERRADO": "Cerrado", "PANTANAL": "Pantanal"}
    for item in deter:
        item["bioma"] = biome_names.get(item["bioma"], item["bioma"])
    sources["inpe_deter"] = {**sources.get("inpe_deter", {}),
                            "versao": "TerraBrasilis · " + ", ".join(row["bioma"] for row in deter)}
    metrics = {}
    for code, definition in DEFINITIONS.items():
        source_id, meaning, calculation, caveat = definition
        source = sources.get(source_id, {})
        product = next((p for p in ("soja", "bovinos") if p in code), None)
        metrics[code] = {
            **METRICS[code], "meaning": meaning, "calculation": calculation, "caveat": caveat,
            "version": source.get("versao"), "url": source.get("url"),
            "years": trase_years.get(product) if source_id == "trase_fluxos" else None,
            "start_year": source.get("ano_inicio"), "end_year": source.get("ano_fim"),
            "coverage": deter if source_id == "inpe_deter" else None,
            "frequency": "Mensal ou anual no Ambiance" if source_id == "inpe_deter" else "Anual",
        }
    return {"metrics": metrics, "sources": sources}

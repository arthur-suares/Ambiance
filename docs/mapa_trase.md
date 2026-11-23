# Experimento: rotas Trase com deck.gl

Em `/mapa`, a visão geral lê todas as linhas de soja e permite escolher um ano
ou inspecionar um registro pelo número sequencial, começando em 1 após o cabeçalho.
Trechos iguais são agrupados para somar volumes e contagens. As etapas são
município produtor → hub → saída brasileira → país informado pela Trase.
Um registro pode aparecer em vários trechos, mas conta uma vez nos totais de cobertura.
Quando uma etapa não tem localização identificada, os demais trechos continuam visíveis.

As linhas animadas usam `TripsLayer` e as conexões internacionais usam `ArcLayer`.
O movimento indica o sentido. A espessura representa o volume agrupado.
A rede usa ligações esquemáticas no Brasil e traçados OSRM nas rotas salvas.
Ao inspecionar um registro com origem e hub localizados, é possível solicitar
ao OSRM um traçado estimado para esse trecho. A rede internacional usa pontos
municipais de referência das saídas, inclusive passagens de fronteira, e pontos
cartográficos dos países do [Natural Earth 5.1.2](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_50m_admin_0_map_units.geojson).
O arco representa a relação comercial. A Trase informa país de destino em
2004–2018 e país de primeira importação em 2019–2022. O arco termina no ponto
de referência do país, sem especificar um porto estrangeiro.

Clique em um traço ou arco para abrir suas linhas de origem, com 20 registros
por página. A lista e o mapa usam o mesmo recorte de ano, município produtor,
saída brasileira e país. Cada linha do painel abre a cadeia do registro.

Ao abrir um registro, o mapa enquadra os pontos e trechos brasileiros.
**Ver ligação comercial** exibe o arco esquemático até o país. O painel
continua mostrando destino e volume informados pela Trase.

O servidor local procura o CSV `../dados_processados/trase_soja_fluxos.csv.gz`
em relação ao projeto `Ambiance`. Para usar outro caminho, configure
`TRASE_SOY_MAP_SOURCE` no ambiente do servidor. As referências geográficas
versionadas cobrem os locais identificáveis nesta versão do CSV.

Em `/mapa/fluxo`, o primeiro teste mostra 12 fluxos reais de soja
em 2022, entre município produtor e município do hub logístico. A seleção usa os
maiores volumes elegíveis do arquivo processado, excluindo origem desconhecida,
destino interno/desconhecido, hubs sem identificação única e fluxos dentro do
mesmo município. Todos os exportadores e países elegíveis de cada par são somados.
Não representa a totalidade das exportações brasileiras.

## Executar

Na pasta `Ambiance`:

```bash
.venv/bin/python -m src.web --port 8001
```

Abra <http://127.0.0.1:8001/> para perguntar no modo **Soja no mapa** ou
<http://127.0.0.1:8001/mapa> para explorar diretamente. O modo usa o provedor
de IA do projeto para interpretar um recorte de ano, município produtor,
saída brasileira e país. Os totais e municípios são consultados na mesma
base e com os mesmos filtros que o mapa. **Ver no mapa** abre os filtros
já preenchidos e editáveis.

Perguntas que solicitem também contexto jurídico usam a busca documental do
projeto, com fontes separadas da Trase. A preparação da base jurídica é feita
no fluxo normal de ingestão do projeto. Para executar só o explorador, com
a biblioteca padrão do Python, use `python3 -m src.map_demo --port 8001`.
O exemplo rodoviário permanece em `/mapa/fluxo`.

Selecione um fluxo, alterne entre **Pelas estradas** e **Ligação direta**, aproxime
o mapa e consulte as referências de BRs/rodovias no painel. Os detalhes mostram
os grupos exportadores e países relacionados ao fluxo selecionado.

## Fontes e interpretação

- **Fluxos e volumes:** `trase_soja_fluxos.csv.gz`, Trase Brasil soja v2.6.1,
  ano 2022. O hash SHA-256 do arquivo fonte fica registrado no JSON exportado.
- **Coordenadas:** pontos municipais da base
  [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros),
  fixada no commit `975a51d6f2e7a9ee22a734a42ebd624263812f0c`.
  A origem é associada pelo código municipal; hubs são aceitos somente se o nome
  normalizado tiver uma correspondência única na base de coordenadas.
- **Percursos:** OSRM com a rede OpenStreetMap e perfil `driving`. São estimativas
  atuais entre pontos municipais, sem provar o trajeto da carga em 2022.
  O perfil não incorpora restrições específicas de caminhões. Pode incluir balsas;
  nesse caso o painel informa a travessia. Não modela o transporte multimodal da
  cadeia e não identifica fazendas ou silos específicos.
- **Mapa de fundo:** OpenStreetMap via MapLibre GL JS. Bibliotecas fixadas em
  deck.gl 9.2.6 e MapLibre GL JS 4.7.1, carregadas pelo CDN unpkg.

O JSON versionado em `web/data/trase_map_demo.json` contém os 12 fluxos e trajetos
previamente calculados, com data do cálculo. O mapa de fundo e as bibliotecas
dependem de internet. O serviço público OSRM é usado somente na preparação ou
quando faltar um trajeto salvo; não deve ser tratado como serviço de produção.

O volume no painel pertence ao fluxo comercial Trase. Não é uma medição de carga
transportada na rodovia destacada. A ligação direta é apenas esquemática e não
exibe distância rodoviária. Os indicadores estatísticos do IBGE não são usados.

## Atualizar a amostra

Com o CSV processado disponível:

```bash
python3 scripts/prepare_map_demo.py \
  --source ../dados_processados/trase_soja_fluxos.csv.gz \
  --year 2022 --limit 12 --cache-routes
```

O script preserva o arquivo fonte e sobrescreve apenas a amostra do mapa. Usa o
serviço OSRM público sequencialmente, com intervalo entre consultas. Se um cálculo
falhar, registra a falha; a interface tentará consultar o trajeto ao selecioná-lo.
Reinicie o servidor depois de atualizar a amostra, pois o catálogo fica em memória.

## Validação

```bash
.venv/bin/python -m pytest tests/test_map_demo.py -q
node --check web/map.js
```

Os checks cobrem agregação sem misturar anos/destinos internos, origem desconhecida,
geometrias inválidas, identificação de balsas, consistência da amostra, associação
de trajetos aos fluxos, uso do cache, IDs inválidos e indisponibilidade do roteador.

A rede usa o CSV diretamente. A integração com os resultados da IA segue separada.

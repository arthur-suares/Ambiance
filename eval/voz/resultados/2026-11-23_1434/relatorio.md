# Comparação de modelos multimodais de voz (2026-11-23 14:46)

## Resumo por modelo

| Modelo | Áudios | Erros | WER médio | Acerto de nomes | Local | Commodity | Ano | Tipo | Tempo médio (s) |
|---|---|---|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` | 20 | 8 | 2,4% | 100,0% | 100,0% | 100,0% | 100,0% | 100,0% | 7,449 |
| `gemini-4-hydrogen` | 20 | 17 | 4,5% | — | 100,0% | 100,0% | 100,0% | 100,0% | 110,190 |

## Detalhe por pergunta

### Modelo: `gemini-3.5-flash-lite`

| ID | WER | Nomes | Local | Commodity | Ano | Tipo | Tempo (s) | Transcrição obtida / Erro |
|---|---|---|---|---|---|---|---|---|
| L01 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| L02 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| L03 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| L04 | 6,7% | — | ✓ | ✓ | ✓ | ✓ | 8.73 | Qual a multa para quem desmata corte raso fora da reserva legal sem autorização? |
| S01 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| S02 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 24.32 | Quais foram os três maiores grupos exportadores de soja em volume em 2022? |
| S06 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 4.18 | Qual a produtividade da soja em Sorriso (MT) no ano mais recente disponível? |
| C01 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 2.60 | Qual grupo exportador de carne bovina teve a maior exposição ao desmatamento em 2023? |
| C03 | 6,7% | — | ✓ | ✓ | ✓ | ✓ | 8.16 | Qual município teve a maior exposição ao desmatamento na cadeia de carne bovina em 2023? |
| C04 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 8.63 | Como a exposição total ao desmatamento da carne bovina mudou entre 2015 e 2023? |
| M01 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M02 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M03 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M04 | 8,0% | — | ✓ | ✓ | ✓ | ✓ | 2.55 | Qual foi a exposição do desmatamento da soja na Mata Atlântica em 2022? E em que casos a lei proíbe cortar vegetação primária nesses nesse bioma? |
| M05 | 6,9% | — | ✓ | ✓ | ✓ | ✓ | 2.76 | Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022? E qual meta de redução de emissões a Política Nacional sobre Mudanças no Clima estabeleceu? |
| M06 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-3.5-flash-lite): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M07 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 10.47 | Que percentual da soja exportada pelo Mato Grosso saiu sob compromisso de desmatamento zero em 2022? E o que é o CAR? |
| M08 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 3.07 | Qual município teve a maior exposição ao desmatamento na carne bovina em 2023 e qual a pena para quem destrói floresta de preservação permanente? |
| M09 | 0,0% | 100,0% | ✓ | ✓ | ✓ | ✓ | 11.15 | Compare a exposição ao desmatamento da soja e da carne bovina na Amazônia em 2022 e qual a multa por desmatar a corte raso fora da Reserva Legal. |
| M10 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 2.77 | Qual o maior grupo exportador de soja em 2022 e sua exposição ao desmatamento? Que multa se aplica a quem desmata dentro da reserva legal? |

### Modelo: `gemini-4-hydrogen`

| ID | WER | Nomes | Local | Commodity | Ano | Tipo | Tempo (s) | Transcrição obtida / Erro |
|---|---|---|---|---|---|---|---|---|
| L01 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| L02 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| L03 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| L04 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| S01 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| S02 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| S06 | 0,0% | — | ✓ | ✓ | ✓ | ✓ | 304.54 | Qual a produtividade da soja em Sorriso, MT, no ano mais recente disponível? |
| C01 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| C03 | 6,7% | — | ✓ | ✓ | ✓ | ✓ | 4.51 | Qual município teve a maior exposição ao desmatamento na cadeia de carne bovina em 2023? |
| C04 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M01 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M02 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M03 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M04 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M05 | 6,9% | — | ✓ | ✓ | ✓ | ✓ | 21.52 | Quanto a cadeia da soja emitiu de CO2 associado ao desmatamento em 2022 e qual meta de redução de emissões a Política Nacional sobre Mudanças no Clima estabeleceu? |
| M06 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M07 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M08 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M09 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |
| M10 | — | — | ✗ | ✗ | ✗ | ✗ | — | ERRO: VoiceProviderError: Falha ao chamar Gemini (gemini-4-hydrogen): ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}} |

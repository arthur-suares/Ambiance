# Plano: pergunta por voz (entrada multimodal)

> Status: **em revisão** — nada foi implementado ainda.
> Data: 2026-11-23

## 1. Objetivo

Permitir que o usuário faça perguntas **falando**, de forma que o sistema seja multimodal de verdade: um **modelo de linguagem recebe o áudio** e o interpreta (transcreve e identifica local, commodity, ano e tipo da pergunta), em vez de apenas converter fala em texto.

O Claude (modelo do agente atual) não aceita áudio como entrada. Por isso, um segundo modelo, o **Gemini**, que aceita áudio, entra **antes** do pipeline atual. Do pipeline em diante, nada muda.

### Por que conta como multimodal

| Abordagem | O modelo processa áudio? | Multimodal? |
|---|---|---|
| Web Speech API / Whisper transcrevem e o Claude recebe texto | Não (só um reconhecedor de fala) | Interface multimodal, modelo não |
| **Gemini recebe o áudio, transcreve e extrai informações** | **Sim** | **Sim** |

## 2. Fluxo

```
🎤 navegador grava (WAV) ──► POST /api/voice ──► Gemini ouve o áudio
                                                   └─► JSON: transcrição + local, commodity, ano, tipo
campo de pergunta preenchido + seletores ajustados ◄──┘
        └─► usuário revisa e clica "Perguntar" ──► /api/chat (pipeline atual, sem mudanças)
```

## 3. Decisões

| Tema | Decisão | Motivo |
|---|---|---|
| Transcrição | Aparece no campo de pergunta; o usuário revisa e envia | Nomes como "Querência" ou "JBS" podem sair errados, e o pipeline depende deles |
| Informações extraídas | Ajustam os seletores "Modo" e "Domínio" e aparecem na tela | Uso visível, sem alterar o pipeline do agente |
| Provedor | Gemini direto (chave gratuita do AI Studio), configurável no `.env` | Custo zero no nível gratuito; troca de modelo sem mudar código |
| Modelo padrão | `gemini-3.5-flash-lite` (alternativa: `gemini-4-hydrogen`) | Leve, rápido, gratuito e com entrada de áudio; a comparação (etapa 8) confirma a escolha |
| Biblioteca | SDK oficial `google-genai` | Menos código; suporta áudio e saída em JSON com esquema |
| Formato de gravação | WAV mono 16 kHz, gerado no navegador | O Chrome grava `webm` por padrão, que o Gemini não aceita; WAV funciona em todos os navegadores e provedores, sem dependência nova |
| Duração máxima | 60 segundos (~1,9 MB) | Cobre perguntas longas; protege a cota gratuita |
| Armazenamento do áudio | **Não guardar** (só em memória durante a requisição) | Privacidade. Única exceção: modo de gravação para avaliação (etapa 7), desligado por padrão |
| Vocabulário do domínio | Lista fixa de ~50 termos no prompt | Melhora o reconhecimento de nomes, sem depender do banco |
| Falhas | Sem chave → microfone não aparece; erro da API → aviso "digite a pergunta" | O resto do sistema segue funcionando |
| Resposta falada | Botão "Ouvir resposta" (voz do navegador) | Sem custo e sem backend; pula tabelas e citações |
| Provedores implementados | Só Gemini; interface pronta para OpenRouter | Evita código sem teste; adicionar depois não exige refazer nada |

## 4. Etapas

### Etapa 1 — Configuração
- Novas variáveis em `.env.example` e `src/config.py`:
  - `GEMINI_API_KEY` — chave do AI Studio (nunca versionada)
  - `VOICE_PROVIDER=gemini`
  - `VOICE_MODEL=gemini-3.5-flash-lite`
  - `VOICE_MAX_SECONDS=60`
  - `VOICE_RECORD_DIR=` — vazio = modo de gravação desligado (ver etapa 7)
- Adicionar `google-genai` ao `requirements.txt`.

### Etapa 2 — Módulo de voz (`src/voice.py`) ⭐ parte multimodal
- Função única `ouvir_pergunta(audio: bytes, mime: str) -> ResultadoVoz`.
- Envia o áudio ao Gemini com um prompt que pede transcrição + extração, incluindo a lista de vocabulário (siglas como CAR/PRA, empresas, municípios e leis mais citados).
- Resposta em JSON com esquema fixo:
  ```json
  {"transcricao": "quanto Sorriso exportou de soja em 2020?",
   "local": "Sorriso (MT)", "commodity": "soja", "ano": 2020, "tipo": "dados"}
  ```
  - `commodity`: `soja` | `carne` | `ambas` | `null`
  - `tipo`: `dados` | `leis` | `misto` | `fora_escopo`
- Validação: valores fora do esperado viram "não identificado" e não quebram o fluxo.
- O provedor fica atrás de uma interface simples, para adicionar o OpenRouter no futuro.

### Etapa 3 — Endpoint (`src/web.py`)
- `POST /api/voice`: corpo = áudio WAV bruto (`Content-Type: audio/wav`).
- Checa o tamanho pelo `Content-Length` **antes** de ler o corpo.
- Respostas de erro:

  | Situação | Status |
  |---|---|
  | Corpo vazio | 400 |
  | Áudio acima do limite | 413 |
  | Formato diferente de WAV | 415 |
  | Sem chave configurada | 503 |
  | Falha ou resposta inválida do Gemini | 502 |
- `/api/health` passa a informar `voice_available`.
- Registra no log só a transcrição e o tempo gasto, nunca o áudio.

### Etapa 4 — Front-end (`web/index.html`)
- Botão 🎤 ao lado de "Perguntar", visível só se `voice_available`.
- Estados: parado → gravando (cronômetro `0:12 / 1:00`, clique para parar, para sozinho em 60 s) → processando → pronto ou erro.
- Grava WAV mono 16 kHz via Web Audio API.
- Ao receber o resultado:
  - preenche o campo de pergunta com a transcrição (editável);
  - mostra uma linha do tipo *"Entendi: Sorriso (MT) · soja · 2020 · dados"*;
  - ajusta os seletores:

    | Extraído | Modo | Domínio |
    |---|---|---|
    | tipo = leis | Só leis | Legislação ambiental |
    | tipo = dados, commodity = soja | Dados + leis | Soja |
    | tipo = dados, commodity = carne | Dados + leis | Carne bovina |
    | tipo = misto ou commodity = ambas | Dados + leis | Consulta integrada |
    | demais casos | (sem mudança) | Automático |
- Botão "Ouvir resposta" após cada resposta: lê o texto com `speechSynthesis` (pt-BR), pula tabelas e citações (D1, L1); o mesmo botão para a leitura.
- O navegador pede permissão de microfone na primeira vez (funciona em `127.0.0.1`).

### Etapa 5 — Testes automáticos (`tests/test_voice.py`)
- Gemini simulado (mock): roda sem internet e sem gastar cota, no padrão de `tests/test_pipeline_web.py`.
- Casos cobertos:
  - áudio válido → transcrição e campos extraídos;
  - corpo vazio, áudio grande demais, formato errado;
  - sem chave → `voice_available: false` e endpoint 503;
  - JSON inválido ou com valores fora do esquema vindo do modelo;
  - tabela de ajuste dos seletores;
  - modo de gravação: recusa nomes de arquivo que não sejam IDs de pergunta.

### Etapa 6 — README
- Como criar a chave no AI Studio e configurar o `.env`.
- O que torna o sistema multimodal (tabela da seção 1).
- Aviso: no nível gratuito, o Google pode usar o conteúdo enviado (os áudios) para melhorar os produtos dele.

### Etapa 7 — Modo de gravação para avaliação
- Liga com `VOICE_RECORD_DIR=eval/voz/audios`; desligado por padrão.
- Com o modo ligado, a tela mostra um painel com as perguntas de `eval/perguntas.jsonl`, uma por vez: o usuário lê o texto na tela, grava, e o arquivo é salvo como `<id>.wav` (ex.: `L01.wav`, `S03.wav`). Permite regravar e pular; mostra quais já foram gravadas.
- O servidor só aceita salvar com nomes que sejam IDs existentes no arquivo de perguntas.
- Sugestão para a primeira rodada: **15 áudios** (3 de lei, 3 de soja, 3 de carne, 4 mistas, 2 fora de escopo); os demais podem ser gravados depois.

### Etapa 8 — Gabarito e comparação de modelos (`eval/voice_compare.py`)
- **Gabarito** (`eval/voz/gabarito_voz.jsonl`), gerado a partir de `eval/perguntas.jsonl`:
  - transcrição esperada = campo `pergunta`;
  - tipo: `lei` → leis; `soja`/`carne` → dados; `mista` → misto; `fora_escopo` → fora_escopo;
  - commodity: derivada do tipo e do texto;
  - entidades: campo `entidades` (para medir o acerto de nomes);
  - local e ano: preenchidos por mim, com marcação **"revisar"** para conferência manual.
- O script roda cada áudio gravado no **`gemini-3.5-flash-lite`** e no **`gemini-4-hydrogen`** e mede:

  | Métrica | O que mostra |
  |---|---|
  | Taxa de erro de palavras (WER) | Fidelidade da transcrição; usa a normalização de `eval/text_metrics.py` |
  | Acerto de nomes | Se as entidades (municípios, empresas, leis) aparecem corretas na transcrição |
  | Acerto por campo | Local, commodity, ano e tipo comparados ao gabarito |
  | Tempo por pergunta | Latência de cada modelo |
- Saída: resumo no terminal + relatório em `eval/voz/resultados/` com uma linha por pergunta (onde cada modelo errou).
- Cota gratuita: pausa entre chamadas e nova tentativa automática quando o limite for atingido.

## 5. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `src/voice.py` | **novo** — chamada ao Gemini, prompt, validação |
| `src/web.py` | `POST /api/voice`, gravação para avaliação, `voice_available` no health |
| `src/config.py`, `.env.example` | novas variáveis |
| `requirements.txt` | `google-genai` |
| `web/index.html` | microfone, gravação WAV, seletores, "Ouvir resposta", painel de gravação |
| `tests/test_voice.py` | **novo** |
| `eval/voice_compare.py` | **novo** |
| `eval/voz/gabarito_voz.jsonl` | **novo** |
| `README.md` | nova seção |

O pipeline do agente (`src/pipeline/`, `src/agent.py`, `src/dashboard/`) **não é alterado**.

## 6. Fora do escopo (pode vir depois sem refazer nada)
- Guardar áudios fora do modo de avaliação.
- Enviar as informações extraídas ao pipeline do agente (roteamento).
- Implementação do provedor OpenRouter.
- Resposta falada gerada por modelo (hoje: voz do navegador).

## 7. O que o usuário precisa fazer
1. Criar a chave em aistudio.google.com e colocá-la no `.env` como `GEMINI_API_KEY`.
2. Conferir os limites do nível gratuito em aistudio.google.com/rate-limit.
3. Testar no Chrome ou no Edge, permitindo o uso do microfone.
4. Ligar o modo de gravação, gravar os áudios de avaliação e revisar os campos "revisar" do gabarito.
5. Rodar `eval/voice_compare.py` e escolher o modelo padrão.

## 8. Riscos e cuidados
- **Nomes próprios mal transcritos** → mitigado pela confirmação do usuário e pela lista de vocabulário.
- **Limites do nível gratuito** → limite de 60 s por áudio; pausa e nova tentativa no script de comparação.
- **Uso dos dados pelo Google no nível gratuito** → aviso no README; o áudio não é guardado pelo sistema.
- **Modelos mudam de nome ou são descontinuados** (ex.: série 2.5 sendo redirecionada) → modelo configurável no `.env`.
- **Áudio como vetor de instruções maliciosas** ("ignore as instruções e...") → a saída do Gemini é tratada como dado, validada pelo esquema e revisada pelo usuário antes de chegar ao agente.

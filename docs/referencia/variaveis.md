# Valores aceitos por variável

Esta página responde **"que valores essa variável aceita e o que cada um faz"**.
Para **"quais variáveis vão no `.env` de cada serviço"**, veja
[configuracao-por-servico.md](../arquitetura/configuracao-por-servico.md).

O `Settings` tem 137 campos. Documentar todos linha a linha esconderia
justamente os que importam, porque a maioria é endereço, chave ou caminho — o
valor aceito é "o endereço certo", e errar dá erro visível. Aqui estão os ~50
onde **um valor errado muda o comportamento em silêncio**: enumerados,
booleanos e numéricos com regra própria.

## A regra que vale para todos

**Valor desconhecido não quebra o boot.** Quase toda leitura enumerada faz
`.strip().lower()` e compara com o valor especial; qualquer outra coisa cai no
padrão. Isso é deliberado — um backend que não sobe por causa de um typo numa
variável de voz seria pior —, mas tem um custo: `TOOL_TRANSPORT=Remoto`
(português) roda `local` sem reclamar. As colunas **"o que faz"** abaixo sempre
dizem onde cai o valor inválido.

**Booleano** é lido pelo pydantic-settings. Contam como verdadeiro: `true`,
`True`, `1`, `yes`, `on`. Como falso: `false`, `False`, `0`, `no`, `off`.
Qualquer outra coisa — inclusive `sim`, `nao` ou string vazia — é **erro de
validação no boot**, e aí o processo não sobe. É a única família que falha alto.

---

## Transporte entre serviços

Variáveis de **cliente**: quem as lê é quem precisa alcançar a capacidade,
nunca o serviço que leva o nome dela.

| Variável | Valores | O que faz |
|---|---|---|
| `TOOL_TRANSPORT` | `local` (padrão) | Catálogo de ferramentas roda no próprio processo |
| | `remote` | Fala com o `tool-service` por HTTP; exige `TOOL_SERVICE_URL` em PaaS |
| | qualquer outro | Cai em `local`, sem aviso |
| `MCP_TRANSPORT` | `local` (padrão) | Conecta direto aos servidores de `MCP_SERVERS`, com cache e disjuntor |
| | `remote` | Fala com o `mcp-service`; cache e disjuntor passam a ser dele |
| | qualquer outro | Cai em `local` |
| `ORCHESTRATOR_TRANSPORT` | `local` (padrão) | Grafo do chat roda dentro da `assistant-api` |
| | `remote` | Cada turno vai para o `agent-orchestrator`. Sem `INTERNAL_SERVICE_TOKEN` **nos dois lados**, o backend sobe, registra `ERROR` no boot e todo turno é recusado com `503` |
| | qualquer outro | Cai em `local` |
| `TOOL_SERVICE_URL` / `MCP_SERVICE_URL` / `ORCHESTRATOR_URL` | vazio (padrão) | Deduz `http://127.0.0.1:<porta>` — só serve no mesmo host |
| | URL | Usada como está, sem a barra final |

> Com `ORCHESTRATOR_TRANSPORT=remote`, `TOOL_TRANSPORT` e `MCP_TRANSPORT`
> passam a valer no `.env` do **orquestrador**: é lá que o agente roda. A cópia
> na API sobra para a tela `GET /system/agents/status`.

`TOOL_TRANSPORT=remote` **não** move as ferramentas que leem o banco: elas
continuam no processo do chat, somadas ao catálogo remoto. Ligar `remote` não
cria necessidade de `DATABASE_URL` no `tool-service`.

---

## Agente e grafo

| Variável | Valores | O que faz |
|---|---|---|
| `AGENT_MAX_TOOL_ITERATIONS` | `1`+ (padrão `3`) | Rodadas de ferramenta antes de fechar a resposta à força |
| | `0` ou negativo | **Travado em 1** (`max(1, …)`): uma rodada sempre acontece |
| `AGENT_MAX_HANDOFFS` | `0` | Desliga transferência entre especialistas — quem recebe a mensagem responde |
| | `1`+ (padrão `2`) | Teto de transferências por mensagem |
| | negativo | Travado em `0` |
| `GRAPH_NODE_MAX_RETRIES` | `1`+ (padrão `2`) | Tentativas por nó que fala com serviço externo. `1` = sem retentativa |
| | `0` ou negativo | Travado em `1` |

Destino inválido ou já visitado encerra o repasse antes do teto, então
`AGENT_MAX_HANDOFFS` alto não cria ping-pong entre dois agentes.

---

## Resiliência de ferramenta e MCP

| Variável | Valores | O que faz |
|---|---|---|
| `TOOL_TIMEOUT_SECONDS` | `20.0` (padrão) | Teto por chamada. Ferramenta com teto próprio no descritor vence este |
| `TOOL_MAX_RETRIES` | `0` | Uma tentativa só |
| | `1`+ (padrão `1`) | Retentativas **apenas** para o que é transitório: timeout e falha de transporte. Argumento inválido ou ferramenta inexistente nunca repete |
| | negativo | Travado em `0` |
| `TOOL_RETRY_BACKOFF_SECONDS` | `0.5` (padrão) | Espera entre tentativas, multiplicada pelo número da tentativa |
| `MCP_TIMEOUT_SECONDS` | `30.0` (padrão) | Teto por chamada MCP |
| `MCP_MAX_RETRIES` | `0`+ (padrão `2`) | Mesma regra do tool |
| `MCP_CIRCUIT_FAILURE_THRESHOLD` | `1`+ (padrão `3`) | Falhas seguidas até abrir o disjuntor daquele servidor |
| `MCP_CIRCUIT_RESET_SECONDS` | `60.0` (padrão) | Quanto o disjuntor fica aberto antes de tentar de novo |
| `MCP_TOOLS_CACHE_TTL_SECONDS` | `300.0` (padrão) | Validade do catálogo MCP em cache |
| | `0` | Reconsulta os servidores a **cada** listagem — custa latência em toda mensagem |
| `MCP_SERVERS` | vazio (padrão) | Nenhum servidor MCP; o catálogo fica só com as ferramentas locais |
| | JSON mapa | `{"fs": {"command": "npx", "args": [...]}}` → stdio; `{"docs": {"url": "http://..."}}` → streamable_http |
| | JSON lista | Mesma coisa com `"name"` dentro de cada item |
| | JSON inválido | **Warning no log e nenhum servidor** — o backend sobe normalmente, e MCP simplesmente não existe |

> `MCP_CIRCUIT_FAILURE_THRESHOLD`, `MCP_CIRCUIT_RESET_SECONDS` e
> `MCP_TOOLS_CACHE_TTL_SECONDS` só valem com `MCP_TRANSPORT=local`. Com
> `remote`, o gateway leva apenas endereço, timeout e retentativa — cache e
> disjuntor passam a ser do `mcp-service`, e defini-las deste lado não faz
> nada.

---

## Checkpoint do grafo

| Variável | Valores | O que faz |
|---|---|---|
| `CHECKPOINT_BACKEND` | `memory` (padrão) | Retomada dentro da sessão; **não** sobrevive a restart |
| | `sqlite` | Persiste em disco — exige `langgraph-checkpoint-sqlite` instalado **e** volume montado |
| | `none`, `off`, `disabled` | Desliga a persistência: cada mensagem recomeça do zero |
| | qualquer outro | Cai em `memory` |
| `CHECKPOINT_SQLITE_PATH` | caminho (padrão `data/checkpoints.sqlite`) | Só lido com backend `sqlite`; diretórios são criados |
| `CHECKPOINT_MAX_THREADS` | `1`+ (padrão `200`) | Conversas retidas em memória. ~7 KB cada; 200 ≈ 1,4 MB estáveis |
| | `0` ou negativo | Travado em `1` |

> **`sqlite` indisponível não quebra o boot.** Sem o pacote, ou com o caminho
> inacessível, o backend registra um warning e **cai para `memory`** — a
> persistência some sem erro. Se você configurou `sqlite` e a retomada não
> sobrevive ao restart, procure esse warning no log antes de qualquer outra
> coisa.

---

## Embeddings

| Variável | Valores | O que faz |
|---|---|---|
| `EMBEDDING_PROVIDER` | `auto` (padrão) | Tenta em ordem: `custom` → `localai` → `ollama` → `local` → `openai` → `hash` |
| | `custom` | Endpoint próprio de `EMBEDDING_BASE_URL` |
| | `localai` / `ollama` | O servidor local correspondente, pela URL já configurada |
| | `local` | Modelo ONNX dentro do backend — sem chave, ~220 MB no primeiro uso |
| | `openai` | API da OpenAI; exige `OPENAI_API_KEY` |
| | `hash` | Vetor determinístico offline. **Não é semântico**: busca por sentido deixa de funcionar |
| | qualquer outro | Vira o único candidato e falha — sem `auto`, não há reserva |
| `EMBEDDING_DIMENSIONS` | `0` (padrão) | Usa `QDRANT_VECTOR_SIZE` |
| | `1`+ | Fixa a dimensão do vetor |
| `EMBEDDING_CACHE_DIR` | vazio (padrão) | Cache padrão do HuggingFace — em container efêmero, baixa de novo a cada deploy |
| | caminho | Aponte para um volume para baixar uma vez só |

> **Trocar de provedor depois de indexar exige reindexar.** Dimensões
> diferentes não se comparam, e a busca passa a devolver resultado sem sentido
> em vez de erro. `POST /education/reindex` refaz o índice.

A ordem do `auto` põe `local` **antes** de `openai` de propósito: indexar aula
não pode parar porque uma chave paga venceu.

---

## Voz

| Variável | Valores | O que faz |
|---|---|---|
| `STT_PROVIDER` | `local` (padrão) | Whisper em processo |
| | `auto` ou `openai` | Tenta a OpenAI **se houver** `OPENAI_API_KEY`; falha cai no Whisper local |
| | qualquer outro | Vai direto ao Whisper local |
| `TTS_PROVIDER` | `auto` (padrão) ou `openai` | Tenta a OpenAI se houver chave; falha cai no gTTS |
| | qualquer outro | Vai direto ao gTTS |
| `WHISPER_DEVICE` | `cpu` (padrão) | Transcrição em CPU |
| | `cuda` | GPU — **exige** `nvidia-cublas-cu12` e `nvidia-cudnn-cu12`; sem elas o modelo não carrega e o STT fica indisponível |
| `WHISPER_COMPUTE_TYPE` | `int8` (padrão) | Quantizado, para CPU |
| | `float16` | Par usual de `cuda` |
| | `int8_float16`, `float32` | Aceitos pelo faster-whisper; valor inválido só falha ao carregar o modelo |
| `WHISPER_MODEL` | `tiny`…`large-v3` (padrão `small`) | Modelo baixado no primeiro uso; maior = mais lento e mais preciso |
| `WHISPER_VAD_FILTER` | booleano (padrão `true`) | Corta silêncio antes de transcrever |
| `OPENAI_TTS_SPEED` | `0.25`–`4.0` (padrão `0.95`) | Velocidade da fala |
| | fora da faixa | **Travado** na borda mais próxima, sem aviso: `10` vira `4.0` |
| | não numérico | Cai em `0.95` |

---

## Notificações

| Variável | Valores | O que faz |
|---|---|---|
| `WA_PROVIDER` | `callmebot` (padrão) | API do CallMeBot; `WA_TOKEN` é a apikey |
| | `zapi` | Z-API; usa `WA_SID` como instância |
| | `twilio` | Twilio; `WA_SID` + `WA_TOKEN` |
| | qualquer outro | Levanta "Provedor desconhecido" e o envio devolve `False` — registrado no log, sem quebrar o fluxo |
| `SMTP_STARTTLS` / `SMTP_USE_SSL` | booleanos (padrão `true` / `false`) | Ligue **um** dos dois: STARTTLS na 587, SSL na 465 |

Sem `WA_NUMBER` o envio nem tenta, seja qual for o provedor.

---

## Observabilidade

| Variável | Valores | O que faz |
|---|---|---|
| `OTEL_ENABLED` | `false` (padrão) | Sem OpenTelemetry; os spans continuam no sink de memória |
| | `true` | Liga o exporter OTLP/HTTP |
| `OTEL_EXPORTER_ENDPOINT` | vazio (padrão) | Usa o padrão do próprio SDK (`localhost:4318`) |
| | URL | Endpoint do collector |
| `OTEL_CONSOLE_EXPORT` | booleano (padrão `false`) | Também imprime spans no stdout — útil local, barulhento em produção |
| `OTEL_SERVICE_NAME` | texto (padrão `assistant-api`) | Nome no trace. Só a `assistant-api` lê |
| `TELEMETRY_MEMORY_EVENTS` | `1`+ (padrão `2000`) | Eventos retidos para a tela de observabilidade. Janela limitada de propósito: o backend roda por dias e histórico ilimitado vaza memória |
| | `0` | `deque(maxlen=0)`: nada é retido e a tela fica **sempre vazia** — sem erro que explique |
| `LANGSMITH_ENABLED` | booleano (padrão `false`) | Envia o plano de IA ao LangSmith; sem `LANGSMITH_API_KEY` não tem efeito |
| `LLM_PRICING` | vazio (padrão) | Tabela interna de preços |
| | JSON | Sobrescreve: `{"claude": {"input": 3.0, "output": 15.0}}`, por milhão de tokens. JSON inválido é ignorado com warning |

> **Pacote ausente não derruba o boot.** Sem os pacotes de OTel instalados,
> `OTEL_ENABLED=true` registra warning e segue: o backend precisa subir mesmo
> sem coletor.

---

## Segurança e acesso

| Variável | Valores | O que faz |
|---|---|---|
| `INTERNAL_SERVICE_TOKEN` | vazio (padrão) | **Fecha** as rotas internas: elas respondem `503`. Vazio nunca abre |
| | segredo | Mesmo valor na API e no orquestrador; comparado em tempo constante |
| `JWT_SECRET` / `SECRET_KEY` | os padrões estão no repositório | Trocar é obrigatório em qualquer ambiente exposto |
| `JWT_ALGORITHM` | `HS256` (padrão) | Simétrico. Algoritmo inválido só falha ao assinar, no login |
| `JWT_EXPIRE_MINUTES` | `1440` (padrão) | Validade do token. Muito curto derruba a sessão no meio da aula |
| `CREDENTIAL_ENCRYPTION_KEY` | vazio (padrão) | As credenciais de usuário **não são cifradas** no banco |
| | chave Fernet | Cifra as chaves de provedor. Trocar depois torna as já salvas ilegíveis |
| `REGISTRATION_INVITE_REQUIRED` | `false` (padrão) | Cadastro aberto enquanto não houver nenhum usuário |
| | `true` | Exige convite desde o primeiro cadastro |
| `CORS_ORIGINS` | lista separada por vírgula | Em PaaS, o padrão (`localhost`) **bloqueia** a interface publicada |
| `FORWARDED_ALLOW_IPS` | `*` em PaaS | Sem isso o redirect do OAuth sai em `http://` e falha |

---

## Banco de dados

| Variável | Valores | O que faz |
|---|---|---|
| `DATABASE_URL` | `mysql+aiomysql://…` | O formato esperado |
| | `mysql://…` | Driver síncrono: **trocado automaticamente** por `mysql+aiomysql://`, com warning |
| | incompleta | Log de erro e queda para as variáveis `MYSQL_*` do ambiente, quando existirem |
| | vazia ou o padrão de desenvolvimento | Tenta `MYSQL_*`; senão, o padrão local |
| `DATABASE_SEED` | vazio, `0`, `false`, `none`, `off` (padrão vazio) | Nenhum seed |
| | `demo-v1` | Popula dados de demonstração **uma vez**, marcado no banco |
| | qualquer outro | `ValueError` no startup: o processo **não sobe**. É a exceção à regra de "valor inválido cai no padrão" |
| `QDRANT_VECTOR_SIZE` | `384` (padrão) | Dimensão da coleção. Mudar depois de indexar exige reindexar |
| `QDRANT_COLLECTION_PREFIX` | `assistant` (padrão) | Permite dois ambientes no mesmo Qdrant |
| `REDIS_URL` | URL | Rate limiting. **Inalcançável não impede o boot**: o limite é simplesmente pulado |

> **Banco fora do ar não derruba o boot** — vira warning e as funções de
> histórico ficam desativadas. A exceção é quando `DATABASE_SEED` pede um seed:
> aí a falha sobe e o processo não sobe, porque seed pela metade é pior que
> nenhum.

---

## Processo

| Variável | Valores | O que faz |
|---|---|---|
| `PORT` | número | Injetada pela plataforma. Tem **precedência** sobre `ASSISTANT_API_PORT` |
| `HOST` | `0.0.0.0` (padrão) | `127.0.0.1` fecha o acesso externo |
| `RELOAD` | `true` (padrão) | Recarrega ao salvar. **Sempre `false` em deploy**: o reloader dobra o processo e a memória |
| `LOG_LEVEL` | `critical`, `error`, `warning`, `info` (padrão), `debug`, `trace` | Nível do uvicorn — são exatamente esses seis |
| | qualquer outro | O uvicorn recusa a subida com `KeyError`. Aqui o valor errado **falha alto** |

---

## Modo educação

| Variável | Valores | O que faz |
|---|---|---|
| `EDUCATION_SEGMENT_SECONDS` | `60` (padrão) | Tamanho do bloco de áudio transcrito |
| `EDUCATION_SUMMARY_MAX_CHARS` | `24000` (padrão) | Teto de transcrição por chamada de resumo |
| `EDUCATION_SUMMARY_MAX_PROVIDERS` | `3` (padrão) | Provedores tentados antes de desistir do resumo |
| `EDUCATION_SUMMARY_ALLOW_PAID_FALLBACK` | `true` (padrão) | Permite cair em provedor pago quando o local falha |
| | `false` | Sem provedor local disponível, a aula fica **sem resumo** em vez de gerar custo |
| `LOCAL_LLM_CONTEXT_TOKENS` | `8192` (padrão) | Janela dos modelos locais. Menor que o real devolve **erro**, não resumo ruim |
| `OCR_ENABLED` | `true` (padrão) | OCR local de material digitalizado, sem enviar nada para terceiros |
| `OCR_MAX_PAGES` | `1`+ (padrão `20`) | Teto por material (~1,7 s/página). Sem teto, uma apostila de 200 páginas seguraria o upload por minutos |
| | `0` ou negativo | Travado em `1` |
| `OCR_DPI` | `200` (padrão) | Abaixo de `150` o reconhecimento cai junto; muito acima só gasta tempo |
| `OCR_MIN_SCORE` | `0.0`–`1.0` (padrão `0.5`) | Linha abaixo disso é descartada. `0` aceita tudo — texto errado é pior que texto faltando |

---

## Como confirmar o que está valendo

A configuração é lida **uma vez por processo** (`get_settings()` é cacheado):
mudar o `.env` com o serviço no ar não tem efeito até reiniciar.

Para ver o que o processo entendeu, sem adivinhar:

```bash
# assistant-api no ar
curl -H "Authorization: Bearer <token>" http://localhost:8000/system/agents/status
```

A resposta traz o catálogo **efetivo** por especialista (já filtrado por escopo
e com as capacidades MCP), a saúde do Tool Gateway, o estado do MCP e o
provedor de embeddings **resolvido** — não o pedido no `.env`.

> **Uma exceção que engana: `graph.checkpointing` repete o valor configurado,
> não o que está em uso.** Se `CHECKPOINT_BACKEND=sqlite` caiu para memória por
> falta do pacote, essa resposta continua dizendo `sqlite`. Só o warning no log
> do boot denuncia a queda.

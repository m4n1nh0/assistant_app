# Configuração por serviço

Referência operacional: **qual variável de ambiente pertence a qual processo**.

O INTARQ roda como um processo só por padrão — `assistant-api`, com MCP e
ferramentas in-process. Este documento importa quando você separa os serviços
(`MCP_TRANSPORT=remote`, `TOOL_TRANSPORT=remote`) ou implanta em PaaS, onde cada
serviço tem seu próprio conjunto de variáveis.

Para o *porquê* de cada fronteira, veja
[Arquitetura agentiva](arquitetura-agentes.md).

---

## Como ler as tabelas

| Marca | Significado |
|---|---|
| **obrigatória** | Sem ela o serviço sobe degradado ou não atende |
| opcional | Tem padrão utilizável; ajuste quando precisar |
| — | O serviço não lê essa variável |
| ⚠ | Carregada por import transitivo, mas **não usada** — veja [a nota](#o-que-o-tool-service-carrega-sem-usar) |

As listas abaixo foram derivadas do fecho de imports de cada entrypoint cruzado
com as leituras de `settings.*` no código, e não de memória.

---

## Porta: a regra que vale para todos

Todo entrypoint resolve a porta com a mesma regra, em `services/common.py`:

```
PORT (injetada pela plataforma)  →  vence sempre que existe
    ↓ ausente
MCP_SERVICE_PORT / TOOL_SERVICE_PORT / ORCHESTRATOR_PORT / ASSISTANT_API_PORT
    ↓ ausente
padrão do Settings (8002 / 8003 / 8001 / 8000)
```

> **Em PaaS, não defina a porta específica do serviço.** Railway, Render e Fly
> injetam `PORT` e roteiam o tráfego para ela. Fixar `MCP_SERVICE_PORT=8002` num
> serviço dedicado faria o processo escutar numa porta que o roteador não
> conhece — e o healthcheck reprovaria sem mensagem útil.
>
> As portas específicas existem para o desenvolvimento local, onde os três
> processos precisam conviver na mesma máquina.

---

## `assistant-api`

O processo do produto. Lê praticamente todo o `Settings` — **124 variáveis** —
porque expõe chat, agenda, educação, quiz, voz, notificações e autenticação.

Use o `backend/.env.example` como base. O que a migração
agentiva acrescentou está agrupado abaixo.

### Orquestração

| Variável | Padrão | Efeito |
|---|---|---|
| `AGENT_MAX_TOOL_ITERATIONS` | `3` | Rodadas de ferramenta antes de fechar a resposta |
| `AGENT_MAX_HANDOFFS` | `2` | Transferências entre especialistas por mensagem |
| `GRAPH_NODE_MAX_RETRIES` | `2` | Tentativas por nó que fala com serviço externo |
| `CHECKPOINT_BACKEND` | `memory` | `memory`, `sqlite` ou `none` |
| `CHECKPOINT_SQLITE_PATH` | `data/checkpoints.sqlite` | Só com backend `sqlite` **e** volume montado |
| `CHECKPOINT_MAX_THREADS` | `200` | Teto de conversas retidas em memória — ver abaixo |

> **`CHECKPOINT_MAX_THREADS` não é enfeite.** O `InMemorySaver` do LangGraph
> nunca descarta nada; sem teto, um processo de vida longa acumula todo
> checkpoint já gravado. Medido neste projeto: ~7 KB por conversa de uma
> mensagem. Com o teto em 200, a memória estabiliza em ~1,4 MB mesmo depois de
> milhares de conversas.

### Transporte das capacidades

| Variável | Padrão | Efeito |
|---|---|---|
| `TOOL_TRANSPORT` | `local` | `remote` move o catálogo para o `tool-service` |
| `TOOL_SERVICE_URL` | deduz da porta | Obrigatória quando `remote` em PaaS |
| `MCP_TRANSPORT` | `local` | `remote` move o MCP para o `mcp-service` |
| `MCP_SERVICE_URL` | deduz da porta | Obrigatória quando `remote` em PaaS |

Com transporte `local`, este serviço também precisa do bloco de MCP e de
ferramentas listado nas seções seguintes — é ele quem executa tudo.

### Observabilidade

| Variável | Padrão | Efeito |
|---|---|---|
| `OTEL_ENABLED` | `false` | Ligue **só** com collector alcançável |
| `OTEL_SERVICE_NAME` | `assistant-api` | Nome no trace. **Só este serviço lê** — os outros passam o próprio nome no código |
| `OTEL_EXPORTER_ENDPOINT` | padrão do SDK | Endpoint OTLP/HTTP |
| `OTEL_CONSOLE_EXPORT` | `false` | Também imprime spans no stdout |
| `TELEMETRY_MEMORY_EVENTS` | `2000` | Janela de diagnóstico; já é limitada |
| `LANGSMITH_ENABLED` | `false` | Tracing dos fluxos de IA |
| `LANGSMITH_API_KEY` | — | Obrigatória se `LANGSMITH_ENABLED=true` |
| `LANGSMITH_PROJECT` | `assistant-app` | Projeto que recebe os traces |
| `LANGSMITH_ENDPOINT` | — | Instalação própria do LangSmith |
| `LLM_PRICING` | — | Preço por milhão de tokens, sobrescreve a tabela interna |

---

## `mcp-service`

O serviço mais enxuto: **18 settings**, nenhum segredo de aplicação. Não conhece
banco, JWT, provedores de LLM nem Qdrant.

```bash
# --- obrigatória -----------------------------------------------------------
MCP_SERVERS={"fs":{"command":"npx","args":["-y","@mcp/server-fs","/dados"]}}

# --- porta -----------------------------------------------------------------
# Em PaaS: nada aqui — a plataforma injeta PORT.
MCP_SERVICE_PORT=8002          # só no desenvolvimento local

# --- resiliência -----------------------------------------------------------
MCP_TIMEOUT_SECONDS=30
MCP_MAX_RETRIES=2
MCP_RETRY_BACKOFF_SECONDS=0.5
MCP_CIRCUIT_FAILURE_THRESHOLD=3
MCP_CIRCUIT_RESET_SECONDS=60
MCP_TOOLS_CACHE_TTL_SECONDS=300

# --- processo --------------------------------------------------------------
HOST=0.0.0.0
LOG_LEVEL=info
RELOAD=false

# --- observabilidade (opcional) --------------------------------------------
OTEL_ENABLED=false
OTEL_EXPORTER_ENDPOINT=
TELEMETRY_MEMORY_EVENTS=2000
```

**Sem `MCP_SERVERS`** o serviço sobe, responde `live` e reporta
`ready: {ok: true, configured: false, servers: 0}` — uma instalação que
simplesmente não usa MCP não é uma falha.

**Não coloque aqui:** `DATABASE_URL`, `JWT_SECRET`, `REDIS_URL`, chaves de
provedor, `CREDENTIAL_ENCRYPTION_KEY`, `LANGSMITH_*`. Nenhuma é lida — e chave
que não é usada não deve existir no ambiente.

---

## `tool-service`

Catálogo e execução das ferramentas. Precisa do bloco de MCP porque **publica as
capacidades MCP no catálogo** — é o gateway dele que fala com o `mcp-service`.

```bash
# --- porta -----------------------------------------------------------------
TOOL_SERVICE_PORT=8003         # só no desenvolvimento local

# --- execução de ferramenta ------------------------------------------------
TOOL_TIMEOUT_SECONDS=20
TOOL_MAX_RETRIES=1
TOOL_RETRY_BACKOFF_SECONDS=0.5

# --- de onde vêm as capacidades MCP ----------------------------------------
MCP_TRANSPORT=remote
MCP_SERVICE_URL=http://mcp-service.railway.internal:8002
MCP_TIMEOUT_SECONDS=30
MCP_MAX_RETRIES=2
MCP_RETRY_BACKOFF_SECONDS=0.5
# Se MCP_TRANSPORT=local, troque as duas linhas acima por MCP_SERVERS.

# --- processo --------------------------------------------------------------
HOST=0.0.0.0
LOG_LEVEL=info
RELOAD=false

# --- observabilidade (opcional) --------------------------------------------
OTEL_ENABLED=false
OTEL_EXPORTER_ENDPOINT=
```

### O que o `tool-service` carrega sem usar

⚠ Ao montar o catálogo, este serviço importa transitivamente
`app.core.database`, `app.core.security` e `credential_storage_service`:

```
tool_service.main
  └── build_local_tool_gateway
        └── toolkit.catalog.build_local_registry
              └── services.assistant_tools
                    └── launcher_service ── app.core.database  (modelos + engine)
                    └── user_llm_config_service ── app.core.security          (JWT)
                                                └── credential_storage_service (cifra)
```

Consequência prática: `DATABASE_URL`, `JWT_SECRET` e
`CREDENTIAL_ENCRYPTION_KEY` aparecem no fecho de imports, mas **nenhum código
executado pelo `tool-service` os utiliza**. As ferramentas dele só montam
proposta; não consultam banco nem autenticam.

O engine do SQLAlchemy é criado no import (`app/core/database.py:62`), porém não
conecta até o primeiro uso — que nunca acontece aqui. Então:

- **Não defina** essas variáveis no `tool-service`. Sem elas o padrão do
  `Settings` é usado, o engine é construído e fica ocioso, e nada quebra.
- Definir um `DATABASE_URL` real seria dar ao serviço uma credencial que ele não
  precisa.

É uma aresta conhecida, não um requisito. Resolvê-la significa separar as
construtoras puras (`build_project_open_action`,
`build_shortcut_registration_action`) do módulo que carrega os modelos de banco.

---

## `agent-orchestrator`

Ao subir, lê apenas **9 settings**. Ao atender uma requisição, precisa de quase
tudo que a `assistant-api` precisa — e é exatamente por isso que ele **não é
extraído por padrão**.

```bash
ORCHESTRATOR_PORT=8001         # só no desenvolvimento local
CHECKPOINT_BACKEND=memory
CHECKPOINT_MAX_THREADS=200
CHECKPOINT_SQLITE_PATH=data/checkpoints.sqlite
GRAPH_NODE_MAX_RETRIES=2
HOST=0.0.0.0
LOG_LEVEL=info
RELOAD=false
```

> **Antes de separar este serviço, leia isto.** As credenciais de nuvem são de
> cada usuário, ficam cifradas no banco e são decifradas **por requisição** num
> `ContextVar`. Um orquestrador em outro processo precisaria receber essas chaves
> pela rede a cada mensagem — trocando segurança por um isolamento que, num
> backend que roda na máquina do usuário, não resolve problema nenhum.
>
> O entrypoint existe para teste de carga isolado do fluxo agentivo e para o dia
> em que API e orquestração precisarem escalar separado. Nesse dia, ele precisará
> também do bloco de provedores, de `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL` e
> `EMBEDDING_*`.

---

## `otel-collector`

Não é código deste repositório — é a imagem oficial, configurada por arquivo.

| Variável | Padrão | Efeito |
|---|---|---|
| `OBSERVABILITY_PORT` | `8004` | Porta publicada do receptor OTLP/HTTP |

A configuração de destino vive em `infra/otel-collector.yaml`.
Trocar de backend de observabilidade é acrescentar um exporter ali — não há nome
de fornecedor no código da aplicação.

---

## Matriz resumida

| Variável | assistant-api | mcp-service | tool-service | orchestrator |
|---|:---:|:---:|:---:|:---:|
| `PORT` (plataforma) | **obrig.** | **obrig.** | **obrig.** | **obrig.** |
| `HOST` / `LOG_LEVEL` / `RELOAD` | opcional | opcional | opcional | opcional |
| `MCP_SERVERS` | se local | **obrig.** | se local | — |
| `MCP_TIMEOUT_SECONDS` e demais `MCP_*` | opcional | opcional | opcional | — |
| `MCP_TRANSPORT` / `MCP_SERVICE_URL` | opcional | — | opcional | — |
| `TOOL_TIMEOUT_SECONDS` / `TOOL_MAX_RETRIES` | opcional | — | opcional | — |
| `TOOL_TRANSPORT` / `TOOL_SERVICE_URL` | opcional | — | — | — |
| `CHECKPOINT_*` / `GRAPH_NODE_MAX_RETRIES` | opcional | — | — | opcional |
| `AGENT_MAX_*` | opcional | — | — | opcional |
| `OTEL_*` / `TELEMETRY_MEMORY_EVENTS` | opcional | opcional | opcional | opcional |
| `OTEL_SERVICE_NAME` | opcional | — | — | — |
| `LANGSMITH_*` / `LLM_PRICING` | opcional | — | — | opcional |
| `DATABASE_URL` | **obrig.** | — | ⚠ | futuro |
| `REDIS_URL` | opcional | — | — | futuro |
| `QDRANT_*` / `EMBEDDING_*` | opcional | — | — | futuro |
| `JWT_SECRET` / `SECRET_KEY` | **obrig.** | — | ⚠ | futuro |
| `CREDENTIAL_ENCRYPTION_KEY` | **obrig.** | — | ⚠ | futuro |
| Chaves de provedor (`CLAUDE_API_KEY`…) | migração inicial | — | — | futuro |
| `SMTP_*` / `BREVO_API_KEY` | opcional | — | — | — |
| `TELEGRAM_*` / `WA_*` | opcional | — | — | — |
| `GOOGLE_OAUTH_*` / `MICROSOFT_OAUTH_*` | opcional | — | — | — |
| `WHISPER_*` / `STT_*` / `TTS_*` | opcional | — | — | — |

As chaves de provedor no `.env` servem apenas para a migração única da primeira
conta administrativa; cada usuário cadastra as suas pela aba **Agentes**, e elas
ficam cifradas no banco.

---

## Variáveis compartilhadas entre todos

Três grupos precisam ter o **mesmo valor** em todos os serviços de um ambiente:

1. **Endpoint de observabilidade** (`OTEL_EXPORTER_ENDPOINT`) — para os spans dos
   quatro processos caírem no mesmo collector e formarem um trace só.
2. **Parâmetros de resiliência do MCP** — quando `assistant-api` e `tool-service`
   falam com o mesmo `mcp-service`, timeouts divergentes produzem
   comportamento inconsistente sob falha.
3. **`LOG_LEVEL`** — não é obrigatório, mas depurar com níveis diferentes por
   serviço é a receita para perder metade do rastro.

Os identificadores de correlação (`request_id`, `trace_id`, `conversation_id`,
`execution_id`) **não** são configuração: viajam em cabeçalho
(`traceparent`, `X-Request-ID`, `X-Conversation-ID`, `X-Execution-ID`) e são
gerados quando ausentes.

---

## Receita: separar os serviços no Railway

1. **`mcp-service`** — novo serviço, mesmo repositório.
   Start command: `python -m services.mcp_service.main`
   Variáveis: só o bloco de `mcp-service` acima, **sem** `MCP_SERVICE_PORT`.
   Healthcheck: `/health/live`.

2. **`tool-service`** — novo serviço, mesmo repositório.
   Start command: `python -m services.tool_service.main`
   Variáveis: bloco de `tool-service`, com
   `MCP_SERVICE_URL=http://mcp-service.railway.internal:8002`.

3. **`assistant-api`** — no serviço existente, acrescente:
   ```bash
   TOOL_TRANSPORT=remote
   TOOL_SERVICE_URL=http://tool-service.railway.internal:8003
   MCP_TRANSPORT=remote
   MCP_SERVICE_URL=http://mcp-service.railway.internal:8002
   ```
   E **remova** `MCP_SERVERS` — quem fala com os servidores agora é o
   `mcp-service`.

Os domínios `*.railway.internal` só respondem entre serviços do mesmo projeto.
As portas nas URLs internas são as que cada serviço realmente abriu — a
plataforma injeta `PORT` em cada um, então confirme no log de boot a linha
`… escutando em 0.0.0.0:<porta>`.

Localmente, o mesmo arranjo sobe com:

```bash
docker compose --profile services up
```

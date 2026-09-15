# Configuração por serviço

Referência operacional: **qual variável de ambiente pertence a qual processo**.

O INTARQ roda como um processo só por padrão — `assistant-api`, com MCP e
ferramentas in-process. Este documento importa quando você separa os serviços
(`MCP_TRANSPORT=remote`, `TOOL_TRANSPORT=remote`) ou implanta em PaaS, onde cada
serviço tem seu próprio conjunto de variáveis.

Para o *porquê* de cada fronteira, veja
[Arquitetura agentiva](arquitetura-agentes.md). Se você veio aqui para **criar
os serviços agora**, o caminho curto é [a receita](#receita-criar-os-servicos) —
mas leia antes [o que não copiar do `.env.example`](#o-que-nao-copiar-do-envexample),
que é onde o deploy costuma quebrar.

---

## Como ler as tabelas

| Marca | Significado |
|---|---|
| **obrigatória** | Sem ela o serviço sobe degradado ou não atende |
| opcional | Tem padrão utilizável; ajuste quando precisar |
| lida, sem efeito | O processo lê no boot, mas não há nele nada que use o valor |
| — | O serviço não lê essa variável |
| ⚠ | Carregada por import transitivo, mas **não usada** — veja [a nota](#o-que-o-tool-service-carrega-sem-usar) |

As listas abaixo não vêm de memória: cada entrypoint foi importado, os módulos
efetivamente carregados (`sys.modules`) foram cruzados com as leituras de
`settings.*` desses módulos, e o resultado é o que está aqui. Import preguiçoso
dentro de função conta quando a função roda na subida — que é o caso de
`build_mcp_client()` e `build_local_tool_gateway()`.

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

> **Nunca defina a porta específica do serviço em PaaS.** `MCP_SERVICE_PORT` e
> companhia perdem para `PORT` e só servem para confundir o diagnóstico: você lê
> `8002` no painel e o processo está escutando em outra porta.
>
> As portas específicas existem para o desenvolvimento local, onde os três
> processos precisam conviver na mesma máquina.

**`PORT`, por outro lado, vale fixar nos serviços dedicados.** Rede interna se
endereça por `host:porta` — `http://mcp-service.railway.internal:8002` só
funciona se o `mcp-service` realmente abriu a 8002. Deixando a plataforma
escolher, o endereço muda quando ela quiser e você descobre pelo timeout. Fixe
`PORT=8002` no `mcp-service` e `PORT=8003` no `tool-service`, e as URLs internas
viram constantes. Se preferir deixar a plataforma decidir, a porta efetiva está
no log de boot:

```
services.mcp_service.main:app escutando em 0.0.0.0:<porta>
```

---

## O que não copiar do `.env.example`

O `backend/.env.example` é um arquivo de **desenvolvimento**. Três linhas dele
quebram um deploy em silêncio:

| Linha | O que acontece se você copiar | O que usar |
|---|---|---|
| `RELOAD=true` | `serve()` passa `reload=True` ao uvicorn: o processo sobe um *file watcher* e um subprocesso extra em produção, para vigiar arquivos que nunca mudam | `RELOAD=false` em **todo** serviço implantado |
| `PORT=8000` | Todos os serviços escutam na 8000; a plataforma roteia para a porta que ela injetou, não acha ninguém, e o healthcheck reprova sem mensagem útil | Não copie. Fixe `PORT` por serviço (8002/8003) ou deixe a plataforma injetar |
| Chaves de provedor | Ficam num serviço que não fala com modelo nenhum | Só na `assistant-api`, e só para a migração inicial |

O `RELOAD` merece um parágrafo porque o padrão do `Settings` é `True`
(`app/core/config.py:44`) — quem **não** definir a variável também sobe com
reload ligado. No `docker-compose.yml` isso não aparece porque os serviços
extraídos são chamados com `python -m uvicorn ... --host --port`, desviando de
`serve()`; num PaaS com `python -m services.<x>.main`, aparece.

---

## Bloco de observabilidade: igual nos quatro processos

`create_service()` chama `setup_observability()` em todo entrypoint extraído, e
`app/main.py` faz o mesmo pela `assistant-api`. Consequência: **os quatro
processos leem estas nove variáveis no boot**, sem exceção.

```bash
OTEL_ENABLED=false
OTEL_EXPORTER_ENDPOINT=
OTEL_CONSOLE_EXPORT=false
TELEMETRY_MEMORY_EVENTS=2000
LLM_PRICING=
LANGSMITH_ENABLED=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=assistant-app
LANGSMITH_ENDPOINT=
```

Ler não é o mesmo que usar. `LANGSMITH_*` e `LLM_PRICING` só produzem efeito
onde existe chamada de modelo — `assistant-api` e `agent-orchestrator`. No
`mcp-service` e no `tool-service` elas são lidas, ligam um tracing que nunca
receberá um span de LLM, e **não deveriam estar no ambiente**: variável sem
efeito é credencial exposta sem contrapartida.

`OTEL_SERVICE_NAME` é a exceção do bloco. Só a `assistant-api` a lê
(`app/main.py:187`); os serviços extraídos passam o próprio nome no código, em
`create_service(name=...)`. Defini-la num serviço extraído não renomeia nada.

---

## `assistant-api`

O processo do produto. É o único que pode ler qualquer um dos **124 campos** do
`Settings`: 105 já aparecem no fecho de imports da subida, e o resto entra em
módulos carregados sob demanda (voz, e-mail, integrações). Por isso a lista dele
é o `backend/.env.example` inteiro, e não uma tabela aqui.

O que a migração agentiva acrescentou está agrupado abaixo.

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

### Rede e sessão

| Variável | Padrão | Efeito |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost,http://127.0.0.1` | Lista separada por vírgula. Em PaaS, o padrão bloqueia a interface publicada |
| `JWT_SECRET` / `SECRET_KEY` | valores de exemplo | Trocar é obrigatório: o padrão está no repositório |
| `CREDENTIAL_ENCRYPTION_KEY` | — | Sem ela as credenciais de usuário não são cifradas no banco |

### Observabilidade

Além das [nove do bloco comum](#bloco-de-observabilidade-igual-nos-quatro-processos),
só aqui vale:

| Variável | Padrão | Efeito |
|---|---|---|
| `OTEL_SERVICE_NAME` | `assistant-api` | Nome no trace. **Só este serviço lê** |

---

## `mcp-service`

O serviço mais enxuto: **20 variáveis** — 11 próprias e as 9 do bloco de
observabilidade — mais o `PORT` que a plataforma injeta. Não conhece banco, JWT,
provedores de LLM nem Qdrant: nenhum desses módulos entra no processo.

O arquivo pronto é `backend/.env.mcp-service.example`. Copie para
`backend/.env.mcp-service` — é o nome que o `docker-compose.yml` lê — ou cole o
conteúdo nas variáveis do serviço em PaaS.

```bash
# --- obrigatória -----------------------------------------------------------
MCP_SERVERS={"fs":{"command":"npx","args":["-y","@mcp/server-fs","/dados"]}}

# --- porta -----------------------------------------------------------------
PORT=8002                      # fixe em PaaS: a URL interna depende dela
# MCP_SERVICE_PORT=8002        # só no desenvolvimento local, sem PORT

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

# --- observabilidade -------------------------------------------------------
OTEL_ENABLED=false
OTEL_EXPORTER_ENDPOINT=
OTEL_CONSOLE_EXPORT=false
TELEMETRY_MEMORY_EVENTS=2000
```

**Sem `MCP_SERVERS`** o serviço sobe, responde `live` e reporta
`ready: {ok: true, configured: false, servers: 0}` — uma instalação que
simplesmente não usa MCP não é uma falha.

**Não coloque aqui:** `DATABASE_URL`, `JWT_SECRET`, `REDIS_URL`, chaves de
provedor, `CREDENTIAL_ENCRYPTION_KEY`, `CORS_ORIGINS`. Nenhuma é lida — e chave
que não é usada não deve existir no ambiente.

`LANGSMITH_*` e `LLM_PRICING` são um caso à parte: **são lidas** no boot, porque
`setup_observability()` roda em todo entrypoint. Também não pertencem aqui —
mas por não terem efeito, e não por não serem lidas. Não há componente LangChain
neste processo para gerar trace.

---

## `tool-service`

Catálogo e execução das ferramentas: **21 variáveis** no arranjo recomendado
(MCP remoto) — 12 próprias e as 9 do bloco de observabilidade. Precisa do bloco
de MCP porque **publica as capacidades MCP no catálogo**: é o gateway dele que
fala com o `mcp-service`.

Arquivo pronto: `backend/.env.tool-service.example` → `backend/.env.tool-service`.

```bash
# --- porta -----------------------------------------------------------------
PORT=8003                      # fixe em PaaS
# TOOL_SERVICE_PORT=8003       # só no desenvolvimento local, sem PORT

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
# Com MCP_TRANSPORT=local, troque as duas primeiras linhas por MCP_SERVERS e
# acrescente MCP_TOOLS_CACHE_TTL_SECONDS e as duas MCP_CIRCUIT_* — o cliente
# direto usa cache e disjuntor; o gateway remoto, não.

# --- processo --------------------------------------------------------------
HOST=0.0.0.0
LOG_LEVEL=info
RELOAD=false

# --- observabilidade -------------------------------------------------------
OTEL_ENABLED=false
OTEL_EXPORTER_ENDPOINT=
OTEL_CONSOLE_EXPORT=false
TELEMETRY_MEMORY_EVENTS=2000
```

> **O healthcheck da plataforma é `/health/live`, não `/health/ready`.** O
> `ready` deste serviço só responde `ok: true` com pelo menos uma ferramenta
> publicada (`services/tool_service/main.py:37`). É o comportamento certo para
> quem vai *mandar trabalho* — e o errado para quem decide *reiniciar o
> container*: um catálogo momentaneamente vazio viraria loop de restart.

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

Ao subir, lê **17 variáveis** — 8 próprias e as 9 do bloco de observabilidade.
Ao atender uma requisição, precisa de quase tudo que a `assistant-api` precisa —
e é exatamente por isso que ele **não é extraído por padrão**.

```bash
ORCHESTRATOR_PORT=8001         # só no desenvolvimento local
CHECKPOINT_BACKEND=memory
CHECKPOINT_MAX_THREADS=200
CHECKPOINT_SQLITE_PATH=data/checkpoints.sqlite
GRAPH_NODE_MAX_RETRIES=2
HOST=0.0.0.0
LOG_LEVEL=info
RELOAD=false
# + o bloco de observabilidade; aqui LANGSMITH_* tem efeito real,
#   porque é neste processo que o grafo LangGraph roda.
```

No `docker-compose.yml` ele tem **perfil próprio**, `orchestrator`, fora de
`services`: o arranjo padrão de desenvolvimento é MCP e ferramentas remotos com
o grafo rodando dentro da `assistant-api`. Sobe com
`docker compose --profile orchestrator up`, ou direto de `backend/` com
`python -m services.orchestrator.main`. O arquivo de variáveis é
`backend/.env.orchestrator.example`, e o bloco comentado no fim dele é o que
falta para o serviço **atender** requisição, e não só subir.

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

`OBSERVABILITY_PORT` é lida pelo **`docker-compose.yml`**, na interpolação
`${OBSERVABILITY_PORT:-8004}`; nenhum código da aplicação a consulta. Definir a
variável no ambiente de um serviço Python não muda nada.

A configuração de destino vive em `infra/otel-collector.yaml`.
Trocar de backend de observabilidade é acrescentar um exporter ali — não há nome
de fornecedor no código da aplicação.

---

## Matriz resumida

| Variável | assistant-api | mcp-service | tool-service | orchestrator |
|---|:---:|:---:|:---:|:---:|
| `PORT` (plataforma) | **obrig.** | **obrig.** | **obrig.** | **obrig.** |
| `HOST` / `LOG_LEVEL` | opcional | opcional | opcional | opcional |
| `RELOAD` | **`false`** | **`false`** | **`false`** | **`false`** |
| `MCP_SERVERS` | se local | **obrig.** | se local | — |
| `MCP_TIMEOUT_SECONDS` / `MCP_MAX_RETRIES` / `MCP_RETRY_BACKOFF_SECONDS` | opcional | opcional | opcional | — |
| `MCP_TOOLS_CACHE_TTL_SECONDS` / `MCP_CIRCUIT_*` | se local | opcional | se local | — |
| `MCP_TRANSPORT` / `MCP_SERVICE_URL` | opcional | — | opcional | — |
| `TOOL_TIMEOUT_SECONDS` / `TOOL_MAX_RETRIES` | opcional | — | opcional | — |
| `TOOL_TRANSPORT` / `TOOL_SERVICE_URL` | opcional | — | — | — |
| `CHECKPOINT_*` / `GRAPH_NODE_MAX_RETRIES` | opcional | — | — | opcional |
| `AGENT_MAX_*` | opcional | — | — | opcional |
| `OTEL_ENABLED` / `OTEL_EXPORTER_ENDPOINT` / `OTEL_CONSOLE_EXPORT` | opcional | opcional | opcional | opcional |
| `TELEMETRY_MEMORY_EVENTS` | opcional | opcional | opcional | opcional |
| `OTEL_SERVICE_NAME` | opcional | — | — | — |
| `LANGSMITH_*` / `LLM_PRICING` | opcional | lida, sem efeito | lida, sem efeito | opcional |
| `CORS_ORIGINS` | **obrig.** em PaaS | — | — | — |
| `DATABASE_URL` | **obrig.** | — | ⚠ | futuro |
| `REDIS_URL` | opcional | — | — | futuro |
| `QDRANT_*` / `EMBEDDING_*` | opcional | — | — | futuro |
| `JWT_SECRET` / `SECRET_KEY` | **obrig.** | — | ⚠ | futuro |
| `CREDENTIAL_ENCRYPTION_KEY` | **obrig.** | — | ⚠ | futuro |
| Chaves de provedor (`CLAUDE_API_KEY`…) | migração inicial | — | — | futuro |
| `SMTP_*` / `BREVO_API_KEY` | opcional | — | — | — |
| `TELEGRAM_*` / `WA_*` | opcional | — | ⚠ | — |
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

## Receita: criar os serviços

A ordem importa. O `mcp-service` não depende de ninguém, o `tool-service`
depende dele, e a `assistant-api` depende dos dois. Crie de dentro para fora e
**verifique cada um antes de criar o próximo** — assim, quando algo falhar, o
serviço culpado é o último que você mexeu.

### Uma imagem por serviço, menos uma

Cada serviço extraído tem o **próprio Dockerfile e o próprio recorte de
dependências**, derivado do fecho de imports real do entrypoint — o processo foi
importado e os módulos de terceiros carregados foram mapeados de volta para as
distribuições que os fornecem.

| Serviço | Dockerfile | Requisitos | Pacotes instalados |
|---|---|---|---:|
| `assistant-api` | `Dockerfile` | `requirements.txt` | tudo |
| `mcp-service` | `Dockerfile.mcp-service` | `requirements-mcp-service.txt` | 70 — **101 MB** |
| `tool-service` | `Dockerfile.tool-service` | `requirements-tool-service.txt` | 87 — **136 MB** |
| `agent-orchestrator` | `Dockerfile` | `requirements.txt` | tudo |

Os dois números em negrito são o `site-packages` de um virtualenv limpo com cada
arquivo instalado — medidos, não estimados. Do lado da imagem cheia, o número
que importa é este: **`nvidia-cublas-cu12` e `nvidia-cudnn-cu12` ocupam 2,1 GB**
e existem só para `WHISPER_DEVICE=cuda`.

O que mais fica de fora dos dois enxutos: `faster-whisper`,
`fastembed`/`onnxruntime`, os SDKs de provedor (`anthropic`, `openai`,
`google-generativeai`, `huggingface-hub`), `qdrant-client`, `redis`,
`apscheduler`, `python-telegram-bot` e o cliente do Google. Nenhum é importado
por eles.

O comando de entrada é o `CMD` de cada Dockerfile, `python -m
services.<x>.main`. Em PaaS, portanto, o *start command* fica vazio: a imagem já
sabe o que rodar.

#### Por que o `agent-orchestrator` fica na imagem cheia

Não é esquecimento. Ao atender `POST /orchestrate/chat` ele importa
`agent_service` e `langchain_agent_service` — imports dentro do nó, em
`app/orchestration/nodes/dispatch.py:169` —, que puxam os SDKs de provedor, o
banco e o Qdrant. Uma imagem enxuta aqui **subiria e
passaria no healthcheck**, e só quebraria na primeira requisição real. Trocar
2 GB por esse tipo de falha não é economia — é adiar o erro para o pior momento.

É a mesma regra para qualquer serviço futuro: só vale recortar dependência de um
processo cujo caminho de execução inteiro você conhece.

#### O risco que a separação cria, e o que o cobre

Dependência recortada quebra em **runtime**, não no build. Isso não é teórico:
a primeira versão de `requirements-tool-service.txt` esqueceu `pytz`, e o serviço
só falhou ao ser instalado num virtualenv limpo — o import está dentro de
`assistant_tools`, então a falta derruba a montagem do catálogo e o processo nem
sobe. O erro foi encontrado assim, e é assim que se encontra:

```bash
python -m venv /tmp/v && /tmp/v/bin/pip install -r requirements-mcp-service.txt
/tmp/v/bin/python -m services.mcp_service.main    # tem de responder /health/ready
```

Contra a deriva de **versão** — quatro imagens com `langchain` ou `pydantic`
diferentes, que produz bug em um serviço e não no outro —, existe
`tests/test_service_requirements.py`: ele falha se um pino divergir do
`requirements.txt`, se um arquivo de serviço citar pacote que não existe lá, ou
se um `Dockerfile.<serviço>` ficar sem o `requirements-<serviço>.txt` do par.

Contra a deriva de **pacote** não há teste possível a partir do código-fonte; o
sinal é o healthcheck do deploy. Era o preço anunciado.

### Antes de começar

Em cada serviço novo da plataforma:

- *Root directory*: `backend` — os Dockerfiles e o pacote `services/` estão lá.
- *Dockerfile*: o da tabela acima (no Railway, `RAILWAY_DOCKERFILE_PATH`).
- *Start command*: **vazio** — o `CMD` da imagem já é o certo.
- *Variáveis*: o `backend/.env.<serviço>.example` correspondente.

> **Servidor MCP `stdio` precisa do runtime dele dentro da imagem.** O
> `Dockerfile.mcp-service` traz Python e `curl` — **não traz Node**, porque isso
> dobraria o tamanho da imagem e nem todo servidor precisa. Se os seus
> `MCP_SERVERS` usam `npx`, construa com `--build-arg WITH_NODE=true` (no
> compose, `MCP_WITH_NODE=true`). Servidores com transporte `http` não têm esse
> requisito.

### 1. `mcp-service`

```
Dockerfile:    backend/Dockerfile.mcp-service
Start command: vazio (o CMD da imagem)
Healthcheck:   /health/live
Variáveis:     backend/.env.mcp-service.example (PORT=8002, RELOAD=false)
```

Verifique no log de boot, nesta ordem:

```
services.mcp_service.main:app escutando em 0.0.0.0:8002
mcp-service pronto: N capacidades de M servidor(es)
```

A segunda linha vira `mcp-service sem servidores declarados em MCP_SERVERS` se
você ainda não configurou nenhum servidor — e isso é um estado válido:
`/health/ready` responde `{"ok": true, "configured": false, "servers": 0}`.

### 2. `tool-service`

```
Dockerfile:    backend/Dockerfile.tool-service
Start command: vazio (o CMD da imagem)
Healthcheck:   /health/live   (nunca /health/ready — veja a nota acima)
Variáveis:     backend/.env.tool-service.example (PORT=8003, RELOAD=false),
               trocando MCP_SERVICE_URL pelo domínio interno da plataforma:
               http://mcp-service.railway.internal:8002
```

Verifique:

```
tool-service pronto: N ferramentas
```

`N` inclui as capacidades vindas do `mcp-service`. Se ele estiver de pé com
servidores e `N` for igual ao número de ferramentas locais, a URL interna está
errada — confira a porta contra a linha `escutando em` do serviço anterior.

### 3. `assistant-api`

No serviço que já existe, acrescente:

```bash
TOOL_TRANSPORT=remote
TOOL_SERVICE_URL=http://tool-service.railway.internal:8003
MCP_TRANSPORT=remote
MCP_SERVICE_URL=http://mcp-service.railway.internal:8002
```

E **remova** `MCP_SERVERS` — quem fala com os servidores agora é o
`mcp-service`. No boot, o container registra as duas trocas:

```
MCP remoto em http://mcp-service.railway.internal:8002
Tool service remoto em http://tool-service.railway.internal:8003
```

A confirmação de ponta a ponta é `GET /system/agents/status` (autenticado): o
campo `tools.transport` e o campo `mcp.transport` precisam dizer `"remote"`, e
`tools.tools` precisa bater com o `N` do log do `tool-service`.

### Voltar atrás

Trocar `TOOL_TRANSPORT` e `MCP_TRANSPORT` de volta para `local` e restaurar
`MCP_SERVERS` na `assistant-api` desfaz tudo, sem redeploy dos outros serviços e
sem tocar em código. Os dois serviços dedicados podem ficar de pé, ociosos, até
você decidir.

### Rede interna

Os domínios `*.railway.internal` só respondem entre serviços do mesmo projeto —
não há como testá-los do seu terminal. Para inspecionar `/tools` ou
`/mcp/servers` durante a configuração, dê um domínio público **temporário** ao
serviço e remova depois: nenhum dos dois tem autenticação própria.

---

## O mesmo arranjo, localmente

```bash
cp backend/.env.mcp-service.example  backend/.env.mcp-service
cp backend/.env.tool-service.example backend/.env.tool-service
# e, no backend/.env:  MCP_TRANSPORT=remote  e  TOOL_TRANSPORT=remote
docker compose --profile services up
```

Cada serviço lê o **próprio** arquivo; nenhum deles herda o `backend/.env`. É a
mesma separação do PaaS, pela mesma razão: processo que não lê `DATABASE_URL`
não deve recebê-la nem na sua máquina.

O transporte aparece em **dois** arquivos, e não é redundância. O `backend/.env`
diz à `assistant-api` que ela fala por HTTP com os dois serviços; o
`backend/.env.tool-service` diz ao `tool-service` como *ele* chega ao
`mcp-service`. São duas decisões distintas, cada uma no arquivo do processo que
a toma.

Para subir o orquestrador:

```bash
cp backend/.env.orchestrator.example backend/.env.orchestrator
docker compose --profile orchestrator up
```

> **A regra do Compose que morde:** `environment:` **vence** `env_file:`. No
> `docker-compose.yml` deste projeto sobrou nesse bloco apenas o que o compose
> de fato decide — `RELOAD=false` nos serviços extraídos e os endereços de
> `mysql`, `qdrant`, `redis` e `ollama` no backend. Se você acrescentar ali uma
> variável de aplicação, o `.env` correspondente deixa de valer para ela **sem
> erro nenhum**. Era o caso de `MCP_TRANSPORT` no `tool-service`, que ficava
> preso em `local` por mais que o `.env` dissesse outra coisa.

As portas seguem a mesma lógica dos serviços dedicados: em `"8002:8002"`, o lado
esquerdo é a porta na sua máquina — troque por `MCP_HOST_PORT`, `TOOL_HOST_PORT`
ou `ORCHESTRATOR_HOST_PORT` se ela já estiver ocupada — e o direito é a porta
dentro do container, fixada por `PORT` no arquivo do serviço.

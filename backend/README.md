# Backend — FastAPI

API REST, SSE e WebSocket do Assistente Desktop.

---

## Instalação rápida

```bash
cd backend

# Copiar e configurar variáveis de ambiente
cp .env.example .env
# Editar .env com suas chaves

# Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# Instalar dependências
pip install -r requirements.txt

# Iniciar servidor
python run.py
```


Acesse a documentação OpenAPI em `http://localhost:8000/docs`. Para os
recursos completos, mantenha MySQL, Qdrant e Redis disponíveis; o backend
continua iniciando em modo degradado quando essas dependências opcionais estão
indisponíveis, exceto quando um `DATABASE_SEED` foi solicitado.

---

## Docker

```bash
# Na raiz do projeto
docker compose up -d

# Ver logs
docker compose logs -f backend

# Parar
docker compose down
```

O ambiente Docker sobe cinco serviços: backend, MySQL, Qdrant, Redis e Ollama.
O MySQL guarda configurações, identificação do tutor, aprovações, automações e
auditoria. O Qdrant guarda memórias aprovadas para preferências, comportamento,
instruções e automações. O Redis guarda os contadores do rate limiting por IP
(`fastapi-limiter`); sem ele o backend sobe normalmente, só sem esse limite. A
imagem do Ollama baixa `llama3.2:3b`; mantenha `OLLAMA_MODEL=llama3.2:3b` no
`backend/.env` para usar esse modelo no compose.

---

## Orquestração De Chat

O chat completo via REST (`POST /chat/`) e WebSocket (`type: chat`) usa um
`StateGraph` assíncrono definido em `app/services/chat_graph_service.py`. O
workflow detecta ações locais, resolve atalhos e escolhe entre despacho
`single`, `multi` e `chain`. Os nós chamam a Service Layer existente, mantendo
banco, provedores e execução local fora do grafo. O SSE (`POST /chat/stream`) e
o WebSocket `chat_stream` usam o caminho direto para entregar cada token assim
que ele chega.

As ações detectáveis são `StructuredTool`s do LangChain registradas em
`app/services/assistant_tools.py`: diagnóstico do computador, execução de
script, inspeção de workspace, abertura de projeto e cadastro de atalho. A
seleção dessas tools é determinística e elas apenas produzem propostas tipadas;
não existe um agente executando comandos de forma autônoma no backend. A
interface continua responsável por confirmar e executar qualquer ação local.

Os provedores passam por `ProviderChatModel`, em
`app/services/langchain_agent_service.py`. Esse adaptador converte o histórico
para mensagens LangChain e valida a saída como `StructuredModelResponse` antes
de devolvê-la no contrato público `LLMResponse`.

| Rota do grafo | Comportamento |
|---------------|--------------|
| ação local | Devolve uma proposta `computer_action`, `coding_action`, `launch` ou `register_shortcut` no campo `action` |
| `single` | Usa o provedor solicitado ou escolhe automaticamente um disponível |
| `multi` | Consulta em paralelo todos os provedores disponíveis, ou apenas o solicitado |
| `chain` | Passa a resposta de cada provedor ao próximo para refinamento |

Diagnóstico, script, workspace, projeto e cadastro encerram o grafo com uma
confirmação produzida pelo próprio backend. Um atalho de abertura já cadastrado
mantém a proposta no campo `action` e segue também para o LLM, que formula a
resposta ao usuário.

---

## Provedores Locais De LLM

O backend suporta dois provedores locais independentes:

| ID no chat | Provedor | API de status | API de chat |
|------------|----------|---------------|-------------|
| `llama` | Ollama | `GET /api/tags` | `POST /api/chat` |
| `localai` | LocalAI | `GET /v1/models` | `POST /v1/chat/completions` |

Variáveis reconhecidas:

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL raiz da API Ollama |
| `OLLAMA_MODEL` | `llama3` | Nome exato do modelo Ollama |
| `LOCALAI_BASE_URL` | vazio | URL raiz do LocalAI; habilita o provedor |
| `LOCALAI_MODEL` | vazio | ID do modelo; vazio seleciona o primeiro de `/v1/models` |
| `LOCALAI_API_KEY` | vazio | Chave opcional enviada como Bearer token |

As URLs podem ser informadas com ou sem `http://`. Para hosts internos da
Railway sem porta, o backend usa `11434` para Ollama e `8080` para LocalAI. Uma
URL LocalAI que já termina em `/v1` também é aceita sem duplicar esse prefixo.

As chamadas internas ao LocalAI também consomem a resposta por streaming. Isso
evita que resumos e outros fluxos não incrementais atinjam timeout enquanto um
modelo local mais lento continua gerando tokens; o contrato HTTP desses fluxos
permanece uma resposta única.

Nos resumos de aula, o backend envia `reasoning_effort=none`, limita a saída e
executa um workflow LangGraph com fallback. A ordem automática prioriza LocalAI
e Ollama disponíveis; depois usa no máximo
`EDUCATION_SUMMARY_MAX_PROVIDERS` provedores. Cada tentativa é limitada por
`EDUCATION_SUMMARY_PROVIDER_TIMEOUT_SECONDS`. Defina
`EDUCATION_SUMMARY_ALLOW_PAID_FALLBACK=false` para impedir que o resumo use uma
API paga depois que os provedores locais falharem. A janela configurada em
`LOCAL_LLM_CONTEXT_TOKENS` deve ser igual à `LOCALAI_CONTEXT_SIZE` do serviço.

### Escolha Automática Do Provedor

Quando o cliente não informa `llm` na requisição de chat — o caso normal, já
que a interface só envia esse campo quando o usuário escolhe um provedor
explicitamente — o backend seleciona sozinho entre os provedores disponíveis,
nesta ordem de prioridade:

1. provedores locais/gratuitos (`llama`, `localai`);
2. provedores pagos com crédito confirmado (`balance_ok=true`, hoje só
   `openrouter` e `deepseek` expõem saldo);
3. provedores pagos sem sinal de saldo.

Empates dentro do mesmo nível seguem a ordem de `active_llms`. Provedores sem
crédito ou offline nunca entram na disputa, porque já são excluídos de
`available_llms`. Isso vale para `POST /chat/`, `POST /chat/stream` e o
WebSocket; os modos `multi` e `chain` continuam usando a lista inteira.

Os status de disponibilidade e saldo são cacheados no Redis
(chave `assistant:llm_status`, mesmo TTL do cache em memória: 300s quando há
algum provedor disponível, 30s quando todos falharam). Assim um processo que
sobe do zero aproveita a varredura feita por outro em vez de refazer as dez
verificações — duas delas batem em API de saldo. Sem Redis, cada processo
mantém apenas o cache local, sem erro.

### Railway

No serviço do **backend**, configure:

```dotenv
OLLAMA_BASE_URL=http://${{ollama-7c414367-1ecc-440a-99b9-5125eb1185e9.RAILWAY_PRIVATE_DOMAIN}}:11434
OLLAMA_MODEL=llama3.2:3b

LOCALAI_BASE_URL=http://${{localai.RAILWAY_PRIVATE_DOMAIN}}:8080
LOCALAI_MODEL=minicpm5-1b-claude-opus-fable5-v2-thinking
LOCALAI_API_KEY=
```

Se preferir o hostname direto, o valor abaixo é equivalente:

```dotenv
LOCALAI_BASE_URL=localai.railway.internal
```

No serviço do **LocalAI**, deixe a API acessível a outros containers:

```dotenv
LOCALAI_ADDRESS=:8080
LOCALAI_MODELS_PATH=/models
LOCALAI_BACKENDS_PATH=/models/.backends
LOCALAI_EXTERNAL_BACKENDS=llama-cpp
LOCALAI_CONTEXT_SIZE=8192
LOCALAI_THREADS=4
LOCALAI_AGENT_POOL_DEFAULT_MODEL=minicpm5-1b-claude-opus-fable5-v2-thinking
PRELOAD_MODELS=[{"id":"localai@minicpm5-1b-claude-opus-fable5-v2-thinking"}]
```

Crie um Railway Volume com mount path `/models`. O backend `llama-cpp` fica em
`/models/.backends`, no mesmo volume do GGUF e do YAML. Sem o volume, os
arquivos somem com o container e o preload repete o download em cada deploy.

Não confunda as variáveis dos dois serviços: `LOCALAI_BASE_URL` desta aplicação
deve ser cadastrada no backend. No processo do LocalAI, a variável de bind é
`LOCALAI_ADDRESS`.

O hostname da referência (`localai` no exemplo) deve corresponder ao nome real
do serviço Railway. Os serviços precisam estar no mesmo projeto e ambiente.
Não é necessário criar domínio público para Ollama ou LocalAI.

Referências: [rede privada da Railway](https://docs.railway.com/private-networking)
e [API compatível com OpenAI do LocalAI](https://localai.io/basics/getting_started/index.html).

### Modelo E Diagnóstico

O LocalAI normalmente retorna os modelos em `GET /v1/models`. Em versões que
mantêm o catálogo vazio até a primeira inferência, o health check também
confirma o `LOCALAI_MODEL` por `GET /api/models/config-json/{modelo}`. O log
`Agent pool started (standalone/LocalAGI mode)` informa que o pool iniciou, mas
não garante que um modelo de inferência esteja instalado.

Após o redeploy, consulte:

```bash
curl http://localhost:8000/health
```

Na primeira chamada, `/health` aguarda as verificações dos provedores para não
devolver um estado provisório `checking`. Configure o healthcheck da
infraestrutura em `/health/live`, que responde sem consultar os LLMs.

Em produção, substitua a URL pela URL pública do backend. Confira os campos:

- `active_llms`: provedores configurados;
- `available_llms`: provedores configurados e realmente disponíveis;
- `llm_status.localai.error`: motivo de indisponibilidade do LocalAI;
- `llm_status.llama.error`: motivo de indisponibilidade do Ollama.

Erros comuns:

| Erro | Verificação |
|------|-------------|
| Falha de conexão | Serviço ativo, mesmo ambiente Railway, porta e `LOCALAI_ADDRESS` |
| `Modelo ... não encontrado` | `LOCALAI_MODEL` deve existir em `/v1/models` ou em `/api/models/config-json/{modelo}` |
| `Nenhum modelo disponível` | Instalar/carregar um modelo no LocalAI |
| HTTP 401 | Replicar a chave do LocalAI em `LOCALAI_API_KEY` no backend |
| Ollama offline | Conferir `OLLAMA_BASE_URL`, porta `11434` e `OLLAMA_MODEL` |

### Usuários E Convites Por Email

A primeira conta criada recebe o papel `admin`. Depois disso, um novo
`POST /auth/register` só é aceito com um convite individual emitido pelo admin.
Para proteger por e-mail também a criação da primeira conta, habilite:

```dotenv
REGISTRATION_INVITE_REQUIRED=true
REGISTRATION_ADMIN_EMAIL=admin@example.com
REGISTRATION_TOKEN_EXPIRE_MINUTES=30
REGISTRATION_TOKEN_REQUEST_COOLDOWN_SECONDS=60

SMTP_FROM=assistente@example.com
BREVO_API_KEY=chave-da-api-brevo
```

O envio é feito pela API HTTP transacional do Brevo (`POST
api.brevo.com/v3/smtp/email`), não por SMTP puro: PaaS como o Railway costumam
bloquear saída nas portas SMTP (25/465/587), e a API contorna isso por rodar
sobre HTTPS. `SMTP_FROM` precisa estar validado na conta Brevo (remetente
individual verificado ou domínio autenticado via DNS) — caso contrário a API
aceita o pedido normalmente, mas o envio é rejeitado depois, sem erro visível
na chamada. Para depurar isso sem gastar um envio real, `GET
/auth/smtp-check?secret=<JWT_SECRET>` testa a chave da API Brevo (rota oculta
do `/docs`).

No bootstrap, a interface chama `POST /auth/registration-token` e o token é
enviado exclusivamente para `REGISTRATION_ADMIN_EMAIL`. Depois do login, o
admin usa `POST /auth/invitations` com o e-mail do convidado. O backend gera um
token aleatório de uso único, salva somente seu hash HMAC e envia o valor
original ao destinatário. Um novo pedido para o mesmo e-mail revoga o convite
anterior (mesmo que ainda válido) e emite outro; só é bloqueado dentro da
janela de `REGISTRATION_TOKEN_REQUEST_COOLDOWN_SECONDS` (padrão 60s), como
proteção contra spam. O e-mail administrativo aparece na interface apenas de
forma mascarada.

Cada usuário é vinculado a um perfil `tutor` próprio. Identificadores enviados
pelo cliente não definem propriedade: o backend usa `uid` e `tutor_id`
resolvidos da conta autenticada. Conversas, memórias, automações, atalhos,
scripts, agenda, notificações, scheduler e WebSocket são filtrados por esse
proprietário. Ao iniciar uma base antiga, a migração compatível adiciona as
colunas necessárias e atribui os dados existentes ao primeiro admin.

### Seed de demonstração

Para alimentar uma base nova durante um deploy de teste, configure a seguinte
variável no serviço web:

```env
DATABASE_SEED=demo-v1
```

O backend executa o seed depois de inicializar o banco e grava um marcador na
mesma transação. Reinicializações posteriores detectam esse marcador e não
duplicam os dados. Um valor desconhecido ou uma falha no seed interrompe o
startup para que o deploy não fique disponível com dados incompletos.

O seed não cria credenciais administrativas. Depois do deploy, cadastre
imediatamente o primeiro usuário pela interface e remova `DATABASE_SEED` do
serviço. A remoção não apaga os dados já inseridos.

Para executar ou recriar os dados manualmente:

```bash
python seed_dev.py
python seed_dev.py --reset
```

O `--reset` remove apenas registros identificados pelo seed de demonstração.

### Rate Limiting E Logs De Requisição

As rotas públicas de autenticação (`/auth/login`, `/auth/register`,
`/auth/registration-token`) têm dois limites de requisição por IP empilhados,
via `fastapi-limiter` + Redis:

- geral: 20 requisições/minuto;
- rajada: 5 requisições/10s (janela mais curta, pega picos que o limite geral
  ainda não bloquearia).

`/auth/invitations` (protegida por admin) tem um limite único de 30/min. O IP
usado é o primeiro valor de `X-Forwarded-For` (real atrás do proxy da
Railway), com fallback pro IP do socket. Configure `REDIS_URL` (padrão
`redis://localhost:6379/0`); se o Redis estiver indisponível no startup, o
backend loga um aviso e segue no ar sem aplicar limite algum, em vez de falhar.

Toda requisição HTTP é logada via middleware (IP, método, path, status e
duração), inclusive quando a rota estoura uma exceção não tratada — útil para
depurar 500s em produção sem precisar reproduzir localmente.

---

## Endpoints REST

Salvo quando indicado como público, os endpoints exigem
`Authorization: Bearer <token>`. A especificação completa, com schemas de
entrada e saída, fica disponível em `/docs` e `/openapi.json`.

### Health

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Público: info do servidor |
| GET | `/health` | Público: status completo, incluindo disponibilidade dos LLMs |
| GET | `/health/live` | Liveness público, sem consultar dependências |
| GET | `/system/storage/status` | Status do MySQL e Qdrant |

### Auth

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/auth/status` | Público: consultar o estado do primeiro cadastro |
| POST | `/auth/registration-token` | Público: enviar token único ao e-mail administrativo |
| POST | `/auth/register` | Público: criar o primeiro admin ou uma conta convidada |
| POST | `/auth/login` | Público: autenticar e obter JWT |
| GET | `/auth/me` | Consultar a sessão autenticada |
| PUT | `/auth/password` | Alterar a senha da conta |
| POST | `/auth/invitations` | Admin: enviar convite individual por e-mail |
| GET | `/auth/users` | Admin: listar contas cadastradas |

### Chat

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/chat/` | Conversa completa (single/multi/chain) |
| POST | `/chat/stream` | SSE streaming por tokens |
| GET | `/chat/history/{session_id}` | Histórico de conversa |
| DELETE | `/chat/history/{session_id}` | Limpar histórico |

### Calendário

Nas rotas abreviadas abaixo, `{provider}` representa os endpoints concretos
`google` e `microsoft`.

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/calendar/events` | Listar eventos das contas conectadas |
| POST | `/calendar/events` | Criar evento confirmado em uma conta conectada |
| GET | `/calendar/status` | Consultar credenciais e contas configuradas, sem expor segredos |
| GET | `/calendar/accounts` | Listar contas Google e Microsoft, inclusive conexões pendentes |
| PUT | `/calendar/{provider}/oauth-app` | Salvar as credenciais do aplicativo OAuth |
| GET | `/calendar/{provider}/start` | Criar uma conexão usando as credenciais já salvas |
| POST | `/calendar/{provider}/connect` | Salvar credenciais e iniciar uma conexão |
| POST | `/calendar/{provider}/callback` | Trocar manualmente o código OAuth e persistir a conta |
| GET | `/calendar/{provider}/oauth-callback` | Público: callback aberto pelo navegador |
| GET | `/calendar/{provider}/auth-url` | Obter URL OAuth pelo fluxo de compatibilidade |
| DELETE | `/calendar/{provider}/accounts/{account_id}` | Desconectar uma conta específica |
| DELETE | `/calendar/{provider}/disconnect` | Desconectar todas as contas do provedor |

Perguntas enviadas a `POST /chat/`, como `O que tenho na agenda amanhã?`, são
interpretadas como um plano estruturado `calendar_query`. O backend valida o
período, consulta somente as contas do usuário autenticado e devolve os eventos
como uma resposta comum do chat. A criação usa `calendar_create` e continua
dependendo da confirmação da interface antes do `POST /calendar/events`.

O cadastro dos clientes OAuth, escopos, callbacks locais e Railway e a conexão
das contas estão documentados em
[Configuração de calendários](../docs/CONFIGURACAO_CALENDARIOS.md).

### Notificações

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/notifications/config` | Consultar a configuração do usuário |
| PUT | `/notifications/config` | Persistir configuração de Telegram e WhatsApp |
| POST | `/notifications/send` | Enviar notificação |
| POST | `/notifications/test/telegram` | Testar Telegram |
| POST | `/notifications/test/whatsapp` | Testar WhatsApp |

### Voz

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/voice/transcribe` | Upload de áudio → texto |
| POST | `/voice/tts` | Texto → áudio MP3 |

### Tutor

| Método | Rota | Descrição |
|--------|------|-----------|
| PUT | `/tutor/` | Criar ou atualizar tutor e perfil |
| GET | `/tutor/{tutor_id}` | Obter tutor e perfil |
| PUT | `/tutor/{tutor_id}/settings/{key}` | Criar ou atualizar configuração |
| GET | `/tutor/{tutor_id}/settings` | Listar configurações |

O `tutor_id` efetivo é derivado da conta autenticada. Valores enviados pelo
cliente não permitem acessar dados de outra conta.

### Atalhos E Histórico De Aberturas

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/launcher/suggest-command?name=` | Sugerir o executável de um aplicativo |
| POST | `/launcher/shortcuts` | Criar atalho de aplicativo, URL ou comando |
| GET | `/launcher/shortcuts?tutor_id=` | Listar atalhos da conta autenticada |
| PATCH | `/launcher/shortcuts/{shortcut_id}` | Atualizar atalho |
| DELETE | `/launcher/shortcuts/{shortcut_id}` | Excluir atalho |
| POST | `/launcher/shortcuts/{shortcut_id}/launched` | Registrar o resultado de uma tentativa de abertura |
| GET | `/launcher/launches?tutor_id=` | Consultar histórico de aberturas |

### Computador, Scripts E Contexto Do Desktop

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/computer/actions` | Listar ações locais reconhecidas |
| POST | `/computer/actions/{action_id}/run` | Contrato reservado; responde `501`, pois a execução pertence à interface |
| GET | `/computer/scripts/shells` | Listar shells reconhecidos |
| GET/POST | `/computer/scripts` | Listar ou cadastrar snippets da conta |
| PATCH/DELETE | `/computer/scripts/{script_id}` | Atualizar ou excluir um snippet |
| POST | `/computer/scripts/run` | Contrato reservado; responde `501`, pois a execução pertence à interface |
| GET | `/desktop/windows` | Listar janelas visíveis no host do backend |
| GET | `/desktop/windows/{window_id}/context` | Extrair contexto textual de uma janela |

As rotas `/computer` e `/desktop` aceitam somente clientes locais. Mesmo nesse
caso, o backend não executa scripts nem ações: a interface desktop aplica as
confirmações, limites e bloqueios de risco e devolve apenas o resultado para
análise.

### Memória

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/memory/review` | Propor memória para aprovação |
| GET | `/memory/review?tutor_id=&status=` | Listar memórias por status |
| POST | `/memory/review/{id}/approve` | Aprovar e salvar no Qdrant |
| POST | `/memory/review/{id}/reject` | Rejeitar memória |
| POST | `/memory/review/{id}/voice-decision` | Aprovar ou rejeitar pela transcrição de voz |
| GET | `/memory/search?tutor_id=&q=` | Buscar memórias aprovadas |

### Automações

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/automations/` | Aprovar automação |
| GET | `/automations/?tutor_id=` | Listar automações aprovadas |
| PATCH | `/automations/{automation_id}` | Atualizar agenda/status |
| POST | `/automations/audit` | Registrar ação executada |
| GET | `/automations/audit?tutor_id=` | Consultar auditoria |

---

## WebSocket

Conecte em
`ws://localhost:8000/ws/{session_id}?token=<JWT_URL_ENCODED>`. Em produção,
use `wss://` quando o backend estiver publicado com HTTPS. O servidor valida o
JWT antes de aceitar a conexão e fecha com o código `4401` quando o token é
inválido ou está ausente.

### Mensagens enviadas pelo cliente

```jsonc
// Conversa completa
{ "type": "chat", "payload": { "message": "Olá", "mode": "single", "llm": "claude", "history": [] } }

// Conversa com streaming (também aceita "llama" e "localai")
{ "type": "chat_stream", "payload": { "message": "Olá", "llm": "localai" } }

// Transcrever áudio (base64)
{ "type": "voice_transcribe", "payload": { "audio_b64": "...", "language": "pt" } }

// TTS — gerar áudio
{ "type": "tts", "payload": { "text": "Olá mundo", "language": "pt-BR" } }

// Sincronizar calendários conectados no banco
{ "type": "calendar_sync", "payload": {} }

// Enviar notificação
{ "type": "notify", "payload": { "message": "teste", "channels": ["telegram"] } }

// Ping
{ "type": "ping" }
```

### Mensagens recebidas pelo servidor

```jsonc
// Conexão estabelecida
{ "type": "status", "payload": { "connected": true, "active_llms": ["claude", "gpt"] } }

// Provedores que serão consultados
{ "type": "thinking", "payload": { "llms": ["claude"] } }

// Resposta de chat
{ "type": "chat_response", "payload": { "mode": "single", "responses": [{ "llm": "claude", "content": "...", "duration_ms": 1200 }], "action": null } }

// Chunk de streaming
{ "type": "stream_chunk", "payload": { "chunk": "Olá", "llm": "claude", "done": false } }
{ "type": "stream_end",   "payload": { "llm": "claude", "full_response": "...", "done": true } }

// Transcrição de voz
{ "type": "transcription", "payload": { "transcript": "texto falado", "confidence": 0.98 } }

// Áudio TTS
{ "type": "tts_audio", "payload": { "audio_b64": "...", "format": "mp3" } }

// Eventos de calendário
{ "type": "calendar_events", "payload": { "events": [...], "total": 5 } }

// Lembrete automático (enviado pelo scheduler)
{ "type": "event_reminder", "payload": { "title": "Reunião", "minutes_left": 15 } }

// Resultado de notificação
{ "type": "notify_result", "payload": { "telegram_ok": true, "whatsapp_ok": false } }

// Erro
{ "type": "error", "payload": { "detail": "mensagem de erro" } }
```

---

## Estrutura

```text
backend/
├── app/
│   ├── main.py              # FastAPI app + lifespan
│   ├── core/
│   │   ├── config.py        # Pydantic settings (.env)
│   │   ├── database.py      # SQLAlchemy async + modelos
│   │   ├── security.py      # JWT + bcrypt
│   │   ├── net.py           # IP real do cliente (X-Forwarded-For)
│   │   └── rate_limit.py    # dependência de rate limit por IP (Redis)
│   ├── models/
│   │   └── schemas.py       # Pydantic schemas (request/response)
│   ├── services/
│   │   ├── assistant_tools.py  # tools tipadas do LangChain
│   │   ├── chat_graph_service.py  # workflow LangGraph do chat
│   │   ├── langchain_agent_service.py  # modelos e respostas estruturadas
│   │   ├── llm_service.py   # chamadas e streaming dos provedores de LLM
│   │   ├── llm_status_service.py  # disponibilidade e modelos dos LLMs
│   │   ├── calendar_service.py  # Google + Microsoft OAuth
│   │   ├── notification_service.py  # Telegram + WhatsApp
│   │   └── voice_service.py  # transcrição + síntese de voz
│   ├── routers/
│   │   ├── chat.py          # REST chat + SSE stream
│   │   ├── computer.py      # catálogo de ações e snippets locais
│   │   ├── desktop.py       # contexto de janelas do host local
│   │   ├── launcher.py      # atalhos e auditoria de aberturas
│   │   ├── memory.py        # revisão e busca de memórias
│   │   ├── automations.py   # automações aprovadas e auditoria
│   │   ├── websocket.py     # WebSocket hub
│   │   └── routes.py        # auth, calendário, notificações, voz e health
│   └── utils/
│       └── scheduler.py     # APScheduler (calendar polling)
├── tests/                   # testes unitários e de contratos
├── run.py                   # Entry point
├── seed_dev.py              # seed de demonstração manual
├── requirements.txt
├── Dockerfile
└── .env.example
```

## Testes

A partir de `backend/`, com o ambiente virtual ativado:

```bash
python -m pytest tests
```

Os testes isolam os provedores externos com mocks. Alguns testes de integração
inicializam os contratos da aplicação, mas não exigem credenciais reais de LLM.

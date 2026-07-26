
# Backend — FastAPI

API REST + WebSocket — Aplicativo de assistente pessoal.

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


Acesse: http://localhost:8000/docs

---

## Docker

```bash
# Na raiz do projeto
docker-compose up -d

# Ver logs
docker-compose logs -f backend

# Parar
docker-compose down
```

O ambiente Docker sobe quatro serviços: backend, MySQL, Qdrant e Ollama. O
MySQL guarda configurações, identificação do tutor, aprovações, automações e
auditoria. O Qdrant guarda memórias aprovadas para preferências, comportamento,
instruções e automações. A imagem do Ollama baixa `llama3.2:3b`; mantenha
`OLLAMA_MODEL=llama3.2:3b` no `backend/.env` para usar esse modelo no compose.

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
LOCALAI_CONTEXT_SIZE=2048
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

### Cadastro Administrativo Por Email

Por padrão, o backend mantém o comportamento legado: somente a primeira conta
pode ser criada e qualquer segundo `POST /auth/register` é bloqueado. Para
proteger também a criação dessa primeira conta, habilite o convite
administrativo:

```dotenv
REGISTRATION_INVITE_REQUIRED=true
REGISTRATION_ADMIN_EMAIL=admin@example.com
REGISTRATION_TOKEN_EXPIRE_MINUTES=30
REGISTRATION_TOKEN_REQUEST_COOLDOWN_SECONDS=60

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=usuario-smtp
SMTP_PASSWORD=senha-smtp
SMTP_FROM=assistente@example.com
SMTP_STARTTLS=true
SMTP_USE_SSL=false
```

A interface chama `POST /auth/registration-token`. O backend gera um token
aleatório de uso único, salva somente seu hash HMAC, envia o valor original
exclusivamente para `REGISTRATION_ADMIN_EMAIL` e exige o token em
`POST /auth/register`. Enquanto um token válido estiver ativo, novas
solicitações são recusadas para evitar spam e substituição do convite.

Para SMTP com SSL direto, normalmente na porta `465`, use
`SMTP_USE_SSL=true` e `SMTP_STARTTLS=false`. O e-mail administrativo aparece
na interface apenas de forma mascarada.

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

---

## Endpoints REST

### Health
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Info do servidor |
| GET | `/health` | Status completo, incluindo disponibilidade dos LLMs |
| GET | `/health/live` | Liveness check sem consultar dependências |
| GET | `/system/storage/status` | Status do MySQL e Qdrant |

### Auth
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/auth/status` | Estado do primeiro cadastro e entrega do convite |
| POST | `/auth/registration-token` | Enviar token único ao e-mail administrativo |
| POST | `/auth/register` | Criar a primeira conta administrativa |
| POST | `/auth/login` | Autenticar e obter JWT |
| GET | `/auth/me` | Consultar a sessão autenticada |
| PUT | `/auth/password` | Alterar a senha da conta |

### Chat
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/chat/` | Conversa completa (single/multi/chain) |
| POST | `/chat/stream` | SSE streaming por tokens |
| GET | `/chat/history/{session_id}` | Histórico de conversa |
| DELETE | `/chat/history/{session_id}` | Limpar histórico |

### Calendar
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/calendar/events` | Eventos dos próximos 7 dias |
| GET | `/calendar/google/auth-url` | URL OAuth Google |
| POST | `/calendar/google/exchange?code=` | Trocar código por refresh token |
| GET | `/calendar/microsoft/auth-url` | URL OAuth Microsoft |
| POST | `/calendar/microsoft/exchange?code=` | Trocar código Microsoft |

### Notifications
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/notifications/send` | Enviar notificação |
| POST | `/notifications/test/telegram` | Testar Telegram |
| POST | `/notifications/test/whatsapp` | Testar WhatsApp |

### Voice
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

Conecte em: `ws://localhost:8000/ws/{session_id}`

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

// Resposta de chat
{ "type": "chat_response", "payload": { "mode": "single", "responses": [{ "llm": "claude", "content": "...", "duration_ms": 1200 }] } }

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

```
backend/
├── app/
│   ├── main.py              # FastAPI app + lifespan
│   ├── core/
│   │   ├── config.py        # Pydantic settings (.env)
│   │   ├── database.py      # SQLAlchemy async + modelos
│   │   └── security.py      # JWT + bcrypt
│   ├── models/
│   │   └── schemas.py       # Pydantic schemas (request/response)
│   ├── services/
│   │   ├── llm_service.py   # chamadas e streaming dos provedores de LLM
│   │   ├── llm_status_service.py  # disponibilidade e modelos dos LLMs
│   │   ├── calendar_service.py  # Google + Microsoft OAuth
│   │   ├── notification_service.py  # Telegram + WhatsApp
│   │   └── voice_service.py  # transcrição + síntese de voz
│   ├── routers/
│   │   ├── chat.py          # REST chat + SSE stream
│   │   ├── websocket.py     # WebSocket hub
│   │   └── routes.py        # auth, calendar, notif, voice, health
│   └── utils/
│       └── scheduler.py     # APScheduler (calendar polling)
├── run.py                   # Entry point
├── requirements.txt
├── Dockerfile
└── .env.example
```

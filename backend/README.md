
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

O ambiente Docker sobe três serviços: backend, MySQL e Qdrant. O MySQL guarda
configurações, identificação do tutor, aprovações, automações e auditoria. O
Qdrant guarda memórias aprovadas para preferências, comportamento, instruções e
automações.

---

## Endpoints REST

### Health
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Info do servidor |
| GET | `/health` | Status |
| GET | `/system/storage/status` | Status do MySQL e Qdrant |

### Auth
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/auth/setup` | Configurar PIN/voz/face |
| POST | `/auth/verify` | Autenticar e obter JWT |

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

// Conversa com streaming
{ "type": "chat_stream", "payload": { "message": "Olá", "llm": "gpt" } }

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
│   │   ├── llm_service.py   # motores de resposta
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

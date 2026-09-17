# Infraestrutura

Esta e a unica secao da referencia escrita a mao: docker-compose, Dockerfile e
scripts nao tem docstring para extrair. Quando um servico, porta ou variavel
mudar, edite `docs/referencia/infra.md` junto com o arquivo alterado.

## Servicos do compose

`docker-compose.yml` sobe cinco containers por padrao. O backend depende dos
quatro outros e so inicia quando MySQL e Redis passam no healthcheck. Os servicos
extraidos ficam atras de perfis.

| Servico | Imagem | Porta(s) | Volume | Papel |
| --- | --- | --- | --- | --- |
| `mysql` | `mysql:8.4` | 3306 | `assistant_mysql` | Banco relacional (usuarios, aulas, presenca, quizzes, config). |
| `qdrant` | `qdrant/qdrant:v1.12.6` | 6333, 6334 | `assistant_qdrant` | Banco vetorial da memoria e do indice de aulas. |
| `redis` | `redis:7-alpine` | 6379 | `assistant_redis` | Rate limiting por IP (`fastapi-limiter`). Opcional em runtime. |
| `ollama` | build de `ollama/` | 11434 | `assistant_ollama` | LLM local. Reserva todas as GPUs NVIDIA disponiveis. |
| `backend` | build de `backend/` | 8000 | `assistant_data`, `assistant_logs` | FastAPI. Monta `./backend` como bind mount. |
| `mcp-service` | `Dockerfile.mcp-service` | 8002 | — | Perfis `services`, `mcp`. Le `backend/.env.mcp-service`. |
| `tool-service` | `Dockerfile.tool-service` | 8003 | — | Perfis `services`, `tools`. Le `backend/.env.tool-service`. |
| `agent-orchestrator` | `Dockerfile` | 8001 | — | Perfis `services`, `orchestrator`. Le `backend/.env.orchestrator`. |
| `otel-collector` | `otel/opentelemetry-collector-contrib` | 8004, 4317 | — | Perfil `observability`. |

O container `ollama` e uma imagem propria justamente para ja trazer o modelo:
o `Dockerfile` em `ollama/` sobe o servidor durante o build, espera o
`ollama list` responder e faz `ollama pull llama3.2:3b`. Sem isso a primeira
conversa apos cada deploy pagaria o download do modelo.

O `backend` recebe do compose os enderecos internos da rede
(`mysql:3306`, `http://qdrant:6333`, `http://ollama:11434`, `redis://redis:6379/0`)
e sobrescreve o que estiver em `backend/.env` — esse arquivo entra como
`env_file` opcional (`required: false`), entao o compose sobe mesmo sem ele.

```bash
docker compose up -d                       # backend + infraestrutura
docker compose --profile services up -d    # + mcp, tool e orquestrador
docker compose logs -f backend
docker compose down                        # preserva os volumes
```

## Imagem do backend

`backend/Dockerfile` e multi-stage sobre `python:3.14-slim`:

1. **builder** — cria um venv em `/opt/venv` e instala `requirements.txt` com
   `--only-binary=:all:`. A restricao a wheels e proposital: garante que o build
   falhe cedo em vez de tentar compilar dependencia pesada dentro da imagem.
2. **runtime** — copia so o venv pronto, instala `ffmpeg` (processamento de audio
   do modo educacao) e `curl` (healthcheck), cria o usuario nao-root `app`
   (uid 10001) e roda `python run.py`.

`run.py` e o entrypoint: le `app.core.config.get_settings()` e chama o uvicorn
sobre `app.main:app`, com ping de WebSocket a cada 30s.

O healthcheck do compose bate em `/health/live` a cada 30s.

### Imagens por servico

| Dockerfile | Requisitos | Copia | CMD |
| --- | --- | --- | --- |
| `Dockerfile` | `requirements.txt` | tudo | `python run.py` (o orquestrador troca por `python -m services.orchestrator.main`) |
| `Dockerfile.tool-service` | `requirements-tool-service.txt` | `shared/`, `app/`, `services/` | `python -m services.tool_service.main` |
| `Dockerfile.mcp-service` | `requirements-mcp-service.txt` | `shared/`, `services/` | `python -m services.mcp_service.main` |

As imagens enxutas nao levam faster-whisper nem os wheels de CUDA (~2,1 GB). A do
mcp-service nao copia `app/`, e a do tool-service nao instala pacote de banco nem
de JWT; `backend/tests/test_import_boundaries.py` reprova o import que quebraria
essas imagens.

## Setup da interface

`setup.sh` (bash) e `setup.bat` (Windows) fazem o mesmo caminho para o Flutter:
verificam se o `flutter` esta no PATH, habilitam o target desktop, rodam
`flutter pub get` e sobem o app com `flutter run -d <plataforma>`. O `setup.sh`
detecta a plataforma via `uname` e ainda tenta instalar o Flutter por snap no
Linux quando ele nao existe.

Os scripts nao sobem o backend — a interface espera encontrar o FastAPI ja
rodando em `localhost:8000`.

## Variaveis de ambiente

`backend/.env.example` documenta apenas o que continua vindo do ambiente (os
servicos extraidos tem `.env.<servico>.example` proprios; blocos para a Railway em
[Deploy na Railway](../arquitetura/deploy-railway.md)). A regra
do projeto e: **configuracao de usuario mora no banco**, ambiente guarda
infraestrutura e segredo de aplicacao. Os grupos:

| Grupo | Variaveis principais | Observacao |
| --- | --- | --- |
| Servidor | `HOST`, `PORT`, `RELOAD`, `LOG_LEVEL`, `CORS_ORIGINS`, `SECRET_KEY` | Lidas por `run.py` e `app.core.config`. |
| Autenticacao | `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`, `CREDENTIAL_ENCRYPTION_KEY` | `CREDENTIAL_ENCRYPTION_KEY` cifra refresh token OAuth em repouso — rotacionar exige reconectar as contas ja salvas. |
| Cadastro e recuperacao | `REGISTRATION_INVITE_REQUIRED`, `REGISTRATION_ADMIN_EMAIL`, `PASSWORD_RESET_*`, `SMTP_FROM`, `BREVO_API_KEY` | Entrega de token por HTTP API da Brevo, nao SMTP (PaaS costuma bloquear porta SMTP). |
| Microsoft OAuth | `MICROSOFT_OAUTH_CLIENT_ID`, `_SECRET`, `_TENANT_ID` | Um App Registration multitenant do deploy, nao um por organizacao de usuario. |
| Persistencia | `DATABASE_URL`, `DATABASE_SEED`, `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX`, `QDRANT_VECTOR_SIZE`, `REDIS_URL` | Redis inalcancavel nao impede o boot: o rate limiting simplesmente e pulado. |
| LLM local | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `LOCALAI_*`, `LOCAL_LLM_CONTEXT_TOKENS` | Modelos por usuario ficam no banco; aqui so o endereco da infra. |
| Embeddings | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL`, `EMBEDDING_LOCAL_MODEL`, `EMBEDDING_CACHE_DIR`, `EMBEDDING_DIMENSIONS` | Em `auto` a ordem e endpoint proprio, LocalAI, Ollama, modelo local em processo, OpenAI e hash offline. |
| Agentes e MCP | `MCP_SERVERS`, `AGENT_MAX_TOOL_ITERATIONS`, `AGENT_MAX_HANDOFFS` | `MCP_SERVERS` e um JSON; `command` vira stdio e `url` vira streamable_http. |
| Servicos | `ORCHESTRATOR_TRANSPORT`, `ORCHESTRATOR_URL`, `TOOL_TRANSPORT`, `TOOL_SERVICE_URL`, `MCP_TRANSPORT`, `MCP_SERVICE_URL`, `INTERNAL_SERVICE_TOKEN`, `ASSISTANT_API_URL` | `local` roda in-process; `remote` usa o servico. O token e obrigatorio com orquestrador remoto; `ASSISTANT_API_URL` so e lida pelo orquestrador. |
| Proxy | `FORWARDED_ALLOW_IPS` | Lida pelo uvicorn. `*` em PaaS, senao o redirect do OAuth sai em `http://`. |
| OCR | `OCR_ENABLED`, `OCR_MAX_PAGES`, `OCR_DPI`, `OCR_MIN_SCORE` | OCR local do material didatico. |
| Modo educacao | `EDUCATION_SEGMENT_SECONDS`, `EDUCATION_SUMMARY_MAX_CHARS`, `EDUCATION_SUMMARY_PROVIDER_TIMEOUT_SECONDS`, `EDUCATION_SUMMARY_MAX_PROVIDERS`, `EDUCATION_SUMMARY_ALLOW_PAID_FALLBACK` | Controlam o fatiamento do audio e o fallback entre provedores no resumo. |
| Voz | `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `WHISPER_VAD_*`, `STT_PROVIDER`, `TTS_PROVIDER`, `OPENAI_TTS_*` | `cuda`/`float16` exige `nvidia-cublas-cu12` e `nvidia-cudnn-cu12`; sem GPU, volte para `cpu`/`int8`. |

## Outros arquivos do backend

| Caminho | Conteudo |
| --- | --- |
| `backend/run.py` | Entrypoint do uvicorn. |
| `backend/seed_dev.py` | Popula dados de desenvolvimento. |
| `backend/sql/shortcut_launch_logs.sql` | DDL auxiliar do log de atalhos. |
| `backend/static/` | `quiz_player.html` e `quiz_dashboard.html`, as paginas servidas ao aluno e ao professor durante o quiz. |
| `backend/data/`, `backend/logs/` | Dados e log locais (volumes no compose). |
| `backend/requirements-docs.txt` | Toolchain desta documentacao. |

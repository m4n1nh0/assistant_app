# Assistente Desktop 

Aplicacao de assistente pessoal desktop com backend FastAPI, interface Flutter,
memoria vetorial, automacoes locais, integracao com calendarios, voz,
notificacoes e multiplos provedores de LLM.

O projeto foi pensado para rodar localmente, com dados e credenciais sensiveis
fora do repositorio. O arquivo `backend/.env.example` documenta apenas as
variaveis de infraestrutura e provedores que continuam vindo do ambiente. As
configuracoes de notificacao e calendario sao persistidas no banco pela propria
aplicacao.

## Arquitetura

O projeto e dividido em duas aplicacoes principais: uma interface desktop em
Flutter e um backend local em FastAPI. O backend concentra regras de negocio,
persistencia, integracoes externas e comunicacao com provedores de LLM. A
interface fica responsavel pela experiencia desktop, estado visual, captura de
contexto local e comunicacao com a API.

```text
assistant_app/
|-- backend/                 FastAPI + Python
|   |-- app/
|   |   |-- core/            configuracao, banco e seguranca
|   |   |-- models/          schemas Pydantic e contratos de API
|   |   |-- routers/         endpoints REST, SSE e WebSocket
|   |   |-- services/        regras de negocio e integracoes externas
|   |   `-- utils/           scheduler e utilitarios
|   |-- tests/               testes unitarios do backend
|   |-- Dockerfile
|   `-- requirements.txt
|
|-- interface/               Flutter Desktop + Dart
|   |-- lib/
|   |   |-- models/          modelos de estado e DTOs
|   |   |-- providers/       estado global via Riverpod
|   |   |-- screens/         telas principais
|   |   |-- services/        clientes HTTP/WebSocket e servicos locais
|   |   |-- utils/           tema e helpers
|   |   `-- widgets/         componentes reutilizaveis
|   `-- test/                testes da interface
|
|-- ollama/                  imagem auxiliar para modelo local
|-- docker-compose.yml       MySQL, Qdrant, Ollama e backend
|-- setup.bat
`-- setup.sh
```

### Diagrama De Componentes

```mermaid
flowchart LR
    User[Usuario] --> UI[Interface Flutter Desktop]

    UI --> State[Riverpod Providers]
    UI --> LocalServices[Servicos locais do desktop]
    UI --> ApiClient[ApiService HTTP / SSE / WebSocket]

    ApiClient --> FastAPI[Backend FastAPI]

    FastAPI --> Routers[Routers REST / SSE / WebSocket]
    Routers --> Services[Service Layer]
    Services --> Models[Schemas Pydantic]
    Services --> DB[(MySQL)]
    Services --> Vector[(Qdrant)]
    Services --> Scheduler[APScheduler]
    Services --> LLMs[LLMs em nuvem]
    Services --> Ollama[Ollama local]
    Services --> Calendar[Google / Microsoft Calendar]
    Services --> Notify[Telegram / WhatsApp]
    Services --> Voice[STT / TTS]

    Scheduler --> Calendar
    Scheduler --> Notify
```

### Componentes

- **Interface desktop**: Flutter para Windows, macOS e Linux. Cuida de chat,
  configuracao inicial, captura de contexto local, atalhos, voz e preferencias.
- **Backend API**: FastAPI com REST, SSE e WebSocket para chat, historico,
  agenda, notificacoes, automacoes, memoria e acoes locais.
- **Banco relacional**: MySQL via SQLAlchemy async para conversas,
  configuracoes, perfis, atalhos, auditoria e automacoes aprovadas.
- **Memoria vetorial**: Qdrant para memorias revisadas e aprovadas.
- **LLMs**: provedores em nuvem configurados por `.env` e modelo local via
  Ollama.
- **Scheduler**: APScheduler para sincronizacao periodica de calendario e envio
  de lembretes.

## Diagrama De Fluxo Da Aplicacao

Fluxo principal de uma interacao de chat:

```mermaid
sequenceDiagram
    actor U as Usuario
    participant UI as Flutter Desktop
    participant API as FastAPI Backend
    participant SVC as Services
    participant DB as MySQL
    participant MEM as Qdrant
    participant LLM as Provedor LLM/Ollama

    U->>UI: Envia mensagem ou comando por voz
    UI->>API: POST /chat ou WebSocket /ws
    API->>SVC: Monta contexto e identifica a acao

    alt Pedido comum de conversa
        SVC->>MEM: Busca memorias aprovadas quando aplicavel
        SVC->>LLM: Envia prompt, historico e contexto
        LLM-->>SVC: Retorna resposta
    else Pedido de acao local
        SVC-->>UI: Retorna action para confirmacao
        UI->>UI: Executa acao local autorizada
        UI->>API: Envia resultado coletado
        API->>LLM: Solicita analise com contexto real
    else Pedido de agenda/notificacao
        SVC->>DB: Le configuracoes e contas conectadas
        SVC->>SVC: Sincroniza agenda ou envia notificacao
    end

    SVC->>DB: Persiste conversa, auditoria ou configuracao
    API-->>UI: Resposta, stream ou resultado da acao
    UI-->>U: Exibe resposta e atualiza estado
```

Fluxo de configuracao e persistencia:

```mermaid
flowchart TD
    Config[Tela de configuracao] --> LocalStore[Storage local da interface]
    Config --> BackendConfig[Endpoints de configuracao]

    BackendConfig --> ConfigTable[(Tabela config)]
    BackendConfig --> TutorTables[(Tutors / Profiles / Settings)]
    BackendConfig --> CalendarAccounts[(Contas de calendario)]

    Env[backend/.env local] --> Runtime[Settings de infraestrutura]
    Runtime --> Backend[Backend FastAPI]
    ConfigTable --> Backend
    CalendarAccounts --> Backend
```

## Padrao De Projeto

O projeto usa principalmente **arquitetura em camadas** com **Service Layer**.
O objetivo e manter transporte, regra de negocio, persistencia e UI separados.

### Backend

No backend, o padrao principal e:

- `routers`: camada de transporte. Recebe requests, valida entrada e devolve
  responses. Nao deve concentrar regra de negocio pesada.
- `services`: regras de negocio, integracoes externas e orquestracao.
- `models`: contratos Pydantic usados pela API e pela aplicacao.
- `core`: infraestrutura compartilhada, como configuracao, banco e seguranca.
- `utils`: processos auxiliares, como scheduler.

Na pratica, isso cria este fluxo:

```text
Request -> Router -> Service -> Database/Provider -> Service -> Response
```

Padroes usados no backend:

- **Service Layer**: `app/services` concentra integracoes com LLMs, calendario,
  notificacoes, voz, Qdrant e runtime config.
- **DTO / Schema Objects**: `app/models/schemas.py` define contratos de entrada
  e saida com Pydantic.
- **Dependency Injection simples**: FastAPI injeta sessoes de banco e
  autenticacao via `Depends`.
- **Repository leve via SQLAlchemy**: os modelos em `core/database.py` sao
  acessados pelos routers/services com sessoes async.
- **Configuration Object**: `core/config.py` centraliza settings vindos do
  ambiente.

### Interface

A interface segue separacao semelhante:

- `screens`: composicao de telas e fluxos principais.
- `widgets`: componentes visuais reutilizaveis.
- `services`: acesso ao backend, armazenamento local e integracoes do desktop.
- `providers`: estado global da aplicacao.
- `models`: configuracoes e estruturas de dados usadas pela UI.

Padroes usados na interface:

- **Provider/State Management**: Riverpod centraliza estado compartilhado.
- **Service Client**: `ApiService` encapsula HTTP, SSE e WebSocket.
- **Local Services**: servicos especificos isolam automacao local, workspace,
  scripts e contexto de janelas.
- **Component Composition**: telas sao compostas por widgets menores e
  reutilizaveis.

Esse desenho evita colocar regra de negocio nos endpoints ou nos widgets,
mantendo integracoes e fluxos testaveis em servicos dedicados.

## Configuracao Segura

Arquivos reais de ambiente e dados locais nao devem ser publicados:

- `backend/.env`
- `.env` e `.env.*`
- `backend/logs/`
- `backend/data/`
- `.venv/`
- `interface/build/`
- `interface/windows/flutter/ephemeral/`

Esses caminhos ja estao cobertos por `.gitignore` e `.dockerignore`.

Antes de publicar, crie o ambiente a partir do exemplo:

```bash
cd backend
cp .env.example .env
```

Preencha apenas o que for necessario para rodar localmente. Credenciais de
notificacao e OAuth de calendario devem ser configuradas pela tela da aplicacao,
pois sao salvas no banco.

## Execucao Local

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

API local: `http://localhost:8000/docs`

### Interface

```bash
cd interface
flutter pub get
flutter run -d windows
```

Para macOS ou Linux, troque o device para `macos` ou `linux`.

### Docker

Na raiz do projeto:

```bash
docker-compose up -d
```

O compose sobe MySQL, Qdrant, Ollama e backend. A interface Flutter continua
sendo executada localmente.

## Testes E Qualidade

Backend:

```bash
.\.venv\Scripts\python.exe -m pytest backend\tests
```

Interface:

```bash
cd interface
flutter analyze
flutter test
```

## Licenca

Este projeto e disponibilizado sob uma licenca de uso nao comercial. Uso,
copia, modificacao e distribuicao sao permitidos apenas para fins pessoais,
educacionais, de pesquisa ou internos sem finalidade comercial.

Uso comercial exige permissao previa por escrito. Consulte [LICENSE](LICENSE).

## Documentacao Complementar

- `backend/README.md`: endpoints, WebSocket e detalhes do servidor.
- `interface/README.md`: execucao e estrutura da aplicacao Flutter.

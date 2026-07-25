# Interface Desktop

Aplicacao Flutter Desktop do Assistente. Esta camada cuida da janela principal,
configuracao inicial, conversa, autenticacao local, atalhos, notificacoes e
visualizacao de agenda.

## Requisitos

- Flutter com suporte a desktop habilitado
- Dart SDK incluido na instalacao do Flutter
- Backend em execucao, por padrao em `http://localhost:8000`

Para habilitar desktop:

```bash
flutter config --enable-windows-desktop
flutter config --enable-macos-desktop
flutter config --enable-linux-desktop
```

## Instalar Dependencias

```bash
cd interface
flutter pub get
```

## Executar

Windows:

```bash
flutter run -d windows
```

macOS:

```bash
flutter run -d macos
```

Linux:

```bash
flutter run -d linux
```

## Backend

A interface usa `localhost:8000` por padrao. Para apontar para outro host ou
porta, use `--dart-define`:

```bash
flutter run -d windows --dart-define=APP_BACKEND_HOST=127.0.0.1 --dart-define=APP_BACKEND_PORT=8000
```

Antes de abrir a interface, suba o backend na raiz do projeto:

```bash
cd ../backend
python run.py
```

Ou, pela raiz do projeto:

```bash
docker-compose up -d
```

## Provedores De IA

A interface não se conecta diretamente ao Ollama ou ao LocalAI. Ela consulta
`GET /health` no backend e usa os campos `active_llms`, `available_llms`,
`llm_labels` e `llm_status` para montar a lista de provedores disponíveis.

O backend reconhece estes IDs locais:

| ID | Nome exibido | Configuração feita em |
|----|--------------|-----------------------|
| `llama` | Ollama | Variáveis `OLLAMA_*` do backend |
| `localai` | LocalAI | Variáveis `LOCALAI_*` do backend |

O status é atualizado periodicamente pela interface. Um provedor pode estar
configurado (`active_llms`) e ainda aparecer offline quando não estiver em
`available_llms`. Nesse caso, o detalhe retornado em `llm_status` é exibido
para ajudar no diagnóstico.

Em um deploy Railway, somente o backend acessa endereços como
`localai.railway.internal`. Nunca use esse endereço como
`APP_BACKEND_HOST`: a interface desktop deve apontar para um endpoint acessível
do backend e não consegue resolver diretamente o domínio privado da Railway.
O cliente atual monta esse endpoint como `http://<host>:<porta>`.
Consulte o [README do backend](../backend/README.md#railway) para as variáveis
completas.

## Primeira Configuracao

Na primeira abertura, o app exibe a tela de configuracao. Nela voce define:

- Nome do assistente, seu nome e perfil de atendimento
- Senha de acesso
- Canais e preferências de notificação
- Credenciais OAuth e contas de agenda
- Preferências de voz, inicialização e comportamento da interface

As credenciais e URLs dos provedores de LLM são configurações de
infraestrutura do backend e devem ser fornecidas por variáveis de ambiente.

## Estrutura

```text
interface/
├── assets/
│   ├── fonts/
│   └── icons/
├── lib/
│   ├── main.dart
│   ├── models/
│   │   ├── app_config.dart
│   │   └── hive_adapters.dart
│   ├── providers/
│   │   └── app_provider.dart
│   ├── screens/
│   │   ├── splash_screen.dart
│   │   ├── config_screen.dart
│   │   └── main_screen.dart
│   ├── services/
│   │   ├── api_service.dart
│   │   └── storage_service.dart
│   ├── utils/
│   │   └── theme.dart
│   └── widgets/
│       ├── auth_dialog.dart
│       ├── chat_panel.dart
│       ├── left_panel.dart
│       ├── right_panel.dart
│       └── title_bar.dart
└── pubspec.yaml
```

## Verificacao

```bash
dart format lib
flutter analyze
flutter test
```

## Problemas Comuns

Se `flutter` ou `dart` nao forem reconhecidos, confira se a pasta `bin` do
Flutter esta no `PATH`.

Se a interface abrir mas nao responder, confirme se o backend esta ativo em
`http://localhost:8000/health`. Se o backend estiver online mas nenhum LLM
aparecer disponível, confira `available_llms` e `llm_status` na resposta desse
endpoint.

Se o LocalAI aparecer como configurado, mas offline:

- confira `llm_status.localai.error`;
- verifique se `/v1/models` do LocalAI retorna pelo menos um modelo;
- confirme que `LOCALAI_BASE_URL` foi definida no backend, e não na interface;
- na Railway, confirme que backend e LocalAI estão no mesmo projeto e ambiente.

Se uma plataforma desktop nao aparecer em `flutter devices`, habilite o suporte
correspondente com `flutter config`.

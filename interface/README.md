# Interface Desktop

Aplicação Flutter Desktop do Assistente. Esta camada cuida da janela principal,
configuração inicial, conversa, autenticação, atalhos, ações locais,
notificações e visualização de agenda. O repositório versiona atualmente o
runner Windows.

## Requisitos

- Flutter com suporte a Windows Desktop habilitado
- Dart SDK `>=3.2.0 <4.0.0`, incluído na instalação do Flutter
- Toolchain de desenvolvimento desktop do Windows reconhecida por
  `flutter doctor`
- Backend em execucao, por padrao em `http://localhost:8000`

Para habilitar o alvo versionado:

```bash
flutter config --enable-windows-desktop
flutter doctor
```

## Instalar Dependencias

```bash
cd interface
flutter pub get
```

## Executar

```bash
flutter run -d windows
```

### Outras Plataformas

O código Dart foi organizado para desktop, mas os runners `macos/` e `linux/`
não estão versionados. No sistema de destino, eles podem ser gerados a partir
de `interface/`:

```bash
flutter create --platforms=macos,linux .
```

Depois, valide a disponibilidade dos plugins e dos serviços locais usados pela
aplicação antes de distribuir o build nessas plataformas.

## Backend

A interface usa `http://localhost:8000` por padrão e guarda o endereço do
backend localmente (Hive), editável em **Configurações > Sistema > Conexão
com o backend** — não precisa recompilar pra trocar entre um backend local e
um em produção (ex. Railway). O botão "Aplicar e testar" salva o endereço e
chama `/health` na hora pra confirmar que respondeu.

Para mudar o padrão de fábrica usado antes da primeira configuração (útil em
builds de CI/distribuição), use `--dart-define`:

```bash
flutter run -d windows --dart-define=APP_BACKEND_URL=https://seu-app.host.app
```

Antes de abrir a interface, suba o backend na raiz do projeto:

```bash
cd ../backend
python run.py
```

Ou, pela raiz do projeto:

```bash
docker compose up -d
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
`APP_BACKEND_URL`: a interface desktop deve apontar para a URL pública completa
do backend e não consegue resolver diretamente o domínio privado da Railway.
URLs sem esquema recebem `http://`; URLs HTTPS geram automaticamente a conexão
WebSocket equivalente em `wss://`.
Consulte o [README do backend](../backend/README.md#railway) para as variáveis
completas.

## Primeira Configuracao

Na primeira abertura, o app exibe a tela de configuracao. Nela voce define:

- Nome do assistente, seu nome e perfil de atendimento
- Senha de acesso
- Canais e preferências de notificação
- Credenciais OAuth e contas de agenda
- Preferências de voz, inicialização e comportamento da interface

Se o backend habilitar `REGISTRATION_INVITE_REQUIRED`, a tela de acesso também
mostra o e-mail administrativo mascarado, solicita o envio do convite e exige o
token recebido antes de criar a primeira conta. A interface nunca recebe o
token diretamente da API: ele é entregue somente por e-mail.

Após o primeiro cadastro, a conta administrativa pode convidar usuários em
**Configurações > Autenticação**. O convidado seleciona **Criar conta com
convite** na tela de acesso e informa o token recebido. Configuração, histórico
de conversa e eventos armazenados localmente usam um escopo por conta; os dados
legados são migrados somente para o primeiro admin.

As credenciais e URLs dos provedores de LLM são configurações de
infraestrutura do backend e devem ser fornecidas por variáveis de ambiente.

## Ações Locais E Segurança

O backend pode devolver propostas tipadas para diagnósticos, scripts, inspeção
de workspace, abertura de projetos e cadastro de atalhos. Essas propostas não
são executadas no servidor. A interface:

1. interpreta o campo `action` da resposta do chat;
2. pede confirmação quando a ação exige autorização;
3. executa com os serviços locais apropriados;
4. devolve ao chat somente o resultado necessário para análise.

Scripts de risco alto permanecem bloqueados até autorização explícita. Os
snippets cadastrados no backend são isolados por conta, enquanto a execução
ocorre no computador em que a interface está aberta.

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
│   │   ├── api_service.dart                 # REST, SSE e WebSocket
│   │   ├── storage_service.dart             # Hive e escopo por conta
│   │   ├── local_computer_action_service.dart
│   │   ├── local_workspace_service.dart
│   │   ├── local_script_service.dart
│   │   ├── project_discovery_service.dart
│   │   └── external_launcher_service.dart
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
dart format lib test
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
- verifique se `/v1/models` lista o modelo ou se
  `/api/models/config-json/{modelo}` retorna a configuração instalada;
- confirme que `LOCALAI_BASE_URL` foi definida no backend, e não na interface;
- na Railway, confirme que backend e LocalAI estão no mesmo projeto e ambiente.

Se uma plataforma desktop nao aparecer em `flutter devices`, habilite o suporte
correspondente com `flutter config`.

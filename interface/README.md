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

## Primeira Configuracao

Na primeira abertura, o app exibe a tela de configuracao. Nela voce define:

- Nome do app e seu nome de usuario
- Perfil de atendimento e idioma
- Credenciais dos servicos de resposta
- Metodos de autenticacao
- Canais de notificacao
- Integracoes de agenda
- Preferencias do sistema

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
`http://localhost:8000/health`.

Se uma plataforma desktop nao aparecer em `flutter devices`, habilite o suporte
correspondente com `flutter config`.

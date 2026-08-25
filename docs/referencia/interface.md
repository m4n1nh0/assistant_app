# Interface Flutter

A referencia da interface e gerada pelo `dart doc`, que le os comentarios `///`
do codigo em `interface/lib`. O mkdocs nao consegue ler Dart, entao a saida do
`dart doc` entra no site como um subsite estatico.

!!! info "Gerar a referencia"

    ```bash
    cd interface
    flutter pub get
    dart doc --output ../site/referencia/interface/api
    ```

    Ou, para gerar backend e interface de uma vez, `./scripts/build_docs.ps1`
    (Windows) / `./scripts/build_docs.sh`. Depois disso a API Dart fica em
    <a href="interface/api/index.html"><code>referencia/interface/api/</code></a>.

## Como a camada esta organizada

A interface e um app Flutter Desktop com estado global em Riverpod. O ponto de
entrada e `lib/main.dart`, que inicializa `window_manager` (janela sem barra
nativa), `Hive` (cache local) e `hotkey_manager` (atalho global) antes de montar
`AssistantApp`.

| Diretorio | Papel |
| --- | --- |
| `branding/` | `IntarqBrand`, `IntarqLockup` e `IntarqMark`: nome, cores e simbolo da marca usados por splash, barra e relatorios. |
| `models/` | DTOs e estado serializavel — `AppConfig`, `ChatMessage`, `CalendarEvent`, acoes devolvidas pelo backend (`ComputerAction`, `LaunchAction`, ...) e os adaptadores Hive. |
| `providers/` | `app_provider.dart` concentra o estado global: `configProvider`, `ChatNotifier`, `EventsNotifier` e os flags de UI (`isLoadingProvider`, `isRecordingProvider`, `sideTabProvider`, ...). |
| `screens/` | As tres telas de topo: `SplashScreen`, `ConfigScreen` e `MainScreen`. |
| `widgets/` | Os paineis e dialogos que compoem a `MainScreen` — `chat_panel.dart` e `education_dialog.dart` sao os maiores e concentram a maior parte da interacao. |
| `services/` | Clientes de API e servicos que rodam na maquina do usuario. |
| `utils/` | Tema (`theme.dart`) e helpers de atalho de teclado. |

## Servicos da interface

Os servicos se dividem em dois grupos, e a distincao importa porque so o
primeiro atravessa a rede:

**Clientes do backend** — `ApiService` (cliente HTTP central), `EducationService`,
`CalendarService`, `LlmService`, `NotificationService` e `ConnectedAiService`.
Falam com o FastAPI local, carregam o token JWT e traduzem as respostas para os
modelos de `models/`.

**Servicos locais** — rodam na maquina e nao dependem do backend:
captura de audio e wake word (`audio_input_service`, `wake_word_service`,
`neural_tts_service`, `neural_audio_player`), contexto do desktop
(`local_desktop_context_service`, `installed_apps_service`,
`external_launcher_service`), acoes de codigo e workspace
(`local_workspace_service`, `workspace_diff_service`, `syntax_check_service`,
`project_discovery_service`, `local_script_service`), geracao de PDF
(`lesson_pdf_service`, `academic_report_pdf_service`) e persistencia local
(`storage_service` sobre Hive e `flutter_secure_storage`).

## Convencao de comentario

O `dart doc` usa `///` acima da declaracao. A primeira frase vira o resumo na
listagem, entao ela precisa se sustentar sozinha; referencias entre simbolos vao
entre colchetes e viram link.

```dart
/// Cliente HTTP do backend local, compartilhado por toda a interface.
///
/// Guarda o token JWT obtido em [login] e o injeta nas chamadas seguintes.
/// Lanca [EducationException] quando o backend responde erro de negocio.
class ApiService {
  /// Envia [mensagem] ao chat e devolve a resposta ja normalizada.
  ///
  /// [conversaId] nulo abre uma conversa nova.
  Future<ChatResult> enviarMensagem(String mensagem, {String? conversaId}) async {
    ...
  }
}
```

Classes com prefixo `_` sao privadas ao arquivo e o `dart doc` ja as ignora — a
maior parte dos `_SectionCard`, `_TabBtn` e afins de `config_screen.dart` cai
nesse caso e nao precisa de `///`.

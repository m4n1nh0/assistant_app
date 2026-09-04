/// Catalogo do que esta maquina sabe fazer.
///
/// Uma entrada declara **e** executa: a mesma lista gera o manifesto que a
/// interface publica para o backend e resolve a chamada quando a acao chega.
/// Isso torna impossivel anunciar o que nao se sabe executar - ou executar o
/// que nunca foi anunciado - que e o que acontecia com o catalogo escrito em
/// Python do outro lado, longe de quem tem a maquina.
///
/// A descricao de cada capacidade e o texto que o modelo le para decidir se ela
/// serve, entao ela e escrita para ser lida por um humano, nao por regex.
///
/// O que **nao** mora aqui: confirmacao e qualquer dialogo. Runner e funcao
/// pura de argumentos; quem tem o `BuildContext` pergunta ao usuario antes e
/// passa os argumentos ja resolvidos.
library;

import 'dart:io';

import 'api_service.dart';
import 'local_computer_action_service.dart';
import 'local_script_service.dart';
import 'local_workspace_service.dart';

/// Executor de uma capacidade: recebe os argumentos e devolve o resultado.
typedef CapabilityRunner = Future<CapabilityRunResult> Function(
  Map<String, dynamic> args,
);

/// Falha ao rodar uma capacidade local.
class LocalCapabilityException implements Exception {
  final String message;

  const LocalCapabilityException(this.message);

  @override
  String toString() => message;
}

/// O que uma capacidade produziu.
///
/// [summary] e a linha que a conversa mostra; [promptText] e o texto completo
/// que vai para a IA. [raw] carrega o objeto tipado do servico que executou
/// (`ComputerActionResult`, `ScriptRunResult`, `WorkspaceSnapshot`) para quem
/// precisa do detalhe - o transporte generico do backend usa so os dois textos.
class CapabilityRunResult {
  final String capabilityId;
  final String name;
  final bool ok;
  final String summary;
  final String promptText;
  final int durationMs;
  final Object? raw;

  const CapabilityRunResult({
    required this.capabilityId,
    required this.name,
    required this.ok,
    required this.summary,
    required this.promptText,
    required this.durationMs,
    this.raw,
  });
}

/// Uma capacidade declarada por esta maquina.
class LocalCapability {
  final String id;
  final String name;

  /// Em linguagem natural: e o que o modelo le para decidir se serve.
  final String description;

  /// JSON Schema dos argumentos aceitos.
  final Map<String, dynamic> argsSchema;

  /// `low`, `medium` ou `high`.
  final String riskLevel;

  /// Se a interface deve perguntar ao usuario antes de executar.
  final bool requiresConfirmation;

  /// True quando so coleta ou le, sem alterar nada na maquina.
  final bool readOnly;

  /// Sistemas onde vale. Vazio significa todos.
  final Set<String> platforms;

  final CapabilityRunner run;

  const LocalCapability({
    required this.id,
    required this.name,
    required this.description,
    required this.argsSchema,
    required this.run,
    this.riskLevel = 'low',
    this.requiresConfirmation = false,
    this.readOnly = true,
    this.platforms = const {},
  });

  /// Diz se esta capacidade vale no sistema informado.
  bool supportsPlatform(String platform) =>
      platforms.isEmpty || platforms.contains(platform);

  /// A declaracao como ela vai para o backend, sem o executor.
  Map<String, dynamic> toManifestEntry() => {
        'id': id,
        'name': name,
        'description': description,
        'args_schema': argsSchema,
        'risk_level': riskLevel,
        'requires_confirmation': requiresConfirmation,
        'read_only': readOnly,
        'platforms': platforms.toList()..sort(),
      };
}

/// O catalogo desta maquina.
class LocalCapabilityRegistry {
  /// Sistema atual, no vocabulario do manifesto.
  static String get currentPlatform {
    if (Platform.isWindows) return 'windows';
    if (Platform.isMacOS) return 'macos';
    if (Platform.isLinux) return 'linux';
    return Platform.operatingSystem;
  }

  static final Map<String, LocalCapability> _capabilities = {
    for (final capability in _declared) capability.id: capability,
  };

  static final List<LocalCapability> _declared = [
    LocalCapability(
      id: 'network_diagnostics',
      name: 'Diagnostico de rede',
      description:
          'Coleta a configuracao de rede desta maquina (IP local, gateway, DNS), '
          'descobre o IP externo e mede um ping, para analisar conectividade, '
          'lentidao ou queda de internet.',
      argsSchema: const {'type': 'object', 'properties': {}},
      run: (args) async {
        final result = await LocalComputerActionService.runNetworkDiagnostics();
        return _fromComputerAction('network_diagnostics', result);
      },
    ),
    LocalCapability(
      id: 'system_diagnostics',
      name: 'Diagnostico do sistema',
      description:
          'Coleta uso de memoria RAM, processos que mais consomem e espaco em '
          'disco desta maquina, para analisar lentidao ou falta de recurso.',
      argsSchema: const {'type': 'object', 'properties': {}},
      run: (args) async {
        final result = await LocalComputerActionService.runSystemDiagnostics();
        return _fromComputerAction('system_diagnostics', result);
      },
    ),
    LocalCapability(
      id: 'inspect_workspace',
      name: 'Inspecionar workspace local',
      description:
          'Le a estrutura de pastas e o conteudo dos arquivos relevantes de um '
          'projeto nesta maquina, para responder sobre o codigo com o contexto '
          'real em vez de suposicao.',
      argsSchema: const {
        'type': 'object',
        'properties': {
          'query': {
            'type': 'string',
            'description': 'Pedido do usuario, usado para escolher os arquivos.',
          },
          'root_path': {
            'type': 'string',
            'description': 'Pasta do projeto. Vazio deixa a interface resolver.',
          },
          'max_files': {'type': 'integer', 'minimum': 30, 'maximum': 800},
          'max_file_chars': {
            'type': 'integer',
            'minimum': 1000,
            'maximum': 16000,
          },
          'max_total_chars': {
            'type': 'integer',
            'minimum': 6000,
            'maximum': 60000,
          },
        },
      },
      requiresConfirmation: true,
      run: (args) async {
        final started = DateTime.now();
        final query = args['query']?.toString() ?? '';
        final snapshot = await LocalWorkspaceService.inspectWorkspace(
          query: query,
          rootPath: args['root_path']?.toString() ?? '',
          maxTreeFiles: _intArg(args['max_files'], 320, 30, 800),
          maxFileChars: _intArg(args['max_file_chars'], 8000, 1000, 16000),
          maxTotalChars: _intArg(args['max_total_chars'], 26000, 6000, 60000),
        );
        return CapabilityRunResult(
          capabilityId: 'inspect_workspace',
          name: 'Inspecionar workspace local',
          ok: true,
          summary: 'Workspace lido: ${snapshot.name} '
              '(${snapshot.scannedFiles} arquivos).',
          promptText: snapshot.toPromptText(
            userRequest: query,
            allowEdits: args['allow_edits'] == true,
          ),
          durationMs: DateTime.now().difference(started).inMilliseconds,
          raw: snapshot,
        );
      },
    ),
    LocalCapability(
      id: 'run_script',
      name: 'Executar script local',
      description:
          'Executa no shell desta maquina um script que o usuario pediu '
          'explicitamente, e devolve saida, erro e codigo de retorno.',
      argsSchema: const {
        'type': 'object',
        'required': ['script'],
        'properties': {
          'script': {'type': 'string', 'description': 'Conteudo do script.'},
          'shell': {
            'type': 'string',
            'description': 'powershell, cmd, bash, sh ou python.',
          },
          'working_directory': {'type': 'string'},
          'timeout_seconds': {
            'type': 'integer',
            'minimum': 1,
            'maximum': LocalScriptService.maxTimeoutSeconds,
          },
          'allow_high_risk': {'type': 'boolean'},
        },
      },
      riskLevel: 'medium',
      requiresConfirmation: true,
      readOnly: false,
      run: (args) async {
        final script = args['script']?.toString().trim() ?? '';
        if (script.isEmpty) {
          throw const LocalCapabilityException(
            'Nenhum script recebido para executar.',
          );
        }
        final result = await LocalScriptService.runScript(
          shell: args['shell']?.toString() ?? '',
          script: script,
          workingDirectory: args['working_directory']?.toString() ?? '',
          timeoutSeconds: _intArg(
            args['timeout_seconds'],
            60,
            1,
            LocalScriptService.maxTimeoutSeconds,
          ),
          allowHighRisk: args['allow_high_risk'] == true,
        );
        return CapabilityRunResult(
          capabilityId: 'run_script',
          name: 'Executar script local',
          ok: result.exitCode == 0 && !result.timedOut,
          summary: result.timedOut
              ? 'Script excedeu o tempo limite.'
              : 'Script finalizado com codigo ${result.exitCode}.',
          promptText: result.toPromptText(),
          durationMs: result.durationMs,
          raw: result,
        );
      },
    ),
  ];

  /// Todas as capacidades declaradas, inclusive as de outro sistema.
  static List<LocalCapability> get all => List.unmodifiable(_declared);

  /// As que valem nesta maquina.
  static List<LocalCapability> get supportedHere => List.unmodifiable(
        _declared
            .where((item) => item.supportsPlatform(currentPlatform))
            .toList(),
      );

  static LocalCapability? find(String id) => _capabilities[id.trim()];

  /// O que a interface publica: so o que roda de fato nesta maquina.
  static Map<String, dynamic> manifest() => {
        'platform': currentPlatform,
        'capabilities':
            supportedHere.map((item) => item.toManifestEntry()).toList(),
      };

  /// Executa uma capacidade pelo id.
  ///
  /// Confirmacao e responsabilidade de quem chama: aqui nao ha usuario para
  /// perguntar.
  static Future<CapabilityRunResult> run(
    String id,
    Map<String, dynamic> args,
  ) async {
    final capability = find(id);
    if (capability == null) {
      throw LocalCapabilityException(
        'Capacidade local desconhecida nesta maquina: $id',
      );
    }
    if (!capability.supportsPlatform(currentPlatform)) {
      throw LocalCapabilityException(
        '${capability.name} nao esta disponivel em $currentPlatform.',
      );
    }
    return capability.run(args);
  }

  static CapabilityRunResult _fromComputerAction(
    String id,
    ComputerActionResult result,
  ) =>
      CapabilityRunResult(
        capabilityId: id,
        name: result.actionName,
        ok: result.status == 'executed',
        summary: result.toLocalSummaryText(),
        promptText: result.toPromptText(),
        durationMs: result.durationMs,
        raw: result,
      );

  static int _intArg(Object? value, int fallback, int min, int max) {
    final parsed = value is int
        ? value
        : value is num
            ? value.toInt()
            : int.tryParse(value?.toString().trim() ?? '') ?? fallback;
    return parsed.clamp(min, max).toInt();
  }
}

import 'dart:async';
import 'dart:convert';
import 'dart:io';

class ConnectedAiStatus {
  final String id;
  final String label;
  final bool installed;
  final bool authenticated;
  final String executablePath;
  final String accountLabel;
  final String version;
  final String detail;

  const ConnectedAiStatus({
    required this.id,
    required this.label,
    required this.installed,
    required this.authenticated,
    this.executablePath = '',
    this.accountLabel = '',
    this.version = '',
    this.detail = '',
  });
}

class ConnectedAiResult {
  final String agentId;
  final String content;
  final bool isError;

  const ConnectedAiResult({
    required this.agentId,
    required this.content,
    this.isError = false,
  });
}

/// Uses the official, locally installed Codex/Claude Code clients.
///
/// Authentication remains in each vendor's CLI credential store. INTARQ only
/// detects login state and starts a restricted, non-interactive process; it
/// never reads or copies OAuth tokens.
class ConnectedAiService {
  static const supportedAgents = <String, String>{
    'codex_cli': 'Codex conectado',
    'claude_cli': 'Claude conectado',
  };

  static Future<List<ConnectedAiStatus>> checkAll() async => Future.wait(
        supportedAgents.keys.map(check),
      );

  static Future<ConnectedAiStatus> check(String id) async {
    final label = supportedAgents[id] ?? id;
    final executable = await _resolveExecutable(id);
    if (executable == null) {
      return ConnectedAiStatus(
        id: id,
        label: label,
        installed: false,
        authenticated: false,
        detail: 'Cliente não encontrado neste computador.',
      );
    }

    try {
      final versionResult = await Process.run(executable, ['--version'])
          .timeout(const Duration(seconds: 8));
      final version = '${versionResult.stdout}'.trim();
      final args = id == 'codex_cli'
          ? const ['login', 'status']
          : const ['auth', 'status'];
      final result = await Process.run(executable, args)
          .timeout(const Duration(seconds: 12));
      final output = '${result.stdout}\n${result.stderr}'.trim();
      var authenticated = result.exitCode == 0;
      var account = '';
      var detail = output;
      if (id == 'codex_cli') {
        authenticated =
            authenticated && output.toLowerCase().contains('logged in');
        detail = authenticated
            ? 'Sessão oficial do Codex disponível.'
            : 'Codex instalado, mas sem login.';
      } else {
        try {
          final data = jsonDecode('${result.stdout}') as Map<String, dynamic>;
          authenticated = data['loggedIn'] == true;
          account = data['email']?.toString() ?? '';
          final method = data['authMethod']?.toString() ?? '';
          detail = authenticated
              ? 'Sessão oficial ${method.isEmpty ? 'Claude' : method} disponível.'
              : 'Claude instalado, mas sem login.';
        } catch (_) {
          authenticated =
              authenticated && output.toLowerCase().contains('loggedin');
        }
      }
      return ConnectedAiStatus(
        id: id,
        label: label,
        installed: true,
        authenticated: authenticated,
        executablePath: executable,
        accountLabel: account,
        version: version,
        detail: detail,
      );
    } catch (error) {
      return ConnectedAiStatus(
        id: id,
        label: label,
        installed: true,
        authenticated: false,
        executablePath: executable,
        detail: 'Não foi possível consultar o login: $error',
      );
    }
  }

  static Future<void> startLogin(String id) async {
    final executable = await _resolveExecutable(id);
    if (executable == null) {
      throw Exception('${supportedAgents[id] ?? id} não está instalado.');
    }
    final args = id == 'codex_cli' ? const ['login'] : const ['auth', 'login'];
    final process = await Process.start(
      executable,
      args,
      mode: ProcessStartMode.detachedWithStdio,
    );
    process.stdout.drain<void>();
    process.stderr.drain<void>();
  }

  static Future<void> logout(String id) async {
    final executable = await _resolveExecutable(id);
    if (executable == null) return;
    final args =
        id == 'codex_cli' ? const ['logout'] : const ['auth', 'logout'];
    final result = await Process.run(executable, args)
        .timeout(const Duration(seconds: 30));
    if (result.exitCode != 0) {
      throw Exception('${result.stderr}'.trim());
    }
  }

  static Future<ConnectedAiResult> run({
    required String agentId,
    required String prompt,
    List<Map<String, String>> history = const [],
    String assistantName = 'Assistant',
    String personality = '',
    String language = 'pt-BR',
    String workingDirectory = '',
  }) async {
    final status = await check(agentId);
    if (!status.installed || !status.authenticated) {
      return ConnectedAiResult(
        agentId: agentId,
        content: status.installed
            ? '${status.label} precisa ser conectado em Configurações > Agentes.'
            : '${status.label} não está instalado neste computador.',
        isError: true,
      );
    }

    final fullPrompt = _buildPrompt(
      prompt: prompt,
      history: history,
      assistantName: assistantName,
      personality: personality,
      language: language,
    );
    try {
      final content = agentId == 'codex_cli'
          ? await _runCodex(
              status.executablePath,
              fullPrompt,
              workingDirectory,
            )
          : await _runClaude(
              status.executablePath,
              fullPrompt,
              workingDirectory,
            );
      return ConnectedAiResult(agentId: agentId, content: content);
    } on TimeoutException {
      return ConnectedAiResult(
        agentId: agentId,
        content: 'O agente local excedeu o limite de 5 minutos.',
        isError: true,
      );
    } catch (error) {
      return ConnectedAiResult(
        agentId: agentId,
        content: 'Falha ao executar ${status.label}: $error',
        isError: true,
      );
    }
  }

  static String _buildPrompt({
    required String prompt,
    required List<Map<String, String>> history,
    required String assistantName,
    required String personality,
    required String language,
  }) {
    final buffer = StringBuffer()
      ..writeln('Você está atendendo dentro do assistente INTARQ.')
      ..writeln('Na interface, seu nome é $assistantName.')
      ..writeln(
          'Responda em ${language == 'pt-BR' ? 'português brasileiro' : language}.')
      ..writeln(
          'Não altere arquivos nem execute ações destrutivas; responda ao usuário em texto.');
    if (personality.trim().isNotEmpty) {
      buffer.writeln('Estilo solicitado: ${personality.trim()}');
    }
    if (history.isNotEmpty) {
      buffer.writeln('\nHistórico recente:');
      for (final message in history.takeLast(8)) {
        final role = message['role'] == 'assistant' ? 'Assistente' : 'Usuário';
        buffer.writeln('$role: ${message['content'] ?? ''}');
      }
    }
    buffer.writeln('\nPedido atual do usuário:\n$prompt');
    return buffer.toString();
  }

  static Future<String> _runCodex(
    String executable,
    String prompt,
    String workingDirectory,
  ) async {
    final output = File(
      '${Directory.systemTemp.path}${Platform.pathSeparator}'
      'intarq_codex_${DateTime.now().microsecondsSinceEpoch}.txt',
    );
    try {
      final args = <String>[
        'exec',
        '--sandbox',
        'read-only',
        '--ephemeral',
        '--skip-git-repo-check',
        '--color',
        'never',
        '-o',
        output.path,
        if (workingDirectory.trim().isNotEmpty) ...[
          '-C',
          workingDirectory.trim(),
        ],
        '-',
      ];
      final result = await _runProcess(executable, args, prompt);
      if (result.exitCode != 0) {
        throw Exception(_safeProcessError(result));
      }
      final content = await output.exists() ? await output.readAsString() : '';
      if (content.trim().isEmpty) {
        throw Exception('Codex terminou sem devolver uma resposta.');
      }
      return content.trim();
    } finally {
      if (await output.exists()) await output.delete();
    }
  }

  static Future<String> _runClaude(
    String executable,
    String prompt,
    String workingDirectory,
  ) async {
    final args = <String>[
      '--print',
      '--output-format',
      'json',
      '--permission-mode',
      'plan',
      '--no-session-persistence',
      '--tools',
      'Read,Glob,Grep',
    ];
    final result = await _runProcess(
      executable,
      args,
      prompt,
      workingDirectory: workingDirectory,
    );
    if (result.exitCode != 0) throw Exception(_safeProcessError(result));
    final data = jsonDecode(result.stdout) as Map<String, dynamic>;
    final content = data['result']?.toString().trim() ?? '';
    if (content.isEmpty) {
      throw Exception('Claude terminou sem devolver uma resposta.');
    }
    return content;
  }

  static Future<_ProcessOutput> _runProcess(
    String executable,
    List<String> args,
    String stdin, {
    String workingDirectory = '',
  }) async {
    final process = await Process.start(
      executable,
      args,
      workingDirectory:
          workingDirectory.trim().isEmpty ? null : workingDirectory.trim(),
    );
    final stdoutFuture = process.stdout.transform(utf8.decoder).join();
    final stderrFuture = process.stderr.transform(utf8.decoder).join();
    process.stdin.write(stdin);
    await process.stdin.close();
    try {
      final exitCode =
          await process.exitCode.timeout(const Duration(minutes: 5));
      return _ProcessOutput(
        exitCode,
        await stdoutFuture,
        await stderrFuture,
      );
    } on TimeoutException {
      process.kill();
      rethrow;
    }
  }

  static String _safeProcessError(_ProcessOutput result) {
    final error = _redact(result.stderr.trim());
    if (error.isNotEmpty) {
      return error.length > 800 ? error.substring(0, 800) : error;
    }
    return 'processo encerrado com código ${result.exitCode}';
  }

  static String _redact(String value) => value
      .replaceAll(
        RegExp(
          r'(api[_ -]?key|access[_ -]?token|authorization|bearer)\s*[:=]?\s*[^\s,;]+',
          caseSensitive: false,
        ),
        '[credential redacted]',
      )
      .replaceAll(
        RegExp(r'\bsk-[A-Za-z0-9_-]{12,}\b'),
        '[redacted]',
      );

  static Future<String?> _resolveExecutable(String id) async {
    final command = id == 'codex_cli' ? 'codex' : 'claude';
    final fromPath = await _findOnPath(command);
    if (fromPath != null) return fromPath;
    if (!Platform.isWindows) return null;

    final profile = Platform.environment['USERPROFILE'];
    if (profile == null || profile.isEmpty) return null;
    final extensions = Directory('$profile\\.vscode\\extensions');
    if (!await extensions.exists()) return null;
    final prefix =
        id == 'codex_cli' ? 'openai.chatgpt-' : 'anthropic.claude-code-';
    final folders = extensions
        .listSync(followLinks: false)
        .whereType<Directory>()
        .where((item) =>
            item.path.split(Platform.pathSeparator).last.startsWith(prefix))
        .toList()
      ..sort((a, b) => b.path.compareTo(a.path));
    for (final folder in folders) {
      final relative = id == 'codex_cli'
          ? 'bin\\windows-x86_64\\codex.exe'
          : 'resources\\native-binary\\claude.exe';
      final candidate = File('${folder.path}\\$relative');
      if (await candidate.exists()) return candidate.path;
    }
    return null;
  }

  static Future<String?> _findOnPath(String command) async {
    try {
      final locator = Platform.isWindows ? 'where.exe' : 'which';
      final result = await Process.run(locator, [command])
          .timeout(const Duration(seconds: 5));
      if (result.exitCode != 0) return null;
      for (final line in '${result.stdout}'.split(RegExp(r'[\r\n]+'))) {
        final path = line.trim();
        if (path.isNotEmpty && await File(path).exists()) return path;
      }
    } catch (_) {}
    return null;
  }
}

class _ProcessOutput {
  final int exitCode;
  final String stdout;
  final String stderr;

  const _ProcessOutput(this.exitCode, this.stdout, this.stderr);
}

extension<T> on Iterable<T> {
  Iterable<T> takeLast(int count) {
    final values = toList();
    return values.skip(values.length > count ? values.length - count : 0);
  }
}

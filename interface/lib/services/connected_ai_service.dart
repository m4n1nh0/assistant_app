/// Ponte com agentes de IA instalados na maquina (Codex, Claude Code).
///
/// Aproveita a janela de contexto enorme desses agentes para tarefas que nao cabem
/// nos provedores locais - resumo de aula inteira, por exemplo.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Estado de um agente conectado: se esta instalado e pronto para uso.
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

/// Resposta de um agente conectado, com o texto e se houve erro.
class ConnectedAiResult {
  final String agentId;
  final String content;
  final bool isError;

  /// Caminhos relativos alterados pelo agente nesta execução, detectados
  /// pelo git. Vazio quando o workspace não é um repositório git.
  final List<String> changedFiles;

  const ConnectedAiResult({
    required this.agentId,
    required this.content,
    this.isError = false,
    this.changedFiles = const [],
  });
}

/// Uses the official, locally installed Codex/Claude Code clients.
///
/// Authentication remains in each vendor's CLI credential store. INTARQ only
/// detects login state and starts a restricted, non-interactive process; it
/// never reads or copies OAuth tokens.
///
/// By default the agents run read-only. When the user authorizes edits on a
/// workspace, the agent process gains write access limited to that folder
/// (Codex: sandbox workspace-write; Claude: permission-mode acceptEdits) and
/// edits files directly with its own tools, like the VSCode extensions do.
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
    bool allowWorkspaceEdits = false,
    void Function(String activity)? onProgress,
    String systemPrompt = '',
    Duration? timeoutOverride,
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

    final root = workingDirectory.trim();
    final writeMode = allowWorkspaceEdits && root.isNotEmpty;
    // Sessões agênticas com escrita leem e editam vários arquivos; precisam
    // de mais tempo do que uma resposta somente leitura.
    final timeout = timeoutOverride ??
        (writeMode ? const Duration(minutes: 10) : const Duration(minutes: 5));

    final fullPrompt = _buildPrompt(
      prompt: prompt,
      history: history,
      assistantName: assistantName,
      personality: personality,
      language: language,
      allowWorkspaceEdits: writeMode,
      workspaceRoot: root,
      systemPrompt: systemPrompt,
    );
    try {
      final statusBefore = writeMode
          ? await _gitStatusLines(root)
          : const <String>{};
      final content = agentId == 'codex_cli'
          ? await _runCodex(
              status.executablePath,
              fullPrompt,
              root,
              allowEdits: writeMode,
              timeout: timeout,
              onProgress: onProgress,
            )
          : await _runClaude(
              status.executablePath,
              fullPrompt,
              root,
              allowEdits: writeMode,
              timeout: timeout,
              onProgress: onProgress,
            );
      // O diff completo é mostrado pela interface; aqui basta a lista de
      // arquivos tocados nesta execução.
      final changedFiles = writeMode
          ? _changedPaths((await _gitStatusLines(root)).difference(statusBefore))
          : const <String>[];
      return ConnectedAiResult(
        agentId: agentId,
        content: content,
        changedFiles: changedFiles,
      );
    } on TimeoutException {
      return ConnectedAiResult(
        agentId: agentId,
        content:
            'O agente local excedeu o limite de ${timeout.inMinutes} minutos.',
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
    bool allowWorkspaceEdits = false,
    String workspaceRoot = '',
    String systemPrompt = '',
  }) {
    // Tarefa fora do chat (resumo de aula, por exemplo): as instrucoes da
    // tarefa substituem a persona do assistente e o historico da conversa,
    // que so atrapalhariam o formato pedido. A trava de nao escrever em
    // arquivo continua, porque estes clientes sabem editar disco.
    if (systemPrompt.trim().isNotEmpty) {
      final task = StringBuffer()
        ..writeln(systemPrompt.trim())
        ..writeln(
            'Nao altere arquivos nem execute acoes destrutivas: responda '
            'apenas com o texto pedido, sem comentarios antes ou depois.')
        ..writeln()
        ..writeln(prompt);
      return task.toString().trim();
    }

    final buffer = StringBuffer()
      ..writeln('Você está atendendo dentro do assistente INTARQ.')
      ..writeln('Na interface, seu nome é $assistantName.')
      ..writeln(
          'Responda em ${language == 'pt-BR' ? 'português brasileiro' : language}.');
    if (allowWorkspaceEdits) {
      buffer
        ..writeln(
            'O usuário autorizou você a editar arquivos diretamente no '
            'workspace em ${workspaceRoot.trim()} usando suas próprias '
            'ferramentas de leitura e edição.')
        ..writeln(
            'Trabalhe como em uma sessão de código na IDE: explore os '
            'arquivos necessários, faça as alterações pedidas e mantenha as '
            'mudanças mínimas e consistentes com o estilo do projeto. Para '
            'pedidos de revisão ou análise, apenas leia e responda em texto, '
            'sem editar nada.')
        ..writeln(
            'Nunca altere arquivos fora do workspace nem arquivos sensíveis '
            '(.env, segredos, chaves, tokens) e não execute ações '
            'destrutivas.')
        ..writeln(
            'Ao terminar, responda com um resumo objetivo do que foi feito, '
            'listando cada arquivo alterado e o motivo da mudança.');
    } else {
      buffer.writeln(
          'Não altere arquivos nem execute ações destrutivas; responda ao usuário em texto.');
    }
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
    String workingDirectory, {
    bool allowEdits = false,
    Duration timeout = const Duration(minutes: 5),
    void Function(String activity)? onProgress,
  }) async {
    final output = File(
      '${Directory.systemTemp.path}${Platform.pathSeparator}'
      'intarq_codex_${DateTime.now().microsecondsSinceEpoch}.txt',
    );
    try {
      final args = <String>[
        'exec',
        '--sandbox',
        // workspace-write limita a escrita do Codex à pasta autorizada.
        allowEdits ? 'workspace-write' : 'read-only',
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
      final result = await _runProcess(
        executable,
        args,
        prompt,
        timeout: timeout,
        onOutputLine: onProgress == null
            ? null
            : (line) {
                final label = _codexProgressLabel(line);
                if (label != null) onProgress(label);
              },
      );
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
    String workingDirectory, {
    bool allowEdits = false,
    Duration timeout = const Duration(minutes: 5),
    void Function(String activity)? onProgress,
  }) async {
    final args = <String>[
      '--print',
      '--permission-mode',
      // acceptEdits aceita edições apenas dentro do diretório de trabalho;
      // sem autorização o Claude segue em modo plan (somente leitura).
      allowEdits ? 'acceptEdits' : 'plan',
      '--no-session-persistence',
      '--tools',
      allowEdits ? 'Read,Glob,Grep,Edit,Write' : 'Read,Glob,Grep',
    ];
    if (onProgress != null) {
      return _runClaudeStreaming(
        executable,
        args,
        prompt,
        workingDirectory,
        timeout,
        onProgress,
      );
    }
    final result = await _runProcess(
      executable,
      [...args, '--output-format', 'json'],
      prompt,
      workingDirectory: workingDirectory,
      timeout: timeout,
    );
    if (result.exitCode != 0) throw Exception(_safeProcessError(result));
    final data = jsonDecode(result.stdout) as Map<String, dynamic>;
    final content = data['result']?.toString().trim() ?? '';
    if (content.isEmpty) {
      throw Exception('Claude terminou sem devolver uma resposta.');
    }
    return content;
  }

  /// Executa o Claude com saída stream-json para relatar em tempo real qual
  /// ferramenta está em uso (leitura, busca, edição), como a extensão do
  /// VSCode faz. O texto final vem no evento `result`.
  static Future<String> _runClaudeStreaming(
    String executable,
    List<String> baseArgs,
    String prompt,
    String workingDirectory,
    Duration timeout,
    void Function(String activity) onProgress,
  ) async {
    final process = await Process.start(
      executable,
      // stream-json no modo --print exige --verbose para emitir os eventos.
      [...baseArgs, '--output-format', 'stream-json', '--verbose'],
      workingDirectory:
          workingDirectory.trim().isEmpty ? null : workingDirectory.trim(),
    );
    final stderrFuture = process.stderr.transform(utf8.decoder).join();
    String? result;
    String? resultError;
    final stdoutDone = process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .forEach((line) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) return;
      try {
        final event = jsonDecode(trimmed);
        if (event is! Map<String, dynamic>) return;
        final type = event['type']?.toString();
        if (type == 'assistant') {
          final message = event['message'];
          final content = message is Map ? message['content'] : null;
          if (content is! List) return;
          for (final block in content) {
            if (block is! Map) continue;
            if (block['type'] == 'tool_use') {
              final label = _toolProgressLabel(
                block['name']?.toString() ?? '',
                block['input'],
              );
              if (label != null) onProgress(label);
            } else if (block['type'] == 'text' &&
                '${block['text'] ?? ''}'.trim().isNotEmpty) {
              onProgress('💬 Escrevendo resposta...');
            }
          }
        } else if (type == 'result') {
          final text = event['result']?.toString().trim() ?? '';
          if (event['is_error'] == true) {
            resultError = text.isEmpty ? 'o agente reportou erro' : text;
          } else {
            result = text;
          }
        }
      } catch (_) {
        // Linhas que não são JSON (avisos, etc.) são ignoradas.
      }
    });
    process.stdin.write(prompt);
    await process.stdin.close();
    try {
      final exitCode = await process.exitCode.timeout(timeout);
      await stdoutDone;
      if (resultError != null) throw Exception(_redact(resultError!));
      if (exitCode != 0) {
        throw Exception(
          _safeProcessError(_ProcessOutput(exitCode, '', await stderrFuture)),
        );
      }
      final content = result?.trim() ?? '';
      if (content.isEmpty) {
        throw Exception('Claude terminou sem devolver uma resposta.');
      }
      return content;
    } on TimeoutException {
      process.kill();
      rethrow;
    }
  }

  static String? _toolProgressLabel(String tool, dynamic input) {
    String field(String key) {
      if (input is Map && input[key] != null) return '${input[key]}'.trim();
      return '';
    }

    String shorten(String path) {
      final normalized = path.replaceAll('\\', '/');
      final parts =
          normalized.split('/').where((item) => item.isNotEmpty).toList();
      return parts.length <= 2
          ? normalized
          : parts.sublist(parts.length - 2).join('/');
    }

    switch (tool) {
      case 'Read':
        return '📖 Lendo ${shorten(field('file_path'))}';
      case 'Edit':
        return '✏️ Editando ${shorten(field('file_path'))}';
      case 'Write':
        return '📝 Gravando ${shorten(field('file_path'))}';
      case 'Glob':
        return '🔎 Listando ${field('pattern')}';
      case 'Grep':
        return '🔎 Procurando "${field('pattern')}"';
      default:
        return tool.isEmpty ? null : '⚙️ $tool...';
    }
  }

  /// Converte uma linha de progresso do `codex exec` em um rótulo curto para
  /// a interface; retorna null para linhas de ruído.
  static String? _codexProgressLabel(String line) {
    var text = line.trim().replaceFirst(RegExp(r'^\[[^\]]*\]\s*'), '');
    if (text.isEmpty) return null;
    final lower = text.toLowerCase();
    if (lower.startsWith('reading prompt') ||
        lower.startsWith('tokens used') ||
        lower.startsWith('--------')) {
      return null;
    }
    if (text.length > 90) text = '${text.substring(0, 90)}...';
    return '🤖 $text';
  }

  static Future<_ProcessOutput> _runProcess(
    String executable,
    List<String> args,
    String stdin, {
    String workingDirectory = '',
    Duration timeout = const Duration(minutes: 5),
    void Function(String line)? onOutputLine,
  }) async {
    final process = await Process.start(
      executable,
      args,
      workingDirectory:
          workingDirectory.trim().isEmpty ? null : workingDirectory.trim(),
    );

    Future<String> collect(Stream<List<int>> stream) async {
      if (onOutputLine == null) return stream.transform(utf8.decoder).join();
      final buffer = StringBuffer();
      await stream
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .forEach((line) {
        buffer.writeln(line);
        if (line.trim().isNotEmpty) onOutputLine(line);
      });
      return buffer.toString();
    }

    final stdoutFuture = collect(process.stdout);
    final stderrFuture = collect(process.stderr);
    process.stdin.write(stdin);
    await process.stdin.close();
    try {
      final exitCode = await process.exitCode.timeout(timeout);
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

  /// Linhas de `git status --porcelain` do workspace, ou vazio quando a
  /// pasta não é um repositório git ou o git não está disponível.
  static Future<Set<String>> _gitStatusLines(String root) async {
    try {
      final result = await Process.run(
        'git',
        ['status', '--porcelain'],
        workingDirectory: root,
      ).timeout(const Duration(seconds: 10));
      if (result.exitCode != 0) return const {};
      return '${result.stdout}'
          .split(RegExp(r'[\r\n]+'))
          .map((line) => line.trimRight())
          .where((line) => line.trim().isNotEmpty)
          .toSet();
    } catch (_) {
      return const {};
    }
  }

  /// Extrai os caminhos relativos de linhas de `git status --porcelain`.
  static List<String> _changedPaths(Set<String> lines) {
    final paths = <String>{};
    for (final line in lines) {
      final raw = line.length > 3 ? line.substring(3).trim() : line.trim();
      if (raw.isEmpty) continue;
      // Renomeações vêm como "antigo -> novo"; interessa o destino.
      final arrow = raw.indexOf(' -> ');
      paths.add(arrow >= 0 ? raw.substring(arrow + 4).trim() : raw);
    }
    final sorted = paths.toList()..sort();
    return sorted;
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

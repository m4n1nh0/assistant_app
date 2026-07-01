import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'api_service.dart';

class LocalScriptException implements Exception {
  final String message;

  const LocalScriptException(this.message);

  @override
  String toString() => message;
}

class LocalScriptService {
  static const int maxScriptChars = 20000;
  static const int maxTimeoutSeconds = 180;
  static const int maxOutputChars = 12000;

  static const Map<String, String> _extensions = {
    'powershell': '.ps1',
    'pwsh': '.ps1',
    'cmd': '.cmd',
    'bash': '.sh',
    'sh': '.sh',
    'zsh': '.sh',
  };

  static final List<RegExp> _highRiskPatterns = [
    RegExp(r'\brm\s+-rf\s+[/~*]', caseSensitive: false),
    RegExp(r'\bremove-item\b[\s\S]*\s-recurse\b[\s\S]*\s-force\b',
        caseSensitive: false),
    RegExp(r'\bdel\s+/[fsq]', caseSensitive: false),
    RegExp(r'\bformat\s+[a-z]:', caseSensitive: false),
    RegExp(r'\bshutdown\b|\brestart-computer\b|\bstop-computer\b',
        caseSensitive: false),
    RegExp(r'\bdiskpart\b|\bmkfs\.', caseSensitive: false),
    RegExp(r'\breg\s+delete\b', caseSensitive: false),
  ];

  static Future<ScriptShellsInfo> shellInfo() async {
    final shells = <String>[];
    for (final shell in _candidateShells()) {
      if (!shells.contains(shell) && await _shellExists(shell)) {
        shells.add(shell);
      }
    }
    if (shells.isEmpty) shells.add(_fallbackShell());
    final preferred = _preferredShell();
    return ScriptShellsInfo(
      defaultShell: shells.contains(preferred) ? preferred : shells.first,
      availableShells: shells,
    );
  }

  static Future<ScriptRunResult> runScript({
    required String shell,
    required String script,
    String workingDirectory = '',
    int timeoutSeconds = 30,
    bool allowHighRisk = false,
  }) async {
    final normalizedShell = shell.trim().toLowerCase();
    if (!_extensions.containsKey(normalizedShell)) {
      throw LocalScriptException('Shell nao suportado: $shell');
    }

    final executable = _executableName(normalizedShell);
    if (!await _shellExists(normalizedShell)) {
      throw LocalScriptException(
        'Shell nao encontrada neste computador: $normalizedShell',
      );
    }

    final cleanScript = script.trim();
    if (cleanScript.isEmpty) {
      throw const LocalScriptException('Script vazio.');
    }
    if (cleanScript.length > maxScriptChars) {
      throw const LocalScriptException('Script excede 20000 caracteres.');
    }

    final highRisk = hasHighRiskContent(cleanScript);
    if (highRisk && !allowHighRisk) {
      throw const LocalScriptException(
        'Script contem comandos de alto risco. Habilite permissao explicita para executar.',
      );
    }

    final timeout = timeoutSeconds.clamp(1, maxTimeoutSeconds).toInt();
    final cwd = await _resolveWorkingDirectory(workingDirectory);
    final started = DateTime.now();
    final tempDir = await Directory.systemTemp.createTemp('assistant_script_');

    try {
      final scriptPath =
          '${tempDir.path}${Platform.pathSeparator}script${_extensions[normalizedShell]}';
      final scriptFile = File(scriptPath);
      final body = _scriptBody(normalizedShell, cleanScript);
      await scriptFile.writeAsBytes(_scriptBytes(normalizedShell, body),
          flush: true);

      final command = _buildCommand(normalizedShell, executable, scriptPath);
      final process = await Process.start(
        command.first,
        command.sublist(1),
        workingDirectory: cwd.path,
        runInShell: false,
      );
      const decoder = Utf8Decoder(allowMalformed: true);
      final stdoutFuture = process.stdout.transform(decoder).join();
      final stderrFuture = process.stderr.transform(decoder).join();

      var timedOut = false;
      var exitCode = 0;
      try {
        exitCode = await process.exitCode.timeout(Duration(seconds: timeout));
      } on TimeoutException {
        timedOut = true;
        exitCode = 124;
        process.kill();
        await process.exitCode
            .timeout(const Duration(seconds: 2), onTimeout: () => exitCode);
      }

      final stdout = await stdoutFuture.timeout(
        const Duration(seconds: 2),
        onTimeout: () => '',
      );
      var stderr = await stderrFuture.timeout(
        const Duration(seconds: 2),
        onTimeout: () => '',
      );
      if (timedOut && stderr.trim().isEmpty) {
        stderr = 'Timeout apos ${timeout}s';
      }

      return ScriptRunResult(
        shell: normalizedShell,
        command: _commandPreview(command),
        workingDirectory: cwd.path,
        exitCode: exitCode,
        stdout: _trimOutput(stdout),
        stderr: _trimOutput(stderr),
        durationMs: DateTime.now().difference(started).inMilliseconds,
        timedOut: timedOut,
        highRiskDetected: highRisk,
      );
    } finally {
      try {
        await tempDir.delete(recursive: true);
      } catch (_) {}
    }
  }

  static bool hasHighRiskContent(String script) =>
      _highRiskPatterns.any((pattern) => pattern.hasMatch(script));

  static List<String> _candidateShells() {
    if (Platform.isWindows) {
      return const ['powershell', 'pwsh', 'cmd', 'bash', 'sh'];
    }
    if (Platform.isMacOS) {
      return const ['zsh', 'bash', 'sh', 'pwsh', 'powershell'];
    }
    return const ['bash', 'sh', 'zsh', 'pwsh', 'powershell'];
  }

  static String _preferredShell() {
    if (Platform.isWindows) return 'powershell';
    if (Platform.isMacOS) return 'zsh';
    return 'bash';
  }

  static String _fallbackShell() {
    if (Platform.isWindows) return 'powershell';
    if (Platform.isMacOS) return 'zsh';
    return 'sh';
  }

  static Future<bool> _shellExists(String shell) async {
    final executable = _executableName(shell);
    if (executable.isEmpty) return false;
    if (Platform.isWindows && (shell == 'powershell' || shell == 'cmd')) {
      return true;
    }
    try {
      final locator = Platform.isWindows ? 'where' : 'which';
      final result = await Process.run(locator, [executable])
          .timeout(const Duration(seconds: 2));
      return result.exitCode == 0;
    } catch (_) {
      return false;
    }
  }

  static String _executableName(String shell) {
    switch (shell) {
      case 'powershell':
        return Platform.isWindows ? 'powershell.exe' : 'powershell';
      case 'pwsh':
        return Platform.isWindows ? 'pwsh.exe' : 'pwsh';
      case 'cmd':
        return Platform.isWindows ? 'cmd.exe' : '';
      case 'bash':
      case 'sh':
      case 'zsh':
        return shell;
    }
    return '';
  }

  static Future<Directory> _resolveWorkingDirectory(String rawPath) async {
    final path = rawPath.trim();
    if (path.isEmpty) return Directory.current.absolute;
    final directory = Directory(path).absolute;
    if (await directory.exists()) return directory;
    throw LocalScriptException('Diretorio de trabalho invalido: $rawPath');
  }

  static String _scriptBody(String shell, String script) {
    if (shell == 'powershell' || shell == 'pwsh') {
      return '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n'
          r'$OutputEncoding = [System.Text.Encoding]::UTF8'
          '\n$script';
    }
    return script;
  }

  static List<int> _scriptBytes(String shell, String body) {
    final bytes = utf8.encode(body);
    if (shell == 'powershell' || shell == 'pwsh') {
      return [0xEF, 0xBB, 0xBF, ...bytes];
    }
    return bytes;
  }

  static List<String> _buildCommand(
    String shell,
    String executable,
    String scriptPath,
  ) {
    if (shell == 'powershell' || shell == 'pwsh') {
      return [
        executable,
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
      ];
    }
    if (shell == 'cmd') {
      return [executable, '/d', '/s', '/c', scriptPath];
    }
    return [executable, scriptPath];
  }

  static String _commandPreview(List<String> command) =>
      command.map(_quoteIfNeeded).join(' ');

  static String _quoteIfNeeded(String value) {
    if (value.isEmpty) return '""';
    if (!RegExp(r'\s').hasMatch(value)) return value;
    return '"${value.replaceAll('"', r'\"')}"';
  }

  static String _trimOutput(String value) {
    if (value.length <= maxOutputChars) return value;
    return '${value.substring(0, maxOutputChars)}\n...[saida truncada]';
  }
}

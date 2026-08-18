import 'dart:async';
import 'dart:convert';
import 'dart:io';

class SyntaxCheckResult {
  final bool ok;

  /// false quando não há validador real disponível para a linguagem
  /// (ferramenta ausente no PATH ou linguagem sem suporte).
  final bool supported;
  final String message;

  const SyntaxCheckResult({
    required this.ok,
    required this.supported,
    required this.message,
  });
}

/// Identifica a linguagem pelo nome do arquivo e valida sintaxe usando o
/// validador mais forte disponível na máquina: `dart analyze` para Dart,
/// o interpretador Python para `.py`, parser interno para JSON e uma
/// verificação básica de delimitadores para as demais linguagens.
class SyntaxCheckService {
  static const _languageByExtension = <String, String>{
    '.dart': 'Dart',
    '.py': 'Python',
    '.js': 'JavaScript',
    '.jsx': 'JavaScript (JSX)',
    '.ts': 'TypeScript',
    '.tsx': 'TypeScript (TSX)',
    '.json': 'JSON',
    '.yaml': 'YAML',
    '.yml': 'YAML',
    '.md': 'Markdown',
    '.html': 'HTML',
    '.htm': 'HTML',
    '.css': 'CSS',
    '.sql': 'SQL',
    '.sh': 'Shell',
    '.ps1': 'PowerShell',
    '.bat': 'Batch',
    '.cmd': 'Batch',
    '.toml': 'TOML',
    '.xml': 'XML',
    '.ini': 'INI',
    '.java': 'Java',
    '.kt': 'Kotlin',
    '.go': 'Go',
    '.rs': 'Rust',
    '.c': 'C',
    '.h': 'C/C++ (header)',
    '.cpp': 'C++',
    '.cs': 'C#',
    '.php': 'PHP',
    '.rb': 'Ruby',
    '.txt': 'Texto',
    '.csv': 'CSV',
    '.env.example': 'Env',
  };

  static String languageFor(String path) {
    final name = path.split(RegExp(r'[\\/]')).last.toLowerCase();
    if (name == 'dockerfile') return 'Dockerfile';
    if (name == 'makefile') return 'Makefile';
    final dot = name.lastIndexOf('.');
    if (dot < 0) return 'Texto';
    final ext = name.substring(dot);
    return _languageByExtension[ext] ??
        (ext.length > 1 ? ext.substring(1).toUpperCase() : 'Texto');
  }

  /// Valida o conteúdo do arquivo. Dart é validado pelo arquivo em disco
  /// (o analisador precisa do contexto do projeto); JSON e Python usam o
  /// [content] recebido, então funcionam mesmo sem salvar.
  static Future<SyntaxCheckResult> check({
    required String absolutePath,
    required String content,
  }) async {
    final name = absolutePath.split(RegExp(r'[\\/]')).last.toLowerCase();
    final dot = name.lastIndexOf('.');
    final ext = dot < 0 ? '' : name.substring(dot);
    switch (ext) {
      case '.json':
        return _checkJson(content);
      case '.dart':
        return _checkDart(absolutePath);
      case '.py':
        return _checkPython(content);
      default:
        return _checkDelimiters(content);
    }
  }

  static SyntaxCheckResult _checkJson(String content) {
    try {
      jsonDecode(content);
      return const SyntaxCheckResult(
        ok: true,
        supported: true,
        message: 'JSON válido.',
      );
    } on FormatException catch (e) {
      return SyntaxCheckResult(
        ok: false,
        supported: true,
        message: 'JSON inválido: ${e.message}',
      );
    }
  }

  static Future<SyntaxCheckResult> _checkDart(String absolutePath) async {
    final result = await _run(
      'dart',
      ['analyze', absolutePath],
      timeout: const Duration(seconds: 120),
    );
    if (result == null) {
      return const SyntaxCheckResult(
        ok: false,
        supported: false,
        message: 'dart não encontrado no PATH; validação indisponível.',
      );
    }
    if (result.exitCode == 0) {
      return const SyntaxCheckResult(
        ok: true,
        supported: true,
        message: 'dart analyze sem problemas.',
      );
    }
    final output = '${result.stdout}\n${result.stderr}'.trim();
    return SyntaxCheckResult(
      ok: false,
      supported: true,
      message: _tail(output.isEmpty ? 'dart analyze falhou.' : output, 900),
    );
  }

  static Future<SyntaxCheckResult> _checkPython(String content) async {
    for (final python in const ['python', 'py']) {
      final result = await _runWithStdin(
        python,
        const ['-c', 'import sys, ast; ast.parse(sys.stdin.read())'],
        content,
        timeout: const Duration(seconds: 30),
      );
      if (result == null) continue;
      if (result.exitCode == 0) {
        return const SyntaxCheckResult(
          ok: true,
          supported: true,
          message: 'Sintaxe Python válida.',
        );
      }
      return SyntaxCheckResult(
        ok: false,
        supported: true,
        message: _tail(result.stderr.trim(), 900),
      );
    }
    return const SyntaxCheckResult(
      ok: false,
      supported: false,
      message: 'Python não encontrado no PATH; validação indisponível.',
    );
  }

  /// Verificação básica: parênteses, colchetes e chaves balanceados fora de
  /// strings. Não substitui um compilador, mas pega o erro mais comum das
  /// edições geradas por IA.
  static SyntaxCheckResult _checkDelimiters(String content) {
    const pairs = {')': '(', ']': '[', '}': '{'};
    final stack = <String>[];
    final lines = <int>[];
    var line = 1;
    String? inQuote;

    for (var i = 0; i < content.length; i++) {
      final char = content[i];
      if (char == '\n') {
        line++;
        // Strings simples não atravessam linhas na maioria das linguagens.
        if (inQuote == "'" || inQuote == '"') inQuote = null;
        continue;
      }
      if (inQuote != null) {
        if (char == r'\') {
          i++;
        } else if (char == inQuote) {
          inQuote = null;
        }
        continue;
      }
      if (char == "'" || char == '"' || char == '`') {
        inQuote = char;
        continue;
      }
      if (char == '(' || char == '[' || char == '{') {
        stack.add(char);
        lines.add(line);
      } else if (pairs.containsKey(char)) {
        if (stack.isEmpty || stack.last != pairs[char]) {
          return SyntaxCheckResult(
            ok: false,
            supported: true,
            message:
                'Delimitador "$char" sem correspondente na linha $line (verificação básica).',
          );
        }
        stack.removeLast();
        lines.removeLast();
      }
    }
    if (stack.isNotEmpty) {
      return SyntaxCheckResult(
        ok: false,
        supported: true,
        message:
            'Delimitador "${stack.last}" aberto na linha ${lines.last} não foi fechado (verificação básica).',
      );
    }
    return const SyntaxCheckResult(
      ok: true,
      supported: true,
      message: 'Delimitadores balanceados (verificação básica).',
    );
  }

  static Future<ProcessResult?> _run(
    String executable,
    List<String> args, {
    required Duration timeout,
  }) async {
    try {
      return await Process.run(executable, args).timeout(timeout);
    } catch (_) {
      return null;
    }
  }

  static Future<_StdinRunResult?> _runWithStdin(
    String executable,
    List<String> args,
    String stdinText, {
    required Duration timeout,
  }) async {
    try {
      final process = await Process.start(executable, args);
      final stdoutFuture = process.stdout.transform(utf8.decoder).join();
      final stderrFuture = process.stderr.transform(utf8.decoder).join();
      process.stdin.write(stdinText);
      await process.stdin.close();
      final exitCode = await process.exitCode.timeout(timeout);
      return _StdinRunResult(
        exitCode,
        await stdoutFuture,
        await stderrFuture,
      );
    } catch (_) {
      return null;
    }
  }

  static String _tail(String text, int limit) =>
      text.length <= limit ? text : text.substring(text.length - limit);
}

class _StdinRunResult {
  final int exitCode;
  final String stdout;
  final String stderr;

  const _StdinRunResult(this.exitCode, this.stdout, this.stderr);
}

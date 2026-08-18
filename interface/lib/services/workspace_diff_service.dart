import 'dart:convert';
import 'dart:io';

enum DiffLineType { context, addition, deletion, hunk, meta }

class DiffLine {
  final DiffLineType type;
  final String text;

  /// Número da linha no arquivo original (null em linhas adicionadas).
  final int? oldNumber;

  /// Número da linha no arquivo novo (null em linhas removidas).
  final int? newNumber;

  const DiffLine({
    required this.type,
    required this.text,
    this.oldNumber,
    this.newNumber,
  });
}

class FileDiff {
  final String relativePath;
  final List<DiffLine> lines;
  final int additions;
  final int deletions;
  final bool isNew;
  final bool truncated;

  /// Mensagem quando não foi possível gerar o diff (binário, git ausente).
  final String? note;

  const FileDiff({
    required this.relativePath,
    required this.lines,
    required this.additions,
    required this.deletions,
    this.isNew = false,
    this.truncated = false,
    this.note,
  });

  bool get hasContent => lines.isNotEmpty;
}

/// Gera o diff das alterações pendentes no workspace usando o git local.
/// Arquivos ainda não rastreados aparecem inteiros como adição, do mesmo
/// jeito que um cliente git mostra um arquivo novo.
class WorkspaceDiffService {
  static const _maxLinesPerFile = 1200;

  static Future<bool> isGitRepository(String root) async {
    final result = await _git(root, ['rev-parse', '--is-inside-work-tree']);
    return result != null && result.trim() == 'true';
  }

  /// Caminhos relativos com alterações pendentes (modificados e novos).
  static Future<List<String>> changedPaths(String root) async {
    final output = await _git(root, ['status', '--porcelain']);
    if (output == null) return const [];
    final paths = <String>[];
    for (final line in output.split(RegExp(r'[\r\n]+'))) {
      if (line.trim().isEmpty) continue;
      final path = line.length > 3 ? line.substring(3).trim() : '';
      if (path.isEmpty) continue;
      // Renomeações vêm como "antigo -> novo"; interessa o destino.
      final arrow = path.indexOf(' -> ');
      paths.add(arrow >= 0 ? path.substring(arrow + 4).trim() : path);
    }
    return paths;
  }

  static Future<List<FileDiff>> diffFor(
    String root,
    List<String> relativePaths,
  ) async {
    final diffs = <FileDiff>[];
    for (final path in relativePaths) {
      diffs.add(await _diffForFile(root, path.replaceAll('\\', '/')));
    }
    return diffs;
  }

  static Future<FileDiff> _diffForFile(String root, String path) async {
    // Working tree contra HEAD cobre alterações staged e não staged.
    final tracked = await _git(root, [
      'diff',
      '--no-color',
      '--unified=3',
      'HEAD',
      '--',
      path,
    ]);
    if (tracked != null && tracked.trim().isNotEmpty) {
      return _parseUnifiedDiff(path, tracked);
    }

    // Sem diff contra HEAD: arquivo novo (não rastreado) ou sem mudanças.
    final file = File('$root${Platform.pathSeparator}'
        '${path.replaceAll('/', Platform.pathSeparator)}');
    if (!await file.exists()) {
      return FileDiff(
        relativePath: path,
        lines: const [],
        additions: 0,
        deletions: 0,
        note: 'Arquivo removido do workspace.',
      );
    }
    try {
      final bytes = await file.readAsBytes();
      if (bytes.contains(0)) {
        return FileDiff(
          relativePath: path,
          lines: const [],
          additions: 0,
          deletions: 0,
          isNew: true,
          note: 'Arquivo binário: diff não disponível.',
        );
      }
      final content = utf8.decode(bytes, allowMalformed: true);
      final rawLines = const LineSplitter().convert(content);
      final limited = rawLines.take(_maxLinesPerFile).toList();
      return FileDiff(
        relativePath: path,
        lines: [
          for (var i = 0; i < limited.length; i++)
            DiffLine(
              type: DiffLineType.addition,
              text: limited[i],
              newNumber: i + 1,
            ),
        ],
        additions: limited.length,
        deletions: 0,
        isNew: true,
        truncated: rawLines.length > limited.length,
      );
    } catch (e) {
      return FileDiff(
        relativePath: path,
        lines: const [],
        additions: 0,
        deletions: 0,
        note: 'Não consegui ler o arquivo: $e',
      );
    }
  }

  static FileDiff _parseUnifiedDiff(String path, String raw) {
    final lines = <DiffLine>[];
    var additions = 0;
    var deletions = 0;
    var isNew = false;
    var oldNumber = 0;
    var newNumber = 0;
    var started = false;
    var truncated = false;

    for (final line in const LineSplitter().convert(raw)) {
      if (line.startsWith('new file mode')) isNew = true;
      if (!started) {
        // Pula o cabeçalho (diff --git, index, ---, +++) até o primeiro hunk.
        if (!line.startsWith('@@')) continue;
        started = true;
      }
      if (lines.length >= _maxLinesPerFile) {
        truncated = true;
        break;
      }

      if (line.startsWith('@@')) {
        final match =
            RegExp(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@').firstMatch(line);
        if (match != null) {
          oldNumber = int.parse(match.group(1)!);
          newNumber = int.parse(match.group(2)!);
        }
        lines.add(DiffLine(type: DiffLineType.hunk, text: line));
      } else if (line.startsWith('+')) {
        additions++;
        lines.add(DiffLine(
          type: DiffLineType.addition,
          text: line.substring(1),
          newNumber: newNumber++,
        ));
      } else if (line.startsWith('-')) {
        deletions++;
        lines.add(DiffLine(
          type: DiffLineType.deletion,
          text: line.substring(1),
          oldNumber: oldNumber++,
        ));
      } else if (line.startsWith('\\')) {
        // "\ No newline at end of file"
        lines.add(DiffLine(type: DiffLineType.meta, text: line));
      } else {
        lines.add(DiffLine(
          type: DiffLineType.context,
          text: line.isEmpty ? '' : line.substring(1),
          oldNumber: oldNumber++,
          newNumber: newNumber++,
        ));
      }
    }

    return FileDiff(
      relativePath: path,
      lines: lines,
      additions: additions,
      deletions: deletions,
      isNew: isNew,
      truncated: truncated,
    );
  }

  /// Restaura o arquivo ao estado do HEAD; para arquivos novos, apaga.
  static Future<void> revertFile(String root, String relativePath) async {
    final path = relativePath.replaceAll('\\', '/');
    final restored = await _git(root, ['checkout', 'HEAD', '--', path]);
    if (restored != null) return;
    final file = File('$root${Platform.pathSeparator}'
        '${path.replaceAll('/', Platform.pathSeparator)}');
    if (await file.exists()) await file.delete();
  }

  static Future<String?> _git(String root, List<String> args) async {
    try {
      final result = await Process.run(
        'git',
        args,
        workingDirectory: root,
        stdoutEncoding: utf8,
        stderrEncoding: utf8,
      ).timeout(const Duration(seconds: 20));
      if (result.exitCode != 0) return null;
      return '${result.stdout}';
    } catch (_) {
      return null;
    }
  }
}

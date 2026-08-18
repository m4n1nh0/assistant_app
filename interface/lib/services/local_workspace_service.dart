import 'dart:convert';
import 'dart:io';

import 'project_discovery_service.dart';

class WorkspaceInspectionException implements Exception {
  final String message;

  const WorkspaceInspectionException(this.message);

  @override
  String toString() => message;
}

class WorkspaceSnapshot {
  final String name;
  final String path;
  final List<String> markers;
  final List<String> tree;
  final List<WorkspaceFileSnippet> files;
  final int scannedFiles;
  final bool treeTruncated;
  final bool contentTruncated;

  const WorkspaceSnapshot({
    required this.name,
    required this.path,
    required this.markers,
    required this.tree,
    required this.files,
    required this.scannedFiles,
    required this.treeTruncated,
    required this.contentTruncated,
  });

  String toPromptText({
    required String userRequest,
    String actionName = 'Inspecionar workspace local',
    bool allowEdits = false,
  }) {
    final editInstruction = allowEdits
        ? 'O usuario autorizou a interface a editar arquivos somente dentro do caminho informado. '
            'Quando quiser que a interface aplique edicoes, responda com um unico bloco fenced chamado workspace_edits contendo JSON neste formato: '
            '{"summary":"resumo curto","edits":[...]}. Cada item de edits usa uma destas formas: '
            '{"path":"caminho/relativo.ext","content":"conteudo completo do arquivo"} para criar ou reescrever um arquivo inteiro, ou '
            '{"path":"caminho/relativo.ext","find":"trecho exato atual","replace":"trecho novo"} para alterar apenas um trecho. '
            'Prefira find/replace para mudancas pequenas em arquivos grandes. '
            'No find, copie o trecho exatamente como esta no arquivo (indentacao inclusive) e inclua linhas suficientes para ele ser unico no arquivo. '
            'Use apenas caminhos relativos dentro do workspace.'
        : 'O usuario ainda nao autorizou edicao. Quando sugerir edicoes, cite caminhos de arquivo e alteracoes objetivas.';
    final buffer = StringBuffer()
      ..writeln('Contexto local do workspace capturado pela interface.')
      ..writeln('Acao: $actionName')
      ..writeln('Workspace: $name')
      ..writeln('Caminho: $path')
      ..writeln('Permissao local de edicao: ${allowEdits ? "sim" : "nao"}')
      ..writeln('Arquivos escaneados: $scannedFiles')
      ..writeln(
          'Marcadores: ${markers.isEmpty ? "(nenhum)" : markers.join(", ")}')
      ..writeln('Arvore truncada: ${treeTruncated ? "sim" : "nao"}')
      ..writeln('Conteudo truncado: ${contentTruncated ? "sim" : "nao"}')
      ..writeln()
      ..writeln('Pedido original do usuario:')
      ..writeln(userRequest.trim().isEmpty ? '(sem texto)' : userRequest.trim())
      ..writeln()
      ..writeln('Arvore de arquivos:')
      ..writeln(tree.isEmpty ? '(sem arquivos listaveis)' : tree.join('\n'));

    if (files.isNotEmpty) {
      buffer
        ..writeln()
        ..writeln('Arquivos relevantes lidos conforme o pedido:');
      for (final file in files) {
        buffer
          ..writeln()
          ..writeln(
              '--- ${file.relativePath}${file.truncated ? " (truncado)" : ""} ---')
          ..writeln(
              file.content.trim().isEmpty ? '(vazio)' : file.content.trim());
      }
    }

    buffer
      ..writeln()
      ..writeln('Instrucao para a IA:')
      ..writeln(
        'Use somente esse contexto local e o historico da conversa para analisar o projeto. '
        'Se precisar de mais arquivos, peca para a interface ler caminhos especificos. '
        'Quando sugerir comandos, explique o objetivo e prefira comandos seguros de diagnostico/teste. '
        '$editInstruction',
      );

    return buffer.toString().trim();
  }
}

class WorkspaceFileSnippet {
  final String relativePath;
  final String content;
  final bool truncated;

  const WorkspaceFileSnippet({
    required this.relativePath,
    required this.content,
    required this.truncated,
  });
}

class WorkspaceFileEdit {
  final String relativePath;

  /// Conteúdo completo do arquivo (cria ou reescreve o arquivo inteiro).
  final String? content;

  /// Trecho exato a localizar no arquivo para edição parcial.
  final String? find;

  /// Novo trecho no lugar de [find]; vazio remove o trecho.
  final String? replace;

  const WorkspaceFileEdit({
    required this.relativePath,
    this.content,
    this.find,
    this.replace,
  });

  bool get isPartial => find != null && find!.isNotEmpty;
}

class WorkspaceEditResult {
  final String relativePath;
  final int bytesWritten;
  final bool partial;

  const WorkspaceEditResult({
    required this.relativePath,
    required this.bytesWritten,
    this.partial = false,
  });
}

class LocalWorkspaceService {
  static const _maxTreeFiles = 320;
  static const _maxFileChars = 8000;
  static const _maxTotalChars = 26000;
  static const _contentScanChars = 12000;

  static final _importantNames = <String>{
    'readme.md',
    'docker-compose.yml',
    'docker-compose.yaml',
    'pubspec.yaml',
    'package.json',
    'pyproject.toml',
    'requirements.txt',
    'main.py',
    'app.py',
    'dockerfile',
  };

  static final _importantRelativePaths = <String>{
    'backend/readme.md',
    'interface/readme.md',
    'backend/app/main.py',
    'backend/app/routers/chat.py',
    'backend/app/core/config.py',
    'interface/lib/main.dart',
    'interface/lib/widgets/chat_panel.dart',
    'interface/lib/services/api_service.dart',
  };

  static final _textExtensions = <String>{
    '.dart',
    '.py',
    '.md',
    '.txt',
    '.yaml',
    '.yml',
    '.json',
    '.toml',
    '.ini',
    '.env.example',
    '.html',
    '.css',
    '.js',
    '.ts',
    '.tsx',
    '.jsx',
    '.sql',
    '.sh',
    '.ps1',
    '.bat',
    '.cmd',
    '.dockerfile',
  };

  static Future<String?> pickDirectory({String initialPath = ''}) async {
    if (Platform.isWindows) {
      return _pickDirectoryWindows(initialPath: initialPath);
    }
    if (Platform.isMacOS) {
      return _pickDirectoryMac(initialPath: initialPath);
    }
    if (Platform.isLinux) {
      return _pickDirectoryLinux();
    }
    return null;
  }

  static Future<WorkspaceSnapshot> inspectWorkspace({
    String query = '',
    String rootPath = '',
    int maxTreeFiles = _maxTreeFiles,
    int maxFileChars = _maxFileChars,
    int maxTotalChars = _maxTotalChars,
  }) async {
    final root = await _resolveRoot(query: query, rootPath: rootPath);
    final rootDirectory = Directory(root);
    if (!await rootDirectory.exists()) {
      throw WorkspaceInspectionException('Workspace nao encontrado: $root');
    }

    final markers = await _markers(rootDirectory);
    final treeResult = await _buildTree(rootDirectory, maxFiles: maxTreeFiles);
    final snippets = await _readRelevantFiles(
      rootDirectory,
      treeResult.files,
      query: query,
      maxFileChars: maxFileChars,
      maxTotalChars: maxTotalChars,
    );

    return WorkspaceSnapshot(
      name: _basename(rootDirectory.path),
      path: rootDirectory.path,
      markers: markers,
      tree: treeResult.lines,
      files: snippets.files,
      scannedFiles: treeResult.totalFiles,
      treeTruncated: treeResult.truncated,
      contentTruncated: snippets.truncated,
    );
  }

  static Future<List<WorkspaceEditResult>> applyEdits({
    required String rootPath,
    required List<WorkspaceFileEdit> edits,
  }) async {
    final root = Directory(rootPath).absolute;
    if (!await root.exists()) {
      throw WorkspaceInspectionException(
          'Workspace de edicao nao encontrado: $rootPath');
    }
    if (edits.isEmpty) {
      throw const WorkspaceInspectionException('Nenhuma edicao recebida.');
    }

    final results = <WorkspaceEditResult>[];
    for (final edit in edits) {
      final target = _resolveEditableFile(root, edit.relativePath);
      final content = edit.isPartial
          ? await _applyPartialEdit(target, edit)
          : edit.content;
      if (content == null || content.isEmpty) {
        throw WorkspaceInspectionException(
          'Edicao sem conteudo para ${edit.relativePath}.',
        );
      }
      if (content.length > 220000) {
        throw WorkspaceInspectionException(
          'Edicao muito grande para ${edit.relativePath}.',
        );
      }
      final parent = target.parent;
      if (!await parent.exists()) {
        await parent.create(recursive: true);
      }
      await target.writeAsString(content, encoding: utf8);
      results.add(WorkspaceEditResult(
        relativePath: edit.relativePath.replaceAll('\\', '/'),
        bytesWritten: utf8.encode(content).length,
        partial: edit.isPartial,
      ));
    }
    return results;
  }

  /// Substitui um trecho exato e único do arquivo. Falha com mensagem clara
  /// quando o trecho não existe ou aparece mais de uma vez, para a IA
  /// reenviar com mais contexto em vez de gravar no lugar errado.
  static Future<String> _applyPartialEdit(
    File target,
    WorkspaceFileEdit edit,
  ) async {
    if (!await target.exists()) {
      throw WorkspaceInspectionException(
        'Arquivo nao encontrado para edicao parcial: ${edit.relativePath}. '
        'Para criar um arquivo novo, use o formato com "content".',
      );
    }
    final original = await target.readAsString();
    var find = edit.find!;
    var replace = edit.replace ?? '';
    var occurrences = _countOccurrences(original, find);
    if (occurrences == 0 &&
        original.contains('\r\n') &&
        !find.contains('\r')) {
      // A IA costuma responder com \n mesmo quando o arquivo usa \r\n.
      find = find.replaceAll('\n', '\r\n');
      replace = replace.replaceAll('\n', '\r\n');
      occurrences = _countOccurrences(original, find);
    }
    if (occurrences == 0) {
      throw WorkspaceInspectionException(
        'Trecho nao encontrado em ${edit.relativePath}. '
        'Reenvie o campo find exatamente como esta no arquivo.',
      );
    }
    if (occurrences > 1) {
      throw WorkspaceInspectionException(
        'Trecho ambiguo em ${edit.relativePath} ($occurrences ocorrencias). '
        'Inclua mais linhas de contexto no campo find.',
      );
    }
    return original.replaceFirst(find, replace);
  }

  static int _countOccurrences(String text, String pattern) {
    if (pattern.isEmpty) return 0;
    var count = 0;
    var index = text.indexOf(pattern);
    while (index != -1) {
      count++;
      index = text.indexOf(pattern, index + pattern.length);
    }
    return count;
  }

  static Future<String> _resolveRoot({
    required String query,
    required String rootPath,
  }) async {
    final explicit = rootPath.trim();
    if (explicit.isNotEmpty) return Directory(explicit).absolute.path;

    final found = await ProjectDiscoveryService.findProject(query);
    if (found != null) return Directory(found.path).absolute.path;

    final current = await _bestProjectFromCurrentDirectory();
    if (current != null) return current.path;

    throw const WorkspaceInspectionException(
      'Nao encontrei um workspace local. Abra o projeto pela IDE ou informe o nome/pasta do projeto.',
    );
  }

  static Future<String?> _pickDirectoryWindows({
    required String initialPath,
  }) async {
    final escapedInitial = initialPath.replaceAll("'", "''");
    final script = '''
Add-Type -AssemblyName System.Windows.Forms
\$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
\$dialog.Description = 'Selecione a pasta do workspace'
\$dialog.ShowNewFolderButton = \$false
\$initial = '$escapedInitial'
if (\$initial -and (Test-Path -LiteralPath \$initial -PathType Container)) {
  \$dialog.SelectedPath = \$initial
}
if (\$dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  Write-Output \$dialog.SelectedPath
}
''';
    final result = await Process.run(
      'powershell',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
      runInShell: false,
    );
    if (result.exitCode != 0) return null;
    final path = result.stdout.toString().trim();
    return path.isEmpty ? null : path;
  }

  static Future<String?> _pickDirectoryMac(
      {required String initialPath}) async {
    const prompt = 'Selecione a pasta do workspace';
    final escapedPrompt = prompt.replaceAll('"', '\\"');
    final script = initialPath.trim().isEmpty
        ? 'POSIX path of (choose folder with prompt "$escapedPrompt")'
        : 'POSIX path of (choose folder with prompt "$escapedPrompt" default location POSIX file "${initialPath.replaceAll('"', '\\"')}")';
    final result = await Process.run('osascript', ['-e', script]);
    if (result.exitCode != 0) return null;
    final path = result.stdout.toString().trim();
    return path.isEmpty ? null : path;
  }

  static Future<String?> _pickDirectoryLinux() async {
    final result = await Process.run(
      'zenity',
      [
        '--file-selection',
        '--directory',
        '--title=Selecione a pasta do workspace'
      ],
    );
    if (result.exitCode != 0) return null;
    final path = result.stdout.toString().trim();
    return path.isEmpty ? null : path;
  }

  static File _resolveEditableFile(Directory root, String relativePath) {
    final raw = relativePath.trim().replaceAll('\\', '/');
    if (raw.isEmpty) {
      throw const WorkspaceInspectionException('Caminho de arquivo vazio.');
    }
    if (raw.contains('\u0000') ||
        raw.startsWith('/') ||
        RegExp(r'^[a-zA-Z]:').hasMatch(raw)) {
      throw WorkspaceInspectionException(
          'Caminho absoluto nao permitido: $relativePath');
    }
    final segments = raw
        .split('/')
        .where((part) => part.trim().isNotEmpty && part != '.')
        .toList();
    if (segments.isEmpty || segments.any((part) => part == '..')) {
      throw WorkspaceInspectionException(
          'Caminho fora do workspace nao permitido: $relativePath');
    }
    final normalized = segments.join('/');
    if (_isSensitivePath(normalized)) {
      throw WorkspaceInspectionException(
          'Arquivo sensivel nao pode ser editado: $relativePath');
    }

    var current = root.path;
    for (final segment in segments) {
      current = _join(current, segment);
    }
    return File(current).absolute;
  }

  static Future<Directory?> _bestProjectFromCurrentDirectory() async {
    var dir = Directory.current.absolute;
    Directory? best;
    var bestScore = 0;

    for (var depth = 0; depth < 8; depth++) {
      final score = await _projectScore(dir);
      if (score > bestScore) {
        best = dir;
        bestScore = score;
      }
      final parent = dir.parent.absolute;
      if (parent.path == dir.path) break;
      dir = parent;
    }

    return bestScore > 0 ? best : null;
  }

  static Future<int> _projectScore(Directory dir) async {
    var score = 0;
    if (await File(_join(dir.path, 'docker-compose.yml')).exists()) score += 50;
    if (await Directory(_join(dir.path, 'backend')).exists()) score += 25;
    if (await Directory(_join(dir.path, 'interface')).exists()) score += 25;
    if (await File(_join(dir.path, 'pubspec.yaml')).exists()) score += 35;
    if (await File(_join(dir.path, 'package.json')).exists()) score += 35;
    if (await File(_join(dir.path, 'pyproject.toml')).exists()) score += 35;
    if (await Directory(_join(dir.path, '.git')).exists()) score += 20;
    return score;
  }

  static Future<List<String>> _markers(Directory root) async {
    final markers = <String>[];
    for (final marker in ProjectDiscoveryService.projectMarkers) {
      final path = _join(root.path, marker);
      if (await File(path).exists() || await Directory(path).exists()) {
        markers.add(marker);
      }
    }
    return markers;
  }

  static Future<_TreeResult> _buildTree(
    Directory root, {
    required int maxFiles,
  }) async {
    final lines = <String>[];
    final files = <File>[];
    var totalFiles = 0;
    var truncated = false;

    Future<void> visit(Directory dir, int depth) async {
      if (truncated || depth > 5) return;
      final entries = <FileSystemEntity>[];
      try {
        await for (final entry in dir.list(followLinks: false)) {
          final name = _basename(entry.path);
          if (_shouldSkip(name, entry is Directory)) continue;
          entries.add(entry);
        }
      } catch (_) {
        return;
      }

      entries.sort((a, b) {
        final aDir = a is Directory;
        final bDir = b is Directory;
        if (aDir != bDir) return aDir ? -1 : 1;
        return _basename(a.path).toLowerCase().compareTo(
              _basename(b.path).toLowerCase(),
            );
      });

      for (final entry in entries) {
        if (truncated) return;
        final relative = _relativePath(root.path, entry.path);
        final indent = '  ' * depth;
        if (entry is Directory) {
          lines.add('$indent${_basename(entry.path)}/');
          await visit(entry, depth + 1);
        } else if (entry is File) {
          totalFiles++;
          if (files.length >= maxFiles) {
            truncated = true;
            return;
          }
          files.add(entry);
          lines.add('$indent${relative.replaceAll('\\', '/')}');
        }
      }
    }

    await visit(root, 0);
    return _TreeResult(
      lines: lines,
      files: files,
      totalFiles: totalFiles,
      truncated: truncated,
    );
  }

  static Future<_SnippetResult> _readRelevantFiles(
    Directory root,
    List<File> treeFiles, {
    required String query,
    required int maxFileChars,
    required int maxTotalChars,
  }) async {
    final terms = _queryTerms(query);
    final fileRefs = _fileReferences(query);
    final candidates = <_FileCandidate>[];
    final seen = <String>{};

    for (final file in treeFiles) {
      final relative =
          _relativePath(root.path, file.path).replaceAll('\\', '/');
      final lowerRelative = relative.toLowerCase();
      final name = _basename(file.path).toLowerCase();
      if (_isSensitivePath(lowerRelative)) continue;
      if (!await _looksTextFile(file)) continue;

      final key = file.absolute.path.toLowerCase();
      if (!seen.add(key)) continue;

      final important = _importantNames.contains(name) ||
          _importantRelativePaths.contains(lowerRelative);
      var score = important ? 90 : 0;
      score += _pathRelevanceScore(relative, terms, fileRefs);

      if (terms.isNotEmpty) {
        final sample = await _readText(file, _contentScanChars);
        score += _contentRelevanceScore(sample.content, terms);
      }

      if (score > 0) {
        candidates.add(
            _FileCandidate(file: file, relativePath: relative, score: score));
      }
    }

    candidates.sort((a, b) {
      final score = b.score.compareTo(a.score);
      if (score != 0) return score;
      return a.relativePath
          .toLowerCase()
          .compareTo(b.relativePath.toLowerCase());
    });

    final snippets = <WorkspaceFileSnippet>[];
    var remaining = maxTotalChars;
    var truncated = false;

    for (final candidate in candidates.take(24)) {
      if (remaining <= 0) {
        truncated = true;
        break;
      }
      final file = candidate.file;
      final readLimit = remaining < maxFileChars ? remaining : maxFileChars;
      final read = await _readText(file, readLimit);
      remaining -= read.content.length;
      truncated = truncated || read.truncated;
      snippets.add(WorkspaceFileSnippet(
        relativePath: _relativePath(root.path, file.path).replaceAll('\\', '/'),
        content: read.content,
        truncated: read.truncated,
      ));
    }

    return _SnippetResult(files: snippets, truncated: truncated);
  }

  static List<String> _queryTerms(String query) {
    final normalized = _normalizeText(query);
    final stopWords = {
      'a',
      'o',
      'os',
      'as',
      'um',
      'uma',
      'de',
      'do',
      'da',
      'dos',
      'das',
      'em',
      'no',
      'na',
      'nos',
      'nas',
      'e',
      'ou',
      'para',
      'por',
      'com',
      'que',
      'me',
      'meu',
      'minha',
      'esse',
      'essa',
      'este',
      'esta',
      'projeto',
      'codigo',
      'arquivo',
      'arquivos',
      'pasta',
      'subpasta',
      'subpastas',
      'analise',
      'analisar',
      'corrija',
      'corrigir',
      'ajuste',
      'ajustar',
      'implemente',
      'implementar',
      'edite',
      'editar',
      'verifique',
      'verificar',
    };
    final terms = normalized
        .split(RegExp(r'[^a-z0-9_.\/-]+'))
        .map((item) => item.trim())
        .where((item) => item.length >= 2 && !stopWords.contains(item))
        .toSet()
        .toList();
    return terms.take(40).toList();
  }

  static List<String> _fileReferences(String query) {
    final refs = <String>{};
    final matches = RegExp(r'[\w./\\-]+\.[a-zA-Z0-9]{1,12}').allMatches(query);
    for (final match in matches) {
      final value = match.group(0);
      if (value == null) continue;
      final normalized = _normalizePath(value);
      if (normalized.isNotEmpty) refs.add(normalized);
    }
    return refs.toList();
  }

  static int _pathRelevanceScore(
    String relativePath,
    List<String> terms,
    List<String> fileRefs,
  ) {
    final path = _normalizePath(relativePath);
    final name = _normalizeText(_basename(relativePath));
    final ext = _extension(relativePath).toLowerCase();
    var score = 0;

    for (final ref in fileRefs) {
      if (path == ref || path.endsWith('/$ref') || path.contains(ref)) {
        score += 160;
      }
    }

    for (final term in terms) {
      if (term.length < 2) continue;
      if (name == term) score += 80;
      if (name.contains(term)) score += 55;
      if (path.contains(term)) score += 35;
      score += _languageOrAreaScore(term, path, ext);
    }

    return score;
  }

  static int _languageOrAreaScore(String term, String path, String ext) {
    switch (term) {
      case 'dart':
      case 'flutter':
        return ext == '.dart' || path.contains('interface/lib') ? 35 : 0;
      case 'python':
      case 'py':
      case 'fastapi':
        return ext == '.py' || path.contains('backend/app') ? 35 : 0;
      case 'backend':
      case 'api':
      case 'router':
      case 'endpoint':
        return path.contains('backend/') || path.contains('/routers/') ? 45 : 0;
      case 'frontend':
      case 'interface':
      case 'tela':
      case 'widget':
        return path.contains('interface/') || ext == '.dart' ? 45 : 0;
      case 'docker':
      case 'compose':
      case 'container':
      case 'ollama':
        return path.contains('docker') || path.contains('ollama') ? 80 : 0;
      case 'readme':
      case 'documentacao':
      case 'doc':
        return ext == '.md' || path.contains('docs/') ? 40 : 0;
      case 'config':
      case 'settings':
      case 'env':
        return {'.yaml', '.yml', '.json', '.toml', '.ini'}.contains(ext)
            ? 35
            : 0;
      case 'teste':
      case 'testes':
      case 'test':
      case 'tests':
        return path.contains('test') || path.contains('tests') ? 55 : 0;
    }
    return 0;
  }

  static int _contentRelevanceScore(String content, List<String> terms) {
    final normalized = _normalizeText(content);
    if (normalized.isEmpty) return 0;
    var score = 0;
    for (final term in terms) {
      if (term.length < 3) continue;
      final matches = RegExp(r'\b' + RegExp.escape(term) + r'\b')
          .allMatches(normalized)
          .length;
      if (matches > 0) {
        final capped = matches > 5 ? 5 : matches;
        score += capped * 8;
      }
    }
    return score;
  }

  static Future<bool> _looksTextFile(File file) async {
    final name = _basename(file.path).toLowerCase();
    if (name == 'dockerfile') return true;
    final ext = _extension(name);
    if (!_textExtensions.contains(ext)) return false;
    try {
      final stat = await file.stat();
      return stat.size <= 1024 * 1024;
    } catch (_) {
      return false;
    }
  }

  static Future<_ReadTextResult> _readText(File file, int maxChars) async {
    final raf = await file.open();
    try {
      final bytes = await raf.read(maxChars + 1024);
      final content = utf8.decode(bytes, allowMalformed: true);
      final truncated = content.length > maxChars;
      return _ReadTextResult(
        content: truncated ? content.substring(0, maxChars) : content,
        truncated: truncated,
      );
    } finally {
      await raf.close();
    }
  }

  static bool _shouldSkip(String name, bool isDirectory) {
    final lower = name.toLowerCase();
    if (isDirectory) {
      return lower == '.git' ||
          lower == '.dart_tool' ||
          lower == '.idea' ||
          lower == '.gradle' ||
          lower == '.venv' ||
          lower == 'venv' ||
          lower == 'node_modules' ||
          lower == 'build' ||
          lower == 'dist' ||
          lower == 'target' ||
          lower == '__pycache__';
    }
    return _isSensitivePath(lower) ||
        lower.endsWith('.png') ||
        lower.endsWith('.jpg') ||
        lower.endsWith('.jpeg') ||
        lower.endsWith('.gif') ||
        lower.endsWith('.webp') ||
        lower.endsWith('.ico') ||
        lower.endsWith('.pdf') ||
        lower.endsWith('.zip') ||
        lower.endsWith('.exe') ||
        lower.endsWith('.dll');
  }

  static bool _isSensitivePath(String path) {
    final lower = path.toLowerCase().replaceAll('\\', '/');
    final name = lower.split('/').last;
    if (name == '.env' || name.startsWith('.env.')) return true;
    return lower.contains('/secrets/') ||
        lower.contains('/credentials/') ||
        name.contains('secret') ||
        name.contains('token') ||
        name.endsWith('.pem') ||
        name.endsWith('.key') ||
        name == 'id_rsa' ||
        name == 'id_dsa';
  }

  static String _join(String left, String right) =>
      '$left${Platform.pathSeparator}$right';

  static String _basename(String path) {
    final normalized = path.replaceAll('/', '\\');
    final parts = normalized.split('\\').where((item) => item.isNotEmpty);
    return parts.isEmpty ? path : parts.last;
  }

  static String _extension(String name) {
    final index = name.lastIndexOf('.');
    if (index <= 0) return '';
    return name.substring(index);
  }

  static String _normalizePath(String text) =>
      _normalizeText(text).replaceAll('\\', '/');

  static String _normalizeText(String text) {
    const accentMap = {
      'á': 'a',
      'à': 'a',
      'â': 'a',
      'ã': 'a',
      'ä': 'a',
      'é': 'e',
      'è': 'e',
      'ê': 'e',
      'ë': 'e',
      'í': 'i',
      'ì': 'i',
      'î': 'i',
      'ï': 'i',
      'ó': 'o',
      'ò': 'o',
      'ô': 'o',
      'õ': 'o',
      'ö': 'o',
      'ú': 'u',
      'ù': 'u',
      'û': 'u',
      'ü': 'u',
      'ç': 'c',
    };
    final buffer = StringBuffer();
    for (final rune in text.toLowerCase().runes) {
      final char = String.fromCharCode(rune);
      buffer.write(accentMap[char] ?? char);
    }
    return buffer.toString();
  }

  static String _relativePath(String root, String path) {
    final rootNormalized = Directory(root).absolute.path;
    final pathNormalized = File(path).absolute.path;
    final rootLower = rootNormalized.toLowerCase();
    final pathLower = pathNormalized.toLowerCase();
    if (pathLower == rootLower) return '.';
    final prefix = rootLower.endsWith(Platform.pathSeparator)
        ? rootLower
        : '$rootLower${Platform.pathSeparator}';
    if (pathLower.startsWith(prefix)) {
      return pathNormalized.substring(prefix.length);
    }
    return path;
  }
}

class _TreeResult {
  final List<String> lines;
  final List<File> files;
  final int totalFiles;
  final bool truncated;

  const _TreeResult({
    required this.lines,
    required this.files,
    required this.totalFiles,
    required this.truncated,
  });
}

class _SnippetResult {
  final List<WorkspaceFileSnippet> files;
  final bool truncated;

  const _SnippetResult({
    required this.files,
    required this.truncated,
  });
}

class _FileCandidate {
  final File file;
  final String relativePath;
  final int score;

  const _FileCandidate({
    required this.file,
    required this.relativePath,
    required this.score,
  });
}

class _ReadTextResult {
  final String content;
  final bool truncated;

  const _ReadTextResult({
    required this.content,
    required this.truncated,
  });
}

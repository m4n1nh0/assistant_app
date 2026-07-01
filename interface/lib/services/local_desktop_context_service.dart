import 'dart:convert';
import 'dart:io';

import 'api_service.dart';
import 'project_discovery_service.dart';

class LocalDesktopContextException implements Exception {
  final String message;

  const LocalDesktopContextException(this.message);

  @override
  String toString() => message;
}

class LocalDesktopContextService {
  static const int maxContextChars = 12000;

  static Future<List<DesktopWindowInfo>> listWindows() async {
    if (!Platform.isWindows) {
      throw const LocalDesktopContextException(
        'Captura local de janelas disponivel apenas no Windows.',
      );
    }

    final result = await _runPowerShell(_listWindowsScript());
    final raw = result.stdout.toString().trim();
    if (result.exitCode != 0) {
      throw LocalDesktopContextException(_errorText(result));
    }
    if (raw.isEmpty) return const [];

    final decoded = jsonDecode(raw);
    final items = decoded is List ? decoded : [decoded];
    return items
        .whereType<Map>()
        .map((item) => DesktopWindowInfo.fromJson(
              item.map((key, value) => MapEntry(key.toString(), value)),
            ))
        .where((window) => window.title.trim().isNotEmpty)
        .toList();
  }

  static Future<DesktopWindowContext> getWindowContext(
    DesktopWindowInfo window,
  ) async {
    if (!Platform.isWindows) {
      throw const LocalDesktopContextException(
        'Captura local de janelas disponivel apenas no Windows.',
      );
    }

    final result = await _runPowerShell(
      _windowTextScript(),
      environment: {'ASSISTANT_WINDOW_HANDLE': window.id},
      timeoutSeconds: 12,
    );
    if (result.exitCode != 0) {
      throw LocalDesktopContextException(_errorText(result));
    }

    final raw = result.stdout.toString().trim();
    var text = '';
    var truncated = false;
    if (raw.isNotEmpty) {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        text = decoded['text']?.toString() ?? '';
        truncated = decoded['truncated'] == true;
      }
    }

    final warning = text.trim().isEmpty
        ? 'A janela nao expos texto via acessibilidade.'
        : null;
    final fallback = await _fallbackContentForWindow(window, text);
    if (fallback != null) {
      return DesktopWindowContext(
        window: window,
        text: fallback.text,
        extractionMethod: fallback.method,
        warning: fallback.warning,
        truncated: fallback.truncated,
        contextPrompt: _contextPrompt(
          window,
          fallback.text,
          fallback.truncated,
          sourcePath: fallback.sourcePath,
          extractionMethod: fallback.method,
        ),
      );
    }

    return DesktopWindowContext(
      window: window,
      text: text,
      extractionMethod: text.trim().isEmpty ? 'metadata' : 'uia-local',
      warning: warning,
      truncated: truncated,
      contextPrompt: _contextPrompt(
        window,
        text,
        truncated,
        extractionMethod: text.trim().isEmpty ? 'metadata' : 'uia-local',
      ),
    );
  }

  static Future<ProcessResult> _runPowerShell(
    String script, {
    Map<String, String>? environment,
    int timeoutSeconds = 8,
  }) =>
      Process.run(
        'powershell.exe',
        ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
        environment: environment,
      ).timeout(Duration(seconds: timeoutSeconds));

  static String _errorText(ProcessResult result) {
    final stderr = result.stderr.toString().trim();
    final stdout = result.stdout.toString().trim();
    if (stderr.isNotEmpty) return stderr;
    if (stdout.isNotEmpty) return stdout;
    return 'Processo retornou ${result.exitCode}';
  }

  static String _contextPrompt(
    DesktopWindowInfo window,
    String text,
    bool truncated, {
    String? sourcePath,
    String extractionMethod = 'metadata',
  }) {
    final buffer = StringBuffer()
      ..writeln('Contexto da janela escolhida pelo usuario.')
      ..writeln('Titulo: ${window.displayTitle}')
      ..writeln('Processo: ${window.displayProcess} (PID ${window.processId})');
    if (window.executablePath.trim().isNotEmpty) {
      buffer.writeln('Executavel: ${window.executablePath}');
    }
    buffer.writeln('Metodo de extracao: $extractionMethod');
    if (sourcePath != null && sourcePath.trim().isNotEmpty) {
      buffer.writeln('Arquivo lido: $sourcePath');
    }
    buffer
      ..writeln('Janela ativa: ${window.isActive ? 'sim' : 'nao'}')
      ..writeln();
    if (text.trim().isNotEmpty) {
      buffer
        ..writeln('Texto acessivel da janela:')
        ..writeln(text.trim());
      if (truncated) buffer.writeln('...[contexto truncado]');
    } else {
      buffer.writeln('Texto acessivel da janela: nao disponivel.');
    }
    return buffer.toString().trim();
  }

  static Future<_FallbackContent?> _fallbackContentForWindow(
    DesktopWindowInfo window,
    String currentText,
  ) async {
    if (_looksUsefulEditorText(currentText)) return null;

    final process = window.processName.toLowerCase();
    if (process.contains('winword')) {
      final word = await _readWordDocument(window);
      if (word != null && word.text.trim().isNotEmpty) return word;
    }

    final fileContext = await _readLikelyFileFromWindowTitle(window);
    if (fileContext != null && fileContext.text.trim().isNotEmpty) {
      return fileContext;
    }
    return null;
  }

  static bool _looksUsefulEditorText(String text) {
    final clean = text.trim();
    if (clean.length >= 160) return true;
    final lines = clean
        .split(RegExp(r'\r?\n'))
        .map((line) => line.trim().toLowerCase())
        .where((line) => line.isNotEmpty)
        .toList();
    if (lines.length >= 8) return true;
    const chromeTerms = {
      'minimize',
      'maximize',
      'restore',
      'close',
      'visual studio code',
      'file',
      'edit',
      'selection',
      'view',
      'go',
      'run',
      'terminal',
      'help',
    };
    final meaningful =
        lines.where((line) => !chromeTerms.contains(line)).join(' ').trim();
    return meaningful.length >= 80;
  }

  static Future<_FallbackContent?> _readLikelyFileFromWindowTitle(
    DesktopWindowInfo window,
  ) async {
    final fileNames = _fileNamesFromTitle(window.title);
    if (fileNames.isEmpty) return null;

    final workspaceHints = _workspaceHintsFromTitle(window.title, fileNames);
    final roots = await _searchRoots(workspaceHints);
    for (final fileName in fileNames) {
      final file = await _findBestFile(fileName, roots, workspaceHints);
      if (file == null) continue;
      final content = await _readTextFile(file);
      if (content == null || content.text.trim().isEmpty) continue;
      return _FallbackContent(
        text: content.text,
        method: 'file-inferido',
        sourcePath: file.path,
        truncated: content.truncated,
        warning:
            'Texto lido diretamente do arquivo inferido pelo titulo da janela.',
      );
    }
    return null;
  }

  static Future<_FallbackContent?> _readWordDocument(
    DesktopWindowInfo window,
  ) async {
    final result = await _runPowerShell(
      _wordDocumentScript(),
      environment: {
        'ASSISTANT_WINDOW_TITLE': window.title,
      },
      timeoutSeconds: 12,
    );
    if (result.exitCode != 0 || result.stdout.toString().trim().isEmpty) {
      return null;
    }
    try {
      final decoded = jsonDecode(result.stdout.toString());
      if (decoded is! Map) return null;
      final text = decoded['text']?.toString() ?? '';
      if (text.trim().isEmpty) return null;
      return _FallbackContent(
        text: text,
        method: 'word-com',
        sourcePath: decoded['path']?.toString(),
        truncated: decoded['truncated'] == true,
        warning: 'Texto lido do documento aberto no Word.',
      );
    } catch (_) {
      return null;
    }
  }

  static List<String> _fileNamesFromTitle(String title) {
    final matches = RegExp(
      r'(?<![\\/:*?"<>|])([\w .()@+\-]+?\.(?:dart|py|js|jsx|ts|tsx|java|cs|cpp|c|h|hpp|go|rs|php|rb|swift|kt|kts|html|css|scss|json|yaml|yml|toml|xml|sql|sh|ps1|bat|cmd|md|markdown|txt|log|csv|ini|env|docx|doc|rtf))\b',
      caseSensitive: false,
    ).allMatches(title);
    return matches
        .map((match) => match.group(1)?.trim())
        .whereType<String>()
        .where((item) => item.isNotEmpty)
        .toSet()
        .toList();
  }

  static List<String> _workspaceHintsFromTitle(
    String title,
    List<String> fileNames,
  ) {
    var clean = title;
    for (final name in fileNames) {
      clean = clean.replaceAll(name, ' ');
    }
    final parts = clean
        .split(RegExp(r'\s+-\s+|\s+\u2014\s+|\s+\u2013\s+'))
        .map((item) => item.trim())
        .where((item) =>
            item.length >= 3 &&
            !RegExp(r'visual studio code|notepad|word|bloco de notas',
                    caseSensitive: false)
                .hasMatch(item))
        .toList();
    return parts.toSet().toList();
  }

  static Future<List<Directory>> _searchRoots(
      List<String> workspaceHints) async {
    final roots = <String>{};
    void add(String? path) {
      if (path == null || path.trim().isEmpty) return;
      roots.add(Directory(path).absolute.path);
    }

    add(Directory.current.path);
    var current = Directory.current.absolute;
    for (var i = 0; i < 4; i++) {
      add(current.path);
      final parent = current.parent;
      if (parent.path == current.path) break;
      current = parent;
    }

    final env = Platform.environment;
    final user = env['USERPROFILE'] ?? env['HOME'];
    if (user != null && user.isNotEmpty) {
      add('$user\\vscode-projects');
      add('$user\\Documents');
      add('$user\\Desktop');
      add('$user\\Downloads');
      add('$user\\OneDrive\\Documents');
    }

    for (final hint in workspaceHints) {
      final project = await ProjectDiscoveryService.findProject(hint);
      if (project != null) add(project.path);
    }
    return roots.map(Directory.new).toList();
  }

  static Future<File?> _findBestFile(
    String fileName,
    List<Directory> roots,
    List<String> workspaceHints,
  ) async {
    _FileCandidate? best;
    var visited = 0;
    for (final root in roots) {
      if (!await root.exists()) continue;
      final queue = <_DirDepth>[_DirDepth(root, 0)];
      while (queue.isNotEmpty && visited < 16000) {
        final current = queue.removeAt(0);
        visited++;
        if (current.depth > 7) continue;
        try {
          await for (final entity in current.dir.list(followLinks: false)) {
            final name = _basename(entity.path);
            if (entity is Directory) {
              if (!_shouldSkipDir(name)) {
                queue.add(_DirDepth(entity, current.depth + 1));
              }
              continue;
            }
            if (entity is! File) continue;
            if (name.toLowerCase() != fileName.toLowerCase()) continue;
            final score = _fileScore(entity, root, workspaceHints);
            if (best == null || score > best.score) {
              best = _FileCandidate(entity, score);
            }
          }
        } catch (_) {}
      }
    }
    return best?.file;
  }

  static int _fileScore(
    File file,
    Directory root,
    List<String> workspaceHints,
  ) {
    final path = file.path.toLowerCase();
    var score = 1000 - path.length.clamp(0, 900);
    for (final hint in workspaceHints) {
      final key = hint.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '');
      final compactPath = path.replaceAll(RegExp(r'[^a-z0-9]+'), '');
      if (key.isNotEmpty && compactPath.contains(key)) score += 500;
    }
    if (path.startsWith(root.absolute.path.toLowerCase())) score += 80;
    return score;
  }

  static Future<_TextFileContent?> _readTextFile(File file) async {
    final ext = _extension(file.path).toLowerCase();
    if (const {'.doc', '.docx', '.rtf'}.contains(ext)) return null;
    try {
      final bytes = await file.readAsBytes();
      final decoded = utf8.decode(bytes, allowMalformed: true);
      final truncated = decoded.length > maxContextChars;
      return _TextFileContent(
        truncated ? decoded.substring(0, maxContextChars) : decoded,
        truncated,
      );
    } catch (_) {
      return null;
    }
  }

  static String _basename(String path) {
    final normalized = path.replaceAll('/', Platform.pathSeparator);
    final parts = normalized
        .split(Platform.pathSeparator)
        .where((item) => item.isNotEmpty)
        .toList();
    return parts.isEmpty ? path : parts.last;
  }

  static String _extension(String path) {
    final name = _basename(path);
    final index = name.lastIndexOf('.');
    return index < 0 ? '' : name.substring(index);
  }

  static bool _shouldSkipDir(String name) {
    final key = name.toLowerCase();
    return key == '.git' ||
        key == '.dart_tool' ||
        key == '.idea' ||
        key == '.gradle' ||
        key == 'node_modules' ||
        key == 'build' ||
        key == 'dist' ||
        key == 'target' ||
        key == 'venv' ||
        key == '.venv' ||
        key == '__pycache__';
  }

  static String _listWindowsScript() => r'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class AssistantWinApi {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
"@
$active = [AssistantWinApi]::GetForegroundWindow().ToInt64()
$items = Get-Process |
  Where-Object { $_.MainWindowHandle -ne 0 -and -not [string]::IsNullOrWhiteSpace($_.MainWindowTitle) } |
  ForEach-Object {
    $path = ""
    try { $path = $_.Path } catch {}
    [pscustomobject]@{
      id = "$($_.MainWindowHandle.ToInt64())"
      title = $_.MainWindowTitle
      process_id = $_.Id
      process_name = $_.ProcessName
      executable_path = $path
      class_name = ""
      is_active = ($_.MainWindowHandle.ToInt64() -eq $active)
    }
  } |
  Sort-Object @{Expression="is_active";Descending=$true}, process_name, title
@($items) | ConvertTo-Json -Depth 4 -Compress
''';

  static String _windowTextScript() => r'''
Add-Type -AssemblyName UIAutomationClient
$handleText = $env:ASSISTANT_WINDOW_HANDLE
if ([string]::IsNullOrWhiteSpace($handleText)) { throw "Handle vazio." }
$handle = [IntPtr]([int64]$handleText)
$root = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
if ($null -eq $root) { throw "Elemento da janela nao encontrado." }

$items = New-Object System.Collections.ArrayList
$maxItems = 500

function Add-Text([string]$value) {
  $clean = ($value -replace "\s+", " ").Trim()
  if ($clean.Length -gt 1 -and -not $items.Contains($clean)) {
    [void]$items.Add($clean)
  }
}

function Add-PatternText($element) {
  try {
    $textPattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$textPattern)) {
      Add-Text $textPattern.DocumentRange.GetText(12000)
    }
  } catch {}
  try {
    $valuePattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$valuePattern)) {
      Add-Text $valuePattern.Current.Value
    }
  } catch {}
}

function Walk($element, [int]$depth) {
  if ($null -eq $element -or $items.Count -ge $maxItems -or $depth -gt 7) { return }
  try { Add-Text $element.Current.Name } catch {}
  Add-PatternText $element
  try {
    $children = $element.FindAll(
      [System.Windows.Automation.TreeScope]::Children,
      [System.Windows.Automation.Condition]::TrueCondition
    )
    foreach ($child in $children) {
      Walk $child ($depth + 1)
      if ($items.Count -ge $maxItems) { break }
    }
  } catch {}
}

Add-PatternText $root
Walk $root 0
$text = (($items | Select-Object -First $maxItems) -join "`n").Trim()
if ($text.Length -gt 12000) {
  $text = $text.Substring(0, 12000)
  $truncated = $true
} else {
  $truncated = ($items.Count -ge $maxItems)
}
[pscustomobject]@{ text = $text; truncated = $truncated } |
  ConvertTo-Json -Depth 3 -Compress
''';

  static String _wordDocumentScript() => r'''
$title = $env:ASSISTANT_WINDOW_TITLE
$word = $null
try {
  $word = [Runtime.InteropServices.Marshal]::GetActiveObject("Word.Application")
} catch {
  exit 0
}

$doc = $null
try {
  if ($word.ActiveDocument -ne $null) { $doc = $word.ActiveDocument }
} catch {}

if ($title -and $word.Documents.Count -gt 0) {
  foreach ($candidate in $word.Documents) {
    try {
      if ($title -like "*$($candidate.Name)*" -or $title -like "*$($candidate.FullName)*") {
        $doc = $candidate
        break
      }
    } catch {}
  }
}

if ($null -eq $doc) { exit 0 }
$text = ""
try { $text = $doc.Content.Text } catch {}
$truncated = $false
if ($text.Length -gt 12000) {
  $text = $text.Substring(0, 12000)
  $truncated = $true
}
$path = ""
try { $path = $doc.FullName } catch {}
[pscustomobject]@{ text = $text; path = $path; truncated = $truncated } |
  ConvertTo-Json -Depth 3 -Compress
''';
}

class _FallbackContent {
  final String text;
  final String method;
  final String? sourcePath;
  final bool truncated;
  final String? warning;

  const _FallbackContent({
    required this.text,
    required this.method,
    this.sourcePath,
    required this.truncated,
    this.warning,
  });
}

class _TextFileContent {
  final String text;
  final bool truncated;

  const _TextFileContent(this.text, this.truncated);
}

class _FileCandidate {
  final File file;
  final int score;

  const _FileCandidate(this.file, this.score);
}

class _DirDepth {
  final Directory dir;
  final int depth;

  const _DirDepth(this.dir, this.depth);
}

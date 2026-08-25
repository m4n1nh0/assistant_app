/// Descoberta dos aplicativos instalados, para sugerir atalhos.
///
/// Combina regras de aplicativos conhecidos com a varredura do sistema.
library;

import 'dart:convert';
import 'dart:io';

/// Um aplicativo encontrado na maquina, candidato a virar atalho.
class InstalledAppCandidate {
  final String name;
  final String target;
  final String type;
  final String sourceTarget;
  final String launchCommand;
  final List<String> aliases;
  final String description;
  final String reason;
  final String source;
  final int score;

  const InstalledAppCandidate({
    required this.name,
    required this.target,
    this.type = 'app',
    this.sourceTarget = '',
    this.launchCommand = '',
    this.aliases = const [],
    this.description = '',
    this.reason = '',
    this.source = 'pc',
    this.score = 0,
  });

  bool get isUrl => type == 'url';
  bool get isCommand => type == 'command';
  String get displayTarget => sourceTarget.isEmpty ? target : sourceTarget;
}

/// Ajusta o candidato para o formato de comando que a plataforma aceita.
class LaunchCommandAgent {
  static InstalledAppCandidate prepare(InstalledAppCandidate candidate) {
    if (!Platform.isWindows || candidate.isUrl) return candidate;
    final sourceTarget = candidate.sourceTarget.isEmpty
        ? candidate.target
        : candidate.sourceTarget;
    final command = windowsShellExecute(sourceTarget);
    return InstalledAppCandidate(
      name: candidate.name,
      target: command.payload,
      type: 'command',
      sourceTarget: sourceTarget,
      launchCommand: command.preview,
      aliases: candidate.aliases,
      description: candidate.description,
      reason: candidate.reason.isEmpty
          ? 'Agente montou chamada segura para o atalho local.'
          : candidate.reason,
      source: candidate.source,
      score: candidate.score,
    );
  }

  static LaunchCommandSpec windowsShellExecute(String target) {
    const preview =
        r'powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Item -LiteralPath $env:ASSISTANT_LAUNCH_TARGET"';
    return LaunchCommandSpec(
      payload: jsonEncode({
        'version': 1,
        'platform': 'windows',
        'runner': 'windowsShellExecute',
        'target': target,
        'command_preview': preview,
      }),
      preview: preview,
    );
  }
}

/// Comando de abertura pronto, com a previa mostrada ao usuario.
class LaunchCommandSpec {
  final String payload;
  final String preview;

  const LaunchCommandSpec({
    required this.payload,
    required this.preview,
  });
}

class _ShortcutRule {
  final String label;
  final List<String> patterns;
  final List<String> aliases;
  final String description;
  final int score;

  const _ShortcutRule({
    required this.label,
    required this.patterns,
    required this.aliases,
    required this.description,
    required this.score,
  });

  bool matches(InstalledAppCandidate candidate) {
    final text = InstalledAppsService._norm(
      '${candidate.name} ${candidate.target} ${candidate.sourceTarget}',
    );
    return patterns.any(
      (pattern) => text.contains(InstalledAppsService._norm(pattern)),
    );
  }
}

/// Descobre os aplicativos instalados para sugerir atalhos.
///
/// Combina regras conhecidas de aplicativos comuns com a varredura do sistema, o
/// que evita depender so da varredura - lenta e cheia de falso positivo.
class InstalledAppsService {
  static const _developerRules = [
    _ShortcutRule(
      label: 'Visual Studio Code',
      patterns: ['visual studio code', 'vscode', 'code.exe'],
      aliases: ['vscode', 'code', 'editor'],
      description: 'Editor principal para projetos e scripts.',
      score: 100,
    ),
    _ShortcutRule(
      label: 'Visual Studio',
      patterns: ['visual studio', 'devenv.exe'],
      aliases: ['visual studio', 'ide', 'dotnet'],
      description: 'IDE para .NET, C++, testes e depuracao.',
      score: 96,
    ),
    _ShortcutRule(
      label: 'Windows Terminal',
      patterns: ['windows terminal', 'wt.exe'],
      aliases: ['terminal', 'console', 'shell'],
      description: 'Terminal central para shells e ferramentas CLI.',
      score: 94,
    ),
    _ShortcutRule(
      label: 'Git Bash',
      patterns: ['git bash', 'git-bash.exe'],
      aliases: ['git bash', 'bash', 'git'],
      description: 'Shell Git para comandos de versionamento.',
      score: 93,
    ),
    _ShortcutRule(
      label: 'Docker Desktop',
      patterns: ['docker desktop', 'docker desktop.exe'],
      aliases: ['docker', 'containers', 'compose'],
      description: 'Containers locais, Compose e ambientes de desenvolvimento.',
      score: 92,
    ),
    _ShortcutRule(
      label: 'Postman',
      patterns: ['postman'],
      aliases: ['postman', 'api client', 'apis'],
      description: 'Cliente para testar APIs e colecoes HTTP.',
      score: 89,
    ),
    _ShortcutRule(
      label: 'Insomnia',
      patterns: ['insomnia'],
      aliases: ['insomnia', 'api client', 'apis'],
      description: 'Cliente leve para testar requisicoes HTTP.',
      score: 87,
    ),
    _ShortcutRule(
      label: 'DBeaver',
      patterns: ['dbeaver'],
      aliases: ['dbeaver', 'banco', 'database'],
      description: 'Cliente de banco de dados para consultas e administracao.',
      score: 86,
    ),
    _ShortcutRule(
      label: 'JetBrains',
      patterns: [
        'intellij',
        'pycharm',
        'webstorm',
        'phpstorm',
        'datagrip',
        'rider',
      ],
      aliases: ['jetbrains', 'ide'],
      description: 'IDE de desenvolvimento para projetos especificos.',
      score: 84,
    ),
    _ShortcutRule(
      label: 'Android Studio',
      patterns: ['android studio'],
      aliases: ['android studio', 'android', 'flutter'],
      description: 'IDE para Android, emuladores e apps Flutter.',
      score: 83,
    ),
    _ShortcutRule(
      label: 'GitHub Desktop',
      patterns: ['github desktop'],
      aliases: ['github desktop', 'github', 'git'],
      description: 'Cliente visual para repositorios GitHub.',
      score: 82,
    ),
    _ShortcutRule(
      label: 'Node.js',
      patterns: ['node.js', 'nodejs', 'node.exe'],
      aliases: ['node', 'nodejs', 'javascript'],
      description: 'Runtime JavaScript para ferramentas e servidores locais.',
      score: 78,
    ),
    _ShortcutRule(
      label: 'Python',
      patterns: ['python', 'python.exe', 'idle'],
      aliases: ['python', 'py', 'python shell'],
      description: 'Ambiente Python para scripts, APIs e automacoes.',
      score: 76,
    ),
    _ShortcutRule(
      label: 'WSL',
      patterns: ['wsl', 'ubuntu', 'debian'],
      aliases: ['wsl', 'linux', 'ubuntu'],
      description: 'Ambiente Linux local para desenvolvimento.',
      score: 74,
    ),
  ];

  static const _developerWebSuggestions = [
    InstalledAppCandidate(
      name: 'GitHub',
      target: 'https://github.com',
      type: 'url',
      aliases: ['github', 'repositorios', 'git'],
      description: 'Repositorios, pull requests, issues e actions.',
      reason: 'Portal web essencial para fluxo Git e colaboracao.',
      source: 'web',
      score: 98,
    ),
    InstalledAppCandidate(
      name: 'Stack Overflow',
      target: 'https://stackoverflow.com',
      type: 'url',
      aliases: ['stackoverflow', 'stack overflow', 'duvidas dev'],
      description: 'Pesquisa rapida de erros, exemplos e discussoes tecnicas.',
      reason: 'Base recorrente para diagnostico de problemas de codigo.',
      source: 'web',
      score: 91,
    ),
    InstalledAppCandidate(
      name: 'MDN Web Docs',
      target: 'https://developer.mozilla.org',
      type: 'url',
      aliases: ['mdn', 'docs web', 'javascript docs'],
      description: 'Referencia de HTML, CSS, JavaScript e APIs Web.',
      reason: 'Documentacao confiavel para desenvolvimento web.',
      source: 'web',
      score: 90,
    ),
    InstalledAppCandidate(
      name: 'Docker Hub',
      target: 'https://hub.docker.com',
      type: 'url',
      aliases: ['docker hub', 'imagens docker', 'containers'],
      description: 'Busca e gerenciamento de imagens Docker.',
      reason: 'Atalho util para ambientes conteinerizados.',
      source: 'web',
      score: 88,
    ),
    InstalledAppCandidate(
      name: 'npm',
      target: 'https://www.npmjs.com',
      type: 'url',
      aliases: ['npm', 'pacotes node', 'javascript packages'],
      description: 'Registro de pacotes JavaScript e TypeScript.',
      reason: 'Consulta frequente para dependencias front-end e Node.',
      source: 'web',
      score: 86,
    ),
    InstalledAppCandidate(
      name: 'PyPI',
      target: 'https://pypi.org',
      type: 'url',
      aliases: ['pypi', 'pacotes python', 'python packages'],
      description: 'Registro de pacotes Python.',
      reason: 'Consulta rapida para dependencias Python.',
      source: 'web',
      score: 84,
    ),
    InstalledAppCandidate(
      name: 'DevDocs',
      target: 'https://devdocs.io',
      type: 'url',
      aliases: ['devdocs', 'documentacao', 'docs'],
      description: 'Documentacao tecnica agregada e pesquisavel.',
      reason: 'Bom hub de referencia para varias stacks.',
      source: 'web',
      score: 80,
    ),
    InstalledAppCandidate(
      name: 'Regex101',
      target: 'https://regex101.com',
      type: 'url',
      aliases: ['regex101', 'regex', 'expressoes regulares'],
      description: 'Editor e depurador de expressoes regulares.',
      reason: 'Ferramenta pratica para validar regex antes de usar no codigo.',
      source: 'web',
      score: 76,
    ),
  ];

  static Future<List<InstalledAppCandidate>> discover() async {
    if (!Platform.isWindows) return [];

    final env = Platform.environment;
    final roots = <String>[
      if (env['ProgramData'] != null)
        '${env['ProgramData']}\\Microsoft\\Windows\\Start Menu\\Programs',
      if (env['APPDATA'] != null)
        '${env['APPDATA']}\\Microsoft\\Windows\\Start Menu\\Programs',
      if (env['PUBLIC'] != null) '${env['PUBLIC']}\\Desktop',
      if (env['USERPROFILE'] != null) '${env['USERPROFILE']}\\Desktop',
    ];

    final byTarget = <String, InstalledAppCandidate>{};
    for (final root in roots) {
      final dir = Directory(root);
      if (!await dir.exists()) continue;

      await for (final entity
          in dir.list(recursive: true, followLinks: false)) {
        if (entity is! File) continue;
        final lower = entity.path.toLowerCase();
        if (!lower.endsWith('.lnk') && !lower.endsWith('.url')) continue;

        final name = _cleanName(entity.uri.pathSegments.last);
        if (name.length < 2) continue;
        final urlTarget =
            lower.endsWith('.url') ? await _readInternetShortcut(entity) : null;
        byTarget.putIfAbsent(
          urlTarget ?? entity.path,
          () => LaunchCommandAgent.prepare(
            InstalledAppCandidate(
              name: name,
              target: urlTarget ?? entity.path,
              type: urlTarget == null ? 'app' : 'url',
              sourceTarget: urlTarget ?? entity.path,
              aliases: _aliasesFromName(name),
              source: 'pc',
            ),
          ),
        );
      }
    }

    for (final candidate in await _discoverRegistryAppPaths()) {
      byTarget.putIfAbsent(_targetKey(candidate.target), () => candidate);
    }
    for (final candidate in await _knownWindowsApps()) {
      byTarget.putIfAbsent(_targetKey(candidate.target), () => candidate);
    }

    final result = byTarget.values.toList()
      ..sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
    return result.take(300).toList();
  }

  static Future<List<InstalledAppCandidate>> recommendForProfile({
    String profile = 'developer',
    Iterable<String> existingNames = const [],
    Iterable<String> existingTargets = const [],
  }) async {
    if (_norm(profile) != 'developer') return [];

    final existingNameKeys = existingNames.map(_norm).toSet();
    final existingTargetKeys = existingTargets.map(_targetKey).toSet();
    final installed = await discover();
    final suggestions = <InstalledAppCandidate>[];

    for (final candidate in installed) {
      final rule = _bestRule(candidate);
      if (rule == null) continue;

      suggestions.add(
        InstalledAppCandidate(
          name: candidate.name,
          target: candidate.target,
          type: candidate.type,
          sourceTarget: candidate.sourceTarget,
          launchCommand: candidate.launchCommand,
          aliases: _mergeAliases(candidate.aliases, rule.aliases),
          description: rule.description,
          reason: candidate.isCommand
              ? 'Encontrado no PC como ${rule.label}; agente montou o comando.'
              : 'Encontrado no PC e parece ser ${rule.label}.',
          source: 'pc',
          score: rule.score,
        ),
      );
    }

    suggestions.addAll(_developerWebSuggestions);

    final byTarget = <String, InstalledAppCandidate>{};
    for (final suggestion in suggestions) {
      final targetKey = _targetKey(suggestion.target);
      if (existingNameKeys.contains(_norm(suggestion.name)) ||
          existingTargetKeys.contains(targetKey)) {
        continue;
      }

      final current = byTarget[targetKey];
      if (current == null || suggestion.score > current.score) {
        byTarget[targetKey] = suggestion;
      }
    }

    final result = byTarget.values.toList()
      ..sort((a, b) {
        final scoreOrder = b.score.compareTo(a.score);
        if (scoreOrder != 0) return scoreOrder;
        return a.name.toLowerCase().compareTo(b.name.toLowerCase());
      });
    return result.take(40).toList();
  }

  static String _cleanName(String fileName) {
    var name = fileName;
    try {
      name = Uri.decodeComponent(fileName);
    } catch (_) {
      name = fileName;
    }
    name = name.replaceAll(RegExp(r'\.(lnk|url)$', caseSensitive: false), '');
    name =
        name.replaceAll(RegExp(r'\s*-\s*Shortcut$', caseSensitive: false), '');
    return name.trim();
  }

  static Future<String?> _readInternetShortcut(File file) async {
    try {
      final lines = await file.readAsLines();
      for (final line in lines) {
        final trimmed = line.trim();
        if (!trimmed.toLowerCase().startsWith('url=')) continue;
        final url = trimmed.substring(4).trim();
        final uri = Uri.tryParse(url);
        if (uri != null && uri.hasScheme) return url;
      }
    } catch (_) {}
    return null;
  }

  static Future<List<InstalledAppCandidate>> _discoverRegistryAppPaths() async {
    const script = r'''
$roots = @(
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths',
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths',
  'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths'
)
$items = foreach ($root in $roots) {
  if (Test-Path -LiteralPath $root) {
    Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue | ForEach-Object {
      try {
        $props = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction Stop
        $target = $props.'(default)'
        if (-not [string]::IsNullOrWhiteSpace($target)) {
          [PSCustomObject]@{
            name = [System.IO.Path]::GetFileNameWithoutExtension($_.PSChildName)
            target = [Environment]::ExpandEnvironmentVariables($target)
          }
        }
      } catch {}
    }
  }
}
@($items) | ConvertTo-Json -Depth 3 -Compress
''';

    try {
      final result = await Process.run(
        'powershell',
        ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
      ).timeout(const Duration(seconds: 6));
      if (result.exitCode != 0) return [];

      final output = result.stdout?.toString().trim() ?? '';
      if (output.isEmpty) return [];
      final decoded = jsonDecode(output);
      final rows = decoded is List ? decoded : [decoded];
      final candidates = <InstalledAppCandidate>[];
      for (final row in rows) {
        if (row is! Map) continue;
        final target = _cleanExecutableTarget(row['target']?.toString() ?? '');
        if (target.isEmpty || !await File(target).exists()) continue;
        final rawName = row['name']?.toString().trim() ?? '';
        final name = _friendlyExecutableName(rawName, target);
        candidates.add(LaunchCommandAgent.prepare(InstalledAppCandidate(
          name: name,
          target: target,
          sourceTarget: target,
          aliases: _aliasesForExecutable(rawName, name),
          source: 'registry',
          score: 30,
        )));
      }
      return candidates;
    } catch (_) {
      return [];
    }
  }

  static String _cleanExecutableTarget(String rawTarget) {
    final trimmed = rawTarget.trim();
    if (trimmed.isEmpty) return '';
    final quoted = RegExp(r'^"([^"]+)"').firstMatch(trimmed);
    if (quoted != null) return quoted.group(1)!.trim();
    final exe = RegExp(
      r'^(.+?\.(?:exe|cmd|bat|ps1|lnk))(?:\s|$)',
      caseSensitive: false,
    ).firstMatch(trimmed);
    if (exe != null) return exe.group(1)!.trim();
    return trimmed;
  }

  static Future<List<InstalledAppCandidate>> _knownWindowsApps() async {
    final env = Platform.environment;
    final windir = env['WINDIR'] ?? r'C:\Windows';
    final programFiles = env['ProgramFiles'];
    final programFilesX86 = env['ProgramFiles(x86)'];
    final localAppData = env['LOCALAPPDATA'];

    final specs = <({String name, String path, List<String> aliases})>[
      (
        name: 'Bloco de Notas',
        path: '$windir\\System32\\notepad.exe',
        aliases: [
          'bloco de notas',
          'notepad',
          'notepad.exe',
          'editor de texto'
        ],
      ),
      (
        name: 'Calculadora',
        path: '$windir\\System32\\calc.exe',
        aliases: ['calculadora', 'calculator', 'calc'],
      ),
      (
        name: 'Paint',
        path: '$windir\\System32\\mspaint.exe',
        aliases: ['paint', 'mspaint', 'microsoft paint'],
      ),
      (
        name: 'Explorador de Arquivos',
        path: '$windir\\explorer.exe',
        aliases: ['explorador', 'explorador de arquivos', 'windows explorer'],
      ),
      (
        name: 'Prompt de Comando',
        path: '$windir\\System32\\cmd.exe',
        aliases: ['cmd', 'prompt', 'prompt de comando'],
      ),
      (
        name: 'PowerShell',
        path: '$windir\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
        aliases: ['powershell', 'windows powershell'],
      ),
      if (programFiles != null)
        (
          name: 'Notepad++',
          path: '$programFiles\\Notepad++\\notepad++.exe',
          aliases: ['notepad++', 'notepad plus plus'],
        ),
      if (programFilesX86 != null)
        (
          name: 'Notepad++',
          path: '$programFilesX86\\Notepad++\\notepad++.exe',
          aliases: ['notepad++', 'notepad plus plus'],
        ),
      if (localAppData != null)
        (
          name: 'Notepad++',
          path: '$localAppData\\Programs\\Notepad++\\notepad++.exe',
          aliases: ['notepad++', 'notepad plus plus'],
        ),
    ];

    final candidates = <InstalledAppCandidate>[];
    final seen = <String>{};
    for (final spec in specs) {
      final key = spec.path.toLowerCase();
      if (seen.contains(key) || !await File(spec.path).exists()) continue;
      seen.add(key);
      candidates.add(LaunchCommandAgent.prepare(InstalledAppCandidate(
        name: spec.name,
        target: spec.path,
        sourceTarget: spec.path,
        aliases: spec.aliases,
        source: 'system',
        score: 90,
      )));
    }
    return candidates;
  }

  static String _friendlyExecutableName(String rawName, String target) {
    final base = rawName.trim().isNotEmpty
        ? rawName.trim()
        : target.replaceAll('/', '\\').split('\\').last;
    final lower = base.toLowerCase();
    if (lower == 'notepad') return 'Bloco de Notas';
    if (lower == 'notepad++') return 'Notepad++';
    if (lower == 'calc') return 'Calculadora';
    if (lower == 'mspaint') return 'Paint';
    if (lower == 'explorer') return 'Explorador de Arquivos';
    if (lower == 'cmd') return 'Prompt de Comando';
    if (lower == 'powershell') return 'PowerShell';
    return _cleanName('$base.exe')
        .replaceAll(RegExp(r'\.exe$', caseSensitive: false), '')
        .trim();
  }

  static List<String> _aliasesForExecutable(String rawName, String name) {
    final aliases = <String>{..._aliasesFromName(name)};
    final lower = rawName.toLowerCase();
    if (lower.isNotEmpty) aliases.add(lower);
    if (lower == 'notepad') {
      aliases.addAll(['bloco de notas', 'notepad.exe', 'editor de texto']);
    }
    if (lower == 'notepad++') {
      aliases.addAll(['notepad++', 'notepad plus plus']);
    }
    return aliases.where((item) => item.trim().length > 1).toList();
  }

  static _ShortcutRule? _bestRule(InstalledAppCandidate candidate) {
    _ShortcutRule? best;
    for (final rule in _developerRules) {
      if (!rule.matches(candidate)) continue;
      if (best == null || rule.score > best.score) best = rule;
    }
    return best;
  }

  static List<String> _aliasesFromName(String name) {
    final cleaned = name.trim();
    final aliases = <String>{cleaned.toLowerCase()};
    final withoutSuffix = cleaned
        .replaceAll(RegExp(r'\s+\d{4}$'), '')
        .replaceAll(RegExp(r'\s+\(.*?\)$'), '')
        .trim();
    if (withoutSuffix.isNotEmpty) aliases.add(withoutSuffix.toLowerCase());
    return aliases.where((item) => item.length > 1).toList();
  }

  static List<String> _mergeAliases(List<String> first, List<String> second) {
    final aliases = <String>{};
    for (final item in [...first, ...second]) {
      final trimmed = item.trim().toLowerCase();
      if (trimmed.length > 1) aliases.add(trimmed);
    }
    return aliases.toList();
  }

  static String _norm(String text) =>
      text.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();

  static String _targetKey(String target) {
    var text = target.trim().toLowerCase();
    try {
      final decoded = jsonDecode(target);
      if (decoded is Map && decoded['target'] != null) {
        text = decoded['target'].toString().trim().toLowerCase();
      }
    } catch (_) {}
    final uri = Uri.tryParse(text);
    if (uri != null && uri.hasScheme) {
      final path = uri.path.endsWith('/') && uri.path.length > 1
          ? uri.path.substring(0, uri.path.length - 1)
          : uri.path;
      return '${uri.scheme}://${uri.host}$path'.toLowerCase();
    }
    return text.replaceAll('/', '\\');
  }
}

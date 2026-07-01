import 'dart:io';

class ProjectCandidate {
  final String name;
  final String path;
  final int score;

  const ProjectCandidate({
    required this.name,
    required this.path,
    required this.score,
  });
}

class ProjectDiscoveryService {
  static const _projectMarkers = [
    '.idea',
    '.git',
    'pyproject.toml',
    'requirements.txt',
    'pubspec.yaml',
    'package.json',
    'docker-compose.yml',
    'README.md',
    'pom.xml',
    'build.gradle',
    'Cargo.toml',
  ];

  static List<String> get projectMarkers => List.unmodifiable(_projectMarkers);

  static Future<ProjectCandidate?> findProject(
    String query, {
    Iterable<Directory>? roots,
    int maxDepth = 5,
    int maxVisited = 8000,
  }) async {
    final terms = _queryTerms(query);
    if (terms.isEmpty) return null;

    final searchRoots = roots?.toList() ?? _defaultRoots();
    ProjectCandidate? best;
    var visited = 0;

    for (final root in searchRoots) {
      if (!await root.exists()) continue;
      final queue = <_DirDepth>[_DirDepth(root, 0)];
      while (queue.isNotEmpty && visited < maxVisited) {
        final current = queue.removeAt(0);
        visited++;

        final dir = current.dir;
        final name = _basename(dir.path);
        final score = await _scoreDirectory(terms, dir, name);
        if (score > 0 &&
            (best == null ||
                score > best.score ||
                (score == best.score && dir.path.length < best.path.length))) {
          best = ProjectCandidate(name: name, path: dir.path, score: score);
          if (score >= 180) return best;
        }

        if (current.depth >= maxDepth || _shouldSkipDir(name)) continue;
        try {
          await for (final entity in dir.list(followLinks: false)) {
            if (entity is Directory) {
              queue.add(_DirDepth(entity, current.depth + 1));
            }
          }
        } catch (_) {}
      }
    }

    return best;
  }

  static List<Directory> _defaultRoots() {
    final env = Platform.environment;
    final user = env['USERPROFILE'] ?? env['HOME'] ?? '';
    final roots = <String>[
      if (user.isNotEmpty) '$user\\vscode-projects',
      if (user.isNotEmpty) '$user\\PycharmProjects',
      if (user.isNotEmpty) '$user\\PyCharmProjects',
      if (user.isNotEmpty) '$user\\source',
      if (user.isNotEmpty) '$user\\projects',
      if (user.isNotEmpty) '$user\\Projetos',
      if (user.isNotEmpty) '$user\\Documents',
      Directory.current.path,
    ];
    return roots.map(Directory.new).toList();
  }

  static Future<int> _scoreDirectory(
    List<String> terms,
    Directory dir,
    String name,
  ) async {
    final nameKey = _key(name);
    final compactName = _compactKey(name);
    var best = 0;

    for (final term in terms) {
      final termKey = _key(term);
      final compactTerm = _compactKey(term);
      if (termKey.isEmpty || compactTerm.isEmpty) continue;
      if (nameKey == termKey || compactName == compactTerm) {
        best = best < 160 ? 160 : best;
      } else if (nameKey.contains(termKey) ||
          compactName.contains(compactTerm)) {
        best = best < 105 ? 105 : best;
      } else if (termKey.contains(nameKey) && nameKey.length >= 4) {
        best = best < 80 ? 80 : best;
      }
    }

    if (best == 0) return 0;
    if (await _looksLikeProject(dir)) best += 25;
    return best;
  }

  static Future<bool> _looksLikeProject(Directory dir) async {
    for (final marker in _projectMarkers) {
      final path = '${dir.path}${Platform.pathSeparator}$marker';
      if (await File(path).exists() || await Directory(path).exists()) {
        return true;
      }
    }
    return false;
  }

  static List<String> _queryTerms(String query) {
    final clean = query
        .replaceAll(
            RegExp(r'\b(projeto|project|repo|repositorio)\b',
                caseSensitive: false),
            ' ')
        .trim();
    return [
      clean,
      clean.replaceAll(RegExp(r'[_-]+'), ' '),
    ].where((item) => item.trim().length > 1).toSet().toList();
  }

  static String _basename(String path) {
    final normalized = path.replaceAll('/', '\\');
    final parts = normalized.split('\\').where((item) => item.isNotEmpty);
    return parts.isEmpty ? path : parts.last;
  }

  static String _key(String text) =>
      text.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();

  static String _compactKey(String text) => _key(text).replaceAll(' ', '');

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
}

class _DirDepth {
  final Directory dir;
  final int depth;

  const _DirDepth(this.dir, this.depth);
}

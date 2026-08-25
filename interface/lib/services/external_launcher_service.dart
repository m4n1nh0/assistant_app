/// Abre URL, aplicativo ou comando na maquina.
///
/// E o executor final dos atalhos: o backend propoe o alvo, este servico abre.
library;

import 'dart:convert';
import 'dart:io';

import 'package:url_launcher/url_launcher.dart';
import 'project_discovery_service.dart';

/// Abre URL, aplicativo ou comando na maquina do usuario.
///
/// E o executor final dos atalhos: o backend propoe o alvo, este servico abre.
class ExternalLauncherService {
  static Future<void> openUrl(String rawUrl, {String browser = ''}) async {
    final url = rawUrl.trim();
    if (url.isEmpty) throw Exception('URL vazia');

    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme) {
      throw Exception('URL invalida');
    }

    final preferredBrowser = browser.trim().toLowerCase();
    if (preferredBrowser.isNotEmpty &&
        await _openUrlWithBrowser(url, preferredBrowser)) {
      return;
    }

    if (await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      return;
    }

    await openTarget(url);
  }

  static Future<bool> _openUrlWithBrowser(String url, String browser) async {
    final target = await _resolveBrowserExecutable(browser);
    if (target == null || target.trim().isEmpty) return false;

    try {
      if (Platform.isWindows) {
        await _runChecked(
          'powershell',
          [
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-Command',
            r'''
$browser = $env:ASSISTANT_BROWSER_TARGET
$url = $env:ASSISTANT_BROWSER_URL
if ([string]::IsNullOrWhiteSpace($browser)) { throw "navegador vazio" }
if ([string]::IsNullOrWhiteSpace($url)) { throw "url vazia" }
Start-Process -FilePath $browser -ArgumentList @($url)
''',
          ],
          environment: {
            'ASSISTANT_BROWSER_TARGET': target,
            'ASSISTANT_BROWSER_URL': url,
          },
        );
        return true;
      }

      if (Platform.isMacOS) {
        await _runChecked('open', ['-a', target, url]);
        return true;
      }

      await _runChecked(target, [url]);
      return true;
    } catch (_) {
      return false;
    }
  }

  static Future<void> openTarget(String rawTarget) async {
    final target = rawTarget.trim();
    if (target.isEmpty) throw Exception('alvo vazio');

    if (Platform.isWindows) {
      await _runChecked(
        'powershell',
        [
          '-NoProfile',
          '-ExecutionPolicy',
          'Bypass',
          '-Command',
          r'''
$target = $env:ASSISTANT_LAUNCH_TARGET
if ([string]::IsNullOrWhiteSpace($target)) { throw "alvo vazio" }
if (Test-Path -LiteralPath $target) {
  Invoke-Item -LiteralPath $target
} else {
  Start-Process -FilePath $target
}
''',
        ],
        environment: {'ASSISTANT_LAUNCH_TARGET': target},
      );
      return;
    }

    if (Platform.isMacOS) {
      await _runChecked('open', [target]);
      return;
    }

    await _runChecked('xdg-open', [target]);
  }

  static Future<void> runLaunchCommand(String payload) async {
    final decoded = jsonDecode(payload);
    if (decoded is! Map) throw Exception('comando de atalho invalido');

    final runner = decoded['runner']?.toString() ?? '';
    if (Platform.isWindows && runner == 'windowsShellExecute') {
      final target = decoded['target']?.toString() ?? '';
      await openTarget(target);
      return;
    }
    if (runner == 'openProjectInIde') {
      final ide = decoded['ide']?.toString() ?? '';
      final query = decoded['project_query']?.toString() ??
          decoded['projectQuery']?.toString() ??
          '';
      await openProjectInIde(ide: ide, projectQuery: query);
      return;
    }

    throw Exception('executor de comando nao suportado: $runner');
  }

  /// IDEs the assistant can open a project folder with. Keys match the `ide`
  /// field the backend sends in the openProjectInIde payload.
  static const ideLabels = <String, String>{
    'pycharm': 'PyCharm',
    'vscode': 'VS Code',
  };

  static Future<void> openProjectInIde({
    required String ide,
    required String projectQuery,
  }) async {
    final normalizedIde = ide.trim().toLowerCase();
    final label = ideLabels[normalizedIde];
    if (label == null) {
      throw Exception('IDE nao suportada: $ide');
    }

    final project = await ProjectDiscoveryService.findProject(projectQuery);
    if (project == null) {
      throw Exception('projeto nao encontrado: $projectQuery');
    }

    final executable = await _resolveIdeExecutable(normalizedIde);
    if (executable == null || executable.trim().isEmpty) {
      throw Exception('$label nao encontrado neste computador');
    }

    if (Platform.isWindows) {
      await _runChecked(
        'powershell',
        [
          '-NoProfile',
          '-ExecutionPolicy',
          'Bypass',
          '-Command',
          r'''
$ide = $env:ASSISTANT_IDE_TARGET
$project = $env:ASSISTANT_PROJECT_PATH
if ([string]::IsNullOrWhiteSpace($ide)) { throw "IDE vazia" }
if ([string]::IsNullOrWhiteSpace($project)) { throw "projeto vazio" }
if (-not (Test-Path -LiteralPath $project -PathType Container)) {
  throw "projeto nao encontrado: $project"
}
Start-Process -FilePath $ide -ArgumentList @($project)
''',
        ],
        environment: {
          'ASSISTANT_IDE_TARGET': executable,
          'ASSISTANT_PROJECT_PATH': project.path,
        },
      );
      return;
    }

    await _runChecked(executable, [project.path]);
  }

  static Future<String?> _resolveIdeExecutable(String ide) {
    switch (ide) {
      case 'pycharm':
        return _resolvePyCharmExecutable();
      case 'vscode':
        return _resolveVsCodeExecutable();
      default:
        return Future.value(null);
    }
  }

  static Future<String?> _resolveVsCodeExecutable() async {
    if (Platform.isWindows) {
      final env = Platform.environment;
      // Code.exe takes the folder as a plain argument; code.cmd would work too
      // but flashes a console window, so it is only the fallback.
      final candidates = [
        if (env['LOCALAPPDATA'] != null)
          '${env['LOCALAPPDATA']}\\Programs\\Microsoft VS Code\\Code.exe',
        if (env['ProgramFiles'] != null)
          '${env['ProgramFiles']}\\Microsoft VS Code\\Code.exe',
        if (env['ProgramFiles(x86)'] != null)
          '${env['ProgramFiles(x86)']}\\Microsoft VS Code\\Code.exe',
      ];
      for (final candidate in candidates) {
        if (await File(candidate).exists()) return candidate;
      }
      return _whereFirst(['code.exe', 'code.cmd']);
    }

    if (Platform.isMacOS) {
      const app =
          '/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code';
      if (await File(app).exists()) return app;
    }

    return _whereFirst(['code']);
  }

  static Future<String?> _resolvePyCharmExecutable() async {
    if (Platform.isWindows) {
      final env = Platform.environment;
      final roots = [
        env['ProgramFiles'],
        env['ProgramFiles(x86)'],
        env['LOCALAPPDATA'] == null ? null : '${env['LOCALAPPDATA']}\\Programs',
      ].whereType<String>();

      for (final root in roots) {
        final dir = Directory('$root\\JetBrains');
        if (!await dir.exists()) continue;
        try {
          await for (final entity in dir.list(followLinks: false)) {
            if (entity is! Directory) continue;
            final candidate = File('${entity.path}\\bin\\pycharm64.exe');
            if (await candidate.exists()) return candidate.path;
          }
        } catch (_) {}
      }

      final whereResult = await _whereFirst(['pycharm64.exe', 'pycharm.exe']);
      if (whereResult != null) return whereResult;

      final startMenu = [
        if (env['ProgramData'] != null)
          '${env['ProgramData']}\\Microsoft\\Windows\\Start Menu\\Programs',
        if (env['APPDATA'] != null)
          '${env['APPDATA']}\\Microsoft\\Windows\\Start Menu\\Programs',
      ];
      for (final root in startMenu) {
        final dir = Directory(root);
        if (!await dir.exists()) continue;
        try {
          await for (final entity
              in dir.list(recursive: true, followLinks: false)) {
            if (entity is File &&
                entity.path.toLowerCase().endsWith('.lnk') &&
                entity.path.toLowerCase().contains('pycharm')) {
              return entity.path;
            }
          }
        } catch (_) {}
      }
    }

    if (Platform.isMacOS) {
      const app = '/Applications/PyCharm.app/Contents/MacOS/pycharm';
      if (await File(app).exists()) return app;
    }

    return _whereFirst(['pycharm', 'pycharm.sh']);
  }

  static Future<String?> _whereFirst(List<String> commands) async {
    final resolver = Platform.isWindows ? 'where' : 'which';
    for (final command in commands) {
      try {
        final result = await Process.run(resolver, [command])
            .timeout(const Duration(seconds: 3));
        if (result.exitCode != 0) continue;
        final lines = result.stdout
            ?.toString()
            .split(RegExp(r'\r?\n'))
            .map((line) => line.trim())
            .where((line) => line.isNotEmpty)
            .toList();
        if (lines != null && lines.isNotEmpty) return lines.first;
      } catch (_) {}
    }
    return null;
  }

  static Future<String?> _resolveBrowserExecutable(String browser) async {
    final normalized = browser.trim().toLowerCase();
    if (normalized.isEmpty) return null;

    if (Platform.isWindows) {
      final command = await _whereFirst(_browserWindowsCommands(normalized));
      if (command != null) return command;

      for (final candidate in _browserWindowsPaths(normalized)) {
        if (await File(candidate).exists()) return candidate;
      }
      return null;
    }

    if (Platform.isMacOS) {
      final app = _browserMacApp(normalized);
      if (app.isNotEmpty) return app;
    }

    return _whereFirst(_browserLinuxCommands(normalized));
  }

  static List<String> _browserWindowsCommands(String browser) {
    switch (browser) {
      case 'chrome':
        return ['chrome.exe', 'google-chrome.exe'];
      case 'edge':
        return ['msedge.exe'];
      case 'firefox':
        return ['firefox.exe'];
      case 'brave':
        return ['brave.exe'];
      case 'opera':
        return ['opera.exe', 'launcher.exe'];
      case 'vivaldi':
        return ['vivaldi.exe'];
      case 'chromium':
        return ['chromium.exe'];
    }
    return [];
  }

  static List<String> _browserWindowsPaths(String browser) {
    final env = Platform.environment;
    final programFiles = [
      env['ProgramFiles'],
      env['ProgramFiles(x86)'],
      env['LOCALAPPDATA'] == null ? null : '${env['LOCALAPPDATA']}\\Programs',
    ].whereType<String>().toList();

    final paths = <String>[];
    for (final root in programFiles) {
      switch (browser) {
        case 'chrome':
          paths.add('$root\\Google\\Chrome\\Application\\chrome.exe');
          break;
        case 'edge':
          paths.add('$root\\Microsoft\\Edge\\Application\\msedge.exe');
          break;
        case 'firefox':
          paths.add('$root\\Mozilla Firefox\\firefox.exe');
          break;
        case 'brave':
          paths.add(
              '$root\\BraveSoftware\\Brave-Browser\\Application\\brave.exe');
          break;
        case 'opera':
          paths.add('$root\\Opera\\launcher.exe');
          paths.add('$root\\Opera GX\\launcher.exe');
          break;
        case 'vivaldi':
          paths.add('$root\\Vivaldi\\Application\\vivaldi.exe');
          break;
        case 'chromium':
          paths.add('$root\\Chromium\\Application\\chromium.exe');
          break;
      }
    }
    return paths;
  }

  static String _browserMacApp(String browser) {
    switch (browser) {
      case 'chrome':
        return 'Google Chrome';
      case 'edge':
        return 'Microsoft Edge';
      case 'firefox':
        return 'Firefox';
      case 'brave':
        return 'Brave Browser';
      case 'opera':
        return 'Opera';
      case 'vivaldi':
        return 'Vivaldi';
      case 'chromium':
        return 'Chromium';
    }
    return '';
  }

  static List<String> _browserLinuxCommands(String browser) {
    switch (browser) {
      case 'chrome':
        return ['google-chrome', 'google-chrome-stable', 'chrome'];
      case 'edge':
        return ['microsoft-edge', 'microsoft-edge-stable'];
      case 'firefox':
        return ['firefox'];
      case 'brave':
        return ['brave-browser', 'brave'];
      case 'opera':
        return ['opera'];
      case 'vivaldi':
        return ['vivaldi', 'vivaldi-stable'];
      case 'chromium':
        return ['chromium', 'chromium-browser'];
    }
    return [];
  }

  static Future<void> _runChecked(
    String executable,
    List<String> arguments, {
    Map<String, String>? environment,
  }) async {
    final result = await Process.run(
      executable,
      arguments,
      environment: environment,
    );
    if (result.exitCode == 0) return;

    final stderr = result.stderr?.toString().trim() ?? '';
    final stdout = result.stdout?.toString().trim() ?? '';
    final detail = stderr.isNotEmpty
        ? stderr
        : stdout.isNotEmpty
            ? stdout
            : 'processo retornou ${result.exitCode}';
    throw Exception(detail);
  }
}

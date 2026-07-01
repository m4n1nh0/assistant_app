import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/shortcut_matching.dart';
import 'package:assistant_app/services/installed_apps_service.dart';
import 'package:assistant_app/models/app_config.dart';

InstalledAppCandidate _app(
  String name, {
  String target = '',
  String sourceTarget = '',
  List<String> aliases = const [],
  int score = 0,
  String type = 'app',
}) =>
    InstalledAppCandidate(
      name: name,
      target: target,
      sourceTarget: sourceTarget,
      aliases: aliases,
      score: score,
      type: type,
    );

ShortcutRegistrationAction _action(
  String name, {
  String query = '',
  List<String> aliases = const [],
}) =>
    ShortcutRegistrationAction(
      type: 'register_shortcut',
      name: name,
      query: query.isEmpty ? name : query,
      target: '',
      targetType: 'app',
      aliases: aliases,
    );

void main() {
  group('ShortcutMatching.compactKey', () {
    test('removes spaces and non-alphanumeric', () {
      expect(ShortcutMatching.compactKey('Google Chrome'), 'googlechrome');
      expect(ShortcutMatching.compactKey('Visual Studio Code'),
          'visualstudiocode');
      expect(ShortcutMatching.compactKey('C:\\path\\to\\app.exe'),
          'cpathtoappexe');
    });

    test('keeps plus-plus app names distinguishable', () {
      expect(ShortcutMatching.compactKey('Notepad++'), 'notepadplusplus');
      expect(ShortcutMatching.compactKey('Notepad'), 'notepad');
    });

    test('handles empty string', () {
      expect(ShortcutMatching.compactKey(''), '');
    });
  });

  group('ShortcutMatching.scoreCandidateAgainstTerms', () {
    test('exact name match scores 140', () {
      final candidate = _app('Chrome');
      final score =
          ShortcutMatching.scoreCandidateAgainstTerms(['chrome'], candidate);
      expect(score, greaterThanOrEqualTo(140));
    });

    test('partial name match (Chrome in Google Chrome) scores >= 100', () {
      final candidate = _app('Google Chrome',
          target: r'C:\ProgramData\...\Google Chrome.lnk',
          sourceTarget: r'C:\ProgramData\...\Google Chrome.lnk');
      final score =
          ShortcutMatching.scoreCandidateAgainstTerms(['chrome'], candidate);
      expect(score, greaterThanOrEqualTo(100));
    });

    test('alias exact match scores >= 130', () {
      final candidate = _app('Visual Studio Code', aliases: ['vscode', 'code']);
      final score =
          ShortcutMatching.scoreCandidateAgainstTerms(['vscode'], candidate);
      expect(score, greaterThanOrEqualTo(130));
    });

    test('haystack-only match scores >= 70', () {
      final candidate = _app('My App', target: 'chrome-target-path');
      final score =
          ShortcutMatching.scoreCandidateAgainstTerms(['chrome'], candidate);
      expect(score, greaterThanOrEqualTo(70));
    });

    test('no match scores 0', () {
      final candidate = _app('Notepad');
      final score =
          ShortcutMatching.scoreCandidateAgainstTerms(['photoshop'], candidate);
      expect(score, equals(0));
    });

    test('candidate.score bonus is added', () {
      final low = _app('Chrome', score: 0);
      final high = _app('Chrome', score: 100);
      final sLow = ShortcutMatching.scoreCandidateAgainstTerms(['chrome'], low);
      final sHigh =
          ShortcutMatching.scoreCandidateAgainstTerms(['chrome'], high);
      expect(sHigh, greaterThan(sLow));
    });
  });

  group('ShortcutMatching.bestCandidate', () {
    test('finds Google Chrome by term "Chrome"', () {
      final candidates = [
        _app('Notepad'),
        _app('Google Chrome',
            sourceTarget: r'C:\Start Menu\Google Chrome.lnk',
            target: r'C:\Start Menu\Google Chrome.lnk'),
        _app('Calculator'),
      ];
      final result =
          ShortcutMatching.bestCandidate(_action('Chrome'), candidates);
      expect(result, isNotNull);
      expect(result!.name, 'Google Chrome');
    });

    test('returns null when no candidate reaches min score', () {
      final candidates = [_app('Notepad'), _app('Calculator')];
      final result =
          ShortcutMatching.bestCandidate(_action('Photoshop'), candidates);
      expect(result, isNull);
    });

    test('prefers higher-scoring candidate', () {
      final candidates = [
        _app('Chrome Helper', score: 10),
        _app('Google Chrome', score: 80),
      ];
      final result =
          ShortcutMatching.bestCandidate(_action('Chrome'), candidates);
      expect(result!.name, 'Google Chrome');
    });

    test('distinguishes Notepad from Notepad++', () {
      final candidates = [
        _app('Bloco de Notas', aliases: ['notepad', 'bloco de notas']),
        _app('Notepad++', aliases: ['notepad++', 'notepad plus plus']),
      ];

      expect(
          ShortcutMatching.bestCandidate(_action('notepad'), candidates)!.name,
          'Bloco de Notas');
      expect(
          ShortcutMatching.bestCandidate(_action('notepad++'), candidates)!
              .name,
          'Notepad++');
    });

    test('returns null when terms list is empty', () {
      final candidates = [_app('Chrome')];
      final result = ShortcutMatching.bestCandidate(
        ShortcutRegistrationAction(
          type: 'register_shortcut',
          name: '',
          query: '',
          target: '',
          targetType: 'app',
          aliases: const [],
        ),
        candidates,
      );
      expect(result, isNull);
    });
  });

  group('ShortcutMatching.shortcutExists', () {
    test('detects duplicate by name', () {
      final existing = [
        ShortcutEntry(
          id: '1',
          tutorId: 'default',
          name: 'Google Chrome',
          type: 'app',
          target: '/some/path',
        ),
      ];
      final candidate = _app('Google Chrome', target: '/other/path');
      expect(ShortcutMatching.shortcutExists(existing, candidate), isTrue);
    });

    test('detects duplicate by target for command shortcuts', () {
      const jsonTarget =
          '{"runner":"windowsShellExecute","target":"C:\\\\chrome.lnk"}';
      final existing = [
        ShortcutEntry(
          id: '1',
          tutorId: 'default',
          name: 'Browser',
          type: 'command',
          target: jsonTarget,
        ),
      ];
      final candidate = _app('Google Chrome', target: jsonTarget);
      expect(ShortcutMatching.shortcutExists(existing, candidate), isTrue);
    });

    test('returns false when no duplicate', () {
      final existing = [
        ShortcutEntry(
          id: '1',
          tutorId: 'default',
          name: 'Notepad',
          type: 'app',
          target: 'notepad.exe',
        ),
      ];
      final candidate = _app('Chrome', target: 'chrome.exe');
      expect(ShortcutMatching.shortcutExists(existing, candidate), isFalse);
    });

    test('returns matching shortcut for duplicate target', () {
      const jsonTarget =
          '{"runner":"windowsShellExecute","target":"C:\\\\Windows\\\\System32\\\\notepad.exe"}';
      final existingShortcut = ShortcutEntry(
        id: '1',
        tutorId: 'default',
        name: 'Notepad',
        type: 'command',
        target: jsonTarget,
      );
      final candidate = _app(
        'Bloco de Notas',
        target: jsonTarget,
        type: 'command',
      );

      expect(
        ShortcutMatching.matchingShortcut([existingShortcut], candidate),
        same(existingShortcut),
      );
    });
  });

  group('ShortcutMatching.isSupportedCommand', () {
    test('accepts valid windowsShellExecute payload', () {
      const payload =
          '{"version":1,"runner":"windowsShellExecute","target":"C:\\\\chrome.lnk"}';
      expect(ShortcutMatching.isSupportedCommand(payload), isTrue);
    });

    test('rejects empty target', () {
      const payload = '{"runner":"windowsShellExecute","target":""}';
      expect(ShortcutMatching.isSupportedCommand(payload), isFalse);
    });

    test('rejects unknown runner', () {
      const payload = '{"runner":"exec","target":"chrome.exe"}';
      expect(ShortcutMatching.isSupportedCommand(payload), isFalse);
    });

    test('rejects invalid JSON', () {
      expect(ShortcutMatching.isSupportedCommand('not json'), isFalse);
    });
  });

  group('ShortcutEntry browser metadata', () {
    test('reads and strips preferred URL browser marker', () {
      final shortcut = ShortcutEntry(
        id: '1',
        tutorId: 'default',
        name: 'Dashboard',
        type: 'url',
        target: 'https://example.test',
        description: 'Painel interno\n[assistant:url_browser=firefox]',
      );

      expect(shortcut.preferredBrowser, 'firefox');
      expect(shortcut.visibleDescription, 'Painel interno');
      expect(
        ShortcutEntry.descriptionWithBrowser('Painel interno', 'edge'),
        'Painel interno\n[assistant:url_browser=edge]',
      );
    });
  });
}

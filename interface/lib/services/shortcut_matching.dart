import 'dart:convert';

import '../models/app_config.dart';
import '../services/installed_apps_service.dart';

/// Pure-logic helpers for shortcut candidate scoring and resolution.
/// Extracted from ChatPanel to enable unit testing.
class ShortcutMatching {
  static String looseKey(String text) => text
      .toLowerCase()
      .replaceAll('++', ' plus plus ')
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .trim();

  static String compactKey(String text) => looseKey(text).replaceAll(' ', '');

  static String targetKey(String target) {
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

  static int scoreCandidateAgainstTerms(
    List<String> terms,
    InstalledAppCandidate candidate,
  ) {
    final nameKey = compactKey(candidate.name);
    final aliasKeys = candidate.aliases.map(compactKey).toList();
    final haystack = compactKey(
      '${candidate.name} ${candidate.aliases.join(' ')} '
      '${candidate.target} ${candidate.sourceTarget}',
    );

    var best = 0;
    for (final term in terms) {
      final key = compactKey(term);
      if (key.isEmpty) continue;
      if (key == nameKey) best = best < 140 ? 140 : best;
      if (aliasKeys.contains(key)) best = best < 130 ? 130 : best;
      if (nameKey.contains(key) || key.contains(nameKey)) {
        best = best < 100 ? 100 : best;
      }
      if (haystack.contains(key)) best = best < 70 ? 70 : best;
    }

    return best + (candidate.score ~/ 10);
  }

  static const int kMinScore = 60;

  static InstalledAppCandidate? bestCandidate(
    ShortcutRegistrationAction action,
    List<InstalledAppCandidate> candidates,
  ) {
    final terms = <String>[action.query, action.name, ...action.aliases]
        .map((t) => t.trim())
        .where((t) => t.length > 1)
        .toSet()
        .toList();
    if (terms.isEmpty) return null;

    InstalledAppCandidate? best;
    var bestScore = 0;
    for (final candidate in candidates) {
      final score = scoreCandidateAgainstTerms(terms, candidate);
      if (score > bestScore) {
        best = candidate;
        bestScore = score;
      }
    }
    return bestScore >= kMinScore ? best : null;
  }

  static bool shortcutExists(
    List<ShortcutEntry> existing,
    InstalledAppCandidate candidate,
  ) =>
      matchingShortcut(existing, candidate) != null;

  static ShortcutEntry? matchingShortcut(
    List<ShortcutEntry> existing,
    InstalledAppCandidate candidate,
  ) {
    final nameKey = looseKey(candidate.name);
    final tKey = targetKey(candidate.target);
    for (final shortcut in existing) {
      if (looseKey(shortcut.name) == nameKey ||
          targetKey(shortcut.target) == tKey) {
        return shortcut;
      }
    }
    return null;
  }

  static bool isSupportedCommand(String payload) {
    try {
      final decoded = jsonDecode(payload);
      return decoded is Map &&
          decoded['runner'] == 'windowsShellExecute' &&
          decoded['target']?.toString().trim().isNotEmpty == true;
    } catch (_) {
      return false;
    }
  }
}

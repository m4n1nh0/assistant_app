class WakeWordCommand {
  final String text;
  final bool usedWakeWord;

  const WakeWordCommand(this.text, this.usedWakeWord);
}

WakeWordCommand parseWakeWordCommand(
  String transcript,
  String assistantName,
) {
  final rawWords = _voiceWords(transcript);
  if (rawWords.isEmpty) return WakeWordCommand(transcript, false);

  for (final nameTokens in _wakeNameTokenSets(assistantName)) {
    final maxStart = rawWords.length - nameTokens.length;
    for (var start = 0; start <= maxStart && start <= 6; start++) {
      final candidate = rawWords
          .skip(start)
          .take(nameTokens.length)
          .map(_normalizeVoiceToken)
          .toList();
      if (!_sameTokens(candidate, nameTokens)) continue;

      final prefix = rawWords.take(start).map(_normalizeVoiceToken).toList();
      final prefixIsGreeting = prefix.isEmpty ||
          prefix.every((word) => {
                'a',
                'o',
                'ok',
                'okay',
                'oi',
                'ola',
                'hey',
                'ei',
                'certo',
                'por',
                'favor',
              }.contains(word));
      if (!prefixIsGreeting) continue;

      final command = rawWords.skip(start + nameTokens.length).join(' ');
      return WakeWordCommand(_trimVoiceCommand(command), true);
    }
  }

  return WakeWordCommand(transcript, false);
}

List<List<String>> _wakeNameTokenSets(String assistantName) {
  final name = assistantName.trim().isEmpty ? 'Assistente' : assistantName;
  final tokens = _normalizedWords(name);
  return tokens.isEmpty ? const [] : [tokens];
}

List<String> _voiceWords(String text) {
  final words = <String>[];
  final buffer = StringBuffer();

  void flush() {
    final word = buffer.toString().trim();
    if (word.isNotEmpty) words.add(word);
    buffer.clear();
  }

  for (final rune in text.runes) {
    final char = String.fromCharCode(rune);
    if (_normalizeVoiceToken(char).isEmpty) {
      flush();
    } else {
      buffer.write(char);
    }
  }
  flush();
  return words;
}

List<String> _normalizedWords(String text) => _voiceWords(text)
    .map(_normalizeVoiceToken)
    .where((word) => word.isNotEmpty)
    .toList();

bool _sameTokens(List<String> heard, List<String> expected) {
  if (heard.length != expected.length) return false;
  for (var i = 0; i < heard.length; i++) {
    if (!_voiceTokenMatches(heard[i], expected[i])) return false;
  }
  return true;
}

bool _voiceTokenMatches(String heard, String expected) {
  if (heard == expected) return true;
  if (_phoneticNameKey(heard) == _phoneticNameKey(expected) &&
      _phoneticNameKey(heard).length >= 3) {
    return true;
  }
  if (heard.length >= 4 && expected.length >= 4) {
    if (heard.contains(expected) || expected.contains(heard)) return true;
    return _editDistanceAtMostOne(heard, expected);
  }
  return false;
}

String _phoneticNameKey(String value) {
  var key = value.replaceAll('y', 'i');
  if (key.startsWith('h')) key = key.substring(1);
  if (key.endsWith('h')) key = key.substring(0, key.length - 1);
  final collapsed = StringBuffer();
  String? previous;
  for (final rune in key.runes) {
    final char = String.fromCharCode(rune);
    if (char != previous) collapsed.write(char);
    previous = char;
  }
  return collapsed.toString();
}

bool _editDistanceAtMostOne(String a, String b) {
  if ((a.length - b.length).abs() > 1) return false;
  var i = 0;
  var j = 0;
  var edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] == b[j]) {
      i++;
      j++;
      continue;
    }
    edits++;
    if (edits > 1) return false;
    if (a.length > b.length) {
      i++;
    } else if (b.length > a.length) {
      j++;
    } else {
      i++;
      j++;
    }
  }
  if (i < a.length || j < b.length) edits++;
  return edits <= 1;
}

String _normalizeVoiceToken(String text) {
  const accents = {
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
    buffer.write(accents[char] ?? char);
  }
  return buffer
      .toString()
      .replaceAll('y', 'i')
      .replaceAll(RegExp(r'[^a-z0-9]'), '');
}

String _trimVoiceCommand(String text) =>
    text.trim().replaceFirst(RegExp(r'^[,.:;!?-]+\s*'), '').trim();

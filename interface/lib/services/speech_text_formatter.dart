const _monthsPt = <String>[
  'janeiro',
  'fevereiro',
  'março',
  'abril',
  'maio',
  'junho',
  'julho',
  'agosto',
  'setembro',
  'outubro',
  'novembro',
  'dezembro',
];

/// Converte o texto visual da conversa em uma versão própria para fala.
///
/// A resposta continua compacta na tela, mas Markdown, datas e horários são
/// expandidos antes de chegar ao sintetizador de voz.
String formatSpeechText(String content, {String language = 'pt-BR'}) {
  var text = content.replaceAll(RegExp(r'```[\s\S]*?```'), ' ');
  text = text.replaceAllMapped(
    RegExp(r'\[([^\]]+)\]\([^)]+\)'),
    (match) => match.group(1) ?? '',
  );
  text = text.replaceAllMapped(
    RegExp(r'`([^`]+)`'),
    (match) => match.group(1) ?? '',
  );
  text = text.replaceAll(
    RegExp(
      r'(?:link\s+da\s+reunião\s*:\s*)?https?://\S+',
      caseSensitive: false,
    ),
    'link da reunião disponível nos detalhes',
  );

  if (_isPortuguese(language)) {
    text = _formatCalendarEventLines(text);
    text = _formatCalendarPeriods(text);
    text = _formatFullDates(text);
    text = _formatShortDates(text);
    text = _formatTimeRanges(text);
    text = _formatStandaloneTimes(text);
    text = text.replaceAllMapped(
      RegExp(r'\b1\s+evento\(s\)', caseSensitive: false),
      (_) => 'um evento',
    );
    text = text.replaceAllMapped(
      RegExp(r'\b(\d+)\s+evento\(s\)', caseSensitive: false),
      (match) => '${match.group(1)} eventos',
    );
  }

  text = text.replaceAll(RegExp(r'\\([\\`*_{}\[\]()#+.!|>])'), r'$1');
  text = text.replaceAll(RegExp(r'[*_#>`~]+'), ' ');
  text = text.replaceAll(RegExp(r'^\s*[-+]\s+', multiLine: true), '. ');
  text = text.replaceAll(RegExp(r'\s*[—–]\s*'), ', ');
  text = text.replaceAll(RegExp(r'\s*\n+\s*'), '. ');
  text = text.replaceAll(RegExp(r'\s+'), ' ');
  text = text.replaceAll(RegExp(r'\s+([,.;:])'), r'$1');
  text = text.replaceAll(RegExp(r'\.{2,}'), '.');
  return text.trim();
}

bool _isPortuguese(String language) =>
    language.trim().toLowerCase().startsWith('pt');

String _formatCalendarEventLines(String text) {
  final eventLine = RegExp(
    r'^\s*[-+]\s+\*{0,2}(\d{1,2})/(\d{1,2})\s+'
    r'(\d{1,2}):(\d{2})(?:\s*[–-]\s*(\d{1,2}):(\d{2}))?'
    r'\*{0,2}\s*[—-]\s*(.+?)\s+'
    r'\((Google|Outlook|Teams|Microsoft)\)\s*$',
    multiLine: true,
    caseSensitive: false,
  );
  return text.replaceAllMapped(eventLine, (match) {
    final day = int.parse(match.group(1)!);
    final month = int.parse(match.group(2)!);
    final startHour = int.parse(match.group(3)!);
    final startMinute = int.parse(match.group(4)!);
    final endHour = int.tryParse(match.group(5) ?? '');
    final endMinute = int.tryParse(match.group(6) ?? '');
    final title = (match.group(7) ?? '').replaceAll(
      RegExp(r'\\([\\`*_{}\[\]()#+.!|>])'),
      r'$1',
    );
    final provider = _spokenProvider(match.group(8) ?? '');
    final date = _spokenShortDate(day, month, prefixDay: true);
    final time = endHour == null || endMinute == null
        ? _atTime(startHour, startMinute)
        : _timeRange(startHour, startMinute, endHour, endMinute);
    return 'No $date, $time: $title, $provider.';
  });
}

String _formatCalendarPeriods(String text) {
  final range = RegExp(
    r'Encontrei\s+(\d+)\s+evento(?:\(s\)|s)?\s+de\s+'
    r'(\d{1,2})/(\d{1,2})/(\d{4})\s+a\s+'
    r'(\d{1,2})/(\d{1,2})/(\d{4})\s*:',
    caseSensitive: false,
  );
  text = text.replaceAllMapped(range, (match) {
    final count = int.parse(match.group(1)!);
    final start = _spokenFullDate(
      int.parse(match.group(2)!),
      int.parse(match.group(3)!),
      int.parse(match.group(4)!),
    );
    final end = _spokenFullDate(
      int.parse(match.group(5)!),
      int.parse(match.group(6)!),
      int.parse(match.group(7)!),
    );
    return '${_eventCount(count)} entre $start e $end.';
  });

  final singleDay = RegExp(
    r'Encontrei\s+(\d+)\s+evento(?:\(s\)|s)?\s+em\s+'
    r'(\d{1,2})/(\d{1,2})/(\d{4})\s*:',
    caseSensitive: false,
  );
  return text.replaceAllMapped(singleDay, (match) {
    final count = int.parse(match.group(1)!);
    final date = _spokenFullDate(
      int.parse(match.group(2)!),
      int.parse(match.group(3)!),
      int.parse(match.group(4)!),
    );
    return '${_eventCount(count)} em $date.';
  });
}

String _formatFullDates(String text) => text.replaceAllMapped(
      RegExp(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b'),
      (match) => _spokenFullDate(
        int.parse(match.group(1)!),
        int.parse(match.group(2)!),
        int.parse(match.group(3)!),
      ),
    );

String _formatShortDates(String text) => text.replaceAllMapped(
      RegExp(r'\b(\d{1,2})/(\d{1,2})(?!/\d)\b'),
      (match) => _spokenShortDate(
        int.parse(match.group(1)!),
        int.parse(match.group(2)!),
      ),
    );

String _formatTimeRanges(String text) => text.replaceAllMapped(
      RegExp(
        r'\b(?:das?\s+)?(\d{1,2}):(\d{2})\s*'
        r'(?:[–-]|a|às)\s*(\d{1,2}):(\d{2})\b',
        caseSensitive: false,
      ),
      (match) => _timeRange(
        int.parse(match.group(1)!),
        int.parse(match.group(2)!),
        int.parse(match.group(3)!),
        int.parse(match.group(4)!),
      ),
    );

String _formatStandaloneTimes(String text) {
  text = text.replaceAllMapped(
    RegExp(r'(?:às|as)\s+(\d{1,2}):(\d{2})\b', caseSensitive: false),
    (match) => _atTime(
      int.parse(match.group(1)!),
      int.parse(match.group(2)!),
    ),
  );
  return text.replaceAllMapped(
    RegExp(r'(?:às|as)\s+(\d{1,2})h(\d{2})\b', caseSensitive: false),
    (match) => _atTime(
      int.parse(match.group(1)!),
      int.parse(match.group(2)!),
    ),
  );
}

String _eventCount(int count) =>
    count == 1 ? 'Encontrei um evento' : 'Encontrei $count eventos';

String _spokenProvider(String provider) {
  switch (provider.toLowerCase()) {
    case 'google':
      return 'no Google Agenda';
    case 'microsoft':
      return 'no calendário da Microsoft';
    case 'outlook':
      return 'no Outlook';
    case 'teams':
      return 'no Teams';
    default:
      return 'no calendário';
  }
}

String _spokenFullDate(int day, int month, int year) {
  final short = _spokenShortDate(day, month);
  return '$short de $year';
}

String _spokenShortDate(int day, int month, {bool prefixDay = false}) {
  if (month < 1 || month > _monthsPt.length) {
    return '${prefixDay ? 'dia ' : ''}$day do mês $month';
  }
  return '${prefixDay ? 'dia ' : ''}$day de ${_monthsPt[month - 1]}';
}

String _timeRange(
  int startHour,
  int startMinute,
  int endHour,
  int endMinute,
) {
  final start = _spokenTime(startHour, startMinute);
  final end = _spokenTime(endHour, endMinute);
  final from = startHour == 1 || start == 'meia-noite' || start == 'meio-dia'
      ? 'da'
      : 'das';
  final until = end == 'meia-noite'
      ? 'à meia-noite'
      : end == 'meio-dia'
          ? 'ao meio-dia'
          : endHour == 1
              ? 'à $end'
              : 'às $end';
  return '$from $start $until';
}

String _atTime(int hour, int minute) {
  final time = _spokenTime(hour, minute);
  if (time == 'meia-noite') return 'à meia-noite';
  if (time == 'meio-dia') return 'ao meio-dia';
  return hour == 1 ? 'à $time' : 'às $time';
}

String _spokenTime(int hour, int minute) {
  if (hour == 0 && minute == 0) return 'meia-noite';
  if (hour == 12 && minute == 0) return 'meio-dia';
  final hours = hour == 1 ? '1 hora' : '$hour horas';
  if (minute == 0) return hours;
  final minutes = minute == 1 ? '1 minuto' : '$minute minutos';
  return '$hours e $minutes';
}

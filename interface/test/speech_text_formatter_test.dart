import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/speech_text_formatter.dart';

void main() {
  test('turns a compact calendar response into natural Portuguese speech', () {
    const response = '''
Encontrei 1 evento de 10/08/2026 a 16/08/2026:
- **14/08 17:00–18:00** — Consulta às Rede D'Or (Google)
''';

    final speech = formatSpeechText(response);

    expect(
      speech,
      contains(
        'Encontrei um evento entre 10 de agosto de 2026 e '
        '16 de agosto de 2026.',
      ),
    );
    expect(
      speech,
      contains(
        "No dia 14 de agosto, das 17 horas às 18 horas: "
        "Consulta às Rede D'Or, no Google Agenda.",
      ),
    );
    expect(speech, isNot(contains('**')));
    expect(speech, isNot(contains('evento(s)')));
  });

  test('uses singular and speaks minutes naturally', () {
    const response = '''
Encontrei 1 evento em 05/08/2026:
- **05/08 09:30–10:45** — Reunião pedagógica (Outlook)
''';

    final speech = formatSpeechText(response);

    expect(speech, startsWith('Encontrei um evento em 5 de agosto de 2026.'));
    expect(
      speech,
      contains(
        'No dia 5 de agosto, das 9 horas e 30 minutos às '
        '10 horas e 45 minutos: Reunião pedagógica, no Outlook.',
      ),
    );
  });

  test('keeps non-Portuguese dates untouched while removing Markdown', () {
    final speech = formatSpeechText(
      '**Meeting** on 14/08 at `17:00`.',
      language: 'en-US',
    );

    expect(speech, 'Meeting on 14/08 at 17:00.');
  });

  test('humanizes a creation proposal and does not read the meeting URL', () {
    const response =
        'Preparei o evento “Bate-papo Dev Python GENAI” para 10/08/2026 '
        'às 14:30. Link da reunião: '
        'https://teams.live.com/meet/9360968074888?p=secret';

    final speech = formatSpeechText(response);

    expect(speech, contains('10 de agosto de 2026'));
    expect(speech, contains('às 14 horas e 30 minutos'));
    expect(speech, contains('link da reunião disponível nos detalhes'));
    expect(speech, isNot(contains('https://')));
    expect(speech, isNot(contains('p=secret')));
  });
}

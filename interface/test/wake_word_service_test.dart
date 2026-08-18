import 'package:flutter_test/flutter_test.dart';
import 'package:assistant_app/services/wake_word_service.dart';

void main() {
  test('uses the configured assistant name as wake word', () {
    final command = parseWakeWordCommand(
      'Hannah, abra o modo educação',
      'Hannah',
    );

    expect(command.usedWakeWord, isTrue);
    expect(command.text, 'abra o modo educação');
  });

  test('accepts a common phonetic transcription of Hannah', () {
    final command = parseWakeWordCommand(
      'Ana abra a agenda',
      'Hannah',
    );

    expect(command.usedWakeWord, isTrue);
    expect(command.text, 'abra a agenda');
  });

  test('does not keep Dani as a hidden wake word', () {
    final command = parseWakeWordCommand(
      'Dani abra a agenda',
      'Hannah',
    );

    expect(command.usedWakeWord, isFalse);
    expect(command.text, 'Dani abra a agenda');
  });

  test('allows a greeting before the configured name', () {
    final command = parseWakeWordCommand(
      'Oi Hannah, quais são meus compromissos?',
      'Hannah',
    );

    expect(command.usedWakeWord, isTrue);
    expect(command.text, 'quais são meus compromissos');
  });

  test('uses the per-user pronunciation as an additional wake word', () {
    final command = parseWakeWordCommand(
      'Raná, abra o modo educação',
      'Hannah',
      'Raná',
    );

    expect(command.usedWakeWord, isTrue);
    expect(command.text, 'abra o modo educação');
  });

  test('pronunciation changes only synthesized speech, not displayed text', () {
    const displayed = 'Hannah está pronta. Fale com Hannah.';
    final spoken = applyAssistantPronunciation(displayed, 'Hannah', 'Raná');

    expect(spoken, 'Raná está pronta. Fale com Raná.');
    expect(displayed, contains('Hannah'));
  });
}

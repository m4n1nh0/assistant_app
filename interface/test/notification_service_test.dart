import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/services/notification_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('event message uses the configured advance in minutes', () {
    final service = NotificationService(
      NotifConfig(reminderMinutes: 45),
      'Dani',
    );
    final event = CalendarEvent(
      id: 'event-1',
      title: 'Aula de Banco de Dados',
      startTime: DateTime(2026, 8, 17, 19),
      source: 'google',
    );

    final message = service.buildEventMessage(event, is15min: true);

    expect(message, contains('em 45 minutos'));
    expect(message, contains('Aula de Banco de Dados'));
  });

  test('send explains that no channel is active instead of failing silently',
      () async {
    final service = NotificationService(NotifConfig(), 'Dani');

    final result = await service.send('teste');

    expect(result.ok, isFalse);
    expect(result.detail, contains('nenhum canal ativo'));
    expect(result.summary, contains('Não enviada'));
  });

  test('send points to the missing Telegram credentials', () async {
    final service = NotificationService(
      NotifConfig(tgEnabled: true, tgToken: '  ', tgChatId: ''),
      'Dani',
    );

    final result = await service.send('teste');

    expect(result.ok, isFalse);
    expect(result.detail, contains('token ou Chat ID'));
  });
}

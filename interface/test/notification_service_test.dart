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
}

import 'package:assistant_app/models/app_config.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('LlmStatus reports checking separately from offline', () {
    const status = LlmStatus(
      id: 'gpt',
      label: 'GPT',
      configured: true,
      online: false,
      available: false,
      hasBalanceCheck: false,
      status: 'checking',
    );

    expect(status.shortStatus, 'CHECANDO');
  });

  test('CalendarCreateAction parses structured assistant proposal', () {
    final action = CalendarCreateAction.fromJson({
      'type': 'calendar_create',
      'title': 'Consulta',
      'start_time': '2026-08-10T14:00:00-03:00',
      'end_time': '2026-08-10T15:00:00-03:00',
      'timezone': 'America/Sao_Paulo',
      'provider': 'google',
      'requires_confirmation': true,
    });

    expect(action.title, 'Consulta');
    expect(action.provider, 'google');
    expect(
        action.endTime.difference(action.startTime), const Duration(hours: 1));
    expect(action.requiresConfirmation, isTrue);
  });

  test('CalendarEvent parses API snake case response', () {
    final event = CalendarEvent.fromJson({
      'id': 'google:one:event',
      'title': 'Consulta',
      'start_time': '2026-08-10T17:00:00Z',
      'end_time': '2026-08-10T18:00:00Z',
      'source': 'google',
    });

    expect(event.id, 'google:one:event');
    expect(event.title, 'Consulta');
    expect(event.endTime, isNotNull);
  });

  test('EducationOpenAction identifies the requested education tab', () {
    final action = EducationOpenAction.fromJson({
      'type': 'education_open',
      'destination': 'attendance',
      'reason': 'Inicio de chamada.',
      'requires_confirmation': true,
    });

    expect(action.destination, 'attendance');
    expect(action.requiresConfirmation, isTrue);
  });

  test('CalendarConfig keeps automatic creation disabled by default', () {
    expect(CalendarConfig().autoCreateEvents, isFalse);

    final restored = CalendarConfig.fromJson({
      'autoCreateEvents': true,
    });
    expect(restored.autoCreateEvents, isTrue);
    expect(restored.toJson()['autoCreateEvents'], isTrue);
  });

  test('send on enter is optional and survives persistence payload', () {
    expect(AppConfig().sendMessageOnEnter, isTrue);

    final restored = AppConfig.fromJson({'sendMessageOnEnter': false});
    expect(restored.sendMessageOnEnter, isFalse);
    expect(restored.toJson()['sendMessageOnEnter'], isFalse);
  });

  test('calendar reminder minutes survive backend and local payloads', () {
    final fromBackend = NotifConfig.fromJson({
      'notify_15min': true,
      'reminder_minutes': 30,
    });
    expect(fromBackend.reminderMinutes, 30);
    expect(fromBackend.toJson()['reminderMinutes'], 30);

    final clamped = NotifConfig.fromJson({'reminderMinutes': 9999});
    expect(clamped.reminderMinutes, 1440);
  });
}

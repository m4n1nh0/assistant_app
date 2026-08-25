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

  test('retired Railway backend URL migrates to local default', () {
    final restored = AppConfig.fromJson({
      'backendUrl': 'https://assistantapp-production-cabc.up.railway.app',
    });

    expect(restored.backendUrl, AppConfig.defaultBackendUrl);
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

  test('selected audio input survives persistence payload', () {
    final restored = AppConfig.fromJson({
      'audioInputDeviceId': 'jbl-hands-free',
      'audioInputDeviceLabel': 'JBL Hands-Free AG Audio',
    });

    expect(restored.audioInputDeviceId, 'jbl-hands-free');
    expect(restored.audioInputDeviceLabel, 'JBL Hands-Free AG Audio');
    expect(restored.toJson()['audioInputDeviceId'], 'jbl-hands-free');
  });

  test('unnamed and legacy personas use Assistant as the default', () {
    expect(AppConfig().assistantName, 'Assistant');
    expect(AppConfig.fromJson({}).assistantName, 'Assistant');
    expect(
      AppConfig.fromJson({'assistantName': 'Assistente'}).assistantName,
      'Assistant',
    );
    expect(
      AppConfig.fromJson({'assistantName': 'Hannah'}).assistantName,
      'Hannah',
    );
  });

  test('assistant pronunciation survives persistence payload', () {
    final restored = AppConfig.fromJson({
      'assistantName': 'Hannah',
      'assistantPronunciation': 'Raná',
    });

    expect(restored.assistantPronunciation, 'Raná');
    expect(restored.toJson()['assistantPronunciation'], 'Raná');
  });

  test('legacy exclusive connected mode migrates to agent selection', () {
    final restored = AppConfig.fromJson({
      'connectedAgentMode': true,
      'connectedAgentId': 'claude_cli',
    });

    expect(restored.selectedAgent, 'claude_cli');
    expect(restored.serviceName('claude_cli'), 'Claude conectado');
    expect(restored.toSafeJson()['selectedAgent'], 'claude_cli');
  });

  test('agent selection and connected agents survive persistence', () {
    final restored = AppConfig.fromJson({
      'selectedAgent': 'deepseek',
      'connectedAgents': {'claude_cli': true, 'codex_cli': false},
      'activeLlms': {'deepseek': true, 'gpt': true},
    });

    expect(restored.selectedAgent, 'deepseek');
    expect(restored.connectedAgentList, ['claude_cli']);
    expect(restored.availableAgents, ['deepseek', 'gpt', 'claude_cli']);
    expect(restored.effectiveAgent, 'deepseek');
    expect(restored.toSafeJson()['selectedAgent'], 'deepseek');
  });

  test('selection falls back to auto when the agent is unavailable', () {
    final config = AppConfig.fromJson({
      'selectedAgent': 'claude_cli',
      'connectedAgents': {'claude_cli': false},
      'activeLlms': {'gpt': true},
    });

    expect(config.effectiveAgent, AppConfig.autoAgent);
    expect(config.selectedIsConnectedAgent, isFalse);
  });
}

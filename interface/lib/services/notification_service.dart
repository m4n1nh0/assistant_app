import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/app_config.dart';

class SendResult {
  final bool ok;
  SendResult(this.ok);
  String get summary =>
      ok ? '✅ Notificação enviada!' : '❌ Falhou — verifique as configurações';
}

class NotificationService {
  final NotifConfig config;
  final String assistantName;

  NotificationService(this.config, this.assistantName);

  String buildEventMessage(CalendarEvent event, {required bool is15min}) {
    final when = is15min ? 'em ${config.reminderMinutes} minutos' : 'agora';
    final buf = StringBuffer();
    buf.write('🔔 [$assistantName] ${event.title} — $when');
    if (config.includeLink && event.meetingUrl != null) {
      buf.write('\n🔗 ${event.meetingUrl}');
    }
    return buf.toString();
  }

  Future<SendResult> send(String message, {CalendarEvent? event}) async {
    bool ok = false;
    if (config.tgEnabled && config.tgToken.isNotEmpty) {
      ok = await _sendTelegram(message) || ok;
    }
    if (!ok &&
        config.fallbackEnabled &&
        config.waEnabled &&
        config.waNumber.isNotEmpty) {
      ok = await _sendWhatsApp(message) || ok;
    }
    return SendResult(ok);
  }

  Future<bool> testTelegram() async {
    try {
      if (config.tgToken.isEmpty || config.tgChatId.isEmpty) return false;
      return await _sendTelegram('Assistente conectado! Notificacoes ativas.')
          .timeout(const Duration(seconds: 15));
    } catch (_) {
      return false;
    }
  }

  Future<bool> _sendTelegram(String message) async {
    try {
      final url = Uri.parse(
        'https://api.telegram.org/bot${config.tgToken}/sendMessage',
      );
      final r = await http.post(url, body: {
        'chat_id': config.tgChatId,
        'text': message
      }).timeout(const Duration(seconds: 10));
      final data = jsonDecode(r.body) as Map<String, dynamic>;
      return data['ok'] == true;
    } catch (_) {
      return false;
    }
  }

  String buildReminderMessage(CalendarEvent event, int minutesBefore) {
    final when = minutesBefore >= 60
        ? 'em ${minutesBefore ~/ 60}h${(minutesBefore % 60) == 0 ? '' : '${minutesBefore % 60}min'}'
        : 'em $minutesBefore minutos';
    final buf = StringBuffer('🔔 [$assistantName] ${event.title} — $when');
    if (config.includeLink && (event.meetingUrl?.isNotEmpty ?? false)) {
      buf.write('\n🔗 ${event.meetingUrl}');
    }
    return buf.toString();
  }

  Future<bool> _sendWhatsApp(String message) async {
    try {
      switch (config.waProvider) {
        case 'callmebot':
          final url = Uri.parse(
            'https://api.callmebot.com/whatsapp.php'
            '?phone=${Uri.encodeComponent(config.waNumber)}'
            '&text=${Uri.encodeComponent(message)}'
            '&apikey=${Uri.encodeComponent(config.waToken)}',
          );
          final r = await http.get(url).timeout(const Duration(seconds: 10));
          return r.statusCode == 200;
        default:
          return false;
      }
    } catch (_) {
      return false;
    }
  }
}

/// Lembrete agendado pelo botão Notificar do painel de próximos eventos.
class PendingEventReminder {
  final String eventId;
  final String title;
  final int minutesBefore;
  final DateTime fireAt;

  const PendingEventReminder({
    required this.eventId,
    required this.title,
    required this.minutesBefore,
    required this.fireAt,
  });
}

/// Agenda lembretes por evento com antecedência escolhida pelo usuário.
/// Os timers vivem enquanto o app estiver aberto (mesma limitação dos
/// lembretes automáticos da agenda) e cada evento tem no máximo um lembrete
/// manual: reagendar substitui o anterior.
class EventReminderScheduler {
  static final Map<String, Timer> _timers = {};
  static final Map<String, PendingEventReminder> _pending = {};

  static PendingEventReminder? pendingFor(String eventId) => _pending[eventId];

  /// Agenda (ou reagenda) o envio para [minutesBefore] minutos antes do
  /// início do evento e retorna o horário de disparo. Se esse horário já
  /// passou, o envio acontece imediatamente.
  static DateTime schedule({
    required CalendarEvent event,
    required int minutesBefore,
    required NotifConfig notif,
    required String assistantName,
  }) {
    cancel(event.id);
    final fireAt = event.startTime.subtract(Duration(minutes: minutesBefore));
    var delay = fireAt.difference(DateTime.now());
    if (delay.isNegative) delay = Duration.zero;

    _pending[event.id] = PendingEventReminder(
      eventId: event.id,
      title: event.title,
      minutesBefore: minutesBefore,
      fireAt: fireAt,
    );
    _timers[event.id] = Timer(delay, () {
      _timers.remove(event.id);
      _pending.remove(event.id);
      final service = NotificationService(notif, assistantName);
      unawaited(
        service.send(
          service.buildReminderMessage(event, minutesBefore),
          event: event,
        ),
      );
    });
    return fireAt;
  }

  static bool cancel(String eventId) {
    _timers.remove(eventId)?.cancel();
    return _pending.remove(eventId) != null;
  }
}

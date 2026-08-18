import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/app_config.dart';

class SendResult {
  final bool ok;

  /// Motivo da falha (ou canal usado no sucesso). Sem isso a notificação
  /// falhava em silêncio e não dava para saber o que corrigir.
  final String detail;

  const SendResult(this.ok, [this.detail = '']);

  String get summary => ok
      ? '✅ Notificação enviada${detail.isEmpty ? '' : ' via $detail'}!'
      : '❌ Não enviada — ${detail.isEmpty ? 'verifique as configurações' : detail}';
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
    final problems = <String>[];

    if (config.tgEnabled) {
      if (config.tgToken.trim().isEmpty || config.tgChatId.trim().isEmpty) {
        problems.add('Telegram sem token ou Chat ID em Configuracoes');
      } else {
        final error = await _sendTelegram(message);
        if (error == null) return const SendResult(true, 'Telegram');
        problems.add('Telegram: $error');
      }
    }

    final canUseWhatsApp =
        config.waEnabled && config.waNumber.trim().isNotEmpty;
    if (canUseWhatsApp && (problems.isEmpty || config.fallbackEnabled)) {
      if (await _sendWhatsApp(message)) {
        return const SendResult(true, 'WhatsApp');
      }
      problems.add('WhatsApp recusou o envio');
    }

    if (problems.isEmpty) {
      return const SendResult(
        false,
        'nenhum canal ativo (ative Telegram ou WhatsApp em Configuracoes)',
      );
    }
    return SendResult(false, problems.join(' | '));
  }

  Future<bool> testTelegram() async {
    try {
      if (config.tgToken.trim().isEmpty || config.tgChatId.trim().isEmpty) {
        return false;
      }
      final error =
          await _sendTelegram('Assistente conectado! Notificacoes ativas.')
              .timeout(const Duration(seconds: 15));
      return error == null;
    } catch (_) {
      return false;
    }
  }

  /// Retorna null no sucesso ou uma mensagem explicando a recusa.
  Future<String?> _sendTelegram(String message) async {
    try {
      final url = Uri.parse(
        'https://api.telegram.org/bot${config.tgToken.trim()}/sendMessage',
      );
      final r = await http.post(url, body: {
        'chat_id': config.tgChatId.trim(),
        'text': message,
      }).timeout(const Duration(seconds: 10));
      final data = jsonDecode(r.body) as Map<String, dynamic>;
      if (data['ok'] == true) return null;
      return _telegramError(
        r.statusCode,
        data['description']?.toString() ?? '',
      );
    } on TimeoutException {
      return 'o Telegram demorou para responder';
    } catch (e) {
      return 'falha de conexao ($e)';
    }
  }

  /// Mesmas traducoes usadas pelo backend, sem expor token nem URL.
  static String _telegramError(int statusCode, String description) {
    final lowered = description.toLowerCase();
    if (statusCode == 401 || lowered.contains('unauthorized')) {
      return 'token do bot invalido (gere outro no BotFather)';
    }
    if (lowered.contains('chat not found')) {
      return 'Chat ID nao encontrado (envie /start para o bot e confira o ID)';
    }
    if (statusCode == 403 || lowered.contains('bot was blocked')) {
      return 'o bot foi bloqueado ou nao pode enviar nesse chat';
    }
    if (statusCode == 429 || lowered.contains('too many requests')) {
      return 'o Telegram limitou os envios; tente em instantes';
    }
    return description.isEmpty
        ? 'recusado pelo Telegram (HTTP $statusCode)'
        : 'recusado pelo Telegram ($description)';
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

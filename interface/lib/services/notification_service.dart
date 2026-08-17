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

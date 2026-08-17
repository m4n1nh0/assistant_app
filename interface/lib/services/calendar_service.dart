import '../models/app_config.dart';
import 'api_service.dart';

class CalendarService {
  final CalendarConfig config;

  CalendarService(this.config);

  Future<List<CalendarEvent>> fetchAllEvents() async {
    try {
      final items = await api.getEvents().timeout(const Duration(seconds: 30));
      return items.map(CalendarEvent.fromJson).toList();
    } catch (_) {
      return [];
    }
  }

  String getGoogleAuthUrl() {
    final params = {
      'client_id': config.gcalClientId,
      'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
      'response_type': 'code',
      'scope': 'https://www.googleapis.com/auth/calendar.events',
      'access_type': 'offline',
      'prompt': 'consent',
    };
    final qs = params.entries
        .map((e) => '${e.key}=${Uri.encodeComponent(e.value)}')
        .join('&');
    return 'https://accounts.google.com/o/oauth2/auth?$qs';
  }
}

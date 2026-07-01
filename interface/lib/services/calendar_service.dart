import '../models/app_config.dart';
import 'api_service.dart';

class CalendarService {
  final CalendarConfig config;

  CalendarService(this.config);

  Future<List<CalendarEvent>> fetchAllEvents() async {
    try {
      final items = await api.getEvents().timeout(const Duration(seconds: 30));
      return items.map(_parseEvent).toList();
    } catch (_) {
      return [];
    }
  }

  String getGoogleAuthUrl() {
    final params = {
      'client_id': config.gcalClientId,
      'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
      'response_type': 'code',
      'scope': 'https://www.googleapis.com/auth/calendar.readonly',
      'access_type': 'offline',
      'prompt': 'consent',
    };
    final qs = params.entries
        .map((e) => '${e.key}=${Uri.encodeComponent(e.value)}')
        .join('&');
    return 'https://accounts.google.com/o/oauth2/auth?$qs';
  }

  String getMicrosoftAuthUrl() {
    final tenant = config.msTenantId.isEmpty ? 'common' : config.msTenantId;
    final params = {
      'client_id': config.msClientId,
      'response_type': 'code',
      'redirect_uri':
          'https://login.microsoftonline.com/common/oauth2/nativeclient',
      'scope': 'Calendars.Read offline_access',
      'response_mode': 'query',
    };
    final qs = params.entries
        .map((e) => '${e.key}=${Uri.encodeComponent(e.value)}')
        .join('&');
    return 'https://login.microsoftonline.com/$tenant/oauth2/v2.0/authorize?$qs';
  }

  CalendarEvent _parseEvent(Map<String, dynamic> e) {
    return CalendarEvent(
      id: e['id'] ?? '',
      title: e['title'] ?? 'Sem título',
      startTime: DateTime.parse(e['start_time']).toLocal(),
      endTime: e['end_time'] != null
          ? DateTime.parse(e['end_time']).toLocal()
          : null,
      source: e['source'] ?? 'google',
      meetingUrl: e['meeting_url'] as String?,
      description: e['description'] as String?,
      notified15: e['notified_15'] == true,
      notifiedOnTime: e['notified_0'] == true,
    );
  }
}

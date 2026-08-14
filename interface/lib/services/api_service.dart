import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/app_config.dart';
import 'storage_service.dart';

class ApiService {
  String baseUrl;
  String wsUrl;
  String? _token;

  WebSocketChannel? _ws;
  StreamController<Map<String, dynamic>>? _wsStream;

  ApiService({String backendUrl = AppConfig.defaultBackendUrl})
      : baseUrl = _normalizeHttpUrl(backendUrl),
        wsUrl = _toWsUrl(_normalizeHttpUrl(backendUrl));

  /// Reponta o cliente para outro backend em runtime (chamado ao carregar ou
  /// salvar as configurações). Sobrescreve [baseUrl] e [wsUrl].
  void configure(String backendUrl) {
    baseUrl = _normalizeHttpUrl(backendUrl);
    wsUrl = _toWsUrl(baseUrl);
  }

  static String _normalizeHttpUrl(String value) {
    var v = value.trim();
    if (v.isEmpty) return AppConfig.defaultBackendUrl;
    if (!v.contains('://')) v = 'http://$v';
    while (v.endsWith('/')) {
      v = v.substring(0, v.length - 1);
    }
    return v;
  }

  static String _toWsUrl(String httpUrl) {
    if (httpUrl.startsWith('https://')) return 'wss://${httpUrl.substring(8)}';
    if (httpUrl.startsWith('http://')) return 'ws://${httpUrl.substring(7)}';
    return httpUrl;
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token != null) 'Authorization': 'Bearer $_token',
      };

  String? get token => _token;

  void setToken(String? token) {
    _token = token;
  }

  Future<Map<String, dynamic>> health() async {
    final r = await http
        .get(Uri.parse('$baseUrl/health'))
        .timeout(const Duration(seconds: 15));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Returns first-run registration requirements from the backend.
  Future<AuthSetupStatus> authStatus() async {
    final r = await http
        .get(Uri.parse('$baseUrl/auth/status'))
        .timeout(const Duration(seconds: 10));
    if (r.statusCode >= 400) {
      return const AuthSetupStatus(needsSetup: false);
    }
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return AuthSetupStatus.fromJson(data);
  }

  Future<bool> needsAuthSetup() async => (await authStatus()).needsSetup;

  Future<String> requestRegistrationToken() async {
    final r = await http.post(
      Uri.parse('$baseUrl/auth/registration-token'),
      headers: _headers,
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    if (r.statusCode >= 400) {
      throw Exception(
        data['detail']?.toString() ?? 'Falha ao enviar token administrativo',
      );
    }
    return data['message']?.toString() ??
        'Token enviado ao email administrativo.';
  }

  Future<AuthResult> register(
    String username,
    String password, {
    String registrationToken = '',
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/auth/register'),
      headers: _headers,
      body: jsonEncode({
        'username': username,
        'password': password,
        'registration_token': registrationToken,
      }),
    );
    return _handleAuthResponse(r);
  }

  Future<AuthResult> login(String username, String password) async {
    final r = await http.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: _headers,
      body: jsonEncode({'username': username, 'password': password}),
    );
    return _handleAuthResponse(r);
  }

  AuthResult _handleAuthResponse(http.Response r) {
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    if (data['success'] == true) {
      _token = data['token'] as String?;
    }
    return AuthResult(
      success: data['success'] == true,
      message: (data['message'] ?? data['detail'])?.toString() ?? '',
      token: data['token'] as String?,
    );
  }

  /// Renews the session before it expires. A recorded lesson can outlive the
  /// token, and every audio chunk after that would come back 401.
  Future<bool> refreshSession() async {
    if (_token == null) return false;
    try {
      final r = await http
          .post(Uri.parse('$baseUrl/auth/refresh'), headers: _headers)
          .timeout(const Duration(seconds: 10));
      if (r.statusCode >= 400) return false;
      final data = jsonDecode(r.body) as Map<String, dynamic>;
      final token = data['token'] as String?;
      if (data['success'] != true || token == null || token.isEmpty) {
        return false;
      }
      _token = token;
      await StorageService.saveAuthToken(token);
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Validates the current in-memory token and returns its account context.
  Future<CurrentAccount?> currentAccount() async {
    if (_token == null) return null;
    try {
      final r = await http
          .get(Uri.parse('$baseUrl/auth/me'), headers: _headers)
          .timeout(const Duration(seconds: 10));
      if (r.statusCode >= 400) return null;
      final data = jsonDecode(r.body) as Map<String, dynamic>;
      return CurrentAccount.fromJson(data);
    } catch (_) {
      return null;
    }
  }

  Future<String?> currentUsername() async => (await currentAccount())?.username;

  Future<String> inviteUser(String email) async {
    final r = await http.post(
      Uri.parse('$baseUrl/auth/invitations'),
      headers: _headers,
      body: jsonEncode({'email': email}),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    if (r.statusCode >= 400) {
      throw Exception(data['detail']?.toString() ?? 'Falha ao enviar convite');
    }
    return data['message']?.toString() ?? 'Convite enviado por email.';
  }

  Future<List<AdminUser>> listUsers() async {
    final r = await http.get(
      Uri.parse('$baseUrl/auth/users'),
      headers: _headers,
    );
    final data = jsonDecode(r.body);
    if (r.statusCode >= 400) {
      final detail = data is Map<String, dynamic> ? data['detail'] : null;
      throw Exception(detail?.toString() ?? 'Falha ao carregar usuarios');
    }
    return (data as List<dynamic>)
        .whereType<Map<String, dynamic>>()
        .map(AdminUser.fromJson)
        .toList();
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final r = await http.put(
      Uri.parse('$baseUrl/auth/password'),
      headers: _headers,
      body: jsonEncode({
        'current_password': currentPassword,
        'new_password': newPassword,
      }),
    );
    if (r.statusCode >= 400) {
      final data = jsonDecode(r.body) as Map<String, dynamic>;
      throw Exception(data['detail'] ?? 'Falha ao trocar senha');
    }
  }

  void logout() {
    _token = null;
    disconnectWebSocket();
  }

  Future<Map<String, dynamic>> chat({
    required String message,
    List<Map<String, String>> history = const [],
    String mode = 'single',
    String? llm,
    String sessionId = 'default',
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/chat/'),
      headers: _headers,
      body: jsonEncode({
        'message': message,
        'history': history,
        'mode': mode,
        if (llm != null) 'llm': llm,
        'session_id': sessionId,
        'stream': false,
      }),
    );
    return _decodeObjectResponse(
      r,
      httpError: 'Falha ao conversar com o assistente',
      invalidResponse: 'Resposta invalida recebida do assistente',
    );
  }

  Stream<String> chatStream({
    required String message,
    List<Map<String, String>> history = const [],
    String? llm,
    String sessionId = 'default',
  }) async* {
    final request = http.Request('POST', Uri.parse('$baseUrl/chat/stream'));
    request.headers.addAll(_headers);
    request.body = jsonEncode({
      'message': message,
      'history': history,
      if (llm != null) 'llm': llm,
      'session_id': sessionId,
      'stream': true,
    });

    final response = await http.Client().send(request);
    await for (final chunk in response.stream.transform(utf8.decoder)) {
      for (final line in chunk.split('\n')) {
        if (line.startsWith('data: ')) {
          final json = jsonDecode(line.substring(6)) as Map<String, dynamic>;
          if (json['chunk'] != null) yield json['chunk'] as String;
          if (json['done'] == true) return;
        }
      }
    }
  }

  Future<List<Map<String, dynamic>>> getHistory(String sessionId) async {
    final r = await http.get(Uri.parse('$baseUrl/chat/history/$sessionId'),
        headers: _headers);
    return (jsonDecode(r.body) as List).cast<Map<String, dynamic>>();
  }

  Future<void> clearHistory(String sessionId) async {
    await http.delete(Uri.parse('$baseUrl/chat/history/$sessionId'),
        headers: _headers);
  }

  Future<Map<String, dynamic>> storageStatus() async {
    final r = await http.get(Uri.parse('$baseUrl/system/storage/status'),
        headers: _headers);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<DesktopWindowInfo>> listDesktopWindows() async {
    final r = await http
        .get(Uri.parse('$baseUrl/desktop/windows'), headers: _headers)
        .timeout(const Duration(seconds: 8));
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao listar janelas');
    final windows = data['windows'] as List<dynamic>? ?? const [];
    return windows
        .map((item) => DesktopWindowInfo.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<DesktopWindowContext> getDesktopWindowContext(String windowId) async {
    final r = await http
        .get(
          Uri.parse(
            '$baseUrl/desktop/windows/${Uri.encodeComponent(windowId)}/context',
          ),
          headers: _headers,
        )
        .timeout(const Duration(seconds: 12));
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao ler janela');
    return DesktopWindowContext.fromJson(data);
  }

  Future<Map<String, dynamic>> saveTutorProfile(
      Map<String, dynamic> profile) async {
    final r = await http.put(
      Uri.parse('$baseUrl/tutor/'),
      headers: _headers,
      body: jsonEncode(profile),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getTutorProfile(String tutorId) async {
    final r =
        await http.get(Uri.parse('$baseUrl/tutor/$tutorId'), headers: _headers);
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> listMemoryReviews(String tutorId,
      {String status = 'pending'}) async {
    final r = await http.get(
      Uri.parse(
          '$baseUrl/memory/review?tutor_id=${Uri.encodeComponent(tutorId)}&status=${Uri.encodeComponent(status)}'),
      headers: _headers,
    );
    return (jsonDecode(r.body) as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> proposeMemory(
      Map<String, dynamic> memory) async {
    final r = await http.post(
      Uri.parse('$baseUrl/memory/review'),
      headers: _headers,
      body: jsonEncode(memory),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> approveMemory(String memoryId,
      {String reviewerNote = ''}) async {
    final r = await http.post(
      Uri.parse('$baseUrl/memory/review/$memoryId/approve'),
      headers: _headers,
      body: jsonEncode({'reviewer_note': reviewerNote}),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> rejectMemory(String memoryId,
      {String reviewerNote = ''}) async {
    final r = await http.post(
      Uri.parse('$baseUrl/memory/review/$memoryId/reject'),
      headers: _headers,
      body: jsonEncode({'reviewer_note': reviewerNote}),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> decideMemoryByVoice(
      String memoryId, String transcript,
      {String reviewerNote = ''}) async {
    final r = await http.post(
      Uri.parse('$baseUrl/memory/review/$memoryId/voice-decision'),
      headers: _headers,
      body: jsonEncode({
        'transcript': transcript,
        'reviewer_note': reviewerNote,
      }),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> decideMemoryByAudio(
      String memoryId, List<int> audioBytes,
      {String language = 'pt', String reviewerNote = ''}) async {
    final transcript = await transcribeAudio(audioBytes, language: language);
    return decideMemoryByVoice(memoryId, transcript,
        reviewerNote: reviewerNote);
  }

  Future<List<Map<String, dynamic>>> searchMemory(String tutorId, String query,
      {String? category, int limit = 5}) async {
    final params = {
      'tutor_id': tutorId,
      'q': query,
      'limit': '$limit',
      if (category != null) 'category': category,
    };
    final uri =
        Uri.parse('$baseUrl/memory/search').replace(queryParameters: params);
    final r = await http.get(uri, headers: _headers);
    return (jsonDecode(r.body) as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> approveAutomation(
      Map<String, dynamic> automation) async {
    final r = await http.post(
      Uri.parse('$baseUrl/automations/'),
      headers: _headers,
      body: jsonEncode(automation),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<Map<String, dynamic>>> listAutomations(String tutorId) async {
    final r = await http.get(
      Uri.parse(
          '$baseUrl/automations/?tutor_id=${Uri.encodeComponent(tutorId)}'),
      headers: _headers,
    );
    return (jsonDecode(r.body) as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> updateAutomation(
      String automationId, Map<String, dynamic> changes) async {
    final r = await http.patch(
      Uri.parse('$baseUrl/automations/$automationId'),
      headers: _headers,
      body: jsonEncode(changes),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<List<ShortcutEntry>> listShortcuts(String tutorId) async {
    final uri = Uri.parse('$baseUrl/launcher/shortcuts').replace(
      queryParameters: {'tutor_id': tutorId},
    );
    final r = await http.get(uri, headers: _headers);
    _throwIfHttpError(r, fallback: 'Falha ao listar atalhos');
    final data = jsonDecode(r.body) as List<dynamic>;
    return data
        .map((item) => ShortcutEntry.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<ShortcutEntry> createShortcut({
    required String tutorId,
    required String name,
    required String type,
    required String target,
    List<String> aliases = const [],
    String? description,
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/launcher/shortcuts'),
      headers: _headers,
      body: jsonEncode({
        'tutor_id': tutorId,
        'name': name,
        'type': type,
        'target': target,
        'aliases': aliases,
        if (description?.trim().isNotEmpty ?? false)
          'description': description!.trim(),
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao criar atalho');
    return ShortcutEntry.fromJson(data);
  }

  Future<ShortcutEntry> updateShortcut({
    required String shortcutId,
    required String name,
    required String type,
    required String target,
    List<String> aliases = const [],
    String? description,
  }) async {
    final r = await http.patch(
      Uri.parse('$baseUrl/launcher/shortcuts/$shortcutId'),
      headers: _headers,
      body: jsonEncode({
        'name': name,
        'type': type,
        'target': target,
        'aliases': aliases,
        'description': description?.trim() ?? '',
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao atualizar atalho');
    return ShortcutEntry.fromJson(data);
  }

  Future<String?> suggestCommand(String name) async {
    try {
      final r = await http
          .get(
            Uri.parse(
                '$baseUrl/launcher/suggest-command?name=${Uri.encodeComponent(name)}'),
            headers: _headers,
          )
          .timeout(const Duration(seconds: 20));
      if (r.statusCode == 200) {
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        final target = data['target']?.toString() ?? '';
        return target.isEmpty ? null : target;
      }
    } catch (_) {}
    return null;
  }

  Future<void> deleteShortcut(String shortcutId) async {
    final r = await http.delete(
      Uri.parse('$baseUrl/launcher/shortcuts/$shortcutId'),
      headers: _headers,
    );
    _throwIfHttpError(r, fallback: 'Falha ao remover atalho');
  }

  Future<List<SavedScriptEntry>> listSavedScripts(String tutorId) async {
    final uri = Uri.parse('$baseUrl/computer/scripts').replace(
      queryParameters: {'tutor_id': tutorId},
    );
    final r = await http.get(uri, headers: _headers);
    final data = jsonDecode(r.body);
    _throwIfHttpError(
      r,
      data: data is Map<String, dynamic> ? data : null,
      fallback: 'Falha ao listar scripts',
    );
    return (data as List<dynamic>)
        .map((item) => SavedScriptEntry.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<SavedScriptEntry> createSavedScript({
    required String tutorId,
    required String name,
    required String shell,
    required String script,
    String workingDirectory = '',
    int timeoutSeconds = 30,
    bool allowHighRisk = false,
    String description = '',
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/computer/scripts'),
      headers: _headers,
      body: jsonEncode({
        'tutor_id': tutorId,
        'name': name,
        'shell': shell,
        'script': script,
        if (workingDirectory.trim().isNotEmpty)
          'working_directory': workingDirectory.trim(),
        'timeout_seconds': timeoutSeconds,
        'allow_high_risk': allowHighRisk,
        'description': description.trim(),
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao salvar script');
    return SavedScriptEntry.fromJson(data);
  }

  Future<SavedScriptEntry> updateSavedScript({
    required String scriptId,
    required String name,
    required String shell,
    required String script,
    String workingDirectory = '',
    int timeoutSeconds = 30,
    bool allowHighRisk = false,
    String description = '',
  }) async {
    final r = await http.patch(
      Uri.parse('$baseUrl/computer/scripts/$scriptId'),
      headers: _headers,
      body: jsonEncode({
        'name': name,
        'shell': shell,
        'script': script,
        'working_directory': workingDirectory.trim(),
        'timeout_seconds': timeoutSeconds,
        'allow_high_risk': allowHighRisk,
        'description': description.trim(),
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao atualizar script');
    return SavedScriptEntry.fromJson(data);
  }

  Future<void> deleteSavedScript(String scriptId) async {
    final r = await http.delete(
      Uri.parse('$baseUrl/computer/scripts/$scriptId'),
      headers: _headers,
    );
    _throwIfHttpError(r, fallback: 'Falha ao remover script');
  }

  Future<void> confirmShortcutLaunched(
    String shortcutId, {
    String status = 'executed',
    String source = 'interface',
    String? platform,
    Map<String, dynamic> request = const {},
    Map<String, dynamic> result = const {},
    String? error,
  }) async {
    if (shortcutId.trim().isEmpty) return;
    final r = await http.post(
      Uri.parse('$baseUrl/launcher/shortcuts/$shortcutId/launched'),
      headers: _headers,
      body: jsonEncode({
        'status': status,
        'source': source,
        if (platform?.trim().isNotEmpty ?? false) 'platform': platform!.trim(),
        'request': request,
        'result': result,
        if (error?.trim().isNotEmpty ?? false) 'error': error!.trim(),
      }),
    );
    _throwIfHttpError(r, fallback: 'Falha ao registrar uso do atalho');
  }

  Future<List<ShortcutLaunchEntry>> listShortcutLaunches(
    String tutorId, {
    String? shortcutId,
    String? status,
    int limit = 100,
  }) async {
    final uri = Uri.parse('$baseUrl/launcher/launches').replace(
      queryParameters: {
        'tutor_id': tutorId,
        'limit': '$limit',
        if (shortcutId?.trim().isNotEmpty ?? false)
          'shortcut_id': shortcutId!.trim(),
        if (status?.trim().isNotEmpty ?? false) 'status': status!.trim(),
      },
    );
    final r = await http.get(uri, headers: _headers);
    _throwIfHttpError(r, fallback: 'Falha ao listar historico de apps');
    final data = jsonDecode(r.body) as List<dynamic>;
    return data
        .map((item) =>
            ShortcutLaunchEntry.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<List<ActionAuditEntry>> listActionAudits(
    String tutorId, {
    String? automationId,
  }) async {
    final uri = Uri.parse('$baseUrl/automations/audit').replace(
      queryParameters: {
        'tutor_id': tutorId,
        if (automationId?.trim().isNotEmpty ?? false)
          'automation_id': automationId!.trim(),
      },
    );
    final r = await http.get(uri, headers: _headers);
    final data = jsonDecode(r.body);
    _throwIfHttpError(
      r,
      data: data is Map<String, dynamic> ? data : null,
      fallback: 'Falha ao listar acoes',
    );
    return (data as List<dynamic>)
        .map((item) => ActionAuditEntry.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  void _throwIfHttpError(
    http.Response response, {
    Map<String, dynamic>? data,
    required String fallback,
  }) {
    if (response.statusCode < 400) return;
    Object? decoded = data;
    if (decoded == null && response.body.trim().isNotEmpty) {
      try {
        decoded = jsonDecode(response.body);
      } catch (_) {}
    }
    if (decoded is Map && decoded['detail'] != null) {
      throw Exception(decoded['detail']);
    }
    throw Exception('$fallback (HTTP ${response.statusCode})');
  }

  Map<String, dynamic> _decodeObjectResponse(
    http.Response response, {
    required String httpError,
    required String invalidResponse,
  }) {
    Object? decoded;
    if (response.body.trim().isNotEmpty) {
      try {
        decoded = jsonDecode(response.body);
      } catch (_) {
        _throwIfHttpError(response, fallback: httpError);
        throw FormatException(invalidResponse);
      }
    }

    _throwIfHttpError(
      response,
      data: decoded is Map<String, dynamic> ? decoded : null,
      fallback: httpError,
    );
    if (decoded is! Map) {
      throw FormatException(invalidResponse);
    }
    return decoded.map((key, value) => MapEntry(key.toString(), value));
  }

  Future<List<Map<String, dynamic>>> getEvents() async {
    final r = await http.get(Uri.parse('$baseUrl/calendar/events'),
        headers: _headers);
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    return (data['events'] as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> createCalendarEvent({
    required String provider,
    required String accountId,
    required String title,
    required DateTime startTime,
    required DateTime endTime,
    required String timezone,
    String? description,
    String? location,
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/calendar/events'),
      headers: _headers,
      body: jsonEncode({
        'provider': provider,
        'account_id': accountId,
        'title': title,
        'start_time': startTime.toIso8601String(),
        'end_time': endTime.toIso8601String(),
        'timezone': timezone,
        if (description?.trim().isNotEmpty ?? false)
          'description': description!.trim(),
        if (location?.trim().isNotEmpty ?? false) 'location': location!.trim(),
        'confirmed': true,
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao criar evento');
    return data;
  }

  Future<String> getGoogleAuthUrl() async {
    final r = await http.get(Uri.parse('$baseUrl/calendar/google/auth-url'),
        headers: _headers);
    return (jsonDecode(r.body) as Map<String, dynamic>)['url'] as String;
  }

  Future<CalendarConnectResult> startGoogleCalendarAuth() async {
    final r = await http.get(
      Uri.parse('$baseUrl/calendar/google/start'),
      headers: _headers,
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao iniciar Google Calendar');
    return CalendarConnectResult.fromJson(data);
  }

  Future<void> saveGoogleOAuthApp({
    required String clientId,
    required String clientSecret,
  }) async {
    final r = await http.put(
      Uri.parse('$baseUrl/calendar/google/oauth-app'),
      headers: _headers,
      body: jsonEncode({
        'client_id': clientId,
        'client_secret': clientSecret,
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao salvar credenciais Google');
  }

  Future<CalendarConnectResult> connectGoogleCalendar({
    required String clientId,
    required String clientSecret,
    String? label,
    String? accountId,
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/calendar/google/connect'),
      headers: _headers,
      body: jsonEncode({
        'client_id': clientId,
        'client_secret': clientSecret,
        if (label?.trim().isNotEmpty ?? false) 'label': label!.trim(),
        if (accountId?.trim().isNotEmpty ?? false)
          'account_id': accountId!.trim(),
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao iniciar Google Calendar');
    return CalendarConnectResult.fromJson(data);
  }

  Future<Map<String, dynamic>> finishGoogleCalendarAuth(
    String code, {
    String? accountId,
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/calendar/google/callback'),
      headers: _headers,
      body: jsonEncode({
        'code': code,
        if (accountId?.trim().isNotEmpty ?? false)
          'account_id': accountId!.trim(),
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao concluir Google Calendar');
    return data;
  }

  Future<Map<String, dynamic>> exchangeGoogleCode(String code) {
    return finishGoogleCalendarAuth(code);
  }

  Future<String> getMicrosoftAuthUrl() async {
    final r = await http.get(Uri.parse('$baseUrl/calendar/microsoft/auth-url'),
        headers: _headers);
    return (jsonDecode(r.body) as Map<String, dynamic>)['url'] as String;
  }

  Future<CalendarConnectResult> startMicrosoftCalendarAuth() async {
    final r = await http.get(
      Uri.parse('$baseUrl/calendar/microsoft/start'),
      headers: _headers,
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao iniciar Microsoft Calendar');
    return CalendarConnectResult.fromJson(data);
  }

  Future<void> saveMicrosoftOAuthApp({
    required String clientId,
    required String clientSecret,
    String tenantId = 'common',
  }) async {
    final r = await http.put(
      Uri.parse('$baseUrl/calendar/microsoft/oauth-app'),
      headers: _headers,
      body: jsonEncode({
        'client_id': clientId,
        'client_secret': clientSecret,
        'tenant_id': tenantId,
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao salvar credenciais Microsoft');
  }

  Future<CalendarConnectResult> connectMicrosoftCalendar({
    required String clientId,
    required String clientSecret,
    String tenantId = 'common',
    String? label,
    String? accountId,
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/calendar/microsoft/connect'),
      headers: _headers,
      body: jsonEncode({
        'client_id': clientId,
        'client_secret': clientSecret,
        'tenant_id': tenantId,
        if (label?.trim().isNotEmpty ?? false) 'label': label!.trim(),
        if (accountId?.trim().isNotEmpty ?? false)
          'account_id': accountId!.trim(),
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao iniciar Microsoft Calendar');
    return CalendarConnectResult.fromJson(data);
  }

  Future<Map<String, dynamic>> finishMicrosoftCalendarAuth(
    String code, {
    String? accountId,
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/calendar/microsoft/callback'),
      headers: _headers,
      body: jsonEncode({
        'code': code,
        if (accountId?.trim().isNotEmpty ?? false)
          'account_id': accountId!.trim(),
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao concluir Microsoft Calendar');
    return data;
  }

  Future<Map<String, List<CalendarAccount>>> listCalendarAccounts() async {
    final r = await http.get(
      Uri.parse('$baseUrl/calendar/accounts'),
      headers: _headers,
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao listar agendas');
    return {
      'google': (data['google'] as List<dynamic>? ?? const [])
          .map((item) => CalendarAccount.fromJson(item as Map<String, dynamic>))
          .toList(),
      'microsoft': (data['microsoft'] as List<dynamic>? ?? const [])
          .map((item) => CalendarAccount.fromJson(item as Map<String, dynamic>))
          .toList(),
    };
  }

  Future<void> disconnectCalendarAccount({
    required String provider,
    required String accountId,
  }) async {
    final normalized = provider == 'microsoft' ? 'microsoft' : 'google';
    final r = await http.delete(
      Uri.parse('$baseUrl/calendar/$normalized/accounts/$accountId'),
      headers: _headers,
    );
    _throwIfHttpError(r, fallback: 'Falha ao remover agenda');
  }

  Future<NotifConfig> getNotificationConfig() async {
    final r = await http.get(
      Uri.parse('$baseUrl/notifications/config'),
      headers: _headers,
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r,
        data: data, fallback: 'Falha ao carregar notificacoes');
    return NotifConfig.fromJson(data);
  }

  Future<NotifConfig> saveNotificationConfig(NotifConfig config) async {
    final r = await http.put(
      Uri.parse('$baseUrl/notifications/config'),
      headers: _headers,
      body: jsonEncode({
        'telegram_token': config.tgToken,
        'telegram_chat_id': config.tgChatId,
        'telegram_enabled': config.tgEnabled,
        'wa_provider': config.waProvider,
        'wa_number': config.waNumber,
        'wa_token': config.waToken,
        'wa_sid': config.waSid,
        'wa_enabled': config.waEnabled,
        'notify_15min': config.notify15min,
        'notify_on_time': config.notifyOnTime,
        'fallback_enabled': config.fallbackEnabled,
        'include_link': config.includeLink,
      }),
    );
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    _throwIfHttpError(r, data: data, fallback: 'Falha ao salvar notificacoes');
    return NotifConfig.fromJson(data);
  }

  Future<Map<String, dynamic>> sendNotification({
    required String message,
    List<String> channels = const ['telegram', 'whatsapp'],
  }) async {
    final r = await http.post(
      Uri.parse('$baseUrl/notifications/send'),
      headers: _headers,
      body: jsonEncode({'message': message, 'channels': channels}),
    );
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<bool> testTelegram() async {
    final r = await http.post(Uri.parse('$baseUrl/notifications/test/telegram'),
        headers: _headers);
    return (jsonDecode(r.body) as Map<String, dynamic>)['ok'] == true;
  }

  Future<bool> testWhatsApp() async {
    final r = await http.post(Uri.parse('$baseUrl/notifications/test/whatsapp'),
        headers: _headers);
    return (jsonDecode(r.body) as Map<String, dynamic>)['ok'] == true;
  }

  Future<String> transcribeAudio(List<int> audioBytes,
      {String language = 'pt'}) async {
    final request =
        http.MultipartRequest('POST', Uri.parse('$baseUrl/voice/transcribe'));
    request.headers
        .addAll(_token != null ? {'Authorization': 'Bearer $_token'} : {});
    request.files.add(http.MultipartFile.fromBytes('file', audioBytes,
        filename: 'audio.wav'));
    request.fields['language'] = language;
    final response = await request.send();
    final body = await response.stream.bytesToString();
    return (jsonDecode(body) as Map<String, dynamic>)['transcript']
            as String? ??
        '';
  }

  Future<List<int>> textToSpeech(String text,
      {String language = 'pt-BR', double speed = 0.95}) async {
    final r = await http
        .post(
          Uri.parse('$baseUrl/voice/tts'),
          headers: _headers,
          body:
              jsonEncode({'text': text, 'language': language, 'speed': speed}),
        )
        .timeout(const Duration(seconds: 8));
    if (r.statusCode >= 400 || r.bodyBytes.isEmpty) return const [];
    final contentType = r.headers['content-type'] ?? '';
    if (!contentType.toLowerCase().startsWith('audio/')) return const [];
    return r.bodyBytes.toList();
  }

  Stream<Map<String, dynamic>> connectWebSocket(String sessionId) {
    _wsStream = StreamController<Map<String, dynamic>>.broadcast();
    final tokenQuery =
        _token != null ? '?token=${Uri.encodeComponent(_token!)}' : '';
    _ws =
        WebSocketChannel.connect(Uri.parse('$wsUrl/ws/$sessionId$tokenQuery'));

    _ws!.stream.listen(
      (raw) {
        try {
          final data = jsonDecode(raw as String) as Map<String, dynamic>;
          _wsStream!.add(data);
        } catch (_) {}
      },
      onDone: () => _wsStream!.close(),
      onError: (e) => _wsStream!.addError(e),
    );

    return _wsStream!.stream;
  }

  void wsSend(Map<String, dynamic> data) {
    _ws?.sink.add(jsonEncode(data));
  }

  void wsChat({
    required String message,
    String mode = 'single',
    String? llm,
    bool stream = true,
    Map<String, String>? assistantMeta,
  }) {
    wsSend({
      'type': stream ? 'chat_stream' : 'chat',
      'payload': {
        'message': message,
        'mode': mode,
        if (llm != null) 'llm': llm,
        'stream': stream,
        ...?assistantMeta,
      },
    });
  }

  void wsCalendarSync(Map<String, String> calendarCreds) {
    wsSend({'type': 'calendar_sync', 'payload': calendarCreds});
  }

  void wsNotify(String message,
      {List<String> channels = const ['telegram', 'whatsapp']}) {
    wsSend({
      'type': 'notify',
      'payload': {'message': message, 'channels': channels}
    });
  }

  void wsPing() => wsSend({'type': 'ping', 'payload': {}});

  void disconnectWebSocket() {
    _ws?.sink.close();
    _wsStream?.close();
    _ws = null;
    _wsStream = null;
  }
}

final api = ApiService();

class CalendarConnectResult {
  final String authUrl;
  final String accountId;

  const CalendarConnectResult({
    required this.authUrl,
    required this.accountId,
  });

  factory CalendarConnectResult.fromJson(Map<String, dynamic> json) =>
      CalendarConnectResult(
        authUrl: (json['auth_url'] ?? json['url'])?.toString() ?? '',
        accountId: (json['account_id'] ?? json['accountId'])?.toString() ?? '',
      );
}

class CalendarAccount {
  final String id;
  final String provider;
  final String label;
  final bool connected;
  final String? tenantId;

  const CalendarAccount({
    required this.id,
    required this.provider,
    required this.label,
    required this.connected,
    this.tenantId,
  });

  factory CalendarAccount.fromJson(Map<String, dynamic> json) =>
      CalendarAccount(
        id: json['id']?.toString() ?? '',
        provider: json['provider']?.toString() ?? '',
        label: json['label']?.toString() ?? '',
        connected: json['connected'] == true,
        tenantId: (json['tenant_id'] ?? json['tenantId'])?.toString(),
      );
}

class AuthResult {
  final bool success;
  final String message;
  final String? token;

  const AuthResult({
    required this.success,
    required this.message,
    this.token,
  });
}

class AuthSetupStatus {
  final bool needsSetup;
  final bool inviteRegistrationEnabled;
  final bool registrationRequiresToken;
  final bool registrationDeliveryConfigured;
  final String adminEmailHint;

  const AuthSetupStatus({
    required this.needsSetup,
    this.inviteRegistrationEnabled = true,
    this.registrationRequiresToken = false,
    this.registrationDeliveryConfigured = false,
    this.adminEmailHint = '',
  });

  factory AuthSetupStatus.fromJson(Map<String, dynamic> json) =>
      AuthSetupStatus(
        needsSetup: json['needs_setup'] == true,
        inviteRegistrationEnabled: json['invite_registration_enabled'] != false,
        registrationRequiresToken: json['registration_requires_token'] == true,
        registrationDeliveryConfigured:
            json['registration_delivery_configured'] == true,
        adminEmailHint: json['admin_email_hint']?.toString() ?? '',
      );
}

class CurrentAccount {
  final String id;
  final String username;
  final String email;
  final String role;
  final String tutorId;

  const CurrentAccount({
    required this.id,
    required this.username,
    required this.email,
    required this.role,
    required this.tutorId,
  });

  bool get isAdmin => role == 'admin';

  factory CurrentAccount.fromJson(Map<String, dynamic> json) => CurrentAccount(
        id: json['id']?.toString() ?? '',
        username: json['username']?.toString() ?? '',
        email: json['email']?.toString() ?? '',
        role: json['role']?.toString() ?? 'user',
        tutorId: json['tutor_id']?.toString() ?? '',
      );
}

class AdminUser {
  final String id;
  final String username;
  final String email;
  final String role;
  final bool isActive;

  const AdminUser({
    required this.id,
    required this.username,
    required this.email,
    required this.role,
    required this.isActive,
  });

  factory AdminUser.fromJson(Map<String, dynamic> json) => AdminUser(
        id: json['id']?.toString() ?? '',
        username: json['username']?.toString() ?? '',
        email: json['email']?.toString() ?? '',
        role: json['role']?.toString() ?? 'user',
        isActive: json['is_active'] == true,
      );
}

class DesktopWindowInfo {
  final String id;
  final String title;
  final int processId;
  final String processName;
  final String executablePath;
  final String className;
  final bool isActive;

  const DesktopWindowInfo({
    required this.id,
    required this.title,
    required this.processId,
    required this.processName,
    required this.executablePath,
    required this.className,
    required this.isActive,
  });

  String get displayTitle => title.trim().isEmpty ? '(sem titulo)' : title;
  String get displayProcess =>
      processName.trim().isEmpty ? 'processo desconhecido' : processName;

  factory DesktopWindowInfo.fromJson(Map<String, dynamic> json) =>
      DesktopWindowInfo(
        id: json['id']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        processId: _intValue(json['process_id'] ?? json['processId']),
        processName: json['process_name']?.toString() ??
            json['processName']?.toString() ??
            '',
        executablePath: json['executable_path']?.toString() ??
            json['executablePath']?.toString() ??
            '',
        className: json['class_name']?.toString() ??
            json['className']?.toString() ??
            '',
        isActive: json['is_active'] == true || json['isActive'] == true,
      );
}

class DesktopWindowContext {
  final DesktopWindowInfo window;
  final String text;
  final String extractionMethod;
  final String? warning;
  final bool truncated;
  final String contextPrompt;

  const DesktopWindowContext({
    required this.window,
    required this.text,
    required this.extractionMethod,
    this.warning,
    required this.truncated,
    required this.contextPrompt,
  });

  String get label => '${window.displayTitle} - ${window.displayProcess}';

  factory DesktopWindowContext.fromJson(Map<String, dynamic> json) {
    final rawWindow = json['window'];
    final windowJson = rawWindow is Map
        ? rawWindow.map((key, value) => MapEntry(key.toString(), value))
        : <String, dynamic>{};

    return DesktopWindowContext(
      window: DesktopWindowInfo.fromJson(windowJson),
      text: json['text']?.toString() ?? '',
      extractionMethod: json['extraction_method']?.toString() ??
          json['extractionMethod']?.toString() ??
          'metadata',
      warning: json['warning']?.toString(),
      truncated: json['truncated'] == true,
      contextPrompt: json['context_prompt']?.toString() ??
          json['contextPrompt']?.toString() ??
          '',
    );
  }
}

int _intValue(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

class ActionAuditEntry {
  final String id;
  final String tutorId;
  final String? automationId;
  final String actionType;
  final String status;
  final Map<String, dynamic> request;
  final Map<String, dynamic> result;
  final DateTime createdAt;

  const ActionAuditEntry({
    required this.id,
    required this.tutorId,
    this.automationId,
    required this.actionType,
    required this.status,
    this.request = const {},
    this.result = const {},
    required this.createdAt,
  });

  factory ActionAuditEntry.fromJson(Map<String, dynamic> json) =>
      ActionAuditEntry(
        id: json['id']?.toString() ?? '',
        tutorId: (json['tutor_id'] ?? json['tutorId'])?.toString() ?? '',
        automationId:
            (json['automation_id'] ?? json['automationId'])?.toString(),
        actionType:
            (json['action_type'] ?? json['actionType'])?.toString() ?? '',
        status: json['status']?.toString() ?? '',
        request: _dynamicMap(json['request']),
        result: _dynamicMap(json['result']),
        createdAt: _dateValue(json['created_at'] ?? json['createdAt']) ??
            DateTime.fromMillisecondsSinceEpoch(0),
      );
}

Map<String, dynamic> _dynamicMap(Object? value) {
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  return {};
}

DateTime? _dateValue(Object? value) {
  final text = value?.toString();
  if (text == null || text.isEmpty) return null;
  return DateTime.tryParse(text)?.toLocal();
}

class ComputerActionResult {
  final String actionId;
  final String actionName;
  final String status;
  final String summary;
  final List<ComputerCommandOutput> outputs;
  final int durationMs;

  const ComputerActionResult({
    required this.actionId,
    required this.actionName,
    required this.status,
    required this.summary,
    required this.outputs,
    required this.durationMs,
  });

  String toPromptText() {
    final buffer = StringBuffer()
      ..writeln('Acao: $actionName ($actionId)')
      ..writeln('Status: $status')
      ..writeln('Resumo: $summary')
      ..writeln('Duracao: ${durationMs}ms');
    for (final output in outputs) {
      buffer
        ..writeln()
        ..writeln('--- ${output.label} ---')
        ..writeln('Comando: ${output.command}')
        ..writeln('Exit code: ${output.exitCode}');
      if (output.stdout.trim().isNotEmpty) {
        buffer
          ..writeln('STDOUT:')
          ..writeln(output.stdout.trim());
      }
      if (output.stderr.trim().isNotEmpty) {
        buffer
          ..writeln('STDERR:')
          ..writeln(output.stderr.trim());
      }
    }
    return buffer.toString().trim();
  }

  String toLocalSummaryText() {
    final title = actionName.trim().isEmpty ? 'Acao local' : actionName.trim();
    final buffer = StringBuffer()
      ..writeln('Resultado local coletado: $title')
      ..writeln(summary.trim().isEmpty
          ? 'Resumo: coleta finalizada.'
          : 'Resumo: ${summary.trim()}');
    if (outputs.isNotEmpty) {
      buffer.writeln();
      buffer.writeln('Etapas:');
      for (final output in outputs) {
        final ok = output.exitCode == 0 ? 'ok' : 'erro ${output.exitCode}';
        buffer.writeln('- ${output.label}: $ok (${output.durationMs}ms)');
      }
    }
    buffer
      ..writeln()
      ..write('Vou enviar os dados completos para a IA analisar.');
    return buffer.toString();
  }

  factory ComputerActionResult.fromJson(Map<String, dynamic> json) {
    final rawAction = json['action'];
    final action = rawAction is Map
        ? rawAction.map((key, value) => MapEntry(key.toString(), value))
        : <String, dynamic>{};
    final rawOutputs = json['outputs'] as List<dynamic>? ?? const [];

    return ComputerActionResult(
      actionId: action['id']?.toString() ?? '',
      actionName: action['name']?.toString() ?? '',
      status: json['status']?.toString() ?? '',
      summary: json['summary']?.toString() ?? '',
      outputs: rawOutputs
          .map((item) =>
              ComputerCommandOutput.fromJson(item as Map<String, dynamic>))
          .toList(),
      durationMs: _intValue(json['duration_ms'] ?? json['durationMs']),
    );
  }
}

class ComputerCommandOutput {
  final String label;
  final String command;
  final int exitCode;
  final String stdout;
  final String stderr;
  final int durationMs;

  const ComputerCommandOutput({
    required this.label,
    required this.command,
    required this.exitCode,
    required this.stdout,
    required this.stderr,
    required this.durationMs,
  });

  factory ComputerCommandOutput.fromJson(Map<String, dynamic> json) =>
      ComputerCommandOutput(
        label: json['label']?.toString() ?? '',
        command: json['command']?.toString() ?? '',
        exitCode: _intValue(json['exit_code'] ?? json['exitCode']),
        stdout: json['stdout']?.toString() ?? '',
        stderr: json['stderr']?.toString() ?? '',
        durationMs: _intValue(json['duration_ms'] ?? json['durationMs']),
      );
}

class ScriptShellsInfo {
  final String defaultShell;
  final List<String> availableShells;

  const ScriptShellsInfo({
    required this.defaultShell,
    required this.availableShells,
  });

  factory ScriptShellsInfo.fromJson(Map<String, dynamic> json) =>
      ScriptShellsInfo(
        defaultShell:
            (json['default_shell'] ?? json['defaultShell'])?.toString() ?? '',
        availableShells: (json['available_shells'] as List<dynamic>? ??
                json['availableShells'] as List<dynamic>? ??
                const [])
            .map((item) => item.toString())
            .where((item) => item.trim().isNotEmpty)
            .toList(),
      );
}

class SavedScriptEntry {
  final String id;
  final String tutorId;
  final String name;
  final String shell;
  final String script;
  final String workingDirectory;
  final int timeoutSeconds;
  final bool allowHighRisk;
  final String description;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  const SavedScriptEntry({
    required this.id,
    required this.tutorId,
    required this.name,
    required this.shell,
    required this.script,
    required this.workingDirectory,
    required this.timeoutSeconds,
    required this.allowHighRisk,
    required this.description,
    this.createdAt,
    this.updatedAt,
  });

  String get displayShell => shell.trim().isEmpty ? 'shell' : shell;

  factory SavedScriptEntry.fromJson(Map<String, dynamic> json) =>
      SavedScriptEntry(
        id: json['id']?.toString() ?? '',
        tutorId: (json['tutor_id'] ?? json['tutorId'])?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        shell: json['shell']?.toString() ?? '',
        script: json['script']?.toString() ?? '',
        workingDirectory:
            (json['working_directory'] ?? json['workingDirectory'])
                    ?.toString() ??
                '',
        timeoutSeconds:
            _intValue(json['timeout_seconds'] ?? json['timeoutSeconds']),
        allowHighRisk:
            json['allow_high_risk'] == true || json['allowHighRisk'] == true,
        description: json['description']?.toString() ?? '',
        createdAt: _dateValue(json['created_at'] ?? json['createdAt']),
        updatedAt: _dateValue(json['updated_at'] ?? json['updatedAt']),
      );
}

class ScriptRunResult {
  final String shell;
  final String command;
  final String workingDirectory;
  final int exitCode;
  final String stdout;
  final String stderr;
  final int durationMs;
  final bool timedOut;
  final bool highRiskDetected;

  const ScriptRunResult({
    required this.shell,
    required this.command,
    required this.workingDirectory,
    required this.exitCode,
    required this.stdout,
    required this.stderr,
    required this.durationMs,
    required this.timedOut,
    required this.highRiskDetected,
  });

  bool get ok => exitCode == 0 && !timedOut;

  String get combinedOutput {
    final parts = [
      if (stdout.trim().isNotEmpty) stdout.trim(),
      if (stderr.trim().isNotEmpty) 'STDERR:\n${stderr.trim()}',
    ];
    return parts.isEmpty ? '(sem saida)' : parts.join('\n\n');
  }

  factory ScriptRunResult.fromJson(Map<String, dynamic> json) =>
      ScriptRunResult(
        shell: json['shell']?.toString() ?? '',
        command: json['command']?.toString() ?? '',
        workingDirectory:
            (json['working_directory'] ?? json['workingDirectory'])
                    ?.toString() ??
                '',
        exitCode: _intValue(json['exit_code'] ?? json['exitCode']),
        stdout: json['stdout']?.toString() ?? '',
        stderr: json['stderr']?.toString() ?? '',
        durationMs: _intValue(json['duration_ms'] ?? json['durationMs']),
        timedOut: json['timed_out'] == true || json['timedOut'] == true,
        highRiskDetected: json['high_risk_detected'] == true ||
            json['highRiskDetected'] == true,
      );
}

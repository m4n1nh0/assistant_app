import 'dart:convert';

import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('configure normaliza URL sem esquema e remove barra final', () {
    final svc = ApiService();
    svc.configure('localhost:8000/');
    expect(svc.baseUrl, 'http://localhost:8000');
    expect(svc.wsUrl, 'ws://localhost:8000');
  });

  test('configure preserva https e deriva wss', () {
    final svc = ApiService();
    svc.configure('https://assistantapp-production-cabc.up.railway.app');
    expect(svc.baseUrl, 'https://assistantapp-production-cabc.up.railway.app');
    expect(svc.wsUrl, 'wss://assistantapp-production-cabc.up.railway.app');
  });

  test('configure com valor vazio cai no padrão', () {
    final svc = ApiService();
    svc.configure('   ');
    expect(svc.baseUrl, AppConfig.defaultBackendUrl);
  });

  test('construtor usa o backend padrao carregado em runtime', () {
    final previous = AppConfig.defaultBackendUrl;
    addTearDown(() => AppConfig.setDefaultBackendUrl(previous));

    AppConfig.setDefaultBackendUrl('https://api.intarq.app');

    final svc = ApiService();
    expect(svc.baseUrl, 'https://api.intarq.app');
    expect(svc.wsUrl, 'wss://api.intarq.app');
  });

  test('agentes externos sao salvos por usuario e locais nao sao enviados',
      () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    svc.setToken('user-token');
    final client = MockClient((request) async {
      expect(request.method, 'PUT');
      expect(request.url.path, '/llm/config');
      expect(request.headers['authorization'], 'Bearer user-token');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final providers = body['providers'] as List<dynamic>;
      expect(providers, hasLength(1));
      expect(providers.first['id'], 'gpt');
      expect(providers.first['api_key'], 'user-openai-key');
      expect(providers.any((item) => item['id'] == 'llama'), isFalse);
      return http.Response(
        '{"providers":[{"id":"gpt","label":"OpenAI","kind":"external",'
        '"enabled":true,"configured":true,"model":"gpt-4o"}],'
        '"active_llms":["gpt","llama"],"llm_labels":{},"llm_status":{}}',
        200,
      );
    });

    final response = await http.runWithClient(
      () => svc.saveLlmConfig(const [
        LlmProviderConfig(
          id: 'gpt',
          label: 'OpenAI',
          kind: 'external',
          enabled: true,
          configured: false,
          model: 'gpt-4o',
          apiKey: 'user-openai-key',
        ),
        LlmProviderConfig(
          id: 'llama',
          label: 'Ollama',
          kind: 'local',
          enabled: true,
          configured: true,
          model: 'llama3',
        ),
      ]),
      () => client,
    );

    expect(response.providers.single.configured, isTrue);
    expect(response.providers.single.apiKey, isEmpty);
  });

  test('recuperação solicita token sem enviar senha', () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/auth/password-recovery/request');
      expect(jsonDecode(request.body), {'identifier': 'mariano@example.com'});
      expect(request.body, isNot(contains('password')));
      return http.Response(
        '{"success":true,"message":"Se houver uma conta, enviaremos."}',
        200,
      );
    });

    final message = await http.runWithClient(
      () => svc.requestPasswordRecovery('mariano@example.com'),
      () => client,
    );

    expect(message, contains('Se houver uma conta'));
  });

  test('recuperação confirma token e nova senha', () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/auth/password-recovery/confirm');
      expect(jsonDecode(request.body), {
        'token': 'one-time-token',
        'new_password': 'secret1',
      });
      return http.Response(
        '{"success":true,"message":"Senha redefinida com sucesso."}',
        200,
      );
    });

    final message = await http.runWithClient(
      () => svc.confirmPasswordRecovery(
        token: 'one-time-token',
        newPassword: 'secret1',
      ),
      () => client,
    );

    expect(message, 'Senha redefinida com sucesso.');
  });

  test('chat transforma erro HTTP sem JSON em mensagem legivel', () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.url.path, '/chat/');
      return http.Response('Internal Server Error', 500);
    });

    final request = http.runWithClient(
      () => svc.chat(message: 'Ola'),
      () => client,
    );

    await expectLater(
      request,
      throwsA(
        isA<Exception>().having(
          (error) => error.toString(),
          'mensagem',
          contains('Falha ao conversar com o assistente (HTTP 500)'),
        ),
      ),
    );
  });

  test('chat preserva detalhe JSON retornado pelo backend', () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient(
      (_) async => http.Response(
        '{"detail":"Agente temporariamente indisponivel"}',
        503,
        headers: {'content-type': 'application/json'},
      ),
    );

    final request = http.runWithClient(
      () => svc.chat(message: 'Ola'),
      () => client,
    );

    await expectLater(
      request,
      throwsA(
        isA<Exception>().having(
          (error) => error.toString(),
          'mensagem',
          contains('Agente temporariamente indisponivel'),
        ),
      ),
    );
  });

  test('pronuncia da assistente e salva no perfil isolado do usuario',
      () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.method, 'PUT');
      expect(request.url.path, '/tutor/');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['assistant_name'], 'Hannah');
      expect(body['config']['assistant_pronunciation'], 'Raná');
      expect(body['config']['existing_setting'], isTrue);
      return http.Response(request.body, 200);
    });

    await http.runWithClient(
      () => svc.saveAssistantProfile(
        const CurrentAccount(
          id: 'user-1',
          username: 'mariano',
          email: 'mariano@example.com',
          role: 'admin',
          tutorId: 'tutor-1',
        ),
        AppConfig(
          assistantName: 'Hannah',
          assistantPronunciation: 'Raná',
        ),
        currentProfile: {
          'display_name': 'Mariano',
          'config': {'existing_setting': true},
        },
      ),
      () => client,
    );
  });

  test('agenda de turmas envia uma unica requisicao confirmada em lote',
      () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/calendar/class-agenda');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['provider'], 'google');
      expect(body['class_ids'], ['c1', 'c2']);
      expect(body['date_from'], '2026-08-16');
      expect(body['date_to'], '2026-12-31');
      expect(body['confirmed'], isTrue);
      return http.Response(
        '{"class_count":2,"created_series":3,'
        '"skipped_series":0,"failed_series":0,"errors":[]}',
        201,
      );
    });

    final result = await http.runWithClient(
      () => svc.createClassAgenda(
        provider: 'google',
        accountId: 'google-1',
        classIds: const ['c1', 'c2'],
        dateFrom: DateTime(2026, 8, 16),
        dateTo: DateTime(2026, 12, 31),
      ),
      () => client,
    );

    expect(result['created_series'], 3);
  });

  test('reconexao Microsoft envia somente o identificador publico da conta',
      () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.method, 'GET');
      expect(request.url.path, '/calendar/microsoft/start');
      expect(request.url.queryParameters, {'account_id': 'microsoft-1'});
      expect(request.body, isEmpty);
      return http.Response(
        '{"auth_url":"https://login.microsoftonline.com/common/oauth2/v2.0/authorize",'
        '"account_id":"microsoft-1"}',
        200,
      );
    });

    final result = await http.runWithClient(
      () => svc.startMicrosoftCalendarAuth(accountId: 'microsoft-1'),
      () => client,
    );

    expect(result.accountId, 'microsoft-1');
    expect(result.authUrl, startsWith('https://login.microsoftonline.com/'));
  });

  test('conta Microsoft mostra email e necessidade de reconexao', () {
    final account = CalendarAccount.fromJson({
      'id': 'microsoft-1',
      'provider': 'microsoft',
      'label': 'Professora Ana',
      'email': 'ana@example.edu',
      'connected': false,
      'status': 'reconnect_required',
    });

    expect(account.email, 'ana@example.edu');
    expect(account.statusLabel, 'RECONECTAR');
  });

  test('notification config sends the editable reminder minutes', () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.method, 'PUT');
      expect(request.url.path, '/notifications/config');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['reminder_minutes'], 30);
      return http.Response(
        '{"notify_15min":true,"reminder_minutes":30}',
        200,
      );
    });

    final saved = await http.runWithClient(
      () => svc.saveNotificationConfig(NotifConfig(reminderMinutes: 30)),
      () => client,
    );

    expect(saved.reminderMinutes, 30);
  });

  test('teste do Telegram passa pelo backend e preserva o diagnostico',
      () async {
    final svc = ApiService(backendUrl: 'https://backend.test');
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/notifications/test/telegram');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['telegram_token'], 'bot-token');
      expect(body['telegram_chat_id'], 'chat-1');
      return http.Response(
        '{"ok":false,"message":"Chat ID nao encontrado. Envie /start."}',
        200,
      );
    });

    final result = await http.runWithClient(
      () => svc.testTelegram(
        NotifConfig(
          tgToken: 'bot-token',
          tgChatId: 'chat-1',
          tgEnabled: true,
        ),
      ),
      () => client,
    );

    expect(result.ok, isFalse);
    expect(result.message, contains('/start'));
  });
}

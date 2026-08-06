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
}

import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';

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
}

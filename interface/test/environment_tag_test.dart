import 'package:assistant_app/widgets/environment_tag.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> _show(
  WidgetTester tester, {
  required ServerInfoFetcher fetch,
  String baseUrl = 'https://assistantapp-production-cabc.up.railway.app',
}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Center(
        child: EnvironmentTag(
            key: UniqueKey(), baseUrl: baseUrl, fetch: fetch, refreshEvery: Duration.zero),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('o host sai do endereço completo', () {
    expect(hostOf('https://app.up.railway.app/'), 'app.up.railway.app');
    expect(hostOf('http://localhost:8000'), 'localhost');
    expect(hostOf('sem esquema'), 'sem esquema');
  });

  testWidgets('produção aparece discreta, com o host do servidor', (tester) async {
    await _show(tester, fetch: (_) async => const ServerInfo(
        environment: 'production', revision: 'a1b2c3d', uptimeSeconds: 7200));

    expect(find.text('PRODUÇÃO'), findsOneWidget);
    expect(find.text('assistantapp-production-cabc.up.railway.app'), findsOneWidget);
  });

  testWidgets('local chama atenção e mostra que não é produção', (tester) async {
    await _show(tester,
        baseUrl: 'http://localhost:8000',
        fetch: (_) async => const ServerInfo(environment: 'local'));

    expect(find.text('LOCAL'), findsOneWidget);
    expect(find.text('localhost'), findsOneWidget);
    expect(find.text('PRODUÇÃO'), findsNothing);
  });

  testWidgets('homologação e ambientes desconhecidos também são avisados', (tester) async {
    await _show(tester, fetch: (_) async => const ServerInfo(environment: 'staging'));
    expect(find.text('HOMOLOGAÇÃO'), findsOneWidget);

    await _show(tester, fetch: (_) async => const ServerInfo(environment: 'demo'));
    expect(find.text('DEMO'), findsOneWidget);

    // Servidor antigo que ainda não informa o ambiente.
    await _show(tester, fetch: (_) async => const ServerInfo());
    expect(find.text('AMBIENTE ?'), findsOneWidget);
  });

  testWidgets('servidor que não responde mostra sem conexão, não um ambiente falso',
      (tester) async {
    await _show(tester, fetch: (_) async => throw Exception('timeout'));

    expect(find.text('SEM CONEXÃO'), findsOneWidget);
    expect(find.text('PRODUÇÃO'), findsNothing);
  });
}

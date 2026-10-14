import 'dart:convert';

import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/student_portal_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:qr_flutter/qr_flutter.dart';

class _Backend {
  bool active = true;
  final requests = <http.Request>[];

  http.Response handle(http.Request request) {
    requests.add(request);
    if (request.url.path.endsWith('/education/portal-link')) {
      if (request.method == 'PATCH') {
        active = (jsonDecode(request.body) as Map)['active'] == true;
      }
      return http.Response(
          jsonEncode({'path': '/education/portal/tokabc', 'active': active}), 200);
    }
    return http.Response('{"detail":"inesperado"}', 404);
  }
}

Future<void> _open(WidgetTester tester, _Backend backend,
    {required Future<void> Function() body}) async {
  tester.view.physicalSize = const Size(1200, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(
            onPressed: () => showStudentPortalDialog(
              context,
              service: education,
              baseUrl: 'https://app.exemplo.com/',
            ),
            child: const Text('abrir'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('abrir'));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

void main() {
  testWidgets('mostra o link completo do portal, o QR Code e o aviso da matrícula',
      (tester) async {
    await _open(tester, _Backend(), body: () async {
      expect(find.text('https://app.exemplo.com/education/portal/tokabc'), findsOneWidget);
      expect(find.byType(QrImageView), findsOneWidget);
      expect(find.textContaining('o acesso é só pela matrícula'), findsOneWidget);
    });
  });

  testWidgets('copia o link', (tester) async {
    final copied = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          copied.add((call.arguments as Map)['text'] as String);
        }
        return null;
      },
    );
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    await _open(tester, _Backend(), body: () async {
      await tester.tap(find.byTooltip('Copiar link'));
      await tester.pumpAndSettle();

      expect(copied.single, 'https://app.exemplo.com/education/portal/tokabc');
      expect(find.text('Link copiado.'), findsOneWidget);
    });
  });

  testWidgets('fechar o portal grava na hora e avisa', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('portal-active')));
      await tester.pumpAndSettle();

      expect(backend.active, isFalse);
      expect(find.textContaining('Portal fechado'), findsOneWidget);

      await tester.tap(find.byKey(const Key('portal-active')));
      await tester.pumpAndSettle();
      expect(backend.active, isTrue);
      expect(find.textContaining('Portal aberto'), findsWidgets);
    });
  });
}

import 'package:assistant_app/services/in_app_notification_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  tearDown(InAppNotificationService.dismiss);

  testWidgets('shows summary completion above the current route',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      navigatorKey: appNavigatorKey,
      home: const Scaffold(body: Text('conteudo')),
    ));

    InAppNotificationService.showSummaryReady(
      discipline: 'Banco de Dados',
      title: 'Normalizacao',
      llm: 'localai',
      usedSegments: 9,
    );
    await tester.pump();

    expect(find.text('RESUMO PRONTO'), findsOneWidget);
    expect(find.text('Banco de Dados — Normalizacao'), findsOneWidget);
    expect(find.text('localai • 9 trecho(s)'), findsOneWidget);

    await tester.tap(find.byTooltip('Fechar aviso'));
    await tester.pump();

    expect(find.text('RESUMO PRONTO'), findsNothing);
  });
}

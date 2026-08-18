import 'package:assistant_app/widgets/auth_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('tela de acesso oferece recuperação de conta', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AuthDialog(
            assistantName: 'Assistant',
            needsSetup: false,
          ),
        ),
      ),
    );

    expect(find.text('RECUPERAR CONTA'), findsOneWidget);
    await tester.tap(find.byKey(const Key('recover-account-button')));
    await tester.pump();

    expect(find.text('ENVIAR TOKEN'), findsOneWidget);
    expect(find.text('VOLTAR AO ACESSO'), findsOneWidget);
    expect(find.byKey(const Key('auth-identifier')), findsOneWidget);
  });
}

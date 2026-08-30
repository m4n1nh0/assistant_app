/// Privacidade da tela de acesso.
///
/// A tela principal so monta os paineis depois da autenticacao. Antes disso o
/// app renderizava a conversa inteira atras do dialogo de acesso - o dialogo
/// sobe um quadro depois da tela, entao a conversa do usuario anterior ficava
/// visivel, inclusive em screenshot.
///
/// Estes testes fixam as duas metades da solucao: o fundo que substitui o
/// conteudo, e o desfoque da barreira do dialogo.
library;

import 'package:assistant_app/widgets/blurred_barrier.dart';
import 'package:assistant_app/widgets/locked_backdrop.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('LockedBackdrop', () {
    testWidgets('nao exibe texto algum', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: LockedBackdrop())),
      );

      // Sem texto nao ha nome de usuario, conversa ou agenda para vazar. E a
      // verificacao mais direta de que o fundo nao carrega dado do app.
      expect(find.byType(Text), findsNothing);
    });

    testWidgets('mostra a marca discreta ao fundo', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: LockedBackdrop())),
      );

      expect(find.byType(Image), findsOneWidget);

      final opacity = tester.widget<Opacity>(find.byType(Opacity));
      expect(
        opacity.opacity,
        lessThan(0.3),
        reason: 'a marca e plano de fundo; quem chama atencao e o dialogo.',
      );
    });

    testWidgets('marca ausente nao vira tela de erro', (tester) async {
      // O `errorBuilder` existe porque falta de asset nao pode transformar a
      // tela de acesso num quadro vermelho de excecao.
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: LockedBackdrop())),
      );
      await tester.pump();

      expect(tester.takeException(), isNull);
    });
  });

  group('BlurredBarrier', () {
    testWidgets('aplica desfoque em toda a area, nao so atras do filho',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: BlurredBarrier(child: SizedBox(width: 40, height: 40)),
          ),
        ),
      );

      expect(find.byType(BackdropFilter), findsOneWidget);

      final filterSize = tester.getSize(find.byType(BackdropFilter));
      final screenSize = tester.getSize(find.byType(Scaffold));
      expect(
        filterSize,
        screenSize,
        reason: 'limitado ao filho, o resto da janela continuaria nitido.',
      );
    });

    testWidgets('mantem o filho nitido por cima', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: BlurredBarrier(child: Center(child: Text('ACESSO'))),
          ),
        ),
      );

      expect(find.text('ACESSO'), findsOneWidget);

      // O filho tem que vir depois do filtro na ordem de pintura; invertido, o
      // proprio dialogo sairia borrado.
      final stack = tester.widget<Stack>(find.byType(Stack).first);
      expect(stack.children.length, 2);
      expect(
          find.descendant(
              of: find.byType(Stack), matching: find.text('ACESSO')),
          findsOneWidget);
    });

    testWidgets('nao quebra a centralizacao de um Dialog', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: BlurredBarrier(
            child: Dialog(child: SizedBox(width: 200, height: 120)),
          ),
        ),
      );

      final dialog = tester.getRect(find.byType(SizedBox).last);
      final screen = tester.getRect(find.byType(MaterialApp));

      expect(dialog.center.dx, closeTo(screen.center.dx, 1));
      expect(dialog.center.dy, closeTo(screen.center.dy, 1));
    });
  });
}

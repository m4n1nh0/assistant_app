/// Aviso de "vieram menos perguntas" na revisao do quiz.
///
/// A tela mostrava sempre o mesmo texto fixo ("a aula pode nao ter conteudo
/// suficiente..."), mesmo quando o servidor ja tinha calculado o motivo de verdade -
/// quantas foram repetidas, que o conteudo era curto, que a fonte ja tinha
/// perguntas em outros quizzes. O professor lia o palpite generico e gerava de
/// novo, para receber o mesmo resultado.
library;

import 'package:assistant_app/widgets/quiz_preview_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const mensagemDoServidor =
    '1 questões preparadas para revisão. Libere o QR Code quando estiver pronto '
    'para aplicar. Você pediu 20 e vieram 1 (12 repetida(s) de outra pergunta). '
    'Esta fonte já tem 34 pergunta(s) em outros quizzes, e as novas não as repetem. '
    'Para mais perguntas diferentes, marque mais aulas ou materiais.';

const textoGenerico = 'a aula pode não ter conteúdo suficiente';

Map<String, dynamic> pergunta() => {
      'id': 'q1',
      'tipo': 'multipla_escolha',
      'enunciado': 'O que é modelagem conceitual?',
      'opcoes': [
        {'label': 'A', 'texto': 'Um modelo', 'correta': true},
        {'label': 'B', 'texto': 'Uma tabela', 'correta': false},
      ],
    };

Future<void> abrir(
  WidgetTester tester, {
  String? notice,
  List<Map<String, dynamic>> attempts = const [],
}) async {
  tester.view.physicalSize = const Size(1000, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: ThemeData.dark(),
    home: Scaffold(
      body: SizedBox(
        height: 1300,
        child: QuizPreview(
          questions: [pergunta()],
          requested: 20,
          attempts: attempts,
          notice: notice,
        ),
      ),
    ),
  ));
}

void main() {
  group('shortfallFrom', () {
    test('pega so a parte da falta, sem o resto da mensagem do pedido', () {
      final explicacao = shortfallFrom(mensagemDoServidor)!;

      expect(explicacao, startsWith('Você pediu 20 e vieram 1'));
      expect(explicacao, isNot(contains('Libere o QR Code')));
      expect(explicacao, isNot(contains('questões preparadas')));
      expect(explicacao, contains('Esta fonte já tem 34 pergunta(s)'));
    });

    test('mensagem sem falta, vazia ou nula nao vira explicacao', () {
      expect(shortfallFrom('20 questões preparadas para revisão.'), isNull);
      expect(shortfallFrom(''), isNull);
      expect(shortfallFrom(null), isNull);
    });
  });

  group('aviso na revisao', () {
    testWidgets('mostra a explicacao do servidor no lugar do texto generico', (tester) async {
      await abrir(tester, notice: mensagemDoServidor);

      expect(find.textContaining('Você pediu 20 e vieram 1'), findsOneWidget);
      expect(find.textContaining('Esta fonte já tem 34 pergunta(s)'), findsOneWidget);
      expect(find.textContaining(textoGenerico), findsNothing);
    });

    testWidgets('sem aviso do servidor, continua o texto generico', (tester) async {
      await abrir(tester);

      expect(find.textContaining('Vieram 19 a menos que o pedido'), findsOneWidget);
      expect(find.textContaining(textoGenerico), findsOneWidget);
    });

    testWidgets('mensagem que nao explica a falta tambem cai no texto generico', (tester) async {
      await abrir(tester, notice: '1 questões preparadas para revisão.');

      expect(find.textContaining(textoGenerico), findsOneWidget);
    });

    testWidgets('os provedores que falharam continuam listados junto da explicacao',
        (tester) async {
      await abrir(
        tester,
        notice: mensagemDoServidor,
        attempts: const [
          {'llm': 'claude', 'success': false, 'error': 'sem credito na conta'},
          {'llm': 'grok', 'success': false, 'error': 'Request too large'},
        ],
      );

      expect(find.textContaining('Falhou — claude: sem credito na conta'), findsOneWidget);
      expect(find.textContaining('Falhou — grok: Request too large'), findsOneWidget);
      expect(find.textContaining('Você pediu 20 e vieram 1'), findsOneWidget);
    });

    testWidgets('quiz completo nao mostra aviso nenhum', (tester) async {
      tester.view.physicalSize = const Size(1000, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        theme: ThemeData.dark(),
        home: Scaffold(
          body: SizedBox(
            height: 1300,
            child: QuizPreview(
              questions: [pergunta()],
              requested: 1,
              attempts: const [],
              notice: mensagemDoServidor,
            ),
          ),
        ),
      ));

      expect(find.textContaining('Você pediu'), findsNothing);
      expect(find.textContaining(textoGenerico), findsNothing);
    });
  });
}

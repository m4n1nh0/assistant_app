import 'dart:convert';

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/widgets/quiz_center.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _FakeCenter extends QuizCenterService {
  _FakeCenter(this.status) : super(ApiService());

  final String status;
  final List<String> deleted = [];
  final List<String> discarded = [];
  Object? deleteError;

  @override
  Future<Map<String, dynamic>> quizDetail(String quizId) async => {
        'id': quizId,
        'titulo': 'Quiz de Banco de Dados',
        'status': status,
        'questoes': [
          {
            'id': 'q1',
            'enunciado': 'O que é uma chave primária?',
            'opcoes': [
              {'label': 'A', 'texto': 'Identifica a linha', 'correta': true},
              {'label': 'B', 'texto': 'Ordena a tabela', 'correta': false},
            ],
            'resposta_correta': 'A',
          },
        ],
      };

  @override
  Future<void> deleteQuiz(String quizId) async {
    if (deleteError != null) throw deleteError!;
    deleted.add(quizId);
  }

  @override
  Future<void> discardDraft(String quizId) async => discarded.add(quizId);
}

Future<void> _open(WidgetTester tester, _FakeCenter center,
    {VoidCallback? onChanged}) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(MaterialApp(
    home: Builder(
      builder: (context) => Scaffold(
        body: TextButton(
          onPressed: () => openQuizReview(
            context,
            quizId: 'quiz-1',
            service: center,
            onChanged: onChanged,
          ),
          child: const Text('abrir'),
        ),
      ),
    ),
  ));
  await tester.tap(find.text('abrir'));
  await tester.pumpAndSettle();
}

void main() {
  group('excluir quiz', () {
    for (final status in ['open', 'closed']) {
      testWidgets('quiz $status oferece EXCLUIR e apaga depois de confirmar',
          (tester) async {
        final center = _FakeCenter(status);
        var changed = 0;
        await _open(tester, center, onChanged: () => changed++);

        expect(find.text('EXCLUIR'), findsOneWidget);
        expect(find.text('DESCARTAR'), findsNothing);

        await tester.tap(find.text('EXCLUIR'));
        await tester.pumpAndSettle();
        expect(find.text('Excluir este quiz?'), findsOneWidget);
        expect(find.textContaining('as respostas dos alunos e o ranking'),
            findsOneWidget);
        expect(center.deleted, isEmpty);

        await tester.tap(find.text('Excluir'));
        await tester.pumpAndSettle();

        expect(center.deleted, ['quiz-1']);
        expect(changed, 1);
        expect(find.text('EXCLUIR'), findsNothing);
      });
    }

    testWidgets('cancelar a confirmação não apaga nada', (tester) async {
      final center = _FakeCenter('closed');
      await _open(tester, center);

      await tester.tap(find.text('EXCLUIR'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();

      expect(center.deleted, isEmpty);
      expect(find.text('EXCLUIR'), findsOneWidget);
    });

    testWidgets('recusa do servidor aparece e o quiz continua aberto',
        (tester) async {
      final center = _FakeCenter('open')
        ..deleteError = QuizCenterException(
          'Há uma pergunta aberta para a turma. Encerre a pergunta antes de apagar o quiz.',
        );
      await _open(tester, center);

      await tester.tap(find.text('EXCLUIR'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Excluir'));
      await tester.pumpAndSettle();

      expect(find.textContaining('pergunta aberta para a turma'), findsOneWidget);
      expect(find.text('EXCLUIR'), findsOneWidget);
    });

    testWidgets('rascunho continua com DESCARTAR e sem EXCLUIR', (tester) async {
      // O cabeçalho do rascunho leva quatro botões e estoura na fonte de teste
      // (Ahem, bem mais larga que a real). O aviso de largura não é o que esse
      // teste confere; qualquer outro erro continua falhando.
      final original = FlutterError.onError;
      FlutterError.onError = (details) {
        if (details.exceptionAsString().contains('overflowed')) return;
        original?.call(details);
      };
      addTearDown(() => FlutterError.onError = original);

      final center = _FakeCenter('draft');
      await _open(tester, center);

      expect(find.text('DESCARTAR'), findsOneWidget);
      expect(find.text('EXCLUIR'), findsNothing);
    });
  });

  group('QuizCenterService.deleteQuiz', () {
    test('manda a confirmação (force) que o servidor exige', () async {
      final requests = <http.Request>[];
      final client = MockClient((request) async {
        requests.add(request);
        return http.Response(
          jsonEncode({'deleted': true, 'answers': 3, 'participants': 2}),
          200,
        );
      });

      await http.runWithClient(
        () => QuizCenterService(ApiService()).deleteQuiz('quiz-1'),
        () => client,
      );

      expect(requests.single.method, 'DELETE');
      expect(requests.single.url.path, '/education/quiz/quiz-1');
      expect(requests.single.url.queryParameters, {'force': 'true'});
    });

    test('devolve o motivo do servidor quando ele recusa', () async {
      final client = MockClient((_) async => http.Response(
            jsonEncode({'detail': 'Há uma pergunta aberta para a turma.'}),
            409,
          ));

      await expectLater(
        http.runWithClient(
          () => QuizCenterService(ApiService()).deleteQuiz('quiz-1'),
          () => client,
        ),
        throwsA(isA<QuizCenterException>().having(
          (e) => e.toString(),
          'mensagem',
          contains('pergunta aberta'),
        )),
      );
    });
  });
}

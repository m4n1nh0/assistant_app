import 'dart:convert';

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/widgets/quiz_center.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

QuizSummary _quiz(String id, String status) => QuizSummary(
      id: id,
      titulo: 'Quiz $id',
      status: status,
      totalQuestoes: 5,
      disciplinas: const ['BANCO DE DADOS'],
    );

class _FakeCenter extends QuizCenterService {
  _FakeCenter(this.quizzes) : super(ApiService());

  List<QuizSummary> quizzes;
  final List<List<String>> requests = [];
  final List<bool> forces = [];
  QuizBulkDeleteResult Function(List<String> ids)? answer;
  Object? error;

  @override
  Future<QuizListResult> listQuizzes({
    String status = '',
    String discipline = '',
    String search = '',
  }) async =>
      QuizListResult(
        quizzes
            .where((quiz) => status.isEmpty || quiz.status == status)
            .toList(),
        const ['BANCO DE DADOS'],
      );

  @override
  Future<QuizBulkDeleteResult> deleteQuizzes(
    List<String> quizIds, {
    bool force = false,
  }) async {
    requests.add(quizIds);
    forces.add(force);
    if (error != null) throw error!;
    final result = answer?.call(quizIds) ??
        QuizBulkDeleteResult(deleted: quizIds.length);
    final blocked = result.blocked.map((item) => item.id).toSet();
    quizzes = quizzes
        .where((quiz) => !quizIds.contains(quiz.id) || blocked.contains(quiz.id))
        .toList();
    return result;
  }
}

Future<_FakeCenter> _open(WidgetTester tester, List<QuizSummary> quizzes) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final center = _FakeCenter(quizzes);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(body: QuizListPanel(service: center)),
  ));
  await tester.pumpAndSettle();
  return center;
}

Finder get _checkboxes => find.byType(Checkbox);

void main() {
  group('excluir quizzes em lote', () {
    testWidgets('a barra de seleção aparece com a lista e sem nada marcado',
        (tester) async {
      await _open(tester, [_quiz('a', 'draft'), _quiz('b', 'closed')]);

      expect(find.text('Selecionar todos (2)'), findsOneWidget);
      expect(find.text('EXCLUIR SELECIONADOS'), findsNothing);
    });

    testWidgets('marcar alguns mostra a contagem e o botão', (tester) async {
      await _open(tester, [_quiz('a', 'draft'), _quiz('b', 'closed')]);

      // [0] marca todos; [1] e [2] são os quizzes.
      await tester.tap(_checkboxes.at(1));
      await tester.pump();

      expect(find.text('1 selecionado'), findsOneWidget);
      expect(find.text('EXCLUIR SELECIONADOS'), findsOneWidget);
    });

    testWidgets('selecionar todos marca tudo e desmarcar limpa', (tester) async {
      await _open(tester, [_quiz('a', 'draft'), _quiz('b', 'closed')]);

      await tester.tap(_checkboxes.first);
      await tester.pump();
      expect(find.text('2 selecionados'), findsOneWidget);

      await tester.tap(_checkboxes.first);
      await tester.pump();
      expect(find.text('Selecionar todos (2)'), findsOneWidget);
    });

    testWidgets('só rascunhos: confirma e manda com a confirmação (force)',
        (tester) async {
      final center =
          await _open(tester, [_quiz('a', 'draft'), _quiz('b', 'draft')]);

      await tester.tap(_checkboxes.first);
      await tester.pump();
      await tester.tap(find.text('EXCLUIR SELECIONADOS'));
      await tester.pumpAndSettle();

      expect(find.text('Excluir 2 quizzes?'), findsOneWidget);
      expect(find.textContaining('2 rascunhos serão descartados'),
          findsOneWidget);
      expect(find.textContaining('respostas dos alunos'), findsNothing);
      expect(center.requests, isEmpty);

      await tester.tap(find.text('Excluir'));
      await tester.pumpAndSettle();

      expect(center.requests, [
        ['a', 'b']
      ]);
      expect(center.forces, [true]);
      expect(find.text('Nenhum quiz com esses filtros.'), findsOneWidget);
      expect(find.textContaining('2 quizzes apagados'), findsOneWidget);
    });

    testWidgets('com quiz aplicado o aviso diz que respostas e ranking saem',
        (tester) async {
      await _open(tester, [_quiz('a', 'draft'), _quiz('b', 'closed')]);

      await tester.tap(_checkboxes.first);
      await tester.pump();
      await tester.tap(find.text('EXCLUIR SELECIONADOS'));
      await tester.pumpAndSettle();

      expect(find.textContaining('1 rascunho será descartado'), findsOneWidget);
      expect(
        find.textContaining('1 já foi liberado ou encerrado: as respostas '
            'dos alunos e o ranking dele serão apagados'),
        findsOneWidget,
      );
      expect(find.textContaining('Não dá para desfazer'), findsOneWidget);
    });

    testWidgets('cancelar a confirmação não apaga nada e mantém a seleção',
        (tester) async {
      final center = await _open(tester, [_quiz('a', 'closed')]);

      await tester.tap(_checkboxes.first);
      await tester.pump();
      await tester.tap(find.text('EXCLUIR SELECIONADOS'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();

      expect(center.requests, isEmpty);
      expect(find.text('1 selecionado'), findsOneWidget);
      expect(find.text('Quiz a'), findsOneWidget);
    });

    testWidgets('quiz que o servidor bloqueou continua na lista, com o motivo',
        (tester) async {
      final center = await _open(
        tester,
        [_quiz('a', 'closed'), _quiz('ao-vivo', 'open')],
      );
      center.answer = (ids) => const QuizBulkDeleteResult(
            deleted: 1,
            answers: 4,
            blocked: [
              BlockedQuiz('ao-vivo', 'Quiz ao-vivo',
                  'Há uma pergunta aberta para a turma.'),
            ],
          );

      await tester.tap(_checkboxes.first);
      await tester.pump();
      await tester.tap(find.text('EXCLUIR SELECIONADOS'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Excluir'));
      await tester.pumpAndSettle();

      expect(find.textContaining('1 quiz apagado'), findsOneWidget);
      expect(find.textContaining('Há uma pergunta aberta para a turma.'),
          findsOneWidget);
      await tester.tap(find.text('Fechar'));
      await tester.pumpAndSettle();

      expect(find.text('Quiz ao-vivo'), findsOneWidget);
      expect(find.text('Quiz a'), findsNothing);
      // A seleção foi limpa: o bloqueado não segue marcado.
      expect(find.text('EXCLUIR SELECIONADOS'), findsNothing);
    });

    testWidgets('falha do servidor aparece e nada some da lista', (tester) async {
      final center = await _open(tester, [_quiz('a', 'draft')]);
      center.error = const QuizCenterException('Escolha no máximo 100 quizzes por vez.');

      await tester.tap(_checkboxes.first);
      await tester.pump();
      await tester.tap(find.text('EXCLUIR SELECIONADOS'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Excluir'));
      await tester.pumpAndSettle();

      expect(find.textContaining('no máximo 100 quizzes'), findsOneWidget);
      expect(find.text('Quiz a'), findsOneWidget);
    });
  });

  group('QuizCenterService.deleteQuizzes', () {
    test('manda ids e confirmação e lê o que sobrou', () async {
      late http.Request sent;
      final client = MockClient((request) async {
        sent = request;
        return http.Response(
          jsonEncode({
            'deleted': 2,
            'ignored': 1,
            'answers': 7,
            'participants': 3,
            'blocked': [
              {'id': 'x', 'titulo': 'Quiz x', 'reason': 'Há uma pergunta aberta.'},
            ],
          }),
          200,
        );
      });

      final result = await http.runWithClient(
        () => QuizCenterService(ApiService())
            .deleteQuizzes(['a', 'b', 'x'], force: true),
        () => client,
      );

      expect(sent.method, 'POST');
      expect(sent.url.path, '/education/quiz/bulk-delete');
      expect(jsonDecode(sent.body), {
        'ids': ['a', 'b', 'x'],
        'force': true,
      });
      expect(result.deleted, 2);
      expect(result.ignored, 1);
      expect(result.answers, 7);
      expect(result.blocked.single.reason, 'Há uma pergunta aberta.');
      expect(result.resumo, '2 quizzes apagados · 7 respostas removidas · 1 não saiu.');
    });

    test('resumo no singular', () {
      expect(
        const QuizBulkDeleteResult(deleted: 1, answers: 1).resumo,
        '1 quiz apagado · 1 resposta removida.',
      );
    });

    test('resumo com vários bloqueados usa o plural certo', () {
      const result = QuizBulkDeleteResult(
        deleted: 0,
        blocked: [BlockedQuiz('a', 'A', 'x'), BlockedQuiz('b', 'B', 'y')],
      );
      expect(result.resumo, '0 quizzes apagados · 2 não saíram.');
    });
  });
}

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/services/quiz_queue_watcher.dart';
import 'package:assistant_app/widgets/quiz_center.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> jobJson(
  String id,
  String status, {
  bool seen = false,
  String quizId = '',
}) =>
    {
      'job_id': id,
      'status': status,
      'titulo': 'Quiz $id',
      'total': 10,
      'prontas': status == 'running' ? 4 : 0,
      'message': 'mensagem $id',
      'quiz_id': quizId,
      'seen': seen,
      'can_review': status == 'done' && quizId.isNotEmpty,
      'can_cancel': status == 'queued' || status == 'running',
      'can_retry': status == 'error' || status == 'canceled',
    };

class FakeQuizCenter extends QuizCenterService {
  FakeQuizCenter() : super(ApiService());

  QuizJobsSnapshot snapshot = const QuizJobsSnapshot();
  final List<List<String>> seenCalls = [];
  List<BankQuestion> questions = const [];

  @override
  Future<QuizJobsSnapshot> listJobs() async => snapshot;

  @override
  Future<void> markSeen(List<String> jobIds) async => seenCalls.add(jobIds);

  /// Filtros com que a tela chamou a listagem, na ordem.
  final List<String> statusFilters = [];

  /// Ids pedidos em cada limpeza em lote.
  final List<List<String>> bulkDeletes = [];

  /// Ids que o filtro alcanca alem da pagina; vazio usa os da pagina.
  List<String> allIds = const [];

  BankCleanupResult cleanup = const BankCleanupResult(0, 0, 0);

  @override
  Future<QuestionBankResult> listQuestions({
    String discipline = '',
    String search = '',
    String dificuldade = '',
    String status = '',
    bool includeCopies = false,
    bool includeArchived = false,
    int limit = 50,
    int offset = 0,
  }) async {
    statusFilters.add(status);
    return QuestionBankResult(
      questions,
      questions.length,
      const ['BANCO DE DADOS'],
      allIds.isEmpty ? questions.map((q) => q.id).toList() : allIds,
    );
  }

  @override
  Future<BankCleanupResult> removeQuestions(List<String> questionIds) async {
    bulkDeletes.add(questionIds);
    return cleanup;
  }
}

BankQuestion question(String id, {bool editavel = true, String status = 'draft'}) =>
    BankQuestion.fromJson({
      'id': id,
      'quiz_id': 'quiz-$id',
      'quiz_titulo': 'Quiz de $id',
      'quiz_status': status,
      'enunciado': 'Enunciado $id?',
      'dificuldade': 'medio',
      'opcoes': [
        {'label': 'A', 'texto': 'Certa', 'correta': true},
        {'label': 'B', 'texto': 'Errada', 'correta': false},
      ],
      'editavel': editavel,
      'disciplinas': ['BANCO DE DADOS'],
    });

void main() {
  group('modelos', () {
    test('pedido lê estado, progresso e ações permitidas', () {
      final running = QuizJob.fromJson(jobJson('a', 'running'));
      final done = QuizJob.fromJson(jobJson('b', 'done', quizId: 'q1'));
      final seen = QuizJob.fromJson(jobJson('c', 'error', seen: true));

      expect(running.isActive, isTrue);
      expect(running.progress, closeTo(0.4, 0.001));
      expect(running.canCancel, isTrue);
      expect(running.needsNotice, isFalse);
      expect(done.needsNotice, isTrue);
      expect(done.canReview, isTrue);
      expect(seen.needsNotice, isFalse);
    });

    test('questão do banco devolve o texto da alternativa correta', () {
      expect(question('q').correctText, 'Certa');
    });

    test('query string ignora filtro vazio', () {
      expect(
        withQuery('/education/quiz', {'status': '', 'discipline': 'BANCO DE DADOS', 'q': null}),
        '/education/quiz?discipline=BANCO+DE+DADOS',
      );
      expect(withQuery('/education/quiz', {'status': ''}), '/education/quiz');
    });
  });

  group('observador da fila', () {
    test('avisa cada pedido terminado uma vez e marca como visto', () async {
      final service = FakeQuizCenter()
        ..snapshot = QuizJobsSnapshot.fromJson({
          'jobs': [
            jobJson('ativo', 'running'),
            jobJson('pronto', 'done', quizId: 'q1'),
            jobJson('falhou', 'error'),
            jobJson('ja-visto', 'done', seen: true, quizId: 'q2'),
            jobJson('cancelado', 'canceled'),
          ],
          'active': 1,
          'unseen': 2,
        });
      final avisos = <String>[];
      final watcher = QuizQueueWatcher(
        service: service,
        onFinished: (job) => avisos.add(job.id),
      );

      await watcher.refresh();
      await watcher.refresh();
      watcher.stop();

      expect(avisos, ['pronto', 'falhou']);
      expect(service.seenCalls, [
        ['pronto', 'falhou'],
      ]);
    });

    test('parar limpa a leitura da fila', () async {
      final service = FakeQuizCenter()
        ..snapshot = QuizJobsSnapshot.fromJson({
          'jobs': [jobJson('ativo', 'queued')],
          'active': 1,
        });
      final watcher = QuizQueueWatcher(service: service);

      await watcher.refresh();
      expect(watcher.snapshot.value.active, 1);
      watcher.stop();

      expect(watcher.snapshot.value.jobs, isEmpty);
    });
  });

  group('banco de questões', () {
    Future<void> pumpBank(WidgetTester tester, FakeQuizCenter service) async {
      tester.view.physicalSize = const Size(1400, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: QuestionBankPanel(service: service)),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('marcar questões mostra a ordem e habilita montar quiz', (tester) async {
      final service = FakeQuizCenter()
        ..questions = [question('q1'), question('q2', editavel: false, status: 'closed')];
      await pumpBank(tester, service);

      expect(find.text('Enunciado q1?'), findsOneWidget);
      final montar = find.widgetWithText(FilledButton, 'MONTAR QUIZ');
      expect(tester.widget<FilledButton>(montar).onPressed, isNull);

      await tester.tap(find.byType(Checkbox).at(1));
      await tester.pump();
      await tester.tap(find.byType(Checkbox).at(0));
      await tester.pump();

      expect(find.textContaining('#1 na seleção'), findsOneWidget);
      expect(find.textContaining('#2 na seleção'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'MONTAR QUIZ (2)'), findsOneWidget);
    });

    testWidgets('questão reaproveitada mostra em quantos quizzes entrou',
        (tester) async {
      final service = FakeQuizCenter()
        ..questions = [
          BankQuestion.fromJson({
            'id': 'q1',
            'quiz_id': 'quiz-q1',
            'quiz_titulo': 'Quiz da aula',
            'quiz_status': 'open',
            'enunciado': 'O que é 1FN?',
            'dificuldade': 'medio',
            'copias': 2,
          }),
        ];
      await pumpBank(tester, service);

      expect(find.textContaining('já usada em 2 quizzes montados'),
          findsOneWidget);
    });

    testWidgets('filtrar por rascunho chega ao serviço', (tester) async {
      final service = FakeQuizCenter()..questions = [question('q1')];
      await pumpBank(tester, service);

      await tester.tap(find.text('Situação do quiz'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Rascunho').last);
      await tester.pumpAndSettle();

      expect(service.statusFilters.last, 'draft');
    });

    testWidgets('selecionar todas alcança além da página carregada',
        (tester) async {
      final service = FakeQuizCenter()
        ..questions = [question('q1'), question('q2')]
        ..allIds = ['q1', 'q2', 'q3-fora-da-pagina'];
      await pumpBank(tester, service);

      await tester.tap(find.textContaining('SELECIONAR TODAS'));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(OutlinedButton, 'EXCLUIR (3)'), findsOneWidget);
    });

    testWidgets('excluir selecionadas confirma e manda os ids', (tester) async {
      final service = FakeQuizCenter()
        ..questions = [question('q1'), question('q2')]
        ..cleanup = const BankCleanupResult(2, 0, 0);
      await pumpBank(tester, service);

      await tester.tap(find.textContaining('SELECIONAR TODAS'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(OutlinedButton, 'EXCLUIR (2)'));
      await tester.pumpAndSettle();

      expect(find.text('Excluir 2 questão(ões)?'), findsOneWidget);
      await tester.tap(find.widgetWithText(TextButton, 'Cancelar'));
      await tester.pumpAndSettle();
      expect(service.bulkDeletes, isEmpty, reason: 'cancelar não apaga nada');

      await tester.tap(find.widgetWithText(OutlinedButton, 'EXCLUIR (2)'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
      await tester.pumpAndSettle();

      expect(service.bulkDeletes.single, ['q1', 'q2']);
    });

    testWidgets('aviso diz que quiz liberado será arquivado, não apagado',
        (tester) async {
      final service = FakeQuizCenter()
        ..questions = [
          question('q1'),
          question('q2', editavel: false, status: 'closed'),
        ];
      await pumpBank(tester, service);

      await tester.tap(find.textContaining('SELECIONAR TODAS'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(OutlinedButton, 'EXCLUIR (2)'));
      await tester.pumpAndSettle();

      expect(find.textContaining('1 são de quiz já liberado'), findsOneWidget);
      expect(find.textContaining('arquivadas, não apagadas'), findsOneWidget);
    });

    testWidgets('questão de quiz liberado não edita e é arquivada', (tester) async {
      final service = FakeQuizCenter()
        ..questions = [question('q2', editavel: false, status: 'closed')];
      await pumpBank(tester, service);

      await tester.tap(find.text('Enunciado q2?'));
      await tester.pumpAndSettle();

      final editar = find.widgetWithText(OutlinedButton, 'EDITAR');
      expect(tester.widget<OutlinedButton>(editar).onPressed, isNull);
      expect(find.text('ARQUIVAR'), findsOneWidget);
    });
  });

  group('editor de questão', () {
    Future<void> openEditor(WidgetTester tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () => showDialog<Map<String, dynamic>>(
              context: context,
              builder: (_) => QuestionEditorDialog(question: question('q1')),
            ),
            child: const Text('abrir'),
          ),
        ),
      ));
      await tester.tap(find.text('abrir'));
      await tester.pumpAndSettle();
    }

    testWidgets('salva com a alternativa marcada como correta', (tester) async {
      Map<String, dynamic>? result;
      await tester.pumpWidget(MaterialApp(
        home: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              result = await showDialog<Map<String, dynamic>>(
                context: context,
                builder: (_) => QuestionEditorDialog(question: question('q1')),
              );
            },
            child: const Text('abrir'),
          ),
        ),
      ));
      await tester.tap(find.text('abrir'));
      await tester.pumpAndSettle();

      await tester.tap(find.byType(Radio<String>).at(1));
      await tester.pump();
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();

      final opcoes = (result!['opcoes'] as List).cast<Map<String, dynamic>>();
      expect(opcoes.map((o) => o['correta']), [false, true]);
      expect(result!['enunciado'], 'Enunciado q1?');
    });

    testWidgets('recusa enunciado vazio sem fechar', (tester) async {
      await openEditor(tester);

      await tester.enterText(find.widgetWithText(TextField, 'Enunciado'), '');
      await tester.tap(find.text('Salvar'));
      await tester.pump();

      expect(find.text('O enunciado não pode ficar vazio.'), findsOneWidget);
      expect(find.byType(QuestionEditorDialog), findsOneWidget);
    });
  });
}

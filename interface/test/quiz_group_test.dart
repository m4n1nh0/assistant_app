import 'package:assistant_app/models/quiz_group.dart';
import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/widgets/quiz_group_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _member(String id, String name,
        {bool eligible = true, bool joined = false}) =>
    {
      'id': id,
      'name': name,
      'eligible': eligible,
      'joined': joined,
      'score': 0,
      'answers': 0,
    };

Map<String, dynamic> _info({
  String mode = 'representante',
  Map<String, dynamic>? repG1,
  List<Map<String, dynamic>> ranking = const [],
}) =>
    {
      'enabled': true,
      'mode': mode,
      'discipline_id': 'd1',
      'discipline': 'ARA0040 - BANCO DE DADOS',
      'semester': '2026.2',
      'seed': 'abc123',
      'algorithm': 'sha256-v1',
      'groups': [
        {
          'id': 'g1',
          'name': 'Grupo 1',
          'representative': repG1,
          'members': [
            _member('m-ana', 'Ana Souza', joined: true),
            _member('m-bia', 'Bia Lima'),
            _member('m-caio', 'Caio Reis', eligible: false),
          ],
        },
        {
          'id': 'g2',
          'name': 'Grupo 2',
          'representative': null,
          'members': [_member('m-davi', 'Davi Alves', eligible: false)],
        },
      ],
      'ranking': ranking,
      'without_representative': <String>[],
    };

const _discipline = Discipline(
  id: 'd1',
  code: 'ARA0040',
  name: 'BANCO DE DADOS',
  label: 'ARA0040 - BANCO DE DADOS',
  semester: '2026.2',
);

class _FakeCenter extends QuizCenterService {
  _FakeCenter(this.current) : super(ApiService());

  QuizGroupInfo current;
  final List<String> calls = [];
  Object? error;

  Future<QuizGroupInfo> _answer(String call, QuizGroupInfo next) async {
    calls.add(call);
    if (error != null) throw error!;
    current = next;
    return next;
  }

  @override
  Future<QuizGroupInfo> groupInfo(String quizId) async => current;

  @override
  Future<QuizGroupInfo> setGroup(String quizId,
          {required String mode,
          required String disciplineId,
          String semester = ''}) =>
      _answer('set:$mode:$disciplineId:$semester',
          QuizGroupInfo.fromJson(_info(mode: mode)));

  @override
  Future<void> unsetGroup(String quizId) async {
    calls.add('unset');
    if (error != null) throw error!;
    current = const QuizGroupInfo();
  }

  @override
  Future<QuizGroupInfo> drawRepresentatives(String quizId,
          {bool redraw = false}) =>
      _answer(
        'draw:$redraw',
        QuizGroupInfo.fromJson(_info(repG1: {
          'member_id': 'm-ana',
          'name': 'Ana Souza',
          'round': 0,
          'origin': 'sorteio',
        })),
      );

  @override
  Future<QuizGroupInfo> redrawRepresentative(String quizId, String groupId) =>
      _answer(
        'redraw:$groupId',
        QuizGroupInfo.fromJson(_info(repG1: {
          'member_id': 'm-bia',
          'name': 'Bia Lima',
          'round': 1,
          'origin': 'sorteio',
        })),
      );

  @override
  Future<QuizGroupInfo> setRepresentative(
          String quizId, String groupId, String memberId) =>
      _answer(
        'set-rep:$groupId:$memberId',
        QuizGroupInfo.fromJson(_info(repG1: {
          'member_id': memberId,
          'name': 'Bia Lima',
          'round': 0,
          'origin': 'manual',
        })),
      );
}

Future<void> _open(WidgetTester tester, _FakeCenter center) async {
  tester.view.physicalSize = const Size(1400, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: QuizGroupPanel(
        quizId: 'quiz-1',
        service: center,
        loadDisciplines: () async => const [_discipline],
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('QuizGroupInfo', () {
    test('quiz individual vem como desligado', () {
      expect(QuizGroupInfo.fromJson({'enabled': false}).enabled, isFalse);
    });

    test('lê grupos, integrantes e representante', () {
      final info = QuizGroupInfo.fromJson(_info(repG1: {
        'member_id': 'm-ana',
        'name': 'Ana Souza',
        'round': 0,
        'origin': 'manual',
      }));

      expect(info.byRepresentative, isTrue);
      expect(info.groups.first.representative?.manual, isTrue);
      expect(info.groups.first.joinedCount, 1);
      expect(info.groups.first.eligibleMembers.map((m) => m.name),
          ['Ana Souza', 'Bia Lima']);
    });

    test('grupo sem ninguém com matrícula fica bloqueado', () {
      final info = QuizGroupInfo.fromJson(_info());
      expect(info.groups[0].blocked, isFalse);
      expect(info.groups[1].blocked, isTrue);
    });

    test('só o modo representante cobra representante', () {
      expect(QuizGroupInfo.fromJson(_info()).withoutRepresentative.length, 2);
      expect(
        QuizGroupInfo.fromJson(_info(mode: 'media')).withoutRepresentative,
        isEmpty,
      );
    });
  });

  group('groupRankingDetail', () {
    test('média mostra quantos integrantes entraram', () {
      expect(
        groupRankingDetail(
          {'mode': 'media', 'members': 2, 'members_total': 3},
          showRound: false,
        ),
        '2 de 3 integrantes',
      );
    });

    test('representante mostra quem responde e a rodada', () {
      expect(
        groupRankingDetail(
          {
            'mode': 'representante',
            'representative': 'Bia Lima',
            'round_score': 700,
          },
          showRound: true,
        ),
        'Representante: Bia Lima · +700 nesta pergunta',
      );
    });

    test('grupo sem representante avisa', () {
      expect(
        groupRankingDetail({'mode': 'representante'}, showRound: false),
        'sem representante',
      );
    });
  });

  group('QuizGroupPanel', () {
    testWidgets('ativa o quiz em grupo com o modo e a disciplina escolhidos',
        (tester) async {
      final center = _FakeCenter(const QuizGroupInfo());
      await _open(tester, center);

      expect(find.text('ATIVAR QUIZ EM GRUPO'), findsOneWidget);
      await tester.tap(find.text('Só o representante'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('ATIVAR QUIZ EM GRUPO'));
      await tester.pumpAndSettle();

      expect(center.calls, ['set:representante:d1:2026.2']);
      expect(find.textContaining('A turma entra com a matrícula'),
          findsOneWidget);
      expect(find.text('Grupo 1'), findsOneWidget);
      expect(find.text('VOLTAR A INDIVIDUAL'), findsOneWidget);
    });

    testWidgets('mostra quem consegue entrar e avisa o grupo sem matrícula',
        (tester) async {
      await _open(tester, _FakeCenter(QuizGroupInfo.fromJson(_info())));

      expect(find.text('1 de 3 entraram'), findsOneWidget);
      expect(find.textContaining('Nenhum integrante tem matrícula vinculada'),
          findsOneWidget);
      expect(find.textContaining('Sem representante: Grupo 1, Grupo 2'),
          findsOneWidget);
    });

    testWidgets('sorteia representantes e depois sorteia outro', (tester) async {
      final center = _FakeCenter(QuizGroupInfo.fromJson(_info()));
      await _open(tester, center);

      await tester.tap(find.text('SORTEAR REPRESENTANTES'));
      await tester.pumpAndSettle();
      expect(center.calls, ['draw:false']);
      expect(find.textContaining('Representante: Ana Souza (sorteado)'),
          findsOneWidget);

      await tester.tap(find.text('SORTEAR OUTRO'));
      await tester.pumpAndSettle();
      expect(center.calls.last, 'redraw:g1');
      expect(find.textContaining('Representante: Bia Lima (sorteio 2)'),
          findsOneWidget);
    });

    testWidgets('refazer todos manda redraw', (tester) async {
      final center = _FakeCenter(QuizGroupInfo.fromJson(_info()));
      await _open(tester, center);

      await tester.tap(find.text('REFAZER TODOS'));
      await tester.pumpAndSettle();
      expect(center.calls, ['draw:true']);
    });

    testWidgets('o professor escolhe o representante pela lista de elegíveis',
        (tester) async {
      final center = _FakeCenter(QuizGroupInfo.fromJson(_info()));
      await _open(tester, center);

      await tester.tap(find.byTooltip('Escolher o representante').first);
      await tester.pumpAndSettle();
      // O menu lista só quem tem matrícula: Bia aparece no chip e no menu; o Caio
      // (sem matrícula) fica só no chip.
      expect(find.text('Bia Lima'), findsNWidgets(2));
      expect(find.text('Caio Reis'), findsOneWidget);
      await tester.tap(find.text('Bia Lima').last);
      await tester.pumpAndSettle();

      expect(center.calls, ['set-rep:g1:m-bia']);
      expect(find.textContaining('(escolhido por você)'), findsOneWidget);
    });

    testWidgets('mostra a recusa do servidor', (tester) async {
      final center = _FakeCenter(const QuizGroupInfo())
        ..error = const QuizCenterException(
          'A turma já respondeu: não dá para mudar o modo ou a disciplina do grupo.',
        );
      await _open(tester, center);

      await tester.tap(find.text('ATIVAR QUIZ EM GRUPO'));
      await tester.pumpAndSettle();

      expect(find.textContaining('A turma já respondeu'), findsOneWidget);
    });

    testWidgets('voltar a individual limpa o painel', (tester) async {
      final center = _FakeCenter(QuizGroupInfo.fromJson(_info(mode: 'media')));
      await _open(tester, center);

      await tester.tap(find.text('VOLTAR A INDIVIDUAL'));
      await tester.pumpAndSettle();

      expect(center.calls, ['unset']);
      expect(find.text('ATIVAR QUIZ EM GRUPO'), findsOneWidget);
      expect(find.textContaining('O quiz voltou a ser individual'),
          findsOneWidget);
    });

    testWidgets('mostra o ranking por grupo', (tester) async {
      final info = QuizGroupInfo.fromJson(_info(mode: 'media', ranking: [
        {
          'position': 1,
          'student_id': 'g1',
          'student_name': 'Grupo 1',
          'score': 1100,
          'mode': 'media',
          'members': 2,
          'members_total': 3,
        },
      ]));
      await _open(tester, _FakeCenter(info));

      expect(find.text('Ranking por grupo'), findsOneWidget);
      expect(find.text('1100 pts'), findsOneWidget);
      expect(find.text('2 de 3 integrantes'), findsOneWidget);
    });
  });
}

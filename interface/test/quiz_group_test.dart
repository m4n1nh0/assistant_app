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
  String absence = 'none',
  int percent = 0,
  List<String> absentG1 = const [],
  int penaltyG1 = 0,
}) =>
    {
      'enabled': true,
      'mode': mode,
      'absence_mode': absence,
      'absence_percent': percent,
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
          'absent': absentG1,
          'penalty_percent': penaltyG1,
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
  /// Turma enviada em cada ativacao, na ordem.
  final List<String?> classIds = [];
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
          String semester = '',
          String? classId,
          String absenceMode = 'none',
          int absencePercent = 0}) {
    classIds.add(classId);
    return _answer(
          'set:$mode:$disciplineId:$semester:$absenceMode:$absencePercent',
          QuizGroupInfo.fromJson(_info(
              mode: mode, absence: absenceMode, percent: absencePercent)));
  }

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

Future<void> _open(WidgetTester tester, _FakeCenter center,
    {List<ClassGroup> classes = const []}) async {
  tester.view.physicalSize = const Size(1400, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: QuizGroupPanel(
        quizId: 'quiz-1',
        service: center,
        loadDisciplines: () async => const [_discipline],
        loadClasses: () async => classes,
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

  group('penalidade por ausente', () {
    test('lê o modo, o percentual e os ausentes de cada grupo', () {
      final info = QuizGroupInfo.fromJson(_info(
        mode: 'media',
        absence: 'percent',
        percent: 10,
        absentG1: ['Bia Lima'],
        penaltyG1: 10,
      ));

      expect(info.absenceMode, AbsencePenalty.percent);
      expect(info.absencePercent, 10);
      expect(info.penalizes, isTrue);
      expect(info.groups.first.absent, ['Bia Lima']);
      expect(info.groups.first.penaltyPercent, 10);
    });

    test('sem penalidade o padrão é desligado', () {
      final info = QuizGroupInfo.fromJson({'enabled': true, 'groups': []});
      expect(info.absenceMode, AbsencePenalty.none);
      expect(info.penalizes, isFalse);
    });

    test('só se fala em ausente depois que alguém entrou', () {
      expect(QuizGroupInfo.fromJson(_info()).anyoneJoined, isTrue); // Ana entrou
      expect(
        QuizGroupInfo.fromJson({'enabled': true, 'groups': []}).anyoneJoined,
        isFalse,
      );
    });

    test('o texto do ranking descreve a regra de cada modo', () {
      expect(
        groupRankingDetail({
          'mode': 'media',
          'members': 1,
          'members_total': 2,
          'absent': 1,
          'absence_mode': 'percent',
          'penalty_percent': 10,
        }, showRound: false),
        '1 de 2 integrantes · 1 ausente (−10%)',
      );
      expect(
        groupRankingDetail({
          'mode': 'media',
          'members': 1,
          'members_total': 3,
          'absent': 2,
          'absence_mode': 'zero',
        }, showRound: false),
        '1 de 3 integrantes · 2 ausentes (contam zero)',
      );
    });

    test('sem penalidade ou sem ausente o texto não muda', () {
      const base = {'mode': 'media', 'members': 2, 'members_total': 2};
      expect(
        groupRankingDetail({...base, 'absent': 1, 'absence_mode': 'none'},
            showRound: false),
        '2 de 2 integrantes',
      );
      expect(
        groupRankingDetail({...base, 'absent': 0, 'absence_mode': 'percent'},
            showRound: false),
        '2 de 2 integrantes',
      );
    });

    test('o texto de apoio explica cada regra', () {
      expect(AbsencePenalty.explanation('percent', 15), contains('15%'));
      expect(AbsencePenalty.explanation('zero', 0), contains('conta zero'));
      expect(AbsencePenalty.explanation('none', 0), contains('não muda'));
    });
  });

  group('turma do quiz em grupo', () {
    ClassGroup turma(String id, String code, String name, int weekday) =>
        ClassGroup(
          id: id,
          code: code,
          name: name,
          discipline: 'BANCO DE DADOS',
          label: '$code $name',
          disciplineId: 'd1',
          schedules: [ClassSchedule(weekday: weekday)],
        );

    final turmas = [
      turma('c-qui', '3002', 'Quinta', 3),
      turma('c-seg', '3001', 'Segunda', 0),
    ];

    testWidgets('sem turmas cadastradas o seletor não aparece', (tester) async {
      await _open(tester, _FakeCenter(const QuizGroupInfo()));
      expect(find.text('Turma (dia de aula)'), findsNothing);
    });

    testWidgets('escolher a turma e ativar manda o id dela', (tester) async {
      final center = _FakeCenter(const QuizGroupInfo());
      await _open(tester, center, classes: turmas);

      expect(find.text('Entram os alunos de todos os grupos da disciplina.'),
          findsOneWidget);
      await tester.tap(find.text('Todas as turmas da disciplina'));
      await tester.pumpAndSettle();
      // Ordenadas pelo primeiro dia de aula: segunda antes de quinta.
      expect(
        tester.getTopLeft(find.text('3001 Segunda · segunda').last).dy <
            tester.getTopLeft(find.text('3002 Quinta · quinta').last).dy,
        isTrue,
      );
      await tester.tap(find.text('3002 Quinta · quinta').last);
      await tester.pumpAndSettle();
      expect(find.textContaining('Só entram os alunos dos grupos desta turma'),
          findsOneWidget);

      await tester.tap(find.text('ATIVAR QUIZ EM GRUPO'));
      await tester.pumpAndSettle();

      expect(center.classIds, ['c-qui']);
    });

    testWidgets('por padrão vale a disciplina toda (sem turma)', (tester) async {
      final center = _FakeCenter(const QuizGroupInfo());
      await _open(tester, center, classes: turmas);

      await tester.tap(find.text('ATIVAR QUIZ EM GRUPO'));
      await tester.pumpAndSettle();

      expect(center.classIds, [null]);
    });

    testWidgets('quiz já ligado numa turma abre com ela marcada', (tester) async {
      final info = QuizGroupInfo.fromJson({
        ..._info(mode: 'media'),
        'class_id': 'c-seg',
        'class_label': '3001 Segunda · segunda',
      });
      expect(info.classId, 'c-seg');
      expect(info.classLabel, '3001 Segunda · segunda');

      await _open(tester, _FakeCenter(info), classes: turmas);

      expect(find.text('3001 Segunda · segunda'), findsWidgets);
      expect(find.textContaining('2 grupos · ARA0040 - BANCO DE DADOS · 3001 Segunda'),
          findsOneWidget);
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

      expect(center.calls, ['set:representante:d1:2026.2:none:0']);
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

    testWidgets('manda a penalidade por desconto com o percentual digitado',
        (tester) async {
      final center = _FakeCenter(const QuizGroupInfo());
      await _open(tester, center);

      await tester.tap(find.text('Desconto por ausente'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, '10'), '15');
      await tester.tap(find.text('ATIVAR QUIZ EM GRUPO'));
      await tester.pumpAndSettle();

      expect(center.calls, ['set:media:d1:2026.2:percent:15']);
    });

    testWidgets('ausente conta zero vai para a média', (tester) async {
      final center = _FakeCenter(const QuizGroupInfo());
      await _open(tester, center);

      await tester.tap(find.text('Ausente conta zero'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('ATIVAR QUIZ EM GRUPO'));
      await tester.pumpAndSettle();

      expect(center.calls, ['set:media:d1:2026.2:zero:0']);
    });

    testWidgets('trocar para representante desliga o "conta zero"',
        (tester) async {
      final center = _FakeCenter(const QuizGroupInfo());
      await _open(tester, center);

      await tester.tap(find.text('Ausente conta zero'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Só o representante'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('ATIVAR QUIZ EM GRUPO'));
      await tester.pumpAndSettle();

      expect(center.calls, ['set:representante:d1:2026.2:none:0']);
    });

    testWidgets('mostra quem faltou e o desconto no grupo', (tester) async {
      await _open(
        tester,
        _FakeCenter(QuizGroupInfo.fromJson(_info(
          mode: 'media',
          absence: 'percent',
          percent: 10,
          absentG1: ['Bia Lima'],
          penaltyG1: 10,
        ))),
      );

      expect(find.textContaining('Ausentes: Bia Lima · desconto de 10% na nota'),
          findsOneWidget);
    });

    testWidgets('sem penalidade ligada a lista de ausentes não aparece',
        (tester) async {
      await _open(
        tester,
        _FakeCenter(QuizGroupInfo.fromJson(_info(
          mode: 'media',
          absentG1: ['Bia Lima'],
        ))),
      );

      expect(find.textContaining('Ausentes:'), findsNothing);
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

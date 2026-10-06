import 'dart:convert';

import 'package:assistant_app/widgets/project_groups_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _discipline() => {
      'id': 'd1',
      'code': 'ARA0040',
      'name': 'BANCO DE DADOS',
      'label': 'ARA0040 - BANCO DE DADOS',
      'semester': '2026.2',
      'active': true,
      'class_count': 2,
    };

Map<String, dynamic> _class(String id, String code, String name, int weekday) => {
      'id': id,
      'code': code,
      'name': name,
      'discipline_id': 'd1',
      'discipline': 'BANCO DE DADOS',
      'semester': '2026.2',
      'label': '$code $name',
      'active': true,
      'student_count': 12,
      'schedules': [
        {'weekday': weekday, 'start_time': '19:00', 'end_time': '20:40'}
      ],
      'schedule_label': '',
    };

Map<String, dynamic> _group(String id, String name,
        {String? classId, List<String>? classIds, String classLabel = ''}) =>
    {
      'id': id,
      'discipline_id': 'd1',
      'discipline': 'ARA0040 - BANCO DE DADOS',
      'class_id': classId ?? (classIds == null || classIds.isEmpty ? null : classIds.first),
      'class_ids': classIds ?? [if (classId != null) classId],
      'class_label': classLabel,
      'class_days': <String>[],
      'semester': '2026.2',
      'name': name,
      'project_title': '',
      'project_description': '',
      'review_notes': '',
      'score': null,
      'penalty_points': 0,
      'source_note': '',
      'members': [
        {
          'id': 'm-$id',
          'name': 'Aluno $name',
          'student_id': null,
          'student_name': null,
          'source_note': '',
          'position': 0,
        }
      ],
    };

bool _marcada(WidgetTester tester, String classId) => tester
    .widget<CheckboxListTile>(find.byKey(ValueKey('escolher-turma-$classId')))
    .value!;

const _segunda = '3001 Presencial · segunda';
const _quinta = '3002 Semipresencial · quinta';

class _Backend {
  final List<Map<String, dynamic>> groups;
  final List<Map<String, dynamic>>? classes;
  final List<String> conflicts;
  final requests = <http.Request>[];

  _Backend(this.groups, {this.classes, this.conflicts = const []});

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);

    if (path.endsWith('/education/disciplines')) return json([_discipline()]);
    if (path.endsWith('/education/classes')) {
      return json(classes ??
          [
            _class('c-qui', '3002', 'Semipresencial', 3),
            _class('c-seg', '3001', 'Presencial', 0),
          ]);
    }
    if (path.endsWith('/education/students')) return json([]);
    if (path.endsWith('/education/lessons')) return json([]);
    if (request.method == 'GET' && path.endsWith('/education/project-groups')) {
      return json(groups);
    }
    if (path.endsWith('/project-groups/infer-classes')) {
      return json({
        'assigned': 1,
        'without_linked_members': ['GRUPO 2'],
        'conflicting': [],
        'groups': {},
      });
    }
    if (path.endsWith('/project-groups/assign-class')) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      return json({'assigned': (body['group_ids'] as List).length});
    }
    if (path.endsWith('/project-groups/preview')) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      return json({
        'groups': 1,
        'members': 1,
        'linked': 0,
        'roster_count': 0,
        'names_without_unique_match': 1,
        'new_groups': 1,
        'updated_groups': 0,
        'members_removed_on_update': 0,
        'conflicting_names': conflicts,
        'group_names': [
          {
            'name': 'GRUPO 1',
            'members': 1,
            'source_note': '',
            'names': [
              {'name': 'Kaic Vinicius', 'linked': false, 'candidates': []},
            ],
          }
        ],
        'preview_sha256': 'a' * 64,
        'discipline_code': 'ARA0040',
        'discipline_name': 'BANCO DE DADOS',
        'semester': '2026.2',
        'class_ids': body['class_ids'] ?? [],
        'class_label': ((body['class_ids'] ?? []) as List)
            .map((id) => id == 'c-seg' ? _segunda : id == 'c-qui' ? _quinta : '$id')
            .join(' + '),
        'list_context': 'Grupos turma segunda:',
      });
    }
    if (path.endsWith('/project-groups/import')) {
      return json({
        'created': 1,
        'updated': 0,
        'linked_members': 0,
        'names_without_link': 1,
      });
    }
    return http.Response('{"detail":"inesperado $path"}', 404);
  }

  Map<String, dynamic> bodyOf(String suffix) => jsonDecode(
      requests.lastWhere((r) => r.url.path.endsWith(suffix)).body)
      as Map<String, dynamic>;
}

/// Dias usados nos testes: 05/10/2026 e segunda; 07/10 e quarta (nenhuma turma tem
/// aula); 08/10 e quinta. A turma "de hoje" depende do dia, entao ele e fixado.
final _segundaFeira = DateTime(2026, 10, 5, 10);
final _quartaFeira = DateTime(2026, 10, 7, 10);
final _quintaFeira = DateTime(2026, 10, 8, 10);

Future<void> _open(
  WidgetTester tester,
  _Backend backend, {
  String initialText = '',
  DateTime? now,
  required Future<void> Function() body,
}) async {
  final today = now ?? _quartaFeira;
  tester.view.physicalSize = const Size(1700, 1300);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ProjectGroupsTab(
          initialText: initialText,
          initialDisciplineCode: 'ARA0040',
          clock: () => today,
        ),
      ),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

/// Avanca alguns quadros sem esperar "assentar": enquanto a janela de previa esta
/// aberta a aba segue `busy`, com um indicador de carregamento que nunca para.
Future<void> _pumpFrames(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 150));
  }
}

void main() {
  group('filtro por turma', () {
    final groups = [
      _group('g1', 'GRUPO 1', classId: 'c-seg', classLabel: _segunda),
      _group('g2', 'GRUPO 1', classId: 'c-qui', classLabel: _quinta),
      _group('g3', 'GRUPO 7'),
    ];

    testWidgets('mostra cada turma com o dia, os alunos e a quantidade de grupos',
        (tester) async {
      await _open(tester, _Backend(groups), body: () async {
        expect(find.text('3 grupos cadastrados'), findsOneWidget);

        expect(find.text('Todas as turmas (3)'), findsOneWidget);
        expect(find.text('Sem turma (1)'), findsOneWidget);
        expect(find.text('$_segunda  ·  12 alunos  ·  1 grupos'), findsOneWidget);
        expect(find.text('$_quinta  ·  12 alunos  ·  1 grupos'), findsOneWidget);
      });
    });

    testWidgets('num dia sem aula as turmas ficam todas juntas, sem "hoje"',
        (tester) async {
      await _open(tester, _Backend(groups), now: _quartaFeira, body: () async {
        expect(find.textContaining('HOJE,'), findsNothing);
        expect(find.text('TURMAS'), findsOneWidget);
        expect(find.text('OUTRAS TURMAS'), findsNothing);
        // Nada marcado: aparecem todos os grupos.
        expect(find.text('3 grupos cadastrados'), findsOneWidget);
      });
    });

    testWidgets('na segunda a turma da segunda vem marcada e separada em "hoje"',
        (tester) async {
      await _open(tester, _Backend(groups), now: _segundaFeira, body: () async {
        expect(find.text('HOJE, SEGUNDA-FEIRA'), findsOneWidget);
        expect(find.text('OUTRAS TURMAS'), findsOneWidget);

        final hoje = tester.widget<ChoiceChip>(find.byKey(const ValueKey('turma-c-seg')));
        final outra = tester.widget<ChoiceChip>(find.byKey(const ValueKey('turma-c-qui')));
        expect(hoje.selected, isTrue);
        expect(outra.selected, isFalse);

        // Só os grupos da segunda, e a tela diz que há mais na disciplina.
        expect(find.text('1 grupos cadastrados (de 3 na disciplina)'), findsOneWidget);
        expect(find.textContaining('GRUPO 1 • $_segunda'), findsOneWidget);
        expect(find.textContaining('GRUPO 1 • $_quinta'), findsNothing);
      });
    });

    testWidgets('as turmas de hoje aparecem acima das outras', (tester) async {
      await _open(tester, _Backend(groups), now: _quintaFeira, body: () async {
        expect(find.text('HOJE, QUINTA-FEIRA'), findsOneWidget);
        final hoje = tester.getTopLeft(find.byKey(const ValueKey('turma-c-qui'))).dy;
        final outras = tester.getTopLeft(find.byKey(const ValueKey('turma-c-seg'))).dy;
        final rotulo = tester.getTopLeft(find.text('OUTRAS TURMAS')).dy;

        expect(hoje < rotulo && rotulo < outras, isTrue);
      });
    });

    testWidgets('o professor pode ampliar para todas as turmas', (tester) async {
      await _open(tester, _Backend(groups), now: _segundaFeira, body: () async {
        await tester.tap(find.byKey(const ValueKey('turma-todas')));
        await tester.pumpAndSettle();

        expect(find.text('3 grupos cadastrados'), findsOneWidget);
        expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey('turma-todas'))).selected,
            isTrue);
      });
    });

    testWidgets('escolher a quinta deixa só os grupos dela', (tester) async {
      await _open(tester, _Backend(groups), body: () async {
        await tester.tap(find.byKey(const ValueKey('turma-c-qui')));
        await tester.pumpAndSettle();

        expect(find.text('1 grupos cadastrados (de 3 na disciplina)'),
            findsOneWidget);
        expect(find.textContaining('GRUPO 1 • $_quinta'), findsOneWidget);
        expect(find.textContaining('GRUPO 1 • $_segunda'), findsNothing);
        expect(find.textContaining('GRUPO 7'), findsNothing);
      });
    });

    testWidgets('"sem turma" mostra os grupos antigos', (tester) async {
      await _open(tester, _Backend(groups), body: () async {
        await tester.tap(find.byKey(const ValueKey('turma-sem')));
        await tester.pumpAndSettle();

        expect(find.text('GRUPO 7 • 2026.2'), findsOneWidget);
        expect(find.text('1 grupos cadastrados (de 3 na disciplina)'), findsOneWidget);
      });
    });

    testWidgets('duas turmas no mesmo dia: as duas em "hoje" e as duas marcadas',
        (tester) async {
      final backend = _Backend(groups, classes: [
        _class('c-seg', '3001', 'Presencial', 0),
        _class('c-noite', '3003', 'Noite', 0),
      ]);
      await _open(tester, backend, now: _segundaFeira, body: () async {
        expect(find.text('HOJE, SEGUNDA-FEIRA'), findsOneWidget);
        expect(find.byKey(const ValueKey('turma-c-seg')), findsOneWidget);
        expect(find.byKey(const ValueKey('turma-c-noite')), findsOneWidget);
        expect(find.text('OUTRAS TURMAS'), findsNothing);
        // O grupo é do dia: as duas turmas dele vêm marcadas, e "todas" não.
        ChoiceChip chip(String key) =>
            tester.widget<ChoiceChip>(find.byKey(ValueKey(key)));
        expect(chip('turma-c-seg').selected, isTrue);
        expect(chip('turma-c-noite').selected, isTrue);
        expect(chip('turma-todas').selected, isFalse);
      });
    });

    testWidgets('tocar em outra turma junta ao filtro; tocar de novo tira',
        (tester) async {
      final backend = _Backend([
        _group('g1', 'GRUPO 1', classIds: ['c-seg']),
        _group('g2', 'GRUPO 2', classIds: ['c-noite']),
        _group('g3', 'GRUPO 3', classIds: ['c-qui']),
      ], classes: [
        _class('c-seg', '3001', 'Presencial', 0),
        _class('c-noite', '3003', 'Noite', 0),
        _class('c-qui', '3002', 'Quinta', 3),
      ]);
      await _open(tester, backend, now: _segundaFeira, body: () async {
        expect(find.text('2 grupos cadastrados (de 3 na disciplina)'), findsOneWidget);

        await tester.tap(find.byKey(const ValueKey('turma-c-qui')));
        await tester.pumpAndSettle();
        expect(find.text('3 grupos cadastrados'), findsOneWidget);

        await tester.tap(find.byKey(const ValueKey('turma-c-seg')));
        await tester.pumpAndSettle();
        expect(find.text('2 grupos cadastrados (de 3 na disciplina)'), findsOneWidget);
        expect(find.text('GRUPO 1 • 2026.2'), findsNothing);

        await tester.tap(find.byKey(const ValueKey('turma-todas')));
        await tester.pumpAndSettle();
        expect(find.text('3 grupos cadastrados'), findsOneWidget);
      });
    });

    testWidgets('as duas turmas marcadas vão sugeridas na importação',
        (tester) async {
      final backend = _Backend([], classes: [
        _class('c-seg', '3001', 'Presencial', 0),
        _class('c-noite', '3003', 'Noite', 0),
      ]);
      await _open(tester, backend,
          now: _segundaFeira,
          initialText: 'GRUPO 1\n- Kaic Vinicius\n', body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();

        expect(_marcada(tester, 'c-seg'), isTrue);
        expect(_marcada(tester, 'c-noite'), isTrue);
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);
        expect(backend.bodyOf('/project-groups/preview')['class_ids'],
            ['c-noite', 'c-seg']);
      });
    });

    testWidgets('o cartão do grupo diz de qual turma ele é', (tester) async {
      await _open(tester, _Backend(groups), body: () async {
        expect(find.textContaining('GRUPO 1 • $_segunda • 2026.2'),
            findsOneWidget);
        expect(find.textContaining('GRUPO 1 • $_quinta • 2026.2'),
            findsOneWidget);
        // Grupo antigo, sem turma: continua como era.
        expect(find.text('GRUPO 7 • 2026.2'), findsOneWidget);
      });
    });
  });

  group('ligar grupos sem turma', () {
    testWidgets('liga todos os grupos soltos à turma escolhida',
        (tester) async {
      final backend = _Backend([
        _group('g1', 'GRUPO 1'),
        _group('g2', 'GRUPO 2'),
        _group('g3', 'GRUPO 3', classId: 'c-qui', classLabel: _quinta),
      ]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.text('Ligar grupos sem turma'));
        await tester.pumpAndSettle();
        expect(find.text('Ligar 2 grupos sem turma'), findsOneWidget);

        await tester.tap(find.text(_segunda));
        await tester.pump();
        await tester.tap(find.text('Ligar à turma'));
        await tester.pumpAndSettle();

        final body = backend.bodyOf('/project-groups/assign-class');
        expect(body['class_ids'], ['c-seg']);
        expect(body['group_ids'], ['g1', 'g2']);
        expect(find.text('2 grupos ligados à turma.'), findsOneWidget);
      });
    });

    testWidgets('sem grupo solto o botão não aparece', (tester) async {
      await _open(
        tester,
        _Backend([_group('g1', 'GRUPO 1', classId: 'c-seg', classLabel: _segunda)]),
        body: () async {
          expect(find.text('Ligar grupos sem turma'), findsNothing);
        },
      );
    });
  });

  group('cadastrar a lista de uma turma', () {
    const lista = 'Grupos turma segunda:\nGRUPO 1\n- Kaic Vinicius\n';

    testWidgets('o título da lista já marca a turma da segunda', (tester) async {
      final backend = _Backend([]);
      await _open(tester, backend, initialText: lista, body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();

        expect(find.text('Esta lista é de quais turmas?'), findsOneWidget);
        expect(find.textContaining('O título da lista indica as turmas marcadas'),
            findsOneWidget);
        expect(_marcada(tester, 'c-seg'), isTrue);
        expect(_marcada(tester, 'c-qui'), isFalse);
        expect(backend.requests.any((r) => r.url.path.endsWith('/preview')),
            isFalse);

        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);

        expect(backend.bodyOf('/project-groups/preview')['class_ids'], ['c-seg']);
        expect(find.text('Turma: $_segunda'), findsOneWidget);
      });
    });

    testWidgets('confirmar cadastra na turma escolhida', (tester) async {
      final backend = _Backend([]);
      await _open(tester, backend, initialText: lista, body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);
        await tester.tap(find.text('Confirmar cadastro'));
        await tester.pumpAndSettle();

        final body = backend.bodyOf('/project-groups/import');
        expect(body['class_ids'], ['c-seg']);
        expect(body['discipline_id'], 'd1');
        expect(find.textContaining('1 grupos criados'), findsOneWidget);
      });
    });

    testWidgets('lista sem título pede a turma e não escolhe sozinha',
        (tester) async {
      final backend = _Backend([]);
      await _open(tester, backend,
          initialText: 'GRUPO 1\n- Kaic Vinicius\n', body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();

        final continuar = tester.widget<ElevatedButton>(
            find.widgetWithText(ElevatedButton, 'Continuar'));
        expect(continuar.onPressed, isNull); // nenhuma turma marcada
        expect(find.textContaining('o GRUPO 1 da segunda não se confunde'),
            findsOneWidget);

        await tester.tap(find.text(_quinta));
        await tester.pump();
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);
        expect(backend.bodyOf('/project-groups/preview')['class_ids'], ['c-qui']);
      });
    });

    testWidgets('a turma do dia, marcada na tela, vem sugerida na importação',
        (tester) async {
      final backend = _Backend([]);
      await _open(tester, backend,
          now: _segundaFeira,
          initialText: 'GRUPO 1\n- Kaic Vinicius\n', body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();

        expect(_marcada(tester, 'c-seg'), isTrue);
        // A sugestão veio da tela, não do título da lista: o texto não diz isso.
        expect(find.textContaining('O título da lista indica'), findsNothing);
      });
    });

    testWidgets('"sem turma" cadastra como antes, sem turma nenhuma', (tester) async {
      final backend = _Backend([]);
      await _open(tester, backend,
          initialText: 'GRUPO 1\n- Kaic Vinicius\n', body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Sem turma'));
        await tester.pump();
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);

        expect(backend.bodyOf('/project-groups/preview').containsKey('class_ids'),
            isFalse);
      });
    });

    testWidgets('cancelar a escolha da turma não manda nada', (tester) async {
      final backend = _Backend([]);
      await _open(tester, backend, initialText: lista, body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Cancelar'));
        await tester.pumpAndSettle();

        expect(backend.requests.any((r) => r.url.path.endsWith('/preview')),
            isFalse);
      });
    });
  });

  group('deduzir as turmas pelos alunos', () {
    testWidgets('o botão manda a disciplina e conta o que ficou de fora',
        (tester) async {
      final backend = _Backend([
        _group('g1', 'GRUPO 1'),
        _group('g2', 'GRUPO 2'),
      ]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.text('Deduzir turmas pelos alunos'));
        await tester.pumpAndSettle();

        expect(backend.bodyOf('/project-groups/infer-classes')['discipline_id'], 'd1');
        expect(find.textContaining('1 grupos ligados às turmas dos seus alunos.'),
            findsOneWidget);
        expect(find.textContaining('Sem aluno vinculado, ficaram sem turma: GRUPO 2'),
            findsOneWidget);
      });
    });

    testWidgets('sem grupo solto o botão não aparece', (tester) async {
      await _open(
        tester,
        _Backend([_group('g1', 'GRUPO 1', classIds: ['c-seg'])]),
        body: () async {
          expect(find.text('Deduzir turmas pelos alunos'), findsNothing);
        },
      );
    });
  });

  group('aula reunida: grupos que misturam duas turmas', () {
    // Segunda tem duas turmas (3002 e 3030); a quinta tem a 3001.
    final turmas = [
      _class('c-3002', '3002', 'A', 0),
      _class('c-3030', '3030', 'B', 0),
      _class('c-qui', '3001', 'Quinta', 3),
    ];
    const lista = 'Grupos turma segunda:\nGRUPO 1\n- Kaic Vinicius\n';

    testWidgets('o título "segunda" marca as duas turmas da segunda',
        (tester) async {
      final backend = _Backend([], classes: turmas);
      await _open(tester, backend, initialText: lista, body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();

        expect(_marcada(tester, 'c-3002'), isTrue);
        expect(_marcada(tester, 'c-3030'), isTrue);
        expect(_marcada(tester, 'c-qui'), isFalse);
        expect(find.byKey(const ValueKey('aviso-aula-reunida')), findsOneWidget);

        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);

        expect(backend.bodyOf('/project-groups/preview')['class_ids'],
            ['c-3002', 'c-3030']);
        expect(find.textContaining('Turma: '), findsOneWidget);
        expect(find.textContaining(' + '), findsWidgets);
      });
    });

    testWidgets('confirmar manda as duas turmas no cadastro', (tester) async {
      final backend = _Backend([], classes: turmas);
      await _open(tester, backend, initialText: lista, body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);
        await tester.tap(find.text('Confirmar cadastro'));
        await tester.pumpAndSettle();

        expect(backend.bodyOf('/project-groups/import')['class_ids'],
            ['c-3002', 'c-3030']);
      });
    });

    testWidgets('o professor desmarca uma turma e o aviso some', (tester) async {
      final backend = _Backend([], classes: turmas);
      await _open(tester, backend, initialText: lista, body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(const ValueKey('escolher-turma-c-3030')));
        await tester.pump();

        expect(_marcada(tester, 'c-3030'), isFalse);
        expect(find.byKey(const ValueKey('aviso-aula-reunida')), findsNothing);
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);
        expect(backend.bodyOf('/project-groups/preview')['class_ids'], ['c-3002']);
      });
    });

    testWidgets('marcar uma turma desmarca "sem turma" e vice-versa',
        (tester) async {
      final backend = _Backend([], classes: turmas);
      await _open(tester, backend,
          initialText: 'GRUPO 1\n- Kaic Vinicius\n', body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(const ValueKey('escolher-sem-turma')));
        await tester.pump();
        await tester.tap(find.byKey(const ValueKey('escolher-turma-c-3002')));
        await tester.pump();

        final semTurma = tester.widget<CheckboxListTile>(
            find.byKey(const ValueKey('escolher-sem-turma')));
        expect(semTurma.value, isFalse);
        expect(_marcada(tester, 'c-3002'), isTrue);

        await tester.tap(find.byKey(const ValueKey('escolher-sem-turma')));
        await tester.pump();
        expect(_marcada(tester, 'c-3002'), isFalse);
      });
    });

    testWidgets('nome em conflito bloqueia o cadastro e explica', (tester) async {
      final backend = _Backend([], classes: turmas, conflicts: ['GRUPO 1']);
      await _open(tester, backend, initialText: lista, body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);

        expect(find.byKey(const ValueKey('aviso-nome-em-conflito')), findsOneWidget);
        final confirmar = tester.widget<ElevatedButton>(
            find.widgetWithText(ElevatedButton, 'Confirmar cadastro'));
        expect(confirmar.onPressed, isNull);
      });
    });

    testWidgets('o grupo misturado aparece no filtro das duas turmas',
        (tester) async {
      final misto = _group('g1', 'GRUPO 1', classIds: ['c-3002', 'c-3030']);
      final backend = _Backend([
        misto,
        _group('g2', 'GRUPO 2', classIds: ['c-3002']),
        _group('g3', 'GRUPO 3', classIds: ['c-qui']),
      ], classes: turmas);
      await _open(tester, backend, body: () async {
        expect(find.text('3 grupos cadastrados'), findsOneWidget);

        // Cada chip conta os grupos em que a turma participa.
        expect(find.textContaining('3002 A · segunda  ·  12 alunos  ·  2 grupos'),
            findsOneWidget);
        expect(find.textContaining('3030 B · segunda  ·  12 alunos  ·  1 grupos'),
            findsOneWidget);

        await tester.tap(find.byKey(const ValueKey('turma-c-3030')));
        await tester.pumpAndSettle();
        expect(find.text('1 grupos cadastrados (de 3 na disciplina)'), findsOneWidget);
        expect(find.text('GRUPO 1 • 2026.2'), findsOneWidget);
        expect(find.text('GRUPO 2 • 2026.2'), findsNothing);

        await tester.tap(find.byKey(const ValueKey('turma-c-3002')));
        await tester.pumpAndSettle();
        expect(find.text('2 grupos cadastrados (de 3 na disciplina)'), findsOneWidget);
        expect(find.text('GRUPO 1 • 2026.2'), findsOneWidget);
        expect(find.text('GRUPO 2 • 2026.2'), findsOneWidget);
      });
    });

    testWidgets('ligar grupos soltos a duas turmas de uma vez', (tester) async {
      final backend = _Backend([
        _group('g1', 'GRUPO 1'),
        _group('g2', 'GRUPO 2'),
      ], classes: turmas);
      await _open(tester, backend, body: () async {
        await tester.tap(find.text('Ligar grupos sem turma'));
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(const ValueKey('escolher-turma-c-3002')));
        await tester.pump();
        await tester.tap(find.byKey(const ValueKey('escolher-turma-c-3030')));
        await tester.pump();
        await tester.tap(find.text('Ligar à turma'));
        await tester.pumpAndSettle();

        final body = backend.bodyOf('/project-groups/assign-class');
        expect(body['class_ids'], ['c-3002', 'c-3030']);
        expect(body['group_ids'], ['g1', 'g2']);
      });
    });
  });
}

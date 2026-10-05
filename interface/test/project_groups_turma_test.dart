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
        {String? classId, String classLabel = ''}) =>
    {
      'id': id,
      'discipline_id': 'd1',
      'discipline': 'ARA0040 - BANCO DE DADOS',
      'class_id': classId,
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

const _segunda = '3001 Presencial · segunda';
const _quinta = '3002 Semipresencial · quinta';

class _Backend {
  final List<Map<String, dynamic>> groups;
  final requests = <http.Request>[];

  _Backend(this.groups);

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);

    if (path.endsWith('/education/disciplines')) return json([_discipline()]);
    if (path.endsWith('/education/classes')) {
      return json([
        _class('c-qui', '3002', 'Semipresencial', 3),
        _class('c-seg', '3001', 'Presencial', 0),
      ]);
    }
    if (path.endsWith('/education/students')) return json([]);
    if (path.endsWith('/education/lessons')) return json([]);
    if (request.method == 'GET' && path.endsWith('/education/project-groups')) {
      return json(groups);
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
        'class_id': body['class_id'],
        'class_label': body['class_id'] == 'c-seg' ? _segunda : '',
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

Future<void> _open(
  WidgetTester tester,
  _Backend backend, {
  String initialText = '',
  required Future<void> Function() body,
}) async {
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

    testWidgets('mostra cada turma com o dia e a quantidade de grupos',
        (tester) async {
      await _open(tester, _Backend(groups), body: () async {
        expect(find.text('3 grupos cadastrados'), findsOneWidget);

        await tester.tap(find.text('Todas as turmas (3)'));
        await tester.pumpAndSettle();

        expect(find.text('$_segunda (1)'), findsOneWidget);
        expect(find.text('$_quinta (1)'), findsOneWidget);
        expect(find.text('Sem turma (1)'), findsOneWidget);
      });
    });

    testWidgets('escolher a quinta deixa só os grupos dela', (tester) async {
      await _open(tester, _Backend(groups), body: () async {
        await tester.tap(find.text('Todas as turmas (3)'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('$_quinta (1)').last);
        await tester.pumpAndSettle();

        expect(find.text('1 grupos cadastrados (de 3 na disciplina)'),
            findsOneWidget);
        expect(find.textContaining('GRUPO 1 • $_quinta'), findsOneWidget);
        expect(find.textContaining('GRUPO 1 • $_segunda'), findsNothing);
        expect(find.textContaining('GRUPO 7'), findsNothing);
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
        expect(body['class_id'], 'c-seg');
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

        expect(find.text('Esta lista é de qual turma?'), findsOneWidget);
        expect(find.textContaining('O título da lista indica a turma marcada'),
            findsOneWidget);
        final segunda = tester.widget<RadioListTile<String>>(
            find.widgetWithText(RadioListTile<String>, _segunda));
        expect(segunda.groupValue, 'c-seg');
        expect(backend.requests.any((r) => r.url.path.endsWith('/preview')),
            isFalse);

        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);

        expect(backend.bodyOf('/project-groups/preview')['class_id'], 'c-seg');
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
        expect(body['class_id'], 'c-seg');
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
        expect(backend.bodyOf('/project-groups/preview')['class_id'], 'c-qui');
      });
    });

    testWidgets('"sem turma" cadastra como antes, sem class_id', (tester) async {
      final backend = _Backend([]);
      await _open(tester, backend,
          initialText: 'GRUPO 1\n- Kaic Vinicius\n', body: () async {
        await tester.tap(find.text('Conferir e cadastrar grupos'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Sem turma'));
        await tester.pump();
        await tester.tap(find.text('Continuar'));
        await _pumpFrames(tester);

        expect(backend.bodyOf('/project-groups/preview').containsKey('class_id'),
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
}

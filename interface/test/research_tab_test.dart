import 'dart:convert';

import 'package:assistant_app/widgets/research_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:qr_flutter/qr_flutter.dart';

Map<String, dynamic> _project({
  String id = 'p1',
  String title = 'IA no diagnóstico de plantas',
  String status = 'active',
  int stages = 3,
  int done = 1,
  int overdue = 1,
  int participants = 2,
  int pending = 0,
}) =>
    {
      'id': id,
      'title': title,
      'description': 'Visão computacional aplicada',
      'area': 'Computação',
      'semester': '2026.2',
      'status': status,
      'start_date': '2026-10-01T00:00:00',
      'end_date': null,
      'stages': stages,
      'done': done,
      'overdue': overdue,
      'progress': stages == 0 ? 0 : (done * 100 / stages).round(),
      'participants': participants,
      'pending': pending,
      'next_due': '2026-11-20T23:59:00',
      'next_title': 'Coleta',
    };

Map<String, dynamic> _stage(String id, String title, String status, String state,
        {String? due}) =>
    {
      'id': id,
      'title': title,
      'description': 'Fazer isto',
      'due_at': due,
      'status': status,
      'state': state,
      'position': 0,
    };

Map<String, dynamic> _person(String id, String name,
        {String role = 'orientando',
        bool known = false,
        String institution = '',
        String status = 'accepted'}) =>
    {
      'id': id,
      'name': name,
      'email': '$id@exemplo.com',
      'phone': '',
      'enrollment': known ? '20240001' : '',
      'institution': institution,
      'role': role,
      'known_student': known,
      'status': status,
    };

class _Backend {
  List<Map<String, dynamic>> projects;
  List<Map<String, dynamic>> stages;
  List<Map<String, dynamic>> people;
  final requests = <http.Request>[];
  bool aiAnswers = true;
  Map<String, dynamic> joinLink = {
    'path': '/education/research-join/tok123',
    'active': true,
    'role': 'orientando',
    'pending': 0,
  };

  _Backend({
    List<Map<String, dynamic>>? projects,
    List<Map<String, dynamic>>? stages,
    List<Map<String, dynamic>>? people,
  })  : projects = projects ?? [],
        stages = stages ?? [],
        people = people ?? [];

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);

    if (path.endsWith('/generate-plan')) {
      return json({
        'from_ai': aiAnswers,
        'stages': [
          {'title': 'Revisão bibliográfica', 'description': 'Ler', 'due_at': '2026-11-10T00:00:00'},
          {'title': 'Coleta de dados', 'description': '', 'due_at': null},
        ],
      });
    }
    if (path.endsWith('/education/research')) {
      if (request.method == 'POST') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final created = _project(id: 'novo', title: body['title'] as String,
            stages: (body['stages'] as List).length, done: 0, overdue: 0, participants: 0);
        projects = [created, ...projects];
        return json(created);
      }
      return json(projects);
    }
    if (path.endsWith('/participants') && request.method == 'POST') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final created = _person('n${people.length}', body['name'] as String,
          role: body['role'] as String);
      people = [...people, created];
      return json(created);
    }
    if (path.endsWith('/join-link')) {
      if (request.method == 'PATCH') {
        joinLink = {...joinLink, ...jsonDecode(request.body) as Map<String, dynamic>};
      }
      return json(joinLink);
    }
    final decision = RegExp(r'/participants/(\w+)/decision$').firstMatch(path);
    if (decision != null && request.method == 'POST') {
      final accept = (jsonDecode(request.body) as Map<String, dynamic>)['accept'] == true;
      final id = decision.group(1);
      final person = people.firstWhere((p) => p['id'] == id);
      people = accept
          ? [for (final p in people) p['id'] == id ? {...p, 'status': 'accepted'} : p]
          : [for (final p in people) if (p['id'] != id) p];
      return json({...person, 'status': accept ? 'accepted' : 'pending'});
    }
    final stage = RegExp(r'/stages/(\w+)$').firstMatch(path);
    if (stage != null && request.method == 'PATCH') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      stages = [
        for (final s in stages)
          s['id'] == stage.group(1)
              ? {...s, ...body, 'state': body['status'] ?? s['state']}
              : s
      ];
      return json(stages.firstWhere((s) => s['id'] == stage.group(1)));
    }
    if (path.endsWith('/stages') && request.method == 'POST') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final created = _stage('n${stages.length}', body['title'] as String, 'todo', 'todo');
      stages = [...stages, created];
      return json(created);
    }
    final one = RegExp(r'/education/research/(\w+)$').firstMatch(path);
    if (one != null && request.method == 'GET') {
      final project = projects.firstWhere((p) => p['id'] == one.group(1));
      return json({'project': project, 'stages': stages, 'participants': people});
    }
    if (one != null && request.method == 'PATCH') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      projects = [
        for (final p in projects) p['id'] == one.group(1) ? {...p, ...body} : p
      ];
      return json(projects.firstWhere((p) => p['id'] == one.group(1)));
    }
    return http.Response('{"detail":"inesperado $path"}', 404);
  }

  bool called(String method, String suffix) =>
      requests.any((r) => r.method == method && r.url.path.endsWith(suffix));

  Map<String, dynamic> bodyOf(String method, String suffix) => jsonDecode(requests
      .lastWhere((r) => r.method == method && r.url.path.endsWith(suffix))
      .body) as Map<String, dynamic>;
}

Future<void> _open(
  WidgetTester tester,
  _Backend backend, {
  required Future<void> Function() body,
}) async {
  tester.view.physicalSize = const Size(1600, 2200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: ResearchTab(pollEvery: Duration.zero)),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

_Backend _withProject() => _Backend(
      projects: [_project()],
      stages: [
        _stage('s1', 'Revisão bibliográfica', 'done', 'done', due: '2026-09-01T00:00:00'),
        _stage('s2', 'Coleta de dados', 'doing', 'overdue', due: '2026-09-20T00:00:00'),
        _stage('s3', 'Artigo', 'todo', 'todo', due: '2027-01-10T00:00:00'),
      ],
      people: [
        _person('a1', 'Ana Souza', known: true),
        _person('c1', 'Dr. Carlos', role: 'colaborador', institution: 'USP'),
      ],
    );

void main() {
  testWidgets('sem pesquisas, orienta a criar a primeira', (tester) async {
    await _open(tester, _Backend(), body: () async {
      expect(find.textContaining('Nenhuma pesquisa ainda'), findsOneWidget);
      expect(find.byKey(const Key('research-new')), findsOneWidget);
    });
  });

  testWidgets('descrever, gerar o plano com a IA, ajustar e criar', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('research-new')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('research-generate')));
      await tester.pumpAndSettle();
      expect(backend.called('POST', '/generate-plan'), isFalse,
          reason: 'sem título a IA nem é chamada');

      await tester.enterText(find.byKey(const Key('research-title')), 'Minha pesquisa');
      await tester.enterText(
          find.byKey(const Key('research-description')), 'Visão computacional');
      await tester.tap(find.byKey(const Key('research-generate')));
      await tester.pumpAndSettle();

      final plan = backend.bodyOf('POST', '/generate-plan');
      expect(plan['title'], 'Minha pesquisa');
      expect(plan['weeks'], 24);
      expect(find.text('Revisão bibliográfica'), findsOneWidget);
      expect(find.textContaining('A IA montou 2 etapas'), findsOneWidget);

      await tester.tap(find.byKey(const Key('research-create')));
      await tester.pumpAndSettle();

      final sent = backend.bodyOf('POST', '/education/research');
      expect(sent['title'], 'Minha pesquisa');
      expect((sent['stages'] as List).map((s) => s['title']),
          ['Revisão bibliográfica', 'Coleta de dados']);
      expect((sent['stages'] as List).first.containsKey('due_at'), isTrue);
      expect((sent['stages'] as List).last.containsKey('due_at'), isFalse);
      expect(find.text('MINHA PESQUISA'), findsOneWidget);
    });
  });

  testWidgets('IA fora do ar avisa que usou as etapas padrão', (tester) async {
    final backend = _Backend()..aiAnswers = false;
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('research-new')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('research-title')), 'Tema');
      await tester.tap(find.byKey(const Key('research-generate')));
      await tester.pumpAndSettle();

      expect(find.textContaining('A IA não respondeu'), findsOneWidget);
    });
  });

  testWidgets('mostra progresso, participantes e etapas com o atraso em destaque',
      (tester) async {
    await _open(tester, _withProject(), body: () async {
      expect(find.text('IA NO DIAGNÓSTICO DE PLANTAS'), findsOneWidget);
      expect(find.text('33%'), findsOneWidget);
      expect(find.text('1 atrasada(s)'), findsOneWidget);
      expect(find.text('Ana Souza'), findsOneWidget);
      expect(find.text('ALUNO CONHECIDO'), findsOneWidget);
      expect(find.text('USP'), findsOneWidget);
      expect(find.text('Colaborador'), findsOneWidget);
      expect(find.text('Coleta de dados'), findsOneWidget);
      expect(find.textContaining('Venceu'), findsOneWidget);
    });
  });

  testWidgets('tocar no ícone da etapa avança a situação (fazendo para feita)',
      (tester) async {
    final backend = _withProject();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('stage-status-s2')));
      await tester.pumpAndSettle();

      final sent = backend.bodyOf('PATCH', '/stages/s2');
      expect(sent['status'], 'done');
    });
  });

  testWidgets('adiciona um participante de fora', (tester) async {
    final backend = _withProject();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('participant-add')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('participant-name')), 'Maria Externa');
      await tester.tap(find.byKey(const Key('participant-save')));
      await tester.pumpAndSettle();

      final sent = backend.bodyOf('POST', '/participants');
      expect(sent['name'], 'Maria Externa');
      expect(sent['role'], 'orientando');
      expect(find.text('Maria Externa'), findsOneWidget);
    });
  });

  testWidgets('cria uma etapa nova com título', (tester) async {
    final backend = _withProject();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('stage-add')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('stage-title')), 'Submissão');
      await tester.tap(find.byKey(const Key('stage-save')));
      await tester.pumpAndSettle();

      expect(backend.bodyOf('POST', '/stages')['title'], 'Submissão');
      expect(find.text('Submissão'), findsOneWidget);
    });
  });

  testWidgets('mudar a situação da pesquisa grava na hora', (tester) async {
    final backend = _withProject();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('research-status')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Concluída').last);
      await tester.pumpAndSettle();

      expect(backend.bodyOf('PATCH', '/education/research/p1')['status'], 'done');
    });
  });

  testWidgets('LINK ONLINE mostra o endereço, o QR Code e copia o link', (tester) async {
    final backend = _withProject();
    final copied = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform,
        (call) async {
      if (call.method == 'Clipboard.setData') {
        copied.add((call.arguments as Map)['text'] as String);
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));

    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('participant-link')));
      await tester.pumpAndSettle();

      expect(find.text('Cadastro online na pesquisa'), findsOneWidget);
      expect(find.byType(QrImageView), findsOneWidget);
      final shown = tester.widget<SelectableText>(find.byKey(const Key('join-url'))).data!;
      expect(shown, endsWith('/education/research-join/tok123'));

      await tester.tap(find.byKey(const Key('join-copy')));
      await tester.pumpAndSettle();
      expect(copied, [shown]);
    });
  });

  testWidgets('fechar o link e trocar o papel gravam na hora', (tester) async {
    final backend = _withProject();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('participant-link')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('join-active')));
      await tester.pumpAndSettle();
      expect(backend.bodyOf('PATCH', '/join-link'), {'active': false});

      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Colaborador').last);
      await tester.pumpAndSettle();
      expect(backend.bodyOf('PATCH', '/join-link'), {'role': 'colaborador'});
    });
  });

  testWidgets('quem preencheu o link aparece aguardando e o professor aceita', (tester) async {
    final backend = _Backend(
      projects: [_project(participants: 1, pending: 1)],
      stages: [_stage('s1', 'Revisão', 'todo', 'todo')],
      people: [
        _person('a1', 'Ana Souza', known: true),
        _person('b2', 'Bia Online', status: 'pending'),
      ],
    );
    await _open(tester, backend, body: () async {
      expect(find.text('1 aguardando você'), findsOneWidget);
      expect(find.text('AGUARDANDO'), findsOneWidget);
      // Quem já participa continua com o botão de tirar; quem aguarda tem aceitar e recusar.
      expect(find.byTooltip('Tirar da pesquisa'), findsOneWidget);

      await tester.tap(find.byKey(const Key('participant-accept-b2')));
      await tester.pumpAndSettle();

      expect(backend.bodyOf('POST', '/participants/b2/decision'), {'accept': true});
      expect(find.text('AGUARDANDO'), findsNothing);
      expect(find.byTooltip('Tirar da pesquisa'), findsNWidgets(2));
    });
  });

  testWidgets('recusar tira o cadastro da lista', (tester) async {
    final backend = _Backend(
      projects: [_project(participants: 0, pending: 1)],
      stages: [_stage('s1', 'Revisão', 'todo', 'todo')],
      people: [_person('b2', 'Bia Online', status: 'pending')],
    );
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('participant-reject-b2')));
      await tester.pumpAndSettle();

      expect(backend.bodyOf('POST', '/participants/b2/decision'), {'accept': false});
      expect(find.text('Bia Online'), findsNothing);
    });
  });
}

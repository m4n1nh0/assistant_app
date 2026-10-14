import 'dart:convert';

import 'package:assistant_app/models/mentorship.dart';
import 'package:assistant_app/widgets/mentorships_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _form({
  String id = 'f1',
  String title = 'Mentoria de dados',
  int signups = 0,
  int pending = 0,
  int accepted = 0,
  String state = 'open',
}) =>
    {
      'id': id,
      'path': '/education/mentorship-signup/tok$id',
      'title': title,
      'description': 'Encontros quinzenais',
      'semester': '2026.2',
      'fields': [
        {'id': 'idade', 'label': 'Idade', 'type': 'number', 'required': true, 'options': []},
        {
          'id': 'horarios',
          'label': 'Horários livres',
          'type': 'availability',
          'required': true,
          'options': []
        },
      ],
      'active': state != 'closed',
      'state': state,
      'max_slots': 8,
      'signups': signups,
      'pending': pending,
      'accepted': accepted,
    };

Map<String, dynamic> _signup(String id, String name, {String status = 'pending', bool known = false}) => {
      'id': id,
      'enrollment': '2024000$id',
      'name': name,
      'email': '$id@exemplo.com',
      'phone': '11912345678',
      'answers': {
        'idade': 21,
        'horarios': ['sab-manha', 'seg-noite'],
      },
      'known_student': known,
      'status': status,
    };

class _Backend {
  List<Map<String, dynamic>> forms;
  List<Map<String, dynamic>> signups;
  final requests = <http.Request>[];
  bool aiAnswers = true;

  _Backend({List<Map<String, dynamic>>? forms, List<Map<String, dynamic>>? signups})
      : forms = forms ?? [],
        signups = signups ?? [];

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);

    if (path.endsWith('/generate-fields')) {
      return json({
        'from_ai': aiAnswers,
        'fields': [
          {'id': 'objetivo', 'label': 'Objetivo', 'type': 'textarea', 'required': true, 'options': []},
          {'id': 'idade', 'label': 'Idade', 'type': 'number', 'required': true, 'options': []},
        ],
      });
    }
    if (path.endsWith('/education/mentorships')) {
      if (request.method == 'POST') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final created = {..._form(id: 'novo', title: body['title'] as String), 'fields': body['fields']};
        forms = [created, ...forms];
        return json(created);
      }
      return json(forms);
    }
    if (path.endsWith('/signups/status')) {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final ids = (body['ids'] as List).cast<String>();
      signups = [
        for (final s in signups)
          ids.contains(s['id']) ? {...s, 'status': body['status']} : s
      ];
      return json({
        'changed': ids.length,
        'class_id': 'c1',
        'form': _form(signups: signups.length, accepted: ids.length),
      });
    }
    if (path.endsWith('/signups')) return json(signups);
    if (path.endsWith('/export')) return json({'csv': 'Matrícula;Nome\n1;Ana', 'count': 1});
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
  tester.view.physicalSize = const Size(1600, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: MentorshipsTab(baseUrl: 'https://app.exemplo.com')),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

void main() {
  test('horários livres aparecem legíveis', () {
    expect(availabilityText(['sab-manha', 'seg-noite']), 'Sáb manhã, Seg noite');
    expect(availabilityText(null), '');
  });

  testWidgets('sem formulário, orienta a criar o primeiro', (tester) async {
    await _open(tester, _Backend(), body: () async {
      expect(find.textContaining('Nenhum formulário ainda'), findsOneWidget);
      expect(find.byKey(const Key('mentorship-new')), findsOneWidget);
    });
  });

  testWidgets('descrever, gerar com a IA, ajustar e criar o formulário', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('mentorship-new')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('mentorship-generate')));
      await tester.pumpAndSettle();
      expect(backend.called('POST', '/generate-fields'), isFalse,
          reason: 'sem descrição a IA nem é chamada');

      await tester.enterText(
          find.byKey(const Key('mentorship-title')), 'Mentoria de carreira');
      await tester.enterText(find.byKey(const Key('mentorship-description')),
          'Carreira em dados para ADS');
      await tester.tap(find.byKey(const Key('mentorship-generate')));
      await tester.pumpAndSettle();

      expect(backend.bodyOf('POST', '/generate-fields')['description'],
          'Carreira em dados para ADS');
      expect(find.text('Objetivo'), findsOneWidget);
      expect(find.textContaining('A IA montou 2 campos'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('mentorship-slots')), '12');
      await tester.tap(find.byKey(const Key('mentorship-create')));
      await tester.pumpAndSettle();

      final sent = backend.bodyOf('POST', '/education/mentorships');
      expect(sent['title'], 'Mentoria de carreira');
      expect(sent['max_slots'], 12);
      expect((sent['fields'] as List).map((f) => f['label']), ['Objetivo', 'Idade']);
      expect(find.text('MENTORIA DE CARREIRA'), findsOneWidget);
      expect(find.textContaining('/education/mentorship-signup/toknovo'), findsOneWidget);
    });
  });

  testWidgets('IA fora do ar avisa que usou os campos padrão', (tester) async {
    final backend = _Backend()..aiAnswers = false;
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('mentorship-new')));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.byKey(const Key('mentorship-description')), 'Mentoria de dados');
      await tester.tap(find.byKey(const Key('mentorship-generate')));
      await tester.pumpAndSettle();

      expect(find.textContaining('A IA não respondeu'), findsOneWidget);
    });
  });

  testWidgets('lista os inscritos com respostas, marca aluno conhecido e aceita', (tester) async {
    final backend = _Backend(
      forms: [_form(signups: 2, pending: 2)],
      signups: [_signup('1', 'Ana Souza', known: true), _signup('2', 'Bruno Lima')],
    );
    await _open(tester, backend, body: () async {
      expect(find.text('Ana Souza'), findsOneWidget);
      expect(find.text('ALUNO CONHECIDO'), findsOneWidget);
      expect(find.text('Horários livres: Sáb manhã, Seg noite'), findsNWidgets(2));
      expect(find.text('2 inscritos · 8 vagas'), findsOneWidget);

      await tester.tap(find.text('ACEITAR').first);
      await tester.pumpAndSettle();

      final sent = backend.bodyOf('POST', '/signups/status');
      expect(sent['status'], 'accepted');
      expect(sent['ids'], ['1']);
      expect(find.textContaining('Já estão na turma da mentoria'), findsOneWidget);
    });
  });

  testWidgets('filtra os inscritos por situação', (tester) async {
    final backend = _Backend(
      forms: [_form(signups: 2, pending: 2)],
      signups: [_signup('1', 'Ana Souza'), _signup('2', 'Bruno Lima', status: 'rejected')],
    );
    await _open(tester, backend, body: () async {
      await tester.tap(find.text('Recusados'));
      await tester.pumpAndSettle();
      expect(find.text('Ana Souza'), findsNothing);
      expect(find.text('Bruno Lima'), findsOneWidget);
    });
  });

  testWidgets('copia o link público e o CSV dos inscritos', (tester) async {
    final copied = <String>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          copied.add((call.arguments as Map)['text'] as String);
        }
        return null;
      },
    );
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    final backend = _Backend(
      forms: [_form(signups: 1, pending: 1)],
      signups: [_signup('1', 'Ana Souza')],
    );
    await _open(tester, backend, body: () async {
      await tester.tap(find.byTooltip('Copiar link'));
      await tester.pumpAndSettle();
      expect(copied.last, 'https://app.exemplo.com/education/mentorship-signup/tokf1');

      await tester.tap(find.text('COPIAR CSV'));
      await tester.pumpAndSettle();
      expect(copied.last, contains('Matrícula;Nome'));
    });
  });
}

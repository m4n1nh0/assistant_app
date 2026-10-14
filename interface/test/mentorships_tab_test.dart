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
  int activities = 0,
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
      'activities': activities,
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
  List<Map<String, dynamic>> activities = [];
  List<Map<String, dynamic>> rows = [];
  List<Map<String, dynamic>> risk = [];

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
    if (path.endsWith('/activities')) {
      if (request.method == 'POST') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final created = {
          'id': 'a${activities.length + 1}',
          'title': body['title'],
          'instructions': body['instructions'],
          'due_at': body['due_at'],
          'remind': body['remind'],
          'delivered': 0,
          'expected': 2,
        };
        activities = [...activities, created];
        return json(created);
      }
      return json({'path': '/education/mentorship-deliver/tokf1', 'activities': activities});
    }
    if (path.endsWith('/deliveries')) return json({'activities': activities, 'rows': rows});
    if (path.endsWith('/at-risk')) return json({'misses': 2, 'students': risk});
    final detail = RegExp(r'/deliveries/(\w+)$').firstMatch(path);
    if (detail != null) {
      return json({
        'id': detail.group(1),
        'text': 'https://github.com/aluno/projeto',
        'filename': '',
        'file_size': 0,
        'late': false,
        'delivered_at': '2026-10-14T12:00:00',
      });
    }
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
  Duration pollEvery = Duration.zero,
  required Future<void> Function() body,
}) async {
  tester.view.physicalSize = const Size(1600, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: MentorshipsTab(baseUrl: 'https://app.exemplo.com', pollEvery: pollEvery)),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

Map<String, dynamic> _activity(String id, String title, {int delivered = 1, String? due}) => {
      'id': id,
      'title': title,
      'instructions': 'Faça isto',
      'due_at': due ?? '2026-10-20T23:59:00',
      'remind': true,
      'delivered': delivered,
      'expected': 2,
    };

Map<String, dynamic> _row(String id, String name, List<String> statuses) => {
      'signup_id': id,
      'name': name,
      'enrollment': '2024000$id',
      'cells': [
        for (var i = 0; i < statuses.length; i++)
          {
            'activity_id': 'a${i + 1}',
            'status': statuses[i],
            'delivery_id': statuses[i] == 'delivered' || statuses[i] == 'late' ? 'd$id$i' : null,
            'text_preview': 'resposta',
          },
      ],
    };

/// Abre a mentoria pela lista.
Future<void> _openCard(WidgetTester tester, [String id = 'f1']) async {
  await tester.tap(find.byKey(Key('mentorship-card-$id')));
  await tester.pumpAndSettle();
}

/// Troca a seção da tela da mentoria (INSCRITOS, ATIVIDADES ou LINK E DADOS).
Future<void> _goTo(WidgetTester tester, String label) async {
  await tester.tap(find.textContaining(label));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('mostra as atividades, o link de entrega, a matriz e quem está faltando',
      (tester) async {
    final backend = _Backend(forms: [_form(signups: 2, accepted: 2)], signups: [
      _signup('1', 'Ana Souza', status: 'accepted'),
      _signup('2', 'Bruno Lima', status: 'accepted'),
    ])
      ..activities = [_activity('a1', 'Ler o capítulo 1'), _activity('a2', 'Projeto final', delivered: 0)]
      ..rows = [
        _row('1', 'Ana Souza', ['delivered', 'late']),
        _row('2', 'Bruno Lima', ['overdue', 'pending']),
      ]
      ..risk = [
        {'signup_id': '2', 'name': 'Bruno Lima', 'enrollment': '20240002', 'misses': 2},
      ];
    await _open(tester, backend, body: () async {
      await _openCard(tester);
      await _goTo(tester, 'ATIVIDADES');
      expect(find.text('ATIVIDADES E ENTREGAS'), findsOneWidget);
      expect(find.textContaining('/education/mentorship-deliver/tokf1'), findsOneWidget);
      expect(find.text('Ler o capítulo 1'), findsWidgets);
      expect(find.text('1/2 entregaram'), findsOneWidget);
      expect(find.text('QUEM ENTREGOU'), findsOneWidget);
      expect(find.byKey(const Key('cell-1-a1')), findsOneWidget);
      expect(find.text('2 sem entrega'), findsOneWidget);
    });
  });

  testWidgets('cria uma atividade com título e instruções', (tester) async {
    final backend = _Backend(forms: [_form(signups: 1, accepted: 1)], signups: [
      _signup('1', 'Ana Souza', status: 'accepted'),
    ]);
    await _open(tester, backend, body: () async {
      await _openCard(tester);
      await _goTo(tester, 'ATIVIDADES');
      await tester.tap(find.byKey(const Key('activity-new')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('activity-title')), 'Primeira tarefa');
      await tester.enterText(find.byKey(const Key('activity-instructions')), 'Leia e resuma');
      await tester.tap(find.byKey(const Key('activity-save')));
      await tester.pumpAndSettle();

      final sent = backend.bodyOf('POST', '/activities');
      expect(sent['title'], 'Primeira tarefa');
      expect(sent['instructions'], 'Leia e resuma');
      expect(sent.containsKey('due_at'), isFalse, reason: 'prazo é opcional');
      expect(find.text('Primeira tarefa'), findsWidgets);
    });
  });

  testWidgets('abrir uma entrega mostra o texto enviado pelo aluno', (tester) async {
    final backend = _Backend(forms: [_form(signups: 1, accepted: 1)], signups: [
      _signup('1', 'Ana Souza', status: 'accepted'),
    ])
      ..activities = [_activity('a1', 'Ler o capítulo 1')]
      ..rows = [_row('1', 'Ana Souza', ['delivered'])];
    await _open(tester, backend, body: () async {
      await _openCard(tester);
      await _goTo(tester, 'ATIVIDADES');
      await tester.tap(find.byKey(const Key('cell-1-a1')));
      await tester.pumpAndSettle();

      expect(find.text('https://github.com/aluno/projeto'), findsOneWidget);
      expect(find.textContaining('Entregue no prazo'), findsOneWidget);
    });
  });

  testWidgets('tirar da mentoria quem está faltando pede confirmação e só então remove',
      (tester) async {
    final backend = _Backend(forms: [_form(signups: 1, accepted: 1)], signups: [
      _signup('2', 'Bruno Lima', status: 'accepted'),
    ])
      ..activities = [_activity('a1', 'Ler o capítulo 1', delivered: 0)]
      ..rows = [_row('2', 'Bruno Lima', ['overdue'])]
      ..risk = [
        {'signup_id': '2', 'name': 'Bruno Lima', 'enrollment': '20240002', 'misses': 1},
      ];
    await _open(tester, backend, body: () async {
      await _openCard(tester);
      await _goTo(tester, 'ATIVIDADES');
      await tester.ensureVisible(find.byKey(const Key('risk-remove-2')));
      await tester.tap(find.byKey(const Key('risk-remove-2')));
      await tester.pumpAndSettle();
      expect(backend.called('POST', '/signups/status'), isFalse,
          reason: 'nada sai antes da confirmação');

      await tester.tap(find.text('Tirar'));
      await tester.pumpAndSettle();

      final sent = backend.bodyOf('POST', '/signups/status');
      expect(sent['status'], 'removed');
      expect(sent['ids'], ['2']);
    });
  });

  testWidgets('novas inscrições aparecem sozinhas, sem apertar nada', (tester) async {
    final backend = _Backend(
      forms: [_form(signups: 1, pending: 1)],
      signups: [_signup('1', 'Ana Souza')],
    );
    await _open(tester, backend, pollEvery: const Duration(seconds: 15), body: () async {
      await _openCard(tester);
      expect(find.text('Ana Souza'), findsOneWidget);
      expect(find.text('Bruno Lima'), findsNothing);

      backend.forms = [_form(signups: 2, pending: 2)];
      backend.signups = [_signup('1', 'Ana Souza'), _signup('2', 'Bruno Lima')];
      await tester.pump(const Duration(seconds: 16));
      await tester.pumpAndSettle();

      expect(find.text('Bruno Lima'), findsOneWidget);
      expect(find.text('INSCRITOS (2)'), findsOneWidget);
    });
    // Desmonta a tela para o timer periódico não ficar pendente.
    await tester.pumpWidget(const SizedBox());
  });

  test('horários livres aparecem legíveis', () {
    expect(availabilityText(['sab-manha', 'seg-noite']), 'Sáb manhã, Seg noite');
    expect(availabilityText(null), '');
  });

  testWidgets('com mais de uma mentoria, a lista mostra um cartão de cada com o que pede atenção',
      (tester) async {
    final backend = _Backend(forms: [
      _form(id: 'f1', title: 'Mentoria de dados', signups: 4, pending: 2, accepted: 2, activities: 3),
      _form(id: 'f2', title: 'Mentoria de IA', signups: 1, pending: 0, accepted: 1, state: 'closed'),
    ]);
    await _open(tester, backend, body: () async {
      expect(find.text('MENTORIAS (2)'), findsOneWidget);
      expect(find.byKey(const Key('mentorship-card-f1')), findsOneWidget);
      expect(find.byKey(const Key('mentorship-card-f2')), findsOneWidget);
      expect(find.text('2 aguardando você'), findsOneWidget);
      expect(find.text('3 atividades'), findsOneWidget);
      expect(find.text('FECHADO'), findsOneWidget);
      // Ainda na lista: nada de inscritos nem de atividades.
      expect(find.text('INSCRITOS'), findsNothing);
      expect(backend.called('GET', '/signups'), isFalse,
          reason: 'só carrega os inscritos da mentoria que for aberta');
    });
  });

  testWidgets('abre uma mentoria pelo cartão, vê só os dados dela e volta para a lista',
      (tester) async {
    final backend = _Backend(
      forms: [
        _form(id: 'f1', title: 'Mentoria de dados', signups: 1, pending: 1),
        _form(id: 'f2', title: 'Mentoria de IA'),
      ],
      signups: [_signup('1', 'Ana Souza')],
    );
    await _open(tester, backend, body: () async {
      await _openCard(tester, 'f2');

      expect(find.text('MENTORIA DE IA'), findsOneWidget);
      expect(find.byKey(const Key('mentorship-sections')), findsOneWidget);
      expect(backend.requests.any((r) => r.url.path.contains('/f2/signups')), isTrue);
      expect(find.text('Mentoria de dados'), findsNothing,
          reason: 'a outra mentoria some da tela');

      await tester.tap(find.byKey(const Key('mentorship-back')));
      await tester.pumpAndSettle();

      expect(find.text('MENTORIAS (2)'), findsOneWidget);
      expect(find.byKey(const Key('mentorship-card-f1')), findsOneWidget);
    });
  });

  testWidgets('a tela da mentoria separa inscritos, atividades e link em seções',
      (tester) async {
    final backend = _Backend(
      forms: [_form(signups: 1, pending: 1, activities: 2)],
      signups: [_signup('1', 'Ana Souza')],
    );
    await _open(tester, backend, body: () async {
      await _openCard(tester);

      expect(find.text('INSCRITOS (1)'), findsOneWidget);
      expect(find.text('ATIVIDADES (2)'), findsOneWidget);
      expect(find.text('Ana Souza'), findsOneWidget);
      expect(find.text('LINK E DADOS'), findsOneWidget, reason: 'só o rótulo da seção');
      expect(find.text('ATIVIDADES E ENTREGAS'), findsNothing);

      await _goTo(tester, 'ATIVIDADES');
      expect(find.text('ATIVIDADES E ENTREGAS'), findsOneWidget);
      expect(find.text('Ana Souza'), findsNothing);

      await _goTo(tester, 'LINK E DADOS');
      expect(find.textContaining('/education/mentorship-signup/tokf1'), findsOneWidget);
      expect(find.text('FECHAR INSCRIÇÕES'), findsOneWidget);
    });
  });

  testWidgets('criar a mentoria já abre a tela dela na seção do link', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('mentorship-new')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('mentorship-title')), 'Nova mentoria');
      await tester.tap(find.byKey(const Key('mentorship-create')));
      await tester.pumpAndSettle();

      expect(find.text('NOVA MENTORIA'), findsWidgets);
      expect(find.byKey(const Key('mentorship-back')), findsOneWidget);
      expect(find.textContaining('/education/mentorship-signup/toknovo'), findsOneWidget);
    });
  });

  testWidgets('sem formulário, orienta a criar o primeiro', (tester) async {
    await _open(tester, _Backend(), body: () async {
      expect(find.textContaining('Nenhuma mentoria ainda'), findsOneWidget);
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
      await _openCard(tester);
      expect(find.text('Ana Souza'), findsOneWidget);
      expect(find.text('ALUNO CONHECIDO'), findsOneWidget);
      expect(find.text('Horários livres: Sáb manhã, Seg noite'), findsNWidgets(2));
      expect(find.text('INSCRITOS (2)'), findsOneWidget);

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
      await _openCard(tester);
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
      await _openCard(tester);
      await _goTo(tester, 'LINK E DADOS');
      await tester.tap(find.byTooltip('Copiar link'));
      await tester.pumpAndSettle();
      expect(copied.last, 'https://app.exemplo.com/education/mentorship-signup/tokf1');

      await _goTo(tester, 'INSCRITOS');
      await tester.tap(find.text('COPIAR CSV'));
      await tester.pumpAndSettle();
      expect(copied.last, contains('Matrícula;Nome'));
    });
  });
}

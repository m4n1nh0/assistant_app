import 'dart:convert';

import 'package:assistant_app/models/availability.dart';
import 'package:assistant_app/widgets/availability_tab.dart';
import 'package:assistant_app/widgets/meeting_plan_panel.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

AvailabilityOccurrence _occ(String date, String start, String end, {bool blocked = false}) =>
    AvailabilityOccurrence(
      date: date,
      weekday: DateTime.parse(date).weekday - 1,
      blocked: blocked,
      startTime: blocked ? '' : start,
      endTime: blocked ? '' : end,
    );

BusyEvent _event(String title, DateTime start, DateTime end) =>
    BusyEvent(title: title, start: start, end: end);

Map<String, dynamic> _slotJson(String id, int weekday, String start, String end,
        {String mode = 'ambos', String audience = 'todos', bool active = true, String location = ''}) =>
    {
      'id': id,
      'weekday': weekday,
      'weekday_name': weekdayNames[weekday],
      'start_time': start,
      'end_time': end,
      'mode': mode,
      'location': location,
      'audience': audience,
      'note': '',
      'active': active,
    };

Map<String, dynamic> _occJson(String date, int weekday, String start, String end,
        {bool blocked = false, String note = ''}) =>
    {
      'date': date,
      'weekday': weekday,
      'blocked': blocked,
      'start_time': start,
      'end_time': end,
      'mode': blocked ? '' : 'online',
      'location': '',
      'audience': 'todos',
      'note': note,
      'source': blocked ? 'blocked' : 'weekly',
    };

class _Backend {
  List<Map<String, dynamic>> slots;
  List<Map<String, dynamic>> exceptions;
  List<Map<String, dynamic>> occurrences;
  final requests = <http.Request>[];
  int? failSlotStatus;

  _Backend({
    List<Map<String, dynamic>>? slots,
    List<Map<String, dynamic>>? exceptions,
    List<Map<String, dynamic>>? occurrences,
  })  : slots = slots ?? [],
        exceptions = exceptions ?? [],
        occurrences = occurrences ?? [];

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);

    if (path.endsWith('/availability/preview')) {
      return json({'start': '2026-10-15', 'days': 28, 'occurrences': occurrences});
    }
    if (path.endsWith('/availability/slots') && request.method == 'POST') {
      if (failSlotStatus != null) {
        return http.Response('{"detail":"O fim precisa ser depois do início."}', failSlotStatus!);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final created = _slotJson('n${slots.length}', body['weekday'] as int,
          body['start_time'] as String, body['end_time'] as String,
          mode: body['mode'] as String, audience: body['audience'] as String,
          location: body['location'] as String);
      slots = [...slots, created];
      return json(created);
    }
    final slot = RegExp(r'/availability/slots/(\w+)$').firstMatch(path);
    if (slot != null && request.method == 'PATCH') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      slots = [for (final s in slots) s['id'] == slot.group(1) ? {...s, ...body} : s];
      return json(slots.firstWhere((s) => s['id'] == slot.group(1)));
    }
    if (slot != null && request.method == 'DELETE') {
      slots = [for (final s in slots) if (s['id'] != slot.group(1)) s];
      return json({'ok': true});
    }
    if (path.endsWith('/availability/exceptions') && request.method == 'POST') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final created = {'id': 'e${exceptions.length}', 'start_time': '', 'end_time': '', 'mode': 'ambos', 'location': '', 'audience': 'todos', ...body};
      exceptions = [...exceptions, created];
      return json(created);
    }
    final exception = RegExp(r'/availability/exceptions/(\w+)$').firstMatch(path);
    if (exception != null && request.method == 'DELETE') {
      exceptions = [for (final e in exceptions) if (e['id'] != exception.group(1)) e];
      return json({'ok': true});
    }
    if (path.endsWith('/education/availability')) {
      return json({'slots': slots, 'exceptions': exceptions});
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
  BusyEventsLoader? events,
  required Future<void> Function() body,
}) async {
  tester.view.physicalSize = const Size(1600, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AvailabilityTab(loadEvents: events ?? (_, __) async => const [])),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

void main() {
  group('choque com o calendário', () {
    final atendimento = _occ('2026-10-15', '19:00', '21:00');

    test('evento que cai dentro do atendimento conflita', () {
      final conflitos = findConflicts([atendimento], [
        _event('Reunião de pais', DateTime(2026, 10, 15, 20), DateTime(2026, 10, 15, 21)),
      ]);

      expect(conflitos, hasLength(1));
      expect(conflitos.single.event.title, 'Reunião de pais');
    });

    test('evento que só encosta no começo ou no fim não conflita', () {
      final conflitos = findConflicts([atendimento], [
        _event('Antes', DateTime(2026, 10, 15, 18), DateTime(2026, 10, 15, 19)),
        _event('Depois', DateTime(2026, 10, 15, 21), DateTime(2026, 10, 15, 22)),
        _event('Outro dia', DateTime(2026, 10, 16, 19), DateTime(2026, 10, 16, 20)),
      ]);

      expect(conflitos, isEmpty);
    });

    test('evento que atravessa o atendimento inteiro conflita', () {
      expect(
        findConflicts([atendimento], [
          _event('Dia todo', DateTime(2026, 10, 15, 8), DateTime(2026, 10, 15, 23)),
        ]),
        hasLength(1),
      );
    });

    test('dia bloqueado não tem o que conflitar', () {
      expect(
        findConflicts([_occ('2026-10-15', '', '', blocked: true)], [
          _event('Viagem', DateTime(2026, 10, 15, 8), DateTime(2026, 10, 15, 23)),
        ]),
        isEmpty,
      );
    });
  });

  group('aba de atendimento', () {
    testWidgets('sem faixas, orienta a criar a primeira', (tester) async {
      await _open(tester, _Backend(), body: () async {
        expect(find.textContaining('Nenhuma faixa ainda'), findsOneWidget);
        expect(find.textContaining('Nada publicado'), findsOneWidget);
      });
    });

    testWidgets('lista as faixas agrupadas por dia da semana, com modalidade e público',
        (tester) async {
      final backend = _Backend(slots: [
        _slotJson('s1', 3, '19:00', '21:00', mode: 'online', location: 'https://meet.exemplo.com/x'),
        _slotJson('s2', 5, '09:00', '11:00', mode: 'presencial', audience: 'mentoria', location: 'Sala 12'),
      ]);
      await _open(tester, backend, body: () async {
        expect(find.text('Quinta'), findsOneWidget);
        expect(find.text('Sábado'), findsOneWidget);
        expect(find.text('19:00 às 21:00'), findsOneWidget);
        expect(find.text('Online'), findsOneWidget);
        expect(find.text('Só mentoria'), findsOneWidget);
        expect(find.text('Sala 12'), findsOneWidget);
        expect(find.text('Segunda'), findsNothing, reason: 'dia sem faixa não aparece');
      });
    });

    testWidgets('cria uma faixa com dia, horário, modalidade e local', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const Key('avail-new-slot')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('slot-start')), '19:00');
        await tester.enterText(find.byKey(const Key('slot-end')), '21:00');
        await tester.enterText(find.byKey(const Key('slot-location')), 'Sala 3');
        await tester.tap(find.byKey(const Key('slot-save')));
        await tester.pumpAndSettle();

        final sent = backend.bodyOf('POST', '/availability/slots');
        expect(sent['weekday'], 3);
        expect(sent['start_time'], '19:00');
        expect(sent['end_time'], '21:00');
        expect(sent['location'], 'Sala 3');
        expect(sent['mode'], 'ambos');
        expect(sent['audience'], 'todos');
        expect(find.text('19:00 às 21:00'), findsOneWidget);
      });
    });

    testWidgets('horário inválido mostra o erro do servidor e não cria a faixa',
        (tester) async {
      final backend = _Backend()..failSlotStatus = 400;
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const Key('avail-new-slot')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('slot-start')), '21:00');
        await tester.enterText(find.byKey(const Key('slot-end')), '19:00');
        await tester.tap(find.byKey(const Key('slot-save')));
        await tester.pumpAndSettle();

        expect(find.textContaining('O fim precisa ser depois do início'), findsOneWidget);
        expect(find.textContaining('Nenhuma faixa ainda'), findsOneWidget);
      });
    });

    testWidgets('desligar uma faixa grava na hora e a marca como desligada', (tester) async {
      final backend = _Backend(slots: [_slotJson('s1', 3, '19:00', '21:00')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const Key('slot-active-s1')));
        await tester.pumpAndSettle();

        expect(backend.bodyOf('PATCH', '/slots/s1'), {'active': false});
        expect(find.text('DESLIGADA'), findsOneWidget);
      });
    });

    testWidgets('apagar uma faixa', (tester) async {
      final backend = _Backend(slots: [_slotJson('s1', 3, '19:00', '21:00')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byTooltip('Apagar'));
        await tester.pumpAndSettle();

        expect(backend.called('DELETE', '/slots/s1'), isTrue);
        expect(find.textContaining('Nenhuma faixa ainda'), findsOneWidget);
      });
    });

    testWidgets('bloquear um dia pede a data e guarda o motivo', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const Key('avail-new-exception')));
        await tester.pumpAndSettle();

        // Sem escolher a data, nada é enviado.
        await tester.tap(find.byKey(const Key('exc-save')));
        await tester.pumpAndSettle();
        expect(backend.called('POST', '/availability/exceptions'), isFalse);
        expect(find.text('Escolha a data.'), findsOneWidget);

        await tester.tap(find.byKey(const Key('avail-new-exception')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('exc-day')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('OK'));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('exc-note')), 'Viagem');
        await tester.tap(find.byKey(const Key('exc-save')));
        await tester.pumpAndSettle();

        final sent = backend.bodyOf('POST', '/availability/exceptions');
        expect(sent['kind'], 'blocked');
        expect(sent['note'], 'Viagem');
        expect(sent['day'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
        expect(sent.containsKey('start_time'), isFalse);
        expect(find.text('NÃO ATENDO'), findsOneWidget);
      });
    });

    testWidgets('a prévia muda o público e pede ao servidor só o que o aluno veria',
        (tester) async {
      final backend = _Backend(occurrences: [_occJson('2026-10-15', 3, '19:00', '21:00')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.text('Aluno de mentoria'));
        await tester.pumpAndSettle();

        final previews = backend.requests.where((r) => r.url.path.endsWith('/preview'));
        expect(previews.last.url.queryParameters['audience'], 'mentoria');
        expect(previews.first.url.queryParameters.containsKey('audience'), isFalse);
      });
    });

    testWidgets('mostra o choque com o calendário e o nome do evento', (tester) async {
      final backend = _Backend(occurrences: [
        _occJson('2026-10-15', 3, '19:00', '21:00'),
        _occJson('2026-10-22', 3, '19:00', '21:00'),
      ]);
      await _open(
        tester,
        backend,
        events: (_, __) async => [
          _event('Banca de TCC', DateTime(2026, 10, 15, 19, 30), DateTime(2026, 10, 15, 20, 30)),
        ],
        body: () async {
          expect(find.byKey(const Key('avail-conflicts')), findsOneWidget);
          expect(find.text('1 choque(s) com o seu calendário nestes dias.'), findsOneWidget);
          expect(find.textContaining('Choca com: Banca de TCC'), findsOneWidget);
        },
      );
    });

    testWidgets('sem choques, diz que conferiu', (tester) async {
      final backend = _Backend(occurrences: [_occJson('2026-10-15', 3, '19:00', '21:00')]);
      await _open(tester, backend, body: () async {
        expect(find.textContaining('Nenhum choque com o seu calendário'), findsOneWidget);
      });
    });

    testWidgets('calendário indisponível não finge que não há choque', (tester) async {
      final backend = _Backend(occurrences: [_occJson('2026-10-15', 3, '19:00', '21:00')]);
      await _open(
        tester,
        backend,
        events: (_, __) async => throw Exception('sem conta'),
        body: () async {
          expect(find.textContaining('Não consegui ler o seu calendário'), findsOneWidget);
          expect(find.textContaining('Nenhum choque'), findsNothing);
        },
      );
    });

    testWidgets('dia bloqueado aparece como sem atendimento, com o motivo', (tester) async {
      final backend = _Backend(occurrences: [
        _occJson('2026-10-15', 3, '', '', blocked: true, note: 'Viagem'),
      ]);
      await _open(tester, backend, body: () async {
        expect(find.text('Sem atendimento · Viagem'), findsOneWidget);
      });
    });
  });

  group('plano de encontros', () {
    Future<void> show(WidgetTester tester, Map<String, dynamic> plan) async {
      final client = MockClient((request) async => http.Response(jsonEncode(plan), 200));
      await http.runWithClient(() async {
        await tester.pumpWidget(MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: MeetingPlanPanel(formId: 'f1', service: education, accepted: 3),
            ),
          ),
        ));
        await tester.pumpAndSettle();
      }, () => client);
    }

    Map<String, dynamic> option(String id, String day, int weekday, int count, List<String> names) => {
          'slot_id': id,
          'weekday': weekday,
          'weekday_name': day,
          'start_time': '19:00',
          'end_time': '21:00',
          'mode': 'online',
          'location': '',
          'count': count,
          'names': names,
        };

    testWidgets('destaca a melhor opção e lista quem não consegue nenhuma', (tester) async {
      await show(tester, {
        'accepted': 3,
        'with_availability': 3,
        'has_slots': true,
        'options': [
          option('a', 'Quinta', 3, 2, ['Ana', 'Bia']),
          option('b', 'Sábado', 5, 1, ['Caio']),
        ],
        'uncovered': ['Davi'],
      });

      expect(find.text('MELHOR OPÇÃO'), findsOneWidget);
      expect(find.byKey(const Key('plan-count-a')), findsOneWidget);
      expect(find.text('Quinta 19:00 às 21:00'), findsOneWidget);
      expect(find.text('Conseguem: Ana, Bia'), findsOneWidget);
      expect(find.text('Sem nenhuma das suas faixas: Davi.'), findsOneWidget);
      expect(find.text('3 de 3 aceitos informaram horários livres.'), findsOneWidget);
    });

    testWidgets('sem faixa para mentoria, manda cadastrar a agenda', (tester) async {
      await show(tester, {
        'accepted': 2, 'with_availability': 2, 'has_slots': false,
        'options': <Object>[], 'uncovered': ['Ana', 'Bia'],
      });

      expect(find.textContaining('Cadastre em Atendimento'), findsOneWidget);
      expect(find.text('MELHOR OPÇÃO'), findsNothing);
    });

    testWidgets('sem aceitos, explica o que falta', (tester) async {
      await show(tester, {
        'accepted': 0, 'with_availability': 0, 'has_slots': true,
        'options': <Object>[], 'uncovered': <Object>[],
      });

      expect(find.textContaining('Ainda não há alunos aceitos'), findsOneWidget);
    });

    testWidgets('opção que ninguém consegue não é marcada como melhor', (tester) async {
      await show(tester, {
        'accepted': 1, 'with_availability': 1, 'has_slots': true,
        'options': [option('a', 'Quinta', 3, 0, <String>[])],
        'uncovered': ['Ana'],
      });

      expect(find.text('MELHOR OPÇÃO'), findsNothing);
    });
  });
}

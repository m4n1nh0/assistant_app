import 'dart:convert';

import 'package:assistant_app/models/group_draw.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/group_draw_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _entry(
  String id,
  String name, {
  int? position,
  int? day,
  String status = 'pendente',
  String representative = '',
  int round = 0,
}) =>
    {
      'id': id,
      'group_id': 'g-$id',
      'group_name': name,
      'position': position,
      'day': day,
      'status': status,
      'representative_member_id': representative.isEmpty ? null : 'm-$id',
      'representative_name': representative,
      'representative_round': round,
      'drawn_at': null,
      'presented_at': null,
    };

Map<String, dynamic> _draw(
  List<Map<String, dynamic>> entries, {
  String mode = 'fila',
  int? perDay,
  String id = 'sorteio-1',
}) {
  final sorteados = entries.where((e) => e['position'] != null).length;
  return {
    'id': id,
    'discipline_id': 'd1',
    'discipline': 'ARA0040 - BANCO DE DADOS',
    'semester': '2026.2',
    'title': 'Ordem de apresentacao',
    'mode': mode,
    'seed': 'abc123',
    'algorithm': 'sha256-v1',
    'per_day': perDay,
    'step': sorteados,
    'total': entries.length,
    'remaining': entries.length - sorteados,
    'verified': true,
    'created_at': '2026-10-04T12:00:00',
    if (entries.isNotEmpty) 'entries': entries,
  };
}

const _discipline = Discipline(
  id: 'd1',
  code: 'ARA0040',
  name: 'BANCO DE DADOS',
  label: 'ARA0040 - BANCO DE DADOS',
  semester: '2026.2',
);

void main() {
  group('GroupDraw', () {
    final draw = GroupDraw.fromJson(_draw([
      _entry('a', 'Grupo 3', position: 1, day: 1, status: 'apresentou'),
      _entry('b', 'Grupo 1', position: 2, day: 1),
      _entry('c', 'Grupo 4', position: 3, day: 2),
      _entry('d', 'Grupo 2', position: 4, day: 2, status: 'ausente'),
    ], perDay: 2));

    test('current is the first group that has not presented yet', () {
      expect(draw.current?.groupName, 'Grupo 1');
      expect(draw.next?.groupName, 'Grupo 4');
    });

    test('a group marked as presenting takes precedence', () {
      final onStage = GroupDraw.fromJson(_draw([
        _entry('a', 'Grupo 3', position: 1, day: 1),
        _entry('b', 'Grupo 1', position: 2, day: 1, status: 'apresentando'),
      ]));
      expect(onStage.current?.groupName, 'Grupo 1');
      expect(onStage.next, isNull);
    });

    test('the queue is split by day, in order', () {
      expect(draw.byDay.keys, [1, 2]);
      expect(draw.byDay[2]!.map((e) => e.groupName), ['Grupo 4', 'Grupo 2']);
    });

    test('counts by status and the finished flag', () {
      expect(draw.count('apresentou'), 1);
      expect(draw.count('ausente'), 1);
      expect(draw.finished, isTrue);
      expect(draw.canDrawNext, isFalse);
    });

    test('one-by-one draw keeps undrawn groups apart and can draw next', () {
      final partial = GroupDraw.fromJson(_draw([
        _entry('a', 'Grupo 3', position: 1, day: 1),
        _entry('b', 'Grupo 1'),
        _entry('c', 'Grupo 2'),
      ], mode: 'avulso'));
      expect(partial.drawn.map((e) => e.groupName), ['Grupo 3']);
      expect(partial.notDrawn.length, 2);
      expect(partial.canDrawNext, isTrue);
      expect(partial.remaining, 2);
    });

    test('nobody is on stage before anything is drawn', () {
      final empty = GroupDraw.fromJson(
        _draw([_entry('a', 'Grupo 1')], mode: 'avulso'),
      );
      expect(empty.current, isNull);
      expect(empty.next, isNull);
    });
  });

  group('GroupDrawPanel', () {
    testWidgets('creates a draw and marks a group as presented', (tester) async {
      tester.view.physicalSize = const Size(1400, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);

      Map<String, dynamic>? created;
      var entries = <Map<String, dynamic>>[];

      final client = MockClient((request) async {
        final path = request.url.path;
        if (request.method == 'GET' && path.endsWith('/group-draws')) {
          return http.Response('[]', 200);
        }
        if (request.method == 'POST' && path.endsWith('/group-draws')) {
          created = jsonDecode(request.body) as Map<String, dynamic>;
          entries = [
            _entry('a', 'Grupo 3', position: 1, day: 1),
            _entry('b', 'Grupo 1', position: 2, day: 1),
          ];
          return http.Response(jsonEncode(_draw(entries)), 200);
        }
        if (request.method == 'PATCH') {
          entries = [
            {...entries[0], 'status': 'apresentou'},
            entries[1],
          ];
          return http.Response(jsonEncode(_draw(entries)), 200);
        }
        return http.Response('{"detail":"inesperado $path"}', 404);
      });

      await http.runWithClient(() async {
        await tester.pumpWidget(const MaterialApp(
          home: Scaffold(body: GroupDrawPanel(discipline: _discipline)),
        ));
        await tester.pumpAndSettle();

        expect(find.text('Ordem completa'), findsOneWidget);
        await tester.enterText(
          find.widgetWithText(TextField, 'Apresentações por dia'),
          '2',
        );
        await tester.tap(find.text('SORTEAR'));
        await tester.pumpAndSettle();

        expect(created, {
          'discipline_id': 'd1',
          'semester': '2026.2',
          'title': '',
          'mode': 'fila',
          'per_day': 2,
        });
        expect(find.text('Grupo 3'), findsOneWidget);
        expect(find.text('Grupo 1'), findsOneWidget);
        expect(find.textContaining('Conferido · semente abc123'), findsOneWidget);

        await tester.tap(find.byTooltip('Apresentou').first);
        await tester.pumpAndSettle();

        expect(find.text('APRESENTOU'), findsOneWidget);
        expect(find.textContaining('1 apresentaram'), findsOneWidget);
      }, () => client);
    });

    testWidgets('one-by-one mode draws the next group on request',
        (tester) async {
      tester.view.physicalSize = const Size(1400, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);

      var drawn = <Map<String, dynamic>>[
        _entry('a', 'Grupo 3'),
        _entry('b', 'Grupo 1'),
      ];
      final client = MockClient((request) async {
        final path = request.url.path;
        if (request.method == 'GET' && path.endsWith('/group-draws')) {
          return http.Response(
            jsonEncode([_draw([], mode: 'avulso')..['remaining'] = 2]),
            200,
          );
        }
        if (request.method == 'GET' && path.endsWith('/group-draws/sorteio-1')) {
          return http.Response(
            jsonEncode(_draw(drawn, mode: 'avulso')),
            200,
          );
        }
        if (request.method == 'POST' && path.endsWith('/next')) {
          drawn = [
            _entry('a', 'Grupo 3', position: 1, day: 1),
            _entry('b', 'Grupo 1'),
          ];
          return http.Response(jsonEncode(_draw(drawn, mode: 'avulso')), 200);
        }
        return http.Response('{"detail":"inesperado $path"}', 404);
      });

      await http.runWithClient(() async {
        await tester.pumpWidget(const MaterialApp(
          home: Scaffold(body: GroupDrawPanel(discipline: _discipline)),
        ));
        await tester.pumpAndSettle();

        expect(find.text('Nenhum grupo sorteado ainda.'), findsOneWidget);
        await tester.tap(find.textContaining('SORTEAR PRÓXIMO GRUPO'));
        // A animação dura 1,8 s: o resultado só aparece depois dela.
        await tester.pump(const Duration(milliseconds: 100));
        await tester.pumpAndSettle(const Duration(seconds: 3));

        expect(find.text('Grupo 3'), findsOneWidget);
        expect(find.text('Nenhum grupo sorteado ainda.'), findsNothing);
      }, () => client);
    });

    testWidgets('shows the server error instead of failing silently',
        (tester) async {
      final client = MockClient((request) async {
        if (request.method == 'GET') return http.Response('[]', 200);
        return http.Response(
          jsonEncode({'detail': 'Essa disciplina nao tem grupos de projeto para sortear'}),
          422,
        );
      });

      await http.runWithClient(() async {
        await tester.pumpWidget(const MaterialApp(
          home: Scaffold(body: GroupDrawPanel(discipline: _discipline)),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.text('SORTEAR'));
        await tester.pumpAndSettle();

        expect(
          find.textContaining('nao tem grupos de projeto'),
          findsOneWidget,
        );
      }, () => client);
    });
  });
}

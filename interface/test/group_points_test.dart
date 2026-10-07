import 'dart:convert';

import 'package:assistant_app/models/group_points.dart';
import 'package:assistant_app/widgets/group_points_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _entry(
  String id,
  double points, {
  String reason = '',
  bool credit = false,
  int credited = 0,
  String date = '2026-10-06T21:00:00',
}) =>
    {
      'id': id,
      'group_id': 'g1',
      'points': points,
      'reason': reason,
      'entry_date': date,
      'credit_members': credit,
      'credited_count': credited,
      'created_at': date,
    };

Map<String, dynamic> _group({int linked = 2, int total = 3}) => {
      'id': 'g1',
      'name': 'GRUPO 1',
      'members': [
        for (var i = 0; i < total; i++)
          {
            'id': 'm$i',
            'name': 'Aluno $i',
            'student_id': i < linked ? 's$i' : null,
            'position': i,
          }
      ],
    };

class _Backend {
  final List<Map<String, dynamic>> entries;
  final requests = <http.Request>[];
  int? failStatus;
  String? message;

  _Backend([List<Map<String, dynamic>>? entries]) : entries = entries ?? [];

  double get total =>
      entries.fold(0.0, (sum, item) => sum + (item['points'] as num).toDouble());

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);
    final body = request.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(request.body) as Map<String, dynamic>;
    if (failStatus != null && request.method != 'GET') {
      return http.Response(
          '{"detail":"Informe uma quantidade de pontos diferente de zero"}',
          failStatus!);
    }
    if (request.method == 'GET' && path.endsWith('/points')) {
      return json({
        'group_id': 'g1',
        'group_name': 'GRUPO 1',
        'total': total,
        'entries': entries,
      });
    }
    if (request.method == 'POST' && path.endsWith('/points')) {
      final created = _entry(
        'novo${entries.length}',
        (body['points'] as num).toDouble(),
        reason: '${body['reason']}',
        credit: body['credit_members'] == true,
        credited: body['credit_members'] == true ? 2 : 0,
      );
      entries.insert(0, created);
      return json({
        ...created,
        'group_total': total,
        'message': message ?? '',
      });
    }
    final match = RegExp(r'/points/(\w+)$').firstMatch(path);
    if (match != null && request.method == 'PATCH') {
      final index = entries.indexWhere((e) => e['id'] == match.group(1));
      entries[index] = {
        ...entries[index],
        if (body.containsKey('points')) 'points': body['points'],
        if (body.containsKey('reason')) 'reason': body['reason'],
        if (body.containsKey('credit_members'))
          'credit_members': body['credit_members'],
      };
      return json({...entries[index], 'group_total': total, 'message': ''});
    }
    if (match != null && request.method == 'DELETE') {
      entries.removeWhere((e) => e['id'] == match.group(1));
      return json({'deleted': match.group(1), 'group_total': total});
    }
    return http.Response('{"detail":"inesperado $path"}', 404);
  }

  Map<String, dynamic> lastBody(String method) => jsonDecode(requests
      .lastWhere((r) => r.method == method && r.url.path.contains('/points'))
      .body) as Map<String, dynamic>;

  bool called(String method) => requests.any(
      (r) => r.method == method && r.url.path.contains('/points') && method != 'GET');
}

Future<void> _open(
  WidgetTester tester,
  _Backend backend, {
  Map<String, dynamic>? group,
  required Future<void> Function() body,
}) async {
  tester.view.physicalSize = const Size(1400, 2000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: GroupPointsPanel(group: group ?? _group())),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

Future<void> _lancar(WidgetTester tester, String points,
    {String reason = ''}) async {
  await tester.enterText(find.byKey(const ValueKey('campo-pontos')), points);
  if (reason.isNotEmpty) {
    await tester.enterText(find.byKey(const ValueKey('campo-motivo')), reason);
  }
  await tester.ensureVisible(find.byKey(const ValueKey('lancar')));
  await tester.tap(find.byKey(const ValueKey('lancar')));
  await tester.pumpAndSettle();
}

void main() {
  group('formatGroupPoints', () {
    test('soma, tira e zero', () {
      expect(formatGroupPoints(1.5), '+1,5');
      expect(formatGroupPoints(2), '+2');
      expect(formatGroupPoints(-0.5), '−0,5');
      expect(formatGroupPoints(0), '0');
      expect(formatGroupPoints(1.25), '+1,25');
    });

    test('sem sinal explícito', () {
      expect(formatGroupPoints(1.5, sign: false), '1,5');
      expect(formatGroupPoints(-1.5, sign: false), '−1,5');
    });

    test('ruído de ponto flutuante não aparece', () {
      expect(formatGroupPoints(0.1 + 0.2), '+0,3');
      expect(formatGroupPoints(2.3000000001), '+2,3');
    });
  });

  group('parseGroupPoints', () {
    test('aceita vírgula, ponto e os sinais', () {
      expect(parseGroupPoints('1,5'), 1.5);
      expect(parseGroupPoints('1.5'), 1.5);
      expect(parseGroupPoints('+2'), 2);
      expect(parseGroupPoints('-0,5'), -0.5);
      expect(parseGroupPoints('−1'), -1);
      expect(parseGroupPoints('  3 '), 3);
      expect(parseGroupPoints('- 1'), -1);
    });

    test('recusa vazio, texto, zero e acima do limite', () {
      for (final bad in ['', '  ', 'abc', '0', '0,0', '-0', '101', '-100,5', '1,2,3', 'NaN', 'Infinity']) {
        expect(parseGroupPoints(bad), isNull, reason: bad);
      }
      expect(parseGroupPoints('100'), 100);
      expect(parseGroupPoints('-100'), -100);
    });

    test('o que se mostra pode ser lido de volta', () {
      for (final value in [1.5, -0.5, 2.0, -3.25]) {
        expect(parseGroupPoints(formatGroupPoints(value)), value);
      }
    });
  });

  group('modelos', () {
    test('lançamento: leitura e rótulo do alcance', () {
      final so = GroupPointEntry.fromJson(_entry('a', 1.0, reason: 'x'));
      final credito = GroupPointEntry.fromJson(
          _entry('b', -0.5, credit: true, credited: 2));
      final um = GroupPointEntry.fromJson(_entry('c', 1, credit: true, credited: 1));

      expect(so.scopeLabel, 'só o grupo');
      expect(so.isSubtraction, isFalse);
      expect(credito.isSubtraction, isTrue);
      expect(credito.scopeLabel, 'creditado a 2 integrantes');
      expect(um.scopeLabel, 'creditado a 1 integrante');
      expect(so.entryDate, DateTime.parse('2026-10-06T21:00:00'));
    });

    test('histórico lê total e lançamentos', () {
      final history = GroupPointsHistory.fromJson({
        'group_id': 'g1',
        'group_name': 'GRUPO 1',
        'total': 2.5,
        'entries': [_entry('a', 3.0), _entry('b', -0.5)],
      });

      expect(history.total, 2.5);
      expect(history.entries.map((e) => e.id), ['a', 'b']);
      expect(const GroupPointsHistory(groupId: 'x').entries, isEmpty);
    });

    test('quantos integrantes podem receber o crédito', () {
      final counts = memberLinkCounts(_group(linked: 2, total: 3)['members'] as List);

      expect(counts.linked, 2);
      expect(counts.total, 3);
      expect(memberLinkCounts(const []).total, 0);
    });
  });

  group('janela de pontos do grupo', () {
    testWidgets('sem lançamentos, mostra o total zerado e o histórico vazio',
        (tester) async {
      await _open(tester, _Backend(), body: () async {
        expect(find.text('PONTOS · GRUPO 1'), findsOneWidget);
        expect(find.text('Total do grupo: 0 (0 lançamentos)'), findsOneWidget);
        expect(find.byKey(const ValueKey('historico-vazio')), findsOneWidget);
      });
    });

    testWidgets('mostra o histórico com valor, motivo, data e alcance',
        (tester) async {
      final backend = _Backend([
        _entry('a', 2.0, reason: 'Melhor apresentação', credit: true, credited: 2),
        _entry('b', -0.5, reason: 'Atraso na entrega'),
      ]);
      await _open(tester, backend, body: () async {
        expect(find.text('Total do grupo: +1,5 (2 lançamentos)'), findsOneWidget);
        // O "+2" também é um atalho do formulário: o valor do histórico tem chave.
        expect(tester.widget<Text>(find.byKey(const ValueKey('valor-a'))).data, '+2');
        expect(tester.widget<Text>(find.byKey(const ValueKey('valor-b'))).data, '−0,5');
        expect(find.text('Melhor apresentação'), findsOneWidget);
        expect(find.text('06/10/2026 · creditado a 2 integrantes'), findsOneWidget);
        expect(find.text('06/10/2026 · só o grupo'), findsOneWidget);
      });
    });

    testWidgets('lança pontos com vírgula e motivo, só para o grupo', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        await _lancar(tester, '1,5', reason: 'Melhor ideia');

        final body = backend.lastBody('POST');
        expect(body['points'], 1.5);
        expect(body['reason'], 'Melhor ideia');
        expect(body['credit_members'], false);
        expect(body.containsKey('entry_date'), isFalse);
        expect(find.text('Total do grupo: +1,5 (1 lançamento)'), findsOneWidget);
        expect(find.text('Pontos lançados.'), findsOneWidget);
        // O formulário volta ao começo.
        expect(
          tester
              .widget<TextField>(find.byKey(const ValueKey('campo-pontos')))
              .controller!
              .text,
          isEmpty,
        );
      });
    });

    testWidgets('os atalhos preenchem o valor', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('rapido-−0,5')));
        await tester.pump();
        await tester.ensureVisible(find.byKey(const ValueKey('lancar')));
        await tester.tap(find.byKey(const ValueKey('lancar')));
        await tester.pumpAndSettle();

        expect(backend.lastBody('POST')['points'], -0.5);
        expect(find.text('Total do grupo: −0,5 (1 lançamento)'), findsOneWidget);
      });
    });

    testWidgets('valor inválido não chega ao servidor e explica', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        for (final bad in ['', '0', 'abc', '150']) {
          await _lancar(tester, bad);
          expect(find.textContaining('Informe os pontos'), findsOneWidget,
              reason: bad);
        }
        expect(backend.called('POST'), isFalse);
      });
    });

    testWidgets('creditar aos integrantes: mostra quantos recebem e manda a opção',
        (tester) async {
      final backend = _Backend()
        ..message = 'Creditado a 2 integrante(s); 1 sem aluno vinculado ficaram de fora.';
      await _open(tester, backend, body: () async {
        expect(
          tester.widget<Text>(find.byKey(const ValueKey('resumo-creditar'))).data,
          allOf(contains('2 de 3 integrantes'), contains('Os outros ficam de fora')),
        );
        await tester.ensureVisible(find.byKey(const ValueKey('creditar-integrantes')));
        await tester.tap(find.byKey(const ValueKey('creditar-integrantes')));
        await tester.pump();
        await _lancar(tester, '1', reason: 'Melhor ideia');

        expect(backend.lastBody('POST')['credit_members'], true);
        expect(find.textContaining('Creditado a 2 integrante(s)'), findsOneWidget);
        expect(find.text('06/10/2026 · creditado a 2 integrantes'), findsOneWidget);
      });
    });

    testWidgets('sem integrante vinculado a opção de creditar fica desligada',
        (tester) async {
      final backend = _Backend();
      await _open(tester, backend, group: _group(linked: 0), body: () async {
        final opcao = tester.widget<SwitchListTile>(
            find.byKey(const ValueKey('creditar-integrantes')));
        expect(opcao.onChanged, isNull);
        expect(opcao.value, isFalse);
        expect(
          tester.widget<Text>(find.byKey(const ValueKey('resumo-creditar'))).data,
          contains('nada seria creditado'),
        );
      });
    });

    testWidgets('todos vinculados não fala dos que ficam de fora', (tester) async {
      await _open(tester, _Backend(), group: _group(linked: 3), body: () async {
        expect(
          tester.widget<Text>(find.byKey(const ValueKey('resumo-creditar'))).data,
          allOf(contains('3 de 3'), isNot(contains('ficam de fora'))),
        );
      });
    });

    testWidgets('corrige um lançamento: carrega os valores e salva a correção',
        (tester) async {
      final backend = _Backend([_entry('a', 1.0, reason: 'inicial')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('editar-a')));
        await tester.pump();

        expect(find.text('CORRIGIR LANÇAMENTO'), findsOneWidget);
        expect(find.text('SALVAR CORREÇÃO'), findsOneWidget);
        expect(
          tester.widget<TextField>(find.byKey(const ValueKey('campo-pontos'))).controller!.text,
          '1',
        );
        expect(
          tester.widget<TextField>(find.byKey(const ValueKey('campo-motivo'))).controller!.text,
          'inicial',
        );

        await _lancar(tester, '2,5', reason: 'corrigido');

        final body = backend.lastBody('PATCH');
        expect(body['points'], 2.5);
        expect(body['reason'], 'corrigido');
        expect(find.text('Lançamento corrigido.'), findsOneWidget);
        expect(find.text('Total do grupo: +2,5 (1 lançamento)'), findsOneWidget);
        expect(find.text('NOVO LANÇAMENTO'), findsOneWidget);
      });
    });

    testWidgets('corrigir um subtraído mantém o sinal na caixa', (tester) async {
      final backend = _Backend([_entry('a', -0.5, reason: 'atraso')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('editar-a')));
        await tester.pump();

        expect(
          tester.widget<TextField>(find.byKey(const ValueKey('campo-pontos'))).controller!.text,
          '-0,5',
        );
      });
    });

    testWidgets('cancelar a correção volta ao lançamento novo', (tester) async {
      final backend = _Backend([_entry('a', 1.0, reason: 'inicial')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('editar-a')));
        await tester.pump();
        await tester.ensureVisible(find.byKey(const ValueKey('cancelar-correcao')));
        await tester.tap(find.byKey(const ValueKey('cancelar-correcao')));
        await tester.pump();

        expect(find.text('NOVO LANÇAMENTO'), findsOneWidget);
        expect(
          tester.widget<TextField>(find.byKey(const ValueKey('campo-pontos'))).controller!.text,
          isEmpty,
        );
        expect(backend.called('PATCH'), isFalse);
      });
    });

    testWidgets('apaga com confirmação e avisa dos integrantes creditados',
        (tester) async {
      final backend = _Backend([
        _entry('a', 1.0, reason: 'fica'),
        _entry('b', 2.0, reason: 'sai', credit: true, credited: 2),
      ]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('apagar-b')));
        await tester.pumpAndSettle();
        expect(find.textContaining('também sai de 2 integrantes'), findsOneWidget);
        expect(backend.called('DELETE'), isFalse);

        await tester.tap(find.byKey(const ValueKey('confirmar-apagar')));
        await tester.pumpAndSettle();

        expect(backend.called('DELETE'), isTrue);
        expect(find.byKey(const ValueKey('lancamento-b')), findsNothing);
        expect(find.text('Total do grupo: +1 (1 lançamento)'), findsOneWidget);
        expect(find.text('Lançamento apagado.'), findsOneWidget);
      });
    });

    testWidgets('apagar um lançamento só do grupo não fala em integrantes',
        (tester) async {
      final backend = _Backend([_entry('a', 1.0, reason: 'x')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('apagar-a')));
        await tester.pumpAndSettle();

        expect(find.text('O total do grupo diminui.'), findsOneWidget);
      });
    });

    testWidgets('cancelar a confirmação não apaga', (tester) async {
      final backend = _Backend([_entry('a', 1.0, reason: 'x')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('apagar-a')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Cancelar'));
        await tester.pumpAndSettle();

        expect(backend.called('DELETE'), isFalse);
        expect(find.byKey(const ValueKey('lancamento-a')), findsOneWidget);
      });
    });

    testWidgets('apagar o lançamento que está sendo corrigido limpa o formulário',
        (tester) async {
      final backend = _Backend([_entry('a', 1.0, reason: 'x')]);
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('editar-a')));
        await tester.pump();
        await tester.tap(find.byKey(const ValueKey('apagar-a')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('confirmar-apagar')));
        await tester.pumpAndSettle();

        expect(find.text('NOVO LANÇAMENTO'), findsOneWidget);
      });
    });

    testWidgets('mostra o erro do servidor', (tester) async {
      final backend = _Backend()..failStatus = 422;
      await _open(tester, backend, body: () async {
        await _lancar(tester, '1');

        expect(find.textContaining('diferente de zero'), findsOneWidget);
        expect(find.text('Pontos lançados.'), findsNothing);
      });
    });

    testWidgets('total negativo aparece com o sinal de menos', (tester) async {
      final backend = _Backend([_entry('a', -2.0, reason: 'penalidade')]);
      await _open(tester, backend, body: () async {
        expect(find.text('Total do grupo: −2 (1 lançamento)'), findsOneWidget);
      });
    });
  });
}

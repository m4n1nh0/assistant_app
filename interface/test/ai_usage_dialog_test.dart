import 'dart:convert';

import 'package:assistant_app/models/ai_usage.dart';
import 'package:assistant_app/widgets/ai_usage_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _total({
  int calls = 12,
  int errors = 0,
  int unpriced = 0,
  int input = 120000,
  int output = 30000,
  double cost = 0.84,
}) =>
    {
      'calls': calls,
      'errors': errors,
      'unpriced_calls': unpriced,
      'input_tokens': input,
      'output_tokens': output,
      'cached_tokens': 0,
      'cost_usd': cost,
    };

Map<String, dynamic> _usage({
  String groupBy = 'provider',
  String scope = 'mine',
  int unpriced = 0,
  List<Map<String, dynamic>>? groups,
}) =>
    {
      'days': 30,
      'group_by': groupBy,
      'scope': scope,
      'estimated': true,
      'total': _total(unpriced: unpriced),
      'groups': groups ??
          [
            {'key': 'claude', 'label': 'claude', ..._total(calls: 9, cost: 0.80)},
            {'key': 'gpt', 'label': 'gpt', ..._total(calls: 3, input: 0, output: 0, cost: 0.04)},
          ],
    };

Map<String, dynamic> _price(String id, String provider, String model,
        {double input = 3, double output = 15, String source = 'litellm'}) =>
    {
      'id': id,
      'provider': provider,
      'model': model,
      'input_per_mtok': input,
      'output_per_mtok': output,
      'cached_input_per_mtok': null,
      'source': source,
    };

class _Backend {
  final requests = <http.Request>[];
  Map<String, dynamic> usage = _usage();
  List<Map<String, dynamic>> prices = [
    _price('p1', 'claude', 'claude-sonnet-4-5'),
    _price('p2', 'openrouter', 'meta-llama/llama:free', input: 0, output: 0, source: 'manual'),
  ];
  String syncError = '';

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body, [int status = 200]) =>
        http.Response(jsonEncode(body), status);
    if (path.endsWith('/observability/usage')) {
      return json({
        ...usage,
        'group_by': request.url.queryParameters['group_by'],
        'scope': request.url.queryParameters['scope'],
      });
    }
    if (path.endsWith('/prices/sync')) {
      if (syncError.isNotEmpty) return json({'detail': syncError}, 502);
      return json({'models_in_source': 286, 'added': 280, 'updated': 2, 'kept_manual': 4});
    }
    if (path.endsWith('/observability/prices') && request.method == 'PUT') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final saved = _price('novo', body['provider'] as String, body['model'] as String,
          input: (body['input_per_mtok'] as num).toDouble(),
          output: (body['output_per_mtok'] as num).toDouble(),
          source: 'manual');
      prices = [...prices, saved];
      return json(saved);
    }
    if (path.endsWith('/observability/prices') && request.method == 'GET') {
      return json({
        'providers': ['claude', 'gpt', 'openrouter'],
        'prices': prices,
      });
    }
    final delete = RegExp(r'/prices/(\w+)$').firstMatch(path);
    if (delete != null && request.method == 'DELETE') {
      prices = [
        for (final p in prices)
          if (p['id'] != delete.group(1)) p
      ];
      return json({'ok': true});
    }
    return http.Response('{"detail":"inesperado $path"}', 404);
  }

  http.Request last(String method, String suffix) =>
      requests.lastWhere((r) => r.method == method && r.url.path.endsWith(suffix));

  bool called(String method, String suffix) =>
      requests.any((r) => r.method == method && r.url.path.endsWith(suffix));
}

Future<void> _open(
  WidgetTester tester,
  _Backend backend, {
  bool admin = false,
  required Future<void> Function() body,
}) async {
  tester.view.physicalSize = const Size(1600, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AiUsageDialog(isAdmin: admin)),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

Future<void> _openPrices(WidgetTester tester) async {
  await tester.tap(find.text('PREÇOS'));
  await tester.pumpAndSettle();
}

void main() {
  group('formatação', () {
    test('dólar com a precisão que o valor pede', () {
      expect(formatUsd(0), 'US\$ 0,00');
      expect(formatUsd(0.0042), 'US\$ 0,0042');
      expect(formatUsd(0.84), 'US\$ 0,840');
      expect(formatUsd(12.5), 'US\$ 12,50');
    });

    test('inteiro com separador de milhar', () {
      expect(formatCount(0), '0');
      expect(formatCount(999), '999');
      expect(formatCount(1234567), '1.234.567');
    });
  });

  testWidgets('mostra o consumo da conta: chamadas, tokens e custo estimado', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, body: () async {
      expect(find.text('12'), findsOneWidget); // chamadas
      expect(find.text('150.000'), findsOneWidget); // 120 mil de entrada + 30 mil de saída
      expect(find.textContaining('120.000 entrada'), findsOneWidget);
      expect(find.byKey(const Key('usage-cost')), findsOneWidget);
      expect(find.text('claude'), findsOneWidget);
      expect(find.byKey(const Key('usage-unpriced')), findsNothing);
      expect(backend.last('GET', '/usage').url.queryParameters['scope'], 'mine');
    });
  });

  testWidgets('a tabela mostra as falhas de cada provedor', (tester) async {
    final backend = _Backend()
      ..usage = _usage(groups: [
        {'key': 'claude', 'label': 'claude', ..._total(calls: 9, errors: 7, input: 0, output: 0, cost: 0)},
        {'key': 'together', 'label': 'together', ..._total(calls: 5, errors: 0, cost: 0.027)},
      ]);
    await _open(tester, backend, body: () async {
      expect(find.text('FALHAS'), findsOneWidget);
      // claude: 9 chamadas, 7 falharam e nenhum token (falha nao traz token)
      expect(find.text('7'), findsOneWidget);
      expect(find.text('9'), findsOneWidget);
    });
  });

  testWidgets('avisa quando há chamadas sem preço, para o custo não enganar', (tester) async {
    final backend = _Backend()..usage = _usage(unpriced: 3);
    await _open(tester, backend, body: () async {
      expect(find.byKey(const Key('usage-unpriced')), findsOneWidget);
      expect(find.textContaining('3 chamada(s) ficaram sem preço'), findsOneWidget);
      expect(find.textContaining('Codex'), findsOneWidget);
    });
  });

  testWidgets('sem consumo, explica que só vale a partir de agora', (tester) async {
    final backend = _Backend()..usage = _usage(groups: const []);
    await _open(tester, backend, body: () async {
      expect(find.textContaining('Nenhum consumo registrado'), findsOneWidget);
    });
  });

  testWidgets('conta comum não vê a escolha de todos os clientes', (tester) async {
    await _open(tester, _Backend(), body: () async {
      expect(find.byKey(const Key('usage-scope')), findsNothing);
    });
  });

  testWidgets('administrador soma todos os clientes e passa a poder agrupar por cliente',
      (tester) async {
    final backend = _Backend();
    await _open(tester, backend, admin: true, body: () async {
      await tester.tap(find.text('TODOS OS CLIENTES'));
      await tester.pumpAndSettle();
      expect(backend.last('GET', '/usage').url.queryParameters['scope'], 'all');

      await tester.tap(find.byKey(const Key('usage-group')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Por cliente').last);
      await tester.pumpAndSettle();
      final request = backend.last('GET', '/usage');
      expect(request.url.queryParameters['group_by'], 'tenant');
      expect(request.url.queryParameters['scope'], 'all');
    });
  });

  testWidgets('voltar para a própria conta tira o agrupamento por cliente', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, admin: true, body: () async {
      await tester.tap(find.text('TODOS OS CLIENTES'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('usage-group')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Por cliente').last);
      await tester.pumpAndSettle();

      await tester.tap(find.text('MINHA CONTA'));
      await tester.pumpAndSettle();
      final request = backend.last('GET', '/usage');
      expect(request.url.queryParameters['scope'], 'mine');
      expect(request.url.queryParameters['group_by'], 'provider');
    });
  });

  testWidgets('trocar o período recarrega o consumo', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, body: () async {
      await tester.tap(find.byKey(const Key('usage-days')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Últimos 7 dias').last);
      await tester.pumpAndSettle();
      expect(backend.last('GET', '/usage').url.queryParameters['days'], '7');
    });
  });

  testWidgets('aba de preços lista a tabela e marca o gratuito e o digitado', (tester) async {
    await _open(tester, _Backend(), body: () async {
      await _openPrices(tester);
      expect(find.text('claude-sonnet-4-5'), findsOneWidget);
      expect(find.text('meta-llama/llama:free'), findsOneWidget);
      expect(find.text('GRÁTIS'), findsOneWidget);
      expect(find.text('DIGITADO'), findsOneWidget);
      expect(find.text('TABELA PÚBLICA'), findsOneWidget);
    });
  });

  testWidgets('conta comum só lê os preços', (tester) async {
    await _open(tester, _Backend(), body: () async {
      await _openPrices(tester);
      expect(find.byKey(const Key('price-sync')), findsNothing);
      expect(find.byKey(const Key('price-add')), findsNothing);
      expect(find.byTooltip('Editar preço'), findsNothing);
      expect(find.byTooltip('Apagar preço'), findsNothing);
    });
  });

  testWidgets('administrador importa a tabela pública e vê o resumo', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, admin: true, body: () async {
      await _openPrices(tester);
      await tester.tap(find.byKey(const Key('price-sync')));
      await tester.pumpAndSettle();

      expect(backend.called('POST', '/prices/sync'), isTrue);
      expect(find.textContaining('280 novo(s)'), findsOneWidget);
      expect(find.textContaining('4 preço(s) digitado(s) à mão mantido(s)'), findsOneWidget);
    });
  });

  testWidgets('sem rede a importação mostra o motivo e a lista continua', (tester) async {
    final backend = _Backend()..syncError = 'Nao consegui baixar a tabela de precos: timeout';
    await _open(tester, backend, admin: true, body: () async {
      await _openPrices(tester);
      await tester.tap(find.byKey(const Key('price-sync')));
      await tester.pumpAndSettle();

      expect(find.textContaining('timeout'), findsOneWidget);
      expect(find.text('claude-sonnet-4-5'), findsOneWidget);
    });
  });

  testWidgets('administrador cadastra o preço de um modelo', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, admin: true, body: () async {
      await _openPrices(tester);
      await tester.tap(find.byKey(const Key('price-add')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('price-model')), 'claude-opus-4');
      await tester.enterText(find.byKey(const Key('price-input')), '15');
      await tester.enterText(find.byKey(const Key('price-output')), '75,5'); // vírgula vale
      await tester.tap(find.byKey(const Key('price-save')));
      await tester.pumpAndSettle();

      final sent = jsonDecode(backend.last('PUT', '/prices').body) as Map<String, dynamic>;
      expect(sent['provider'], 'claude');
      expect(sent['model'], 'claude-opus-4');
      expect(sent['input_per_mtok'], 15);
      expect(sent['output_per_mtok'], 75.5);
      expect(find.text('claude-opus-4'), findsOneWidget);
    });
  });

  testWidgets('preço sem valor não vai para o servidor', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, admin: true, body: () async {
      await _openPrices(tester);
      await tester.tap(find.byKey(const Key('price-add')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('price-model')), 'x');
      await tester.tap(find.byKey(const Key('price-save')));
      await tester.pumpAndSettle();

      expect(backend.called('PUT', '/prices'), isFalse);
      expect(find.textContaining('Informe os preços de entrada e saída'), findsOneWidget);
    });
  });

  testWidgets('administrador apaga um preço', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, admin: true, body: () async {
      await _openPrices(tester);
      await tester.tap(find.byTooltip('Apagar preço').first);
      await tester.pumpAndSettle();

      expect(backend.called('DELETE', '/prices/p1'), isTrue);
      expect(find.text('claude-sonnet-4-5'), findsNothing);
    });
  });

  testWidgets('buscar um modelo filtra pela busca do servidor', (tester) async {
    final backend = _Backend();
    await _open(tester, backend, body: () async {
      await _openPrices(tester);
      await tester.enterText(find.byKey(const Key('price-search')), 'sonnet');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();

      expect(backend.last('GET', '/prices').url.queryParameters['q'], 'sonnet');
    });
  });
}

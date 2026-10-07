import 'dart:convert';
import 'dart:io';

import 'package:assistant_app/models/combined_summary.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/services/lesson_pdf_service.dart';
import 'package:assistant_app/widgets/combined_summary_dialog.dart';
import 'package:assistant_app/widgets/pdf_preview_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Lesson _lesson(String id, String kind, {String title = '', String group = ''}) =>
    Lesson(
      id: id,
      kind: kind,
      title: title,
      groupName: group,
      discipline: kind == 'apresentacao' ? 'ARA0058 - CLOUD' : 'BANCO DE DADOS',
      classGroup: '',
      status: 'closed',
      startedAt: DateTime(2026, 10, 6, 21, 0),
    );

Map<String, dynamic> _result({
  String kind = 'selecao-apresentacao',
  String style = 'standard',
  List<Map<String, dynamic>>? items,
  List<Map<String, dynamic>> skipped = const [],
}) =>
    {
      'summary': '## Visao geral\nResumo conjunto.\n\n## Por grupo\n### GRUPO 1\nFalou de sensores.\n- usou MQTT',
      'llm': 'llama',
      'style': style,
      'title': 'Apresentações dos grupos',
      'subtitle': 'ARA0058 - CLOUD  -  06/10/2026  -  2 gravações',
      'kind': kind,
      'items': items ??
          [
            {'id': 'p1', 'label': 'GRUPO 1 (06/10 21:00)', 'kind': 'apresentacao', 'group_name': 'GRUPO 1', 'source': 'resumo'},
            {'id': 'p2', 'label': 'GRUPO 2 (06/10 21:15)', 'kind': 'apresentacao', 'group_name': 'GRUPO 2', 'source': 'gerado'},
          ],
      'skipped': skipped,
    };

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('CombinedSummary', () {
    test('lê o resumo, os itens e o que ficou de fora', () {
      final combined = CombinedSummary.fromJson(_result(skipped: [
        {'id': 'p3', 'label': 'GRUPO 3', 'reason': 'sem resumo e sem transcrição'},
      ]));

      expect(combined.title, 'Apresentações dos grupos');
      expect(combined.items.map((i) => i.id), ['p1', 'p2']);
      expect(combined.items.first.groupName, 'GRUPO 1');
      expect(combined.skipped.single.reason, 'sem resumo e sem transcrição');
      expect(combined.kind, 'selecao-apresentacao');
    });

    test('de onde veio o texto de cada gravação', () {
      CombinedItem item(String source) => CombinedItem(id: 'x', label: 'x', source: source);

      expect(item('resumo').sourceLabel, 'a partir do resumo que ela já tinha');
      expect(item('gerado').sourceLabel, 'resumida agora, a partir da transcrição');
      expect(item('transcricao').sourceLabel,
          'a partir da transcrição (não deu para resumir)');
    });

    test('a etiqueta segue o tipo comum das gravações', () {
      expect(CombinedSummary.fromJson(_result()).heading, 'RESUMO DAS APRESENTAÇÕES');
      expect(combinedHeading('aula'), 'RESUMO DAS AULAS');
      expect(combinedHeading('palestra'), 'RESUMO DAS PALESTRAS');
      expect(combinedHeading('reuniao'), 'RESUMO DAS REUNIÕES');
      expect(combinedHeading(null), 'RESUMO DAS GRAVAÇÕES');
    });

    test('gravações de tipos misturados não têm tipo comum', () {
      final mixed = CombinedSummary.fromJson(_result(kind: 'selecao', items: [
        {'id': 'a', 'label': 'a', 'kind': 'aula'},
        {'id': 'b', 'label': 'b', 'kind': 'palestra'},
      ]));

      expect(mixed.commonKind, isNull);
      expect(mixed.heading, 'RESUMO DAS GRAVAÇÕES');
    });
  });

  group('describeSelection', () {
    test('conta por tipo, no plural e no singular', () {
      expect(describeSelection([_lesson('a', 'apresentacao'), _lesson('b', 'apresentacao')]),
          '2 apresentações');
      expect(describeSelection([_lesson('a', 'aula')]), '1 aula');
      expect(describeSelection([_lesson('a', 'reuniao'), _lesson('b', 'reuniao')]), '2 reuniões');
    });

    test('mistura lista os tipos com vírgula e "e"', () {
      expect(
        describeSelection([
          _lesson('a', 'aula'),
          _lesson('b', 'aula'),
          _lesson('c', 'palestra'),
          _lesson('d', 'apresentacao'),
        ]),
        '1 apresentação, 2 aulas e 1 palestra',
      );
      expect(describeSelection(const []), '');
    });
  });

  group('PDF do resumo conjunto', () {
    test('subtítulo "###" vira subseção, e "##" continua seção', () {
      final blocks = parseSummary('## Por grupo\n### GRUPO 1\nTexto.\n- item');

      expect(blocks, [
        const SummaryBlock(SummaryBlockKind.heading, 'Por grupo'),
        const SummaryBlock(SummaryBlockKind.subheading, 'GRUPO 1'),
        const SummaryBlock(SummaryBlockKind.paragraph, 'Texto.'),
        const SummaryBlock(SummaryBlockKind.bullet, 'item'),
      ]);
    });

    test('cabeçalho: etiqueta, título, grupos incluídos e o que ficou de fora', () {
      final header = combinedSummaryHeader(
        CombinedSummary.fromJson(_result(skipped: [
          {'id': 'p3', 'label': 'GRUPO 3', 'reason': 'sem transcrição'},
        ])),
        generatedAt: DateTime(2026, 10, 7, 9, 30),
      );

      expect(header.kindLabel, 'RESUMO DAS APRESENTAÇÕES');
      expect(header.heading, 'Apresentações dos grupos');
      expect(header.subtitle, 'ARA0058 - CLOUD  -  06/10/2026  -  2 gravações');
      expect(header.membersLabel, 'Grupos');
      expect(header.members, ['GRUPO 1 (06/10 21:00)', 'GRUPO 2 (06/10 21:15)']);
      expect(header.meta, contains('2 gravações incluídas'));
      expect(header.meta, contains('1 ficaram de fora'));
      expect(header.meta, contains('gerado em 07/10/2026'));
      expect(header.running, 'Apresentações dos grupos   |   ARA0058 - CLOUD');
    });

    test('mistura de tipos chama a lista de "Gravações"', () {
      final header = combinedSummaryHeader(CombinedSummary.fromJson(_result(
        kind: 'selecao',
        items: [
          {'id': 'a', 'label': 'a', 'kind': 'aula'},
          {'id': 'b', 'label': 'b', 'kind': 'palestra'},
        ],
      )));

      expect(header.membersLabel, 'Gravações');
      expect(header.kindLabel, 'RESUMO DAS GRAVAÇÕES');
    });

    test('o nome do arquivo leva título, disciplina e período, sem acentos', () {
      expect(
        combinedPdfFilename(CombinedSummary.fromJson(_result())),
        'apresentacoes-dos-grupos-ara0058-cloud-06-10-2026.pdf',
      );
      expect(
        combinedPdfFilename(CombinedSummary.fromJson(_result(style: 'detailed'))),
        'apresentacoes-dos-grupos-ara0058-cloud-06-10-2026-detalhado.pdf',
      );
    });

    test('nome do arquivo sem título cai no padrão e não passa de um tamanho', () {
      expect(
        combinedPdfFilename(const CombinedSummary(summary: 'x')),
        'resumo-das-gravacoes.pdf',
      );
      final longo = CombinedSummary(
        summary: 'x',
        title: 'T' * 300,
      );
      expect(combinedPdfFilename(longo).length, lessThanOrEqualTo(115));
    });

    test('gera o PDF com as gravações incluídas e as que ficaram de fora', () async {
      final bytes = await buildCombinedSummaryPdf(
        combined: CombinedSummary.fromJson(_result(skipped: [
          {'id': 'p3', 'label': 'GRUPO 3', 'reason': 'sem resumo e sem transcrição'},
        ])),
        generatedAt: DateTime(2026, 10, 7, 9, 30),
      );

      expect(String.fromCharCodes(bytes.take(4)), '%PDF');
      expect(bytes.length, greaterThan(1500));
      expect(
        String.fromCharCodes(bytes),
        anyOf(contains('Resumo detalhado'), contains('Resumo comum')),
      );
    });
  });

  group('barra de seleção do histórico', () {
    Future<void> pump(WidgetTester tester,
        {required int count, required int total,
        VoidCallback? onToggle, VoidCallback? onSummarise}) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: LessonSelectionBar(
            count: count,
            total: total,
            onToggleAll: onToggle ?? () {},
            onSummarise: onSummarise ?? () {},
          ),
        ),
      ));
    }

    FilledButton button(WidgetTester tester) => tester
        .widget<FilledButton>(find.byKey(const ValueKey('resumo-da-selecao')));

    testWidgets('sem seleção o resumo fica desligado', (tester) async {
      await pump(tester, count: 0, total: 5);

      expect(button(tester).onPressed, isNull);
      expect(find.text('RESUMO DA SELEÇÃO'), findsOneWidget);
      expect(find.text('SELECIONAR TODAS'), findsOneWidget);
      expect(find.byKey(const ValueKey('dica-selecao')), findsNothing);
    });

    testWidgets('com uma só, pede mais uma', (tester) async {
      await pump(tester, count: 1, total: 5);

      expect(button(tester).onPressed, isNull);
      expect(find.text('marque mais uma'), findsOneWidget);
    });

    testWidgets('com duas ou mais liga e mostra quantas', (tester) async {
      var abriu = 0;
      await pump(tester, count: 3, total: 5, onSummarise: () => abriu++);

      expect(find.text('RESUMO DA SELEÇÃO (3)'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('resumo-da-selecao')));
      expect(abriu, 1);
      expect(find.byKey(const ValueKey('dica-selecao')), findsNothing);
    });

    testWidgets('com todas marcadas o botão passa a limpar', (tester) async {
      var alternou = 0;
      await pump(tester, count: 5, total: 5, onToggle: () => alternou++);

      expect(find.text('LIMPAR'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('selecionar-todas')));
      expect(alternou, 1);
    });

    testWidgets('lista vazia não se confunde com "todas marcadas"', (tester) async {
      await pump(tester, count: 0, total: 0);

      expect(find.text('SELECIONAR TODAS'), findsOneWidget);
    });
  });

  group('janela do resumo da seleção', () {
    final lessons = [
      _lesson('p1', 'apresentacao', group: 'GRUPO 1'),
      _lesson('p2', 'apresentacao', group: 'GRUPO 2'),
    ];
    final requests = <http.Request>[];
    int? failStatus;

    Future<void> open(
      WidgetTester tester, {
      required Future<void> Function() body,
      Map<String, dynamic>? result,
      PdfPagesBuilder? pages,
      List<String>? printed,
      List<Map<String, String>>? saved,
    }) async {
      tester.view.physicalSize = const Size(1400, 2000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      requests.clear();
      final client = MockClient((request) async {
        requests.add(request);
        if (failStatus != null) {
          return http.Response(
              '{"detail":"Não foi possível gerar o resumo conjunto: sem resposta"}',
              failStatus!);
        }
        return http.Response(jsonEncode(result ?? _result()), 200);
      });
      await http.runWithClient(() async {
        await tester.pumpWidget(MaterialApp(
          home: Scaffold(
            body: CombinedSummaryPanel(
              lessons: lessons,
              pdfPages: pages ?? (bytes, name) => Text('páginas ${bytes.length}'),
              printer: (bytes, {required String name}) async =>
                  printed?.add(name),
              saver: ({
                required Uint8List bytes,
                required String fileName,
                required String dialogTitle,
                required String extension,
              }) async {
                saved?.add({'file': fileName, 'title': dialogTitle});
                return File('saida/$fileName');
              },
            ),
          ),
        ));
        await tester.pumpAndSettle();
        await body();
      }, () => client);
    }

    Map<String, dynamic> sent() =>
        jsonDecode(requests.last.body) as Map<String, dynamic>;

    setUp(() => failStatus = null);

    testWidgets('mostra o que será resumido antes de gerar', (tester) async {
      await open(tester, body: () async {
        expect(find.text('RESUMIR 2 APRESENTAÇÕES'), findsOneWidget);
        expect(find.textContaining('GRUPO 1'), findsOneWidget);
        expect(find.textContaining('GRUPO 2'), findsOneWidget);
        expect(find.byKey(const ValueKey('aviso-sem-resumo')), findsOneWidget);
        expect(find.byKey(const ValueKey('resumo-conjunto')), findsNothing);
        expect(requests, isEmpty);
      });
    });

    testWidgets('gera na ordem recebida, no formato comum e sem foco', (tester) async {
      await open(tester, body: () async {
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();

        expect(sent()['lesson_ids'], ['p1', 'p2']);
        expect(sent()['style'], 'standard');
        expect(sent()['focus'], '');
        expect(find.byKey(const ValueKey('resumo-conjunto')), findsOneWidget);
        expect(find.text('RESUMO DAS APRESENTAÇÕES'), findsOneWidget);
        expect(find.text('Apresentações dos grupos'), findsOneWidget);
        expect(find.text('GERAR DE NOVO'), findsOneWidget);
      });
    });

    testWidgets('formato detalhado e foco vão no pedido', (tester) async {
      await open(tester, body: () async {
        await tester.tap(find.text('Detalhado'));
        await tester.pump();
        await tester.enterText(
            find.byKey(const ValueKey('foco')), '  tecnologias usadas  ');
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();

        expect(sent()['style'], 'detailed');
        expect(sent()['focus'], 'tecnologias usadas');
      });
    });

    testWidgets('lista as gravações incluídas, de onde veio cada uma e as de fora',
        (tester) async {
      await open(
        tester,
        result: _result(skipped: [
          {'id': 'p3', 'label': 'GRUPO 3 (06/10 21:30)', 'reason': 'sem resumo e sem transcrição'},
        ]),
        body: () async {
          await tester.tap(find.byKey(const ValueKey('gerar')));
          await tester.pumpAndSettle();

          expect(
            find.text('• GRUPO 1 (06/10 21:00) — a partir do resumo que ela já tinha'),
            findsOneWidget,
          );
          expect(
            find.text('• GRUPO 2 (06/10 21:15) — resumida agora, a partir da transcrição'),
            findsOneWidget,
          );
          expect(
            find.text('• Ficou de fora: GRUPO 3 (06/10 21:30) — sem resumo e sem transcrição'),
            findsOneWidget,
          );
        },
      );
    });

    testWidgets('erro do servidor aparece e não deixa resumo na tela', (tester) async {
      failStatus = 502;
      await open(tester, body: () async {
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();

        expect(find.textContaining('Não foi possível gerar o resumo conjunto'), findsOneWidget);
        expect(find.byKey(const ValueKey('resumo-conjunto')), findsNothing);
        expect(find.text('GERAR RESUMO'), findsOneWidget);
      });
    });

    testWidgets('copiar manda o texto do resumo para a área de transferência',
        (tester) async {
      final copiado = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copiado.add((call.arguments as Map)['text'] as String);
          }
          return null;
        },
      );
      addTearDown(() => tester.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null));
      await open(tester, body: () async {
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byKey(const ValueKey('copiar')));
        await tester.tap(find.byKey(const ValueKey('copiar')));
        await tester.pumpAndSettle();

        expect(copiado.single, startsWith('## Visao geral'));
        expect(find.text('Resumo copiado.'), findsOneWidget);
      });
    });

    testWidgets('o PDF abre a prévia antes de qualquer saída', (tester) async {
      final printed = <String>[];
      final saved = <Map<String, String>>[];
      await open(tester, printed: printed, saved: saved, body: () async {
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byKey(const ValueKey('abrir-previa')));
        await tester.tap(find.byKey(const ValueKey('abrir-previa')));
        await tester.pumpAndSettle();

        expect(find.text('PRÉ-VISUALIZAÇÃO · RESUMO DAS APRESENTAÇÕES'), findsOneWidget);
        expect(printed, isEmpty);
        expect(saved, isEmpty);

        await tester.tap(find.byKey(const ValueKey('previa-salvar')));
        await tester.pumpAndSettle();

        expect(saved, [
          {
            'file': 'apresentacoes-dos-grupos-ara0058-cloud-06-10-2026.pdf',
            'title': 'Salvar resumo conjunto',
          }
        ]);
        expect(printed, isEmpty);
      });
    });

    testWidgets('na prévia também dá para imprimir, ou fechar sem nada', (tester) async {
      final printed = <String>[];
      await open(tester, printed: printed, body: () async {
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byKey(const ValueKey('abrir-previa')));

        await tester.tap(find.byKey(const ValueKey('abrir-previa')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('previa-cancelar')));
        await tester.pumpAndSettle();
        expect(printed, isEmpty);

        await tester.tap(find.byKey(const ValueKey('abrir-previa')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('previa-imprimir')));
        await tester.pumpAndSettle();
        expect(printed, ['apresentacoes-dos-grupos-ara0058-cloud-06-10-2026.pdf']);
      });
    });

    testWidgets('gerar de novo refaz o pedido com o formato escolhido agora',
        (tester) async {
      await open(tester, body: () async {
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Detalhado'));
        await tester.pump();
        await tester.ensureVisible(find.byKey(const ValueKey('gerar')));
        await tester.tap(find.byKey(const ValueKey('gerar')));
        await tester.pumpAndSettle();

        expect(requests.length, 2);
        expect(sent()['style'], 'detailed');
      });
    });
  });
}

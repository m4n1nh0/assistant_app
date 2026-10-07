import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:assistant_app/widgets/pdf_output.dart';
import 'package:assistant_app/widgets/pdf_preview_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

final _bytes = Uint8List.fromList([37, 80, 68, 70, 1, 2, 3]);

Widget _pages(Uint8List bytes, String name) =>
    Text('páginas de $name (${bytes.length} bytes)', key: const ValueKey('paginas'));

class _Output {
  final printed = <String>[];
  final saved = <Map<String, String>>[];
  Object? printError;
  File? savedFile = File('relatorios/saida.pdf');

  Future<void> printer(Uint8List bytes, {required String name}) async {
    if (printError != null) throw printError!;
    printed.add('$name:${bytes.length}');
  }

  Future<dynamic> saver({
    required Uint8List bytes,
    required String fileName,
    required String dialogTitle,
    required String extension,
  }) async {
    saved.add({'file': fileName, 'title': dialogTitle, 'ext': extension});
    return savedFile;
  }
}

Future<void> _open(
  WidgetTester tester,
  _Output output, {
  Future<Uint8List> Function()? build,
  PdfDestination? preferred,
  String title = 'PRÉ-VISUALIZAÇÃO DO PDF',
}) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Builder(
        builder: (context) => TextButton(
          key: const ValueKey('abrir'),
          onPressed: () => previewAndDeliverPdf(
            context,
            build: build ?? () async => _bytes,
            fileName: 'relatorio-teste.pdf',
            saveDialogTitle: 'Salvar relatório de teste',
            title: title,
            preferred: preferred,
            pages: _pages,
            printer: output.printer,
            saver: output.saver,
          ),
          child: const Text('abrir'),
        ),
      ),
    ),
  ));
  await tester.tap(find.byKey(const ValueKey('abrir')));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => pdfPagesBuilder = _pages);
  tearDown(() => pdfPagesBuilder = defaultPdfPages);

  group('prévia do PDF', () {
    testWidgets('a prévia aparece antes de qualquer saída', (tester) async {
      final output = _Output();
      await _open(tester, output);

      expect(find.text('PRÉ-VISUALIZAÇÃO DO PDF'), findsOneWidget);
      expect(find.textContaining('Confira o documento'), findsOneWidget);
      expect(find.text('páginas de relatorio-teste.pdf (7 bytes)'), findsOneWidget);
      expect(output.printed, isEmpty);
      expect(output.saved, isEmpty);
    });

    testWidgets('imprimir só depois de ver a prévia', (tester) async {
      final output = _Output();
      await _open(tester, output);

      await tester.tap(find.byKey(const ValueKey('previa-imprimir')));
      await tester.pumpAndSettle();

      expect(output.printed, ['relatorio-teste.pdf:7']);
      expect(output.saved, isEmpty);
      expect(find.byKey(const ValueKey('paginas')), findsNothing);
    });

    testWidgets('salvar grava como PDF e avisa onde', (tester) async {
      final output = _Output();
      await _open(tester, output);

      await tester.tap(find.byKey(const ValueKey('previa-salvar')));
      await tester.pumpAndSettle();

      expect(output.saved, [
        {'file': 'relatorio-teste.pdf', 'title': 'Salvar relatório de teste', 'ext': 'pdf'}
      ]);
      expect(output.printed, isEmpty);
      expect(find.text('PDF salvo em relatorios/saida.pdf'), findsOneWidget);
    });

    testWidgets('salvar e cancelar a escolha do arquivo não avisa nada',
        (tester) async {
      final output = _Output()..savedFile = null;
      await _open(tester, output);

      await tester.tap(find.byKey(const ValueKey('previa-salvar')));
      await tester.pumpAndSettle();

      expect(output.saved, hasLength(1));
      expect(find.textContaining('PDF salvo'), findsNothing);
    });

    testWidgets('fechar a prévia não imprime nem salva', (tester) async {
      final output = _Output();
      await _open(tester, output);

      await tester.tap(find.byKey(const ValueKey('previa-cancelar')));
      await tester.pumpAndSettle();

      expect(output.printed, isEmpty);
      expect(output.saved, isEmpty);
      expect(find.byKey(const ValueKey('paginas')), findsNothing);
    });

    testWidgets('o X do cabeçalho também fecha sem sair nada', (tester) async {
      final output = _Output();
      await _open(tester, output);

      await tester.tap(find.byKey(const ValueKey('previa-fechar')));
      await tester.pumpAndSettle();

      expect(output.printed, isEmpty);
      expect(output.saved, isEmpty);
    });

    testWidgets('o título da prévia diz de que relatório se trata', (tester) async {
      await _open(tester, _Output(), title: 'PRÉ-VISUALIZAÇÃO · RELATÓRIO DO QUIZ');

      expect(find.text('PRÉ-VISUALIZAÇÃO · RELATÓRIO DO QUIZ'), findsOneWidget);
    });

    testWidgets('mostra "gerando" enquanto o relatório é montado', (tester) async {
      final output = _Output();
      final pronto = Completer<Uint8List>();
      tester.view.physicalSize = const Size(1400, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              key: const ValueKey('abrir'),
              onPressed: () => previewAndDeliverPdf(
                context,
                build: () => pronto.future,
                fileName: 'x.pdf',
                saveDialogTitle: 'Salvar',
                pages: _pages,
                printer: output.printer,
                saver: output.saver,
              ),
              child: const Text('abrir'),
            ),
          ),
        ),
      ));

      await tester.tap(find.byKey(const ValueKey('abrir')));
      await tester.pump();
      expect(find.byKey(const ValueKey('gerando-relatorio')), findsOneWidget);
      expect(find.byKey(const ValueKey('previa-salvar')), findsNothing);

      pronto.complete(_bytes);
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('gerando-relatorio')), findsNothing);
      expect(find.byKey(const ValueKey('previa-salvar')), findsOneWidget);
    });

    testWidgets('falha ao gerar: avisa e não abre a prévia', (tester) async {
      final output = _Output();
      await _open(tester, output, build: () async => throw StateError('sem memória'));

      expect(find.textContaining('Falha ao gerar o PDF'), findsOneWidget);
      expect(find.textContaining('sem memória'), findsOneWidget);
      expect(find.byKey(const ValueKey('previa-salvar')), findsNothing);
      expect(find.byKey(const ValueKey('gerando-relatorio')), findsNothing);
      expect(output.printed, isEmpty);
    });

    testWidgets('falha ao imprimir: avisa depois da prévia', (tester) async {
      final output = _Output()..printError = StateError('sem impressora');
      await _open(tester, output);

      await tester.tap(find.byKey(const ValueKey('previa-imprimir')));
      await tester.pumpAndSettle();

      expect(find.textContaining('Falha ao concluir'), findsOneWidget);
      expect(find.textContaining('sem impressora'), findsOneWidget);
    });

    testWidgets('o botão do que o professor já tinha pedido vem destacado',
        (tester) async {
      await _open(tester, _Output(), preferred: PdfDestination.print);

      expect(find.byType(FilledButton), findsOneWidget);
      expect(
        tester.widget(find.byKey(const ValueKey('previa-imprimir'))),
        isA<FilledButton>(),
      );
      expect(
        tester.widget(find.byKey(const ValueKey('previa-salvar'))),
        isA<OutlinedButton>(),
      );
    });

    testWidgets('sem preferência, salvar é o destaque', (tester) async {
      await _open(tester, _Output());

      expect(
        tester.widget(find.byKey(const ValueKey('previa-salvar'))),
        isA<FilledButton>(),
      );
      expect(
        tester.widget(find.byKey(const ValueKey('previa-imprimir'))),
        isA<OutlinedButton>(),
      );
    });
  });

  group('offerPdf (relação de grupos, ordem de apresentação)', () {
    testWidgets('passa pela mesma prévia, com o nome do relatório no título',
        (tester) async {
      var built = false;
      tester.view.physicalSize = const Size(1400, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              key: const ValueKey('abrir'),
              onPressed: () => offerPdf(
                context,
                title: 'Relação de grupos',
                fileName: 'grupos.pdf',
                build: () async {
                  built = true;
                  return _bytes;
                },
              ),
              child: const Text('abrir'),
            ),
          ),
        ),
      ));

      await tester.tap(find.byKey(const ValueKey('abrir')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(built, isTrue);
      expect(find.text('PRÉ-VISUALIZAÇÃO · RELAÇÃO DE GRUPOS'), findsOneWidget);
    });
  });

  group('prévia da planilha', () {
    Future<bool?> open(WidgetTester tester, String csv, {required String tap}) async {
      tester.view.physicalSize = const Size(1400, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      bool? result;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              key: const ValueKey('abrir'),
              onPressed: () async =>
                  result = await showCsvPreviewDialog(context, csv: csv),
              child: const Text('abrir'),
            ),
          ),
        ),
      ));
      await tester.tap(find.byKey(const ValueKey('abrir')));
      await tester.pumpAndSettle();
      if (tap.isNotEmpty) {
        await tester.tap(find.byKey(ValueKey(tap)));
        await tester.pumpAndSettle();
      }
      return result;
    }

    testWidgets('mostra as linhas e só oferece salvar', (tester) async {
      await open(tester, 'aluno;nota\nAna;10\nBia;8', tap: '');

      expect(find.text('PRÉ-VISUALIZAÇÃO DA PLANILHA'), findsOneWidget);
      expect(find.text('3 linha(s). Confira antes de salvar a planilha.'), findsOneWidget);
      expect(tester.widget<SelectableText>(find.byKey(const ValueKey('previa-csv'))).data,
          'aluno;nota\nAna;10\nBia;8');
      expect(find.byKey(const ValueKey('previa-salvar')), findsOneWidget);
      expect(find.byKey(const ValueKey('previa-imprimir')), findsNothing);
      expect(find.text('SALVAR PLANILHA'), findsOneWidget);
    });

    testWidgets('salvar confirma; fechar não', (tester) async {
      expect(await open(tester, 'a;b\n1;2', tap: 'previa-salvar'), isTrue);
      expect(await open(tester, 'a;b\n1;2', tap: 'previa-cancelar'), isFalse);
    });

    testWidgets('planilha grande mostra o começo e diz quantas linhas faltam',
        (tester) async {
      final csv = [for (var i = 0; i < 250; i++) 'linha $i;x'].join('\n');
      await open(tester, csv, tap: '');

      final texto = tester
          .widget<SelectableText>(find.byKey(const ValueKey('previa-csv')))
          .data!;
      expect(texto.split('\n').length, 201);
      expect(texto, contains('linha 199;x'));
      expect(texto, isNot(contains('linha 200;x')));
      expect(texto, endsWith('… mais 50 linha(s) no arquivo'));
      expect(find.text('250 linha(s). Confira antes de salvar a planilha.'), findsOneWidget);
    });
  });
}

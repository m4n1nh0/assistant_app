/// Prévia de relatório antes de imprimir ou salvar.
///
/// Todo relatório do app passa por aqui: o documento é gerado, o professor confere
/// como ficou e só então escolhe imprimir ou salvar. A planilha (CSV) tem a mesma
/// etapa, com o conteúdo em texto.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:printing/printing.dart';

import '../services/pdf_common.dart';
import '../utils/theme.dart';

/// O que fazer com o relatório depois de ver a prévia.
enum PdfDestination { print, save }

/// Monta o visualizador das páginas. Os testes trocam o `PdfPreview` real (que depende
/// do plugin de impressão) por um widget simples.
typedef PdfPagesBuilder = Widget Function(Uint8List bytes, String fileName);

/// Visualizador usado por toda prévia. Os testes de tela o trocam por um widget simples:
/// o `PdfPreview` de verdade depende do plugin de impressão e nunca "assenta" num
/// `pumpAndSettle`.
@visibleForTesting
PdfPagesBuilder pdfPagesBuilder = defaultPdfPages;

/// O visualizador de verdade, com o `PdfPreview` do pacote de impressão.
Widget defaultPdfPages(Uint8List bytes, String fileName) => PdfPreview(
      build: (_) async => bytes,
      pdfFileName: fileName,
      useActions: false,
      allowPrinting: false,
      allowSharing: false,
      canChangePageFormat: false,
      canChangeOrientation: false,
      canDebug: false,
      maxPageWidth: 720,
      padding: const EdgeInsets.all(18),
      scrollViewDecoration: const BoxDecoration(color: Color(0xFFE6EBF1)),
      pdfPreviewPageDecoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.18),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      onError: (_, error) => Center(
        child: Text(
          'Não foi possível visualizar o PDF: $error',
          style: const TextStyle(color: AssistantTheme.danger),
        ),
      ),
    );

/// Imprimir e salvar de verdade, nomeados para quem precisa repassá-los.
Future<void> defaultPdfPrinter(Uint8List bytes, {required String name}) =>
    printPdf(bytes, name: name);

Future<dynamic> defaultPdfSaver({
  required Uint8List bytes,
  required String fileName,
  required String dialogTitle,
  required String extension,
}) =>
    saveBytes(
      bytes: bytes,
      fileName: fileName,
      dialogTitle: dialogTitle,
      extension: extension,
    );

/// Mostra o PDF e devolve o que o professor escolheu fazer com ele (`null` = fechou).
///
/// [preferred] só destaca o botão que o professor já tinha pedido antes de gerar.
Future<PdfDestination?> showPdfPreviewDialog(
  BuildContext context, {
  required Uint8List bytes,
  required String fileName,
  String title = 'PRÉ-VISUALIZAÇÃO DO PDF',
  String? detail,
  PdfDestination? preferred,
  PdfPagesBuilder? pages,
}) {
  return showDialog<PdfDestination>(
    context: context,
    builder: (_) => _PreviewFrame(
      title: title,
      detail: detail ?? 'Confira o documento antes de imprimir ou salvar.',
      preferred: preferred,
      body: (pages ?? pdfPagesBuilder)(bytes, fileName),
      saveLabel: 'SALVAR PDF',
      printLabel: 'IMPRIMIR',
    ),
  );
}

/// Prévia da planilha: as linhas como serão gravadas, em texto, e só então salvar.
Future<bool> showCsvPreviewDialog(
  BuildContext context, {
  required String csv,
  String title = 'PRÉ-VISUALIZAÇÃO DA PLANILHA',
  String? detail,
}) async {
  final lines = const LineSplitter().convert(csv);
  const shown = 200;
  final result = await showDialog<PdfDestination>(
    context: context,
    builder: (_) => _PreviewFrame(
      title: title,
      detail: detail ??
          '${lines.length} linha(s). Confira antes de salvar a planilha.',
      body: Container(
        color: const Color(0xFFE6EBF1),
        padding: const EdgeInsets.all(14),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: SingleChildScrollView(
            child: SelectableText(
              [
                ...lines.take(shown),
                if (lines.length > shown)
                  '… mais ${lines.length - shown} linha(s) no arquivo',
              ].join('\n'),
              key: const ValueKey('previa-csv'),
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                color: Colors.black87,
              ),
            ),
          ),
        ),
      ),
      saveLabel: 'SALVAR PLANILHA',
      printLabel: null,
    ),
  );
  return result == PdfDestination.save;
}

class _PreviewFrame extends StatelessWidget {
  final String title;
  final String detail;
  final Widget body;
  final PdfDestination? preferred;
  final String saveLabel;
  final String? printLabel;

  const _PreviewFrame({
    required this.title,
    required this.detail,
    required this.body,
    required this.saveLabel,
    required this.printLabel,
    this.preferred,
  });

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final width = (size.width - 48).clamp(280.0, 1100.0).toDouble();
    final height = (size.height - 48).clamp(360.0, 820.0).toDouble();
    final saveFirst = preferred != PdfDestination.print;

    final save = saveFirst
        ? FilledButton.icon(
            key: const ValueKey('previa-salvar'),
            onPressed: () => Navigator.of(context).pop(PdfDestination.save),
            icon: const Icon(Icons.save_alt_outlined, size: 16),
            label: Text(saveLabel),
          )
        : OutlinedButton.icon(
            key: const ValueKey('previa-salvar'),
            onPressed: () => Navigator.of(context).pop(PdfDestination.save),
            icon: const Icon(Icons.save_alt_outlined, size: 16),
            label: Text(saveLabel),
          );
    final print = printLabel == null
        ? null
        : saveFirst
            ? OutlinedButton.icon(
                key: const ValueKey('previa-imprimir'),
                onPressed: () =>
                    Navigator.of(context).pop(PdfDestination.print),
                icon: const Icon(Icons.print_outlined, size: 16),
                label: Text(printLabel!),
              )
            : FilledButton.icon(
                key: const ValueKey('previa-imprimir'),
                onPressed: () =>
                    Navigator.of(context).pop(PdfDestination.print),
                icon: const Icon(Icons.print_outlined, size: 16),
                label: Text(printLabel!),
              );

    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      child: SizedBox(
        width: width,
        height: height,
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.fromLTRB(18, 12, 10, 12),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: AssistantTheme.border2)),
              ),
              child: Row(children: [
                const Icon(Icons.preview_outlined,
                    size: 18, color: AssistantTheme.c3),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1.2,
                          color: AssistantTheme.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        detail,
                        key: const ValueKey('previa-detalhe'),
                        style: const TextStyle(
                            fontSize: 10, color: AssistantTheme.textSecondary),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  key: const ValueKey('previa-fechar'),
                  tooltip: 'Fechar a prévia',
                  onPressed: () => Navigator.of(context).pop(),
                  icon: const Icon(Icons.close, size: 18),
                ),
              ]),
            ),
            Expanded(child: body),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: AssistantTheme.border2)),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    key: const ValueKey('previa-cancelar'),
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('FECHAR'),
                  ),
                  const SizedBox(width: 8),
                  if (saveFirst) ...[
                    if (print != null) print,
                    if (print != null) const SizedBox(width: 8),
                    save,
                  ] else ...[
                    save,
                    const SizedBox(width: 8),
                    print!,
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Faz o que o professor escolheu na prévia: imprime ou salva.
///
/// Devolve o arquivo salvo, ou `null` se imprimiu ou cancelou. Imprimir e salvar são
/// trocáveis nos testes.
Future<void> deliverPdf(
  BuildContext context, {
  required PdfDestination destination,
  required Uint8List bytes,
  required String fileName,
  required String saveDialogTitle,
  Future<void> Function(Uint8List bytes, {required String name}) printer = printPdf,
  Future<dynamic> Function({
    required Uint8List bytes,
    required String fileName,
    required String dialogTitle,
    required String extension,
  }) saver = saveBytes,
}) async {
  if (destination == PdfDestination.print) {
    await printer(bytes, name: fileName);
    return;
  }
  final file = await saver(
    bytes: bytes,
    fileName: fileName,
    dialogTitle: saveDialogTitle,
    extension: 'pdf',
  );
  if (file != null && context.mounted) {
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
      SnackBar(content: Text('PDF salvo em ${file.path}')),
    );
  }
}

/// Gera, mostra a prévia e entrega: o caminho de todo relatório em PDF.
///
/// [build] só roda aqui, e a prévia vem antes de qualquer impressão ou arquivo.
Future<void> previewAndDeliverPdf(
  BuildContext context, {
  required Future<Uint8List> Function() build,
  required String fileName,
  required String saveDialogTitle,
  String title = 'PRÉ-VISUALIZAÇÃO DO PDF',
  String? detail,
  PdfDestination? preferred,
  PdfPagesBuilder? pages,
  Future<void> Function(Uint8List bytes, {required String name}) printer = printPdf,
  Future<dynamic> Function({
    required Uint8List bytes,
    required String fileName,
    required String dialogTitle,
    required String extension,
  }) saver = saveBytes,
}) async {
  Uint8List bytes;
  try {
    bytes = await _withProgress(context, build);
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(
        content: Text('Falha ao gerar o PDF: $error'),
        backgroundColor: AssistantTheme.danger,
      ));
    }
    return;
  }
  if (!context.mounted) return;
  final destination = await showPdfPreviewDialog(
    context,
    bytes: bytes,
    fileName: fileName,
    title: title,
    detail: detail,
    preferred: preferred,
    pages: pages,
  );
  if (destination == null || !context.mounted) return;
  try {
    await deliverPdf(
      context,
      destination: destination,
      bytes: bytes,
      fileName: fileName,
      saveDialogTitle: saveDialogTitle,
      printer: printer,
      saver: saver,
    );
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(
        content: Text('Falha ao concluir: $error'),
        backgroundColor: AssistantTheme.danger,
      ));
    }
  }
}

/// "Gerando o relatório..." enquanto o documento é montado (fonte e imagens custam).
Future<T> _withProgress<T>(
    BuildContext context, Future<T> Function() work) async {
  showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => const PopScope(
      canPop: false,
      child: AlertDialog(
        key: ValueKey('gerando-relatorio'),
        content: Row(mainAxisSize: MainAxisSize.min, children: [
          SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 16),
          Text('Gerando o relatório...'),
        ]),
      ),
    ),
  );
  try {
    return await work();
  } finally {
    if (context.mounted) Navigator.of(context, rootNavigator: true).pop();
  }
}

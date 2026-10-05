/// Pergunta se o PDF vai para a impressora ou para um arquivo, e faz o que foi
/// escolhido. Os PDFs de grupos usam a mesma saída dos PDFs do quiz.
library;

import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../services/pdf_common.dart';
import '../utils/theme.dart';

enum PdfDestination { print, save }

Future<PdfDestination?> askPdfDestination(
  BuildContext context, {
  required String title,
  String? detail,
}) {
  return showDialog<PdfDestination>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: Text(title),
      content: detail == null
          ? null
          : Text(
              detail,
              style: const TextStyle(color: AssistantTheme.textSecondary),
            ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('CANCELAR'),
        ),
        OutlinedButton.icon(
          onPressed: () => Navigator.pop(dialogContext, PdfDestination.save),
          icon: const Icon(Icons.save_alt_outlined, size: 16),
          label: const Text('SALVAR PDF'),
        ),
        FilledButton.icon(
          onPressed: () => Navigator.pop(dialogContext, PdfDestination.print),
          icon: const Icon(Icons.print_outlined, size: 16),
          label: const Text('IMPRIMIR'),
        ),
      ],
    ),
  );
}

void _snack(BuildContext context, String message, {bool error = false}) {
  ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(
    content: Text(message),
    backgroundColor: error ? AssistantTheme.danger : null,
  ));
}

/// Pergunta o destino, gera o PDF e imprime ou salva.
///
/// `build` só roda depois da escolha: gerar o PDF custa fonte e imagem, e quem
/// cancelou não deve esperar por isso.
Future<void> offerPdf(
  BuildContext context, {
  required String title,
  required String fileName,
  required Future<Uint8List> Function() build,
  String? detail,
  String saveDialogTitle = 'Salvar PDF',
}) async {
  final destination = await askPdfDestination(context, title: title, detail: detail);
  if (destination == null || !context.mounted) return;

  try {
    final bytes = await build();
    if (destination == PdfDestination.print) {
      await printPdf(bytes, name: fileName);
      return;
    }
    final file = await saveBytes(
      bytes: bytes,
      fileName: fileName,
      dialogTitle: saveDialogTitle,
      extension: 'pdf',
    );
    if (file != null && context.mounted) {
      _snack(context, 'PDF salvo em ${file.path}');
    }
  } catch (error) {
    if (context.mounted) {
      _snack(context, 'Falha ao gerar o PDF: $error', error: true);
    }
  }
}


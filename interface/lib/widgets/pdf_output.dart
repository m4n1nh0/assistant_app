/// Saída dos PDFs de grupos: gera, mostra a prévia e só então imprime ou salva.
/// É a mesma etapa dos relatórios do quiz (veja `pdf_preview_dialog.dart`).
library;

import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'pdf_preview_dialog.dart';

export 'pdf_preview_dialog.dart' show PdfDestination;

/// Gera o PDF, mostra a prévia e imprime ou salva o que o professor escolher.
///
/// `build` só roda depois do pedido, e nada é impresso nem gravado antes de a prévia
/// ser vista: cancelar na prévia não deixa arquivo nenhum.
Future<void> offerPdf(
  BuildContext context, {
  required String title,
  required String fileName,
  required Future<Uint8List> Function() build,
  String? detail,
  String saveDialogTitle = 'Salvar PDF',
}) =>
    previewAndDeliverPdf(
      context,
      build: build,
      fileName: fileName,
      saveDialogTitle: saveDialogTitle,
      title: 'PRÉ-VISUALIZAÇÃO · ${title.toUpperCase()}',
      detail: detail,
    );

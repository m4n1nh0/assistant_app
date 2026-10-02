/// O que os PDFs do quiz (exercicios e relatorio) compartilham: paleta, fonte com
/// acento, rodape e o salvar/imprimir.
///
/// Mesma identidade dos outros PDFs do app (resumo de aula, relatorios
/// academicos): corpo claro, porque e papel que se imprime e distribui, e a marca
/// no cabecalho e no rodape.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

import '../branding/intarq_brand.dart';

const pdfAccent = PdfColor.fromInt(0xFF00A9D4);
const pdfAccentDark = PdfColor.fromInt(0xFF0A3A59);
const pdfInk = PdfColor.fromInt(0xFF111827);
const pdfInkSoft = PdfColor.fromInt(0xFF44566B);
const pdfRule = PdfColor.fromInt(0xFFD8E0EA);
const pdfPanel = PdfColor.fromInt(0xFFF3F6FA);
const pdfHeader = PdfColor.fromInt(0xFFF4F8FC);
const pdfGood = PdfColor.fromInt(0xFF15803D);
const pdfBad = PdfColor.fromInt(0xFFB91C1C);
const pdfWarn = PdfColor.fromInt(0xFFB45309);

pw.ThemeData? _theme;

/// As fontes embutidas do PDF sao ASCII: sem uma TTF de verdade todo acento sai
/// errado. Roboto vem junto no aplicativo.
Future<pw.ThemeData> pdfTheme() async {
  if (_theme != null) return _theme!;
  try {
    final theme = pw.ThemeData.withFont(
      base:
          pw.Font.ttf(await rootBundle.load('assets/fonts/roboto-regular.ttf')),
      bold: pw.Font.ttf(await rootBundle.load('assets/fonts/roboto-bold.ttf')),
    );
    // So guarda o que deu certo: fallback em cache deixaria o documento sem
    // acento pelo resto da sessao.
    _theme = theme;
    return theme;
  } catch (_) {
    return pw.ThemeData.withFont();
  }
}

/// Rodape com a marca e o numero da pagina.
pw.Widget pdfFooter(pw.Context context) => pw.Container(
      padding: const pw.EdgeInsets.only(top: 8),
      decoration: const pw.BoxDecoration(
        border: pw.Border(top: pw.BorderSide(color: pdfRule)),
      ),
      child: pw.Row(
        mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
        children: [
          IntarqBrand.pdfWordmark(fontSize: 8, intarColor: pdfInkSoft),
          pw.Text(
            '${context.pageNumber}/${context.pagesCount}',
            style: const pw.TextStyle(fontSize: 8, color: pdfInkSoft),
          ),
        ],
      ),
    );

/// Titulo de secao: caixa alta com espacamento e um traco, como nos outros PDFs.
pw.Widget pdfSectionTitle(String text) => pw.Padding(
      padding: const pw.EdgeInsets.only(top: 16, bottom: 8),
      child: pw.Column(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          pw.Text(
            text.toUpperCase(),
            style: pw.TextStyle(
              fontSize: 10,
              letterSpacing: 1.6,
              color: pdfInk,
              fontWeight: pw.FontWeight.bold,
            ),
          ),
          pw.SizedBox(height: 4),
          pw.Container(height: 1.4, width: 46, color: pdfAccent),
        ],
      ),
    );

/// Faixa de abertura do documento, com a marca a direita.
pw.Widget pdfBanner({
  required String kicker,
  required String title,
  required List<String> details,
  required pw.MemoryImage? brandMark,
  String? subtitle,
}) {
  return pw.Container(
    width: double.infinity,
    margin: const pw.EdgeInsets.only(bottom: 4),
    padding: const pw.EdgeInsets.fromLTRB(18, 20, 18, 18),
    decoration: const pw.BoxDecoration(
      color: pdfHeader,
      border: pw.Border(
        left: pw.BorderSide(color: IntarqBrand.pdfGold, width: 5),
        bottom: pw.BorderSide(color: pdfRule, width: 1),
      ),
    ),
    child: pw.Row(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.Expanded(
          child: pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Text(
                kicker.toUpperCase(),
                style: pw.TextStyle(
                  fontSize: 9,
                  letterSpacing: 3,
                  color: pdfAccentDark,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              pw.SizedBox(height: 8),
              pw.Text(
                title,
                style: pw.TextStyle(
                  fontSize: 19,
                  color: pdfInk,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              if (subtitle != null && subtitle.isNotEmpty) ...[
                pw.SizedBox(height: 2),
                pw.Text(
                  subtitle,
                  style: const pw.TextStyle(fontSize: 12, color: pdfInkSoft),
                ),
              ],
              if (details.isNotEmpty) ...[
                pw.SizedBox(height: 10),
                pw.Text(
                  details.join('   |   '),
                  style: const pw.TextStyle(fontSize: 9, color: pdfInkSoft),
                ),
              ],
            ],
          ),
        ),
        pw.SizedBox(width: 12),
        IntarqBrand.pdfSignature(brandMark, width: 132, height: 51),
      ],
    ),
  );
}

String formatDateTime(DateTime? date) {
  if (date == null) return '';
  final local = date.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}/${two(local.month)}/${local.year} '
      'às ${two(local.hour)}:${two(local.minute)}';
}

String formatDate(DateTime? date) {
  if (date == null) return '';
  final local = date.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}/${two(local.month)}/${local.year}';
}

/// Salva os bytes no caminho que o professor escolher. Devolve o arquivo, ou
/// `null` se ele cancelou.
///
/// No desktop o `file_picker` devolve o caminho e nao grava sozinho: o conteudo e
/// conferido depois e gravado se faltar, como nos outros exportadores do app.
Future<File?> saveBytes({
  required Uint8List bytes,
  required String fileName,
  required String dialogTitle,
  required String extension,
}) async {
  final path = await FilePicker.saveFile(
    dialogTitle: dialogTitle,
    fileName: fileName,
    type: FileType.custom,
    allowedExtensions: [extension],
    bytes: bytes,
  );
  if (path == null) return null;
  final file = File(
    path.toLowerCase().endsWith('.$extension') ? path : '$path.$extension',
  );
  if (!await file.exists() || await file.length() != bytes.length) {
    await file.writeAsBytes(bytes);
  }
  return file;
}

/// Abre o dialogo de impressao do sistema com o PDF.
Future<void> printPdf(Uint8List bytes, {required String name}) async {
  await Printing.layoutPdf(onLayout: (_) async => bytes, name: name);
}

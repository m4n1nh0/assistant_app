import 'dart:typed_data';

import 'package:flutter/services.dart' show rootBundle;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../branding/intarq_brand.dart';
import 'education_service.dart';

/// Gera o PDF do resumo da aula com a identidade visual do aplicativo.
///
/// O documento nasce do resumo em markdown que o backend devolve. O corpo e
/// claro de proposito — resumo de aula costuma ser impresso e distribuido —,
/// e a identidade vem do cabecalho claro, da paleta e das etiquetas em caixa
/// alta com espacamento, do mesmo jeito que na interface.

// Paleta espelhada de AssistantTheme.
const _accent = PdfColor.fromInt(0xFF00A9D4);
const _accentDark = PdfColor.fromInt(0xFF0A3A59);
const _accentSoft = PdfColor.fromInt(0xFF9A7621);
const _ink = PdfColor.fromInt(0xFF111827);
const _inkSoft = PdfColor.fromInt(0xFF44566B);
const _rule = PdfColor.fromInt(0xFFD8E0EA);
const _panel = PdfColor.fromInt(0xFFF3F6FA);
const _header = PdfColor.fromInt(0xFFF4F8FC);
const _headerBadge = PdfColor.fromInt(0xFFFFFFFF);

enum SummaryBlockKind { heading, bullet, paragraph }

class SummaryBlock {
  final SummaryBlockKind kind;
  final String text;

  const SummaryBlock(this.kind, this.text);

  @override
  bool operator ==(Object other) =>
      other is SummaryBlock && other.kind == kind && other.text == text;

  @override
  int get hashCode => Object.hash(kind, text);

  @override
  String toString() => '${kind.name}:$text';
}

/// Interpreta o markdown enxuto que o resumo usa: titulos com `#`, itens com
/// `-` ou `*` e o resto como paragrafo. Nao e um parser de markdown completo,
/// e sim o suficiente para o formato que o prompt do resumo pede.
List<SummaryBlock> parseSummary(String summary) {
  final blocks = <SummaryBlock>[];
  final paragraph = StringBuffer();

  void flush() {
    final text = paragraph.toString().trim();
    if (text.isNotEmpty) {
      blocks.add(SummaryBlock(SummaryBlockKind.paragraph, text));
    }
    paragraph.clear();
  }

  for (final rawLine in summary.split('\n')) {
    final line = rawLine.trim();
    if (line.isEmpty) {
      flush();
      continue;
    }
    if (line.startsWith('#')) {
      flush();
      final title = line.replaceFirst(RegExp(r'^#+\s*'), '').trim();
      if (title.isNotEmpty) {
        blocks.add(SummaryBlock(SummaryBlockKind.heading, title));
      }
      continue;
    }
    if (RegExp(r'^[-*]\s+').hasMatch(line)) {
      flush();
      final item = line.replaceFirst(RegExp(r'^[-*]\s+'), '').trim();
      if (item.isNotEmpty) {
        blocks.add(SummaryBlock(SummaryBlockKind.bullet, _stripEmphasis(item)));
      }
      continue;
    }
    if (paragraph.isNotEmpty) paragraph.write(' ');
    paragraph.write(_stripEmphasis(line));
  }
  flush();
  return blocks;
}

/// O gerador de PDF nao entende `**negrito**`; sem isso os asteriscos apareciam
/// crus no documento.
String _stripEmphasis(String text) => text
    .replaceAllMapped(RegExp(r'\*\*(.+?)\*\*'), (match) => match.group(1)!)
    .replaceAllMapped(RegExp(r'\*(.+?)\*'), (match) => match.group(1)!)
    .replaceAll('**', '')
    .replaceAll('`', '');

/// As fontes embutidas do PDF sao ASCII: sem uma TTF de verdade, todo acento
/// do resumo sai errado. Roboto vem junto no aplicativo.
pw.ThemeData? _theme;

Future<pw.ThemeData> _pdfTheme() async {
  if (_theme != null) return _theme!;
  try {
    final theme = pw.ThemeData.withFont(
      base:
          pw.Font.ttf(await rootBundle.load('assets/fonts/roboto-regular.ttf')),
      bold: pw.Font.ttf(await rootBundle.load('assets/fonts/roboto-bold.ttf')),
    );
    // So guarda o que deu certo: um fallback em cache deixaria o documento
    // sem acento pelo resto da sessao.
    _theme = theme;
    return theme;
  } catch (_) {
    // Sem o pacote de assets, segue com a fonte embutida.
    return pw.ThemeData.withFont();
  }
}

String _formatDate(DateTime? date) {
  if (date == null) return '';
  final local = date.toLocal();
  final day = local.day.toString().padLeft(2, '0');
  final month = local.month.toString().padLeft(2, '0');
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$day/$month/${local.year} as $hour:$minute';
}

String _formatPoints(double value) {
  final rounded = value.toStringAsFixed(2);
  return rounded.endsWith('.00')
      ? rounded.substring(0, rounded.length - 3)
      : rounded;
}

/// Nome sugerido no dialogo de salvar: disciplina, turma e data.
String lessonPdfFilename(Lesson lesson) {
  final parts = [
    lesson.semester,
    lesson.discipline,
    lesson.classLabels.isEmpty
        ? lesson.classGroup
        : lesson.classLabels.join('-'),
    _formatDate(lesson.startedAt).split(' ').first.replaceAll('/', '-'),
  ].where((part) => part.trim().isNotEmpty);

  final slug = parts
      .join('-')
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9\-]+'), '-')
      .replaceAll(RegExp(r'-+'), '-')
      .replaceAll(RegExp(r'^-|-$'), '');
  return '${slug.isEmpty ? "resumo-da-aula" : slug}.pdf';
}

Future<Uint8List> buildLessonSummaryPdf({
  required Lesson lesson,
  required String summary,
  List<LessonPoint> points = const [],
}) async {
  final document = pw.Document(
    title: 'Resumo da aula - ${lesson.discipline}',
    author: 'INTARQ',
  );
  final blocks = parseSummary(summary);
  final brandMark = await IntarqBrand.loadPdfMark();
  final turmas = lesson.classLabels.isEmpty
      ? lesson.classGroup
      : lesson.classLabels.join(' + ');

  document.addPage(
    pw.MultiPage(
      pageTheme: pw.PageTheme(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.fromLTRB(36, 0, 36, 40),
        theme: await _pdfTheme(),
      ),
      header: (context) => context.pageNumber == 1
          ? _buildBanner(lesson, turmas, brandMark)
          : _buildRunningHeader(lesson, brandMark),
      footer: (context) => _buildFooter(context),
      build: (context) => [
        pw.SizedBox(height: 18),
        ..._buildBody(blocks),
        if (points.isNotEmpty) ..._buildPoints(points),
      ],
    ),
  );

  return document.save();
}

pw.Widget _buildBanner(
  Lesson lesson,
  String turmas,
  pw.MemoryImage? brandMark,
) {
  return pw.Container(
    width: double.infinity,
    margin: const pw.EdgeInsets.only(bottom: 4),
    padding: const pw.EdgeInsets.fromLTRB(18, 20, 18, 18),
    decoration: const pw.BoxDecoration(
      color: _header,
      border: pw.Border(
        left: pw.BorderSide(color: IntarqBrand.pdfGold, width: 5),
        bottom: pw.BorderSide(color: _rule, width: 1),
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
                'RESUMO DA AULA',
                style: pw.TextStyle(
                  fontSize: 9,
                  letterSpacing: 3,
                  color: _accentDark,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              pw.SizedBox(height: 8),
              pw.Text(
                lesson.discipline,
                style: pw.TextStyle(
                  fontSize: 19,
                  color: _ink,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              if (lesson.title.isNotEmpty) ...[
                pw.SizedBox(height: 2),
                pw.Text(
                  lesson.title,
                  style: const pw.TextStyle(
                    fontSize: 12,
                    color: _accentSoft,
                  ),
                ),
              ],
              pw.SizedBox(height: 10),
              pw.Text(
                [
                  if (turmas.isNotEmpty) 'Turma: $turmas',
                  if (lesson.startedAt != null) _formatDate(lesson.startedAt),
                  '${lesson.segmentCount} trechos gravados',
                ].join('   |   '),
                style: const pw.TextStyle(fontSize: 9, color: _inkSoft),
              ),
            ],
          ),
        ),
        pw.SizedBox(width: 12),
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.end,
          children: [
            IntarqBrand.pdfSignature(brandMark, width: 132, height: 51),
            if (lesson.semester.isNotEmpty) ...[
              pw.SizedBox(height: 7),
              pw.Container(
                padding:
                    const pw.EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: pw.BoxDecoration(
                  color: _headerBadge,
                  border: pw.Border.all(color: IntarqBrand.pdfGold),
                  borderRadius:
                      const pw.BorderRadius.all(pw.Radius.circular(4)),
                ),
                child: pw.Text(
                  lesson.semester,
                  style: pw.TextStyle(
                    fontSize: 9,
                    color: _accentDark,
                    fontWeight: pw.FontWeight.bold,
                  ),
                ),
              ),
            ],
          ],
        ),
      ],
    ),
  );
}

pw.Widget _buildRunningHeader(
  Lesson lesson,
  pw.MemoryImage? brandMark,
) {
  return pw.Container(
    margin: const pw.EdgeInsets.only(bottom: 12),
    padding: const pw.EdgeInsets.only(top: 24, bottom: 6),
    decoration: const pw.BoxDecoration(
      border: pw.Border(bottom: pw.BorderSide(color: _rule)),
    ),
    child: pw.Row(
      mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
      children: [
        pw.Expanded(
          child: pw.Text(
            '${lesson.semester.isEmpty ? "" : "${lesson.semester}   |   "}'
            '${lesson.discipline}   |   ${_formatDate(lesson.startedAt)}',
            style: const pw.TextStyle(fontSize: 8, color: _inkSoft),
          ),
        ),
        IntarqBrand.pdfSignature(brandMark, width: 82, height: 30),
      ],
    ),
  );
}

pw.Widget _buildFooter(pw.Context context) {
  return pw.Container(
    padding: const pw.EdgeInsets.only(top: 8),
    decoration: const pw.BoxDecoration(
      border: pw.Border(top: pw.BorderSide(color: _rule)),
    ),
    child: pw.Row(
      mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
      children: [
        IntarqBrand.pdfWordmark(fontSize: 8, intarColor: _inkSoft),
        pw.Text(
          '${context.pageNumber}/${context.pagesCount}',
          style: const pw.TextStyle(fontSize: 8, color: _inkSoft),
        ),
      ],
    ),
  );
}

List<pw.Widget> _buildBody(List<SummaryBlock> blocks) {
  final widgets = <pw.Widget>[];
  for (final block in blocks) {
    switch (block.kind) {
      case SummaryBlockKind.heading:
        widgets.add(pw.Padding(
          padding: const pw.EdgeInsets.only(top: 14, bottom: 6),
          child: pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Text(
                block.text.toUpperCase(),
                style: pw.TextStyle(
                  fontSize: 10,
                  letterSpacing: 1.6,
                  color: _ink,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              pw.SizedBox(height: 4),
              pw.Container(height: 1.4, width: 46, color: _accent),
            ],
          ),
        ));
      case SummaryBlockKind.bullet:
        widgets.add(pw.Padding(
          padding: const pw.EdgeInsets.only(bottom: 4, left: 4),
          child: pw.Row(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Container(
                width: 3,
                height: 3,
                margin: const pw.EdgeInsets.only(top: 5, right: 7),
                decoration: const pw.BoxDecoration(
                  color: _accent,
                  shape: pw.BoxShape.circle,
                ),
              ),
              pw.Expanded(
                child: pw.Text(
                  block.text,
                  style: const pw.TextStyle(
                      fontSize: 10.5, color: _ink, lineSpacing: 2),
                ),
              ),
            ],
          ),
        ));
      case SummaryBlockKind.paragraph:
        widgets.add(pw.Padding(
          padding: const pw.EdgeInsets.only(bottom: 8),
          child: pw.Text(
            block.text,
            textAlign: pw.TextAlign.justify,
            style: const pw.TextStyle(
                fontSize: 10.5, color: _ink, lineSpacing: 2.5),
          ),
        ));
    }
  }
  return widgets;
}

List<pw.Widget> _buildPoints(List<LessonPoint> points) {
  return [
    pw.SizedBox(height: 18),
    pw.Container(
      width: double.infinity,
      padding: const pw.EdgeInsets.all(14),
      decoration: pw.BoxDecoration(
        color: _panel,
        border: pw.Border.all(color: _rule),
      ),
      child: pw.Column(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          pw.Text(
            'PONTUACOES EXTRAS',
            style: pw.TextStyle(
              fontSize: 9,
              letterSpacing: 2,
              color: _ink,
              fontWeight: pw.FontWeight.bold,
            ),
          ),
          pw.SizedBox(height: 10),
          for (final point in points)
            pw.Padding(
              padding: const pw.EdgeInsets.only(bottom: 5),
              child: pw.Row(
                crossAxisAlignment: pw.CrossAxisAlignment.start,
                children: [
                  pw.Expanded(
                    child: pw.Text(
                      point.reason == null || point.reason!.isEmpty
                          ? point.studentName
                          : '${point.studentName} - ${point.reason}',
                      style: const pw.TextStyle(fontSize: 10, color: _ink),
                    ),
                  ),
                  pw.Text(
                    '+${_formatPoints(point.points)}',
                    style: pw.TextStyle(
                      fontSize: 10,
                      color: _ink,
                      fontWeight: pw.FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    ),
  ];
}

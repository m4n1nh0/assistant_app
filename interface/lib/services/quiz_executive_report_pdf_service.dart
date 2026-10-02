/// PDF do resumo executivo do quiz: uma pagina, so numeros agregados.
///
/// Para quem decide sem ter estado na sala. O veredito vem primeiro, depois os
/// indicadores, dois graficos (onde os alunos se concentram e como foi cada
/// pergunta) e, por ultimo, o que fazer. Nunca leva nome de aluno: quem precisa
/// dele tem o relatorio completo.
library;

import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../branding/intarq_brand.dart';
import 'pdf_common.dart';
import 'quiz_executive_summary.dart';
import 'quiz_report.dart';

PdfColor _toneColor(String tone) => switch (tone) {
      'bom' => pdfGood,
      'atencao' => pdfWarn,
      'critico' => pdfBad,
      _ => pdfInkSoft,
    };

PdfColor _rateColor(double percent) => percent >= goodRate
    ? pdfGood
    : percent >= warnRate
        ? pdfWarn
        : pdfBad;

PdfColor _verdictColor(Verdict verdict) => switch (verdict) {
      Verdict.bom => pdfGood,
      Verdict.atencao => pdfWarn,
      Verdict.critico => pdfBad,
      Verdict.semDados => pdfInkSoft,
    };

Future<Uint8List> buildQuizExecutiveReportPdf(
  QuizReport report, {
  DateTime? generatedAt,
}) async {
  final summary = buildExecutiveSummary(report);
  final document = pw.Document(
    title: 'Resumo executivo - ${report.titulo}',
    author: 'INTARQ',
  );
  final brandMark = await IntarqBrand.loadPdfMark();

  document.addPage(
    pw.MultiPage(
      pageTheme: pw.PageTheme(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.fromLTRB(36, 0, 36, 36),
        theme: await pdfTheme(),
      ),
      header: (context) => pdfBanner(
        kicker: 'Resumo executivo',
        title: report.titulo,
        subtitle: report.disciplinas.join(', '),
        details: [
          '${report.participantes} participantes',
          '${report.perguntasAplicadas} de ${report.totalQuestoes} perguntas aplicadas',
          if (report.encerradoEm != null)
            formatDate(report.encerradoEm)
          else if (report.criadoEm != null)
            formatDate(report.criadoEm),
        ],
        brandMark: brandMark,
      ),
      footer: pdfFooter,
      build: (context) => [
        pw.SizedBox(height: 14),
        _verdictStrip(summary),
        if (summary.verdict != Verdict.semDados || report.participantes > 0) ...[
          pw.SizedBox(height: 12),
          _kpis(report, summary),
        ],
        if (!report.semDados) ...[
          pw.SizedBox(height: 14),
          pw.Row(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Expanded(child: _bandsChart(summary)),
              pw.SizedBox(width: 16),
              pw.Expanded(flex: 2, child: _questionsChart(report)),
            ],
          ),
          if (summary.findings.isNotEmpty) ...[
            pdfSectionTitle('O que os números mostram'),
            for (final finding in summary.findings) _bullet(finding),
          ],
          pdfSectionTitle('O que fazer'),
          for (var i = 0; i < summary.recommendations.length; i++)
            _numbered(i + 1, summary.recommendations[i]),
        ],
        pw.SizedBox(height: 14),
        pw.Text(
          summary.caveat,
          style: const pw.TextStyle(fontSize: 7.5, color: pdfInkSoft, lineSpacing: 1.5),
        ),
      ],
    ),
  );

  return document.save();
}

/// A faixa do veredito: cor, rotulo e a frase que resume a turma.
pw.Widget _verdictStrip(ExecutiveSummary summary) {
  final color = _verdictColor(summary.verdict);
  return pw.Container(
    width: double.infinity,
    padding: const pw.EdgeInsets.fromLTRB(14, 12, 14, 12),
    decoration: pw.BoxDecoration(
      color: pdfPanel,
      border: pw.Border(
        left: pw.BorderSide(color: color, width: 5),
        top: const pw.BorderSide(color: pdfRule),
        right: const pw.BorderSide(color: pdfRule),
        bottom: const pw.BorderSide(color: pdfRule),
      ),
    ),
    child: pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.Text(
          summary.verdict.label.toUpperCase(),
          style: pw.TextStyle(
            fontSize: 9,
            letterSpacing: 2.2,
            color: color,
            fontWeight: pw.FontWeight.bold,
          ),
        ),
        pw.SizedBox(height: 5),
        pw.Text(
          summary.headline,
          style: pw.TextStyle(
            fontSize: 13,
            color: pdfInk,
            lineSpacing: 2,
            fontWeight: pw.FontWeight.bold,
          ),
        ),
      ],
    ),
  );
}

pw.Widget _kpis(QuizReport report, ExecutiveSummary summary) {
  pw.Widget tile(String value, String label, {PdfColor color = pdfInk}) =>
      pw.Expanded(
        child: pw.Container(
          margin: const pw.EdgeInsets.only(right: 8),
          padding: const pw.EdgeInsets.all(10),
          decoration: pw.BoxDecoration(
            color: pdfPanel,
            border: pw.Border.all(color: pdfRule),
          ),
          child: pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Text(
                value,
                style: pw.TextStyle(
                  fontSize: 17,
                  color: color,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              pw.SizedBox(height: 3),
              pw.Text(
                label.toUpperCase(),
                style: pw.TextStyle(
                  fontSize: 7,
                  letterSpacing: 1,
                  color: pdfInkSoft,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
      );

  return pw.Row(
    children: [
      tile(
        formatPercent(summary.participation),
        'Participação',
        color: summary.participation >= lowParticipationRate ? pdfInk : pdfWarn,
      ),
      tile(
        formatPercent(report.taxaAcerto),
        'Taxa de acerto',
        color: _rateColor(report.taxaAcerto),
      ),
      tile('${report.pontosMedios}', 'Pontos médios'),
      tile(formatSeconds(report.tempoMedioMs), 'Tempo por resposta'),
    ],
  );
}

/// Onde os alunos se concentram: barras horizontais por faixa de acerto.
pw.Widget _bandsChart(ExecutiveSummary summary) {
  final total = summary.bands.fold<int>(0, (sum, band) => sum + band.count);
  final max = summary.bands.fold<int>(0, (m, band) => band.count > m ? band.count : m);

  return pw.Column(
    crossAxisAlignment: pw.CrossAxisAlignment.start,
    children: [
      _chartTitle('Alunos por faixa de acerto'),
      pw.SizedBox(height: 6),
      for (final band in summary.bands)
        pw.Padding(
          padding: const pw.EdgeInsets.only(bottom: 6),
          child: pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Row(
                mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
                children: [
                  pw.Text(
                    band.label,
                    style: const pw.TextStyle(fontSize: 8, color: pdfInkSoft),
                  ),
                  pw.Text(
                    '${band.count}'
                    '${total == 0 ? '' : ' (${formatPercent(band.count / total * 100)})'}',
                    style: pw.TextStyle(
                      fontSize: 8,
                      color: pdfInk,
                      fontWeight: pw.FontWeight.bold,
                    ),
                  ),
                ],
              ),
              pw.SizedBox(height: 2),
              pw.Stack(
                children: [
                  pw.Container(height: 6, color: pdfHeader),
                  pw.LayoutBuilder(
                    builder: (context, constraints) => pw.Container(
                      height: 6,
                      width: max == 0
                          ? 0
                          : (constraints?.maxWidth ?? 0) * band.count / max,
                      color: _toneColor(band.tone),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
    ],
  );
}

/// Como foi cada pergunta: uma barra por pergunta, na cor da faixa.
pw.Widget _questionsChart(QuizReport report) {
  final questions = report.aplicadas;
  const chartHeight = 78.0;
  // Muita pergunta: o rotulo de todas nao cabe, so as de numero redondo.
  final labelEvery = questions.length <= 16 ? 1 : questions.length <= 32 ? 2 : 5;

  return pw.Column(
    crossAxisAlignment: pw.CrossAxisAlignment.start,
    children: [
      _chartTitle('Acerto por pergunta'),
      pw.SizedBox(height: 6),
      pw.Container(
        height: chartHeight + 14,
        padding: const pw.EdgeInsets.only(top: 4),
        decoration: const pw.BoxDecoration(
          border: pw.Border(bottom: pw.BorderSide(color: pdfRule)),
        ),
        child: pw.Row(
          crossAxisAlignment: pw.CrossAxisAlignment.end,
          children: [
            for (var i = 0; i < questions.length; i++)
              pw.Expanded(
                child: pw.Padding(
                  padding: const pw.EdgeInsets.symmetric(horizontal: 1.2),
                  child: pw.Column(
                    mainAxisAlignment: pw.MainAxisAlignment.end,
                    children: [
                      pw.Container(
                        height: (chartHeight * questions[i].percentual / 100).clamp(1.5, chartHeight),
                        color: _rateColor(questions[i].percentual),
                      ),
                      pw.SizedBox(
                        height: 10,
                        child: i % labelEvery == 0
                            ? pw.Center(
                                child: pw.Text(
                                  '${questions[i].indice + 1}',
                                  style: const pw.TextStyle(fontSize: 6, color: pdfInkSoft),
                                ),
                              )
                            : null,
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
      pw.SizedBox(height: 5),
      pw.Text(
        'Verde: ${formatPercent(goodRate)} ou mais   |   Âmbar: ${formatPercent(warnRate)} a '
        '${formatPercent(goodRate - 1)}   |   Vermelho: abaixo de ${formatPercent(warnRate)}',
        style: const pw.TextStyle(fontSize: 6.5, color: pdfInkSoft),
      ),
    ],
  );
}

pw.Widget _chartTitle(String text) => pw.Text(
      text.toUpperCase(),
      style: pw.TextStyle(
        fontSize: 8,
        letterSpacing: 1.3,
        color: pdfAccentDark,
        fontWeight: pw.FontWeight.bold,
      ),
    );

pw.Widget _bullet(String text) => pw.Padding(
      padding: const pw.EdgeInsets.only(bottom: 4),
      child: pw.Row(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          pw.Container(
            width: 3,
            height: 3,
            margin: const pw.EdgeInsets.only(top: 5, right: 7),
            decoration: const pw.BoxDecoration(
              color: pdfAccent,
              shape: pw.BoxShape.circle,
            ),
          ),
          pw.Expanded(
            child: pw.Text(
              text,
              style: const pw.TextStyle(fontSize: 10, color: pdfInk, lineSpacing: 1.8),
            ),
          ),
        ],
      ),
    );

pw.Widget _numbered(int number, String text) => pw.Padding(
      padding: const pw.EdgeInsets.only(bottom: 5),
      child: pw.Row(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          pw.SizedBox(
            width: 18,
            child: pw.Text(
              '$number.',
              style: pw.TextStyle(
                fontSize: 10,
                color: pdfAccentDark,
                fontWeight: pw.FontWeight.bold,
              ),
            ),
          ),
          pw.Expanded(
            child: pw.Text(
              text,
              style: const pw.TextStyle(fontSize: 10, color: pdfInk, lineSpacing: 1.8),
            ),
          ),
        ],
      ),
    );

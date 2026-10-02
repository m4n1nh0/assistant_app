/// PDF do relatorio de desempenho do quiz: a turma, cada pergunta e, se pedido, uma
/// folha por aluno.
///
/// Os numeros vem prontos do servidor (`QuizReport`); aqui so se diagrama. A folha
/// individual existe porque "o relatorio por aluno" e o que o professor entrega ou
/// guarda no historico do aluno: uma pagina que se destaca do conjunto.
library;

import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../branding/intarq_brand.dart';
import 'pdf_common.dart';
import 'quiz_report.dart';

/// O que o professor escolheu incluir no PDF do relatorio.
class ReportPdfOptions {
  /// Uma pagina por aluno, com o que ele respondeu pergunta a pergunta.
  final bool studentSheets;

  const ReportPdfOptions({this.studentSheets = true});
}

String _clip(String text, int limit) {
  final clean = text.replaceAll(RegExp(r'\s+'), ' ').trim();
  return clean.length <= limit ? clean : '${clean.substring(0, limit - 1).trimRight()}…';
}

PdfColor _rateColor(double percent) => percent >= 70
    ? pdfGood
    : percent >= 50
        ? pdfWarn
        : pdfBad;

Future<Uint8List> buildQuizReportPdf(
  QuizReport report, {
  ReportPdfOptions options = const ReportPdfOptions(),
  DateTime? generatedAt,
}) async {
  final document = pw.Document(
    title: 'Relatório do quiz - ${report.titulo}',
    author: 'INTARQ',
  );
  final brandMark = await IntarqBrand.loadPdfMark();
  final pageTheme = pw.PageTheme(
    pageFormat: PdfPageFormat.a4,
    margin: const pw.EdgeInsets.fromLTRB(36, 0, 36, 40),
    theme: await pdfTheme(),
  );
  final disciplina = report.disciplinas.join(', ');

  document.addPage(
    pw.MultiPage(
      pageTheme: pageTheme,
      header: (context) => context.pageNumber == 1
          ? pdfBanner(
              kicker: 'Relatório do quiz',
              title: report.titulo,
              subtitle: disciplina,
              details: [
                '${report.participantes} participantes',
                '${report.perguntasAplicadas} de ${report.totalQuestoes} perguntas aplicadas',
                if (report.encerradoEm != null)
                  'Encerrado em ${formatDateTime(report.encerradoEm)}'
                else if (report.criadoEm != null)
                  'Criado em ${formatDate(report.criadoEm)}',
              ],
              brandMark: brandMark,
            )
          : _runningHeader(report, brandMark),
      footer: pdfFooter,
      build: (context) => [
        pw.SizedBox(height: 14),
        if (report.semDados)
          pw.Text(
            'Ninguém participou deste quiz ainda.',
            style: const pw.TextStyle(fontSize: 11, color: pdfInkSoft),
          )
        else ...[
          _summary(report),
          ..._attention(report),
          pdfSectionTitle('Desempenho por aluno'),
          _studentsTable(report),
          if (report.aplicadas.isNotEmpty) ...[
            pdfSectionTitle('Análise por pergunta'),
            _questionsTable(report),
          ],
        ],
      ],
    ),
  );

  if (options.studentSheets && !report.semDados) {
    for (final student in report.alunos) {
      document.addPage(
        pw.Page(
          pageTheme: pageTheme,
          build: (context) => _studentSheet(report, student, brandMark),
        ),
      );
    }
  }

  return document.save();
}

pw.Widget _runningHeader(QuizReport report, pw.MemoryImage? brandMark) =>
    pw.Container(
      margin: const pw.EdgeInsets.only(bottom: 12),
      padding: const pw.EdgeInsets.only(top: 24, bottom: 6),
      decoration: const pw.BoxDecoration(
        border: pw.Border(bottom: pw.BorderSide(color: pdfRule)),
      ),
      child: pw.Row(
        mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
        children: [
          pw.Expanded(
            child: pw.Text(
              [
                if (report.disciplinas.isNotEmpty) report.disciplinas.join(', '),
                report.titulo,
                'Relatório do quiz',
              ].join('   |   '),
              style: const pw.TextStyle(fontSize: 8, color: pdfInkSoft),
            ),
          ),
          IntarqBrand.pdfSignature(brandMark, width: 82, height: 30),
        ],
      ),
    );

/// Indicadores da turma em quadros lado a lado.
pw.Widget _summary(QuizReport report) {
  pw.Widget tile(String value, String label, {PdfColor color = pdfInk}) =>
      pw.Expanded(
        child: pw.Container(
          margin: const pw.EdgeInsets.only(right: 8),
          padding: const pw.EdgeInsets.symmetric(horizontal: 10, vertical: 10),
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
      tile('${report.responderam}/${report.participantes}', 'Responderam'),
      tile(
        formatPercent(report.taxaAcerto),
        'Taxa de acerto',
        color: _rateColor(report.taxaAcerto),
      ),
      tile('${report.pontosMedios}', 'Pontos médios'),
      tile(formatSeconds(report.tempoMedioMs), 'Tempo médio'),
    ],
  );
}

/// O que merece a atencao do professor: perguntas que a turma errou e alunos que
/// precisam de apoio ou nem responderam.
List<pw.Widget> _attention(QuizReport report) {
  final hasAnything = report.perguntasEmAtencao.isNotEmpty ||
      report.alunosComDificuldade.isNotEmpty ||
      report.alunosSemResposta.isNotEmpty;
  if (!hasAnything) return const [];

  pw.Widget bullet(String text) => pw.Padding(
        padding: const pw.EdgeInsets.only(bottom: 3),
        child: pw.Row(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            pw.Container(
              width: 3,
              height: 3,
              margin: const pw.EdgeInsets.only(top: 5, right: 7),
              decoration: const pw.BoxDecoration(
                color: pdfWarn,
                shape: pw.BoxShape.circle,
              ),
            ),
            pw.Expanded(
              child: pw.Text(
                text,
                style: const pw.TextStyle(fontSize: 10, color: pdfInk, lineSpacing: 1.5),
              ),
            ),
          ],
        ),
      );

  return [
    pdfSectionTitle('Pontos de atenção'),
    pw.Container(
      width: double.infinity,
      padding: const pw.EdgeInsets.all(12),
      decoration: pw.BoxDecoration(
        color: pdfPanel,
        border: pw.Border.all(color: pdfRule),
      ),
      child: pw.Column(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          for (final question in report.perguntasEmAtencao)
            bullet(
              'Pergunta ${question.indice + 1} (${formatPercent(question.percentual)} '
              'de acerto): ${_clip(question.enunciado, 110)}'
              '${question.maisEscolhidaErrada == null ? '' : ' — a turma mais marcou ${question.maisEscolhidaErrada!.label}'
                  '${question.maisEscolhidaErrada!.texto.isEmpty ? '' : ' (${_clip(question.maisEscolhidaErrada!.texto, 40)})'}'}',
            ),
          if (report.alunosComDificuldade.isNotEmpty)
            bullet(
              'Acertaram menos da metade: ${report.alunosComDificuldade.join(', ')}.',
            ),
          if (report.alunosSemResposta.isNotEmpty)
            bullet(
              'Entraram e não responderam: ${report.alunosSemResposta.join(', ')}.',
            ),
        ],
      ),
    ),
  ];
}

pw.Widget _cell(
  String text, {
  pw.TextAlign align = pw.TextAlign.left,
  bool bold = false,
  PdfColor color = pdfInk,
}) =>
    pw.Padding(
      padding: const pw.EdgeInsets.symmetric(horizontal: 5, vertical: 4),
      child: pw.Text(
        text,
        textAlign: align,
        style: pw.TextStyle(
          fontSize: 9,
          color: color,
          fontWeight: bold ? pw.FontWeight.bold : pw.FontWeight.normal,
        ),
      ),
    );

pw.Widget _headCell(String text, {pw.TextAlign align = pw.TextAlign.left}) =>
    pw.Padding(
      padding: const pw.EdgeInsets.symmetric(horizontal: 5, vertical: 5),
      child: pw.Text(
        text.toUpperCase(),
        textAlign: align,
        style: pw.TextStyle(
          fontSize: 7,
          letterSpacing: 0.8,
          color: pdfAccentDark,
          fontWeight: pw.FontWeight.bold,
        ),
      ),
    );

pw.Widget _studentsTable(QuizReport report) {
  return pw.Table(
    border: const pw.TableBorder(
      horizontalInside: pw.BorderSide(color: pdfRule, width: 0.5),
      bottom: pw.BorderSide(color: pdfRule),
    ),
    columnWidths: const {
      0: pw.FixedColumnWidth(26),
      1: pw.FlexColumnWidth(4),
      2: pw.FixedColumnWidth(44),
      3: pw.FixedColumnWidth(46),
      4: pw.FixedColumnWidth(40),
      5: pw.FixedColumnWidth(58),
      6: pw.FixedColumnWidth(48),
    },
    children: [
      pw.TableRow(
        decoration: const pw.BoxDecoration(color: pdfHeader),
        children: [
          _headCell('#'),
          _headCell('Aluno'),
          _headCell('Pontos', align: pw.TextAlign.right),
          _headCell('Acertos', align: pw.TextAlign.right),
          _headCell('Erros', align: pw.TextAlign.right),
          _headCell('% acerto', align: pw.TextAlign.right),
          _headCell('Tempo', align: pw.TextAlign.right),
        ],
      ),
      for (final student in report.alunos)
        pw.TableRow(
          children: [
            _cell('${student.posicao}', color: pdfInkSoft),
            _cell(
              student.semNenhumaResposta ? '${student.nome} (não respondeu)' : student.nome,
              bold: true,
              color: student.semNenhumaResposta ? pdfInkSoft : pdfInk,
            ),
            _cell('${student.pontos}', align: pw.TextAlign.right),
            _cell(
              '${student.acertos}/${report.perguntasAplicadas}',
              align: pw.TextAlign.right,
            ),
            _cell('${student.erros}', align: pw.TextAlign.right),
            _cell(
              formatPercent(student.percentual),
              align: pw.TextAlign.right,
              bold: true,
              color: _rateColor(student.percentual),
            ),
            _cell(formatSeconds(student.tempoMedioMs), align: pw.TextAlign.right),
          ],
        ),
    ],
  );
}

pw.Widget _questionsTable(QuizReport report) {
  return pw.Table(
    border: const pw.TableBorder(
      horizontalInside: pw.BorderSide(color: pdfRule, width: 0.5),
      bottom: pw.BorderSide(color: pdfRule),
    ),
    columnWidths: const {
      0: pw.FixedColumnWidth(24),
      1: pw.FlexColumnWidth(5),
      2: pw.FixedColumnWidth(58),
      3: pw.FlexColumnWidth(2.6),
      4: pw.FixedColumnWidth(58),
    },
    children: [
      pw.TableRow(
        decoration: const pw.BoxDecoration(color: pdfHeader),
        children: [
          _headCell('#'),
          _headCell('Pergunta'),
          _headCell('% acerto', align: pw.TextAlign.right),
          _headCell('Mais marcada errada'),
          _headCell('Em branco', align: pw.TextAlign.right),
        ],
      ),
      for (final question in report.aplicadas)
        pw.TableRow(
          children: [
            _cell('${question.indice + 1}', color: pdfInkSoft),
            _cell(_clip(question.enunciado, 120)),
            _cell(
              formatPercent(question.percentual),
              align: pw.TextAlign.right,
              bold: true,
              color: _rateColor(question.percentual),
            ),
            _cell(
              question.maisEscolhidaErrada == null
                  ? '—'
                  : '${question.maisEscolhidaErrada!.label}) '
                      '${_clip(question.maisEscolhidaErrada!.texto, 22)}  '
                      '(${question.maisEscolhidaErrada!.quantidade})',
              color: pdfInkSoft,
            ),
            _cell('${question.semResposta}', align: pw.TextAlign.right),
          ],
        ),
    ],
  );
}

/// Uma pagina por aluno: posicao, pontos e o que respondeu em cada pergunta.
pw.Widget _studentSheet(
  QuizReport report,
  ReportStudent student,
  pw.MemoryImage? brandMark,
) {
  final byIndex = {for (final item in student.porPergunta) item.indice: item};

  return pw.Column(
    crossAxisAlignment: pw.CrossAxisAlignment.start,
    children: [
      pdfBanner(
        kicker: 'Desempenho do aluno',
        title: student.nome,
        subtitle: report.titulo,
        details: [
          if (report.disciplinas.isNotEmpty) report.disciplinas.join(', '),
          if (!student.semNenhumaResposta) '${student.posicao}º de ${report.participantes}',
          if (report.encerradoEm != null) formatDate(report.encerradoEm),
        ],
        brandMark: brandMark,
      ),
      pw.SizedBox(height: 14),
      pw.Row(
        children: [
          _sheetStat('${student.pontos}', 'Pontos'),
          _sheetStat(
            '${student.acertos}/${report.perguntasAplicadas}',
            'Acertos',
          ),
          _sheetStat(
            formatPercent(student.percentual),
            '% de acerto',
            color: _rateColor(student.percentual),
          ),
          _sheetStat(formatSeconds(student.tempoMedioMs), 'Tempo médio'),
        ],
      ),
      if (student.semNenhumaResposta)
        pw.Padding(
          padding: const pw.EdgeInsets.only(top: 14),
          child: pw.Text(
            'Entrou no quiz e não respondeu nenhuma pergunta.',
            style: const pw.TextStyle(fontSize: 10.5, color: pdfInkSoft),
          ),
        )
      else ...[
        pdfSectionTitle('Pergunta a pergunta'),
        pw.Table(
          border: const pw.TableBorder(
            horizontalInside: pw.BorderSide(color: pdfRule, width: 0.5),
            bottom: pw.BorderSide(color: pdfRule),
          ),
          columnWidths: const {
            0: pw.FixedColumnWidth(22),
            1: pw.FlexColumnWidth(4.5),
            2: pw.FlexColumnWidth(3),
            3: pw.FixedColumnWidth(62),
            4: pw.FixedColumnWidth(50),
          },
          children: [
            pw.TableRow(
              decoration: const pw.BoxDecoration(color: pdfHeader),
              children: [
                _headCell('#'),
                _headCell('Pergunta'),
                _headCell('Resposta do aluno'),
                _headCell('Resultado'),
                _headCell('Pontos', align: pw.TextAlign.right),
              ],
            ),
            for (final question in report.aplicadas)
              _sheetRow(question, byIndex[question.indice]),
          ],
        ),
      ],
    ],
  );
}

pw.Widget _sheetStat(String value, String label, {PdfColor color = pdfInk}) =>
    pw.Expanded(
      child: pw.Container(
        margin: const pw.EdgeInsets.only(right: 8),
        padding: const pw.EdgeInsets.symmetric(horizontal: 10, vertical: 10),
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

pw.TableRow _sheetRow(ReportQuestion question, ReportAnswer? answer) {
  final status = answer?.status ?? 'sem_resposta';
  final (label, color) = switch (status) {
    'acertou' => ('Acertou', pdfGood),
    'errou' => ('Errou', pdfBad),
    'pulou' => ('Pulou', pdfWarn),
    _ => ('Sem resposta', pdfInkSoft),
  };

  var chosen = '—';
  if (answer != null && answer.resposta.isNotEmpty) {
    final text = question.textoDe(answer.resposta);
    chosen = text.isEmpty
        ? answer.resposta
        : '${answer.resposta}) ${_clip(text, 46)}';
  }
  // Errou: mostra o que era certo, que e o que o aluno vai querer saber.
  final showKey = status == 'errou' || status == 'pulou' || status == 'sem_resposta';
  final keyText = question.textoDe(question.correta);
  final correctLine = showKey && question.correta.isNotEmpty
      ? 'Certa: ${question.correta}${keyText.isEmpty ? '' : ') ${_clip(keyText, 40)}'}'
      : '';

  return pw.TableRow(
    children: [
      _cell('${question.indice + 1}', color: pdfInkSoft),
      _cell(_clip(question.enunciado, 90)),
      pw.Padding(
        padding: const pw.EdgeInsets.symmetric(horizontal: 5, vertical: 4),
        child: pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            pw.Text(chosen, style: const pw.TextStyle(fontSize: 9, color: pdfInk)),
            if (correctLine.isNotEmpty)
              pw.Text(
                correctLine,
                style: const pw.TextStyle(fontSize: 8, color: pdfInkSoft),
              ),
          ],
        ),
      ),
      _cell(label, bold: true, color: color),
      _cell('${answer?.pontos ?? 0}', align: pw.TextAlign.right),
    ],
  );
}

/// PDF dos exercicios do quiz, para imprimir como prova ou lista de exercicios.
///
/// Sai em duas partes que o professor escolhe: a folha do aluno (perguntas e
/// alternativas, sem gabarito, com campos de nome, turma e data) e o gabarito em
/// pagina separada, que ele guarda. Misturar os dois no mesmo papel obrigaria a
/// imprimir duas vezes - e o gabarito na mesma folha que o aluno recebe nao serve
/// para prova.
library;

import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../branding/intarq_brand.dart';
import 'pdf_common.dart';

/// Uma alternativa como sai no papel.
class ExerciseOption {
  final String label;
  final String texto;
  final bool correta;

  const ExerciseOption({
    required this.label,
    required this.texto,
    this.correta = false,
  });
}

/// Uma pergunta como sai no papel.
class ExerciseQuestion {
  final String enunciado;
  final String tipo;
  final String dificuldade;
  final List<ExerciseOption> opcoes;
  final String respostaCorreta;
  final String justificativa;

  const ExerciseQuestion({
    required this.enunciado,
    this.tipo = 'multipla_escolha',
    this.dificuldade = '',
    this.opcoes = const [],
    this.respostaCorreta = '',
    this.justificativa = '',
  });

  /// Le a pergunta como o servidor a devolve (`GET /education/quiz/{id}`).
  factory ExerciseQuestion.fromJson(Map<String, dynamic> json) {
    final options = (json['opcoes'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => ExerciseOption(
              label: '${item['label'] ?? ''}',
              texto: '${item['texto'] ?? ''}',
              correta: item['correta'] == true,
            ))
        .toList();
    return ExerciseQuestion(
      enunciado: '${json['enunciado'] ?? ''}'.trim(),
      tipo: '${json['tipo'] ?? 'multipla_escolha'}',
      dificuldade: '${json['dificuldade'] ?? ''}',
      opcoes: options,
      respostaCorreta: '${json['resposta_correta'] ?? ''}'.trim(),
      justificativa: '${json['justificativa'] ?? ''}'.trim(),
    );
  }

  bool get ehMultiplaEscolha => tipo == 'multipla_escolha' && opcoes.isNotEmpty;
  bool get ehVerdadeiroFalso => tipo == 'verdadeiro_falso';

  /// Letra da alternativa correta, ou o texto esperado nos outros tipos.
  String get gabarito {
    if (ehMultiplaEscolha) {
      for (final option in opcoes) {
        if (option.correta) return option.label;
      }
    }
    if (ehVerdadeiroFalso) {
      final value = respostaCorreta.toLowerCase();
      return const {'verdadeiro', 'v', 'true', 'sim'}.contains(value)
          ? 'Verdadeiro'
          : 'Falso';
    }
    return respostaCorreta;
  }

  /// Texto da alternativa correta, para o gabarito comentado.
  String get textoDaCorreta {
    for (final option in opcoes) {
      if (option.correta) return option.texto;
    }
    return '';
  }
}

/// O que o professor escolheu incluir no PDF.
class ExercisesPdfOptions {
  /// Gabarito em pagina separada, no fim.
  final bool includeAnswerKey;

  /// Justificativa de cada pergunta no gabarito.
  final bool includeJustifications;

  /// Campos de nome, turma e data na primeira pagina.
  final bool studentFields;

  const ExercisesPdfOptions({
    this.includeAnswerKey = true,
    this.includeJustifications = false,
    this.studentFields = true,
  });
}

/// Uma linha do gabarito: numero, resposta e, se pedido, o texto e a justificativa.
class AnswerKeyLine {
  final int numero;
  final String resposta;
  final String texto;
  final String justificativa;

  const AnswerKeyLine({
    required this.numero,
    required this.resposta,
    this.texto = '',
    this.justificativa = '',
  });
}

/// Gabarito na ordem em que as perguntas saem no papel.
List<AnswerKeyLine> answerKeyLines(
  List<ExerciseQuestion> questions, {
  bool withJustifications = false,
}) =>
    [
      for (var i = 0; i < questions.length; i++)
        AnswerKeyLine(
          numero: i + 1,
          resposta: questions[i].gabarito,
          texto: questions[i].textoDaCorreta,
          justificativa: withJustifications ? questions[i].justificativa : '',
        ),
    ];

Future<Uint8List> buildQuizExercisesPdf({
  required String title,
  required List<ExerciseQuestion> questions,
  String discipline = '',
  ExercisesPdfOptions options = const ExercisesPdfOptions(),
  DateTime? generatedAt,
}) async {
  final document = pw.Document(title: title, author: 'INTARQ');
  final brandMark = await IntarqBrand.loadPdfMark();
  final theme = await pdfTheme();
  final pageTheme = pw.PageTheme(
    pageFormat: PdfPageFormat.a4,
    margin: const pw.EdgeInsets.fromLTRB(36, 0, 36, 40),
    theme: theme,
  );
  final details = [
    '${questions.length} questões',
    if (generatedAt != null) formatDate(generatedAt),
  ];

  document.addPage(
    pw.MultiPage(
      pageTheme: pageTheme,
      header: (context) => context.pageNumber == 1
          ? pdfBanner(
              kicker: 'Exercícios',
              title: title,
              subtitle: discipline,
              details: details,
              brandMark: brandMark,
            )
          : _runningHeader(title, discipline, brandMark),
      footer: pdfFooter,
      build: (context) => [
        pw.SizedBox(height: 14),
        if (options.studentFields) _studentFields(),
        pw.SizedBox(height: 10),
        if (questions.isEmpty)
          pw.Text(
            'Este quiz não tem perguntas.',
            style: const pw.TextStyle(fontSize: 11, color: pdfInkSoft),
          ),
        for (var i = 0; i < questions.length; i++)
          _questionBlock(i + 1, questions[i]),
      ],
    ),
  );

  if (options.includeAnswerKey && questions.isNotEmpty) {
    document.addPage(
      pw.MultiPage(
        pageTheme: pageTheme,
        header: (context) => _runningHeader(title, discipline, brandMark),
        footer: pdfFooter,
        build: (context) => _answerKey(
          answerKeyLines(
            questions,
            withJustifications: options.includeJustifications,
          ),
          withJustifications: options.includeJustifications,
        ),
      ),
    );
  }

  return document.save();
}

pw.Widget _runningHeader(
  String title,
  String discipline,
  pw.MemoryImage? brandMark,
) =>
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
              [if (discipline.isNotEmpty) discipline, title].join('   |   '),
              style: const pw.TextStyle(fontSize: 8, color: pdfInkSoft),
            ),
          ),
          IntarqBrand.pdfSignature(brandMark, width: 82, height: 30),
        ],
      ),
    );

/// Nome, turma, data e nota para o aluno preencher.
pw.Widget _studentFields() {
  pw.Widget field(String label, {double width = 0}) => pw.Expanded(
        flex: width == 0 ? 3 : width.toInt(),
        child: pw.Row(
          crossAxisAlignment: pw.CrossAxisAlignment.end,
          children: [
            pw.Text(
              '$label: ',
              style: pw.TextStyle(
                fontSize: 9,
                color: pdfInkSoft,
                fontWeight: pw.FontWeight.bold,
              ),
            ),
            pw.Expanded(
              child: pw.Container(
                height: 12,
                decoration: const pw.BoxDecoration(
                  border: pw.Border(bottom: pw.BorderSide(color: pdfInkSoft)),
                ),
              ),
            ),
          ],
        ),
      );

  return pw.Padding(
    padding: const pw.EdgeInsets.only(top: 6, bottom: 6),
    child: pw.Row(
      children: [
        field('Nome', width: 6),
        pw.SizedBox(width: 14),
        field('Turma', width: 2),
        pw.SizedBox(width: 14),
        field('Data', width: 2),
        pw.SizedBox(width: 14),
        field('Nota', width: 1),
      ],
    ),
  );
}

/// Uma pergunta inteira num bloco so: a pergunta nao se parte entre duas
/// paginas, com o enunciado numa e as alternativas na outra.
pw.Widget _questionBlock(int number, ExerciseQuestion question) {
  return pw.Container(
    margin: const pw.EdgeInsets.only(bottom: 14),
    child: pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.Row(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            pw.SizedBox(
              width: 24,
              child: pw.Text(
                '$number.',
                style: pw.TextStyle(
                  fontSize: 11,
                  color: pdfAccentDark,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
            ),
            pw.Expanded(
              child: pw.Text(
                question.enunciado,
                style: pw.TextStyle(
                  fontSize: 11,
                  color: pdfInk,
                  lineSpacing: 2,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
        pw.SizedBox(height: 6),
        if (question.ehMultiplaEscolha)
          for (final option in question.opcoes) _optionRow(option.label, option.texto)
        else if (question.ehVerdadeiroFalso) ...[
          _optionRow('', 'Verdadeiro'),
          _optionRow('', 'Falso'),
        ] else
          // Espaco de verdade para escrever: linhas finas e coladas nao dao.
          for (var i = 0; i < 4; i++)
            pw.Container(
              margin: const pw.EdgeInsets.only(left: 24, top: 20),
              height: 0.8,
              color: pdfInkSoft,
            ),
      ],
    ),
  );
}

pw.Widget _optionRow(String label, String text) => pw.Padding(
      padding: const pw.EdgeInsets.only(left: 24, bottom: 4),
      child: pw.Row(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          pw.Container(
            width: 14,
            height: 14,
            margin: const pw.EdgeInsets.only(right: 8, top: 0.5),
            alignment: pw.Alignment.center,
            decoration: pw.BoxDecoration(
              shape: pw.BoxShape.circle,
              border: pw.Border.all(color: pdfInkSoft, width: 0.8),
            ),
            child: label.isEmpty
                ? pw.SizedBox()
                : pw.Text(
                    label,
                    style: pw.TextStyle(
                      fontSize: 7.5,
                      color: pdfInkSoft,
                      fontWeight: pw.FontWeight.bold,
                    ),
                  ),
          ),
          pw.Expanded(
            child: pw.Text(
              text,
              style: const pw.TextStyle(fontSize: 10.5, color: pdfInk, lineSpacing: 1.5),
            ),
          ),
        ],
      ),
    );

List<pw.Widget> _answerKey(
  List<AnswerKeyLine> lines, {
  required bool withJustifications,
}) {
  return [
    pw.SizedBox(height: 14),
    pw.Container(
      width: double.infinity,
      padding: const pw.EdgeInsets.all(12),
      decoration: pw.BoxDecoration(
        color: pdfPanel,
        border: pw.Border.all(color: pdfRule),
      ),
      child: pw.Text(
        'GABARITO  |  uso do professor — não entregue esta página aos alunos',
        style: pw.TextStyle(
          fontSize: 9,
          letterSpacing: 1.4,
          color: pdfAccentDark,
          fontWeight: pw.FontWeight.bold,
        ),
      ),
    ),
    pw.SizedBox(height: 12),
    if (!withJustifications)
      // Compacto: "1  B", em grade, cabe a prova inteira numa olhada.
      pw.Wrap(
        spacing: 10,
        runSpacing: 8,
        children: [
          for (final line in lines)
            pw.Container(
              width: 70,
              padding: const pw.EdgeInsets.symmetric(horizontal: 8, vertical: 5),
              decoration: pw.BoxDecoration(
                border: pw.Border.all(color: pdfRule),
                borderRadius: const pw.BorderRadius.all(pw.Radius.circular(4)),
              ),
              child: pw.Row(
                mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
                children: [
                  pw.Text(
                    '${line.numero}',
                    style: const pw.TextStyle(fontSize: 9, color: pdfInkSoft),
                  ),
                  pw.Text(
                    line.resposta.isEmpty ? '—' : line.resposta,
                    style: pw.TextStyle(
                      fontSize: 11,
                      color: pdfInk,
                      fontWeight: pw.FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ),
        ],
      )
    else
      for (final line in lines)
        pw.Container(
          margin: const pw.EdgeInsets.only(bottom: 9),
          child: pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              pw.Text(
                '${line.numero}.  ${line.resposta.isEmpty ? '—' : line.resposta}'
                '${line.texto.isEmpty ? '' : '  —  ${line.texto}'}',
                style: pw.TextStyle(
                  fontSize: 10.5,
                  color: pdfInk,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              if (line.justificativa.isNotEmpty)
                pw.Padding(
                  padding: const pw.EdgeInsets.only(left: 18, top: 2),
                  child: pw.Text(
                    line.justificativa,
                    style: const pw.TextStyle(
                      fontSize: 9.5,
                      color: pdfInkSoft,
                      lineSpacing: 1.5,
                    ),
                  ),
                ),
            ],
          ),
        ),
  ];
}

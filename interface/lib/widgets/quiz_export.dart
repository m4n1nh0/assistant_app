/// Exportar os exercicios do quiz para PDF (prova, lista de exercicios).
///
/// O professor escolhe o que sai no papel - gabarito em pagina separada,
/// justificativas, campos do aluno - e depois salva o PDF ou imprime direto.
library;

import 'package:flutter/material.dart';

import '../services/quiz_center_service.dart';
import '../services/quiz_exercises_pdf_service.dart';
import '../services/quiz_report.dart';
import '../utils/theme.dart';
import 'pdf_preview_dialog.dart';

/// Como o professor quer o PDF dos exercicios, e o que fazer com ele.
enum ExportAction { save, print }

class ExerciseExportChoice {
  final ExercisesPdfOptions options;
  final ExportAction action;

  const ExerciseExportChoice(this.options, this.action);
}

/// Pergunta o que incluir e se salva ou imprime. `null` quando cancelou.
Future<ExerciseExportChoice?> askExerciseExport(
  BuildContext context, {
  required String title,
  required int questionCount,
}) {
  return showDialog<ExerciseExportChoice>(
    context: context,
    builder: (_) => _ExerciseExportDialog(
      title: title,
      questionCount: questionCount,
    ),
  );
}

class _ExerciseExportDialog extends StatefulWidget {
  final String title;
  final int questionCount;

  const _ExerciseExportDialog({
    required this.title,
    required this.questionCount,
  });

  @override
  State<_ExerciseExportDialog> createState() => _ExerciseExportDialogState();
}

class _ExerciseExportDialogState extends State<_ExerciseExportDialog> {
  bool _answerKey = true;
  bool _justifications = false;
  bool _studentFields = true;

  ExercisesPdfOptions get _options => ExercisesPdfOptions(
        includeAnswerKey: _answerKey,
        includeJustifications: _answerKey && _justifications,
        studentFields: _studentFields,
      );

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: const Text('Exportar exercícios em PDF'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${widget.title} · ${widget.questionCount} pergunta(s)',
              style: const TextStyle(color: AssistantTheme.textSecondary),
            ),
            const SizedBox(height: 12),
            CheckboxListTile(
              value: _studentFields,
              onChanged: (value) => setState(() => _studentFields = value ?? true),
              title: const Text('Campos de nome, turma, data e nota'),
              subtitle: const Text('Para o aluno preencher na prova.'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
            ),
            CheckboxListTile(
              value: _answerKey,
              onChanged: (value) => setState(() => _answerKey = value ?? true),
              title: const Text('Gabarito em página separada'),
              subtitle: const Text(
                'Fica no fim do arquivo: imprima só as primeiras páginas para a turma.',
              ),
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
            ),
            CheckboxListTile(
              value: _answerKey && _justifications,
              onChanged: _answerKey
                  ? (value) => setState(() => _justifications = value ?? false)
                  : null,
              title: const Text('Justificativas no gabarito'),
              subtitle: const Text('Gabarito comentado, com a alternativa correta por extenso.'),
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        OutlinedButton.icon(
          onPressed: () =>
              Navigator.pop(context, ExerciseExportChoice(_options, ExportAction.print)),
          icon: const Icon(Icons.print_outlined, size: 16),
          label: const Text('IMPRIMIR'),
        ),
        FilledButton.icon(
          onPressed: () =>
              Navigator.pop(context, ExerciseExportChoice(_options, ExportAction.save)),
          icon: const Icon(Icons.picture_as_pdf_outlined, size: 16),
          label: const Text('SALVAR PDF'),
        ),
      ],
    );
  }
}

void _snack(BuildContext context, String message, {bool error = false}) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      backgroundColor: error ? Colors.red : null,
    ),
  );
}

/// Fluxo completo: busca as perguntas, pergunta o que incluir, gera o PDF e salva
/// ou imprime.
Future<void> exportQuizExercises(
  BuildContext context, {
  required String quizId,
  String? title,
  String discipline = '',
  QuizCenterService? service,
}) async {
  final center = service ?? quizCenter;
  final Map<String, dynamic> quiz;
  try {
    quiz = await center.quizDetail(quizId);
  } catch (error) {
    if (context.mounted) _snack(context, 'Não abri o quiz: $error', error: true);
    return;
  }
  if (!context.mounted) return;

  final questions = [
    for (final item in (quiz['questoes'] as List? ?? const []).whereType<Map>())
      ExerciseQuestion.fromJson(Map<String, dynamic>.from(item)),
  ];
  final quizTitle = title ?? quiz['titulo']?.toString() ?? 'Quiz';
  if (questions.isEmpty) {
    _snack(context, 'Este quiz não tem perguntas para exportar.', error: true);
    return;
  }

  final choice = await askExerciseExport(
    context,
    title: quizTitle,
    questionCount: questions.length,
  );
  if (choice == null || !context.mounted) return;

  await previewAndDeliverPdf(
    context,
    build: () => buildQuizExercisesPdf(
      title: quizTitle,
      discipline: discipline,
      questions: questions,
      options: choice.options,
      generatedAt: DateTime.now(),
    ),
    fileName: quizFilename(quizTitle, suffix: 'exercicios'),
    saveDialogTitle: 'Salvar exercícios do quiz',
    title: 'PRÉ-VISUALIZAÇÃO · EXERCÍCIOS DO QUIZ',
    preferred: choice.action == ExportAction.print
        ? PdfDestination.print
        : PdfDestination.save,
  );
}

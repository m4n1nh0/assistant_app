/// Resumo conjunto das gravações marcadas no histórico.
///
/// Feito para o dia de apresentações de grupo: marca-se as gravações, escolhe-se o
/// formato e sai um resumo só, com uma seção por grupo e a comparação entre eles. Vale
/// também para aulas, palestras e reuniões. O resultado vai para o PDF com prévia.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/combined_summary.dart';
import '../services/education_service.dart';
import '../services/lesson_pdf_service.dart';
import '../utils/theme.dart';
import 'pdf_preview_dialog.dart';

Future<void> showCombinedSummaryDialog(
  BuildContext context, {
  required List<Lesson> lessons,
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: const EdgeInsets.all(20),
      child: CombinedSummaryPanel(lessons: lessons),
    ),
  );
}

/// "5 apresentações", "3 aulas e 2 palestras": o que há na seleção, em palavras.
String describeSelection(List<Lesson> lessons) {
  const names = {
    'aula': ('aula', 'aulas'),
    'apresentacao': ('apresentação', 'apresentações'),
    'palestra': ('palestra', 'palestras'),
    'reuniao': ('reunião', 'reuniões'),
  };
  final counts = <String, int>{};
  for (final lesson in lessons) {
    counts[lesson.kind] = (counts[lesson.kind] ?? 0) + 1;
  }
  final parts = [
    for (final kind in const ['apresentacao', 'aula', 'palestra', 'reuniao'])
      if ((counts[kind] ?? 0) > 0)
        '${counts[kind]} ${(counts[kind] == 1 ? names[kind]!.$1 : names[kind]!.$2)}',
  ];
  if (parts.length <= 1) return parts.join();
  return '${parts.sublist(0, parts.length - 1).join(', ')} e ${parts.last}';
}

String _date(DateTime? value) {
  if (value == null) return 'sem data';
  final local = value.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}/${two(local.month)} ${two(local.hour)}:${two(local.minute)}';
}

/// A barra acima da lista do histórico: marcar todas e pedir o resumo da seleção.
///
/// O resumo conjunto pede pelo menos duas gravações; com uma só, a barra diz que falta
/// mais uma.
class LessonSelectionBar extends StatelessWidget {
  final int count;
  final int total;
  final VoidCallback onToggleAll;
  final VoidCallback onSummarise;

  const LessonSelectionBar({
    super.key,
    required this.count,
    required this.total,
    required this.onToggleAll,
    required this.onSummarise,
  });

  @override
  Widget build(BuildContext context) {
    final all = total > 0 && count == total;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Wrap(
        spacing: 6,
        runSpacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          TextButton(
            key: const ValueKey('selecionar-todas'),
            onPressed: onToggleAll,
            child: Text(all ? 'LIMPAR' : 'SELECIONAR TODAS',
                style: const TextStyle(fontSize: 10)),
          ),
          FilledButton.icon(
            key: const ValueKey('resumo-da-selecao'),
            onPressed: count < 2 ? null : onSummarise,
            icon: const Icon(Icons.library_books_outlined, size: 14),
            label: Text(
              count < 2 ? 'RESUMO DA SELEÇÃO' : 'RESUMO DA SELEÇÃO ($count)',
              style: const TextStyle(fontSize: 10),
            ),
          ),
          if (count == 1)
            const Text('marque mais uma',
                key: ValueKey('dica-selecao'),
                style: TextStyle(fontSize: 10, color: AssistantTheme.textMuted)),
        ],
      ),
    );
  }
}

class CombinedSummaryPanel extends StatefulWidget {
  final List<Lesson> lessons;

  /// Trocam os serviços e o visualizador nos testes.
  final EducationService? service;
  final PdfPagesBuilder? pdfPages;
  final Future<void> Function(Uint8List bytes, {required String name})? printer;
  final Future<dynamic> Function({
    required Uint8List bytes,
    required String fileName,
    required String dialogTitle,
    required String extension,
  })? saver;

  const CombinedSummaryPanel({
    super.key,
    required this.lessons,
    this.service,
    this.pdfPages,
    this.printer,
    this.saver,
  });

  @override
  State<CombinedSummaryPanel> createState() => _CombinedSummaryPanelState();
}

class _CombinedSummaryPanelState extends State<CombinedSummaryPanel> {
  EducationService get _service => widget.service ?? education;

  final _focus = TextEditingController();
  String _style = summaryStyleStandard;
  bool _busy = false;
  bool _error = false;
  String _message = '';
  CombinedSummary? _result;

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  String _errorText(Object error) => error is EducationException
      ? error.message
      : '$error'.replaceFirst('Exception: ', '');

  Future<void> _generate() async {
    setState(() {
      _busy = true;
      _error = false;
      _message = _style == summaryStyleDetailed
          ? 'Gerando o resumo detalhado (leva mais tempo)...'
          : 'Gerando o resumo conjunto...';
    });
    try {
      final result = await _service.combinedSummary(
        [for (final lesson in widget.lessons) lesson.id],
        style: _style,
        focus: _focus.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _result = result;
        _message = '';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = true;
        _message = _errorText(e);
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copy(CombinedSummary result) async {
    await Clipboard.setData(ClipboardData(text: result.summary));
    if (!mounted) return;
    setState(() {
      _error = false;
      _message = 'Resumo copiado.';
    });
  }

  Future<void> _openPdf(CombinedSummary result) => previewAndDeliverPdf(
        context,
        build: () => buildCombinedSummaryPdf(
          combined: result,
          generatedAt: DateTime.now(),
        ),
        fileName: combinedPdfFilename(result),
        saveDialogTitle: 'Salvar resumo conjunto',
        title: 'PRÉ-VISUALIZAÇÃO · ${result.heading}',
        pages: widget.pdfPages,
        printer: widget.printer ?? defaultPdfPrinter,
        saver: widget.saver ?? defaultPdfSaver,
      );

  Widget _selectionList() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final lesson in widget.lessons)
          Padding(
            key: ValueKey('selecionada-${lesson.id}'),
            padding: const EdgeInsets.only(bottom: 3),
            child: Text(
              '${_date(lesson.startedAt)}  -  ${lesson.displayLabel}',
              style: const TextStyle(fontSize: 12),
            ),
          ),
      ],
    );
  }

  Widget _form() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'RESUMIR ${describeSelection(widget.lessons).toUpperCase()}',
          key: const ValueKey('descricao-selecao'),
          style: const TextStyle(
              fontSize: 10, letterSpacing: 1.5, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 6),
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 190),
          child: SingleChildScrollView(child: _selectionList()),
        ),
        const SizedBox(height: 12),
        SegmentedButton<String>(
          key: const ValueKey('formato'),
          segments: const [
            ButtonSegment(value: summaryStyleStandard, label: Text('Comum')),
            ButtonSegment(value: summaryStyleDetailed, label: Text('Detalhado')),
          ],
          selected: {_style},
          onSelectionChanged:
              _busy ? null : (value) => setState(() => _style = value.first),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const ValueKey('foco'),
          controller: _focus,
          maxLength: 500,
          decoration: const InputDecoration(
            labelText: 'Foco do resumo (opcional)',
            hintText: 'ex.: tecnologias usadas por cada grupo',
            counterText: '',
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'A gravação que ainda não tem resumo é resumida agora, só para este '
          'documento: a gravação em si não muda.',
          key: ValueKey('aviso-sem-resumo'),
          style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 10),
        FilledButton.icon(
          key: const ValueKey('gerar'),
          onPressed: _busy ? null : _generate,
          icon: const Icon(Icons.auto_awesome, size: 16),
          label: Text(_result == null ? 'GERAR RESUMO' : 'GERAR DE NOVO'),
        ),
      ],
    );
  }

  Widget _resultView(CombinedSummary result) {
    const muted = TextStyle(fontSize: 11, color: AssistantTheme.textMuted);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 18),
        Text(result.heading,
            key: const ValueKey('titulo-resultado'),
            style: const TextStyle(
                fontSize: 10, letterSpacing: 1.5, color: AssistantTheme.textMuted)),
        const SizedBox(height: 4),
        Text(result.title,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        if (result.subtitle.isNotEmpty) Text(result.subtitle, style: muted),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 4, children: [
          OutlinedButton.icon(
            key: const ValueKey('abrir-previa'),
            onPressed: () => _openPdf(result),
            icon: const Icon(Icons.picture_as_pdf_outlined, size: 16),
            label: const Text('PDF COM PRÉVIA'),
          ),
          OutlinedButton.icon(
            key: const ValueKey('copiar'),
            onPressed: () => _copy(result),
            icon: const Icon(Icons.copy, size: 16),
            label: const Text('COPIAR'),
          ),
        ]),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            border: Border.all(color: AssistantTheme.border),
            borderRadius: BorderRadius.circular(4),
          ),
          child: SelectableText(
            result.summary,
            key: const ValueKey('resumo-conjunto'),
            style: const TextStyle(fontSize: 12.5, height: 1.5),
          ),
        ),
        const SizedBox(height: 10),
        Text('Gravações incluídas', style: muted),
        for (final item in result.items)
          Text('• ${item.label} — ${item.sourceLabel}',
              key: ValueKey('incluida-${item.id}'),
              style: const TextStyle(fontSize: 11)),
        for (final item in result.skipped)
          Text('• Ficou de fora: ${item.label} — ${item.reason}',
              key: ValueKey('fora-${item.id}'),
              style: const TextStyle(fontSize: 11, color: AssistantTheme.danger)),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final result = _result;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 760, maxHeight: 780),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Expanded(
                child: Text('RESUMO DA SELEÇÃO',
                    style: TextStyle(
                        fontWeight: FontWeight.bold, letterSpacing: 1.5)),
              ),
              IconButton(
                key: const ValueKey('fechar'),
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close),
              ),
            ]),
            if (_busy) const LinearProgressIndicator(minHeight: 2),
            if (_message.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_message,
                    key: const ValueKey('mensagem'),
                    style: TextStyle(
                        fontSize: 12,
                        color: _error ? AssistantTheme.danger : AssistantTheme.c3)),
              ),
            const SizedBox(height: 10),
            Expanded(
              child: ListView(children: [
                _form(),
                if (result != null) _resultView(result),
              ]),
            ),
          ],
        ),
      ),
    );
  }
}

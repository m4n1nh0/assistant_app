/// Relatorio de desempenho do quiz: quem foi bem, quem precisa de apoio e quais
/// perguntas a turma errou.
///
/// Mesmos numeros do PDF e da planilha: o servidor faz as contas, e as tres saidas
/// so apresentam. Cores do tema escuro de ponta a ponta, texto legivel sobre
/// fundo escuro.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../services/pdf_common.dart';
import '../services/quiz_center_service.dart';
import '../services/quiz_executive_report_pdf_service.dart';
import '../services/quiz_executive_summary.dart';
import '../services/quiz_report.dart';
import '../services/quiz_report_pdf_service.dart';
import '../utils/theme.dart';
import 'quiz_export.dart' show ExportAction;

/// Qual PDF exportar: o relatorio completo (com nomes) ou o resumo executivo
/// (uma pagina, so numeros agregados).
enum ReportKind { complete, executive }

/// Abre o relatorio do quiz.
Future<void> showQuizReportDialog(
  BuildContext context, {
  required String quizId,
  String title = '',
  QuizCenterService? service,
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => Dialog(
      backgroundColor: AssistantTheme.surface,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 980, maxHeight: 720),
        child: QuizReportView(quizId: quizId, title: title, service: service),
      ),
    ),
  );
}

Color rateColor(double percent) => percent >= 70
    ? Colors.greenAccent.shade400
    : percent >= 50
        ? Colors.orangeAccent
        : Colors.redAccent;

class QuizReportView extends StatefulWidget {
  final String quizId;
  final String title;
  final QuizCenterService? service;

  const QuizReportView({
    super.key,
    required this.quizId,
    this.title = '',
    this.service,
  });

  @override
  State<QuizReportView> createState() => _QuizReportViewState();
}

class _QuizReportViewState extends State<QuizReportView> {
  QuizReport? _report;
  String _error = '';
  bool _loading = true;
  bool _exporting = false;

  QuizCenterService get _service => widget.service ?? quizCenter;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final report = await _service.quizReport(widget.quizId);
      if (mounted) setState(() => _report = report);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _snack(String message, {bool error = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: error ? Colors.red : null),
    );
  }

  Future<void> _exportPdf() async {
    final report = _report;
    if (report == null || _exporting) return;
    final choice = await showDialog<({ReportKind kind, bool sheets, ExportAction action})>(
      context: context,
      builder: (_) => const _ReportExportDialog(),
    );
    if (choice == null || !mounted) return;

    setState(() => _exporting = true);
    try {
      final executive = choice.kind == ReportKind.executive;
      final bytes = executive
          ? await buildQuizExecutiveReportPdf(report, generatedAt: DateTime.now())
          : await buildQuizReportPdf(
              report,
              options: ReportPdfOptions(studentSheets: choice.sheets),
              generatedAt: DateTime.now(),
            );
      final fileName = quizFilename(
        report.titulo,
        suffix: executive ? 'resumo-executivo' : 'relatorio',
      );
      if (choice.action == ExportAction.print) {
        await printPdf(bytes, name: fileName);
        return;
      }
      final file = await saveBytes(
        bytes: bytes,
        fileName: fileName,
        dialogTitle: 'Salvar relatório do quiz',
        extension: 'pdf',
      );
      if (file != null && mounted) _snack('PDF salvo em ${file.path}');
    } catch (error) {
      if (mounted) _snack('Falha ao gerar o PDF: $error', error: true);
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<void> _exportCsv() async {
    final report = _report;
    if (report == null || _exporting) return;
    setState(() => _exporting = true);
    try {
      final bytes = Uint8List.fromList(utf8.encode(quizReportCsv(report)));
      final file = await saveBytes(
        bytes: bytes,
        fileName: quizFilename(report.titulo, suffix: 'resultados', extension: 'csv'),
        dialogTitle: 'Salvar planilha do quiz',
        extension: 'csv',
      );
      if (file != null && mounted) _snack('Planilha salva em ${file.path}');
    } catch (error) {
      if (mounted) _snack('Falha ao gerar a planilha: $error', error: true);
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final report = _report;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _header(report),
        if (_loading) const LinearProgressIndicator(minHeight: 2),
        if (_error.isNotEmpty)
          Padding(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Não consegui carregar o relatório: $_error',
                    style: const TextStyle(color: AssistantTheme.danger),
                  ),
                ),
                TextButton(onPressed: _load, child: const Text('Tentar de novo')),
              ],
            ),
          ),
        if (report != null) Expanded(child: _body(report)),
      ],
    );
  }

  Widget _header(QuizReport? report) {
    final title = report?.titulo.isNotEmpty == true ? report!.titulo : widget.title;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 10),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Relatório do quiz',
                  style: TextStyle(
                    fontSize: 12,
                    letterSpacing: 1.4,
                    color: AssistantTheme.textSecondary,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 19,
                    fontWeight: FontWeight.bold,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
                if (report != null && report.disciplinas.isNotEmpty)
                  Text(
                    report.disciplinas.join(', '),
                    style: const TextStyle(color: AssistantTheme.textSecondary),
                  ),
              ],
            ),
          ),
          OutlinedButton.icon(
            onPressed: report == null || report.semDados || _exporting ? null : _exportCsv,
            icon: const Icon(Icons.table_chart_outlined, size: 16),
            label: const Text('PLANILHA'),
          ),
          const SizedBox(width: 8),
          FilledButton.icon(
            onPressed: report == null || report.semDados || _exporting ? null : _exportPdf,
            icon: _exporting
                ? const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.picture_as_pdf_outlined, size: 16),
            label: const Text('PDF'),
          ),
          IconButton(
            tooltip: 'Fechar',
            icon: const Icon(Icons.close),
            onPressed: () => Navigator.pop(context),
          ),
        ],
      ),
    );
  }

  Widget _body(QuizReport report) {
    if (report.semDados) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Text(
            'Ninguém participou deste quiz ainda.',
            style: TextStyle(color: AssistantTheme.textSecondary, fontSize: 15),
          ),
        ),
      );
    }

    return DefaultTabController(
      length: 3,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _summaryTiles(report),
                _attention(report),
              ],
            ),
          ),
          TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: [
              Tab(text: 'Alunos (${report.alunos.length})'),
              Tab(text: 'Perguntas (${report.aplicadas.length})'),
              const Tab(text: 'Resumo executivo'),
            ],
          ),
          Expanded(
            child: TabBarView(
              children: [
                _studentsTab(report),
                _questionsTab(report),
                _executiveTab(report),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _summaryTiles(QuizReport report) {
    Widget tile(String value, String label, {Color? color}) => Container(
          width: 168,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AssistantTheme.surface2,
            border: Border.all(color: AssistantTheme.border2),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: color ?? AssistantTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                label,
                style: const TextStyle(
                  fontSize: 12,
                  color: AssistantTheme.textSecondary,
                ),
              ),
            ],
          ),
        );

    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        tile('${report.responderam}/${report.participantes}', 'responderam'),
        tile(
          formatPercent(report.taxaAcerto),
          'taxa de acerto',
          color: rateColor(report.taxaAcerto),
        ),
        tile('${report.pontosMedios}', 'pontos médios'),
        tile(formatSeconds(report.tempoMedioMs), 'tempo médio por resposta'),
        tile(
          '${report.perguntasAplicadas}/${report.totalQuestoes}',
          'perguntas aplicadas',
        ),
      ],
    );
  }

  Widget _attention(QuizReport report) {
    final lines = <Widget>[];
    Widget line(IconData icon, String text) => Padding(
          padding: const EdgeInsets.only(top: 5),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: 15, color: Colors.orangeAccent),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  text,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
              ),
            ],
          ),
        );

    for (final question in report.perguntasEmAtencao) {
      final wrong = question.maisEscolhidaErrada;
      lines.add(line(
        Icons.help_outline,
        'Pergunta ${question.indice + 1} — só ${formatPercent(question.percentual)} '
        'acertaram: ${_clip(question.enunciado, 100)}'
        '${wrong == null ? '' : ' (a turma mais marcou ${wrong.label})'}',
      ));
    }
    if (report.alunosComDificuldade.isNotEmpty) {
      lines.add(line(
        Icons.person_search_outlined,
        'Acertaram menos da metade: ${report.alunosComDificuldade.join(', ')}',
      ));
    }
    if (report.alunosSemResposta.isNotEmpty) {
      lines.add(line(
        Icons.person_off_outlined,
        'Entraram e não responderam: ${report.alunosSemResposta.join(', ')}',
      ));
    }
    if (lines.isEmpty) return const SizedBox.shrink();

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: BoxDecoration(
        color: Colors.orange.withValues(alpha: 0.10),
        border: Border.all(color: Colors.orangeAccent.withValues(alpha: 0.6)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'PONTOS DE ATENÇÃO',
            style: TextStyle(
              fontSize: 11,
              letterSpacing: 1.4,
              fontWeight: FontWeight.bold,
              color: Colors.orangeAccent,
            ),
          ),
          ...lines,
        ],
      ),
    );
  }

  String _clip(String text, int limit) {
    final clean = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    return clean.length <= limit ? clean : '${clean.substring(0, limit - 1).trimRight()}…';
  }

  Widget _studentsTab(QuizReport report) {
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
      itemCount: report.alunos.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (_, index) => _studentTile(report, report.alunos[index]),
    );
  }

  Widget _studentTile(QuizReport report, ReportStudent student) {
    final byIndex = {for (final item in student.porPergunta) item.indice: item};
    return ExpansionTile(
      tilePadding: const EdgeInsets.symmetric(horizontal: 8),
      leading: SizedBox(
        width: 34,
        child: Text(
          '#${student.posicao}',
          style: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.bold,
            color: AssistantTheme.textSecondary,
          ),
        ),
      ),
      title: Text(
        student.semNenhumaResposta ? '${student.nome} (não respondeu)' : student.nome,
        style: TextStyle(
          fontWeight: FontWeight.w600,
          color: student.semNenhumaResposta
              ? AssistantTheme.textSecondary
              : AssistantTheme.textPrimary,
        ),
      ),
      subtitle: Text(
        '${student.pontos} pts · ${student.acertos}/${report.perguntasAplicadas} acertos'
        ' · ${formatSeconds(student.tempoMedioMs)} por resposta',
        style: const TextStyle(color: AssistantTheme.textSecondary, fontSize: 12),
      ),
      trailing: Text(
        formatPercent(student.percentual),
        style: TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.bold,
          color: rateColor(student.percentual),
        ),
      ),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(42, 0, 8, 12),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final question in report.aplicadas)
                  _answerChip(question, byIndex[question.indice]),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _answerChip(ReportQuestion question, ReportAnswer? answer) {
    final status = answer?.status ?? 'sem_resposta';
    final color = switch (status) {
      'acertou' => Colors.greenAccent.shade400,
      'errou' => Colors.redAccent,
      'pulou' => Colors.orangeAccent,
      _ => AssistantTheme.textMuted,
    };
    final text = answer == null ? '—' : answerCell(answer);
    return Tooltip(
      message: _clip(question.enunciado, 140),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          border: Border.all(color: color),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(
          'P${question.indice + 1}  $text',
          style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }

  /// O mesmo resumo que vai no PDF executivo: veredito, faixas, constatacoes e o
  /// que fazer. Sem nome de aluno.
  Widget _executiveTab(QuizReport report) {
    final summary = buildExecutiveSummary(report);
    final color = switch (summary.verdict) {
      Verdict.bom => Colors.greenAccent.shade400,
      Verdict.atencao => Colors.orangeAccent,
      Verdict.critico => Colors.redAccent,
      Verdict.semDados => AssistantTheme.textSecondary,
    };
    final total = summary.bands.fold<int>(0, (sum, band) => sum + band.count);
    final maxCount =
        summary.bands.fold<int>(0, (m, band) => band.count > m ? band.count : m);

    Widget title(String text) => Padding(
          padding: const EdgeInsets.only(top: 18, bottom: 8),
          child: Text(
            text.toUpperCase(),
            style: const TextStyle(
              fontSize: 11,
              letterSpacing: 1.4,
              fontWeight: FontWeight.bold,
              color: AssistantTheme.textSecondary,
            ),
          ),
        );

    Widget bullet(String text, {Color dot = AssistantTheme.c1}) => Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 6, right: 10),
                child: Icon(Icons.circle, size: 6, color: dot),
              ),
              Expanded(
                child: Text(
                  text,
                  style: const TextStyle(
                    fontSize: 13.5,
                    height: 1.4,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
              ),
            ],
          ),
        );

    Color toneColor(String tone) => switch (tone) {
          'bom' => Colors.greenAccent.shade400,
          'atencao' => Colors.orangeAccent,
          'critico' => Colors.redAccent,
          _ => AssistantTheme.textMuted,
        };

    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 20),
      children: [
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AssistantTheme.surface2,
            // Faixa lateral colorida: borda de cores diferentes nao combina com
            // cantos arredondados (o Flutter recusa na hora de pintar).
            border: Border(
              left: BorderSide(color: color, width: 5),
              top: const BorderSide(color: AssistantTheme.border2),
              right: const BorderSide(color: AssistantTheme.border2),
              bottom: const BorderSide(color: AssistantTheme.border2),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                summary.verdict.label.toUpperCase(),
                style: TextStyle(
                  fontSize: 11,
                  letterSpacing: 2,
                  fontWeight: FontWeight.bold,
                  color: color,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                summary.headline,
                style: const TextStyle(
                  fontSize: 16,
                  height: 1.35,
                  fontWeight: FontWeight.w700,
                  color: AssistantTheme.textPrimary,
                ),
              ),
            ],
          ),
        ),
        title('Alunos por faixa de acerto'),
        for (final band in summary.bands)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                SizedBox(
                  width: 130,
                  child: Text(
                    band.label,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AssistantTheme.textSecondary,
                    ),
                  ),
                ),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(3),
                    child: LinearProgressIndicator(
                      minHeight: 10,
                      value: maxCount == 0 ? 0 : band.count / maxCount,
                      backgroundColor: AssistantTheme.surface2,
                      color: toneColor(band.tone),
                    ),
                  ),
                ),
                SizedBox(
                  width: 90,
                  child: Text(
                    '${band.count}'
                    '${total == 0 ? '' : ' (${formatPercent(band.count / total * 100)})'}',
                    textAlign: TextAlign.right,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AssistantTheme.textPrimary,
                    ),
                  ),
                ),
              ],
            ),
          ),
        if (summary.findings.isNotEmpty) title('O que os números mostram'),
        for (final finding in summary.findings) bullet(finding),
        if (summary.recommendations.isNotEmpty) title('O que fazer'),
        for (var i = 0; i < summary.recommendations.length; i++)
          bullet('${i + 1}. ${summary.recommendations[i]}', dot: Colors.orangeAccent),
        const SizedBox(height: 16),
        Text(
          summary.caveat,
          style: const TextStyle(
            fontSize: 11.5,
            height: 1.4,
            color: AssistantTheme.textSecondary,
          ),
        ),
      ],
    );
  }

  Widget _questionsTab(QuizReport report) {
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
      itemCount: report.aplicadas.length,
      separatorBuilder: (_, __) => const Divider(height: 24),
      itemBuilder: (_, index) => _questionTile(report.aplicadas[index]),
    );
  }

  Widget _questionTile(ReportQuestion question) {
    final maxCount = question.distribuicao.fold<int>(
      0,
      (max, option) => option.quantidade > max ? option.quantidade : max,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 34,
                child: Text(
                  'P${question.indice + 1}',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    color: AssistantTheme.textSecondary,
                  ),
                ),
              ),
              Expanded(
                child: Text(
                  question.enunciado,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Text(
                formatPercent(question.percentual),
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: rateColor(question.percentual),
                ),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(left: 34, top: 4, bottom: 8),
            child: Text(
              '${question.acertos} acertaram · ${question.erros} erraram'
              '${question.semResposta > 0 ? ' · ${question.semResposta} em branco' : ''}'
              ' · ${formatSeconds(question.tempoMedioMs)} por resposta',
              style: const TextStyle(fontSize: 12, color: AssistantTheme.textSecondary),
            ),
          ),
          for (final option in question.distribuicao)
            Padding(
              padding: const EdgeInsets.only(left: 34, bottom: 4),
              child: Row(
                children: [
                  SizedBox(
                    width: 22,
                    child: Text(
                      option.label,
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: option.correta
                            ? Colors.greenAccent.shade400
                            : AssistantTheme.textSecondary,
                      ),
                    ),
                  ),
                  Expanded(
                    flex: 5,
                    child: Text(
                      option.texto,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 13,
                        color: option.correta
                            ? Colors.greenAccent.shade400
                            : AssistantTheme.textPrimary,
                        fontWeight: option.correta ? FontWeight.w700 : FontWeight.normal,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    flex: 3,
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(3),
                      child: LinearProgressIndicator(
                        minHeight: 8,
                        value: maxCount == 0 ? 0 : option.quantidade / maxCount,
                        backgroundColor: AssistantTheme.surface2,
                        color: option.correta
                            ? Colors.greenAccent.shade400
                            : Colors.redAccent.withValues(alpha: 0.75),
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 30,
                    child: Text(
                      '${option.quantidade}',
                      textAlign: TextAlign.right,
                      style: const TextStyle(color: AssistantTheme.textPrimary),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _ReportExportDialog extends StatefulWidget {
  const _ReportExportDialog();

  @override
  State<_ReportExportDialog> createState() => _ReportExportDialogState();
}

class _ReportExportDialogState extends State<_ReportExportDialog> {
  ReportKind _kind = ReportKind.complete;
  bool _sheets = true;

  void _finish(ExportAction action) =>
      Navigator.pop(context, (kind: _kind, sheets: _sheets, action: action));

  @override
  Widget build(BuildContext context) {
    final complete = _kind == ReportKind.complete;
    return AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: const Text('Exportar relatório em PDF'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            RadioGroup<ReportKind>(
              groupValue: _kind,
              onChanged: (value) => setState(() => _kind = value ?? _kind),
              child: const Column(
                children: [
                  RadioListTile<ReportKind>(
                    value: ReportKind.complete,
                    title: Text('Relatório completo'),
                    subtitle: Text(
                      'Todos os alunos, pergunta a pergunta, com nomes. Para o '
                      'professor.',
                    ),
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                  ),
                  RadioListTile<ReportKind>(
                    value: ReportKind.executive,
                    title: Text('Resumo executivo'),
                    subtitle: Text(
                      'Uma página: veredito, indicadores, gráficos e o que fazer. '
                      'Só números agregados, sem nome de aluno — para coordenação '
                      'ou direção.',
                    ),
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                  ),
                ],
              ),
            ),
            if (complete) ...[
              const Divider(height: 20),
              CheckboxListTile(
                value: _sheets,
                onChanged: (value) => setState(() => _sheets = value ?? true),
                title: const Text('Uma folha por aluno'),
                subtitle: const Text(
                  'Posição, pontos e o que cada aluno respondeu, numa página que '
                  'se destaca do conjunto.',
                ),
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        OutlinedButton.icon(
          onPressed: () => _finish(ExportAction.print),
          icon: const Icon(Icons.print_outlined, size: 16),
          label: const Text('IMPRIMIR'),
        ),
        FilledButton.icon(
          onPressed: () => _finish(ExportAction.save),
          icon: const Icon(Icons.picture_as_pdf_outlined, size: 16),
          label: const Text('SALVAR PDF'),
        ),
      ],
    );
  }
}

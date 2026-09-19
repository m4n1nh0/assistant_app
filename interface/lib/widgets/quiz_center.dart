/// Central de quizzes: fila de geracao, quizzes gravados e banco de questoes.
///
/// O fluxo de um quiz tem estados definidos, e cada tela so oferece a acao que
/// faz sentido no estado em que ele esta:
///
///   pedido:  na fila -> gerando -> pronto | com erro | cancelado
///   quiz:    rascunho -> liberado -> encerrado
///
/// Pedido pronto vira rascunho para revisar; rascunho e liberado pelo QR Code;
/// questoes de qualquer quiz ficam no banco para consultar, corrigir e montar
/// quizzes novos sem chamar a IA.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../services/quiz_center_service.dart';
import '../services/quiz_queue_watcher.dart';
import '../utils/theme.dart';
import 'quiz_preview_dialog.dart';
import 'quiz_qrcode_monitor.dart';

// --- rotulos ---------------------------------------------------------------

String jobStatusLabel(String status) => switch (status) {
      QuizJobStatus.queued => 'NA FILA',
      QuizJobStatus.running => 'GERANDO',
      QuizJobStatus.done => 'PRONTO',
      QuizJobStatus.error => 'COM ERRO',
      QuizJobStatus.canceled => 'CANCELADO',
      _ => status.toUpperCase(),
    };

Color jobStatusColor(String status) => switch (status) {
      QuizJobStatus.queued => AssistantTheme.textSecondary,
      QuizJobStatus.running => AssistantTheme.c1,
      QuizJobStatus.done => AssistantTheme.c3,
      QuizJobStatus.error => AssistantTheme.danger,
      _ => AssistantTheme.textMuted,
    };

String quizStatusLabel(String status) => switch (status) {
      QuizStatus.draft => 'RASCUNHO',
      QuizStatus.open => 'LIBERADO',
      QuizStatus.closed => 'ENCERRADO',
      _ => status.toUpperCase(),
    };

Color quizStatusColor(String status) => switch (status) {
      QuizStatus.draft => AssistantTheme.c4,
      QuizStatus.open => AssistantTheme.c3,
      _ => AssistantTheme.textMuted,
    };

String difficultyLabel(String value) => switch (value) {
      'facil' => 'Fácil',
      'medio' => 'Médio',
      'dificil' => 'Difícil',
      _ => value,
    };

String _when(DateTime? value) {
  if (value == null) return '';
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(value.day)}/${two(value.month)} ${two(value.hour)}:${two(value.minute)}';
}

void _snack(BuildContext context, String message, {bool error = false}) {
  final messenger = ScaffoldMessenger.maybeOf(context);
  messenger?.showSnackBar(SnackBar(
    content: Text(message),
    backgroundColor: error ? AssistantTheme.danger : null,
  ));
}

class _StatusChip extends StatelessWidget {
  final String label;
  final Color color;
  const _StatusChip(this.label, this.color);

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(
          border: Border.all(color: color),
          borderRadius: BorderRadius.circular(3),
        ),
        child: Text(
          label,
          style: TextStyle(fontSize: 9, letterSpacing: 1, color: color),
        ),
      );
}

class _Empty extends StatelessWidget {
  final IconData icon;
  final String text;
  const _Empty(this.icon, this.text);

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 34, color: AssistantTheme.textMuted),
              const SizedBox(height: 10),
              Text(
                text,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 12, color: AssistantTheme.textSecondary),
              ),
            ],
          ),
        ),
      );
}

// --- revisao ---------------------------------------------------------------

/// Abre a revisao de um quiz gravado, com as acoes do estado em que ele esta.
///
/// Rascunho: liberar o QR Code ou descartar. Liberado: abrir o QR. Encerrado:
/// so consulta. `onChanged` avisa quem abriu que o quiz mudou de estado.
Future<void> openQuizReview(
  BuildContext context, {
  required String quizId,
  List<Map<String, dynamic>> attempts = const [],
  int? requested,
  VoidCallback? onChanged,
  QuizCenterService? service,
}) async {
  final center = service ?? quizCenter;
  final Map<String, dynamic> quiz;
  try {
    quiz = await center.quizDetail(quizId);
  } catch (e) {
    if (context.mounted) _snack(context, 'Não abri o quiz: $e', error: true);
    return;
  }
  if (!context.mounted) return;

  final questions = (quiz['questoes'] is List ? quiz['questoes'] as List : const [])
      .whereType<Map>()
      .map((item) => item.map((k, v) => MapEntry(k.toString(), v)))
      .toList();
  final status = quiz['status']?.toString() ?? QuizStatus.open;
  final titulo = quiz['titulo']?.toString() ?? 'Quiz';

  Future<void> openMonitor(BuildContext from) => showDialog<void>(
        context: from,
        builder: (_) => QuizQRCodeMonitor(
          quizId: quizId,
          quizTitle: titulo,
          totalQuestions: questions.length,
        ),
      );

  await showQuizPreviewDialog(
    context,
    questions: questions,
    requested: requested ?? questions.length,
    attempts: attempts,
    title: '$titulo · ${quizStatusLabel(status).toLowerCase()}',
    actionsBuilder: (dialogContext) => [
      if (status == QuizStatus.draft) ...[
        TextButton.icon(
          onPressed: () async {
            final ok = await _confirm(
              dialogContext,
              'Descartar rascunho?',
              'As ${questions.length} pergunta(s) deste rascunho serão apagadas.',
              confirm: 'Descartar',
            );
            if (!ok) return;
            try {
              await center.discardDraft(quizId);
              onChanged?.call();
              if (dialogContext.mounted) Navigator.pop(dialogContext);
            } catch (e) {
              if (dialogContext.mounted) _snack(dialogContext, '$e', error: true);
            }
          },
          icon: const Icon(Icons.delete_outline, size: 16),
          label: const Text('DESCARTAR'),
          style: TextButton.styleFrom(foregroundColor: AssistantTheme.danger),
        ),
        FilledButton.icon(
          onPressed: questions.isEmpty
              ? null
              : () async {
                  try {
                    await center.publishQuiz(quizId);
                    onChanged?.call();
                    if (!dialogContext.mounted) return;
                    Navigator.pop(dialogContext);
                    if (context.mounted) await openMonitor(context);
                  } catch (e) {
                    if (dialogContext.mounted) _snack(dialogContext, '$e', error: true);
                  }
                },
          icon: const Icon(Icons.qr_code_2, size: 16),
          label: const Text('LIBERAR QR CODE'),
        ),
      ] else if (status == QuizStatus.open)
        FilledButton.icon(
          onPressed: () async {
            Navigator.pop(dialogContext);
            if (context.mounted) await openMonitor(context);
          },
          icon: const Icon(Icons.qr_code_2, size: 16),
          label: const Text('ABRIR QR CODE'),
        ),
    ],
  );
}

Future<bool> _confirm(
  BuildContext context,
  String title,
  String message, {
  String confirm = 'Confirmar',
}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext, false),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(dialogContext, true),
          child: Text(confirm),
        ),
      ],
    ),
  );
  return result == true;
}

/// Aviso padrao de fim de geracao: abre a revisao, ou a fila quando falhou.
void showQuizCenterDialog(BuildContext context, {int initialIndex = 0}) {
  showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      child: SizedBox(
        width: 980,
        height: 680,
        child: QuizCenterTabs(
          initialIndex: initialIndex,
          onClose: () => Navigator.pop(dialogContext),
        ),
      ),
    ),
  );
}

/// As tres areas da central, em abas. `generator`, quando informado, entra
/// como primeira aba - e o arranjo da aba Quiz do Modo Aula.
class QuizCenterTabs extends StatefulWidget {
  final Widget? generator;
  final int initialIndex;
  final VoidCallback? onClose;

  const QuizCenterTabs({
    super.key,
    this.generator,
    this.initialIndex = 0,
    this.onClose,
  });

  @override
  State<QuizCenterTabs> createState() => QuizCenterTabsState();
}

class QuizCenterTabsState extends State<QuizCenterTabs>
    with SingleTickerProviderStateMixin {
  late final TabController _controller;
  final _quizzesKey = GlobalKey<_QuizListPanelState>();

  int get _offset => widget.generator == null ? 0 : 1;

  @override
  void initState() {
    super.initState();
    _controller = TabController(
      length: 3 + _offset,
      vsync: this,
      initialIndex: widget.initialIndex.clamp(0, 2 + _offset),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// Leva para a aba da fila, usado depois de enfileirar um pedido.
  void showQueue() => _controller.animateTo(_offset);

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: TabBar(
                controller: _controller,
                isScrollable: true,
                tabAlignment: TabAlignment.start,
                indicatorColor: AssistantTheme.c3,
                labelColor: AssistantTheme.c3,
                unselectedLabelColor: AssistantTheme.textMuted,
                labelStyle: const TextStyle(fontSize: 11, letterSpacing: 1),
                tabs: [
                  if (widget.generator != null)
                    const Tab(icon: Icon(Icons.auto_awesome, size: 16), text: 'GERAR'),
                  Tab(
                    icon: const Icon(Icons.pending_actions_outlined, size: 16),
                    child: ValueListenableBuilder<QuizJobsSnapshot>(
                      valueListenable: quizQueueWatcher.snapshot,
                      builder: (_, snap, __) => Text(
                        snap.active > 0 ? 'FILA (${snap.active})' : 'FILA',
                      ),
                    ),
                  ),
                  const Tab(icon: Icon(Icons.quiz_outlined, size: 16), text: 'QUIZZES'),
                  const Tab(
                      icon: Icon(Icons.library_books_outlined, size: 16),
                      text: 'BANCO DE QUESTÕES'),
                ],
              ),
            ),
            if (widget.onClose != null)
              IconButton(
                tooltip: 'Fechar',
                onPressed: widget.onClose,
                icon: const Icon(Icons.close),
              ),
          ],
        ),
        const Divider(height: 1),
        Expanded(
          child: TabBarView(
            controller: _controller,
            children: [
              if (widget.generator != null) widget.generator!,
              QuizQueuePanel(
                onReviewed: () => _quizzesKey.currentState?.reload(),
              ),
              QuizListPanel(key: _quizzesKey),
              const QuestionBankPanel(),
            ],
          ),
        ),
      ],
    );
  }
}

// --- fila ------------------------------------------------------------------

class QuizQueuePanel extends StatefulWidget {
  final VoidCallback? onReviewed;
  const QuizQueuePanel({super.key, this.onReviewed});

  @override
  State<QuizQueuePanel> createState() => _QuizQueuePanelState();
}

class _QuizQueuePanelState extends State<QuizQueuePanel> {
  final Set<String> _busy = {};

  @override
  void initState() {
    super.initState();
    unawaited(quizQueueWatcher.refresh());
  }

  Future<void> _act(QuizJob job, Future<void> Function() action) async {
    setState(() => _busy.add(job.id));
    try {
      await action();
      await quizQueueWatcher.refresh();
    } catch (e) {
      if (mounted) _snack(context, '$e', error: true);
    } finally {
      if (mounted) setState(() => _busy.remove(job.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<QuizJobsSnapshot>(
      valueListenable: quizQueueWatcher.snapshot,
      builder: (context, snap, _) {
        if (snap.jobs.isEmpty) {
          return const _Empty(
            Icons.pending_actions_outlined,
            'Nenhum pedido de quiz ainda. Peça um na aba GERAR: ele entra na '
            'fila e você é avisado quando ficar pronto.',
          );
        }
        return RefreshIndicator(
          onRefresh: quizQueueWatcher.refresh,
          child: ListView.separated(
            padding: const EdgeInsets.all(14),
            itemCount: snap.jobs.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (_, index) => _jobCard(snap.jobs[index]),
          ),
        );
      },
    );
  }

  Widget _jobCard(QuizJob job) {
    final busy = _busy.contains(job.id);
    final color = jobStatusColor(job.status);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AssistantTheme.bg2,
        border: Border.all(
          color: job.isActive ? color.withOpacity(0.6) : AssistantTheme.border,
        ),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _StatusChip(jobStatusLabel(job.status), color),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  job.titulo,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
              ),
              Text(
                '${job.total} pergunta(s) · ${_when(job.createdAt)}',
                style: const TextStyle(fontSize: 10, color: AssistantTheme.textMuted),
              ),
            ],
          ),
          if (job.status == QuizJobStatus.running) ...[
            const SizedBox(height: 10),
            LinearProgressIndicator(
              value: job.progress == null || job.prontas == 0 ? null : job.progress,
              color: AssistantTheme.c1,
              backgroundColor: AssistantTheme.border,
            ),
          ],
          const SizedBox(height: 8),
          Text(
            job.message,
            style: TextStyle(
              fontSize: 11,
              color: job.status == QuizJobStatus.error
                  ? AssistantTheme.danger
                  : AssistantTheme.textSecondary,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              if (job.canReview)
                FilledButton.icon(
                  onPressed: busy
                      ? null
                      : () => openQuizReview(
                            context,
                            quizId: job.quizId,
                            attempts: job.attempts,
                            requested: job.total,
                            onChanged: widget.onReviewed,
                          ),
                  icon: const Icon(Icons.fact_check_outlined, size: 16),
                  label: const Text('REVISAR'),
                ),
              if (job.canRetry)
                OutlinedButton.icon(
                  onPressed: busy
                      ? null
                      : () => _act(job, () => quizCenter.retryJob(job.id)),
                  icon: const Icon(Icons.replay, size: 16),
                  label: const Text('TENTAR DE NOVO'),
                ),
              if (job.canCancel)
                TextButton.icon(
                  onPressed: busy
                      ? null
                      : () => _act(job, () => quizCenter.cancelJob(job.id)),
                  icon: const Icon(Icons.stop_circle_outlined, size: 16),
                  label: const Text('CANCELAR'),
                  style: TextButton.styleFrom(foregroundColor: AssistantTheme.danger),
                ),
              if (job.status == QuizJobStatus.error && job.attempts.isNotEmpty)
                TextButton.icon(
                  onPressed: () => _showAttempts(job),
                  icon: const Icon(Icons.info_outline, size: 16),
                  label: const Text('POR QUE FALHOU'),
                ),
            ],
          ),
        ],
      ),
    );
  }

  void _showAttempts(QuizJob job) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(job.titulo),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: SelectableText([
              job.error,
              '',
              for (final attempt in job.attempts)
                if (attempt['success'] != true)
                  '• ${attempt['llm'] ?? 'modelo'}: ${attempt['error'] ?? 'sem detalhe'}',
            ].join('\n')),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Fechar'),
          ),
        ],
      ),
    );
  }
}

// --- quizzes ---------------------------------------------------------------

class QuizListPanel extends StatefulWidget {
  const QuizListPanel({super.key});

  @override
  State<QuizListPanel> createState() => _QuizListPanelState();
}

class _QuizListPanelState extends State<QuizListPanel> {
  final _search = TextEditingController();
  Timer? _debounce;
  String _status = '';
  String _discipline = '';
  List<QuizSummary> _quizzes = const [];
  List<String> _disciplinas = const [];
  bool _loading = false;
  String _error = '';

  @override
  void initState() {
    super.initState();
    reload();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> reload() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final result = await quizCenter.listQuizzes(
        status: _status,
        discipline: _discipline,
        search: _search.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _quizzes = result.quizzes;
        _disciplinas = result.disciplinas;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _search,
                  decoration: const InputDecoration(
                    isDense: true,
                    prefixIcon: Icon(Icons.search, size: 18),
                    hintText: 'Buscar pelo título',
                  ),
                  onChanged: (_) {
                    _debounce?.cancel();
                    _debounce = Timer(const Duration(milliseconds: 350), reload);
                  },
                ),
              ),
              const SizedBox(width: 10),
              _DisciplineFilter(
                value: _discipline,
                options: _disciplinas,
                onChanged: (value) {
                  _discipline = value;
                  reload();
                },
              ),
              const SizedBox(width: 10),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: '', label: Text('Todos')),
                  ButtonSegment(value: QuizStatus.draft, label: Text('Rascunho')),
                  ButtonSegment(value: QuizStatus.open, label: Text('Liberado')),
                  ButtonSegment(value: QuizStatus.closed, label: Text('Encerrado')),
                ],
                selected: {_status},
                showSelectedIcon: false,
                onSelectionChanged: (value) {
                  _status = value.first;
                  reload();
                },
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (_loading) const LinearProgressIndicator(minHeight: 2),
          if (_error.isNotEmpty)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(_error, style: const TextStyle(color: AssistantTheme.danger)),
            ),
          Expanded(
            child: _quizzes.isEmpty && !_loading
                ? const _Empty(Icons.quiz_outlined, 'Nenhum quiz com esses filtros.')
                : ListView.separated(
                    itemCount: _quizzes.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (_, index) => _quizTile(_quizzes[index]),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _quizTile(QuizSummary quiz) {
    final detalhes = [
      if (quiz.disciplinas.isNotEmpty) quiz.disciplinas.join(', '),
      '${quiz.totalQuestoes} pergunta(s)',
      if (quiz.fontes.length > 1) '${quiz.fontes.length} fontes',
      _when(quiz.createdAt),
    ].join(' · ');
    return ListTile(
      dense: true,
      leading: _StatusChip(quizStatusLabel(quiz.status), quizStatusColor(quiz.status)),
      title: Text(quiz.titulo, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(detalhes, style: const TextStyle(fontSize: 11)),
      trailing: Wrap(
        spacing: 6,
        children: [
          OutlinedButton(
            onPressed: () => openQuizReview(
              context,
              quizId: quiz.id,
              onChanged: reload,
            ),
            child: Text(quiz.status == QuizStatus.draft ? 'REVISAR' : 'ABRIR'),
          ),
        ],
      ),
      onTap: () => openQuizReview(context, quizId: quiz.id, onChanged: reload),
    );
  }
}

class _DisciplineFilter extends StatelessWidget {
  final String value;
  final List<String> options;
  final ValueChanged<String> onChanged;

  const _DisciplineFilter({
    required this.value,
    required this.options,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final items = {'', ...options, if (value.isNotEmpty) value}.toList();
    return SizedBox(
      width: 220,
      child: DropdownButtonFormField<String>(
        value: value,
        isExpanded: true,
        decoration: const InputDecoration(isDense: true, labelText: 'Disciplina'),
        items: [
          for (final item in items)
            DropdownMenuItem(
              value: item,
              child: Text(item.isEmpty ? 'Todas' : item, overflow: TextOverflow.ellipsis),
            ),
        ],
        onChanged: (selected) => onChanged(selected ?? ''),
      ),
    );
  }
}

// --- banco de questoes -----------------------------------------------------

class QuestionBankPanel extends StatefulWidget {
  final QuizCenterService? service;
  const QuestionBankPanel({super.key, this.service});

  @override
  State<QuestionBankPanel> createState() => _QuestionBankPanelState();
}

class _QuestionBankPanelState extends State<QuestionBankPanel> {
  static const _pageSize = 40;

  QuizCenterService get _service => widget.service ?? quizCenter;

  final _search = TextEditingController();
  Timer? _debounce;
  String _discipline = '';
  String _dificuldade = '';
  String _status = '';
  bool _archived = false;

  /// Ids de tudo que o filtro alcanca, para "selecionar todas" poder passar
  /// alem da pagina carregada.
  List<String> _allIds = const [];
  List<BankQuestion> _questions = const [];
  List<String> _disciplinas = const [];
  int _total = 0;
  bool _loading = false;
  String _error = '';

  /// Selecao para montar quiz, na ordem em que o professor marcou.
  final List<String> _selected = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load({bool append = false}) async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final result = await _service.listQuestions(
        discipline: _discipline,
        search: _search.text.trim(),
        dificuldade: _dificuldade,
        status: _status,
        includeArchived: _archived,
        limit: _pageSize,
        offset: append ? _questions.length : 0,
      );
      if (!mounted) return;
      setState(() {
        _questions = append ? [..._questions, ...result.questions] : result.questions;
        _total = result.total;
        _disciplinas = result.disciplinas;
        _allIds = result.allIds;
        // Marcada que saiu do filtro nao fica marcada em segredo: o botao de
        // excluir diz um numero, e ele tem de ser o que esta a vista.
        _selected.removeWhere((id) => !_allIds.contains(id));
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toggle(BankQuestion question, bool selected) {
    setState(() {
      _selected.remove(question.id);
      if (selected) _selected.add(question.id);
    });
  }

  void _selectAll() => setState(() {
        _selected
          ..clear()
          ..addAll(_allIds);
      });

  /// Limpeza em lote. O aviso e explicito sobre o que nao sera apagado: quiz ja
  /// aplicado so arquiva, e descobrir isso depois seria ruim.
  Future<void> _removeSelected() async {
    final marcadas = List.of(_selected);
    if (marcadas.isEmpty) return;
    final naPagina = _questions.where((q) => marcadas.contains(q.id));
    final arquivaveis = naPagina.where((q) => !q.editavel).length;
    final ok = await _confirm(
      context,
      'Excluir ${marcadas.length} questão(ões)?',
      'As de rascunho são apagadas de vez.'
      '${arquivaveis > 0 ? ' Pelo menos $arquivaveis são de quiz já liberado: '
          'essas são arquivadas, não apagadas, porque continuam ligadas às '
          'respostas da turma.' : ''}'
      ' Não dá para desfazer o que for apagado.',
      confirm: 'Excluir',
    );
    if (!ok) return;
    try {
      final resultado = await _service.removeQuestions(marcadas);
      if (mounted) {
        setState(_selected.clear);
        _snack(context, resultado.resumo);
      }
      await _load();
    } catch (e) {
      if (mounted) _snack(context, '$e', error: true);
    }
  }

  Future<void> _remove(BankQuestion question) async {
    final ok = await _confirm(
      context,
      question.editavel ? 'Excluir questão?' : 'Arquivar questão?',
      question.editavel
          ? 'Ela será apagada do rascunho "${question.quizTitulo}".'
          : 'O quiz "${question.quizTitulo}" já foi liberado: a questão sai do '
              'banco e das próximas gerações, mas continua ligada às respostas da turma.',
      confirm: question.editavel ? 'Excluir' : 'Arquivar',
    );
    if (!ok) return;
    try {
      final archived = await _service.removeQuestion(question.id);
      _selected.remove(question.id);
      if (mounted) _snack(context, archived ? 'Questão arquivada.' : 'Questão excluída.');
      await _load();
    } catch (e) {
      if (mounted) _snack(context, '$e', error: true);
    }
  }

  Future<void> _restore(BankQuestion question) async {
    try {
      await _service.restoreQuestion(question.id);
      await _load();
    } catch (e) {
      if (mounted) _snack(context, '$e', error: true);
    }
  }

  Future<void> _edit(BankQuestion question) async {
    final changes = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => QuestionEditorDialog(question: question),
    );
    if (changes == null) return;
    try {
      await _service.updateQuestion(question.id, changes);
      if (mounted) _snack(context, 'Questão atualizada.');
      await _load();
    } catch (e) {
      if (mounted) _snack(context, '$e', error: true);
    }
  }

  Future<void> _buildQuiz() async {
    final titleController = TextEditingController(text: 'Simulado');
    var tipo = 'pratica';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: Text('Montar quiz com ${_selected.length} questão(ões)'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: titleController,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Título'),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: tipo,
                  decoration: const InputDecoration(labelText: 'Tipo de quiz'),
                  items: const [
                    DropdownMenuItem(value: 'pratica', child: Text('Prática')),
                    DropdownMenuItem(value: 'revisao', child: Text('Revisão')),
                    DropdownMenuItem(value: 'diagnostico', child: Text('Diagnóstico')),
                  ],
                  onChanged: (value) => setDialogState(() => tipo = value ?? tipo),
                ),
                const SizedBox(height: 10),
                const Text(
                  'As questões são copiadas para um rascunho novo, na ordem em '
                  'que foram marcadas. Nenhuma chamada à IA.',
                  style: TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Montar'),
            ),
          ],
        ),
      ),
    );
    final titulo = titleController.text.trim();
    titleController.dispose();
    if (confirmed != true || titulo.isEmpty) return;

    try {
      final quiz = await _service.createQuizFromQuestions(
        titulo: titulo,
        questionIds: List.of(_selected),
        tipoQuiz: tipo,
      );
      if (!mounted) return;
      setState(_selected.clear);
      _snack(context, 'Rascunho "$titulo" criado.');
      await openQuizReview(context, quizId: quiz['id']?.toString() ?? '', service: _service);
    } catch (e) {
      if (mounted) _snack(context, '$e', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _search,
                  decoration: const InputDecoration(
                    isDense: true,
                    prefixIcon: Icon(Icons.search, size: 18),
                    hintText: 'Buscar no enunciado, tópico ou conceito',
                  ),
                  onChanged: (_) {
                    _debounce?.cancel();
                    _debounce = Timer(const Duration(milliseconds: 350), _load);
                  },
                ),
              ),
              const SizedBox(width: 10),
              _DisciplineFilter(
                value: _discipline,
                options: _disciplinas,
                onChanged: (value) {
                  _discipline = value;
                  _load();
                },
              ),
              const SizedBox(width: 10),
              SizedBox(
                width: 160,
                child: DropdownButtonFormField<String>(
                  value: _dificuldade,
                  isExpanded: true,
                  decoration: const InputDecoration(isDense: true, labelText: 'Dificuldade'),
                  items: const [
                    DropdownMenuItem(value: '', child: Text('Todas')),
                    DropdownMenuItem(value: 'facil', child: Text('Fácil')),
                    DropdownMenuItem(value: 'medio', child: Text('Médio')),
                    DropdownMenuItem(value: 'dificil', child: Text('Difícil')),
                  ],
                  onChanged: (value) {
                    _dificuldade = value ?? '';
                    _load();
                  },
                ),
              ),
              const SizedBox(width: 10),
              SizedBox(
                width: 170,
                child: DropdownButtonFormField<String>(
                  value: _status,
                  isExpanded: true,
                  decoration: const InputDecoration(
                      isDense: true, labelText: 'Situação do quiz'),
                  items: const [
                    DropdownMenuItem(value: '', child: Text('Todas')),
                    DropdownMenuItem(value: 'draft', child: Text('Rascunho')),
                    DropdownMenuItem(value: 'open', child: Text('Liberado')),
                    DropdownMenuItem(value: 'closed', child: Text('Encerrado')),
                  ],
                  onChanged: (value) {
                    _status = value ?? '';
                    _load();
                  },
                ),
              ),
              const SizedBox(width: 6),
              FilterChip(
                label: const Text('Arquivadas'),
                selected: _archived,
                onSelected: (value) {
                  setState(() => _archived = value);
                  _load();
                },
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Text(
                '$_total questão(ões)'
                '${_selected.isEmpty ? '' : ' · ${_selected.length} marcada(s)'}',
                style: const TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
              ),
              const Spacer(),
              // Sao quatro acoes e os rotulos crescem com o numero marcado:
              // numa janela estreita elas descem de linha em vez de vazar.
              Flexible(
                child: Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  alignment: WrapAlignment.end,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    if (_allIds.isNotEmpty && _selected.length < _allIds.length)
                      TextButton.icon(
                        onPressed: _selectAll,
                        icon: const Icon(Icons.checklist, size: 16),
                        label: Text('SELECIONAR TODAS ($_total)'),
                      ),
                    if (_selected.isNotEmpty) ...[
                      TextButton(
                        onPressed: () => setState(_selected.clear),
                        child: const Text('LIMPAR SELEÇÃO'),
                      ),
                      OutlinedButton.icon(
                        onPressed: _removeSelected,
                        icon: const Icon(Icons.delete_sweep_outlined, size: 16),
                        label: Text('EXCLUIR (${_selected.length})'),
                        style: OutlinedButton.styleFrom(
                            foregroundColor: AssistantTheme.danger),
                      ),
                    ],
                    FilledButton.icon(
                      onPressed: _selected.isEmpty ? null : _buildQuiz,
                      icon: const Icon(Icons.playlist_add_check, size: 16),
                      label: Text(_selected.isEmpty
                          ? 'MONTAR QUIZ'
                          : 'MONTAR QUIZ (${_selected.length})'),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (_loading) const LinearProgressIndicator(minHeight: 2),
          if (_error.isNotEmpty)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(_error, style: const TextStyle(color: AssistantTheme.danger)),
            ),
          Expanded(
            child: _questions.isEmpty && !_loading
                ? const _Empty(
                    Icons.library_books_outlined,
                    'Nenhuma questão com esses filtros. As questões de todo quiz '
                    'gerado entram aqui automaticamente.',
                  )
                : ListView.builder(
                    itemCount: _questions.length + (_questions.length < _total ? 1 : 0),
                    itemBuilder: (_, index) {
                      if (index == _questions.length) {
                        return Padding(
                          padding: const EdgeInsets.all(10),
                          child: Center(
                            child: OutlinedButton(
                              onPressed: _loading ? null : () => _load(append: true),
                              child: Text('CARREGAR MAIS (${_total - _questions.length})'),
                            ),
                          ),
                        );
                      }
                      return _questionTile(_questions[index]);
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Widget _questionTile(BankQuestion question) {
    final order = _selected.indexOf(question.id);
    return Card(
      color: AssistantTheme.bg2,
      margin: const EdgeInsets.only(top: 6),
      child: ExpansionTile(
        key: PageStorageKey(question.id),
        leading: Checkbox(
          value: order >= 0,
          onChanged: question.arquivada ? null : (value) => _toggle(question, value ?? false),
        ),
        title: Text(
          question.enunciado,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 13,
            color: question.arquivada ? AssistantTheme.textMuted : AssistantTheme.textPrimary,
            decoration: question.arquivada ? TextDecoration.lineThrough : null,
          ),
        ),
        subtitle: Text(
          [
            if (order >= 0) '#${order + 1} na seleção',
            difficultyLabel(question.dificuldade),
            if (question.disciplinas.isNotEmpty) question.disciplinas.join(', '),
            'de "${question.quizTitulo}" (${quizStatusLabel(question.quizStatus).toLowerCase()})',
            if (!question.verificado) 'não verificada',
          ].join(' · '),
          style: const TextStyle(fontSize: 10, color: AssistantTheme.textSecondary),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(56, 0, 16, 12),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final opcao in question.opcoes)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Row(
                children: [
                  Icon(
                    opcao['correta'] == true
                        ? Icons.check_circle_outline
                        : Icons.radio_button_unchecked,
                    size: 14,
                    color: opcao['correta'] == true
                        ? AssistantTheme.c3
                        : AssistantTheme.textMuted,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      '${opcao['label'] ?? ''}. ${opcao['texto'] ?? ''}',
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                ],
              ),
            ),
          if (question.justificativa.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                question.justificativa,
                style: const TextStyle(
                  fontSize: 11,
                  fontStyle: FontStyle.italic,
                  color: AssistantTheme.textSecondary,
                ),
              ),
            ),
          if (question.topicoOrigem.isNotEmpty || question.conceitos.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                [
                  if (question.topicoOrigem.isNotEmpty) 'Tópico: ${question.topicoOrigem}',
                  if (question.conceitos.isNotEmpty) 'Conceitos: ${question.conceitos.join(', ')}',
                ].join(' · '),
                style: const TextStyle(fontSize: 10, color: AssistantTheme.textMuted),
              ),
            ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              if (question.arquivada)
                OutlinedButton.icon(
                  onPressed: () => _restore(question),
                  icon: const Icon(Icons.unarchive_outlined, size: 16),
                  label: const Text('RESTAURAR'),
                )
              else ...[
                Tooltip(
                  message: question.editavel
                      ? ''
                      : 'Quiz já liberado: monte um quiz novo com esta questão para editá-la.',
                  child: OutlinedButton.icon(
                    onPressed: question.editavel ? () => _edit(question) : null,
                    icon: const Icon(Icons.edit_outlined, size: 16),
                    label: const Text('EDITAR'),
                  ),
                ),
                TextButton.icon(
                  onPressed: () => _remove(question),
                  icon: Icon(
                    question.editavel ? Icons.delete_outline : Icons.archive_outlined,
                    size: 16,
                  ),
                  label: Text(question.editavel ? 'EXCLUIR' : 'ARQUIVAR'),
                  style: TextButton.styleFrom(foregroundColor: AssistantTheme.danger),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

/// Edicao de uma questao de rascunho. Devolve so os campos alterados.
class QuestionEditorDialog extends StatefulWidget {
  final BankQuestion question;
  const QuestionEditorDialog({super.key, required this.question});

  @override
  State<QuestionEditorDialog> createState() => _QuestionEditorDialogState();
}

class _QuestionEditorDialogState extends State<QuestionEditorDialog> {
  static const _labels = ['A', 'B', 'C', 'D'];

  late final TextEditingController _enunciado;
  late final TextEditingController _justificativa;
  late final List<TextEditingController> _opcoes;
  late String _correta;
  late String _dificuldade;
  String _error = '';

  @override
  void initState() {
    super.initState();
    final q = widget.question;
    _enunciado = TextEditingController(text: q.enunciado);
    _justificativa = TextEditingController(text: q.justificativa);
    _opcoes = [
      for (final label in _labels)
        TextEditingController(
          text: q.opcoes
                  .firstWhere(
                    (o) => o['label']?.toString() == label,
                    orElse: () => const {},
                  )['texto']
                  ?.toString() ??
              '',
        ),
    ];
    _correta = q.opcoes
            .firstWhere((o) => o['correta'] == true, orElse: () => const {})['label']
            ?.toString() ??
        'A';
    _dificuldade = ['facil', 'medio', 'dificil'].contains(q.dificuldade) ? q.dificuldade : 'medio';
  }

  @override
  void dispose() {
    _enunciado.dispose();
    _justificativa.dispose();
    for (final controller in _opcoes) {
      controller.dispose();
    }
    super.dispose();
  }

  void _save() {
    final enunciado = _enunciado.text.trim();
    final opcoes = [
      for (var i = 0; i < _labels.length; i++)
        if (_opcoes[i].text.trim().isNotEmpty)
          {
            'label': _labels[i],
            'texto': _opcoes[i].text.trim(),
            'correta': _labels[i] == _correta,
          },
    ];
    if (enunciado.isEmpty) {
      setState(() => _error = 'O enunciado não pode ficar vazio.');
      return;
    }
    if (opcoes.length < 2) {
      setState(() => _error = 'Preencha ao menos duas alternativas.');
      return;
    }
    if (!opcoes.any((o) => o['correta'] == true)) {
      setState(() => _error = 'A alternativa correta precisa ter texto.');
      return;
    }
    Navigator.pop(context, {
      'enunciado': enunciado,
      'opcoes': opcoes,
      'justificativa': _justificativa.text.trim(),
      'dificuldade': _dificuldade,
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Editar questão'),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: _enunciado,
                maxLines: 3,
                minLines: 1,
                decoration: const InputDecoration(labelText: 'Enunciado'),
              ),
              const SizedBox(height: 12),
              const Text('Alternativas (marque a correta)',
                  style: TextStyle(fontSize: 11, color: AssistantTheme.textSecondary)),
              for (var i = 0; i < _labels.length; i++)
                Row(
                  children: [
                    Radio<String>(
                      value: _labels[i],
                      groupValue: _correta,
                      onChanged: (value) => setState(() => _correta = value ?? _correta),
                    ),
                    Expanded(
                      child: TextField(
                        controller: _opcoes[i],
                        maxLength: 60,
                        decoration: InputDecoration(
                          isDense: true,
                          counterText: '',
                          labelText: 'Alternativa ${_labels[i]}',
                        ),
                      ),
                    ),
                  ],
                ),
              const SizedBox(height: 12),
              TextField(
                controller: _justificativa,
                maxLines: 3,
                minLines: 1,
                decoration: const InputDecoration(labelText: 'Justificativa'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: _dificuldade,
                decoration: const InputDecoration(labelText: 'Dificuldade'),
                items: const [
                  DropdownMenuItem(value: 'facil', child: Text('Fácil')),
                  DropdownMenuItem(value: 'medio', child: Text('Médio')),
                  DropdownMenuItem(value: 'dificil', child: Text('Difícil')),
                ],
                onChanged: (value) => setState(() => _dificuldade = value ?? _dificuldade),
              ),
              if (_error.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Text(_error, style: const TextStyle(color: AssistantTheme.danger)),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        FilledButton(onPressed: _save, child: const Text('Salvar')),
      ],
    );
  }
}

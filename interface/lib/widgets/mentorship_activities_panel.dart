/// Atividades de uma mentoria: cadastrar, acompanhar quem entregou e ver quem está
/// faltando.
///
/// O aluno entrega por uma página pública (matrícula do aceito); aqui fica o lado do
/// professor: a lista de atividades com o link de entrega, a matriz aluno x atividade, a
/// conferência de cada entrega (texto e arquivo) e a lista de quem deixou de entregar.
/// A lista de faltosos só **sugere**: tirar alguém da mentoria é decisão do professor.
library;

import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/mentorship.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

class MentorshipActivitiesPanel extends StatefulWidget {
  final MentorshipForm form;
  final String baseUrl;
  final EducationService service;

  /// Tira da mentoria os inscritos escolhidos (quem chama muda a situação deles).
  final Future<void> Function(List<String> signupIds) onRemove;

  /// De quanto em quanto tempo a tela se atualiza sozinha. Zero desliga (testes).
  final Duration pollEvery;

  const MentorshipActivitiesPanel({
    super.key,
    required this.form,
    required this.baseUrl,
    required this.service,
    required this.onRemove,
    this.pollEvery = const Duration(seconds: 30),
  });

  @override
  State<MentorshipActivitiesPanel> createState() => _MentorshipActivitiesPanelState();
}

class _MentorshipActivitiesPanelState extends State<MentorshipActivitiesPanel> {
  String _path = '';
  List<MentorshipActivity> _activities = const [];
  List<DeliveryRow> _rows = const [];
  List<AtRiskStudent> _risk = const [];
  int _misses = 2;
  bool _loading = true;
  bool _busy = false;
  String _message = '';
  bool _error = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    if (widget.pollEvery > Duration.zero) {
      _timer = Timer.periodic(widget.pollEvery, (_) => _load(silent: true));
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String _errorText(Object error) => error is EducationException
      ? error.message
      : '$error'.replaceFirst('Exception: ', '');

  void _report(String text, {bool error = false}) {
    if (!mounted) return;
    setState(() {
      _message = text;
      _error = error;
    });
  }

  Future<void> _load({bool silent = false}) async {
    if (silent && _busy) return;
    try {
      final id = widget.form.id;
      final listing = await widget.service.listMentorshipActivities(id);
      final matrix = await widget.service.mentorshipDeliveries(id);
      final risk = await widget.service.mentorshipAtRisk(id, _misses);
      if (!mounted) return;
      setState(() {
        _path = listing.path;
        _activities = listing.activities;
        _rows = matrix.rows;
        _risk = risk;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      if (!silent) _report('Falha ao carregar as atividades: ${_errorText(e)}', error: true);
    }
  }

  Future<void> _guard(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String get _deliveryUrl =>
      '${widget.baseUrl.replaceAll(RegExp(r'/+$'), '')}$_path';

  Future<void> _copyLink() async {
    await Clipboard.setData(ClipboardData(text: _deliveryUrl));
    _report('Link de entrega copiado. Os alunos aceitos entram com a matrícula.');
  }

  // --- atividades -------------------------------------------------------------------

  Future<void> _editActivity([MentorshipActivity? current]) async {
    final title = TextEditingController(text: current?.title ?? '');
    final instructions = TextEditingController(text: current?.instructions ?? '');
    DateTime? due = current?.dueAt;
    var remind = current?.remind ?? true;

    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text(current == null ? 'Nova atividade' : 'Editar atividade'),
          content: SizedBox(
            width: 460,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                  key: const Key('activity-title'),
                  controller: title,
                  decoration: const InputDecoration(labelText: 'TÍTULO', isDense: true),
                ),
                const SizedBox(height: 10),
                TextField(
                  key: const Key('activity-instructions'),
                  controller: instructions,
                  minLines: 3,
                  maxLines: 6,
                  decoration: const InputDecoration(
                      labelText: 'INSTRUÇÕES', isDense: true, alignLabelWithHint: true),
                ),
                const SizedBox(height: 10),
                Row(children: [
                  OutlinedButton.icon(
                    onPressed: () async {
                      final now = DateTime.now();
                      final day = await showDatePicker(
                        context: dialogContext,
                        initialDate: due ?? now.add(const Duration(days: 7)),
                        firstDate: now.subtract(const Duration(days: 30)),
                        lastDate: now.add(const Duration(days: 365)),
                      );
                      if (day == null || !dialogContext.mounted) return;
                      final time = await showTimePicker(
                        context: dialogContext,
                        initialTime: TimeOfDay.fromDateTime(due ?? DateTime(0, 1, 1, 23, 59)),
                      );
                      setDialogState(() => due = DateTime(day.year, day.month, day.day,
                          time?.hour ?? 23, time?.minute ?? 59));
                    },
                    icon: const Icon(Icons.event, size: 16),
                    label: Text(due == null ? 'PRAZO (OPCIONAL)' : _dateTime(due!)),
                  ),
                  if (due != null)
                    IconButton(
                      tooltip: 'Tirar o prazo',
                      onPressed: () => setDialogState(() => due = null),
                      icon: const Icon(Icons.close, size: 16),
                    ),
                ]),
                CheckboxListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  value: remind,
                  onChanged: due == null
                      ? null
                      : (value) => setDialogState(() => remind = value ?? true),
                  title: const Text('Lembrar por e-mail 24 h antes de vencer',
                      style: TextStyle(fontSize: 12)),
                  subtitle: const Text('Só para quem ainda não entregou.',
                      style: TextStyle(fontSize: 11)),
                ),
              ]),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('CANCELAR')),
            FilledButton(
                key: const Key('activity-save'),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('SALVAR')),
          ],
        ),
      ),
    );
    // Sem dispose: a animação de fechar do diálogo ainda desenha estes campos.
    final name = title.text.trim();
    final text = instructions.text.trim();
    if (saved != true) return;
    if (name.isEmpty) {
      _report('Dê um título à atividade.', error: true);
      return;
    }
    await _guard(() async {
      if (current == null) {
        await widget.service.createMentorshipActivity(widget.form.id,
            title: name, instructions: text, dueAt: due, remind: remind);
      } else {
        await widget.service.updateMentorshipActivity(current.id, {
          'title': name,
          'instructions': text,
          'remind': remind,
          if (due == null) 'clear_due': true else 'due_at': due!.toUtc().toIso8601String(),
        });
      }
      await _load();
      _report(current == null ? 'Atividade criada.' : 'Atividade atualizada.');
    });
  }

  Future<void> _deleteActivity(MentorshipActivity activity) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Apagar atividade?'),
        content: Text('“${activity.title}” e as ${activity.delivered} entrega(s) '
            'dela serão apagadas.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Apagar')),
        ],
      ),
    );
    if (confirmed != true) return;
    await _guard(() async {
      await widget.service.deleteMentorshipActivity(activity.id);
      await _load();
      _report('Atividade apagada.');
    });
  }

  // --- entregas ---------------------------------------------------------------------

  Future<void> _openDelivery(DeliveryRow row, MentorshipActivity activity, DeliveryCell cell) async {
    final id = cell.deliveryId;
    if (id == null) return;
    DeliveryDetail detail;
    try {
      detail = await widget.service.getMentorshipDelivery(id);
    } catch (e) {
      _report('Falha ao abrir a entrega: ${_errorText(e)}', error: true);
      return;
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: Text('${row.name} · ${activity.title}'),
        content: SizedBox(
          width: 480,
          child: SingleChildScrollView(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                '${detail.late ? 'Entregue com atraso' : 'Entregue no prazo'}'
                '${detail.deliveredAt == null ? '' : ' · ${_dateTime(detail.deliveredAt!)}'}',
                style: TextStyle(
                    fontSize: 12,
                    color: detail.late ? Colors.amber : AssistantTheme.c3),
              ),
              if (detail.text.isNotEmpty) ...[
                const SizedBox(height: 10),
                SelectableText(detail.text, style: const TextStyle(fontSize: 13)),
              ],
              if (detail.hasFile) ...[
                const SizedBox(height: 12),
                Text('${detail.filename} · ${(detail.fileSize / 1024).ceil()} KB',
                    style: const TextStyle(fontSize: 12)),
              ],
            ]),
          ),
        ),
        actions: [
          if (detail.text.isNotEmpty)
            TextButton(
              onPressed: () => Clipboard.setData(ClipboardData(text: detail.text)),
              child: const Text('COPIAR TEXTO'),
            ),
          if (detail.hasFile)
            TextButton.icon(
              onPressed: () => _saveFile(detail),
              icon: const Icon(Icons.download, size: 16),
              label: const Text('BAIXAR ARQUIVO'),
            ),
          TextButton(
              onPressed: () => Navigator.pop(dialogContext), child: const Text('FECHAR')),
        ],
      ),
    );
  }

  Future<void> _saveFile(DeliveryDetail detail) => _guard(() async {
        final bytes = await widget.service.downloadMentorshipDeliveryFile(detail.id);
        final path = await FilePicker.saveFile(
          dialogTitle: 'Salvar a entrega',
          fileName: detail.filename,
          bytes: Uint8List.fromList(bytes),
        );
        if (path == null) return;
        final file = File(path);
        if (!await file.exists() || await file.length() != bytes.length) {
          await file.writeAsBytes(bytes);
        }
        _report('Arquivo salvo em ${file.path}');
      });

  // --- quem está faltando ----------------------------------------------------------

  Future<void> _setMisses(int value) async {
    setState(() => _misses = value);
    try {
      final risk = await widget.service.mentorshipAtRisk(widget.form.id, value);
      if (mounted) setState(() => _risk = risk);
    } catch (e) {
      _report('Falha ao atualizar a lista: ${_errorText(e)}', error: true);
    }
  }

  Future<void> _remove(List<AtRiskStudent> students) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Tirar da mentoria?'),
        content: Text(students.length == 1
            ? '${students.first.name} sai da turma da mentoria. O histórico fica guardado '
                'e dá para aceitar de novo depois.'
            : '${students.length} alunos saem da turma da mentoria. O histórico fica '
                'guardado e dá para aceitar de novo depois.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Tirar')),
        ],
      ),
    );
    if (confirmed != true) return;
    await _guard(() async {
      await widget.onRemove([for (final s in students) s.signupId]);
      await _load();
    });
  }

  // --- tela -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AssistantTheme.bg.withOpacity(.38),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AssistantTheme.c3.withOpacity(.45)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(
            child: Text('ATIVIDADES E ENTREGAS',
                style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1,
                    color: AssistantTheme.c3)),
          ),
          FilledButton.icon(
            key: const Key('activity-new'),
            onPressed: _busy ? null : () => _editActivity(),
            icon: const Icon(Icons.add, size: 16),
            label: const Text('NOVA ATIVIDADE'),
          ),
        ]),
        if (_message.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(_message,
                style: TextStyle(
                    fontSize: 12, color: _error ? Colors.redAccent : AssistantTheme.c3)),
          ),
        const SizedBox(height: 8),
        if (_loading)
          const Padding(
              padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()))
        else ...[
          Row(children: [
            Expanded(
              child: SelectableText(_deliveryUrl,
                  style: const TextStyle(fontSize: 12, color: AssistantTheme.c1)),
            ),
            IconButton(
                tooltip: 'Copiar link de entrega',
                onPressed: _copyLink,
                icon: const Icon(Icons.copy, size: 18)),
          ]),
          const Text(
            'Os alunos aceitos abrem este link, digitam a matrícula e entregam texto e/ou '
            'arquivo. Dá para reenviar até o fim; depois do prazo a entrega fica como atrasada.',
            style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
          ),
          const SizedBox(height: 10),
          if (_activities.isEmpty)
            const Text('Nenhuma atividade ainda. Clique em NOVA ATIVIDADE.',
                style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted))
          else ...[
            for (final activity in _activities) _buildActivity(activity),
            const SizedBox(height: 10),
            _buildMatrix(),
            const SizedBox(height: 12),
            _buildRisk(),
          ],
        ],
      ]),
    );
  }

  Widget _buildActivity(MentorshipActivity activity) {
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AssistantTheme.border),
      ),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(activity.title,
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
            Text(
              activity.dueAt == null
                  ? 'Sem prazo'
                  : '${activity.overdue ? 'Venceu' : 'Vence'} em ${_dateTime(activity.dueAt!)}',
              style: TextStyle(
                  fontSize: 11,
                  color: activity.overdue ? Colors.redAccent : AssistantTheme.textSecondary),
            ),
          ]),
        ),
        _Pill('${activity.delivered}/${activity.expected} entregaram', AssistantTheme.c1),
        IconButton(
            tooltip: 'Editar',
            onPressed: _busy ? null : () => _editActivity(activity),
            icon: const Icon(Icons.edit_outlined, size: 16)),
        IconButton(
            tooltip: 'Apagar',
            onPressed: _busy ? null : () => _deleteActivity(activity),
            icon: const Icon(Icons.delete_outline, size: 16)),
      ]),
    );
  }

  Widget _buildMatrix() {
    if (_rows.isEmpty) {
      return const Text('Quando houver alunos aceitos, a tabela de entregas aparece aqui.',
          style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('QUEM ENTREGOU',
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, letterSpacing: 1)),
      const SizedBox(height: 4),
      const Wrap(spacing: 10, children: [
        _Legend('Entregue', Icons.check_circle, AssistantTheme.c3),
        _Legend('Atrasada', Icons.schedule, Colors.amber),
        _Legend('Vencida', Icons.cancel, Colors.redAccent),
        _Legend('Pendente', Icons.radio_button_unchecked, AssistantTheme.textMuted),
      ]),
      const SizedBox(height: 6),
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Table(
          defaultColumnWidth: const FixedColumnWidth(96),
          columnWidths: const {0: FixedColumnWidth(190)},
          defaultVerticalAlignment: TableCellVerticalAlignment.middle,
          children: [
            TableRow(children: [
              const SizedBox.shrink(),
              for (final a in _activities)
                Padding(
                  padding: const EdgeInsets.all(4),
                  child: Tooltip(
                    message: a.title,
                    child: Text(a.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                  ),
                ),
            ]),
            for (final row in _rows)
              TableRow(
                decoration: const BoxDecoration(
                    border: Border(top: BorderSide(color: AssistantTheme.border))),
                children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
                    child: Text(row.name,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 12)),
                  ),
                  for (var i = 0; i < _activities.length; i++)
                    _cell(row, _activities[i], row.cells.length > i ? row.cells[i] : null),
                ],
              ),
          ],
        ),
      ),
    ]);
  }

  Widget _cell(DeliveryRow row, MentorshipActivity activity, DeliveryCell? cell) {
    final status = cell?.status ?? 'pending';
    final (icon, color, label) = switch (status) {
      'delivered' => (Icons.check_circle, AssistantTheme.c3, 'Entregue'),
      'late' => (Icons.schedule, Colors.amber, 'Entregue com atraso'),
      'overdue' => (Icons.cancel, Colors.redAccent, 'Prazo vencido sem entrega'),
      _ => (Icons.radio_button_unchecked, AssistantTheme.textMuted, 'Pendente'),
    };
    final tappable = cell != null && cell.hasDelivery;
    return Tooltip(
      message: label,
      child: IconButton(
        key: Key('cell-${row.signupId}-${activity.id}'),
        onPressed: tappable ? () => _openDelivery(row, activity, cell) : null,
        icon: Icon(icon, size: 20, color: color),
      ),
    );
  }

  Widget _buildRisk() {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const Text('QUEM ESTÁ FALTANDO',
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, letterSpacing: 1)),
        const SizedBox(width: 12),
        const Text('não entregou as últimas', style: TextStyle(fontSize: 11)),
        const SizedBox(width: 6),
        DropdownButton<int>(
          key: const Key('risk-misses'),
          value: _misses,
          isDense: true,
          items: [
            for (final n in const [1, 2, 3, 4])
              DropdownMenuItem(value: n, child: Text('$n')),
          ],
          onChanged: (value) => value == null ? null : _setMisses(value),
        ),
        const SizedBox(width: 6),
        const Text('vencidas', style: TextStyle(fontSize: 11)),
      ]),
      const SizedBox(height: 4),
      if (_risk.isEmpty)
        const Text('Ninguém nessa situação.',
            style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted))
      else ...[
        const Text('O app só sugere: ninguém sai da mentoria sem você confirmar.',
            style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
        const SizedBox(height: 6),
        for (final student in _risk)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(children: [
              Expanded(
                  child: Text('${student.name}  ·  mat. ${student.enrollment}',
                      style: const TextStyle(fontSize: 12))),
              _Pill('${student.misses} sem entrega', Colors.redAccent),
              const SizedBox(width: 8),
              OutlinedButton(
                key: Key('risk-remove-${student.signupId}'),
                onPressed: _busy ? null : () => _remove([student]),
                child: const Text('TIRAR DA MENTORIA'),
              ),
            ]),
          ),
      ],
    ]);
  }
}

String _dateTime(DateTime value) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(value.day)}/${two(value.month)}/${value.year} ${two(value.hour)}:${two(value.minute)}';
}

class _Pill extends StatelessWidget {
  final String text;
  final Color color;

  const _Pill(this.text, this.color);

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: color.withOpacity(.12),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withOpacity(.5)),
        ),
        child: Text(text,
            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color)),
      );
}

class _Legend extends StatelessWidget {
  final String text;
  final IconData icon;
  final Color color;

  const _Legend(this.text, this.icon, this.color);

  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 13, color: color),
        const SizedBox(width: 3),
        Text(text, style: const TextStyle(fontSize: 10, color: AssistantTheme.textMuted)),
      ]);
}

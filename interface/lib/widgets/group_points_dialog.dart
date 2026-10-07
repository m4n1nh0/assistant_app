/// Pontos do grupo de projeto: lançar, ver o histórico, corrigir e apagar.
///
/// Cada lançamento soma (ou, negativo, tira) pontos, com motivo e data. Na hora de
/// lançar, o professor escolhe se o ponto vale só para o grupo ou também para cada
/// integrante ligado a um aluno.
library;

import 'package:flutter/material.dart';

import '../models/group_points.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

Future<void> showGroupPointsDialog(
  BuildContext context, {
  required Map<String, dynamic> group,
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: const EdgeInsets.all(20),
      child: GroupPointsPanel(group: group),
    ),
  );
}

String _date(DateTime? value) {
  if (value == null) return '';
  final local = value.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}/${two(local.month)}/${local.year}';
}

class GroupPointsPanel extends StatefulWidget {
  /// O grupo como a lista de grupos o devolve (id, nome, integrantes).
  final Map<String, dynamic> group;

  /// Troca o serviço nos testes.
  final EducationService? service;

  /// Dia de hoje; os testes o fixam.
  final DateTime Function() clock;

  const GroupPointsPanel({
    super.key,
    required this.group,
    this.service,
    this.clock = DateTime.now,
  });

  @override
  State<GroupPointsPanel> createState() => _GroupPointsPanelState();
}

class _GroupPointsPanelState extends State<GroupPointsPanel> {
  EducationService get _service => widget.service ?? education;

  String get _groupId => '${widget.group['id']}';
  String get _groupName => '${widget.group['name']}';

  final _points = TextEditingController();
  final _reason = TextEditingController();
  DateTime? _pickedDate;
  bool _credit = false;
  GroupPointEntry? _editing;

  GroupPointsHistory _history = const GroupPointsHistory(groupId: '');
  bool _loading = true;
  bool _busy = false;
  bool _error = false;
  String _message = '';

  ({int linked, int total}) get _links =>
      memberLinkCounts((widget.group['members'] as List?) ?? const []);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _points.dispose();
    _reason.dispose();
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

  Future<void> _load() async {
    try {
      final history = await _service.listProjectGroupPoints(_groupId);
      if (!mounted) return;
      setState(() {
        _history = history;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      _report('Falha ao carregar: ${_errorText(e)}', error: true);
    }
  }

  void _resetForm() {
    _points.clear();
    _reason.clear();
    _pickedDate = null;
    _credit = false;
    _editing = null;
  }

  Future<void> _pickDate() async {
    final now = widget.clock();
    final picked = await showDatePicker(
      context: context,
      initialDate: _pickedDate ?? now,
      firstDate: DateTime(now.year - 1),
      lastDate: DateTime(now.year, now.month, now.day).add(const Duration(days: 1)),
      helpText: 'Data do lançamento',
    );
    if (picked == null || !mounted) return;
    final base = widget.clock();
    setState(() => _pickedDate =
        DateTime(picked.year, picked.month, picked.day, base.hour, base.minute));
  }

  Future<void> _submit() async {
    final value = parseGroupPoints(_points.text);
    if (value == null) {
      _report(
        'Informe os pontos: um número diferente de zero, até '
        '${formatGroupPoints(maxGroupPoints, sign: false)} (use − para tirar).',
        error: true,
      );
      return;
    }
    final editing = _editing;
    setState(() => _busy = true);
    try {
      final result = editing == null
          ? await _service.addProjectGroupPoints(
              _groupId,
              points: value,
              reason: _reason.text.trim(),
              date: _pickedDate,
              creditMembers: _credit,
            )
          : await _service.updateProjectGroupPoints(
              _groupId,
              editing.id,
              points: value,
              reason: _reason.text.trim(),
              date: _pickedDate,
              creditMembers: _credit,
            );
      setState(_resetForm);
      await _load();
      final extra = '${result['message'] ?? ''}'.trim();
      _report([
        editing == null ? 'Pontos lançados.' : 'Lançamento corrigido.',
        if (extra.isNotEmpty) extra,
      ].join(' '));
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _startEdit(GroupPointEntry entry) => setState(() {
        _editing = entry;
        _points.text = formatGroupPoints(entry.points, sign: false)
            .replaceAll('−', '-');
        _reason.text = entry.reason;
        _pickedDate = entry.entryDate?.toLocal();
        _credit = entry.creditMembers;
        _message = '';
      });

  Future<void> _delete(GroupPointEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Apagar o lançamento de ${formatGroupPoints(entry.points)}?'),
        content: Text(entry.creditMembers && entry.creditedCount > 0
            ? 'O total do grupo diminui e o ponto também sai de '
                '${entry.creditedCount} integrante'
                '${entry.creditedCount == 1 ? '' : 's'}.'
            : 'O total do grupo diminui.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            key: const ValueKey('confirmar-apagar'),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Apagar'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => _busy = true);
    try {
      await _service.deleteProjectGroupPoints(_groupId, entry.id);
      if (_editing?.id == entry.id) setState(_resetForm);
      await _load();
      _report('Lançamento apagado.');
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _form() {
    final links = _links;
    final editing = _editing;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          editing == null ? 'NOVO LANÇAMENTO' : 'CORRIGIR LANÇAMENTO',
          style: const TextStyle(
              fontSize: 10, letterSpacing: 1.5, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 6),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 150,
              child: TextField(
                key: const ValueKey('campo-pontos'),
                controller: _points,
                keyboardType: const TextInputType.numberWithOptions(
                    decimal: true, signed: true),
                decoration: const InputDecoration(
                  labelText: 'Pontos',
                  hintText: 'ex.: 1 ou -0,5',
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: TextField(
                key: const ValueKey('campo-motivo'),
                controller: _reason,
                maxLength: 500,
                decoration: const InputDecoration(
                  labelText: 'Motivo',
                  hintText: 'ex.: melhor apresentação',
                  counterText: '',
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 4, children: [
          for (final preset in const ['+0,5', '+1', '+2', '−0,5', '−1'])
            ActionChip(
              key: ValueKey('rapido-$preset'),
              label: Text(preset, style: const TextStyle(fontSize: 11)),
              onPressed: () => setState(() => _points.text = preset),
            ),
        ]),
        const SizedBox(height: 6),
        Row(children: [
          OutlinedButton.icon(
            key: const ValueKey('escolher-data'),
            onPressed: _busy ? null : _pickDate,
            icon: const Icon(Icons.event, size: 16),
            label: Text(_pickedDate == null
                ? 'Hoje'
                : _date(_pickedDate)),
          ),
          if (_pickedDate != null)
            IconButton(
              tooltip: 'Voltar para hoje',
              onPressed: () => setState(() => _pickedDate = null),
              icon: const Icon(Icons.close, size: 16),
            ),
        ]),
        SwitchListTile(
          key: const ValueKey('creditar-integrantes'),
          dense: true,
          contentPadding: EdgeInsets.zero,
          title: const Text('Creditar também a cada integrante'),
          subtitle: Text(
            links.linked == 0
                ? 'Nenhum integrante está ligado a um aluno cadastrado: '
                    'nada seria creditado.'
                : '${links.linked} de ${links.total} integrantes estão ligados a '
                    'um aluno e recebem o ponto na aba Pontuações.'
                    '${links.linked < links.total ? ' Os outros ficam de fora.' : ''}',
            key: const ValueKey('resumo-creditar'),
          ),
          value: _credit && links.linked > 0,
          onChanged: _busy || links.linked == 0
              ? null
              : (value) => setState(() => _credit = value),
        ),
        Row(children: [
          FilledButton.icon(
            key: const ValueKey('lancar'),
            onPressed: _busy ? null : _submit,
            icon: Icon(editing == null ? Icons.add : Icons.check, size: 16),
            label: Text(editing == null ? 'LANÇAR' : 'SALVAR CORREÇÃO'),
          ),
          if (editing != null) ...[
            const SizedBox(width: 8),
            TextButton(
              key: const ValueKey('cancelar-correcao'),
              onPressed: _busy ? null : () => setState(_resetForm),
              child: const Text('Cancelar correção'),
            ),
          ],
        ]),
      ],
    );
  }

  Widget _entryRow(GroupPointEntry entry) {
    final color =
        entry.isSubtraction ? AssistantTheme.danger : AssistantTheme.c3;
    return Container(
      key: ValueKey('lancamento-${entry.id}'),
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: AssistantTheme.border)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 64,
            child: Text(
              formatGroupPoints(entry.points),
              key: ValueKey('valor-${entry.id}'),
              style: TextStyle(
                  fontWeight: FontWeight.bold, fontSize: 15, color: color),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(entry.reason.isEmpty ? 'sem motivo' : entry.reason),
                Text(
                  '${_date(entry.entryDate)} · ${entry.scopeLabel}',
                  style: const TextStyle(
                      fontSize: 11, color: AssistantTheme.textMuted),
                ),
              ],
            ),
          ),
          IconButton(
            key: ValueKey('editar-${entry.id}'),
            tooltip: 'Corrigir',
            visualDensity: VisualDensity.compact,
            onPressed: _busy ? null : () => _startEdit(entry),
            icon: const Icon(Icons.edit_outlined, size: 18),
          ),
          IconButton(
            key: ValueKey('apagar-${entry.id}'),
            tooltip: 'Apagar',
            visualDensity: VisualDensity.compact,
            onPressed: _busy ? null : () => _delete(entry),
            icon: const Icon(Icons.delete_outline, size: 18),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final total = _history.total;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 620, maxHeight: 760),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: _loading
            ? const SizedBox(
                height: 160, child: Center(child: CircularProgressIndicator()))
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Expanded(
                      child: Text('PONTOS · $_groupName',
                          style: const TextStyle(
                              fontWeight: FontWeight.bold, letterSpacing: 1.5)),
                    ),
                    IconButton(
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close),
                    ),
                  ]),
                  Text(
                    'Total do grupo: ${formatGroupPoints(total)}'
                    ' (${_history.entries.length} lançamento'
                    '${_history.entries.length == 1 ? '' : 's'})',
                    key: const ValueKey('total-grupo'),
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.bold,
                      color: total < 0
                          ? AssistantTheme.danger
                          : AssistantTheme.c3,
                    ),
                  ),
                  if (_message.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(_message,
                          key: const ValueKey('mensagem'),
                          style: TextStyle(
                              fontSize: 12,
                              color: _error
                                  ? AssistantTheme.danger
                                  : AssistantTheme.c3)),
                    ),
                  const SizedBox(height: 12),
                  Expanded(
                    child: ListView(children: [
                      _form(),
                      const SizedBox(height: 18),
                      const Text('HISTÓRICO',
                          style: TextStyle(
                              fontSize: 10,
                              letterSpacing: 1.5,
                              color: AssistantTheme.textMuted)),
                      const SizedBox(height: 6),
                      if (_history.entries.isEmpty)
                        const Text(
                          'Nenhum lançamento ainda.',
                          key: ValueKey('historico-vazio'),
                          style: TextStyle(color: AssistantTheme.textMuted),
                        ),
                      for (final entry in _history.entries) _entryRow(entry),
                    ]),
                  ),
                ],
              ),
      ),
    );
  }
}

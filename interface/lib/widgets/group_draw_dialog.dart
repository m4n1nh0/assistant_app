/// Sorteio da ordem de apresentacao dos grupos de projeto.
///
/// Dois modos, os dois verificaveis pela semente que fica a mostra: a ordem
/// inteira de uma vez, ou um grupo por clique. A visao de projecao existe para
/// a turma acompanhar o sorteio no telao.
library;

import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

import '../models/group_draw.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

Future<void> showGroupDrawDialog(
  BuildContext context, {
  required Discipline discipline,
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: const EdgeInsets.all(20),
      child: GroupDrawPanel(discipline: discipline),
    ),
  );
}

/// Quanto tempo os nomes "giram" antes de o resultado aparecer. O resultado ja
/// veio do servidor; a espera e so para a turma ver o sorteio acontecer.
const _spinDuration = Duration(milliseconds: 1800);

String _errorText(Object error) => error is EducationException
    ? error.message
    : '$error'.replaceFirst('Exception: ', '');

String statusLabel(String status) {
  switch (status) {
    case GroupDrawEntry.statusPresenting:
      return 'NA VEZ';
    case GroupDrawEntry.statusDone:
      return 'APRESENTOU';
    case GroupDrawEntry.statusAbsent:
      return 'AUSENTE';
    default:
      return 'AGUARDANDO';
  }
}

Color statusColor(String status) {
  switch (status) {
    case GroupDrawEntry.statusPresenting:
      return AssistantTheme.c1;
    case GroupDrawEntry.statusDone:
      return AssistantTheme.c3;
    case GroupDrawEntry.statusAbsent:
      return AssistantTheme.danger;
    default:
      return AssistantTheme.textMuted;
  }
}

class GroupDrawPanel extends StatefulWidget {
  final Discipline discipline;

  /// Troca o servico nos testes.
  final EducationService? service;

  const GroupDrawPanel({super.key, required this.discipline, this.service});

  @override
  State<GroupDrawPanel> createState() => _GroupDrawPanelState();
}

class _GroupDrawPanelState extends State<GroupDrawPanel> {
  EducationService get _service => widget.service ?? education;

  final _perDay = TextEditingController();
  final _title = TextEditingController();
  final _random = Random();

  List<GroupDraw> _history = const [];
  GroupDraw? _draw;
  String _mode = GroupDraw.modeQueue;
  bool _loading = true;
  bool _busy = false;
  bool _creating = false;
  bool _projecting = false;
  String _message = '';
  bool _error = false;

  /// Nome que aparece girando na projecao; `null` quando nao esta sorteando.
  String? _spinning;
  Timer? _spinTimer;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _spinTimer?.cancel();
    _perDay.dispose();
    _title.dispose();
    super.dispose();
  }

  void _report(String text, {bool error = false}) {
    if (!mounted) return;
    setState(() {
      _message = text;
      _error = error;
    });
  }

  Future<void> _load() async {
    try {
      final history =
          await _service.listGroupDraws(disciplineId: widget.discipline.id);
      GroupDraw? latest;
      if (history.isNotEmpty) latest = await _service.getGroupDraw(history.first.id);
      if (!mounted) return;
      setState(() {
        _history = history;
        _draw = latest;
        _creating = latest == null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      _report('Falha ao carregar os sorteios: ${_errorText(e)}', error: true);
    }
  }

  Future<void> _refreshHistory() async {
    final history =
        await _service.listGroupDraws(disciplineId: widget.discipline.id);
    if (mounted) setState(() => _history = history);
  }

  /// Roda uma chamada ao servidor com o painel travado e o erro na tela.
  Future<void> _run(Future<GroupDraw> Function() call) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final updated = await call();
      if (!mounted) return;
      setState(() {
        _draw = updated;
        _creating = false;
        _message = '';
      });
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _create() async {
    final perDay = int.tryParse(_perDay.text.trim());
    await _run(() => _service.createGroupDraw(
          disciplineId: widget.discipline.id,
          semester: widget.discipline.semester,
          title: _title.text.trim(),
          mode: _mode,
          perDay: perDay != null && perDay > 0 ? perDay : null,
        ));
    if (_draw != null && mounted) await _refreshHistory();
  }

  Future<void> _select(String? id) async {
    if (id == null) return;
    await _run(() => _service.getGroupDraw(id));
  }

  /// Sorteia o proximo grupo girando os nomes enquanto o servidor responde.
  Future<void> _drawNext() async {
    final draw = _draw;
    if (draw == null || _busy || !draw.canDrawNext) return;
    final names = draw.notDrawn.map((entry) => entry.groupName).toList();

    _spinTimer?.cancel();
    setState(() => _spinning = names[_random.nextInt(names.length)]);
    _spinTimer = Timer.periodic(const Duration(milliseconds: 80), (_) {
      if (mounted) {
        setState(() => _spinning = names[_random.nextInt(names.length)]);
      }
    });

    final started = DateTime.now();
    await _run(() => _service.drawNextGroup(draw.id));
    final left = _spinDuration - DateTime.now().difference(started);
    if (!left.isNegative) await Future<void>.delayed(left);

    _spinTimer?.cancel();
    if (mounted) setState(() => _spinning = null);
  }

  Future<void> _setStatus(GroupDrawEntry entry, String status) async {
    final draw = _draw;
    if (draw == null) return;
    await _run(() => _service.setGroupDrawStatus(draw.id, entry.id, status));
  }

  Future<void> _drawRepresentative(GroupDrawEntry entry) async {
    final draw = _draw;
    if (draw == null) return;
    await _run(() => _service.drawGroupRepresentative(draw.id, entry.id));
  }

  Future<void> _delete() async {
    final draw = _draw;
    if (draw == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Excluir sorteio'),
        content: const Text(
          'O sorteio e o histórico de quem apresentou saem da lista.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('EXCLUIR'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await _service.deleteGroupDraw(draw.id);
      await _load();
    } catch (e) {
      _report('Falha ao excluir: ${_errorText(e)}', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    return ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: min(size.width - 40, 980),
        maxHeight: size.height - 40,
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: _loading
            ? const SizedBox(
                height: 160,
                child: Center(child: CircularProgressIndicator()),
              )
            : Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _header(),
                  const SizedBox(height: 10),
                  if (_message.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        _message,
                        style: TextStyle(
                          fontSize: 12,
                          color: _error
                              ? AssistantTheme.danger
                              : AssistantTheme.c3,
                        ),
                      ),
                    ),
                  Flexible(
                    child: _creating || _draw == null
                        ? _createForm()
                        : _projecting
                            ? _projection(_draw!)
                            : _drawView(_draw!),
                  ),
                ],
              ),
      ),
    );
  }

  Widget _header() {
    final draw = _draw;
    return Row(
      children: [
        Expanded(
          child: Text(
            'Sorteio de apresentação — ${widget.discipline.label}',
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
            overflow: TextOverflow.ellipsis,
          ),
        ),
        if (_history.length > 1 && draw != null && !_creating)
          DropdownButton<String>(
            value: _history.any((item) => item.id == draw.id) ? draw.id : null,
            hint: const Text('Sorteios'),
            underline: const SizedBox.shrink(),
            items: [
              for (final item in _history)
                DropdownMenuItem(
                  value: item.id,
                  child: Text(
                    '${item.title} (${item.createdAt == null ? "" : _day(item.createdAt!)})',
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
            ],
            onChanged: _busy ? null : _select,
          ),
        if (draw != null && !_creating) ...[
          IconButton(
            tooltip: _projecting ? 'Voltar à lista' : 'Projetar para a turma',
            icon: Icon(_projecting ? Icons.list : Icons.cast_outlined, size: 18),
            onPressed: () => setState(() => _projecting = !_projecting),
          ),
          IconButton(
            tooltip: 'Novo sorteio',
            icon: const Icon(Icons.add, size: 18),
            onPressed: _busy
                ? null
                : () => setState(() {
                      _creating = true;
                      _projecting = false;
                    }),
          ),
          IconButton(
            tooltip: 'Excluir sorteio',
            icon: const Icon(Icons.delete_outline, size: 18),
            onPressed: _busy ? null : _delete,
          ),
        ],
        IconButton(
          tooltip: 'Fechar',
          icon: const Icon(Icons.close, size: 18),
          onPressed: () => Navigator.pop(context),
        ),
      ],
    );
  }

  String _day(DateTime value) {
    final local = value.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(local.day)}/${two(local.month)} ${two(local.hour)}:${two(local.minute)}';
  }

  Widget _createForm() {
    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Sorteia a ordem em que os grupos da disciplina vão apresentar. '
            'O resultado pode ser conferido depois pela semente.',
            style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted),
          ),
          const SizedBox(height: 14),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                value: GroupDraw.modeQueue,
                icon: Icon(Icons.format_list_numbered, size: 16),
                label: Text('Ordem completa'),
              ),
              ButtonSegment(
                value: GroupDraw.modeOneByOne,
                icon: Icon(Icons.casino_outlined, size: 16),
                label: Text('Um grupo por vez'),
              ),
            ],
            selected: {_mode},
            onSelectionChanged: (value) => setState(() => _mode = value.first),
          ),
          const SizedBox(height: 6),
          Text(
            _mode == GroupDraw.modeQueue
                ? 'Todos os grupos saem de uma vez, já com a ordem e o dia.'
                : 'Cada clique sorteia o próximo grupo, na hora da apresentação.',
            style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              SizedBox(
                width: 220,
                child: TextField(
                  controller: _perDay,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Apresentações por dia',
                    helperText: 'Vazio: todas no mesmo dia',
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _title,
                  maxLength: 255,
                  decoration: const InputDecoration(
                    labelText: 'Nome do sorteio (opcional)',
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              FilledButton.icon(
                onPressed: _busy ? null : _create,
                icon: _busy
                    ? const SizedBox.square(
                        dimension: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.casino_outlined, size: 16),
                label: Text(_busy ? 'SORTEANDO...' : 'SORTEAR'),
              ),
              if (_draw != null) ...[
                const SizedBox(width: 8),
                TextButton(
                  onPressed: _busy ? null : () => setState(() => _creating = false),
                  child: const Text('VOLTAR AO SORTEIO ATUAL'),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  Widget _proof(GroupDraw draw) {
    return Row(
      children: [
        Icon(
          draw.verified ? Icons.verified_outlined : Icons.warning_amber_outlined,
          size: 15,
          color: draw.verified ? AssistantTheme.c3 : AssistantTheme.danger,
        ),
        const SizedBox(width: 6),
        Expanded(
          child: SelectableText(
            draw.verified
                ? 'Conferido · semente ${draw.seed} · ${draw.algorithm}'
                : 'A ordem gravada NÃO bate com a semente ${draw.seed}',
            style: const TextStyle(fontSize: 10, color: AssistantTheme.textMuted),
          ),
        ),
      ],
    );
  }

  Widget _drawView(GroupDraw draw) {
    final days = draw.byDay;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          draw.title,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 2),
        Text(
          '${draw.total} grupos · ${draw.count(GroupDrawEntry.statusDone)} '
          'apresentaram · ${draw.count(GroupDrawEntry.statusAbsent)} ausentes'
          '${draw.perDay == null ? "" : " · ${draw.perDay} por dia"}',
          style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 4),
        _proof(draw),
        const SizedBox(height: 10),
        if (draw.canDrawNext)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: FilledButton.icon(
              onPressed: _busy ? null : _drawNext,
              icon: const Icon(Icons.casino_outlined, size: 16),
              label: Text('SORTEAR PRÓXIMO GRUPO (${draw.remaining} restantes)'),
            ),
          ),
        Flexible(
          child: days.isEmpty
              ? const Center(
                  child: Text(
                    'Nenhum grupo sorteado ainda.',
                    style: TextStyle(color: AssistantTheme.textMuted),
                  ),
                )
              : ListView(
                  shrinkWrap: true,
                  children: [
                    for (final day in days.entries) ...[
                      if (days.length > 1 || draw.perDay != null)
                        Padding(
                          padding: const EdgeInsets.fromLTRB(0, 8, 0, 4),
                          child: Text(
                            'DIA ${day.key}',
                            style: const TextStyle(
                              fontSize: 11,
                              letterSpacing: 1,
                              color: AssistantTheme.c2,
                            ),
                          ),
                        ),
                      for (final entry in day.value) _entryRow(entry),
                    ],
                  ],
                ),
        ),
      ],
    );
  }

  Widget _entryRow(GroupDrawEntry entry) {
    final color = statusColor(entry.status);
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AssistantTheme.surface2,
        border: Border(left: BorderSide(color: color, width: 3)),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 34,
            child: Text(
              '${entry.position}º',
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(entry.groupName, style: const TextStyle(fontSize: 13)),
                Text(
                  entry.hasRepresentative
                      ? 'Representante: ${entry.representativeName}'
                          '${entry.representativeRound > 0 ? " (sorteio ${entry.representativeRound + 1})" : ""}'
                      : statusLabel(entry.status),
                  style: TextStyle(
                    fontSize: 10,
                    color: entry.hasRepresentative
                        ? AssistantTheme.c2
                        : color,
                  ),
                ),
              ],
            ),
          ),
          if (entry.hasRepresentative)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text(
                statusLabel(entry.status),
                style: TextStyle(fontSize: 10, color: color),
              ),
            ),
          IconButton(
            tooltip: entry.hasRepresentative
                ? 'Sortear outro representante'
                : 'Sortear representante do grupo',
            icon: const Icon(Icons.person_search_outlined, size: 17),
            onPressed: _busy ? null : () => _drawRepresentative(entry),
          ),
          IconButton(
            tooltip: 'Na vez',
            icon: const Icon(Icons.play_circle_outline, size: 17),
            color: AssistantTheme.c1,
            onPressed: _busy || entry.status == GroupDrawEntry.statusPresenting
                ? null
                : () => _setStatus(entry, GroupDrawEntry.statusPresenting),
          ),
          IconButton(
            tooltip: 'Apresentou',
            icon: const Icon(Icons.check_circle_outline, size: 17),
            color: AssistantTheme.c3,
            onPressed: _busy || entry.status == GroupDrawEntry.statusDone
                ? null
                : () => _setStatus(entry, GroupDrawEntry.statusDone),
          ),
          IconButton(
            tooltip: 'Ausente',
            icon: const Icon(Icons.person_off_outlined, size: 17),
            color: AssistantTheme.danger,
            onPressed: _busy || entry.status == GroupDrawEntry.statusAbsent
                ? null
                : () => _setStatus(entry, GroupDrawEntry.statusAbsent),
          ),
        ],
      ),
    );
  }

  /// Tela grande para o telao: quem esta na vez, quem e o representante e quem
  /// vem depois. O sorteio avulso acontece aqui, com os nomes girando.
  Widget _projection(GroupDraw draw) {
    final current = draw.current;
    final next = draw.next;
    final spinning = _spinning;

    Widget big(String text, {double size = 54, Color? color}) => FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            text,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: size,
              fontWeight: FontWeight.w700,
              color: color ?? AssistantTheme.textPrimary,
            ),
          ),
        );

    return SizedBox(
      height: 420,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (spinning != null) ...[
            const Text('SORTEANDO...',
                style: TextStyle(letterSpacing: 4, color: AssistantTheme.c2)),
            const SizedBox(height: 16),
            big(spinning, color: AssistantTheme.c2),
          ] else if (current != null) ...[
            Text(
              '${current.position}º A APRESENTAR'
              '${draw.perDay == null ? "" : " · DIA ${current.day}"}',
              style: const TextStyle(letterSpacing: 4, color: AssistantTheme.c2),
            ),
            const SizedBox(height: 16),
            big(current.groupName),
            if (current.hasRepresentative) ...[
              const SizedBox(height: 14),
              big('Representante: ${current.representativeName}',
                  size: 28, color: AssistantTheme.c3),
            ],
            const SizedBox(height: 18),
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: _busy ? null : () => _drawRepresentative(current),
                  icon: const Icon(Icons.person_search_outlined, size: 16),
                  label: Text(current.hasRepresentative
                      ? 'SORTEAR OUTRO REPRESENTANTE'
                      : 'SORTEAR REPRESENTANTE'),
                ),
                if (current.status != GroupDrawEntry.statusPresenting)
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _setStatus(current, GroupDrawEntry.statusPresenting),
                    icon: const Icon(Icons.play_circle_outline, size: 16),
                    label: const Text('COMEÇAR'),
                  ),
                FilledButton.icon(
                  onPressed: _busy
                      ? null
                      : () => _setStatus(current, GroupDrawEntry.statusDone),
                  icon: const Icon(Icons.check, size: 16),
                  label: const Text('APRESENTOU'),
                ),
                OutlinedButton.icon(
                  onPressed: _busy
                      ? null
                      : () => _setStatus(current, GroupDrawEntry.statusAbsent),
                  icon: const Icon(Icons.person_off_outlined, size: 16),
                  label: const Text('AUSENTE'),
                ),
              ],
            ),
            if (next != null) ...[
              const SizedBox(height: 22),
              Text(
                'Depois: ${next.groupName}',
                style: const TextStyle(
                    fontSize: 15, color: AssistantTheme.textMuted),
              ),
            ],
          ] else
            big(draw.finished ? 'Todos os grupos já foram chamados' : 'Pronto para sortear',
                size: 34, color: AssistantTheme.textMuted),
          const SizedBox(height: 22),
          if (draw.canDrawNext && spinning == null)
            FilledButton.icon(
              onPressed: _busy ? null : _drawNext,
              icon: const Icon(Icons.casino_outlined, size: 18),
              label: Text('SORTEAR PRÓXIMO GRUPO (${draw.remaining} restantes)'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 16),
              ),
            ),
        ],
      ),
    );
  }
}

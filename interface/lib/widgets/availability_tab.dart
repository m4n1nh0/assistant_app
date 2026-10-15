/// Agenda de atendimento: as faixas semanais em que você atende, as exceções por data e a
/// prévia de como o aluno vê, já cruzada com o seu calendário.
///
/// O aluno enxerga a agenda numa aba do portal. Cada faixa diz se é presencial ou online,
/// o local ou o link e para quem vale (todos, graduação ou mentoria). A mesma agenda alimenta
/// o plano de encontros da mentoria.
library;

import 'package:flutter/material.dart';

import '../models/availability.dart';
import '../services/api_service.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

typedef BusyEventsLoader = Future<List<BusyEvent>> Function(DateTime start, DateTime end);

/// Eventos do Google/Microsoft Calendar do professor, pelo cliente que o app já usa.
Future<List<BusyEvent>> loadCalendarEvents(DateTime start, DateTime end) async {
  final rows = await api.getEvents(start: start, end: end, maxResults: 100);
  final events = <BusyEvent>[];
  for (final row in rows) {
    final from = DateTime.tryParse('${row['start_time'] ?? row['startTime'] ?? ''}')?.toLocal();
    if (from == null) continue;
    final to = DateTime.tryParse('${row['end_time'] ?? row['endTime'] ?? ''}')?.toLocal() ??
        from.add(const Duration(hours: 1));
    events.add(BusyEvent(title: '${row['title'] ?? 'Evento'}', start: from, end: to));
  }
  return events;
}

class AvailabilityTab extends StatefulWidget {
  /// Trocam serviço e leitura do calendário nos testes.
  final EducationService? service;
  final BusyEventsLoader? loadEvents;

  const AvailabilityTab({super.key, this.service, this.loadEvents});

  @override
  State<AvailabilityTab> createState() => _AvailabilityTabState();
}

class _AvailabilityTabState extends State<AvailabilityTab> {
  EducationService get _service => widget.service ?? education;

  List<AvailabilitySlot> _slots = const [];
  List<AvailabilityException> _exceptions = const [];
  List<AvailabilityOccurrence> _occurrences = const [];
  List<AvailabilityConflict> _conflicts = const [];
  String? _audience; // nulo = tudo, como o professor vê
  bool _calendarOk = true;
  bool _loading = true;
  bool _busy = false;
  String _message = '';
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _load();
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
      final overview = await _service.availabilityOverview();
      final preview = await _service.availabilityPreview(days: 28, audience: _audience);
      if (!mounted) return;
      setState(() {
        _slots = overview.slots;
        _exceptions = overview.exceptions;
        _occurrences = preview;
        _loading = false;
      });
      await _crossWithCalendar();
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      _report('Falha ao carregar a agenda: ${_errorText(e)}', error: true);
    }
  }

  /// Cruza os atendimentos com o calendário. Sem calendário conectado a agenda segue
  /// valendo; só deixa de avisar dos choques, e a tela diz isso em vez de calar.
  Future<void> _crossWithCalendar() async {
    final dates = [for (final o in _occurrences) if (!o.blocked) o.starts].whereType<DateTime>();
    if (dates.isEmpty) {
      if (mounted) setState(() => _conflicts = const []);
      return;
    }
    final start = dates.reduce((a, b) => a.isBefore(b) ? a : b);
    final end = dates.reduce((a, b) => a.isAfter(b) ? a : b).add(const Duration(days: 1));
    try {
      final events = await (widget.loadEvents ?? loadCalendarEvents)(start, end);
      if (!mounted) return;
      setState(() {
        _conflicts = findConflicts(_occurrences, events);
        _calendarOk = true;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _conflicts = const [];
          _calendarOk = false;
        });
      }
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

  // --- faixas -------------------------------------------------------------------------

  Future<void> _editSlot([AvailabilitySlot? current]) async {
    var weekday = current?.weekday ?? 3;
    var mode = current?.mode ?? 'ambos';
    var audience = current?.audience ?? 'todos';
    final start = TextEditingController(text: current?.startTime ?? '');
    final end = TextEditingController(text: current?.endTime ?? '');
    final location = TextEditingController(text: current?.location ?? '');
    final note = TextEditingController(text: current?.note ?? '');
    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text(current == null ? 'Nova faixa de atendimento' : 'Editar faixa'),
          content: SizedBox(
            width: 460,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                DropdownButtonFormField<int>(
                  key: const Key('slot-weekday'),
                  initialValue: weekday,
                  decoration: const InputDecoration(labelText: 'DIA DA SEMANA', isDense: true),
                  items: [
                    for (var i = 0; i < 7; i++)
                      DropdownMenuItem(value: i, child: Text(weekdayNames[i])),
                  ],
                  onChanged: (v) => setDialogState(() => weekday = v ?? weekday),
                ),
                const SizedBox(height: 8),
                Row(children: [
                  Expanded(
                    child: TextField(
                      key: const Key('slot-start'),
                      controller: start,
                      decoration: const InputDecoration(
                          labelText: 'DAS (HH:MM)', hintText: '19:00', isDense: true),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      key: const Key('slot-end'),
                      controller: end,
                      decoration: const InputDecoration(
                          labelText: 'ATÉ (HH:MM)', hintText: '21:00', isDense: true),
                    ),
                  ),
                ]),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: mode,
                  decoration: const InputDecoration(labelText: 'MODALIDADE', isDense: true),
                  items: [
                    for (final e in availabilityModes.entries)
                      DropdownMenuItem(value: e.key, child: Text(e.value)),
                  ],
                  onChanged: (v) => setDialogState(() => mode = v ?? mode),
                ),
                const SizedBox(height: 8),
                TextField(
                  key: const Key('slot-location'),
                  controller: location,
                  decoration: const InputDecoration(
                      labelText: 'LOCAL OU LINK DA REUNIÃO ONLINE', isDense: true),
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: audience,
                  decoration: const InputDecoration(labelText: 'PARA QUEM VALE', isDense: true),
                  items: [
                    for (final e in availabilityAudiences.entries)
                      DropdownMenuItem(value: e.key, child: Text(e.value)),
                  ],
                  onChanged: (v) => setDialogState(() => audience = v ?? audience),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: note,
                  decoration: const InputDecoration(labelText: 'OBSERVAÇÃO', isDense: true),
                ),
              ]),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('CANCELAR')),
            FilledButton(
                key: const Key('slot-save'),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('SALVAR')),
          ],
        ),
      ),
    );
    final body = {
      'weekday': weekday,
      'start_time': start.text.trim(),
      'end_time': end.text.trim(),
      'mode': mode,
      'location': location.text.trim(),
      'audience': audience,
      'note': note.text.trim(),
    };
    // Sem dispose: a animação de fechar do diálogo ainda desenha estes campos.
    if (saved != true) return;
    await _guard(() async {
      await _service.saveAvailabilitySlot(body, id: current?.id);
      await _load();
      _report(current == null ? 'Faixa criada.' : 'Faixa atualizada.');
    });
  }

  Future<void> _toggleSlot(AvailabilitySlot slot) => _guard(() async {
        await _service.saveAvailabilitySlot({'active': !slot.active}, id: slot.id);
        await _load();
      });

  Future<void> _deleteSlot(AvailabilitySlot slot) => _guard(() async {
        await _service.deleteAvailabilitySlot(slot.id);
        await _load();
        _report('Faixa apagada.');
      });

  // --- exceções -----------------------------------------------------------------------

  Future<void> _addException() async {
    var kind = 'blocked';
    var mode = 'ambos';
    var audience = 'todos';
    DateTime? day;
    final start = TextEditingController();
    final end = TextEditingController();
    final location = TextEditingController();
    final note = TextEditingController();
    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: const Text('Exceção por data'),
          content: SizedBox(
            width: 460,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                SegmentedButton<String>(
                  key: const Key('exc-kind'),
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: 'blocked', label: Text('NÃO ATENDO NO DIA')),
                    ButtonSegment(value: 'extra', label: Text('HORÁRIO EXTRA')),
                  ],
                  selected: {kind},
                  onSelectionChanged: (v) => setDialogState(() => kind = v.first),
                ),
                const SizedBox(height: 10),
                Align(
                  alignment: Alignment.centerLeft,
                  child: OutlinedButton.icon(
                    key: const Key('exc-day'),
                    onPressed: () async {
                      final now = DateTime.now();
                      final picked = await showDatePicker(
                        context: dialogContext,
                        initialDate: day ?? now,
                        firstDate: now.subtract(const Duration(days: 1)),
                        lastDate: now.add(const Duration(days: 365)),
                      );
                      if (picked != null) setDialogState(() => day = picked);
                    },
                    icon: const Icon(Icons.event, size: 16),
                    label: Text(day == null ? 'ESCOLHER A DATA' : _isoDay(day!)),
                  ),
                ),
                if (kind == 'extra') ...[
                  const SizedBox(height: 8),
                  Row(children: [
                    Expanded(
                      child: TextField(
                        key: const Key('exc-start'),
                        controller: start,
                        decoration: const InputDecoration(
                            labelText: 'DAS (HH:MM)', isDense: true),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextField(
                        key: const Key('exc-end'),
                        controller: end,
                        decoration: const InputDecoration(
                            labelText: 'ATÉ (HH:MM)', isDense: true),
                      ),
                    ),
                  ]),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    initialValue: mode,
                    decoration: const InputDecoration(labelText: 'MODALIDADE', isDense: true),
                    items: [
                      for (final e in availabilityModes.entries)
                        DropdownMenuItem(value: e.key, child: Text(e.value)),
                    ],
                    onChanged: (v) => setDialogState(() => mode = v ?? mode),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: location,
                    decoration: const InputDecoration(
                        labelText: 'LOCAL OU LINK', isDense: true),
                  ),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    initialValue: audience,
                    decoration:
                        const InputDecoration(labelText: 'PARA QUEM VALE', isDense: true),
                    items: [
                      for (final e in availabilityAudiences.entries)
                        DropdownMenuItem(value: e.key, child: Text(e.value)),
                    ],
                    onChanged: (v) => setDialogState(() => audience = v ?? audience),
                  ),
                ],
                const SizedBox(height: 8),
                TextField(
                  key: const Key('exc-note'),
                  controller: note,
                  decoration: const InputDecoration(
                      labelText: 'MOTIVO (OS ALUNOS VEEM)', isDense: true),
                ),
              ]),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('CANCELAR')),
            FilledButton(
                key: const Key('exc-save'),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('SALVAR')),
          ],
        ),
      ),
    );
    final chosen = day;
    final body = {
      'kind': kind,
      if (chosen != null) 'day': _isoDay(chosen),
      if (kind == 'extra') ...{
        'start_time': start.text.trim(),
        'end_time': end.text.trim(),
        'mode': mode,
        'location': location.text.trim(),
        'audience': audience,
      },
      'note': note.text.trim(),
    };
    if (saved != true) return;
    if (chosen == null) {
      _report('Escolha a data.', error: true);
      return;
    }
    await _guard(() async {
      await _service.createAvailabilityException(body);
      await _load();
      _report('Exceção salva.');
    });
  }

  Future<void> _deleteException(AvailabilityException item) => _guard(() async {
        await _service.deleteAvailabilityException(item.id);
        await _load();
      });

  Future<void> _setAudience(String? audience) async {
    setState(() => _audience = audience);
    await _load();
  }

  // --- tela ---------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        Row(children: [
          const Icon(Icons.event_available_outlined, color: AssistantTheme.c3),
          const SizedBox(width: 8),
          const Expanded(
            child: Text('AGENDA DE ATENDIMENTO',
                style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.6)),
          ),
          OutlinedButton.icon(
            key: const Key('avail-new-exception'),
            onPressed: _busy ? null : _addException,
            icon: const Icon(Icons.event_busy_outlined, size: 16),
            label: const Text('EXCEÇÃO POR DATA'),
          ),
          const SizedBox(width: 8),
          FilledButton.icon(
            key: const Key('avail-new-slot'),
            onPressed: _busy ? null : () => _editSlot(),
            icon: const Icon(Icons.add, size: 16),
            label: const Text('NOVA FAIXA'),
          ),
        ]),
        if (_message.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_message,
                style: TextStyle(
                    fontSize: 12, color: _error ? Colors.redAccent : AssistantTheme.c3)),
          ),
        const SizedBox(height: 10),
        _buildWeek(),
        const SizedBox(height: 12),
        _buildExceptions(),
        const SizedBox(height: 12),
        _buildPreview(),
      ],
    );
  }

  Widget _buildWeek() {
    return _Panel(
      title: 'HORÁRIOS DA SEMANA',
      child: _slots.isEmpty
          ? const _Hint('Nenhuma faixa ainda. Clique em NOVA FAIXA e diga, por exemplo, '
              'quinta das 19:00 às 21:00.')
          : Column(children: [
              for (var day = 0; day < 7; day++)
                if (_slots.any((s) => s.weekday == day))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      SizedBox(
                        width: 84,
                        child: Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: Text(weekdayNames[day],
                              style: const TextStyle(
                                  fontWeight: FontWeight.w800, fontSize: 13)),
                        ),
                      ),
                      Expanded(
                        child: Column(children: [
                          for (final slot in _slots.where((s) => s.weekday == day))
                            _buildSlot(slot),
                        ]),
                      ),
                    ]),
                  ),
            ]),
    );
  }

  Widget _buildSlot(AvailabilitySlot slot) {
    return Container(
      margin: const EdgeInsets.only(bottom: 4),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AssistantTheme.border),
      ),
      child: Opacity(
        opacity: slot.active ? 1 : .5,
        child: Row(children: [
          Expanded(
            child: Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center,
                children: [
              Text(slot.range,
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
              _Chip(availabilityModes[slot.mode] ?? slot.mode, AssistantTheme.c1),
              if (slot.audience != 'todos')
                _Chip(availabilityAudiences[slot.audience] ?? slot.audience, AssistantTheme.c2),
              if (!slot.active) _Chip('DESLIGADA', AssistantTheme.textMuted),
              if (slot.location.isNotEmpty)
                Text(slot.location,
                    style: const TextStyle(fontSize: 11, color: AssistantTheme.textSecondary)),
              if (slot.note.isNotEmpty)
                Text(slot.note,
                    style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
            ]),
          ),
          Switch(
            key: Key('slot-active-${slot.id}'),
            value: slot.active,
            onChanged: _busy ? null : (_) => _toggleSlot(slot),
          ),
          IconButton(
              tooltip: 'Editar',
              onPressed: _busy ? null : () => _editSlot(slot),
              icon: const Icon(Icons.edit_outlined, size: 16)),
          IconButton(
              tooltip: 'Apagar',
              onPressed: _busy ? null : () => _deleteSlot(slot),
              icon: const Icon(Icons.delete_outline, size: 16)),
        ]),
      ),
    );
  }

  Widget _buildExceptions() {
    return _Panel(
      title: 'EXCEÇÕES POR DATA',
      child: _exceptions.isEmpty
          ? const _Hint('Nenhuma exceção. Use para bloquear um dia (viagem, feriado) ou '
              'abrir um horário extra numa data.')
          : Column(children: [
              for (final item in _exceptions)
                Container(
                  margin: const EdgeInsets.only(bottom: 4),
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: AssistantTheme.border),
                  ),
                  child: Row(children: [
                    Expanded(
                      child: Wrap(spacing: 8, runSpacing: 4,
                          crossAxisAlignment: WrapCrossAlignment.center, children: [
                        Text(_brDay(item.day),
                            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
                        item.isBlocked
                            ? _Chip('NÃO ATENDO', Colors.redAccent)
                            : _Chip('EXTRA ${item.startTime}–${item.endTime}', AssistantTheme.c4),
                        if (item.note.isNotEmpty)
                          Text(item.note,
                              style: const TextStyle(
                                  fontSize: 11, color: AssistantTheme.textSecondary)),
                      ]),
                    ),
                    IconButton(
                        tooltip: 'Apagar exceção',
                        onPressed: _busy ? null : () => _deleteException(item),
                        icon: const Icon(Icons.delete_outline, size: 16)),
                  ]),
                ),
            ]),
    );
  }

  Widget _buildPreview() {
    final conflictKeys = {
      for (final c in _conflicts) '${c.occurrence.date}|${c.occurrence.startTime}': c,
    };
    return _Panel(
      title: 'COMO O ALUNO VÊ · PRÓXIMOS 28 DIAS',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, children: [
          for (final entry in const {
            null: 'Tudo (visão sua)',
            'graduacao': 'Aluno de graduação',
            'mentoria': 'Aluno de mentoria',
          }.entries)
            ChoiceChip(
              label: Text(entry.value, style: const TextStyle(fontSize: 11)),
              selected: _audience == entry.key,
              onSelected: (_) => _setAudience(entry.key),
            ),
        ]),
        const SizedBox(height: 8),
        if (!_calendarOk)
          const _Hint('Não consegui ler o seu calendário, então os choques não foram '
              'conferidos. Conecte uma conta em Configurações > Calendários.')
        else if (_conflicts.isEmpty && _occurrences.any((o) => !o.blocked))
          const _Hint('Nenhum choque com o seu calendário nestes dias.')
        else if (_conflicts.isNotEmpty)
          Text('${_conflicts.length} choque(s) com o seu calendário nestes dias.',
              key: const Key('avail-conflicts'),
              style: const TextStyle(fontSize: 12, color: Colors.amber)),
        const SizedBox(height: 6),
        if (_occurrences.isEmpty)
          const _Hint('Nada publicado para este público nos próximos dias.')
        else
          for (final o in _occurrences)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(
                  width: 108,
                  child: Text('${weekdayNames[o.weekday].substring(0, 3)} ${_brDay(o.date)}',
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
                ),
                Expanded(
                  child: o.blocked
                      ? Text('Sem atendimento${o.note.isEmpty ? '' : ' · ${o.note}'}',
                          style: const TextStyle(fontSize: 12, color: Colors.redAccent))
                      : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(
                            '${o.startTime} às ${o.endTime} · '
                            '${availabilityModes[o.mode] ?? o.mode}'
                            '${o.location.isEmpty ? '' : ' · ${o.location}'}'
                            '${o.source == 'extra' ? ' · extra' : ''}',
                            style: const TextStyle(fontSize: 12),
                          ),
                          if (conflictKeys['${o.date}|${o.startTime}'] case final c?)
                            Text('⚠ Choca com: ${c.event.title}',
                                style: const TextStyle(fontSize: 11, color: Colors.amber)),
                        ]),
                ),
              ]),
            ),
      ]),
    );
  }
}

String _isoDay(DateTime d) =>
    '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

String _brDay(String iso) {
  final parts = iso.split('-');
  return parts.length == 3 ? '${parts[2]}/${parts[1]}' : iso;
}

class _Panel extends StatelessWidget {
  final String title;
  final Widget child;

  const _Panel({required this.title, required this.child});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AssistantTheme.bg.withOpacity(.38),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AssistantTheme.c3.withOpacity(.45)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title,
              style: const TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1,
                  color: AssistantTheme.c3)),
          const SizedBox(height: 8),
          child,
        ]),
      );
}

class _Chip extends StatelessWidget {
  final String text;
  final Color color;

  const _Chip(this.text, this.color);

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

class _Hint extends StatelessWidget {
  final String text;

  const _Hint(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text(text,
            style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
      );
}

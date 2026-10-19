/// Periodo do semestre (inicio e fim das aulas) e datas sem aula.
///
/// O horario semanal da turma diz "segunda, 18:30" e repete para sempre. Aqui o professor diz
/// quando o semestre comeca e termina e em quais datas nao ha aula (feriado, recesso, aula
/// cancelada), e o assistente passa a responder "tem aula hoje?" com isso.
library;

import 'package:flutter/material.dart';

import '../services/education_service.dart';
import '../utils/theme.dart';

/// AAAA-MM-DD, o formato que o backend guarda.
String isoDay(DateTime day) =>
    '${day.year.toString().padLeft(4, '0')}-${day.month.toString().padLeft(2, '0')}-${day.day.toString().padLeft(2, '0')}';

/// De AAAA-MM-DD para DD/MM/AAAA; texto que nao e data volta como veio.
String brDay(String iso) {
  final parts = iso.split('-');
  if (parts.length != 3 || parts.any((part) => part.isEmpty)) return iso;
  return '${parts[2]}/${parts[1]}/${parts[0]}';
}

/// De AAAA-MM-DD para data; `null` quando vazio ou invalido.
DateTime? parseIsoDay(String iso) {
  final parts = iso.split('-');
  if (parts.length != 3) return null;
  final year = int.tryParse(parts[0]);
  final month = int.tryParse(parts[1]);
  final day = int.tryParse(parts[2]);
  if (year == null || month == null || day == null) return null;
  final parsed = DateTime(year, month, day);
  // DateTime "rola" datas invalidas (31/02 vira 03/03): confere que ficou igual.
  return parsed.year == year && parsed.month == month && parsed.day == day
      ? parsed
      : null;
}

/// Como uma data sem aula aparece na lista: um dia ou um intervalo.
String breakDates(ClassBreak item) => item.isRange
    ? '${brDay(item.dateFrom)} a ${brDay(item.dateTo)}'
    : brDay(item.dateFrom);

/// Texto do periodo para mostrar ao lado do semestre.
String periodSummary(Semester semester) {
  if (semester.startDate.isEmpty && semester.endDate.isEmpty) {
    return 'periodo nao informado';
  }
  final start =
      semester.startDate.isEmpty ? '?' : brDay(semester.startDate);
  final end = semester.endDate.isEmpty ? '?' : brDay(semester.endDate);
  final breaks = semester.breakCount == 0
      ? ''
      : '  -  ${semester.breakCount} data(s) sem aula';
  return '$start a $end$breaks';
}

class SemesterPeriodDialog extends StatefulWidget {
  final String semester;

  const SemesterPeriodDialog({super.key, required this.semester});

  @override
  State<SemesterPeriodDialog> createState() => _SemesterPeriodDialogState();
}

class _SemesterPeriodDialogState extends State<SemesterPeriodDialog> {
  final _reasonCtrl = TextEditingController();

  var _loading = true;
  var _status = '';
  var _start = '';
  var _end = '';
  List<ClassBreak> _breaks = const [];
  List<ClassGroup> _classes = const [];

  // Formulario de data sem aula.
  DateTime? _breakFrom;
  DateTime? _breakTo;
  String? _breakClassId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _reasonCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final semesters = await education.listSemesters();
      final breaks = await education.listSemesterBreaks(widget.semester);
      final classes = await education.listClasses(activeOnly: false);
      final current = semesters.where((item) => item.code == widget.semester);
      if (!mounted) return;
      setState(() {
        if (current.isNotEmpty) {
          _start = current.first.startDate;
          _end = current.first.endDate;
        }
        _breaks = breaks;
        _classes = classes
            .where((item) => item.semester == widget.semester)
            .toList();
        _loading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _status = 'Falha ao carregar: $e';
          _loading = false;
        });
      }
    }
  }

  Future<DateTime?> _pick(String current) {
    final initial = parseIsoDay(current) ?? DateTime.now();
    return showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(2020),
      lastDate: DateTime(2100),
    );
  }

  Future<void> _pickPeriod({required bool start}) async {
    final picked = await _pick(start ? _start : _end);
    if (picked == null) return;
    setState(() => start ? _start = isoDay(picked) : _end = isoDay(picked));
  }

  Future<void> _savePeriod() async {
    final from = parseIsoDay(_start);
    final to = parseIsoDay(_end);
    if (from != null && to != null && to.isBefore(from)) {
      setState(() => _status = 'O fim do semestre deve ser depois do inicio.');
      return;
    }
    try {
      await education.updateSemester(
        widget.semester,
        startDate: _start,
        endDate: _end,
      );
      if (mounted) setState(() => _status = 'Periodo salvo.');
    } catch (e) {
      if (mounted) setState(() => _status = '$e');
    }
  }

  Future<void> _addBreak() async {
    final from = _breakFrom;
    if (from == null) {
      setState(() => _status = 'Escolha a data sem aula.');
      return;
    }
    final to = _breakTo;
    if (to != null && to.isBefore(from)) {
      setState(() => _status = 'A data final deve ser depois da inicial.');
      return;
    }
    try {
      await education.createSemesterBreak(
        widget.semester,
        dateFrom: isoDay(from),
        dateTo: to == null ? null : isoDay(to),
        classGroupId: _breakClassId,
        reason: _reasonCtrl.text.trim(),
      );
      _reasonCtrl.clear();
      setState(() {
        _breakFrom = null;
        _breakTo = null;
        _status = '';
      });
      await _load();
    } catch (e) {
      if (mounted) setState(() => _status = '$e');
    }
  }

  Future<void> _removeBreak(ClassBreak item) async {
    try {
      await education.deleteSemesterBreak(widget.semester, item.id);
      await _load();
    } catch (e) {
      if (mounted) setState(() => _status = '$e');
    }
  }

  Widget _dateButton({
    required String label,
    required String value,
    required VoidCallback onPressed,
    VoidCallback? onClear,
  }) {
    return Expanded(
      child: Row(
        children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: onPressed,
              icon: const Icon(Icons.event_outlined, size: 14),
              label: Text(
                value.isEmpty ? label : '$label  ${brDay(value)}',
                style: const TextStyle(fontSize: 10),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
          if (onClear != null && value.isNotEmpty)
            IconButton(
              tooltip: 'Limpar',
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.close, size: 14),
              onPressed: onClear,
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: Text('Periodo do semestre ${widget.semester}'),
      content: SizedBox(
        width: 560,
        height: 520,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Com o inicio e o fim das aulas e as datas sem aula, o '
                    'assistente sabe quando ha aula de verdade, em vez de '
                    'repetir o horario semanal para sempre.',
                    style: TextStyle(
                        fontSize: 11, color: AssistantTheme.textSecondary),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      _dateButton(
                        label: 'INICIO',
                        value: _start,
                        onPressed: () => _pickPeriod(start: true),
                        onClear: () => setState(() => _start = ''),
                      ),
                      const SizedBox(width: 8),
                      _dateButton(
                        label: 'FIM',
                        value: _end,
                        onPressed: () => _pickPeriod(start: false),
                        onClear: () => setState(() => _end = ''),
                      ),
                      const SizedBox(width: 8),
                      FilledButton(
                        onPressed: _savePeriod,
                        style: FilledButton.styleFrom(
                          backgroundColor: AssistantTheme.c3,
                          foregroundColor: AssistantTheme.bg,
                        ),
                        child: const Text('SALVAR'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  const Text(
                    'DATAS SEM AULA',
                    style: TextStyle(
                      fontSize: 9,
                      letterSpacing: 1.5,
                      color: AssistantTheme.textMuted,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      _dateButton(
                        label: 'DATA',
                        value: _breakFrom == null ? '' : isoDay(_breakFrom!),
                        onPressed: () async {
                          final picked = await _pick(
                              _breakFrom == null ? '' : isoDay(_breakFrom!));
                          if (picked != null) {
                            setState(() => _breakFrom = picked);
                          }
                        },
                      ),
                      const SizedBox(width: 8),
                      _dateButton(
                        label: 'ATE (opcional)',
                        value: _breakTo == null ? '' : isoDay(_breakTo!),
                        onPressed: () async {
                          final picked = await _pick(
                              _breakTo == null ? '' : isoDay(_breakTo!));
                          if (picked != null) setState(() => _breakTo = picked);
                        },
                        onClear: () => setState(() => _breakTo = null),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: DropdownButtonFormField<String?>(
                          initialValue: _breakClassId,
                          isExpanded: true,
                          decoration: const InputDecoration(
                            isDense: true,
                            labelText: 'VALE PARA',
                            labelStyle: TextStyle(fontSize: 10),
                          ),
                          items: [
                            const DropdownMenuItem<String?>(
                              value: null,
                              child: Text('Todas as turmas',
                                  style: TextStyle(fontSize: 11)),
                            ),
                            for (final group in _classes)
                              DropdownMenuItem<String?>(
                                value: group.id,
                                child: Text(group.label,
                                    style: const TextStyle(fontSize: 11),
                                    overflow: TextOverflow.ellipsis),
                              ),
                          ],
                          onChanged: (value) =>
                              setState(() => _breakClassId = value),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: TextField(
                          controller: _reasonCtrl,
                          onSubmitted: (_) => _addBreak(),
                          style: const TextStyle(
                              fontSize: 12, color: AssistantTheme.textPrimary),
                          decoration: const InputDecoration(
                            isDense: true,
                            labelText: 'MOTIVO',
                            hintText: 'Feriado, recesso, congresso...',
                            labelStyle: TextStyle(fontSize: 10),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      FilledButton.icon(
                        onPressed: _addBreak,
                        icon: const Icon(Icons.add, size: 15),
                        label: const Text('ADICIONAR'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Expanded(
                    child: _breaks.isEmpty
                        ? const Center(
                            child: Text(
                              'Nenhuma data sem aula cadastrada.',
                              style: TextStyle(
                                  fontSize: 11,
                                  color: AssistantTheme.textMuted),
                            ),
                          )
                        : ListView.separated(
                            itemCount: _breaks.length,
                            separatorBuilder: (_, __) => const Divider(
                                height: 8, color: AssistantTheme.border),
                            itemBuilder: (_, index) {
                              final item = _breaks[index];
                              return Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          breakDates(item),
                                          style: const TextStyle(
                                              fontSize: 12,
                                              color:
                                                  AssistantTheme.textPrimary),
                                        ),
                                        Text(
                                          [
                                            item.classLabel.isEmpty
                                                ? 'todas as turmas'
                                                : 'turma ${item.classLabel}',
                                            if (item.reason.isNotEmpty)
                                              item.reason,
                                          ].join('  -  '),
                                          style: const TextStyle(
                                              fontSize: 10,
                                              color: AssistantTheme.textMuted),
                                        ),
                                      ],
                                    ),
                                  ),
                                  IconButton(
                                    tooltip: 'Remover',
                                    icon: const Icon(Icons.delete_outline,
                                        size: 16),
                                    color: AssistantTheme.danger,
                                    onPressed: () => _removeBreak(item),
                                  ),
                                ],
                              );
                            },
                          ),
                  ),
                  if (_status.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text(
                        _status,
                        style: const TextStyle(
                            fontSize: 11,
                            color: AssistantTheme.textSecondary),
                      ),
                    ),
                ],
              ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('FECHAR'),
        ),
      ],
    );
  }
}

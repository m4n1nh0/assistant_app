/// Criar no calendário externo a agenda semanal das turmas.
///
/// Vive junto do cadastro de turmas porque é lá que se definem os dias e horários de
/// cada turma; cada horário cadastrado vira uma série semanal no Google ou Microsoft
/// Calendar, e os eventos aparecem no painel de próximos eventos com os avisos
/// configurados em Notificações.
library;

import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

/// O que contar ao professor depois do fluxo.
class ClassAgendaOutcome {
  final String message;
  final bool error;

  const ClassAgendaOutcome(this.message, {this.error = false});
}

String currentSemesterCode(DateTime now) =>
    '${now.year}.${now.month <= 6 ? 1 : 2}';

DateTime semesterEnd(String semester, DateTime fallback) {
  final parts = semester.split('.');
  final year = parts.isNotEmpty ? int.tryParse(parts.first) : null;
  final half = parts.length > 1 ? int.tryParse(parts[1]) : null;
  if (year != null && half == 1) return DateTime(year, 6, 30);
  if (year != null && half == 2) return DateTime(year, 12, 31);
  return DateTime(fallback.year, fallback.month <= 6 ? 6 : 12,
      fallback.month <= 6 ? 30 : 31);
}

class _AgendaSelection {
  final CalendarAccount account;
  final DateTime from;
  final DateTime to;

  const _AgendaSelection({
    required this.account,
    required this.from,
    required this.to,
  });
}

String _date(DateTime value) =>
    '${value.year}-${value.month.toString().padLeft(2, '0')}-'
    '${value.day.toString().padLeft(2, '0')}';

/// Pergunta conta e período e cria a agenda das turmas ativas com horário.
///
/// Devolve `null` quando o professor cancela. Usa as turmas do semestre atual; sem
/// nenhuma, cai em todas as ativas com horário.
Future<ClassAgendaOutcome?> createClassAgendaFlow(
  BuildContext context,
  List<ClassGroup> allClasses,
) async {
  final now = DateTime.now();
  final currentSemester = currentSemesterCode(now);
  var agendaClasses = allClasses
      .where((group) =>
          group.active &&
          group.schedules.isNotEmpty &&
          group.semester == currentSemester)
      .toList();
  if (agendaClasses.isEmpty) {
    agendaClasses = allClasses
        .where((group) => group.active && group.schedules.isNotEmpty)
        .toList();
  }
  if (agendaClasses.isEmpty) {
    return const ClassAgendaOutcome(
      'Cadastre os dias e horarios das turmas antes de criar a agenda.',
      error: true,
    );
  }

  try {
    final accountGroups = await api.listCalendarAccounts();
    final accounts = [
      ...accountGroups['google'] ?? const <CalendarAccount>[],
      ...accountGroups['microsoft'] ?? const <CalendarAccount>[],
    ].where((account) => account.connected).toList();
    if (!context.mounted) return null;
    if (accounts.isEmpty) {
      return const ClassAgendaOutcome(
        'Conecte uma conta Google ou Microsoft em Configuracoes > Calendarios.',
        error: true,
      );
    }

    final semester = agendaClasses.first.semester.isEmpty
        ? currentSemester
        : agendaClasses.first.semester;
    final selection = await showDialog<_AgendaSelection>(
      context: context,
      builder: (dialogContext) {
        var account = accounts.first;
        var from = DateTime(now.year, now.month, now.day);
        var to = semesterEnd(semester, now);
        if (to.isBefore(from)) {
          to = from.add(const Duration(days: 120));
        }
        return StatefulBuilder(
          builder: (context, setDialogState) => AlertDialog(
            backgroundColor: AssistantTheme.surface,
            title: const Text('CRIAR AGENDA DAS TURMAS'),
            content: SizedBox(
              width: 470,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${agendaClasses.length} turma(s) de $semester serao '
                    'sincronizadas em uma unica operacao. Cada horario vira '
                    'uma serie semanal.',
                    style: const TextStyle(fontSize: 12),
                  ),
                  const SizedBox(height: 14),
                  DropdownButtonFormField<CalendarAccount>(
                    initialValue: account,
                    decoration: _decoration('CALENDARIO'),
                    items: accounts
                        .map((item) => DropdownMenuItem(
                              value: item,
                              child: Text(
                                '${item.provider == 'google' ? 'Google' : 'Microsoft'} - ${item.label}',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ))
                        .toList(),
                    onChanged: (value) => setDialogState(
                      () => account = value ?? account,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: _DateButton(
                          label: 'INICIO',
                          value: from,
                          onTap: () async {
                            final picked = await showDatePicker(
                              context: dialogContext,
                              initialDate: from,
                              firstDate: DateTime(now.year - 1),
                              lastDate: DateTime(now.year + 2),
                            );
                            if (picked != null) {
                              setDialogState(() => from = picked);
                            }
                          },
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: _DateButton(
                          label: 'FIM',
                          value: to,
                          onTap: () async {
                            final picked = await showDatePicker(
                              context: dialogContext,
                              initialDate: to,
                              firstDate: from,
                              lastDate: DateTime(now.year + 2),
                            );
                            if (picked != null) {
                              setDialogState(() => to = picked);
                            }
                          },
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Os eventos aparecerao no painel de proximos eventos e '
                    'usarao a antecedencia e o aviso no horario configurados '
                    'na tela de Notificacoes.',
                    style: TextStyle(
                      color: AssistantTheme.textSecondary,
                      fontSize: 10,
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('CANCELAR'),
              ),
              FilledButton.icon(
                onPressed: to.isBefore(from)
                    ? null
                    : () => Navigator.pop(
                          dialogContext,
                          _AgendaSelection(account: account, from: from, to: to),
                        ),
                icon: const Icon(Icons.event_repeat, size: 16),
                label: const Text('CONFIRMAR'),
              ),
            ],
          ),
        );
      },
    );
    if (selection == null) return null;

    final result = await api.createClassAgenda(
      provider: selection.account.provider,
      accountId: selection.account.id,
      classIds: agendaClasses.map((group) => group.id).toList(),
      dateFrom: selection.from,
      dateTo: selection.to,
    );
    final created = (result['created_series'] as num?)?.toInt() ?? 0;
    final skipped = (result['skipped_series'] as num?)?.toInt() ?? 0;
    final failed = (result['failed_series'] as num?)?.toInt() ?? 0;
    final errors = (result['errors'] as List<dynamic>? ?? const [])
        .map((item) => item.toString())
        .toList();
    if (failed > 0 && created == 0) {
      return ClassAgendaOutcome(
        'Nenhuma serie foi criada. ${errors.firstOrNull ?? 'Verifique os horarios e a conta.'}',
        error: true,
      );
    }
    return ClassAgendaOutcome(
      'Agenda pronta: $created serie(s) criada(s), $skipped ja existente(s)'
      '${failed > 0 ? ' e $failed falha(s)' : ''}. Os lembretes serao '
      'carregados na proxima sincronizacao.',
      error: failed > 0,
    );
  } catch (e) {
    return ClassAgendaOutcome('Falha ao criar agenda das turmas: $e', error: true);
  }
}

InputDecoration _decoration(String label) => InputDecoration(
      labelText: label,
      labelStyle: const TextStyle(
        fontSize: 9,
        letterSpacing: 1.1,
        color: AssistantTheme.textMuted,
      ),
      isDense: true,
      filled: true,
      fillColor: AssistantTheme.bg2,
    );

class _DateButton extends StatelessWidget {
  final String label;
  final DateTime value;
  final VoidCallback onTap;

  const _DateButton({
    required this.label,
    required this.value,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) => OutlinedButton.icon(
        onPressed: onTap,
        icon: const Icon(Icons.calendar_today_outlined, size: 13),
        label: Text('$label ${_date(value)}'),
        style: OutlinedButton.styleFrom(
          foregroundColor: AssistantTheme.textSecondary,
          side: const BorderSide(color: AssistantTheme.border2),
        ),
      );
}

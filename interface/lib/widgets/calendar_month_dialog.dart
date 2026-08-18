import 'package:flutter/material.dart';

import '../models/app_config.dart';
import '../services/calendar_service.dart';
import '../services/external_launcher_service.dart';
import '../utils/theme.dart';

/// Calendário mensal com os eventos das agendas conectadas (Google e
/// Microsoft). Aberto pelo botão no painel de próximos eventos.
class CalendarMonthDialog extends StatefulWidget {
  const CalendarMonthDialog({super.key});

  @override
  State<CalendarMonthDialog> createState() => _CalendarMonthDialogState();
}

class _CalendarMonthDialogState extends State<CalendarMonthDialog> {
  static const _monthNames = [
    'Janeiro',
    'Fevereiro',
    'Março',
    'Abril',
    'Maio',
    'Junho',
    'Julho',
    'Agosto',
    'Setembro',
    'Outubro',
    'Novembro',
    'Dezembro',
  ];
  static const _weekdayLabels = ['DOM', 'SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SAB'];
  static const _sourceColors = {
    'google': AssistantTheme.c1,
    'teams': AssistantTheme.c2,
    'outlook': AssistantTheme.c4,
  };
  static const _sourceLabels = {
    'google': 'Google',
    'teams': 'Teams',
    'outlook': 'Outlook',
  };

  late DateTime _month;
  late DateTime _selectedDay;
  List<CalendarEvent> _events = const [];
  bool _loading = true;
  String _error = '';

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _month = DateTime(now.year, now.month);
    _selectedDay = DateTime(now.year, now.month, now.day);
    _loadMonth();
  }

  /// Primeiro domingo visível na grade do mês.
  DateTime get _gridStart {
    final first = _month;
    return first.subtract(Duration(days: first.weekday % 7));
  }

  Future<void> _loadMonth() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final start = _gridStart;
      final events = await CalendarService.fetchEventsRange(
        start: start,
        end: start.add(const Duration(days: 42)),
      );
      if (!mounted) return;
      setState(() {
        _events = events;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Não consegui carregar as agendas: '
            '${e.toString().replaceFirst('Exception: ', '')}';
      });
    }
  }

  void _changeMonth(int delta) {
    setState(() {
      _month = DateTime(_month.year, _month.month + delta);
    });
    _loadMonth();
  }

  void _goToday() {
    final now = DateTime.now();
    setState(() {
      _month = DateTime(now.year, now.month);
      _selectedDay = DateTime(now.year, now.month, now.day);
    });
    _loadMonth();
  }

  DateTime _dayKey(DateTime time) => DateTime(time.year, time.month, time.day);

  List<CalendarEvent> _eventsOn(DateTime day) {
    final key = _dayKey(day);
    final list = _events
        .where((event) => _dayKey(event.startTime) == key)
        .toList()
      ..sort((a, b) => a.startTime.compareTo(b.startTime));
    return list;
  }

  String _hhmm(DateTime time) => '${time.hour.toString().padLeft(2, '0')}:'
      '${time.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    return Dialog(
      backgroundColor: AssistantTheme.bg2,
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: SizedBox(
        width: (size.width - 120).clamp(560.0, 860.0),
        height: (size.height - 90).clamp(480.0, 760.0),
        child: Column(
          children: [
            _buildHeader(),
            const Divider(height: 1, color: AssistantTheme.border),
            _buildWeekdayLabels(),
            Expanded(flex: 5, child: _buildGrid()),
            const Divider(height: 1, color: AssistantTheme.border),
            Expanded(flex: 2, child: _buildDayDetail()),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
      child: Row(
        children: [
          const Icon(Icons.calendar_month, size: 18, color: AssistantTheme.c1),
          const SizedBox(width: 10),
          IconButton(
            tooltip: 'Mês anterior',
            constraints: const BoxConstraints.tightFor(width: 30, height: 30),
            padding: EdgeInsets.zero,
            onPressed: () => _changeMonth(-1),
            icon: const Icon(Icons.chevron_left, size: 20),
            color: AssistantTheme.textSecondary,
          ),
          SizedBox(
            width: 170,
            child: Text(
              '${_monthNames[_month.month - 1].toUpperCase()} ${_month.year}',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: 'Rajdhani',
                fontSize: 15,
                fontWeight: FontWeight.w700,
                letterSpacing: 2.5,
                color: AssistantTheme.textPrimary,
              ),
            ),
          ),
          IconButton(
            tooltip: 'Próximo mês',
            constraints: const BoxConstraints.tightFor(width: 30, height: 30),
            padding: EdgeInsets.zero,
            onPressed: () => _changeMonth(1),
            icon: const Icon(Icons.chevron_right, size: 20),
            color: AssistantTheme.textSecondary,
          ),
          const SizedBox(width: 8),
          TextButton(
            onPressed: _goToday,
            child: const Text('Hoje'),
          ),
          const Spacer(),
          if (_loading)
            const SizedBox.square(
              dimension: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          const SizedBox(width: 10),
          for (final source in _sourceLabels.keys) ...[
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: _sourceColors[source],
              ),
            ),
            const SizedBox(width: 4),
            Text(
              _sourceLabels[source]!,
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                color: AssistantTheme.textMuted,
              ),
            ),
            const SizedBox(width: 10),
          ],
          IconButton(
            tooltip: 'Fechar',
            onPressed: () => Navigator.pop(context),
            icon: const Icon(Icons.close, size: 18),
            color: AssistantTheme.textSecondary,
          ),
        ],
      ),
    );
  }

  Widget _buildWeekdayLabels() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      child: Row(
        children: [
          for (final label in _weekdayLabels)
            Expanded(
              child: Text(
                label,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9,
                  letterSpacing: 2,
                  color: AssistantTheme.textMuted,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildGrid() {
    final today = _dayKey(DateTime.now());
    final start = _gridStart;
    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
      child: Column(
        children: [
          for (var week = 0; week < 6; week++)
            Expanded(
              child: Row(
                children: [
                  for (var weekday = 0; weekday < 7; weekday++)
                    Expanded(
                      child: _buildDayCell(
                        start.add(Duration(days: week * 7 + weekday)),
                        today,
                      ),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildDayCell(DateTime day, DateTime today) {
    final key = _dayKey(day);
    final inMonth = day.month == _month.month;
    final isToday = key == today;
    final isSelected = key == _selectedDay;
    final events = _eventsOn(day);

    return InkWell(
      onTap: () => setState(() => _selectedDay = key),
      child: Container(
        margin: const EdgeInsets.all(1.5),
        padding: const EdgeInsets.all(4),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(3),
          border: Border.all(
            color: isToday
                ? AssistantTheme.c3
                : isSelected
                    ? AssistantTheme.c1.withOpacity(0.6)
                    : AssistantTheme.border.withOpacity(0.6),
          ),
          color: isSelected
              ? AssistantTheme.c1.withOpacity(0.08)
              : Colors.transparent,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${day.day}',
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 10,
                fontWeight: isToday ? FontWeight.w700 : FontWeight.w400,
                color: !inMonth
                    ? AssistantTheme.textMuted.withOpacity(0.5)
                    : isToday
                        ? AssistantTheme.c3
                        : AssistantTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 2),
            if (events.isNotEmpty)
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final event in events.take(2))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 1),
                        child: Row(
                          children: [
                            Container(
                              width: 5,
                              height: 5,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: _sourceColors[event.source] ??
                                    AssistantTheme.c1,
                              ),
                            ),
                            const SizedBox(width: 3),
                            Expanded(
                              child: Text(
                                event.title,
                                style: TextStyle(
                                  fontFamily: 'JetBrains Mono',
                                  fontSize: 8,
                                  color: inMonth
                                      ? AssistantTheme.textSecondary
                                      : AssistantTheme.textMuted,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    if (events.length > 2)
                      Text(
                        '+${events.length - 2}',
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 8,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildDayDetail() {
    final events = _eventsOn(_selectedDay);
    final label = '${_selectedDay.day.toString().padLeft(2, '0')} de '
        '${_monthNames[_selectedDay.month - 1]} de ${_selectedDay.year}';
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 8, 14, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label.toUpperCase(),
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 9,
              letterSpacing: 2,
              color: AssistantTheme.textMuted,
            ),
          ),
          const SizedBox(height: 6),
          if (_error.isNotEmpty)
            Text(
              _error,
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 10,
                color: AssistantTheme.danger,
              ),
            )
          else if (events.isEmpty)
            const Text(
              'Sem eventos neste dia.',
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 10,
                color: AssistantTheme.textMuted,
              ),
            )
          else
            Expanded(
              child: ListView.separated(
                itemCount: events.length,
                separatorBuilder: (_, __) => const SizedBox(height: 4),
                itemBuilder: (_, index) {
                  final event = events[index];
                  final color =
                      _sourceColors[event.source] ?? AssistantTheme.c1;
                  final end = event.endTime;
                  return Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 5),
                    decoration: BoxDecoration(
                      border: Border(left: BorderSide(color: color, width: 3)),
                      color: color.withOpacity(0.04),
                    ),
                    child: Row(
                      children: [
                        Text(
                          end == null
                              ? _hhmm(event.startTime)
                              : '${_hhmm(event.startTime)}–${_hhmm(end)}',
                          style: TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 10,
                            color: color,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            event.title,
                            style: const TextStyle(
                              fontFamily: 'JetBrains Mono',
                              fontSize: 11,
                              color: AssistantTheme.textPrimary,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          _sourceLabels[event.source] ?? event.source,
                          style: const TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 9,
                            color: AssistantTheme.textMuted,
                          ),
                        ),
                        if (event.meetingUrl?.isNotEmpty ?? false) ...[
                          const SizedBox(width: 8),
                          InkWell(
                            onTap: () => ExternalLauncherService.openUrl(
                                event.meetingUrl!),
                            child: Text(
                              '🔗 Entrar',
                              style: TextStyle(
                                fontFamily: 'JetBrains Mono',
                                fontSize: 10,
                                color: color,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}

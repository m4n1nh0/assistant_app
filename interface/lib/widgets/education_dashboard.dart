import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../services/education_service.dart';
import '../utils/theme.dart';

typedef EducationDisciplinesLoader = Future<List<Discipline>> Function();

class EducationSemesterSummary {
  final String code;
  final bool active;
  final int disciplineCount;
  final int classCount;
  final int studentCount;

  const EducationSemesterSummary({
    required this.code,
    required this.active,
    required this.disciplineCount,
    required this.classCount,
    required this.studentCount,
  });
}

class EducationAgendaEntry {
  final int weekday;
  final String startTime;
  final String endTime;
  final String classCode;
  final String discipline;

  const EducationAgendaEntry({
    required this.weekday,
    required this.startTime,
    required this.endTime,
    required this.classCode,
    required this.discipline,
  });
}

List<EducationSemesterSummary> summarizeEducationSemesters(
  Iterable<Discipline> disciplines,
  Iterable<ClassGroup> classes,
) {
  final bySemester = <String, _MutableSemester>{};

  for (final discipline in disciplines) {
    final code = discipline.semester.trim();
    if (code.isEmpty) continue;
    final item = bySemester.putIfAbsent(code, _MutableSemester.new);
    item.disciplineCount += 1;
    item.reportedClassCount += discipline.classCount;
    item.active = item.active || discipline.active;
  }

  for (final group in classes) {
    final code = group.semester.trim();
    if (code.isEmpty) continue;
    final item = bySemester.putIfAbsent(code, _MutableSemester.new);
    item.loadedClassCount += 1;
    item.studentCount += group.studentCount;
    item.active = item.active || group.active;
  }

  final result = bySemester.entries
      .map(
        (entry) => EducationSemesterSummary(
          code: entry.key,
          active: entry.value.active,
          disciplineCount: entry.value.disciplineCount,
          classCount: math.max(
            entry.value.reportedClassCount,
            entry.value.loadedClassCount,
          ),
          studentCount: entry.value.studentCount,
        ),
      )
      .toList();
  result.sort((a, b) => b.code.compareTo(a.code));
  return result;
}

List<EducationAgendaEntry> buildEducationAgenda(
  Iterable<ClassGroup> classes,
) {
  final result = <EducationAgendaEntry>[];
  for (final group in classes.where((item) => item.active)) {
    for (final schedule in group.schedules) {
      if (schedule.weekday < 0 || schedule.weekday > 6) continue;
      result.add(
        EducationAgendaEntry(
          weekday: schedule.weekday,
          startTime: schedule.startTime,
          endTime: schedule.endTime,
          classCode: group.code.isEmpty ? group.label : group.code,
          discipline: group.discipline,
        ),
      );
    }
  }
  result.sort((a, b) {
    final day = a.weekday.compareTo(b.weekday);
    if (day != 0) return day;
    final time = a.startTime.compareTo(b.startTime);
    if (time != 0) return time;
    return a.classCode.compareTo(b.classCode);
  });
  return result;
}

String currentEducationSemesterCode(DateTime now) =>
    '${now.year}.${now.month <= 6 ? 1 : 2}';

class _MutableSemester {
  bool active = false;
  int disciplineCount = 0;
  int reportedClassCount = 0;
  int loadedClassCount = 0;
  int studentCount = 0;
}

class EducationDashboard extends StatefulWidget {
  final ValueListenable<List<ClassGroup>?> classes;
  final VoidCallback onOpenClasses;
  final VoidCallback onOpenPoints;
  final VoidCallback onOpenHistory;
  final VoidCallback onOpenAttendance;
  final EducationDisciplinesLoader? loadDisciplines;

  const EducationDashboard({
    super.key,
    required this.classes,
    required this.onOpenClasses,
    required this.onOpenPoints,
    required this.onOpenHistory,
    required this.onOpenAttendance,
    this.loadDisciplines,
  });

  @override
  State<EducationDashboard> createState() => _EducationDashboardState();
}

class _EducationDashboardState extends State<EducationDashboard> {
  List<Discipline> _disciplines = const [];
  var _loading = true;
  var _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = '';
      });
    }
    try {
      final loader = widget.loadDisciplines ??
          () => education.listDisciplines(activeOnly: false);
      final disciplines = await loader();
      if (!mounted) return;
      setState(() => _disciplines = disciplines);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = 'Nao foi possivel carregar o painel: $error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<List<ClassGroup>?>(
      valueListenable: widget.classes,
      builder: (context, value, _) {
        final classes = value ?? const <ClassGroup>[];
        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _DashboardHeading(
                loading: _loading,
                error: _error,
                onRefresh: _load,
              ),
              const SizedBox(height: 12),
              Expanded(child: _buildGrid(classes)),
            ],
          ),
        );
      },
    );
  }

  Widget _buildGrid(List<ClassGroup> classes) {
    final semesters = summarizeEducationSemesters(_disciplines, classes);
    final agenda = buildEducationAgenda(classes);
    final panels = <Widget>[
      _SemestersPanel(
        semesters: semesters,
        onOpen: widget.onOpenClasses,
      ),
      _ClassesPanel(classes: classes, onOpen: widget.onOpenClasses),
      _AgendaPanel(entries: agenda, onOpen: widget.onOpenAttendance),
      _ReportsPanel(
        classes: classes,
        onOpenAttendance: widget.onOpenAttendance,
        onOpenHistory: widget.onOpenHistory,
        onOpenPoints: widget.onOpenPoints,
      ),
    ];

    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 760 || constraints.maxHeight < 480) {
          return ListView.separated(
            itemCount: panels.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (_, index) => SizedBox(
              height: 260,
              child: panels[index],
            ),
          );
        }
        return Column(
          children: [
            Expanded(
              child: Row(
                children: [
                  Expanded(child: panels[0]),
                  const SizedBox(width: 12),
                  Expanded(child: panels[1]),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: Row(
                children: [
                  Expanded(child: panels[2]),
                  const SizedBox(width: 12),
                  Expanded(child: panels[3]),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

class _DashboardHeading extends StatelessWidget {
  final bool loading;
  final String error;
  final VoidCallback onRefresh;

  const _DashboardHeading({
    required this.loading,
    required this.error,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) => Row(
        children: [
          const Icon(Icons.dashboard_customize_outlined,
              size: 24, color: AssistantTheme.c1),
          const SizedBox(width: 10),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'TUDO ORGANIZADO',
                  style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 2.4,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
                Text(
                  'Semestres  •  Turmas e alunos  •  Agenda  •  Relatorios',
                  style: TextStyle(
                    fontSize: 10,
                    color: AssistantTheme.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          if (error.isNotEmpty)
            Tooltip(
              message: error,
              child: const Icon(Icons.warning_amber_rounded,
                  size: 17, color: AssistantTheme.c4),
            ),
          IconButton(
            tooltip: 'Atualizar painel',
            onPressed: loading ? null : onRefresh,
            icon: loading
                ? const SizedBox.square(
                    dimension: 15,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh, size: 18),
          ),
        ],
      );
}

class _SemestersPanel extends StatelessWidget {
  final List<EducationSemesterSummary> semesters;
  final VoidCallback onOpen;

  const _SemestersPanel({required this.semesters, required this.onOpen});

  @override
  Widget build(BuildContext context) {
    final current = currentEducationSemesterCode(DateTime.now());
    return _DashboardPanel(
      title: 'SEMESTRES',
      icon: Icons.menu_book_outlined,
      color: AssistantTheme.c1,
      actionLabel: 'GERENCIAR',
      onAction: onOpen,
      child: semesters.isEmpty
          ? const _DashboardEmpty('Nenhum semestre cadastrado.')
          : GridView.builder(
              padding: EdgeInsets.zero,
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 145,
                mainAxisExtent: 82,
                crossAxisSpacing: 8,
                mainAxisSpacing: 8,
              ),
              itemCount: math.min(semesters.length, 6),
              itemBuilder: (_, index) {
                final item = semesters[index];
                final selected = item.code == current;
                return InkWell(
                  onTap: onOpen,
                  borderRadius: BorderRadius.circular(6),
                  child: Container(
                    padding: const EdgeInsets.all(9),
                    decoration: BoxDecoration(
                      color: selected
                          ? AssistantTheme.c1.withOpacity(.08)
                          : AssistantTheme.bg2,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(
                        color: selected
                            ? AssistantTheme.c1
                            : AssistantTheme.border2,
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                item.code,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                  color: AssistantTheme.textPrimary,
                                ),
                              ),
                            ),
                            Icon(
                              item.active
                                  ? Icons.check_circle_outline
                                  : Icons.archive_outlined,
                              size: 13,
                              color: item.active
                                  ? AssistantTheme.c3
                                  : AssistantTheme.textMuted,
                            ),
                          ],
                        ),
                        const Spacer(),
                        Text(
                          '${item.disciplineCount} disciplina(s)',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 9, color: AssistantTheme.textSecondary),
                        ),
                        Text(
                          '${item.classCount} turma(s)',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 9, color: AssistantTheme.textMuted),
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }
}

class _ClassesPanel extends StatelessWidget {
  final List<ClassGroup> classes;
  final VoidCallback onOpen;

  const _ClassesPanel({required this.classes, required this.onOpen});

  @override
  Widget build(BuildContext context) {
    final current = currentEducationSemesterCode(DateTime.now());
    final ordered = List<ClassGroup>.of(classes)
      ..sort((a, b) {
        final aCurrent = a.semester == current ? 0 : 1;
        final bCurrent = b.semester == current ? 0 : 1;
        final bySemester = aCurrent.compareTo(bCurrent);
        if (bySemester != 0) return bySemester;
        return a.code.compareTo(b.code);
      });
    return _DashboardPanel(
      title: 'TURMAS E ALUNOS',
      icon: Icons.groups_outlined,
      color: AssistantTheme.c2,
      actionLabel: 'ABRIR CADASTRO',
      onAction: onOpen,
      child: ordered.isEmpty
          ? const _DashboardEmpty('Nenhuma turma ativa.')
          : ListView.separated(
              padding: EdgeInsets.zero,
              itemCount: math.min(ordered.length, 5),
              separatorBuilder: (_, __) =>
                  const Divider(height: 1, color: AssistantTheme.border),
              itemBuilder: (_, index) {
                final group = ordered[index];
                return InkWell(
                  onTap: onOpen,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 7),
                    child: Row(
                      children: [
                        CircleAvatar(
                          radius: 14,
                          backgroundColor: AssistantTheme.c2.withOpacity(.12),
                          child: const Icon(Icons.school_outlined,
                              size: 14, color: AssistantTheme.c2),
                        ),
                        const SizedBox(width: 9),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                group.code.isEmpty ? group.label : group.code,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w700,
                                  color: AssistantTheme.textPrimary,
                                ),
                              ),
                              Text(
                                group.discipline,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    fontSize: 9,
                                    color: AssistantTheme.textMuted),
                              ),
                            ],
                          ),
                        ),
                        Text(
                          '${group.studentCount}',
                          style: const TextStyle(
                              fontWeight: FontWeight.w700,
                              color: AssistantTheme.c3),
                        ),
                        const SizedBox(width: 5),
                        const Icon(Icons.person_outline,
                            size: 14, color: AssistantTheme.textMuted),
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }
}

class _AgendaPanel extends StatelessWidget {
  static const _days = ['SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SAB', 'DOM'];

  final List<EducationAgendaEntry> entries;
  final VoidCallback onOpen;

  const _AgendaPanel({required this.entries, required this.onOpen});

  @override
  Widget build(BuildContext context) => _DashboardPanel(
        title: 'AGENDA DA SEMANA',
        icon: Icons.calendar_month_outlined,
        color: AssistantTheme.c3,
        actionLabel: 'PRESENCA E AGENDA',
        onAction: onOpen,
        child: entries.isEmpty
            ? const _DashboardEmpty('Cadastre dias e horarios nas turmas.')
            : SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (var day = 0; day < 7; day++)
                      SizedBox(
                        width: 72,
                        child: _AgendaDay(
                          label: _days[day],
                          selected: DateTime.now().weekday - 1 == day,
                          entries: entries
                              .where((item) => item.weekday == day)
                              .toList(),
                        ),
                      ),
                  ],
                ),
              ),
      );
}

class _AgendaDay extends StatelessWidget {
  final String label;
  final bool selected;
  final List<EducationAgendaEntry> entries;

  const _AgendaDay({
    required this.label,
    required this.selected,
    required this.entries,
  });

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(right: 6),
        padding: const EdgeInsets.all(5),
        decoration: BoxDecoration(
          color: selected ? AssistantTheme.c3.withOpacity(.07) : null,
          borderRadius: BorderRadius.circular(5),
          border: Border.all(
            color: selected ? AssistantTheme.c3 : AssistantTheme.border,
          ),
        ),
        child: Column(
          children: [
            Text(
              label,
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w700,
                color:
                    selected ? AssistantTheme.c3 : AssistantTheme.textSecondary,
              ),
            ),
            const SizedBox(height: 6),
            if (entries.isEmpty)
              const Text('—', style: TextStyle(color: AssistantTheme.textMuted))
            else
              for (final entry in entries.take(3))
                Container(
                  width: double.infinity,
                  margin: const EdgeInsets.only(bottom: 5),
                  padding: const EdgeInsets.symmetric(vertical: 5),
                  decoration: BoxDecoration(
                    color: AssistantTheme.surface2,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Column(
                    children: [
                      Text(
                        entry.startTime.isEmpty ? '--:--' : entry.startTime,
                        style: const TextStyle(
                            fontSize: 8, color: AssistantTheme.c1),
                      ),
                      Text(
                        entry.classCode,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 8,
                            fontWeight: FontWeight.w700,
                            color: AssistantTheme.textPrimary),
                      ),
                    ],
                  ),
                ),
          ],
        ),
      );
}

class _ReportsPanel extends StatelessWidget {
  final List<ClassGroup> classes;
  final VoidCallback onOpenAttendance;
  final VoidCallback onOpenHistory;
  final VoidCallback onOpenPoints;

  const _ReportsPanel({
    required this.classes,
    required this.onOpenAttendance,
    required this.onOpenHistory,
    required this.onOpenPoints,
  });

  @override
  Widget build(BuildContext context) {
    final students = classes.fold<int>(
      0,
      (total, item) => total + item.studentCount,
    );
    return _DashboardPanel(
      title: 'RELATORIOS EM PDF',
      icon: Icons.description_outlined,
      color: AssistantTheme.c1,
      child: Column(
        children: [
          Row(
            children: [
              _Metric(value: '${classes.length}', label: 'turmas'),
              const SizedBox(width: 8),
              _Metric(value: '$students', label: 'alunos'),
              const Spacer(),
              const Icon(Icons.picture_as_pdf_outlined,
                  size: 34, color: AssistantTheme.c1),
            ],
          ),
          const SizedBox(height: 10),
          Expanded(
            child: Column(
              children: [
                Expanded(
                  child: _ReportShortcut(
                    icon: Icons.fact_check_outlined,
                    label: 'PRESENCA E LISTAGENS',
                    color: AssistantTheme.c3,
                    onTap: onOpenAttendance,
                  ),
                ),
                const SizedBox(height: 7),
                Expanded(
                  child: Row(
                    children: [
                      Expanded(
                        child: _ReportShortcut(
                          icon: Icons.history,
                          label: 'RESUMOS',
                          color: AssistantTheme.c2,
                          onTap: onOpenHistory,
                        ),
                      ),
                      const SizedBox(width: 7),
                      Expanded(
                        child: _ReportShortcut(
                          icon: Icons.emoji_events_outlined,
                          label: 'PONTOS',
                          color: AssistantTheme.c4,
                          onTap: onOpenPoints,
                        ),
                      ),
                    ],
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

class _Metric extends StatelessWidget {
  final String value;
  final String label;

  const _Metric({required this.value, required this.label});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: AssistantTheme.bg2,
          borderRadius: BorderRadius.circular(5),
          border: Border.all(color: AssistantTheme.border),
        ),
        child: Row(
          children: [
            Text(
              value,
              style: const TextStyle(
                fontWeight: FontWeight.w800,
                color: AssistantTheme.textPrimary,
              ),
            ),
            const SizedBox(width: 4),
            Text(label,
                style: const TextStyle(
                    fontSize: 9, color: AssistantTheme.textMuted)),
          ],
        ),
      );
}

class _ReportShortcut extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _ReportShortcut({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(5),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: color.withOpacity(.07),
            borderRadius: BorderRadius.circular(5),
            border: Border.all(color: color.withOpacity(.45)),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 15, color: color),
              const SizedBox(width: 7),
              Flexible(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    color: color,
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}

class _DashboardPanel extends StatelessWidget {
  final String title;
  final IconData icon;
  final Color color;
  final Widget child;
  final String? actionLabel;
  final VoidCallback? onAction;

  const _DashboardPanel({
    required this.title,
    required this.icon,
    required this.color,
    required this.child,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AssistantTheme.bg.withOpacity(.38),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color.withOpacity(.55)),
          boxShadow: [
            BoxShadow(color: color.withOpacity(.06), blurRadius: 16),
          ],
        ),
        child: Column(
          children: [
            Row(
              children: [
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: color.withOpacity(.12),
                    border: Border.all(color: color.withOpacity(.65)),
                  ),
                  child: Icon(icon, size: 16, color: color),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    title,
                    style: TextStyle(
                      fontFamily: 'Rajdhani',
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1,
                      color: color,
                    ),
                  ),
                ),
                if (actionLabel != null)
                  TextButton(
                    onPressed: onAction,
                    child: Text(
                      actionLabel!,
                      style: const TextStyle(fontSize: 8),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Expanded(child: child),
          ],
        ),
      );
}

class _DashboardEmpty extends StatelessWidget {
  final String text;

  const _DashboardEmpty(this.text);

  @override
  Widget build(BuildContext context) => Center(
        child: Text(
          text,
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontSize: 10,
            color: AssistantTheme.textMuted,
          ),
        ),
      );
}

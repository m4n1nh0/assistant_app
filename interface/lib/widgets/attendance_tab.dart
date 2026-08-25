/// Aba de chamada: sessao, QR Code e acompanhamento dos presentes.
library;

import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:printing/printing.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/api_service.dart';
import '../services/academic_report_pdf_service.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';
import 'sia_attendance_importer.dart';

/// Turmas validas para abrir a chamada, na ordem em que acontecem no dia.
List<ClassGroup> attendanceClassesForDay(
  Iterable<ClassGroup> classes,
  int dartWeekday,
) {
  final backendWeekday = dartWeekday - 1;
  final result = classes
      .where((group) => group.active && group.meetsOn(dartWeekday))
      .toList();
  String startOf(ClassGroup group) => group.schedules
      .where((schedule) => schedule.weekday == backendWeekday)
      .map((schedule) => schedule.startTime)
      .where((value) => value.isNotEmpty)
      .fold('99:99',
          (first, value) => value.compareTo(first) < 0 ? value : first);
  result.sort((a, b) {
    final byTime = startOf(a).compareTo(startOf(b));
    return byTime != 0 ? byTime : a.display.compareTo(b.display);
  });
  return result;
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

String attendanceSessionTranscript(AttendanceSession session) {
  final classes = session.classes.isNotEmpty
      ? session.classes
      : [
          AttendanceClass(
            classId: session.classId,
            classLabel: session.classLabel,
            discipline: session.discipline,
            semester: session.semester,
            expectedCount: session.expectedCount,
          ),
        ];
  final students = <AttendanceStudent>[
    ...session.records,
    ...session.absentStudents,
  ];
  final presentIds = session.records.map((item) => item.studentId).toSet();
  final buffer = StringBuffer()
    ..writeln('RELATORIO DE CHAMADA')
    ..writeln('Data: ${session.attendanceDate}')
    ..writeln(
      'Turmas: ${classes.map((item) => item.classLabel).join(' | ')}',
    )
    ..writeln(
      'Resultado: ${session.presentCount} presentes, '
      '${session.absentCount} ausentes, ${session.expectedCount} alunos',
    );
  if (session.title.trim().isNotEmpty) {
    buffer.writeln('Aula: ${session.title.trim()}');
  }

  for (final group in classes) {
    final roster = students.where((student) {
      if (student.classId.isNotEmpty) return student.classId == group.classId;
      return classes.length == 1;
    }).toList()
      ..sort((a, b) => a.studentName.compareTo(b.studentName));
    final present = roster
        .where((student) => presentIds.contains(student.studentId))
        .length;
    buffer
      ..writeln()
      ..writeln(
        '${group.classLabel} | ${group.discipline} | ${group.semester}',
      )
      ..writeln('$present/${roster.length} presentes')
      ..writeln('MATRICULA | ALUNO | SITUACAO');
    for (final student in roster) {
      buffer.writeln(
        '${student.enrollment} | ${student.studentName} | '
        '${presentIds.contains(student.studentId) ? 'PRESENTE' : 'AUSENTE'}',
      );
    }
  }
  return buffer.toString().trimRight();
}

AttendanceReport attendanceReportForSession(AttendanceSession session) =>
    AttendanceReport(
      dateFrom: session.attendanceDate,
      dateTo: session.attendanceDate,
      classId: session.classId,
      sessionCount: 1,
      expectedTotal: session.expectedCount,
      presentTotal: session.presentCount,
      sessions: [session],
    );

String attendanceSessionPdfFilename(AttendanceSession session) {
  final date = session.attendanceDate.isEmpty
      ? DateTime.now().toIso8601String().split('T').first
      : session.attendanceDate;
  final reference = session.id
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9-]'), '-')
      .replaceAll(RegExp(r'-+'), '-')
      .replaceAll(RegExp(r'^-|-$'), '');
  return 'relatorio-presenca-$date${reference.isEmpty ? '' : '-$reference'}.pdf';
}

/// Aba de chamada: abre a sessao, mostra o QR Code e acompanha os presentes.
class AttendanceTab extends StatefulWidget {
  final ValueNotifier<List<ClassGroup>?> classes;

  const AttendanceTab({super.key, required this.classes});

  @override
  State<AttendanceTab> createState() => _AttendanceTabState();
}

class _AttendanceTabState extends State<AttendanceTab> {
  final _titleCtrl = TextEditingController();
  final _manualEnrollmentCtrl = TextEditingController();
  Set<String> _selectedClassIds = {};
  AttendanceSession? _activeSession;
  List<AttendanceSession> _sessions = [];
  List<ClassGroup> _reportClasses = [];
  List<Discipline> _disciplines = [];
  List<Student> _students = [];
  DateTime _from = DateTime.now().subtract(const Duration(days: 30));
  DateTime _to = DateTime.now();
  int _durationMinutes = 15;
  bool _loading = true;
  bool _creating = false;
  String? _deletingSessionId;
  bool _exporting = false;
  bool _syncingAgenda = false;
  String _status = '';
  bool _statusError = false;
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    widget.classes.addListener(_classesChanged);
    _classesChanged();
    _loadReports();
    _refreshTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (_activeSession?.open == true) _refreshActiveSession();
    });
  }

  @override
  void dispose() {
    widget.classes.removeListener(_classesChanged);
    _refreshTimer?.cancel();
    _titleCtrl.dispose();
    _manualEnrollmentCtrl.dispose();
    super.dispose();
  }

  void _classesChanged() {
    final classes = widget.classes.value ?? const <ClassGroup>[];
    final todayClasses = attendanceClassesForDay(
      classes,
      DateTime.now().weekday,
    );
    if (!mounted) return;
    setState(() {
      final available = todayClasses.map((group) => group.id).toSet();
      final retained = _selectedClassIds.intersection(available);
      _selectedClassIds = retained.isEmpty ? available : retained;
    });
  }

  void _report(String message, {bool error = false}) {
    if (!mounted) return;
    setState(() {
      _status = message;
      _statusError = error;
    });
  }

  Future<void> _loadReports() async {
    if (mounted) setState(() => _loading = true);
    try {
      final results = await Future.wait([
        education.listAttendanceSessions(
          dateFrom: _date(_from),
          dateTo: _date(_to),
        ),
        education.listStudents(activeOnly: false),
        education.listDisciplines(activeOnly: false),
        education.listClasses(activeOnly: false),
      ]);
      if (!mounted) return;
      setState(() {
        _sessions = results[0] as List<AttendanceSession>;
        _students = results[1] as List<Student>;
        _disciplines = results[2] as List<Discipline>;
        _reportClasses = results[3] as List<ClassGroup>;
      });
    } catch (e) {
      _report('Falha ao carregar presencas: $e', error: true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _createSession() async {
    final todayClasses = attendanceClassesForDay(
      widget.classes.value ?? const <ClassGroup>[],
      DateTime.now().weekday,
    );
    final selected = todayClasses
        .where((group) => _selectedClassIds.contains(group.id))
        .toList();
    if (selected.isEmpty) {
      _report('Escolha ao menos uma turma para abrir a chamada.', error: true);
      return;
    }
    setState(() => _creating = true);
    try {
      final session = await education.createAttendanceSession(
        classIds: selected.map((group) => group.id).toList(),
        attendanceDate: _date(DateTime.now()),
        durationMinutes: _durationMinutes,
        title: _titleCtrl.text.trim(),
      );
      if (!mounted) return;
      setState(() => _activeSession = session);
      _report(
        'QR Code unico gerado para ${selected.length} turma(s). '
        'A chamada fecha em $_durationMinutes minutos.',
      );
      await _loadReports();
    } catch (e) {
      _report('Falha ao abrir chamada: $e', error: true);
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  Future<void> _refreshActiveSession() async {
    final current = _activeSession;
    if (current == null) return;
    try {
      final updated = await education.getAttendanceSession(current.id);
      if (!mounted || _activeSession?.id != current.id) return;
      setState(() {
        // O backend guarda somente o hash do token; a URL continua sendo a
        // copia recebida na abertura da chamada.
        _activeSession = AttendanceSession(
          id: updated.id,
          classId: updated.classId,
          classLabel: updated.classLabel,
          classIds: updated.classIds,
          classes: updated.classes,
          discipline: updated.discipline,
          attendanceDate: updated.attendanceDate,
          open: updated.open,
          semester: updated.semester,
          title: updated.title,
          lessonId: updated.lessonId,
          openedAt: updated.openedAt,
          expiresAt: updated.expiresAt,
          closedAt: updated.closedAt,
          checkInUrl: current.checkInUrl,
          expectedCount: updated.expectedCount,
          presentCount: updated.presentCount,
          records: updated.records,
          absentStudents: updated.absentStudents,
        );
      });
    } catch (_) {
      // A atualizacao automatica tenta novamente no proximo ciclo.
    }
  }

  Future<void> _closeSession() async {
    final current = _activeSession;
    if (current == null) return;
    try {
      final closed = await education.closeAttendanceSession(current.id);
      if (!mounted) return;
      setState(() => _activeSession = closed);
      _report('Chamada encerrada com ${closed.presentCount} presenca(s).');
      await _loadReports();
    } catch (e) {
      _report('Falha ao encerrar chamada: $e', error: true);
    }
  }

  Future<void> _deleteSession(AttendanceSession session) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Excluir chamada?'),
        content: Text(
          'A chamada de ${session.attendanceDate} das turmas '
          '${session.classLabel}, com ${session.presentCount} presença(s), '
          'será excluída permanentemente. A turma e os alunos permanecerão '
          'cadastrados.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.delete_outline, size: 16),
            label: const Text('EXCLUIR CHAMADA'),
            style: FilledButton.styleFrom(
              backgroundColor: AssistantTheme.danger,
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _deletingSessionId = session.id);
    try {
      await education.deleteAttendanceSession(session.id);
      if (!mounted) return;
      setState(() {
        if (_activeSession?.id == session.id) _activeSession = null;
        _sessions.removeWhere((item) => item.id == session.id);
      });
      _report('Chamada de ${session.attendanceDate} excluída.');
      await _loadReports();
    } catch (e) {
      _report('Falha ao excluir chamada: $e', error: true);
    } finally {
      if (mounted && _deletingSessionId == session.id) {
        setState(() => _deletingSessionId = null);
      }
    }
  }

  Future<void> _addManualAttendance() async {
    final current = _activeSession;
    final enrollment = _manualEnrollmentCtrl.text.trim();
    if (current == null || enrollment.isEmpty) return;
    try {
      final updated =
          await education.addManualAttendance(current.id, enrollment);
      if (!mounted) return;
      setState(() => _activeSession = AttendanceSession(
            id: updated.id,
            classId: updated.classId,
            classLabel: updated.classLabel,
            classIds: updated.classIds,
            classes: updated.classes,
            discipline: updated.discipline,
            attendanceDate: updated.attendanceDate,
            open: updated.open,
            semester: updated.semester,
            title: updated.title,
            lessonId: updated.lessonId,
            openedAt: updated.openedAt,
            expiresAt: updated.expiresAt,
            closedAt: updated.closedAt,
            checkInUrl: current.checkInUrl,
            expectedCount: updated.expectedCount,
            presentCount: updated.presentCount,
            records: updated.records,
            absentStudents: updated.absentStudents,
          ));
      _manualEnrollmentCtrl.clear();
      _report('Presenca registrada manualmente.');
    } catch (e) {
      _report('Falha ao registrar presenca: $e', error: true);
    }
  }

  Future<void> _deleteRecord(AttendanceRecord record) async {
    final current = _activeSession;
    if (current == null) return;
    try {
      await education.deleteAttendanceRecord(current.id, record.id);
      await _refreshActiveSession();
      _report('Presenca de ${record.studentName} removida.');
    } catch (e) {
      _report('Falha ao remover presenca: $e', error: true);
    }
  }

  Future<void> _openSessionReport(AttendanceSession session) async {
    await showDialog<void>(
      context: context,
      builder: (_) => _AttendanceSessionReportDialog(
        session: session,
        onPrint: () => _exportSessionAttendance(session),
      ),
    );
  }

  Future<void> _pickDate({required bool from}) async {
    final picked = await showDatePicker(
      context: context,
      initialDate: from ? _from : _to,
      firstDate: DateTime(2020),
      lastDate: DateTime(2100),
    );
    if (picked == null) return;
    setState(() => from ? _from = picked : _to = picked);
    await _loadReports();
  }

  Future<void> _exportReport() async {
    final kind = await showDialog<AcademicReportKind>(
      context: context,
      builder: (_) => const _ReportKindDialog(),
    );
    if (kind == null || !mounted) return;
    setState(() => _exporting = true);
    try {
      final bytes = await buildAcademicReportPdf(
        classes: _reportClasses,
        disciplines: _disciplines,
        students: _students,
        attendance: const AttendanceReport(),
        generatedAt: DateTime.now(),
        kind: kind,
      );
      if (!mounted) return;
      final fileName = academicReportFilename(DateTime.now(), kind: kind);
      final save = await showDialog<bool>(
        context: context,
        builder: (_) => _AcademicPdfPreview(
          bytes: bytes,
          fileName: fileName,
          reportTitle: kind.title,
        ),
      );
      if (save != true) return;
      final path = await FilePicker.saveFile(
        dialogTitle: 'Salvar relatorio educacional',
        fileName: fileName,
        type: FileType.custom,
        allowedExtensions: const ['pdf'],
        bytes: bytes,
      );
      if (path == null) return;
      final file =
          File(path.toLowerCase().endsWith('.pdf') ? path : '$path.pdf');
      if (!await file.exists() || await file.length() != bytes.length) {
        await file.writeAsBytes(bytes);
      }
      _report('${kind.title} salvo em ${file.path}');
    } catch (e) {
      _report('Falha ao gerar relatorio: $e', error: true);
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<void> _exportSessionAttendance(AttendanceSession session) async {
    if (_exporting) return;
    setState(() => _exporting = true);
    try {
      final report = attendanceReportForSession(session);
      final sessionClassIds = session.classIds.isEmpty
          ? {session.classId}
          : session.classIds.toSet();
      final bytes = await buildAcademicReportPdf(
        classes: _reportClasses
            .where((group) => sessionClassIds.contains(group.id))
            .toList(),
        disciplines: _disciplines,
        students: _students
            .where((student) => sessionClassIds.contains(student.classId))
            .toList(),
        attendance: report,
        generatedAt: DateTime.now(),
        kind: AcademicReportKind.attendance,
      );
      if (!mounted) return;
      final fileName = attendanceSessionPdfFilename(session);
      final save = await showDialog<bool>(
        context: context,
        builder: (_) => _AcademicPdfPreview(
          bytes: bytes,
          fileName: fileName,
          reportTitle: 'Presença da chamada de ${session.attendanceDate}',
          allowPrinting: true,
        ),
      );
      if (save != true) return;
      final path = await FilePicker.saveFile(
        dialogTitle: 'Salvar presença desta chamada',
        fileName: fileName,
        type: FileType.custom,
        allowedExtensions: const ['pdf'],
        bytes: bytes,
      );
      if (path == null) return;
      final file =
          File(path.toLowerCase().endsWith('.pdf') ? path : '$path.pdf');
      if (!await file.exists() || await file.length() != bytes.length) {
        await file.writeAsBytes(bytes);
      }
      _report('Presença desta chamada salva em ${file.path}');
    } catch (e) {
      _report('Falha ao imprimir a presença desta chamada: $e', error: true);
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<void> _createAgenda() async {
    final now = DateTime.now();
    final allClasses = widget.classes.value ?? const <ClassGroup>[];
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
      _report(
        'Cadastre os dias e horarios das turmas antes de criar a agenda.',
        error: true,
      );
      return;
    }

    setState(() => _syncingAgenda = true);
    try {
      final accountGroups = await api.listCalendarAccounts();
      final accounts = [
        ...accountGroups['google'] ?? const <CalendarAccount>[],
        ...accountGroups['microsoft'] ?? const <CalendarAccount>[],
      ].where((account) => account.connected).toList();
      if (!mounted) return;
      if (accounts.isEmpty) {
        _report(
          'Conecte uma conta Google ou Microsoft em Configuracoes > Calendarios.',
          error: true,
        );
        return;
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
                          child: _AttendanceDateButton(
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
                          child: _AttendanceDateButton(
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
                            _AgendaSelection(
                              account: account,
                              from: from,
                              to: to,
                            ),
                          ),
                  icon: const Icon(Icons.event_repeat, size: 16),
                  label: const Text('CONFIRMAR'),
                ),
              ],
            ),
          );
        },
      );
      if (selection == null) return;

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
        _report(
          'Nenhuma serie foi criada. ${errors.firstOrNull ?? 'Verifique os horarios e a conta.'}',
          error: true,
        );
      } else {
        _report(
          'Agenda pronta: $created serie(s) criada(s), $skipped ja existente(s)'
          '${failed > 0 ? ' e $failed falha(s)' : ''}. Os lembretes serao '
          'carregados na proxima sincronizacao.',
          error: failed > 0,
        );
      }
    } catch (e) {
      _report('Falha ao criar agenda das turmas: $e', error: true);
    } finally {
      if (mounted) setState(() => _syncingAgenda = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final classes = widget.classes.value ?? const <ClassGroup>[];
    final todayClasses = attendanceClassesForDay(
      classes,
      DateTime.now().weekday,
    );
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildToolbar(todayClasses),
          if (_status.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              _status,
              style: TextStyle(
                fontSize: 11,
                color: _statusError
                    ? AssistantTheme.danger
                    : AssistantTheme.textSecondary,
              ),
            ),
          ],
          const SizedBox(height: 10),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 6, child: _buildCallPanel()),
                const SizedBox(width: 14),
                Expanded(
                  flex: 5,
                  child: _buildReportsPanel(todayClasses),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _selectTodayClasses(List<ClassGroup> todayClasses) async {
    if (todayClasses.isEmpty || _activeSession?.open == true) return;
    var draft = Set<String>.of(_selectedClassIds);
    final selected = await showDialog<Set<String>>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Turmas desta chamada'),
          content: SizedBox(
            width: 480,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'As turmas previstas para hoje ja estao selecionadas. '
                  'Todos os alunos usarao o mesmo QR Code.',
                  style: TextStyle(fontSize: 12),
                ),
                const SizedBox(height: 10),
                for (final group in todayClasses)
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: draft.contains(group.id),
                    title: Text(group.display),
                    subtitle: Text(group.scheduleLabel),
                    onChanged: (checked) => setDialogState(() {
                      if (checked == true) {
                        draft.add(group.id);
                      } else {
                        draft.remove(group.id);
                      }
                    }),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => setDialogState(
                () => draft = todayClasses.map((item) => item.id).toSet(),
              ),
              child: const Text('SELECIONAR TODAS'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('CANCELAR'),
            ),
            FilledButton(
              onPressed: draft.isEmpty
                  ? null
                  : () => Navigator.pop(dialogContext, draft),
              child: const Text('APLICAR'),
            ),
          ],
        ),
      ),
    );
    if (selected != null && mounted) {
      setState(() => _selectedClassIds = selected);
    }
  }

  Widget _buildToolbar(List<ClassGroup> todayClasses) => Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            flex: 3,
            child: InkWell(
              onTap: _activeSession?.open == true
                  ? null
                  : () => _selectTodayClasses(todayClasses),
              borderRadius: BorderRadius.circular(4),
              child: InputDecorator(
                decoration: _decoration('TURMAS DE HOJE - QR UNICO'),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        todayClasses.isEmpty
                            ? 'Nenhuma turma prevista hoje'
                            : '${_selectedClassIds.length} de ${todayClasses.length} selecionada(s)',
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 11),
                      ),
                    ),
                    const Icon(Icons.arrow_drop_down, size: 18),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 2,
            child: TextField(
              controller: _titleCtrl,
              decoration: _decoration('IDENTIFICACAO DA AULA').copyWith(
                hintText: 'Ex.: Revisao para prova',
              ),
              style: const TextStyle(fontSize: 11),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 112,
            child: DropdownButtonFormField<int>(
              initialValue: _durationMinutes,
              isExpanded: true,
              decoration: _decoration('DURACAO'),
              items: const [10, 15, 30, 45, 60]
                  .map((minutes) => DropdownMenuItem(
                        value: minutes,
                        child: Text('$minutes min'),
                      ))
                  .toList(),
              onChanged: _activeSession?.open == true
                  ? null
                  : (value) => setState(
                        () => _durationMinutes = value ?? 15,
                      ),
            ),
          ),
          const SizedBox(width: 8),
          FilledButton.icon(
            onPressed: _creating ||
                    _activeSession?.open == true ||
                    _selectedClassIds.isEmpty
                ? null
                : _createSession,
            icon: _creating
                ? const SizedBox.square(
                    dimension: 14,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.qr_code_2, size: 16),
            label: Text(_creating ? 'GERANDO...' : 'GERAR QR'),
            style: FilledButton.styleFrom(
              backgroundColor: AssistantTheme.c3,
              foregroundColor: AssistantTheme.bg,
              minimumSize: const Size(120, 40),
            ),
          ),
        ],
      );

  Widget _buildCallPanel() {
    final session = _activeSession;
    return _AttendancePanel(
      title:
          session == null ? 'CHAMADA ATUAL' : session.classLabel.toUpperCase(),
      trailing: session == null
          ? null
          : Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (session.open)
                  TextButton.icon(
                    onPressed: _closeSession,
                    icon: const Icon(Icons.stop_circle_outlined, size: 14),
                    label: const Text(
                      'ENCERRAR',
                      style: TextStyle(fontSize: 10),
                    ),
                  ),
                IconButton(
                  tooltip: 'Relatorio exclusivo desta chamada',
                  onPressed: () => _openSessionReport(session),
                  icon: const Icon(Icons.assignment_outlined, size: 17),
                ),
                IconButton(
                  tooltip: 'Excluir chamada',
                  onPressed: _deletingSessionId != null
                      ? null
                      : () => _deleteSession(session),
                  icon: _deletingSessionId == session.id
                      ? const SizedBox.square(
                          dimension: 14,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(
                          Icons.delete_outline,
                          size: 17,
                          color: AssistantTheme.danger,
                        ),
                ),
              ],
            ),
      child: session == null
          ? _AttendanceEmpty(
              icon: Icons.qr_code_2,
              text: _selectedClassIds.isEmpty
                  ? 'Nenhuma turma esta prevista para hoje. Confira os dias de aula no cadastro da turma.'
                  : 'As turmas de hoje ja foram selecionadas. Gere um unico QR Code para iniciar a chamada.',
            )
          : Column(
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 190,
                      height: 190,
                      color: Colors.white,
                      padding: const EdgeInsets.all(8),
                      child: session.checkInUrl.isEmpty
                          ? const Center(
                              child: Text(
                                'QR indisponivel. Gere uma nova chamada.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Colors.black54,
                                  fontSize: 11,
                                ),
                              ),
                            )
                          : QrImageView(
                              data: session.checkInUrl,
                              version: QrVersions.auto,
                            ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(child: _buildSessionSummary(session)),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _manualEnrollmentCtrl,
                        onSubmitted: (_) => _addManualAttendance(),
                        decoration: _decoration('PRESENCA MANUAL').copyWith(
                          hintText: 'Matricula do aluno',
                        ),
                        style: const TextStyle(fontSize: 11),
                      ),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton.icon(
                      onPressed: _addManualAttendance,
                      icon: const Icon(Icons.person_add_alt_1, size: 15),
                      label: const Text('MARCAR'),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: session.records.isEmpty
                      ? const _AttendanceEmpty(
                          icon: Icons.how_to_reg_outlined,
                          text: 'Aguardando as primeiras confirmacoes.',
                        )
                      : ListView.separated(
                          itemCount: session.records.length,
                          separatorBuilder: (_, __) => const Divider(
                            height: 8,
                            color: AssistantTheme.border,
                          ),
                          itemBuilder: (_, index) {
                            final record = session.records[index];
                            return Row(
                              children: [
                                const Icon(
                                  Icons.check_circle,
                                  size: 15,
                                  color: AssistantTheme.c3,
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        '${record.studentName}  -  ${record.enrollment}',
                                        style: const TextStyle(
                                          fontSize: 11,
                                          color: AssistantTheme.textPrimary,
                                        ),
                                      ),
                                      if (session.classCount > 1)
                                        Text(
                                          record.classLabel,
                                          style: const TextStyle(
                                            fontSize: 8,
                                            color: AssistantTheme.textMuted,
                                          ),
                                        ),
                                    ],
                                  ),
                                ),
                                Text(
                                  record.source == 'manual' ? 'manual' : 'QR',
                                  style: const TextStyle(
                                    fontSize: 9,
                                    color: AssistantTheme.textMuted,
                                  ),
                                ),
                                IconButton(
                                  tooltip: 'Remover presenca',
                                  onPressed: () => _deleteRecord(record),
                                  icon: const Icon(
                                    Icons.close,
                                    size: 14,
                                    color: AssistantTheme.textMuted,
                                  ),
                                ),
                              ],
                            );
                          },
                        ),
                ),
              ],
            ),
    );
  }

  Widget _buildSessionSummary(AttendanceSession session) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            session.discipline,
            style: const TextStyle(
              color: AssistantTheme.textPrimary,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
          if (session.classCount > 1) ...[
            const SizedBox(height: 4),
            Text(
              '${session.classCount} turmas reunidas em um unico QR Code',
              style: const TextStyle(
                color: AssistantTheme.c2,
                fontSize: 10,
              ),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            '${session.presentCount} presentes de ${session.expectedCount}',
            style: const TextStyle(
              color: AssistantTheme.c3,
              fontSize: 18,
              fontWeight: FontWeight.w700,
            ),
          ),
          Text(
            '${session.absentCount} ainda nao confirmaram',
            style: const TextStyle(
              color: AssistantTheme.textMuted,
              fontSize: 10,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            session.open
                ? 'Aberta ate ${_time(session.expiresAt)}'
                : 'Chamada encerrada',
            style: TextStyle(
              color: session.open
                  ? AssistantTheme.textSecondary
                  : AssistantTheme.danger,
              fontSize: 10,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 4,
            children: [
              IconButton(
                tooltip: 'Copiar link',
                onPressed: session.checkInUrl.isEmpty
                    ? null
                    : () async {
                        await Clipboard.setData(
                          ClipboardData(text: session.checkInUrl),
                        );
                        _report('Link da chamada copiado.');
                      },
                icon: const Icon(Icons.copy, size: 16),
              ),
              IconButton(
                tooltip: 'Testar pagina no navegador',
                onPressed: session.checkInUrl.isEmpty
                    ? null
                    : () => launchUrl(
                          Uri.parse(session.checkInUrl),
                          mode: LaunchMode.externalApplication,
                        ),
                icon: const Icon(Icons.open_in_browser, size: 16),
              ),
              IconButton(
                tooltip: 'Atualizar presencas',
                onPressed: _refreshActiveSession,
                icon: const Icon(Icons.refresh, size: 16),
              ),
            ],
          ),
        ],
      );

  Widget _buildReportsPanel(List<ClassGroup> todayClasses) => _AttendancePanel(
        title: 'RELATORIOS E AULAS DO DIA',
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconButton(
              tooltip: 'Criar agenda das turmas no calendario',
              onPressed: _syncingAgenda ? null : _createAgenda,
              icon: _syncingAgenda
                  ? const SizedBox.square(
                      dimension: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.event_repeat, size: 17),
            ),
            FilledButton.icon(
              onPressed: _exporting ? null : _exportReport,
              icon: const Icon(Icons.picture_as_pdf_outlined, size: 14),
              label: Text(
                _exporting ? 'GERANDO...' : 'GERAR RELATORIO',
                style: const TextStyle(fontSize: 10),
              ),
              style: FilledButton.styleFrom(
                backgroundColor: AssistantTheme.c3,
                foregroundColor: AssistantTheme.bg,
              ),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: _AttendanceDateButton(
                    label: 'DE',
                    value: _from,
                    onTap: () => _pickDate(from: true),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _AttendanceDateButton(
                    label: 'ATE',
                    value: _to,
                    onTap: () => _pickDate(from: false),
                  ),
                ),
                const SizedBox(width: 4),
                IconButton(
                  tooltip: 'Atualizar relatorios',
                  onPressed: _loadReports,
                  icon: const Icon(Icons.refresh, size: 16),
                ),
              ],
            ),
            const SizedBox(height: 10),
            const Text(
              'AULAS DE HOJE',
              style: TextStyle(
                color: AssistantTheme.textMuted,
                fontSize: 9,
                letterSpacing: 1.4,
              ),
            ),
            const SizedBox(height: 5),
            if (todayClasses.isEmpty)
              const Text(
                'Nenhuma aula prevista para hoje.',
                style: TextStyle(
                  color: AssistantTheme.textSecondary,
                  fontSize: 10,
                ),
              )
            else
              ...todayClasses.map(
                (group) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    '${group.scheduleLabel}  |  ${group.discipline}  |  ${group.label}',
                    style: const TextStyle(
                      color: AssistantTheme.textPrimary,
                      fontSize: 10,
                    ),
                  ),
                ),
              ),
            const Divider(height: 18, color: AssistantTheme.border),
            Row(
              children: [
                const Text(
                  'CHAMADAS NO PERIODO',
                  style: TextStyle(
                    color: AssistantTheme.textMuted,
                    fontSize: 9,
                    letterSpacing: 1.4,
                  ),
                ),
                const Spacer(),
                Text(
                  '${_sessions.length}',
                  style: const TextStyle(
                    color: AssistantTheme.c3,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 5),
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : _sessions.isEmpty
                      ? const _AttendanceEmpty(
                          icon: Icons.fact_check_outlined,
                          text: 'Nenhuma chamada no periodo selecionado.',
                        )
                      : ListView.separated(
                          itemCount: _sessions.length,
                          separatorBuilder: (_, __) => const Divider(
                            height: 10,
                            color: AssistantTheme.border,
                          ),
                          itemBuilder: (_, index) {
                            final session = _sessions[index];
                            return Row(
                              key: ValueKey(session.id),
                              children: [
                                Icon(
                                  session.open
                                      ? Icons.radio_button_checked
                                      : Icons.fact_check_outlined,
                                  size: 15,
                                  color: session.open
                                      ? AssistantTheme.c3
                                      : AssistantTheme.textMuted,
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        '${session.attendanceDate}  |  ${session.classLabel}',
                                        style: const TextStyle(
                                          color: AssistantTheme.textPrimary,
                                          fontSize: 11,
                                        ),
                                      ),
                                      Text(
                                        '${session.discipline}  -  '
                                        '${session.presentCount}/${session.expectedCount} presentes',
                                        style: const TextStyle(
                                          color: AssistantTheme.textMuted,
                                          fontSize: 9,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                IconButton(
                                  tooltip: 'Relatorio exclusivo desta chamada',
                                  onPressed: () => _openSessionReport(session),
                                  icon: const Icon(
                                    Icons.assignment_outlined,
                                    size: 16,
                                    color: AssistantTheme.c1,
                                  ),
                                ),
                                IconButton(
                                  tooltip: 'Lancar esta chamada no SIA',
                                  onPressed: () => showDialog(
                                    context: context,
                                    builder: (_) => SiaAttendanceImporter(refId: session.id),
                                  ),
                                  icon: const Icon(
                                    Icons.cloud_upload_outlined,
                                    size: 16,
                                    color: AssistantTheme.c2,
                                  ),
                                ),
                                IconButton(
                                  tooltip: 'Excluir chamada',
                                  onPressed: _deletingSessionId != null
                                      ? null
                                      : () => _deleteSession(session),
                                  icon: _deletingSessionId == session.id
                                      ? const SizedBox.square(
                                          dimension: 14,
                                          child: CircularProgressIndicator(
                                            strokeWidth: 2,
                                          ),
                                        )
                                      : const Icon(
                                          Icons.delete_outline,
                                          size: 16,
                                          color: AssistantTheme.danger,
                                        ),
                                ),
                              ],
                            );
                          },
                        ),
            ),
          ],
        ),
      );

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
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        border: const OutlineInputBorder(
          borderSide: BorderSide(color: AssistantTheme.border),
        ),
        enabledBorder: const OutlineInputBorder(
          borderSide: BorderSide(color: AssistantTheme.border),
        ),
      );
}

class _AttendancePanel extends StatelessWidget {
  final String title;
  final Widget child;
  final Widget? trailing;

  const _AttendancePanel({
    required this.title,
    required this.child,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AssistantTheme.bg2,
          border: Border.all(color: AssistantTheme.border),
          borderRadius: BorderRadius.circular(3),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AssistantTheme.textMuted,
                      fontSize: 9,
                      letterSpacing: 1.5,
                    ),
                  ),
                ),
                trailing ?? const SizedBox.shrink(),
              ],
            ),
            const SizedBox(height: 8),
            Expanded(child: child),
          ],
        ),
      );
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

class _AttendanceEmpty extends StatelessWidget {
  final IconData icon;
  final String text;

  const _AttendanceEmpty({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 30, color: AssistantTheme.textMuted),
            const SizedBox(height: 8),
            Text(
              text,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: AssistantTheme.textMuted,
                fontSize: 11,
              ),
            ),
          ],
        ),
      );
}

class _AttendanceDateButton extends StatelessWidget {
  final String label;
  final DateTime value;
  final VoidCallback onTap;

  const _AttendanceDateButton({
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

class _AttendanceSessionReportDialog extends StatelessWidget {
  final AttendanceSession session;
  final VoidCallback onPrint;

  const _AttendanceSessionReportDialog({
    required this.session,
    required this.onPrint,
  });

  @override
  Widget build(BuildContext context) {
    final transcript = attendanceSessionTranscript(session);
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760, maxHeight: 680),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.assignment_outlined,
                    color: AssistantTheme.c1,
                  ),
                  const SizedBox(width: 9),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'RELATORIO DESTA CHAMADA',
                          style: TextStyle(
                            color: AssistantTheme.textPrimary,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 1.2,
                          ),
                        ),
                        Text(
                          'Copie, salve ou imprima somente este registro',
                          style: TextStyle(
                            color: AssistantTheme.textMuted,
                            fontSize: 10,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  _SessionMetric(
                    value: '${session.classCount}',
                    label: 'turmas',
                  ),
                  const SizedBox(width: 8),
                  _SessionMetric(
                    value: '${session.presentCount}',
                    label: 'presentes',
                    color: AssistantTheme.c3,
                  ),
                  const SizedBox(width: 8),
                  _SessionMetric(
                    value: '${session.absentCount}',
                    label: 'ausentes',
                    color: AssistantTheme.c4,
                  ),
                  const Spacer(),
                  Text(
                    session.attendanceDate,
                    style: const TextStyle(
                      color: AssistantTheme.textSecondary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Expanded(
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: AssistantTheme.bg2,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: AssistantTheme.border2),
                  ),
                  child: SingleChildScrollView(
                    child: SelectableText(
                      transcript,
                      style: const TextStyle(
                        color: AssistantTheme.textPrimary,
                        fontSize: 11,
                        height: 1.55,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Wrap(
                alignment: WrapAlignment.end,
                spacing: 8,
                runSpacing: 8,
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('FECHAR'),
                  ),
                  OutlinedButton.icon(
                    onPressed: () {
                      Navigator.pop(context);
                      onPrint();
                    },
                    icon: const Icon(Icons.print_outlined, size: 16),
                    label: const Text('IMPRIMIR / PDF'),
                  ),
                  FilledButton.icon(
                    onPressed: () async {
                      await Clipboard.setData(ClipboardData(text: transcript));
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text(
                            'Relatorio copiado. Pronto para colar no ambiente da faculdade.',
                          ),
                        ),
                      );
                    },
                    icon: const Icon(Icons.copy_all_outlined, size: 16),
                    label: const Text('COPIAR PARA A FACULDADE'),
                    style: FilledButton.styleFrom(
                      backgroundColor: AssistantTheme.c3,
                      foregroundColor: AssistantTheme.bg,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SessionMetric extends StatelessWidget {
  final String value;
  final String label;
  final Color color;

  const _SessionMetric({
    required this.value,
    required this.label,
    this.color = AssistantTheme.c1,
  });

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          color: color.withOpacity(.08),
          borderRadius: BorderRadius.circular(5),
          border: Border.all(color: color.withOpacity(.45)),
        ),
        child: Row(
          children: [
            Text(
              value,
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(width: 5),
            Text(
              label,
              style: const TextStyle(
                color: AssistantTheme.textMuted,
                fontSize: 9,
              ),
            ),
          ],
        ),
      );
}

class _ReportKindDialog extends StatelessWidget {
  const _ReportKindDialog();

  @override
  Widget build(BuildContext context) => Dialog(
        backgroundColor: AssistantTheme.surface,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620, maxHeight: 660),
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.description_outlined, color: AssistantTheme.c1),
                    SizedBox(width: 9),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'ESCOLHA O RELATORIO',
                            style: TextStyle(
                              color: AssistantTheme.textPrimary,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 1.2,
                            ),
                          ),
                          Text(
                            'Cada documento pode ser gerado de forma independente.',
                            style: TextStyle(
                              color: AssistantTheme.textMuted,
                              fontSize: 10,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Flexible(
                  child: ListView.separated(
                    shrinkWrap: true,
                    itemCount: generalAcademicReportKinds.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, index) {
                      final kind = generalAcademicReportKinds[index];
                      final consolidated =
                          kind == AcademicReportKind.consolidated;
                      return InkWell(
                        onTap: () => Navigator.pop(context, kind),
                        borderRadius: BorderRadius.circular(7),
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: consolidated
                                ? AssistantTheme.c2.withOpacity(.08)
                                : AssistantTheme.bg2,
                            borderRadius: BorderRadius.circular(7),
                            border: Border.all(
                              color: consolidated
                                  ? AssistantTheme.c2.withOpacity(.55)
                                  : AssistantTheme.border2,
                            ),
                          ),
                          child: Row(
                            children: [
                              Container(
                                width: 38,
                                height: 38,
                                decoration: BoxDecoration(
                                  color: _reportKindColor(kind).withOpacity(.1),
                                  borderRadius: BorderRadius.circular(6),
                                ),
                                child: Icon(
                                  _reportKindIcon(kind),
                                  size: 20,
                                  color: _reportKindColor(kind),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      kind.title,
                                      style: const TextStyle(
                                        color: AssistantTheme.textPrimary,
                                        fontWeight: FontWeight.w700,
                                        fontSize: 12,
                                      ),
                                    ),
                                    const SizedBox(height: 3),
                                    Text(
                                      kind.description,
                                      style: const TextStyle(
                                        color: AssistantTheme.textMuted,
                                        fontSize: 10,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              if (consolidated)
                                const Padding(
                                  padding: EdgeInsets.only(right: 8),
                                  child: Text(
                                    'COMPLETO',
                                    style: TextStyle(
                                      color: AssistantTheme.c2,
                                      fontSize: 8,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ),
                              const Icon(Icons.chevron_right, size: 18),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
                const SizedBox(height: 10),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('CANCELAR'),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}

IconData _reportKindIcon(AcademicReportKind kind) => switch (kind) {
      AcademicReportKind.attendance => Icons.fact_check_outlined,
      AcademicReportKind.schedule => Icons.calendar_view_week_outlined,
      AcademicReportKind.roster => Icons.groups_outlined,
      AcademicReportKind.disciplines => Icons.school_outlined,
      AcademicReportKind.consolidated => Icons.dashboard_customize_outlined,
    };

Color _reportKindColor(AcademicReportKind kind) => switch (kind) {
      AcademicReportKind.attendance => AssistantTheme.c3,
      AcademicReportKind.schedule => AssistantTheme.c1,
      AcademicReportKind.roster => AssistantTheme.c2,
      AcademicReportKind.disciplines => AssistantTheme.c4,
      AcademicReportKind.consolidated => AssistantTheme.c2,
    };

class _AcademicPdfPreview extends StatelessWidget {
  final Uint8List bytes;
  final String fileName;
  final String reportTitle;
  final bool allowPrinting;

  const _AcademicPdfPreview({
    required this.bytes,
    required this.fileName,
    required this.reportTitle,
    this.allowPrinting = false,
  });

  @override
  Widget build(BuildContext context) => Dialog(
        insetPadding: const EdgeInsets.all(24),
        backgroundColor: AssistantTheme.surface,
        child: SizedBox(
          width: 900,
          height: 700,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 10, 8, 10),
                child: Row(
                  children: [
                    const Icon(
                      Icons.preview_outlined,
                      color: AssistantTheme.c3,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'PRE-VISUALIZACAO - ${reportTitle.toUpperCase()}',
                        style: const TextStyle(
                          color: AssistantTheme.textPrimary,
                          fontWeight: FontWeight.w700,
                          fontSize: 11,
                        ),
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.pop(context, false),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: PdfPreview(
                  build: (_) async => bytes,
                  pdfFileName: fileName,
                  useActions: allowPrinting,
                  allowPrinting: allowPrinting,
                  allowSharing: false,
                  canChangePageFormat: false,
                  canChangeOrientation: false,
                  canDebug: false,
                  maxPageWidth: 720,
                  padding: const EdgeInsets.all(18),
                  scrollViewDecoration:
                      const BoxDecoration(color: Color(0xFFE6EBF1)),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(10),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('CANCELAR'),
                    ),
                    const SizedBox(width: 8),
                    FilledButton.icon(
                      onPressed: () => Navigator.pop(context, true),
                      icon: const Icon(Icons.save_alt, size: 15),
                      label: const Text('SALVAR PDF'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}

String _date(DateTime value) {
  final local = value.toLocal();
  final month = local.month.toString().padLeft(2, '0');
  final day = local.day.toString().padLeft(2, '0');
  return '${local.year}-$month-$day';
}

String _time(DateTime? value) {
  if (value == null) return '--:--';
  final local = value.toLocal();
  return '${local.hour.toString().padLeft(2, '0')}:'
      '${local.minute.toString().padLeft(2, '0')}';
}

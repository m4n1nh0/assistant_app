/// Geracao dos PDFs academicos: presenca, agenda e lista de alunos.
library;

import 'dart:typed_data';

import 'package:flutter/services.dart' show rootBundle;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../branding/intarq_brand.dart';
import 'education_service.dart';

const _accent = PdfColor.fromInt(0xFF007F9E);
const _accentLight = PdfColor.fromInt(0xFFEAF8FC);
const _ink = PdfColor.fromInt(0xFF111827);
const _muted = PdfColor.fromInt(0xFF526277);
const _rule = PdfColor.fromInt(0xFFD8E0EA);

/// Tipo de relatorio academico gerado em PDF.
enum AcademicReportKind {
  attendance,
  schedule,
  roster,
  disciplines,
  consolidated,
}

const generalAcademicReportKinds = [
  AcademicReportKind.schedule,
  AcademicReportKind.roster,
  AcademicReportKind.disciplines,
  AcademicReportKind.consolidated,
];

bool academicReportIncludesAttendance(AcademicReportKind kind) =>
    kind == AcademicReportKind.attendance;

extension AcademicReportKindDetails on AcademicReportKind {
  String get title => switch (this) {
        AcademicReportKind.attendance => 'Relatório de presença',
        AcademicReportKind.schedule => 'Quadro de aulas',
        AcademicReportKind.roster => 'Relatório de turmas e alunos',
        AcademicReportKind.disciplines => 'Relatório de disciplinas',
        AcademicReportKind.consolidated => 'Relatório educacional geral',
      };

  String get description => switch (this) {
        AcademicReportKind.attendance =>
          'Chamadas, presentes e ausentes no período selecionado.',
        AcademicReportKind.schedule =>
          'Dias, horários, turmas, disciplinas e semestre.',
        AcademicReportKind.roster =>
          'Relação de alunos com matrícula, separada por turma.',
        AcademicReportKind.disciplines =>
          'Disciplinas cadastradas, semestre e situação.',
        AcademicReportKind.consolidated =>
          'Aulas, turmas, alunos e disciplinas. Presença sai pela chamada.',
      };

  String get filePrefix => switch (this) {
        AcademicReportKind.attendance => 'relatorio-presenca',
        AcademicReportKind.schedule => 'quadro-aulas',
        AcademicReportKind.roster => 'turmas-alunos',
        AcademicReportKind.disciplines => 'disciplinas',
        AcademicReportKind.consolidated => 'relatorio-educacional',
      };
}

pw.ThemeData? _cachedTheme;

Future<pw.ThemeData> _theme() async {
  if (_cachedTheme != null) return _cachedTheme!;
  try {
    _cachedTheme = pw.ThemeData.withFont(
      base:
          pw.Font.ttf(await rootBundle.load('assets/fonts/roboto-regular.ttf')),
      bold: pw.Font.ttf(await rootBundle.load('assets/fonts/roboto-bold.ttf')),
    );
    return _cachedTheme!;
  } catch (_) {
    return pw.ThemeData.withFont();
  }
}

const _weekdays = [
  'Segunda-feira',
  'Terça-feira',
  'Quarta-feira',
  'Quinta-feira',
  'Sexta-feira',
  'Sábado',
  'Domingo',
];

String academicReportFilename(
  DateTime generatedAt, {
  AcademicReportKind kind = AcademicReportKind.consolidated,
}) {
  final date = generatedAt.toLocal().toIso8601String().split('T').first;
  return '${kind.filePrefix}-$date.pdf';
}

Future<Uint8List> buildAcademicReportPdf({
  required List<ClassGroup> classes,
  required List<Discipline> disciplines,
  required List<Student> students,
  required AttendanceReport attendance,
  required DateTime generatedAt,
  AcademicReportKind kind = AcademicReportKind.consolidated,
}) async {
  final document = pw.Document(
    title: kind.title,
    author: 'INTARQ',
  );
  final brandMark = await IntarqBrand.loadPdfMark();
  final orderedClasses = [...classes]..sort((a, b) =>
      '${a.semester}${a.discipline}${a.label}'
          .compareTo('${b.semester}${b.discipline}${b.label}'));
  final scheduleRows = <List<String>>[];
  for (final group in orderedClasses) {
    for (final schedule in group.schedules) {
      scheduleRows.add([
        _weekdays[schedule.weekday.clamp(0, 6)],
        [schedule.startTime, schedule.endTime]
            .where((part) => part.isNotEmpty)
            .join(' - '),
        group.discipline,
        group.label,
        group.semester,
      ]);
    }
  }
  scheduleRows.sort((a, b) {
    final day = _weekdays.indexOf(a[0]).compareTo(_weekdays.indexOf(b[0]));
    return day != 0 ? day : a[1].compareTo(b[1]);
  });
  final includeAttendance = academicReportIncludesAttendance(kind);
  final includeSchedule = kind == AcademicReportKind.schedule ||
      kind == AcademicReportKind.consolidated;
  final includeRoster = kind == AcademicReportKind.roster ||
      kind == AcademicReportKind.consolidated;
  final includeDisciplines = kind == AcademicReportKind.disciplines ||
      kind == AcademicReportKind.consolidated;

  document.addPage(
    pw.MultiPage(
      pageTheme: pw.PageTheme(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.fromLTRB(34, 28, 34, 38),
        theme: await _theme(),
      ),
      header: (context) => pw.Container(
        padding: const pw.EdgeInsets.only(bottom: 10),
        decoration: const pw.BoxDecoration(
          border: pw.Border(bottom: pw.BorderSide(color: _rule)),
        ),
        child: pw.Row(
          mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
          children: [
            IntarqBrand.pdfSignature(brandMark, width: 122, height: 45),
            pw.Text(
              _formatDate(generatedAt),
              style: const pw.TextStyle(color: _muted, fontSize: 9),
            ),
          ],
        ),
      ),
      footer: (context) => pw.Row(
        mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
        children: [
          IntarqBrand.pdfWordmark(fontSize: 8, intarColor: _muted),
          pw.Text(
            'Página ${context.pageNumber} de ${context.pagesCount}',
            style: const pw.TextStyle(color: _muted, fontSize: 8),
          ),
        ],
      ),
      build: (context) => [
        pw.SizedBox(height: 16),
        pw.Text(
          kind.title,
          style: pw.TextStyle(
            color: _ink,
            fontSize: 22,
            fontWeight: pw.FontWeight.bold,
          ),
        ),
        pw.SizedBox(height: 4),
        pw.Text(
          includeAttendance ? _periodLabel(attendance) : kind.description,
          style: const pw.TextStyle(color: _muted, fontSize: 10),
        ),
        pw.SizedBox(height: 16),
        _kindSummary(
          kind,
          attendance,
          orderedClasses,
          disciplines,
          students,
          scheduleRows.length,
        ),
        if (includeSchedule) ...[
          pw.SizedBox(height: 22),
          _heading('Quadro semanal de aulas'),
          if (scheduleRows.isEmpty)
            _empty('Nenhum horário cadastrado nas turmas.')
          else
            _table(
              headers: const [
                'Dia',
                'Horário',
                'Disciplina',
                'Turma',
                'Semestre'
              ],
              rows: scheduleRows,
            ),
        ],
        if (includeAttendance) ...[
          pw.SizedBox(height: 22),
          _heading('Relatório de presença'),
          if (attendance.sessions.isEmpty)
            _empty('Nenhuma chamada encontrada no período.')
          else
            ...attendance.sessions.expand(_attendanceSection),
        ],
        if (includeDisciplines) ...[
          pw.SizedBox(height: 22),
          _heading('Disciplinas'),
          if (disciplines.isEmpty)
            _empty('Nenhuma disciplina cadastrada.')
          else
            _table(
              headers: const ['Semestre', 'Código', 'Disciplina', 'Situação'],
              rows: ([...disciplines]..sort((a, b) => '${a.semester}${a.label}'
                      .compareTo('${b.semester}${b.label}')))
                  .map((item) => [
                        item.semester,
                        item.code,
                        item.name,
                        item.active ? 'Ativa' : 'Encerrada',
                      ])
                  .toList(),
            ),
        ],
        if (includeRoster) ...[
          pw.SizedBox(height: 22),
          _heading('Turmas e alunos'),
          if (orderedClasses.isEmpty)
            _empty('Nenhuma turma cadastrada.')
          else
            ...orderedClasses.map(
              (group) => _rosterSection(
                group,
                students
                    .where((student) => student.classId == group.id)
                    .toList(),
              ),
            ),
        ],
      ],
    ),
  );
  return document.save();
}

pw.Widget _summary(
  List<ClassGroup> classes,
  List<Discipline> disciplines,
  List<Student> students,
) {
  return pw.Container(
    padding: const pw.EdgeInsets.all(14),
    decoration: pw.BoxDecoration(
      color: _accentLight,
      border: pw.Border.all(color: _rule),
      borderRadius: const pw.BorderRadius.all(pw.Radius.circular(5)),
    ),
    child: pw.Row(
      mainAxisAlignment: pw.MainAxisAlignment.spaceAround,
      children: [
        _metric('${classes.length}', 'turmas'),
        _metric('${disciplines.length}', 'disciplinas'),
        _metric('${students.length}', 'alunos'),
      ],
    ),
  );
}

pw.Widget _kindSummary(
  AcademicReportKind kind,
  AttendanceReport attendance,
  List<ClassGroup> classes,
  List<Discipline> disciplines,
  List<Student> students,
  int scheduleCount,
) {
  if (kind == AcademicReportKind.consolidated) {
    return _summary(classes, disciplines, students);
  }
  final metrics = switch (kind) {
    AcademicReportKind.attendance => [
        ['${attendance.sessionCount}', 'chamadas'],
        ['${attendance.expectedTotal}', 'alunos esperados'],
        ['${attendance.presentTotal}', 'presenças'],
        [
          '${(attendance.expectedTotal - attendance.presentTotal).clamp(0, attendance.expectedTotal)}',
          'ausências'
        ],
        [
          '${(attendance.presenceRate * 100).toStringAsFixed(1)}%',
          'frequência'
        ],
      ],
    AcademicReportKind.schedule => [
        ['${classes.length}', 'turmas'],
        ['$scheduleCount', 'aulas semanais'],
        [
          '${classes.map((item) => item.discipline).toSet().length}',
          'disciplinas'
        ],
      ],
    AcademicReportKind.roster => [
        ['${classes.length}', 'turmas'],
        ['${students.length}', 'alunos'],
      ],
    AcademicReportKind.disciplines => [
        ['${disciplines.length}', 'disciplinas'],
        ['${disciplines.where((item) => item.active).length}', 'ativas'],
        ['${disciplines.where((item) => !item.active).length}', 'encerradas'],
      ],
    AcademicReportKind.consolidated => const <List<String>>[],
  };
  return _metricsSummary(metrics);
}

pw.Widget _metricsSummary(List<List<String>> metrics) => pw.Container(
      padding: const pw.EdgeInsets.all(14),
      decoration: pw.BoxDecoration(
        color: _accentLight,
        border: pw.Border.all(color: _rule),
        borderRadius: const pw.BorderRadius.all(pw.Radius.circular(5)),
      ),
      child: pw.Row(
        mainAxisAlignment: pw.MainAxisAlignment.spaceAround,
        children: metrics.map((item) => _metric(item[0], item[1])).toList(),
      ),
    );

pw.Widget _metric(String value, String label) => pw.Column(
      children: [
        pw.Text(
          value,
          style: pw.TextStyle(
            color: _accent,
            fontSize: 16,
            fontWeight: pw.FontWeight.bold,
          ),
        ),
        pw.Text(label, style: const pw.TextStyle(color: _muted, fontSize: 8)),
      ],
    );

Iterable<pw.Widget> _attendanceSection(AttendanceSession session) sync* {
  final rate = (session.presenceRate * 100).toStringAsFixed(1);
  yield pw.Container(
    margin: const pw.EdgeInsets.only(bottom: 5, top: 8),
    child: pw.Text(
      '${session.attendanceDate} | ${session.classLabel} | '
      '${session.discipline} | ${session.presentCount}/${session.expectedCount} ($rate%)',
      style: pw.TextStyle(
        color: _ink,
        fontSize: 10,
        fontWeight: pw.FontWeight.bold,
      ),
    ),
  );
  final includeClass = session.classCount > 1;
  final present = session.records
      .map((record) => [
            record.enrollment,
            record.studentName,
            if (includeClass) record.classLabel,
            'Presente'
          ])
      .toList();
  final absent = session.absentStudents
      .map((student) => [
            student.enrollment,
            student.studentName,
            if (includeClass) student.classLabel,
            'Ausente'
          ])
      .toList();
  yield _table(
    headers: [
      'Matrícula',
      'Aluno',
      if (includeClass) 'Turma',
      'Situação',
    ],
    rows: [...present, ...absent],
  );
}

pw.Widget _rosterSection(ClassGroup group, List<Student> students) {
  students.sort((a, b) => a.name.compareTo(b.name));
  return pw.Container(
    margin: const pw.EdgeInsets.only(top: 9),
    child: pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.Text(
          '${group.label} | ${group.discipline} | ${group.semester}',
          style: pw.TextStyle(
            color: _ink,
            fontSize: 10,
            fontWeight: pw.FontWeight.bold,
          ),
        ),
        pw.SizedBox(height: 4),
        if (students.isEmpty)
          _empty('Turma sem alunos.')
        else
          _table(
            headers: const ['Matrícula', 'Aluno'],
            rows: students
                .map((student) => [student.externalId ?? '', student.name])
                .toList(),
          ),
      ],
    ),
  );
}

pw.Widget _heading(String text) => pw.Container(
      margin: const pw.EdgeInsets.only(bottom: 7),
      child: pw.Text(
        text.toUpperCase(),
        style: pw.TextStyle(
          color: _accent,
          fontSize: 11,
          letterSpacing: 1.3,
          fontWeight: pw.FontWeight.bold,
        ),
      ),
    );

pw.Widget _empty(String text) => pw.Text(
      text,
      style: const pw.TextStyle(color: _muted, fontSize: 9),
    );

pw.Widget _table({
  required List<String> headers,
  required List<List<String>> rows,
}) =>
    pw.TableHelper.fromTextArray(
      headers: headers,
      data: rows,
      border: pw.TableBorder.all(color: _rule, width: .6),
      headerDecoration: const pw.BoxDecoration(color: _accentLight),
      headerStyle: pw.TextStyle(
        color: _accent,
        fontSize: 8,
        fontWeight: pw.FontWeight.bold,
      ),
      cellStyle: const pw.TextStyle(color: _ink, fontSize: 8),
      cellPadding: const pw.EdgeInsets.symmetric(horizontal: 5, vertical: 4),
    );

String _periodLabel(AttendanceReport attendance) {
  if (attendance.dateFrom == null && attendance.dateTo == null) {
    return 'Todos os registros disponíveis';
  }
  return 'Período: ${attendance.dateFrom ?? "início"} a '
      '${attendance.dateTo ?? "hoje"}';
}

String _formatDate(DateTime value) {
  final local = value.toLocal();
  final day = local.day.toString().padLeft(2, '0');
  final month = local.month.toString().padLeft(2, '0');
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$day/$month/${local.year} $hour:$minute';
}

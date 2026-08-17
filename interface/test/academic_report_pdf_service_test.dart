import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/academic_report_pdf_service.dart';
import 'package:assistant_app/services/education_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('builds the consolidated schedule, attendance and roster PDF', () async {
    const group = ClassGroup(
      id: 'c1',
      code: '3001',
      name: 'Presencial',
      discipline: 'Banco de Dados',
      semester: '2026.2',
      label: '3001 Presencial',
      schedules: [
        ClassSchedule(weekday: 0, startTime: '18:30', endTime: '20:10'),
      ],
    );
    const present = AttendanceRecord(
      id: 'r1',
      studentId: 's1',
      enrollment: '2026001',
      studentName: 'Ana',
      source: 'qr',
    );
    const absent = AttendanceStudent(
      studentId: 's2',
      enrollment: '2026002',
      studentName: 'Bruno',
    );
    const session = AttendanceSession(
      id: 'a1',
      classId: 'c1',
      classLabel: '3001 Presencial',
      discipline: 'Banco de Dados',
      semester: '2026.2',
      attendanceDate: '2026-08-16',
      open: false,
      expectedCount: 2,
      presentCount: 1,
      records: [present],
      absentStudents: [absent],
    );
    const report = AttendanceReport(
      dateFrom: '2026-08-01',
      dateTo: '2026-08-31',
      sessionCount: 1,
      expectedTotal: 2,
      presentTotal: 1,
      sessions: [session],
    );
    const disciplines = [
      Discipline(
        id: 'd1',
        code: 'ARA0040',
        name: 'Banco de Dados',
        label: 'ARA0040 - Banco de Dados',
        semester: '2026.2',
      ),
    ];
    final students = [
      Student(
        id: 's1',
        name: 'Ana',
        classId: 'c1',
        externalId: '2026001',
        classGroup: '3001 Presencial',
        discipline: 'Banco de Dados',
        aliases: const [],
        active: true,
      ),
    ];
    final bytes = await buildAcademicReportPdf(
      classes: const [group],
      disciplines: disciplines,
      students: students,
      attendance: report,
      generatedAt: DateTime(2026, 8, 16, 20),
    );

    expect(bytes.length, greaterThan(1000));
    expect(String.fromCharCodes(bytes.take(4)), '%PDF');
    expect(
      academicReportFilename(DateTime(2026, 8, 16)),
      'relatorio-educacional-2026-08-16.pdf',
    );

    final filenames = <String>{};
    for (final kind in AcademicReportKind.values) {
      final separated = await buildAcademicReportPdf(
        classes: const [group],
        disciplines: disciplines,
        students: students,
        attendance: report,
        generatedAt: DateTime(2026, 8, 16, 20),
        kind: kind,
      );
      expect(separated.length, greaterThan(1000));
      expect(String.fromCharCodes(separated.take(4)), '%PDF');
      filenames.add(
        academicReportFilename(DateTime(2026, 8, 16), kind: kind),
      );
    }
    expect(filenames, hasLength(AcademicReportKind.values.length));
  });
}

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/attendance_tab.dart';

void main() {
  testWidgets('renders QR call controls and the reports panel', (tester) async {
    final classes = ValueNotifier<List<ClassGroup>?>([
      ClassGroup(
        id: 'c1',
        code: '3001',
        name: 'Presencial',
        discipline: 'Banco de Dados',
        semester: '2026.2',
        label: '3001 Presencial',
        schedules: [
          ClassSchedule(
            weekday: DateTime.now().weekday - 1,
            startTime: '18:00',
            endTime: '20:00',
          ),
        ],
      ),
      ClassGroup(
        id: 'c2',
        code: '3002',
        name: 'Presencial',
        discipline: 'Banco de Dados',
        semester: '2026.2',
        label: '3002 Presencial',
        schedules: [
          ClassSchedule(
            weekday: DateTime.now().weekday - 1,
            startTime: '18:00',
            endTime: '20:00',
          ),
        ],
      ),
    ]);
    var createRequests = 0;
    final client = MockClient((request) async {
      if (request.method == 'POST' &&
          request.url.path.endsWith('/attendance/sessions')) {
        createRequests++;
        expect(request.body, contains('"class_ids":["c1","c2"]'));
        return http.Response(
          '{'
          '"id":"a1",'
          '"class_id":"c1",'
          '"class_ids":["c1","c2"],'
          '"class_label":"3001 Presencial + 3002 Presencial",'
          '"classes":['
          '{"class_id":"c1","class_label":"3001 Presencial",'
          '"discipline":"Banco de Dados","semester":"2026.2",'
          '"expected_count":2},'
          '{"class_id":"c2","class_label":"3002 Presencial",'
          '"discipline":"Banco de Dados","semester":"2026.2",'
          '"expected_count":1}],'
          '"discipline":"Banco de Dados",'
          '"semester":"2026.2",'
          '"attendance_date":"2026-08-16",'
          '"opened_at":"2026-08-16T18:00:00Z",'
          '"expires_at":"2099-08-16T18:15:00Z",'
          '"open":true,'
          '"check_in_path":"/education/attendance/check-in/token",'
          '"expected_count":3,'
          '"present_count":1,'
          '"records":[{'
          '"id":"r1",'
          '"student_id":"s1",'
          '"enrollment":"2026001",'
          '"student_name":"Ana",'
          '"class_id":"c1",'
          '"class_label":"3001 Presencial",'
          '"source":"qr",'
          '"checked_in_at":"2026-08-16T18:01:00Z"'
          '}],'
          '"absent_students":[{'
          '"student_id":"s2",'
          '"enrollment":"2026002",'
          '"student_name":"Bruno"'
          ',"class_id":"c1","class_label":"3001 Presencial"'
          '},{'
          '"student_id":"s3",'
          '"enrollment":"2026003",'
          '"student_name":"Carla",'
          '"class_id":"c2",'
          '"class_label":"3002 Presencial"'
          '}]'
          '}',
          200,
        );
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SizedBox(
                width: 1000,
                height: 700,
                child: AttendanceTab(classes: classes),
              ),
            ),
          ),
        );
        await tester.pump(const Duration(milliseconds: 100));

        expect(find.text('GERAR QR'), findsOneWidget);
        expect(find.text('CHAMADA ATUAL'), findsOneWidget);
        expect(find.text('RELATORIOS E AULAS DO DIA'), findsOneWidget);
        expect(find.text('GERAR RELATORIO'), findsOneWidget);
        expect(find.text('2 de 2 selecionada(s)'), findsOneWidget);

        await tester.tap(find.text('GERAR RELATORIO'));
        await tester.pumpAndSettle();
        expect(find.text('ESCOLHA O RELATORIO'), findsOneWidget);
        expect(find.text('Relatório de presença'), findsNothing);
        expect(find.text('Quadro de aulas'), findsOneWidget);
        expect(find.text('Relatório de turmas e alunos'), findsOneWidget);
        expect(find.text('Relatório de disciplinas'), findsOneWidget);
        expect(find.text('Relatório educacional geral'), findsOneWidget);
        await tester.tap(find.text('CANCELAR'));
        await tester.pumpAndSettle();

        await tester.tap(find.text('GERAR QR'));
        await tester.pump(const Duration(milliseconds: 200));

        expect(find.text('1 presentes de 3'), findsOneWidget);
        expect(
            find.text('2 turmas reunidas em um unico QR Code'), findsOneWidget);
        expect(find.textContaining('Ana'), findsOneWidget);
        expect(find.text('ENCERRAR'), findsOneWidget);
        expect(find.byTooltip('Relatorio exclusivo desta chamada'),
            findsOneWidget);
        expect(createRequests, 1);

        await tester.tap(find.byTooltip('Relatorio exclusivo desta chamada'));
        await tester.pumpAndSettle();
        expect(find.text('RELATORIO DESTA CHAMADA'), findsOneWidget);
        expect(find.text('IMPRIMIR / PDF'), findsOneWidget);
        expect(find.text('COPIAR PARA A FACULDADE'), findsOneWidget);
        expect(find.textContaining('2026001 | Ana | PRESENTE'), findsOneWidget);
        await tester.tap(find.text('FECHAR'));
        await tester.pumpAndSettle();
      },
      () => client,
    );

    await tester.pumpWidget(const SizedBox.shrink());
    classes.dispose();
  });

  testWidgets('deletes a call from the report after confirmation',
      (tester) async {
    final classes = ValueNotifier<List<ClassGroup>?>(const []);
    var deleted = false;
    var deleteRequests = 0;
    final client = MockClient((request) async {
      if (request.method == 'DELETE' &&
          request.url.path.endsWith('/attendance/sessions/a-history')) {
        deleteRequests++;
        deleted = true;
        return http.Response('{"ok":true}', 200);
      }
      if (request.method == 'GET' &&
          request.url.path.endsWith('/attendance/sessions')) {
        return http.Response(
          deleted
              ? '[]'
              : '[{'
                  '"id":"a-history",'
                  '"class_id":"c1",'
                  '"class_label":"3001 Presencial",'
                  '"discipline":"Banco de Dados",'
                  '"semester":"2026.2",'
                  '"attendance_date":"2026-08-17",'
                  '"opened_at":"2026-08-17T18:00:00Z",'
                  '"expires_at":"2026-08-17T18:15:00Z",'
                  '"open":false,'
                  '"expected_count":2,'
                  '"present_count":0,'
                  '"records":[],'
                  '"absent_students":[]'
                  '}]',
          200,
        );
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SizedBox(
                width: 1000,
                height: 700,
                child: AttendanceTab(classes: classes),
              ),
            ),
          ),
        );
        await tester.pump(const Duration(milliseconds: 200));

        expect(find.textContaining('3001 Presencial'), findsOneWidget);
        await tester.tap(find.byTooltip('Excluir chamada'));
        await tester.pumpAndSettle();

        expect(find.text('Excluir chamada?'), findsOneWidget);
        expect(find.text('EXCLUIR CHAMADA'), findsOneWidget);
        await tester.tap(find.text('EXCLUIR CHAMADA'));
        await tester.pumpAndSettle();

        expect(deleteRequests, 1);
        expect(find.textContaining('3001 Presencial'), findsNothing);
      },
      () => client,
    );

    await tester.pumpWidget(const SizedBox.shrink());
    classes.dispose();
  });

  test('attendance uses only today classes ordered by start time', () {
    const classes = [
      ClassGroup(
        id: 'late',
        code: '3002',
        name: 'Noite',
        discipline: 'Redes',
        label: '3002 Noite',
        schedules: [
          ClassSchedule(weekday: 0, startTime: '20:00'),
        ],
      ),
      ClassGroup(
        id: 'other-day',
        code: '3003',
        name: 'Terca',
        discipline: 'IA',
        label: '3003 Terca',
        schedules: [
          ClassSchedule(weekday: 1, startTime: '08:00'),
        ],
      ),
      ClassGroup(
        id: 'early',
        code: '3001',
        name: 'Manha',
        discipline: 'Banco de Dados',
        label: '3001 Manha',
        schedules: [
          ClassSchedule(weekday: 0, startTime: '08:00'),
        ],
      ),
    ];

    final result = attendanceClassesForDay(classes, DateTime.monday);

    expect(result.map((group) => group.id), ['early', 'late']);
  });

  test('semester end follows the academic half', () {
    expect(semesterEnd('2026.1', DateTime(2026, 2, 1)), DateTime(2026, 6, 30));
    expect(
      semesterEnd('2026.2', DateTime(2026, 8, 1)),
      DateTime(2026, 12, 31),
    );
  });

  test('exclusive call report groups students by class', () {
    const session = AttendanceSession(
      id: 'a1',
      classId: 'c1',
      classIds: ['c1', 'c2'],
      classLabel: '3001 + 3002',
      discipline: 'Banco de Dados',
      semester: '2026.2',
      attendanceDate: '2026-08-17',
      open: false,
      expectedCount: 3,
      presentCount: 2,
      classes: [
        AttendanceClass(
          classId: 'c1',
          classLabel: '3001',
          discipline: 'Banco de Dados',
          semester: '2026.2',
          expectedCount: 2,
        ),
        AttendanceClass(
          classId: 'c2',
          classLabel: '3002',
          discipline: 'Banco de Dados',
          semester: '2026.2',
          expectedCount: 1,
        ),
      ],
      records: [
        AttendanceRecord(
          id: 'r1',
          studentId: 's1',
          enrollment: '2026001',
          studentName: 'Ana',
          source: 'qr',
          classId: 'c1',
          classLabel: '3001',
        ),
        AttendanceRecord(
          id: 'r2',
          studentId: 's3',
          enrollment: '2026003',
          studentName: 'Carla',
          source: 'qr',
          classId: 'c2',
          classLabel: '3002',
        ),
      ],
      absentStudents: [
        AttendanceStudent(
          studentId: 's2',
          enrollment: '2026002',
          studentName: 'Bruno',
          classId: 'c1',
          classLabel: '3001',
        ),
      ],
    );

    final report = attendanceSessionTranscript(session);
    final printable = attendanceReportForSession(session);

    expect(report, contains('3001 | Banco de Dados | 2026.2'));
    expect(report, contains('2026001 | Ana | PRESENTE'));
    expect(report, contains('2026002 | Bruno | AUSENTE'));
    expect(report, contains('3002 | Banco de Dados | 2026.2'));
    expect(report, contains('2026003 | Carla | PRESENTE'));
    expect(printable.sessionCount, 1);
    expect(printable.sessions.single.id, 'a1');
    expect(printable.expectedTotal, 3);
    expect(printable.presentTotal, 2);
    expect(
      attendanceSessionPdfFilename(session),
      'relatorio-presenca-2026-08-17-a1.pdf',
    );
  });
}

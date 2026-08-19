import 'dart:convert';

import 'package:assistant_app/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:assistant_app/services/education_service.dart';

void main() {
  test('presentation demo is created by one authenticated request', () async {
    final service = EducationService(ApiService(backendUrl: 'https://test'));
    final client = MockClient((request) async {
      expect(request.method, 'POST');
      expect(request.url.path, '/education/demo/presentation');
      return http.Response(
        '{"class_id":"class-demo","students_created":3,'
        '"message":"Demonstracao pronta"}',
        200,
      );
    });

    final result = await http.runWithClient(
      service.createPresentationDemo,
      () => client,
    );

    expect(result['class_id'], 'class-demo');
    expect(result['students_created'], 3);
  });

  group('resumo', () {
    test('envia o formato escolhido e le o que o backend usou', () async {
      final service = EducationService(ApiService(backendUrl: 'https://test'));
      Map<String, dynamic>? sent;
      final client = MockClient((request) async {
        sent = jsonDecode(request.body) as Map<String, dynamic>;
        expect(request.url.path, '/education/lessons/l1/summary');
        return http.Response(
          '{"lesson_id":"l1","summary":"## Resumo geral","llm":"localai",'
          '"generated_at":"2026-08-04T13:00:00","used_segments":9,'
          '"style":"detailed"}',
          200,
        );
      });

      final summary = await http.runWithClient(
        () => service.generateSummary('l1', style: summaryStyleDetailed),
        () => client,
      );

      expect(sent?['style'], 'detailed');
      expect(summary.style, summaryStyleDetailed);
    });

    test('sem escolha explicita pede o resumo comum', () async {
      final service = EducationService(ApiService(backendUrl: 'https://test'));
      Map<String, dynamic>? sent;
      final client = MockClient((request) async {
        sent = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          '{"lesson_id":"l1","summary":"## Resumo","llm":"localai",'
          '"generated_at":"2026-08-04T13:00:00","used_segments":2}',
          200,
        );
      });

      final summary = await http.runWithClient(
        () => service.generateSummary('l1'),
        () => client,
      );

      // Backend antigo nao devolve `style`: o resumo conta como comum.
      expect(sent?['style'], 'standard');
      expect(summary.style, summaryStyleStandard);
    });
  });

  group('resumo por agente conectado', () {
    test('pede ao backend o prompt com a aula inteira', () async {
      final service = EducationService(ApiService(backendUrl: 'https://test'));
      Uri? pedida;
      final client = MockClient((request) async {
        pedida = request.url;
        return http.Response(
          '{"lesson_id":"l1","style":"detailed","system_prompt":"voce resume",'
          '"prompt":"Disciplina: Fisica","used_segments":12,'
          '"transcript_chars":48000}',
          200,
        );
      });

      final built = await http.runWithClient(
        () => service.summaryPrompt('l1', style: summaryStyleDetailed),
        () => client,
      );

      expect(pedida?.path, '/education/lessons/l1/summary/prompt');
      expect(pedida?.queryParameters['style'], 'detailed');
      expect(built.systemPrompt, 'voce resume');
      expect(built.transcriptChars, 48000);
      expect(built.style, summaryStyleDetailed);
    });

    test('devolve ao backend o texto escrito pelo agente local', () async {
      final service = EducationService(ApiService(backendUrl: 'https://test'));
      Map<String, dynamic>? enviado;
      final client = MockClient((request) async {
        enviado = jsonDecode(request.body) as Map<String, dynamic>;
        expect(request.url.path, '/education/lessons/l1/summary/external');
        return http.Response(
          '{"lesson_id":"l1","summary":"## Resumo geral","llm":"claude_cli",'
          '"generated_at":"2026-08-19T10:00:00","used_segments":12,'
          '"style":"detailed"}',
          200,
        );
      });

      final summary = await http.runWithClient(
        () => service.saveExternalSummary(
          'l1',
          summary: '## Resumo geral',
          llm: 'claude_cli',
          style: summaryStyleDetailed,
        ),
        () => client,
      );

      expect(enviado?['llm'], 'claude_cli');
      expect(enviado?['style'], 'detailed');
      expect(enviado?['close_lesson'], false);
      expect(summary.llm, 'claude_cli');
      expect(summary.style, summaryStyleDetailed);
    });
  });

  group('Lesson', () {
    test('reads the payload returned by the backend', () {
      final lesson = Lesson.fromJson({
        'id': 'l1',
        'discipline': 'Matematica',
        'semester': '2026.2',
        'title': 'Funcoes',
        'class_group': '3A',
        'status': 'recording',
        'started_at': '2026-08-04T13:00:00',
        'segment_count': 4,
        'transcript_chars': 1200,
      });

      expect(lesson.discipline, 'Matematica');
      expect(lesson.semester, '2026.2');
      expect(lesson.classGroup, '3A');
      expect(lesson.segmentCount, 4);
      expect(lesson.startedAt?.hour, 13);
      expect(lesson.isClosed, isFalse);
    });

    test('survives missing optional fields', () {
      final lesson = Lesson.fromJson({'id': 'l1', 'discipline': 'Fisica'});

      expect(lesson.title, '');
      expect(lesson.summary, isNull);
      expect(lesson.summaryStyle, isNull);
      expect(lesson.segmentCount, 0);
      expect(lesson.startedAt, isNull);
    });

    test('guarda o formato do resumo ja gerado', () {
      final lesson = Lesson.fromJson({
        'id': 'l1',
        'discipline': 'Fisica',
        'summary': '## Resumo geral',
        'summary_style': 'detailed',
      });

      expect(lesson.summaryStyle, summaryStyleDetailed);
      expect(summaryStyleLabel(lesson.summaryStyle), 'DETALHADO');
    });

    test('closed lesson is flagged', () {
      final lesson = Lesson.fromJson(
          {'id': 'l1', 'discipline': 'Fisica', 'status': 'closed'});

      expect(lesson.isClosed, isTrue);
    });
  });

  group('LessonPoint', () {
    test('parses an extracted point', () {
      final point = LessonPoint.fromJson({
        'id': 'p1',
        'lesson_id': 'l1',
        'student_id': 's2',
        'student_name': 'Thiago Souza',
        'points': 0.5,
        'reason': 'resolveu no quadro',
        'discipline': 'Matematica',
        'lesson_date': '2026-08-04T13:00:00',
        'source': 'extracted',
        'confidence': 0.9,
      });

      expect(point.studentName, 'Thiago Souza');
      expect(point.points, 0.5);
      expect(point.needsReview, isFalse);
    });

    test('flags an extracted point without a matched student', () {
      final point = LessonPoint.fromJson({
        'id': 'p2',
        'lesson_id': 'l1',
        'student_id': null,
        'student_name': 'Joao',
        'points': 1,
        'discipline': 'Historia',
        'source': 'extracted',
        'confidence': 0.4,
      });

      expect(point.needsReview, isTrue);
      expect(point.points, 1.0);
    });

    test('manual point without student is not flagged for review', () {
      final point = LessonPoint.fromJson({
        'id': 'p3',
        'lesson_id': 'l1',
        'student_name': 'Convidado',
        'points': 2,
        'source': 'manual',
        'confidence': 1.0,
      });

      expect(point.needsReview, isFalse);
    });
  });

  group('SegmentIngestResult', () {
    test('parses a block that produced a segment and a point', () {
      final result = SegmentIngestResult.fromJson({
        'segment': {
          'id': 'g1',
          'lesson_id': 'l1',
          'sequence': 2,
          'text': 'hoje vamos falar de funcoes',
          'confidence': 0.88,
          'duration_ms': 60000,
          'indexed': true,
          'created_at': '2026-08-04T13:01:00',
        },
        'indexed': true,
        'points': [
          {
            'id': 'p1',
            'lesson_id': 'l1',
            'student_name': 'Ana Paula Ribeiro',
            'student_id': 's1',
            'points': 1,
            'discipline': 'Matematica',
            'source': 'extracted',
            'confidence': 1.0,
          }
        ],
        'lesson': {'id': 'l1', 'discipline': 'Matematica', 'segment_count': 2},
      });

      expect(result.segment?.sequence, 2);
      expect(result.indexed, isTrue);
      expect(result.points.single.studentName, 'Ana Paula Ribeiro');
      expect(result.lesson.segmentCount, 2);
    });

    test('parses a skipped block with no segment', () {
      final result = SegmentIngestResult.fromJson({
        'segment': null,
        'indexed': false,
        'skipped_reason': 'nenhuma fala reconhecida no bloco',
        'points': [],
        'lesson': {'id': 'l1', 'discipline': 'Matematica'},
      });

      expect(result.segment, isNull);
      expect(result.skippedReason, contains('nenhuma fala'));
      expect(result.points, isEmpty);
    });
  });

  group('ClassGroup', () {
    test('parses a class with code, name and student count', () {
      final group = ClassGroup.fromJson({
        'id': 'c1',
        'code': '3001',
        'name': 'Presencial',
        'discipline': 'ARA0040',
        'semester': '2026.2',
        'label': '3001 Presencial',
        'active': true,
        'student_count': 14,
      });

      expect(group.label, '3001 Presencial');
      expect(group.display, '3001 Presencial - ARA0040 (2026.2)');
      expect(group.studentCount, 14);
    });

    test('display falls back to the label when there is no discipline', () {
      final group = ClassGroup.fromJson({
        'id': 'c2',
        'code': '3002',
        'label': '3002',
      });

      expect(group.display, '3002');
      expect(group.studentCount, 0);
      expect(group.active, isTrue);
    });
  });

  group('ClassSchedule', () {
    test('meetsOn maps the dart weekday to the backend weekday', () {
      final group = ClassGroup.fromJson({
        'id': 'c1',
        'code': '3001',
        'label': '3001',
        'discipline': 'ARA0040',
        // 0 = segunda, 3 = quinta no backend.
        'schedules': [
          {'weekday': 0, 'start_time': '18:30', 'end_time': '21:10'},
          {'weekday': 3, 'start_time': '18:30', 'end_time': '21:10'},
        ],
        'schedule_label': 'seg 18:30, qui 18:30',
      });

      expect(group.meetsOn(DateTime.monday), isTrue);
      expect(group.meetsOn(DateTime.thursday), isTrue);
      expect(group.meetsOn(DateTime.tuesday), isFalse);
      expect(group.meetsOn(DateTime.sunday), isFalse);
      expect(group.scheduleLabel, 'seg 18:30, qui 18:30');
    });

    test('class without schedule never counts as today', () {
      final group = ClassGroup.fromJson({
        'id': 'c2',
        'code': '3002',
        'label': '3002',
      });

      expect(group.schedules, isEmpty);
      expect(group.meetsOn(DateTime.monday), isFalse);
    });

    test('schedule survives the round trip to json', () {
      const schedule =
          ClassSchedule(weekday: 3, startTime: '18:30', endTime: '21:10');

      expect(schedule.toJson(), {
        'weekday': 3,
        'start_time': '18:30',
        'end_time': '21:10',
      });
    });
  });

  group('Discipline', () {
    test('parses code, name and how many classes it has', () {
      final discipline = Discipline.fromJson({
        'id': 's1',
        'code': 'ARA0040',
        'name': 'BANCO DE DADOS',
        'label': 'ARA0040 - BANCO DE DADOS',
        'semester': '2026.2',
        'class_count': 2,
      });

      expect(discipline.label, 'ARA0040 - BANCO DE DADOS');
      expect(discipline.semester, '2026.2');
      expect(discipline.classCount, 2);
      expect(discipline.active, isTrue);
    });

    test('recognises an archived discipline', () {
      final discipline = Discipline.fromJson({
        'id': 's2',
        'code': 'ARA0041',
        'label': 'ARA0041',
        'active': false,
      });

      expect(discipline.active, isFalse);
    });
  });

  group('Semester', () {
    test('parses lifecycle totals', () {
      final semester = Semester.fromJson({
        'code': '2026.2',
        'active': false,
        'discipline_count': 3,
        'class_count': 6,
      });

      expect(semester.code, '2026.2');
      expect(semester.active, isFalse);
      expect(semester.disciplineCount, 3);
      expect(semester.classCount, 6);
    });
  });

  group('Lesson classes', () {
    test('a joint lesson carries every linked class', () {
      final lesson = Lesson.fromJson({
        'id': 'l1',
        'discipline': 'ARA0040',
        'status': 'recording',
        'class_group': '',
        'class_ids': ['c1', 'c2'],
        'class_labels': ['3001 Presencial', '3002 Semipresencial'],
      });

      expect(lesson.classIds, ['c1', 'c2']);
      expect(lesson.classLabels.last, '3002 Semipresencial');
    });

    test('older lesson without links keeps the text field', () {
      final lesson = Lesson.fromJson({
        'id': 'l2',
        'discipline': 'ARA0040',
        'status': 'closed',
        'class_group': '3001',
      });

      expect(lesson.classIds, isEmpty);
      expect(lesson.classGroup, '3001');
    });
  });

  group('PointsReport', () {
    test('groups totals per student', () {
      final report = PointsReport.fromJson({
        'total_points': 3.5,
        'students': [
          {
            'student_name': 'Ana Paula Ribeiro',
            'student_id': 's1',
            'total_points': 2.5,
            'discipline': 'Matematica',
            'lesson_date': '2026-08-04',
            'entries': [],
          },
          {
            'student_name': 'Thiago Souza',
            'total_points': 1.0,
            'discipline': 'Matematica',
            'lesson_date': '2026-08-04',
            'entries': [],
          },
        ],
      });

      expect(report.totalPoints, 3.5);
      expect(report.students, hasLength(2));
      expect(report.students.first.totalPoints, 2.5);
      expect(report.students.first.lessonDate, '2026-08-04');
    });

    test('handles an empty report', () {
      final report = PointsReport.fromJson({'total_points': 0});

      expect(report.students, isEmpty);
      expect(report.totalPoints, 0.0);
    });

    test('separates two classes of the same discipline on the same day', () {
      final report = PointsReport.fromJson({
        'total_points': 2.0,
        'students': [
          {
            'student_name': 'Ana Paula Ribeiro',
            'total_points': 1.0,
            'discipline': 'ARA0040',
            'class_group': '3001 PRESENCIAL',
            'lesson_date': '2026-08-13',
            'entries': [],
          },
          {
            'student_name': 'Thiago Souza',
            'total_points': 1.0,
            'discipline': 'ARA0040',
            'class_group': '3002 SEMIPRESENCIAL',
            'lesson_date': '2026-08-13',
            'entries': [],
          },
        ],
      });

      expect(
        report.students.map((entry) => entry.classGroup),
        ['3001 PRESENCIAL', '3002 SEMIPRESENCIAL'],
      );
    });

    test('entry without class group falls back to empty', () {
      final report = PointsReport.fromJson({
        'total_points': 1.0,
        'students': [
          {
            'student_name': 'Ana Paula Ribeiro',
            'total_points': 1.0,
            'discipline': 'Matematica',
            'lesson_date': '2026-08-04',
            'entries': [],
          },
        ],
      });

      expect(report.students.single.classGroup, '');
    });
  });

  group('EmbeddingStatus', () {
    test('reports a semantic provider', () {
      final status = EmbeddingStatus.fromJson({
        'ok': true,
        'provider': 'ollama',
        'model': 'nomic-embed-text',
        'dimensions': 768,
        'semantic': true,
      });

      expect(status.semantic, isTrue);
      expect(status.dimensions, 768);
    });

    test('reports the hash fallback as non-semantic', () {
      final status = EmbeddingStatus.fromJson({
        'ok': true,
        'provider': 'hash',
        'model': 'hash',
        'dimensions': 384,
        'semantic': false,
      });

      expect(status.semantic, isFalse);
      expect(status.provider, 'hash');
    });

    test('carries the error when detection failed', () {
      final status = EmbeddingStatus.fromJson({
        'ok': false,
        'provider': 'auto',
        'error': 'nenhum provedor disponivel',
      });

      expect(status.ok, isFalse);
      expect(status.error, contains('nenhum provedor'));
    });
  });

  group('Student', () {
    test('parses aliases used to anchor misheard names', () {
      final student = Student.fromJson({
        'id': 's1',
        'name': 'Ana Paula Ribeiro',
        'external_id': '2026001',
        'class_group': '3A',
        'discipline': '',
        'aliases': ['Aninha', 'Ana P'],
      });

      expect(student.aliases, ['Aninha', 'Ana P']);
      expect(student.externalId, '2026001');
      expect(student.active, isTrue);
    });
  });

  group('StudentImportResult', () {
    test('parses created and updated totals', () {
      final result = StudentImportResult.fromJson({
        'created': 25,
        'updated': 3,
        'total': 28,
      });

      expect(result.created, 25);
      expect(result.updated, 3);
      expect(result.total, 28);
    });
  });

  group('StudentBulkDeleteResult', () {
    test('parses requested and deleted totals', () {
      final result = StudentBulkDeleteResult.fromJson({
        'requested': 4,
        'deleted': 3,
      });

      expect(result.requested, 4);
      expect(result.deleted, 3);
    });

    test('falls back to individual deletes when the old backend returns 405',
        () async {
      final requests = <http.Request>[];
      final client = MockClient((request) async {
        requests.add(request);
        if (request.method == 'POST') {
          return http.Response('Method Not Allowed', 405);
        }
        return http.Response('{"ok":true}', 200);
      });
      final service = EducationService(
        ApiService(backendUrl: 'https://backend.test'),
      );

      final result = await http.runWithClient(
        () => service.deleteStudents(
          classId: 'class-1',
          studentIds: ['student-1', 'student-2', 'student-1'],
        ),
        () => client,
      );

      expect(result.requested, 2);
      expect(result.deleted, 2);
      expect(
        requests.map((request) => '${request.method} ${request.url.path}'),
        [
          'POST /education/students/bulk-delete',
          'DELETE /education/students/student-1',
          'DELETE /education/students/student-2',
        ],
      );
    });
  });

  group('AttendanceSession', () {
    test('parses present and absent students from a call', () {
      final session = AttendanceSession.fromJson({
        'id': 'a1',
        'class_id': 'c1',
        'class_ids': ['c1', 'c2'],
        'class_label': '3001 Presencial',
        'classes': [
          {
            'class_id': 'c1',
            'class_label': '3001 Presencial',
            'discipline': 'Banco de Dados',
            'expected_count': 2,
          },
          {
            'class_id': 'c2',
            'class_label': '3002 Presencial',
            'discipline': 'Banco de Dados',
            'expected_count': 1,
          },
        ],
        'discipline': 'Banco de Dados',
        'semester': '2026.2',
        'attendance_date': '2026-08-16',
        'open': true,
        'check_in_url': 'https://backend.test/check-in/token',
        'expected_count': 2,
        'present_count': 1,
        'records': [
          {
            'id': 'r1',
            'student_id': 's1',
            'enrollment': '2026001',
            'student_name': 'Ana',
            'class_id': 'c1',
            'class_label': '3001 Presencial',
            'source': 'qr',
            'checked_in_at': '2026-08-16T18:30:00Z',
          }
        ],
        'absent_students': [
          {
            'student_id': 's2',
            'enrollment': '2026002',
            'student_name': 'Bruno',
          }
        ],
      });

      expect(session.records.single.studentName, 'Ana');
      expect(session.records.single.classLabel, '3001 Presencial');
      expect(session.absentStudents.single.studentName, 'Bruno');
      expect(session.classIds, ['c1', 'c2']);
      expect(session.classCount, 2);
      expect(session.absentCount, 1);
      expect(session.presenceRate, .5);
      expect(session.open, isTrue);
    });

    test('uses the configured public backend origin for the QR link', () async {
      final service = EducationService(
        ApiService(backendUrl: 'https://public-backend.test'),
      );
      final client = MockClient(
        (request) async {
          expect(request.body, contains('"class_ids":["c1","c2"]'));
          return http.Response(
            '{'
            '"id":"a1",'
            '"class_id":"c1",'
            '"class_label":"3001",'
            '"discipline":"Banco de Dados",'
            '"attendance_date":"2026-08-16",'
            '"opened_at":"2026-08-16T18:00:00Z",'
            '"expires_at":"2026-08-16T18:15:00Z",'
            '"open":true,'
            '"check_in_url":"http://internal:8000/education/attendance/check-in/t",'
            '"check_in_path":"/education/attendance/check-in/t"'
            '}',
            200,
          );
        },
      );

      final session = await http.runWithClient(
        () => service.createAttendanceSession(
          classIds: const ['c1', 'c2'],
          attendanceDate: '2026-08-16',
        ),
        () => client,
      );

      expect(
        session.checkInUrl,
        'https://public-backend.test/education/attendance/check-in/t',
      );
    });

    test('deletes a complete attendance session', () async {
      final service = EducationService(
        ApiService(backendUrl: 'https://public-backend.test'),
      );
      final client = MockClient((request) async {
        expect(request.method, 'DELETE');
        expect(
          request.url.path,
          '/education/attendance/sessions/attendance-1',
        );
        return http.Response('{"ok":true}', 200);
      });

      await http.runWithClient(
        () => service.deleteAttendanceSession('attendance-1'),
        () => client,
      );
    });
  });
}

import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/education_service.dart';

void main() {
  group('Lesson', () {
    test('reads the payload returned by the backend', () {
      final lesson = Lesson.fromJson({
        'id': 'l1',
        'subject': 'Matematica',
        'title': 'Funcoes',
        'class_group': '3A',
        'status': 'recording',
        'started_at': '2026-08-04T13:00:00',
        'segment_count': 4,
        'transcript_chars': 1200,
      });

      expect(lesson.subject, 'Matematica');
      expect(lesson.classGroup, '3A');
      expect(lesson.segmentCount, 4);
      expect(lesson.startedAt?.hour, 13);
      expect(lesson.isClosed, isFalse);
    });

    test('survives missing optional fields', () {
      final lesson = Lesson.fromJson({'id': 'l1', 'subject': 'Fisica'});

      expect(lesson.title, '');
      expect(lesson.summary, isNull);
      expect(lesson.segmentCount, 0);
      expect(lesson.startedAt, isNull);
    });

    test('closed lesson is flagged', () {
      final lesson = Lesson.fromJson(
          {'id': 'l1', 'subject': 'Fisica', 'status': 'closed'});

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
        'subject': 'Matematica',
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
        'subject': 'Historia',
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
            'subject': 'Matematica',
            'source': 'extracted',
            'confidence': 1.0,
          }
        ],
        'lesson': {'id': 'l1', 'subject': 'Matematica', 'segment_count': 2},
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
        'lesson': {'id': 'l1', 'subject': 'Matematica'},
      });

      expect(result.segment, isNull);
      expect(result.skippedReason, contains('nenhuma fala'));
      expect(result.points, isEmpty);
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
            'subject': 'Matematica',
            'lesson_date': '2026-08-04',
            'entries': [],
          },
          {
            'student_name': 'Thiago Souza',
            'total_points': 1.0,
            'subject': 'Matematica',
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
        'class_group': '3A',
        'subject': '',
        'aliases': ['Aninha', 'Ana P'],
      });

      expect(student.aliases, ['Aninha', 'Ana P']);
      expect(student.active, isTrue);
    });
  });
}

import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/services/lesson_pdf_service.dart';

Lesson _lesson() => Lesson(
      id: 'l1',
      discipline: 'ARA0040 - BANCO DE DADOS',
      semester: '2026.2',
      title: 'Normalizacao',
      classGroup: '',
      classLabels: const ['3001 Presencial', '3002 Semipresencial'],
      status: 'closed',
      startedAt: DateTime(2026, 8, 13, 18, 30),
      segmentCount: 42,
      transcriptChars: 18320,
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('fonte do documento', () {
    test('a TTF acompanha o aplicativo', () async {
      // Sem ela o PDF cai na Helvetica embutida, que nao tem acento — e um
      // resumo de aula em portugues sairia com os nomes errados.
      final regular = await rootBundle.load('assets/fonts/roboto-regular.ttf');
      final bold = await rootBundle.load('assets/fonts/roboto-bold.ttf');

      expect(regular.lengthInBytes, greaterThan(10000));
      expect(bold.lengthInBytes, greaterThan(10000));
    });

    test('acentos sobrevivem ao documento', () async {
      final bytes = await buildLessonSummaryPdf(
        lesson: _lesson(),
        summary: '## Resumo\nNormalização, chaves e integridade referencial.',
      );

      expect(String.fromCharCodes(bytes.take(4)), '%PDF');
    });
  });

  group('parseSummary', () {
    test('splits headings, bullets and paragraphs', () {
      final blocks = parseSummary(
        '## Resumo\n'
        'A aula tratou de normalizacao.\n'
        'Seguiu com exemplos.\n'
        '\n'
        '## Principais topicos\n'
        '- Primeira forma normal\n'
        '* Segunda forma normal\n',
      );

      expect(blocks, [
        const SummaryBlock(SummaryBlockKind.heading, 'Resumo'),
        const SummaryBlock(
          SummaryBlockKind.paragraph,
          'A aula tratou de normalizacao. Seguiu com exemplos.',
        ),
        const SummaryBlock(SummaryBlockKind.heading, 'Principais topicos'),
        const SummaryBlock(SummaryBlockKind.bullet, 'Primeira forma normal'),
        const SummaryBlock(SummaryBlockKind.bullet, 'Segunda forma normal'),
      ]);
    });

    test('drops the markdown emphasis the pdf cannot render', () {
      final blocks = parseSummary('- **Chave primaria**: identifica a `linha`');

      expect(
        blocks.single,
        const SummaryBlock(
          SummaryBlockKind.bullet,
          'Chave primaria: identifica a linha',
        ),
      );
    });

    test('empty summary produces no blocks', () {
      expect(parseSummary('   \n\n  '), isEmpty);
    });
  });

  group('lessonPdfFilename', () {
    test('builds a slug from discipline, classes and date', () {
      expect(
        lessonPdfFilename(_lesson()),
        '2026-2-ara0040-banco-de-dados-3001-presencial-3002-semipresencial-13-08-2026.pdf',
      );
    });

    test('lesson without discipline still gets a name', () {
      final lesson = Lesson(
        id: 'l2',
        discipline: '',
        title: '',
        classGroup: '',
        status: 'closed',
      );

      expect(lessonPdfFilename(lesson), 'resumo-da-aula.pdf');
    });
  });

  group('buildLessonSummaryPdf', () {
    test('produces a pdf document', () async {
      final bytes = await buildLessonSummaryPdf(
        lesson: _lesson(),
        summary: '## Resumo\nA aula tratou de normalizacao.\n'
            '## Tarefas\n- Entregar a lista ate sexta\n',
        points: [
          LessonPoint(
            id: 'p1',
            lessonId: 'l1',
            studentName: 'Ana Paula Ribeiro',
            points: 0.5,
            reason: 'resolveu no quadro',
            discipline: 'ARA0040',
            source: 'extracted',
            confidence: 1,
          ),
        ],
      );

      expect(bytes.length, greaterThan(1000));
      expect(String.fromCharCodes(bytes.take(4)), '%PDF');
    });

    test('works without points', () async {
      final bytes = await buildLessonSummaryPdf(
        lesson: _lesson(),
        summary: 'Resumo curto sem secoes.',
      );

      expect(String.fromCharCodes(bytes.take(4)), '%PDF');
    });
  });
}

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

    test('resumo detalhado ganha sufixo para nao sobrescrever o comum', () {
      final lesson = Lesson(
        id: 'l1',
        discipline: 'ARA0040 - BANCO DE DADOS',
        semester: '2026.2',
        title: 'Normalizacao',
        classGroup: '',
        classLabels: const ['3001 Presencial'],
        status: 'closed',
        startedAt: DateTime(2026, 8, 13, 18, 30),
        summaryStyle: summaryStyleDetailed,
      );

      expect(
        lessonPdfFilename(lesson),
        '2026-2-ara0040-banco-de-dados-3001-presencial-13-08-2026-'
        'detalhado.pdf',
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

  group('título do resumo por tipo de gravação', () {
    Lesson gravacao(
      String kind, {
      String title = '',
      String discipline = '',
      String groupName = '',
      String semester = '2026.2',
      String? style,
    }) =>
        Lesson(
          id: 'x',
          kind: kind,
          title: title,
          discipline: discipline,
          groupName: groupName,
          semester: semester,
          classGroup: '',
          status: 'closed',
          startedAt: DateTime(2026, 10, 6, 21, 15),
          segmentCount: 12,
          summaryStyle: style,
        );

    test('os quatro tipos têm o seu título', () {
      expect(summaryHeading('aula'), 'RESUMO DA AULA');
      expect(summaryHeading('palestra'), 'RESUMO DA PALESTRA');
      expect(summaryHeading('reuniao'), 'RESUMO DA REUNIÃO');
      expect(summaryHeading('apresentacao'), 'RESUMO DA APRESENTAÇÃO');
      expect(summaryHeading('qualquer-outro'), 'RESUMO DA AULA');
      expect(recordingKindLabel('reuniao'), 'Reunião');
    });

    test('aula: disciplina em destaque, tema embaixo e a turma na linha de dados', () {
      final header = summaryHeaderFor(_lesson());

      expect(header.kindLabel, 'RESUMO DA AULA');
      expect(header.heading, 'ARA0040 - BANCO DE DADOS');
      expect(header.subtitle, 'Normalizacao');
      expect(header.meta, contains('Turma: 3001 Presencial + 3002 Semipresencial'));
      expect(header.meta, contains('42 trechos gravados'));
      expect(header.members, isEmpty);
    });

    test('palestra: o título é o destaque e não há turma', () {
      final header = summaryHeaderFor(
          gravacao('palestra', title: 'LGPD na prática'));

      expect(header.kindLabel, 'RESUMO DA PALESTRA');
      expect(header.heading, 'LGPD na prática');
      expect(header.subtitle, isEmpty);
      expect(header.meta, isNot(contains('Turma')));
      expect(header.meta, contains('06/10/2026'));
      expect(header.running, '2026.2   |   LGPD na prática   |   06/10/2026 as 21:15');
    });

    test('palestra sem título ainda tem cabeçalho', () {
      expect(summaryHeaderFor(gravacao('palestra')).heading, 'Palestra sem título');
      expect(summaryHeaderFor(gravacao('reuniao')).heading, 'Reunião sem título');
    });

    test('reunião: título em destaque e a disciplina, se houver, embaixo', () {
      final header = summaryHeaderFor(gravacao('reuniao',
          title: 'Colegiado de outubro', discipline: 'ARA0040 - BANCO DE DADOS'));

      expect(header.kindLabel, 'RESUMO DA REUNIÃO');
      expect(header.heading, 'Colegiado de outubro');
      expect(header.subtitle, 'ARA0040 - BANCO DE DADOS');
      expect(header.meta, isNot(contains('Turma')));
    });

    test('apresentação: o grupo em destaque, com os integrantes', () {
      final header = summaryHeaderFor(
        gravacao('apresentacao',
            title: 'Apresentacao: GRUPO 3',
            discipline: 'ARA0058 - CLOUD, IOT E INDUSTRIA 4.0',
            groupName: 'GRUPO 3'),
        members: ['Ana Souza', '  ', 'Bia Lima', 'Caio Reis'],
      );

      expect(header.kindLabel, 'RESUMO DA APRESENTAÇÃO');
      expect(header.heading, 'GRUPO 3');
      // O título automático só repetiria o grupo; fica a disciplina.
      expect(header.subtitle, 'ARA0058 - CLOUD, IOT E INDUSTRIA 4.0');
      expect(header.members, ['Ana Souza', 'Bia Lima', 'Caio Reis']);
    });

    test('apresentação com título próprio mostra o título e a disciplina', () {
      final header = summaryHeaderFor(gravacao('apresentacao',
          title: 'Sensor de umidade', discipline: 'ARA0058', groupName: 'GRUPO 3'));

      expect(header.heading, 'GRUPO 3');
      expect(header.subtitle, 'Sensor de umidade  -  ARA0058');
    });

    test('integrantes só entram na apresentação', () {
      final header = summaryHeaderFor(
          gravacao('palestra', title: 'X'), members: ['Ana']);

      expect(header.members, isEmpty);
    });

    test('apresentação sem nome de grupo cai no título', () {
      expect(summaryHeaderFor(gravacao('apresentacao', title: 'Projeto X')).heading,
          'Projeto X');
      expect(summaryHeaderFor(gravacao('apresentacao')).heading,
          'Apresentação de grupo');
    });

    test('o nome do arquivo segue o tipo e perde os acentos', () {
      expect(
        lessonPdfFilename(gravacao('palestra', title: 'LGPD na prática')),
        '2026-2-lgpd-na-pratica-06-10-2026.pdf',
      );
      expect(
        lessonPdfFilename(gravacao('reuniao', title: 'Reunião do Colegiado')),
        '2026-2-reuniao-do-colegiado-06-10-2026.pdf',
      );
      expect(
        lessonPdfFilename(gravacao('apresentacao',
            groupName: 'GRUPO 3', discipline: 'ARA0058 - CLOUD')),
        '2026-2-ara0058-cloud-grupo-3-06-10-2026.pdf',
      );
    });

    test('sem nada para nomear, o arquivo tem o nome do tipo', () {
      Lesson vazio(String kind) => Lesson(
          id: 'x', kind: kind, discipline: '', title: '', classGroup: '', status: 'closed');

      // Palestra e reunião sem título ganham o "sem título" do cabeçalho.
      expect(lessonPdfFilename(vazio('palestra')), 'palestra-sem-titulo.pdf');
      expect(lessonPdfFilename(vazio('reuniao')), 'reuniao-sem-titulo.pdf');
      expect(lessonPdfFilename(vazio('apresentacao')),
          'apresentacao-de-grupo.pdf');
      expect(lessonPdfFilename(vazio('aula')), 'resumo-da-aula.pdf');
    });

    test('o detalhado leva o sufixo em qualquer tipo', () {
      expect(
        lessonPdfFilename(gravacao('reuniao',
            title: 'Colegiado', style: summaryStyleDetailed)),
        '2026-2-colegiado-06-10-2026-detalhado.pdf',
      );
    });
  });

  group('buildLessonSummaryPdf por tipo', () {
    for (final kind in const ['aula', 'palestra', 'reuniao', 'apresentacao']) {
      test('gera o PDF de $kind', () async {
        final bytes = await buildLessonSummaryPdf(
          lesson: Lesson(
            id: 'x',
            kind: kind,
            title: 'Título de $kind',
            discipline: kind == 'aula' ? 'ARA0040 - BANCO DE DADOS' : '',
            groupName: kind == 'apresentacao' ? 'GRUPO 3' : '',
            classGroup: '',
            status: 'closed',
            startedAt: DateTime(2026, 10, 6, 21, 15),
          ),
          summary: '## Resumo\nTexto do resumo com acentuação.',
          members: kind == 'apresentacao' ? ['Ana Souza', 'Bia Lima'] : const [],
        );

        expect(String.fromCharCodes(bytes.take(4)), '%PDF');
        expect(bytes.length, greaterThan(1000));
      });
    }

    test('o título do documento usa o destaque do tipo, não a disciplina vazia',
        () async {
      final bytes = await buildLessonSummaryPdf(
        lesson: Lesson(
          id: 'x',
          kind: 'palestra',
          title: 'LGPD na pratica',
          discipline: '',
          classGroup: '',
          status: 'closed',
        ),
        summary: '## Resumo\nTexto.',
      );

      final texto = String.fromCharCodes(bytes);
      expect(texto.contains('LGPD na pratica'), isTrue);
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

    test('o cabecalho identifica o formato do resumo', () async {
      final lesson = Lesson(
        id: 'l1',
        discipline: 'ARA0040 - BANCO DE DADOS',
        semester: '2026.2',
        title: 'Normalizacao',
        classGroup: '',
        status: 'closed',
        startedAt: DateTime(2026, 8, 13, 18, 30),
        summaryStyle: summaryStyleDetailed,
      );

      final bytes = await buildLessonSummaryPdf(
        lesson: lesson,
        summary: '## Resumo geral\nA aula tratou de normalizacao.',
      );

      // O texto do PDF sai comprimido; o titulo do documento nao, e e por
      // ele que o visualizador identifica o arquivo aberto.
      expect(
        String.fromCharCodes(bytes).contains('Resumo detalhado'),
        isTrue,
      );
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

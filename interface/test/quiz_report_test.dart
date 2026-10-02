/// Relatorio do quiz e exercicios em PDF: o que o servidor devolve, a planilha, os
/// dois PDFs e a tela.
///
/// Os numeros vem prontos do servidor; estes testes guardam que tela, PDF e
/// planilha apresentam o mesmo numero e que o que vem de campo livre (o nome que
/// o aluno digitou) nao quebra nada.
library;

import 'dart:convert';

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/services/quiz_exercises_pdf_service.dart';
import 'package:assistant_app/services/quiz_report.dart';
import 'package:assistant_app/services/quiz_report_pdf_service.dart';
import 'package:assistant_app/widgets/quiz_report_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Relatorio como o servidor o devolve: Ana (2 acertos), Bia (1 acerto, 1 erro) e
/// Caio (entrou e nao respondeu). A terceira pergunta nunca foi aplicada.
Map<String, dynamic> relatorioJson({
  List<Map<String, dynamic>>? alunos,
  int participantes = 3,
}) =>
    {
      'quiz': {
        'id': 'quiz',
        'titulo': 'Modelagem',
        'status': 'closed',
        'total_questoes': 3,
        'perguntas_aplicadas': 2,
        'criado_em': '2026-09-17T12:00:00',
        'encerrado_em': '2026-09-17T13:00:00',
        'disciplinas': ['Banco de Dados'],
        'fontes': ['Aula 3'],
      },
      'resumo': {
        'participantes': participantes,
        'responderam': 2,
        'sem_resposta_nenhuma': 1,
        'respostas': 4,
        'acertos': 3,
        'erros': 1,
        'puladas': 0,
        'taxa_acerto': 75.0,
        'pontos_medios': 733,
        'tempo_medio_ms': 5250,
      },
      'alunos': alunos ??
          [
            _aluno('Ana', 1, 1700, 2, 0, 0, 100.0, [
              _resp(0, 'acertou', 'A', 900),
              _resp(1, 'acertou', 'A', 800),
            ]),
            _aluno('Bia', 2, 500, 1, 1, 0, 50.0, [
              _resp(0, 'errou', 'B', 0),
              _resp(1, 'acertou', 'A', 500),
            ]),
            _aluno('Caio', 3, 0, 0, 0, 2, 0.0, [
              _resp(0, 'sem_resposta', '', 0),
              _resp(1, 'sem_resposta', '', 0),
            ]),
          ],
      'perguntas': [
        _pergunta(0, true, 'Qual forma normal elimina dependência transitiva?', 50.0),
        _pergunta(1, true, 'Qual forma normal exige a 2FN?', 100.0),
        _pergunta(2, false, 'Pergunta que ninguém viu?', 0.0),
      ],
      'atencao': {
        'perguntas': [
          {
            'indice': 0,
            'enunciado': 'Qual forma normal elimina dependência transitiva?',
            'percentual': 25.0,
            'respostas': 4,
            'mais_escolhida_errada': {
              'label': 'B',
              'texto': '1FN',
              'quantidade': 3,
              'correta': false,
            },
          },
        ],
        'alunos_com_dificuldade': ['Bia'],
        'alunos_sem_resposta': ['Caio'],
      },
    };

Map<String, dynamic> _aluno(
  String nome,
  int posicao,
  int pontos,
  int acertos,
  int erros,
  int semResposta,
  double percentual,
  List<Map<String, dynamic>> porPergunta,
) =>
    {
      'student_id': nome.toLowerCase(),
      'nome': nome,
      'posicao': posicao,
      'pontos': pontos,
      'acertos': acertos,
      'erros': erros,
      'puladas': 0,
      'sem_resposta': semResposta,
      'respondidas': acertos + erros,
      'percentual': percentual,
      'tempo_medio_ms': semResposta == 2 ? null : 3000,
      'por_pergunta': porPergunta,
    };

Map<String, dynamic> _resp(int indice, String status, String resposta, int pontos) => {
      'indice': indice,
      'status': status,
      'resposta': resposta,
      'pontos': pontos,
      'tempo_ms': status == 'sem_resposta' ? null : 3000,
    };

Map<String, dynamic> _pergunta(int indice, bool aplicada, String enunciado, double pct) => {
      'indice': indice,
      'aplicada': aplicada,
      'enunciado': enunciado,
      'correta': 'A',
      'respostas': aplicada ? 2 : 0,
      'acertos': 1,
      'erros': 1,
      'sem_resposta': aplicada ? 1 : 0,
      'percentual': pct,
      'tempo_medio_ms': 4000,
      'distribuicao': [
        {'label': 'A', 'texto': '3FN', 'quantidade': 1, 'correta': true},
        {'label': 'B', 'texto': '1FN', 'quantidade': 1, 'correta': false},
        {'label': 'C', 'texto': '2FN', 'quantidade': 0, 'correta': false},
      ],
      'mais_escolhida_errada': {
        'label': 'B',
        'texto': '1FN',
        'quantidade': 1,
        'correta': false,
      },
    };

/// Paginas do PDF, contadas nos objetos `/Type /Page` (os de `/Pages` ficam fora).
int paginas(List<int> bytes) =>
    RegExp(r'/Type\s*/Page(?!s)').allMatches(latin1.decode(bytes)).length;

QuizReport relatorio({List<Map<String, dynamic>>? alunos, int participantes = 3}) =>
    QuizReport.fromJson(relatorioJson(alunos: alunos, participantes: participantes));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('leitura do relatorio', () {
    test('le quiz, resumo, alunos, perguntas e pontos de atencao', () {
      final report = relatorio();

      expect(report.titulo, 'Modelagem');
      expect(report.disciplinas, ['Banco de Dados']);
      expect(report.perguntasAplicadas, 2);
      expect(report.totalQuestoes, 3);
      expect(report.participantes, 3);
      expect(report.taxaAcerto, 75.0);
      expect(report.tempoMedioMs, 5250);
      expect(report.alunos.map((a) => a.nome), ['Ana', 'Bia', 'Caio']);
      expect(report.alunos.first.porPergunta.first.acertou, isTrue);
      expect(report.alunos.last.semNenhumaResposta, isTrue);
      expect(report.perguntasEmAtencao.single.maisEscolhidaErrada?.label, 'B');
      expect(report.alunosComDificuldade, ['Bia']);
      expect(report.alunosSemResposta, ['Caio']);
    });

    test('so as perguntas aplicadas entram na lista de analise', () {
      final report = relatorio();

      expect(report.perguntas, hasLength(3));
      expect(report.aplicadas.map((q) => q.indice), [0, 1]);
    });

    test('resposta vazia ou incompleta nao quebra a leitura', () {
      final report = QuizReport.fromJson({});

      expect(report.semDados, isTrue);
      expect(report.alunos, isEmpty);
      expect(report.status, 'open');
    });

    test('texto da alternativa pela letra', () {
      final pergunta = relatorio().perguntas.first;

      expect(pergunta.textoDe('A'), '3FN');
      expect(pergunta.textoDe('Z'), '');
    });
  });

  group('formatacao', () {
    test('percentual com virgula e sem casa decimal inutil', () {
      expect(formatPercent(100), '100%');
      expect(formatPercent(66.7), '66,7%');
      expect(formatPercent(0), '0%');
    });

    test('tempo em segundos', () {
      expect(formatSeconds(3200), '3,2 s');
      expect(formatSeconds(null), '—');
    });

    test('nome de arquivo sem acento nem simbolo', () {
      expect(
        quizFilename('Quiz: Normalização & Chaves!', suffix: 'relatorio'),
        'quiz-normalizacao-chaves-relatorio.pdf',
      );
      expect(quizFilename('', extension: 'csv'), 'quiz.csv');
    });
  });

  group('planilha', () {
    test('abre no Excel em portugues: BOM, ponto e virgula, virgula decimal', () {
      final csv = quizReportCsv(relatorio());

      expect(csv.startsWith('\u{FEFF}'), isTrue);
      final linhas = csv.trim().split('\r\n');
      expect(linhas.first.replaceFirst('\u{FEFF}', ''),
          'Posição;Aluno;Pontos;Acertos;Erros;Puladas;Sem resposta;% de acerto;Tempo médio (s);P1;P2');
      expect(linhas[1], '1;Ana;1700;2;0;0;0;100,0;3,0;A ✓;A ✓');
      expect(linhas[2], '2;Bia;500;1;1;0;0;50,0;3,0;B ✗;A ✓');
    });

    test('so as perguntas aplicadas viram coluna', () {
      final cabecalho = quizReportCsv(relatorio()).split('\r\n').first;

      expect(cabecalho.endsWith('P1;P2'), isTrue);
      expect(cabecalho.contains('P3'), isFalse);
    });

    test('quem nao respondeu aparece com tracos e sem tempo', () {
      final linhas = quizReportCsv(relatorio()).trim().split('\r\n');

      expect(linhas[3], '3;Caio;0;0;0;0;2;0,0;;—;—');
    });

    test('a ultima linha traz o gabarito', () {
      final linhas = quizReportCsv(relatorio()).trim().split('\r\n');

      expect(linhas.last, ';Gabarito;;;;;;;;A;A');
    });

    test('nome com ponto e virgula ou aspas e protegido', () {
      final report = relatorio(alunos: [
        _aluno('Ana; "a boa"', 1, 100, 1, 0, 0, 100.0, [_resp(0, 'acertou', 'A', 100)]),
      ]);

      final linha = quizReportCsv(report).trim().split('\r\n')[1];

      expect(linha.startsWith('1;"Ana; ""a boa"""'), isTrue, reason: linha);
    });

    test('nome que comeca como formula nao executa na planilha', () {
      // O nome vem de um campo livre, digitado por quem escaneou o QR Code.
      for (final perigoso in ['=HYPERLINK("http://x")', '+1+1', '-2+3', '@SUM(A1)']) {
        final report = relatorio(alunos: [
          _aluno(perigoso, 1, 0, 0, 0, 0, 0.0, []),
        ]);

        final linha = quizReportCsv(report).trim().split('\r\n')[1];
        final campoNome = linha.split(';')[1];

        expect(
          campoNome.replaceAll('"', '').startsWith("'"),
          isTrue,
          reason: 'sem apostrofo: $perigoso -> $linha',
        );
      }
    });
  });

  group('PDF do relatorio', () {
    test('gera um PDF valido com resumo, alunos e uma folha por aluno', () async {
      final bytes = await buildQuizReportPdf(relatorio());

      expect(latin1.decode(bytes.sublist(0, 5)), '%PDF-');
      // 1 pagina do conjunto + 3 folhas individuais.
      expect(paginas(bytes), 4);
    });

    test('sem as folhas individuais sobra so o conjunto', () async {
      final bytes = await buildQuizReportPdf(
        relatorio(),
        options: const ReportPdfOptions(studentSheets: false),
      );

      expect(paginas(bytes), 1);
    });

    test('quiz sem participante gera uma pagina e nenhuma folha', () async {
      final bytes = await buildQuizReportPdf(
        relatorio(alunos: const [], participantes: 0),
      );

      expect(paginas(bytes), 1);
    });

    test('turma grande continua gerando: uma folha por aluno', () async {
      final alunos = [
        for (var i = 1; i <= 40; i++)
          _aluno('Aluno $i', i, 1000 - i, 1, 1, 0, 50.0, [
            _resp(0, 'acertou', 'A', 500),
            _resp(1, 'errou', 'B', 0),
          ]),
      ];

      final bytes = await buildQuizReportPdf(
        relatorio(alunos: alunos, participantes: 40),
      );

      expect(paginas(bytes), greaterThanOrEqualTo(41));
    });

    test('textos longos e acentos nao quebram o PDF', () async {
      final json = relatorioJson();
      (json['perguntas'] as List)[0]['enunciado'] = 'Muito longo ' * 80;
      (json['alunos'] as List)[0]['nome'] = 'Ana Conceição da Silva Ávila ' * 4;

      final bytes = await buildQuizReportPdf(QuizReport.fromJson(json));

      expect(paginas(bytes), greaterThanOrEqualTo(4));
    });
  });

  group('PDF dos exercicios', () {
    ExerciseQuestion mc(String enunciado, {String correta = 'B', String justificativa = ''}) =>
        ExerciseQuestion.fromJson({
          'enunciado': enunciado,
          'tipo': 'multipla_escolha',
          'opcoes': [
            {'label': 'A', 'texto': '1FN', 'correta': correta == 'A'},
            {'label': 'B', 'texto': '3FN', 'correta': correta == 'B'},
            {'label': 'C', 'texto': '2FN', 'correta': correta == 'C'},
          ],
          'justificativa': justificativa,
        });

    test('gabarito de multipla escolha e a letra da alternativa marcada', () {
      expect(mc('x', correta: 'C').gabarito, 'C');
      expect(mc('x', correta: 'B').textoDaCorreta, '3FN');
    });

    test('verdadeiro ou falso entende as grafias do servidor', () {
      ExerciseQuestion vf(String resposta) => ExerciseQuestion.fromJson(
          {'enunciado': 'x', 'tipo': 'verdadeiro_falso', 'resposta_correta': resposta});

      expect(vf('verdadeiro').gabarito, 'Verdadeiro');
      expect(vf('V').gabarito, 'Verdadeiro');
      expect(vf('false').gabarito, 'Falso');
    });

    test('pergunta aberta usa a resposta esperada como gabarito', () {
      final aberta = ExerciseQuestion.fromJson({
        'enunciado': 'Explique a 3FN.',
        'tipo': 'aberta',
        'resposta_correta': 'Sem dependência transitiva.',
      });

      expect(aberta.gabarito, 'Sem dependência transitiva.');
      expect(aberta.ehMultiplaEscolha, isFalse);
    });

    test('gabarito segue a ordem do papel e leva a justificativa so se pedida', () {
      final perguntas = [
        mc('Primeira?', correta: 'A', justificativa: 'Porque sim.'),
        mc('Segunda?', correta: 'C', justificativa: 'Porque nao.'),
      ];

      final sem = answerKeyLines(perguntas);
      final com = answerKeyLines(perguntas, withJustifications: true);

      expect(sem.map((l) => '${l.numero}${l.resposta}'), ['1A', '2C']);
      expect(sem.every((l) => l.justificativa.isEmpty), isTrue);
      expect(com.map((l) => l.justificativa), ['Porque sim.', 'Porque nao.']);
      expect(com.first.texto, '1FN');
    });

    test('a prova sai sem gabarito e o gabarito acrescenta uma pagina separada', () async {
      final perguntas = [mc('Primeira?'), mc('Segunda?')];

      final prova = await buildQuizExercisesPdf(
        title: 'Quiz',
        questions: perguntas,
        options: const ExercisesPdfOptions(includeAnswerKey: false),
      );
      final comGabarito = await buildQuizExercisesPdf(
        title: 'Quiz',
        questions: perguntas,
      );

      expect(latin1.decode(prova.sublist(0, 5)), '%PDF-');
      expect(paginas(prova), 1);
      expect(paginas(comGabarito), 2, reason: 'o gabarito vai em pagina propria');
    });

    test('prova longa passa de uma pagina e o gabarito continua no fim', () async {
      final perguntas = [
        for (var i = 1; i <= 40; i++) mc('Pergunta $i sobre normalização?'),
      ];

      final sem = await buildQuizExercisesPdf(
        title: 'Quiz',
        questions: perguntas,
        options: const ExercisesPdfOptions(includeAnswerKey: false),
      );
      final com = await buildQuizExercisesPdf(title: 'Quiz', questions: perguntas);

      expect(paginas(sem), greaterThan(1));
      expect(paginas(com), paginas(sem) + 1);
    });

    test('todos os tipos de pergunta saem no papel', () async {
      final bytes = await buildQuizExercisesPdf(
        title: 'Misto',
        discipline: 'Banco de Dados',
        questions: [
          mc('Múltipla?'),
          ExerciseQuestion.fromJson({
            'enunciado': 'Verdadeiro ou falso?',
            'tipo': 'verdadeiro_falso',
            'resposta_correta': 'falso',
          }),
          ExerciseQuestion.fromJson({
            'enunciado': 'Explique.',
            'tipo': 'aberta',
            'resposta_correta': 'Algo.',
          }),
        ],
        options: const ExercisesPdfOptions(includeJustifications: true),
        generatedAt: DateTime(2026, 10, 1),
      );

      expect(latin1.decode(bytes.sublist(0, 5)), '%PDF-');
    });

    test('quiz sem pergunta ainda gera o documento, sem gabarito', () async {
      final bytes = await buildQuizExercisesPdf(title: 'Vazio', questions: const []);

      expect(paginas(bytes), 1);
    });
  });

  group('tela do relatorio', () {
    Future<void> abrir(WidgetTester tester, FakeCenter center) async {
      tester.view.physicalSize = const Size(1200, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        theme: ThemeData.dark(),
        home: Scaffold(
          body: QuizReportView(quizId: 'quiz', title: 'Modelagem', service: center),
        ),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('mostra resumo, pontos de atencao e o ranking dos alunos', (tester) async {
      await abrir(tester, FakeCenter(relatorioJson()));

      expect(find.text('Modelagem'), findsOneWidget);
      expect(find.text('2/3'), findsWidgets, reason: 'responderam / participantes');
      expect(find.text('75%'), findsOneWidget);
      expect(find.text('733'), findsOneWidget);
      expect(find.text('PONTOS DE ATENÇÃO'), findsOneWidget);
      expect(find.textContaining('só 25% acertaram'), findsOneWidget);
      expect(find.textContaining('Acertaram menos da metade: Bia'), findsOneWidget);
      expect(find.textContaining('Entraram e não responderam: Caio'), findsOneWidget);
      expect(find.text('Alunos (3)'), findsOneWidget);
      expect(find.text('Perguntas (2)'), findsOneWidget);
      expect(find.text('Ana'), findsOneWidget);
      expect(find.text('Caio (não respondeu)'), findsOneWidget);
    });

    testWidgets('abrir um aluno mostra o que ele respondeu em cada pergunta', (tester) async {
      await abrir(tester, FakeCenter(relatorioJson()));

      await tester.tap(find.text('Bia'));
      await tester.pumpAndSettle();

      expect(find.text('P1  B ✗'), findsOneWidget);
      expect(find.text('P2  A ✓'), findsOneWidget);
    });

    testWidgets('aba de perguntas mostra a distribuicao das alternativas', (tester) async {
      await abrir(tester, FakeCenter(relatorioJson()));

      await tester.tap(find.text('Perguntas (2)'));
      await tester.pumpAndSettle();

      expect(find.textContaining('Qual forma normal elimina dependência transitiva?'),
          findsWidgets);
      expect(find.text('3FN'), findsWidgets);
      expect(find.textContaining('1 acertaram · 1 erraram · 1 em branco'), findsWidgets);
    });

    testWidgets('quiz sem participante diz isso e nao oferece exportar', (tester) async {
      await abrir(
        tester,
        FakeCenter(relatorioJson(alunos: const [], participantes: 0)),
      );

      expect(find.text('Ninguém participou deste quiz ainda.'), findsOneWidget);
      final pdf = tester.widget<FilledButton>(find.ancestor(
        of: find.text('PDF'),
        matching: find.byType(FilledButton),
      ));
      expect(pdf.onPressed, isNull);
    });

    testWidgets('com dados, PDF e planilha ficam disponiveis', (tester) async {
      await abrir(tester, FakeCenter(relatorioJson()));

      final pdf = tester.widget<FilledButton>(find.ancestor(
        of: find.text('PDF'),
        matching: find.byType(FilledButton),
      ));
      expect(pdf.onPressed, isNotNull);
      expect(find.text('PLANILHA'), findsOneWidget);
    });

    testWidgets('erro do servidor aparece e da para tentar de novo', (tester) async {
      final center = FakeCenter(relatorioJson())..falhas = 1;
      await abrir(tester, center);

      expect(find.textContaining('Não consegui carregar o relatório'), findsOneWidget);

      await tester.tap(find.text('Tentar de novo'));
      await tester.pumpAndSettle();

      expect(find.text('Alunos (3)'), findsOneWidget);
      expect(center.pedidos, 2);
    });
  });
}

class FakeCenter extends QuizCenterService {
  FakeCenter(this.json) : super(ApiService());

  final Map<String, dynamic> json;
  int falhas = 0;
  int pedidos = 0;

  @override
  Future<QuizReport> quizReport(String quizId) async {
    pedidos++;
    if (falhas > 0) {
      falhas--;
      throw const QuizCenterException('servidor fora do ar');
    }
    return QuizReport.fromJson(json);
  }
}

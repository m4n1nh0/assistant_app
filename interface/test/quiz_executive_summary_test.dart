/// Resumo executivo do quiz: o texto sai de regras sobre os numeros, e nunca leva
/// nome de aluno.
///
/// Quem le o resumo executivo (coordenacao, direcao) nao esteve na sala nem tem
/// como conferir o que esta escrito. Por isso as frases vem de regras, nao de um
/// modelo de IA que poderia inventar uma conclusao, e o documento circula sem
/// expor ninguem.
library;

import 'dart:convert';

import 'package:assistant_app/services/quiz_executive_report_pdf_service.dart';
import 'package:assistant_app/services/quiz_executive_summary.dart';
import 'package:assistant_app/services/quiz_report.dart';
import 'package:assistant_app/widgets/quiz_report_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'quiz_report_test.dart' as base;

const nomes = ['Ana', 'Bia', 'Caio', 'Dani', 'Eduardo'];

Map<String, dynamic> aluno(String nome, double pct, {int respondidas = 4}) => {
      'student_id': nome,
      'nome': nome,
      'posicao': 1,
      'pontos': 100,
      'acertos': (pct / 100 * 4).round(),
      'erros': 4 - (pct / 100 * 4).round(),
      'puladas': 0,
      'sem_resposta': respondidas == 0 ? 4 : 0,
      'respondidas': respondidas,
      'percentual': pct,
      'tempo_medio_ms': respondidas == 0 ? null : 3000,
      'por_pergunta': const [],
    };

Map<String, dynamic> pergunta(int indice, double pct, {int respostas = 10}) => {
      'indice': indice,
      'aplicada': true,
      'enunciado': 'Pergunta $indice sobre normalização?',
      'correta': 'A',
      'respostas': respostas,
      'acertos': 1,
      'erros': 1,
      'sem_resposta': 0,
      'percentual': pct,
      'tempo_medio_ms': 3000,
      'distribuicao': [
        {'label': 'A', 'texto': '3FN', 'quantidade': 1, 'correta': true},
        {'label': 'B', 'texto': '1FN', 'quantidade': 1, 'correta': false},
      ],
      'mais_escolhida_errada': {
        'label': 'B',
        'texto': '1FN',
        'quantidade': 1,
        'correta': false,
      },
    };

/// Monta um relatorio so com o que o teste precisa.
QuizReport relatorio({
  required List<Map<String, dynamic>> alunos,
  List<Map<String, dynamic>>? perguntas,
  double taxa = 75,
  int aplicadas = 4,
  int total = 4,
  List<Map<String, dynamic>> fracas = const [],
}) {
  final responderam = alunos.where((a) => a['respondidas'] != 0).length;
  return QuizReport.fromJson({
    'quiz': {
      'id': 'q',
      'titulo': 'Modelagem',
      'status': 'closed',
      'total_questoes': total,
      'perguntas_aplicadas': aplicadas,
      'disciplinas': ['Banco de Dados'],
      'encerrado_em': '2026-09-17T13:00:00',
    },
    'resumo': {
      'participantes': alunos.length,
      'responderam': responderam,
      'sem_resposta_nenhuma': alunos.length - responderam,
      'taxa_acerto': taxa,
      'pontos_medios': 500,
      'tempo_medio_ms': 3000,
    },
    'alunos': alunos,
    'perguntas': perguntas ?? [pergunta(0, 80), pergunta(1, 60)],
    'atencao': {
      'perguntas': fracas,
      'alunos_com_dificuldade': [for (final a in alunos) if ((a['percentual'] as double) < 50) a['nome']],
      'alunos_sem_resposta': [for (final a in alunos) if (a['respondidas'] == 0) a['nome']],
    },
  });
}

Map<String, dynamic> fraca(int indice, double pct) => {
      'indice': indice,
      'enunciado': 'Pergunta $indice sobre normalização?',
      'percentual': pct,
      'respostas': 10,
      'mais_escolhida_errada': {'label': 'B', 'texto': '1FN', 'quantidade': 6, 'correta': false},
    };

int paginas(List<int> bytes) =>
    RegExp(r'/Type\s*/Page(?!s)').allMatches(latin1.decode(bytes)).length;

String todoOTexto(ExecutiveSummary s) => [
      s.headline,
      ...s.findings,
      ...s.recommendations,
      s.caveat,
      ...s.bands.map((b) => b.label),
      ...s.weakest.map((q) => q.enunciado),
    ].join('\n');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('veredito', () {
    ExecutiveSummary para(double taxa) => buildExecutiveSummary(
          relatorio(alunos: [aluno('Ana', 80)], taxa: taxa),
        );

    test('70% ou mais e bom desempenho; de 50 a 70 pede atencao; menos de 50 e critico', () {
      expect(para(100).verdict, Verdict.bom);
      expect(para(70).verdict, Verdict.bom);
      expect(para(69.9).verdict, Verdict.atencao);
      expect(para(50).verdict, Verdict.atencao);
      expect(para(49.9).verdict, Verdict.critico);
      expect(para(0).verdict, Verdict.critico);
    });

    test('a frase acompanha o veredito e traz o percentual', () {
      expect(para(78).headline, contains('A turma foi bem: 78% de acerto'));
      expect(para(60).headline, contains('Desempenho intermediário: 60% de acerto'));
      expect(para(30).headline, contains('abaixo do esperado: 30% de acerto'));
    });

    test('sem ninguem, diz que ninguem participou', () {
      final summary = buildExecutiveSummary(relatorio(alunos: const []));

      expect(summary.verdict, Verdict.semDados);
      expect(summary.headline, 'Ninguém participou deste quiz ainda.');
      expect(summary.findings, isEmpty);
      expect(summary.recommendations, isEmpty);
    });

    test('todos entraram e ninguem respondeu nao vira "turma foi bem"', () {
      final summary = buildExecutiveSummary(relatorio(
        alunos: [aluno('Ana', 0, respondidas: 0), aluno('Bia', 0, respondidas: 0)],
        taxa: 0,
      ));

      expect(summary.verdict, Verdict.semDados);
      expect(summary.headline, 'Os 2 participantes entraram, mas ninguém respondeu.');
    });
  });

  group('faixas de acerto', () {
    test('conta cada aluno na faixa certa, com os limites em 90, 70 e 50', () {
      final summary = buildExecutiveSummary(relatorio(alunos: [
        aluno('Ana', 100),
        aluno('Bia', 90),
        aluno('Caio', 89.9),
        aluno('Dani', 70),
        aluno('Eduardo', 69.9),
        aluno('Fer', 50),
        aluno('Gui', 49.9),
        aluno('Hel', 0),
      ]));

      expect({for (final b in summary.bands) b.label: b.count}, {
        '90% ou mais': 2,
        '70% a 89%': 2,
        '50% a 69%': 2,
        'Menos de 50%': 2,
        'Não responderam': 0,
      });
    });

    test('quem entrou e nao respondeu tem faixa propria e nao conta como 0% de acerto', () {
      final summary = buildExecutiveSummary(relatorio(alunos: [
        aluno('Ana', 80),
        aluno('Bia', 0, respondidas: 0),
      ]));

      final porFaixa = {for (final b in summary.bands) b.label: b.count};
      expect(porFaixa['Não responderam'], 1);
      expect(porFaixa['Menos de 50%'], 0);
    });

    test('a participacao e quem respondeu sobre quem entrou', () {
      final summary = buildExecutiveSummary(relatorio(alunos: [
        aluno('Ana', 80),
        aluno('Bia', 0, respondidas: 0),
        aluno('Caio', 0, respondidas: 0),
        aluno('Dani', 60),
      ]));

      expect(summary.participation, 50);
    });
  });

  group('constatacoes', () {
    test('participacao no singular e no plural', () {
      final um = buildExecutiveSummary(relatorio(alunos: [
        aluno('Ana', 80),
        aluno('Bia', 0, respondidas: 0),
      ]));
      final dois = buildExecutiveSummary(relatorio(alunos: [
        aluno('Ana', 80),
        aluno('Bia', 0, respondidas: 0),
        aluno('Caio', 0, respondidas: 0),
      ]));

      expect(um.findings.first,
          '1 de 2 participantes responderam (50%). 1 entrou e não respondeu.');
      expect(dois.findings.first, contains('2 entraram e não responderam'));
    });

    test('a pergunta fraca vem do que o servidor apontou, com a alternativa mais marcada', () {
      final summary = buildExecutiveSummary(relatorio(
        alunos: [aluno('Ana', 80)],
        fracas: [fraca(2, 25)],
      ));

      expect(summary.weakest.single.number, 3);
      expect(summary.findings.any((f) =>
          f.contains('P3 teve só 25% de acerto') && f.contains('a turma mais marcou B) 1FN')),
          isTrue);
    });

    test('conteudo dominado entra nos pontos fortes, so com respostas suficientes', () {
      final summary = buildExecutiveSummary(relatorio(
        alunos: [aluno('Ana', 80)],
        perguntas: [
          pergunta(0, 95),
          pergunta(1, 100, respostas: 2),
          pergunta(2, 86),
          pergunta(3, 84),
        ],
      ));

      expect(summary.strongest.map((q) => q.number), [1, 3]);
      expect(summary.findings.any((f) => f.startsWith('Conteúdo dominado: P1 (95%), P3 (86%)')),
          isTrue);
    });

    test('alunos abaixo de 50% entram com a proporcao de quem respondeu', () {
      final summary = buildExecutiveSummary(relatorio(alunos: [
        aluno('Ana', 80),
        aluno('Bia', 20),
        aluno('Caio', 10),
        aluno('Dani', 90),
      ]));

      expect(summary.findings.any((f) =>
          f.contains('2 alunos (50% de quem respondeu) acertaram menos da metade')),
          isTrue);
    });
  });

  group('recomendacoes', () {
    test('pergunta fraca pede retomar em aula', () {
      final summary = buildExecutiveSummary(relatorio(
        alunos: [aluno('Ana', 80)],
        fracas: [fraca(0, 20), fraca(1, 30)],
      ));

      expect(summary.recommendations.first,
          startsWith('Retomar em aula: P1 — Pergunta 0 sobre normalização; P2 —'));
    });

    test('aluno abaixo de 50% pede reforco, no singular e no plural', () {
      final um = buildExecutiveSummary(relatorio(alunos: [aluno('Ana', 80), aluno('Bia', 20)]));
      final dois = buildExecutiveSummary(
          relatorio(alunos: [aluno('Ana', 80), aluno('Bia', 20), aluno('Caio', 10)]));

      expect(um.recommendations, contains('Oferecer reforço a 1 aluno que acertou menos da metade.'));
      expect(dois.recommendations,
          contains('Oferecer reforço a 2 alunos que acertaram menos da metade.'));
    });

    test('pouca participacao pede checar o acesso, nao o conteudo', () {
      final summary = buildExecutiveSummary(relatorio(alunos: [
        aluno('Ana', 80),
        aluno('Bia', 0, respondidas: 0),
        aluno('Caio', 0, respondidas: 0),
      ]));

      expect(summary.recommendations.any((r) =>
          r.startsWith('Verificar o acesso: 2 participantes não responderam')),
          isTrue);
    });

    test('quiz encerrado antes do fim avisa que o resultado cobre so uma parte', () {
      final summary = buildExecutiveSummary(
        relatorio(alunos: [aluno('Ana', 80)], aplicadas: 3, total: 10),
      );

      expect(summary.recommendations.any((r) =>
          r.contains('encerrado com 3 de 10 perguntas aplicadas')),
          isTrue);
    });

    test('turma muito bem sem ponto fraco pode avancar', () {
      final summary = buildExecutiveSummary(
        relatorio(alunos: [aluno('Ana', 95), aluno('Bia', 90)], taxa: 92),
      );

      expect(summary.recommendations,
          ['Turma pronta para avançar; considerar perguntas mais difíceis no próximo quiz.']);
    });

    test('quando nada pede acao, diz isso em vez de ficar vazio', () {
      final summary = buildExecutiveSummary(
        relatorio(alunos: [aluno('Ana', 75), aluno('Bia', 72)], taxa: 73),
      );

      expect(summary.recommendations,
          ['Sem ação específica: o desempenho está dentro do esperado.']);
    });

    test('o aviso de limite acompanha todo resumo', () {
      final summary = buildExecutiveSummary(relatorio(alunos: [aluno('Ana', 80)]));

      expect(summary.caveat, contains('amostra da aula'));
      expect(summary.caveat, contains('navegador identificado pelo nome digitado'));
    });
  });

  group('privacidade', () {
    test('nenhum texto do resumo leva nome de aluno', () {
      // Bia e Caio estao abaixo de 50% e Dani nem respondeu: o relatorio completo
      // os nomeia, o executivo nao.
      final summary = buildExecutiveSummary(relatorio(
        alunos: [
          aluno('Ana', 90),
          aluno('Bia', 20),
          aluno('Caio', 10),
          aluno('Dani', 0, respondidas: 0),
          aluno('Eduardo', 70),
        ],
        taxa: 55,
        fracas: [fraca(1, 30)],
      ));

      final texto = todoOTexto(summary);
      for (final nome in nomes) {
        expect(texto.contains(nome), isFalse, reason: 'o nome "$nome" vazou: $texto');
      }
    });
  });

  group('PDF executivo', () {
    test('cabe numa pagina', () async {
      final bytes = await buildQuizExecutiveReportPdf(
        relatorio(
          alunos: [aluno('Ana', 90), aluno('Bia', 20), aluno('Caio', 70)],
          fracas: [fraca(0, 20), fraca(1, 30), fraca(2, 40)],
        ),
        generatedAt: DateTime(2026, 10, 1),
      );

      expect(latin1.decode(bytes.sublist(0, 5)), '%PDF-');
      expect(paginas(bytes), 1);
    });

    test('turma e quiz enormes continuam numa pagina', () async {
      final alunos = [for (var i = 0; i < 120; i++) aluno('Aluno $i', (i * 7 % 100).toDouble())];
      final perguntas = [for (var i = 0; i < 50; i++) pergunta(i, (i * 13 % 100).toDouble())];

      final bytes = await buildQuizExecutiveReportPdf(
        relatorio(
          alunos: alunos,
          perguntas: perguntas,
          aplicadas: 50,
          total: 50,
          fracas: [fraca(0, 20), fraca(1, 30), fraca(2, 40)],
        ),
      );

      expect(paginas(bytes), 1);
    });

    test('enunciados enormes sao cortados e nao estouram a pagina', () async {
      final longa = 'Texto muito longo ' * 60;
      final perguntas = [pergunta(0, 20)..['enunciado'] = longa];
      final bytes = await buildQuizExecutiveReportPdf(
        relatorio(
          alunos: [aluno('Ana', 40)],
          perguntas: perguntas,
          fracas: [fraca(0, 20)..['enunciado'] = longa],
        ),
      );

      expect(paginas(bytes), 1);
    });

    test('quiz sem participante ainda gera o documento', () async {
      final bytes = await buildQuizExecutiveReportPdf(relatorio(alunos: const []));

      expect(paginas(bytes), 1);
    });
  });

  group('tela', () {
    Future<void> abrir(WidgetTester tester, Map<String, dynamic> json) async {
      // Alto o bastante para a lista desenhar tudo: ela so constroi o que cabe.
      tester.view.physicalSize = const Size(1200, 2600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        theme: ThemeData.dark(),
        home: Scaffold(
          body: QuizReportView(
            quizId: 'quiz',
            service: base.FakeCenter(json),
          ),
        ),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('a aba mostra veredito, faixas, constatacoes e o que fazer', (tester) async {
      await abrir(tester, base.relatorioJson());

      await tester.tap(find.text('Resumo executivo'));
      await tester.pumpAndSettle();

      expect(find.text('BOM DESEMPENHO'), findsOneWidget);
      expect(find.textContaining('A turma foi bem: 75% de acerto'), findsOneWidget);
      expect(find.text('Alunos por faixa de acerto'.toUpperCase()), findsOneWidget);
      expect(find.text('O QUE OS NÚMEROS MOSTRAM'), findsOneWidget);
      expect(find.text('O QUE FAZER'), findsOneWidget);
      expect(find.textContaining('amostra da aula'), findsOneWidget);
    });

    testWidgets('a aba executiva nao mostra nome de aluno', (tester) async {
      await abrir(tester, base.relatorioJson());

      await tester.tap(find.text('Resumo executivo'));
      await tester.pumpAndSettle();

      // O painel de atencao acima das abas e a tela do professor e nomeia; o que
      // vira documento para a coordenacao, a aba, nao.
      final aba = find.byType(TabBarView);
      for (final nome in ['Ana', 'Bia', 'Caio']) {
        expect(
          find.descendant(of: aba, matching: find.textContaining(nome)),
          findsNothing,
          reason: nome,
        );
      }
    });
  });
}

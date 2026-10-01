/// Revisao das perguntas por Codex e Claude, os agentes da maquina do professor.
///
/// O app so leva o prompt do servidor ate os agentes e traz o texto de volta; o
/// veredito e do servidor. O que este arquivo guarda e a ordem e o isolamento
/// dessa ponte: um agente que falha nao derruba o outro, e as respostas chegam
/// ao servidor uma de cada vez porque o veredito soma as leituras de todos.
library;

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/connected_ai_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/services/quiz_specialist_review.dart';
import 'package:assistant_app/widgets/quiz_preview_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

ConnectedAiStatus agente(
  String id, {
  bool instalado = true,
  bool logado = true,
}) =>
    ConnectedAiStatus(
      id: id,
      label: ConnectedAiService.supportedAgents[id] ?? id,
      installed: instalado,
      authenticated: logado,
    );

class FakeCentral extends QuizCenterService {
  FakeCentral() : super(ApiService());

  final List<String> entregues = [];
  bool servidorRecusa = false;
  int promptsPedidos = 0;

  @override
  Future<QuizReviewPrompt> reviewPrompt(String quizId) async {
    promptsPedidos++;
    return const QuizReviewPrompt(
      systemPrompt: 'sistema',
      prompt: 'prompt sem gabarito',
      questionIds: ['q1'],
    );
  }

  @override
  Future<Map<String, dynamic>> submitReview(
    String quizId, {
    required String agent,
    required String content,
  }) async {
    if (servidorRecusa) {
      throw const QuizCenterException('revisão ilegível');
    }
    entregues.add(agent);
    return {
      'questoes': [
        {'id': 'q1', 'revisao': {'status': 'aprovada'}},
      ],
      'review_summary': {'aprovada': 1},
    };
  }
}

Future<ConnectedAiResult> Function({
  required String agentId,
  required String prompt,
  required String systemPrompt,
  void Function(String activity)? onProgress,
}) agentesQue(Map<String, ConnectedAiResult> respostas, List<String> prompts) {
  return ({
    required String agentId,
    required String prompt,
    required String systemPrompt,
    void Function(String activity)? onProgress,
  }) async {
    prompts.add(prompt);
    final resposta = respostas[agentId];
    if (resposta == null) throw Exception('agente sem resposta no teste');
    return resposta;
  };
}

void main() {
  group('reviewWithSpecialists', () {
    test('sem agente conectado nao chama o servidor nem diz que revisou', () async {
      final central = FakeCentral();

      final resultado = await reviewWithSpecialists(
        quizId: 'quiz',
        service: central,
        checkAgents: () async => [
          agente('codex_cli', instalado: false),
          agente('claude_cli', logado: false),
        ],
      );

      expect(resultado.noAgents, isTrue);
      expect(resultado.anyOk, isFalse);
      expect(central.promptsPedidos, 0);
      expect(resultado.message, contains('Configurações > Agentes'));
    });

    test('os dois agentes recebem o mesmo prompt e as respostas vao uma a uma', () async {
      final central = FakeCentral();
      final prompts = <String>[];

      final resultado = await reviewWithSpecialists(
        quizId: 'quiz',
        service: central,
        checkAgents: () async => [agente('codex_cli'), agente('claude_cli')],
        runAgent: agentesQue({
          'codex_cli': const ConnectedAiResult(agentId: 'codex_cli', content: '{"revisoes": []}'),
          'claude_cli': const ConnectedAiResult(agentId: 'claude_cli', content: '{"revisoes": []}'),
        }, prompts),
      );

      expect(prompts, ['prompt sem gabarito', 'prompt sem gabarito']);
      expect(central.entregues, ['codex_cli', 'claude_cli']);
      expect(resultado.runs.map((r) => r.ok), [true, true]);
      expect(resultado.summary, {'aprovada': 1});
      expect(resultado.message, contains('Codex: revisou'));
      expect(resultado.message, contains('Claude: revisou'));
      expect(resultado.message, contains('1 aprovada'));
    });

    test('agente que falha nao derruba o outro e o motivo aparece', () async {
      final central = FakeCentral();

      final resultado = await reviewWithSpecialists(
        quizId: 'quiz',
        service: central,
        checkAgents: () async => [agente('codex_cli'), agente('claude_cli')],
        runAgent: agentesQue({
          'codex_cli': const ConnectedAiResult(
            agentId: 'codex_cli',
            content: 'O agente local excedeu o limite de 12 minutos.',
            isError: true,
          ),
          'claude_cli': const ConnectedAiResult(agentId: 'claude_cli', content: '{}'),
        }, []),
      );

      expect(central.entregues, ['claude_cli']);
      expect(resultado.anyOk, isTrue);
      expect(resultado.runs.first.ok, isFalse);
      expect(resultado.message, contains('Codex: falhou — O agente local excedeu'));
    });

    test('excecao do agente vira falha daquele agente, nao do fluxo', () async {
      final central = FakeCentral();

      final resultado = await reviewWithSpecialists(
        quizId: 'quiz',
        service: central,
        checkAgents: () async => [agente('codex_cli'), agente('claude_cli')],
        // So o Claude responde; o Codex levanta excecao.
        runAgent: agentesQue({
          'claude_cli': const ConnectedAiResult(agentId: 'claude_cli', content: '{}'),
        }, []),
      );

      expect(resultado.runs.map((r) => r.ok), [false, true]);
      expect(central.entregues, ['claude_cli']);
    });

    test('servidor que recusa a resposta e registrado como falha do agente', () async {
      final central = FakeCentral()..servidorRecusa = true;

      final resultado = await reviewWithSpecialists(
        quizId: 'quiz',
        service: central,
        checkAgents: () async => [agente('codex_cli')],
        runAgent: agentesQue({
          'codex_cli': const ConnectedAiResult(agentId: 'codex_cli', content: 'texto solto'),
        }, []),
      );

      expect(resultado.anyOk, isFalse);
      expect(resultado.quiz, isNull);
      expect(resultado.message, contains('Codex: falhou — revisão ilegível'));
    });

    test('so usa agente instalado e logado', () async {
      final central = FakeCentral();
      final prompts = <String>[];

      await reviewWithSpecialists(
        quizId: 'quiz',
        service: central,
        checkAgents: () async => [
          agente('codex_cli', logado: false),
          agente('claude_cli'),
        ],
        runAgent: agentesQue({
          'claude_cli': const ConnectedAiResult(agentId: 'claude_cli', content: '{}'),
        }, prompts),
      );

      expect(prompts, hasLength(1));
      expect(central.entregues, ['claude_cli']);
    });
  });

  test('resumo em palavras', () {
    expect(describeReviewSummary({'aprovada': 8, 'divergente': 1}),
        '8 aprovadas, 1 com divergência');
    expect(describeReviewSummary({'aprovada': 1}), '1 aprovada');
    expect(describeReviewSummary({'revisar': 2, 'sem_gabarito': 1}),
        '2 a revisar, 1 sem gabarito');
    expect(describeReviewSummary({}), '');
  });

  group('revisao na tela', () {
    Map<String, dynamic> pergunta({Map<String, dynamic>? revisao}) => {
          'id': 'q1',
          'tipo': 'multipla_escolha',
          'enunciado': 'Qual forma normal elimina dependencia transitiva?',
          'opcoes': [
            {'label': 'A', 'texto': '1FN', 'correta': false},
            {'label': 'B', 'texto': '3FN', 'correta': true},
          ],
          'verificado': revisao?['status'] == 'aprovada',
          'revisao': revisao,
        };

    Future<void> mostrar(
      WidgetTester tester,
      Map<String, dynamic> question, {
      void Function(Map<String, dynamic>)? onApply,
    }) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: QuestionReviewCard(
              number: 1,
              question: question,
              onApplySuggestion: onApply,
            ),
          ),
        ),
      ));
    }

    testWidgets('pergunta aprovada pelos dois mostra quem verificou', (tester) async {
      await mostrar(
        tester,
        pergunta(revisao: {
          'status': 'aprovada',
          'agentes': {
            'codex_cli': {'resposta': 'B', 'ancorada': true, 'problemas': []},
            'claude_cli': {'resposta': 'B', 'ancorada': true, 'problemas': []},
          },
        }),
      );

      expect(find.text('VERIFICADA · CODEX + CLAUDE'), findsOneWidget);
      expect(find.textContaining('confere com o gabarito'), findsNWidgets(2));
    });

    testWidgets('divergencia diz qual alternativa o agente achou e o que e o gabarito',
        (tester) async {
      await mostrar(
        tester,
        pergunta(revisao: {
          'status': 'divergente',
          'agentes': {
            'claude_cli': {
              'resposta': 'A',
              'ancorada': false,
              'problemas': ['a aula não trata de 1FN'],
            },
          },
        }),
      );

      expect(find.text('DIVERGÊNCIA DE GABARITO'), findsOneWidget);
      expect(find.textContaining('resolveu como A — o gabarito é B'), findsOneWidget);
      expect(find.textContaining('a aula não sustenta essa resposta'), findsOneWidget);
      expect(find.text('• a aula não trata de 1FN'), findsOneWidget);
    });

    testWidgets('sugestao do agente pode ser aplicada pelo professor', (tester) async {
      Map<String, dynamic>? aplicada;
      await mostrar(
        tester,
        pergunta(revisao: {
          'status': 'revisar',
          'agentes': {
            'codex_cli': {
              'resposta': 'B',
              'ancorada': true,
              'problemas': ['enunciado ambíguo'],
              'sugestao': {
                'enunciado': 'Qual forma normal remove dependência transitiva?',
                'opcoes': [
                  {'label': 'A', 'texto': '1FN', 'correta': false},
                  {'label': 'B', 'texto': '3FN', 'correta': true},
                ],
                'resposta_correta': 'B',
                'justificativa': '',
              },
            },
          },
        }),
        onApply: (sugestao) => aplicada = sugestao,
      );

      expect(find.text('Sugestão de Codex'), findsOneWidget);
      await tester.tap(find.text('APLICAR SUGESTÃO'));

      expect(aplicada?['enunciado'], 'Qual forma normal remove dependência transitiva?');
    });

    testWidgets('sem a revisao o aviso continua sendo o de nao verificada', (tester) async {
      await mostrar(tester, pergunta());

      expect(find.text('NÃO VERIFICADA'), findsOneWidget);
      expect(find.textContaining('Sugestão de'), findsNothing);
    });

    testWidgets('botao dos especialistas so existe quando ha como revisar', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SizedBox(
            height: 600,
            child: QuizPreview(
              questions: [pergunta()],
              requested: 1,
              attempts: const [],
            ),
          ),
        ),
      ));
      expect(find.text('REVISAR COM CODEX + CLAUDE'), findsNothing);

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SizedBox(
            height: 600,
            child: QuizPreview(
              questions: [pergunta()],
              requested: 1,
              attempts: const [],
              onSpecialistReview: (_) async => const SpecialistReviewOutcome(),
            ),
          ),
        ),
      ));
      expect(find.text('REVISAR COM CODEX + CLAUDE'), findsOneWidget);
    });

    testWidgets('depois de revisar, a lista mostra o veredito que o servidor devolveu',
        (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SizedBox(
            height: 700,
            width: 900,
            child: QuizPreview(
              questions: [pergunta()],
              requested: 1,
              attempts: const [],
              onSpecialistReview: (_) async => SpecialistReviewOutcome(
                runs: const [
                  SpecialistRun(agentId: 'codex_cli', label: 'Codex', ok: true),
                ],
                summary: const {'aprovada': 1},
                quiz: {
                  'questoes': [
                    pergunta(revisao: {
                      'status': 'aprovada',
                      'agentes': {
                        'codex_cli': {'resposta': 'B', 'ancorada': true, 'problemas': []},
                      },
                    }),
                  ],
                },
              ),
            ),
          ),
        ),
      ));
      expect(find.text('NÃO VERIFICADA'), findsOneWidget);

      await tester.tap(find.text('REVISAR COM CODEX + CLAUDE'));
      await tester.pumpAndSettle();

      expect(find.text('NÃO VERIFICADA'), findsNothing);
      expect(find.text('VERIFICADA · CODEX'), findsOneWidget);
      expect(find.textContaining('Codex: revisou · 1 aprovada'), findsOneWidget);
    });
  });
}

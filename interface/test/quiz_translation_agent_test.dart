/// Traducao de reserva das perguntas do quiz pelo agente do professor.
///
/// O servidor traduz com o provedor de IA do professor. Sem provedor (ou com ele
/// fora do ar) a turma que escolheu ingles ou espanhol lia a pergunta em
/// portugues; o painel do professor, que tem Codex e Claude conectados, assume.
library;

import 'dart:async';

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/connected_ai_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/services/quiz_translation_agent.dart';
import 'package:assistant_app/widgets/quiz_qrcode_monitor.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

ConnectedAiStatus agente(String id, {bool instalado = true, bool logado = true}) =>
    ConnectedAiStatus(
      id: id,
      label: ConnectedAiService.supportedAgents[id] ?? id,
      installed: instalado,
      authenticated: logado,
    );

class FakeCentral extends QuizCenterService {
  FakeCentral() : super(ApiService());

  final List<String> idiomasPedidos = [];
  final List<({String idioma, String conteudo})> entregues = [];

  /// Mensagens de erro do servidor para a proxima entrega, na ordem.
  final List<String> recusas = [];
  String? promptErro;

  @override
  Future<QuizTranslationPrompt> translationPrompt(
    String quizId,
    String language,
  ) async {
    idiomasPedidos.add(language);
    if (promptErro != null) throw QuizCenterException(promptErro!);
    return QuizTranslationPrompt(
      language: language,
      systemPrompt: 'sistema',
      prompt: 'traduza para $language',
      questionIds: const ['p1'],
    );
  }

  @override
  Future<Map<String, dynamic>> submitTranslation(
    String quizId, {
    required String language,
    required String content,
  }) async {
    if (recusas.isNotEmpty) throw QuizCenterException(recusas.removeAt(0));
    entregues.add((idioma: language, conteudo: content));
    return {'stored': 2, 'missing': 0};
  }
}

AgentRunner agentesQue(Map<String, ConnectedAiResult> respostas, List<String> ordem) {
  return ({
    required String agentId,
    required String prompt,
    required String systemPrompt,
    void Function(String activity)? onProgress,
  }) async {
    ordem.add(agentId);
    final resposta = respostas[agentId];
    if (resposta == null) throw Exception('sem resposta no teste');
    return resposta;
  };
}

typedef AgentRunner = Future<ConnectedAiResult> Function({
  required String agentId,
  required String prompt,
  required String systemPrompt,
  void Function(String activity)? onProgress,
});

void main() {
  group('translateWithAgent', () {
    test('sem agente conectado avisa o professor e nao chama o servidor', () async {
      final central = FakeCentral();

      final resultado = await translateWithAgent(
        quizId: 'quiz',
        language: 'en',
        service: central,
        checkAgents: () async => [
          agente('codex_cli', instalado: false),
          agente('claude_cli', logado: false),
        ],
      );

      expect(resultado.ok, isFalse);
      expect(resultado.noAgents, isTrue);
      expect(central.idiomasPedidos, isEmpty);
      expect(resultado.message, contains('Configurações > Agentes'));
    });

    test('o primeiro agente que o servidor aceita traduz, sem gastar o outro', () async {
      final central = FakeCentral();
      final ordem = <String>[];

      final resultado = await translateWithAgent(
        quizId: 'quiz',
        language: 'en',
        service: central,
        checkAgents: () async => [agente('codex_cli'), agente('claude_cli')],
        runAgent: agentesQue({
          'codex_cli': const ConnectedAiResult(agentId: 'codex_cli', content: '{"traducoes": []}'),
          'claude_cli': const ConnectedAiResult(agentId: 'claude_cli', content: 'nao deveria rodar'),
        }, ordem),
      );

      expect(resultado.ok, isTrue);
      expect(resultado.agentLabel, 'Codex');
      expect(resultado.stored, 2);
      expect(ordem, ['codex_cli']);
      expect(central.entregues.single.idioma, 'en');
      expect(central.entregues.single.conteudo, '{"traducoes": []}');
      expect(resultado.message, 'Traduzido para English por Codex.');
    });

    test('agente que falha passa a vez para o proximo', () async {
      final central = FakeCentral();
      final ordem = <String>[];

      final resultado = await translateWithAgent(
        quizId: 'quiz',
        language: 'es',
        service: central,
        checkAgents: () async => [agente('codex_cli'), agente('claude_cli')],
        runAgent: agentesQue({
          'codex_cli': const ConnectedAiResult(
            agentId: 'codex_cli',
            content: 'excedeu o limite de 6 minutos',
            isError: true,
          ),
          'claude_cli': const ConnectedAiResult(agentId: 'claude_cli', content: '{}'),
        }, ordem),
      );

      expect(ordem, ['codex_cli', 'claude_cli']);
      expect(resultado.ok, isTrue);
      expect(resultado.agentLabel, 'Claude');
      expect(resultado.message, contains('Español'));
    });

    test('traducao que o servidor recusa conta como falha do agente', () async {
      final central = FakeCentral()..recusas.add('alternativas não batem');
      final ordem = <String>[];

      final resultado = await translateWithAgent(
        quizId: 'quiz',
        language: 'en',
        service: central,
        checkAgents: () async => [agente('codex_cli'), agente('claude_cli')],
        runAgent: agentesQue({
          'codex_cli': const ConnectedAiResult(agentId: 'codex_cli', content: 'ruim'),
          'claude_cli': const ConnectedAiResult(agentId: 'claude_cli', content: 'boa'),
        }, ordem),
      );

      expect(ordem, ['codex_cli', 'claude_cli']);
      expect(resultado.agentLabel, 'Claude');
      expect(central.entregues.single.conteudo, 'boa');
    });

    test('todos falhando devolve o motivo de cada um', () async {
      final central = FakeCentral();

      final resultado = await translateWithAgent(
        quizId: 'quiz',
        language: 'en',
        service: central,
        checkAgents: () async => [agente('codex_cli'), agente('claude_cli')],
        runAgent: agentesQue({
          'codex_cli': const ConnectedAiResult(
              agentId: 'codex_cli', content: 'sem login', isError: true),
        }, []),
      );

      expect(resultado.ok, isFalse);
      expect(resultado.message, contains('Codex: sem login'));
      expect(resultado.message, contains('Claude: Exception: sem resposta no teste'));
    });

    test('tudo ja traduzido nao vira falha do agente', () async {
      final central = FakeCentral()
        ..promptErro = 'Todas as perguntas já estão traduzidas para este idioma.';
      final ordem = <String>[];

      final resultado = await translateWithAgent(
        quizId: 'quiz',
        language: 'en',
        service: central,
        checkAgents: () async => [agente('codex_cli')],
        runAgent: agentesQue({}, ordem),
      );

      expect(resultado.ok, isFalse);
      expect(ordem, isEmpty, reason: 'nenhum agente e chamado sem o que traduzir');
      expect(resultado.message, contains('já estão traduzidas'));
    });
  });

  test('le o aviso de traducao pendente do servidor', () {
    final lista = PendingTranslation.listFrom([
      {'language': 'en', 'students': 3, 'missing': 5, 'backend_failed': true},
      {'language': 'es', 'students': 1, 'missing': 2},
      {'students': 9},
      'lixo',
    ]);

    expect(lista.map((p) => p.language), ['en', 'es']);
    expect(lista.first.students, 3);
    expect(lista.first.backendFailed, isTrue);
    expect(lista.last.backendFailed, isFalse);
    expect(PendingTranslation.listFrom(null), isEmpty);
  });

  group('painel do professor', () {
    Map<String, dynamic> estatisticas(List<Map<String, dynamic>> pendentes,
            {String status = 'open'}) =>
        {
          'live_phase': 'lobby',
          'status': status,
          'participants': 2,
          'participants_online': 2,
          'participant_names': ['Ana', 'Bia'],
          'progress': {'total_answers': 0, 'correct': 0, 'incorrect': 0},
          'translations_pending': pendentes,
        };

    /// Relogio do painel nos testes: o de mentira do `pump` nao move
    /// `DateTime.now()`, entao as janelas de espera andam por aqui.
    var agora = DateTime(2026, 10, 1, 12);
    DateTime relogio() => agora;

    Future<void> passar(WidgetTester tester, Duration tempo) async {
      agora = agora.add(tempo);
      await tester.pump(tempo);
    }

    Future<void> abrir(
      WidgetTester tester,
      Map<String, dynamic> stats,
      TranslationRunner traduzir,
    ) async {
      agora = DateTime(2026, 10, 1, 12);
      tester.view.physicalSize = const Size(1000, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        theme: ThemeData.dark(),
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => QuizQRCodeMonitor(
                  quizId: 'quiz',
                  quizTitle: 'Modelagem',
                  totalQuestions: 2,
                  initialStats: stats,
                  autoConnect: false,
                  translator: traduzir,
                  now: relogio,
                ),
              ),
              child: const Text('abrir'),
            ),
          ),
        ),
      ));
      await tester.tap(find.text('abrir'));
      await tester.pump();
    }

    testWidgets('servidor que desistiu: o painel traduz na hora com o agente', (tester) async {
      final chamadas = <String>[];
      await abrir(
        tester,
        estatisticas([
          {'language': 'en', 'students': 2, 'missing': 3, 'backend_failed': true},
        ]),
        ({required quizId, required language, required onProgress}) async {
          chamadas.add(language);
          return const TranslationOutcome(ok: true, message: 'ok', agentLabel: 'Codex');
        },
      );

      await passar(tester, const Duration(seconds: 1));

      expect(chamadas, ['en']);
    });

    testWidgets('o servidor tem a primeira chance: o agente espera a janela', (tester) async {
      final chamadas = <String>[];
      await abrir(
        tester,
        estatisticas([
          {'language': 'es', 'students': 1, 'missing': 3, 'backend_failed': false},
        ]),
        ({required quizId, required language, required onProgress}) async {
          chamadas.add(language);
          return const TranslationOutcome(ok: true, message: 'ok');
        },
      );

      await passar(tester, const Duration(seconds: 1)); // painel ve o aviso pela 1a vez
      await passar(tester, const Duration(seconds: 10));
      expect(chamadas, isEmpty, reason: 'o servidor ainda pode estar traduzindo');

      await passar(tester, esperaDoServidorParaTraduzir);
      expect(chamadas, ['es']);
    });

    testWidgets('traducao gravada nao dispara outra enquanto o aviso velho ainda chega', (tester) async {
      final chamadas = <String>[];
      await abrir(
        tester,
        estatisticas([
          {'language': 'en', 'students': 2, 'missing': 3, 'backend_failed': true},
        ]),
        ({required quizId, required language, required onProgress}) async {
          chamadas.add(language);
          return const TranslationOutcome(ok: true, message: 'ok');
        },
      );

      await passar(tester, const Duration(seconds: 1));
      // O WebSocket ainda lista o idioma como pendente nos proximos segundos.
      await passar(tester, const Duration(seconds: 5));

      expect(chamadas, ['en']);
    });

    testWidgets('sem nada pendente o agente nao e chamado', (tester) async {
      final chamadas = <String>[];
      await abrir(
        tester,
        estatisticas(const []),
        ({required quizId, required language, required onProgress}) async {
          chamadas.add(language);
          return const TranslationOutcome(ok: true, message: 'ok');
        },
      );

      await passar(tester, const Duration(seconds: 30));

      expect(chamadas, isEmpty);
    });

    testWidgets('quiz encerrado nao gasta o agente', (tester) async {
      final chamadas = <String>[];
      await abrir(
        tester,
        estatisticas([
          {'language': 'en', 'students': 2, 'missing': 3, 'backend_failed': true},
        ], status: 'closed'),
        ({required quizId, required language, required onProgress}) async {
          chamadas.add(language);
          return const TranslationOutcome(ok: true, message: 'ok');
        },
      );

      await passar(tester, const Duration(seconds: 5));

      expect(chamadas, isEmpty);
    });

    testWidgets('falha avisa o professor e so tenta de novo depois da pausa', (tester) async {
      final chamadas = <String>[];
      await abrir(
        tester,
        estatisticas([
          {'language': 'en', 'students': 4, 'missing': 3, 'backend_failed': true},
        ]),
        ({required quizId, required language, required onProgress}) async {
          chamadas.add(language);
          return const TranslationOutcome(
            ok: false,
            message: 'Nenhum agente conectado.',
            noAgents: true,
          );
        },
      );

      await passar(tester, const Duration(seconds: 1));
      await passar(tester, const Duration(seconds: 1));

      expect(chamadas, ['en']);
      expect(
        find.textContaining('4 aluno(s) leem em English com a pergunta em português'),
        findsOneWidget,
      );
      expect(find.textContaining('Nenhum agente conectado.'), findsOneWidget);

      // Nao insiste a cada segundo: gastaria a conta do agente em loop.
      await passar(tester, const Duration(seconds: 30));
      expect(chamadas, ['en']);

      await passar(tester, pausaAposFalhaDeTraducao);
      expect(chamadas, ['en', 'en']);
    });

    testWidgets('enquanto traduz mostra o andamento, um idioma por vez', (tester) async {
      var chamadas = 0;
      final termino = Completer<TranslationOutcome>();
      await abrir(
        tester,
        estatisticas([
          {'language': 'en', 'students': 2, 'missing': 3, 'backend_failed': true},
        ]),
        ({required quizId, required language, required onProgress}) {
          chamadas++;
          onProgress('Codex traduzindo para English...');
          return termino.future;
        },
      );

      await passar(tester, const Duration(seconds: 1));
      await passar(tester, const Duration(seconds: 3));

      expect(chamadas, 1, reason: 'um idioma nao e traduzido duas vezes ao mesmo tempo');
      expect(find.text('Codex traduzindo para English...'), findsOneWidget);

      termino.complete(const TranslationOutcome(ok: true, message: 'ok'));
      await tester.pump();
    });
  });
}

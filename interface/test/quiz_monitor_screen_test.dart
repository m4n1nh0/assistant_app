/// A tela que o professor projeta durante o quiz.
///
/// Tres reclamacoes de aula real guiam estes testes:
///
/// - o professor nao conseguia ler a pergunta: o cartao era roxo claro e o texto
///   ficava na cor do tema escuro (cinza claro sobre roxo claro), e as
///   alternativas nem apareciam;
/// - o ranking entre perguntas mostrava so os pontos da pergunta, sem o acumulado;
/// - a tela nao maximizava, e a sala nao lia o texto de longe.
library;

import 'package:assistant_app/utils/theme.dart';
import 'package:assistant_app/widgets/quiz_qrcode_monitor.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> estatisticas({
  String fase = 'question',
  int? restante = 25,
  int prazo = 30,
  int indice = 0,
  int total = 3,
  List<Map<String, dynamic>>? ranking,
}) {
  final revelar = fase != 'question';
  return {
    'live_phase': fase,
    'status': 'open',
    'time_limit_seconds': prazo,
    'seconds_remaining': restante,
    'total_questions': total,
    'participants': 12,
    'participants_online': 12,
    'participant_names': ['Ana', 'Bia'],
    'progress': {'total_answers': 7, 'correct': 5, 'incorrect': 2},
    // No lobby e no fim nao ha pergunta aberta: o servidor manda `null`.
    'current_question': fase == 'lobby' || fase == 'finished'
        ? null
        : {
            'question_id': 'p1',
            'index': indice,
            'question_text': 'Qual forma normal elimina dependência transitiva?',
            'total_answers': 7,
            'options': [
              {'label': 'A', 'texto': '1FN', if (revelar) 'correta': false},
              {'label': 'B', 'texto': '3FN', if (revelar) 'correta': true},
              {'label': 'C', 'texto': '2FN', if (revelar) 'correta': false},
            ],
          },
    'ranking_top10': ranking ??
        [
          {
            'position': 1,
            'student_name': 'Bia',
            'score': 1200,
            'round_score': 800,
            'round_correct': true,
          },
          {
            'position': 2,
            'student_name': 'Ana',
            'score': 1000,
            'round_score': 100,
            'round_correct': true,
          },
          {
            'position': 3,
            'student_name': 'Caio',
            'score': 400,
            'round_score': 0,
            'round_correct': false,
          },
        ],
  };
}

Future<void> abrir(
  WidgetTester tester,
  Map<String, dynamic> stats, {
  Size tela = const Size(1000, 900),
}) async {
  tester.view.physicalSize = tela;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(MaterialApp(
    // Mesmo tema escuro do app, sem a fonte baixada da internet.
    theme: ThemeData.dark(),
    home: Scaffold(
      body: Builder(
        builder: (context) => Center(
          child: ElevatedButton(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (_) => QuizQRCodeMonitor(
                quizId: 'quiz',
                quizTitle: 'Modelagem',
                totalQuestions: 3,
                initialStats: stats,
                autoConnect: false,
              ),
            ),
            child: const Text('abrir'),
          ),
        ),
      ),
    ),
  ));
  await tester.tap(find.text('abrir'));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
}

/// Contraste WCAG entre duas cores; 4.5 e o minimo para texto corrido.
double contraste(Color a, Color b) {
  final la = a.computeLuminance();
  final lb = b.computeLuminance();
  final claro = la > lb ? la : lb;
  final escuro = la > lb ? lb : la;
  return (claro + 0.05) / (escuro + 0.05);
}

Text textoDe(WidgetTester tester, String conteudo) =>
    tester.widget<Text>(find.text(conteudo));

void main() {
  group('legibilidade da pergunta', () {
    testWidgets('mostra a pergunta e as alternativas, com texto legivel no cartao',
        (tester) async {
      await abrir(tester, estatisticas());

      expect(
        find.text('Qual forma normal elimina dependência transitiva?'),
        findsOneWidget,
      );
      for (final alternativa in ['1FN', '3FN', '2FN']) {
        expect(find.text(alternativa), findsOneWidget);
      }
      expect(find.text('Pergunta 1 de 3'), findsOneWidget);

      // O texto da pergunta usa a cor clara do tema escuro, sobre o cartao
      // escuro: o defeito era cinza claro sobre roxo claro.
      final pergunta =
          textoDe(tester, 'Qual forma normal elimina dependência transitiva?');
      expect(pergunta.style?.color, AssistantTheme.textPrimary);
      expect(
        contraste(pergunta.style!.color!, AssistantTheme.surface2),
        greaterThan(7),
      );
      final alternativa = textoDe(tester, '1FN');
      expect(
        contraste(alternativa.style!.color!, AssistantTheme.surface),
        greaterThan(7),
      );
    });

    testWidgets('com a pergunta aberta o gabarito nao aparece', (tester) async {
      await abrir(tester, estatisticas(fase: 'question'));

      expect(find.byIcon(Icons.check_circle), findsNothing);
    });

    testWidgets('ao encerrar, a alternativa correta fica destacada', (tester) async {
      await abrir(tester, estatisticas(fase: 'results', restante: null));

      expect(find.byIcon(Icons.check_circle), findsOneWidget);
    });
  });

  group('ranking com pontos acumulados', () {
    testWidgets('mostra o total de cada aluno e o que ele fez na pergunta', (tester) async {
      await abrir(tester, estatisticas(fase: 'results', restante: null));

      expect(find.text('Ranking · pontos acumulados'), findsOneWidget);
      expect(find.text('1200 pts'), findsOneWidget);
      expect(find.text('+800 nesta pergunta'), findsOneWidget);
      expect(find.text('+100 nesta pergunta'), findsOneWidget);
      expect(find.text('errou esta pergunta'), findsOneWidget);
      // Ana fez poucos pontos na pergunta, mas o total dela e o que a coloca em 2o.
      expect(find.text('1000 pts'), findsOneWidget);
    });

    testWidgets('o ranking final mostra o total sem repetir a rodada', (tester) async {
      await abrir(tester, estatisticas(fase: 'finished', restante: null));

      expect(find.text('Ranking Final'), findsWidgets);
      expect(find.text('1200 pts'), findsOneWidget);
      expect(find.textContaining('nesta pergunta'), findsNothing);
    });

    testWidgets('depois do ranking o professor chama a proxima pergunta', (tester) async {
      await abrir(tester, estatisticas(fase: 'results', restante: null));

      expect(find.text('Próxima Pergunta'), findsOneWidget);
      expect(find.text('Encerrar Agora'), findsNothing);
    });

    testWidgets('na ultima pergunta o botao leva ao ranking final', (tester) async {
      await abrir(
        tester,
        estatisticas(fase: 'results', restante: null, indice: 2, total: 3),
      );

      expect(find.text('Ver Ranking Final'), findsOneWidget);
      expect(find.text('Próxima Pergunta'), findsNothing);
    });
  });

  group('tempo por pergunta', () {
    testWidgets('o professor escolhe o prazo entre manual e varios tempos', (tester) async {
      await abrir(tester, estatisticas(fase: 'lobby', restante: null, prazo: 0));

      expect(find.text('Tempo por pergunta'), findsOneWidget);
      for (final rotulo in ['Manual', '15s', '30s', '1 min', '2 min', 'Outro...']) {
        expect(find.text(rotulo), findsOneWidget, reason: rotulo);
      }
      expect(
        find.text('Manual: a pergunta fica aberta até você encerrar.'),
        findsOneWidget,
      );
    });

    testWidgets('com prazo definido avisa que a pergunta fecha sozinha', (tester) async {
      await abrir(tester, estatisticas(fase: 'lobby', restante: null, prazo: 30));

      expect(find.textContaining('a pergunta fecha sozinha'), findsOneWidget);
    });

    testWidgets('mostra o relogio no cabecalho enquanto a pergunta esta aberta',
        (tester) async {
      await abrir(tester, estatisticas(fase: 'question', restante: 25));

      expect(find.text('0:25'), findsOneWidget);
      // Com prazo, o professor ainda pode encerrar antes.
      expect(find.text('Encerrar Agora'), findsOneWidget);
    });

    testWidgets('sem prazo nao ha relogio e o botao e o de encerrar na mao', (tester) async {
      await abrir(
        tester,
        estatisticas(fase: 'question', restante: null, prazo: 0),
      );

      expect(find.byIcon(Icons.timer_outlined), findsOneWidget,
          reason: 'so o do seletor; o relogio do cabecalho nao existe');
      expect(find.text('Encerrar Pergunta'), findsOneWidget);
    });
  });

  group('tela maximizada', () {
    testWidgets('o botao maximiza, aumenta as letras e poe o QR Code ao lado',
        (tester) async {
      await abrir(tester, estatisticas(), tela: const Size(1500, 900));

      final antes =
          textoDe(tester, 'Qual forma normal elimina dependência transitiva?')
              .style!
              .fontSize!;
      expect(find.byTooltip('Maximizar a tela'), findsOneWidget);

      await tester.tap(find.byTooltip('Maximizar a tela'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      final depois =
          textoDe(tester, 'Qual forma normal elimina dependência transitiva?')
              .style!
              .fontSize!;
      expect(depois, greaterThan(antes * 1.4));
      expect(find.byTooltip('Sair da tela cheia'), findsOneWidget);

      // Em tela larga a pergunta fica a esquerda e o QR Code a direita.
      final pergunta = tester.getTopLeft(
        find.text('Qual forma normal elimina dependência transitiva?'),
      );
      final qr = tester.getTopLeft(find.text('📱 Escanear para responder'));
      expect(qr.dx, greaterThan(pergunta.dx + 400));
      expect(tester.takeException(), isNull);
    });

    testWidgets('voltar do modo maximizado restaura o tamanho normal', (tester) async {
      await abrir(tester, estatisticas(), tela: const Size(1500, 900));
      const pergunta = 'Qual forma normal elimina dependência transitiva?';
      final normal = textoDe(tester, pergunta).style!.fontSize!;

      await tester.tap(find.byTooltip('Maximizar a tela'));
      await tester.pump(const Duration(milliseconds: 300));
      await tester.tap(find.byTooltip('Sair da tela cheia'));
      await tester.pump(const Duration(milliseconds: 300));

      expect(textoDe(tester, pergunta).style!.fontSize, normal);
    });

    testWidgets('em tela pequena a pergunta vem antes do QR Code depois que o quiz comeca',
        (tester) async {
      await abrir(tester, estatisticas(fase: 'question'));

      final pergunta = tester.getTopLeft(
        find.text('Qual forma normal elimina dependência transitiva?'),
      );
      final qr = tester.getTopLeft(find.text('📱 Escanear para responder'));
      expect(pergunta.dy, lessThan(qr.dy));
    });

    testWidgets('no lobby o QR Code vem primeiro, e o que a turma precisa escanear',
        (tester) async {
      await abrir(tester, estatisticas(fase: 'lobby', restante: null));

      final qr = tester.getTopLeft(find.text('📱 Escanear para responder'));
      final lobby = tester.getTopLeft(find.text('Lobby do Quiz'));
      expect(qr.dy, lessThan(lobby.dy));
    });
  });
}

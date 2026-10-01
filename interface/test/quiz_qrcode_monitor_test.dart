/// O monitor do quiz ao vivo, quando o professor manda um comando.
///
/// O defeito veio de aula real: o professor clicava "Iniciar Quiz", a pergunta
/// abria de verdade para a turma, mas a tela dele continuava mostrando o lobby
/// e o mesmo botao. Ele clicava de novo e cada clique avancava mais uma
/// pergunta, jogando a turma adiante sem ninguem ter respondido.
library;

import 'package:assistant_app/widgets/quiz_qrcode_monitor.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> respostaDoComando({
  required String fase,
  String? perguntaAtual,
}) =>
    {
      'id': 'q1',
      'status': 'open',
      'live_phase': fase,
      'current_question_id': perguntaAtual,
      'questoes': [
        {'id': 'p1', 'enunciado': 'Primeira pergunta?'},
        {'id': 'p2', 'enunciado': 'Segunda pergunta?'},
      ],
    };

const lobby = {
  'live_phase': 'lobby',
  'current_question_id': null,
  'status': 'open',
  'participants': 3,
  'progress': {'total_answers': 0},
};

void main() {
  test('iniciar o quiz muda a fase na hora, sem esperar o WebSocket', () {
    final depois = mesclarQuizAoVivo(
      lobby,
      respostaDoComando(fase: 'question', perguntaAtual: 'p1'),
    )!;

    expect(depois['live_phase'], 'question');
    expect(depois['current_question_id'], 'p1');
    expect(depois['current_question']['index'], 0);
    expect(depois['current_question']['question_text'], 'Primeira pergunta?');
  });

  test('a pergunta nova comeca com zero respostas', () {
    final emAndamento = mesclarQuizAoVivo(
      lobby,
      respostaDoComando(fase: 'question', perguntaAtual: 'p1'),
    )!;
    emAndamento['current_question']['total_answers'] = 7;

    final proxima = mesclarQuizAoVivo(
      emAndamento,
      respostaDoComando(fase: 'question', perguntaAtual: 'p2'),
    )!;

    expect(proxima['current_question']['index'], 1);
    expect(proxima['current_question']['total_answers'], 0);
  });

  test('encerrar a pergunta mantem os numeros que o WebSocket ja trouxe', () {
    final depois = mesclarQuizAoVivo(
      lobby,
      respostaDoComando(fase: 'results', perguntaAtual: 'p1'),
    )!;

    expect(depois['live_phase'], 'results');
    expect(depois['participants'], 3);
  });

  test('sem pergunta aberta a tela nao mostra pergunta atual', () {
    final depois = mesclarQuizAoVivo(
      lobby,
      respostaDoComando(fase: 'finished'),
    )!;

    expect(depois['live_phase'], 'finished');
    expect(depois['current_question'], isNull);
  });

  test('resposta sem fase nao mexe na tela', () {
    expect(mesclarQuizAoVivo(lobby, {'id': 'q1'}), isNull);
    expect(mesclarQuizAoVivo(lobby, 'erro'), isNull);
  });

  test('funciona antes do primeiro pacote do WebSocket', () {
    final depois = mesclarQuizAoVivo(
      null,
      respostaDoComando(fase: 'question', perguntaAtual: 'p1'),
    )!;

    expect(depois['live_phase'], 'question');
    expect(depois['progress'], isNotNull);
  });

  group('alternativas e prazo no painel do professor', () {
    Map<String, dynamic> comAlternativas(String fase, {int? restante}) => {
          'id': 'q1',
          'status': 'open',
          'live_phase': fase,
          'current_question_id': 'p1',
          'time_limit_seconds': 30,
          'seconds_remaining': restante,
          'questoes': [
            {
              'id': 'p1',
              'enunciado': 'Qual forma elimina dependencia transitiva?',
              'opcoes': [
                {'label': 'A', 'texto': '1FN', 'correta': false},
                {'label': 'B', 'texto': '3FN', 'correta': true},
              ],
            },
          ],
        };

    test('mostra as alternativas, mas nao entrega o gabarito com a pergunta aberta',
        () {
      final depois =
          mesclarQuizAoVivo(lobby, comAlternativas('question', restante: 28))!;

      final opcoes = depois['current_question']['options'] as List;
      expect(opcoes.map((o) => o['texto']), ['1FN', '3FN']);
      // O painel costuma estar projetado: o gabarito so aparece ao encerrar.
      expect(opcoes.every((o) => !(o as Map).containsKey('correta')), isTrue);
    });

    test('revela o gabarito quando a pergunta encerra', () {
      final depois = mesclarQuizAoVivo(lobby, comAlternativas('results'))!;

      final opcoes = depois['current_question']['options'] as List;
      expect(opcoes.map((o) => o['correta']), [false, true]);
    });

    test('carrega o prazo e os segundos que faltam', () {
      final depois =
          mesclarQuizAoVivo(lobby, comAlternativas('question', restante: 28))!;

      expect(depois['time_limit_seconds'], 30);
      expect(depois['seconds_remaining'], 28);
    });

    test('sem prazo na resposta, mantem o que a tela ja tinha', () {
      final base = {...lobby, 'time_limit_seconds': 45};
      final resposta = respostaDoComando(fase: 'question', perguntaAtual: 'p1');

      final depois = mesclarQuizAoVivo(base, resposta)!;

      expect(depois['time_limit_seconds'], 45);
      expect(depois['seconds_remaining'], isNull);
    });
  });

  group('formatacao do tempo', () {
    test('rotulo do tempo por pergunta', () {
      expect(formatarTempoPorPergunta(0), 'Manual');
      expect(formatarTempoPorPergunta(15), '15s');
      expect(formatarTempoPorPergunta(60), '1 min');
      expect(formatarTempoPorPergunta(90), '1 min 30s');
      expect(formatarTempoPorPergunta(120), '2 min');
    });

    test('relogio da pergunta', () {
      expect(formatarRelogio(45), '0:45');
      expect(formatarRelogio(65), '1:05');
      expect(formatarRelogio(0), '0:00');
      expect(formatarRelogio(-3), '0:00');
    });

    test('o professor pode escolher manual e prazos de 15s a 2 min', () {
      expect(tempoPorPerguntaOpcoes.first, 0);
      expect(tempoPorPerguntaOpcoes, containsAll([15, 30, 60, 120]));
    });
  });
}

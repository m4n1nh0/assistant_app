/// O card que mostra o que o assistente leu do banco.
///
/// Ele nasceu de uma conversa em que o assistente disse não ter acesso às
/// questões e pediu que o usuário as colasse. Agora ele lê -- e o card existe
/// para o usuário conferir o dado em vez de confiar na releitura do modelo.
library;

import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/widgets/tool_read_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> montar(WidgetTester tester, ToolReadResult result) =>
    tester.pumpWidget(MaterialApp(
      home: Scaffold(body: ToolReadCard(result: result)),
    ));

void main() {
  testWidgets('banco de questões mostra enunciado e como abrir', (tester) async {
    await montar(
      tester,
      const ToolReadResult(
        tool: 'education_search_question_bank',
        kind: 'question_bank',
        title: '2 questão(oes)',
        total: 2,
        items: [
          {
            'enunciado': 'O que e uma entidade?',
            'dificuldade': 'medio',
            'disciplina': 'BANCO DE DADOS',
            'quiz': 'Quiz de Modelagem',
          },
          {'enunciado': 'Quando aplicar a 3FN?', 'dificuldade': 'dificil'},
        ],
      ),
    );

    expect(find.text('2 questão(oes)'), findsOneWidget);
    expect(find.text('O que e uma entidade?'), findsOneWidget);
    expect(find.text('Abrir banco'), findsOneWidget);
    // A procedência é o ponto do card: sem ela o número parece coisa do modelo.
    expect(find.text('lido do seu cadastro'), findsOneWidget);
  });

  testWidgets('diz quantas linhas ficaram de fora', (tester) async {
    await montar(
      tester,
      ToolReadResult(
        tool: 'education_list_students',
        kind: 'students',
        title: '40 aluno(s)',
        total: 40,
        truncated: true,
        items: List.generate(
          8,
          (index) => {'nome': 'Aluno $index', 'turma': '3001'},
        ),
      ),
    );

    // Cinco linhas na tela, e o resto contado a partir do total do banco --
    // não do tamanho da lista que coube na resposta.
    expect(find.text('Aluno 4'), findsOneWidget);
    expect(find.text('Aluno 5'), findsNothing);
    expect(find.text('+35 no seu cadastro'), findsOneWidget);
  });

  testWidgets('leitura de tipo desconhecido aparece sem botão', (tester) async {
    await montar(
      tester,
      const ToolReadResult(
        tool: 'education_algo_novo',
        kind: 'coisa_nova',
        title: 'Consulta',
        total: 1,
        items: [{'nome': 'Linha qualquer'}],
      ),
    );

    expect(find.text('Linha qualquer'), findsOneWidget);
    expect(find.byIcon(Icons.open_in_new), findsNothing);
  });

  testWidgets('resultado de quiz mostra o ranking', (tester) async {
    await montar(
      tester,
      const ToolReadResult(
        tool: 'education_get_quiz_results',
        kind: 'quiz_results',
        title: 'Resultado de Quiz de Modelagem',
        total: 2,
        items: [
          {'posicao': 1, 'aluno': 'Ana', 'pontos': 900, 'acertos': 1,
           'respostas': 1},
          {'posicao': 2, 'aluno': 'Bruno', 'pontos': 0, 'acertos': 0,
           'respostas': 1},
        ],
      ),
    );

    expect(find.text('1. Ana'), findsOneWidget);
    expect(find.text('900 pts · 1/1 acertos'), findsOneWidget);
  });
}

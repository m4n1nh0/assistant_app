import 'package:assistant_app/utils/theme.dart';
import 'package:assistant_app/widgets/study_time_dashboard.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Este painel é projetado para a turma. O que se cobra aqui é que ele diga de
/// que conjunto está falando: quem ficou de fora do ranking, o que a cor
/// significa e o que a planilha não conta.
void main() {
  List<Map<String, dynamic>> turma(int quantos) => [
        for (var i = 1; i <= quantos; i++)
          {
            'discipline_code': 'ARA0058',
            'student_id': 'a$i',
            'student_name': 'Aluno $i',
            'minutes': (quantos - i + 1) * 60,
          }
      ];

  Future<void> abrir(WidgetTester tester, List<Map<String, dynamic>> records) async {
    tester.view.physicalSize = const Size(1900, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      theme: AssistantTheme.darkTheme,
      home: StudyTimeDashboard(records: records, title: 'Minhas disciplinas'),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('declara que o ranking é recorte e quanto ficou de fora',
      (tester) async {
    await abrir(tester, turma(13));

    expect(find.text('10 de 13'), findsOneWidget);
    expect(find.textContaining('Os demais 3 somam'), findsOneWidget);
  });

  testWidgets('ranking curto diz o total em vez de fingir recorte',
      (tester) async {
    await abrir(tester, turma(4));

    expect(find.text('4 no total'), findsOneWidget);
    expect(find.textContaining('Os demais'), findsNothing);
  });

  testWidgets('tem legenda das cores e o aviso sobre a planilha',
      (tester) async {
    await abrir(tester, turma(6));

    expect(find.text('Tempo do aluno ou da disciplina'), findsOneWidget);
    expect(find.text('Quantidade de alunos na faixa'), findsOneWidget);
    expect(find.textContaining('vazio não é zero'), findsOneWidget);
  });

  testWidgets('mostra mediana e concentração, não só o total', (tester) async {
    await abrir(tester, turma(5));

    expect(find.text('Mediana por aluno'), findsOneWidget);
    expect(find.text('Concentração nos 5 primeiros'), findsOneWidget);
    expect(find.text('Distribuição da turma'), findsOneWidget);
  });

  testWidgets('registro sem aluno é destacado, não escondido', (tester) async {
    await abrir(tester, [
      ...turma(3),
      {
        'discipline_code': 'ARA0058',
        'student_id': null,
        'student_name': null,
        'minutes': 120,
      },
    ]);

    expect(find.text('Sem aluno no cadastro'), findsOneWidget);
    expect(find.text('contam no total, ficam fora do ranking'), findsOneWidget);
  });

  testWidgets('sem registros não tenta desenhar gráfico', (tester) async {
    await abrir(tester, []);

    expect(find.text('Não há registros para o filtro escolhido.'), findsOneWidget);
  });

  testWidgets('nome longo de aluno não estoura a barra', (tester) async {
    await abrir(tester, [
      {
        'discipline_code': 'ARA0058',
        'student_id': 'a1',
        'student_name': 'HENRI JOSE SOBRAL DE ALCANTARA MENDONCA DA SILVA FILHO',
        'minutes': 712,
      },
    ]);

    expect(tester.takeException(), isNull);
  });
}

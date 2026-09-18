import 'package:assistant_app/services/study_time_stats.dart';
import 'package:assistant_app/utils/theme.dart';
import 'package:assistant_app/widgets/study_time_charts.dart';
import 'package:assistant_app/widgets/study_time_dashboard.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Este painel é projetado para a turma e serve para perguntar, não só para
/// olhar. O que se cobra aqui: que ele diga de que conjunto fala, que o clique
/// recorte a tela inteira e que a turma mostrada seja a do cadastro do
/// professor, nunca a sequência da planilha.
void main() {
  Map<String, dynamic> registro({
    required String id,
    required String nome,
    required int minutos,
    String turma = '3001 Presencial',
    String disciplina = 'ARA0058',
  }) =>
      {
        'discipline_code': disciplina,
        'group_sequence': '15034853',
        'student_id': id,
        'student_name': nome,
        'class_label': turma,
        'minutes': minutos,
      };

  List<Map<String, dynamic>> turma(int quantos, {String nome = '3001 Presencial'}) => [
        for (var i = 1; i <= quantos; i++)
          registro(
            id: '$nome-a$i',
            nome: 'Aluno $i de $nome',
            minutos: (quantos - i + 1) * 60,
            turma: nome,
          )
      ];

  Future<void> abrir(
    WidgetTester tester,
    List<Map<String, dynamic>> records, {
    StudyTimeFilter filter = const StudyTimeFilter(),
  }) async {
    tester.view.physicalSize = const Size(1900, 1040);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      theme: AssistantTheme.darkTheme,
      home: StudyTimeDashboard(
        records: records,
        title: 'Minhas disciplinas',
        initialFilter: filter,
      ),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('cada aluno mostra a turma do cadastro', (tester) async {
    await abrir(tester, turma(3));

    expect(find.text('3001 Presencial'), findsWidgets);
    expect(find.text('15034853'), findsNothing,
        reason: 'a sequência da planilha não agrupa nada aqui');
  });

  testWidgets('declara quanto ficou fora do topo, sem precisar rolar',
      (tester) async {
    await abrir(tester, turma(13));

    expect(find.text('10 de 13'), findsOneWidget);
    expect(find.textContaining('Os demais 3 somam'), findsOneWidget);
  });

  testWidgets('ver todos abre o ranking inteiro', (tester) async {
    await abrir(tester, turma(13));

    await tester.tap(find.text('VER TODOS'));
    await tester.pumpAndSettle();

    expect(find.text('13 no total, do maior para o menor'), findsOneWidget);
    expect(find.textContaining('Os demais'), findsNothing);
  });

  testWidgets('ranking curto não finge ser recorte', (tester) async {
    await abrir(tester, turma(4));

    expect(find.text('4 no total, do maior para o menor'), findsOneWidget);
    expect(find.text('VER TODOS'), findsNothing);
  });

  testWidgets('clicar na turma da legenda recorta a tela inteira',
      (tester) async {
    await abrir(tester, [
      ...turma(3, nome: '3001 Presencial'),
      ...turma(2, nome: '3002 Semipresencial'),
    ]);
    expect(find.text('Aluno 1 de 3001 Presencial'), findsOneWidget);

    await tester.tap(find.descendant(
      of: find.byType(StudyTimeLegend),
      matching: find.text('3002 Semipresencial'),
    ));
    await tester.pumpAndSettle();

    expect(find.text('LIMPAR FILTROS'), findsOneWidget);
    expect(find.text('Aluno 1 de 3001 Presencial'), findsNothing,
        reason: 'a tela inteira acompanha a fatia escolhida');
    expect(find.text('2 no total, do maior para o menor'), findsOneWidget);
  });

  testWidgets('clicar de novo na mesma turma desfaz o recorte', (tester) async {
    await abrir(tester, [
      ...turma(3, nome: '3001 Presencial'),
      ...turma(2, nome: '3002 Semipresencial'),
    ]);
    final alvo = find.descendant(
      of: find.byType(StudyTimeLegend),
      matching: find.text('3002 Semipresencial'),
    );

    await tester.tap(alvo);
    await tester.pumpAndSettle();
    await tester.tap(alvo);
    await tester.pumpAndSettle();

    expect(find.text('LIMPAR FILTROS'), findsNothing);
    expect(find.text('Aluno 1 de 3001 Presencial'), findsWidgets);
  });

  testWidgets('clicar numa faixa deixa só os alunos dela', (tester) async {
    await abrir(tester, [
      registro(id: 'a1', nome: 'Muito', minutos: 700),
      registro(id: 'a2', nome: 'Pouco', minutos: 30),
    ]);

    await tester.tap(find.text('Menos de 1 h'));
    await tester.pumpAndSettle();

    expect(find.text('Pouco'), findsOneWidget);
    expect(find.text('Muito'), findsNothing);
  });

  testWidgets('recorte vazio explica em vez de mostrar tela em branco',
      (tester) async {
    await abrir(
      tester,
      turma(3),
      filter: const StudyTimeFilter(discipline: 'ARA9999'),
    );

    expect(find.textContaining('Nenhum registro neste recorte'), findsOneWidget);
  });

  testWidgets('abre no recorte que a aba já tinha', (tester) async {
    await abrir(
      tester,
      [
        ...turma(3, nome: '3001 Presencial'),
        ...turma(2, nome: '3002 Semipresencial'),
      ],
      filter: const StudyTimeFilter(classLabel: '3002 Semipresencial'),
    );

    expect(find.text('Aluno 1 de 3001 Presencial'), findsNothing);
    expect(find.text('Aluno 1 de 3002 Semipresencial'), findsOneWidget);
  });

  testWidgets('registro sem aluno é destacado e fica sem turma',
      (tester) async {
    await abrir(tester, [
      ...turma(3),
      {
        'discipline_code': 'ARA0058',
        'group_sequence': '15034853',
        'student_id': null,
        'student_name': null,
        'class_label': '',
        'minutes': 120,
      },
    ]);

    expect(find.text('Sem aluno no cadastro'), findsOneWidget);
    expect(find.text('contam no total, ficam fora do ranking'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(StudyTimeLegend),
        matching: find.text(semTurma),
      ),
      findsOneWidget,
    );
  });

  testWidgets('mostra mediana, concentração e distribuição', (tester) async {
    await abrir(tester, turma(5));

    expect(find.text('Mediana por aluno'), findsOneWidget);
    expect(find.text('Concentração nos 5 primeiros'), findsOneWidget);
    expect(find.text('Distribuição da turma'), findsOneWidget);
    expect(find.byType(StudyTimeDonut), findsOneWidget);
  });

  testWidgets('sem registros não tenta desenhar gráfico', (tester) async {
    await abrir(tester, []);

    expect(find.text('Não há registros para o filtro escolhido.'), findsOneWidget);
    expect(find.byType(StudyTimeDonut), findsNothing);
  });

  testWidgets('nome longo de aluno não estoura a barra', (tester) async {
    await abrir(tester, [
      registro(
        id: 'a1',
        nome: 'HENRI JOSE SOBRAL DE ALCANTARA MENDONCA DA SILVA FILHO',
        minutos: 712,
      ),
    ]);

    expect(tester.takeException(), isNull);
  });
}

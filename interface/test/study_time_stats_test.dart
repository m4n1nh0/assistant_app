import 'package:assistant_app/services/study_time_stats.dart';
import 'package:flutter_test/flutter_test.dart';

/// O painel de tempo de estudo e projetado para a turma. Numero errado ali e
/// numero errado na frente de todo mundo, entao as contas ficam aqui.
void main() {
  Map<String, dynamic> linha({
    String disciplina = 'ARA0058',
    String? alunoId,
    String? aluno,
    required int minutos,
  }) =>
      {
        'discipline_code': disciplina,
        'student_id': alunoId,
        'student_name': aluno,
        'minutes': minutos,
      };

  test('soma por aluno junta os registros do mesmo aluno', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Gledson', minutos: 400),
      linha(alunoId: 'a1', aluno: 'Gledson', minutos: 312),
      linha(alunoId: 'a2', aluno: 'Victor', minutos: 451),
    ]);

    expect(stats.students.first.label, 'Gledson');
    expect(stats.students.first.minutes, 712);
    expect(stats.studentCount, 2);
    expect(stats.recordCount, 3, reason: 'registros nao viram alunos');
  });

  test('a fatia de cada um soma 1 quando todos tem aluno', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Gledson', minutos: 300),
      linha(alunoId: 'a2', aluno: 'Victor', minutos: 100),
    ]);

    expect(stats.students.first.share, closeTo(0.75, 0.001));
    expect(stats.students.last.share, closeTo(0.25, 0.001));
  });

  test('matricula sem aluno entra no total mas fica fora do ranking', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Gledson', minutos: 300),
      linha(minutos: 100),
    ]);

    expect(stats.totalMinutes, 400);
    expect(stats.studentCount, 1);
    expect(stats.unlinkedRecords, 1);
    expect(stats.students.first.share, closeTo(0.75, 0.001),
        reason: 'a fatia e do total, senao o ranking mente sobre o todo');
  });

  test('mediana nao se deixa levar pelo aluno que estudou muito', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Um', minutos: 1200),
      linha(alunoId: 'a2', aluno: 'Dois', minutos: 60),
      linha(alunoId: 'a3', aluno: 'Tres', minutos: 30),
    ]);

    expect(stats.medianMinutes, 60);
    expect(stats.averageMinutesPerRecord, 430);
  });

  test('mediana com numero par de alunos e a media dos dois do meio', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Um', minutos: 100),
      linha(alunoId: 'a2', aluno: 'Dois', minutos: 60),
      linha(alunoId: 'a3', aluno: 'Tres', minutos: 40),
      linha(alunoId: 'a4', aluno: 'Quatro', minutos: 20),
    ]);

    expect(stats.medianMinutes, 50);
  });

  test('concentracao mostra quanto os primeiros respondem do total', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Um', minutos: 700),
      linha(alunoId: 'a2', aluno: 'Dois', minutos: 200),
      linha(alunoId: 'a3', aluno: 'Tres', minutos: 100),
    ]);

    expect(stats.topShare(2), closeTo(0.9, 0.001));
    expect(stats.minutesBeyond(2), 100);
    expect(stats.minutesBeyond(5), 0, reason: 'nao ha quarto aluno');
  });

  test('faixas separam quem quase nao estudou de quem estudou muito', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Um', minutos: 30),
      linha(alunoId: 'a2', aluno: 'Dois', minutos: 90),
      linha(alunoId: 'a3', aluno: 'Tres', minutos: 240),
      linha(alunoId: 'a4', aluno: 'Quatro', minutos: 400),
      linha(alunoId: 'a5', aluno: 'Cinco', minutos: 712),
    ]);

    expect(
      {for (final faixa in stats.bands) faixa.label: faixa.students},
      {
        'Menos de 1 h': 1,
        'De 1 h a 3 h': 1,
        'De 3 h a 6 h': 1,
        '6 h ou mais': 2,
      },
    );
  });

  test('limite da faixa pertence a faixa de cima', () {
    final stats = StudyTimeStats.fromRecords([
      linha(alunoId: 'a1', aluno: 'Um', minutos: 60),
      linha(alunoId: 'a2', aluno: 'Dois', minutos: 59),
    ]);

    final faixas = {for (final faixa in stats.bands) faixa.label: faixa.students};
    expect(faixas['Menos de 1 h'], 1, reason: '59 min ainda e menos de 1 h');
    expect(faixas['De 1 h a 3 h'], 1, reason: '60 min ja e 1 h');
  });

  test('lista vazia nao divide por zero', () {
    final stats = StudyTimeStats.fromRecords([]);

    expect(stats.totalMinutes, 0);
    expect(stats.averageMinutesPerRecord, 0);
    expect(stats.topShare(), 0);
    expect(stats.bands, isEmpty);
  });
}

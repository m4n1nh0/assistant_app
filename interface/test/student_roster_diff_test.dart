import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/services/student_csv_parser.dart';
import 'package:assistant_app/utils/student_roster_diff.dart';

Student _aluno(String nome, String? matricula, {bool active = true}) => Student(
      id: 'id-${matricula ?? nome}',
      name: nome,
      externalId: matricula,
      classGroup: '3001',
      discipline: 'ARA0040',
      active: active,
    );

StudentCsvRow _linha(String matricula, String nome) =>
    StudentCsvRow(enrollment: matricula, name: nome);

void main() {
  test('separa novos, mantidos e ausentes pela matricula', () {
    final diff = diffRoster(
      roster: [
        _aluno('Ana Silva', '1001'),
        _aluno('Bruno Lima', '1002'),
        _aluno('Carla Souza', '1003'),
      ],
      file: [
        _linha('1001', 'ANA SILVA'),
        _linha('1002', 'Bruno Lima'),
        _linha('1004', 'Diego Rocha'),
      ],
    );

    expect(diff.kept.map((r) => r.enrollment), ['1001', '1002']);
    expect(diff.incoming.map((r) => r.enrollment), ['1004']);
    expect(diff.missing.map((m) => m.student.name), ['Carla Souza']);
  });

  test('matricula casa mesmo com espaco e caixa diferentes', () {
    final diff = diffRoster(
      roster: [_aluno('Ana', ' 1001 ')],
      file: [_linha('1001', 'Ana')],
    );

    expect(diff.kept, hasLength(1));
    expect(diff.missing, isEmpty);
  });

  test('nome diferente com a mesma matricula nao vira aluno novo', () {
    // O SIA manda "ADRIAN DA COSTA RAMOS" e o cadastro tem "Adrian Ramos":
    // comparar por nome criaria um duplicado e marcaria o original como ausente.
    final diff = diffRoster(
      roster: [_aluno('Adrian Ramos', '202603348491')],
      file: [_linha('202603348491', 'ADRIAN DA COSTA RAMOS')],
    );

    expect(diff.incoming, isEmpty);
    expect(diff.missing, isEmpty);
    expect(diff.kept.single.name, 'ADRIAN DA COSTA RAMOS');
  });

  test('aluno sem matricula nunca entra na lista de ausentes', () {
    // Cadastro manual antigo nao pode ser desativado so porque a planilha,
    // que fala por matricula, nao tem como mencionar ele.
    final diff = diffRoster(
      roster: [_aluno('Sem Matricula', null), _aluno('Ana', '1001')],
      file: [_linha('1001', 'Ana')],
    );

    expect(diff.missing, isEmpty);
    expect(diff.unmatchable.single.name, 'Sem Matricula');
  });

  test('aluno ja desativado nao volta como ausente', () {
    final diff = diffRoster(
      roster: [_aluno('Saiu', '2002', active: false), _aluno('Ana', '1001')],
      file: [_linha('1001', 'Ana')],
    );

    expect(diff.missing, isEmpty);
    expect(diff.kept, hasLength(1));
  });

  test('arquivo igual a turma nao muda nada', () {
    final diff = diffRoster(
      roster: [_aluno('Ana', '1001'), _aluno('Bruno', '1002')],
      file: [_linha('1001', 'Ana'), _linha('1002', 'Bruno')],
    );

    expect(diff.changesNothing, isTrue);
    expect(diff.kept, hasLength(2));
  });

  test('turma vazia: tudo do arquivo e novo', () {
    final diff = diffRoster(
      roster: const [],
      file: [_linha('1001', 'Ana'), _linha('1002', 'Bruno')],
    );

    expect(diff.incoming, hasLength(2));
    expect(diff.missing, isEmpty);
  });
}

import 'package:assistant_app/models/group_class.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:flutter_test/flutter_test.dart';

ClassGroup _class(
  String id,
  String code,
  String name,
  List<int> days, {
  String disciplineId = 'd1',
}) =>
    ClassGroup(
      id: id,
      code: code,
      name: name,
      discipline: 'BANCO DE DADOS',
      label: '$code $name'.trim(),
      disciplineId: disciplineId,
      schedules: [for (final day in days) ClassSchedule(weekday: day)],
    );

final _segunda = _class('c-seg', '3001', 'Presencial', [0]);
final _quinta = _class('c-qui', '3002', 'Semipresencial', [3]);

void main() {
  group('classDisplay', () {
    test('mostra o nome e o dia de aula', () {
      expect(classDisplay(_segunda), '3001 Presencial · segunda');
    });

    test('junta os dias com vírgula e "e"', () {
      expect(classDisplay(_class('x', '3001', 'A', [0, 3])),
          '3001 A · segunda e quinta');
      expect(classDisplay(_class('x', '3001', 'A', [0, 2, 4])),
          '3001 A · segunda, quarta e sexta');
    });

    test('sem horário cadastrado sai só o nome', () {
      expect(classDisplay(_class('x', '3001', 'A', [])), '3001 A');
    });

    test('ignora dia fora da semana e repetido', () {
      expect(classDisplay(_class('x', '3001', 'A', [3, 3, 9])), '3001 A · quinta');
    });
  });

  group('classesOfDiscipline', () {
    test('só as da disciplina, na ordem do primeiro dia de aula', () {
      final result = classesOfDiscipline([
        _quinta,
        _class('outra', '9', 'Cloud', [0], disciplineId: 'd2'),
        _segunda,
      ], 'd1');
      expect(result.map((item) => item.id), ['c-seg', 'c-qui']);
    });

    test('sem disciplina escolhida não há turma', () {
      expect(classesOfDiscipline([_segunda], null), isEmpty);
    });

    test('turma sem horário vai para o fim', () {
      final result = classesOfDiscipline(
          [_class('sem', '1', 'X', []), _quinta, _segunda], 'd1');
      expect(result.last.id, 'sem');
    });
  });

  group('inferClassFromListText', () {
    final classes = [_segunda, _quinta];

    test('a lista da segunda aponta para a turma da segunda', () {
      expect(
        inferClassFromListText('Grupos turma segunda:\nGRUPO 1\n- Ana', classes)?.id,
        'c-seg',
      );
    });

    test('entende quinta-feira, maiúsculas e acento', () {
      expect(
        inferClassFromListText('GRUPOS DA TURMA DE QUINTA-FEIRA\nGRUPO 1\nAna', classes)?.id,
        'c-qui',
      );
      expect(
        inferClassFromListText('Terça\nGRUPO 1\nAna', [_class('t', '1', 'T', [1])])?.id,
        't',
      );
    });

    test('o código da turma vale mais que o dia', () {
      expect(
        inferClassFromListText('Turma 3002 (segunda?)\nGRUPO 1\nAna', classes)?.id,
        'c-qui',
      );
    });

    test('em dúvida não escolhe: dois dias citados', () {
      expect(
        inferClassFromListText('Segunda e quinta\nGRUPO 1\nAna', classes),
        isNull,
      );
    });

    test('em dúvida não escolhe: dia que duas turmas têm', () {
      final duas = [_segunda, _class('c2', '3003', 'Noite', [0])];
      expect(inferClassFromListText('Segunda\nGRUPO 1\nAna', duas), isNull);
    });

    test('sem título nem turma, devolve nulo', () {
      expect(inferClassFromListText('GRUPO 1\n- Ana', classes), isNull);
      expect(inferClassFromListText('Segunda\nGRUPO 1', const []), isNull);
    });

    test('só olha antes do primeiro grupo: nome de aluno não conta', () {
      expect(
        inferClassFromListText('GRUPO 1\n- Quinta Feira da Silva', classes),
        isNull,
      );
    });
  });

  group('filterGroupsByClass', () {
    final groups = [
      {'name': 'GRUPO 1', 'class_id': 'c-seg'},
      {'name': 'GRUPO 1', 'class_id': 'c-qui'},
      {'name': 'GRUPO 7', 'class_id': null},
      {'name': 'GRUPO 8'},
    ];

    test('sem filtro vêm todos', () {
      expect(filterGroupsByClass(groups, null), hasLength(4));
    });

    test('por turma', () {
      expect(filterGroupsByClass(groups, 'c-qui').single['class_id'], 'c-qui');
    });

    test('"sem turma" pega nulo e ausente', () {
      expect(filterGroupsByClass(groups, noClassFilter).map((g) => g['name']),
          ['GRUPO 7', 'GRUPO 8']);
    });
  });
}

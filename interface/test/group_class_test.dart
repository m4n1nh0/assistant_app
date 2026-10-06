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

  group('inferClassesFromListText', () {
    final classes = [_segunda, _quinta];
    List<String> ids(String text, List<ClassGroup> list) =>
        inferClassesFromListText(text, list).map((item) => item.id).toList();

    test('a lista da segunda aponta para a turma da segunda', () {
      expect(ids('Grupos turma segunda:\nGRUPO 1\n- Ana', classes), ['c-seg']);
    });

    test('entende quinta-feira, maiúsculas e acento', () {
      expect(ids('GRUPOS DA TURMA DE QUINTA-FEIRA\nGRUPO 1\nAna', classes), ['c-qui']);
      expect(ids('Terça\nGRUPO 1\nAna', [_class('t', '1', 'T', [1])]), ['t']);
    });

    test('o código da turma vale mais que o dia', () {
      expect(ids('Turma 3002 (segunda?)\nGRUPO 1\nAna', classes), ['c-qui']);
    });

    test('dois códigos citados sugerem as duas turmas', () {
      expect(ids('Turmas 3001 e 3002\nGRUPO 1\nAna', classes), ['c-seg', 'c-qui']);
    });

    test('aula reunida: o dia que duas turmas têm sugere as duas', () {
      final duas = [_segunda, _class('c2', '3003', 'Noite', [0]), _quinta];
      expect(ids('Segunda\nGRUPO 1\nAna', duas), ['c-seg', 'c2']);
    });

    test('em dúvida não sugere: dois dias citados', () {
      expect(ids('Segunda e quinta\nGRUPO 1\nAna', classes), isEmpty);
    });

    test('sem título nem turma, devolve vazio', () {
      expect(ids('GRUPO 1\n- Ana', classes), isEmpty);
      expect(ids('Segunda\nGRUPO 1', const []), isEmpty);
    });

    test('dia sem nenhuma turma, devolve vazio', () {
      expect(ids('Sexta\nGRUPO 1\nAna', classes), isEmpty);
    });

    test('só olha antes do primeiro grupo: nome de aluno não conta', () {
      expect(ids('GRUPO 1\n- Quinta Feira da Silva', classes), isEmpty);
    });
  });

  group('groupClassIds', () {
    test('usa class_ids quando o servidor manda', () {
      expect(groupClassIds({'class_ids': ['a', 'b'], 'class_id': 'a'}), ['a', 'b']);
    });

    test('servidor antigo: só a turma principal', () {
      expect(groupClassIds({'class_id': 'a'}), ['a']);
    });

    test('lista vazia e class_id vazio ou ausente é sem turma', () {
      expect(groupClassIds({'class_ids': [], 'class_id': null}), isEmpty);
      expect(groupClassIds({'class_id': ''}), isEmpty);
      expect(groupClassIds({}), isEmpty);
    });

    test('ignora id vazio dentro da lista', () {
      expect(groupClassIds({'class_ids': ['', 'a']}), ['a']);
    });
  });

  group('filterGroupsByClass', () {
    final groups = [
      {'name': 'GRUPO 1', 'class_id': 'c-seg', 'class_ids': ['c-seg']},
      {'name': 'GRUPO 1', 'class_id': 'c-qui'},
      {'name': 'GRUPO 3', 'class_id': 'c-seg', 'class_ids': ['c-seg', 'c-qui']},
      {'name': 'GRUPO 7', 'class_id': null},
      {'name': 'GRUPO 8'},
    ];

    test('sem filtro vêm todos', () {
      expect(filterGroupsByClass(groups, null), hasLength(5));
    });

    test('por turma, com o grupo de aula reunida em cada uma das suas turmas', () {
      expect(filterGroupsByClass(groups, {'c-qui'}).map((g) => g['name']),
          ['GRUPO 1', 'GRUPO 3']);
      expect(filterGroupsByClass(groups, {'c-seg'}).map((g) => g['name']),
          ['GRUPO 1', 'GRUPO 3']);
    });

    test('"sem turma" pega nulo e ausente', () {
      expect(filterGroupsByClass(groups, {noClassFilter}).map((g) => g['name']),
          ['GRUPO 7', 'GRUPO 8']);
    });

    test('varias turmas juntas: grupos de qualquer uma, sem repetir', () {
      expect(filterGroupsByClass(groups, {'c-seg', 'c-qui'}).map((g) => g['name']),
          ['GRUPO 1', 'GRUPO 1', 'GRUPO 3']);
    });

    test('turma e "sem turma" juntas', () {
      expect(
          filterGroupsByClass(groups, {'c-qui', noClassFilter}).map((g) => g['name']),
          ['GRUPO 1', 'GRUPO 3', 'GRUPO 7', 'GRUPO 8']);
    });

    test('conjunto vazio é "todas"', () {
      expect(filterGroupsByClass(groups, <String>{}), hasLength(5));
    });
  });

  group('turmas de hoje', () {
    // 05/10/2026 é segunda; 08/10 é quinta; 07/10 é quarta.
    const segunda = 1, quarta = 3, quinta = 4;

    test('nome do dia por extenso, a partir do weekday do Dart', () {
      expect(weekdayLabel(1), 'segunda-feira');
      expect(weekdayLabel(4), 'quinta-feira');
      expect(weekdayLabel(6), 'sábado');
      expect(weekdayLabel(7), 'domingo');
    });

    test('separa as turmas que têm aula hoje das outras', () {
      final split = splitClassesByDay([_segunda, _quinta], segunda);

      expect(split.today.map((item) => item.id), ['c-seg']);
      expect(split.others.map((item) => item.id), ['c-qui']);
    });

    test('num dia sem aula, todas ficam em "outras"', () {
      final split = splitClassesByDay([_segunda, _quinta], quarta);

      expect(split.today, isEmpty);
      expect(split.others, hasLength(2));
    });

    test('turma com dois dias de aula conta nos dois', () {
      final dupla = _class('dupla', '3004', 'Dupla', [0, 3]);

      expect(splitClassesByDay([dupla], segunda).today, hasLength(1));
      expect(splitClassesByDay([dupla], quinta).today, hasLength(1));
      expect(splitClassesByDay([dupla], quarta).today, isEmpty);
    });

    test('mantém a ordem em que as turmas chegaram', () {
      final a = _class('a', '1', 'A', [0]);
      final b = _class('b', '2', 'B', [0]);

      expect(splitClassesByDay([b, a], segunda).today.map((item) => item.id), ['b', 'a']);
    });

    test('a turma de hoje já vem escolhida', () {
      expect(defaultClassFilter([_segunda, _quinta], segunda), {'c-seg'});
      expect(defaultClassFilter([_segunda, _quinta], quinta), {'c-qui'});
    });

    test('duas turmas no mesmo dia vêm escolhidas juntas (o grupo é do dia)', () {
      expect(
        defaultClassFilter(
            [_segunda, _class('c2', '3003', 'Noite', [0]), _quinta], segunda),
        {'c-seg', 'c2'},
      );
    });

    test('sem turma hoje, ou sem turmas, fica "todas" (vazio)', () {
      expect(defaultClassFilter([_segunda, _quinta], quarta), isEmpty);
      expect(defaultClassFilter(const [], segunda), isEmpty);
    });

    test('turma sem horário cadastrado nunca é "de hoje"', () {
      final sem = _class('sem', '9', 'Sem horário', []);
      expect(splitClassesByDay([sem], segunda).today, isEmpty);
      expect(defaultClassFilter([sem], segunda), isEmpty);
    });
  });
}

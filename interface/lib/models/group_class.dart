/// A turma (o dia de aula) a que um grupo de projeto pertence.
///
/// Disciplina com duas turmas, uma na segunda e outra na quinta, tem "GRUPO 1" nas
/// duas. O grupo pertence a uma turma, e é ela que diz o dia. Aqui ficam as contas
/// que a tela precisa: o rótulo da turma, quais turmas a disciplina tem e a turma
/// que a própria lista colada já anuncia ("Grupos turma segunda").
library;

import '../services/education_service.dart';

const _weekdayNames = [
  'segunda',
  'terça',
  'quarta',
  'quinta',
  'sexta',
  'sábado',
  'domingo',
];

/// Filtro "grupos sem turma", como o servidor o entende.
const noClassFilter = 'none';

String _joinDays(List<String> days) {
  if (days.length <= 1) return days.join();
  return '${days.sublist(0, days.length - 1).join(', ')} e ${days.last}';
}

/// "3001 Presencial · segunda e quinta"; sem horário cadastrado, só o nome.
String classDisplay(ClassGroup item) {
  final name = [item.code.trim(), item.name.trim()]
      .where((part) => part.isNotEmpty)
      .join(' ');
  final label = name.isNotEmpty
      ? name
      : item.label.trim().isNotEmpty
          ? item.label.trim()
          : 'turma';
  final days = (item.schedules.map((row) => row.weekday).toSet().toList()..sort())
      .where((day) => day >= 0 && day < 7)
      .map((day) => _weekdayNames[day])
      .toList();
  return days.isEmpty ? label : '$label · ${_joinDays(days)}';
}

/// Turmas de uma disciplina, na ordem do primeiro dia de aula.
List<ClassGroup> classesOfDiscipline(
  List<ClassGroup> all,
  String? disciplineId,
) {
  if (disciplineId == null) return const [];
  int firstDay(ClassGroup item) => item.schedules.isEmpty
      ? 99
      : item.schedules.map((row) => row.weekday).reduce((a, b) => a < b ? a : b);
  return all.where((item) => item.disciplineId == disciplineId).toList()
    ..sort((a, b) {
      final byDay = firstDay(a).compareTo(firstDay(b));
      return byDay != 0 ? byDay : a.code.compareTo(b.code);
    });
}

String _fold(String text) {
  const from = 'áàâãäéèêëíìîïóòôõöúùûüç';
  const to = 'aaaaaeeeeiiiiooooouuuuc';
  final buffer = StringBuffer();
  for (final char in text.toLowerCase().split('')) {
    final index = from.indexOf(char);
    buffer.write(index >= 0 ? to[index] : char);
  }
  return buffer.toString();
}

final _groupHeader = RegExp(r'^\s*grupo\s+\d+', caseSensitive: false);

final _weekdayPatterns = <int, RegExp>{
  0: RegExp(r'\bsegunda\b'),
  1: RegExp(r'\bterca\b'),
  2: RegExp(r'\bquarta\b'),
  3: RegExp(r'\bquinta\b'),
  4: RegExp(r'\bsexta\b'),
  5: RegExp(r'\bsabado\b'),
  6: RegExp(r'\bdomingo\b'),
};

/// A turma que o texto colado já anuncia, ou `null` quando não dá para ter certeza.
///
/// Olha só o que vem antes do primeiro "GRUPO 1" ("Grupos turma segunda:"): é o
/// título que o professor escreve, e os nomes dos alunos não têm nada a ver com dia
/// de aula. Vale o código da turma (3002) e, depois, o dia da semana - mas só se
/// apontar para uma turma única. Em dúvida, não escolhe: quem decide é o professor.
ClassGroup? inferClassFromListText(String text, List<ClassGroup> classes) {
  final context = <String>[];
  for (final line in text.split('\n')) {
    if (_groupHeader.hasMatch(line)) break;
    context.add(line);
  }
  final head = _fold(context.join(' '));
  if (head.trim().isEmpty || classes.isEmpty) return null;

  final byCode = classes
      .where((item) =>
          item.code.trim().isNotEmpty &&
          RegExp('\\b${RegExp.escape(_fold(item.code.trim()))}\\b').hasMatch(head))
      .toList();
  if (byCode.length == 1) return byCode.single;

  final days = [
    for (final entry in _weekdayPatterns.entries)
      if (entry.value.hasMatch(head)) entry.key,
  ];
  if (days.length != 1) return null;
  final byDay = classes
      .where((item) => item.schedules.any((row) => row.weekday == days.single))
      .toList();
  return byDay.length == 1 ? byDay.single : null;
}

/// Grupos de uma turma; `null` é "todas" e [noClassFilter] são os sem turma.
List<Map<String, dynamic>> filterGroupsByClass(
  List<Map<String, dynamic>> groups,
  String? filter,
) {
  if (filter == null) return groups;
  return groups.where((group) {
    final classId = (group['class_id'] ?? '').toString();
    return filter == noClassFilter ? classId.isEmpty : classId == filter;
  }).toList();
}

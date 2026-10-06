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

/// As turmas que o texto colado já anuncia; vazio quando não dá para ter certeza.
///
/// Olha só o que vem antes do primeiro "GRUPO 1" ("Grupos turma segunda:"): é o
/// título que o professor escreve, e os nomes dos alunos não têm nada a ver com dia
/// de aula. Valem os códigos de turma citados (3002, 3030) e, sem eles, o dia da
/// semana, desde que seja um só: todas as turmas que têm aula nesse dia, porque duas
/// turmas na mesma aula costumam ter grupos que misturam os alunos das duas. É só uma
/// sugestão: quem confirma é o professor.
List<ClassGroup> inferClassesFromListText(String text, List<ClassGroup> classes) {
  final context = <String>[];
  for (final line in text.split('\n')) {
    if (_groupHeader.hasMatch(line)) break;
    context.add(line);
  }
  final head = _fold(context.join(' '));
  if (head.trim().isEmpty || classes.isEmpty) return const [];

  final byCode = classes
      .where((item) =>
          item.code.trim().isNotEmpty &&
          RegExp('\\b${RegExp.escape(_fold(item.code.trim()))}\\b').hasMatch(head))
      .toList();
  if (byCode.isNotEmpty) return byCode;

  final days = [
    for (final entry in _weekdayPatterns.entries)
      if (entry.value.hasMatch(head)) entry.key,
  ];
  if (days.length != 1) return const [];
  return classes
      .where((item) => item.schedules.any((row) => row.weekday == days.single))
      .toList();
}

/// Turmas de um grupo. Aula reunida tem mais de uma; os grupos antigos, nenhuma.
///
/// Vale `class_ids`; sem ele (servidor antigo), a turma principal `class_id`.
List<String> groupClassIds(Map<String, dynamic> group) {
  final ids = group['class_ids'];
  if (ids is List) {
    final found = [
      for (final item in ids)
        if ('$item'.isNotEmpty) '$item',
    ];
    if (found.isNotEmpty) return found;
  }
  final single = (group['class_id'] ?? '').toString();
  return single.isEmpty ? const [] : [single];
}

/// Grupos das turmas escolhidas; vazio (ou `null`) é "todas".
///
/// Com várias turmas entram os grupos de qualquer uma delas, e [noClassFilter] junta
/// os grupos sem turma. O grupo de aula reunida aparece em cada uma das suas turmas.
List<Map<String, dynamic>> filterGroupsByClass(
  List<Map<String, dynamic>> groups,
  Iterable<String>? filter,
) {
  final wanted = filter?.toSet() ?? const <String>{};
  if (wanted.isEmpty) return groups;
  return groups.where((group) {
    final ids = groupClassIds(group);
    if (ids.isEmpty) return wanted.contains(noClassFilter);
    return ids.any(wanted.contains);
  }).toList();
}

const _weekdayFullNames = [
  'segunda-feira',
  'terça-feira',
  'quarta-feira',
  'quinta-feira',
  'sexta-feira',
  'sábado',
  'domingo',
];

/// Nome do dia a partir do `DateTime.weekday` (segunda = 1).
String weekdayLabel(int dartWeekday) =>
    _weekdayFullNames[(dartWeekday - 1).clamp(0, 6)];

/// As turmas separadas em "de hoje" e "outras", como a aba Gravar faz.
///
/// Uma turma é "de hoje" quando tem aula no dia da semana (`DateTime.weekday`,
/// segunda = 1). Cada lista mantém a ordem recebida.
({List<ClassGroup> today, List<ClassGroup> others}) splitClassesByDay(
  List<ClassGroup> classes,
  int dartWeekday,
) =>
    (
      today: classes.where((item) => item.meetsOn(dartWeekday)).toList(),
      others: classes.where((item) => !item.meetsOn(dartWeekday)).toList(),
    );

/// As turmas que já vêm marcadas ao abrir uma disciplina: todas as que têm aula hoje.
///
/// O grupo é do dia, e as turmas do mesmo dia (3002 e 3030, na segunda) dividem os
/// grupos, então as duas vêm marcadas juntas. Sem aula hoje, vazio: "todas".
Set<String> defaultClassFilter(List<ClassGroup> classes, int dartWeekday) =>
    splitClassesByDay(classes, dartWeekday).today.map((item) => item.id).toSet();

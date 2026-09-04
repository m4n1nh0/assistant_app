/// Comparacao entre a lista da turma e o arquivo importado.
///
/// A importacao deixou de ser "manda tudo e torce": antes de aplicar, a tela
/// mostra o que vai mudar. O que responde a pergunta que o professor faz na
/// hora - *o que este arquivo vai fazer com a minha turma?* - e a separacao em
/// novos, mantidos e ausentes.
///
/// A matricula e a chave. Nome muda de caixa, ganha e perde acento, vem
/// abreviado num sistema e completo em outro; matricula e estavel.
library;

import '../services/education_service.dart';
import '../services/student_csv_parser.dart';

/// Um aluno da turma que nao veio no arquivo.
class MissingStudent {
  final Student student;

  const MissingStudent(this.student);

  String get label => student.externalId?.trim().isNotEmpty == true
      ? '${student.name} (${student.externalId})'
      : student.name;
}

/// O que a importacao vai fazer com a turma.
class RosterDiff {
  /// Matriculas do arquivo que a turma ainda nao tem.
  final List<StudentCsvRow> incoming;

  /// Matriculas presentes nos dois lados: o nome e atualizado.
  final List<StudentCsvRow> kept;

  /// Alunos ativos da turma que ficaram de fora do arquivo.
  final List<MissingStudent> missing;

  /// Alunos sem matricula cadastrada, que nao dao para comparar.
  final List<Student> unmatchable;

  const RosterDiff({
    required this.incoming,
    required this.kept,
    required this.missing,
    required this.unmatchable,
  });

  bool get isEmpty =>
      incoming.isEmpty && kept.isEmpty && missing.isEmpty;

  /// True quando o arquivo nao acrescenta nem altera nada.
  bool get changesNothing => incoming.isEmpty && missing.isEmpty;
}

/// Compara a turma com o arquivo.
///
/// Aluno ja desativado fica de fora: ele nao aparece na turma, e reaparecer na
/// lista de ausentes a cada importacao seria ruido.
RosterDiff diffRoster({
  required List<Student> roster,
  required List<StudentCsvRow> file,
}) {
  final fileByEnrollment = <String, StudentCsvRow>{
    for (final row in file) _key(row.enrollment): row,
  };

  final incoming = <StudentCsvRow>[];
  final kept = <StudentCsvRow>[];
  final missing = <MissingStudent>[];
  final unmatchable = <Student>[];

  final rosterKeys = <String>{};
  for (final student in roster) {
    if (!student.active) continue;
    final key = _key(student.externalId ?? '');
    if (key.isEmpty) {
      // Sem matricula nao da para provar ausencia: cadastro manual antigo nao
      // pode ser desativado so porque a planilha nao o menciona.
      unmatchable.add(student);
      continue;
    }
    rosterKeys.add(key);
    if (!fileByEnrollment.containsKey(key)) {
      missing.add(MissingStudent(student));
    }
  }

  for (final row in file) {
    if (rosterKeys.contains(_key(row.enrollment))) {
      kept.add(row);
    } else {
      incoming.add(row);
    }
  }

  return RosterDiff(
    incoming: incoming,
    kept: kept,
    missing: missing,
    unmatchable: unmatchable,
  );
}

String _key(String enrollment) => enrollment.trim().toLowerCase();

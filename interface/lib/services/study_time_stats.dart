/// Leitura dos tempos de estudo importados da planilha.
///
/// Separado da tela porque a mesma conta aparece em dois lugares - a aba e o
/// painel de projetar em sala - e porque numero que o professor mostra para a
/// turma precisa de teste, nao de conferencia no olho.
///
/// Duas regras que vem do proprio import e mudam o que pode ser dito aqui:
/// linha com tempo vazio nao e importada (vazio nao e zero), e matricula sem
/// aluno no cadastro entra no total mas nao tem nome. Por isso o ranking por
/// aluno soma menos que o total, e a diferenca e declarada em vez de escondida.
library;

/// Uma linha do ranking: disciplina ou aluno, com o quanto representa do total.
class StudyTimeEntry {
  final String label;
  final int minutes;

  /// Fracao do total geral, de 0 a 1. Serve tanto para o texto quanto para a
  /// largura da barra, que assim medem a mesma coisa.
  final double share;

  const StudyTimeEntry({
    required this.label,
    required this.minutes,
    required this.share,
  });

  double get hours => minutes / 60;
}

/// Uma faixa de dedicacao e quantos alunos caem nela.
class StudyTimeBand {
  final String label;
  final int students;

  const StudyTimeBand({required this.label, required this.students});
}

/// O que da para afirmar sobre um conjunto de registros de tempo de estudo.
class StudyTimeStats {
  final int totalMinutes;
  final int recordCount;
  final int linkedRecords;
  final int unlinkedRecords;

  /// Ranking por aluno cadastrado, do maior para o menor.
  final List<StudyTimeEntry> students;

  /// Ranking por disciplina, do maior para o menor.
  final List<StudyTimeEntry> disciplines;

  /// Mediana dos minutos por aluno. Diz mais que a media quando um aluno sozinho
  /// puxa o total para cima, que e o caso comum numa turma.
  final int medianMinutes;

  /// Distribuicao dos alunos por faixa de dedicacao.
  final List<StudyTimeBand> bands;

  const StudyTimeStats({
    required this.totalMinutes,
    required this.recordCount,
    required this.linkedRecords,
    required this.unlinkedRecords,
    required this.students,
    required this.disciplines,
    required this.medianMinutes,
    required this.bands,
  });

  static const empty = StudyTimeStats(
    totalMinutes: 0,
    recordCount: 0,
    linkedRecords: 0,
    unlinkedRecords: 0,
    students: [],
    disciplines: [],
    medianMinutes: 0,
    bands: [],
  );

  factory StudyTimeStats.fromRecords(List<Map<String, dynamic>> records) {
    if (records.isEmpty) return empty;

    var total = 0;
    var linked = 0;
    final byDiscipline = <String, int>{};
    final byStudent = <String, int>{};
    final nameOf = <String, String>{};

    for (final row in records) {
      final minutes = (row['minutes'] as num?)?.toInt() ?? 0;
      total += minutes;

      final code = '${row['discipline_code'] ?? ''}';
      if (code.isNotEmpty) {
        byDiscipline[code] = (byDiscipline[code] ?? 0) + minutes;
      }

      final id = row['student_id'];
      final name = row['student_name'];
      if (id != null && name != null) {
        linked++;
        final key = '$id';
        byStudent[key] = (byStudent[key] ?? 0) + minutes;
        nameOf[key] = '$name';
      }
    }

    List<StudyTimeEntry> rank(Map<String, int> counted, String Function(String) label) {
      final entries = counted.entries
          .map((entry) => StudyTimeEntry(
                label: label(entry.key),
                minutes: entry.value,
                share: total == 0 ? 0 : entry.value / total,
              ))
          .toList()
        ..sort((a, b) => b.minutes.compareTo(a.minutes));
      return entries;
    }

    final students = rank(byStudent, (key) => nameOf[key] ?? key);

    return StudyTimeStats(
      totalMinutes: total,
      recordCount: records.length,
      linkedRecords: linked,
      unlinkedRecords: records.length - linked,
      students: students,
      disciplines: rank(byDiscipline, (key) => key),
      medianMinutes: _median(students.map((s) => s.minutes).toList()),
      bands: _bands(students),
    );
  }

  /// Quantos alunos distintos aparecem com nome.
  int get studentCount => students.length;

  double get totalHours => totalMinutes / 60;

  /// Media por registro - a conta que a aba ja mostrava.
  int get averageMinutesPerRecord =>
      recordCount == 0 ? 0 : (totalMinutes / recordCount).round();

  /// Fatia do total concentrada nos [count] alunos que mais estudaram.
  ///
  /// E a leitura que interessa ao professor: se poucos alunos respondem por
  /// quase tudo, a media da turma esta escondendo o resto dela.
  double topShare([int count = 5]) {
    if (totalMinutes == 0 || students.isEmpty) return 0;
    final soma = students
        .take(count)
        .fold<int>(0, (sum, entry) => sum + entry.minutes);
    return soma / totalMinutes;
  }

  /// Minutos que sobram fora dos [count] primeiros do ranking de alunos.
  int minutesBeyond(int count) => students.length <= count
      ? 0
      : students.skip(count).fold<int>(0, (sum, entry) => sum + entry.minutes);

  static int _median(List<int> values) {
    if (values.isEmpty) return 0;
    final ordered = [...values]..sort();
    final meio = ordered.length ~/ 2;
    if (ordered.length.isOdd) return ordered[meio];
    return ((ordered[meio - 1] + ordered[meio]) / 2).round();
  }

  static List<StudyTimeBand> _bands(List<StudyTimeEntry> students) {
    if (students.isEmpty) return const [];
    const limites = <String, int>{
      'Menos de 1 h': 60,
      'De 1 h a 3 h': 180,
      'De 3 h a 6 h': 360,
    };
    final contagem = {for (final nome in limites.keys) nome: 0};
    var acima = 0;
    for (final aluno in students) {
      final faixa = limites.entries
          .where((limite) => aluno.minutes < limite.value)
          .map((limite) => limite.key)
          .firstOrNull;
      if (faixa == null) {
        acima++;
      } else {
        contagem[faixa] = contagem[faixa]! + 1;
      }
    }
    return [
      for (final nome in limites.keys)
        StudyTimeBand(label: nome, students: contagem[nome]!),
      StudyTimeBand(label: '6 h ou mais', students: acima),
    ];
  }
}

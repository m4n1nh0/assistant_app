/// Leitura dos tempos de estudo importados da planilha.
///
/// Separado da tela porque a mesma conta aparece em tres lugares - a aba, o
/// painel de projetar em sala e os filtros que os dois compartilham - e porque
/// numero que o professor mostra para a turma precisa de teste, nao de
/// conferencia no olho.
///
/// Tres regras vem do proprio import e mudam o que pode ser dito aqui: linha
/// com tempo vazio nao e importada (vazio nao e zero); matricula sem aluno no
/// cadastro entra no total mas nao tem nome nem turma; e a turma da planilha
/// ("15034853") nao e a turma do professor ("3001"), entao agrupar por turma so
/// funciona pelo aluno, nunca pela sequencia do arquivo.
library;

/// Rotulo usado quando o registro nao chega a uma turma do cadastro.
const semTurma = 'Sem turma no cadastro';

/// Uma linha de ranking: disciplina, turma ou aluno.
class StudyTimeEntry {
  /// Chave estavel: id do aluno, codigo da disciplina ou rotulo da turma.
  final String id;

  final String label;

  /// Turma do cadastro a que a linha pertence, quando faz sentido. Vazio nas
  /// linhas que ja sao turma ou disciplina.
  final String group;

  final int minutes;

  /// Fracao do total geral, de 0 a 1. Serve para o texto e para a barra, que
  /// assim medem a mesma coisa.
  final double share;

  const StudyTimeEntry({
    required this.id,
    required this.label,
    required this.minutes,
    required this.share,
    this.group = '',
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

  /// Ranking pela turma do cadastro - nao pela sequencia da planilha.
  final List<StudyTimeEntry> classes;

  /// Mediana dos minutos por aluno. Diz mais que a media quando um aluno sozinho
  /// puxa o total para cima, que e o caso comum numa turma.
  final int medianMinutes;

  /// Distribuicao dos alunos por faixa de dedicacao.
  final List<StudyTimeBand> bands;

  /// Faixa de cada aluno, para o clique numa faixa poder filtrar a tela.
  final Map<String, String> bandByStudent;

  const StudyTimeStats({
    required this.totalMinutes,
    required this.recordCount,
    required this.linkedRecords,
    required this.unlinkedRecords,
    required this.students,
    required this.disciplines,
    required this.classes,
    required this.medianMinutes,
    required this.bands,
    required this.bandByStudent,
  });

  static const empty = StudyTimeStats(
    totalMinutes: 0,
    recordCount: 0,
    linkedRecords: 0,
    unlinkedRecords: 0,
    students: [],
    disciplines: [],
    classes: [],
    medianMinutes: 0,
    bands: [],
    bandByStudent: {},
  );

  /// Limites das faixas, em minutos. O valor do limite pertence a faixa de cima.
  static const bandLimits = <String, int>{
    'Menos de 1 h': 60,
    'De 1 h a 3 h': 180,
    'De 3 h a 6 h': 360,
  };
  static const topBand = '6 h ou mais';

  /// Em que faixa cai um aluno com [minutes] minutos.
  static String bandOf(int minutes) {
    for (final limite in bandLimits.entries) {
      if (minutes < limite.value) return limite.key;
    }
    return topBand;
  }

  /// A turma do cadastro de um registro, ou [semTurma].
  static String classOf(Map<String, dynamic> row) {
    final label = '${row['class_label'] ?? ''}'.trim();
    return label.isEmpty ? semTurma : label;
  }

  factory StudyTimeStats.fromRecords(List<Map<String, dynamic>> records) {
    if (records.isEmpty) return empty;

    var total = 0;
    var linked = 0;
    final byDiscipline = <String, int>{};
    final byClass = <String, int>{};
    final byStudent = <String, int>{};
    final nameOf = <String, String>{};
    final classOfStudent = <String, String>{};

    for (final row in records) {
      final minutes = (row['minutes'] as num?)?.toInt() ?? 0;
      total += minutes;

      final code = '${row['discipline_code'] ?? ''}';
      if (code.isNotEmpty) {
        byDiscipline[code] = (byDiscipline[code] ?? 0) + minutes;
      }

      final turma = classOf(row);
      byClass[turma] = (byClass[turma] ?? 0) + minutes;

      final id = row['student_id'];
      final name = row['student_name'];
      if (id != null && name != null) {
        linked++;
        final key = '$id';
        byStudent[key] = (byStudent[key] ?? 0) + minutes;
        nameOf[key] = '$name';
        classOfStudent[key] = turma;
      }
    }

    List<StudyTimeEntry> rank(
      Map<String, int> counted, {
      String Function(String key)? label,
      String Function(String key)? group,
    }) {
      final entries = counted.entries
          .map((entry) => StudyTimeEntry(
                id: entry.key,
                label: label?.call(entry.key) ?? entry.key,
                group: group?.call(entry.key) ?? '',
                minutes: entry.value,
                share: total == 0 ? 0 : entry.value / total,
              ))
          .toList()
        ..sort((a, b) {
          final porTempo = b.minutes.compareTo(a.minutes);
          return porTempo != 0 ? porTempo : a.label.compareTo(b.label);
        });
      return entries;
    }

    final students = rank(
      byStudent,
      label: (key) => nameOf[key] ?? key,
      group: (key) => classOfStudent[key] ?? semTurma,
    );

    return StudyTimeStats(
      totalMinutes: total,
      recordCount: records.length,
      linkedRecords: linked,
      unlinkedRecords: records.length - linked,
      students: students,
      disciplines: rank(byDiscipline),
      classes: rank(byClass),
      medianMinutes: _median(students.map((s) => s.minutes).toList()),
      bands: _bands(students),
      bandByStudent: {
        for (final aluno in students) aluno.id: bandOf(aluno.minutes),
      },
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
    final soma = students.take(count).fold<int>(0, (sum, e) => sum + e.minutes);
    return soma / totalMinutes;
  }

  /// Minutos que sobram fora dos [count] primeiros do ranking de alunos.
  int minutesBeyond(int count) => students.length <= count
      ? 0
      : students.skip(count).fold<int>(0, (sum, e) => sum + e.minutes);

  static int _median(List<int> values) {
    if (values.isEmpty) return 0;
    final ordered = [...values]..sort();
    final meio = ordered.length ~/ 2;
    if (ordered.length.isOdd) return ordered[meio];
    return ((ordered[meio - 1] + ordered[meio]) / 2).round();
  }

  static List<StudyTimeBand> _bands(List<StudyTimeEntry> students) {
    if (students.isEmpty) return const [];
    final contagem = {
      for (final nome in bandLimits.keys) nome: 0,
      topBand: 0,
    };
    for (final aluno in students) {
      final faixa = bandOf(aluno.minutes);
      contagem[faixa] = contagem[faixa]! + 1;
    }
    return [
      for (final entrada in contagem.entries)
        StudyTimeBand(label: entrada.key, students: entrada.value),
    ];
  }
}

/// Um recorte da tela: os filtros que a aba e o painel compartilham.
///
/// Guardado como valor para o painel poder recalcular tudo a cada clique sem
/// precisar de estado espalhado - e para o teste conseguir descrever um recorte
/// sem montar widget.
class StudyTimeFilter {
  final String? discipline;
  final String? classLabel;
  final String? band;
  final String? course;
  final String? semester;

  /// Turma como veio da planilha. Continua filtravel para conferir a origem.
  final String? importedGroup;

  final bool pendingOnly;

  const StudyTimeFilter({
    this.discipline,
    this.classLabel,
    this.band,
    this.course,
    this.semester,
    this.importedGroup,
    this.pendingOnly = false,
  });

  bool get isEmpty =>
      discipline == null &&
      classLabel == null &&
      band == null &&
      course == null &&
      semester == null &&
      importedGroup == null &&
      !pendingOnly;

  StudyTimeFilter copyWith({
    String? discipline,
    String? classLabel,
    String? band,
    String? course,
    String? semester,
    String? importedGroup,
    bool? pendingOnly,
    bool clearDiscipline = false,
    bool clearClass = false,
    bool clearBand = false,
  }) =>
      StudyTimeFilter(
        discipline: clearDiscipline ? null : (discipline ?? this.discipline),
        classLabel: clearClass ? null : (classLabel ?? this.classLabel),
        band: clearBand ? null : (band ?? this.band),
        course: course ?? this.course,
        semester: semester ?? this.semester,
        importedGroup: importedGroup ?? this.importedGroup,
        pendingOnly: pendingOnly ?? this.pendingOnly,
      );

  /// Aplica o recorte. A faixa depende do tempo somado do aluno, entao ela e
  /// resolvida sobre o conjunto ja filtrado pelas outras dimensoes - senao um
  /// aluno mudaria de faixa conforme a disciplina escolhida sem avisar.
  List<Map<String, dynamic>> apply(List<Map<String, dynamic>> records) {
    final semFaixa = records.where((row) =>
        (discipline == null || row['discipline_code'] == discipline) &&
        (classLabel == null || StudyTimeStats.classOf(row) == classLabel) &&
        (course == null || row['course'] == course) &&
        (semester == null || row['semester'] == semester) &&
        (importedGroup == null || row['group_sequence'] == importedGroup) &&
        (!pendingOnly || row['student_id'] == null)).toList();
    if (band == null) return semFaixa;

    final faixas = StudyTimeStats.fromRecords(semFaixa).bandByStudent;
    return semFaixa
        .where((row) => faixas['${row['student_id']}'] == band)
        .toList();
  }
}

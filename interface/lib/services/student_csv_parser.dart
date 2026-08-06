class StudentCsvRow {
  final String enrollment;
  final String name;

  const StudentCsvRow({required this.enrollment, required this.name});
}

List<StudentCsvRow> parseStudentCsv(String content) {
  if (content.trim().isEmpty) {
    throw const FormatException('O arquivo CSV esta vazio.');
  }

  final delimiter = _detectDelimiter(content);
  final rows = _parseRows(content, delimiter)
      .where((row) => row.any((cell) => cell.trim().isNotEmpty))
      .toList();
  if (rows.isEmpty) {
    throw const FormatException('O arquivo CSV esta vazio.');
  }

  final headers = rows.first.map(_normaliseHeader).toList();
  final enrollmentIndex = _headerIndex(
    headers,
    const ['matricula', 'ra', 'registro', 'id'],
  );
  final nameIndex = _headerIndex(
    headers,
    const ['nome', 'nomecompleto', 'aluno'],
  );
  if (enrollmentIndex < 0 || nameIndex < 0) {
    throw const FormatException(
      'O CSV precisa ter as colunas matricula e nome.',
    );
  }

  final parsed = <StudentCsvRow>[];
  final enrollmentLines = <String, int>{};
  for (var index = 1; index < rows.length; index++) {
    final row = rows[index];
    final enrollment = _cell(row, enrollmentIndex).trim();
    final name = _cell(row, nameIndex).trim();
    if (enrollment.isEmpty && name.isEmpty) continue;
    if (enrollment.isEmpty || name.isEmpty) {
      throw FormatException(
        'Linha ${index + 1}: matricula e nome sao obrigatorios.',
      );
    }

    final key = enrollment.toLowerCase();
    final previousLine = enrollmentLines[key];
    if (previousLine != null) {
      throw FormatException(
        'Matricula $enrollment repetida nas linhas $previousLine e '
        '${index + 1}.',
      );
    }
    enrollmentLines[key] = index + 1;
    parsed.add(StudentCsvRow(enrollment: enrollment, name: name));
  }

  if (parsed.isEmpty) {
    throw const FormatException('O CSV nao possui alunos para importar.');
  }
  return parsed;
}

int _headerIndex(List<String> headers, List<String> accepted) {
  for (var index = 0; index < headers.length; index++) {
    if (accepted.contains(headers[index])) return index;
  }
  return -1;
}

String _cell(List<String> row, int index) =>
    index < row.length ? row[index] : '';

String _normaliseHeader(String value) {
  var result = value.replaceAll('\uFEFF', '').trim().toLowerCase();
  const accents = {
    'a': 'áàâãä',
    'e': 'éèêë',
    'i': 'íìîï',
    'o': 'óòôõö',
    'u': 'úùûü',
    'c': 'ç',
  };
  for (final entry in accents.entries) {
    for (final accented in entry.value.split('')) {
      result = result.replaceAll(accented, entry.key);
    }
  }
  return result.replaceAll(RegExp('[^a-z0-9]'), '');
}

String _detectDelimiter(String content) {
  final counts = {',': 0, ';': 0, '\t': 0};
  var quoted = false;
  for (var index = 0; index < content.length; index++) {
    final char = content[index];
    if (char == '"') {
      if (quoted && index + 1 < content.length && content[index + 1] == '"') {
        index++;
      } else {
        quoted = !quoted;
      }
      continue;
    }
    if (!quoted && (char == '\r' || char == '\n')) break;
    if (!quoted && counts.containsKey(char)) counts[char] = counts[char]! + 1;
  }
  return counts.entries.reduce((a, b) => a.value >= b.value ? a : b).key;
}

List<List<String>> _parseRows(String content, String delimiter) {
  final rows = <List<String>>[];
  var row = <String>[];
  var field = StringBuffer();
  var quoted = false;

  void finishField() {
    row.add(field.toString());
    field = StringBuffer();
  }

  void finishRow() {
    finishField();
    rows.add(row);
    row = <String>[];
  }

  for (var index = 0; index < content.length; index++) {
    final char = content[index];
    if (quoted) {
      if (char == '"') {
        if (index + 1 < content.length && content[index + 1] == '"') {
          field.write('"');
          index++;
        } else {
          quoted = false;
        }
      } else {
        field.write(char);
      }
      continue;
    }

    if (char == '"' && field.isEmpty) {
      quoted = true;
    } else if (char == delimiter) {
      finishField();
    } else if (char == '\r' || char == '\n') {
      finishRow();
      if (char == '\r' &&
          index + 1 < content.length &&
          content[index + 1] == '\n') {
        index++;
      }
    } else {
      field.write(char);
    }
  }

  if (quoted) {
    throw const FormatException('O CSV possui aspas sem fechamento.');
  }
  if (field.isNotEmpty || row.isNotEmpty) finishRow();
  return rows;
}

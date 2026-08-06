import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/student_csv_parser.dart';

void main() {
  test('imports matricula and nome from a semicolon CSV', () {
    final rows = parseStudentCsv(
      '\uFEFFMatrícula;Nome\r\n2026001;Ana Silva\r\n2026002;Bruno Lima\r\n',
    );

    expect(rows, hasLength(2));
    expect(rows.first.enrollment, '2026001');
    expect(rows.first.name, 'Ana Silva');
  });

  test('accepts comma CSV and quoted names', () {
    final rows = parseStudentCsv(
      'matricula,nome\n1001,"Silva, Ana"\n',
    );

    expect(rows.single.name, 'Silva, Ana');
  });

  test('rejects a file without the expected headers', () {
    expect(
      () => parseStudentCsv('codigo;estudante\n1;Ana'),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects duplicate enrollment', () {
    expect(
      () => parseStudentCsv('matricula;nome\n1;Ana\n1;Bruno'),
      throwsA(
        isA<FormatException>().having(
          (error) => error.message,
          'message',
          contains('repetida'),
        ),
      ),
    );
  });
}

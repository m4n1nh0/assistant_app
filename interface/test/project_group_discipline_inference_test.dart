import 'package:flutter_test/flutter_test.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/project_groups_tab.dart';

void main() {
  const disciplines = [
    Discipline(id: 'database', code: 'ARA0040-BANCO DE DADOS', name: '',
      label: 'Banco de dados', semester: '2026.2'),
    Discipline(id: 'iot', code: 'ARA0058', name: 'APL. DE CLOUD, IOT E INDÚSTRIA',
      label: 'IoT', semester: '2026.2'),
    Discipline(id: 'iot-previous', code: 'ARA0058', name: 'APL. DE CLOUD, IOT',
      label: 'IoT', semester: '2026.1'),
  ];

  test('arquivo de IoT seleciona ARA0058, mesmo que Banco de Dados venha primeiro', () {
    expect(inferProjectGroupDiscipline(disciplines,
      'GRUPOS IOT 2026-2.txt')?.id, 'iot');
  });

  test('lista sem pista de disciplina exige escolha explícita', () {
    expect(inferProjectGroupDiscipline(disciplines,
      'GRUPO 1\nNICOLAS ROSA'), isNull);
  });
}

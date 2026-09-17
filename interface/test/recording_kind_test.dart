import 'package:assistant_app/services/education_service.dart';
import 'package:flutter_test/flutter_test.dart';

/// Aula, apresentação de grupo e palestra usam a mesma gravação, mas não se
/// confundem numa lista: quem escolhe a fonte de um quiz precisa saber se
/// aquilo é a aula de terça ou a palestra da semana passada.
void main() {
  Lesson lesson(Map<String, dynamic> extra) => Lesson.fromJson({
        'id': 'l1',
        'discipline': 'ARA0040 - BANCO DE DADOS',
        'title': '',
        'class_group': '',
        'status': 'closed',
        ...extra,
      });

  test('aula mostra disciplina e tema', () {
    expect(lesson({'title': 'Normalização'}).displayLabel,
        'ARA0040 - BANCO DE DADOS — Normalização');
    expect(lesson({}).displayLabel, 'ARA0040 - BANCO DE DADOS');
  });

  test('apresentação mostra o grupo', () {
    final apresentacao = lesson({
      'kind': 'apresentacao',
      'group_id': 'g1',
      'group_name': 'Grupo 4',
      'title': 'Apresentacao: Grupo 4',
    });

    expect(apresentacao.kind, 'apresentacao');
    expect(apresentacao.groupId, 'g1');
    expect(apresentacao.displayLabel, 'Apresentação: Grupo 4');
  });

  test('palestra mostra o título, sem disciplina', () {
    final palestra = lesson({
      'kind': 'palestra',
      'discipline': '',
      'title': 'LGPD na prática',
    });

    expect(palestra.displayLabel, 'Palestra: LGPD na prática');
  });

  test('rótulo do tipo tem nome legível', () {
    expect(recordingKindLabel('aula'), 'Aula');
    expect(recordingKindLabel('apresentacao'), 'Apresentação');
    expect(recordingKindLabel('palestra'), 'Palestra');
    expect(recordingKindLabel('desconhecido'), 'Aula');
  });
}

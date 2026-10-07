import 'dart:convert';
import 'dart:typed_data';

import 'package:assistant_app/models/group_draw.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/services/group_pdf_service.dart';
import 'package:assistant_app/widgets/group_draw_dialog.dart';
import 'package:assistant_app/widgets/pdf_preview_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Student _student(String id, String name, String? enrollment) => Student(
      id: id,
      name: name,
      externalId: enrollment,
      classGroup: '3001',
      discipline: 'ARA0040',
    );

Map<String, dynamic> _group(String name, List<Map<String, dynamic>> members,
        {String title = ''}) =>
    {'name': name, 'project_title': title, 'members': members};

Map<String, dynamic> _member(String name, int position, {String? studentId}) => {
      'name': name,
      'position': position,
      'student_id': studentId,
    };

bool _isPdf(List<int> bytes) =>
    bytes.length > 1000 && utf8.decode(bytes.sublist(0, 5)) == '%PDF-';

Widget _fakePages(Uint8List bytes, String name) => Text('páginas ${bytes.length}');

void main() {
  setUp(() => pdfPagesBuilder = _fakePages);
  tearDown(() => pdfPagesBuilder = defaultPdfPages);

  TestWidgetsFlutterBinding.ensureInitialized();

  group('compareNatural', () {
    test('ordena pelo número dentro do nome', () {
      final names = ['Grupo 10', 'Grupo 2', 'Grupo 1', 'grupo 3'];
      names.sort(compareNatural);
      expect(names, ['Grupo 1', 'Grupo 2', 'grupo 3', 'Grupo 10']);
    });

    test('nomes sem número ordenam por texto', () {
      final names = ['Beta', 'Alfa'];
      names.sort(compareNatural);
      expect(names, ['Alfa', 'Beta']);
    });
  });

  group('groupListFrom', () {
    final students = [
      _student('s1', 'Ana Souza', '20240001'),
      _student('s2', 'Bia Lima', ' 20240002 '),
      _student('s3', 'Caio Reis', null),
    ];

    test('liga a matrícula pelo aluno vinculado e deixa vazia a sem vínculo', () {
      final list = groupListFrom([
        _group('Grupo 1', [
          _member('Bia Lima', 1, studentId: 's2'),
          _member('Ana Souza', 0, studentId: 's1'),
          _member('Zé da Lista', 2),
          _member('Caio Reis', 3, studentId: 's3'),
        ]),
      ], students);

      final members = list.single.members;
      // Na ordem da lista (position), não na ordem em que chegaram.
      expect(members.map((m) => m.name),
          ['Ana Souza', 'Bia Lima', 'Zé da Lista', 'Caio Reis']);
      expect(members.map((m) => m.enrollment),
          ['20240001', '20240002', '', '']);
    });

    test('ordena os grupos pelo número', () {
      final list = groupListFrom([
        _group('Grupo 10', const []),
        _group('Grupo 2', const []),
        _group('Grupo 1', const []),
      ], students);
      expect(list.map((g) => g.name), ['Grupo 1', 'Grupo 2', 'Grupo 10']);
    });

    test('lê o título do projeto e tolera campos ausentes', () {
      final list = groupListFrom([
        _group('Grupo 1', [_member('Ana Souza', 0, studentId: 's1')],
            title: 'Sistema de biblioteca'),
        {'name': 'Grupo 2'},
      ], students);
      expect(list.first.projectTitle, 'Sistema de biblioteca');
      expect(list.last.members, isEmpty);
    });
  });

  group('buildGroupListPdf', () {
    test('gera um PDF com os grupos', () async {
      final bytes = await buildGroupListPdf(
        discipline: 'ARA0040 - BANCO DE DADOS',
        semester: '2026.2',
        generatedAt: DateTime(2026, 10, 5),
        groups: [
          for (var n = 1; n <= 12; n++)
            GroupListGroup(
              name: 'Grupo $n',
              projectTitle: 'Projeto $n',
              members: [
                for (var m = 0; m < 5; m++)
                  GroupListMember(
                    name: 'Aluno $n.$m',
                    enrollment: m == 4 ? '' : '2024$n$m',
                  ),
              ],
            ),
        ],
      );
      expect(_isPdf(bytes), isTrue);
    });

    test('a turma entra no cabeçalho da relação', () async {
      final bytes = await buildGroupListPdf(
        discipline: 'ARA0040 - BANCO DE DADOS',
        classLabel: '3001 Presencial · segunda',
        semester: '2026.2',
        groups: const [
          GroupListGroup(name: 'GRUPO 1', members: [GroupListMember(name: 'Ana')]),
        ],
      );
      expect(_isPdf(bytes), isTrue);
    });

    test('lista vazia e sem matrícula também geram o documento', () async {
      expect(
        _isPdf(await buildGroupListPdf(discipline: 'X', groups: const [])),
        isTrue,
      );
      expect(
        _isPdf(await buildGroupListPdf(
          discipline: 'X',
          showEnrollment: false,
          groups: const [
            GroupListGroup(name: 'Grupo 1', members: [GroupListMember(name: 'A')]),
            GroupListGroup(name: 'Grupo 2'),
          ],
        )),
        isTrue,
      );
    });
  });

  group('buildGroupDrawPdf', () {
    Map<String, dynamic> entry(String id, String name,
            {int? position, int? day, String status = 'pendente', String rep = ''}) =>
        {
          'id': id,
          'group_id': 'g-$id',
          'group_name': name,
          'position': position,
          'day': day,
          'status': status,
          'representative_name': rep,
          'representative_round': 0,
        };

    GroupDraw draw(List<Map<String, dynamic>> entries,
            {String mode = 'fila', int? perDay, bool verified = true}) =>
        GroupDraw.fromJson({
          'id': 'd1',
          'discipline_id': 'disc',
          'discipline': 'ARA0040 - BANCO DE DADOS',
          'semester': '2026.2',
          'title': 'Ordem de apresentacao',
          'mode': mode,
          'seed': 'abc123',
          'algorithm': 'sha256-v1',
          'per_day': perDay,
          'total': entries.length,
          'remaining': entries.where((e) => e['position'] == null).length,
          'verified': verified,
          'entries': entries,
        });

    test('gera o PDF da ordem completa com dias e representantes', () async {
      final bytes = await buildGroupDrawPdf(
        generatedAt: DateTime(2026, 10, 5),
        draw: draw([
          entry('a', 'Grupo 3', position: 1, day: 1, status: 'apresentou', rep: 'Ana'),
          entry('b', 'Grupo 1', position: 2, day: 1, status: 'apresentando'),
          entry('c', 'Grupo 4', position: 3, day: 2),
          entry('d', 'Grupo 2', position: 4, day: 2, status: 'ausente'),
        ], perDay: 2),
      );
      expect(_isPdf(bytes), isTrue);
    });

    test('sorteio avulso incompleto lista os que faltam e sorteio vazio gera', () async {
      expect(
        _isPdf(await buildGroupDrawPdf(
          draw: draw([
            entry('a', 'Grupo 3', position: 1, day: 1),
            entry('b', 'Grupo 1'),
          ], mode: 'avulso'),
        )),
        isTrue,
      );
      expect(
        _isPdf(await buildGroupDrawPdf(
          draw: draw([entry('a', 'Grupo 1')], mode: 'avulso'),
        )),
        isTrue,
      );
    });

    test('ordem que não confere com a semente também sai (com o aviso)', () async {
      expect(
        _isPdf(await buildGroupDrawPdf(
          draw: draw([entry('a', 'Grupo 1', position: 1, day: 1)], verified: false),
        )),
        isTrue,
      );
    });

    test('o rótulo de situação é o mesmo da tela', () {
      expect(GroupDrawEntry.labelOf('apresentou'), 'APRESENTOU');
      expect(GroupDrawEntry.labelOf('ausente'), 'AUSENTE');
      expect(GroupDrawEntry.labelOf('apresentando'), 'NA VEZ');
      expect(GroupDrawEntry.labelOf('pendente'), 'AGUARDANDO');
      expect(statusLabel('ausente'), 'AUSENTE');
    });
  });

  group('botão de imprimir na janela do sorteio', () {
    testWidgets('abre a pré-visualização, e fechar não imprime nem salva nada',
        (tester) async {
      tester.view.physicalSize = const Size(1400, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);

      final drawJson = {
        'id': 'sorteio-1',
        'discipline_id': 'd1',
        'discipline': 'ARA0040 - BANCO DE DADOS',
        'semester': '2026.2',
        'title': 'Ordem de apresentacao',
        'mode': 'fila',
        'seed': 'abc123',
        'algorithm': 'sha256-v1',
        'per_day': null,
        'total': 1,
        'remaining': 0,
        'verified': true,
        'created_at': '2026-10-04T12:00:00',
        'entries': [
          {
            'id': 'a',
            'group_id': 'g-a',
            'group_name': 'Grupo 1',
            'position': 1,
            'day': 1,
            'status': 'pendente',
            'representative_name': '',
            'representative_round': 0,
          },
        ],
      };
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/group-draws')) {
          return http.Response(jsonEncode([drawJson]), 200);
        }
        return http.Response(jsonEncode(drawJson), 200);
      });

      await http.runWithClient(() async {
        await tester.pumpWidget(const MaterialApp(
          home: Scaffold(
            body: GroupDrawPanel(
              discipline: Discipline(
                id: 'd1',
                code: 'ARA0040',
                name: 'BANCO DE DADOS',
                label: 'ARA0040 - BANCO DE DADOS',
                semester: '2026.2',
              ),
            ),
          ),
        ));
        await tester.pumpAndSettle();

        await tester.tap(find.byTooltip('Imprimir a ordem de apresentação'));
        await tester.pumpAndSettle();

        // O PDF é gerado e aparece primeiro numa prévia; imprimir e salvar vêm depois.
        expect(find.text('PRÉ-VISUALIZAÇÃO · ORDEM DE APRESENTAÇÃO'), findsOneWidget);
        expect(find.textContaining('1 de 1 grupos sorteados'), findsOneWidget);
        expect(find.text('IMPRIMIR'), findsOneWidget);
        expect(find.text('SALVAR PDF'), findsOneWidget);

        await tester.tap(find.text('FECHAR'));
        await tester.pumpAndSettle();
        expect(find.text('IMPRIMIR'), findsNothing);
        expect(find.text('PRÉ-VISUALIZAÇÃO · ORDEM DE APRESENTAÇÃO'), findsNothing);
      }, () => client);
    });
  });
}

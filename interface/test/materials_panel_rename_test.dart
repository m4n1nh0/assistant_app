import 'dart:convert';

import 'package:assistant_app/widgets/materials_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _material(String title) => {
      'id': 'm1',
      'discipline_id': null,
      'discipline': 'ARA0040 - BANCO DE DADOS',
      'title': title,
      'filename': '00001.pdf',
      'source_type': 'pdf',
      'page_count': 43,
      'char_count': 79000,
      'truncated': false,
      'created_at': '2026-10-01T12:00:00',
    };

void main() {
  testWidgets('renames a material from the list and shows the new name',
      (tester) async {
    var title = '00001';
    final patches = <Map<String, dynamic>>[];

    final client = MockClient((request) async {
      final path = request.url.path;
      if (request.method == 'PATCH' && path.endsWith('/materials/m1')) {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        patches.add(body);
        title = body['title'] as String;
        return http.Response(jsonEncode(_material(title)), 200);
      }
      if (path.endsWith('/education/materials')) {
        return http.Response(jsonEncode([_material(title)]), 200);
      }
      if (path.endsWith('/education/disciplines')) {
        return http.Response('[]', 200);
      }
      return http.Response('{"detail":"inesperado $path"}', 404);
    });

    await http.runWithClient(() async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: MaterialsPanel())),
      );
      await tester.pumpAndSettle();
      expect(find.text('00001'), findsOneWidget);

      await tester.tap(find.byTooltip('Renomear material'));
      await tester.pumpAndSettle();
      expect(find.text('Renomear material'), findsOneWidget);

      await tester.enterText(
        find.byType(TextField),
        '  Apostila de Banco de Dados ',
      );
      await tester.tap(find.text('SALVAR'));
      await tester.pumpAndSettle();

      expect(patches, [
        {'title': 'Apostila de Banco de Dados'},
      ]);
      expect(find.text('Apostila de Banco de Dados'), findsOneWidget);
      expect(find.text('00001'), findsNothing);
    }, () => client);
  });

  testWidgets('cancelling the rename leaves the name alone', (tester) async {
    final patches = <String>[];
    final client = MockClient((request) async {
      if (request.method == 'PATCH') patches.add(request.url.path);
      if (request.url.path.endsWith('/education/materials')) {
        return http.Response(jsonEncode([_material('00001')]), 200);
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(() async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: MaterialsPanel())),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byTooltip('Renomear material'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('CANCELAR'));
      await tester.pumpAndSettle();

      expect(patches, isEmpty);
      expect(find.text('00001'), findsOneWidget);
    }, () => client);
  });
}

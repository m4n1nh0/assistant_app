import 'dart:convert';

import 'package:assistant_app/widgets/materials_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> _material({bool improved = false, String llm = ''}) => {
      'id': 'm1',
      'discipline_id': null,
      'discipline': 'NUVEM',
      'title': 'Tema 6',
      'filename': 'tema6.pdf',
      'source_type': 'pdf',
      'page_count': 12,
      'char_count': 20000,
      'truncated': false,
      'created_at': '2026-10-01T12:00:00',
      'improved': improved,
      'improved_llm': llm,
    };

void main() {
  testWidgets('improves a material with the chosen AI and marks the row',
      (tester) async {
    var improved = false;
    final posts = <Map<String, dynamic>>[];

    final client = MockClient((request) async {
      final path = request.url.path;
      if (request.method == 'POST' && path.endsWith('/materials/m1/improve')) {
        posts.add(jsonDecode(request.body) as Map<String, dynamic>);
        improved = true;
        return http.Response(
            jsonEncode(_material(improved: true, llm: 'claude')), 200);
      }
      if (path.endsWith('/education/materials')) {
        return http.Response(
            jsonEncode([_material(improved: improved, llm: 'claude')]), 200);
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(() async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: MaterialsPanel())),
      );
      await tester.pumpAndSettle();
      expect(find.text('Tema 6'), findsOneWidget);
      expect(find.byTooltip('Voltar ao texto original'), findsNothing);

      await tester.tap(find.byTooltip('Melhorar texto com IA'));
      await tester.pumpAndSettle();
      expect(find.text('Melhorar texto com IA'), findsOneWidget);

      await tester.enterText(find.byType(TextField), '  manter as siglas ');
      await tester.tap(find.text('MELHORAR'));
      await tester.pumpAndSettle();

      // Sem provedor escolhido (automatico) o campo llm nem vai no corpo.
      expect(posts, [
        {'instructions': 'manter as siglas'},
      ]);
      expect(find.textContaining('caracteres  ·  melhorado por'), findsOneWidget);
      expect(find.byTooltip('Ver texto melhorado'), findsOneWidget);
      expect(find.byTooltip('Voltar ao texto original'), findsOneWidget);
    }, () => client);
  });

  testWidgets('cancelling the dialog does not call the backend',
      (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      if (request.method == 'POST') calls++;
      if (request.url.path.endsWith('/education/materials')) {
        return http.Response(jsonEncode([_material()]), 200);
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(() async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: MaterialsPanel())),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byTooltip('Melhorar texto com IA'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('CANCELAR'));
      await tester.pumpAndSettle();

      expect(calls, 0);
    }, () => client);
  });

  testWidgets('a failed improvement shows the reason and keeps the list',
      (tester) async {
    final client = MockClient((request) async {
      final path = request.url.path;
      if (request.method == 'POST' && path.endsWith('/improve')) {
        return http.Response(
            jsonEncode({'detail': 'A resposta nao parece uma reescrita fiel'}),
            502);
      }
      if (path.endsWith('/education/materials')) {
        return http.Response(jsonEncode([_material()]), 200);
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(() async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: MaterialsPanel())),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byTooltip('Melhorar texto com IA'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('MELHORAR'));
      await tester.pumpAndSettle();

      expect(find.textContaining('reescrita fiel'), findsOneWidget);
      expect(find.text('Tema 6'), findsOneWidget);
      expect(find.byTooltip('Voltar ao texto original'), findsNothing);
    }, () => client);
  });

  testWidgets('discarding the improved text goes back to the original',
      (tester) async {
    var improved = true;
    var deletes = 0;
    final client = MockClient((request) async {
      final path = request.url.path;
      if (request.method == 'DELETE' && path.endsWith('/materials/m1/improved')) {
        deletes++;
        improved = false;
        return http.Response(jsonEncode(_material()), 200);
      }
      if (path.endsWith('/education/materials')) {
        return http.Response(
            jsonEncode([_material(improved: improved, llm: 'gemini')]), 200);
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(() async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: MaterialsPanel())),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('caracteres  ·  melhorado por'), findsOneWidget);

      await tester.tap(find.byTooltip('Voltar ao texto original'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('DESCARTAR'));
      await tester.pumpAndSettle();

      expect(deletes, 1);
      expect(find.textContaining('caracteres  ·  melhorado por'), findsNothing);
      expect(find.byTooltip('Voltar ao texto original'), findsNothing);
    }, () => client);
  });
}

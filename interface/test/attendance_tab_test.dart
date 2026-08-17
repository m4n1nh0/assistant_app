import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/attendance_tab.dart';

void main() {
  testWidgets('renders QR call controls and the reports panel', (tester) async {
    final classes = ValueNotifier<List<ClassGroup>?>(const [
      ClassGroup(
        id: 'c1',
        code: '3001',
        name: 'Presencial',
        discipline: 'Banco de Dados',
        semester: '2026.2',
        label: '3001 Presencial',
      ),
    ]);
    final client = MockClient((request) async {
      if (request.method == 'POST' &&
          request.url.path.endsWith('/attendance/sessions')) {
        return http.Response(
          '{'
          '"id":"a1",'
          '"class_id":"c1",'
          '"class_label":"3001 Presencial",'
          '"discipline":"Banco de Dados",'
          '"semester":"2026.2",'
          '"attendance_date":"2026-08-16",'
          '"opened_at":"2026-08-16T18:00:00Z",'
          '"expires_at":"2099-08-16T18:15:00Z",'
          '"open":true,'
          '"check_in_path":"/education/attendance/check-in/token",'
          '"expected_count":2,'
          '"present_count":1,'
          '"records":[{'
          '"id":"r1",'
          '"student_id":"s1",'
          '"enrollment":"2026001",'
          '"student_name":"Ana",'
          '"source":"qr",'
          '"checked_in_at":"2026-08-16T18:01:00Z"'
          '}],'
          '"absent_students":[{'
          '"student_id":"s2",'
          '"enrollment":"2026002",'
          '"student_name":"Bruno"'
          '}]'
          '}',
          200,
        );
      }
      return http.Response('[]', 200);
    });

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SizedBox(
                width: 1000,
                height: 700,
                child: AttendanceTab(classes: classes),
              ),
            ),
          ),
        );
        await tester.pump(const Duration(milliseconds: 100));

        expect(find.text('GERAR QR'), findsOneWidget);
        expect(find.text('CHAMADA ATUAL'), findsOneWidget);
        expect(find.text('RELATORIOS E AULAS DO DIA'), findsOneWidget);
        expect(find.text('VISUALIZAR PDF'), findsOneWidget);

        await tester.tap(find.text('GERAR QR'));
        await tester.pump(const Duration(milliseconds: 200));

        expect(find.text('1 presentes de 2'), findsOneWidget);
        expect(find.textContaining('Ana'), findsOneWidget);
        expect(find.text('ENCERRAR'), findsOneWidget);
      },
      () => client,
    );

    await tester.pumpWidget(const SizedBox.shrink());
    classes.dispose();
  });
}

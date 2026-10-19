import 'dart:convert';
import 'dart:io';

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/semester_period_dialog.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('datas', () {
    test('isoDay completa com zeros e brDay volta para o formato brasileiro', () {
      expect(isoDay(DateTime(2026, 3, 5)), '2026-03-05');
      expect(brDay('2026-03-05'), '05/03/2026');
    });

    test('brDay devolve o texto como veio quando nao e data', () {
      expect(brDay(''), '');
      expect(brDay('amanha'), 'amanha');
      expect(brDay('2026-03'), '2026-03');
    });

    test('parseIsoDay aceita data valida e recusa vazio, lixo e dia que nao existe', () {
      expect(parseIsoDay('2026-10-19'), DateTime(2026, 10, 19));
      expect(parseIsoDay(''), isNull);
      expect(parseIsoDay('19/10/2026'), isNull);
      expect(parseIsoDay('2026-02-31'), isNull); // DateTime rolaria para 03/03
      expect(parseIsoDay('2026-13-01'), isNull);
    });
  });

  group('Semester', () {
    test('le o periodo e a contagem de datas sem aula', () {
      final semester = Semester.fromJson({
        'code': '2026.2',
        'active': true,
        'discipline_count': 6,
        'class_count': 10,
        'start_date': '2026-08-03',
        'end_date': '2026-12-14',
        'break_count': 3,
      });

      expect(semester.hasPeriod, isTrue);
      expect(periodSummary(semester),
          '03/08/2026 a 14/12/2026  -  3 data(s) sem aula');
    });

    test('backend antigo, sem periodo, continua legivel', () {
      final semester = Semester.fromJson({'code': '2026.2', 'active': true});

      expect(semester.hasPeriod, isFalse);
      expect(semester.breakCount, 0);
      expect(periodSummary(semester), 'periodo nao informado');
    });

    test('periodo pela metade mostra o que falta', () {
      final semester = Semester.fromJson({
        'code': '2026.2',
        'active': true,
        'start_date': '2026-08-03',
      });

      expect(semester.hasPeriod, isFalse);
      expect(periodSummary(semester), '03/08/2026 a ?');
    });
  });

  group('ClassBreak', () {
    test('dia so e intervalo aparecem diferentes na lista', () {
      final single = ClassBreak.fromJson({
        'id': 'b1',
        'semester': '2026.2',
        'date_from': '2026-11-02',
        'date_to': '2026-11-02',
        'reason': 'Finados',
      });
      final range = ClassBreak.fromJson({
        'id': 'b2',
        'semester': '2026.2',
        'date_from': '2026-10-12',
        'date_to': '2026-10-16',
        'class_group_id': 'g1',
        'class_label': '3002',
      });

      expect(single.isRange, isFalse);
      expect(breakDates(single), '02/11/2026');
      expect(single.classGroupId, isNull);
      expect(range.isRange, isTrue);
      expect(breakDates(range), '12/10/2026 a 16/10/2026');
      expect(range.classGroupId, 'g1');
    });

    test('class_group_id vazio vale para todas as turmas', () {
      final item = ClassBreak.fromJson({
        'id': 'b1',
        'semester': '2026.2',
        'date_from': '2026-11-02',
        'date_to': '2026-11-02',
        'class_group_id': '',
      });

      expect(item.classGroupId, isNull);
    });
  });

  group('servico contra o backend', () {
    late String previousUrl;

    setUp(() => previousUrl = api.baseUrl);
    tearDown(() => api.configure(previousUrl));

    Future<HttpServer> serve(
      Future<void> Function(HttpRequest request, String body) handler,
    ) async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        final body = await utf8.decoder.bind(request).join();
        await handler(request, body);
        await request.response.close();
      });
      api.configure('http://127.0.0.1:${server.port}');
      return server;
    }

    test('updateSemester so envia o que foi informado e limpa data com texto vazio', () async {
      final bodies = <Map<String, dynamic>>[];
      final server = await serve((request, body) async {
        expect(request.method, 'PATCH');
        expect(request.uri.path, '/education/semesters/2026.2');
        bodies.add(jsonDecode(body) as Map<String, dynamic>);
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'code': '2026.2',
          'active': true,
          'start_date': '2026-08-03',
          'end_date': '',
        }));
      });
      addTearDown(() => server.close(force: true));

      final saved = await education.updateSemester(
        '2026.2',
        startDate: '2026-08-03',
        endDate: '',
      );
      await education.updateSemester('2026.2', active: false);

      expect(bodies[0], {'start_date': '2026-08-03', 'end_date': ''});
      expect(bodies[1], {'active': false});
      expect(saved.startDate, '2026-08-03');
      expect(saved.endDate, '');
    });

    test('createSemesterBreak omite data final e turma quando nao informadas', () async {
      late Map<String, dynamic> sent;
      final server = await serve((request, body) async {
        sent = jsonDecode(body) as Map<String, dynamic>;
        request.response.statusCode = 201;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'id': 'b1',
          'semester': '2026.2',
          'date_from': '2026-11-02',
          'date_to': '2026-11-02',
          'reason': 'Finados',
        }));
      });
      addTearDown(() => server.close(force: true));

      final created = await education.createSemesterBreak(
        '2026.2',
        dateFrom: '2026-11-02',
        reason: 'Finados',
      );

      expect(sent, {'date_from': '2026-11-02', 'reason': 'Finados'});
      expect(created.id, 'b1');
    });

    test('listSemesters e listSemesterBreaks leem as listas do backend', () async {
      final server = await serve((request, body) async {
        request.response.headers.contentType = ContentType.json;
        if (request.uri.path == '/education/semesters') {
          request.response.write(jsonEncode([
            {'code': '2026.2', 'active': true, 'break_count': 1},
          ]));
        } else {
          request.response.write(jsonEncode([
            {
              'id': 'b1',
              'semester': '2026.2',
              'date_from': '2026-11-02',
              'date_to': '2026-11-02',
            },
          ]));
        }
      });
      addTearDown(() => server.close(force: true));

      final semesters = await education.listSemesters();
      final breaks = await education.listSemesterBreaks('2026.2');

      expect(semesters.single.breakCount, 1);
      expect(breaks.single.dateFrom, '2026-11-02');
    });

    test('deleteSemesterBreak chama a rota certa', () async {
      String? seen;
      final server = await serve((request, body) async {
        seen = '${request.method} ${request.uri.path}';
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'ok': true}));
      });
      addTearDown(() => server.close(force: true));

      await education.deleteSemesterBreak('2026.2', 'b1');

      expect(seen, 'DELETE /education/semesters/2026.2/breaks/b1');
    });

    test('erro do backend sobe como excecao com a mensagem', () async {
      final server = await serve((request, body) async {
        request.response.statusCode = 422;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'detail': 'O fim do semestre deve ser igual ou posterior ao inicio'
        }));
      });
      addTearDown(() => server.close(force: true));

      expect(
        () => education.updateSemester('2026.2', endDate: '2026-01-01'),
        throwsA(predicate((e) => e.toString().contains('posterior ao inicio'))),
      );
    });
  });
}

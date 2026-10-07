import 'dart:convert';

import 'package:assistant_app/models/meeting_room.dart';
import 'package:assistant_app/widgets/meetings_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:qr_flutter/qr_flutter.dart';

Map<String, dynamic> _room(
  String id,
  String title, {
  String status = 'open',
  int online = 0,
  int people = 0,
  int segments = 0,
  String key = 'chave-secreta',
}) =>
    {
      'id': id,
      'title': title,
      'status': status,
      'token': 'tok$id',
      'join_path': '/education/meet/tok$id',
      'host_path': '/education/meet/tok$id#host=$key',
      'guests_allowed': true,
      'max_participants': 30,
      'lesson_id': 'l-$id',
      'created_at': '2026-10-07T20:00:00',
      'ended_at': status == 'ended' ? '2026-10-07T21:00:00' : null,
      'online': online,
      'people': people,
      'segments': segments,
    };

Map<String, dynamic> _person(
  String name, {
  bool host = false,
  bool guest = false,
  bool online = true,
  int seconds = 600,
  int chunks = 0,
}) =>
    {
      'name': name,
      'student_id': guest || host ? null : 's-$name',
      'is_host': host,
      'guest': guest,
      'online': online,
      'seconds': seconds,
      'chunks': chunks,
      'first_joined': '2026-10-07T20:01:00',
    };

Map<String, dynamic> _line(String id, int seq, String text) =>
    {'id': id, 'sequence': seq, 'text': text, 'created_at': '2026-10-07T20:05:00'};

class _Backend {
  Map<String, dynamic> config;
  List<Map<String, dynamic>> rooms;
  final Map<String, Map<String, dynamic>> details;
  final requests = <http.Request>[];
  int? createStatus;

  _Backend({
    Map<String, dynamic>? config,
    List<Map<String, dynamic>>? rooms,
    Map<String, Map<String, dynamic>>? details,
  })  : config = config ??
            {
              'configured': true,
              'media_host': 'meet.exemplo.com',
              'default_max_participants': 30,
              'missing': <String>[],
            },
        rooms = rooms ?? [],
        details = details ?? {};

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);

    if (path.endsWith('/education/meetings/config')) return json(config);
    if (path.endsWith('/education/meetings')) {
      if (request.method == 'POST') {
        if (createStatus != null) {
          return http.Response('{"detail":"Título obrigatório"}', createStatus!);
        }
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final created = _room('novo${rooms.length}', body['title'] as String);
        rooms = [created, ...rooms];
        details[created['id'] as String] = {...created, 'participants': [], 'transcript': []};
        return json(created);
      }
      return json(rooms);
    }
    final end = RegExp(r'/education/meetings/(\w+)/end$').firstMatch(path);
    if (end != null) {
      final id = end.group(1)!;
      rooms = [
        for (final r in rooms) r['id'] == id ? {...r, 'status': 'ended'} : r
      ];
      details[id] = {...?details[id], 'status': 'ended'};
      return json(rooms.firstWhere((r) => r['id'] == id));
    }
    final one = RegExp(r'/education/meetings/(\w+)$').firstMatch(path);
    if (one != null && request.method == 'GET') {
      final detail = details[one.group(1)];
      return detail == null
          ? http.Response('{"detail":"Reunião não encontrada"}', 404)
          : json(detail);
    }
    return http.Response('{"detail":"inesperado $path"}', 404);
  }

  bool called(String method, String suffix) => requests
      .any((r) => r.method == method && r.url.path.endsWith(suffix));

  Map<String, dynamic> bodyOf(String method, String suffix) => jsonDecode(requests
      .lastWhere((r) => r.method == method && r.url.path.endsWith(suffix))
      .body) as Map<String, dynamic>;
}

Future<void> _open(
  WidgetTester tester,
  _Backend backend, {
  Future<bool> Function(Uri uri)? launcher,
  String baseUrl = 'https://app.exemplo.com',
  Duration pollEvery = Duration.zero,
  required Future<void> Function() body,
}) async {
  tester.view.physicalSize = const Size(1600, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: MeetingsTab(
          launcher: launcher ?? (uri) async => true,
          baseUrl: baseUrl,
          pollEvery: pollEvery,
        ),
      ),
    ));
    await tester.pumpAndSettle();
    await body();
  }, () => client);
}

void main() {
  group('modelos', () {
    test('os links juntam o endereço do servidor; o do professor leva a chave', () {
      final room = MeetingRoom.fromJson(_room('r1', 'Mentoria'));

      expect(room.joinUrl('https://app.exemplo.com'),
          'https://app.exemplo.com/education/meet/tokr1');
      expect(room.joinUrl('https://app.exemplo.com/'),
          'https://app.exemplo.com/education/meet/tokr1');
      expect(room.hostUrl('https://app.exemplo.com'),
          'https://app.exemplo.com/education/meet/tokr1#host=chave-secreta');
      expect(room.joinUrl('https://app.exemplo.com'), isNot(contains('chave-secreta')));
      expect(room.isOpen, isTrue);
      expect(MeetingRoom.fromJson(_room('r', 'x', status: 'ended')).isOpen, isFalse);
    });

    test('quem é professor, aluno ou convidado', () {
      expect(MeetingParticipant.fromJson(_person('Prof', host: true)).roleLabel, 'Professor');
      expect(MeetingParticipant.fromJson(_person('Ana')).roleLabel, 'Aluno');
      expect(MeetingParticipant.fromJson(_person('Visita', guest: true)).roleLabel, 'Convidado');
    });

    test('a fala separa quem falou do que foi dito', () {
      final line = MeetingLine.fromJson(_line('a', 1, 'ANA SOUZA: bom dia pessoal'));

      expect(line.speaker, 'ANA SOUZA');
      expect(line.said, 'bom dia pessoal');
    });

    test('só o primeiro dois-pontos separa o nome; texto sem nome fica inteiro', () {
      expect(MeetingLine.fromJson(_line('a', 1, 'Ana: o plano é: revisar')).said,
          'o plano é: revisar');
      final sem = MeetingLine.fromJson(_line('b', 2, 'texto solto'));
      expect(sem.speaker, isEmpty);
      expect(sem.said, 'texto solto');
      // Frase longa com dois-pontos no meio não é nome.
      final longa = MeetingLine.fromJson(_line('c', 3, '${'x' * 90}: coisa'));
      expect(longa.speaker, isEmpty);
    });

    test('o tempo na sala em palavras', () {
      expect(formatMeetingDuration(45), '45 s');
      expect(formatMeetingDuration(60), '1 min');
      expect(formatMeetingDuration(12 * 60 + 30), '12 min');
      expect(formatMeetingDuration(65 * 60), '1 h 05 min');
      expect(formatMeetingDuration(3 * 3600), '3 h 00 min');
    });

    test('configuração lê o que falta', () {
      final config = MeetingConfig.fromJson({
        'configured': false,
        'media_host': '',
        'default_max_participants': 25,
        'missing': ['LIVEKIT_URL', 'LIVEKIT_API_KEY'],
      });

      expect(config.configured, isFalse);
      expect(config.missing, ['LIVEKIT_URL', 'LIVEKIT_API_KEY']);
      expect(config.defaultMaxParticipants, 25);
      expect(const MeetingConfig().defaultMaxParticipants, 30);
    });

    test('detalhe lê a sala, a presença e o fim da transcrição', () {
      final detail = MeetingDetail.fromJson({
        ..._room('r1', 'Mentoria', online: 2, people: 2, segments: 3),
        'participants': [_person('Prof', host: true), _person('Ana')],
        'transcript': [_line('a', 1, 'Ana: oi')],
      });

      expect(detail.room.online, 2);
      expect(detail.participants.map((p) => p.name), ['Prof', 'Ana']);
      expect(detail.transcript.single.speaker, 'Ana');
    });
  });

  group('aba de reuniões', () {
    testWidgets('sem servidor de vídeo configurado, avisa o que falta', (tester) async {
      final backend = _Backend(config: {
        'configured': false,
        'media_host': '',
        'default_max_participants': 30,
        'missing': ['LIVEKIT_URL', 'LIVEKIT_API_SECRET'],
      });
      await _open(tester, backend, body: () async {
        final aviso = tester.widget<Container>(
            find.byKey(const ValueKey('aviso-servidor-de-video')));
        expect(aviso, isNotNull);
        expect(find.textContaining('LIVEKIT_URL, LIVEKIT_API_SECRET'), findsOneWidget);
      });
    });

    testWidgets('com tudo configurado não há aviso', (tester) async {
      await _open(tester, _Backend(), body: () async {
        expect(find.byKey(const ValueKey('aviso-servidor-de-video')), findsNothing);
        expect(find.byKey(const ValueKey('sem-reunioes')), findsOneWidget);
        expect(find.byKey(const ValueKey('nenhuma-selecionada')), findsOneWidget);
      });
    });

    testWidgets('exige título antes de criar', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('criar-reuniao')));
        await tester.pumpAndSettle();

        expect(find.text('Dê um título à reunião.'), findsOneWidget);
        expect(backend.called('POST', '/education/meetings'), isFalse);
      });
    });

    testWidgets('cria a reunião e já mostra a sala', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        await tester.enterText(
            find.byKey(const ValueKey('titulo-reuniao')), '  Mentoria de outubro ');
        await tester.tap(find.byKey(const ValueKey('criar-reuniao')));
        await tester.pumpAndSettle();

        final body = backend.bodyOf('POST', '/education/meetings');
        expect(body['title'], 'Mentoria de outubro');
        expect(body['guests_allowed'], true);
        expect(body.containsKey('max_participants'), isFalse);
        expect(find.byKey(const ValueKey('titulo-detalhe')), findsOneWidget);
        expect(find.text('Mentoria de outubro'), findsNWidgets(2)); // cartão + detalhe
        expect(find.textContaining('Reunião criada'), findsOneWidget);
        expect(
          tester.widget<TextField>(find.byKey(const ValueKey('titulo-reuniao'))).controller!.text,
          isEmpty,
        );
      });
    });

    testWidgets('convidados desligados e limite de pessoas vão no pedido', (tester) async {
      final backend = _Backend();
      await _open(tester, backend, body: () async {
        await tester.enterText(find.byKey(const ValueKey('titulo-reuniao')), 'Orientação');
        await tester.tap(find.byKey(const ValueKey('aceitar-convidados')));
        await tester.pump();
        expect(find.text('Só entra quem digitar uma matrícula do cadastro.'), findsOneWidget);
        await tester.tap(find.byKey(const ValueKey('limite-pessoas')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('12 pessoas').last);
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('criar-reuniao')));
        await tester.pumpAndSettle();

        final body = backend.bodyOf('POST', '/education/meetings');
        expect(body['guests_allowed'], false);
        expect(body['max_participants'], 12);
      });
    });

    testWidgets('erro do servidor ao criar aparece', (tester) async {
      final backend = _Backend()..createStatus = 422;
      await _open(tester, backend, body: () async {
        await tester.enterText(find.byKey(const ValueKey('titulo-reuniao')), 'x');
        await tester.tap(find.byKey(const ValueKey('criar-reuniao')));
        await tester.pumpAndSettle();

        expect(find.textContaining('Título obrigatório'), findsOneWidget);
      });
    });

    testWidgets('a reunião aberta vem selecionada, com presença e transcrição', (tester) async {
      final backend = _Backend(
        rooms: [
          _room('r2', 'Encerrada antes', status: 'ended', people: 3, segments: 9),
          _room('r1', 'Mentoria', online: 2, people: 3, segments: 4),
        ],
        details: {
          'r1': {
            ..._room('r1', 'Mentoria', online: 2, people: 3, segments: 4),
            'participants': [
              _person('Prof. Mariano', host: true, chunks: 2),
              _person('ANA SOUZA', chunks: 3, seconds: 65 * 60),
              _person('Visitante', guest: true, online: false, seconds: 45),
            ],
            'transcript': [
              _line('f1', 1, 'ANA SOUZA: bom dia pessoal'),
              _line('f2', 2, 'Prof. Mariano: vamos começar'),
            ],
          },
        },
      );
      await _open(tester, backend, body: () async {
        expect(tester.widget<Text>(find.byKey(const ValueKey('titulo-detalhe'))).data, 'Mentoria');
        expect(find.text('2 online · 3 pessoas · 4 falas'), findsOneWidget);
        expect(find.text('NA SALA (2 online)'), findsOneWidget);
        // Cada pessoa com papel, tempo e falas.
        expect(find.byKey(const ValueKey('pessoa-Prof. Mariano')), findsOneWidget);
        expect(find.text('Professor'), findsOneWidget);
        expect(find.text('Aluno'), findsOneWidget);
        expect(find.text('Convidado'), findsOneWidget);
        expect(find.text('1 h 05 min'), findsOneWidget);
        expect(find.text('45 s'), findsOneWidget);
        expect(find.text('3 falas'), findsOneWidget);
        expect(find.text('1 fala'), findsNothing);
        // A fala sai com o nome de quem falou destacado.
        expect(
          tester
              .widget<RichText>(find.descendant(
                  of: find.byKey(const ValueKey('fala-f1')),
                  matching: find.byType(RichText)))
              .text
              .toPlainText(),
          'ANA SOUZA: bom dia pessoal',
        );
      });
    });

    testWidgets('convidado e aluno online ganham ponto verde; quem saiu, cinza',
        (tester) async {
      final backend = _Backend(
        rooms: [_room('r1', 'Mentoria', online: 1, people: 2)],
        details: {
          'r1': {
            ..._room('r1', 'Mentoria', online: 1, people: 2),
            'participants': [_person('Ana'), _person('Bia', online: false)],
            'transcript': [],
          },
        },
      );
      await _open(tester, backend, body: () async {
        Color ponto(String nome) => tester
            .widget<Icon>(find.descendant(
                of: find.byKey(ValueKey('pessoa-$nome')), matching: find.byType(Icon)))
            .color!;
        expect(ponto('Ana'), isNot(ponto('Bia')));
        expect(find.byKey(const ValueKey('sem-falas')), findsOneWidget);
      });
    });

    testWidgets('entrar como professor abre o navegador com a chave', (tester) async {
      final abertos = <Uri>[];
      final backend = _Backend(rooms: [_room('r1', 'Mentoria')], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, backend, launcher: (uri) async {
        abertos.add(uri);
        return true;
      }, body: () async {
        await tester.tap(find.byKey(const ValueKey('entrar-r1')));
        await tester.pumpAndSettle();

        expect(abertos.single.toString(),
            'https://app.exemplo.com/education/meet/tokr1#host=chave-secreta');
        expect(find.textContaining('abriu no navegador'), findsOneWidget);
      });
    });

    testWidgets('se o navegador não abrir, explica o que fazer', (tester) async {
      final backend = _Backend(rooms: [_room('r1', 'Mentoria')], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, backend, launcher: (uri) async => false, body: () async {
        await tester.tap(find.byKey(const ValueKey('entrar-r1')));
        await tester.pumpAndSettle();

        expect(find.textContaining('Não consegui abrir o navegador'), findsOneWidget);
      });
    });

    testWidgets('copia o link da turma (sem a chave) e o do professor', (tester) async {
      final copiado = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copiado.add((call.arguments as Map)['text'] as String);
          }
          return null;
        },
      );
      addTearDown(() => tester.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null));
      final backend = _Backend(rooms: [_room('r1', 'Mentoria')], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('copiar-r1')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('copiar-link-professor')));
        await tester.pumpAndSettle();

        expect(copiado, [
          'https://app.exemplo.com/education/meet/tokr1',
          'https://app.exemplo.com/education/meet/tokr1#host=chave-secreta',
        ]);
        expect(copiado.first, isNot(contains('chave-secreta')));
      });
    });

    testWidgets('o QR Code leva o link da turma', (tester) async {
      final backend = _Backend(rooms: [_room('r1', 'Mentoria')], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('qr-r1')));
        await tester.pumpAndSettle();

        expect(find.byType(QrImageView), findsOneWidget);
        expect(find.text('https://app.exemplo.com/education/meet/tokr1'), findsWidgets);
        expect(find.textContaining('chave-secreta'), findsNothing);
      });
    });

    testWidgets('avisa quando o endereço do servidor só abre neste computador',
        (tester) async {
      final backend = _Backend(rooms: [_room('r1', 'Mentoria')], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, backend, baseUrl: 'http://localhost:8000', body: () async {
        expect(find.byKey(const ValueKey('aviso-endereco-local')), findsOneWidget);
      });
      final publico = _Backend(rooms: [_room('r1', 'Mentoria')], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, publico, body: () async {
        expect(find.byKey(const ValueKey('aviso-endereco-local')), findsNothing);
      });
    });

    testWidgets('encerra para todos só depois de confirmar', (tester) async {
      final backend = _Backend(rooms: [_room('r1', 'Mentoria', online: 1, people: 1)], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('encerrar-r1')));
        await tester.pumpAndSettle();
        expect(find.text('Encerrar "Mentoria" para todos?'), findsOneWidget);
        expect(backend.called('POST', '/end'), isFalse);

        await tester.tap(find.byKey(const ValueKey('confirmar-encerrar')));
        await tester.pumpAndSettle();

        expect(backend.called('POST', '/r1/end'), isTrue);
        expect(find.text('ENCERRADA'), findsOneWidget);
        expect(find.byKey(const ValueKey('entrar-r1')), findsNothing);
        expect(find.byKey(const ValueKey('aviso-encerrada')), findsOneWidget);
        expect(find.textContaining('A transcrição está no Histórico'), findsOneWidget);
      });
    });

    testWidgets('cancelar não encerra', (tester) async {
      final backend = _Backend(rooms: [_room('r1', 'Mentoria')], details: {
        'r1': {..._room('r1', 'Mentoria'), 'participants': [], 'transcript': []},
      });
      await _open(tester, backend, body: () async {
        await tester.tap(find.byKey(const ValueKey('encerrar-r1')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Cancelar'));
        await tester.pumpAndSettle();

        expect(backend.called('POST', '/end'), isFalse);
        expect(find.text('ABERTA'), findsOneWidget);
      });
    });

    testWidgets('reunião encerrada não oferece entrar, link nem QR', (tester) async {
      final backend = _Backend(
        rooms: [_room('r1', 'Antiga', status: 'ended', people: 2, segments: 7)],
        details: {
          'r1': {
            ..._room('r1', 'Antiga', status: 'ended', people: 2, segments: 7),
            'participants': [_person('Ana', online: false)],
            'transcript': [_line('f1', 1, 'Ana: fim')],
          },
        },
      );
      await _open(tester, backend, body: () async {
        // Sem aberta, nada vem selecionado: escolhe a encerrada.
        await tester.tap(find.byKey(const ValueKey('sala-r1')));
        await tester.pumpAndSettle();

        expect(find.text('2 pessoas · 7 falas transcritas'), findsOneWidget);
        expect(find.byKey(const ValueKey('entrar-r1')), findsNothing);
        expect(find.byKey(const ValueKey('copiar-r1')), findsNothing);
        expect(find.byKey(const ValueKey('qr-r1')), findsNothing);
        expect(find.byKey(const ValueKey('copiar-link-professor')), findsNothing);
        expect(find.byKey(const ValueKey('fala-f1')), findsOneWidget);
      });
    });

    testWidgets('trocar de reunião carrega a outra', (tester) async {
      final backend = _Backend(
        rooms: [_room('r1', 'Primeira', online: 1), _room('r2', 'Segunda', online: 1)],
        details: {
          'r1': {..._room('r1', 'Primeira'), 'participants': [_person('Ana')], 'transcript': []},
          'r2': {..._room('r2', 'Segunda'), 'participants': [_person('Bia')], 'transcript': []},
        },
      );
      await _open(tester, backend, body: () async {
        expect(find.byKey(const ValueKey('pessoa-Ana')), findsOneWidget);

        // O título da sala, e não o cartão no meio: ali ficam os botões.
        await tester.tap(find.text('Segunda'));
        await tester.pumpAndSettle();

        expect(find.byKey(const ValueKey('pessoa-Bia')), findsOneWidget);
        expect(find.byKey(const ValueKey('pessoa-Ana')), findsNothing);
      });
    });

    testWidgets('a tela se atualiza sozinha: entra gente e a fala aparece', (tester) async {
      final backend = _Backend(rooms: [_room('r1', 'Mentoria', online: 1, people: 1)], details: {
        'r1': {..._room('r1', 'Mentoria', online: 1, people: 1),
          'participants': [_person('Ana')], 'transcript': []},
      });
      await _open(tester, backend, pollEvery: const Duration(milliseconds: 200), body: () async {
        expect(find.byKey(const ValueKey('pessoa-Bia')), findsNothing);

        backend.rooms = [_room('r1', 'Mentoria', online: 2, people: 2, segments: 1)];
        backend.details['r1'] = {
          ..._room('r1', 'Mentoria', online: 2, people: 2, segments: 1),
          'participants': [_person('Ana'), _person('Bia')],
          'transcript': [_line('f9', 1, 'Bia: cheguei')],
        };
        await tester.pump(const Duration(milliseconds: 260));
        await tester.pump();

        expect(find.byKey(const ValueKey('pessoa-Bia')), findsOneWidget);
        expect(find.byKey(const ValueKey('fala-f9')), findsOneWidget);
        expect(find.text('2 online · 2 pessoas · 1 falas'), findsOneWidget);
        // Desliga o relógio antes de fechar a tela.
        await tester.pumpWidget(const SizedBox());
      });
    });

    testWidgets('falha de rede numa atualização automática não apaga a tela',
        (tester) async {
      final backend = _Backend(rooms: [_room('r1', 'Mentoria', online: 1, people: 1)], details: {
        'r1': {..._room('r1', 'Mentoria', online: 1, people: 1),
          'participants': [_person('Ana')], 'transcript': []},
      });
      await _open(tester, backend, pollEvery: const Duration(milliseconds: 200), body: () async {
        backend.details.remove('r1'); // o servidor passa a responder 404
        await tester.pump(const Duration(milliseconds: 260));
        await tester.pump();

        expect(find.byKey(const ValueKey('pessoa-Ana')), findsOneWidget);
        await tester.pumpWidget(const SizedBox());
      });
    });
  });
}

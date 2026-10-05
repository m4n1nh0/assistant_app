import 'dart:io';
import 'dart:typed_data';

import 'package:assistant_app/services/lesson_recovery_service.dart';
import 'package:assistant_app/widgets/lesson_recovery_banner.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// WAV de 16 kHz, mono, 16 bits, com o cabeçalho canônico de 44 bytes.
Uint8List _wav(int dataBytes, {bool closed = true, int fill = 7}) {
  final out = Uint8List(44 + dataBytes);
  final view = ByteData.sublistView(out);
  void tag(int at, String text) {
    for (var i = 0; i < text.length; i++) {
      out[at + i] = text.codeUnitAt(i);
    }
  }

  tag(0, 'RIFF');
  view.setUint32(4, closed ? 36 + dataBytes : 0, Endian.little);
  tag(8, 'WAVE');
  tag(12, 'fmt ');
  view.setUint32(16, 16, Endian.little);
  view.setUint16(20, 1, Endian.little);
  view.setUint16(22, 1, Endian.little);
  view.setUint32(24, 16000, Endian.little);
  view.setUint32(28, 32000, Endian.little);
  view.setUint16(32, 2, Endian.little);
  view.setUint16(34, 16, Endian.little);
  tag(36, 'data');
  view.setUint32(40, closed ? dataBytes : 0, Endian.little);
  for (var i = 44; i < out.length; i++) {
    out[i] = fill;
  }
  return out;
}

int _u32(Uint8List bytes, int at) =>
    ByteData.sublistView(bytes).getUint32(at, Endian.little);

void main() {
  late Directory root;
  late LessonRecoveryService service;

  setUp(() async {
    root = await Directory.systemTemp.createTemp('lesson_recovery_test_');
    service = LessonRecoveryService(root: () async => root);
  });

  tearDown(() async {
    if (await root.exists()) await root.delete(recursive: true);
  });

  Future<File> chunk(String lesson, int stamp, Uint8List bytes,
      {String ext = 'wav'}) async {
    final dir = Directory('${root.path}${Platform.pathSeparator}$lesson');
    await dir.create(recursive: true);
    final file = File('${dir.path}${Platform.pathSeparator}chunk_$stamp.$ext');
    await file.writeAsBytes(bytes);
    return file;
  }

  group('onde o bloco é guardado', () {
    test('cada aula tem a sua pasta, e o nome do bloco leva a hora', () async {
      final path = await service.newChunkPath('aula-123', 'wav');

      expect(path, startsWith('${root.path}${Platform.pathSeparator}aula-123'));
      expect(RegExp(r'chunk_\d{13}\.wav$').hasMatch(path), isTrue);
      expect(await Directory('${root.path}${Platform.pathSeparator}aula-123').exists(),
          isTrue);
    });

    test('o id da aula não consegue sair da pasta base', () async {
      final path = await service.newChunkPath('../../fora', 'wav');

      expect(path.startsWith(root.path), isTrue);
      expect(path.contains('..'), isFalse);
      expect(LessonRecoveryService.safeId('../../fora'), '______fora');
    });

    test('mantém a extensão do formato gravado', () async {
      expect((await service.newChunkPath('a', 'm4a')).endsWith('.m4a'), isTrue);
    });
  });

  group('scan', () {
    test('sem pasta nenhuma não há o que recuperar', () async {
      await root.delete(recursive: true);
      expect(await service.scan(), isEmpty);
    });

    test('lista cada aula com os blocos em ordem de gravação', () async {
      await chunk('aula-a', 1700000002000, _wav(32000));
      await chunk('aula-a', 1700000001000, _wav(64000));
      await chunk('aula-b', 1700000005000, _wav(32000));

      final found = await service.scan();

      expect(found.map((l) => l.lessonId), ['aula-a', 'aula-b']);
      expect(found.first.chunks.map((c) => c.startedAt.millisecondsSinceEpoch),
          [1700000001000, 1700000002000]);
    });

    test('a ordem é numérica, não alfabética', () async {
      // 99999999999 (11 dígitos) vem depois de 1700000000000 na ordem do relógio.
      await chunk('aula-a', 99999999999, _wav(32000));
      await chunk('aula-a', 1700000000000, _wav(32000));

      final stamps = (await service.scan())
          .single
          .chunks
          .map((c) => c.startedAt.millisecondsSinceEpoch)
          .toList();
      expect(stamps, [99999999999, 1700000000000]);
    });

    test('a aula que está gravando agora fica de fora', () async {
      await chunk('em-uso', 1700000000000, _wav(32000));
      await chunk('orfa', 1700000001000, _wav(32000));

      final found = await service.scan(ignoreLessonId: 'em-uso');

      expect(found.map((l) => l.lessonId), ['orfa']);
      // O arquivo da aula em uso continua lá.
      expect(
          await File('${root.path}${Platform.pathSeparator}em-uso'
                  '${Platform.pathSeparator}chunk_1700000000000.wav')
              .exists(),
          isTrue);
    });

    test('bloco só com o cabeçalho é apagado e a pasta vazia some', () async {
      final vazio = await chunk('aula-a', 1700000000000, _wav(0));
      await chunk('aula-b', 1700000001000, _wav(32000));

      final found = await service.scan();

      expect(found.map((l) => l.lessonId), ['aula-b']);
      expect(await vazio.exists(), isFalse);
      expect(await Directory('${root.path}${Platform.pathSeparator}aula-a').exists(),
          isFalse);
    });

    test('arquivo que não é bloco é ignorado e não é apagado', () async {
      await chunk('aula-a', 1700000000000, _wav(32000));
      final estranho = File('${root.path}${Platform.pathSeparator}aula-a'
          '${Platform.pathSeparator}anotacoes.txt');
      await estranho.writeAsString('nao mexa');

      final found = await service.scan();

      expect(found.single.chunks, hasLength(1));
      expect(await estranho.exists(), isTrue);
    });

    test('estima a duração pelo tamanho do WAV', () async {
      await chunk('aula-a', 1700000000000, _wav(32000 * 60)); // 60 s
      await chunk('aula-a', 1700000060000, _wav(32000 * 25)); // 25 s

      final lesson = (await service.scan()).single;

      expect(lesson.chunks.map((c) => c.durationMs), [60000, 25000]);
      expect(lesson.approxSeconds, 85);
      expect(lesson.totalBytes, 2 * 44 + 32000 * 85);
    });

    test('formato que não dá para medir vale o bloco inteiro', () async {
      await chunk('aula-a', 1700000000000, Uint8List(5000), ext: 'm4a');
      expect((await service.scan()).single.chunks.single.durationMs, 60000);
    });
  });

  group('recover', () {
    Future<RecoverableLesson> tres() async {
      await chunk('aula-a', 1700000001000, _wav(32000, closed: false, fill: 1));
      await chunk('aula-a', 1700000002000, _wav(32000, closed: false, fill: 2));
      await chunk('aula-a', 1700000003000, _wav(32000, closed: false, fill: 3));
      return (await service.scan()).single;
    }

    test('envia em ordem, com o cabeçalho consertado, e guarda o que subiu',
        () async {
      final lesson = await tres();
      final sent = <int>[];

      final result = await service.recover(lesson, (c, bytes) async {
        sent.add(bytes[44]);
        // O servidor recebe um WAV coerente, não o cabeçalho zerado da queda.
        expect(_u32(bytes, 40), 32000);
        expect(_u32(bytes, 4), bytes.length - 8);
        return null;
      });

      expect(sent, [1, 2, 3]);
      expect(result.complete, isTrue);
      expect(result.sent, 3);
      // Nada fica pendente, mas o áudio continua guardado, agora como entregue.
      expect(await service.scan(), isEmpty);
      final kept = await service.chunksOf('aula-a');
      expect(kept.map((c) => c.state), everyElement(ChunkState.sent));
      expect(kept, hasLength(3));
    });

    test('para no primeiro que falha e deixa o resto guardado', () async {
      final lesson = await tres();
      var calls = 0;

      final result = await service.recover(lesson, (c, bytes) async {
        calls++;
        if (calls == 2) throw Exception('HTTP 503: carregando');
        return null;
      });

      expect(calls, 2); // o terceiro nem foi tentado: a ordem importa
      expect(result.complete, isFalse);
      expect(result.sent, 1);
      expect(result.remaining, 2);
      expect('${result.error}', contains('HTTP 503'));

      final left = (await service.scan()).single.chunks;
      expect(left.map((c) => c.startedAt.millisecondsSinceEpoch),
          [1700000002000, 1700000003000]);
    });

    test('depois de uma falha dá para tentar de novo e terminar', () async {
      var lesson = await tres();
      await service.recover(lesson, (c, bytes) async => throw Exception('rede'));
      lesson = (await service.scan()).single;
      expect(lesson.chunks, hasLength(3)); // nada foi perdido

      final result = await service.recover(lesson, (c, bytes) async => null);

      expect(result.complete, isTrue);
      expect(await service.scan(), isEmpty);
    });

    test('formato que não é WAV vai como está', () async {
      final original = Uint8List.fromList(List.generate(5000, (i) => i % 251));
      await chunk('aula-a', 1700000000000, original, ext: 'm4a');
      final lesson = (await service.scan()).single;
      Uint8List? received;

      await service.recover(lesson, (c, bytes) async {
        received = bytes;
        return null;
      });

      expect(received, original);
    });
  });

  group('estados do bloco', () {
    test('o resultado do envio troca o prefixo do nome e guarda o motivo',
        () async {
      final file = await chunk('aula-a', 1700000000000, _wav(32000));

      final renamed = await service.markResult('aula-a', file,
          state: ChunkState.quiet, detail: 'nenhuma fala reconhecida');

      expect(await file.exists(), isFalse);
      expect(renamed.path.endsWith('quiet_1700000000000.wav'), isTrue);
      final stored = (await service.chunksOf('aula-a')).single;
      expect(stored.state, ChunkState.quiet);
      expect(stored.detail, 'nenhuma fala reconhecida');
    });

    test('só o que não foi aceito é oferecido para recuperar', () async {
      final sent = await chunk('aula-a', 1700000001000, _wav(32000));
      await service.markResult('aula-a', sent, state: ChunkState.sent);
      final quiet = await chunk('aula-a', 1700000002000, _wav(32000));
      await service.markResult('aula-a', quiet, state: ChunkState.quiet);
      await chunk('aula-a', 1700000003000, _wav(32000));

      final lesson = (await service.scan()).single;

      expect(lesson.chunks.map((c) => c.startedAt.millisecondsSinceEpoch),
          [1700000003000]);
    });

    test('aula só com áudio entregue não é "interrompida" nem é apagada',
        () async {
      final file = await chunk('aula-a', 1700000001000, _wav(32000));
      await service.markResult('aula-a', file, state: ChunkState.sent);

      expect(await service.scan(), isEmpty);
      expect(await service.chunksOf('aula-a'), hasLength(1));
    });

    test('reenviar um bloco sem fala devolve ele à fila', () async {
      final file = await chunk('aula-a', 1700000000000, _wav(32000));
      final quiet = await service.markResult('aula-a', file,
          state: ChunkState.quiet, detail: 'sem fala');

      final back = await service.requeue('aula-a', quiet);

      expect(back.path.endsWith('chunk_1700000000000.wav'), isTrue);
      expect((await service.scan()).single.chunks, hasLength(1));
      expect((await service.chunksOf('aula-a')).single.detail, '');
    });

    test('recuperar guarda como "sem fala" o que o servidor ignorou', () async {
      await chunk('aula-a', 1700000001000, _wav(32000));
      await chunk('aula-a', 1700000002000, _wav(32000));
      final lesson = (await service.scan()).single;
      var n = 0;

      await service.recover(lesson, (c, bytes) async {
        n++;
        return n == 1
            ? const ChunkDelivery(quiet: true, detail: 'nenhuma fala reconhecida')
            : null;
      });

      final states = (await service.chunksOf('aula-a')).map((c) => c.state);
      expect(states, [ChunkState.quiet, ChunkState.sent]);
    });

    test('falha no envio fica anotada no bloco, que segue pendente', () async {
      await chunk('aula-a', 1700000001000, _wav(32000));
      final lesson = (await service.scan()).single;

      await service.recover(
          lesson, (c, bytes) async => throw Exception('HTTP 503: carregando'));

      final stored = (await service.chunksOf('aula-a')).single;
      expect(stored.state, ChunkState.pending);
      expect(stored.detail, contains('HTTP 503'));
    });
  });

  group('manifesto', () {
    test('guarda o nível de áudio que o bloco tinha', () async {
      final file = await chunk('aula-a', 1700000000000, _wav(32000));

      await service.noteChunk('aula-a', file.path,
          peak: 0.25, micPeak: 0.25, systemPeak: 0.0);

      final stored = (await service.chunksOf('aula-a')).single;
      expect(stored.peak, 0.25);
      expect(stored.micPeak, 0.25);
      expect(stored.systemPeak, 0.0);
      expect(stored.peakDb, closeTo(-12.04, 0.01));
    });

    test('anotações do mesmo bloco se somam', () async {
      final file = await chunk('aula-a', 1700000000000, _wav(32000));
      await service.noteChunk('aula-a', file.path, peak: 0.5);
      await service.noteChunk('aula-a', file.path, micPeak: 0.4);

      final stored = (await service.chunksOf('aula-a')).single;
      expect((stored.peak, stored.micPeak), (0.5, 0.4));
    });

    test('escritas simultâneas não perdem nenhuma', () async {
      final files = [
        for (var i = 0; i < 8; i++)
          await chunk('aula-a', 1700000000000 + i * 1000, _wav(32000)),
      ];

      await Future.wait([
        for (var i = 0; i < files.length; i++)
          service.noteChunk('aula-a', files[i].path, peak: (i + 1) / 10),
      ]);

      final peaks =
          (await service.chunksOf('aula-a')).map((c) => c.peak).toList();
      expect(peaks, [for (var i = 1; i <= 8; i++) i / 10]);
    });

    test('manifesto corrompido não atrapalha o áudio', () async {
      await chunk('aula-a', 1700000000000, _wav(32000));
      await File('${root.path}${Platform.pathSeparator}aula-a'
              '${Platform.pathSeparator}manifest.json')
          .writeAsString('{ isto nao e json');

      final stored = (await service.chunksOf('aula-a')).single;

      expect(stored.peak, isNull);
      expect(stored.bytes, 44 + 32000);
    });

    test('sem manifesto, lista os blocos mesmo assim', () async {
      await chunk('aula-a', 1700000002000, _wav(32000));
      await chunk('aula-a', 1700000001000, _wav(32000));

      final stored = await service.chunksOf('aula-a');

      expect(stored.map((c) => c.startedAt.millisecondsSinceEpoch),
          [1700000001000, 1700000002000]);
    });
  });

  group('limpeza do áudio guardado', () {
    Future<void> montar() async {
      final a = await chunk('aula-a', 1700000001000, _wav(32000));
      await service.markResult('aula-a', a, state: ChunkState.sent);
      final b = await chunk('aula-a', 1700000002000, _wav(32000));
      await service.markResult('aula-a', b, state: ChunkState.quiet);
      await chunk('aula-a', 1700000003000, _wav(32000)); // pendente
      final c = await chunk('aula-b', 1700000004000, _wav(64000));
      await service.markResult('aula-b', c, state: ChunkState.sent);
    }

    test('conta o que já foi entregue e o que ainda está pendente', () async {
      await montar();

      final geral = await service.usage();
      final aulaA = await service.usage(lessonId: 'aula-a');

      expect((geral.chunks, geral.pending), (3, 1));
      expect(geral.bytes, 2 * (44 + 32000) + (44 + 64000));
      expect((aulaA.chunks, aulaA.pending), (2, 1));
      expect(geral.isEmpty, isFalse);
    });

    test('rótulo de tamanho em KB e MB', () {
      expect(const StoredAudioUsage(chunks: 1, bytes: 512 * 1024).sizeLabel,
          '512 KB');
      expect(
          const StoredAudioUsage(chunks: 1, bytes: 3 * 1024 * 1024).sizeLabel,
          '3.0 MB');
    });

    test('limpar uma aula apaga o entregue e nunca o que ainda não subiu',
        () async {
      await montar();

      final removed = await service.clearDelivered(lessonId: 'aula-a');

      expect(removed, 2);
      final left = await service.chunksOf('aula-a');
      expect(left.map((c) => c.state), [ChunkState.pending]);
      // A outra aula não foi tocada.
      expect(await service.chunksOf('aula-b'), hasLength(1));
    });

    test('limpar tudo remove as pastas que ficaram sem nada', () async {
      await montar();
      await service.discard('aula-a'); // tira o pendente para a pasta esvaziar

      final removed = await service.clearDelivered();

      expect(removed, 1);
      expect(await root.list().toList(), isEmpty);
    });

    test('sem nada guardado não há o que limpar', () async {
      expect(await service.clearDelivered(), 0);
      expect((await service.usage()).isEmpty, isTrue);
    });
  });

  group('nível de áudio', () {
    test('pico do WAV de 16 bits', () {
      final wav = _wav(1000, fill: 0);
      ByteData.sublistView(wav).setInt16(44 + 200, -16384, Endian.little);

      expect(LessonRecoveryService.wavPeak(wav), closeTo(0.5, 0.0001));
    });

    test('silêncio absoluto tem pico zero e vira -120 dB', () {
      final wav = _wav(1000, fill: 0);
      expect(LessonRecoveryService.wavPeak(wav), 0);
      expect(peakToDb(0), -120);
    });

    test('o que não é WAV não tem pico', () {
      expect(LessonRecoveryService.wavPeak(Uint8List(100)), isNull);
    });

    test('conversão para dBFS', () {
      expect(peakToDb(1), 0);
      expect(peakToDb(0.5), closeTo(-6.02, 0.01));
      expect(peakToDb(0.0025), closeTo(-52.04, 0.01));
      expect(peakToDb(2), 0); // nunca passa de zero
    });

    test('acha os dados depois de um bloco LIST', () {
      final base = _wav(100, fill: 0);
      final list = [...'LIST'.codeUnits, 4, 0, 0, 0, 1, 2, 3, 4];
      final bytes = Uint8List.fromList(
          [...base.sublist(0, 36), ...list, ...base.sublist(36)]);
      ByteData.sublistView(bytes).setInt16(48 + 8 + 10, 8192, Endian.little);

      expect(LessonRecoveryService.wavPeak(bytes), closeTo(0.25, 0.0001));
    });
  });

  group('discard', () {
    test('apaga o áudio guardado da aula e só dela', () async {
      await chunk('aula-a', 1700000000000, _wav(32000));
      await chunk('aula-b', 1700000001000, _wav(32000));

      await service.discard('aula-a');

      expect((await service.scan()).map((l) => l.lessonId), ['aula-b']);
    });

    test('aula sem nada guardado não dá erro', () async {
      await service.discard('nao-existe');
    });
  });

  group('repairWavHeader', () {
    test('WAV íntegro volta igual', () {
      final wav = _wav(32000);
      expect(LessonRecoveryService.repairWavHeader(wav), wav);
    });

    test('cabeçalho zerado pela queda passa a refletir o arquivo', () {
      final fixed = LessonRecoveryService.repairWavHeader(
          _wav(64000, closed: false));
      expect(_u32(fixed, 40), 64000);
      expect(_u32(fixed, 4), 36 + 64000);
      expect(fixed.length, 44 + 64000);
    });

    test('byte solto no fim (amostra cortada ao meio) é descartado', () {
      final cut = Uint8List.fromList([..._wav(32000, closed: false), 9]);
      final fixed = LessonRecoveryService.repairWavHeader(cut);
      expect(fixed.length, 44 + 32000);
      expect(_u32(fixed, 40), 32000);
    });

    test('acha o bloco data depois de um bloco LIST', () {
      final base = _wav(4000, closed: false);
      final list = [
        ...'LIST'.codeUnits, 4, 0, 0, 0, 1, 2, 3, 4, // bloco LIST de 4 bytes
      ];
      final bytes = Uint8List.fromList(
          [...base.sublist(0, 36), ...list, ...base.sublist(36)]);

      final fixed = LessonRecoveryService.repairWavHeader(bytes);

      // data começa em 36 + 12 = 48; os dados têm 4000 bytes.
      expect(String.fromCharCodes(fixed.sublist(48, 52)), 'data');
      expect(_u32(fixed, 52), 4000);
      expect(_u32(fixed, 4), fixed.length - 8);
    });

    test('tamanho "indefinido" (0xFFFFFFFF) também é corrigido', () {
      final wav = _wav(8000);
      ByteData.sublistView(wav).setUint32(40, 0xFFFFFFFF, Endian.little);
      expect(_u32(LessonRecoveryService.repairWavHeader(wav), 40), 8000);
    });

    test('o que não é WAV volta como estava', () {
      final mp4 = Uint8List.fromList(List.generate(200, (i) => i));
      expect(LessonRecoveryService.repairWavHeader(mp4), mp4);
      final curto = Uint8List(5);
      expect(LessonRecoveryService.repairWavHeader(curto), curto);
    });

    test('WAV sem bloco data volta como estava', () {
      final bytes = Uint8List.fromList(_wav(100).sublist(0, 36));
      expect(LessonRecoveryService.repairWavHeader(bytes), bytes);
    });
  });

  group('LessonRecoveryBanner', () {
    RecoverableLesson lesson(int blocks, {int bytes = 32000 * 60}) =>
        RecoverableLesson(
          lessonId: 'a',
          chunks: [
            for (var i = 0; i < blocks; i++)
              RecoverableChunk(
                file: File('chunk_$i.wav'),
                bytes: 44 + bytes,
                startedAt: DateTime(2026, 10, 5, 10, i),
              ),
          ],
        );

    Future<void> show(
      WidgetTester tester,
      RecoverableLesson item, {
      String label = '',
      bool busy = false,
      VoidCallback? onRecover,
      VoidCallback? onDiscard,
    }) {
      return tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: LessonRecoveryBanner(
            lesson: item,
            label: label,
            busy: busy,
            onRecover: onRecover ?? () {},
            onDiscard: onDiscard ?? () {},
          ),
        ),
      ));
    }

    testWidgets('diz quantos blocos e quanto tempo ficaram guardados',
        (tester) async {
      await show(tester, lesson(5), label: 'BANCO DE DADOS - Normalizacao');

      expect(find.textContaining('5 blocos'), findsOneWidget);
      expect(find.textContaining('cerca de 5 minutos'), findsOneWidget);
      expect(find.textContaining('da aula BANCO DE DADOS - Normalizacao'),
          findsOneWidget);
      expect(find.textContaining('ainda não foram transcritos'), findsOneWidget);
    });

    testWidgets('sem nome da aula e no singular', (tester) async {
      await show(tester, lesson(1, bytes: 32000 * 40));

      expect(find.textContaining('1 bloco '), findsOneWidget);
      expect(find.textContaining('cerca de 40 segundos'), findsOneWidget);
      expect(find.textContaining('de uma aula'), findsOneWidget);
    });

    testWidgets('recuperar e descartar chamam o que a tela passou',
        (tester) async {
      var recovered = 0, discarded = 0;
      await show(tester, lesson(2),
          onRecover: () => recovered++, onDiscard: () => discarded++);

      await tester.tap(find.text('RECUPERAR'));
      await tester.tap(find.text('DESCARTAR'));

      expect((recovered, discarded), (1, 1));
    });

    testWidgets('enviando, os dois botões ficam travados', (tester) async {
      var calls = 0;
      await show(tester, lesson(2),
          busy: true, onRecover: () => calls++, onDiscard: () => calls++);

      expect(find.text('ENVIANDO...'), findsOneWidget);
      await tester.tap(find.text('ENVIANDO...'));
      await tester.tap(find.text('DESCARTAR'));
      expect(calls, 0);
    });
  });
}

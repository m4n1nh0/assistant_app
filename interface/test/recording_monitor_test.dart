import 'dart:io';

import 'package:assistant_app/services/lesson_recovery_service.dart';
import 'package:assistant_app/widgets/recording_monitor.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:record/record.dart';

const _fifine = InputDevice(id: 'fifine', label: 'Microfone (fifine SC3)');
const _intel = InputDevice(id: 'intel', label: 'Grupo de microfones (Intel)');

Future<void> _show(WidgetTester tester, Widget child) {
  tester.view.physicalSize = const Size(1200, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  return tester.pumpWidget(MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child))));
}

StoredChunk _chunk(
  int stamp, {
  ChunkState state = ChunkState.sent,
  double? peak,
  double? micPeak,
  double? systemPeak,
  String detail = '',
  int bytes = 44 + 32000 * 60,
  String? name,
}) =>
    StoredChunk(
      file: File('lesson_chunks/aula/${name ?? "chunk_$stamp.wav"}'),
      bytes: bytes,
      startedAt: DateTime(2026, 10, 5, 9, 0, 0).add(Duration(minutes: stamp)),
      state: state,
      peak: peak,
      micPeak: micPeak,
      systemPeak: systemPeak,
      detail: detail,
    );

void main() {
  group('faixas de nível', () {
    test('separa sem sinal, baixo, bom e alto demais pelos dBFS', () {
      expect(classifyLevel(0), LevelKind.silent);
      expect(classifyLevel(0.0005), LevelKind.silent); // -66 dB
      expect(classifyLevel(0.0025), LevelKind.low); // -52 dB: o ruído de uma sala quieta
      expect(classifyLevel(0.03), LevelKind.low); // -30,5 dB: logo abaixo da faixa boa
      expect(classifyLevel(0.04), LevelKind.good); // -28 dB
      expect(classifyLevel(0.3), LevelKind.good);
      expect(classifyLevel(0.9), LevelKind.hot); // -0,9 dB
    });

    test('rótulos e dB legíveis', () {
      expect(levelLabel(LevelKind.silent), 'SEM SINAL');
      expect(levelLabel(LevelKind.good), 'BOM');
      expect(dbText(0), 'sem sinal');
      expect(dbText(0.5), '-6 dB');
    });

    test('dBFS do plugin de gravação vira escala linear', () {
      expect(dbToPeak(0), 1);
      expect(dbToPeak(-6.0206), closeTo(0.5, 0.001));
      expect(dbToPeak(-160), 0);
      expect(dbToPeak(10), 1); // nunca passa do máximo
    });
  });

  group('InputLevelMeter', () {
    testWidgets('a barra enche conforme o nível e o texto diz o estado',
        (tester) async {
      await _show(tester, const InputLevelMeter(label: 'Microfone', peak: 0.1));

      final bar = tester.widget<FractionallySizedBox>(find.byType(FractionallySizedBox));
      expect(bar.widthFactor, closeTo(0.667, 0.01)); // -20 dB de uma escala de 60
      expect(find.text('-20 dB  BOM'), findsOneWidget);
    });

    testWidgets('sem sinal a barra fica vazia e o texto avisa', (tester) async {
      await _show(tester, const InputLevelMeter(label: 'Microfone', peak: 0));

      expect(
        tester.widget<FractionallySizedBox>(find.byType(FractionallySizedBox)).widthFactor,
        0,
      );
      expect(find.text('sem sinal  SEM SINAL'), findsOneWidget);
    });
  });

  group('RecordingMonitor', () {
    Widget monitor({
      bool recording = true,
      bool showSystem = false,
      List<InputDevice> devices = const [_fifine, _intel],
      String selectedId = '',
      String selectedLabel = '',
      ValueChanged<InputDevice?>? onSelect,
      Duration? silentFor,
      Duration elapsed = const Duration(seconds: 83),
      int bytes = 0,
      String? idleHint,
      bool busy = false,
      LevelReading reading = const LevelReading(mic: 0.1, system: 0.02),
    }) =>
        RecordingMonitor(
          level: ValueNotifier(reading),
          recording: recording,
          showSystem: showSystem,
          devices: devices,
          selectedId: selectedId,
          selectedLabel: selectedLabel,
          onSelectDevice: onSelect ?? (_) {},
          onRefreshDevices: () {},
          silentFor: silentFor,
          blockElapsed: elapsed,
          blockBytes: bytes,
          idleHint: idleHint,
          busy: busy,
        );

    testWidgets('gravando mostra o nível do microfone e o tempo do bloco',
        (tester) async {
      await _show(tester, monitor(bytes: 720 * 1024));

      expect(find.text('Microfone'), findsOneWidget);
      expect(find.text('-20 dB  BOM'), findsOneWidget);
      expect(find.textContaining('Bloco atual: 1:23'), findsOneWidget);
      expect(find.textContaining('720 KB gravados'), findsOneWidget);
    });

    testWidgets('sem tamanho de arquivo não mostra "0 KB gravados"',
        (tester) async {
      await _show(tester, monitor(bytes: 44));

      expect(find.textContaining('Bloco atual: 1:23'), findsOneWidget);
      expect(find.textContaining('gravados'), findsNothing);
    });

    testWidgets('na reunião online mostra as duas origens separadas',
        (tester) async {
      await _show(tester, monitor(showSystem: true));

      expect(find.text('Seu microfone'), findsOneWidget);
      expect(find.text('Som do computador'), findsOneWidget);
      expect(find.text('-34 dB  BAIXO'), findsOneWidget); // 0,02 do som do computador
    });

    testWidgets('sem gravar, as barras ficam zeradas e o texto explica',
        (tester) async {
      await _show(tester, monitor(recording: false));

      expect(find.text('sem sinal  SEM SINAL'), findsOneWidget);
      expect(find.textContaining('Gravação pausada'), findsOneWidget);
    });

    testWidgets('antes da aula mostra a orientação passada pela tela',
        (tester) async {
      await _show(
        tester,
        monitor(recording: false, idleHint: 'Escolha o microfone antes de começar.'),
      );

      expect(find.text('Escolha o microfone antes de começar.'), findsOneWidget);
      expect(find.textContaining('Gravação pausada'), findsNothing);
    });

    testWidgets('avisa quando nenhum som chega e diz o que fazer', (tester) async {
      await _show(tester, monitor(silentFor: const Duration(seconds: 12)));

      expect(find.textContaining('Nenhum som chegou nos últimos 12 s'), findsOneWidget);
      expect(find.textContaining('escolha outro dispositivo'), findsOneWidget);
    });

    testWidgets('o aviso de silêncio não aparece com a gravação pausada',
        (tester) async {
      await _show(
        tester,
        monitor(recording: false, silentFor: const Duration(seconds: 30)),
      );
      expect(find.textContaining('Nenhum som chegou'), findsNothing);
    });

    testWidgets('lista o padrão do Windows e cada microfone', (tester) async {
      await _show(tester, monitor());

      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();

      expect(find.text('Microfone padrão do Windows'), findsWidgets);
      expect(find.text('Microfone (fifine SC3)'), findsOneWidget);
      expect(find.text('Grupo de microfones (Intel)'), findsOneWidget);
    });

    testWidgets('escolher um microfone entrega o dispositivo, e o padrão entrega nulo',
        (tester) async {
      final chosen = <InputDevice?>[];
      await _show(tester, monitor(selectedId: 'intel', onSelect: chosen.add));

      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Microfone (fifine SC3)').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Microfone padrão do Windows').last);
      await tester.pumpAndSettle();

      expect(chosen, [_fifine, null]);
    });

    testWidgets('microfone salvo que sumiu aparece como indisponível',
        (tester) async {
      await _show(
        tester,
        monitor(
          selectedId: 'jbl',
          selectedLabel: 'Headset (JBL Tune 530BT)',
        ),
      );

      expect(find.text('Headset (JBL Tune 530BT) (indisponível)'), findsOneWidget);
    });

    testWidgets('durante a troca o seletor fica travado', (tester) async {
      final chosen = <InputDevice?>[];
      await _show(tester, monitor(busy: true, onSelect: chosen.add));

      await tester.tap(find.byType(DropdownButton<String>), warnIfMissed: false);
      await tester.pumpAndSettle();

      expect(find.text('Microfone (fifine SC3)'), findsNothing);
      expect(chosen, isEmpty);
    });
  });

  group('explicação do bloco sem fala', () {
    test('sem sinal aponta a captura', () {
      expect(
        quietExplanation(_chunk(1, state: ChunkState.quiet, peak: 0)),
        contains('problema está na captura'),
      );
    });

    test('som baixo manda aproximar o microfone', () {
      expect(
        quietExplanation(_chunk(1, state: ChunkState.quiet, peak: 0.01)),
        contains('muito baixo'),
      );
    });

    test('com som normal o culpado é o reconhecimento', () {
      expect(
        quietExplanation(_chunk(1, state: ChunkState.quiet, peak: 0.3)),
        contains('o reconhecimento não entendeu'),
      );
    });

    test('só vale para bloco sem fala e com nível medido', () {
      expect(quietExplanation(_chunk(1, state: ChunkState.sent, peak: 0)), isNull);
      expect(quietExplanation(_chunk(1, state: ChunkState.quiet)), isNull);
    });
  });

  group('ChunkList', () {
    ChunkList list(
      List<StoredChunk> chunks, {
      String? livePath,
      String? playingPath,
      StoredAudioUsage usage = const StoredAudioUsage(chunks: 2, bytes: 3 * 1024 * 1024),
      ValueChanged<StoredChunk>? onPlay,
      ValueChanged<StoredChunk>? onResend,
      VoidCallback? onOpenFolder,
      VoidCallback? onClear,
    }) =>
        ChunkList(
          chunks: chunks,
          usage: usage,
          livePath: livePath,
          playingPath: playingPath,
          onPlay: onPlay ?? (_) {},
          onResend: onResend ?? (_) {},
          onOpenFolder: onOpenFolder ?? () {},
          onClear: onClear ?? () {},
        );

    testWidgets('mostra cada bloco com horário, duração, nível e estado',
        (tester) async {
      await _show(
        tester,
        list([
          _chunk(0, peak: 0.1),
          _chunk(1, state: ChunkState.quiet, peak: 0, detail: 'nenhuma fala reconhecida'),
        ]),
      );

      expect(find.text('BLOCOS GRAVADOS (2)'), findsOneWidget);
      expect(find.text('TRANSCRITO'), findsOneWidget);
      expect(find.text('SEM FALA'), findsOneWidget);
      expect(find.text('09:00:00'), findsOneWidget);
      expect(find.text('09:01:00'), findsOneWidget);
      expect(find.text('60s'), findsNWidgets(2));
      expect(find.textContaining('nível -20 dB · bom'), findsOneWidget);
      expect(find.textContaining('problema está na captura'), findsOneWidget);
    });

    testWidgets('o bloco mais recente fica no topo', (tester) async {
      await _show(tester, list([_chunk(0), _chunk(1), _chunk(2)]));

      final first = tester.getTopLeft(find.text('#1')).dy;
      final last = tester.getTopLeft(find.text('#3')).dy;
      expect(last < first, isTrue);
    });

    testWidgets('na reunião mostra o pico de cada origem', (tester) async {
      await _show(
        tester,
        list([_chunk(0, peak: 0.1, micPeak: 0.1, systemPeak: 0)]),
      );

      expect(find.textContaining('mic -20 dB · som do PC sem sinal'), findsOneWidget);
    });

    testWidgets('bloco que falhou mostra o erro; o aguardando não', (tester) async {
      await _show(
        tester,
        list([
          _chunk(0, state: ChunkState.pending),
          _chunk(1, state: ChunkState.pending, detail: 'HTTP 503: carregando'),
        ]),
      );

      expect(find.text('AGUARDANDO'), findsOneWidget);
      expect(find.text('FALHOU'), findsOneWidget);
      expect(find.textContaining('Último erro: HTTP 503'), findsOneWidget);
    });

    testWidgets('ouvir e reenviar entregam o bloco certo', (tester) async {
      final played = <StoredChunk>[], resent = <StoredChunk>[];
      final quiet = _chunk(1, state: ChunkState.quiet, peak: 0.2);
      await _show(
        tester,
        list([quiet], onPlay: played.add, onResend: resent.add),
      );

      await tester.tap(find.byTooltip('Ouvir este bloco'));
      await tester.tap(find.byTooltip('Reenviar para transcrição'));

      expect(played, [quiet]);
      expect(resent, [quiet]);
    });

    testWidgets('bloco já transcrito não oferece reenviar', (tester) async {
      var resent = 0;
      await _show(tester, list([_chunk(0)], onResend: (_) => resent++));

      await tester.tap(find.byTooltip('Reenviar para transcrição'), warnIfMissed: false);
      expect(resent, 0);
    });

    testWidgets('o bloco que está gravando agora não pode ser tocado nem reenviado',
        (tester) async {
      var calls = 0;
      final live = _chunk(0, state: ChunkState.pending);
      await _show(
        tester,
        list([live],
            livePath: live.file.path,
            onPlay: (_) => calls++,
            onResend: (_) => calls++),
      );

      expect(find.text('GRAVANDO'), findsOneWidget);
      await tester.tap(find.byTooltip('Ouvir este bloco'), warnIfMissed: false);
      await tester.tap(find.byTooltip('Reenviar para transcrição'), warnIfMissed: false);
      expect(calls, 0);
    });

    testWidgets('o que está tocando oferece parar', (tester) async {
      final playing = _chunk(0, peak: 0.2);
      await _show(tester, list([playing], playingPath: playing.file.path));

      expect(find.byTooltip('Parar'), findsOneWidget);
    });

    testWidgets('abrir pasta e limpar chamam o que a tela passou', (tester) async {
      var opened = 0, cleared = 0;
      await _show(
        tester,
        list([_chunk(0)], onOpenFolder: () => opened++, onClear: () => cleared++),
      );

      await tester.tap(find.text('ABRIR PASTA'));
      await tester.tap(find.textContaining('LIMPAR ENTREGUES (2 · 3.0 MB)'));

      expect((opened, cleared), (1, 1));
    });

    testWidgets('sem áudio entregue o botão de limpar fica travado', (tester) async {
      var cleared = 0;
      await _show(
        tester,
        list([_chunk(0, state: ChunkState.pending)],
            usage: const StoredAudioUsage(pending: 1), onClear: () => cleared++),
      );

      await tester.tap(find.textContaining('LIMPAR ENTREGUES (0'), warnIfMissed: false);
      expect(cleared, 0);
    });

    testWidgets('sem blocos diz quando o primeiro vai aparecer', (tester) async {
      await _show(tester, list(const []));

      expect(find.text('BLOCOS GRAVADOS (0)'), findsOneWidget);
      expect(find.textContaining('primeiro minuto fechar'), findsOneWidget);
    });
  });
}

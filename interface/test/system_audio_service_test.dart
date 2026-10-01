import 'package:assistant_app/services/system_audio_service.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// A captura do som do computador vive no executavel; aqui fica fixado o que
/// a interface manda para ele e como le a resposta de cada bloco.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('intarq/system_audio');
  final calls = <MethodCall>[];
  Object? reply;

  setUp(() {
    calls.clear();
    reply = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return reply;
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('start leva o arquivo e o microfone escolhido', () async {
    await SystemAudioRecorder().start(path: r'C:\tmp\a.wav', micDeviceId: 'm1');

    expect(calls.single.method, 'start');
    expect(calls.single.arguments, {'path': r'C:\tmp\a.wav', 'micDeviceId': 'm1'});
  });

  test('rotate devolve o bloco fechado com o pico de cada origem', () async {
    reply = {'path': r'C:\tmp\a.wav', 'systemPeak': 0.42, 'micPeak': 0.1};

    final chunk = await SystemAudioRecorder().rotate(r'C:\tmp\b.wav');

    expect(calls.single.arguments, {'path': r'C:\tmp\b.wav'});
    expect(chunk?.path, r'C:\tmp\a.wav');
    expect(chunk?.systemPeak, 0.42);
    expect(chunk?.systemSilent, isFalse);
  });

  test('bloco sem som do computador e reconhecido como silencioso', () async {
    reply = {'path': r'C:\tmp\a.wav', 'systemPeak': 0.0, 'micPeak': 0.3};

    final chunk = await SystemAudioRecorder().stop();

    expect(chunk?.systemSilent, isTrue);
    expect(chunk?.micPeak, 0.3);
  });

  test('stop sem gravacao em andamento nao devolve bloco', () async {
    expect(await SystemAudioRecorder().stop(), isNull);
  });
}

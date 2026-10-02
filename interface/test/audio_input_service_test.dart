import 'package:assistant_app/services/audio_input_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:record/record.dart';

void main() {
  audioInputProblemTests();
  const devices = [
    InputDevice(id: 'built-in', label: 'Microfone interno'),
    InputDevice(id: 'jbl-new-id', label: 'JBL Hands-Free AG Audio'),
  ];

  test('resolves the configured microphone by exact id', () {
    final selected = resolveAudioInputDevice(
      devices,
      deviceId: 'built-in',
      deviceLabel: 'outro nome',
    );
    expect(selected?.id, 'built-in');
  });

  test('recovers a reconnected Bluetooth microphone by label', () {
    final selected = resolveAudioInputDevice(
      devices,
      deviceId: 'jbl-old-id',
      deviceLabel: 'jbl hands-free ag audio',
    );
    expect(selected?.id, 'jbl-new-id');
  });

  test('does not silently replace an unavailable configured microphone', () {
    final selected = resolveAudioInputDevice(
      devices,
      deviceId: 'missing',
      deviceLabel: 'Headset indisponivel',
    );
    expect(selected, isNull);
  });
}

void audioInputProblemTests() {
  const devices = [
    InputDevice(id: 'fifine', label: 'Microfone (fifine SC3)'),
  ];

  test('flags a machine with no active microphone before the lesson starts',
      () {
    final problem = audioInputProblem(const <InputDevice>[], deviceId: '');
    expect(problem, contains('nenhum microfone ativo'));
  });

  test('accepts the system default when the list is not empty', () {
    expect(audioInputProblem(devices, deviceId: ''), isNull);
  });

  test('names the saved microphone that is no longer connected', () {
    final problem = audioInputProblem(
      devices,
      deviceId: 'jbl',
      deviceLabel: 'Headset (JBL Tune 530BT)',
    );
    expect(problem, contains('Headset (JBL Tune 530BT)'));
    expect(problem, contains('nao esta disponivel'));
  });

  test('accepts a saved microphone that came back with another id', () {
    expect(
      audioInputProblem(
        devices,
        deviceId: 'old-id',
        deviceLabel: 'microfone (fifine sc3)',
      ),
      isNull,
    );
  });
}

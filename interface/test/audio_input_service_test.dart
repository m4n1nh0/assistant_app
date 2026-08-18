import 'package:assistant_app/services/audio_input_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:record/record.dart';

void main() {
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

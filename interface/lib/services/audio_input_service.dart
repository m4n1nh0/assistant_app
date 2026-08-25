/// Captura de audio do microfone para transcricao e wake word.
library;

import 'package:record/record.dart';

/// Resolve a entrada salva pelo identificador e, depois, pelo nome. O segundo
/// caminho permite reencontrar headsets Bluetooth cujo ID muda ao reconectar.
InputDevice? resolveAudioInputDevice(
  Iterable<InputDevice> devices, {
  required String deviceId,
  String deviceLabel = '',
}) {
  if (deviceId.trim().isEmpty) return null;

  for (final device in devices) {
    if (device.id == deviceId) return device;
  }

  final expectedLabel = deviceLabel.trim().toLowerCase();
  if (expectedLabel.isNotEmpty) {
    for (final device in devices) {
      if (device.label.trim().toLowerCase() == expectedLabel) return device;
    }
  }
  return null;
}

RecordConfig speechRecordConfig({
  required AudioEncoder encoder,
  InputDevice? device,
}) =>
    RecordConfig(
      encoder: encoder,
      bitRate: 128000,
      sampleRate: 16000,
      numChannels: 1,
      device: device,
      autoGain: true,
      noiseSuppress: true,
      echoCancel: true,
    );

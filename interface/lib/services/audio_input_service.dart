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

/// Motivo pelo qual nao ha entrada para gravar, ou `null` quando ha.
///
/// Sem nenhum microfone ativo no Windows o `record` falha com um erro de
/// driver que nao diz o que fazer; aqui o professor recebe a causa antes de a
/// aula ser criada. Uma entrada salva que sumiu nao e trocada em silencio.
String? audioInputProblem(
  Iterable<InputDevice> devices, {
  required String deviceId,
  String deviceLabel = '',
}) {
  if (devices.isEmpty) {
    return 'o Windows nao listou nenhum microfone ativo. Conecte um '
        'microfone (ou religue o Bluetooth do fone) e tente de novo';
  }
  if (deviceId.trim().isNotEmpty &&
      resolveAudioInputDevice(devices,
              deviceId: deviceId, deviceLabel: deviceLabel) ==
          null) {
    final name = deviceLabel.trim().isEmpty ? 'selecionado' : deviceLabel.trim();
    return 'o microfone $name nao esta disponivel. Conecte-o ou escolha '
        'outro em Configuracoes > Sistema';
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

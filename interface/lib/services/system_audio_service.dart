/// Gravacao do som do computador somado ao microfone, para reuniao online.
library;

import 'dart:io';

import 'package:flutter/services.dart';

/// Bloco de audio fechado pela captura do som do computador.
class SystemAudioChunk {
  final String path;

  /// Maior amplitude (0 a 1) que veio da saida de som durante o bloco. Zero
  /// significa que nada tocou no computador — ou que a reuniao esta saindo
  /// por um aparelho que nao e a saida padrao do Windows.
  final double systemPeak;
  final double micPeak;

  const SystemAudioChunk({
    required this.path,
    this.systemPeak = 0,
    this.micPeak = 0,
  });

  bool get systemSilent => systemPeak <= 0;

  static SystemAudioChunk? fromChannel(Object? value) {
    if (value is! Map) return null;
    final path = value['path']?.toString() ?? '';
    if (path.isEmpty) return null;
    return SystemAudioChunk(
      path: path,
      systemPeak: (value['systemPeak'] as num?)?.toDouble() ?? 0,
      micPeak: (value['micPeak'] as num?)?.toDouble() ?? 0,
    );
  }
}

/// O que a captura ouviu nos ultimos instantes, para o medidor ao vivo.
class SystemAudioLevel {
  /// Picos (0 a 1) desde a consulta anterior.
  final double micPeak;
  final double systemPeak;

  /// Quanto do bloco atual ja foi gravado, em bytes de audio.
  final int bytes;

  const SystemAudioLevel({
    this.micPeak = 0,
    this.systemPeak = 0,
    this.bytes = 0,
  });

  static SystemAudioLevel? fromChannel(Object? value) {
    if (value is! Map) return null;
    return SystemAudioLevel(
      micPeak: (value['micPeak'] as num?)?.toDouble() ?? 0,
      systemPeak: (value['systemPeak'] as num?)?.toDouble() ?? 0,
      bytes: (value['bytes'] as num?)?.toInt() ?? 0,
    );
  }
}

/// Grava o que o computador esta tocando junto com o microfone.
///
/// O microfone sozinho nao registra uma reuniao do Meet ou do Teams: a voz dos
/// outros participantes sai pelo fone e nunca chega nele. Aqui a captura e
/// feita na saida de som do Windows, e o arquivo resultante e o mesmo WAV de
/// 16 kHz mono da gravacao comum — o backend nao distingue um do outro.
class SystemAudioRecorder {
  static const _channel = MethodChannel('intarq/system_audio');

  /// A captura da saida de som so existe no executavel do Windows.
  static bool get isSupported => Platform.isWindows;

  /// Comeca a gravar em [path]. [micDeviceId] vazio usa o microfone padrao.
  Future<void> start({required String path, String micDeviceId = ''}) =>
      _channel.invokeMethod<void>('start', {
        'path': path,
        'micDeviceId': micDeviceId,
      });

  /// Fecha o bloco atual e segue gravando em [path], sem parar a captura.
  Future<SystemAudioChunk?> rotate(String path) async =>
      SystemAudioChunk.fromChannel(
        await _channel.invokeMethod<Object?>('rotate', {'path': path}),
      );

  /// Picos recentes do microfone e do som do computador. Zera a contagem: cada
  /// consulta mostra o que chegou desde a anterior. Executavel antigo, sem o metodo,
  /// devolve `null` e a tela segue sem o medidor em vez de falhar.
  Future<SystemAudioLevel?> level() async {
    try {
      return SystemAudioLevel.fromChannel(
        await _channel.invokeMethod<Object?>('level'),
      );
    } on MissingPluginException {
      return null;
    }
  }

  /// Para a captura e devolve o ultimo bloco, se havia gravacao.
  Future<SystemAudioChunk?> stop() async => SystemAudioChunk.fromChannel(
        await _channel.invokeMethod<Object?>('stop'),
      );
}

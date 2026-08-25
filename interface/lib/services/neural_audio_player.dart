/// Reproducao do audio sintetizado, com implementacao propria no Windows.
///
/// O player padrao engasga com os trechos curtos e encadeados do TTS, entao no
/// Windows usa-se um caminho dedicado.
library;

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart' as audio;
import 'package:media_kit/media_kit.dart' as media;

/// Reproduz os bytes gerados pelo TTS sem usar o plugin audioplayers no
/// Windows. O backend nativo desse plugin emite eventos fora da platform
/// thread; no Windows, media_kit usa FFI e evita esse PlatformChannel.
class NeuralAudioPlayer {
  audio.AudioPlayer? _fallbackPlayer;
  media.Player? _windowsPlayer;
  StreamSubscription<Object?>? _stateSubscription;
  StreamSubscription<Object?>? _completeSubscription;

  final _playingController = StreamController<bool>.broadcast();
  final _completeController = StreamController<void>.broadcast();

  Stream<bool> get playing => _playingController.stream;
  Stream<void> get completed => _completeController.stream;

  Future<void> _ensurePlayer() async {
    if (Platform.isWindows) {
      if (_windowsPlayer != null) return;
      media.MediaKit.ensureInitialized();
      final player = media.Player();
      _windowsPlayer = player;
      _stateSubscription = player.stream.playing.listen((value) {
        if (!_playingController.isClosed) _playingController.add(value);
      });
      _completeSubscription = player.stream.completed.listen((value) {
        if (value && !_completeController.isClosed) {
          _completeController.add(null);
        }
      });
      return;
    }

    if (_fallbackPlayer != null) return;
    final player = audio.AudioPlayer();
    _fallbackPlayer = player;
    _stateSubscription = player.onPlayerStateChanged.listen((value) {
      if (!_playingController.isClosed) {
        _playingController.add(value == audio.PlayerState.playing);
      }
    });
    _completeSubscription = player.onPlayerComplete.listen((_) {
      if (!_completeController.isClosed) _completeController.add(null);
    });
  }

  Future<void> play(Uint8List bytes) async {
    if (bytes.isEmpty) return;
    await _ensurePlayer();
    await stop();
    if (Platform.isWindows) {
      final source = await media.Media.memory(bytes, type: 'audio/mpeg');
      await _windowsPlayer!.open(source, play: true);
    } else {
      await _fallbackPlayer!.play(audio.BytesSource(bytes));
    }
  }

  Future<void> stop() async {
    if (Platform.isWindows) {
      await _windowsPlayer?.stop();
    } else {
      await _fallbackPlayer?.stop();
    }
  }

  Future<void> dispose() async {
    await _stateSubscription?.cancel();
    await _completeSubscription?.cancel();
    await _windowsPlayer?.dispose();
    await _fallbackPlayer?.dispose();
    await _playingController.close();
    await _completeController.close();
  }
}

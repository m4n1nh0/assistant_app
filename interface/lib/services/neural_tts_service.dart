import 'dart:typed_data';

import 'package:edge_tts/edge_tts.dart';

/// Gera a fala da assistente na propria interface, usando as vozes neurais
/// gratuitas do Edge.
///
/// A sintese acontece aqui e nao no backend porque em producao o backend fica
/// remoto: mandar o MP3 de cada resposta de volta pela rede custa banda e
/// atrasa a fala. O Edge ainda exige internet, entao quem chama deve manter um
/// fallback local (flutter_tts) para quando a rede falhar.
class NeuralTtsService {
  /// Vozes pt-BR do Edge, na ordem em que aparecem para o usuario.
  static const voices = <String, String>{
    'pt-BR-FranciscaNeural': 'Francisca (feminina)',
    'pt-BR-ThalitaMultilingualNeural': 'Thalita (feminina)',
    'pt-BR-AntonioNeural': 'Antonio (masculina)',
  };

  static const defaultFemaleVoice = 'pt-BR-FranciscaNeural';
  static const defaultMaleVoice = 'pt-BR-AntonioNeural';

  static String defaultVoiceFor(String gender) =>
      gender == 'm' ? defaultMaleVoice : defaultFemaleVoice;

  static String resolveVoice(String configured, String gender) {
    final trimmed = configured.trim();
    if (voices.containsKey(trimmed)) return trimmed;
    return defaultVoiceFor(gender);
  }

  /// Converte o ajuste percentual salvo na configuracao para o formato que o
  /// Edge espera ("+8%" / "-6%"); 0 vira "+0%".
  static String formatRate(int percent) {
    final clamped = percent.clamp(-50, 50);
    return '${clamped >= 0 ? '+' : ''}$clamped%';
  }

  /// Idem para o tom, em Hz ("+30Hz" / "-25Hz").
  static String formatPitch(int hz) {
    final clamped = hz.clamp(-50, 50);
    return '${clamped >= 0 ? '+' : ''}${clamped}Hz';
  }

  /// Devolve o MP3 falado, ou uma lista vazia se a sintese falhar — nesse caso
  /// quem chamou deve cair no TTS local do sistema.
  static Future<Uint8List> synthesize(
    String text, {
    required String voice,
    int ratePercent = 0,
    int pitchHz = 0,
  }) async {
    final speech = text.trim();
    if (speech.isEmpty) return Uint8List(0);

    final communicate = Communicate(
      text: speech,
      voice: voice,
      rate: formatRate(ratePercent),
      pitch: formatPitch(pitchHz),
    );
    return communicate.toBytes();
  }
}

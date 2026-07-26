import 'package:assistant_app/services/neural_tts_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('formata rate e pitch no formato que o Edge espera', () {
    expect(NeuralTtsService.formatRate(0), '+0%');
    expect(NeuralTtsService.formatRate(8), '+8%');
    expect(NeuralTtsService.formatRate(-6), '-6%');
    expect(NeuralTtsService.formatPitch(0), '+0Hz');
    expect(NeuralTtsService.formatPitch(-25), '-25Hz');
    expect(NeuralTtsService.formatPitch(30), '+30Hz');
  });

  test('limita valores fora da faixa em vez de repassar ao servico', () {
    expect(NeuralTtsService.formatRate(999), '+50%');
    expect(NeuralTtsService.formatPitch(-999), '-50Hz');
  });

  test('resolve a voz pelo genero quando nada foi escolhido', () {
    expect(NeuralTtsService.resolveVoice('', 'f'), 'pt-BR-FranciscaNeural');
    expect(NeuralTtsService.resolveVoice('', 'm'), 'pt-BR-AntonioNeural');
    expect(NeuralTtsService.resolveVoice('   ', 'f'), 'pt-BR-FranciscaNeural');
  });

  test('ignora voz salva que nao existe mais', () {
    expect(
      NeuralTtsService.resolveVoice('pt-BR-VozRemovidaNeural', 'f'),
      'pt-BR-FranciscaNeural',
    );
  });

  test('respeita a voz escolhida pelo usuario', () {
    expect(
      NeuralTtsService.resolveVoice('pt-BR-ThalitaMultilingualNeural', 'f'),
      'pt-BR-ThalitaMultilingualNeural',
    );
  });

  test('texto vazio nao chama o servico', () async {
    expect(
      (await NeuralTtsService.synthesize('   ', voice: 'pt-BR-FranciscaNeural'))
          .length,
      0,
    );
  });
}

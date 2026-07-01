import 'package:assistant_app/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('ComputerActionResult builds a visible local summary', () {
    const result = ComputerActionResult(
      actionId: 'network_diagnostics',
      actionName: 'Diagnostico de rede',
      status: 'executed',
      summary: 'IP externo detectado: 203.0.113.10 Ping executado com sucesso.',
      outputs: [
        ComputerCommandOutput(
          label: 'IP externo',
          command: 'GET https://api.ipify.org',
          exitCode: 0,
          stdout: '203.0.113.10',
          stderr: '',
          durationMs: 50,
        ),
        ComputerCommandOutput(
          label: 'Ping Google',
          command: 'ping google.com',
          exitCode: 1,
          stdout: '',
          stderr: 'falhou',
          durationMs: 2000,
        ),
      ],
      durationMs: 2050,
    );

    final text = result.toLocalSummaryText();

    expect(text, contains('Resultado local coletado: Diagnostico de rede'));
    expect(text, contains('- IP externo: ok'));
    expect(text, contains('- Ping Google: erro 1'));
    expect(text, contains('Vou enviar os dados completos para a IA analisar.'));
  });
}

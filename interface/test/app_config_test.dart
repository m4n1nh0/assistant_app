import 'package:assistant_app/models/app_config.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('LlmStatus reports checking separately from offline', () {
    const status = LlmStatus(
      id: 'gpt',
      label: 'GPT',
      configured: true,
      online: false,
      available: false,
      hasBalanceCheck: false,
      status: 'checking',
    );

    expect(status.shortStatus, 'CHECANDO');
  });
}

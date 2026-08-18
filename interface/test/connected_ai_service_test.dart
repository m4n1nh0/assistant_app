import 'package:assistant_app/services/connected_ai_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('detects supported desktop clients without reading credentials',
      () async {
    final statuses = await ConnectedAiService.checkAll();

    expect(statuses.map((item) => item.id).toSet(), {
      'codex_cli',
      'claude_cli',
    });
    for (final status in statuses) {
      expect(status.label, isNotEmpty);
      if (status.authenticated) {
        expect(status.installed, isTrue);
        expect(status.executablePath, isNotEmpty);
      }
    }
  });
}

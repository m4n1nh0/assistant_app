import 'package:assistant_app/services/local_script_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('runs a simple script in the local default shell', () async {
    final info = await LocalScriptService.shellInfo();
    final shell = info.defaultShell;
    final script = switch (shell) {
      'powershell' || 'pwsh' => 'Write-Output "assistant-local-ok"',
      _ => 'echo assistant-local-ok',
    };

    final result = await LocalScriptService.runScript(
      shell: shell,
      script: script,
      timeoutSeconds: 10,
    );

    expect(result.timedOut, isFalse);
    expect(result.exitCode, 0);
    expect(result.stdout, contains('assistant-local-ok'));
  });

  test('blocks high-risk scripts without explicit permission', () async {
    final info = await LocalScriptService.shellInfo();
    final shell = info.defaultShell;
    final script = switch (shell) {
      'powershell' ||
      'pwsh' =>
        r'Remove-Item C:\temp\assistant -Recurse -Force',
      'cmd' => r'del /s /q C:\temp\assistant',
      _ => 'rm -rf /',
    };

    expect(
      () => LocalScriptService.runScript(shell: shell, script: script),
      throwsA(isA<LocalScriptException>()),
    );
  });
}

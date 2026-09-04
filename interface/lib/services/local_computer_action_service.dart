/// Coletores de diagnostico que rodam nesta maquina.
///
/// Quem despacha por id e o catalogo em `local_capability_registry.dart`; aqui
/// ficam so os coletores, cada um sem saber por que foi chamado.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'api_service.dart';
import 'local_script_service.dart';

/// Falha ao executar uma acao de computador na maquina.
class LocalComputerActionException implements Exception {
  final String message;

  const LocalComputerActionException(this.message);

  @override
  String toString() => message;
}

/// Executa na maquina do usuario as acoes que o backend propos.
///
/// O backend deliberadamente nao executa nada disso: ele monta e valida a acao, e a
/// execucao acontece aqui, depois da confirmacao do usuario.
class LocalComputerActionService {
  /// Coleta a configuracao de rede, o IP externo e um ping desta maquina.
  static Future<ComputerActionResult> runNetworkDiagnostics({
    String name = 'Diagnostico de rede',
  }) async {
    final started = DateTime.now();
    final outputs = <ComputerCommandOutput>[];

    if (Platform.isWindows) {
      outputs.add(
        await _runCommand('Configuracao IP', ['ipconfig', '/all'], 10),
      );
      outputs.add(
        await _runCommand(
          'Ping Google',
          ['ping', '-n', '3', '-w', '2500', 'google.com'],
          20,
        ),
      );
    } else if (Platform.isMacOS) {
      outputs.add(await _runCommand('Configuracao IP', ['ifconfig'], 10));
      outputs.add(await _runCommand('Rotas', ['netstat', '-rn'], 10));
      outputs.add(
        await _runCommand('Ping Google', ['ping', '-c', '3', 'google.com'], 12),
      );
    } else {
      outputs.add(await _runCommand('Configuracao IP', ['ip', 'addr'], 10));
      outputs.add(await _runCommand('Rotas', ['ip', 'route'], 10));
      outputs.add(
        await _runCommand('Ping Google', ['ping', '-c', '3', 'google.com'], 12),
      );
    }

    final externalIpStarted = DateTime.now();
    final externalIp = await _externalIp();
    if (externalIp.isNotEmpty) {
      outputs.insert(
        1,
        ComputerCommandOutput(
          label: 'IP externo',
          command: 'GET https://api.ipify.org',
          exitCode: 0,
          stdout: externalIp,
          stderr: '',
          // Medido de verdade: 0ms fixo fazia a etapa parecer nao ter rodado
          // nesta maquina.
          durationMs:
              DateTime.now().difference(externalIpStarted).inMilliseconds,
        ),
      );
    }

    return ComputerActionResult(
      actionId: 'network_diagnostics',
      actionName: name,
      status: 'executed',
      summary: _buildNetworkSummary(outputs),
      outputs: outputs,
      durationMs: DateTime.now().difference(started).inMilliseconds,
    );
  }

  /// Coleta memoria, processos por consumo e uso de disco desta maquina.
  static Future<ComputerActionResult> runSystemDiagnostics({
    String name = 'Diagnostico do sistema',
  }) async {
    final started = DateTime.now();
    final script = await _systemDiagnosticsScript();
    final result = await LocalScriptService.runScript(
      shell: script.key,
      script: script.value,
      timeoutSeconds: 45,
    );
    final output = ComputerCommandOutput(
      label: 'Recursos do sistema',
      command: result.command,
      exitCode: result.exitCode,
      stdout: result.stdout,
      stderr: result.stderr,
      durationMs: result.durationMs,
    );
    return ComputerActionResult(
      actionId: 'system_diagnostics',
      actionName: name,
      status: result.exitCode == 0 ? 'executed' : 'failed',
      summary: result.exitCode == 0
          ? 'Coleta finalizada. Inclui memoria/RAM, processos por consumo e uso de disco.'
          : 'Coleta de diagnostico do sistema retornou erro.',
      outputs: [output],
      durationMs: DateTime.now().difference(started).inMilliseconds,
    );
  }

  static Future<ComputerCommandOutput> _runCommand(
    String label,
    List<String> command,
    int timeoutSeconds,
  ) async {
    final started = DateTime.now();
    try {
      final process = await Process.start(
        command.first,
        command.sublist(1),
        runInShell: false,
      );
      const decoder = Utf8Decoder(allowMalformed: true);
      final stdoutFuture = process.stdout.transform(decoder).join();
      final stderrFuture = process.stderr.transform(decoder).join();
      var exitCode = 0;
      var timedOut = false;
      try {
        exitCode = await process.exitCode.timeout(
          Duration(seconds: timeoutSeconds),
        );
      } on TimeoutException {
        timedOut = true;
        exitCode = 124;
        process.kill();
        await process.exitCode
            .timeout(const Duration(seconds: 2), onTimeout: () => exitCode);
      }

      final stdout = await stdoutFuture.timeout(
        const Duration(seconds: 2),
        onTimeout: () => '',
      );
      var stderr = await stderrFuture.timeout(
        const Duration(seconds: 2),
        onTimeout: () => '',
      );
      if (timedOut && stderr.trim().isEmpty) {
        stderr = 'Timeout apos ${timeoutSeconds}s';
      }
      return ComputerCommandOutput(
        label: label,
        command: command.map(_quoteIfNeeded).join(' '),
        exitCode: exitCode,
        stdout: _trim(stdout),
        stderr: _trim(stderr),
        durationMs: DateTime.now().difference(started).inMilliseconds,
      );
    } catch (e) {
      return ComputerCommandOutput(
        label: label,
        command: command.map(_quoteIfNeeded).join(' '),
        exitCode: 1,
        stdout: '',
        stderr: e.toString(),
        durationMs: DateTime.now().difference(started).inMilliseconds,
      );
    }
  }

  static Future<String> _externalIp() async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final request = await client
          .getUrl(Uri.parse('https://api.ipify.org'))
          .timeout(const Duration(seconds: 8));
      final response =
          await request.close().timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return '';
      return (await response.transform(utf8.decoder).join())
          .trim()
          .replaceAll(RegExp(r'\s+'), ' ');
    } catch (_) {
      return '';
    } finally {
      client.close(force: true);
    }
  }

  static String _buildNetworkSummary(List<ComputerCommandOutput> outputs) {
    final failures = outputs.where((item) => item.exitCode != 0).toList();
    final ping = outputs
        .where((item) => item.label == 'Ping Google')
        .cast<ComputerCommandOutput?>()
        .firstOrNull;
    final external = outputs
        .where((item) => item.label == 'IP externo')
        .cast<ComputerCommandOutput?>()
        .firstOrNull;
    final parts = <String>[];
    if (external != null && external.stdout.trim().isNotEmpty) {
      parts.add('IP externo detectado: ${external.stdout.trim()}');
    }
    if (ping != null) {
      parts.add(
        ping.exitCode == 0 ? 'Ping executado com sucesso.' : 'Ping falhou.',
      );
    }
    if (failures.isNotEmpty) {
      parts.add('${failures.length} etapa(s) retornaram erro.');
    }
    if (parts.isEmpty) parts.add('Diagnostico coletado.');
    return parts.join(' ');
  }

  static Future<MapEntry<String, String>> _systemDiagnosticsScript() async {
    final info = await LocalScriptService.shellInfo();
    if (Platform.isWindows) {
      final shell = info.availableShells.contains('powershell')
          ? 'powershell'
          : info.availableShells.contains('pwsh')
              ? 'pwsh'
              : info.defaultShell;
      return MapEntry(shell, r'''
$ErrorActionPreference = 'Continue'
Write-Output "=== SISTEMA ==="
Get-CimInstance Win32_OperatingSystem |
  Select-Object @{N='RAM_Total_GB';E={[math]::Round($_.TotalVisibleMemorySize/1MB,2)}},
                @{N='RAM_Livre_GB';E={[math]::Round($_.FreePhysicalMemory/1MB,2)}},
                LastBootUpTime |
  Out-String -Width 180

Write-Output ""
Write-Output "=== TOP PROCESSOS POR RAM ==="
Get-Process |
  Sort-Object WorkingSet -Descending |
  Select-Object -First 15 Name, Id, @{N='RAM_MB';E={[math]::Round($_.WorkingSet/1MB,2)}}, CPU |
  Out-String -Width 180

Write-Output ""
Write-Output "=== DISCOS ==="
Get-PSDrive -PSProvider FileSystem |
  Select-Object Name,
                @{N='Usado_GB';E={[math]::Round($_.Used/1GB,2)}},
                @{N='Livre_GB';E={[math]::Round($_.Free/1GB,2)}},
                @{N='Total_GB';E={[math]::Round(($_.Used + $_.Free)/1GB,2)}} |
  Out-String -Width 180
''');
    }

    final shell = info.availableShells.contains('bash')
        ? 'bash'
        : info.availableShells.contains('zsh')
            ? 'zsh'
            : info.defaultShell;
    return MapEntry(shell, '''
set +e
echo "=== SISTEMA ==="
uname -a
uptime
echo
echo "=== MEMORIA ==="
if command -v free >/dev/null 2>&1; then
  free -h
else
  vm_stat 2>/dev/null || true
fi
echo
echo "=== TOP PROCESSOS POR RAM ==="
ps -eo pid,comm,%mem,%cpu,rss --sort=-rss 2>/dev/null | head -n 16 || ps aux | head -n 16
echo
echo "=== DISCOS ==="
df -h
''');
  }

  static String _quoteIfNeeded(String value) {
    if (value.isEmpty) return '""';
    if (!RegExp(r'\s').hasMatch(value)) return value;
    return '"${value.replaceAll('"', r'\"')}"';
  }

  static String _trim(String value, {int limit = 12000}) {
    final clean = value.trim();
    if (clean.length <= limit) return clean;
    return '${clean.substring(0, limit - 28).trimRight()}\n...[saida truncada]';
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull {
    final iterator = this.iterator;
    if (!iterator.moveNext()) return null;
    return iterator.current;
  }
}

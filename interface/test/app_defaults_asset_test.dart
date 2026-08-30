/// Guarda do asset de distribuicao.
///
/// Este teste existe por causa de um incidente real: o arquivo
/// `assets/config/app_defaults.json` foi removido do disco, o build seguiu sem
/// erro, e o app passou a apontar todos os usuarios para `localhost:8000`. O
/// unico sintoma era "nao conecta".
///
/// O Flutter nao reclama de uma pasta de asset declarada e vazia, entao a
/// verificacao precisa acontecer aqui: `flutter test` reprova antes de o build
/// virar release.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  const assetPath = 'assets/config/app_defaults.json';

  group('asset de defaults da distribuicao', () {
    test('existe em disco', () {
      final file = File(assetPath);

      expect(
        file.existsSync(),
        isTrue,
        reason:
            '$assetPath nao existe. Sem ele o app cai para localhost:8000 em '
            'qualquer build, sem erro visivel. Recrie o arquivo com '
            '{"environment": "...", "backendUrl": "https://..."}.',
      );
    });

    test('e um JSON valido com backendUrl utilizavel', () {
      final raw = File(assetPath).readAsStringSync();

      final decoded = jsonDecode(raw);
      expect(decoded, isA<Map>(),
          reason: '$assetPath deve ser um objeto JSON.');

      final backendUrl =
          (decoded as Map)['backendUrl']?.toString().trim() ?? '';
      expect(
        backendUrl,
        isNotEmpty,
        reason: 'backendUrl vazio faz o app usar o endereco de '
            'desenvolvimento, ignorando o asset.',
      );

      final parsed = Uri.tryParse(backendUrl);
      expect(parsed, isNotNull, reason: 'backendUrl nao e uma URL valida.');
      expect(
        parsed!.hasScheme &&
            (parsed.isScheme('http') || parsed.isScheme('https')),
        isTrue,
        reason: 'backendUrl precisa comecar com http:// ou https://.',
      );
    });

    test('nao aponta para localhost quando o ambiente e producao', () {
      final decoded = jsonDecode(File(assetPath).readAsStringSync())
          as Map<String, dynamic>;
      final environment =
          decoded['environment']?.toString().trim().toLowerCase() ?? '';
      final host =
          Uri.parse(decoded['backendUrl'].toString()).host.toLowerCase();

      if (environment != 'production') return;

      expect(
        host == 'localhost' || host == '127.0.0.1' || host == '::1',
        isFalse,
        reason:
            'environment=production com backendUrl em $host: a distribuicao '
            'apontaria para a maquina de cada usuario.',
      );
    });

    test('a pasta esta declarada no pubspec', () {
      final pubspec = File('pubspec.yaml').readAsStringSync();

      expect(
        pubspec.contains('assets/config/'),
        isTrue,
        reason: 'assets/config/ precisa estar declarada em pubspec.yaml, '
            'senao o arquivo nao entra no bundle.',
      );
    });
  });
}

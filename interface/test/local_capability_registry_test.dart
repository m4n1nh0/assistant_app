import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/local_capability_registry.dart';

/// O catalogo e a fonte do manifesto e do executor ao mesmo tempo: e isso que
/// impede a interface de anunciar o que nao sabe fazer, ou de executar algo que
/// nunca foi anunciado ao backend.
void main() {
  test('toda capacidade declarada e executavel pelo id', () {
    for (final capability in LocalCapabilityRegistry.all) {
      expect(
        LocalCapabilityRegistry.find(capability.id),
        same(capability),
        reason: '${capability.id} esta declarada mas nao resolve por id',
      );
    }
  });

  test('id declarado duas vezes nao passa despercebido', () {
    final ids = LocalCapabilityRegistry.all.map((item) => item.id).toList();

    expect(ids.toSet().length, ids.length);
  });

  test('capacidade sem descricao nao serve para o modelo escolher', () {
    for (final capability in LocalCapabilityRegistry.all) {
      // A descricao e o unico texto que o modelo le para decidir se a
      // capacidade serve: vazia, ela some na pratica.
      expect(capability.description.trim(), isNotEmpty,
          reason: '${capability.id} sem descricao');
      expect(capability.name.trim(), isNotEmpty);
      expect(capability.argsSchema['type'], 'object');
    }
  });

  test('o que altera a maquina pede confirmacao', () {
    for (final capability in LocalCapabilityRegistry.all) {
      if (capability.readOnly) continue;
      expect(capability.requiresConfirmation, isTrue,
          reason: '${capability.id} escreve na maquina sem confirmar');
    }
  });

  test('manifesto sai serializavel e so com o que roda aqui', () {
    final manifest = LocalCapabilityRegistry.manifest();

    // Vai por HTTP/WebSocket: o que nao serializa nao existe para o backend.
    expect(() => jsonEncode(manifest), returnsNormally);
    expect(manifest['platform'], LocalCapabilityRegistry.currentPlatform);

    final entries = (manifest['capabilities'] as List).cast<Map>();
    expect(entries.length, LocalCapabilityRegistry.supportedHere.length);
    expect(
      entries.map((item) => item['id']),
      containsAll(<String>['network_diagnostics', 'inspect_workspace']),
    );

    final script = entries.firstWhere((item) => item['id'] == 'run_script');
    expect(script['risk_level'], 'medium');
    expect(script['requires_confirmation'], isTrue);
    expect(script['read_only'], isFalse);
    expect(
      (script['args_schema'] as Map)['required'],
      contains('script'),
    );
  });

  test('capacidade desconhecida falha nomeando o id', () async {
    await expectLater(
      LocalCapabilityRegistry.run('formatar_disco', const {}),
      throwsA(isA<LocalCapabilityException>().having(
        (e) => e.message,
        'message',
        contains('formatar_disco'),
      )),
    );
  });

  test('script vazio nao chega ao shell', () async {
    await expectLater(
      LocalCapabilityRegistry.run('run_script', const {'script': '   '}),
      throwsA(isA<LocalCapabilityException>()),
    );
  });
}

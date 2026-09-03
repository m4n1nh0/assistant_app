import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/local_capability_registry.dart';

/// O manifesto e o contrato entre a interface e o backend: a interface declara,
/// o backend registra como ferramenta remota e o modelo escolhe pela descricao.
///
/// O arquivo em `contracts/` e a copia que o teste do backend le. Mexer no
/// catalogo sem regenerar o contrato quebra este teste de proposito - e o unico
/// aviso que existe antes de os dois lados discordarem em producao.
void main() {
  final contract = File('../contracts/local_capability_manifest.json');

  test('o catalogo declarado bate com o contrato publicado', () {
    final golden = jsonDecode(contract.readAsStringSync()) as Map;
    final live = LocalCapabilityRegistry.all
        .map((item) => item.toManifestEntry())
        .toList();

    expect(
      jsonDecode(jsonEncode(live)),
      golden['capabilities'],
      reason: 'Catalogo mudou: regenere contracts/'
          'local_capability_manifest.json',
    );
  });
}

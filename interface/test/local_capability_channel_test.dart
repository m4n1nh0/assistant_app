import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/services/local_capability_channel.dart';
import 'package:assistant_app/services/local_capability_registry.dart';

/// O lado da maquina no ciclo de capacidade: publicar o catalogo, atender o
/// pedido e responder pelo mesmo `call_id`.
void main() {
  late List<Map<String, dynamic>> sent;

  setUp(() => sent = []);

  LocalCapabilityChannel channel({
    CapabilityConfirmer? confirm,
    void Function(String)? onRefused,
  }) =>
      LocalCapabilityChannel(
        send: sent.add,
        confirm: confirm,
        onRefused: onRefused,
      );

  Map<String, dynamic> call(String capabilityId, [Map<String, dynamic>? args]) =>
      {
        'type': 'tool_call',
        'payload': {
          'call_id': 'c-1',
          'capability_id': capabilityId,
          'arguments': args ?? const {},
        },
      };

  test('publica o catalogo desta maquina ao abrir a sessao', () {
    channel().publishManifest();

    expect(sent.single['type'], 'capabilities');
    final payload = sent.single['payload'] as Map<String, dynamic>;
    expect(payload['platform'], LocalCapabilityRegistry.currentPlatform);
    expect((payload['capabilities'] as List), isNotEmpty);
  });

  test('capacidade desconhecida volta recusada, nao em silencio', () async {
    await channel().handleMessage(call('formatar_disco'));

    final reply = sent.single['payload'] as Map<String, dynamic>;
    expect(sent.single['type'], 'tool_result');
    expect(reply['call_id'], 'c-1');
    expect(reply['ok'], isFalse);
    expect(reply['error'], contains('formatar_disco'));
  });

  test('sem confirmador, o que exige confirmacao nao roda', () async {
    final avisos = <String>[];

    // `inspect_workspace` le arquivos do usuario: sem alguem para autorizar, a
    // resposta certa e recusar, nao executar.
    await channel(onRefused: avisos.add).handleMessage(
      call('inspect_workspace', {'query': 'x'}),
    );

    final reply = sent.single['payload'] as Map<String, dynamic>;
    expect(reply['ok'], isFalse);
    expect(reply['error'], contains('confirmacao'));
    expect(avisos.single, contains('sem confirmacao'));
  });

  test('usuario que recusa encerra a chamada com motivo', () async {
    final avisos = <String>[];
    var perguntou = false;

    await channel(
      confirm: (capability, args) async {
        perguntou = true;
        return false;
      },
      onRefused: avisos.add,
    ).handleMessage(call('inspect_workspace', {'query': 'x'}));

    expect(perguntou, isTrue);
    final reply = sent.single['payload'] as Map<String, dynamic>;
    expect(reply['ok'], isFalse);
    expect(reply['error'], contains('nao autorizou'));
    expect(avisos.single, contains('cancelada'));
  });

  test('o confirmador recebe a capacidade e os argumentos do pedido', () async {
    LocalCapability? vista;
    Map<String, dynamic>? argsVistos;

    await channel(
      confirm: (capability, args) async {
        vista = capability;
        argsVistos = args;
        return false;
      },
    ).handleMessage(call('run_script', {'script': 'echo oi', 'shell': 'bash'}));

    expect(vista?.id, 'run_script');
    expect(vista?.riskLevel, 'medium');
    expect(argsVistos?['script'], 'echo oi');
  });

  test('falha na execucao vira resposta, nao excecao solta', () async {
    // Script vazio estoura dentro do catalogo: o canal precisa transformar isso
    // em `ok:false`, senao a conversa do outro lado espera ate o timeout.
    await channel(confirm: (_, __) async => true).handleMessage(
      call('run_script', {'script': '   '}),
    );

    final reply = sent.single['payload'] as Map<String, dynamic>;
    expect(reply['ok'], isFalse);
    expect(reply['capability_id'], 'run_script');
    expect(reply['error'], isNotEmpty);
  });

  test('recusa do backend no manifesto vira aviso legivel', () async {
    final avisos = <String>[];

    await channel(onRefused: avisos.add).handleMessage({
      'type': 'capabilities_ack',
      'payload': {
        'published': 3,
        'rejected': ['#2: sem descricao'],
      },
    });

    expect(sent, isEmpty);
    expect(avisos.single, contains('sem descricao'));
  });

  test('mensagem de outro assunto nao gera resposta', () async {
    await channel().handleMessage({'type': 'pong', 'payload': {}});

    expect(sent, isEmpty);
  });
}

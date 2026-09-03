/// O lado da interface no ciclo de capacidade local.
///
/// Publica o catalogo desta maquina quando a sessao abre e atende os pedidos de
/// execucao que chegam do backend: roda pelo catalogo, pergunta ao usuario
/// quando a capacidade exige, e devolve o resultado pelo mesmo `call_id`.
///
/// O transporte entra por injecao, entao o comportamento que so aparece em
/// producao - id desconhecido, usuario que cancela, capacidade que estoura -
/// e testavel sem abrir socket.
///
/// Uma regra que nao se negocia: **capacidade que pede confirmacao nao roda sem
/// alguem para confirmar**. Sem confirmador ligado, o pedido volta recusado, e
/// nao executado em silencio - o backend propoe, mas quem tem o usuario na
/// frente e aqui.
library;

import 'local_capability_registry.dart';

/// Envia uma mensagem pelo canal da sessao.
typedef CapabilitySend = void Function(Map<String, dynamic> message);

/// Pergunta ao usuario se pode executar. `false` recusa.
typedef CapabilityConfirmer = Future<bool> Function(
  LocalCapability capability,
  Map<String, dynamic> args,
);

/// Cliente do canal de capacidades.
class LocalCapabilityChannel {
  final CapabilitySend send;
  final CapabilityConfirmer? confirm;

  /// Avisa que uma execucao comecou, para a conversa mostrar o andamento.
  final void Function(LocalCapability capability)? onStarted;

  /// Entrega o resultado ja pronto, para a conversa mostrar o resumo local.
  final void Function(CapabilityRunResult result)? onExecuted;

  /// Avisa de recusa ou falha, com o motivo em texto.
  final void Function(String message)? onRefused;

  const LocalCapabilityChannel({
    required this.send,
    this.confirm,
    this.onStarted,
    this.onExecuted,
    this.onRefused,
  });

  /// Declara ao backend o que esta maquina sabe fazer.
  ///
  /// Chamado a cada conexao: o catalogo do backend e substituido pelo que
  /// chegar aqui, entao reconectar corrige qualquer divergencia.
  void publishManifest() {
    send({
      'type': 'capabilities',
      'payload': LocalCapabilityRegistry.manifest(),
    });
  }

  /// Trata uma mensagem do canal. Ignora o que nao for deste assunto.
  Future<void> handleMessage(Map<String, dynamic> message) async {
    final type = message['type']?.toString() ?? '';
    final payload = message['payload'];
    final data = payload is Map
        ? payload.map((key, value) => MapEntry(key.toString(), value))
        : <String, dynamic>{};

    switch (type) {
      case 'tool_call':
        await _runCall(data);
        return;
      case 'capabilities_ack':
        final rejected = (data['rejected'] as List?) ?? const [];
        if (rejected.isNotEmpty) {
          onRefused?.call(
            'O backend recusou ${rejected.length} capacidade(s): '
            '${rejected.join('; ')}',
          );
        }
        return;
    }
  }

  Future<void> _runCall(Map<String, dynamic> payload) async {
    final callId = payload['call_id']?.toString() ?? '';
    if (callId.isEmpty) return;

    final capabilityId = payload['capability_id']?.toString() ?? '';
    final rawArgs = payload['arguments'];
    final args = rawArgs is Map
        ? rawArgs.map((key, value) => MapEntry(key.toString(), value))
        : <String, dynamic>{};

    final capability = LocalCapabilityRegistry.find(capabilityId);
    if (capability == null) {
      _reply(callId, ok: false, error: 'Capacidade desconhecida nesta maquina: $capabilityId');
      return;
    }

    if (capability.requiresConfirmation) {
      final confirmer = confirm;
      if (confirmer == null) {
        _reply(
          callId,
          ok: false,
          error: '${capability.name} exige confirmacao e nao ha ninguem para '
              'confirmar nesta sessao.',
        );
        onRefused?.call('${capability.name} recusada: sem confirmacao.');
        return;
      }
      final allowed = await confirmer(capability, args);
      if (!allowed) {
        _reply(callId, ok: false, error: 'O usuario nao autorizou ${capability.name}.');
        onRefused?.call('${capability.name} cancelada pelo usuario.');
        return;
      }
    }

    onStarted?.call(capability);
    try {
      final result = await LocalCapabilityRegistry.run(capability.id, args);
      onExecuted?.call(result);
      _reply(
        callId,
        ok: result.ok,
        summary: result.summary,
        promptText: result.promptText,
        durationMs: result.durationMs,
        capabilityId: capability.id,
      );
    } catch (e) {
      _reply(callId, ok: false, error: '$e', capabilityId: capability.id);
      onRefused?.call('${capability.name} falhou: $e');
    }
  }

  void _reply(
    String callId, {
    required bool ok,
    String summary = '',
    String promptText = '',
    String error = '',
    int durationMs = 0,
    String capabilityId = '',
  }) {
    send({
      'type': 'tool_result',
      'payload': {
        'call_id': callId,
        'capability_id': capabilityId,
        'ok': ok,
        if (summary.isNotEmpty) 'summary': summary,
        if (promptText.isNotEmpty) 'prompt_text': promptText,
        if (error.isNotEmpty) 'error': error,
        'duration_ms': durationMs,
      },
    });
  }
}

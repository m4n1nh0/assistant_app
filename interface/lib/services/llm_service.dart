import 'dart:async';

import '../models/app_config.dart';
import 'api_service.dart';
import 'connected_ai_service.dart';

String _friendlyTimeout(String operation, Duration timeout) =>
    'Tempo limite excedido em $operation (${timeout.inSeconds}s). '
    'Tente novamente, use outro agente ou reduza o pedido.';

class LlmService {
  final AppConfig? config;
  final String workingDirectory;

  /// Autorização de edição do workspace concedida pelo usuário na interface.
  /// Vale apenas para agentes conectados: os provedores do backend recebem a
  /// instrução de edição pelo contexto do workspace enviado na mensagem.
  final bool allowWorkspaceEdits;

  /// Recebe a atividade em tempo real do agente conectado (por exemplo, o
  /// arquivo sendo lido/editado) para a interface exibir enquanto ele trabalha.
  final void Function(String activity)? onAgentProgress;

  /// Agente conectado imposto pela interface para este envio (roteamento de
  /// pedidos de edição do workspace), ignorando a seleção da conversa.
  final String? forcedConnectedAgent;

  LlmService({
    this.config,
    this.workingDirectory = '',
    this.allowWorkspaceEdits = false,
    this.onAgentProgress,
    this.forcedConnectedAgent,
  });

  /// Timeout dos modos do backend; maior com workspace ativo, porque o
  /// contexto do projeto deixa a resposta dos modelos locais bem mais lenta.
  Duration _timeoutFor(int baseSeconds) => Duration(
      seconds:
          workingDirectory.trim().isEmpty ? baseSeconds : baseSeconds + 180);

  /// Agente conectado escolhido na conversa, ou null para usar o backend.
  String? get _selectedConnectedAgent {
    if (forcedConnectedAgent != null) return forcedConnectedAgent;
    final current = config;
    if (current == null || !current.selectedIsConnectedAgent) return null;
    return current.effectiveAgent;
  }

  /// Provedor do backend fixado na conversa, ou null para orquestração auto.
  String? get _selectedBackendLlm {
    final current = config;
    if (current == null) return null;
    final selected = current.effectiveAgent;
    if (selected == AppConfig.autoAgent ||
        AppConfig.connectedAgentIds.contains(selected)) {
      return null;
    }
    return selected;
  }

  Future<ChatResult> _runConnectedAgent(
    String agentId,
    List<Map<String, String>> history,
    String text,
  ) async {
    final current = config!;
    final response = await ConnectedAiService.run(
      agentId: agentId,
      prompt: text,
      history: history,
      assistantName: current.assistantName,
      personality: current.personality,
      language: current.language,
      workingDirectory: workingDirectory,
      allowWorkspaceEdits: allowWorkspaceEdits,
      onProgress: onAgentProgress,
    );
    if (!response.isError) {
      // Mantém histórico e memória do backend completos mesmo quando a
      // resposta foi gerada localmente pelo cliente oficial.
      unawaited(
        api
            .logExternalChat(
              message: text,
              response: response.content,
              llm: response.agentId,
            )
            .catchError((_) => <String, dynamic>{}),
      );
    }
    return ChatResult(responses: [
      LlmResponse(
        llm: response.agentId,
        content: response.content,
        isError: response.isError,
        changedFiles: response.changedFiles,
      ),
    ]);
  }

  Future<ChatResult> call(
    List<Map<String, String>> history,
    String text,
  ) async {
    final connected = _selectedConnectedAgent;
    if (connected != null) return _runConnectedAgent(connected, history, text);
    final timeout = _timeoutFor(120);
    try {
      final data = await api
          .chat(
            message: text,
            history: history,
            mode: 'single',
            llm: _selectedBackendLlm,
          )
          .timeout(timeout);
      return _parseResult(data, fallbackLlm: 'backend');
    } on TimeoutException {
      return ChatResult(responses: [
        LlmResponse(
          llm: 'backend',
          content: _friendlyTimeout('chat', timeout),
          isError: true,
        ),
      ]);
    } catch (e) {
      return ChatResult(responses: [
        LlmResponse(
          llm: 'backend',
          content: 'Erro de conexao: $e',
          isError: true,
        ),
      ]);
    }
  }

  Future<ChatResult> callMulti(
    List<Map<String, String>> history,
    String text,
  ) async {
    final connected = _selectedConnectedAgent;
    if (connected != null) return _runConnectedAgent(connected, history, text);
    final timeout = _timeoutFor(150);
    try {
      final data = await api
          .chat(
            message: text,
            history: history,
            mode: 'multi',
            llm: _selectedBackendLlm,
          )
          .timeout(timeout);
      return _parseResult(data, fallbackLlm: 'backend');
    } on TimeoutException {
      return ChatResult(responses: [
        LlmResponse(
          llm: 'error',
          content: _friendlyTimeout('modo paralelo', timeout),
          isError: true,
        ),
      ]);
    } catch (e) {
      return ChatResult(responses: [
        LlmResponse(llm: 'error', content: 'Erro: $e', isError: true),
      ]);
    }
  }

  Future<ChatResult> callChain(
    List<Map<String, String>> history,
    String text,
  ) async {
    final connected = _selectedConnectedAgent;
    if (connected != null) return _runConnectedAgent(connected, history, text);
    final timeout = _timeoutFor(180);
    try {
      final data = await api
          .chat(
            message: text,
            history: history,
            mode: 'chain',
            llm: _selectedBackendLlm,
          )
          .timeout(timeout);
      return _parseResult(data, fallbackLlm: 'chain');
    } on TimeoutException {
      return ChatResult(responses: [
        LlmResponse(
          llm: 'chain',
          content: _friendlyTimeout('modo em etapas', timeout),
          isError: true,
        ),
      ]);
    } catch (e) {
      return ChatResult(responses: [
        LlmResponse(llm: 'chain', content: 'Erro: $e', isError: true),
      ]);
    }
  }

  ChatResult _parseResult(
    Map<String, dynamic> data, {
    required String fallbackLlm,
  }) {
    final rawResponses = data['responses'] as List<dynamic>? ?? const [];
    final responses = rawResponses.map((item) {
      final response = item as Map<String, dynamic>;
      return LlmResponse(
        llm: response['llm']?.toString() ?? fallbackLlm,
        content: response['content']?.toString() ?? '',
        isError: response['is_error'] == true,
        durationMs: response['duration_ms'] as int?,
      );
    }).toList();

    final rawAction = data['action'];
    LaunchAction? action;
    ShortcutRegistrationAction? registrationAction;
    if (rawAction is Map) {
      final actionData =
          rawAction.map((key, value) => MapEntry(key.toString(), value));
      final actionType = actionData['type']?.toString() ?? 'launch';
      if (actionType == 'register_shortcut') {
        registrationAction = ShortcutRegistrationAction.fromJson(actionData);
      } else if (actionType == 'education_open') {
        return ChatResult(
          responses: responses.isEmpty
              ? [
                  LlmResponse(
                    llm: fallbackLlm,
                    content: 'Posso abrir o Modo Aula para voce.',
                  ),
                ]
              : responses,
          educationOpenAction: EducationOpenAction.fromJson(actionData),
        );
      } else if (actionType == 'calendar_create') {
        return ChatResult(
          responses: responses.isEmpty
              ? [
                  LlmResponse(
                    llm: fallbackLlm,
                    content: 'Confirme os dados para criar o evento.',
                  ),
                ]
              : responses,
          calendarCreateAction: CalendarCreateAction.fromJson(actionData),
        );
      } else if (actionType == 'computer_action') {
        return ChatResult(
          responses: responses.isEmpty
              ? [
                  LlmResponse(
                    llm: fallbackLlm,
                    content: 'Sem resposta',
                    isError: true,
                  ),
                ]
              : responses,
          computerAction: ComputerAction.fromJson(actionData),
        );
      } else if (actionType == 'coding_action') {
        return ChatResult(
          responses: responses.isEmpty
              ? [
                  LlmResponse(
                    llm: fallbackLlm,
                    content: 'Sem resposta',
                    isError: true,
                  ),
                ]
              : responses,
          codingAction: CodingAction.fromJson(actionData),
        );
      } else {
        action = LaunchAction.fromJson(actionData);
      }
    }

    return ChatResult(
      responses: responses.isEmpty
          ? [
              LlmResponse(
                llm: fallbackLlm,
                content: 'Sem resposta',
                isError: true,
              ),
            ]
          : responses,
      action: action,
      registrationAction: registrationAction,
    );
  }
}

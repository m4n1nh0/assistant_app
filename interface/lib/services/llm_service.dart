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

  LlmService({this.config, this.workingDirectory = ''});

  Future<ChatResult> call(
    List<Map<String, String>> history,
    String text,
  ) async {
    final current = config;
    if (current?.connectedAgentMode == true) {
      final response = await ConnectedAiService.run(
        agentId: current!.connectedAgentId,
        prompt: text,
        history: history,
        assistantName: current.assistantName,
        personality: current.personality,
        language: current.language,
        workingDirectory: workingDirectory,
      );
      return ChatResult(responses: [
        LlmResponse(
          llm: response.agentId,
          content: response.content,
          isError: response.isError,
        ),
      ]);
    }
    try {
      const timeout = Duration(seconds: 120);
      final data = await api
          .chat(
            message: text,
            history: history,
            mode: 'single',
          )
          .timeout(timeout);
      return _parseResult(data, fallbackLlm: 'backend');
    } on TimeoutException {
      return ChatResult(responses: [
        LlmResponse(
          llm: 'backend',
          content: _friendlyTimeout('chat', const Duration(seconds: 120)),
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
    if (config?.connectedAgentMode == true) return call(history, text);
    try {
      const timeout = Duration(seconds: 150);
      final data = await api
          .chat(
            message: text,
            history: history,
            mode: 'multi',
          )
          .timeout(timeout);
      return _parseResult(data, fallbackLlm: 'backend');
    } on TimeoutException {
      return ChatResult(responses: [
        LlmResponse(
          llm: 'error',
          content:
              _friendlyTimeout('modo paralelo', const Duration(seconds: 150)),
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
    if (config?.connectedAgentMode == true) return call(history, text);
    try {
      const timeout = Duration(seconds: 180);
      final data = await api
          .chat(
            message: text,
            history: history,
            mode: 'chain',
          )
          .timeout(timeout);
      return _parseResult(data, fallbackLlm: 'chain');
    } on TimeoutException {
      return ChatResult(responses: [
        LlmResponse(
          llm: 'chain',
          content:
              _friendlyTimeout('modo em etapas', const Duration(seconds: 180)),
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

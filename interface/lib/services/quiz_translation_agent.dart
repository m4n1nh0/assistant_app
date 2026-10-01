/// Traducao das perguntas do quiz por um agente do computador do professor.
///
/// O servidor traduz com o provedor de IA do professor. Quando nao ha provedor
/// configurado, ou ele esta fora do ar, a turma que escolheu ingles ou espanhol
/// ficava lendo em portugues. O app do professor tem Codex e Claude conectados:
/// ele busca o prompt no servidor, executa o agente e devolve o texto. Quem
/// valida a traducao contra a pergunta original e grava e o servidor.
library;

import 'dart:async';

import 'connected_ai_service.dart';
import 'quiz_center_service.dart';
import 'quiz_specialist_review.dart' show AgentChecker, AgentRunner;

/// Nome de tela do idioma.
String nomeDoIdioma(String code) => switch (code) {
      'en' => 'English',
      'es' => 'Español',
      'pt' => 'Português',
      _ => code,
    };

/// Idioma que o servidor avisou estar sem traducao.
class PendingTranslation {
  final String language;
  final int students;
  final int missing;

  /// O servidor ja tentou e nao conseguiu (sem provedor, modelo fora do ar).
  final bool backendFailed;

  const PendingTranslation({
    required this.language,
    this.students = 0,
    this.missing = 0,
    this.backendFailed = false,
  });

  static List<PendingTranslation> listFrom(Object? raw) => raw is List
      ? [
          for (final item in raw.whereType<Map>())
            if ((item['language']?.toString() ?? '').isNotEmpty)
              PendingTranslation(
                language: item['language'].toString(),
                students: (item['students'] as num?)?.toInt() ?? 0,
                missing: (item['missing'] as num?)?.toInt() ?? 0,
                backendFailed: item['backend_failed'] == true,
              ),
        ]
      : const [];
}

class TranslationOutcome {
  final bool ok;

  /// Agente que traduziu, quando deu certo.
  final String agentLabel;

  /// Texto curto para o professor.
  final String message;
  final int stored;

  /// Nenhum agente instalado e conectado.
  final bool noAgents;

  const TranslationOutcome({
    required this.ok,
    required this.message,
    this.agentLabel = '',
    this.stored = 0,
    this.noAgents = false,
  });
}

/// Quanto o agente pode levar para traduzir o quiz inteiro.
const Duration translationTimeout = Duration(minutes: 6);

Future<ConnectedAiResult> _runConnectedAgent({
  required String agentId,
  required String prompt,
  required String systemPrompt,
  void Function(String activity)? onProgress,
}) =>
    ConnectedAiService.run(
      agentId: agentId,
      prompt: prompt,
      systemPrompt: systemPrompt,
      timeoutOverride: translationTimeout,
      onProgress: onProgress,
    );

/// Traduz com o primeiro agente conectado que conseguir.
///
/// Tenta os agentes em ordem e para no primeiro que o servidor aceita: nao ha
/// por que gastar a conta dos dois numa traducao so. O que um agente devolve
/// e o servidor recusa (JSON quebrado, alternativas que nao fecham) conta como
/// falha dele, e o proximo tenta.
Future<TranslationOutcome> translateWithAgent({
  required String quizId,
  required String language,
  QuizCenterService? service,
  AgentChecker? checkAgents,
  AgentRunner? runAgent,
  void Function(String message)? onProgress,
}) async {
  final center = service ?? quizCenter;
  final statuses = await (checkAgents ?? ConnectedAiService.checkAll)();
  final ready = statuses.where((s) => s.installed && s.authenticated).toList();
  if (ready.isEmpty) {
    return const TranslationOutcome(
      ok: false,
      noAgents: true,
      message: 'Nenhum agente conectado. Conecte o Codex ou o Claude em '
          'Configurações > Agentes, ou configure um provedor de IA.',
    );
  }

  final QuizTranslationPrompt prompt;
  try {
    prompt = await center.translationPrompt(quizId, language);
  } on QuizCenterException catch (error) {
    // 409: ja esta tudo traduzido (o servidor terminou no meio do caminho).
    return TranslationOutcome(ok: false, message: error.message);
  }

  final run = runAgent ?? _runConnectedAgent;
  final failures = <String>[];
  for (final status in ready) {
    final label = status.label
        .replaceAll(RegExp(r'\s*conectado\s*', caseSensitive: false), '')
        .trim();
    onProgress?.call('$label traduzindo para ${nomeDoIdioma(language)}...');
    ConnectedAiResult result;
    try {
      result = await run(
        agentId: status.id,
        prompt: prompt.prompt,
        systemPrompt: prompt.systemPrompt,
        onProgress: onProgress == null
            ? null
            : (activity) => onProgress('$label: $activity'),
      );
    } catch (error) {
      result = ConnectedAiResult(
        agentId: status.id,
        content: '$error',
        isError: true,
      );
    }
    if (result.isError) {
      failures.add('$label: ${result.content}');
      continue;
    }
    try {
      final saved = await center.submitTranslation(
        quizId,
        language: language,
        content: result.content,
      );
      return TranslationOutcome(
        ok: true,
        agentLabel: label,
        stored: (saved['stored'] as num?)?.toInt() ?? 0,
        message: 'Traduzido para ${nomeDoIdioma(language)} por $label.',
      );
    } on QuizCenterException catch (error) {
      failures.add('$label: ${error.message}');
    }
  }
  return TranslationOutcome(
    ok: false,
    message: 'Não consegui traduzir para ${nomeDoIdioma(language)}. '
        '${failures.join(' · ')}',
  );
}

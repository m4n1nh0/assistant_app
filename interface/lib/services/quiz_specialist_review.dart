/// Revisao das perguntas de um rascunho por Codex e Claude, os agentes
/// instalados no computador do professor.
///
/// Os dois rodam aqui, nao no servidor: o app pede o prompt ao backend, executa
/// cada agente no CLI dele e devolve o texto bruto. Quem le o JSON, confere com o
/// gabarito e decide o veredito e o servidor - o agente nao recebe o gabarito,
/// resolve cada pergunta so com o texto da aula.
library;

import 'dart:async';

import 'connected_ai_service.dart';
import 'quiz_center_service.dart';

/// Quanto cada agente pode levar. Ele le a aula inteira e resolve todas as
/// perguntas de uma vez; mais que isso e agente travado.
const Duration specialistTimeout = Duration(minutes: 12);

/// O que aconteceu com um agente nesta revisao.
class SpecialistRun {
  final String agentId;
  final String label;
  final bool ok;

  /// Motivo da falha, vazio quando deu certo.
  final String detail;

  const SpecialistRun({
    required this.agentId,
    required this.label,
    required this.ok,
    this.detail = '',
  });
}

class SpecialistReviewOutcome {
  final List<SpecialistRun> runs;

  /// O quiz como o servidor o devolveu depois da ultima revisao gravada, com o
  /// veredito de cada pergunta. `null` quando nenhum agente conseguiu revisar.
  final Map<String, dynamic>? quiz;

  /// Quantas perguntas ficaram em cada veredito.
  final Map<String, int> summary;

  const SpecialistReviewOutcome({
    this.runs = const [],
    this.quiz,
    this.summary = const {},
  });

  /// Nenhum agente estava instalado e conectado.
  bool get noAgents => runs.isEmpty;

  bool get anyOk => runs.any((run) => run.ok);

  /// Texto curto para o professor: o que cada agente fez e o resultado.
  String get message {
    if (noAgents) {
      return 'Nenhum agente conectado. Instale e conecte o Codex ou o Claude '
          'em Configurações > Agentes.';
    }
    final partes = [
      for (final run in runs)
        run.ok
            ? '${run.label}: revisou'
            : '${run.label}: falhou — ${run.detail}',
    ];
    if (anyOk && summary.isNotEmpty) {
      partes.add(describeReviewSummary(summary));
    }
    return partes.join(' · ');
  }
}

/// "8 aprovadas, 1 divergente" a partir da contagem por veredito.
String describeReviewSummary(Map<String, int> summary) {
  final partes = <String>[
    if ((summary['aprovada'] ?? 0) > 0)
      '${summary['aprovada']} aprovada${summary['aprovada'] == 1 ? '' : 's'}',
    if ((summary['divergente'] ?? 0) > 0)
      '${summary['divergente']} com divergência',
    if ((summary['revisar'] ?? 0) > 0) '${summary['revisar']} a revisar',
    if ((summary['sem_gabarito'] ?? 0) > 0)
      '${summary['sem_gabarito']} sem gabarito',
  ];
  return partes.join(', ');
}

typedef AgentChecker = Future<List<ConnectedAiStatus>> Function();
typedef AgentRunner = Future<ConnectedAiResult> Function({
  required String agentId,
  required String prompt,
  required String systemPrompt,
  void Function(String activity)? onProgress,
});

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
      timeoutOverride: specialistTimeout,
      onProgress: onProgress,
    );

/// Pede a Codex e Claude que revisem o rascunho e grava o que cada um concluiu.
///
/// Os agentes rodam em paralelo, mas as respostas sao entregues ao servidor uma
/// de cada vez: o veredito soma as leituras de todos, e duas gravacoes
/// simultaneas da mesma pergunta se atropelariam.
Future<SpecialistReviewOutcome> reviewWithSpecialists({
  required String quizId,
  QuizCenterService? service,
  AgentChecker? checkAgents,
  AgentRunner? runAgent,
  void Function(String message)? onProgress,
}) async {
  final center = service ?? quizCenter;
  final statuses = await (checkAgents ?? ConnectedAiService.checkAll)();
  final ready = statuses.where((s) => s.installed && s.authenticated).toList();
  if (ready.isEmpty) return const SpecialistReviewOutcome();

  final prompt = await center.reviewPrompt(quizId);
  final run = runAgent ?? _runConnectedAgent;

  final labels = {
    for (final status in ready) status.id: _shortLabel(status.label),
  };
  onProgress?.call(
    '${labels.values.join(' e ')} lendo as perguntas e a aula...',
  );

  final results = await Future.wait(
    ready.map((status) async {
      try {
        return await run(
          agentId: status.id,
          prompt: prompt.prompt,
          systemPrompt: prompt.systemPrompt,
          onProgress: onProgress == null
              ? null
              : (activity) => onProgress('${labels[status.id]}: $activity'),
        );
      } catch (error) {
        return ConnectedAiResult(
          agentId: status.id,
          content: '$error',
          isError: true,
        );
      }
    }),
  );

  final runs = <SpecialistRun>[];
  Map<String, dynamic>? quiz;
  for (final result in results) {
    final label = labels[result.agentId] ?? result.agentId;
    if (result.isError) {
      runs.add(SpecialistRun(
        agentId: result.agentId,
        label: label,
        ok: false,
        detail: result.content,
      ));
      continue;
    }
    onProgress?.call('Gravando a revisão de $label...');
    try {
      quiz = await center.submitReview(
        quizId,
        agent: result.agentId,
        content: result.content,
      );
      runs.add(SpecialistRun(agentId: result.agentId, label: label, ok: true));
    } on QuizCenterException catch (error) {
      runs.add(SpecialistRun(
        agentId: result.agentId,
        label: label,
        ok: false,
        detail: error.message,
      ));
    }
  }

  final rawSummary = quiz?['review_summary'];
  return SpecialistReviewOutcome(
    runs: runs,
    quiz: quiz,
    summary: rawSummary is Map
        ? {
            for (final entry in rawSummary.entries)
              entry.key.toString(): (entry.value as num).toInt(),
          }
        : const {},
  );
}

/// "Codex", "Claude": o rotulo do agente sem o "conectado" que a tela de
/// configuracao usa.
String _shortLabel(String label) {
  final short =
      label.replaceAll(RegExp(r'\s*conectado\s*', caseSensitive: false), '').trim();
  return short.isEmpty ? label : short;
}

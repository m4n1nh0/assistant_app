/// Aviso de áudio de uma gravação interrompida, com recuperar e descartar.
library;

import 'package:flutter/material.dart';

import '../services/lesson_recovery_service.dart';
import '../utils/theme.dart';

/// "5 minutos", "1 minuto", "40 segundos".
String recoveryDuration(int seconds) {
  if (seconds < 60) return '$seconds segundo${seconds == 1 ? "" : "s"}';
  final minutes = (seconds / 60).round();
  return '$minutes minuto${minutes == 1 ? "" : "s"}';
}

class LessonRecoveryBanner extends StatelessWidget {
  final RecoverableLesson lesson;

  /// Nome da aula (disciplina e título), quando o servidor o informou.
  final String label;
  final bool busy;
  final VoidCallback onRecover;
  final VoidCallback onDiscard;

  const LessonRecoveryBanner({
    super.key,
    required this.lesson,
    required this.onRecover,
    required this.onDiscard,
    this.label = '',
    this.busy = false,
  });

  @override
  Widget build(BuildContext context) {
    final blocks = lesson.chunks.length;
    final what = label.isEmpty ? 'de uma aula' : 'da aula $label';
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: AssistantTheme.c4.withValues(alpha: 0.08),
        border: Border.all(color: AssistantTheme.c4.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Row(
        children: [
          const Icon(Icons.restore, size: 13, color: AssistantTheme.c4),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              'Gravação interrompida: $blocks bloco${blocks == 1 ? "" : "s"} '
              '(cerca de ${recoveryDuration(lesson.approxSeconds)}) '
              '$what ficaram guardados e ainda não foram transcritos.',
              style: const TextStyle(fontSize: 10, color: AssistantTheme.c4),
            ),
          ),
          const SizedBox(width: 7),
          TextButton(
            onPressed: busy ? null : onRecover,
            child: Text(
              busy ? 'ENVIANDO...' : 'RECUPERAR',
              style: const TextStyle(fontSize: 10),
            ),
          ),
          TextButton(
            onPressed: busy ? null : onDiscard,
            style: TextButton.styleFrom(foregroundColor: AssistantTheme.danger),
            child: const Text('DESCARTAR', style: TextStyle(fontSize: 10)),
          ),
        ],
      ),
    );
  }
}

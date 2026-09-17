/// Avisos sobrepostos a janela, sem depender do sistema operacional.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../utils/theme.dart';
import 'education_service.dart';

/// Navegador raiz usado por avisos que precisam sobreviver ao fechamento do
/// dialogo que iniciou uma operacao longa.
final appNavigatorKey = GlobalKey<NavigatorState>();

/// Exibe avisos sobrepostos a janela, sem depender do sistema operacional.
class InAppNotificationService {
  static OverlayEntry? _entry;
  static Timer? _timer;

  static void showSummaryReady({
    required String discipline,
    required String llm,
    required int usedSegments,
    String title = '',
    String style = summaryStyleStandard,
  }) {
    final overlay = appNavigatorKey.currentState?.overlay;
    if (overlay == null) return;

    dismiss();
    late final OverlayEntry entry;
    entry = OverlayEntry(
      builder: (_) => _SummaryReadyNotice(
        discipline: discipline,
        title: title,
        llm: llm,
        usedSegments: usedSegments,
        style: style,
        onClose: () => _remove(entry),
      ),
    );
    _entry = entry;
    overlay.insert(entry);
    _timer = Timer(const Duration(seconds: 15), () => _remove(entry));
  }

  /// Aviso de fim de geracao de quiz, com atalho para a revisao.
  ///
  /// Fica mais tempo na tela que o do resumo: o professor pode estar no meio da
  /// aula, e o botao de revisar e o que evita procurar o quiz depois.
  static void showQuizFinished({
    required String title,
    required bool success,
    required String message,
    VoidCallback? onOpen,
  }) {
    final overlay = appNavigatorKey.currentState?.overlay;
    if (overlay == null) return;

    dismiss();
    late final OverlayEntry entry;
    entry = OverlayEntry(
      builder: (_) => _QuizFinishedNotice(
        title: title,
        success: success,
        message: message,
        onOpen: onOpen == null
            ? null
            : () {
                _remove(entry);
                onOpen();
              },
        onClose: () => _remove(entry),
      ),
    );
    _entry = entry;
    overlay.insert(entry);
    _timer = Timer(const Duration(seconds: 25), () => _remove(entry));
  }

  static void _remove(OverlayEntry entry) {
    if (!identical(_entry, entry)) return;
    _timer?.cancel();
    _timer = null;
    _entry = null;
    if (entry.mounted) entry.remove();
  }

  static void dismiss() {
    final entry = _entry;
    _timer?.cancel();
    _timer = null;
    _entry = null;
    if (entry?.mounted ?? false) entry!.remove();
  }
}

class _SummaryReadyNotice extends StatelessWidget {
  final String discipline;
  final String title;
  final String llm;
  final int usedSegments;
  final String style;
  final VoidCallback onClose;

  const _SummaryReadyNotice({
    required this.discipline,
    required this.title,
    required this.llm,
    required this.usedSegments,
    required this.onClose,
    this.style = summaryStyleStandard,
  });

  @override
  Widget build(BuildContext context) {
    final lesson =
        title.trim().isEmpty ? discipline : '$discipline — ${title.trim()}';
    return Positioned(
      top: 18,
      right: 18,
      child: SafeArea(
        child: Semantics(
          liveRegion: true,
          label: 'Resumo pronto. $lesson',
          child: Material(
            color: Colors.transparent,
            child: Container(
              width: 390,
              padding: const EdgeInsets.fromLTRB(16, 14, 8, 14),
              decoration: BoxDecoration(
                color: AssistantTheme.surface2,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: AssistantTheme.c3.withOpacity(0.7)),
                boxShadow: [
                  BoxShadow(
                    color: AssistantTheme.c3.withOpacity(0.18),
                    blurRadius: 22,
                    offset: const Offset(0, 6),
                  ),
                ],
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 1),
                    child: Icon(
                      Icons.check_circle_outline,
                      color: AssistantTheme.c3,
                      size: 22,
                    ),
                  ),
                  const SizedBox(width: 11),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          style == summaryStyleDetailed
                              ? 'RESUMO DETALHADO PRONTO'
                              : 'RESUMO PRONTO',
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.1,
                            color: AssistantTheme.c3,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          lesson,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AssistantTheme.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Text(
                          '$llm • $usedSegments trecho(s)',
                          style: const TextStyle(
                            fontSize: 10,
                            color: AssistantTheme.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Fechar aviso',
                    visualDensity: VisualDensity.compact,
                    onPressed: onClose,
                    icon: const Icon(
                      Icons.close,
                      size: 16,
                      color: AssistantTheme.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _QuizFinishedNotice extends StatelessWidget {
  final String title;
  final bool success;
  final String message;
  final VoidCallback? onOpen;
  final VoidCallback onClose;

  const _QuizFinishedNotice({
    required this.title,
    required this.success,
    required this.message,
    required this.onClose,
    this.onOpen,
  });

  @override
  Widget build(BuildContext context) {
    final color = success ? AssistantTheme.c3 : AssistantTheme.danger;
    return Positioned(
      top: 18,
      right: 18,
      child: SafeArea(
        child: Semantics(
          liveRegion: true,
          label: success ? 'Quiz pronto. $title' : 'Quiz não gerado. $title',
          child: Material(
            color: Colors.transparent,
            child: Container(
              width: 400,
              padding: const EdgeInsets.fromLTRB(16, 14, 8, 12),
              decoration: BoxDecoration(
                color: AssistantTheme.surface2,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: color.withOpacity(0.7)),
                boxShadow: [
                  BoxShadow(
                    color: color.withOpacity(0.18),
                    blurRadius: 22,
                    offset: const Offset(0, 6),
                  ),
                ],
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    success ? Icons.quiz_outlined : Icons.error_outline,
                    color: color,
                    size: 22,
                  ),
                  const SizedBox(width: 11),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          success ? 'QUIZ PRONTO PARA REVISÃO' : 'QUIZ NÃO GERADO',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.1,
                            color: color,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AssistantTheme.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Text(
                          message,
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 10,
                            color: AssistantTheme.textSecondary,
                          ),
                        ),
                        if (onOpen != null) ...[
                          const SizedBox(height: 8),
                          OutlinedButton.icon(
                            onPressed: onOpen,
                            icon: Icon(
                              success
                                  ? Icons.fact_check_outlined
                                  : Icons.list_alt_outlined,
                              size: 15,
                            ),
                            label: Text(success ? 'REVISAR' : 'VER DETALHES'),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: color,
                              side: BorderSide(color: color.withOpacity(0.7)),
                              visualDensity: VisualDensity.compact,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Fechar aviso',
                    visualDensity: VisualDensity.compact,
                    onPressed: onClose,
                    icon: const Icon(
                      Icons.close,
                      size: 16,
                      color: AssistantTheme.textSecondary,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

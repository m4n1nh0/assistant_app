import 'dart:async';

import 'package:flutter/material.dart';

import '../utils/theme.dart';

/// Navegador raiz usado por avisos que precisam sobreviver ao fechamento do
/// dialogo que iniciou uma operacao longa.
final appNavigatorKey = GlobalKey<NavigatorState>();

class InAppNotificationService {
  static OverlayEntry? _entry;
  static Timer? _timer;

  static void showSummaryReady({
    required String discipline,
    required String llm,
    required int usedSegments,
    String title = '',
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
        onClose: () => _remove(entry),
      ),
    );
    _entry = entry;
    overlay.insert(entry);
    _timer = Timer(const Duration(seconds: 15), () => _remove(entry));
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
  final VoidCallback onClose;

  const _SummaryReadyNotice({
    required this.discipline,
    required this.title,
    required this.llm,
    required this.usedSegments,
    required this.onClose,
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
                        const Text(
                          'RESUMO PRONTO',
                          style: TextStyle(
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

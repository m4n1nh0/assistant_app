import 'package:flutter/material.dart';

import '../utils/theme.dart';
import 'script_runner_dialog.dart';
import 'shortcuts_dialog.dart';

class LocalActionsDialog extends StatelessWidget {
  const LocalActionsDialog({super.key});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1020, maxHeight: 760),
        child: DefaultTabController(
          length: 2,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 14, 10, 8),
                child: Row(
                  children: [
                    const Icon(Icons.desktop_windows_outlined,
                        size: 18, color: AssistantTheme.c1),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        'ACOES LOCAIS',
                        style: TextStyle(
                          fontFamily: 'Rajdhani',
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 3,
                          color: AssistantTheme.textPrimary,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: 'Fechar',
                      icon: const Icon(Icons.close, size: 18),
                      color: AssistantTheme.textSecondary,
                      onPressed: () => Navigator.pop(context),
                    ),
                  ],
                ),
              ),
              const TabBar(
                indicatorColor: AssistantTheme.c1,
                labelColor: AssistantTheme.c1,
                unselectedLabelColor: AssistantTheme.textMuted,
                tabs: [
                  Tab(icon: Icon(Icons.apps, size: 17), text: 'PROGRAMAS'),
                  Tab(icon: Icon(Icons.terminal, size: 17), text: 'SCRIPTS'),
                ],
              ),
              const Expanded(
                child: TabBarView(
                  children: [
                    ShortcutsDialog(embedded: true),
                    ScriptRunnerDialog(embedded: true),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

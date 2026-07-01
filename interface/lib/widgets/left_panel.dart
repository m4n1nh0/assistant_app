import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_provider.dart';
import '../utils/theme.dart';
import 'history_dialog.dart';
import 'local_actions_dialog.dart';

class LeftPanel extends ConsumerStatefulWidget {
  const LeftPanel({super.key});

  @override
  ConsumerState<LeftPanel> createState() => _LeftPanelState();
}

class _LeftPanelState extends ConsumerState<LeftPanel> {
  @override
  Widget build(BuildContext context) {
    final config = ref.watch(configProvider);
    final isRec = ref.watch(isRecordingProvider);
    final isSpeaking = ref.watch(isSpeakingProvider);
    final backendServices =
        config.activeList.isEmpty ? ['backend'] : config.activeList;
    final activeSummary = backendServices.length == 1
        ? config.serviceName(backendServices.first)
        : '${backendServices.length} agentes ativos';

    return Container(
      width: 240,
      color: const Color(0xFF090C13),
      child: Column(
        children: [
          _StatusSummary(
            name: config.assistantName,
            backendSummary: activeSummary,
            isRec: isRec,
            isSpeaking: isSpeaking,
          ),
          _Section(
            label: 'MODO DE RESPOSTA',
            child: Row(
              children: [
                _ModeBtn(id: 'single', label: 'PADRAO'),
                const SizedBox(width: 4),
                _ModeBtn(id: 'multi', label: 'PARALELO'),
                const SizedBox(width: 4),
                _ModeBtn(id: 'chain', label: 'ETAPAS'),
              ],
            ),
          ),
          _Section(
            label: 'FERRAMENTAS',
            child: Row(
              children: [
                Expanded(
                  child: _ToolButton(
                    icon: Icons.desktop_windows_outlined,
                    label: 'PC',
                    color: AssistantTheme.c1,
                    onTap: () => showDialog(
                      context: context,
                      builder: (_) => const LocalActionsDialog(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _ToolButton(
                    icon: Icons.history,
                    label: 'Historico',
                    color: AssistantTheme.c2,
                    onTap: () => showDialog(
                      context: context,
                      builder: (_) => const HistoryDialog(),
                    ),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              child: _Section(
                label: 'COMANDOS RAPIDOS',
                child: Column(
                  children: [
                    _QuickCmd(
                        icon: Icons.terminal,
                        label: 'Terminal / Arquivos',
                        query:
                            'Como listar arquivos, navegar e gerenciar o sistema de arquivos no terminal?'),
                    _QuickCmd(
                        icon: Icons.monitor_heart_outlined,
                        label: 'Monitor do Sistema',
                        query:
                            'Como verificar uso de CPU, memoria RAM e disco no computador?'),
                    _QuickCmd(
                        icon: Icons.today_outlined,
                        label: 'Agenda de Hoje',
                        query:
                            'Quais compromissos e reunioes tenho hoje? Liste minha agenda.'),
                    _QuickCmd(
                        icon: Icons.backup_outlined,
                        label: 'Script de Backup',
                        query:
                            'Crie um script para backup automatico de arquivos importantes, multiplataforma.'),
                    _QuickCmd(
                        icon: Icons.keyboard_outlined,
                        label: 'Atalhos Essenciais',
                        query:
                            'Quais sao os atalhos de teclado mais uteis para produtividade?'),
                    _QuickCmd(
                        icon: Icons.compare_arrows,
                        label: 'Comparar respostas',
                        query:
                            'Compare as opcoes de resposta disponiveis e me de um resumo das diferencas.'),
                    _QuickCmd(
                        icon: Icons.lan_outlined,
                        label: 'Info de Rede',
                        query:
                            'Como verificar meu IP, configuracoes de rede e diagnostico de conexao?'),
                    _QuickCmd(
                        icon: Icons.security_outlined,
                        label: 'Seguranca do Sistema',
                        query:
                            'Como verificar e melhorar a seguranca do meu computador?'),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusSummary extends StatelessWidget {
  final String name;
  final String backendSummary;
  final bool isRec;
  final bool isSpeaking;

  const _StatusSummary({
    required this.name,
    required this.backendSummary,
    required this.isRec,
    required this.isSpeaking,
  });

  @override
  Widget build(BuildContext context) {
    final color = isRec
        ? AssistantTheme.c3
        : isSpeaking
            ? AssistantTheme.c2
            : AssistantTheme.c1;
    final status = isRec
        ? 'OUVINDO'
        : isSpeaking
            ? 'FALANDO'
            : 'PRONTO';
    final icon = isRec
        ? Icons.mic_none_outlined
        : isSpeaking
            ? Icons.volume_up_outlined
            : Icons.check_circle_outline;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AssistantTheme.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            name.toUpperCase(),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontFamily: 'Rajdhani',
              fontSize: 16,
              fontWeight: FontWeight.w800,
              letterSpacing: 3,
              color: AssistantTheme.c1,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: _SummaryPill(
                  icon: icon,
                  text: status,
                  color: color,
                  compact: true,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _SummaryPill(
                  icon: Icons.memory_outlined,
                  text: backendSummary,
                  color: AssistantTheme.c1,
                  compact: true,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SummaryPill extends StatelessWidget {
  final IconData icon;
  final String text;
  final Color color;
  final bool compact;

  const _SummaryPill({
    required this.icon,
    required this.text,
    required this.color,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 10,
        vertical: compact ? 6 : 9,
      ),
      decoration: BoxDecoration(
        border: Border.all(color: color.withOpacity(0.35)),
        borderRadius: BorderRadius.circular(3),
        color: color.withOpacity(0.04),
      ),
      child: Row(
        children: [
          Icon(icon, size: 15, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: compact ? 8.5 : 10,
                color: color,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ModeBtn extends ConsumerWidget {
  final String id;
  final String label;
  const _ModeBtn({required this.id, required this.label});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(configProvider).responseMode;
    final active = mode == id;
    return Expanded(
      child: GestureDetector(
        onTap: () => ref.read(configProvider.notifier).setMode(id),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          height: 28,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            border: Border.all(
                color: active ? AssistantTheme.c1 : AssistantTheme.border),
            borderRadius: BorderRadius.circular(3),
            color: active
                ? AssistantTheme.c1.withOpacity(0.08)
                : Colors.transparent,
          ),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: 'Rajdhani',
              fontSize: 10,
              fontWeight: FontWeight.w600,
              letterSpacing: 1,
              color: active ? AssistantTheme.c1 : AssistantTheme.textMuted,
            ),
          ),
        ),
      ),
    );
  }
}

class _QuickCmd extends ConsumerWidget {
  final IconData icon;
  final String label;
  final String query;
  const _QuickCmd(
      {required this.icon, required this.label, required this.query});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 5),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: () {
            ref.read(queuedChatCommandProvider.notifier).state =
                QueuedChatCommand(query);
          },
          borderRadius: BorderRadius.circular(3),
          hoverColor: AssistantTheme.c1.withOpacity(0.05),
          child: Container(
            height: 34,
            padding: const EdgeInsets.symmetric(horizontal: 9),
            decoration: BoxDecoration(
              border: Border.all(color: AssistantTheme.border),
              borderRadius: BorderRadius.circular(3),
            ),
            child: Row(
              children: [
                Icon(icon, size: 15, color: AssistantTheme.c1),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 10,
                        color: AssistantTheme.textSecondary),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ToolButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _ToolButton({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) => Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(3),
          hoverColor: color.withOpacity(0.05),
          child: Container(
            height: 36,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            decoration: BoxDecoration(
              border: Border.all(color: AssistantTheme.border),
              borderRadius: BorderRadius.circular(3),
              color: color.withOpacity(0.04),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(icon, size: 15, color: color),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 9.5,
                      color: AssistantTheme.textSecondary,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}

class _Section extends StatelessWidget {
  final String label;
  final Widget child;
  const _Section({required this.label, required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 9, 12, 9),
      decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AssistantTheme.border))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 8.5,
                  letterSpacing: 2.2,
                  color: AssistantTheme.textMuted)),
          const SizedBox(height: 7),
          child,
        ],
      ),
    );
  }
}

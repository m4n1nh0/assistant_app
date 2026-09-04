/// Painel de agenda, status dos provedores e memoria.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_provider.dart';
import '../services/external_launcher_service.dart';
import '../services/notification_service.dart';
import '../models/app_config.dart';
import '../utils/theme.dart';
import 'calendar_month_dialog.dart';

/// Painel direito: agenda, status dos provedores e memoria.
class RightPanel extends ConsumerWidget {
  const RightPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(configProvider);
    final events = ref.watch(eventsProvider);
    final isAuth = ref.watch(isAuthenticatedProvider);
    final available = config.availableAgents;
    final selected = config.effectiveAgent;
    final servicesLabel = available.isEmpty
        ? 'BACKEND'
        : '${available.length} disponíveis';
    final agentLabel = selected == AppConfig.autoAgent
        ? 'AUTO'
        : config.shortServiceName(selected);
    final aiStatuses = config.llmStatuses.values.toList();
    // O bloco "AGENTES IA" saiu do painel: repetia os marcadores da conversa e
    // comia 190px. O que so existia la - saldo e motivo de um provedor cair -
    // sobrevive nesta linha, que fica vermelha e explica no tooltip.
    final configured = aiStatuses.where((s) => s.configured).toList();
    final degraded = configured.where((s) => !s.available).toList();
    final iaValue = degraded.isEmpty
        ? servicesLabel
        : '${configured.length - degraded.length}/${configured.length} ONLINE';
    final iaTooltip = degraded.isEmpty
        ? null
        : degraded
            .map((s) => '${s.label}: ${s.balance ?? s.shortStatus}')
            .join('\n');

    return Container(
      width: 260,
      color: AssistantTheme.bg2,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _RpSection(
            label: 'STATUS DO SISTEMA',
            child: Column(
              children: [
                _InfoRow('Assistente', config.assistantName, AssistantTheme.c1),
                _InfoRow(
                    'Usuário',
                    config.userName.isEmpty ? '—' : config.userName,
                    AssistantTheme.c3),
                _InfoRow('IA', iaValue,
                    degraded.isEmpty ? AssistantTheme.c2 : AssistantTheme.c4,
                    tooltip: iaTooltip),
                _InfoRow('Agente', agentLabel, AssistantTheme.c2),
                _InfoRow(
                    'Modo',
                    AppConfig.responseModeLabel(config.responseMode),
                    AssistantTheme.c4),
                _InfoRow('Auth', isAuth ? 'VERIFICADO' : 'PENDENTE',
                    isAuth ? AssistantTheme.c3 : AssistantTheme.danger),
              ],
            ),
          ),
          _RpSection(
            label: 'NOTIFICAÇÕES',
            // Quatro linhas de rotulo + interruptor viravam um quarto do
            // painel para dizer "ligado/desligado": os mesmos quatro estados
            // cabem numa fila de icones, com o nome no tooltip.
            child: Row(
              children: [
                _NotifIcon(
                  id: 'telegram',
                  icon: Icons.send,
                  label: 'Telegram',
                  value: config.notif.tgEnabled,
                  configured: config.notif.tgToken.isNotEmpty,
                  missingHint: 'sem token',
                  onToggle: (v) => ref
                      .read(configProvider.notifier)
                      .setNotifChannel(telegram: v),
                ),
                _NotifIcon(
                  id: 'whatsapp',
                  icon: Icons.chat_bubble,
                  label: 'WhatsApp',
                  value: config.notif.waEnabled,
                  configured: config.notif.waNumber.isNotEmpty,
                  missingHint: 'sem número',
                  onToggle: (v) => ref
                      .read(configProvider.notifier)
                      .setNotifChannel(whatsapp: v),
                ),
                _NotifIcon(
                  id: 'tts',
                  icon: Icons.volume_up,
                  label: 'Resposta por voz',
                  value: config.ttsEnabled,
                  configured: true,
                  onToggle: (v) =>
                      ref.read(configProvider.notifier).setTtsEnabled(v),
                ),
                _NotifIcon(
                  id: 'mic',
                  icon: Icons.mic,
                  label: 'Mic ativo',
                  value: config.continuousVoiceMode,
                  configured: true,
                  onToggle: (v) => ref
                      .read(configProvider.notifier)
                      .setContinuousVoiceMode(v),
                ),
              ],
            ),
          ),
          Expanded(
            child: _RpSection(
              label: 'PRÓXIMOS EVENTOS',
              expand: true,
              trailing: IconButton(
                tooltip: 'Abrir calendário',
                constraints:
                    const BoxConstraints.tightFor(width: 26, height: 26),
                padding: EdgeInsets.zero,
                icon: const Icon(Icons.calendar_month, size: 15),
                color: AssistantTheme.c1,
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => const CalendarMonthDialog(),
                ),
              ),
              child: events.isEmpty
                  ? const Center(
                      child: Text(
                        'Configure as agendas\npara ver eventos',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 10,
                            color: AssistantTheme.textMuted),
                      ),
                    )
                  : ListView.separated(
                      shrinkWrap: true,
                      itemCount: events.length.clamp(0, 8),
                      separatorBuilder: (_, __) => const SizedBox(height: 6),
                      itemBuilder: (_, i) => _EventCard(event: events[i]),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  /// Detalhe que nao cabe na linha (ex: quais provedores cairam).
  final String? tooltip;
  const _InfoRow(this.label, this.value, this.color, {this.tooltip});

  @override
  Widget build(BuildContext context) {
    final row = Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label,
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  color: AssistantTheme.textMuted)),
          Text(value,
              style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  color: color,
                  letterSpacing: 1)),
        ],
      ),
    );
    if (tooltip == null) return row;
    return Tooltip(
      message: tooltip!,
      waitDuration: const Duration(milliseconds: 350),
      child: row,
    );
  }
}

/// Um estado de notificacao como icone: aceso quando ligado e configurado,
/// e clicavel para inverter sem passar pela tela de configuracao.
///
/// Canal sem credencial nao liga no clique - avisa o que falta e oferece o
/// caminho para configurar, porque ligar sem token so daria erro depois.
class _NotifIcon extends StatelessWidget {
  final String id;
  final IconData icon;
  final String label;
  final bool value;
  final bool configured;
  final ValueChanged<bool> onToggle;

  /// O que falta quando [configured] e falso (ex: 'sem token').
  final String? missingHint;

  const _NotifIcon({
    required this.id,
    required this.icon,
    required this.label,
    required this.value,
    required this.configured,
    required this.onToggle,
    this.missingHint,
  });

  @override
  Widget build(BuildContext context) {
    final on = value && configured;
    final color = on
        ? AssistantTheme.c3
        : configured
            ? AssistantTheme.textMuted
            : AssistantTheme.border;

    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Tooltip(
        message: '$label · '
            '${on ? 'ativo' : configured ? 'desligado' : 'não configurado'}'
            '\n${configured ? 'Clique para ${on ? 'desligar' : 'ligar'}' : 'Clique para configurar'}',
        waitDuration: const Duration(milliseconds: 350),
        child: InkWell(
          key: Key('notif-icon-$id'),
          borderRadius: BorderRadius.circular(3),
          onTap: () => _handleTap(context),
          child: Container(
            width: 32,
            height: 26,
            decoration: BoxDecoration(
              border: Border.all(color: color.withOpacity(on ? 0.9 : 0.4)),
              borderRadius: BorderRadius.circular(3),
              color: on ? color.withOpacity(0.12) : null,
            ),
            child: Icon(icon, size: 13, color: color),
          ),
        ),
      ),
    );
  }

  void _handleTap(BuildContext context) {
    if (configured) {
      onToggle(!value);
      return;
    }
    final navigator = Navigator.of(context);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('$label ${missingHint ?? 'não configurado'}.'),
      backgroundColor: AssistantTheme.surface2,
      action: SnackBarAction(
        label: 'CONFIGURAR',
        textColor: AssistantTheme.c1,
        onPressed: () => navigator.pushNamed('/config'),
      ),
    ));
  }
}

class _EventCard extends ConsumerWidget {
  final CalendarEvent event;
  const _EventCard({required this.event});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = {
      'google': AssistantTheme.c1,
      'teams': AssistantTheme.c2,
      'outlook': AssistantTheme.c4
    };
    final color = colors[event.source] ?? AssistantTheme.c1;
    final srcLabels = {
      'google': '📗 Google',
      'teams': '📘 Teams',
      'outlook': '📙 Outlook'
    };

    final untilStr = _untilLabel(event.timeUntil);

    return Container(
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: color, width: 3)),
        color: color.withOpacity(0.03),
      ),
      padding: const EdgeInsets.fromLTRB(10, 8, 8, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(event.title,
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 11,
                  color: AssistantTheme.textPrimary),
              maxLines: 2,
              overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          Row(
            children: [
              Text(
                '${event.startTime.hour.toString().padLeft(2, '0')}:${event.startTime.minute.toString().padLeft(2, '0')}',
                style: TextStyle(
                    fontFamily: 'JetBrains Mono', fontSize: 10, color: color),
              ),
              const SizedBox(width: 6),
              Text(untilStr,
                  style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 9,
                      color: AssistantTheme.textMuted)),
              const Spacer(),
              Text(srcLabels[event.source] ?? '',
                  style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 9,
                      color: AssistantTheme.textMuted)),
            ],
          ),
          const SizedBox(height: 5),
          Row(
            children: [
              _SmallBtn(
                label: '📨 Notificar',
                color: color,
                onTap: () => _notifyFlow(context, ref, color),
              ),
              if (event.meetingUrl?.isNotEmpty ?? false) ...[
                const SizedBox(width: 6),
                _SmallBtn(
                  label: '🔗 Entrar',
                  color: color,
                  onTap: () =>
                      ExternalLauncherService.openUrl(event.meetingUrl!),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  String _untilLabel(Duration until) {
    if (until.isNegative) return 'agora';
    final days = until.inDays;
    final hours = until.inHours.remainder(24);
    final minutes = until.inMinutes.remainder(60);
    if (days > 0) return 'em ${days}d ${hours}h ${minutes}min';
    if (until.inHours > 0) return 'em ${hours}h ${minutes}min';
    return 'em ${minutes}min';
  }

  String _fireAtLabel(DateTime time) {
    final now = DateTime.now();
    final hhmm = '${time.hour.toString().padLeft(2, '0')}:'
        '${time.minute.toString().padLeft(2, '0')}';
    final sameDay = time.year == now.year &&
        time.month == now.month &&
        time.day == now.day;
    if (sameDay) return hhmm;
    return '${time.day.toString().padLeft(2, '0')}/'
        '${time.month.toString().padLeft(2, '0')} $hhmm';
  }

  Future<void> _notifyFlow(
    BuildContext context,
    WidgetRef ref,
    Color color,
  ) async {
    final config = ref.read(configProvider);
    final pending = EventReminderScheduler.pendingFor(event.id);
    final minutes = await _pickReminderMinutes(context, color, pending);
    if (minutes == null || !context.mounted) return;
    final messenger = ScaffoldMessenger.of(context);

    if (minutes == _cancelReminder) {
      EventReminderScheduler.cancel(event.id);
      messenger.showSnackBar(const SnackBar(
        content: Text('🔕 Lembrete cancelado.'),
        backgroundColor: AssistantTheme.surface2,
      ));
      return;
    }

    if (minutes == 0) {
      final svc = NotificationService(config.notif, config.assistantName);
      final msg = svc.buildEventMessage(event, is15min: false);
      final result = await svc.send(msg, event: event);
      if (context.mounted) {
        messenger.showSnackBar(SnackBar(
          content: Text(result.summary),
          backgroundColor: AssistantTheme.surface2,
        ));
      }
      return;
    }

    final fireAt = EventReminderScheduler.schedule(
      event: event,
      minutesBefore: minutes,
      notif: config.notif,
      assistantName: config.assistantName,
    );
    messenger.showSnackBar(SnackBar(
      content: Text(fireAt.isBefore(DateTime.now())
          ? '⏰ Evento a menos de ${minutes}min; notificação enviada agora.'
          : '⏰ Notificação agendada: ${minutes}min antes '
              '(${_fireAtLabel(fireAt)}).'),
      backgroundColor: AssistantTheme.surface2,
    ));
  }

  static const _cancelReminder = -1;

  /// Retorna os minutos de antecedência escolhidos, 0 para enviar agora,
  /// [_cancelReminder] para cancelar o lembrete atual ou null se fechado.
  Future<int?> _pickReminderMinutes(
    BuildContext context,
    Color color,
    PendingEventReminder? pending,
  ) async {
    final customCtrl = TextEditingController();
    const optionStyle = TextStyle(
      fontFamily: 'JetBrains Mono',
      fontSize: 11,
      color: AssistantTheme.textSecondary,
    );
    final result = await showDialog<int>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: Text(
          event.title,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 13,
            color: AssistantTheme.textPrimary,
          ),
        ),
        content: SizedBox(
          width: 360,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (pending != null) ...[
                Text(
                  '⏰ Lembrete atual: ${pending.minutesBefore}min antes '
                  '(${_fireAtLabel(pending.fireAt)}).',
                  style: optionStyle,
                ),
                const SizedBox(height: 10),
              ],
              const Text(
                'Enviar agora ou agendar para antes do evento:',
                style: optionStyle,
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final option in const [0, 5, 15, 30, 60, 120])
                    _SmallBtn(
                      label: option == 0
                          ? 'Agora'
                          : option >= 60
                              ? '${option ~/ 60}h antes'
                              : '${option}min antes',
                      color: color,
                      onTap: () => Navigator.pop(dialogContext, option),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: customCtrl,
                      keyboardType: TextInputType.number,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 12,
                        color: AssistantTheme.textPrimary,
                      ),
                      decoration: const InputDecoration(
                        labelText: 'Minutos antes (ex: 45)',
                        labelStyle: TextStyle(
                          fontSize: 11,
                          color: AssistantTheme.textSecondary,
                        ),
                        isDense: true,
                      ),
                      onSubmitted: (_) =>
                          _confirmCustom(dialogContext, customCtrl.text),
                    ),
                  ),
                  const SizedBox(width: 8),
                  TextButton(
                    onPressed: () =>
                        _confirmCustom(dialogContext, customCtrl.text),
                    child: const Text('Agendar'),
                  ),
                ],
              ),
            ],
          ),
        ),
        actions: [
          if (pending != null)
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, _cancelReminder),
              child: const Text('Cancelar lembrete'),
            ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Fechar'),
          ),
        ],
      ),
    );
    customCtrl.dispose();
    return result;
  }

  void _confirmCustom(BuildContext dialogContext, String text) {
    final minutes = int.tryParse(text.trim());
    // Limite de 7 dias evita agendamentos por engano (ex: digitar o horário).
    if (minutes == null || minutes <= 0 || minutes > 10080) return;
    Navigator.pop(dialogContext, minutes);
  }
}

class _SmallBtn extends StatelessWidget {
  final String label;
  final Color color;
  final VoidCallback onTap;
  const _SmallBtn(
      {required this.label, required this.color, required this.onTap});

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            border: Border.all(color: color.withOpacity(0.3)),
            borderRadius: BorderRadius.circular(2),
          ),
          child: Text(label,
              style: TextStyle(
                  fontFamily: 'JetBrains Mono', fontSize: 9, color: color)),
        ),
      );
}

class _RpSection extends StatelessWidget {
  final String label;
  final Widget child;
  final bool expand;
  final Widget? trailing;
  const _RpSection({
    required this.label,
    required this.child,
    this.expand = false,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    final inner = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(label,
                  style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 9,
                      letterSpacing: 3,
                      color: AssistantTheme.textMuted)),
            ),
            if (trailing != null) trailing!,
          ],
        ),
        const SizedBox(height: 10),
        if (expand) Expanded(child: child) else child,
      ],
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AssistantTheme.border))),
      child: inner,
    );
  }
}

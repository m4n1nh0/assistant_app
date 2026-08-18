import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_provider.dart';
import '../services/external_launcher_service.dart';
import '../services/notification_service.dart';
import '../models/app_config.dart';
import '../utils/theme.dart';

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
        : config.serviceName(selected);
    final aiStatuses = config.llmStatuses.values.toList();

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
                _InfoRow('IA', servicesLabel, AssistantTheme.c2),
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
            label: 'AGENTES IA',
            child: aiStatuses.isEmpty
                ? _InfoRow('Online', servicesLabel, AssistantTheme.c2)
                : ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 190),
                    child: SingleChildScrollView(
                      child: Column(
                        children: aiStatuses
                            .map((status) => _AiStatusRow(status: status))
                            .toList(),
                      ),
                    ),
                  ),
          ),
          _RpSection(
            label: 'NOTIFICAÇÕES',
            child: Column(
              children: [
                _ToggleRow('Telegram', config.notif.tgEnabled,
                    config.notif.tgToken.isNotEmpty),
                _ToggleRow('WhatsApp', config.notif.waEnabled,
                    config.notif.waNumber.isNotEmpty),
                _ToggleRow('Resposta por voz', config.ttsEnabled, true),
                _ToggleRow('Mic ativo', config.continuousVoiceMode, true),
              ],
            ),
          ),
          Expanded(
            child: _RpSection(
              label: 'PRÓXIMOS EVENTOS',
              expand: true,
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

class _AiStatusRow extends StatelessWidget {
  final LlmStatus status;
  const _AiStatusRow({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    final detail = status.balance ??
        (status.error?.isNotEmpty == true ? status.error! : status.shortStatus);

    return Tooltip(
      message: detail,
      waitDuration: const Duration(milliseconds: 350),
      child: Container(
        margin: const EdgeInsets.only(bottom: 5),
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
        decoration: BoxDecoration(
          border: Border.all(color: color.withOpacity(0.24)),
          borderRadius: BorderRadius.circular(3),
          color: color.withOpacity(status.available ? 0.05 : 0.025),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                status.label,
                style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9.5,
                  color: status.available
                      ? AssistantTheme.textPrimary
                      : AssistantTheme.textSecondary,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const SizedBox(width: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 82),
              child: Text(
                status.balance ?? status.shortStatus,
                style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 8.5,
                  letterSpacing: 0.6,
                  color: color,
                ),
                textAlign: TextAlign.right,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Color _statusColor(LlmStatus status) {
    if (!status.configured) return AssistantTheme.textMuted;
    if (status.status == 'checking') return AssistantTheme.c2;
    if (!status.online) return AssistantTheme.danger;
    if (status.balanceOk == false) return AssistantTheme.c4;
    return AssistantTheme.c3;
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _InfoRow(this.label, this.value, this.color);

  @override
  Widget build(BuildContext context) => Padding(
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
}

class _ToggleRow extends StatelessWidget {
  final String label;
  final bool value;
  final bool configured;
  const _ToggleRow(this.label, this.value, this.configured);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label,
                style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 10,
                    color: AssistantTheme.textSecondary)),
            Container(
              width: 28,
              height: 15,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                color: (value && configured)
                    ? AssistantTheme.c3
                    : AssistantTheme.border,
              ),
              child: Align(
                alignment: (value && configured)
                    ? Alignment.centerRight
                    : Alignment.centerLeft,
                child: Container(
                  width: 11,
                  height: 11,
                  margin: const EdgeInsets.all(2),
                  decoration: const BoxDecoration(
                      shape: BoxShape.circle, color: AssistantTheme.bg),
                ),
              ),
            ),
          ],
        ),
      );
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
  const _RpSection(
      {required this.label, required this.child, this.expand = false});

  @override
  Widget build(BuildContext context) {
    final inner = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                letterSpacing: 3,
                color: AssistantTheme.textMuted)),
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

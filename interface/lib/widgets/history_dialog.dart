import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/app_config.dart';
import '../models/hive_adapters.dart';
import '../services/api_service.dart';
import '../utils/theme.dart';

class HistoryDialog extends StatefulWidget {
  const HistoryDialog({super.key});

  @override
  State<HistoryDialog> createState() => _HistoryDialogState();
}

class _HistoryDialogState extends State<HistoryDialog> {
  bool _loading = true;
  String? _status;
  List<Map<String, dynamic>> _localMessages = [];
  List<Map<String, dynamic>> _backendMessages = [];
  List<ShortcutLaunchEntry> _launches = [];
  List<ActionAuditEntry> _audits = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _status = null;
    });

    final notes = <String>[];
    final localMessages = HiveConversations.readAll()
      ..sort((a, b) => _messageDate(b).compareTo(_messageDate(a)));

    List<Map<String, dynamic>> backendMessages = const [];
    List<ShortcutLaunchEntry> launches = const [];
    List<ActionAuditEntry> audits = const [];

    try {
      backendMessages = await api.getHistory('default');
      backendMessages = [...backendMessages]
        ..sort((a, b) => _messageDate(b).compareTo(_messageDate(a)));
    } catch (e) {
      notes.add('conversas do backend indisponiveis');
    }

    try {
      launches = await api.listShortcutLaunches('default', limit: 100);
    } catch (e) {
      notes.add('execucoes indisponiveis');
    }

    try {
      audits = await api.listActionAudits('default');
    } catch (e) {
      notes.add('auditoria indisponivel');
    }

    if (!mounted) return;
    setState(() {
      _localMessages = localMessages;
      _backendMessages = backendMessages;
      _launches = launches;
      _audits = audits;
      _status = notes.isEmpty ? null : notes.join(' | ');
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 920, maxHeight: 720),
        child: DefaultTabController(
          length: 2,
          child: Column(
            children: [
              _Header(onRefresh: _loading ? null : _load),
              const TabBar(
                indicatorColor: AssistantTheme.c1,
                labelColor: AssistantTheme.c1,
                unselectedLabelColor: AssistantTheme.textMuted,
                tabs: [
                  Tab(text: 'CONVERSAS'),
                  Tab(text: 'ACOES'),
                ],
              ),
              if (_status != null)
                _StatusStrip(text: _status!, color: AssistantTheme.c4),
              Expanded(
                child: _loading
                    ? const Center(child: CircularProgressIndicator())
                    : TabBarView(
                        children: [
                          _buildConversations(),
                          _buildActions(),
                        ],
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildConversations() {
    final messages =
        _localMessages.isNotEmpty ? _localMessages : _backendMessages;
    final source = _localMessages.isNotEmpty ? 'LOCAL' : 'BACKEND';

    if (messages.isEmpty) {
      return const _EmptyState(text: 'Sem conversas registradas');
    }

    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: messages.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, index) {
        final msg = messages[index];
        return _ConversationTile(message: msg, source: source);
      },
    );
  }

  Widget _buildActions() {
    if (_launches.isEmpty && _audits.isEmpty) {
      return const _EmptyState(text: 'Sem acoes registradas');
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _HistorySection(
          title: 'EXECUCOES DE PROGRAMAS',
          emptyText: 'Sem execucoes registradas',
          children:
              _launches.map((item) => _LaunchHistoryTile(item: item)).toList(),
        ),
        const SizedBox(height: 14),
        _HistorySection(
          title: 'AUDITORIA DA IA',
          emptyText: 'Sem auditoria registrada',
          children: _audits.map((item) => _AuditTile(item: item)).toList(),
        ),
      ],
    );
  }

  static DateTime _messageDate(Map<String, dynamic> message) {
    final value = message['timestamp'] ?? message['created_at'];
    return DateTime.tryParse(value?.toString() ?? '')?.toLocal() ??
        DateTime.fromMillisecondsSinceEpoch(0);
  }
}

class _Header extends StatelessWidget {
  final VoidCallback? onRefresh;

  const _Header({required this.onRefresh});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 10, 8),
      child: Row(
        children: [
          const Icon(Icons.history, size: 18, color: AssistantTheme.c1),
          const SizedBox(width: 10),
          const Expanded(
            child: Text(
              'HISTORICO',
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
            tooltip: 'Atualizar',
            icon: const Icon(Icons.refresh, size: 18),
            color: AssistantTheme.textSecondary,
            onPressed: onRefresh,
          ),
          IconButton(
            tooltip: 'Fechar',
            icon: const Icon(Icons.close, size: 18),
            color: AssistantTheme.textSecondary,
            onPressed: () => Navigator.pop(context),
          ),
        ],
      ),
    );
  }
}

class _StatusStrip extends StatelessWidget {
  final String text;
  final Color color;

  const _StatusStrip({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
      decoration: BoxDecoration(
        color: color.withOpacity(0.06),
        border: Border(bottom: BorderSide(color: color.withOpacity(0.18))),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontFamily: 'JetBrains Mono',
          fontSize: 10,
          color: color,
        ),
      ),
    );
  }
}

class _ConversationTile extends StatelessWidget {
  final Map<String, dynamic> message;
  final String source;

  const _ConversationTile({
    required this.message,
    required this.source,
  });

  @override
  Widget build(BuildContext context) {
    final role = message['role']?.toString() ?? 'system';
    final content = message['content']?.toString().trim() ?? '';
    final llm = message['llm']?.toString();
    final timestamp =
        DateTime.tryParse(message['timestamp']?.toString() ?? '')?.toLocal();
    final isUser = role == 'user';
    final color = isUser ? AssistantTheme.c3 : AssistantTheme.c1;

    return _HistoryTileFrame(
      leading: Icon(
        isUser ? Icons.person_outline : Icons.smart_toy_outlined,
        size: 16,
        color: color,
      ),
      color: color,
      title: [
        isUser ? 'Usuario' : 'Assistente',
        if (llm?.trim().isNotEmpty ?? false) llm!,
        source,
      ].join(' | '),
      time: timestamp == null ? '' : _formatDate(timestamp),
      body: content.isEmpty ? 'Sem texto' : content,
      onCopy: content.isEmpty
          ? null
          : () => Clipboard.setData(ClipboardData(text: content)),
    );
  }
}

class _LaunchHistoryTile extends StatelessWidget {
  final ShortcutLaunchEntry item;

  const _LaunchHistoryTile({required this.item});

  @override
  Widget build(BuildContext context) {
    final ok = item.status == 'executed';
    final color = ok ? AssistantTheme.c3 : AssistantTheme.danger;
    final body = item.error?.trim().isNotEmpty == true
        ? item.error!.trim()
        : item.target;

    return _HistoryTileFrame(
      leading: Icon(
        ok ? Icons.play_circle_outline : Icons.error_outline,
        size: 16,
        color: color,
      ),
      color: color,
      title: item.shortcutName.isEmpty ? item.targetType : item.shortcutName,
      time: _formatDate(item.launchedAt),
      body: body,
    );
  }
}

class _AuditTile extends StatelessWidget {
  final ActionAuditEntry item;

  const _AuditTile({required this.item});

  @override
  Widget build(BuildContext context) {
    final ok = item.status == 'executed';
    final color = ok
        ? AssistantTheme.c3
        : item.status == 'failed'
            ? AssistantTheme.danger
            : AssistantTheme.c4;

    return _HistoryTileFrame(
      leading: Icon(Icons.rule_folder_outlined, size: 16, color: color),
      color: color,
      title: '${item.actionType} | ${item.status}',
      time: _formatDate(item.createdAt),
      body: _auditDetail(item),
      onCopy: () => Clipboard.setData(
        ClipboardData(
          text: const JsonEncoder.withIndent('  ').convert({
            'action_type': item.actionType,
            'status': item.status,
            'request': item.request,
            'result': item.result,
          }),
        ),
      ),
    );
  }

  static String _auditDetail(ActionAuditEntry item) {
    final candidates = [
      item.result['message'],
      item.result['summary'],
      item.request['title'],
      item.request['description'],
      item.request['trigger'],
    ];
    for (final candidate in candidates) {
      final text = candidate?.toString().trim() ?? '';
      if (text.isNotEmpty) return text;
    }
    if (item.request.isNotEmpty) return jsonEncode(item.request);
    if (item.result.isNotEmpty) return jsonEncode(item.result);
    return 'Sem detalhes';
  }
}

class _HistorySection extends StatelessWidget {
  final String title;
  final String emptyText;
  final List<Widget> children;

  const _HistorySection({
    required this.title,
    required this.emptyText,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 9,
            letterSpacing: 3,
            color: AssistantTheme.textMuted,
          ),
        ),
        const SizedBox(height: 10),
        if (children.isEmpty)
          _InlineEmpty(text: emptyText)
        else
          ...children.expand((child) => [child, const SizedBox(height: 8)]),
      ],
    );
  }
}

class _HistoryTileFrame extends StatelessWidget {
  final Widget leading;
  final Color color;
  final String title;
  final String time;
  final String body;
  final VoidCallback? onCopy;

  const _HistoryTileFrame({
    required this.leading,
    required this.color,
    required this.title,
    required this.time,
    required this.body,
    this.onCopy,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        border: Border.all(color: color.withOpacity(0.24)),
        borderRadius: BorderRadius.circular(4),
        color: color.withOpacity(0.035),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: leading,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 10.5,
                          color: color,
                        ),
                      ),
                    ),
                    if (time.isNotEmpty)
                      Text(
                        time,
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 9,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 5),
                Text(
                  body,
                  maxLines: 4,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 10,
                    height: 1.35,
                    color: AssistantTheme.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          if (onCopy != null) ...[
            const SizedBox(width: 8),
            IconButton(
              tooltip: 'Copiar',
              constraints: const BoxConstraints.tightFor(width: 30, height: 30),
              padding: EdgeInsets.zero,
              icon: const Icon(Icons.copy, size: 14),
              color: AssistantTheme.textSecondary,
              onPressed: onCopy,
            ),
          ],
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final String text;

  const _EmptyState({required this.text});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'JetBrains Mono',
          fontSize: 11,
          color: AssistantTheme.textMuted,
        ),
      ),
    );
  }
}

class _InlineEmpty extends StatelessWidget {
  final String text;

  const _InlineEmpty({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      decoration: BoxDecoration(
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'JetBrains Mono',
          fontSize: 10,
          color: AssistantTheme.textMuted,
        ),
      ),
    );
  }
}

String _formatDate(DateTime value) => '${value.day.toString().padLeft(2, '0')}/'
    '${value.month.toString().padLeft(2, '0')} '
    '${value.hour.toString().padLeft(2, '0')}:'
    '${value.minute.toString().padLeft(2, '0')}';

import 'dart:async';
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
  final _searchCtrl = TextEditingController();
  String _search = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
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
              _SearchField(
                controller: _searchCtrl,
                onChanged: (value) => setState(() => _search = value),
              ),
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

  bool _matchesSearch(String text) {
    final term = _search.trim().toLowerCase();
    if (term.isEmpty) return true;
    return text.toLowerCase().contains(term);
  }

  Widget _buildConversations() {
    final all = _localMessages.isNotEmpty ? _localMessages : _backendMessages;
    final source = _localMessages.isNotEmpty ? 'LOCAL' : 'BACKEND';

    if (all.isEmpty) {
      return const _EmptyState(text: 'Sem conversas registradas');
    }

    final messages = all
        .where((msg) => _matchesSearch(
              '${msg['content'] ?? ''} ${msg['role'] ?? ''} ${msg['llm'] ?? ''}',
            ))
        .toList();
    if (messages.isEmpty) {
      return _EmptyState(text: 'Nenhuma conversa com "${_search.trim()}"');
    }

    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: messages.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, index) {
        final msg = messages[index];
        return _ConversationTile(
          message: msg,
          source: source,
          highlight: _search,
        );
      },
    );
  }

  Widget _buildActions() {
    if (_launches.isEmpty && _audits.isEmpty) {
      return const _EmptyState(text: 'Sem acoes registradas');
    }

    final launches = _launches
        .where((item) => _matchesSearch(
              '${item.shortcutName} ${item.target} ${item.targetType} '
              '${item.status} ${item.error ?? ''}',
            ))
        .toList();
    final audits = _audits
        .where((item) => _matchesSearch(
              '${item.actionType} ${item.status} ${jsonEncode(item.request)} '
              '${jsonEncode(item.result)}',
            ))
        .toList();

    if (launches.isEmpty && audits.isEmpty) {
      return _EmptyState(text: 'Nenhuma acao com "${_search.trim()}"');
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _HistorySection(
          title: 'EXECUCOES DE PROGRAMAS',
          emptyText: 'Sem execucoes registradas',
          children:
              launches.map((item) => _LaunchHistoryTile(item: item)).toList(),
        ),
        const SizedBox(height: 14),
        _HistorySection(
          title: 'AUDITORIA DA IA',
          emptyText: 'Sem auditoria registrada',
          children: audits.map((item) => _AuditTile(item: item)).toList(),
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

class _SearchField extends StatelessWidget {
  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  const _SearchField({required this.controller, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
      child: TextField(
        controller: controller,
        onChanged: onChanged,
        style: const TextStyle(
          fontFamily: 'JetBrains Mono',
          fontSize: 11,
          color: AssistantTheme.textPrimary,
        ),
        decoration: InputDecoration(
          isDense: true,
          hintText: 'Buscar no historico...',
          hintStyle: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 11,
            color: AssistantTheme.textMuted,
          ),
          prefixIcon: const Icon(Icons.search,
              size: 15, color: AssistantTheme.textMuted),
          prefixIconConstraints:
              const BoxConstraints.tightFor(width: 32, height: 30),
          suffixIcon: controller.text.isEmpty
              ? null
              : IconButton(
                  tooltip: 'Limpar busca',
                  constraints:
                      const BoxConstraints.tightFor(width: 30, height: 30),
                  padding: EdgeInsets.zero,
                  icon: const Icon(Icons.close, size: 14),
                  color: AssistantTheme.textMuted,
                  onPressed: () {
                    controller.clear();
                    onChanged('');
                  },
                ),
        ),
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
  final String highlight;

  const _ConversationTile({
    required this.message,
    required this.source,
    this.highlight = '',
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
      highlight: highlight,
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
      details: [
        _DetailSection(label: 'Destino', text: item.target),
        _DetailSection(label: 'Tipo', text: item.targetType),
        _DetailSection(label: 'Status', text: item.status),
        if (item.error?.trim().isNotEmpty ?? false)
          _DetailSection(label: 'Erro', text: item.error!.trim()),
      ],
      onCopy: () => Clipboard.setData(ClipboardData(text: item.target)),
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

    const encoder = JsonEncoder.withIndent('  ');
    return _HistoryTileFrame(
      leading: Icon(Icons.rule_folder_outlined, size: 16, color: color),
      color: color,
      title: '${item.actionType} | ${item.status}',
      time: _formatDate(item.createdAt),
      body: _auditDetail(item),
      details: [
        _DetailSection(label: 'Resumo', text: _auditDetail(item)),
        if (item.request.isNotEmpty)
          _DetailSection(
            label: 'Requisição',
            text: encoder.convert(item.request),
          ),
        if (item.result.isNotEmpty)
          _DetailSection(
            label: 'Resultado',
            text: encoder.convert(item.result),
          ),
      ],
      onCopy: () => Clipboard.setData(
        ClipboardData(
          text: encoder.convert({
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

/// Uma seção de texto na visão de detalhe do item do histórico.
class _DetailSection {
  final String label;
  final String text;

  const _DetailSection({required this.label, required this.text});
}

class _HistoryTileFrame extends StatefulWidget {
  final Widget leading;
  final Color color;
  final String title;
  final String time;
  final String body;
  final VoidCallback? onCopy;

  /// Conteúdo completo mostrado ao clicar no cartão. Vazio usa apenas [body].
  final List<_DetailSection> details;

  /// Trecho destacado no corpo quando há busca ativa.
  final String highlight;

  const _HistoryTileFrame({
    required this.leading,
    required this.color,
    required this.title,
    required this.time,
    required this.body,
    this.onCopy,
    this.details = const [],
    this.highlight = '',
  });

  @override
  State<_HistoryTileFrame> createState() => _HistoryTileFrameState();
}

class _HistoryTileFrameState extends State<_HistoryTileFrame> {
  bool _hovered = false;

  List<_DetailSection> get _sections => widget.details.isNotEmpty
      ? widget.details
      : [_DetailSection(label: '', text: widget.body)];

  int get _bodyLines => '\n'.allMatches(widget.body).length + 1;

  /// Só vale abrir o detalhe quando há mais conteúdo do que o preview mostra.
  bool get _hasMore =>
      widget.details.isNotEmpty || _bodyLines > 4 || widget.body.length > 260;

  void _openDetail() {
    showDialog<void>(
      context: context,
      builder: (_) => _HistoryDetailDialog(
        title: widget.title,
        time: widget.time,
        color: widget.color,
        icon: widget.leading,
        sections: _sections,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        onTap: _openDetail,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            border: Border.all(
              color: widget.color.withOpacity(_hovered ? 0.5 : 0.24),
            ),
            borderRadius: BorderRadius.circular(4),
            color: widget.color.withOpacity(_hovered ? 0.07 : 0.035),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: widget.leading,
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
                            widget.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontFamily: 'JetBrains Mono',
                              fontSize: 10.5,
                              color: widget.color,
                            ),
                          ),
                        ),
                        if (widget.time.isNotEmpty)
                          Text(
                            widget.time,
                            style: const TextStyle(
                              fontFamily: 'JetBrains Mono',
                              fontSize: 9,
                              color: AssistantTheme.textMuted,
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 5),
                    _HighlightedText(
                      text: widget.body,
                      highlight: widget.highlight,
                      maxLines: 4,
                    ),
                    if (_hasMore) ...[
                      const SizedBox(height: 6),
                      Row(
                        children: [
                          Icon(
                            Icons.unfold_more,
                            size: 12,
                            color: widget.color.withOpacity(0.8),
                          ),
                          const SizedBox(width: 4),
                          Text(
                            'Clique para ver o conteúdo completo',
                            style: TextStyle(
                              fontFamily: 'JetBrains Mono',
                              fontSize: 9,
                              color: widget.color.withOpacity(0.8),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
              if (widget.onCopy != null) ...[
                const SizedBox(width: 8),
                IconButton(
                  tooltip: 'Copiar',
                  constraints:
                      const BoxConstraints.tightFor(width: 30, height: 30),
                  padding: EdgeInsets.zero,
                  icon: const Icon(Icons.copy, size: 14),
                  color: AssistantTheme.textSecondary,
                  onPressed: widget.onCopy,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// Texto do preview com o termo buscado destacado.
class _HighlightedText extends StatelessWidget {
  final String text;
  final String highlight;
  final int maxLines;

  const _HighlightedText({
    required this.text,
    required this.highlight,
    required this.maxLines,
  });

  @override
  Widget build(BuildContext context) {
    const style = TextStyle(
      fontFamily: 'JetBrains Mono',
      fontSize: 10,
      height: 1.35,
      color: AssistantTheme.textSecondary,
    );
    final term = highlight.trim();
    if (term.isEmpty) {
      return Text(
        text,
        maxLines: maxLines,
        overflow: TextOverflow.ellipsis,
        style: style,
      );
    }

    final spans = <TextSpan>[];
    final lowerText = text.toLowerCase();
    final lowerTerm = term.toLowerCase();
    var start = 0;
    while (true) {
      final index = lowerText.indexOf(lowerTerm, start);
      if (index < 0) {
        spans.add(TextSpan(text: text.substring(start)));
        break;
      }
      if (index > start) {
        spans.add(TextSpan(text: text.substring(start, index)));
      }
      spans.add(TextSpan(
        text: text.substring(index, index + term.length),
        style: const TextStyle(
          color: AssistantTheme.c2,
          fontWeight: FontWeight.w700,
        ),
      ));
      start = index + term.length;
    }

    return RichText(
      maxLines: maxLines,
      overflow: TextOverflow.ellipsis,
      text: TextSpan(style: style, children: spans),
    );
  }
}

/// Conteúdo completo de um item do histórico, com texto selecionável.
class _HistoryDetailDialog extends StatefulWidget {
  final String title;
  final String time;
  final Color color;
  final Widget icon;
  final List<_DetailSection> sections;

  const _HistoryDetailDialog({
    required this.title,
    required this.time,
    required this.color,
    required this.icon,
    required this.sections,
  });

  @override
  State<_HistoryDetailDialog> createState() => _HistoryDetailDialogState();
}

class _HistoryDetailDialogState extends State<_HistoryDetailDialog> {
  bool _copied = false;
  Timer? _copyTimer;

  @override
  void dispose() {
    _copyTimer?.cancel();
    super.dispose();
  }

  String get _fullText => widget.sections
      .map((section) => section.label.isEmpty
          ? section.text
          : '${section.label}\n${section.text}')
      .join('\n\n');

  void _copyAll() {
    Clipboard.setData(ClipboardData(text: _fullText));
    setState(() => _copied = true);
    _copyTimer?.cancel();
    _copyTimer = Timer(const Duration(seconds: 2), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final color = widget.color;
    final time = widget.time;
    final sections = widget.sections;
    final size = MediaQuery.of(context).size;
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: const EdgeInsets.all(28),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: BorderSide(color: color.withOpacity(0.4)),
      ),
      child: SizedBox(
        width: (size.width - 120).clamp(480.0, 900.0),
        height: (size.height - 140).clamp(320.0, 720.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 10),
              child: Row(
                children: [
                  widget.icon,
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.title,
                          style: TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 12,
                            color: color,
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
                  ),
                  IconButton(
                    tooltip: _copied ? 'Copiado!' : 'Copiar tudo',
                    icon: Icon(_copied ? Icons.check : Icons.copy, size: 16),
                    color:
                        _copied ? AssistantTheme.c3 : AssistantTheme.textSecondary,
                    onPressed: _copyAll,
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
            const Divider(height: 1, color: AssistantTheme.border),
            Expanded(
              child: Container(
                width: double.infinity,
                color: AssistantTheme.bg,
                child: Scrollbar(
                  child: SingleChildScrollView(
                    primary: true,
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final section in sections) ...[
                          if (section.label.isNotEmpty) ...[
                            Text(
                              section.label.toUpperCase(),
                              style: const TextStyle(
                                fontFamily: 'JetBrains Mono',
                                fontSize: 9,
                                letterSpacing: 2,
                                color: AssistantTheme.textMuted,
                              ),
                            ),
                            const SizedBox(height: 6),
                          ],
                          SelectableText(
                            section.text.trim().isEmpty
                                ? 'Sem texto'
                                : section.text,
                            style: const TextStyle(
                              fontFamily: 'JetBrains Mono',
                              fontSize: 11.5,
                              height: 1.55,
                              color: AssistantTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 16),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
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

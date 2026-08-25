/// Cadastro e gerenciamento dos atalhos.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import '../models/app_config.dart';
import '../services/api_service.dart';
import '../services/installed_apps_service.dart';
import '../utils/theme.dart';

/// Cadastro e gerenciamento dos atalhos de app, URL e comando.
class ShortcutsDialog extends StatefulWidget {
  final bool embedded;

  const ShortcutsDialog({super.key, this.embedded = false});

  @override
  State<ShortcutsDialog> createState() => _ShortcutsDialogState();
}

class _ShortcutsDialogState extends State<ShortcutsDialog> {
  static const _tutorId = 'default';

  final _nameCtrl = TextEditingController();
  final _targetCtrl = TextEditingController();
  final _aliasesCtrl = TextEditingController();
  final _descriptionCtrl = TextEditingController();

  var _type = 'app';
  var _browser = '';
  var _loading = true;
  var _saving = false;
  var _scanning = false;
  var _suggesting = false;
  String? _approvingTarget;
  ShortcutEntry? _editingShortcut;
  var _status = '';
  List<ShortcutEntry> _shortcuts = [];
  List<ShortcutLaunchEntry> _launches = [];
  List<InstalledAppCandidate> _candidates = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _targetCtrl.dispose();
    _aliasesCtrl.dispose();
    _descriptionCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final shortcuts = await api.listShortcuts(_tutorId);
      List<ShortcutLaunchEntry> launches = const [];
      try {
        launches = await api.listShortcutLaunches(_tutorId, limit: 20);
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _shortcuts = shortcuts;
        _launches = launches;
        _status = shortcuts.isEmpty
            ? 'Cadastre programas e URLs para abrir pelo chat.'
            : '${shortcuts.length} atalho(s) cadastrado(s).';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao carregar atalhos: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    final name = _nameCtrl.text.trim();
    final target = _normalizedTarget(_targetCtrl.text.trim());
    if (name.isEmpty || target.isEmpty) {
      setState(() => _status = 'Preencha nome e destino.');
      return;
    }
    if (_type == 'url' && Uri.tryParse(target)?.hasScheme != true) {
      setState(() => _status = 'URL invalida. Use algo como https://site.com.');
      return;
    }
    if (_type == 'command' && !_isValidLaunchCommand(target)) {
      setState(() => _status = 'Comando invalido. Use uma sugestao do agente.');
      return;
    }

    setState(() => _saving = true);
    try {
      final aliases = _aliasesCtrl.text
          .split(',')
          .map((item) => item.trim())
          .where((item) => item.isNotEmpty)
          .toList();
      final editing = _editingShortcut;
      if (editing == null) {
        await api.createShortcut(
          tutorId: _tutorId,
          name: name,
          type: _type,
          target: target,
          aliases: aliases,
          description: _descriptionForSave(),
        );
      } else {
        await api.updateShortcut(
          shortcutId: editing.id,
          name: name,
          type: _type,
          target: target,
          aliases: aliases,
          description: _descriptionForSave(),
        );
      }
      _clearForm();
      await _load();
      if (!mounted) return;
      setState(() => _status = editing == null
          ? 'Atalho cadastrado. Teste dizendo: abra $name.'
          : 'Atalho atualizado: $name.');
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao salvar atalho: $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete(ShortcutEntry shortcut) async {
    try {
      await api.deleteShortcut(shortcut.id);
      if (_editingShortcut?.id == shortcut.id) _clearForm();
      await _load();
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao remover: $e');
    }
  }

  Future<void> _scan() async {
    setState(() {
      _scanning = true;
      _status = 'Buscando atalhos instalados...';
    });
    try {
      final candidates = await InstalledAppsService.discover();
      if (!mounted) return;
      setState(() {
        _candidates = candidates;
        _status = candidates.isEmpty
            ? 'Nenhum atalho encontrado automaticamente.'
            : '${candidates.length} app(s) encontrados. Use para revisar ou APROVAR para salvar.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao buscar apps: $e');
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  Future<void> _suggestDeveloperProfile() async {
    setState(() {
      _suggesting = true;
      _status = 'Agente dev montando sugestoes para seu perfil...';
    });
    try {
      final candidates = await InstalledAppsService.recommendForProfile(
        profile: 'developer',
        existingNames: _shortcuts.map((item) => item.name),
        existingTargets: _shortcuts.map((item) => item.target),
      );
      if (!mounted) return;
      setState(() {
        _candidates = candidates;
        _status = candidates.isEmpty
            ? 'Sem sugestoes novas para o perfil desenvolvedor.'
            : '${candidates.length} sugestoes dev. Revise ou aprove.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao sugerir atalhos: $e');
    } finally {
      if (mounted) setState(() => _suggesting = false);
    }
  }

  void _useCandidate(InstalledAppCandidate candidate) {
    final aliases = _candidateAliases(candidate);
    setState(() {
      _nameCtrl.text = candidate.name;
      _targetCtrl.text = candidate.target;
      _aliasesCtrl.text = aliases.join(', ');
      _descriptionCtrl.text = _candidateDescription(candidate);
      _type = candidate.type;
      _browser = '';
      _editingShortcut = null;
      _status = 'Revise e clique em salvar.';
    });
  }

  void _editShortcut(ShortcutEntry shortcut) {
    setState(() {
      _editingShortcut = shortcut;
      _nameCtrl.text = shortcut.name;
      _targetCtrl.text = shortcut.target;
      _aliasesCtrl.text = shortcut.aliases.join(', ');
      _descriptionCtrl.text = shortcut.visibleDescription;
      _type = shortcut.type;
      _browser = shortcut.isUrl ? shortcut.preferredBrowser : '';
      _status = 'Editando: ${shortcut.name}.';
    });
  }

  Future<void> _approveCandidate(InstalledAppCandidate candidate) async {
    if (_isExistingCandidate(candidate)) {
      setState(() => _status = 'Esse atalho ja esta cadastrado.');
      return;
    }

    setState(() => _approvingTarget = candidate.target);
    try {
      await api.createShortcut(
        tutorId: _tutorId,
        name: candidate.name,
        type: candidate.type,
        target: candidate.target,
        aliases: _candidateAliases(candidate),
        description: _candidateDescription(candidate),
      );
      await _load();
      if (!mounted) return;
      setState(() {
        _candidates = _candidates
            .where((item) =>
                _targetKey(item.target) != _targetKey(candidate.target))
            .toList();
        _status = 'Atalho aprovado: ${candidate.name}.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao aprovar atalho: $e');
    } finally {
      if (mounted) setState(() => _approvingTarget = null);
    }
  }

  void _clearForm() {
    _nameCtrl.clear();
    _targetCtrl.clear();
    _aliasesCtrl.clear();
    _descriptionCtrl.clear();
    _type = 'app';
    _browser = '';
    _editingShortcut = null;
  }

  String _descriptionForSave() {
    if (_type != 'url') return _descriptionCtrl.text;
    return ShortcutEntry.descriptionWithBrowser(
        _descriptionCtrl.text, _browser);
  }

  String _normalizedTarget(String raw) {
    if (_type != 'url' || raw.isEmpty) return raw;
    final uri = Uri.tryParse(raw);
    if (uri != null && uri.hasScheme) return raw;
    return 'https://$raw';
  }

  String _targetLabel() {
    if (_type == 'url') return 'URL';
    if (_type == 'command') return 'COMANDO DO AGENTE';
    return 'CAMINHO / ATALHO';
  }

  String _targetHint() {
    if (_type == 'url') return 'https://app.exemplo.com';
    if (_type == 'command') return 'Gerado ao escolher um app descoberto';
    return r'C:\...\Aplicativo.lnk';
  }

  List<String> _candidateAliases(InstalledAppCandidate candidate) {
    final aliases = candidate.aliases.isEmpty
        ? [candidate.name.toLowerCase()]
        : candidate.aliases;
    return aliases
        .map((item) => item.trim().toLowerCase())
        .where((item) => item.length > 1)
        .toSet()
        .toList();
  }

  String _candidateDescription(InstalledAppCandidate candidate) {
    final parts = [
      if (candidate.description.trim().isNotEmpty) candidate.description.trim(),
      if (candidate.reason.trim().isNotEmpty) candidate.reason.trim(),
      if (candidate.launchCommand.trim().isNotEmpty)
        'Comando: ${candidate.launchCommand.trim()}',
    ];
    return parts.join('\n');
  }

  bool _isValidLaunchCommand(String payload) {
    try {
      final decoded = jsonDecode(payload);
      return decoded is Map &&
          decoded['runner'] == 'windowsShellExecute' &&
          decoded['target']?.toString().trim().isNotEmpty == true;
    } catch (_) {
      return false;
    }
  }

  bool _isExistingCandidate(InstalledAppCandidate candidate) {
    final nameKey = _nameKey(candidate.name);
    final targetKey = _targetKey(candidate.target);
    return _shortcuts.any(
      (shortcut) =>
          _nameKey(shortcut.name) == nameKey ||
          _targetKey(shortcut.target) == targetKey,
    );
  }

  String _nameKey(String text) =>
      text.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();

  String _targetKey(String target) {
    var text = target.trim().toLowerCase();
    try {
      final decoded = jsonDecode(target);
      if (decoded is Map && decoded['target'] != null) {
        text = decoded['target'].toString().trim().toLowerCase();
      }
    } catch (_) {}
    final uri = Uri.tryParse(text);
    if (uri != null && uri.hasScheme) {
      final path = uri.path.endsWith('/') && uri.path.length > 1
          ? uri.path.substring(0, uri.path.length - 1)
          : uri.path;
      return '${uri.scheme}://${uri.host}$path'.toLowerCase();
    }
    return text.replaceAll('/', '\\');
  }

  @override
  Widget build(BuildContext context) {
    final body = Column(
      children: [
        if (!widget.embedded) _Header(onClose: () => Navigator.pop(context)),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  child: Column(
                    children: [
                      Expanded(child: _buildShortcutsList()),
                      const SizedBox(height: 16),
                      SizedBox(height: 175, child: _buildLaunchHistory()),
                    ],
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(child: _buildEditor()),
              ],
            ),
          ),
        ),
        _StatusBar(text: _status),
      ],
    );

    if (widget.embedded) return body;

    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      child: SizedBox(
        width: 840,
        height: 640,
        child: body,
      ),
    );
  }

  Widget _buildShortcutsList() {
    return _Panel(
      title: 'PROGRAMAS E URLS',
      child: _loading
          ? const Center(child: CircularProgressIndicator())
          : _shortcuts.isEmpty
              ? const Center(
                  child: Text(
                    'Nenhum atalho cadastrado',
                    style: TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 11,
                      color: AssistantTheme.textMuted,
                    ),
                  ),
                )
              : ListView.separated(
                  itemCount: _shortcuts.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (_, index) {
                    final shortcut = _shortcuts[index];
                    return _ShortcutTile(
                      shortcut: shortcut,
                      editing: _editingShortcut?.id == shortcut.id,
                      onEdit: () => _editShortcut(shortcut),
                      onDelete: () => _delete(shortcut),
                    );
                  },
                ),
    );
  }

  Widget _buildLaunchHistory() {
    return _Panel(
      title: 'HISTORICO DE EXECUCAO',
      child: _loading
          ? const SizedBox.shrink()
          : _launches.isEmpty
              ? const Center(
                  child: Text(
                    'Sem execucoes registradas',
                    style: TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 10,
                      color: AssistantTheme.textMuted,
                    ),
                  ),
                )
              : ListView.separated(
                  itemCount: _launches.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 6),
                  itemBuilder: (_, index) {
                    final item = _launches[index];
                    return _LaunchTile(item: item);
                  },
                ),
    );
  }

  Widget _buildEditor() {
    return Column(
      children: [
        SizedBox(
          height: _type == 'url' ? 365 : 305,
          child: _Panel(
            title: _editingShortcut == null ? 'NOVO ATALHO' : 'EDITAR ATALHO',
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      _TypeButton(
                        label: 'APP',
                        active: _type == 'app',
                        onTap: () => setState(() => _type = 'app'),
                      ),
                      const SizedBox(width: 8),
                      _TypeButton(
                        label: 'URL',
                        active: _type == 'url',
                        onTap: () => setState(() => _type = 'url'),
                      ),
                      const SizedBox(width: 8),
                      _TypeButton(
                        label: 'CMD',
                        active: _type == 'command',
                        onTap: () => setState(() => _type = 'command'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  _Field('NOME', _nameCtrl, hint: 'Chrome, VS Code, Jira...'),
                  _Field(
                    _targetLabel(),
                    _targetCtrl,
                    hint: _targetHint(),
                  ),
                  if (_type == 'url') ...[
                    _BrowserPicker(
                      value: _browser,
                      onChanged: (value) =>
                          setState(() => _browser = value ?? ''),
                    ),
                    const SizedBox(height: 8),
                  ],
                  _Field('APELIDOS', _aliasesCtrl,
                      hint: 'chrome, navegador, browser'),
                  _Field('DESCRICAO', _descriptionCtrl,
                      hint: 'Opcional', maxLines: 2),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: _ActionButton(
                          label: _saving
                              ? 'SALVANDO...'
                              : (_editingShortcut == null
                                  ? 'SALVAR ATALHO'
                                  : 'ATUALIZAR'),
                          onTap: _saving ? null : _save,
                        ),
                      ),
                      if (_editingShortcut != null) ...[
                        const SizedBox(width: 8),
                        Expanded(
                          child: _ActionButton(
                            label: 'CANCELAR',
                            onTap: () => setState(_clearForm),
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 14),
        Expanded(
          child: _Panel(
            title: 'DESCOBRIR E SUGERIR',
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: _ActionButton(
                        label: _scanning ? 'BUSCANDO...' : 'BUSCAR PC',
                        onTap: _scanning ? null : _scan,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: _ActionButton(
                        label: _suggesting ? 'AGENTE...' : 'AGENTE DEV',
                        onTap: _suggesting ? null : _suggestDeveloperProfile,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Expanded(
                  child: _candidates.isEmpty
                      ? const Center(
                          child: Text(
                            'Busca PC usa Menu Iniciar/Desktop.\nAgente Dev sugere ferramentas de desenvolvimento.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontFamily: 'JetBrains Mono',
                              fontSize: 10,
                              color: AssistantTheme.textMuted,
                            ),
                          ),
                        )
                      : ListView.separated(
                          itemCount: _candidates.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(height: 6),
                          itemBuilder: (_, index) {
                            final candidate = _candidates[index];
                            return _CandidateTile(
                              candidate: candidate,
                              onUse: () => _useCandidate(candidate),
                              onApprove: () => _approveCandidate(candidate),
                              approving: _approvingTarget == candidate.target,
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  final VoidCallback onClose;
  const _Header({required this.onClose});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.fromLTRB(18, 14, 10, 12),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AssistantTheme.border)),
        ),
        child: Row(
          children: [
            const Expanded(
              child: Text(
                'PROGRAMAS FAVORITOS',
                style: TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 4,
                  color: AssistantTheme.c1,
                ),
              ),
            ),
            IconButton(
              onPressed: onClose,
              icon: const Icon(Icons.close, color: AssistantTheme.textMuted),
            ),
          ],
        ),
      );
}

class _Panel extends StatelessWidget {
  final String title;
  final Widget child;
  const _Panel({required this.title, required this.child});

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          border: Border.all(color: AssistantTheme.border),
          borderRadius: BorderRadius.circular(4),
          color: AssistantTheme.bg.withOpacity(0.3),
        ),
        child: Column(
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
            const SizedBox(height: 12),
            Expanded(child: child),
          ],
        ),
      );
}

class _BrowserPicker extends StatelessWidget {
  final String value;
  final ValueChanged<String?> onChanged;

  const _BrowserPicker({
    required this.value,
    required this.onChanged,
  });

  static const _options = [
    ('', 'Padrao do sistema'),
    ('chrome', 'Google Chrome'),
    ('edge', 'Microsoft Edge'),
    ('firefox', 'Firefox'),
    ('brave', 'Brave'),
    ('opera', 'Opera'),
    ('vivaldi', 'Vivaldi'),
    ('chromium', 'Chromium'),
  ];

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      value: _options.any((item) => item.$1 == value) ? value : '',
      decoration: const InputDecoration(labelText: 'NAVEGADOR'),
      dropdownColor: AssistantTheme.surface,
      style: const TextStyle(
        fontFamily: 'JetBrains Mono',
        fontSize: 12,
        color: AssistantTheme.textPrimary,
      ),
      items: _options
          .map(
            (item) => DropdownMenuItem<String>(
              value: item.$1,
              child: Text(item.$2),
            ),
          )
          .toList(),
      onChanged: onChanged,
    );
  }
}

class _ShortcutTile extends StatelessWidget {
  final ShortcutEntry shortcut;
  final bool editing;
  final VoidCallback onEdit;
  final VoidCallback onDelete;
  const _ShortcutTile({
    required this.shortcut,
    required this.editing,
    required this.onEdit,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          border: Border.all(
            color: editing ? AssistantTheme.c1 : AssistantTheme.border,
          ),
          borderRadius: BorderRadius.circular(3),
          color: editing ? AssistantTheme.c1.withOpacity(0.05) : null,
        ),
        child: Row(
          children: [
            Icon(
              shortcut.isUrl ? Icons.link : Icons.apps,
              size: 16,
              color: shortcut.isUrl ? AssistantTheme.c2 : AssistantTheme.c3,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    shortcut.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 11,
                      color: AssistantTheme.textPrimary,
                    ),
                  ),
                  Text(
                    shortcut.aliases.isEmpty
                        ? shortcut.target
                        : shortcut.aliases.join(', '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 9,
                      color: AssistantTheme.textMuted,
                    ),
                  ),
                  if (shortcut.useCount > 0)
                    Text(
                      'execucoes: ${shortcut.useCount}'
                      '${shortcut.lastUsedAt == null ? '' : ' | ultimo: ${_formatShortDate(shortcut.lastUsedAt!)}'}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 8.5,
                        color: AssistantTheme.c3,
                      ),
                    ),
                  if (shortcut.isUrl && shortcut.preferredBrowser.isNotEmpty)
                    Text(
                      'navegador: ${_browserLabel(shortcut.preferredBrowser)}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 8.5,
                        color: AssistantTheme.c2,
                      ),
                    ),
                ],
              ),
            ),
            IconButton(
              tooltip: 'Editar',
              onPressed: onEdit,
              icon: const Icon(Icons.edit_outlined,
                  size: 17, color: AssistantTheme.c1),
            ),
            IconButton(
              tooltip: 'Remover',
              onPressed: onDelete,
              icon: const Icon(Icons.delete_outline,
                  size: 17, color: AssistantTheme.danger),
            ),
          ],
        ),
      );

  String _formatShortDate(DateTime value) =>
      '${value.day.toString().padLeft(2, '0')}/'
      '${value.month.toString().padLeft(2, '0')} '
      '${value.hour.toString().padLeft(2, '0')}:'
      '${value.minute.toString().padLeft(2, '0')}';

  String _browserLabel(String value) {
    switch (value) {
      case 'chrome':
        return 'Google Chrome';
      case 'edge':
        return 'Microsoft Edge';
      case 'firefox':
        return 'Firefox';
      case 'brave':
        return 'Brave';
      case 'opera':
        return 'Opera';
      case 'vivaldi':
        return 'Vivaldi';
      case 'chromium':
        return 'Chromium';
    }
    return value;
  }
}

class _LaunchTile extends StatelessWidget {
  final ShortcutLaunchEntry item;

  const _LaunchTile({required this.item});

  @override
  Widget build(BuildContext context) {
    final ok = item.status == 'executed';
    final color = ok ? AssistantTheme.c3 : AssistantTheme.danger;
    final detail = item.error?.trim().isNotEmpty == true
        ? item.error!.trim()
        : item.target;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
      decoration: BoxDecoration(
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Row(
        children: [
          Icon(
            ok ? Icons.check_circle_outline : Icons.error_outline,
            size: 14,
            color: color,
          ),
          const SizedBox(width: 7),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        item.shortcutName.isEmpty
                            ? item.targetType
                            : item.shortcutName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 9.5,
                          color: AssistantTheme.textSecondary,
                        ),
                      ),
                    ),
                    Text(
                      _formatDate(item.launchedAt),
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 8,
                        color: AssistantTheme.textMuted,
                      ),
                    ),
                  ],
                ),
                Text(
                  detail,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 8.2,
                    color: color.withOpacity(0.8),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static String _formatDate(DateTime value) =>
      '${value.day.toString().padLeft(2, '0')}/'
      '${value.month.toString().padLeft(2, '0')} '
      '${value.hour.toString().padLeft(2, '0')}:'
      '${value.minute.toString().padLeft(2, '0')}';
}

class _CandidateTile extends StatelessWidget {
  final InstalledAppCandidate candidate;
  final VoidCallback onUse;
  final VoidCallback onApprove;
  final bool approving;
  const _CandidateTile({
    required this.candidate,
    required this.onUse,
    required this.onApprove,
    required this.approving,
  });

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          border: Border.all(color: AssistantTheme.border),
          borderRadius: BorderRadius.circular(3),
        ),
        child: Row(
          children: [
            Icon(
              candidate.isUrl ? Icons.public : Icons.apps,
              size: 15,
              color: candidate.isUrl ? AssistantTheme.c2 : AssistantTheme.c3,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          candidate.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 10,
                            color: AssistantTheme.textSecondary,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      Text(
                        candidate.source.toUpperCase(),
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 7.5,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                    ],
                  ),
                  if (candidate.reason.isNotEmpty ||
                      candidate.description.isNotEmpty)
                    Text(
                      candidate.reason.isNotEmpty
                          ? candidate.reason
                          : candidate.description,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 8.5,
                        color: AssistantTheme.textMuted,
                      ),
                    ),
                ],
              ),
            ),
            TextButton(
              onPressed: onUse,
              child: const Text('USAR'),
            ),
            TextButton(
              onPressed: approving ? null : onApprove,
              child: Text(approving ? '...' : 'APROVAR'),
            ),
          ],
        ),
      );
}

class _Field extends StatelessWidget {
  final String label;
  final TextEditingController controller;
  final String? hint;
  final int maxLines;

  const _Field(
    this.label,
    this.controller, {
    this.hint,
    this.maxLines = 1,
  });

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 9),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 8.5,
                letterSpacing: 2,
                color: AssistantTheme.textMuted,
              ),
            ),
            const SizedBox(height: 4),
            TextField(
              controller: controller,
              maxLines: maxLines,
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: AssistantTheme.textPrimary,
              ),
              decoration: InputDecoration(hintText: hint),
            ),
          ],
        ),
      );
}

class _TypeButton extends StatelessWidget {
  final String label;
  final bool active;
  final VoidCallback onTap;
  const _TypeButton({
    required this.label,
    required this.active,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) => Expanded(
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
            side: BorderSide(
              color: active ? AssistantTheme.c1 : AssistantTheme.border,
            ),
            foregroundColor:
                active ? AssistantTheme.c1 : AssistantTheme.textMuted,
          ),
          child: Text(label),
        ),
      );
}

class _ActionButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;
  const _ActionButton({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: double.infinity,
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
            side: const BorderSide(color: AssistantTheme.c1),
            foregroundColor: AssistantTheme.c1,
            padding: const EdgeInsets.symmetric(vertical: 11),
          ),
          child: Text(
            label,
            style: const TextStyle(
              fontFamily: 'Rajdhani',
              fontWeight: FontWeight.w700,
              letterSpacing: 2,
            ),
          ),
        ),
      );
}

class _StatusBar extends StatelessWidget {
  final String text;
  const _StatusBar({required this.text});

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: AssistantTheme.border)),
        ),
        child: Text(
          text,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 10,
            color: AssistantTheme.textSecondary,
          ),
        ),
      );
}

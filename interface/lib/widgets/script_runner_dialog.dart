import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/api_service.dart';
import '../services/local_script_service.dart';
import '../utils/theme.dart';

class ScriptRunnerDialog extends StatefulWidget {
  final bool embedded;

  const ScriptRunnerDialog({super.key, this.embedded = false});

  @override
  State<ScriptRunnerDialog> createState() => _ScriptRunnerDialogState();
}

class _ScriptRunnerDialogState extends State<ScriptRunnerDialog> {
  static const _tutorId = 'default';

  final _nameCtrl = TextEditingController();
  final _descriptionCtrl = TextEditingController();
  final _scriptCtrl = TextEditingController();
  final _cwdCtrl = TextEditingController();
  final _timeoutCtrl = TextEditingController(text: '30');

  List<SavedScriptEntry> _savedScripts = const [];
  List<String> _shells = const [];
  String _shell = Platform.isWindows ? 'powershell' : 'bash';
  bool _loadingShells = true;
  bool _loadingScripts = true;
  bool _running = false;
  bool _savingScript = false;
  bool _allowHighRisk = false;
  String? _deletingScriptId;
  SavedScriptEntry? _selectedScript;
  String? _error;
  String _status = '';
  ScriptRunResult? _result;

  @override
  void initState() {
    super.initState();
    _loadShells();
    _loadSavedScripts();
  }

  Future<void> _loadShells() async {
    try {
      final info = await LocalScriptService.shellInfo();
      if (!mounted) return;
      setState(() {
        _shells = info.availableShells.isEmpty
            ? [_fallbackShell()]
            : info.availableShells;
        final selectedShell = _selectedScript?.shell;
        _shell = selectedShell != null && _shells.contains(selectedShell)
            ? selectedShell
            : _shells.contains(info.defaultShell)
                ? info.defaultShell
                : _shells.first;
        _loadingShells = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _shells = [_fallbackShell()];
        _shell = _shells.first;
        _error = 'Nao consegui consultar shells: $e';
        _loadingShells = false;
      });
    }
  }

  Future<void> _loadSavedScripts({String? selectedId}) async {
    setState(() => _loadingScripts = true);
    try {
      final scripts = await api.listSavedScripts(_tutorId);
      if (!mounted) return;
      final keepId = selectedId ?? _selectedScript?.id;
      SavedScriptEntry? selected;
      if (keepId != null) {
        for (final item in scripts) {
          if (item.id == keepId) {
            selected = item;
            break;
          }
        }
      }
      setState(() {
        _savedScripts = scripts;
        _selectedScript = selected;
        _loadingScripts = false;
        _status = scripts.isEmpty
            ? 'Salve scripts para reutilizar e renomear depois.'
            : '${scripts.length} script(s) salvo(s).';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadingScripts = false;
        _status = 'Nao consegui listar scripts: $e';
      });
    }
  }

  Future<void> _run() async {
    final script = _scriptCtrl.text.trim();
    if (script.isEmpty || _running) return;

    final timeout = int.tryParse(_timeoutCtrl.text.trim()) ?? 30;
    setState(() {
      _running = true;
      _error = null;
      _result = null;
    });

    try {
      final result = await LocalScriptService.runScript(
        shell: _shell,
        script: script,
        workingDirectory: _cwdCtrl.text,
        timeoutSeconds: timeout.clamp(1, 180),
        allowHighRisk: _allowHighRisk,
      );
      if (!mounted) return;
      setState(() => _result = result);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  Future<void> _saveScript() async {
    final name = _nameCtrl.text.trim();
    final script = _scriptCtrl.text.trim();
    if (name.isEmpty || script.isEmpty || _savingScript) {
      setState(() => _status = 'Preencha nome e script.');
      return;
    }

    final timeout = int.tryParse(_timeoutCtrl.text.trim()) ?? 30;
    setState(() {
      _savingScript = true;
      _status = 'Salvando script...';
    });

    try {
      final selected = _selectedScript;
      final saved = selected == null
          ? await api.createSavedScript(
              tutorId: _tutorId,
              name: name,
              shell: _shell,
              script: script,
              workingDirectory: _cwdCtrl.text,
              timeoutSeconds: timeout.clamp(1, 180),
              allowHighRisk: _allowHighRisk,
              description: _descriptionCtrl.text,
            )
          : await api.updateSavedScript(
              scriptId: selected.id,
              name: name,
              shell: _shell,
              script: script,
              workingDirectory: _cwdCtrl.text,
              timeoutSeconds: timeout.clamp(1, 180),
              allowHighRisk: _allowHighRisk,
              description: _descriptionCtrl.text,
            );
      if (!mounted) return;
      _selectScript(saved);
      await _loadSavedScripts(selectedId: saved.id);
      if (!mounted) return;
      setState(() => _status = selected == null
          ? 'Script salvo: $name.'
          : 'Script atualizado: $name.');
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao salvar script: $e');
    } finally {
      if (mounted) setState(() => _savingScript = false);
    }
  }

  Future<void> _deleteScript(SavedScriptEntry script) async {
    setState(() {
      _deletingScriptId = script.id;
      _status = 'Removendo script...';
    });
    try {
      await api.deleteSavedScript(script.id);
      if (_selectedScript?.id == script.id) _newScript();
      await _loadSavedScripts();
      if (!mounted) return;
      setState(() => _status = 'Script removido: ${script.name}.');
    } catch (e) {
      if (!mounted) return;
      setState(() => _status = 'Erro ao remover script: $e');
    } finally {
      if (mounted) setState(() => _deletingScriptId = null);
    }
  }

  void _selectScript(SavedScriptEntry script) {
    setState(() {
      _selectedScript = script;
      _nameCtrl.text = script.name;
      _descriptionCtrl.text = script.description;
      _scriptCtrl.text = script.script;
      _cwdCtrl.text = script.workingDirectory;
      _timeoutCtrl.text =
          (script.timeoutSeconds <= 0 ? 30 : script.timeoutSeconds).toString();
      _shell = _shells.contains(script.shell) || _shells.isEmpty
          ? script.shell
          : _shells.first;
      _allowHighRisk = script.allowHighRisk;
      _status = 'Editando: ${script.name}.';
      _result = null;
      _error = null;
    });
  }

  void _newScript() {
    setState(() {
      _selectedScript = null;
      _nameCtrl.clear();
      _descriptionCtrl.clear();
      _scriptCtrl.clear();
      _cwdCtrl.clear();
      _timeoutCtrl.text = '30';
      _allowHighRisk = false;
      _result = null;
      _error = null;
      _status = 'Novo script.';
    });
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _descriptionCtrl.dispose();
    _scriptCtrl.dispose();
    _cwdCtrl.dispose();
    _timeoutCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final body = Column(
      children: [
        if (!widget.embedded) _Header(onClose: () => Navigator.pop(context)),
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                flex: 3,
                child: _SavedScriptsPane(
                  scripts: _savedScripts,
                  selectedId: _selectedScript?.id,
                  loading: _loadingScripts,
                  deletingId: _deletingScriptId,
                  onSelect: _selectScript,
                  onDelete: _deleteScript,
                ),
              ),
              const VerticalDivider(
                width: 1,
                color: AssistantTheme.border,
              ),
              Expanded(
                flex: 5,
                child: _EditorPane(
                  nameCtrl: _nameCtrl,
                  descriptionCtrl: _descriptionCtrl,
                  scriptCtrl: _scriptCtrl,
                  cwdCtrl: _cwdCtrl,
                  timeoutCtrl: _timeoutCtrl,
                  shells: _shells,
                  shell: _shell,
                  loadingShells: _loadingShells,
                  allowHighRisk: _allowHighRisk,
                  running: _running,
                  savingScript: _savingScript,
                  editingSavedScript: _selectedScript != null,
                  onShellChanged: (value) => setState(() => _shell = value),
                  onRiskChanged: (value) =>
                      setState(() => _allowHighRisk = value),
                  onNew: _newScript,
                  onSaveScript: _saveScript,
                  onRun: _run,
                ),
              ),
              const VerticalDivider(
                width: 1,
                color: AssistantTheme.border,
              ),
              Expanded(
                flex: 4,
                child: _OutputPane(
                  result: _result,
                  error: _error,
                  running: _running,
                ),
              ),
            ],
          ),
        ),
        _StatusBar(text: _status),
      ],
    );

    if (widget.embedded) return body;

    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 980, maxHeight: 760),
        child: body,
      ),
    );
  }

  String _fallbackShell() => Platform.isWindows ? 'powershell' : 'sh';
}

class _SavedScriptsPane extends StatelessWidget {
  final List<SavedScriptEntry> scripts;
  final String? selectedId;
  final bool loading;
  final String? deletingId;
  final ValueChanged<SavedScriptEntry> onSelect;
  final ValueChanged<SavedScriptEntry> onDelete;

  const _SavedScriptsPane({
    required this.scripts,
    required this.selectedId,
    required this.loading,
    required this.deletingId,
    required this.onSelect,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'SCRIPTS SALVOS',
            style: TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 10,
              letterSpacing: 3,
              color: AssistantTheme.textMuted,
            ),
          ),
          const SizedBox(height: 10),
          Expanded(
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : scripts.isEmpty
                    ? const Center(
                        child: Text(
                          'Nenhum script salvo',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 11,
                            color: AssistantTheme.textMuted,
                          ),
                        ),
                      )
                    : ListView.separated(
                        itemCount: scripts.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (_, index) {
                          final script = scripts[index];
                          return _SavedScriptTile(
                            script: script,
                            selected: script.id == selectedId,
                            deleting: script.id == deletingId,
                            onSelect: () => onSelect(script),
                            onDelete: () => onDelete(script),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}

class _SavedScriptTile extends StatelessWidget {
  final SavedScriptEntry script;
  final bool selected;
  final bool deleting;
  final VoidCallback onSelect;
  final VoidCallback onDelete;

  const _SavedScriptTile({
    required this.script,
    required this.selected,
    required this.deleting,
    required this.onSelect,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final detail = script.description.trim().isNotEmpty
        ? script.description.trim()
        : script.script.trim().replaceAll(RegExp(r'\s+'), ' ');

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onSelect,
        borderRadius: BorderRadius.circular(3),
        child: Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            border: Border.all(
              color: selected ? AssistantTheme.c1 : AssistantTheme.border,
            ),
            borderRadius: BorderRadius.circular(3),
            color: selected ? AssistantTheme.c1.withOpacity(0.05) : null,
          ),
          child: Row(
            children: [
              Icon(
                Icons.terminal,
                size: 16,
                color: selected ? AssistantTheme.c1 : AssistantTheme.c4,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      script.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 11,
                        color: AssistantTheme.textPrimary,
                      ),
                    ),
                    Text(
                      '${script.displayShell} | ${script.timeoutSeconds}s',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 8.5,
                        color: AssistantTheme.c2,
                      ),
                    ),
                    if (detail.isNotEmpty)
                      Text(
                        detail,
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
              IconButton(
                tooltip: 'Editar',
                onPressed: onSelect,
                icon: const Icon(
                  Icons.edit_outlined,
                  size: 16,
                  color: AssistantTheme.c1,
                ),
              ),
              IconButton(
                tooltip: 'Remover',
                onPressed: deleting ? null : onDelete,
                icon: deleting
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(
                        Icons.delete_outline,
                        size: 16,
                        color: AssistantTheme.danger,
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  final VoidCallback onClose;

  const _Header({required this.onClose});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 10, 8),
      child: Row(
        children: [
          const Icon(Icons.terminal, size: 18, color: AssistantTheme.c4),
          const SizedBox(width: 10),
          const Expanded(
            child: Text(
              'EXECUTOR DE SCRIPTS',
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
            onPressed: onClose,
          ),
        ],
      ),
    );
  }
}

class _EditorPane extends StatelessWidget {
  final TextEditingController nameCtrl;
  final TextEditingController descriptionCtrl;
  final TextEditingController scriptCtrl;
  final TextEditingController cwdCtrl;
  final TextEditingController timeoutCtrl;
  final List<String> shells;
  final String shell;
  final bool loadingShells;
  final bool allowHighRisk;
  final bool running;
  final bool savingScript;
  final bool editingSavedScript;
  final ValueChanged<String> onShellChanged;
  final ValueChanged<bool> onRiskChanged;
  final VoidCallback onNew;
  final VoidCallback onSaveScript;
  final VoidCallback onRun;

  const _EditorPane({
    required this.nameCtrl,
    required this.descriptionCtrl,
    required this.scriptCtrl,
    required this.cwdCtrl,
    required this.timeoutCtrl,
    required this.shells,
    required this.shell,
    required this.loadingShells,
    required this.allowHighRisk,
    required this.running,
    required this.savingScript,
    required this.editingSavedScript,
    required this.onShellChanged,
    required this.onRiskChanged,
    required this.onNew,
    required this.onSaveScript,
    required this.onRun,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: nameCtrl,
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 12,
              color: AssistantTheme.textPrimary,
            ),
            decoration: const InputDecoration(labelText: 'Nome'),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: shells.contains(shell)
                      ? shell
                      : (shells.isEmpty ? null : shells.first),
                  dropdownColor: AssistantTheme.surface,
                  decoration: const InputDecoration(labelText: 'Shell'),
                  items: shells
                      .map((item) => DropdownMenuItem(
                            value: item,
                            child: Text(item),
                          ))
                      .toList(),
                  onChanged:
                      loadingShells ? null : (value) => onShellChanged(value!),
                ),
              ),
              const SizedBox(width: 10),
              SizedBox(
                width: 120,
                child: TextField(
                  controller: timeoutCtrl,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 12,
                    color: AssistantTheme.textPrimary,
                  ),
                  decoration: const InputDecoration(labelText: 'Timeout'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            controller: cwdCtrl,
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 12,
              color: AssistantTheme.textPrimary,
            ),
            decoration: const InputDecoration(labelText: 'Diretorio'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: descriptionCtrl,
            maxLines: 2,
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 12,
              color: AssistantTheme.textPrimary,
            ),
            decoration: const InputDecoration(labelText: 'Descricao'),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: TextField(
              controller: scriptCtrl,
              expands: true,
              minLines: null,
              maxLines: null,
              textAlignVertical: TextAlignVertical.top,
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 12,
                height: 1.35,
                color: AssistantTheme.textPrimary,
              ),
              decoration: const InputDecoration(
                alignLabelWithHint: true,
                labelText: 'Script',
              ),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Checkbox(
                value: allowHighRisk,
                onChanged:
                    running ? null : (value) => onRiskChanged(value == true),
                activeColor: AssistantTheme.danger,
              ),
              const Expanded(
                child: Text(
                  'Permitir alto risco',
                  style: TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 11,
                    color: AssistantTheme.textSecondary,
                  ),
                ),
              ),
              OutlinedButton.icon(
                onPressed: onNew,
                icon: const Icon(Icons.add, size: 17),
                label: const Text('NOVO'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AssistantTheme.textSecondary,
                  side: const BorderSide(color: AssistantTheme.border2),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: savingScript ? null : onSaveScript,
                icon: savingScript
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.save_outlined, size: 17),
                label: Text(editingSavedScript ? 'ATUALIZAR' : 'SALVAR'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AssistantTheme.c1,
                  side: BorderSide(color: AssistantTheme.c1.withOpacity(0.4)),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: running ? null : onRun,
                icon: running
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.play_arrow, size: 17),
                label: Text(running ? 'EXECUTANDO' : 'EXECUTAR'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AssistantTheme.c4,
                  side: BorderSide(color: AssistantTheme.c4.withOpacity(0.4)),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _OutputPane extends StatelessWidget {
  final ScriptRunResult? result;
  final String? error;
  final bool running;

  const _OutputPane({
    required this.result,
    required this.error,
    required this.running,
  });

  @override
  Widget build(BuildContext context) {
    final output = result?.combinedOutput ?? error ?? '';
    final color = error != null
        ? AssistantTheme.danger
        : result == null
            ? AssistantTheme.textMuted
            : result!.ok
                ? AssistantTheme.c3
                : AssistantTheme.c4;

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                result == null ? 'SAIDA' : 'EXIT ${result!.exitCode}',
                style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  letterSpacing: 3,
                  color: color,
                ),
              ),
              const Spacer(),
              IconButton(
                tooltip: 'Copiar saida',
                icon: const Icon(Icons.copy, size: 15),
                color: AssistantTheme.textSecondary,
                onPressed: output.trim().isEmpty
                    ? null
                    : () => Clipboard.setData(ClipboardData(text: output)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (result != null)
            _MetaLine(
              text:
                  '${result!.shell} | ${result!.durationMs}ms | ${result!.workingDirectory}',
            ),
          if (result?.highRiskDetected == true)
            const _MetaLine(text: 'alto risco permitido'),
          const SizedBox(height: 8),
          Expanded(
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                border: Border.all(color: AssistantTheme.border),
                borderRadius: BorderRadius.circular(4),
                color: AssistantTheme.bg2,
              ),
              child: running
                  ? const Center(child: CircularProgressIndicator())
                  : SingleChildScrollView(
                      child: SelectableText(
                        output.trim().isEmpty ? '(sem saida)' : output,
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 11,
                          height: 1.4,
                          color: AssistantTheme.textSecondary,
                        ),
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MetaLine extends StatelessWidget {
  final String text;

  const _MetaLine({required this.text});

  @override
  Widget build(BuildContext context) => Text(
        text,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          fontFamily: 'JetBrains Mono',
          fontSize: 9,
          color: AssistantTheme.textMuted,
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

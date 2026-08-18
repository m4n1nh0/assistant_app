import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/local_workspace_service.dart';
import '../services/syntax_check_service.dart';
import '../utils/theme.dart';
import 'workspace_diff_dialog.dart';

/// Modo editor do workspace: navega pelos diretórios, abre arquivos para
/// edição na própria ferramenta (com gravação apenas quando o usuário
/// autorizou), identifica a linguagem e valida a sintaxe.
///
/// Retorna via [Navigator.pop] o caminho relativo do arquivo aberto quando o
/// usuário escolhe "Mencionar no chat", para o pedido à IA já apontar o
/// arquivo certo.
class WorkspaceEditorDialog extends StatefulWidget {
  final String rootPath;
  final bool allowEdits;

  const WorkspaceEditorDialog({
    super.key,
    required this.rootPath,
    required this.allowEdits,
  });

  @override
  State<WorkspaceEditorDialog> createState() => _WorkspaceEditorDialogState();
}

class _WorkspaceEditorDialogState extends State<WorkspaceEditorDialog> {
  static const _maxFileBytes = 400 * 1024;

  final _contentCtrl = TextEditingController();
  final _treeScrollCtrl = ScrollController();

  final _expanded = <String>{};
  final _childrenCache = <String, List<_TreeEntry>>{};

  String? _openRelativePath;
  String? _openAbsolutePath;
  String _language = '';
  String _loadedContent = '';
  bool _dirty = false;
  bool _busy = false;
  String? _status;
  bool _statusIsError = false;

  @override
  void initState() {
    super.initState();
    _contentCtrl.addListener(() {
      final dirty = _contentCtrl.text != _loadedContent;
      if (dirty != _dirty) setState(() => _dirty = dirty);
    });
    _loadChildren(widget.rootPath);
  }

  @override
  void dispose() {
    _contentCtrl.dispose();
    _treeScrollCtrl.dispose();
    super.dispose();
  }

  String _relativeOf(String absolutePath) {
    final root = widget.rootPath.replaceAll('/', '\\');
    final path = absolutePath.replaceAll('/', '\\');
    if (path.toLowerCase().startsWith('${root.toLowerCase()}\\')) {
      return path.substring(root.length + 1).replaceAll('\\', '/');
    }
    return absolutePath.replaceAll('\\', '/');
  }

  Future<void> _loadChildren(String directoryPath) async {
    final entries = <_TreeEntry>[];
    try {
      await for (final entity
          in Directory(directoryPath).list(followLinks: false)) {
        final name = entity.path
            .replaceAll('/', '\\')
            .split('\\')
            .where((part) => part.isNotEmpty)
            .last;
        final isDir = entity is Directory;
        if (LocalWorkspaceService.shouldSkipEntry(name, isDirectory: isDir)) {
          continue;
        }
        if (!isDir && LocalWorkspaceService.isSensitive(name)) continue;
        entries.add(_TreeEntry(
          name: name,
          path: entity.path,
          isDirectory: isDir,
        ));
      }
    } catch (_) {
      // Pastas sem permissão de leitura ficam vazias na árvore.
    }
    entries.sort((a, b) {
      if (a.isDirectory != b.isDirectory) return a.isDirectory ? -1 : 1;
      return a.name.toLowerCase().compareTo(b.name.toLowerCase());
    });
    if (!mounted) return;
    setState(() => _childrenCache[directoryPath] = entries);
  }

  List<_VisibleNode> _visibleNodes() {
    final nodes = <_VisibleNode>[];
    void visit(String directoryPath, int depth) {
      final children = _childrenCache[directoryPath];
      if (children == null) return;
      for (final entry in children) {
        nodes.add(_VisibleNode(entry: entry, depth: depth));
        if (entry.isDirectory && _expanded.contains(entry.path)) {
          visit(entry.path, depth + 1);
        }
      }
    }

    visit(widget.rootPath, 0);
    return nodes;
  }

  Future<void> _toggleDirectory(_TreeEntry entry) async {
    if (_expanded.contains(entry.path)) {
      setState(() => _expanded.remove(entry.path));
      return;
    }
    setState(() => _expanded.add(entry.path));
    if (!_childrenCache.containsKey(entry.path)) {
      await _loadChildren(entry.path);
    }
  }

  Future<void> _refreshTree() async {
    _childrenCache.clear();
    await _loadChildren(widget.rootPath);
    for (final path in _expanded.toList()) {
      if (await Directory(path).exists()) {
        await _loadChildren(path);
      } else {
        _expanded.remove(path);
      }
    }
  }

  Future<void> _openFile(_TreeEntry entry) async {
    if (_dirty) {
      final discard = await _confirm(
        'Descartar alterações?',
        'O arquivo $_openRelativePath tem alterações não salvas. Abrir outro '
        'arquivo descarta essas alterações.',
        confirmLabel: 'Descartar',
      );
      if (discard != true) return;
    }
    setState(() {
      _busy = true;
      _status = null;
    });
    try {
      final file = File(entry.path);
      final stat = await file.stat();
      if (stat.size > _maxFileBytes) {
        _setStatus(
          'Arquivo muito grande para o editor '
          '(${(stat.size / 1024).round()} KB; limite ${_maxFileBytes ~/ 1024} KB).',
          isError: true,
        );
        return;
      }
      final bytes = await file.readAsBytes();
      final content = utf8.decode(bytes, allowMalformed: true);
      if (!mounted) return;
      setState(() {
        _openAbsolutePath = entry.path;
        _openRelativePath = _relativeOf(entry.path);
        _language = SyntaxCheckService.languageFor(entry.path);
        _loadedContent = content;
        _contentCtrl.text = content;
        _dirty = false;
      });
    } catch (e) {
      _setStatus('Não consegui abrir o arquivo: $e', isError: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    final relative = _openRelativePath;
    if (relative == null || !widget.allowEdits || !_dirty || _busy) return;
    setState(() {
      _busy = true;
      _status = null;
    });
    try {
      // Grava pelo mesmo caminho das edições da IA, com as mesmas proteções
      // de caminho, arquivos sensíveis e tamanho.
      await LocalWorkspaceService.applyEdits(
        rootPath: widget.rootPath,
        edits: [
          WorkspaceFileEdit(
            relativePath: relative,
            content: _contentCtrl.text,
          ),
        ],
      );
      _loadedContent = _contentCtrl.text;
      setState(() => _dirty = false);
      _setStatus('Salvo: $relative');
    } catch (e) {
      _setStatus('Falha ao salvar: $e', isError: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _validate() async {
    final absolute = _openAbsolutePath;
    if (absolute == null || _busy) return;
    // Dart é analisado pelo arquivo em disco: salva antes quando permitido.
    if (_dirty && widget.allowEdits) await _save();
    setState(() {
      _busy = true;
      _status = null;
    });
    try {
      final result = await SyntaxCheckService.check(
        absolutePath: absolute,
        content: _contentCtrl.text,
      );
      final prefix = result.ok
          ? '✅'
          : result.supported
              ? '❌'
              : '⚠️';
      _setStatus('$prefix ${result.message}', isError: !result.ok);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Abre o diff do arquivo aberto ou, sem arquivo, de todas as alterações
  /// pendentes do workspace. Recarrega o conteúdo depois, porque o diff
  /// permite desfazer alterações.
  Future<void> _showDiff() async {
    final relative = _openRelativePath;
    await showDialog<void>(
      context: context,
      builder: (_) => WorkspaceDiffDialog(
        rootPath: widget.rootPath,
        relativePaths: relative == null ? const [] : [relative],
      ),
    );
    if (!mounted || _openAbsolutePath == null || _dirty) return;
    try {
      final content = await File(_openAbsolutePath!).readAsString();
      if (!mounted || content == _loadedContent) return;
      setState(() {
        _loadedContent = content;
        _contentCtrl.text = content;
        _dirty = false;
      });
    } catch (_) {
      // Arquivo pode ter sido removido pelo "desfazer" do diff.
    }
  }

  void _setStatus(String message, {bool isError = false}) {
    if (!mounted) return;
    setState(() {
      _status = message;
      _statusIsError = isError;
    });
  }

  Future<bool?> _confirm(
    String title,
    String message, {
    String confirmLabel = 'Confirmar',
  }) =>
      showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text(
            title,
            style: const TextStyle(
              color: AssistantTheme.textPrimary,
              fontSize: 15,
            ),
          ),
          content: Text(
            message,
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 12,
              color: AssistantTheme.textSecondary,
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: Text(confirmLabel),
            ),
          ],
        ),
      );

  Future<void> _close() async {
    if (_dirty) {
      final discard = await _confirm(
        'Fechar editor?',
        'O arquivo $_openRelativePath tem alterações não salvas.',
        confirmLabel: 'Fechar sem salvar',
      );
      if (discard != true) return;
    }
    if (mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    return Dialog(
      backgroundColor: AssistantTheme.bg2,
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: SizedBox(
        width: (size.width - 80).clamp(640.0, 1240.0),
        height: (size.height - 90).clamp(420.0, 900.0),
        child: Column(
          children: [
            _buildHeader(),
            const Divider(height: 1, color: AssistantTheme.border),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SizedBox(width: 280, child: _buildTree()),
                  const VerticalDivider(width: 1, color: AssistantTheme.border),
                  Expanded(child: _buildEditor()),
                ],
              ),
            ),
            if (_status?.trim().isNotEmpty ?? false) ...[
              const Divider(height: 1, color: AssistantTheme.border),
              Container(
                width: double.infinity,
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Text(
                  _status!,
                  style: TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 11,
                    color: _statusIsError
                        ? AssistantTheme.danger
                        : AssistantTheme.c3,
                  ),
                  maxLines: 4,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    final title = _openRelativePath ?? 'Nenhum arquivo aberto';
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
      child: Row(
        children: [
          const Icon(Icons.code, size: 18, color: AssistantTheme.c1),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'MODO EDITOR — ${widget.rootPath}',
                  style: const TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 2,
                    color: AssistantTheme.textSecondary,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        '$title${_dirty ? ' •' : ''}',
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 12,
                          color: AssistantTheme.textPrimary,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (_language.isNotEmpty) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          border: Border.all(
                              color: AssistantTheme.c2.withOpacity(0.4)),
                          borderRadius: BorderRadius.circular(3),
                        ),
                        child: Text(
                          _language,
                          style: const TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 9,
                            color: AssistantTheme.c2,
                          ),
                        ),
                      ),
                    ],
                    if (!widget.allowEdits) ...[
                      const SizedBox(width: 8),
                      const Text(
                        'somente leitura',
                        style: TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 9,
                          color: AssistantTheme.c4,
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: widget.allowEdits
                ? 'Salvar (Ctrl+S)'
                : 'Edição não autorizada para esta pasta',
            onPressed:
                widget.allowEdits && _dirty && !_busy ? _save : null,
            icon: const Icon(Icons.save_outlined, size: 18),
            color: AssistantTheme.c3,
          ),
          IconButton(
            tooltip: 'Validar sintaxe',
            onPressed: _openAbsolutePath != null && !_busy ? _validate : null,
            icon: const Icon(Icons.rule, size: 18),
            color: AssistantTheme.c2,
          ),
          IconButton(
            tooltip: _openRelativePath == null
                ? 'Ver alterações do workspace'
                : 'Ver alterações deste arquivo',
            onPressed: _busy ? null : _showDiff,
            icon: const Icon(Icons.difference_outlined, size: 17),
            color: AssistantTheme.c3,
          ),
          IconButton(
            tooltip: 'Mencionar arquivo no chat',
            onPressed: _openRelativePath == null
                ? null
                : () => Navigator.pop(context, _openRelativePath),
            icon: const Icon(Icons.alternate_email, size: 18),
            color: AssistantTheme.c1,
          ),
          IconButton(
            tooltip: 'Fechar',
            onPressed: _close,
            icon: const Icon(Icons.close, size: 18),
            color: AssistantTheme.textSecondary,
          ),
        ],
      ),
    );
  }

  Widget _buildTree() {
    final nodes = _visibleNodes();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 4, 4),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'ARQUIVOS',
                  style: TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 9,
                    letterSpacing: 3,
                    color: AssistantTheme.textMuted,
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Atualizar árvore',
                constraints:
                    const BoxConstraints.tightFor(width: 26, height: 26),
                padding: EdgeInsets.zero,
                onPressed: _refreshTree,
                icon: const Icon(Icons.refresh, size: 14),
                color: AssistantTheme.textSecondary,
              ),
            ],
          ),
        ),
        Expanded(
          child: nodes.isEmpty
              ? const Center(
                  child: Text(
                    'Pasta vazia ou\nainda carregando...',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 10,
                      color: AssistantTheme.textMuted,
                    ),
                  ),
                )
              : ListView.builder(
                  controller: _treeScrollCtrl,
                  itemCount: nodes.length,
                  itemBuilder: (_, index) {
                    final node = nodes[index];
                    final entry = node.entry;
                    final isOpen = entry.path == _openAbsolutePath;
                    return InkWell(
                      onTap: () => entry.isDirectory
                          ? _toggleDirectory(entry)
                          : _openFile(entry),
                      child: Container(
                        color: isOpen
                            ? AssistantTheme.c1.withOpacity(0.08)
                            : null,
                        padding: EdgeInsets.only(
                          left: 10.0 + node.depth * 14,
                          top: 4,
                          bottom: 4,
                          right: 6,
                        ),
                        child: Row(
                          children: [
                            Icon(
                              entry.isDirectory
                                  ? (_expanded.contains(entry.path)
                                      ? Icons.folder_open
                                      : Icons.folder)
                                  : Icons.description_outlined,
                              size: 14,
                              color: entry.isDirectory
                                  ? AssistantTheme.c2
                                  : AssistantTheme.textSecondary,
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                entry.name,
                                style: TextStyle(
                                  fontFamily: 'JetBrains Mono',
                                  fontSize: 11,
                                  color: isOpen
                                      ? AssistantTheme.c1
                                      : AssistantTheme.textPrimary,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildEditor() {
    if (_openRelativePath == null) {
      return const Center(
        child: Text(
          'Selecione um arquivo na árvore para abrir.\n'
          'A IA edita melhor quando você menciona o arquivo no chat (@).',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 11,
            color: AssistantTheme.textMuted,
          ),
        ),
      );
    }
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.keyS, control: true): _save,
      },
      child: Container(
        color: AssistantTheme.bg,
        padding: const EdgeInsets.all(10),
        child: TextField(
          controller: _contentCtrl,
          readOnly: !widget.allowEdits,
          maxLines: null,
          expands: true,
          textAlignVertical: TextAlignVertical.top,
          style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 12,
            height: 1.5,
            color: AssistantTheme.textPrimary,
          ),
          decoration: const InputDecoration(
            border: InputBorder.none,
            isDense: true,
          ),
        ),
      ),
    );
  }
}

class _TreeEntry {
  final String name;
  final String path;
  final bool isDirectory;

  const _TreeEntry({
    required this.name,
    required this.path,
    required this.isDirectory,
  });
}

class _VisibleNode {
  final _TreeEntry entry;
  final int depth;

  const _VisibleNode({required this.entry, required this.depth});
}

/// Exibe o diff proposto para o usuario aprovar ou recusar.
library;

import 'package:flutter/material.dart';

import '../services/workspace_diff_service.dart';
import '../utils/theme.dart';

/// Visualizador de alterações do workspace no estilo de um cliente git:
/// lista de arquivos com contagem +/- à esquerda e o diff colorido à direita.
class WorkspaceDiffDialog extends StatefulWidget {
  final String rootPath;

  /// Arquivos a exibir. Vazio consulta o git pelas alterações pendentes.
  final List<String> relativePaths;

  const WorkspaceDiffDialog({
    super.key,
    required this.rootPath,
    this.relativePaths = const [],
  });

  @override
  State<WorkspaceDiffDialog> createState() => _WorkspaceDiffDialogState();
}

class _WorkspaceDiffDialogState extends State<WorkspaceDiffDialog> {
  static const _addColor = AssistantTheme.c3;
  static const _delColor = AssistantTheme.danger;

  List<FileDiff> _diffs = const [];
  int _selected = 0;
  bool _loading = true;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      if (!await WorkspaceDiffService.isGitRepository(widget.rootPath)) {
        if (!mounted) return;
        setState(() {
          _loading = false;
          _error = 'Esta pasta não é um repositório git, então não há '
              'histórico para comparar as alterações.';
        });
        return;
      }
      final paths = widget.relativePaths.isNotEmpty
          ? widget.relativePaths
          : await WorkspaceDiffService.changedPaths(widget.rootPath);
      final diffs = await WorkspaceDiffService.diffFor(widget.rootPath, paths);
      if (!mounted) return;
      setState(() {
        _diffs = diffs;
        _selected = diffs.isEmpty ? 0 : _selected.clamp(0, diffs.length - 1);
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Não consegui gerar o diff: $e';
      });
    }
  }

  Future<void> _revert(FileDiff diff) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text(
          'Desfazer alterações?',
          style: TextStyle(color: AssistantTheme.textPrimary, fontSize: 15),
        ),
        content: Text(
          diff.isNew
              ? 'O arquivo ${diff.relativePath} foi criado agora e será '
                  'apagado. Não dá para desfazer.'
              : 'As alterações em ${diff.relativePath} voltarão ao último '
                  'commit. Não dá para desfazer.',
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
            child: const Text('Desfazer'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await WorkspaceDiffService.revertFile(widget.rootPath, diff.relativePath);
    await _load();
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
        width: (size.width - 80).clamp(640.0, 1180.0),
        height: (size.height - 90).clamp(420.0, 860.0),
        child: Column(
          children: [
            _buildHeader(),
            const Divider(height: 1, color: AssistantTheme.border),
            Expanded(
              child: _loading
                  ? const Center(
                      child: SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    )
                  : _error.isNotEmpty
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(
                              _error,
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                fontFamily: 'JetBrains Mono',
                                fontSize: 11,
                                color: AssistantTheme.textMuted,
                              ),
                            ),
                          ),
                        )
                      : _diffs.isEmpty
                          ? const Center(
                              child: Text(
                                'Nenhuma alteração pendente no workspace.',
                                style: TextStyle(
                                  fontFamily: 'JetBrains Mono',
                                  fontSize: 11,
                                  color: AssistantTheme.textMuted,
                                ),
                              ),
                            )
                          : Row(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                SizedBox(width: 290, child: _buildFileList()),
                                const VerticalDivider(
                                    width: 1, color: AssistantTheme.border),
                                Expanded(child: _buildDiffView()),
                              ],
                            ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    final totalAdd =
        _diffs.fold<int>(0, (sum, diff) => sum + diff.additions);
    final totalDel =
        _diffs.fold<int>(0, (sum, diff) => sum + diff.deletions);
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
      child: Row(
        children: [
          const Icon(Icons.difference_outlined,
              size: 18, color: AssistantTheme.c1),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'ALTERAÇÕES DO WORKSPACE',
                  style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 2.5,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
                Text(
                  widget.rootPath,
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 10,
                    color: AssistantTheme.textMuted,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          if (_diffs.isNotEmpty) ...[
            Text(
              '+$totalAdd',
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: _addColor,
              ),
            ),
            const SizedBox(width: 8),
            Text(
              '−$totalDel',
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: _delColor,
              ),
            ),
            const SizedBox(width: 12),
          ],
          IconButton(
            tooltip: 'Recarregar',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh, size: 17),
            color: AssistantTheme.textSecondary,
          ),
          IconButton(
            tooltip: 'Fechar',
            onPressed: () => Navigator.pop(context),
            icon: const Icon(Icons.close, size: 18),
            color: AssistantTheme.textSecondary,
          ),
        ],
      ),
    );
  }

  Widget _buildFileList() {
    return ListView.builder(
      padding: const EdgeInsets.symmetric(vertical: 6),
      itemCount: _diffs.length,
      itemBuilder: (_, index) {
        final diff = _diffs[index];
        final isSelected = index == _selected;
        final name = diff.relativePath.split('/').last;
        final folder = diff.relativePath.contains('/')
            ? diff.relativePath.substring(
                0, diff.relativePath.lastIndexOf('/'))
            : '';
        return InkWell(
          onTap: () => setState(() => _selected = index),
          child: Container(
            color: isSelected ? AssistantTheme.c1.withOpacity(0.08) : null,
            padding: const EdgeInsets.fromLTRB(12, 7, 8, 7),
            child: Row(
              children: [
                Icon(
                  diff.isNew ? Icons.add_circle_outline : Icons.edit_outlined,
                  size: 13,
                  color: diff.isNew ? _addColor : AssistantTheme.c2,
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        name,
                        style: TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 11,
                          color: isSelected
                              ? AssistantTheme.c1
                              : AssistantTheme.textPrimary,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      if (folder.isNotEmpty)
                        Text(
                          folder,
                          style: const TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 9,
                            color: AssistantTheme.textMuted,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  '+${diff.additions}',
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 9,
                    color: _addColor,
                  ),
                ),
                const SizedBox(width: 5),
                Text(
                  '−${diff.deletions}',
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 9,
                    color: _delColor,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildDiffView() {
    final diff = _diffs[_selected];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(12, 7, 8, 7),
          color: AssistantTheme.surface.withOpacity(0.5),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '${diff.relativePath}${diff.isNew ? '  (novo)' : ''}',
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 11,
                    color: AssistantTheme.textPrimary,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              TextButton.icon(
                onPressed: () => _revert(diff),
                icon: const Icon(Icons.undo, size: 14),
                label: const Text('Desfazer'),
                style: TextButton.styleFrom(
                  foregroundColor: AssistantTheme.textSecondary,
                  textStyle: const TextStyle(fontSize: 11),
                ),
              ),
            ],
          ),
        ),
        if (diff.note != null)
          Padding(
            padding: const EdgeInsets.all(14),
            child: Text(
              diff.note!,
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: AssistantTheme.textMuted,
              ),
            ),
          ),
        Expanded(
          child: Container(
            color: AssistantTheme.bg,
            child: Scrollbar(
              child: ListView.builder(
                primary: true,
                itemCount: diff.lines.length + (diff.truncated ? 1 : 0),
                itemBuilder: (_, index) {
                  if (index >= diff.lines.length) {
                    return const Padding(
                      padding: EdgeInsets.all(10),
                      child: Text(
                        '… diff truncado (arquivo muito grande)',
                        style: TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 10,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                    );
                  }
                  return _buildDiffLine(diff.lines[index]);
                },
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildDiffLine(DiffLine line) {
    late final Color background;
    late final Color textColor;
    late final String marker;

    switch (line.type) {
      case DiffLineType.addition:
        background = _addColor.withOpacity(0.10);
        textColor = _addColor;
        marker = '+';
      case DiffLineType.deletion:
        background = _delColor.withOpacity(0.10);
        textColor = _delColor;
        marker = '−';
      case DiffLineType.hunk:
        background = AssistantTheme.c1.withOpacity(0.08);
        textColor = AssistantTheme.c1;
        marker = '';
      case DiffLineType.meta:
        background = Colors.transparent;
        textColor = AssistantTheme.textMuted;
        marker = '';
      case DiffLineType.context:
        background = Colors.transparent;
        textColor = AssistantTheme.textSecondary;
        marker = ' ';
    }

    return Container(
      color: background,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _lineNumber(line.oldNumber),
          _lineNumber(line.newNumber),
          SizedBox(
            width: 14,
            child: Text(
              marker,
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: textColor,
              ),
            ),
          ),
          Expanded(
            child: SelectableText(
              line.text.isEmpty ? ' ' : line.text,
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                height: 1.45,
                color: textColor,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _lineNumber(int? value) => SizedBox(
        width: 40,
        child: Text(
          value?.toString() ?? '',
          textAlign: TextAlign.right,
          style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 10,
            height: 1.6,
            color: AssistantTheme.textMuted,
          ),
        ),
      );
}

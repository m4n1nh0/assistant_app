/// Material didatico da disciplina: enviar, listar e usar como fonte de quiz.
///
/// A aula gravada nem sempre e a melhor fonte de pergunta - a apostila ja vem
/// organizada por topico e escrita com rigor. Aqui o professor sobe o arquivo
/// uma vez e ele passa a valer para varios quizzes da disciplina.
library;

import 'dart:io';


import 'package:flutter/material.dart';

import '../services/education_service.dart';
import 'package:file_picker/file_picker.dart';
import '../utils/theme.dart';

class MaterialsPanel extends StatefulWidget {
  /// Avisa quem monta a tela que a lista mudou.
  final VoidCallback? onChanged;

  const MaterialsPanel({super.key, this.onChanged});

  @override
  State<MaterialsPanel> createState() => _MaterialsPanelState();
}

class _MaterialsPanelState extends State<MaterialsPanel> {
  List<CourseMaterial> _materials = const [];
  List<Discipline> _disciplines = const [];
  bool _loading = true;
  bool _uploading = false;
  String _status = '';
  bool _error = false;
  String? _disciplineFilter;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      // As disciplinas vem junto: o painel se vira sozinho em vez de depender
      // do estado de outra aba, que nem sempre esta carregado.
      final items = await education.listMaterials();
      final disciplines = await education.listDisciplines();
      if (!mounted) return;
      setState(() {
        _materials = items;
        _disciplines = disciplines;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _status = 'Falha ao carregar materiais: $e';
        _error = true;
      });
    }
  }

  void _report(String message, {bool error = false}) {
    if (!mounted) return;
    setState(() {
      _status = message;
      _error = error;
    });
  }

  Future<void> _upload() async {
    final escolhida = await _pickDiscipline();
    if (escolhida == null) return;

    setState(() => _uploading = true);
    try {
      final selection = await FilePicker.pickFiles(
        type: FileType.custom,
        allowedExtensions: const ['pdf'],
        withData: true,
      );
      if (selection == null || selection.files.isEmpty) return;

      final file = selection.files.single;
      final bytes = file.bytes ??
          (file.path == null ? null : await File(file.path!).readAsBytes());
      if (bytes == null) {
        _report('Nao consegui ler o arquivo escolhido.', error: true);
        return;
      }

      final material = await education.uploadMaterial(
        bytes: bytes,
        filename: file.name,
        disciplineId: escolhida.id,
        discipline: escolhida.label,
      );
      _report(
        '${material.title} carregado: ${material.pageCount} pagina(s)'
        '${material.truncated ? ", texto cortado no limite" : ""}.',
      );
      await _load();
      widget.onChanged?.call();
    } catch (e) {
      // A mensagem do servidor explica o caso mais comum: PDF digitalizado, que
      // e imagem e precisaria de OCR.
      _report('$e', error: true);
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  /// Escolhe a disciplina antes de abrir o seletor de arquivo.
  ///
  /// Material sem disciplina existe, mas some das listas filtradas e nao serve
  /// ao simulado - entao a pergunta vem antes, e nao depois do upload.
  Future<_DisciplineChoice?> _pickDiscipline() async {
    if (_disciplines.isEmpty) {
      return const _DisciplineChoice(id: '', label: '');
    }
    return showDialog<_DisciplineChoice>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Material de qual disciplina?'),
        content: SizedBox(
          width: 420,
          child: ListView(
            shrinkWrap: true,
            children: [
              for (final discipline in _disciplines)
                ListTile(
                  dense: true,
                  title: Text(
                    discipline.label,
                    style: const TextStyle(fontSize: 13),
                  ),
                  onTap: () => Navigator.pop(
                    dialogContext,
                    _DisciplineChoice(
                      id: discipline.id,
                      label: discipline.label,
                    ),
                  ),
                ),
              const Divider(),
              ListTile(
                dense: true,
                title: const Text(
                  'Sem disciplina',
                  style: TextStyle(fontSize: 13),
                ),
                subtitle: const Text(
                  'O material nao aparece nos filtros por disciplina.',
                  style: TextStyle(fontSize: 11),
                ),
                onTap: () => Navigator.pop(
                  dialogContext,
                  const _DisciplineChoice(id: '', label: ''),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('CANCELAR'),
          ),
        ],
      ),
    );
  }

  Future<void> _delete(CourseMaterial material) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Remover material'),
        content: Text(
          '${material.title} sai da lista. '
          'Quiz ja gerado a partir dele continua valendo.',
          style: const TextStyle(color: AssistantTheme.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('REMOVER'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await education.deleteMaterial(material.id);
      _report('${material.title} removido.');
      await _load();
      widget.onChanged?.call();
    } catch (e) {
      _report('Falha ao remover: $e', error: true);
    }
  }

  List<CourseMaterial> get _visible => _disciplineFilter == null
      ? _materials
      : _materials
          .where((item) => item.discipline == _disciplineFilter)
          .toList();

  @override
  Widget build(BuildContext context) {
    final disciplinas = {
      for (final item in _materials)
        if (item.discipline.isNotEmpty) item.discipline
    }.toList()
      ..sort();

    return Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'Material da disciplina — apostila, capitulo, slide. '
                  'Serve de fonte para o quiz, no lugar da aula gravada.',
                  style: TextStyle(
                    fontSize: 11,
                    color: AssistantTheme.textMuted,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton.icon(
                onPressed: _uploading ? null : _upload,
                icon: _uploading
                    ? const SizedBox.square(
                        dimension: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.upload_file_outlined, size: 16),
                label: Text(_uploading ? 'ENVIANDO...' : 'ENVIAR PDF'),
                style: FilledButton.styleFrom(
                  backgroundColor: AssistantTheme.c3,
                  foregroundColor: AssistantTheme.bg,
                ),
              ),
            ],
          ),
          if (disciplinas.length > 1) ...[
            const SizedBox(height: 10),
            Wrap(
              spacing: 6,
              children: [
                _Chip(
                  label: 'TODAS ${_materials.length}',
                  selected: _disciplineFilter == null,
                  onTap: () => setState(() => _disciplineFilter = null),
                ),
                for (final nome in disciplinas)
                  _Chip(
                    label: nome.toUpperCase(),
                    selected: _disciplineFilter == nome,
                    onTap: () => setState(() => _disciplineFilter = nome),
                  ),
              ],
            ),
          ],
          const SizedBox(height: 10),
          if (_status.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                _status,
                style: TextStyle(
                  fontSize: 11,
                  color: _error ? AssistantTheme.danger : AssistantTheme.c3,
                ),
              ),
            ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _visible.isEmpty
                    ? const Center(
                        child: Text(
                          'Nenhum material ainda.\n'
                          'Envie um PDF para gerar quiz a partir dele.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 12,
                            color: AssistantTheme.textMuted,
                          ),
                        ),
                      )
                    : ListView.separated(
                        itemCount: _visible.length,
                        separatorBuilder: (_, __) => const Divider(
                          height: 14,
                          color: AssistantTheme.border,
                        ),
                        itemBuilder: (_, index) => _MaterialRow(
                          material: _visible[index],
                          onDelete: () => _delete(_visible[index]),
                        ),
                      ),
          ),
        ],
      ),
    );
  }
}

class _DisciplineChoice {
  final String id;
  final String label;

  const _DisciplineChoice({required this.id, required this.label});
}

class _MaterialRow extends StatelessWidget {
  final CourseMaterial material;
  final VoidCallback onDelete;

  const _MaterialRow({required this.material, required this.onDelete});

  @override
  Widget build(BuildContext context) {
    final detalhes = [
      if (material.discipline.isNotEmpty) material.discipline,
      '${material.pageCount} pagina(s)',
      '${(material.charCount / 1000).toStringAsFixed(0)} mil caracteres',
      if (material.truncated) 'texto cortado no limite',
    ].join('  ·  ');

    return Row(
      children: [
        const Icon(
          Icons.picture_as_pdf_outlined,
          size: 18,
          color: AssistantTheme.textMuted,
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                material.title.isEmpty ? material.filename : material.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 13,
                  color: AssistantTheme.textPrimary,
                ),
              ),
              Text(
                detalhes,
                style: const TextStyle(
                  fontSize: 10,
                  color: AssistantTheme.textMuted,
                ),
              ),
            ],
          ),
        ),
        IconButton(
          tooltip: 'Remover material',
          icon: const Icon(Icons.delete_outline, size: 16),
          color: AssistantTheme.textMuted,
          onPressed: onDelete,
        ),
      ],
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _Chip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cor = selected ? AssistantTheme.c1 : AssistantTheme.textMuted;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(3),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            border: Border.all(color: cor.withValues(alpha: selected ? 0.9 : 0.35)),
            borderRadius: BorderRadius.circular(3),
            color: selected ? cor.withValues(alpha: 0.12) : null,
          ),
          child: Text(
            label,
            style: TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 9,
              letterSpacing: 0.6,
              color: cor,
            ),
          ),
        ),
      ),
    );
  }
}

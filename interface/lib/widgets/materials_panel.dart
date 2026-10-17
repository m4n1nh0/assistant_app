/// Material didatico da disciplina: enviar, listar e usar como fonte de quiz.
///
/// A aula gravada nem sempre e a melhor fonte de pergunta - a apostila ja vem
/// organizada por topico e escrita com rigor. Aqui o professor sobe o arquivo
/// uma vez e ele passa a valer para varios quizzes da disciplina.
library;

import 'dart:io';


import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/app_config.dart';
import '../providers/app_provider.dart';
import '../services/connected_ai_service.dart';
import '../services/education_service.dart';
import 'package:file_picker/file_picker.dart';
import '../utils/theme.dart';
import 'summary_pickers.dart';

/// O que o seletor de arquivo deixa escolher.
///
/// Espelha os extratores registrados no `material_service` do servidor - e la
/// que a recusa de verdade acontece. Aqui a lista serve so para o professor nao
/// perder tempo escolhendo um arquivo que voltaria com erro.
///
/// As imagens dependem do OCR estar ligado no servidor. Continuam na lista
/// mesmo assim: se estiver desligado, a mensagem que volta explica isso, o que
/// ajuda mais do que o arquivo simplesmente nao aparecer no seletor.
const _extensoesAceitas = [
  'pdf',
  'docx',
  'pptx',
  'txt',
  'md',
  'jpg',
  'jpeg',
  'png',
  'webp',
  'bmp',
  'tiff',
];

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

  /// Material que a IA esta reescrevendo agora; so um por vez.
  String? _improvingId;
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

  /// Se o arquivo pode acabar no OCR, e a espera ser longa.
  ///
  /// Imagem sempre passa por OCR; PDF so quando nao tem camada de texto, o que
  /// nenhum dos dois lados sabe antes de tentar ler. Avisar a mais e melhor que
  /// deixar o professor achando que a tela travou.
  bool _podeExigirOcr(String filename) {
    final nome = filename.toLowerCase();
    return !nome.endsWith('.docx') &&
        !nome.endsWith('.pptx') &&
        !nome.endsWith('.txt') &&
        !nome.endsWith('.md');
  }

  Future<void> _upload() async {
    final escolhida = await _pickDiscipline();
    if (escolhida == null) return;

    setState(() => _uploading = true);
    try {
      final selection = await FilePicker.pickFiles(
        type: FileType.custom,
        allowedExtensions: _extensoesAceitas,
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

      // Nome em branco deixa o servidor escolher: titulo de dentro do
      // documento e, sem ele, o nome do arquivo.
      if (!mounted) return;
      final nome = await _askName(
        title: 'Nome do material',
        hint: 'Ex.: Apostila de Banco de Dados',
        helper: 'Deixe em branco para usar o titulo do documento '
            '(${file.name}).',
        confirm: 'ENVIAR',
      );
      if (nome == null) return;

      // Material digitalizado passa por OCR no servidor, e isso leva dezenas de
      // segundos. Sem dizer nada, a espera parece travamento.
      _report(
        _podeExigirOcr(file.name)
            ? 'Lendo ${file.name}. Material digitalizado leva alguns segundos...'
            : 'Enviando ${file.name}...',
      );

      final material = await education.uploadMaterial(
        bytes: bytes,
        filename: file.name,
        disciplineId: escolhida.id,
        discipline: escolhida.label,
        title: nome,
      );
      _report(
        '${material.title} carregado: '
        '${material.pageCount} ${material.unitLabel}'
        '${material.fromOcr ? ", lido por OCR" : ""}'
        '${material.truncated ? ", texto cortado no limite" : ""}.',
      );
      await _load();
      widget.onChanged?.call();
    } catch (e) {
      // A mensagem vem do servidor: so ele sabe se o caso foi formato recusado
      // ou PDF digitalizado, que e imagem e precisaria de OCR.
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

  /// Pergunta o nome do material. `null` e cancelar; texto vazio e "deixa o
  /// servidor escolher", que so faz sentido no envio.
  Future<String?> _askName({
    required String title,
    required String confirm,
    String initial = '',
    String hint = '',
    String helper = '',
  }) {
    return showDialog<String>(
      context: context,
      builder: (_) => _NameDialog(
        title: title,
        confirm: confirm,
        initial: initial,
        hint: hint,
        helper: helper,
      ),
    );
  }

  Future<void> _rename(CourseMaterial material) async {
    final atual = material.title.isEmpty ? material.filename : material.title;
    final nome = await _askName(
      title: 'Renomear material',
      confirm: 'SALVAR',
      initial: atual,
    );
    if (nome == null || nome.isEmpty || nome == atual) return;
    try {
      await education.renameMaterial(material.id, nome);
      _report('Material renomeado para $nome.');
      await _load();
      widget.onChanged?.call();
    } catch (e) {
      _report('Falha ao renomear: $e', error: true);
    }
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

  /// A configuracao do app, quando ha um ProviderScope acima. Sem ele (testes isolados do
  /// painel) o seletor mostra so o automatico.
  AppConfig? _config() {
    try {
      return ProviderScope.containerOf(context, listen: false)
          .read(configProvider);
    } catch (_) {
      return null;
    }
  }

  Future<void> _improve(CourseMaterial material) async {
    final request = await showDialog<_ImproveRequest>(
      context: context,
      builder: (_) => _ImproveDialog(
        title: material.title.isEmpty ? material.filename : material.title,
        config: _config() ?? AppConfig(),
        replacing: material.improved,
      ),
    );
    if (request == null) return;
    setState(() => _improvingId = material.id);
    _report('Melhorando o texto...');
    try {
      final done = await _runImprove(material, request);
      _report('Texto melhorado por ${AppConfig.serviceLabel(done.improvedLlm)}.');
      await _load();
      widget.onChanged?.call();
    } catch (e) {
      _report('Falha ao melhorar: $e', error: true);
    } finally {
      if (mounted) setState(() => _improvingId = null);
    }
  }

  /// Provedor do backend: o servidor le, reescreve e grava. Agente conectado (Codex,
  /// Claude Code): o backend entrega o prompt, o CLI do usuario reescreve com o material
  /// inteiro em uma chamada e o texto volta para ser gravado.
  Future<CourseMaterial> _runImprove(
    CourseMaterial material,
    _ImproveRequest request,
  ) async {
    if (!AppConfig.connectedAgentIds.contains(request.engine)) {
      return education.improveMaterial(
        material.id,
        llm: request.engine.isEmpty ? null : request.engine,
        instructions: request.instructions,
      );
    }
    final built = await education.materialImprovePrompt(
      material.id,
      instructions: request.instructions,
    );
    _report(
      '${AppConfig.serviceLabel(request.engine)} lendo o material '
      '(${built.chars} caracteres em uma chamada)...',
    );
    final result = await ConnectedAiService.run(
      agentId: request.engine,
      prompt: built.prompt,
      systemPrompt: built.systemPrompt,
      language: _config()?.language ?? 'pt-BR',
      // Material inteiro de uma vez: leva mais que uma resposta de chat.
      timeoutOverride: const Duration(minutes: 15),
      onProgress: (activity) {
        if (mounted) _report(activity);
      },
    );
    if (result.isError) throw EducationException(result.content);
    return education.saveExternalImprovement(
      material.id,
      text: result.content,
      llm: request.engine,
    );
  }

  Future<void> _viewImproved(CourseMaterial material) async {
    try {
      final text = await education.improvedMaterialText(material.id);
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text(material.title.isEmpty ? material.filename : material.title),
          content: SizedBox(
            width: 640,
            height: 420,
            child: SingleChildScrollView(
              child: SelectableText(
                text,
                style: const TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: AssistantTheme.textSecondary,
                ),
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('FECHAR'),
            ),
          ],
        ),
      );
    } catch (e) {
      _report('Falha ao abrir o texto melhorado: $e', error: true);
    }
  }

  Future<void> _discardImprovement(CourseMaterial material) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Voltar ao texto original'),
        content: const Text(
          'A versao melhorada pela IA e descartada. O portal do aluno e o quiz '
          'voltam a usar o texto extraido do arquivo.',
          style: TextStyle(color: AssistantTheme.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('DESCARTAR'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await education.discardImprovement(material.id);
      _report('Voltou ao texto original.');
      await _load();
      widget.onChanged?.call();
    } catch (e) {
      _report('Falha ao descartar: $e', error: true);
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
                label: Text(_uploading ? 'ENVIANDO...' : 'ENVIAR MATERIAL'),
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
                          'Envie apostila, slide, anotacao ou foto do quadro.',
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
                          improving: _improvingId == _visible[index].id,
                          busy: _improvingId != null,
                          onRename: () => _rename(_visible[index]),
                          onDelete: () => _delete(_visible[index]),
                          onImprove: () => _improve(_visible[index]),
                          onViewImproved: () => _viewImproved(_visible[index]),
                          onDiscardImprovement: () =>
                              _discardImprovement(_visible[index]),
                        ),
                      ),
          ),
        ],
      ),
    );
  }
}

/// O que o professor escolheu para a melhoria: quem escreve e o pedido extra.
class _ImproveRequest {
  final String engine;
  final String instructions;

  const _ImproveRequest(this.engine, this.instructions);
}

class _ImproveDialog extends StatefulWidget {
  final String title;
  final AppConfig config;
  final bool replacing;

  const _ImproveDialog({
    required this.title,
    required this.config,
    required this.replacing,
  });

  @override
  State<_ImproveDialog> createState() => _ImproveDialogState();
}

class _ImproveDialogState extends State<_ImproveDialog> {
  final _instructions = TextEditingController();
  String _engine = '';

  @override
  void dispose() {
    _instructions.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: const Text('Melhorar texto com IA'),
      content: SizedBox(
        width: 480,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 13,
                color: AssistantTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'A IA reorganiza o texto extraido em titulos, listas e paragrafos, '
              'sem resumir nem acrescentar nada. O original fica guardado e voce '
              'pode voltar a ele quando quiser.'
              '${widget.replacing ? ' A versao melhorada atual sera substituida.' : ''}',
              style: const TextStyle(
                fontSize: 11,
                height: 1.45,
                color: AssistantTheme.textMuted,
              ),
            ),
            const SizedBox(height: 14),
            SummaryEnginePicker(
              engine: _engine,
              config: widget.config,
              width: 300,
              tooltip: 'Quem reescreve o material.\n'
                  'Automatico: a fila do backend, do gratuito ao pago.\n'
                  'Provedor: fixa nele, sem tentar outro.\n'
                  'Agente conectado (Codex, Claude Code): roda neste computador '
                  'e le o material inteiro de uma vez.',
              onChanged: (engine) => setState(() => _engine = engine),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _instructions,
              maxLines: 2,
              maxLength: 1000,
              style: const TextStyle(
                fontSize: 12,
                color: AssistantTheme.textPrimary,
              ),
              decoration: const InputDecoration(
                labelText: 'PEDIDO EXTRA (OPCIONAL)',
                hintText: 'ex: manter os nomes das plataformas em ingles',
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('CANCELAR'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(
            context,
            _ImproveRequest(_engine, _instructions.text.trim()),
          ),
          child: const Text('MELHORAR'),
        ),
      ],
    );
  }
}

/// Caixa de texto de uma linha. Estado proprio para o controller ser liberado
/// so quando a caixa sai da arvore, e nao no meio da animacao de fechar.
class _NameDialog extends StatefulWidget {
  final String title;
  final String confirm;
  final String initial;
  final String hint;
  final String helper;

  const _NameDialog({
    required this.title,
    required this.confirm,
    required this.initial,
    required this.hint,
    required this.helper,
  });

  @override
  State<_NameDialog> createState() => _NameDialogState();
}

class _NameDialogState extends State<_NameDialog> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() => Navigator.pop(context, _controller.text.trim());

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: Text(widget.title),
      content: SizedBox(
        width: 420,
        child: TextField(
          controller: _controller,
          autofocus: true,
          maxLength: 255,
          onSubmitted: (_) => _submit(),
          decoration: InputDecoration(
            hintText: widget.hint.isEmpty ? null : widget.hint,
            helperText: widget.helper.isEmpty ? null : widget.helper,
            helperMaxLines: 2,
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('CANCELAR'),
        ),
        TextButton(
          onPressed: _submit,
          child: Text(widget.confirm),
        ),
      ],
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
  final VoidCallback onRename;
  final VoidCallback onDelete;
  final VoidCallback onImprove;
  final VoidCallback onViewImproved;
  final VoidCallback onDiscardImprovement;

  /// Esta linha esta sendo reescrita pela IA; [busy] vale para qualquer linha.
  final bool improving;
  final bool busy;

  const _MaterialRow({
    required this.material,
    required this.onRename,
    required this.onDelete,
    required this.onImprove,
    required this.onViewImproved,
    required this.onDiscardImprovement,
    this.improving = false,
    this.busy = false,
  });

  /// Icone que deixa o formato reconhecivel de relance na lista.
  IconData get _icone {
    switch (material.sourceType) {
      case 'pdf':
      case 'pdf-ocr':
        return Icons.picture_as_pdf_outlined;
      case 'pptx':
        return Icons.slideshow_outlined;
      case 'docx':
        return Icons.description_outlined;
      case 'image-ocr':
        return Icons.image_outlined;
      default:
        return Icons.notes_outlined;
    }
  }

  @override
  Widget build(BuildContext context) {
    // O material passou a ser nomeado pelo titulo de dentro do documento. Sem
    // o arquivo aqui, nao da mais para saber qual dos tres PDFs da pasta virou
    // "Modelagem Conceitual de Dados".
    final arquivo = material.filename;
    final detalhes = [
      if (material.discipline.isNotEmpty) material.discipline,
      if (arquivo.isNotEmpty && arquivo != material.title) arquivo,
      '${material.pageCount} ${material.unitLabel}',
      '${(material.charCount / 1000).toStringAsFixed(0)} mil caracteres',
      // OCR erra, e o quiz sai do texto: quem revisa precisa saber que a fonte
      // foi uma imagem reconhecida, e nao um arquivo lido.
      if (material.fromOcr) 'lido por OCR',
      if (material.truncated) 'texto cortado no limite',
      if (material.improved)
        'melhorado por ${AppConfig.serviceLabel(material.improvedLlm)}',
    ].join('  ·  ');

    return Row(
      children: [
        Icon(
          _icone,
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
        if (improving)
          const Padding(
            padding: EdgeInsets.all(12),
            child: SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          )
        else
          IconButton(
            tooltip: 'Melhorar texto com IA',
            icon: const Icon(Icons.auto_fix_high, size: 16),
            color: AssistantTheme.textMuted,
            onPressed: busy ? null : onImprove,
          ),
        if (material.improved) ...[
          IconButton(
            tooltip: 'Ver texto melhorado',
            icon: const Icon(Icons.visibility_outlined, size: 16),
            color: AssistantTheme.textMuted,
            onPressed: onViewImproved,
          ),
          IconButton(
            tooltip: 'Voltar ao texto original',
            icon: const Icon(Icons.undo, size: 16),
            color: AssistantTheme.textMuted,
            onPressed: busy ? null : onDiscardImprovement,
          ),
        ],
        IconButton(
          tooltip: 'Renomear material',
          icon: const Icon(Icons.edit_outlined, size: 16),
          color: AssistantTheme.textMuted,
          onPressed: onRename,
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

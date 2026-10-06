/// Material das apresentações: link para os alunos enviarem, o que chegou de cada
/// grupo e o quiz rápido feito com esse material e a gravação da apresentação.
///
/// O aluno abre o link, digita a matrícula e envia o PDF/PPTX do grupo; aqui o
/// professor vê quem já mandou, liga uma gravação ao grupo e gera o quiz rápido para
/// os outros grupos (o que apresentou fica de fora).
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../models/group_class.dart';
import '../models/presentation_material.dart';
import '../services/education_service.dart';
import '../services/quiz_center_service.dart';
import '../utils/theme.dart';

Future<void> showPresentationMaterialDialog(
  BuildContext context, {
  required Discipline discipline,
  List<ClassGroup> classes = const [],
  Set<String> classFilter = const {},
  VoidCallback? onQuizQueued,
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: const EdgeInsets.all(20),
      child: PresentationMaterialPanel(
        discipline: discipline,
        classes: classes,
        classFilter: classFilter,
        onQuizQueued: onQuizQueued,
      ),
    ),
  );
}

String _when(DateTime? value) {
  if (value == null) return '';
  final local = value.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}/${two(local.month)} ${two(local.hour)}:${two(local.minute)}';
}

class PresentationMaterialPanel extends StatefulWidget {
  final Discipline discipline;

  /// Turmas da disciplina, para o link por turmas e os rótulos do painel.
  final List<ClassGroup> classes;

  /// Turmas marcadas na tela de grupos; vazio mostra todos os grupos.
  final Set<String> classFilter;
  final VoidCallback? onQuizQueued;

  /// Trocam os serviços nos testes.
  final EducationService? service;
  final QuizCenterService? quizService;

  /// Endereço do servidor que o aluno abre; por padrão o do app.
  final String? baseUrl;

  const PresentationMaterialPanel({
    super.key,
    required this.discipline,
    this.classes = const [],
    this.classFilter = const {},
    this.onQuizQueued,
    this.service,
    this.quizService,
    this.baseUrl,
  });

  @override
  State<PresentationMaterialPanel> createState() =>
      _PresentationMaterialPanelState();
}

class _PresentationMaterialPanelState extends State<PresentationMaterialPanel> {
  EducationService get _service => widget.service ?? education;
  QuizCenterService get _quiz => widget.quizService ?? quizCenter;
  String get _baseUrl => widget.baseUrl ?? _service.publicBaseUrl;

  List<MaterialLink> _links = const [];
  List<PresentationRow> _rows = const [];
  bool _loading = true;
  bool _busy = false;
  bool _error = false;
  String _message = '';

  // formulário do link novo
  final _title = TextEditingController(text: 'Material da apresentação');
  final Set<String> _newClassIds = {};
  DateTime? _deadline;

  List<ClassGroup> get _turmas =>
      classesOfDiscipline(widget.classes, widget.discipline.id);

  @override
  void initState() {
    super.initState();
    _newClassIds.addAll(widget.classFilter.where((id) => id != noClassFilter));
    _load();
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  String _errorText(Object error) => error is EducationException
      ? error.message
      : '$error'.replaceFirst('Exception: ', '');

  void _report(String text, {bool error = false}) {
    if (!mounted) return;
    setState(() {
      _message = text;
      _error = error;
    });
  }

  Future<void> _load() async {
    try {
      final links =
          await _service.listMaterialLinks(disciplineId: widget.discipline.id);
      final rows = await _service.listPresentations(widget.discipline.id);
      if (!mounted) return;
      setState(() {
        _links = links;
        _rows = rows;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      _report('Falha ao carregar: ${_errorText(e)}', error: true);
    }
  }

  Future<void> _run(Future<void> Function() action, {String done = ''}) async {
    setState(() => _busy = true);
    try {
      await action();
      await _load();
      if (done.isNotEmpty) _report(done);
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Os grupos que aparecem: os das turmas marcadas na tela, ou todos.
  List<PresentationRow> get _visibleRows {
    final filter = widget.classFilter.where((id) => id != noClassFilter).toSet();
    if (filter.isEmpty) return _rows;
    return _rows
        .where((row) => row.classIds.any(filter.contains))
        .toList();
  }

  // --- link ----------------------------------------------------------------

  Future<void> _createLink() async {
    await _run(
      () async {
        await _service.createMaterialLink(
          disciplineId: widget.discipline.id,
          title: _title.text.trim(),
          classIds: (_newClassIds.toList()..sort()),
          closesAt: _deadline,
        );
      },
      done: 'Link criado. Copie e mande para a turma, ou mostre o QR Code.',
    );
  }

  Future<void> _pickDeadline() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _deadline ?? now.add(const Duration(days: 7)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 365)),
      helpText: 'Último dia para enviar',
    );
    if (picked == null || !mounted) return;
    // O prazo vale até o fim do dia escolhido.
    setState(() =>
        _deadline = DateTime(picked.year, picked.month, picked.day, 23, 59));
  }

  Future<void> _copy(MaterialLink link) async {
    await Clipboard.setData(ClipboardData(text: link.url(_baseUrl)));
    _report('Link copiado.');
  }

  Future<void> _showQr(MaterialLink link) {
    final url = link.url(_baseUrl);
    return showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(link.title.isEmpty ? 'Material da apresentação' : link.title),
        content: SizedBox(
          width: 320,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                color: Colors.white,
                padding: const EdgeInsets.all(12),
                child: QrImageView(
                  key: const ValueKey('material-qr'),
                  data: url,
                  version: QrVersions.auto,
                  size: 280,
                ),
              ),
              const SizedBox(height: 8),
              SelectableText(url, style: const TextStyle(fontSize: 12)),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Fechar'),
          ),
        ],
      ),
    );
  }

  Widget _linkCard(MaterialLink link) {
    final url = link.url(_baseUrl);
    final color = link.isOpen ? AssistantTheme.c3 : AssistantTheme.textMuted;
    return Container(
      key: ValueKey('link-${link.id}'),
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  link.title.isEmpty ? 'Material da apresentação' : link.title,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
              ),
              Text(link.stateLabel.toUpperCase(),
                  key: ValueKey('estado-${link.id}'),
                  style: TextStyle(fontSize: 10, letterSpacing: 1.2, color: color)),
            ],
          ),
          if (link.classLabel.isNotEmpty)
            Text('Turmas: ${link.classLabel}',
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textMuted)),
          Text(link.progressLabel,
              style: const TextStyle(fontSize: 12)),
          if (link.closesAt != null)
            Text('Prazo: ${_when(link.closesAt)}',
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textMuted)),
          const SizedBox(height: 6),
          SelectableText(url, style: const TextStyle(fontSize: 12)),
          if (isLocalAddress(_baseUrl))
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text(
                'Este endereço só abre neste computador. Os alunos precisam do '
                'endereço público do servidor (Configurações).',
                key: ValueKey('aviso-endereco-local'),
                style: TextStyle(fontSize: 11, color: AssistantTheme.danger),
              ),
            ),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 4, children: [
            OutlinedButton.icon(
              key: ValueKey('copiar-${link.id}'),
              onPressed: _busy ? null : () => _copy(link),
              icon: const Icon(Icons.copy, size: 16),
              label: const Text('Copiar link'),
            ),
            OutlinedButton.icon(
              key: ValueKey('qr-${link.id}'),
              onPressed: _busy ? null : () => _showQr(link),
              icon: const Icon(Icons.qr_code_2, size: 16),
              label: const Text('QR Code'),
            ),
            OutlinedButton.icon(
              key: ValueKey('alternar-${link.id}'),
              onPressed: _busy
                  ? null
                  : () => _run(
                        () => _service
                            .updateMaterialLink(link.id,
                                active: !link.isOpen || link.state == 'expired',
                                clearDeadline: link.state == 'expired')
                            .then((_) {}),
                        done: link.isOpen
                            ? 'Recebimento encerrado.'
                            : 'Recebimento reaberto.',
                      ),
              icon: Icon(link.isOpen ? Icons.lock_outline : Icons.lock_open,
                  size: 16),
              label: Text(link.isOpen ? 'Fechar' : 'Reabrir'),
            ),
            TextButton.icon(
              key: ValueKey('apagar-${link.id}'),
              onPressed: _busy
                  ? null
                  : () => _run(() => _service.deleteMaterialLink(link.id),
                      done: 'Link apagado. O que já foi enviado continua.'),
              icon: const Icon(Icons.delete_outline, size: 16),
              label: const Text('Apagar'),
            ),
          ]),
        ],
      ),
    );
  }

  Widget _newLinkForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Crie um link para os alunos enviarem o PDF ou PPTX da apresentação. '
          'Eles digitam a matrícula, o sistema acha o grupo e o material fica '
          'ligado a ele.',
          style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 8),
        TextField(
          key: const ValueKey('titulo-link'),
          controller: _title,
          decoration: const InputDecoration(labelText: 'Nome do link'),
        ),
        if (_turmas.isNotEmpty) ...[
          const SizedBox(height: 8),
          const Text('TURMAS (nenhuma marcada = a disciplina toda)',
              style: TextStyle(
                  fontSize: 9, letterSpacing: 1.5, color: AssistantTheme.textMuted)),
          Wrap(spacing: 8, children: [
            for (final turma in _turmas)
              FilterChip(
                key: ValueKey('novo-turma-${turma.id}'),
                label: Text(classDisplay(turma),
                    style: const TextStyle(fontSize: 11)),
                selected: _newClassIds.contains(turma.id),
                onSelected: (value) => setState(() => value
                    ? _newClassIds.add(turma.id)
                    : _newClassIds.remove(turma.id)),
              ),
          ]),
        ],
        const SizedBox(height: 8),
        Row(children: [
          OutlinedButton.icon(
            key: const ValueKey('escolher-prazo'),
            onPressed: _busy ? null : _pickDeadline,
            icon: const Icon(Icons.event, size: 16),
            label: Text(_deadline == null
                ? 'Sem prazo'
                : 'Até ${_when(_deadline).split(' ').first}'),
          ),
          if (_deadline != null)
            IconButton(
              tooltip: 'Tirar o prazo',
              onPressed: () => setState(() => _deadline = null),
              icon: const Icon(Icons.close, size: 16),
            ),
          const Spacer(),
          FilledButton.icon(
            key: const ValueKey('criar-link'),
            onPressed: _busy ? null : _createLink,
            icon: const Icon(Icons.add_link, size: 16),
            label: const Text('CRIAR LINK'),
          ),
        ]),
      ],
    );
  }

  // --- grupos --------------------------------------------------------------

  Future<void> _linkMaterial(PresentationRow row) async {
    final all = await _service.listMaterials(disciplineId: widget.discipline.id);
    final free = all.where((item) => item.groupId.isEmpty).toList();
    if (!mounted) return;
    if (free.isEmpty) {
      _report('Não há material solto nesta disciplina. Envie o arquivo pela aba '
          'Material ou use o link.');
      return;
    }
    final picked = await showDialog<CourseMaterial>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: Text('Ligar material ao ${row.groupName}'),
        children: [
          for (final item in free)
            SimpleDialogOption(
              key: ValueKey('ligar-material-${item.id}'),
              onPressed: () => Navigator.pop(dialogContext, item),
              child: Text(
                '${item.title.isEmpty ? item.filename : item.title} · ${item.sourceType.toUpperCase()}',
              ),
            ),
        ],
      ),
    );
    if (picked == null) return;
    await _run(
      () async {
        await _service.assignMaterialToGroup(picked.id, row.groupId);
      },
      done: 'Material ligado ao ${row.groupName}.',
    );
  }

  Future<void> _linkRecording(PresentationRow row) async {
    final lessons = <Lesson>[];
    for (final kind in const ['apresentacao', 'palestra']) {
      lessons.addAll(await _service.listLessons(kind: kind, limit: 100));
    }
    final free = lessons.where((item) => item.groupId.isEmpty).toList()
      ..sort((a, b) => (b.startedAt ?? DateTime(0))
          .compareTo(a.startedAt ?? DateTime(0)));
    if (!mounted) return;
    if (free.isEmpty) {
      _report('Não há gravação de palestra ou apresentação sem grupo.');
      return;
    }
    final picked = await showDialog<Lesson>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: Text('Ligar gravação ao ${row.groupName}'),
        children: [
          for (final item in free)
            SimpleDialogOption(
              key: ValueKey('ligar-gravacao-${item.id}'),
              onPressed: () => Navigator.pop(dialogContext, item),
              child: Text(
                '${_when(item.startedAt)} · ${item.title.isEmpty ? 'sem título' : item.title}'
                ' · ${item.segmentCount} trechos',
              ),
            ),
        ],
      ),
    );
    if (picked == null) return;
    await _run(
      () => _service.assignLessonToGroup(picked.id, row.groupId),
      done: 'Gravação ligada ao ${row.groupName}.',
    );
  }

  Future<void> _quickQuiz(PresentationRow row) async {
    final request = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _QuickQuizDialog(
        row: row,
        disciplineId: widget.discipline.id,
        classes: widget.classes,
      ),
    );
    if (request == null) return;
    setState(() => _busy = true);
    try {
      await _quiz.enqueue(request);
      widget.onQuizQueued?.call();
      _report('Gerando o quiz rápido do ${row.groupName}. Quando ficar pronto, '
          'revise as perguntas na Central de quizzes e libere o QR Code.');
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _chip(String text, bool ok, {Key? key}) => Container(
        key: key,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          border: Border.all(
              color: ok ? AssistantTheme.c3 : AssistantTheme.textMuted),
          borderRadius: BorderRadius.circular(3),
        ),
        child: Text(text,
            style: TextStyle(
                fontSize: 11,
                color: ok ? AssistantTheme.c3 : AssistantTheme.textMuted)),
      );

  Widget _rowCard(PresentationRow row) {
    return Container(
      key: ValueKey('grupo-${row.groupId}'),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(
              child: Text(row.groupName,
                  style: const TextStyle(fontWeight: FontWeight.bold)),
            ),
            _chip(
              row.hasMaterial ? 'material ✓' : 'sem material',
              row.hasMaterial,
              key: ValueKey('chip-material-${row.groupId}'),
            ),
            const SizedBox(width: 6),
            _chip(
              row.hasRecording ? 'gravação ✓' : 'sem gravação',
              row.hasRecording,
              key: ValueKey('chip-gravacao-${row.groupId}'),
            ),
          ]),
          Text(row.statusLabel,
              style: const TextStyle(
                  fontSize: 11, color: AssistantTheme.textMuted)),
          for (final file in row.materials)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(children: [
                const Icon(Icons.slideshow, size: 14),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    '${file.title} · ${file.sizeLabel}'
                    '${file.uploaderName.isEmpty ? '' : ' · ${file.uploaderName}'}'
                    '${file.createdAt == null ? '' : ' · ${_when(file.createdAt)}'}'
                    '${file.truncated ? ' · texto cortado' : ''}',
                    style: const TextStyle(fontSize: 12),
                  ),
                ),
                IconButton(
                  key: ValueKey('soltar-material-${file.id}'),
                  tooltip: 'Soltar do grupo',
                  visualDensity: VisualDensity.compact,
                  onPressed: _busy
                      ? null
                      : () => _run(
                            () async {
                              await _service.assignMaterialToGroup(file.id, null);
                            },
                            done: 'Material solto do ${row.groupName}.',
                          ),
                  icon: const Icon(Icons.link_off, size: 16),
                ),
              ]),
            ),
          for (final rec in row.recordings)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(children: [
                const Icon(Icons.mic_none, size: 14),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    '${rec.title.isEmpty ? 'Gravação' : rec.title} · '
                    '${_when(rec.startedAt)} · ${rec.segments} trechos'
                    '${rec.usable ? '' : ' (sem transcrição)'}',
                    style: const TextStyle(fontSize: 12),
                  ),
                ),
              ]),
            ),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 4, children: [
            OutlinedButton.icon(
              key: ValueKey('ligar-material-${row.groupId}'),
              onPressed: _busy ? null : () => _linkMaterial(row),
              icon: const Icon(Icons.attach_file, size: 16),
              label: const Text('Ligar material'),
            ),
            OutlinedButton.icon(
              key: ValueKey('ligar-gravacao-${row.groupId}'),
              onPressed: _busy ? null : () => _linkRecording(row),
              icon: const Icon(Icons.mic, size: 16),
              label: const Text('Ligar gravação'),
            ),
            FilledButton.icon(
              key: ValueKey('quiz-rapido-${row.groupId}'),
              onPressed: _busy || !row.canQuiz ? null : () => _quickQuiz(row),
              icon: const Icon(Icons.bolt, size: 16),
              label: const Text('QUIZ RÁPIDO'),
            ),
          ]),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final rows = _visibleRows;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 880, maxHeight: 760),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: _loading
            ? const SizedBox(
                height: 160, child: Center(child: CircularProgressIndicator()))
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    const Expanded(
                      child: Text('MATERIAL DAS APRESENTAÇÕES',
                          style: TextStyle(
                              fontWeight: FontWeight.bold, letterSpacing: 1.5)),
                    ),
                    IconButton(
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close),
                    ),
                  ]),
                  Text(widget.discipline.label,
                      style: const TextStyle(
                          fontSize: 12, color: AssistantTheme.textMuted)),
                  if (_message.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(_message,
                          key: const ValueKey('mensagem'),
                          style: TextStyle(
                              fontSize: 12,
                              color: _error
                                  ? AssistantTheme.danger
                                  : AssistantTheme.c3)),
                    ),
                  const SizedBox(height: 10),
                  Expanded(
                    child: ListView(children: [
                      const Text('LINK PARA OS ALUNOS',
                          style: TextStyle(
                              fontSize: 10,
                              letterSpacing: 1.5,
                              color: AssistantTheme.textMuted)),
                      const SizedBox(height: 6),
                      for (final link in _links) _linkCard(link),
                      _newLinkForm(),
                      const SizedBox(height: 18),
                      Text(
                          'GRUPOS (${rows.length}${rows.length != _rows.length ? ' de ${_rows.length}' : ''})',
                          style: const TextStyle(
                              fontSize: 10,
                              letterSpacing: 1.5,
                              color: AssistantTheme.textMuted)),
                      const SizedBox(height: 6),
                      if (rows.isEmpty)
                        const Text(
                          'Nenhum grupo cadastrado para esta seleção. Cadastre os '
                          'grupos na lista de grupos de projeto.',
                          style: TextStyle(color: AssistantTheme.textMuted),
                        ),
                      for (final row in rows) _rowCard(row),
                    ]),
                  ),
                ],
              ),
      ),
    );
  }
}

/// Escolhe as fontes e o formato do quiz rápido; devolve o pedido para a fila.
class _QuickQuizDialog extends StatefulWidget {
  final PresentationRow row;
  final String disciplineId;
  final List<ClassGroup> classes;

  const _QuickQuizDialog({
    required this.row,
    required this.disciplineId,
    required this.classes,
  });

  @override
  State<_QuickQuizDialog> createState() => _QuickQuizDialogState();
}

class _QuickQuizDialogState extends State<_QuickQuizDialog> {
  late final Set<String> _materials = {
    for (final item in widget.row.materials) item.id,
  };
  late final Set<String> _lessons = {
    for (final item in widget.row.recordings)
      if (item.usable) item.id,
  };
  int _questions = 8;
  String _mode = 'media';

  String get _turmasLabel {
    final labels = [
      for (final turma in widget.classes)
        if (widget.row.classIds.contains(turma.id)) classDisplay(turma),
    ];
    return labels.isEmpty ? 'todas as turmas da disciplina' : labels.join(' + ');
  }

  @override
  Widget build(BuildContext context) {
    final sources = QuickQuizSources(materialIds: _materials, lessonIds: _lessons);
    return AlertDialog(
      title: Text('Quiz rápido · ${widget.row.groupName}'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Fontes do quiz',
                  style: TextStyle(fontWeight: FontWeight.bold)),
              for (final file in widget.row.materials)
                CheckboxListTile(
                  key: ValueKey('fonte-material-${file.id}'),
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text('${file.title} · ${file.sizeLabel}'),
                  value: _materials.contains(file.id),
                  onChanged: (value) => setState(() => value == true
                      ? _materials.add(file.id)
                      : _materials.remove(file.id)),
                ),
              for (final rec in widget.row.recordings)
                CheckboxListTile(
                  key: ValueKey('fonte-gravacao-${rec.id}'),
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text(
                      'Gravação: ${rec.title.isEmpty ? 'apresentação' : rec.title}'
                      '${rec.usable ? '' : ' (sem transcrição)'}'),
                  value: _lessons.contains(rec.id),
                  onChanged: rec.usable
                      ? (value) => setState(() => value == true
                          ? _lessons.add(rec.id)
                          : _lessons.remove(rec.id))
                      : null,
                ),
              if (widget.row.gaps.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    'Faltou ${widget.row.gaps.join(' e ')}: o quiz usa só o que '
                    'existe.',
                    key: const ValueKey('aviso-falta'),
                    style: const TextStyle(
                        fontSize: 11, color: AssistantTheme.textMuted),
                  ),
                ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                key: const ValueKey('quantidade'),
                value: _questions,
                decoration:
                    const InputDecoration(labelText: 'Quantidade de perguntas'),
                items: [
                  for (final n in const [5, 8, 10, 15])
                    DropdownMenuItem(value: n, child: Text('$n perguntas')),
                ],
                onChanged: (value) => setState(() => _questions = value ?? 8),
              ),
              const SizedBox(height: 12),
              SegmentedButton<String>(
                key: const ValueKey('modo'),
                segments: const [
                  ButtonSegment(value: 'media', label: Text('Média do grupo')),
                  ButtonSegment(
                      value: 'representante', label: Text('Só o representante')),
                ],
                selected: {_mode},
                onSelectionChanged: (value) =>
                    setState(() => _mode = value.first),
              ),
              const SizedBox(height: 12),
              Text(
                'Jogam os grupos de $_turmasLabel. O ${widget.row.groupName} '
                'apresentou e fica de fora. Você revisa as perguntas antes de '
                'liberar o QR Code.',
                key: const ValueKey('resumo-quem-joga'),
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textMuted),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: const ValueKey('gerar-quiz'),
          onPressed: sources.isEmpty
              ? null
              : () => Navigator.pop(
                    context,
                    buildQuickQuizRequest(
                      group: widget.row,
                      disciplineId: widget.disciplineId,
                      sources: sources,
                      questions: _questions,
                      mode: _mode,
                    ),
                  ),
          child: const Text('GERAR QUIZ'),
        ),
      ],
    );
  }
}

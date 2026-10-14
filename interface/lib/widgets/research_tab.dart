/// Pesquisas científicas: cadastrar a pesquisa, deixar a IA propor o plano de etapas,
/// ligar os participantes (alunos ou pessoas de fora) e acompanhar prazos e andamento.
///
/// A IA só propõe: as etapas voltam editáveis e nada é gravado até o professor criar a
/// pesquisa. Se a IA não responder, entram etapas padrão sem prazo.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../models/research.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

class ResearchTab extends StatefulWidget {
  /// Trocam serviço nos testes.
  final EducationService? service;

  /// De quanto em quanto tempo a tela se atualiza sozinha. Zero desliga (testes).
  final Duration pollEvery;

  const ResearchTab({
    super.key,
    this.service,
    this.pollEvery = const Duration(seconds: 30),
  });

  @override
  State<ResearchTab> createState() => _ResearchTabState();
}

class _ResearchTabState extends State<ResearchTab> {
  EducationService get _service => widget.service ?? education;

  // criação
  final _title = TextEditingController();
  final _description = TextEditingController();
  final _area = TextEditingController();
  int _weeks = 24;
  DateTime? _start;
  List<StageDraft> _draft = [];
  bool _creating = false;
  bool _generated = false;

  // lista e detalhe
  List<ResearchProject> _projects = const [];
  String? _selectedId;
  ResearchDetail? _detail;
  bool _loading = true;
  bool _busy = false;
  String _message = '';
  bool _error = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    if (widget.pollEvery > Duration.zero) {
      _timer = Timer.periodic(widget.pollEvery, (_) => _refresh());
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _title.dispose();
    _description.dispose();
    _area.dispose();
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
      final projects = await _service.listResearch();
      if (!mounted) return;
      setState(() {
        _projects = projects;
        _loading = false;
        if (_selectedId == null || !projects.any((p) => p.id == _selectedId)) {
          _selectedId = projects.isEmpty ? null : projects.first.id;
        }
      });
      await _loadDetail();
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      _report('Falha ao carregar: ${_errorText(e)}', error: true);
    }
  }

  Future<void> _loadDetail() async {
    final id = _selectedId;
    if (id == null) {
      if (mounted) setState(() => _detail = null);
      return;
    }
    try {
      final detail = await _service.getResearch(id);
      if (mounted && _selectedId == id) setState(() => _detail = detail);
    } catch (e) {
      _report('Falha ao abrir a pesquisa: ${_errorText(e)}', error: true);
    }
  }

  /// Atualização silenciosa: não mexe na mensagem e fica quieta se a rede falhar.
  Future<void> _refresh() async {
    if (!mounted || _busy || _loading || _creating) return;
    try {
      final projects = await _service.listResearch();
      if (!mounted) return;
      setState(() => _projects = projects);
      final id = _selectedId;
      if (id != null && projects.any((p) => p.id == id)) {
        final detail = await _service.getResearch(id);
        if (mounted && _selectedId == id && !_busy) setState(() => _detail = detail);
      }
    } catch (_) {}
  }

  Future<void> _guard(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reload() async {
    final projects = await _service.listResearch();
    if (mounted) setState(() => _projects = projects);
    await _loadDetail();
  }

  // --- criação ----------------------------------------------------------------------

  void _startCreating() {
    setState(() {
      _creating = true;
      _generated = false;
      _draft = [];
      _title.clear();
      _description.clear();
      _area.clear();
      _weeks = 24;
      _start = null;
    });
  }

  Future<void> _generate() => _guard(() async {
        final title = _title.text.trim();
        if (title.isEmpty) {
          _report('Dê um título à pesquisa para a IA montar o plano.', error: true);
          return;
        }
        final result = await _service.generateResearchPlan(
          title: title,
          description: _description.text.trim(),
          weeks: _weeks,
          startDate: _start,
        );
        if (!mounted) return;
        setState(() {
          _draft = result.stages;
          _generated = true;
        });
        _report(result.fromAi
            ? 'A IA montou ${result.stages.length} etapas. Ajuste o que quiser antes de criar.'
            : 'A IA não respondeu; usei as etapas padrão, sem prazo. Ajuste antes de criar.');
      });

  Future<void> _create() => _guard(() async {
        final title = _title.text.trim();
        if (title.isEmpty) {
          _report('Dê um título à pesquisa.', error: true);
          return;
        }
        final project = await _service.createResearch(
          title: title,
          description: _description.text.trim(),
          area: _area.text.trim(),
          startDate: _start,
          stages: [for (final s in _draft) if (s.title.trim().isNotEmpty) s],
        );
        if (!mounted) return;
        setState(() {
          _projects = [project, ..._projects];
          _selectedId = project.id;
          _creating = false;
        });
        await _loadDetail();
        _report('Pesquisa criada. Adicione os participantes.');
      });

  Future<DateTime?> _pickDate(DateTime? initial) async {
    final now = DateTime.now();
    return showDatePicker(
      context: context,
      initialDate: initial ?? now,
      firstDate: DateTime(now.year - 2),
      lastDate: DateTime(now.year + 6),
    );
  }

  // --- pesquisa selecionada ---------------------------------------------------------

  Future<void> _setStatus(ResearchProject project, String status) => _guard(() async {
        await _service.updateResearch(project.id, {'status': status});
        await _reload();
      });

  Future<void> _delete(ResearchProject project) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Apagar pesquisa?'),
        content: Text('“${project.title}”, as etapas e os participantes serão apagados.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Apagar')),
        ],
      ),
    );
    if (confirmed != true) return;
    await _guard(() async {
      await _service.deleteResearch(project.id);
      if (!mounted) return;
      setState(() {
        _projects = [for (final p in _projects) if (p.id != project.id) p];
        _selectedId = _projects.isEmpty ? null : _projects.first.id;
        _detail = null;
      });
      await _loadDetail();
      _report('Pesquisa apagada.');
    });
  }

  Future<void> _addParticipant(ResearchProject project) async {
    final name = TextEditingController();
    final enrollment = TextEditingController();
    final email = TextEditingController();
    final phone = TextEditingController();
    final institution = TextEditingController();
    var role = 'orientando';
    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: const Text('Adicionar participante'),
          content: SizedBox(
            width: 440,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                    key: const Key('participant-name'),
                    controller: name,
                    decoration: const InputDecoration(labelText: 'NOME', isDense: true)),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: role,
                  decoration: const InputDecoration(labelText: 'PAPEL', isDense: true),
                  items: [
                    for (final e in researchRoles.entries)
                      DropdownMenuItem(value: e.key, child: Text(e.value)),
                  ],
                  onChanged: (value) => setDialogState(() => role = value ?? role),
                ),
                const SizedBox(height: 8),
                TextField(
                    key: const Key('participant-enrollment'),
                    controller: enrollment,
                    decoration: const InputDecoration(
                        labelText: 'MATRÍCULA (SE FOR ALUNO)', isDense: true)),
                const SizedBox(height: 8),
                TextField(
                    controller: email,
                    decoration: const InputDecoration(labelText: 'E-MAIL', isDense: true)),
                const SizedBox(height: 8),
                TextField(
                    controller: phone,
                    decoration: const InputDecoration(labelText: 'TELEFONE', isDense: true)),
                const SizedBox(height: 8),
                TextField(
                    controller: institution,
                    decoration: const InputDecoration(
                        labelText: 'INSTITUIÇÃO (SE FOR DE FORA)', isDense: true)),
              ]),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('CANCELAR')),
            FilledButton(
                key: const Key('participant-save'),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('ADICIONAR')),
          ],
        ),
      ),
    );
    final values = (
      name.text.trim(), role, enrollment.text.trim(), email.text.trim(),
      phone.text.trim(), institution.text.trim(),
    );
    // Sem dispose: a animação de fechar do diálogo ainda desenha estes campos.
    if (saved != true) return;
    if (values.$1.isEmpty) {
      _report('Informe o nome do participante.', error: true);
      return;
    }
    await _guard(() async {
      await _service.addResearchParticipant(project.id,
          name: values.$1, role: values.$2, enrollment: values.$3, email: values.$4,
          phone: values.$5, institution: values.$6);
      await _reload();
      _report('Participante adicionado.');
    });
  }

  Future<void> _removeParticipant(ResearchParticipant person) => _guard(() async {
        await _service.removeResearchParticipant(person.id);
        await _reload();
        _report('${person.name} saiu da pesquisa.');
      });

  Future<void> _editStage(ResearchProject project, [ResearchStage? current]) async {
    final title = TextEditingController(text: current?.title ?? '');
    final description = TextEditingController(text: current?.description ?? '');
    DateTime? due = current?.dueAt;
    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text(current == null ? 'Nova etapa' : 'Editar etapa'),
          content: SizedBox(
            width: 440,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                    key: const Key('stage-title'),
                    controller: title,
                    decoration: const InputDecoration(labelText: 'TÍTULO', isDense: true)),
                const SizedBox(height: 8),
                TextField(
                    controller: description,
                    minLines: 2,
                    maxLines: 5,
                    decoration: const InputDecoration(
                        labelText: 'O QUE FAZER', isDense: true, alignLabelWithHint: true)),
                const SizedBox(height: 8),
                Row(children: [
                  OutlinedButton.icon(
                    onPressed: () async {
                      final picked = await showDatePicker(
                        context: dialogContext,
                        initialDate: due ?? DateTime.now(),
                        firstDate: DateTime(DateTime.now().year - 2),
                        lastDate: DateTime(DateTime.now().year + 6),
                      );
                      if (picked != null) setDialogState(() => due = picked);
                    },
                    icon: const Icon(Icons.event, size: 16),
                    label: Text(due == null ? 'PRAZO (OPCIONAL)' : _date(due!)),
                  ),
                  if (due != null)
                    IconButton(
                        tooltip: 'Tirar o prazo',
                        onPressed: () => setDialogState(() => due = null),
                        icon: const Icon(Icons.close, size: 16)),
                ]),
              ]),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('CANCELAR')),
            FilledButton(
                key: const Key('stage-save'),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('SALVAR')),
          ],
        ),
      ),
    );
    final name = title.text.trim();
    final text = description.text.trim();
    if (saved != true) return;
    if (name.isEmpty) {
      _report('Dê um título à etapa.', error: true);
      return;
    }
    await _guard(() async {
      if (current == null) {
        await _service.addResearchStage(project.id,
            title: name, description: text, dueAt: due);
      } else {
        await _service.updateResearchStage(current.id, {
          'title': name,
          'description': text,
          if (due == null) 'clear_due': true else 'due_at': _endOfDay(due!),
        });
      }
      await _reload();
    });
  }

  String _endOfDay(DateTime day) =>
      DateTime(day.year, day.month, day.day, 23, 59).toUtc().toIso8601String();

  Future<void> _cycleStage(ResearchStage stage) => _guard(() async {
        const next = {'todo': 'doing', 'doing': 'done', 'done': 'todo'};
        await _service.updateResearchStage(stage.id, {'status': next[stage.status]});
        await _reload();
      });

  Future<void> _deleteStage(ResearchStage stage) => _guard(() async {
        await _service.deleteResearchStage(stage.id);
        await _reload();
      });

  // --- tela -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    final detail = _detail;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        Row(children: [
          const Icon(Icons.biotech_outlined, color: AssistantTheme.c3),
          const SizedBox(width: 8),
          const Expanded(
            child: Text('PESQUISAS CIENTÍFICAS',
                style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.6)),
          ),
          if (!_creating)
            FilledButton.icon(
              key: const Key('research-new'),
              onPressed: _startCreating,
              icon: const Icon(Icons.add, size: 16),
              label: const Text('NOVA PESQUISA'),
            ),
        ]),
        if (_message.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_message,
                style: TextStyle(
                    fontSize: 12, color: _error ? Colors.redAccent : AssistantTheme.c3)),
          ),
        const SizedBox(height: 10),
        if (_creating) _buildCreator(),
        if (!_creating && _projects.isEmpty)
          const _Hint('Nenhuma pesquisa ainda. Clique em NOVA PESQUISA, descreva o tema e '
              'a IA propõe as etapas.'),
        if (_projects.length > 1)
          Wrap(spacing: 8, runSpacing: 6, children: [
            for (final p in _projects)
              ChoiceChip(
                label: Text(p.title),
                selected: p.id == _selectedId,
                onSelected: (_) {
                  setState(() {
                    _selectedId = p.id;
                    _detail = null;
                  });
                  _loadDetail();
                },
              ),
          ]),
        if (detail != null) ...[
          const SizedBox(height: 12),
          _buildProject(detail),
          const SizedBox(height: 12),
          _buildParticipants(detail),
          const SizedBox(height: 12),
          _buildStages(detail),
        ],
      ],
    );
  }

  Widget _buildCreator() {
    return _Panel(
      title: 'NOVA PESQUISA',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        TextField(
          key: const Key('research-title'),
          controller: _title,
          decoration: const InputDecoration(labelText: 'TÍTULO DA PESQUISA', isDense: true),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key('research-description'),
          controller: _description,
          minLines: 3,
          maxLines: 6,
          decoration: const InputDecoration(
            labelText: 'TEMA E OBJETIVO (A IA USA ISTO PARA PROPOR AS ETAPAS)',
            isDense: true,
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 10),
        Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
            children: [
          SizedBox(
            width: 220,
            child: TextField(
              controller: _area,
              decoration: const InputDecoration(labelText: 'ÁREA', isDense: true),
            ),
          ),
          SizedBox(
            width: 210,
            child: DropdownButtonFormField<int>(
              key: const Key('research-weeks'),
              isExpanded: true,
              initialValue: _weeks,
              decoration: const InputDecoration(labelText: 'DURAÇÃO', isDense: true),
              items: [
                for (final w in const [8, 12, 24, 36, 52])
                  DropdownMenuItem(value: w, child: Text('$w semanas')),
              ],
              onChanged: (value) => setState(() => _weeks = value ?? _weeks),
            ),
          ),
          OutlinedButton.icon(
            onPressed: () async {
              final picked = await _pickDate(_start);
              if (picked != null) setState(() => _start = picked);
            },
            icon: const Icon(Icons.event, size: 16),
            label: Text(_start == null ? 'INÍCIO (HOJE)' : 'INÍCIO ${_date(_start!)}'),
          ),
        ]),
        const SizedBox(height: 12),
        FilledButton.icon(
          key: const Key('research-generate'),
          onPressed: _busy ? null : _generate,
          icon: const Icon(Icons.auto_awesome, size: 16),
          label: Text(_generated ? 'GERAR O PLANO DE NOVO' : 'GERAR PLANO COM IA'),
        ),
        if (_draft.isNotEmpty || _generated) ...[
          const SizedBox(height: 12),
          const _Hint('Etapas propostas. Edite, apague ou acrescente antes de criar.'),
          for (var i = 0; i < _draft.length; i++) _buildDraftRow(i),
          TextButton.icon(
            onPressed: () => setState(() => _draft.add(StageDraft(title: ''))),
            icon: const Icon(Icons.add, size: 16),
            label: const Text('ADICIONAR ETAPA'),
          ),
        ],
        const Divider(),
        Row(children: [
          FilledButton.icon(
            key: const Key('research-create'),
            onPressed: _busy ? null : _create,
            icon: const Icon(Icons.check, size: 16),
            label: const Text('CRIAR PESQUISA'),
          ),
          const SizedBox(width: 8),
          TextButton(
              onPressed: () => setState(() => _creating = false),
              child: const Text('CANCELAR')),
        ]),
      ]),
    );
  }

  Widget _buildDraftRow(int index) {
    final stage = _draft[index];
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(children: [
        Expanded(
          child: TextFormField(
            key: ValueKey('draft-$index-${stage.title.hashCode}-${_draft.length}'),
            initialValue: stage.title,
            onChanged: (value) => stage.title = value,
            decoration: const InputDecoration(labelText: 'ETAPA', isDense: true),
          ),
        ),
        const SizedBox(width: 8),
        OutlinedButton(
          onPressed: () async {
            final picked = await _pickDate(stage.dueAt);
            if (picked != null) setState(() => stage.dueAt = picked);
          },
          child: Text(stage.dueAt == null ? 'SEM PRAZO' : _date(stage.dueAt!)),
        ),
        IconButton(
          tooltip: 'Remover etapa',
          onPressed: () => setState(() => _draft.removeAt(index)),
          icon: const Icon(Icons.delete_outline, size: 18),
        ),
      ]),
    );
  }

  Widget _buildProject(ResearchDetail detail) {
    final project = detail.project;
    return _Panel(
      title: project.title.toUpperCase(),
      trailing: DropdownButton<String>(
        key: const Key('research-status'),
        value: project.status,
        isDense: true,
        items: [
          for (final e in researchStatuses.entries)
            DropdownMenuItem(value: e.key, child: Text(e.value)),
        ],
        onChanged: _busy ? null : (value) => value == null ? null : _setStatus(project, value),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (project.description.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(project.description,
                style: const TextStyle(fontSize: 12, color: AssistantTheme.textSecondary)),
          ),
        Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center,
            children: [
          if (project.area.isNotEmpty) _Chip(project.area, AssistantTheme.c1),
          _Chip('${project.participants} participantes', AssistantTheme.c2),
          _Chip('${project.done}/${project.stages} etapas', AssistantTheme.c3),
          if (project.overdue > 0)
            _Chip('${project.overdue} atrasada(s)', Colors.redAccent),
          if (project.nextDue != null)
            _Chip('próximo prazo ${_date(project.nextDue!)}', AssistantTheme.textMuted),
          TextButton(
            onPressed: _busy ? null : () => _delete(project),
            child: const Text('APAGAR'),
          ),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: project.progress / 100,
                minHeight: 8,
                color: AssistantTheme.c3,
                backgroundColor: AssistantTheme.c3.withOpacity(.15),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Text('${project.progress}%',
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
        ]),
      ]),
    );
  }

  Widget _buildParticipants(ResearchDetail detail) {
    return _Panel(
      title: 'PARTICIPANTES',
      trailing: FilledButton.tonalIcon(
        key: const Key('participant-add'),
        onPressed: _busy ? null : () => _addParticipant(detail.project),
        icon: const Icon(Icons.person_add_alt, size: 16),
        label: const Text('ADICIONAR'),
      ),
      child: detail.participants.isEmpty
          ? const _Hint('Ninguém ainda. Adicione alunos ou pessoas de fora.')
          : Column(children: [
              for (final person in detail.participants)
                Container(
                  margin: const EdgeInsets.only(bottom: 6),
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: AssistantTheme.border),
                  ),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Wrap(spacing: 8, runSpacing: 4,
                            crossAxisAlignment: WrapCrossAlignment.center, children: [
                          Text(person.name,
                              style: const TextStyle(
                                  fontWeight: FontWeight.w700, fontSize: 13)),
                          _Chip(person.roleLabel, AssistantTheme.c1),
                          if (person.knownStudent)
                            _Chip('ALUNO CONHECIDO', AssistantTheme.c3),
                          if (person.institution.isNotEmpty)
                            _Chip(person.institution, AssistantTheme.textMuted),
                        ]),
                        Text(
                          [
                            if (person.enrollment.isNotEmpty) 'mat. ${person.enrollment}',
                            if (person.email.isNotEmpty) person.email,
                            if (person.phone.isNotEmpty) person.phone,
                          ].join('  ·  '),
                          style: const TextStyle(
                              fontSize: 11, color: AssistantTheme.textSecondary),
                        ),
                      ]),
                    ),
                    IconButton(
                      tooltip: 'Tirar da pesquisa',
                      onPressed: _busy ? null : () => _removeParticipant(person),
                      icon: const Icon(Icons.person_remove_outlined, size: 18),
                    ),
                  ]),
                ),
            ]),
    );
  }

  Widget _buildStages(ResearchDetail detail) {
    return _Panel(
      title: 'ETAPAS E PRAZOS',
      trailing: FilledButton.tonalIcon(
        key: const Key('stage-add'),
        onPressed: _busy ? null : () => _editStage(detail.project),
        icon: const Icon(Icons.add, size: 16),
        label: const Text('NOVA ETAPA'),
      ),
      child: detail.stages.isEmpty
          ? const _Hint('Nenhuma etapa ainda.')
          : Column(children: [
              for (final stage in detail.stages) _buildStage(detail.project, stage),
            ]),
    );
  }

  Widget _buildStage(ResearchProject project, ResearchStage stage) {
    final (icon, color) = switch (stage.state) {
      'done' => (Icons.check_circle, AssistantTheme.c3),
      'doing' => (Icons.timelapse, AssistantTheme.c1),
      'overdue' => (Icons.error_outline, Colors.redAccent),
      _ => (Icons.radio_button_unchecked, AssistantTheme.textMuted),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AssistantTheme.border),
      ),
      child: Row(children: [
        IconButton(
          key: Key('stage-status-${stage.id}'),
          tooltip: 'Mudar a situação (a fazer, fazendo, feita)',
          onPressed: _busy ? null : () => _cycleStage(stage),
          icon: Icon(icon, size: 22, color: color),
        ),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(stage.title,
                style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                    decoration: stage.isDone ? TextDecoration.lineThrough : null)),
            Text(
              stage.dueAt == null
                  ? 'Sem prazo'
                  : '${stage.state == 'overdue' ? 'Venceu' : 'Prazo'} ${_date(stage.dueAt!)}',
              style: TextStyle(
                  fontSize: 11,
                  color: stage.state == 'overdue'
                      ? Colors.redAccent
                      : AssistantTheme.textSecondary),
            ),
            if (stage.description.isNotEmpty)
              Text(stage.description,
                  style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
          ]),
        ),
        IconButton(
            tooltip: 'Editar',
            onPressed: _busy ? null : () => _editStage(project, stage),
            icon: const Icon(Icons.edit_outlined, size: 16)),
        IconButton(
            tooltip: 'Apagar',
            onPressed: _busy ? null : () => _deleteStage(stage),
            icon: const Icon(Icons.delete_outline, size: 16)),
      ]),
    );
  }
}

String _date(DateTime value) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(value.day)}/${two(value.month)}/${value.year}';
}

class _Panel extends StatelessWidget {
  final String title;
  final Widget child;
  final Widget? trailing;

  const _Panel({required this.title, required this.child, this.trailing});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AssistantTheme.bg.withOpacity(.38),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AssistantTheme.c3.withOpacity(.45)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text(title,
                  style: const TextStyle(
                      fontFamily: 'Rajdhani',
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1,
                      color: AssistantTheme.c3)),
            ),
            if (trailing != null) trailing!,
          ]),
          const SizedBox(height: 8),
          child,
        ]),
      );
}

class _Chip extends StatelessWidget {
  final String text;
  final Color color;

  const _Chip(this.text, this.color);

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: color.withOpacity(.12),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withOpacity(.5)),
        ),
        child: Text(text,
            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color)),
      );
}

class _Hint extends StatelessWidget {
  final String text;

  const _Hint(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text(text,
            style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
      );
}

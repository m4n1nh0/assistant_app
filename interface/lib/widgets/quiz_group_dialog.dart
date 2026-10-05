/// Configuração do quiz em grupo: modo, representantes e ranking por grupo.
///
/// O aluno entra com a matrícula e o servidor o liga ao grupo da disciplina; aqui
/// o professor escolhe como o grupo pontua, confere quem consegue entrar e define
/// quem responde pelo grupo.
library;

import 'package:flutter/material.dart';

import '../models/group_class.dart';
import '../models/quiz_group.dart';
import '../services/education_service.dart';
import '../services/quiz_center_service.dart';
import '../utils/theme.dart';

Future<void> showQuizGroupDialog(
  BuildContext context, {
  required String quizId,
  QuizCenterService? service,
  Future<List<Discipline>> Function()? loadDisciplines,
  Future<List<ClassGroup>> Function()? loadClasses,
  VoidCallback? onChanged,
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: const EdgeInsets.all(20),
      child: QuizGroupPanel(
        quizId: quizId,
        service: service,
        loadDisciplines: loadDisciplines,
        loadClasses: loadClasses,
        onChanged: onChanged,
      ),
    ),
  );
}

class QuizGroupPanel extends StatefulWidget {
  final String quizId;
  final QuizCenterService? service;
  final Future<List<Discipline>> Function()? loadDisciplines;
  final Future<List<ClassGroup>> Function()? loadClasses;
  final VoidCallback? onChanged;

  const QuizGroupPanel({
    super.key,
    required this.quizId,
    this.service,
    this.loadDisciplines,
    this.loadClasses,
    this.onChanged,
  });

  @override
  State<QuizGroupPanel> createState() => _QuizGroupPanelState();
}

class _QuizGroupPanelState extends State<QuizGroupPanel> {
  QuizCenterService get _service => widget.service ?? quizCenter;

  QuizGroupInfo _info = const QuizGroupInfo();
  List<Discipline> _disciplines = const [];
  List<ClassGroup> _classes = const [];
  /// Turma dos grupos do quiz; `null` vale para a disciplina toda.
  String? _classId;
  String _mode = QuizGroupMode.average;
  String _absence = AbsencePenalty.none;
  final _percent = TextEditingController(text: '10');
  String? _disciplineId;
  bool _loading = true;
  bool _busy = false;
  String _message = '';
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _percent.dispose();
    super.dispose();
  }

  String _errorText(Object error) => error is QuizCenterException
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
      final info = await _service.groupInfo(widget.quizId);
      final disciplines =
          await (widget.loadDisciplines ?? () => education.listDisciplines())();
      final classes = await (widget.loadClasses ??
          () => education.listClasses(activeOnly: false))();
      if (!mounted) return;
      setState(() {
        _disciplines = disciplines;
        _classes = classes;
        _apply(info);
        _disciplineId ??= disciplines.isEmpty ? null : disciplines.first.id;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      _report('Falha ao carregar: ${_errorText(e)}', error: true);
    }
  }

  void _apply(QuizGroupInfo info) {
    _info = info;
    if (info.enabled) {
      _mode = info.mode;
      _disciplineId = info.disciplineId;
      _classId = info.classId.isEmpty ? null : info.classId;
      _absence = info.absenceMode;
      if (info.absencePercent > 0) _percent.text = '${info.absencePercent}';
    }
  }

  Future<void> _run(Future<QuizGroupInfo> Function() call, {String? done}) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final info = await call();
      if (!mounted) return;
      setState(() => _apply(info));
      widget.onChanged?.call();
      _report(done ?? '');
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  List<ClassGroup> get _turmas => classesOfDiscipline(_classes, _disciplineId);

  Discipline? get _discipline {
    for (final item in _disciplines) {
      if (item.id == _disciplineId) return item;
    }
    return null;
  }

  /// Para o texto de apoio, que precisa de um número mesmo com o campo vazio.
  int get _absencePercentForText =>
      (int.tryParse(_percent.text.trim()) ?? 0).clamp(0, 100);

  /// Percentual digitado; 0 quando o campo está vazio ou inválido.
  int get _absencePercent =>
      _absence == AbsencePenalty.percent
          ? (int.tryParse(_percent.text.trim()) ?? 0).clamp(0, 100)
          : 0;

  Future<void> _save() async {
    final discipline = _discipline;
    if (discipline == null) {
      _report('Escolha a disciplina dos grupos.', error: true);
      return;
    }
    await _run(
      () => _service.setGroup(
        widget.quizId,
        mode: _mode,
        disciplineId: discipline.id,
        semester: discipline.semester,
        classId: _classId,
        absenceMode: _absence,
        absencePercent: _absencePercent,
      ),
      done: _info.enabled
          ? 'Quiz em grupo atualizado.'
          : 'Quiz em grupo ativado. A turma entra com a matrícula.',
    );
  }

  Future<void> _turnOff() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await _service.unsetGroup(widget.quizId);
      if (!mounted) return;
      setState(() => _info = const QuizGroupInfo());
      widget.onChanged?.call();
      _report('O quiz voltou a ser individual.');
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    return ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: size.width < 900 ? size.width - 40 : 860,
        maxHeight: size.height - 40,
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: _loading
            ? const SizedBox(
                height: 160,
                child: Center(child: CircularProgressIndicator()),
              )
            : Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Quiz em grupo',
                          style: TextStyle(
                              fontSize: 15, fontWeight: FontWeight.w600),
                        ),
                      ),
                      IconButton(
                        tooltip: 'Fechar',
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () => Navigator.pop(context),
                      ),
                    ],
                  ),
                  if (_message.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        _message,
                        style: TextStyle(
                          fontSize: 12,
                          color: _error
                              ? AssistantTheme.danger
                              : AssistantTheme.c3,
                        ),
                      ),
                    ),
                  Flexible(
                    child: SingleChildScrollView(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _config(),
                          if (_info.enabled) ...[
                            const SizedBox(height: 16),
                            _teams(),
                            if (_info.ranking.isNotEmpty) ...[
                              const SizedBox(height: 16),
                              _ranking(),
                            ],
                          ],
                        ],
                      ),
                    ),
                  ),
                ],
              ),
      ),
    );
  }

  Widget _config() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Os alunos entram com a matrícula e o sistema liga cada um ao seu '
          'grupo da disciplina.',
          style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 12),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(
              value: QuizGroupMode.average,
              icon: Icon(Icons.functions, size: 16),
              label: Text('Média do grupo'),
            ),
            ButtonSegment(
              value: QuizGroupMode.representative,
              icon: Icon(Icons.record_voice_over_outlined, size: 16),
              label: Text('Só o representante'),
            ),
          ],
          selected: {_mode},
          onSelectionChanged: _busy
              ? null
              : (value) => setState(() {
                    _mode = value.first;
                    // "Ausente conta zero" só existe na média do grupo.
                    if (_mode == QuizGroupMode.representative &&
                        _absence == AbsencePenalty.zero) {
                      _absence = AbsencePenalty.none;
                    }
                  }),
        ),
        const SizedBox(height: 6),
        Text(
          QuizGroupMode.explanation(_mode),
          style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 14),
        const Text(
          'Penalidade por ausente',
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 12,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SegmentedButton<String>(
              segments: [
                const ButtonSegment(
                  value: AbsencePenalty.none,
                  label: Text('Sem penalidade'),
                ),
                ButtonSegment(
                  value: AbsencePenalty.zero,
                  label: const Text('Ausente conta zero'),
                  // Com representante a nota já é só a dele: não há média a diluir.
                  enabled: _mode == QuizGroupMode.average,
                ),
                const ButtonSegment(
                  value: AbsencePenalty.percent,
                  label: Text('Desconto por ausente'),
                ),
              ],
              selected: {_absence},
              showSelectedIcon: false,
              onSelectionChanged: _busy
                  ? null
                  : (value) => setState(() => _absence = value.first),
            ),
            if (_absence == AbsencePenalty.percent)
              SizedBox(
                width: 110,
                child: TextField(
                  controller: _percent,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    isDense: true,
                    labelText: 'Por ausente',
                    suffixText: '%',
                  ),
                  onChanged: (_) => setState(() {}),
                ),
              ),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          '${AbsencePenalty.explanation(_absence, _absencePercentForText)} '
          'Ausente é quem não entrou ou entrou e não respondeu nada; quem não '
          'tem matrícula vinculada não é penalizado.',
          style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 12),
        if (_turmas.isNotEmpty) ...[
          DropdownButtonFormField<String>(
            value: _turmas.any((item) => item.id == _classId)
                ? _classId
                : 'all',
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Turma (dia de aula)'),
            items: [
              const DropdownMenuItem(
                  value: 'all', child: Text('Todas as turmas da disciplina')),
              for (final turma in _turmas)
                DropdownMenuItem(
                  value: turma.id,
                  child: Text(classDisplay(turma), overflow: TextOverflow.ellipsis),
                ),
            ],
            onChanged: _busy
                ? null
                : (value) =>
                    setState(() => _classId = value == 'all' ? null : value),
          ),
          const SizedBox(height: 4),
          Text(
            _classId == null
                ? 'Entram os alunos de todos os grupos da disciplina.'
                : 'Só entram os alunos dos grupos desta turma; a matrícula de quem é de outra turma não vale neste quiz.',
            style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
          ),
          const SizedBox(height: 12),
        ],
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                value: _disciplines.any((item) => item.id == _disciplineId)
                    ? _disciplineId
                    : null,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: 'Disciplina dos grupos',
                ),
                items: [
                  for (final item in _disciplines)
                    DropdownMenuItem(
                      value: item.id,
                      child: Text(
                        '${item.label} (${item.semester})',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: _busy
                    ? null
                    : (value) => setState(() {
                        _disciplineId = value;
                        _classId = null; // a turma pertence a uma disciplina
                      }),
              ),
            ),
            const SizedBox(width: 12),
            FilledButton.icon(
              onPressed: _busy ? null : _save,
              icon: const Icon(Icons.groups_2_outlined, size: 16),
              label: Text(_info.enabled ? 'SALVAR' : 'ATIVAR QUIZ EM GRUPO'),
            ),
            if (_info.enabled) ...[
              const SizedBox(width: 8),
              TextButton(
                onPressed: _busy ? null : _turnOff,
                child: const Text('VOLTAR A INDIVIDUAL'),
              ),
            ],
          ],
        ),
      ],
    );
  }

  Widget _teams() {
    final missing = _info.withoutRepresentative;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                '${_info.groups.length} grupos · ${_info.discipline}'
                '${_info.classLabel.isEmpty ? "" : " · ${_info.classLabel}"}',
                style: const TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w600),
              ),
            ),
            if (_info.byRepresentative) ...[
              OutlinedButton.icon(
                onPressed: _busy || _info.groups.every((g) => g.blocked)
                    ? null
                    : () => _run(
                          () => _service.drawRepresentatives(widget.quizId),
                          done: 'Representantes sorteados.',
                        ),
                icon: const Icon(Icons.casino_outlined, size: 16),
                label: const Text('SORTEAR REPRESENTANTES'),
              ),
              const SizedBox(width: 8),
              TextButton(
                onPressed: _busy || _info.groups.every((g) => g.blocked)
                    ? null
                    : () => _run(
                          () => _service.drawRepresentatives(
                            widget.quizId,
                            redraw: true,
                          ),
                          done: 'Representantes sorteados de novo.',
                        ),
                child: const Text('REFAZER TODOS'),
              ),
            ],
          ],
        ),
        if (missing.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              'Sem representante: ${missing.map((g) => g.name).join(", ")}. '
              'Enquanto isso o grupo não consegue responder.',
              style: const TextStyle(fontSize: 11, color: AssistantTheme.c4),
            ),
          ),
        const SizedBox(height: 8),
        for (final team in _info.groups) _teamCard(team),
        const SizedBox(height: 4),
        SelectableText(
          'Semente do sorteio: ${_info.seed}',
          style: const TextStyle(fontSize: 10, color: AssistantTheme.textMuted),
        ),
      ],
    );
  }

  Widget _teamCard(QuizGroupTeam team) {
    final rep = team.representative;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AssistantTheme.surface2,
        border: Border(
          left: BorderSide(
            color: team.blocked ? AssistantTheme.danger : AssistantTheme.c1,
            width: 3,
          ),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(team.name, style: const TextStyle(fontSize: 13)),
              ),
              Text(
                '${team.joinedCount} de ${team.members.length} entraram',
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textMuted),
              ),
            ],
          ),
          if (team.blocked)
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text(
                'Nenhum integrante tem matrícula vinculada, então ninguém deste '
                'grupo consegue entrar. Vincule os nomes em Grupos de projeto.',
                style: TextStyle(fontSize: 11, color: AssistantTheme.danger),
              ),
            ),
          if (_info.penalizes && _info.anyoneJoined && team.absent.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'Ausentes: ${team.absent.join(", ")}'
                '${team.penaltyPercent > 0 ? " · desconto de ${team.penaltyPercent}% na nota" : _info.absenceMode == AbsencePenalty.zero ? " · contam zero na média" : ""}',
                style: const TextStyle(fontSize: 11, color: AssistantTheme.c4),
              ),
            ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final member in team.members)
                Tooltip(
                  message: member.eligible
                      ? (member.joined ? 'Já entrou' : 'Ainda não entrou')
                      : 'Sem matrícula vinculada: não consegue entrar',
                  child: Chip(
                    visualDensity: VisualDensity.compact,
                    avatar: Icon(
                      member.joined
                          ? Icons.check_circle
                          : member.eligible
                              ? Icons.radio_button_unchecked
                              : Icons.block,
                      size: 14,
                      color: member.joined
                          ? AssistantTheme.c3
                          : member.eligible
                              ? AssistantTheme.textMuted
                              : AssistantTheme.danger,
                    ),
                    label: Text(
                      member.name,
                      style: TextStyle(
                        fontSize: 11,
                        color: rep?.memberId == member.id
                            ? AssistantTheme.c2
                            : AssistantTheme.textPrimary,
                        fontWeight: rep?.memberId == member.id
                            ? FontWeight.w700
                            : FontWeight.w400,
                      ),
                    ),
                    backgroundColor: AssistantTheme.surface,
                    side: const BorderSide(color: AssistantTheme.border2),
                  ),
                ),
            ],
          ),
          if (_info.byRepresentative && !team.blocked)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      rep == null
                          ? 'Representante: ainda não escolhido'
                          : 'Representante: ${rep.name}'
                              '${rep.manual ? " (escolhido por você)" : rep.round > 0 ? " (sorteio ${rep.round + 1})" : " (sorteado)"}',
                      style: TextStyle(
                        fontSize: 12,
                        color: rep == null
                            ? AssistantTheme.c4
                            : AssistantTheme.c2,
                      ),
                    ),
                  ),
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => _run(() => _service.redrawRepresentative(
                              widget.quizId,
                              team.id,
                            )),
                    child: Text(rep == null ? 'SORTEAR' : 'SORTEAR OUTRO'),
                  ),
                  PopupMenuButton<String>(
                    tooltip: 'Escolher o representante',
                    enabled: !_busy,
                    icon: const Icon(Icons.person_pin_outlined, size: 18),
                    onSelected: (memberId) => _run(
                      () => _service.setRepresentative(
                        widget.quizId,
                        team.id,
                        memberId,
                      ),
                    ),
                    itemBuilder: (_) => [
                      for (final member in team.eligibleMembers)
                        PopupMenuItem(
                          value: member.id,
                          child: Text(member.name),
                        ),
                    ],
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _ranking() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Ranking por grupo',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 6),
        for (final row in _info.ranking)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: [
                SizedBox(
                  width: 34,
                  child: Text(
                    '#${row['position']}',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(row['student_name']?.toString() ?? '',
                          style: const TextStyle(fontSize: 13)),
                      Text(
                        groupRankingDetail(row, showRound: false),
                        style: const TextStyle(
                            fontSize: 10, color: AssistantTheme.textMuted),
                      ),
                    ],
                  ),
                ),
                Text('${row['score']} pts',
                    style: const TextStyle(fontWeight: FontWeight.w700)),
              ],
            ),
          ),
      ],
    );
  }
}

/// Inscrição em mentorias: descrever a mentoria, a IA montar o formulário, publicar o
/// link e acompanhar quem se inscreveu.
///
/// A página que o inscrito abre é pública (sem login) e sempre pede matrícula, nome,
/// e-mail e telefone; aqui só se editam os demais campos. Aceitar inscritos cria a
/// mentoria como disciplina com uma turma, e cada aceito vira aluno dela - dali em
/// diante presença, pontos e reunião funcionam como em qualquer turma, e remover quem
/// não entrega é tirar o aluno da turma.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../models/mentorship.dart';
import '../models/presentation_material.dart' show isLocalAddress;
import '../services/education_service.dart';
import '../utils/theme.dart';
import 'mentorship_activities_panel.dart';

class MentorshipsTab extends StatefulWidget {
  /// Trocam serviço e endereço nos testes.
  final EducationService? service;
  final String? baseUrl;

  /// De quanto em quanto tempo a lista se atualiza sozinha, para novas inscrições
  /// aparecerem sem apertar nada. Zero desliga (testes).
  final Duration pollEvery;

  const MentorshipsTab({
    super.key,
    this.service,
    this.baseUrl,
    this.pollEvery = const Duration(seconds: 15),
  });

  @override
  State<MentorshipsTab> createState() => _MentorshipsTabState();
}

class _MentorshipsTabState extends State<MentorshipsTab> {
  EducationService get _service => widget.service ?? education;
  String get _baseUrl => widget.baseUrl ?? _service.publicBaseUrl;

  final _title = TextEditingController();
  final _description = TextEditingController();
  final _slots = TextEditingController();
  List<MentorshipField> _fields = [];
  DateTime? _deadline;
  bool _creating = false;
  bool _generated = false;

  List<MentorshipForm> _forms = const [];
  /// A mentoria aberta; nula = a lista. A tela da mentoria tem três seções.
  String? _selectedId;
  int _section = 0;
  List<MentorshipSignup> _signups = const [];
  String _filter = 'all';
  bool _loading = true;
  bool _busy = false;
  bool _error = false;
  String _message = '';
  Timer? _timer;

  MentorshipForm? get _selected {
    for (final form in _forms) {
      if (form.id == _selectedId) return form;
    }
    return null;
  }

  @override
  void initState() {
    super.initState();
    _load();
    if (widget.pollEvery > Duration.zero) {
      _timer = Timer.periodic(widget.pollEvery, (_) => _refresh());
    }
  }

  /// Atualização silenciosa: não mexe na mensagem nem no que o professor está
  /// escrevendo, e fica quieta quando a rede falha (a próxima rodada resolve).
  Future<void> _refresh() async {
    if (!mounted || _busy || _loading) return;
    try {
      final forms = await _service.listMentorships();
      if (!mounted) return;
      setState(() {
        _forms = forms;
        // A mentoria aberta foi apagada em outro lugar: volta para a lista.
        if (_selectedId != null && _selected == null) _selectedId = null;
      });
      final id = _selectedId;
      if (id == null) return;
      final signups = await _service.listMentorshipSignups(id);
      if (mounted && _selectedId == id && !_busy) setState(() => _signups = signups);
    } catch (_) {}
  }

  @override
  void dispose() {
    _timer?.cancel();
    _title.dispose();
    _description.dispose();
    _slots.dispose();
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
      final forms = await _service.listMentorships();
      if (!mounted) return;
      setState(() {
        _forms = forms;
        _loading = false;
        if (_selectedId != null && _selected == null) _selectedId = null;
      });
      await _loadSignups();
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
      _report('Falha ao carregar: ${_errorText(e)}', error: true);
    }
  }

  Future<void> _loadSignups() async {
    final id = _selectedId;
    if (id == null) {
      if (mounted) setState(() => _signups = const []);
      return;
    }
    try {
      final signups = await _service.listMentorshipSignups(id);
      if (mounted && _selectedId == id) setState(() => _signups = signups);
    } catch (e) {
      _report('Falha ao carregar os inscritos: ${_errorText(e)}', error: true);
    }
  }

  void _replace(MentorshipForm form) {
    setState(() {
      _forms = [for (final f in _forms) f.id == form.id ? form : f];
    });
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

  // --- criação ----------------------------------------------------------------------

  Future<void> _generate() => _guard(() async {
        final description = _description.text.trim();
        if (description.length < 3) {
          _report('Descreva a mentoria para a IA montar o formulário.', error: true);
          return;
        }
        final result = await _service.generateMentorshipFields(description);
        if (!mounted) return;
        setState(() {
          _fields = result.fields;
          _generated = true;
        });
        _report(result.fromAi
            ? 'A IA montou ${result.fields.length} campos. Ajuste o que quiser antes de criar.'
            : 'A IA não respondeu; usei os campos padrão. Ajuste antes de criar.');
      });

  void _startCreating() {
    setState(() {
      _creating = true;
      _generated = false;
      _fields = [];
      _title.clear();
      _description.clear();
      _slots.clear();
      _deadline = null;
    });
  }

  Future<void> _create() => _guard(() async {
        final title = _title.text.trim();
        if (title.isEmpty) {
          _report('Dê um nome à mentoria.', error: true);
          return;
        }
        final fields = [for (final f in _fields) if (f.label.trim().isNotEmpty) f];
        final slots = int.tryParse(_slots.text.trim());
        final form = await _service.createMentorship(
          title: title,
          description: _description.text.trim(),
          fields: fields,
          closesAt: _deadline,
          maxSlots: slots != null && slots > 0 ? slots : null,
        );
        if (!mounted) return;
        setState(() {
          _forms = [form, ..._forms];
          _selectedId = form.id;
          _section = 2; // a primeira coisa a fazer é copiar o link
          _filter = 'all';
          _signups = const [];
          _creating = false;
        });
        _report('Formulário criado. Copie o link e mande para os alunos.');
      });

  Future<void> _pickDeadline() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _deadline ?? now.add(const Duration(days: 7)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 365)),
    );
    if (picked != null) {
      // Vale até o fim do dia escolhido.
      setState(() =>
          _deadline = DateTime(picked.year, picked.month, picked.day, 23, 59));
    }
  }

  // --- formulário publicado ---------------------------------------------------------

  Future<void> _toggleActive(MentorshipForm form) => _guard(() async {
        _replace(await _service.updateMentorship(form.id, {'active': !form.active}));
        _report(form.active ? 'Inscrições fechadas.' : 'Inscrições reabertas.');
      });

  Future<void> _delete(MentorshipForm form) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Apagar formulário?'),
        content: const Text(
            'O link deixa de funcionar e as inscrições são apagadas. A turma e os '
            'alunos já aceitos continuam.'),
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
      await _service.deleteMentorship(form.id);
      if (!mounted) return;
      setState(() {
        _forms = [for (final f in _forms) if (f.id != form.id) f];
        _selectedId = null;
        _signups = const [];
      });
      _report('Formulário apagado.');
    });
  }

  Future<void> _copyLink(MentorshipForm form) async {
    await Clipboard.setData(ClipboardData(text: form.url(_baseUrl)));
    _report('Link copiado.');
  }

  Future<void> _showQr(MentorshipForm form) {
    final url = form.url(_baseUrl);
    return showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(form.title),
        content: SizedBox(
          width: 300,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Container(
              color: Colors.white,
              padding: const EdgeInsets.all(12),
              child: QrImageView(data: url, size: 240),
            ),
            const SizedBox(height: 8),
            SelectableText(url, style: const TextStyle(fontSize: 11)),
          ]),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Fechar')),
        ],
      ),
    );
  }

  Future<void> _copyCsv(MentorshipForm form) => _guard(() async {
        final csv = await _service.exportMentorshipSignups(form.id);
        await Clipboard.setData(ClipboardData(text: csv));
        _report('Inscritos copiados em CSV. Cole numa planilha.');
      });

  Future<void> _setStatus(MentorshipForm form, List<MentorshipSignup> items,
          String status) =>
      _guard(() async {
        final result = await _service.setMentorshipSignupStatus(
            form.id, [for (final s in items) s.id], status);
        _replace(result.form);
        await _loadSignups();
        _report(switch (status) {
          'accepted' => '${items.length} aceito(s). Já estão na turma da mentoria'
              '${result.emailed > 0 ? ' e ${result.emailed} foram avisados por e-mail' : ''}.',
          'rejected' => '${items.length} recusado(s).',
          _ => '${items.length} removido(s) da turma.',
        });
      });

  // --- tela -------------------------------------------------------------------------

  void _open(MentorshipForm form) {
    setState(() {
      _selectedId = form.id;
      _section = 0;
      _filter = 'all';
      _signups = const [];
      _message = '';
    });
    _loadSignups();
  }

  void _back() {
    setState(() {
      _selectedId = null;
      _signups = const [];
      _message = '';
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    final form = _selected;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        if (form == null) _buildListHeader() else _buildDetailHeader(form),
        if (_message.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_message,
                style: TextStyle(
                    fontSize: 12,
                    color: _error ? Colors.redAccent : AssistantTheme.c3)),
          ),
        const SizedBox(height: 10),
        if (form == null) ...[
          if (_creating) _buildCreator(),
          if (!_creating && _forms.isEmpty)
            const _Hint('Nenhuma mentoria ainda. Clique em NOVA MENTORIA, descreva o '
                'tema e a IA monta as perguntas.'),
          for (final f in _forms) _buildCard(f),
        ] else
          ..._buildDetail(form),
      ],
    );
  }

  Widget _buildListHeader() => Row(children: [
        const Icon(Icons.person_add_alt_outlined, color: AssistantTheme.c3),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
              _forms.length > 1 ? 'MENTORIAS (${_forms.length})' : 'MENTORIAS',
              style: const TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.6)),
        ),
        if (!_creating)
          FilledButton.icon(
            key: const Key('mentorship-new'),
            onPressed: _startCreating,
            icon: const Icon(Icons.add, size: 16),
            label: const Text('NOVA MENTORIA'),
          ),
      ]);

  Widget _buildDetailHeader(MentorshipForm form) => Row(children: [
        IconButton(
          key: const Key('mentorship-back'),
          tooltip: 'Voltar para a lista de mentorias',
          onPressed: _back,
          icon: const Icon(Icons.arrow_back),
        ),
        Expanded(
          child: Text(form.title.toUpperCase(),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.2)),
        ),
        const SizedBox(width: 8),
        _Chip(form.stateLabel, form.isOpen ? AssistantTheme.c3 : AssistantTheme.textMuted),
      ]);

  /// O cartão da lista: o suficiente para decidir qual abrir, com o que pede atenção.
  Widget _buildCard(MentorshipForm f) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        key: Key('mentorship-card-${f.id}'),
        borderRadius: BorderRadius.circular(8),
        onTap: () => _open(f),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AssistantTheme.bg.withOpacity(.38),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
                color: (f.pending > 0 ? AssistantTheme.c4 : AssistantTheme.c3)
                    .withOpacity(.5)),
          ),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(f.title,
                    style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
                if (f.description.trim().isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(f.description.trim().replaceAll('\n', ' '),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 12, color: AssistantTheme.textSecondary)),
                  ),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 6, children: [
                  _Chip(f.stateLabel,
                      f.isOpen ? AssistantTheme.c3 : AssistantTheme.textMuted),
                  _Chip(f.summary, AssistantTheme.c1),
                  if (f.pending > 0)
                    _Chip('${f.pending} aguardando você', AssistantTheme.c4),
                  _Chip('${f.accepted} aceitos', AssistantTheme.c3),
                  if (f.activities > 0)
                    _Chip('${f.activities} atividades', AssistantTheme.c2),
                  if (f.closesAt != null)
                    _Chip('prazo ${_formatDate(f.closesAt!.toLocal())}',
                        AssistantTheme.textMuted),
                ]),
              ]),
            ),
            const Icon(Icons.chevron_right, color: AssistantTheme.textMuted),
          ]),
        ),
      ),
    );
  }

  List<Widget> _buildDetail(MentorshipForm form) => [
        SegmentedButton<int>(
          key: const Key('mentorship-sections'),
          showSelectedIcon: false,
          segments: [
            ButtonSegment(
                value: 0,
                icon: const Icon(Icons.how_to_reg_outlined, size: 16),
                label: Text('INSCRITOS (${form.signups})')),
            ButtonSegment(
                value: 1,
                icon: const Icon(Icons.assignment_outlined, size: 16),
                label: Text('ATIVIDADES (${form.activities})')),
            const ButtonSegment(
                value: 2,
                icon: Icon(Icons.link, size: 16),
                label: Text('LINK E DADOS')),
          ],
          selected: {_section},
          onSelectionChanged: (value) => setState(() => _section = value.first),
        ),
        const SizedBox(height: 12),
        if (_section == 0) _buildSignups(form),
        if (_section == 1)
          MentorshipActivitiesPanel(
            // Recarrega quando entra ou sai alguem da turma da mentoria.
            key: ValueKey('${form.id}-${form.accepted}'),
            form: form,
            baseUrl: _baseUrl,
            service: _service,
            pollEvery: widget.pollEvery == Duration.zero
                ? Duration.zero
                : const Duration(seconds: 30),
            onRemove: (ids) => _setStatus(
              form,
              [for (final s in _signups) if (ids.contains(s.id)) s],
              'removed',
            ),
          ),
        if (_section == 2) _buildForm(form),
      ];

  Widget _buildCreator() {
    return _Panel(
      title: 'NOVA MENTORIA',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        TextField(
          key: const Key('mentorship-title'),
          controller: _title,
          decoration: const InputDecoration(
              labelText: 'NOME DA MENTORIA', isDense: true),
        ),
        const SizedBox(height: 10),
        TextField(
          key: const Key('mentorship-description'),
          controller: _description,
          minLines: 3,
          maxLines: 6,
          decoration: const InputDecoration(
            labelText: 'DESCREVA A MENTORIA (A IA USA ISTO PARA MONTAR O FORMULÁRIO)',
            hintText: 'Ex.: mentoria de carreira em dados, encontros quinzenais, para '
                'alunos de ADS e Ciência da Computação...',
            isDense: true,
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 10),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            key: const Key('mentorship-generate'),
            onPressed: _busy ? null : _generate,
            icon: const Icon(Icons.auto_awesome, size: 16),
            label: Text(_generated ? 'GERAR DE NOVO COM IA' : 'GERAR CAMPOS COM IA'),
          ),
        ),
        const SizedBox(height: 12),
        const _Hint('Sempre pedidos: matrícula, nome, e-mail e telefone. Os campos '
            'abaixo são os demais.'),
        for (var i = 0; i < _fields.length; i++) _buildFieldRow(i),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => setState(() => _fields.add(MentorshipField(label: ''))),
            icon: const Icon(Icons.add, size: 16),
            label: const Text('ADICIONAR CAMPO'),
          ),
        ),
        const Divider(),
        Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
            children: [
          SizedBox(
            width: 150,
            child: TextField(
              key: const Key('mentorship-slots'),
              controller: _slots,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: const InputDecoration(
                  labelText: 'VAGAS (OPCIONAL)', isDense: true),
            ),
          ),
          OutlinedButton.icon(
            onPressed: _pickDeadline,
            icon: const Icon(Icons.event, size: 16),
            label: Text(_deadline == null
                ? 'PRAZO (OPCIONAL)'
                : 'ATÉ ${_formatDate(_deadline!)}'),
          ),
          if (_deadline != null)
            IconButton(
              tooltip: 'Tirar o prazo',
              onPressed: () => setState(() => _deadline = null),
              icon: const Icon(Icons.close, size: 16),
            ),
        ]),
        const SizedBox(height: 14),
        Row(children: [
          FilledButton.icon(
            key: const Key('mentorship-create'),
            onPressed: _busy ? null : _create,
            icon: const Icon(Icons.check, size: 16),
            label: const Text('CRIAR FORMULÁRIO'),
          ),
          const SizedBox(width: 8),
          TextButton(
              onPressed: () => setState(() => _creating = false),
              child: const Text('CANCELAR')),
        ]),
      ]),
    );
  }

  Widget _buildFieldRow(int index) {
    final field = _fields[index];
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            flex: 3,
            child: TextFormField(
              key: ValueKey('field-label-$index-${field.id}'),
              initialValue: field.label,
              onChanged: (value) => field.label = value,
              decoration:
                  const InputDecoration(labelText: 'PERGUNTA', isDense: true),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 2,
            child: DropdownButtonFormField<String>(
              value: field.type,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'TIPO', isDense: true),
              items: [
                for (final entry in mentorshipFieldTypes.entries)
                  DropdownMenuItem(value: entry.key, child: Text(entry.value)),
              ],
              onChanged: (value) =>
                  setState(() => field.type = value ?? field.type),
            ),
          ),
          Tooltip(
            message: 'Obrigatório',
            child: Checkbox(
              value: field.required,
              onChanged: (value) => setState(() => field.required = value ?? false),
            ),
          ),
          IconButton(
            tooltip: 'Remover campo',
            onPressed: () => setState(() => _fields.removeAt(index)),
            icon: const Icon(Icons.delete_outline, size: 18),
          ),
        ]),
        if (field.type == 'select')
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: TextFormField(
              key: ValueKey('field-options-$index-${field.id}'),
              initialValue: field.options.join(', '),
              onChanged: (value) => field.options = [
                for (final part in value.split(','))
                  if (part.trim().isNotEmpty) part.trim(),
              ],
              decoration: const InputDecoration(
                  labelText: 'OPÇÕES (SEPARADAS POR VÍRGULA)', isDense: true),
            ),
          ),
      ]),
    );
  }

  Widget _buildForm(MentorshipForm form) {
    final url = form.url(_baseUrl);
    return _Panel(
      title: 'LINK E DADOS',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (form.description.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(form.description,
                style: const TextStyle(
                    fontSize: 12, color: AssistantTheme.textSecondary)),
          ),
        Row(children: [
          Expanded(
            child: SelectableText(url,
                style: const TextStyle(fontSize: 12, color: AssistantTheme.c1)),
          ),
          IconButton(
              tooltip: 'Copiar link',
              onPressed: () => _copyLink(form),
              icon: const Icon(Icons.copy, size: 18)),
          IconButton(
              tooltip: 'Mostrar QR Code',
              onPressed: () => _showQr(form),
              icon: const Icon(Icons.qr_code_2, size: 20)),
        ]),
        if (isLocalAddress(_baseUrl))
          const _Hint('O endereço do servidor é local: os alunos só abrem um endereço '
              'público.'),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center,
            children: [
          _Chip(form.summary, AssistantTheme.c1),
          _Chip('${form.pending} pendentes', AssistantTheme.c4),
          _Chip('${form.accepted} aceitos', AssistantTheme.c3),
          if (form.closesAt != null)
            _Chip('prazo ${_formatDate(form.closesAt!.toLocal())}',
                AssistantTheme.textMuted),
          OutlinedButton(
            onPressed: _busy ? null : () => _toggleActive(form),
            child: Text(form.active ? 'FECHAR INSCRIÇÕES' : 'REABRIR'),
          ),
          TextButton(
            onPressed: _busy ? null : () => _delete(form),
            child: const Text('APAGAR'),
          ),
        ]),
        const SizedBox(height: 8),
        Text(
          'Campos: matrícula, nome, e-mail, telefone'
          '${form.fields.isEmpty ? '' : ', ${form.fields.map((f) => f.label).join(', ')}'}.',
          style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
      ]),
    );
  }

  Widget _buildSignups(MentorshipForm form) {
    final visible = [
      for (final s in _signups)
        if (_filter == 'all' || s.status == _filter) s,
    ];
    final pending = [for (final s in visible) if (s.status == 'pending') s];
    return _Panel(
      title: 'INSCRITOS',
      trailing: TextButton.icon(
        onPressed: _signups.isEmpty || _busy ? null : () => _copyCsv(form),
        icon: const Icon(Icons.table_view_outlined, size: 16),
        label: const Text('COPIAR CSV'),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, children: [
          for (final entry in const {
            'all': 'Todos',
            'pending': 'Pendentes',
            'accepted': 'Aceitos',
            'rejected': 'Recusados',
            'removed': 'Removidos',
          }.entries)
            ChoiceChip(
              label: Text(entry.value, style: const TextStyle(fontSize: 11)),
              selected: _filter == entry.key,
              onSelected: (_) => setState(() => _filter = entry.key),
            ),
        ]),
        if (pending.length > 1)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: FilledButton.tonalIcon(
              onPressed: _busy ? null : () => _setStatus(form, pending, 'accepted'),
              icon: const Icon(Icons.done_all, size: 16),
              label: Text('ACEITAR ${pending.length} PENDENTES'),
            ),
          ),
        const SizedBox(height: 8),
        if (visible.isEmpty)
          const _Hint('Ninguém por aqui ainda.')
        else
          for (final signup in visible) _buildSignup(form, signup),
      ]),
    );
  }

  Widget _buildSignup(MentorshipForm form, MentorshipSignup signup) {
    final answers = <String>[];
    for (final field in form.fields) {
      final value = signup.answers[field.id];
      if (value == null) continue;
      final text = field.type == 'availability'
          ? availabilityText(value)
          : '$value';
      if (text.isNotEmpty) answers.add('${field.label}: $text');
    }
    final accepted = signup.status == 'accepted';
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AssistantTheme.bg.withOpacity(.4),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AssistantTheme.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center,
            children: [
          Text(signup.name,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
          Text('mat. ${signup.enrollment}',
              style: const TextStyle(
                  fontSize: 11, color: AssistantTheme.textSecondary)),
          if (signup.knownStudent) _Chip('ALUNO CONHECIDO', AssistantTheme.c3),
          _Chip(signup.statusLabel,
              accepted ? AssistantTheme.c3 : AssistantTheme.textMuted),
        ]),
        const SizedBox(height: 4),
        SelectableText('${signup.email}  ·  ${signup.phone}',
            style: const TextStyle(fontSize: 12)),
        for (final line in answers)
          Text(line,
              style: const TextStyle(
                  fontSize: 11, color: AssistantTheme.textSecondary)),
        const SizedBox(height: 6),
        Wrap(spacing: 6, children: [
          if (signup.status != 'accepted')
            FilledButton.tonal(
              onPressed: _busy ? null : () => _setStatus(form, [signup], 'accepted'),
              child: const Text('ACEITAR'),
            ),
          if (signup.status == 'pending')
            OutlinedButton(
              onPressed: _busy ? null : () => _setStatus(form, [signup], 'rejected'),
              child: const Text('RECUSAR'),
            ),
          if (accepted)
            OutlinedButton(
              onPressed: _busy ? null : () => _setStatus(form, [signup], 'removed'),
              child: const Text('REMOVER DA TURMA'),
            ),
        ]),
      ]),
    );
  }
}

String _formatDate(DateTime date) =>
    '${date.day.toString().padLeft(2, '0')}/${date.month.toString().padLeft(2, '0')}'
    '/${date.year}';

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

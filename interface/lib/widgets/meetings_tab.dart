/// Reunião online própria: criar a sala, mandar o link, entrar como professor, ver quem
/// está e a fala transcrita ao vivo, e encerrar.
///
/// Vídeo e áudio passam por um servidor de mídia e não são gravados; só a fala é
/// transcrita, com o nome de quem falou, e fica numa gravação do tipo reunião (que
/// depois se resume como qualquer outra). Quem participa abre o link no navegador, sem
/// instalar nada; o professor entra pelo mesmo navegador, com a chave dele.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/meeting_room.dart';
import '../models/presentation_material.dart' show isLocalAddress;
import '../services/education_service.dart';
import '../utils/theme.dart';

class MeetingsTab extends StatefulWidget {
  /// Trocam serviço, abertura de link e endereço nos testes.
  final EducationService? service;
  final Future<bool> Function(Uri uri)? launcher;
  final String? baseUrl;

  /// De quanto em quanto tempo a tela se atualiza sozinha. Zero desliga (testes).
  final Duration pollEvery;

  const MeetingsTab({
    super.key,
    this.service,
    this.launcher,
    this.baseUrl,
    this.pollEvery = const Duration(seconds: 5),
  });

  @override
  State<MeetingsTab> createState() => _MeetingsTabState();
}

class _MeetingsTabState extends State<MeetingsTab> {
  EducationService get _service => widget.service ?? education;
  String get _baseUrl => widget.baseUrl ?? _service.publicBaseUrl;

  final _title = TextEditingController();
  MeetingConfig? _config;
  List<MeetingRoom> _rooms = const [];
  MeetingDetail? _detail;
  String? _selectedId;
  bool _guests = true;
  int? _max;
  bool _loading = true;
  bool _busy = false;
  bool _error = false;
  String _message = '';
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
      final config = await _service.meetingConfig();
      final rooms = await _service.listMeetings();
      if (!mounted) return;
      setState(() {
        _config = config;
        _rooms = rooms;
        _loading = false;
        _selectedId ??= rooms.where((room) => room.isOpen).isEmpty
            ? null
            : rooms.firstWhere((room) => room.isOpen).id;
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
    if (id == null) return;
    try {
      final detail = await _service.getMeeting(id);
      if (mounted && _selectedId == id) setState(() => _detail = detail);
    } catch (e) {
      _report('Falha ao atualizar a sala: ${_errorText(e)}', error: true);
    }
  }

  /// Atualização silenciosa (a cada poucos segundos): não mexe na mensagem da tela.
  Future<void> _refresh() async {
    if (!mounted || _busy || _loading) return;
    try {
      final rooms = await _service.listMeetings();
      if (mounted) setState(() => _rooms = rooms);
      final id = _selectedId;
      if (id != null) {
        final detail = await _service.getMeeting(id);
        if (mounted && _selectedId == id) setState(() => _detail = detail);
      }
    } catch (_) {
      // Sem rede por um instante: a próxima tentativa resolve.
    }
  }

  Future<void> _create() async {
    final title = _title.text.trim();
    if (title.isEmpty) {
      _report('Dê um título à reunião.', error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final room = await _service.createMeeting(
        title: title,
        guestsAllowed: _guests,
        maxParticipants: _max,
      );
      _title.clear();
      final rooms = await _service.listMeetings();
      if (!mounted) return;
      setState(() {
        _rooms = rooms;
        _selectedId = room.id;
        _detail = null;
      });
      await _loadDetail();
      _report('Reunião criada. Mande o link para a turma e entre como professor.');
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _select(MeetingRoom room) {
    setState(() {
      _selectedId = room.id;
      _detail = null;
    });
    _loadDetail();
  }

  Future<void> _enterAsHost(MeetingRoom room) async {
    final uri = Uri.parse(room.hostUrl(_baseUrl));
    final opened = await (widget.launcher ??
        (Uri target) => launchUrl(target, mode: LaunchMode.externalApplication))(uri);
    _report(
      opened
          ? 'A reunião abriu no navegador. Libere câmera e microfone quando ele pedir.'
          : 'Não consegui abrir o navegador. Copie o link do professor e abra nele.',
      error: !opened,
    );
  }

  Future<void> _copy(MeetingRoom room, {bool host = false}) async {
    await Clipboard.setData(ClipboardData(
        text: host ? room.hostUrl(_baseUrl) : room.joinUrl(_baseUrl)));
    _report(host ? 'Link do professor copiado.' : 'Link da turma copiado.');
  }

  Future<void> _showQr(MeetingRoom room) {
    final url = room.joinUrl(_baseUrl);
    return showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(room.title),
        content: SizedBox(
          width: 320,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Container(
              color: Colors.white,
              padding: const EdgeInsets.all(12),
              child: QrImageView(
                key: const ValueKey('qr-reuniao'),
                data: url,
                version: QrVersions.auto,
                size: 280,
              ),
            ),
            const SizedBox(height: 8),
            SelectableText(url, style: const TextStyle(fontSize: 12)),
          ]),
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

  Future<void> _end(MeetingRoom room) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Encerrar "${room.title}" para todos?'),
        content: const Text(
          'Todos saem da sala agora. A fala transcrita fica no Histórico (tipo '
          'Reunião), pronta para gerar o resumo.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            key: const ValueKey('confirmar-encerrar'),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Encerrar'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => _busy = true);
    try {
      await _service.endMeeting(room.id);
      final rooms = await _service.listMeetings();
      if (mounted) setState(() => _rooms = rooms);
      await _loadDetail();
      _report('Reunião encerrada. A transcrição está no Histórico.');
    } catch (e) {
      _report(_errorText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // --- peças ---------------------------------------------------------------------

  Widget _configBanner() {
    final config = _config;
    if (config == null || config.configured) return const SizedBox.shrink();
    return Container(
      key: const ValueKey('aviso-servidor-de-video'),
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: AssistantTheme.danger),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        'O servidor de vídeo ainda não está configurado. Defina no servidor: '
        '${config.missing.join(', ')}. Use o LiveKit Cloud ou um LiveKit seu; '
        'veja a documentação "Reunião online própria". Até lá dá para criar a '
        'sala, mas ninguém consegue entrar.',
        style: const TextStyle(fontSize: 12, color: AssistantTheme.danger),
      ),
    );
  }

  Widget _createForm() {
    final config = _config;
    final defaultMax = config?.defaultMaxParticipants ?? 30;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('NOVA REUNIÃO',
            style: TextStyle(
                fontSize: 10, letterSpacing: 1.5, color: AssistantTheme.textMuted)),
        const SizedBox(height: 6),
        TextField(
          key: const ValueKey('titulo-reuniao'),
          controller: _title,
          decoration: const InputDecoration(
            labelText: 'Título',
            hintText: 'ex.: Mentoria de outubro',
          ),
        ),
        SwitchListTile(
          key: const ValueKey('aceitar-convidados'),
          dense: true,
          contentPadding: EdgeInsets.zero,
          title: const Text('Aceitar convidados sem matrícula'),
          subtitle: Text(_guests
              ? 'Quem não tem matrícula entra só com o nome.'
              : 'Só entra quem digitar uma matrícula do cadastro.'),
          value: _guests,
          onChanged: _busy ? null : (value) => setState(() => _guests = value),
        ),
        DropdownButtonFormField<int?>(
          key: const ValueKey('limite-pessoas'),
          value: _max,
          decoration: const InputDecoration(labelText: 'Limite de pessoas'),
          items: [
            DropdownMenuItem<int?>(
                value: null, child: Text('Padrão ($defaultMax pessoas)')),
            for (final n in const [8, 12, 20, 30, 50])
              DropdownMenuItem<int?>(value: n, child: Text('$n pessoas')),
          ],
          onChanged: _busy ? null : (value) => setState(() => _max = value),
        ),
        const SizedBox(height: 10),
        FilledButton.icon(
          key: const ValueKey('criar-reuniao'),
          onPressed: _busy ? null : _create,
          icon: const Icon(Icons.video_call_outlined, size: 18),
          label: const Text('CRIAR REUNIÃO'),
        ),
        const SizedBox(height: 6),
        const Text(
          'Câmera e microfone ligados para todos, sem gravar: só a fala de cada um '
          'é transcrita, com o nome. Quem entra aceita isso antes.',
          style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
      ],
    );
  }

  Widget _roomCard(MeetingRoom room) {
    final selected = room.id == _selectedId;
    return InkWell(
      key: ValueKey('sala-${room.id}'),
      onTap: () => _select(room),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          border: Border.all(
              color: selected ? AssistantTheme.c3 : AssistantTheme.border),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(
                child: Text(room.title,
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
              Text(room.isOpen ? 'ABERTA' : 'ENCERRADA',
                  key: ValueKey('estado-${room.id}'),
                  style: TextStyle(
                      fontSize: 10,
                      letterSpacing: 1.2,
                      color: room.isOpen
                          ? AssistantTheme.c3
                          : AssistantTheme.textMuted)),
            ]),
            Text(
              room.isOpen
                  ? '${room.online} online · ${room.people} '
                      'pessoa${room.people == 1 ? '' : 's'} · ${room.segments} falas'
                  : '${room.people} pessoa${room.people == 1 ? '' : 's'} · '
                      '${room.segments} falas transcritas',
              style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
            ),
            if (room.isOpen) ...[
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 4, children: [
                FilledButton.icon(
                  key: ValueKey('entrar-${room.id}'),
                  onPressed: _busy ? null : () => _enterAsHost(room),
                  icon: const Icon(Icons.open_in_new, size: 14),
                  label: const Text('ENTRAR COMO PROFESSOR',
                      style: TextStyle(fontSize: 10)),
                ),
                OutlinedButton.icon(
                  key: ValueKey('copiar-${room.id}'),
                  onPressed: () => _copy(room),
                  icon: const Icon(Icons.copy, size: 14),
                  label: const Text('Link da turma', style: TextStyle(fontSize: 11)),
                ),
                OutlinedButton.icon(
                  key: ValueKey('qr-${room.id}'),
                  onPressed: () => _showQr(room),
                  icon: const Icon(Icons.qr_code_2, size: 14),
                  label: const Text('QR Code', style: TextStyle(fontSize: 11)),
                ),
                TextButton.icon(
                  key: ValueKey('encerrar-${room.id}'),
                  onPressed: _busy ? null : () => _end(room),
                  icon: const Icon(Icons.stop_circle_outlined, size: 14),
                  label: const Text('Encerrar', style: TextStyle(fontSize: 11)),
                ),
              ]),
            ],
          ],
        ),
      ),
    );
  }

  Widget _participants(MeetingDetail detail) {
    if (detail.participants.isEmpty) {
      return const Text('Ninguém entrou ainda.',
          key: ValueKey('sem-participantes'),
          style: TextStyle(color: AssistantTheme.textMuted));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final person in detail.participants)
          Padding(
            key: ValueKey('pessoa-${person.name}'),
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(children: [
              Icon(Icons.circle,
                  size: 10,
                  color: person.online
                      ? AssistantTheme.c3
                      : AssistantTheme.textMuted),
              const SizedBox(width: 8),
              Expanded(child: Text(person.name)),
              Text(person.roleLabel,
                  style: const TextStyle(
                      fontSize: 10, color: AssistantTheme.textMuted)),
              const SizedBox(width: 10),
              Text(formatMeetingDuration(person.seconds),
                  style: const TextStyle(fontSize: 11)),
              const SizedBox(width: 10),
              SizedBox(
                width: 58,
                child: Text(
                  '${person.chunks} fala${person.chunks == 1 ? '' : 's'}',
                  textAlign: TextAlign.right,
                  style: const TextStyle(
                      fontSize: 11, color: AssistantTheme.textMuted),
                ),
              ),
            ]),
          ),
      ],
    );
  }

  Widget _transcript(MeetingDetail detail) {
    if (detail.transcript.isEmpty) {
      return Text(
        detail.room.isOpen
            ? 'A transcrição aparece aqui à medida que as pessoas falam.'
            : 'Ninguém falou nesta reunião.',
        key: const ValueKey('sem-falas'),
        style: const TextStyle(color: AssistantTheme.textMuted),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final line in detail.transcript)
          Padding(
            key: ValueKey('fala-${line.id}'),
            padding: const EdgeInsets.only(bottom: 6),
            child: Text.rich(TextSpan(children: [
              if (line.speaker.isNotEmpty)
                TextSpan(
                    text: '${line.speaker}: ',
                    style: const TextStyle(
                        fontWeight: FontWeight.bold, color: AssistantTheme.c3)),
              TextSpan(text: line.said),
            ])),
          ),
      ],
    );
  }

  Widget _detailPanel() {
    final detail = _detail;
    if (_selectedId == null || detail == null) {
      return const Center(
        child: Text(
          'Escolha uma reunião na lista, ou crie uma, para ver quem está nela e '
          'a transcrição.',
          key: ValueKey('nenhuma-selecionada'),
          style: TextStyle(color: AssistantTheme.textMuted),
        ),
      );
    }
    final room = detail.room;
    return ListView(children: [
      Row(children: [
        Expanded(
          child: Text(room.title,
              key: const ValueKey('titulo-detalhe'),
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        ),
        IconButton(
          key: const ValueKey('atualizar'),
          tooltip: 'Atualizar agora',
          onPressed: _loadDetail,
          icon: const Icon(Icons.refresh, size: 18),
        ),
      ]),
      if (room.isOpen) ...[
        const SizedBox(height: 4),
        SelectableText(room.joinUrl(_baseUrl),
            key: const ValueKey('link-turma'), style: const TextStyle(fontSize: 12)),
        if (isLocalAddress(_baseUrl))
          const Padding(
            padding: EdgeInsets.only(top: 4),
            child: Text(
              'Este endereço só abre neste computador. Os alunos precisam do '
              'endereço público do servidor.',
              key: ValueKey('aviso-endereco-local'),
              style: TextStyle(fontSize: 11, color: AssistantTheme.danger),
            ),
          ),
        TextButton.icon(
          key: const ValueKey('copiar-link-professor'),
          onPressed: () => _copy(room, host: true),
          icon: const Icon(Icons.vpn_key_outlined, size: 14),
          label: const Text('Copiar o link do professor (tem a chave de encerrar)',
              style: TextStyle(fontSize: 11)),
        ),
      ] else
        const Padding(
          padding: EdgeInsets.only(top: 4),
          child: Text(
            'Reunião encerrada. A fala transcrita está no Histórico, no tipo '
            'Reunião: dá para gerar o resumo de lá.',
            key: ValueKey('aviso-encerrada'),
            style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted),
          ),
        ),
      const SizedBox(height: 14),
      Text('NA SALA (${detail.participants.where((p) => p.online).length} online)',
          style: const TextStyle(
              fontSize: 10, letterSpacing: 1.5, color: AssistantTheme.textMuted)),
      const SizedBox(height: 6),
      _participants(detail),
      const SizedBox(height: 14),
      const Text('TRANSCRIÇÃO',
          style: TextStyle(
              fontSize: 10, letterSpacing: 1.5, color: AssistantTheme.textMuted)),
      const SizedBox(height: 6),
      _transcript(detail),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 400,
            child: ListView(children: [
              _configBanner(),
              _createForm(),
              if (_message.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Text(_message,
                      key: const ValueKey('mensagem'),
                      style: TextStyle(
                          fontSize: 12,
                          color: _error
                              ? AssistantTheme.danger
                              : AssistantTheme.c3)),
                ),
              const SizedBox(height: 16),
              const Text('REUNIÕES',
                  style: TextStyle(
                      fontSize: 10,
                      letterSpacing: 1.5,
                      color: AssistantTheme.textMuted)),
              const SizedBox(height: 6),
              if (_rooms.isEmpty)
                const Text('Nenhuma reunião ainda.',
                    key: ValueKey('sem-reunioes'),
                    style: TextStyle(color: AssistantTheme.textMuted)),
              for (final room in _rooms) _roomCard(room),
            ]),
          ),
          const SizedBox(width: 18),
          Expanded(child: _detailPanel()),
        ],
      ),
    );
  }
}

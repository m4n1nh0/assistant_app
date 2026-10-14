/// Link do portal do aluno: copiar, mostrar o QR Code e fechar ou reabrir o acesso.
///
/// O portal é um só por professor: o aluno digita a matrícula e vê resumos das aulas,
/// resultados de quiz em grupo, pontos, materiais e, na mentoria, as atividades. O acesso é
/// só pela matrícula, então vale lembrar quem recebe o link de que a matrícula é a chave.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../models/presentation_material.dart' show isLocalAddress;
import '../services/education_service.dart';
import '../utils/theme.dart';

Future<void> showStudentPortalDialog(
  BuildContext context, {
  EducationService? service,
  String? baseUrl,
}) {
  return showDialog<void>(
    context: context,
    builder: (_) => _StudentPortalDialog(
      service: service ?? education,
      baseUrl: baseUrl ?? (service ?? education).publicBaseUrl,
    ),
  );
}

class _StudentPortalDialog extends StatefulWidget {
  final EducationService service;
  final String baseUrl;

  const _StudentPortalDialog({required this.service, required this.baseUrl});

  @override
  State<_StudentPortalDialog> createState() => _StudentPortalDialogState();
}

class _StudentPortalDialogState extends State<_StudentPortalDialog> {
  String _path = '';
  bool _active = true;
  bool _loading = true;
  bool _busy = false;
  String _message = '';
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  String get _url => '${widget.baseUrl.replaceAll(RegExp(r'/+$'), '')}$_path';

  Future<void> _load() async {
    try {
      final link = await widget.service.studentPortalLink();
      if (!mounted) return;
      setState(() {
        _path = link.path;
        _active = link.active;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _message = 'Falha ao carregar o link: $e'.replaceFirst('Exception: ', '');
        _error = true;
      });
    }
  }

  Future<void> _toggle(bool value) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final link = await widget.service.setStudentPortalActive(value);
      if (!mounted) return;
      setState(() {
        _active = link.active;
        _message = link.active
            ? 'Portal aberto: os alunos já conseguem entrar.'
            : 'Portal fechado: ninguém entra até você reabrir.';
        _error = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _message = '$e'.replaceFirst('Exception: ', '');
        _error = true;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: _url));
    if (!mounted) return;
    setState(() {
      _message = 'Link copiado.';
      _error = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: const Text('Portal do aluno'),
      content: SizedBox(
        width: 460,
        child: _loading
            ? const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()))
            : SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Um link só para todas as turmas e mentorias. O aluno digita a '
                      'matrícula e vê os resumos das aulas, o resultado dos quizzes em '
                      'grupo, os pontos extras, os materiais e, na mentoria, as atividades. '
                      'Tudo aparece sozinho, conforme você gera.',
                      style: TextStyle(fontSize: 12),
                    ),
                    const SizedBox(height: 12),
                    if (_path.isNotEmpty) ...[
                      Row(children: [
                        Expanded(
                          child: SelectableText(_url,
                              style: const TextStyle(
                                  fontSize: 12, color: AssistantTheme.c1)),
                        ),
                        IconButton(
                            tooltip: 'Copiar link',
                            onPressed: _copy,
                            icon: const Icon(Icons.copy, size: 18)),
                      ]),
                      if (isLocalAddress(widget.baseUrl))
                        const Text(
                          'O endereço do servidor é local: os alunos só abrem um endereço '
                          'público.',
                          style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
                        ),
                      const SizedBox(height: 10),
                      Center(
                        child: Container(
                          color: Colors.white,
                          padding: const EdgeInsets.all(10),
                          child: QrImageView(data: _url, size: 170),
                        ),
                      ),
                    ],
                    const SizedBox(height: 10),
                    SwitchListTile(
                      key: const Key('portal-active'),
                      contentPadding: EdgeInsets.zero,
                      dense: true,
                      value: _active,
                      onChanged: _busy ? null : _toggle,
                      title: const Text('Portal aberto', style: TextStyle(fontSize: 13)),
                      subtitle: const Text('Desligue para fechar o acesso sem apagar nada.',
                          style: TextStyle(fontSize: 11)),
                    ),
                    const Text(
                      'Atenção: o acesso é só pela matrícula. Quem souber a matrícula de um '
                      'colega vê os resultados dele. Mande o link só para as turmas.',
                      style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
                    ),
                    if (_message.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(_message,
                            style: TextStyle(
                                fontSize: 12,
                                color: _error ? Colors.redAccent : AssistantTheme.c3)),
                      ),
                  ],
                ),
              ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context), child: const Text('FECHAR')),
      ],
    );
  }
}

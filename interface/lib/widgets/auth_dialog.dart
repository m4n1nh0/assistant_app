import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import '../models/app_config.dart';
import '../services/api_service.dart';
import '../utils/theme.dart';
import 'face_capture_dialog.dart';

class AuthDialog extends StatefulWidget {
  final AppConfig config;
  const AuthDialog({super.key, required this.config});

  @override
  State<AuthDialog> createState() => _AuthDialogState();
}

class _AuthDialogState extends State<AuthDialog> {
  final _pinCtrl = TextEditingController();
  String _status = '';
  bool _showPin = false;
  bool _processing = false;
  final _stt = stt.SpeechToText();
  final _recorder = AudioRecorder();
  bool _sttAvailable = false;
  String? _recordPath;

  @override
  void initState() {
    super.initState();
    _initStt();
  }

  @override
  void dispose() {
    _pinCtrl.dispose();
    _stt.cancel();
    unawaited(_recorder.dispose());
    super.dispose();
  }

  Future<void> _initStt() async {
    if (_shouldUseBackendRecorder) return;
    try {
      _sttAvailable = await _stt.initialize();
    } catch (_) {
      _sttAvailable = false;
    }
  }

  void _setStatus(String msg, {bool error = false}) {
    setState(() => _status = msg);
  }

  Future<void> _authByPin() async {
    final entered = _pinCtrl.text.trim();
    if (entered == widget.config.auth.pin) {
      Navigator.of(context).pop(true);
    } else {
      _setStatus('❌ Código incorreto. Tente novamente.', error: true);
      _pinCtrl.clear();
    }
  }

  // ignore: unused_element
  Future<void> _authByVoiceLegacy() async {
    _setStatus('🎙 Fale sua frase secreta agora...');
    setState(() => _processing = true);

    await _stt.listen(
      localeId: widget.config.language,
      onResult: (result) {
        if (result.finalResult) {
          final said = result.recognizedWords.toLowerCase().trim();
          final expected =
              widget.config.auth.voicePassphrase.toLowerCase().trim();
          setState(() => _processing = false);
          if (said.contains(expected) || expected.contains(said)) {
            Navigator.of(context).pop(true);
          } else {
            _setStatus('❌ Frase não reconhecida: "$said"');
          }
        }
      },
    );
  }

  Future<void> _authByVoice() async {
    if (_processing) return;

    if (_shouldUseBackendRecorder || !_sttAvailable) {
      await _authByRecordedVoice();
      return;
    }

    _setStatus('Fale sua frase secreta agora...');
    setState(() => _processing = true);

    try {
      await _stt.listen(
        localeId: _speechLocale(widget.config.language),
        onResult: (result) {
          if (result.finalResult) {
            final said = result.recognizedWords.toLowerCase().trim();
            if (!mounted) return;
            setState(() => _processing = false);
            _finishVoiceAuth(said);
          }
        },
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _processing = false);
      _setStatus('Erro ao ouvir voz: $e', error: true);
    }
  }

  Future<void> _authByRecordedVoice() async {
    setState(() => _processing = true);
    _setStatus('Fale sua frase secreta. Gravando por alguns segundos...');
    String? path;

    try {
      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        _setStatus('Microfone nao autorizado pelo sistema.', error: true);
        return;
      }

      final supportsWav = await _recorder.isEncoderSupported(AudioEncoder.wav);
      final encoder = supportsWav ? AudioEncoder.wav : AudioEncoder.aacLc;
      final extension = supportsWav ? 'wav' : 'm4a';
      final dir = await getTemporaryDirectory();
      _recordPath =
          '${dir.path}${Platform.pathSeparator}assistant_auth_voice_${DateTime.now().millisecondsSinceEpoch}.$extension';

      await _recorder.start(
        RecordConfig(
          encoder: encoder,
          sampleRate: 16000,
          numChannels: 1,
          noiseSuppress: true,
          echoCancel: true,
        ),
        path: _recordPath!,
      );

      await Future.delayed(const Duration(seconds: 5));
      path = await _recorder.stop();

      final audioPath = path ?? _recordPath;
      if (audioPath == null) {
        _setStatus('Nenhuma gravacao encontrada.', error: true);
        return;
      }

      final file = File(audioPath);
      if (!await file.exists() || await file.length() < 256) {
        _setStatus('Audio muito curto para autenticar.', error: true);
        return;
      }

      _setStatus('Transcrevendo voz...');
      final transcript = await api.transcribeAudio(
        await file.readAsBytes(),
        language: _whisperLanguage(widget.config.language),
      );

      if (!mounted) return;
      _finishVoiceAuth(transcript.toLowerCase().trim());
    } catch (e) {
      if (!mounted) return;
      _setStatus('Erro ao autenticar por voz: $e', error: true);
    } finally {
      if (mounted) {
        setState(() => _processing = false);
      }

      final cleanupPath = path ?? _recordPath;
      _recordPath = null;
      if (cleanupPath != null) {
        try {
          final file = File(cleanupPath);
          if (await file.exists()) await file.delete();
        } catch (_) {}
      }
    }
  }

  bool get _shouldUseBackendRecorder =>
      Platform.isWindows || Platform.isLinux || Platform.isMacOS;

  String _speechLocale(String language) => language.replaceAll('-', '_');

  String _whisperLanguage(String language) =>
      language.split(RegExp('[-_]')).first.toLowerCase();

  void _finishVoiceAuth(String said) {
    final expected = widget.config.auth.voicePassphrase.toLowerCase().trim();
    if (said.isNotEmpty &&
        (said.contains(expected) || expected.contains(said))) {
      Navigator.of(context).pop(true);
    } else {
      _setStatus('Frase nao reconhecida: "$said"', error: true);
    }
  }

  Future<void> _authByFace() async {
    final template = widget.config.auth.faceEmbedding;
    if (template == null || template.isEmpty) {
      _setStatus('Reconhecimento facial ainda nao cadastrado.', error: true);
      return;
    }

    final bytes = await showDialog<List<int>>(
      context: context,
      builder: (_) => const FaceCaptureDialog(
        title: 'RECONHECIMENTO FACIAL',
        actionLabel: 'VERIFICAR',
      ),
    );
    if (bytes == null) return;

    setState(() => _processing = true);
    _setStatus('Comparando rosto...');
    try {
      final result = await api.verifyFace(template, bytes);
      if (!mounted) return;
      setState(() => _processing = false);
      if (result.success) {
        Navigator.of(context).pop(true);
      } else {
        _setStatus(
          result.message.isEmpty ? 'Rosto nao reconhecido.' : result.message,
          error: true,
        );
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _processing = false);
      _setStatus('Erro no reconhecimento facial: $e', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = widget.config.auth;

    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      child: Container(
        width: 400,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: AssistantTheme.border2),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              height: 2,
              decoration: const BoxDecoration(
                borderRadius: BorderRadius.vertical(top: Radius.circular(6)),
                gradient: LinearGradient(colors: [
                  AssistantTheme.c1,
                  AssistantTheme.c2,
                  AssistantTheme.c3
                ]),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(28),
              child: Column(
                children: [
                  Text(
                    '${widget.config.assistantName} — ACESSO',
                    style: const TextStyle(
                      fontFamily: 'Rajdhani',
                      fontSize: 20,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 5,
                      color: AssistantTheme.c1,
                    ),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Autentique sua identidade para continuar',
                    style: TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 11,
                        color: AssistantTheme.textMuted),
                  ),
                  const SizedBox(height: 24),
                  if (auth.pinReady) ...[
                    _AuthBtn(
                      icon: '🔑',
                      label: 'CÓDIGO SECRETO',
                      color: AssistantTheme.c1,
                      onTap: () => setState(() => _showPin = !_showPin),
                    ),
                    if (_showPin) ...[
                      const SizedBox(height: 10),
                      TextField(
                        controller: _pinCtrl,
                        obscureText: true,
                        autofocus: true,
                        style: const TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 13,
                            color: AssistantTheme.textPrimary),
                        decoration: const InputDecoration(
                            hintText: 'Digite seu código...'),
                        onSubmitted: (_) => _authByPin(),
                      ),
                      const SizedBox(height: 8),
                      _AuthBtn(
                          icon: '›',
                          label: 'VERIFICAR',
                          color: AssistantTheme.c3,
                          onTap: _authByPin),
                    ],
                    const SizedBox(height: 8),
                  ],
                  if (auth.voiceReady) ...[
                    _AuthBtn(
                      icon: '🎙',
                      label:
                          _processing ? 'OUVINDO...' : 'RECONHECIMENTO DE VOZ',
                      color: AssistantTheme.c3,
                      onTap: _processing ? null : _authByVoice,
                    ),
                    const SizedBox(height: 8),
                  ],
                  if (auth.faceReady) ...[
                    _AuthBtn(
                      icon: '👤',
                      label: 'RECONHECIMENTO FACIAL',
                      color: AssistantTheme.c2,
                      onTap: _processing ? null : _authByFace,
                    ),
                    const SizedBox(height: 8),
                  ],
                  if (_status.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      _status,
                      style: TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 11,
                        color: _status.startsWith('❌')
                            ? AssistantTheme.danger
                            : AssistantTheme.textSecondary,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AuthBtn extends StatefulWidget {
  final String icon;
  final String label;
  final Color color;
  final VoidCallback? onTap;

  const _AuthBtn(
      {required this.icon,
      required this.label,
      required this.color,
      this.onTap});

  @override
  State<_AuthBtn> createState() => _AuthBtnState();
}

class _AuthBtnState extends State<_AuthBtn> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) => MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 13),
            decoration: BoxDecoration(
              border: Border.all(color: widget.color.withOpacity(0.4)),
              borderRadius: BorderRadius.circular(3),
              color: (_hovered && widget.onTap != null)
                  ? widget.color.withOpacity(0.1)
                  : Colors.transparent,
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(widget.icon, style: const TextStyle(fontSize: 16)),
                const SizedBox(width: 10),
                Text(
                  widget.label,
                  style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 3,
                    color: widget.onTap == null
                        ? widget.color.withOpacity(0.5)
                        : widget.color,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}

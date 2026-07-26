import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:flutter_tts/flutter_tts.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import '../providers/app_provider.dart';
import '../services/api_service.dart';
import '../services/external_launcher_service.dart';
import '../services/installed_apps_service.dart';
import '../services/local_computer_action_service.dart';
import '../services/local_desktop_context_service.dart';
import '../services/local_script_service.dart';
import '../services/local_workspace_service.dart';
import '../services/llm_service.dart';
import '../services/neural_tts_service.dart';
import '../services/shortcut_matching.dart';
import '../models/app_config.dart';
import '../utils/theme.dart';

class ChatPanel extends ConsumerStatefulWidget {
  const ChatPanel({super.key});

  @override
  ConsumerState<ChatPanel> createState() => _ChatPanelState();
}

class _VoiceCommand {
  final String text;
  final bool usedWakeWord;

  const _VoiceCommand(this.text, this.usedWakeWord);
}

class _DetectedScript {
  final String name;
  final String shell;
  final String script;
  final String description;
  final int timeoutSeconds;
  final String sourceLlm;

  const _DetectedScript({
    required this.name,
    required this.shell,
    required this.script,
    required this.description,
    required this.timeoutSeconds,
    required this.sourceLlm,
  });

  String get key => '$shell:${script.trim().replaceAll(RegExp(r'\s+'), ' ')}';
}

class _WorkspaceEditProposal {
  final String summary;
  final List<WorkspaceFileEdit> edits;

  const _WorkspaceEditProposal({
    required this.summary,
    required this.edits,
  });
}

String _visibleChatText(String content, {bool isError = false}) {
  final text = content.trim();
  if (text.isNotEmpty) return text;
  return isError
      ? 'Sem texto no retorno deste agente.'
      : 'Sem texto para exibir.';
}

String _shortVoiceText(String text) {
  final clean = text.trim().replaceAll(RegExp(r'\s+'), ' ');
  if (clean.length <= 90) return clean;
  return '${clean.substring(0, 90)}...';
}

bool _isRoutineVoiceNotice(String content) {
  final text = content.trim().toLowerCase();
  return text.startsWith('microfone ativo') ||
      text.startsWith('gravando voz') ||
      text.startsWith('escuta por voz') ||
      text.startsWith('ouvi "') ||
      text.startsWith('transcricao vazia') ||
      text.startsWith('audio muito curto') ||
      text.startsWith('nao consegui transcrever') ||
      text.startsWith('erro ao gravar voz') ||
      text.startsWith('erro ao capturar voz') ||
      text.startsWith('erro ao transcrever voz') ||
      text.startsWith('microfone nao autorizado');
}

String _parseMarkdown(String text) =>
    text.replaceAll('**', '').replaceAll('__', '').replaceAll('`', '');

class _ChatPanelState extends ConsumerState<ChatPanel> {
  final _inputCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();
  final _stt = stt.SpeechToText();
  final _tts = FlutterTts();
  final _backendTtsPlayer = AudioPlayer();
  final _recorder = AudioRecorder();

  bool _sttAvailable = false;
  bool _backendRecording = false;
  bool _continuousVoiceMode = false;
  bool _oneShotVoiceMode = false;
  bool _voiceLoopRunning = false;
  bool _voicePreferenceSyncing = false;
  final bool _voiceBusy = false;
  bool _backendTtsActive = false;
  StreamSubscription<PlayerState>? _backendTtsStateSub;
  StreamSubscription<void>? _backendTtsCompleteSub;
  String? _directRecordPath;
  String? _voiceStatus;
  DesktopWindowContext? _desktopContext;
  String? _lastWorkspacePath;
  String? _editableWorkspaceRoot;
  bool _workspaceEditingAllowed = false;
  bool _windowPickerBusy = false;
  DateTime? _wakeWordArmedUntil;
  int _wakePromptAttempts = 0;

  @override
  void initState() {
    super.initState();
    _initStt();
    _initTts();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _syncContinuousVoicePreference(ref.read(configProvider));
    });
  }

  Future<void> _initStt() async {
    if (_shouldUseBackendRecorder) {
      _sttAvailable = false;
      return;
    }

    try {
      _sttAvailable = await _stt.initialize(
        onStatus: (s) {
          if (s == 'done' || s == 'notListening') {
            if (!mounted) return;
            if (_continuousVoiceMode) {
              Future.delayed(const Duration(milliseconds: 350), () {
                if (mounted &&
                    _continuousVoiceMode &&
                    !_shouldUseBackendRecorder) {
                  _startLocalSpeechRecognition(announce: false);
                }
              });
            } else {
              ref.read(isRecordingProvider.notifier).state = false;
            }
          }
        },
        onError: (_) {
          if (!mounted) return;
          if (!_continuousVoiceMode) {
            ref.read(isRecordingProvider.notifier).state = false;
          }
        },
      );
    } catch (_) {
      _sttAvailable = false;
    }
  }

  Future<void> _initTts() async {
    final config = ref.read(configProvider);
    await _tts.setLanguage(config.language);
    await _selectVoiceFor(config);
    await _tts.setSpeechRate(_localSpeechRate(config));
    await _tts.setPitch(_localPitch(config));
    await _tts.setVolume(1.0);
    _tts.setStartHandler(
        () => ref.read(isSpeakingProvider.notifier).state = true);
    _tts.setCompletionHandler(
        () => ref.read(isSpeakingProvider.notifier).state = false);
    _tts.setCancelHandler(
        () => ref.read(isSpeakingProvider.notifier).state = false);
    _tts.setErrorHandler(
        (_) => ref.read(isSpeakingProvider.notifier).state = false);
    _backendTtsStateSub ??=
        _backendTtsPlayer.onPlayerStateChanged.listen((state) {
      if (!mounted) return;
      if (!_backendTtsActive) return;
      ref.read(isSpeakingProvider.notifier).state =
          state == PlayerState.playing;
    });
    _backendTtsCompleteSub ??= _backendTtsPlayer.onPlayerComplete.listen((_) {
      if (!mounted) return;
      _backendTtsActive = false;
      ref.read(isSpeakingProvider.notifier).state = false;
    });
  }

  double _localSpeechRate(AppConfig config) =>
      config.assistantGender == 'm' ? 0.5 : 0.52;

  double _localPitch(AppConfig config) =>
      config.assistantGender == 'm' ? 0.98 : 1.08;

  Future<void> _selectVoiceFor(AppConfig config) async {
    try {
      final voices = await _tts.getVoices;
      if (voices is! List) return;

      Map<String, String>? bestVoice;
      var bestScore = -1000;
      for (final voice in voices) {
        if (voice is! Map) continue;

        final name = voice['name']?.toString() ?? '';
        final locale = (voice['locale'] ?? voice['language'] ?? '').toString();
        if (name.isEmpty) continue;

        var score = 0;
        final expectedLocale = config.language.toLowerCase();
        final expectedLanguage = expectedLocale.split('-').first;
        final voiceLocale = locale.toLowerCase();
        final voiceText =
            '$name $locale ${voice['gender'] ?? ''}'.toLowerCase();

        if (voiceLocale == expectedLocale) {
          score += 40;
        } else if (voiceLocale.startsWith(expectedLanguage)) {
          score += 25;
        } else if (!voiceLocale.contains(expectedLanguage)) {
          score -= 15;
        }

        if (_voiceMatchesGender(voiceText, config.assistantGender)) {
          score += 50;
        }
        if (_voiceConflictsGender(voiceText, config.assistantGender)) {
          score -= 55;
        }
        score += _preferredVoiceScore(voiceText, config.assistantGender);
        if (_voiceSoundsNatural(voiceText)) score += 18;
        if (_voiceSoundsRobotic(voiceText)) score -= 24;

        if (score > bestScore) {
          bestScore = score;
          bestVoice = {
            'name': name,
            if (locale.isNotEmpty) 'locale': locale,
          };
        }
      }

      if (bestVoice != null && bestScore >= 0) {
        await _tts.setVoice(bestVoice);
      }
    } catch (_) {}
  }

  bool _voiceMatchesGender(String text, String gender) {
    final female = [
      'female',
      'woman',
      'feminina',
      'feminino',
      'mulher',
      'maria',
      'helena',
      'francisca',
      'fernanda',
      'luciana',
      'leticia',
      'camila',
      'vitoria',
      'yara',
    ];
    final male = [
      'male',
      'man',
      'masculina',
      'masculino',
      'homem',
      'daniel',
      'antonio',
      'ricardo',
    ];
    final terms = gender == 'm' ? male : female;
    return terms.any((term) => _containsVoiceTerm(text, term));
  }

  bool _voiceConflictsGender(String text, String gender) {
    final terms = gender == 'm'
        ? [
            'female',
            'woman',
            'feminina',
            'feminino',
            'mulher',
            'maria',
            'helena',
            'francisca',
          ]
        : [
            'male',
            'man',
            'masculina',
            'masculino',
            'homem',
            'daniel',
            'antonio',
            'ricardo',
          ];
    return terms.any((term) => _containsVoiceTerm(text, term));
  }

  int _preferredVoiceScore(String text, String gender) {
    final preferred = gender == 'm'
        ? {
            'daniel': 32,
            'antonio': 24,
            'ricardo': 20,
          }
        : {
            'francisca': 40,
            'maria': 32,
            'helena': 28,
            'fernanda': 24,
            'luciana': 22,
            'leticia': 22,
            'camila': 20,
            'vitoria': 18,
            'yara': 18,
            'brenda': 16,
          };
    var score = 0;
    for (final entry in preferred.entries) {
      if (_containsVoiceTerm(text, entry.key)) score += entry.value;
    }
    return score;
  }

  bool _voiceSoundsNatural(String text) {
    const terms = [
      'natural',
      'neural',
      'online',
      'premium',
      'enhanced',
      'cloud',
    ];
    return terms.any((term) => _containsVoiceTerm(text, term));
  }

  bool _voiceSoundsRobotic(String text) {
    const terms = [
      'espeak',
      'pico',
      'festival',
      'flite',
      'robot',
      'desktop',
    ];
    return terms.any((term) => _containsVoiceTerm(text, term));
  }

  bool _containsVoiceTerm(String text, String term) {
    if (term == 'male' ||
        term == 'female' ||
        term == 'man' ||
        term == 'woman') {
      return RegExp('(^|[^a-z])$term([^a-z]|\$)').hasMatch(text);
    }
    return text.contains(term);
  }

  Future<void> _toggleVoice() async {
    if (_voiceBusy && !_continuousVoiceMode) return;

    if (_oneShotVoiceMode) {
      await _stopBackendRecordingAndSend();
      return;
    }

    await _tts.stop();
    _backendTtsActive = false;
    await _backendTtsPlayer.stop();
    await _pauseContinuousVoice(clearStatus: false);
    await _startOneShotVoiceRecording();
  }

  Future<void> _syncContinuousVoicePreference(AppConfig config) async {
    if (_voicePreferenceSyncing || _oneShotVoiceMode) return;

    if (config.continuousVoiceMode) {
      if (_continuousVoiceMode || _voiceLoopRunning) return;
      _voicePreferenceSyncing = true;
      try {
        if (_shouldUseBackendRecorder || !_sttAvailable) {
          await _startBackendRecording();
        } else {
          await _startLocalSpeechRecognition();
        }
      } finally {
        _voicePreferenceSyncing = false;
      }
    } else {
      if (!_continuousVoiceMode) return;
      _voicePreferenceSyncing = true;
      try {
        await _pauseContinuousVoice(clearStatus: true);
      } finally {
        _voicePreferenceSyncing = false;
      }
    }
  }

  Future<void> _pauseContinuousVoice({bool clearStatus = true}) async {
    if (!_continuousVoiceMode && !_voiceLoopRunning) return;

    _continuousVoiceMode = false;
    _wakeWordArmedUntil = null;
    _wakePromptAttempts = 0;
    ref.read(isRecordingProvider.notifier).state = _oneShotVoiceMode;

    try {
      if (_backendRecording) {
        final path = await _recorder.stop();
        await _deleteRecording(path);
      } else if (!_shouldUseBackendRecorder) {
        await _stt.stop();
      }
    } catch (_) {
    } finally {
      _backendRecording = false;
      if (clearStatus) {
        _setVoiceStatus('Escuta por voz desativada.', clearAfter: true);
      }
    }

    for (var i = 0; i < 20 && _voiceLoopRunning; i++) {
      await Future.delayed(const Duration(milliseconds: 50));
    }
  }

  Future<void> _startOneShotVoiceRecording() async {
    if (_shouldUseBackendRecorder || !_sttAvailable) {
      await _startOneShotBackendRecording();
      return;
    }

    try {
      _oneShotVoiceMode = true;
      if (mounted) setState(() {});
      ref.read(isRecordingProvider.notifier).state = true;
      _setVoiceStatus('Gravando voz. Clique em PARAR para enviar.');
      await _stt.listen(
        onResult: (result) {
          final words = result.recognizedWords.trim();
          if (words.isEmpty) return;

          _inputCtrl.text = words;
          _inputCtrl.selection =
              TextSelection.collapsed(offset: _inputCtrl.text.length);

          if (result.finalResult) {
            unawaited(_completeLocalOneShot(words));
          }
        },
        localeId: _speechLocale(ref.read(configProvider).language),
      );
    } catch (_) {
      _oneShotVoiceMode = false;
      if (mounted) setState(() {});
      ref.read(isRecordingProvider.notifier).state = false;
      await _startOneShotBackendRecording();
    }
  }

  Future<void> _completeLocalOneShot(String transcript) async {
    _oneShotVoiceMode = false;
    ref.read(isRecordingProvider.notifier).state = false;
    if (mounted) setState(() {});
    await _stt.stop();
    await _sendVoiceTranscript(transcript);
    await _resumeContinuousVoiceIfEnabled();
  }

  Future<void> _startOneShotBackendRecording() async {
    try {
      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        _setVoiceStatus('Microfone nao autorizado pelo sistema.');
        return;
      }

      final supportsWav = await _recorder.isEncoderSupported(AudioEncoder.wav);
      final encoder = supportsWav ? AudioEncoder.wav : AudioEncoder.aacLc;
      final extension = supportsWav ? 'wav' : 'm4a';
      final dir = await getTemporaryDirectory();
      _directRecordPath =
          '${dir.path}${Platform.pathSeparator}assistant_direct_voice_${DateTime.now().millisecondsSinceEpoch}.$extension';

      ref.read(isRecordingProvider.notifier).state = true;
      _oneShotVoiceMode = true;
      _backendRecording = true;
      if (mounted) setState(() {});
      _setVoiceStatus('Gravando voz. Fale a instrucao; vou enviar em 5s.');
      await _recorder.start(
        RecordConfig(
          encoder: encoder,
          sampleRate: 16000,
          numChannels: 1,
          noiseSuppress: true,
          echoCancel: true,
        ),
        path: _directRecordPath!,
      );
      final autoStopPath = _directRecordPath;
      unawaited(Future.delayed(const Duration(seconds: 5), () async {
        if (!mounted ||
            !_oneShotVoiceMode ||
            !_backendRecording ||
            _directRecordPath != autoStopPath) {
          return;
        }
        await _stopBackendRecordingAndSend();
      }));
    } catch (e) {
      _oneShotVoiceMode = false;
      _backendRecording = false;
      _directRecordPath = null;
      if (mounted) setState(() {});
      ref.read(isRecordingProvider.notifier).state = false;
      _setVoiceStatus('Erro ao gravar voz: $e');
    }
  }

  bool get _shouldUseBackendRecorder =>
      Platform.isWindows || Platform.isLinux || Platform.isMacOS;

  Future<void> _startLocalSpeechRecognition({bool announce = true}) async {
    try {
      _continuousVoiceMode = true;
      ref.read(isRecordingProvider.notifier).state = true;
      if (announce) _setVoiceStatus(_voiceReadyMessage());
      await _stt.listen(
        onResult: (result) {
          final words = result.recognizedWords.trim();
          if (words.isEmpty) return;

          _inputCtrl.text = words;
          _inputCtrl.selection =
              TextSelection.collapsed(offset: _inputCtrl.text.length);

          if (result.finalResult) {
            _sendVoiceTranscript(words, requireWakeWord: true);
          }
        },
        localeId: _speechLocale(ref.read(configProvider).language),
        listenFor: const Duration(minutes: 5),
        pauseFor: const Duration(seconds: 3),
      );
    } catch (_) {
      _continuousVoiceMode = false;
      ref.read(isRecordingProvider.notifier).state = false;
      await _startBackendRecording();
    }
  }

  Future<void> _startBackendRecording() async {
    try {
      final hasPermission = await _recorder.hasPermission();
      if (!hasPermission) {
        _setVoiceStatus('Microfone nao autorizado pelo sistema.');
        return;
      }

      _continuousVoiceMode = true;
      ref.read(isRecordingProvider.notifier).state = true;
      _setVoiceStatus(_voiceReadyMessage());
      unawaited(_runBackendVoiceLoop());
    } catch (e) {
      _backendRecording = false;
      _continuousVoiceMode = false;
      ref.read(isRecordingProvider.notifier).state = false;
      _setVoiceStatus('Erro ao gravar voz: $e');
    }
  }

  Future<void> _stopBackendRecordingAndSend() async {
    final oneShotMode = _oneShotVoiceMode || !_continuousVoiceMode;
    String? oneShotPath;
    _continuousVoiceMode = false;
    ref.read(isRecordingProvider.notifier).state = false;
    try {
      if (_backendRecording) {
        oneShotPath = await _recorder.stop() ?? _directRecordPath;
      } else {
        await _stt.stop();
      }
    } catch (_) {
    } finally {
      _backendRecording = false;
      _oneShotVoiceMode = false;
      _directRecordPath = null;
      if (mounted) setState(() {});
      if (oneShotMode && oneShotPath != null) {
        await _transcribeOneShotChunk(oneShotPath);
        await _deleteRecording(oneShotPath);
        await _resumeContinuousVoiceIfEnabled();
      } else {
        _wakeWordArmedUntil = null;
        _setVoiceStatus('Escuta por voz desativada.', clearAfter: true);
      }
    }
  }

  Future<void> _resumeContinuousVoiceIfEnabled() async {
    if (!mounted || !ref.read(configProvider).continuousVoiceMode) return;
    await Future.delayed(const Duration(milliseconds: 250));
    if (!mounted || _oneShotVoiceMode || _continuousVoiceMode) return;
    await _syncContinuousVoicePreference(ref.read(configProvider));
  }

  String _voiceReadyMessage() {
    final assistantName = ref.read(configProvider).assistantName.trim();
    final wakeName = assistantName.isEmpty ? 'Dani' : assistantName;
    final wakeHint = 'Diga "$wakeName," antes do comando.';
    return 'Microfone ativo para instrucoes por voz. $wakeHint Clique em PARAR para desligar.';
  }

  Future<void> _runBackendVoiceLoop() async {
    if (_voiceLoopRunning) return;
    _voiceLoopRunning = true;

    try {
      while (mounted && _continuousVoiceMode) {
        if (ref.read(isSpeakingProvider)) {
          await Future.delayed(const Duration(milliseconds: 300));
          continue;
        }

        final path = await _recordBackendChunk(const Duration(seconds: 5));
        if (!_continuousVoiceMode) {
          await _deleteRecording(path);
          break;
        }

        if (path != null) {
          await _transcribeContinuousChunk(path);
          await _deleteRecording(path);
        }

        await _maybeRepromptForInstruction();
        await Future.delayed(const Duration(milliseconds: 250));
      }
    } finally {
      _voiceLoopRunning = false;
      _backendRecording = false;
      if (mounted && !_continuousVoiceMode) {
        ref.read(isRecordingProvider.notifier).state = false;
      }
    }
  }

  Future<String?> _recordBackendChunk(Duration duration) async {
    String? path;
    try {
      final supportsWav = await _recorder.isEncoderSupported(AudioEncoder.wav);
      final encoder = supportsWav ? AudioEncoder.wav : AudioEncoder.aacLc;
      final extension = supportsWav ? 'wav' : 'm4a';
      final dir = await getTemporaryDirectory();
      path =
          '${dir.path}${Platform.pathSeparator}assistant_voice_${DateTime.now().millisecondsSinceEpoch}.$extension';

      await _recorder.start(
        RecordConfig(
          encoder: encoder,
          sampleRate: 16000,
          numChannels: 1,
          noiseSuppress: true,
          echoCancel: true,
        ),
        path: path,
      );

      _backendRecording = true;
      final endAt = DateTime.now().add(duration);
      while (_backendRecording && DateTime.now().isBefore(endAt)) {
        await Future.delayed(const Duration(milliseconds: 100));
      }
      if (!_backendRecording) return path;
      try {
        path = await _recorder.stop() ?? path;
      } catch (_) {}
      return path;
    } catch (e) {
      if (_continuousVoiceMode) {
        _setVoiceStatus('Erro ao capturar voz: $e');
      }
      return path;
    } finally {
      _backendRecording = false;
    }
  }

  Future<void> _transcribeContinuousChunk(String path) async {
    try {
      final audioFile = File(path);
      if (!await audioFile.exists() || await audioFile.length() < 256) {
        return;
      }

      final config = ref.read(configProvider);
      final transcript = await api.transcribeAudio(
        await audioFile.readAsBytes(),
        language: _whisperLanguage(config.language),
      );

      if (transcript.trim().isEmpty) return;

      final command =
          _voiceCommandFromTranscript(transcript, config.assistantName);
      final now = DateTime.now();
      final isArmed = _wakeWordArmedUntil?.isAfter(now) ?? false;
      if (command.usedWakeWord || isArmed) {
        _showVoiceDraft(transcript);
      } else {
        _setVoiceStatus(
          'Aguardando "Dani". Ouvi: ${_shortVoiceText(transcript)}',
          clearAfter: true,
        );
      }

      if (command.usedWakeWord && command.text.isEmpty) {
        await _promptForInstruction();
        return;
      }

      if (!command.usedWakeWord) {
        if (isArmed) {
          _wakeWordArmedUntil = null;
          _wakePromptAttempts = 0;
          await _sendMessage(transcript.trim(), displayText: transcript.trim());
        }
        return;
      }

      _wakeWordArmedUntil = null;
      _wakePromptAttempts = 0;
      await _sendVoiceTranscript(transcript, requireWakeWord: true);
    } catch (e) {
      if (_continuousVoiceMode) {
        _setVoiceStatus('Erro ao transcrever voz: $e');
      }
    }
  }

  int get _maxWakePromptRetries {
    final value = ref.read(configProvider).voicePromptRetries;
    return value < 1 ? 1 : value;
  }

  Future<void> _promptForInstruction() async {
    if (_wakePromptAttempts >= _maxWakePromptRetries) {
      _wakeWordArmedUntil = null;
      _wakePromptAttempts = 0;
      _setVoiceStatus(
          'Nao ouvi a instrucao. Diga o nome da assistente novamente.');
      return;
    }

    _wakePromptAttempts++;
    _wakeWordArmedUntil = DateTime.now().add(const Duration(seconds: 8));
    final prompt = _wakePromptAttempts == 1
        ? 'Dani ouviu. Qual e a instrucao?'
        : 'Qual e a instrucao?';
    _setVoiceStatus(
      '$prompt ($_wakePromptAttempts/$_maxWakePromptRetries)',
    );
    await _speakVoicePrompt(prompt);
  }

  Future<void> _maybeRepromptForInstruction() async {
    final armedUntil = _wakeWordArmedUntil;
    if (armedUntil == null || armedUntil.isAfter(DateTime.now())) return;
    await _promptForInstruction();
  }

  Future<void> _speakVoicePrompt(String prompt) async {
    if (!ref.read(configProvider).ttsEnabled) return;
    await _speakText(prompt);
  }

  Future<void> _transcribeOneShotChunk(String path) async {
    try {
      final audioFile = File(path);
      if (!await audioFile.exists() || await audioFile.length() < 256) {
        _setVoiceStatus('Audio muito curto para transcrever.');
        return;
      }

      final config = ref.read(configProvider);
      final transcript = await api.transcribeAudio(
        await audioFile.readAsBytes(),
        language: _whisperLanguage(config.language),
      );

      if (transcript.trim().isEmpty) {
        _setVoiceStatus(
            'Nao consegui transcrever o audio. Tente falar mais perto do microfone.');
        return;
      }

      _showVoiceDraft(transcript);
      await _sendVoiceTranscript(transcript);
    } catch (e) {
      _setVoiceStatus('Erro ao transcrever voz: $e');
    }
  }

  Future<void> _deleteRecording(String? path) async {
    if (path == null) return;
    try {
      final file = File(path);
      if (await file.exists()) await file.delete();
    } catch (_) {}
  }

  String _speechLocale(String language) => language.replaceAll('-', '_');

  String _whisperLanguage(String language) =>
      language.split(RegExp('[-_]')).first.toLowerCase();

  Future<void> _sendVoiceTranscript(
    String transcript, {
    bool requireWakeWord = false,
  }) async {
    final raw = transcript.trim();
    if (raw.isEmpty) {
      if (!requireWakeWord) _setVoiceStatus('Transcricao vazia.');
      return;
    }
    _showVoiceDraft(raw);

    final config = ref.read(configProvider);
    final command = _voiceCommandFromTranscript(raw, config.assistantName);
    if (requireWakeWord && !command.usedWakeWord) {
      return;
    }
    if (command.usedWakeWord && command.text.isEmpty) {
      await _promptForInstruction();
      return;
    }

    _wakeWordArmedUntil = null;
    _wakePromptAttempts = 0;
    _inputCtrl.text = raw;
    _inputCtrl.selection = TextSelection.collapsed(offset: raw.length);

    await _sendMessage(command.text, displayText: raw);
  }

  void _showVoiceDraft(String transcript) {
    if (!mounted) return;
    final raw = transcript.trim();
    if (raw.isEmpty) return;
    _inputCtrl.text = raw;
    _inputCtrl.selection = TextSelection.collapsed(offset: raw.length);
  }

  _VoiceCommand _voiceCommandFromTranscript(
      String transcript, String assistantName) {
    final rawWords = _voiceWords(transcript);
    if (rawWords.isEmpty) return _VoiceCommand(transcript, false);
    for (final nameTokens in _wakeNameTokenSets(assistantName)) {
      final maxStart = rawWords.length - nameTokens.length;
      for (var start = 0; start <= maxStart && start <= 6; start++) {
        final candidate = rawWords
            .skip(start)
            .take(nameTokens.length)
            .map(_normalizeVoiceToken)
            .toList();
        if (!_sameTokens(candidate, nameTokens)) continue;

        final prefix = rawWords.take(start).map(_normalizeVoiceToken).toList();
        final prefixIsGreeting = prefix.isEmpty ||
            prefix.every((word) => {
                  'a',
                  'o',
                  'ok',
                  'okay',
                  'oi',
                  'ola',
                  'hey',
                  'ei',
                  'certo',
                  'por',
                  'favor',
                }.contains(word));
        if (!prefixIsGreeting) continue;

        final command = rawWords.skip(start + nameTokens.length).join(' ');
        return _VoiceCommand(_trimVoiceCommand(command), true);
      }
    }

    return _VoiceCommand(transcript, false);
  }

  List<List<String>> _wakeNameTokenSets(String assistantName) {
    final names = <String>[
      assistantName,
      'Dani',
      'Dany',
    ];
    final seen = <String>{};
    final sets = <List<String>>[];
    for (final name in names) {
      final tokens = _normalizedWords(name);
      if (tokens.isEmpty) continue;
      final key = tokens.join(' ');
      if (seen.add(key)) sets.add(tokens);
    }
    return sets;
  }

  List<String> _voiceWords(String text) {
    final words = <String>[];
    final buffer = StringBuffer();

    void flush() {
      final word = buffer.toString().trim();
      if (word.isNotEmpty) words.add(word);
      buffer.clear();
    }

    for (final rune in text.runes) {
      final char = String.fromCharCode(rune);
      if (_normalizeVoiceToken(char).isEmpty) {
        flush();
      } else {
        buffer.write(char);
      }
    }
    flush();
    return words;
  }

  List<String> _normalizedWords(String text) => _voiceWords(text)
      .map(_normalizeVoiceToken)
      .where((word) => word.isNotEmpty)
      .toList();

  bool _sameTokens(List<String> a, List<String> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!_voiceTokenMatches(a[i], b[i])) return false;
    }
    return true;
  }

  bool _voiceTokenMatches(String heard, String expected) {
    if (heard == expected) return true;
    if (heard.length >= 4 && expected.length >= 4) {
      if (heard.contains(expected) || expected.contains(heard)) return true;
      return _editDistanceAtMostOne(heard, expected);
    }
    return false;
  }

  bool _editDistanceAtMostOne(String a, String b) {
    if ((a.length - b.length).abs() > 1) return false;
    var i = 0;
    var j = 0;
    var edits = 0;
    while (i < a.length && j < b.length) {
      if (a[i] == b[j]) {
        i++;
        j++;
        continue;
      }
      edits++;
      if (edits > 1) return false;
      if (a.length > b.length) {
        i++;
      } else if (b.length > a.length) {
        j++;
      } else {
        i++;
        j++;
      }
    }
    if (i < a.length || j < b.length) edits++;
    return edits <= 1;
  }

  String _normalizeVoiceToken(String text) {
    const accentRunes = {
      0x00e1: 'a',
      0x00e0: 'a',
      0x00e2: 'a',
      0x00e3: 'a',
      0x00e4: 'a',
      0x00e9: 'e',
      0x00e8: 'e',
      0x00ea: 'e',
      0x00eb: 'e',
      0x00ed: 'i',
      0x00ec: 'i',
      0x00ee: 'i',
      0x00ef: 'i',
      0x00f3: 'o',
      0x00f2: 'o',
      0x00f4: 'o',
      0x00f5: 'o',
      0x00f6: 'o',
      0x00fa: 'u',
      0x00f9: 'u',
      0x00fb: 'u',
      0x00fc: 'u',
      0x00e7: 'c',
    };
    const accents = {
      'á': 'a',
      'à': 'a',
      'â': 'a',
      'ã': 'a',
      'ä': 'a',
      'é': 'e',
      'è': 'e',
      'ê': 'e',
      'ë': 'e',
      'í': 'i',
      'ì': 'i',
      'î': 'i',
      'ï': 'i',
      'ó': 'o',
      'ò': 'o',
      'ô': 'o',
      'õ': 'o',
      'ö': 'o',
      'ú': 'u',
      'ù': 'u',
      'û': 'u',
      'ü': 'u',
      'ç': 'c',
    };
    final buffer = StringBuffer();
    for (final rune in text.toLowerCase().runes) {
      final char = String.fromCharCode(rune);
      buffer.write(accentRunes[rune] ?? accents[char] ?? char);
    }
    return buffer
        .toString()
        .replaceAll('y', 'i')
        .replaceAll(RegExp(r'[^a-z0-9]'), '');
  }

  String _trimVoiceCommand(String text) =>
      text.trim().replaceFirst(RegExp(r'^[,.:;!?-]+\s*'), '').trim();

  Future<void> _sendMessage(
    String text, {
    String? displayText,
    bool showUserMessage = true,
    bool allowDesktopContext = true,
  }) async {
    final rawApiText = text.trim();
    final shownText = (displayText ?? text).trim();
    if (rawApiText.isEmpty && shownText.isEmpty) return;
    _inputCtrl.clear();

    if (allowDesktopContext &&
        _desktopContext == null &&
        _shouldAskInterfaceForDesktopContext(rawApiText)) {
      _addSystemMsg(
        'Esse pedido parece depender da tela, codigo, documento ou janela aberta. Vou pedir contexto para a interface.',
      );
      _scrollToBottom();
      await _chooseDesktopWindow();
    }

    final selectedContext = _desktopContext;
    var apiText = rawApiText;
    if (selectedContext != null && rawApiText.isNotEmpty) {
      final contextPrompt = selectedContext.contextPrompt.trim();
      if (contextPrompt.isNotEmpty) {
        apiText = '$contextPrompt\n\nPedido do usuario:\n$rawApiText';
      }
    }

    final config = ref.read(configProvider);
    final history = ref.read(chatProvider.notifier).toApiHistory(10);

    if (showUserMessage) {
      final userMsg = ChatMessage(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        role: 'user',
        content: shownText.isEmpty ? rawApiText : shownText,
      );
      ref.read(chatProvider.notifier).addMessage(userMsg);
      _scrollToBottom();
    }

    ref.read(isLoadingProvider.notifier).state = true;

    try {
      final llmSvc = LlmService();

      switch (config.responseMode) {
        case 'multi':
          final result = await llmSvc.callMulti(history, apiText);
          final responses = result.responses;
          final primary = responses.firstWhere(
            (response) => !response.isError,
            orElse: () => responses.first,
          );
          final msg = ChatMessage(
            id: DateTime.now().millisecondsSinceEpoch.toString(),
            role: 'assistant',
            content:
                _visibleChatText(primary.content, isError: primary.isError),
            multiResponses: responses,
          );
          ref.read(chatProvider.notifier).addMessage(msg);
          if (config.ttsEnabled && !primary.isError) {
            await _speakPreview(primary.content, 300);
          }
          await _handleAssistantAction(result);
          await _handleGeneratedScripts(result, shownText);
          await _handleWorkspaceEditProposals(result);

        case 'chain':
          final result = await llmSvc.callChain(history, apiText);
          final resp = result.firstResponse;
          final msg = ChatMessage(
            id: DateTime.now().millisecondsSinceEpoch.toString(),
            role: 'assistant',
            content: _visibleChatText(resp.content, isError: resp.isError),
            llm: resp.llm,
          );
          ref.read(chatProvider.notifier).addMessage(msg);
          if (config.ttsEnabled && !resp.isError) {
            await _speakPreview(resp.content, 300);
          }
          await _handleAssistantAction(result);
          await _handleGeneratedScripts(result, shownText);
          await _handleWorkspaceEditProposals(result);

        default:
          final result = await llmSvc.call(history, apiText);
          final resp = result.firstResponse;
          final msg = ChatMessage(
            id: DateTime.now().millisecondsSinceEpoch.toString(),
            role: 'assistant',
            content: _visibleChatText(resp.content, isError: resp.isError),
            llm: resp.llm,
          );
          ref.read(chatProvider.notifier).addMessage(msg);
          if (config.ttsEnabled && !resp.isError) {
            await _speakPreview(resp.content, 400);
          }
          await _handleAssistantAction(result);
          await _handleGeneratedScripts(result, shownText);
          await _handleWorkspaceEditProposals(result);
      }
    } catch (e) {
      _addSystemMsg('Erro: $e');
    }

    ref.read(isLoadingProvider.notifier).state = false;
    _scrollToBottom();
  }

  Future<void> _speakPreview(String content, int maxLength) async {
    final speech = _speechText(content);
    final preview =
        speech.length > maxLength ? speech.substring(0, maxLength) : speech;
    if (preview.trim().isNotEmpty) await _speakText(preview);
  }

  /// Fala a resposta. A sintese acontece aqui na interface (Edge, vozes
  /// neurais) para nao trafegar o audio de volta do backend, que em producao
  /// fica remoto. Sem rede, cai no TTS do proprio sistema.
  Future<void> _speakText(String text) async {
    final speech = text.trim();
    if (speech.isEmpty) return;

    final config = ref.read(configProvider);
    try {
      final audioBytes = await NeuralTtsService.synthesize(
        speech,
        voice: NeuralTtsService.resolveVoice(
          config.ttsVoice,
          config.assistantGender,
        ),
        ratePercent: config.ttsRatePercent,
        pitchHz: config.ttsPitchHz,
      ).timeout(const Duration(seconds: 12));
      if (audioBytes.isNotEmpty) {
        await _tts.stop();
        await _backendTtsPlayer.stop();
        _backendTtsActive = true;
        ref.read(isSpeakingProvider.notifier).state = true;
        await _backendTtsPlayer.play(BytesSource(audioBytes));
        return;
      }
    } catch (_) {
      _backendTtsActive = false;
      ref.read(isSpeakingProvider.notifier).state = false;
    }

    try {
      _backendTtsActive = false;
      await _backendTtsPlayer.stop();
      await _tts.stop();
      await _tts.speak(speech);
    } catch (_) {
      ref.read(isSpeakingProvider.notifier).state = false;
    }
  }

  Future<void> _chooseDesktopWindow() async {
    if (_windowPickerBusy) return;
    setState(() => _windowPickerBusy = true);

    try {
      List<DesktopWindowInfo> windows;
      try {
        windows = await LocalDesktopContextService.listWindows();
      } catch (_) {
        windows = await api.listDesktopWindows();
      }
      if (!mounted) return;

      if (windows.isEmpty) {
        _addSystemMsg('Nao encontrei janelas abertas para usar como contexto.');
        return;
      }

      final selected = await showDialog<DesktopWindowInfo>(
        context: context,
        builder: (_) => _DesktopWindowPickerDialog(windows: windows),
      );
      if (selected == null || !mounted) return;

      _addSystemMsg('Lendo contexto de: ${selected.displayTitle}');
      _scrollToBottom();

      DesktopWindowContext windowContext;
      try {
        windowContext =
            await LocalDesktopContextService.getWindowContext(selected);
      } catch (_) {
        windowContext = await api.getDesktopWindowContext(selected.id);
      }
      if (!mounted) return;

      setState(() => _desktopContext = windowContext);
      final hasText = windowContext.text.trim().isNotEmpty;
      final detail = hasText
          ? 'Texto acessivel capturado via ${windowContext.extractionMethod}.'
          : 'Usei os metadados da janela; texto interno nao ficou disponivel.';
      final warning = windowContext.warning?.trim();
      _addSystemMsg(
        'Contexto selecionado: ${windowContext.window.displayTitle}. $detail'
        '${warning == null || warning.isEmpty ? '' : ' Aviso: $warning'}',
      );
    } catch (e) {
      _addSystemMsg('Nao consegui acessar as janelas do PC: $e');
    } finally {
      if (mounted) setState(() => _windowPickerBusy = false);
      _scrollToBottom();
    }
  }

  void _clearDesktopContext() {
    if (_desktopContext == null) return;
    setState(() => _desktopContext = null);
    _addSystemMsg('Contexto da janela removido.');
    _scrollToBottom();
  }

  bool _shouldAskInterfaceForDesktopContext(String text) {
    final normalized = _normalizeLoose(text);
    if (normalized.isEmpty) return false;
    if (normalized.contains('contexto local do workspace') ||
        normalized.contains('contexto da janela escolhida pelo usuario')) {
      return false;
    }
    if (_messageAlreadyHasCodeContext(text)) return false;
    final negativeTerms = [
      'sem acessar',
      'sem olhar',
      'nao acesse',
      'nao olhe',
      'nao capture',
      'nao veja',
    ];
    if (negativeTerms.any(normalized.contains)) return false;

    final directTerms = [
      'o que estou fazendo',
      'o que eu estou fazendo',
      'o que estou vendo',
      'o que eu estou vendo',
      'minha tela',
      'a minha tela',
      'na minha tela',
      'tela aberta',
      'janela ativa',
      'janela aberta',
      'janelas abertas',
      'programa aberto',
      'app aberto',
      'ide aberta',
      'editor aberto',
      'arquivo aberto',
      'codigo aberto',
      'codigo fonte',
      'fonte aberto',
      'fonte aberta',
      'projeto aberto',
      'repositorio aberto',
      'documento aberto',
      'texto aberto',
      'word aberto',
      'notepad aberto',
      'bloco de notas aberto',
      'meu codigo',
      'meu codigo fonte',
      'meu fonte',
      'meu projeto',
      'meu documento',
      'meu texto',
      'meu word',
      'meu notepad',
      'meu bloco de notas',
      'minha aplicacao',
      'meu aplicativo',
      'meu app',
      'me ajuda com programacao',
      'ajuda com programacao',
      'me ajuda com codigo',
      'ajuda com codigo',
      'me ajuda com fonte',
      'ajuda com fonte',
      'me ajuda no word',
      'ajuda no word',
      'me ajuda no notepad',
      'ajuda no notepad',
      'me ajuda no bloco de notas',
      'ajuda no bloco de notas',
      'auxilio em fonte',
      'auxilio no word',
      'auxilio no notepad',
      'auxilio no bloco de notas',
      'assistente de codigo',
      'assistente de programacao',
      'erro no meu codigo',
      'bug no meu codigo',
      'deu erro no codigo',
      'consegue ver',
      'voce ve',
      'voce esta vendo',
      'analise a tela',
      'analisa a tela',
      'veja a tela',
      'olhe a tela',
      'olha a tela',
      'nesta janela',
      'nessa janela',
      'nesse programa',
      'neste programa',
      'nesse projeto',
      'neste projeto',
      'neste arquivo',
      'nesse arquivo',
      'nesse documento',
      'neste documento',
      'nesse texto',
      'neste texto',
      'nessa ide',
      'nesta ide',
      'nesse editor',
      'neste editor',
      'no word',
      'no notepad',
      'no bloco de notas',
    ];
    if (directTerms.any(normalized.contains)) return true;

    final requestTerms = [
      'analise',
      'analisa',
      'verifique',
      'verifica',
      'cheque',
      'checa',
      'explique',
      'explica',
      'ajude',
      'ajuda',
      'auxilie',
      'auxilia',
      'auxiliar',
      'auxilio',
      'corrija',
      'corrige',
      'resuma',
      'resumir',
      'entenda',
      'entender',
      'identifique',
      'identifica',
    ];
    final contextTerms = [
      'tela',
      'janela',
      'janelas',
      'ide',
      'editor',
      'codigo',
      'fonte',
      'source',
      'arquivo',
      'documento',
      'doc',
      'docx',
      'texto',
      'txt',
      'word',
      'notepad',
      'bloco de notas',
      'programa',
      'aplicativo',
      'app',
      'pc',
      'computador',
      'desktop',
      'projeto',
      'repositorio',
      'programacao',
      'bug',
      'erro',
      'debug',
      'stacktrace',
      'flutter',
      'dart',
      'python',
      'javascript',
      'typescript',
      'node',
      'backend',
      'frontend',
    ];
    final localCodingCueTerms = [
      'meu',
      'minha',
      'meus',
      'minhas',
      'este',
      'esse',
      'esta',
      'essa',
      'neste',
      'nesse',
      'nesta',
      'nessa',
      'aberto',
      'aberta',
      'atual',
      'aqui',
      'agora',
      'word',
      'notepad',
      'bloco de notas',
    ];
    final wantsHelp = requestTerms.any(normalized.contains);
    final hasContextTerm = contextTerms.any(normalized.contains);
    final hasLocalCue = localCodingCueTerms.any(normalized.contains);
    return wantsHelp && hasContextTerm && hasLocalCue;
  }

  bool _messageAlreadyHasCodeContext(String text) {
    if (text.contains('```')) return true;
    if (text.split(RegExp(r'\r?\n')).length >= 6 &&
        RegExp(r'[{};]|=>|class |def |function |import |Traceback|Exception|Error:',
                caseSensitive: false)
            .hasMatch(text)) {
      return true;
    }
    return false;
  }

  Future<void> _handleAssistantAction(ChatResult result) async {
    if (result.codingAction != null) {
      await _executeCodingAction(result.codingAction!);
      return;
    }
    if (result.computerAction != null) {
      await _executeComputerAction(result.computerAction!);
      return;
    }
    if (result.registrationAction != null) {
      await _registerShortcutFromAction(result.registrationAction!);
      return;
    }
    await _executeLaunchAction(result.action);
  }

  Future<void> _handleGeneratedScripts(
    ChatResult result,
    String userRequest,
  ) async {
    if (result.computerAction != null ||
        result.codingAction != null ||
        result.registrationAction != null ||
        result.action != null ||
        _isLocalScriptResultRequest(userRequest)) {
      return;
    }

    final scripts = _detectScriptsFromResponses(result.responses, userRequest);
    if (scripts.isEmpty) return;

    final savedNames = <String>[];
    final runnableScripts = <_DetectedScript>[];
    final seen = <String>{};
    List<SavedScriptEntry> existing = const [];
    try {
      existing = await api.listSavedScripts('default');
    } catch (_) {}

    for (final script in scripts) {
      if (!seen.add(script.key)) continue;
      runnableScripts.add(script);
      try {
        final saved = await _saveDetectedScript(script, existing);
        if (saved != null) {
          savedNames.add(saved.name);
          existing = [...existing, saved];
        }
      } catch (e) {
        _addSystemMsg('Detectei um script, mas nao consegui salvar: $e');
      }
    }

    if (savedNames.isNotEmpty) {
      final suffix = savedNames.length == 1
          ? savedNames.first
          : '${savedNames.length} scripts';
      _addSystemMsg('Script salvo na biblioteca: $suffix.');
    }

    if (_shouldRunDetectedScript(result.responses, userRequest) &&
        runnableScripts.isNotEmpty) {
      await _confirmAndRunDetectedScript(
        _preferredScriptToRun(runnableScripts),
      );
    }
  }

  Future<void> _handleWorkspaceEditProposals(ChatResult result) async {
    if (!_workspaceEditingAllowed || _editableWorkspaceRoot == null) return;
    if (result.codingAction != null || result.computerAction != null) return;

    final proposal = _extractWorkspaceEditProposal(result.responses);
    if (proposal == null || proposal.edits.isEmpty) return;
    if (!mounted) return;

    final files = proposal.edits.map((edit) => edit.relativePath).join('\n');
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text(
          'Aplicar edicoes no workspace?',
          style: TextStyle(color: AssistantTheme.textPrimary),
        ),
        content: SizedBox(
          width: 520,
          child: SingleChildScrollView(
            child: Text(
              '${proposal.summary.trim().isEmpty ? 'A IA solicitou edicoes.' : proposal.summary.trim()}\n\n'
              'Raiz permitida:\n$_editableWorkspaceRoot\n\n'
              'Arquivos:\n$files',
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 12,
                color: AssistantTheme.textSecondary,
              ),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Aplicar'),
          ),
        ],
      ),
    );

    if (ok != true) {
      _addSystemMsg('Edicoes do workspace canceladas.');
      return;
    }

    try {
      final applied = await LocalWorkspaceService.applyEdits(
        rootPath: _editableWorkspaceRoot!,
        edits: proposal.edits,
      );
      final summary = applied
          .map((item) => '${item.relativePath} (${item.bytesWritten} bytes)')
          .join(', ');
      _addSystemMsg('Edicoes aplicadas: $summary.');
    } catch (e) {
      _addSystemMsg('Nao consegui aplicar edicoes no workspace: $e');
    }
  }

  _WorkspaceEditProposal? _extractWorkspaceEditProposal(
    List<LlmResponse> responses,
  ) {
    final fence = RegExp(
      r'```workspace_edits[ \t]*\r?\n([\s\S]*?)```',
      caseSensitive: false,
      multiLine: true,
    );

    for (final response in responses) {
      if (response.isError) continue;
      for (final match in fence.allMatches(response.content)) {
        final body = match.group(1)?.trim() ?? '';
        if (body.isEmpty) continue;
        try {
          final decoded = jsonDecode(body);
          if (decoded is! Map) continue;
          final rawEdits = decoded['edits'];
          if (rawEdits is! List) continue;
          final edits = <WorkspaceFileEdit>[];
          for (final item in rawEdits) {
            if (item is! Map) continue;
            final path = (item['path'] ?? item['relative_path'] ?? item['file'])
                ?.toString()
                .trim();
            final content = item['content']?.toString();
            if (path == null ||
                path.isEmpty ||
                content == null ||
                content.isEmpty) {
              continue;
            }
            edits.add(WorkspaceFileEdit(
              relativePath: path,
              content: content,
            ));
          }
          if (edits.isEmpty) continue;
          return _WorkspaceEditProposal(
            summary: decoded['summary']?.toString() ?? '',
            edits: edits.take(12).toList(),
          );
        } catch (_) {
          continue;
        }
      }
    }
    return null;
  }

  Future<SavedScriptEntry?> _saveDetectedScript(
    _DetectedScript script,
    List<SavedScriptEntry> existing,
  ) async {
    for (final item in existing) {
      final sameShell = item.shell.trim().toLowerCase() == script.shell;
      final sameScript = item.script.trim().replaceAll(RegExp(r'\s+'), ' ') ==
          script.script.trim().replaceAll(RegExp(r'\s+'), ' ');
      if (sameShell && sameScript) return item;
    }

    return api.createSavedScript(
      tutorId: 'default',
      name: script.name,
      shell: script.shell,
      script: script.script,
      timeoutSeconds: script.timeoutSeconds,
      allowHighRisk: false,
      description: script.description,
    );
  }

  Future<void> _confirmAndRunDetectedScript(_DetectedScript script) async {
    if (!mounted) return;

    final preview = script.script.trim().replaceAll(RegExp(r'\s+'), ' ');
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text(
          'Executar script gerado?',
          style: TextStyle(color: AssistantTheme.textPrimary),
        ),
        content: Text(
          '${script.name}\nShell: ${script.shell}\nTimeout: ${script.timeoutSeconds}s\n\n'
          '${preview.length > 420 ? '${preview.substring(0, 420)}...' : preview}',
          style: const TextStyle(color: AssistantTheme.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Executar'),
          ),
        ],
      ),
    );

    if (ok != true) {
      _addSystemMsg('Execucao do script gerado cancelada.');
      return;
    }

    try {
      _addSystemMsg('Executando script gerado: ${script.name}');
      _scrollToBottom();
      final result = await LocalScriptService.runScript(
        shell: script.shell,
        script: script.script,
        timeoutSeconds: script.timeoutSeconds,
        allowHighRisk: false,
      );
      await _sendMessage(
        _scriptRunAnalysisPrompt(script, result),
        displayText: result.timedOut
            ? 'Analise o timeout do script: ${script.name}'
            : 'Analise o resultado do script: ${script.name}',
        allowDesktopContext: false,
      );
    } catch (e) {
      _addSystemMsg('Nao consegui executar o script gerado: $e');
    }
  }

  String _scriptRunAnalysisPrompt(
    _DetectedScript script,
    ScriptRunResult result,
  ) {
    final buffer = StringBuffer()
      ..writeln('Resultado do script local "${script.name}".')
      ..writeln('Shell: ${result.shell}')
      ..writeln('Comando: ${result.command}')
      ..writeln('Diretorio: ${result.workingDirectory}')
      ..writeln('Exit code: ${result.exitCode}')
      ..writeln('Duracao: ${result.durationMs}ms')
      ..writeln('Timeout: ${result.timedOut ? 'sim' : 'nao'}');
    if (result.timedOut) {
      buffer
        ..writeln()
        ..writeln(
          'O script estourou o limite de ${script.timeoutSeconds}s. '
          'Verifique se ele ficou aguardando entrada interativa, rede lenta, instalacao demorada '
          'ou loop. Sugira proximo passo pratico sem pedir para repetir a mesma execucao.',
        );
    }
    if (result.stdout.trim().isNotEmpty) {
      buffer
        ..writeln()
        ..writeln('STDOUT:')
        ..writeln(result.stdout.trim());
    }
    if (result.stderr.trim().isNotEmpty) {
      buffer
        ..writeln()
        ..writeln('STDERR:')
        ..writeln(result.stderr.trim());
    }
    return buffer.toString().trim();
  }

  List<_DetectedScript> _detectScriptsFromResponses(
    List<LlmResponse> responses,
    String userRequest,
  ) {
    final detected = <_DetectedScript>[];
    for (final response in responses) {
      if (response.isError || response.content.trim().isEmpty) continue;
      detected.addAll(
        _detectScriptsFromText(
          response.content,
          userRequest: userRequest,
          sourceLlm: response.llm,
          startIndex: detected.length,
        ),
      );
    }
    return detected.take(5).toList();
  }

  List<_DetectedScript> _detectScriptsFromText(
    String text, {
    required String userRequest,
    required String sourceLlm,
    required int startIndex,
  }) {
    final scripts = <_DetectedScript>[];
    final fence = RegExp(
      r'```([a-zA-Z0-9_+.-]*)[ \t]*\r?\n([\s\S]*?)```',
      multiLine: true,
    );

    for (final match in fence.allMatches(text)) {
      final rawHint = (match.group(1) ?? '').trim();
      final body = (match.group(2) ?? '').trim();
      if (body.isEmpty) continue;
      final shell = _scriptShell(rawHint, body);
      if (shell == null) continue;
      final index = startIndex + scripts.length + 1;
      scripts.add(
        _DetectedScript(
          name: _generatedScriptName(userRequest, shell, index),
          shell: shell,
          script: body,
          timeoutSeconds: _scriptTimeoutSeconds(body),
          sourceLlm: sourceLlm,
          description:
              'Criado a partir da conversa. Pedido: ${_shortText(userRequest, 180)}',
        ),
      );
    }

    return scripts;
  }

  String? _scriptShell(String hint, String script) {
    final normalizedHint = hint.trim().toLowerCase();
    switch (normalizedHint) {
      case 'powershell':
      case 'ps1':
      case 'ps':
        return 'powershell';
      case 'pwsh':
        return 'pwsh';
      case 'cmd':
      case 'bat':
      case 'batch':
        return 'cmd';
      case 'bash':
      case 'shell':
      case 'shellscript':
        return 'bash';
      case 'sh':
        return 'sh';
      case 'zsh':
        return 'zsh';
    }
    if (normalizedHint.isNotEmpty &&
        !{'text', 'txt', 'console', 'terminal'}.contains(normalizedHint)) {
      return null;
    }
    return _inferShellFromScript(script);
  }

  String? _inferShellFromScript(String script) {
    final text = script.trim().toLowerCase();
    if (text.isEmpty) return null;
    if (text.startsWith('#!/bin/zsh')) return 'zsh';
    if (text.startsWith('#!/bin/sh')) return 'sh';
    if (text.startsWith('#!/bin/bash') ||
        text.startsWith('#!/usr/bin/env bash')) {
      return 'bash';
    }
    if (text.contains('@echo off') ||
        text.contains('%userprofile%') ||
        text.contains('%appdata%')) {
      return 'cmd';
    }
    final powershellTerms = [
      'get-',
      'set-',
      'new-',
      'select-object',
      'where-object',
      'write-output',
      r'$env:',
      r'$_.',
    ];
    if (powershellTerms.any(text.contains)) return 'powershell';
    final shellTerms = [
      'sudo ',
      'apt ',
      'brew ',
      'grep ',
      'awk ',
      'sed ',
      'chmod ',
      'export ',
      'df -',
      'ps aux',
      './',
    ];
    if (shellTerms.any(text.contains)) return Platform.isMacOS ? 'zsh' : 'bash';
    if (Platform.isWindows &&
        (text.contains('ipconfig') ||
            text.contains('ping ') ||
            text.startsWith('dir ') ||
            text.startsWith('echo '))) {
      return 'powershell';
    }
    return null;
  }

  int _scriptTimeoutSeconds(String script) {
    final text = script.toLowerCase();
    final slowTerms = [
      'npm install',
      'pnpm install',
      'yarn install',
      'pip install',
      'docker build',
      'docker compose',
      'winget install',
      'choco install',
      'apt install',
      'brew install',
    ];
    if (slowTerms.any(text.contains)) return 120;
    if (text.split('\n').length > 30) return 90;
    return 60;
  }

  bool _shouldRunDetectedScript(
    List<LlmResponse> responses,
    String userRequest,
  ) {
    final normalizedUser = _normalizeLoose(userRequest);
    if (_userAskedNotToExecuteScript(normalizedUser)) return false;
    if (_userAskedToExecuteScript(userRequest)) return true;
    if (_userAskedForScriptOnly(normalizedUser)) return false;

    final assistantText = responses
        .where((response) => !response.isError)
        .map((response) => response.content)
        .join('\n');
    if (_assistantAskedToExecuteScript(assistantText)) return true;
    return _userAskedForLocalCheck(normalizedUser);
  }

  _DetectedScript _preferredScriptToRun(List<_DetectedScript> scripts) {
    final priority = Platform.isWindows
        ? const ['powershell', 'pwsh', 'cmd', 'bash', 'sh', 'zsh']
        : Platform.isMacOS
            ? const ['zsh', 'bash', 'sh', 'pwsh', 'powershell', 'cmd']
            : const ['bash', 'sh', 'zsh', 'pwsh', 'powershell', 'cmd'];
    for (final shell in priority) {
      for (final script in scripts) {
        if (script.shell == shell) return script;
      }
    }
    return scripts.first;
  }

  bool _assistantAskedToExecuteScript(String text) {
    final normalized = _normalizeLoose(text);
    if (_userAskedNotToExecuteScript(normalized)) return false;
    final directTerms = [
      'copie e execute',
      'copie execute',
      'cole esse comando',
      'cole este comando',
      'execute esse comando',
      'execute este comando',
      'execute o comando',
      'rode esse comando',
      'rode este comando',
      'rode o comando',
      'abra o powershell',
      'abra o terminal',
      'run this command',
      'run the command',
    ];
    if (directTerms.any(normalized.contains)) return true;
    final hasShellHint = normalized.contains('powershell') ||
        normalized.contains('terminal') ||
        normalized.contains('cmd') ||
        normalized.contains('bash') ||
        normalized.contains('shell');
    return hasShellHint &&
        ['execute', 'executar', 'rode', 'rodar', 'cole', 'copie']
            .any(normalized.contains);
  }

  bool _userAskedNotToExecuteScript(String normalized) {
    final terms = [
      'nao execute',
      'nao executar',
      'nao rode',
      'nao rodar',
      'sem executar',
      'sem rodar',
      'apenas salvar',
      'apenas salve',
      'somente salvar',
      'somente salve',
      'so salvar',
      'so salve',
    ];
    return terms.any(normalized.contains);
  }

  bool _userAskedForScriptOnly(String normalized) {
    if (!normalized.contains('script') && !normalized.contains('comando')) {
      return false;
    }
    final terms = [
      'crie',
      'criar',
      'gere',
      'gerar',
      'escreva',
      'monte',
      'salve',
      'mostre',
      'me de',
      'forneca',
      'apenas',
      'somente',
    ];
    return terms.any(normalized.contains);
  }

  bool _userAskedForLocalCheck(String normalized) {
    final intentTerms = [
      'verifique',
      'verifica',
      'verificar',
      'cheque',
      'checa',
      'checar',
      'diagnostique',
      'diagnostica',
      'diagnosticar',
      'analise',
      'analisa',
      'analisar',
      'identifique',
      'identifica',
      'identificar',
      'descubra',
      'descobre',
      'descobrir',
      'obtenha',
      'obter',
      'pegue',
      'pega',
      'pegar',
      'liste',
      'lista',
      'listar',
      'mostre',
      'mostrar',
      'qual meu',
    ];
    final subjectTerms = [
      'ip',
      'rede',
      'dns',
      'gateway',
      'ping',
      'internet',
      'vpn',
      'memoria',
      'ram',
      'disco',
      'cpu',
      'gpu',
      'processo',
      'processos',
      'porta',
      'portas',
      'servico',
      'servicos',
      'sistema',
    ];
    return intentTerms.any(normalized.contains) &&
        subjectTerms.any(normalized.contains);
  }

  String _generatedScriptName(String userRequest, String shell, int index) {
    final text = _normalizeLoose(userRequest);
    String base;
    if (text.contains('backup')) {
      base = 'Backup';
    } else if (text.contains('rede') || text.contains('ip')) {
      base = 'Diagnostico de rede';
    } else if (text.contains('memoria') || text.contains('ram')) {
      base = 'Diagnostico de memoria';
    } else if (text.contains('disco')) {
      base = 'Diagnostico de disco';
    } else {
      base = 'Script ${shell.toUpperCase()}';
    }
    final now = DateTime.now();
    final stamp =
        '${now.hour.toString().padLeft(2, '0')}${now.minute.toString().padLeft(2, '0')}';
    return index == 1 ? '$base $stamp' : '$base $index $stamp';
  }

  bool _userAskedToExecuteScript(String text) {
    final normalized = _normalizeLoose(text);
    final hasScriptContext = normalized.contains('script') ||
        normalized.contains('comando') ||
        normalized.contains('powershell') ||
        normalized.contains('shell') ||
        normalized.contains('bash') ||
        normalized.contains('cmd');
    final executeTerms = [
      'execute',
      'executa',
      'executar',
      'executando',
      'rode',
      'rodar',
      'roda',
      'rodando',
      'manda rodar',
      'testar',
      'teste',
      'dispare',
      'disparar',
    ];
    return hasScriptContext && executeTerms.any(normalized.contains);
  }

  bool _isLocalScriptResultRequest(String text) {
    final normalized = _normalizeLoose(text);
    return normalized.contains('resultado do script local') ||
        normalized.contains('resultado da acao local') ||
        normalized.contains('analise o resultado do script') ||
        normalized.contains('analise o timeout do script');
  }

  String _normalizeLoose(String text) {
    const accentRunes = {
      0x00e1: 'a',
      0x00e0: 'a',
      0x00e2: 'a',
      0x00e3: 'a',
      0x00e4: 'a',
      0x00e9: 'e',
      0x00e8: 'e',
      0x00ea: 'e',
      0x00eb: 'e',
      0x00ed: 'i',
      0x00ec: 'i',
      0x00ee: 'i',
      0x00ef: 'i',
      0x00f3: 'o',
      0x00f2: 'o',
      0x00f4: 'o',
      0x00f5: 'o',
      0x00f6: 'o',
      0x00fa: 'u',
      0x00f9: 'u',
      0x00fb: 'u',
      0x00fc: 'u',
      0x00e7: 'c',
    };
    const accents = {
      'á': 'a',
      'à': 'a',
      'â': 'a',
      'ã': 'a',
      'ä': 'a',
      'é': 'e',
      'è': 'e',
      'ê': 'e',
      'ë': 'e',
      'í': 'i',
      'ì': 'i',
      'î': 'i',
      'ï': 'i',
      'ó': 'o',
      'ò': 'o',
      'ô': 'o',
      'õ': 'o',
      'ö': 'o',
      'ú': 'u',
      'ù': 'u',
      'û': 'u',
      'ü': 'u',
      'ç': 'c',
    };
    final buffer = StringBuffer();
    for (final rune in text.toLowerCase().runes) {
      final char = String.fromCharCode(rune);
      buffer.write(accentRunes[rune] ?? accents[char] ?? char);
    }
    return buffer.toString().replaceAll(RegExp(r'\s+'), ' ').trim();
  }

  String _shortText(String text, int limit) {
    final clean = text.trim().replaceAll(RegExp(r'\s+'), ' ');
    if (clean.length <= limit) return clean;
    return '${clean.substring(0, limit)}...';
  }

  Future<void> _executeCodingAction(CodingAction action) async {
    if (action.actionId != 'inspect_workspace') {
      _addSystemMsg('Acao de codigo nao suportada: ${action.actionId}');
      return;
    }

    final query = action.arguments['query']?.toString() ?? '';
    final defaultRootPath =
        (action.arguments['root_path'] ?? action.arguments['rootPath'])
                ?.toString() ??
            _lastWorkspacePath ??
            '';
    var rootPath = defaultRootPath;
    var allowEdits = false;

    if (action.requiresConfirmation) {
      final permission = await showDialog<_CodingWorkspacePermission>(
        context: context,
        builder: (_) => _CodingWorkspacePermissionDialog(
          title: action.name.trim().isEmpty
              ? 'Modo Codex local'
              : action.name.trim(),
          description: action.description.trim().isEmpty
              ? 'A interface vai ler a estrutura e arquivos importantes do workspace local para enviar como contexto para a IA.'
              : action.description.trim(),
          initialPath: defaultRootPath,
        ),
      );
      if (permission == null) {
        _addSystemMsg('Inspecao de workspace cancelada.');
        return;
      }
      rootPath = permission.rootPath;
      allowEdits = permission.allowEdits;
    }

    try {
      _addSystemMsg('Inspecionando workspace local...');
      _scrollToBottom();

      final snapshot = await LocalWorkspaceService.inspectWorkspace(
        query: query,
        rootPath: rootPath,
        maxTreeFiles: _intArgument(action.arguments['max_files'], 320)
            .clamp(30, 800)
            .toInt(),
        maxFileChars: _intArgument(action.arguments['max_file_chars'], 8000)
            .clamp(1000, 16000)
            .toInt(),
        maxTotalChars: _intArgument(action.arguments['max_total_chars'], 26000)
            .clamp(6000, 60000)
            .toInt(),
      );

      _lastWorkspacePath = snapshot.path;
      _workspaceEditingAllowed = allowEdits;
      _editableWorkspaceRoot = allowEdits ? snapshot.path : null;

      _addSystemMsg(
        'Workspace lido: ${snapshot.name} (${snapshot.scannedFiles} arquivos). '
        '${allowEdits ? 'Edicao autorizada nesta pasta.' : 'Modo somente leitura.'}',
      );
      await _sendMessage(
        snapshot.toPromptText(
          userRequest: query,
          actionName: action.name,
          allowEdits: allowEdits,
        ),
        displayText: 'Analise o workspace local: ${snapshot.name}',
      );
    } catch (e) {
      _addSystemMsg('Nao consegui inspecionar o workspace: $e');
    }
  }

  Future<void> _executeComputerAction(ComputerAction action) async {
    if (action.actionId.trim().isEmpty) return;

    if (action.requiresConfirmation) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text(
            action.name,
            style: const TextStyle(color: AssistantTheme.textPrimary),
          ),
          content: Text(
            action.description,
            style: const TextStyle(color: AssistantTheme.textSecondary),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancelar'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Executar'),
            ),
          ],
        ),
      );
      if (ok != true) {
        _addSystemMsg('Acao local cancelada: ${action.name}');
        return;
      }
    }

    if (action.actionId == 'run_script') {
      await _executeLocalScriptAction(action);
      return;
    }

    try {
      _addSystemMsg('Executando acao local: ${action.name}');
      _scrollToBottom();

      final result = await LocalComputerActionService.runAction(action);
      ref.read(chatProvider.notifier).addMessage(ChatMessage(
            id: DateTime.now().millisecondsSinceEpoch.toString(),
            role: 'assistant',
            content: result.toLocalSummaryText(),
            llm: 'backend',
          ));
      _scrollToBottom();

      final prompt = '''
Resultado da acao local "${result.actionName}" executada neste computador.
Analise os dados abaixo, destaque problemas provaveis e diga os proximos passos praticos.
Nao peca para eu executar de novo os mesmos comandos.

${result.toPromptText()}
''';

      await _sendMessage(
        prompt,
        displayText: 'Analise o resultado local: ${result.actionName}',
        showUserMessage: false,
        allowDesktopContext: false,
      );
    } catch (e) {
      _addSystemMsg('Nao consegui executar ${action.name}: $e');
    }
  }

  Future<void> _executeLocalScriptAction(ComputerAction action) async {
    final script = action.arguments['script']?.toString().trim() ?? '';
    if (script.isEmpty) {
      _addSystemMsg('A acao local nao trouxe um script para executar.');
      return;
    }

    final requestedShell = action.arguments['shell']?.toString().trim() ?? '';
    final shell = requestedShell.isNotEmpty
        ? requestedShell
        : (_scriptShell('', script) ??
            (Platform.isWindows ? 'powershell' : 'bash'));
    final timeoutSeconds = _intArgument(
      action.arguments['timeout_seconds'] ?? action.arguments['timeoutSeconds'],
      60,
    ).clamp(1, 180).toInt();
    final workingDirectory = (action.arguments['working_directory'] ??
                action.arguments['workingDirectory'])
            ?.toString() ??
        '';
    final allowHighRisk = action.arguments['allow_high_risk'] == true ||
        action.arguments['allowHighRisk'] == true;

    final detected = _DetectedScript(
      name: action.name.trim().isEmpty ? 'Script local' : action.name,
      shell: shell,
      script: script,
      description: action.description,
      timeoutSeconds: timeoutSeconds,
      sourceLlm: 'acao local',
    );

    try {
      final existing = await api.listSavedScripts('default');
      final saved = await _saveDetectedScript(detected, existing);
      if (saved != null) {
        _addSystemMsg('Script salvo na biblioteca: ${saved.name}.');
      }
    } catch (e) {
      _addSystemMsg('Detectei o script, mas nao consegui salvar: $e');
    }

    try {
      _addSystemMsg('Executando script local: ${detected.name}');
      _scrollToBottom();
      final result = await LocalScriptService.runScript(
        shell: shell,
        script: script,
        workingDirectory: workingDirectory,
        timeoutSeconds: timeoutSeconds,
        allowHighRisk: allowHighRisk,
      );
      await _sendMessage(
        _scriptRunAnalysisPrompt(detected, result),
        displayText: result.timedOut
            ? 'Analise o timeout do script: ${detected.name}'
            : 'Analise o resultado do script: ${detected.name}',
        allowDesktopContext: false,
      );
    } catch (e) {
      _addSystemMsg('Nao consegui executar o script local: $e');
    }
  }

  int _intArgument(Object? value, int fallback) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '') ?? fallback;
  }

  Future<void> _registerShortcutFromAction(
    ShortcutRegistrationAction action,
  ) async {
    try {
      final existing = await api.listShortcuts('default');
      final candidate = await _resolveShortcutRegistration(action, existing);
      if (candidate == null) {
        final hint = action.query.trim().isNotEmpty
            ? action.query.trim()
            : action.name.trim();
        _addSystemMsg(
          hint.isEmpty
              ? 'Nao encontrei um app para cadastrar.'
              : 'Nao encontrei um app para cadastrar: $hint.',
        );
        return;
      }

      final shortcut = _mergeRegistrationCandidate(action, candidate);
      final existingShortcut = _matchingShortcut(existing, shortcut);
      if (existingShortcut != null) {
        if (action.openAfterRegister) {
          _addSystemMsg(
            'Atalho ja cadastrado: ${existingShortcut.name}. Abrindo agora.',
          );
          await _executeLaunchAction(LaunchAction(
            type: 'launch',
            shortcutId: existingShortcut.id,
            name: existingShortcut.name,
            target: existingShortcut.target,
            targetType: existingShortcut.type,
            browser: existingShortcut.preferredBrowser,
          ));
          return;
        }
        _addSystemMsg('Atalho ja cadastrado: ${existingShortcut.name}.');
        return;
      }

      if (shortcut.type == 'command' &&
          !_isSupportedShortcutCommand(shortcut.target)) {
        _addSystemMsg('Comando de atalho nao suportado para cadastro.');
        return;
      }

      final created = await api.createShortcut(
        tutorId: 'default',
        name: shortcut.name,
        type: shortcut.type,
        target: shortcut.target,
        aliases: shortcut.aliases,
        description: shortcut.description,
      );
      if (action.openAfterRegister) {
        _addSystemMsg('Atalho cadastrado: ${shortcut.name}. Abrindo agora.');
        await _executeLaunchAction(LaunchAction(
          type: 'launch',
          shortcutId: created.id,
          name: created.name,
          target: created.target,
          targetType: created.type,
          browser: created.preferredBrowser,
        ));
        return;
      }

      _addSystemMsg(
        'Atalho cadastrado: ${shortcut.name}. Agora diga: abra ${shortcut.name}.',
      );
    } catch (e) {
      _addSystemMsg('Nao consegui cadastrar o atalho: $e');
    }
  }

  Future<InstalledAppCandidate?> _resolveShortcutRegistration(
    ShortcutRegistrationAction action,
    List<ShortcutEntry> existing,
  ) async {
    final target = action.target.trim();
    if (target.isNotEmpty) {
      final normalizedTarget =
          action.isUrl ? _normalizeShortcutUrl(target) : target;
      if (action.isCommand && !_isSupportedShortcutCommand(normalizedTarget)) {
        return null;
      }
      return InstalledAppCandidate(
        name: _firstNonEmpty([action.name, action.query, normalizedTarget]),
        target: normalizedTarget,
        type: action.targetType,
        aliases: action.aliases,
        description: action.description ?? 'Solicitado pelo chat.',
        reason: 'Destino informado pelo chat.',
        source: 'chat',
      );
    }

    final inlineUrl = _urlFromText('${action.name} ${action.query}');
    if (inlineUrl != null) {
      return InstalledAppCandidate(
        name: _firstNonEmpty([action.name, action.query, inlineUrl]),
        target: inlineUrl,
        type: 'url',
        aliases: action.aliases,
        description: action.description ?? 'Solicitado pelo chat.',
        reason: 'URL identificada no pedido.',
        source: 'chat',
      );
    }

    final installed = await InstalledAppsService.discover();
    final installedMatch = _bestRegistrationCandidate(action, installed);
    if (installedMatch != null) return installedMatch;

    final recommendations = await InstalledAppsService.recommendForProfile(
      profile: 'developer',
      existingNames: existing.map((item) => item.name),
      existingTargets: existing.map((item) => item.target),
    );
    final recoMatch = _bestRegistrationCandidate(action, recommendations);
    if (recoMatch != null) return recoMatch;

    // Fallback: ask backend to find the command via 'where' + LLM knowledge
    final suggestedPath = await api.suggestCommand(action.name);
    if (suggestedPath != null && suggestedPath.isNotEmpty) {
      return LaunchCommandAgent.prepare(InstalledAppCandidate(
        name: _firstNonEmpty([action.name, action.query]),
        target: suggestedPath,
        type: 'app',
        sourceTarget: suggestedPath,
        aliases: action.aliases,
        description: 'Localizado via IA.',
        reason: 'Sugerido pelo assistente com base no nome digitado.',
      ));
    }
    return null;
  }

  InstalledAppCandidate _mergeRegistrationCandidate(
    ShortcutRegistrationAction action,
    InstalledAppCandidate candidate,
  ) {
    final aliases = <String>{
      ...candidate.aliases,
      ...action.aliases,
      action.name,
      action.query,
    }
        .map((item) => item.trim().toLowerCase())
        .where((item) => item.length > 1)
        .toSet()
        .toList()
      ..sort();

    final descriptionParts = [
      action.description,
      candidate.description,
      candidate.reason,
      if (candidate.launchCommand.trim().isNotEmpty)
        'Comando: ${candidate.launchCommand.trim()}',
    ]
        .whereType<String>()
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toSet()
        .toList();

    return InstalledAppCandidate(
      name: _firstNonEmpty([candidate.name, action.name, action.query]),
      target: candidate.isUrl
          ? _normalizeShortcutUrl(candidate.target)
          : candidate.target,
      type: candidate.type,
      sourceTarget: candidate.sourceTarget,
      launchCommand: candidate.launchCommand,
      aliases: aliases,
      description: descriptionParts.join('\n'),
      reason: candidate.reason,
      source: candidate.source,
      score: candidate.score,
    );
  }

  InstalledAppCandidate? _bestRegistrationCandidate(
    ShortcutRegistrationAction action,
    List<InstalledAppCandidate> candidates,
  ) =>
      ShortcutMatching.bestCandidate(action, candidates);

  ShortcutEntry? _matchingShortcut(
    List<ShortcutEntry> shortcuts,
    InstalledAppCandidate candidate,
  ) =>
      ShortcutMatching.matchingShortcut(shortcuts, candidate);

  bool _isSupportedShortcutCommand(String payload) =>
      ShortcutMatching.isSupportedCommand(payload);

  String _firstNonEmpty(List<String> values) {
    for (final value in values) {
      final trimmed = value.trim();
      if (trimmed.isNotEmpty) return trimmed;
    }
    return 'Atalho';
  }

  String _normalizeShortcutUrl(String rawUrl) {
    final url = rawUrl.trim().replaceAll(RegExp(r'[.,;]+$'), '');
    if (url.toLowerCase().startsWith('http://') ||
        url.toLowerCase().startsWith('https://')) {
      return url;
    }
    return 'https://$url';
  }

  String? _urlFromText(String text) {
    final match = RegExp(
      r'\b((?:https?:\/\/|www\.)[^\s,;]+|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s,;]*)?)',
      caseSensitive: false,
    ).firstMatch(text);
    final raw = match?.group(1);
    if (raw == null || raw.trim().isEmpty) return null;
    return _normalizeShortcutUrl(raw);
  }

  Future<void> _executeLaunchAction(LaunchAction? action) async {
    if (action == null || action.target.trim().isEmpty) return;

    try {
      if (action.isUrl) {
        await ExternalLauncherService.openUrl(action.target,
            browser: action.browser);
      } else if (action.isCommand) {
        await ExternalLauncherService.runLaunchCommand(action.target);
      } else {
        await ExternalLauncherService.openTarget(action.target);
      }
      try {
        await api.confirmShortcutLaunched(
          action.shortcutId,
          platform: Platform.operatingSystem,
          request: {
            'action': action.type,
            'name': action.name,
            'target_type': action.targetType,
            if (action.browser.trim().isNotEmpty) 'browser': action.browser,
          },
          result: {
            'target': action.target,
            if (action.browser.trim().isNotEmpty) 'browser': action.browser,
          },
        );
      } catch (_) {}
      _addSystemMsg('Ação executada: ${action.name}');
    } catch (e) {
      try {
        await api.confirmShortcutLaunched(
          action.shortcutId,
          status: 'failed',
          platform: Platform.operatingSystem,
          request: {
            'action': action.type,
            'name': action.name,
            'target_type': action.targetType,
            if (action.browser.trim().isNotEmpty) 'browser': action.browser,
          },
          error: e.toString(),
        );
      } catch (_) {}
      _addSystemMsg('Não consegui abrir ${action.name}: $e');
    }
  }

  String _speechText(String content) {
    var text = content;
    text = text.replaceAll(RegExp(r'```[\s\S]*?```'), ' ');
    text = text.replaceAllMapped(
      RegExp(r'\[([^\]]+)\]\([^)]+\)'),
      (match) => match.group(1) ?? '',
    );
    text = text.replaceAllMapped(
      RegExp(r'`([^`]+)`'),
      (match) => match.group(1) ?? '',
    );
    text = text.replaceAll(RegExp(r'[*_#>`~]+'), ' ');
    text = text.replaceAll(RegExp(r'^\s*[-+]\s+', multiLine: true), '');
    text = text.replaceAll(RegExp(r'\s+'), ' ');
    return text.trim();
  }

  void _addSystemMsg(String content) {
    ref.read(chatProvider.notifier).addMessage(ChatMessage(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          role: 'system',
          content: content,
        ));
  }

  void _setVoiceStatus(String? content, {bool clearAfter = false}) {
    if (!mounted) return;
    setState(() => _voiceStatus = content);
    if (clearAfter && content != null) {
      Future.delayed(const Duration(seconds: 3), () {
        if (!mounted || _voiceStatus != content) return;
        setState(() => _voiceStatus = null);
      });
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    _inputCtrl.dispose();
    _scrollCtrl.dispose();
    _stt.cancel();
    _tts.stop();
    _backendTtsActive = false;
    unawaited(_backendTtsStateSub?.cancel());
    unawaited(_backendTtsCompleteSub?.cancel());
    unawaited(_backendTtsPlayer.dispose());
    unawaited(_recorder.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final messages = ref.watch(chatProvider);
    final visibleMessages = messages.where((msg) {
      if (msg.role == 'system' && _isRoutineVoiceNotice(msg.content)) {
        return false;
      }
      return true;
    }).toList();
    final isLoading = ref.watch(isLoadingProvider);
    final isRec = ref.watch(isRecordingProvider);
    final config = ref.watch(configProvider);
    ref.listen<QueuedChatCommand?>(queuedChatCommandProvider, (previous, next) {
      if (next == null || previous?.id == next.id) return;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _sendMessage(next.text);
        ref.read(queuedChatCommandProvider.notifier).state = null;
      });
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _syncContinuousVoicePreference(config);
    });

    return Container(
      decoration: const BoxDecoration(
        border: Border(
          left: BorderSide(color: AssistantTheme.border),
          right: BorderSide(color: AssistantTheme.border),
        ),
      ),
      child: Column(
        children: [
          _ChatHeader(config: config),
          Expanded(
            child: ListView.builder(
              controller: _scrollCtrl,
              padding: const EdgeInsets.all(20),
              itemCount: visibleMessages.length + (isLoading ? 1 : 0),
              itemBuilder: (_, i) {
                if (i == visibleMessages.length) {
                  return const _TypingIndicator();
                }
                final msg = visibleMessages[i];
                return msg.multiResponses != null
                    ? _MultiResponseCard(msg: msg, config: config)
                        .animate()
                        .fadeIn(duration: 250.ms)
                        .slideY(begin: 0.05)
                    : _MessageBubble(msg: msg, config: config)
                        .animate()
                        .fadeIn(duration: 250.ms)
                        .slideY(begin: 0.05);
              },
            ),
          ),
          _InputArea(
            controller: _inputCtrl,
            isListening: isRec || _continuousVoiceMode,
            isDirectRecording: _oneShotVoiceMode,
            isVoiceBusy: _voiceBusy,
            isWindowPickerBusy: _windowPickerBusy,
            sendOnEnter: config.sendMessageOnEnter,
            voiceStatus: _voiceStatus,
            desktopContextLabel: _desktopContext?.label,
            onSend: () => _sendMessage(_inputCtrl.text),
            onVoice: _toggleVoice,
            onPickWindow: _chooseDesktopWindow,
            onClearWindowContext: _clearDesktopContext,
            onClear: () => ref.read(chatProvider.notifier).clear(),
          ),
        ],
      ),
    );
  }
}

class _CodingWorkspacePermission {
  final String rootPath;
  final bool allowEdits;

  const _CodingWorkspacePermission({
    required this.rootPath,
    required this.allowEdits,
  });
}

class _CodingWorkspacePermissionDialog extends StatefulWidget {
  final String title;
  final String description;
  final String initialPath;

  const _CodingWorkspacePermissionDialog({
    required this.title,
    required this.description,
    required this.initialPath,
  });

  @override
  State<_CodingWorkspacePermissionDialog> createState() =>
      _CodingWorkspacePermissionDialogState();
}

class _CodingWorkspacePermissionDialogState
    extends State<_CodingWorkspacePermissionDialog> {
  late final TextEditingController _pathCtrl;
  bool _allowEdits = false;
  bool _picking = false;
  String? _status;

  @override
  void initState() {
    super.initState();
    _pathCtrl = TextEditingController(text: widget.initialPath);
  }

  @override
  void dispose() {
    _pathCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickDirectory() async {
    if (_picking) return;
    setState(() {
      _picking = true;
      _status = null;
    });
    try {
      final picked = await LocalWorkspaceService.pickDirectory(
        initialPath: _pathCtrl.text.trim(),
      );
      if (!mounted) return;
      if (picked == null || picked.trim().isEmpty) {
        setState(() => _status = 'Selecao cancelada.');
        return;
      }
      setState(() {
        _pathCtrl.text = picked.trim();
        _status = 'Pasta selecionada.';
      });
    } catch (e) {
      if (mounted) setState(() => _status = 'Nao consegui abrir seletor: $e');
    } finally {
      if (mounted) setState(() => _picking = false);
    }
  }

  void _confirm() {
    Navigator.pop(
      context,
      _CodingWorkspacePermission(
        rootPath: _pathCtrl.text.trim(),
        allowEdits: _allowEdits,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.folder_open,
                      size: 18, color: AssistantTheme.c1),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      widget.title.toUpperCase(),
                      style: const TextStyle(
                        fontFamily: 'Rajdhani',
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 3,
                        color: AssistantTheme.textPrimary,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Fechar',
                    icon: const Icon(Icons.close, size: 18),
                    color: AssistantTheme.textSecondary,
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                widget.description,
                style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 12,
                  color: AssistantTheme.textSecondary,
                ),
              ),
              const SizedBox(height: 16),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: TextField(
                      controller: _pathCtrl,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 12,
                        color: AssistantTheme.textPrimary,
                      ),
                      decoration: const InputDecoration(
                        labelText: 'Diretorio do workspace',
                        hintText: 'Vazio = detectar automaticamente',
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  SizedBox(
                    height: 48,
                    child: ElevatedButton.icon(
                      onPressed: _picking ? null : _pickDirectory,
                      icon: Icon(
                        _picking ? Icons.hourglass_empty : Icons.folder,
                        size: 16,
                      ),
                      label: const Text('Selecionar'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              CheckboxListTile(
                value: _allowEdits,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                activeColor: AssistantTheme.c3,
                title: const Text(
                  'Permitir edicoes nesta pasta',
                  style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
                subtitle: const Text(
                  'A IA recebe essa permissao no contexto, mas a interface continua limitada ao diretorio selecionado.',
                  style: TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 11,
                    color: AssistantTheme.textSecondary,
                  ),
                ),
                onChanged: (value) =>
                    setState(() => _allowEdits = value == true),
              ),
              if (_status?.trim().isNotEmpty ?? false) ...[
                const SizedBox(height: 8),
                Text(
                  _status!,
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 11,
                    color: AssistantTheme.textSecondary,
                  ),
                ),
              ],
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Cancelar'),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    onPressed: _confirm,
                    child: const Text('Inspecionar'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DesktopWindowPickerDialog extends StatefulWidget {
  final List<DesktopWindowInfo> windows;

  const _DesktopWindowPickerDialog({required this.windows});

  @override
  State<_DesktopWindowPickerDialog> createState() =>
      _DesktopWindowPickerDialogState();
}

class _DesktopWindowPickerDialogState
    extends State<_DesktopWindowPickerDialog> {
  final _filterCtrl = TextEditingController();
  String _filter = '';

  @override
  void dispose() {
    _filterCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filter = _filter.trim().toLowerCase();
    final windows = filter.isEmpty
        ? widget.windows
        : widget.windows.where((window) {
            final text =
                '${window.title} ${window.processName} ${window.executablePath}'
                    .toLowerCase();
            return text.contains(filter);
          }).toList();

    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 660, maxHeight: 560),
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 14, 10, 10),
              child: Row(
                children: [
                  const Icon(Icons.web_asset,
                      size: 18, color: AssistantTheme.c2),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Text(
                      'JANELAS ABERTAS',
                      style: TextStyle(
                        fontFamily: 'Rajdhani',
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 3,
                        color: AssistantTheme.textPrimary,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Fechar',
                    icon: const Icon(Icons.close, size: 18),
                    color: AssistantTheme.textSecondary,
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 0, 18, 12),
              child: TextField(
                controller: _filterCtrl,
                style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 12,
                  color: AssistantTheme.textPrimary,
                ),
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search, size: 18),
                  hintText: 'Filtrar por titulo ou processo',
                ),
                onChanged: (value) => setState(() => _filter = value),
              ),
            ),
            Expanded(
              child: windows.isEmpty
                  ? const Center(
                      child: Text(
                        'Nenhuma janela encontrada.',
                        style: TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 12,
                          color: AssistantTheme.textSecondary,
                        ),
                      ),
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.fromLTRB(14, 0, 14, 16),
                      itemCount: windows.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (_, index) {
                        final window = windows[index];
                        return _DesktopWindowTile(
                          window: window,
                          onTap: () => Navigator.pop(context, window),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DesktopWindowTile extends StatelessWidget {
  final DesktopWindowInfo window;
  final VoidCallback onTap;

  const _DesktopWindowTile({
    required this.window,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(4),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            border: Border.all(
              color: window.isActive
                  ? AssistantTheme.c3.withOpacity(0.55)
                  : AssistantTheme.border,
            ),
            borderRadius: BorderRadius.circular(4),
            color: window.isActive
                ? AssistantTheme.c3.withOpacity(0.06)
                : AssistantTheme.bg2,
          ),
          child: Row(
            children: [
              Icon(
                window.isActive ? Icons.radio_button_checked : Icons.web_asset,
                size: 16,
                color: window.isActive
                    ? AssistantTheme.c3
                    : AssistantTheme.textSecondary,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      window.displayTitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 12,
                        color: AssistantTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${window.displayProcess}  PID ${window.processId}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 10,
                        color: AssistantTheme.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              if (window.isActive) ...[
                const SizedBox(width: 10),
                const Text(
                  'ATIVA',
                  style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 2,
                    color: AssistantTheme.c3,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ChatHeader extends StatelessWidget {
  final AppConfig config;
  const _ChatHeader({required this.config});

  @override
  Widget build(BuildContext context) {
    final llmColors = {
      'backend': AssistantTheme.c1,
      'claude': AssistantTheme.c4,
      'gpt': AssistantTheme.c3,
      'gemini': AssistantTheme.c1,
      'together': AssistantTheme.c1,
      'openrouter': AssistantTheme.c2,
      'deepseek': AssistantTheme.cHF,
      'grok': AssistantTheme.c5,
      'localai': AssistantTheme.c3,
      'llama': AssistantTheme.c2,
      'hf': AssistantTheme.cHF,
    };
    final services =
        config.activeList.isEmpty ? ['backend'] : config.activeList;

    return Container(
      height: 44,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AssistantTheme.border)),
        color: Color(0xFF090C13),
      ),
      child: Row(
        children: [
          Text(
            'CONVERSA',
            style: TextStyle(
              fontFamily: 'Rajdhani',
              fontSize: 12,
              fontWeight: FontWeight.w700,
              letterSpacing: 4,
              color: AssistantTheme.textSecondary,
            ),
          ),
          const SizedBox(width: 12),
          ...services.map((llm) => Padding(
                padding: const EdgeInsets.only(right: 6),
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    border: Border.all(
                        color: (llmColors[llm] ?? AssistantTheme.c1)
                            .withOpacity(0.5)),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    config.serviceName(llm).toUpperCase(),
                    style: TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 8,
                      letterSpacing: 1,
                      color: llmColors[llm] ?? AssistantTheme.c1,
                    ),
                  ),
                ),
              )),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final ChatMessage msg;
  final AppConfig config;
  const _MessageBubble({required this.msg, required this.config});

  @override
  Widget build(BuildContext context) {
    final isUser = msg.role == 'user';
    final isSystem = msg.role == 'system';
    final visibleContent = _visibleChatText(msg.content);

    if (isSystem) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              border: Border.all(color: AssistantTheme.c2.withOpacity(0.2)),
              borderRadius: BorderRadius.circular(3),
              color: AssistantTheme.c2.withOpacity(0.04),
            ),
            child: _ChatText(
              text: _parseMarkdown(visibleContent),
              color: AssistantTheme.c2,
              fontSize: 11,
              textAlign: TextAlign.center,
            ),
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment:
            isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment:
                isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
            children: [
              if (!isUser && msg.llm != null)
                Container(
                  margin: const EdgeInsets.only(right: 8),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
                  decoration: BoxDecoration(
                    border: Border.all(
                        color: (AssistantTheme.llmColors[msg.llm] ??
                                AssistantTheme.c1)
                            .withOpacity(0.4)),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    config.serviceName(msg.llm!).toUpperCase(),
                    style: TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 8,
                      color: AssistantTheme.llmColors[msg.llm] ??
                          AssistantTheme.c1,
                    ),
                  ),
                ),
              Text(
                isUser ? 'VOCÊ' : 'ASSISTENTE',
                style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9,
                  letterSpacing: 2,
                  color: isUser ? AssistantTheme.c3 : AssistantTheme.c1,
                ),
              ),
              const SizedBox(width: 8),
              Text(
                _formatTime(msg.timestamp),
                style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9,
                  color: AssistantTheme.textMuted,
                ),
              ),
            ],
          ),
          const SizedBox(height: 5),
          Row(
            mainAxisAlignment:
                isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 680),
                child: GestureDetector(
                  onSecondaryTapDown: (d) =>
                      _showContextMenu(context, d.globalPosition, msg.content),
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: isUser
                                ? AssistantTheme.c3.withOpacity(0.05)
                                : AssistantTheme.c1.withOpacity(0.04),
                            border: Border.all(
                              color: (isUser
                                      ? AssistantTheme.c3
                                      : AssistantTheme.c1)
                                  .withOpacity(0.15),
                            ),
                            borderRadius: BorderRadius.circular(3),
                          ),
                        ),
                      ),
                      Positioned(
                        top: 0,
                        bottom: 0,
                        left: isUser ? null : 0,
                        right: isUser ? 0 : null,
                        child: Container(
                          width: 2,
                          decoration: BoxDecoration(
                            color:
                                isUser ? AssistantTheme.c3 : AssistantTheme.c1,
                            borderRadius: BorderRadius.horizontal(
                              left: isUser
                                  ? Radius.zero
                                  : const Radius.circular(3),
                              right: isUser
                                  ? const Radius.circular(3)
                                  : Radius.zero,
                            ),
                          ),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 12),
                        child: _ChatText(
                          text: _parseMarkdown(visibleContent),
                          color: isUser
                              ? const Color(0xFF9FEFCF)
                              : AssistantTheme.textPrimary,
                          fontSize: 12,
                          height: 1.55,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _showContextMenu(BuildContext ctx, Offset pos, String content) {
    showMenu(
      context: ctx,
      position: RelativeRect.fromLTRB(pos.dx, pos.dy, pos.dx, pos.dy),
      color: AssistantTheme.surface,
      items: [
        PopupMenuItem(
          child: const Text('Copiar',
              style:
                  TextStyle(color: AssistantTheme.textPrimary, fontSize: 12)),
          onTap: () => Clipboard.setData(ClipboardData(text: content)),
        ),
      ],
    );
  }

  String _formatTime(DateTime dt) =>
      '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
}

class _ChatText extends StatelessWidget {
  final String text;
  final Color color;
  final double fontSize;
  final double height;
  final TextAlign textAlign;

  const _ChatText({
    required this.text,
    required this.color,
    required this.fontSize,
    this.height = 1.35,
    this.textAlign = TextAlign.start,
  });

  @override
  Widget build(BuildContext context) {
    return RichText(
      textDirection: TextDirection.ltr,
      textAlign: textAlign,
      softWrap: true,
      text: TextSpan(
        text: text.trim().isEmpty ? 'Sem texto para exibir.' : text,
        style: TextStyle(
          inherit: false,
          fontFamily: 'Arial',
          fontSize: fontSize,
          height: height,
          color: color,
          letterSpacing: 0,
          decoration: TextDecoration.none,
        ),
      ),
    );
  }
}

class _MultiResponseCard extends StatelessWidget {
  final ChatMessage msg;
  final AppConfig config;
  const _MultiResponseCard({required this.msg, required this.config});

  @override
  Widget build(BuildContext context) {
    final responses = msg.multiResponses!;
    if (responses.isEmpty) return const SizedBox.shrink();
    final cols = responses.length >= 3 ? 3 : responses.length;

    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('◈ MODO PARALELO — ${responses.length} serviços',
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9,
                  letterSpacing: 3,
                  color: AssistantTheme.c1)),
          const SizedBox(height: 8),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: cols,
              childAspectRatio: 1.4,
              crossAxisSpacing: 8,
              mainAxisSpacing: 8,
            ),
            itemCount: responses.length,
            itemBuilder: (_, i) {
              final r = responses[i];
              final color =
                  AssistantTheme.llmColors[r.llm] ?? AssistantTheme.c1;
              return Container(
                decoration: BoxDecoration(
                  border: Border.all(color: color.withOpacity(0.3)),
                  borderRadius: BorderRadius.circular(3),
                  color: color.withOpacity(0.04),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: color.withOpacity(0.1),
                        borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(3)),
                      ),
                      child: Row(
                        children: [
                          Text(config.serviceName(r.llm).toUpperCase(),
                              style: TextStyle(
                                  fontFamily: 'Rajdhani',
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: color)),
                          if (r.durationMs != null) ...[
                            const Spacer(),
                            Text('${r.durationMs}ms',
                                style: TextStyle(
                                    fontFamily: 'JetBrains Mono',
                                    fontSize: 9,
                                    color: color.withOpacity(0.6))),
                          ],
                        ],
                      ),
                    ),
                    Expanded(
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.all(12),
                        child: _ChatText(
                          text: _parseMarkdown(
                            _visibleChatText(r.content, isError: r.isError),
                          ),
                          color: Colors.white,
                          fontSize: 12,
                          height: 1.5,
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _TypingIndicator extends StatefulWidget {
  const _TypingIndicator();

  @override
  State<_TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<_TypingIndicator>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 900))
      ..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          border: Border.all(color: AssistantTheme.c1.withOpacity(0.15)),
          borderRadius: BorderRadius.circular(3),
          color: AssistantTheme.c1.withOpacity(0.04),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(
              3,
              (i) => AnimatedBuilder(
                    animation: _ctrl,
                    builder: (_, __) {
                      final phase = ((_ctrl.value * 3) - i).clamp(0.0, 1.0);
                      return Container(
                        margin: const EdgeInsets.only(right: 5),
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color:
                              AssistantTheme.c1.withOpacity(0.3 + 0.7 * phase),
                        ),
                      );
                    },
                  )),
        ),
      ),
    );
  }
}

class _InputArea extends StatelessWidget {
  final TextEditingController controller;
  final bool isListening;
  final bool isDirectRecording;
  final bool isVoiceBusy;
  final bool isWindowPickerBusy;
  final bool sendOnEnter;
  final String? voiceStatus;
  final String? desktopContextLabel;
  final VoidCallback onSend;
  final VoidCallback onVoice;
  final VoidCallback onPickWindow;
  final VoidCallback onClearWindowContext;
  final VoidCallback onClear;

  const _InputArea({
    required this.controller,
    required this.isListening,
    required this.isDirectRecording,
    required this.isVoiceBusy,
    required this.isWindowPickerBusy,
    required this.sendOnEnter,
    this.voiceStatus,
    this.desktopContextLabel,
    required this.onSend,
    required this.onVoice,
    required this.onPickWindow,
    required this.onClearWindowContext,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: AssistantTheme.border)),
        color: Color(0xFF090C13),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (voiceStatus?.trim().isNotEmpty ?? false) ...[
            Row(
              children: [
                Icon(Icons.mic, size: 13, color: AssistantTheme.c3),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    voiceStatus!,
                    style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 10,
                      color: AssistantTheme.textSecondary,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
          ],
          if (desktopContextLabel?.trim().isNotEmpty ?? false) ...[
            Row(
              children: [
                const Icon(Icons.web_asset, size: 13, color: AssistantTheme.c2),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Contexto: $desktopContextLabel',
                    style: const TextStyle(
                      fontFamily: 'JetBrains Mono',
                      fontSize: 10,
                      color: AssistantTheme.textSecondary,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                IconButton(
                  tooltip: 'Remover contexto',
                  constraints:
                      const BoxConstraints.tightFor(width: 28, height: 28),
                  padding: EdgeInsets.zero,
                  icon: const Icon(Icons.close, size: 14),
                  color: AssistantTheme.textSecondary,
                  onPressed: onClearWindowContext,
                ),
              ],
            ),
            const SizedBox(height: 8),
          ],
          Row(
            children: [
              _ActionBtn(
                label: isDirectRecording ? '⏹ PARAR' : '🎙 VOZ',
                color: AssistantTheme.c3,
                isActive: isListening || isVoiceBusy,
                onTap: onVoice,
              ),
              const SizedBox(width: 10),
              _IconActionBtn(
                icon: Icons.web_asset,
                tooltip: 'Escolher janela',
                color: AssistantTheme.c2,
                isActive: isWindowPickerBusy ||
                    (desktopContextLabel?.trim().isNotEmpty ?? false),
                onTap: isWindowPickerBusy ? null : onPickWindow,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: CallbackShortcuts(
                  bindings: sendOnEnter
                      ? <ShortcutActivator, VoidCallback>{
                          const SingleActivator(LogicalKeyboardKey.enter):
                              onSend,
                          const SingleActivator(LogicalKeyboardKey.numpadEnter):
                              onSend,
                        }
                      : const <ShortcutActivator, VoidCallback>{},
                  child: TextField(
                    controller: controller,
                    style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 12,
                        color: AssistantTheme.textPrimary),
                    maxLines: 3,
                    minLines: 1,
                    decoration: const InputDecoration(
                      hintText: 'Digite ou fale um comando...',
                      hintStyle: TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 12,
                        color: AssistantTheme.textSecondary,
                      ),
                    ),
                    keyboardType: TextInputType.multiline,
                    textInputAction: TextInputAction.newline,
                    onChanged: (_) {},
                  ),
                ),
              ),
              const SizedBox(width: 10),
              _ActionBtn(
                  label: '✕', color: AssistantTheme.textMuted, onTap: onClear),
              const SizedBox(width: 6),
              _ActionBtn(
                  label: 'ENVIAR ›',
                  color: AssistantTheme.c1,
                  isPrimary: true,
                  onTap: onSend),
            ],
          ),
        ],
      ),
    );
  }
}

class _ActionBtn extends StatefulWidget {
  final String label;
  final Color color;
  final bool isActive;
  final bool isPrimary;
  final VoidCallback onTap;

  const _ActionBtn(
      {required this.label,
      required this.color,
      required this.onTap,
      this.isActive = false,
      this.isPrimary = false});

  @override
  State<_ActionBtn> createState() => _ActionBtnState();
}

class _ActionBtnState extends State<_ActionBtn> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          decoration: BoxDecoration(
            border: Border.all(
                color: widget.color.withOpacity(widget.isPrimary ? 0.5 : 0.25)),
            borderRadius: BorderRadius.circular(3),
            color: (_hovered || widget.isActive)
                ? widget.color.withOpacity(0.12)
                : Colors.transparent,
            boxShadow: (widget.isPrimary && _hovered)
                ? [
                    BoxShadow(
                        color: widget.color.withOpacity(0.2), blurRadius: 12)
                  ]
                : null,
          ),
          child: Text(
            widget.label,
            style: TextStyle(
                fontFamily: 'Rajdhani',
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 2,
                color: widget.color),
          ),
        ),
      ),
    );
  }
}

class _IconActionBtn extends StatefulWidget {
  final IconData icon;
  final String tooltip;
  final Color color;
  final bool isActive;
  final VoidCallback? onTap;

  const _IconActionBtn({
    required this.icon,
    required this.tooltip,
    required this.color,
    required this.onTap,
    this.isActive = false,
  });

  @override
  State<_IconActionBtn> createState() => _IconActionBtnState();
}

class _IconActionBtnState extends State<_IconActionBtn> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onTap != null;
    final color = enabled ? widget.color : AssistantTheme.textMuted;

    return Tooltip(
      message: widget.tooltip,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              border: Border.all(color: color.withOpacity(0.3)),
              borderRadius: BorderRadius.circular(3),
              color: (_hovered || widget.isActive)
                  ? color.withOpacity(0.12)
                  : Colors.transparent,
            ),
            child: Icon(widget.icon, size: 18, color: color),
          ),
        ),
      ),
    );
  }
}

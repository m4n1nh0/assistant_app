/// Tela de configuracao da assistente e das integracoes.
///
/// Persona, provedores de LLM, calendarios conectados, notificacao e voz.
library;

import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import '../providers/app_provider.dart';
import '../services/storage_service.dart';
import '../services/api_service.dart';
import '../services/external_launcher_service.dart';
import '../services/neural_tts_service.dart';
import '../services/neural_audio_player.dart';
import '../services/audio_input_service.dart';
import '../services/connected_ai_service.dart';
import '../models/app_config.dart';
import '../utils/theme.dart';
import '../widgets/title_bar.dart';

/// Tela de configuracao: persona, provedores, calendario e notificacao.
class ConfigScreen extends ConsumerStatefulWidget {
  const ConfigScreen({super.key});

  @override
  ConsumerState<ConfigScreen> createState() => _ConfigScreenState();
}

class _ConfigScreenState extends ConsumerState<ConfigScreen> {
  int _tab = 0;
  late AppConfig _draft;

  final _nameCtrl = TextEditingController();
  final _pronunciationCtrl = TextEditingController();
  final _userCtrl = TextEditingController();
  final _personCtrl = TextEditingController();
  final _curPassCtrl = TextEditingController();
  final _newPassCtrl = TextEditingController();
  final _newPassCCtrl = TextEditingController();
  final _inviteEmailCtrl = TextEditingController();
  final _tgTokenCtrl = TextEditingController();
  final _tgChatCtrl = TextEditingController();
  final _waNumCtrl = TextEditingController();
  final _waTokCtrl = TextEditingController();
  final _reminderMinutesCtrl = TextEditingController();
  final _gcalClientCtrl = TextEditingController();
  final _gcalSecretCtrl = TextEditingController();
  final _backendUrlCtrl = TextEditingController();
  bool _backendTestBusy = false;
  bool _telegramTestBusy = false;
  final _voicePreviewPlayer = NeuralAudioPlayer();
  bool _voiceTestBusy = false;
  final _microphoneRecorder = AudioRecorder();
  final _microphonePlayer = AudioPlayer();
  List<InputDevice> _inputDevices = const [];
  bool _microphonesBusy = false;
  bool _microphoneTestBusy = false;
  double? _microphonePeakDb;
  Map<String, List<CalendarAccount>> _calendarAccounts = const {
    'google': [],
    'microsoft': [],
  };
  bool _calendarBusy = false;
  CurrentAccount? _account;
  List<AdminUser> _users = const [];
  bool _inviteBusy = false;
  List<LlmProviderConfig> _llmProviders = const [];
  final Map<String, TextEditingController> _llmModelCtrls = {};
  final Map<String, TextEditingController> _llmKeyCtrls = {};
  final Set<String> _llmKeysToClear = {};
  bool _llmBusy = false;
  List<ConnectedAiStatus> _connectedAiStatuses = const [];
  bool _connectedAiBusy = false;

  @override
  void initState() {
    super.initState();
    _draft = ref.read(configProvider);
    _populate();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadNotificationConfig();
      _loadCalendarAccounts();
      _loadAccountManagement();
      _loadLlmConfig();
      _loadConnectedAiStatuses();
      _loadMicrophones();
    });
  }

  void _populate() {
    _nameCtrl.text = _draft.assistantName;
    _pronunciationCtrl.text = _draft.assistantPronunciation;
    _userCtrl.text = _draft.userName;
    _personCtrl.text = _draft.personality;
    _populateNotifFields();
    _gcalClientCtrl.text = _draft.calendar.gcalClientId;
    _gcalSecretCtrl.text = _draft.calendar.gcalClientSecret;
    _clearLegacyMicrosoftCredentials();
    _backendUrlCtrl.text = _draft.backendUrl;
  }

  Future<void> _clearLegacyMicrosoftCredentials() async {
    if (_draft.calendar.msClientId.isEmpty &&
        _draft.calendar.msClientSecret.isEmpty) {
      return;
    }
    _draft.calendar.msClientId = '';
    _draft.calendar.msClientSecret = '';
    _draft.calendar.msTenantId = 'common';
    await StorageService.saveConfig(_draft);
  }

  void _populateNotifFields() {
    _tgTokenCtrl.text = _draft.notif.tgToken;
    _tgChatCtrl.text = _draft.notif.tgChatId;
    _waNumCtrl.text = _draft.notif.waNumber;
    _waTokCtrl.text = _draft.notif.waToken;
    _reminderMinutesCtrl.text = '${_draft.notif.reminderMinutes}';
  }

  Future<void> _loadNotificationConfig() async {
    try {
      final notif = await api.getNotificationConfig();
      if (!mounted) return;
      setState(() {
        _draft.notif = notif;
        _populateNotifFields();
      });
    } catch (_) {}
  }

  Future<void> _loadAccountManagement() async {
    final account = await api.currentAccount();
    if (!mounted) return;
    setState(() => _account = account);
    if (account?.isAdmin != true) return;
    try {
      final users = await api.listUsers();
      if (mounted) setState(() => _users = users);
    } catch (_) {}
  }

  Future<void> _inviteUser() async {
    final email = _inviteEmailCtrl.text.trim();
    if (email.isEmpty || _inviteBusy) {
      _showSnack('Informe o email do novo usuario.');
      return;
    }
    setState(() => _inviteBusy = true);
    try {
      final message = await api.inviteUser(email);
      _inviteEmailCtrl.clear();
      _showSnack(message);
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _inviteBusy = false);
    }
  }

  Future<void> _loadLlmConfig() async {
    if (api.token == null) return;
    setState(() => _llmBusy = true);
    try {
      final response = await api.getLlmConfig();
      if (!mounted) return;
      _setLlmProviders(response.providers);
    } catch (e) {
      if (mounted) _showSnack('Erro ao carregar agentes: $e');
    } finally {
      if (mounted) setState(() => _llmBusy = false);
    }
  }

  void _setLlmProviders(List<LlmProviderConfig> providers) {
    for (final controller in _llmModelCtrls.values) {
      controller.dispose();
    }
    for (final controller in _llmKeyCtrls.values) {
      controller.dispose();
    }
    _llmModelCtrls.clear();
    _llmKeyCtrls.clear();
    _llmKeysToClear.clear();
    for (final item in providers.where((item) => item.kind == 'external')) {
      _llmModelCtrls[item.id] = TextEditingController(text: item.model);
      _llmKeyCtrls[item.id] = TextEditingController();
    }
    setState(() => _llmProviders = providers);
  }

  Future<bool> _saveLlmConfig({bool showMessage = true}) async {
    if (_llmProviders.isEmpty || _llmBusy) return true;
    setState(() => _llmBusy = true);
    try {
      final updates = _llmProviders.map((item) {
        if (item.kind != 'external') return item;
        return item.copyWith(
          model: _llmModelCtrls[item.id]?.text.trim() ?? item.model,
          apiKey: _llmKeyCtrls[item.id]?.text.trim() ?? '',
          clearApiKey: _llmKeysToClear.contains(item.id),
        );
      }).toList();
      final response = await api.saveLlmConfig(updates);
      if (!mounted) return true;
      _setLlmProviders(response.providers);
      if (showMessage) _showSnack('Agentes do usuário atualizados.');
      return true;
    } catch (e) {
      if (mounted) _showSnack('Erro ao salvar agentes: $e');
      return false;
    } finally {
      if (mounted) setState(() => _llmBusy = false);
    }
  }

  Future<void> _loadConnectedAiStatuses() async {
    if (_connectedAiBusy) return;
    setState(() => _connectedAiBusy = true);
    try {
      final statuses = await ConnectedAiService.checkAll();
      if (mounted) {
        setState(() => _connectedAiStatuses = statuses);
        _pushConnectedAgents(statuses);
      }
    } finally {
      if (mounted) setState(() => _connectedAiBusy = false);
    }
  }

  /// Publica o estado dos agentes conectados para os marcadores da conversa
  /// refletirem a conexão sem depender do botão salvar.
  void _pushConnectedAgents(List<ConnectedAiStatus> statuses) {
    final agents = {
      for (final status in statuses) status.id: status.authenticated,
    };
    _draft.connectedAgents = agents;
    ref.read(configProvider.notifier).setConnectedAgents(agents);
  }

  Future<void> _connectConnectedAi(String id) async {
    if (_connectedAiBusy) return;
    setState(() => _connectedAiBusy = true);
    try {
      await ConnectedAiService.startLogin(id);
      _showSnack('Login oficial aberto. Conclua a autenticação no navegador.');
      for (var attempt = 0; attempt < 60; attempt++) {
        await Future.delayed(const Duration(seconds: 2));
        final status = await ConnectedAiService.check(id);
        if (!mounted) return;
        final updated = [..._connectedAiStatuses];
        final index = updated.indexWhere((item) => item.id == id);
        if (index >= 0) {
          updated[index] = status;
        } else {
          updated.add(status);
        }
        setState(() => _connectedAiStatuses = updated);
        if (status.authenticated) {
          _pushConnectedAgents(updated);
          _showSnack('${status.label} conectado. Ele já aparece como opção '
              'nos marcadores da conversa.');
          return;
        }
      }
      _showSnack(
          'O login ainda não foi concluído. Use ATUALIZAR após autorizar.');
    } catch (e) {
      _showSnack('Não foi possível abrir o login: $e');
    } finally {
      if (mounted) setState(() => _connectedAiBusy = false);
    }
  }

  Future<void> _disconnectConnectedAi(ConnectedAiStatus status) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: Text('Desconectar ${status.label}',
            style: const TextStyle(color: AssistantTheme.textPrimary)),
        content: const Text(
          'Esta sessão é compartilhada com o cliente oficial e a extensão do '
          'VS Code. Ao sair aqui, eles também poderão solicitar novo login.',
          style: TextStyle(color: AssistantTheme.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Desconectar',
                style: TextStyle(color: AssistantTheme.danger)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => _connectedAiBusy = true);
    try {
      await ConnectedAiService.logout(status.id);
      if (_draft.selectedAgent == status.id) {
        _draft.selectedAgent = AppConfig.autoAgent;
      }
      await _loadConnectedAiStatusesAfterAction();
      _showSnack('${status.label} desconectado.');
    } catch (e) {
      _showSnack('Falha ao desconectar: $e');
    } finally {
      if (mounted) setState(() => _connectedAiBusy = false);
    }
  }

  Future<void> _loadConnectedAiStatusesAfterAction() async {
    final statuses = await ConnectedAiService.checkAll();
    if (mounted) {
      setState(() => _connectedAiStatuses = statuses);
      _pushConnectedAgents(statuses);
    }
  }

  Future<void> _save() async {
    _draft.assistantName = _nameCtrl.text.trim().isEmpty
        ? AppConfig.defaultAssistantName
        : _nameCtrl.text.trim();
    _draft.assistantPronunciation = _pronunciationCtrl.text.trim();
    _draft.userName = _userCtrl.text.trim();
    _draft.personality = _personCtrl.text.trim();

    _draft.notif.tgToken = _tgTokenCtrl.text.trim();
    _draft.notif.tgChatId = _tgChatCtrl.text.trim();
    _draft.notif.tgEnabled = _draft.notif.tgToken.isNotEmpty;
    _draft.notif.waNumber = _waNumCtrl.text.trim();
    _draft.notif.waToken = _waTokCtrl.text.trim();
    _draft.notif.waEnabled = _draft.notif.waNumber.isNotEmpty;
    final reminderMinutes = int.tryParse(_reminderMinutesCtrl.text.trim());
    if (reminderMinutes == null ||
        reminderMinutes < 5 ||
        reminderMinutes > 1440) {
      _showSnack('A antecedencia deve ficar entre 5 e 1440 minutos.');
      return;
    }
    _draft.notif.reminderMinutes = reminderMinutes;

    try {
      _draft.notif = await api.saveNotificationConfig(_draft.notif);
      _populateNotifFields();
    } catch (e) {
      _showSnack('Erro ao salvar notificacoes no backend: $e');
      return;
    }

    final gcalClientId = _gcalClientCtrl.text.trim();
    final gcalClientSecret = _gcalSecretCtrl.text.trim();

    if ((gcalClientId.isEmpty) != (gcalClientSecret.isEmpty)) {
      _showSnack('Preencha Client ID e Client Secret do Google.');
      return;
    }

    try {
      if (gcalClientId.isNotEmpty && gcalClientSecret.isNotEmpty) {
        await api.saveGoogleOAuthApp(
          clientId: gcalClientId,
          clientSecret: gcalClientSecret,
        );
      }
    } catch (e) {
      _showSnack('Erro ao salvar credenciais da agenda: $e');
      return;
    }

    try {
      _calendarAccounts = await api.listCalendarAccounts();
    } catch (_) {}

    _draft.calendar.gcalClientId = gcalClientId;
    _draft.calendar.gcalClientSecret = gcalClientSecret;
    _draft.calendar.gcalRefreshToken = '';
    _draft.calendar.gcalEnabled =
        _calendarAccounts['google']?.any((item) => item.connected) == true;
    _draft.calendar.msClientId = '';
    _draft.calendar.msClientSecret = '';
    _draft.calendar.msTenantId = 'common';
    _draft.calendar.msRefreshToken = '';
    _draft.calendar.msEnabled =
        _calendarAccounts['microsoft']?.any((item) => item.connected) == true;

    try {
      final account = _account ?? await api.currentAccount();
      if (account != null && account.tutorId.isNotEmpty) {
        await api.saveAssistantProfile(account, _draft);
      }
    } catch (e) {
      _showSnack('Erro ao salvar o perfil da assistente no backend: $e');
      return;
    }

    if (!await _saveLlmConfig(showMessage: false)) return;

    await StorageService.saveConfig(_draft);
    ref.read(configProvider.notifier).replaceInMemory(_draft);

    if (mounted) {
      ref.read(isAuthenticatedProvider.notifier).state = false;
      Navigator.pushReplacementNamed(context, '/main');
    }
  }

  Future<void> _testTelegram() async {
    if (_telegramTestBusy) return;
    final token = _tgTokenCtrl.text.trim();
    final chatId = _tgChatCtrl.text.trim();
    if (token.isEmpty || chatId.isEmpty) {
      _showSnack('Preencha o token do bot e o Chat ID.');
      return;
    }

    setState(() => _telegramTestBusy = true);
    try {
      final result = await api.testTelegram(
        NotifConfig(
          tgToken: token,
          tgChatId: chatId,
          tgEnabled: true,
        ),
      );
      _showSnack(result.ok ? '✅ ${result.message}' : '❌ ${result.message}');
    } catch (e) {
      _showSnack(
        '❌ ${e.toString().replaceFirst('Exception: ', '')}',
      );
    } finally {
      if (mounted) setState(() => _telegramTestBusy = false);
    }
  }

  Future<void> _applyBackendUrl() async {
    final typed = _backendUrlCtrl.text.trim();
    if (typed.isEmpty) {
      _showSnack('Informe o endereço do backend.');
      return;
    }
    setState(() => _backendTestBusy = true);
    api.configure(typed);
    _draft.backendUrl = api.baseUrl;
    _draft.backendUrlOverride = true;
    _backendUrlCtrl.text = api.baseUrl;
    await StorageService.saveConfig(_draft);
    ref.read(configProvider.notifier).replaceInMemory(_draft);
    try {
      await api.health().timeout(const Duration(seconds: 8));
      _showSnack('Conectado em ${api.baseUrl}');
    } catch (e) {
      _showSnack('Backend salvo, mas não respondeu em ${api.baseUrl}: $e');
    } finally {
      if (mounted) setState(() => _backendTestBusy = false);
    }
  }

  Future<void> _restoreDefaultBackendUrl() async {
    _backendUrlCtrl.text = AppConfig.defaultBackendUrl;
    setState(() => _backendTestBusy = true);
    api.configure(AppConfig.defaultBackendUrl);
    _draft.backendUrl = api.baseUrl;
    _draft.backendUrlOverride = false;
    _backendUrlCtrl.text = api.baseUrl;
    await StorageService.saveConfig(_draft);
    ref.read(configProvider.notifier).replaceInMemory(_draft);
    try {
      await api.health().timeout(const Duration(seconds: 8));
      _showSnack('Conectado em ${api.baseUrl}');
    } catch (e) {
      _showSnack(
          'Backend padrão salvo, mas não respondeu em ${api.baseUrl}: $e');
    } finally {
      if (mounted) setState(() => _backendTestBusy = false);
    }
  }

  Future<void> _testVoice() async {
    setState(() => _voiceTestBusy = true);
    try {
      final bytes = await NeuralTtsService.synthesize(
        'Oi! Sou a ${_pronunciationCtrl.text.trim().isNotEmpty ? _pronunciationCtrl.text.trim() : (_nameCtrl.text.trim().isEmpty ? AppConfig.defaultAssistantName : _nameCtrl.text.trim())}. '
        'E assim que eu vou falar com voce.',
        voice: NeuralTtsService.resolveVoice(
            _draft.ttsVoice, _draft.assistantGender),
        ratePercent: _draft.ttsRatePercent,
        pitchHz: _draft.ttsPitchHz,
      ).timeout(const Duration(seconds: 15));
      if (bytes.isEmpty) {
        _showSnack('Nao foi possivel gerar a voz.');
        return;
      }
      await _voicePreviewPlayer.stop();
      await _voicePreviewPlayer.play(bytes);
    } catch (e) {
      _showSnack('Falha ao gerar a voz (precisa de internet): $e');
    } finally {
      if (mounted) setState(() => _voiceTestBusy = false);
    }
  }

  Map<String, String> get _microphoneItems {
    final items = <String, String>{'': 'Padrao do sistema'};
    for (final device in _inputDevices) {
      items[device.id] = device.label.trim().isEmpty
          ? 'Microfone ${items.length}'
          : device.label.trim();
    }
    final savedId = _draft.audioInputDeviceId;
    if (savedId.isNotEmpty && !items.containsKey(savedId)) {
      final label = _draft.audioInputDeviceLabel.trim().isEmpty
          ? 'Microfone selecionado'
          : _draft.audioInputDeviceLabel.trim();
      items[savedId] = '$label (indisponivel)';
    }
    return items;
  }

  Future<void> _loadMicrophones() async {
    if (_microphonesBusy) return;
    if (mounted) setState(() => _microphonesBusy = true);
    try {
      if (!await _microphoneRecorder.hasPermission()) {
        _showSnack('Autorize o acesso ao microfone no Windows.');
        return;
      }
      final devices = await _microphoneRecorder.listInputDevices();
      if (mounted) setState(() => _inputDevices = devices);
    } catch (e) {
      _showSnack('Nao foi possivel listar os microfones: $e');
    } finally {
      if (mounted) setState(() => _microphonesBusy = false);
    }
  }

  void _selectMicrophone(String? id) {
    final selectedId = id ?? '';
    InputDevice? selected;
    for (final device in _inputDevices) {
      if (device.id == selectedId) {
        selected = device;
        break;
      }
    }
    setState(() {
      _draft.audioInputDeviceId = selectedId;
      _draft.audioInputDeviceLabel = selected?.label ?? '';
      _microphonePeakDb = null;
    });
  }

  Future<void> _testMicrophone() async {
    if (_microphoneTestBusy) return;
    setState(() {
      _microphoneTestBusy = true;
      _microphonePeakDb = null;
    });
    StreamSubscription<Amplitude>? amplitudeSubscription;
    String? path;
    try {
      if (!await _microphoneRecorder.hasPermission()) {
        throw Exception('microfone nao autorizado pelo Windows');
      }
      final devices = await _microphoneRecorder.listInputDevices();
      if (mounted) setState(() => _inputDevices = devices);
      final selected = resolveAudioInputDevice(
        devices,
        deviceId: _draft.audioInputDeviceId,
        deviceLabel: _draft.audioInputDeviceLabel,
      );
      if (_draft.audioInputDeviceId.isNotEmpty && selected == null) {
        throw Exception(
          'o microfone selecionado nao esta disponivel; conecte-o e clique em ATUALIZAR',
        );
      }

      final dir = await getTemporaryDirectory();
      path = '${dir.path}${Platform.pathSeparator}'
          'microphone_test_${DateTime.now().millisecondsSinceEpoch}.wav';
      await _microphonePlayer.stop();
      await _microphoneRecorder.start(
        speechRecordConfig(encoder: AudioEncoder.wav, device: selected),
        path: path,
      );
      amplitudeSubscription = _microphoneRecorder
          .onAmplitudeChanged(const Duration(milliseconds: 200))
          .listen((amplitude) {
        if (!mounted) return;
        final current = amplitude.current;
        if (current.isFinite) {
          setState(() {
            _microphonePeakDb = _microphonePeakDb == null
                ? current
                : (_microphonePeakDb! > current ? _microphonePeakDb : current);
          });
        }
      });
      await Future<void>.delayed(const Duration(seconds: 5));
      path = await _microphoneRecorder.stop() ?? path;
      final recordedFile = File(path);
      if (!await recordedFile.exists() || await recordedFile.length() < 256) {
        throw Exception('a gravacao ficou vazia');
      }
      final label = selected?.label ?? 'padrao do sistema';
      _showSnack('Teste concluido com $label. Reproduzindo agora.');
      unawaited(_microphonePlayer.onPlayerComplete.first.then((_) async {
        if (await recordedFile.exists()) await recordedFile.delete();
      }));
      await _microphonePlayer.play(DeviceFileSource(path));
    } catch (e) {
      try {
        if (await _microphoneRecorder.isRecording()) {
          await _microphoneRecorder.stop();
        }
      } catch (_) {}
      if (path != null) {
        final file = File(path);
        if (await file.exists()) await file.delete();
      }
      _showSnack('Falha no teste do microfone: $e');
    } finally {
      await amplitudeSubscription?.cancel();
      if (mounted) setState(() => _microphoneTestBusy = false);
    }
  }

  Future<void> _loadCalendarAccounts() async {
    try {
      final accounts = await api.listCalendarAccounts();
      if (!mounted) return;
      setState(() => _calendarAccounts = accounts);
    } catch (_) {}
  }

  Future<void> _openGoogleAuthorization() async {
    await _runCalendarAction(() async {
      final clientId = _gcalClientCtrl.text.trim();
      final clientSecret = _gcalSecretCtrl.text.trim();
      if ((clientId.isEmpty) != (clientSecret.isEmpty)) {
        throw Exception('preencha Client ID e Client Secret do Google');
      }

      final result = clientId.isNotEmpty
          ? await api.connectGoogleCalendar(
              clientId: clientId,
              clientSecret: clientSecret,
            )
          : await api.startGoogleCalendarAuth();
      if (result.authUrl.isEmpty || result.accountId.isEmpty) {
        throw Exception('backend nao retornou a URL de autorizacao Google');
      }
      await ExternalLauncherService.openUrl(result.authUrl);
      _showSnack(
          'Autorize no navegador. Vou detectar a conexao automaticamente.');
      final connected = await _waitForCalendarConnection(
        provider: 'google',
        accountId: result.accountId,
      );
      if (connected) {
        _showSnack('Conta Google conectada automaticamente.');
      } else {
        _showSnack('Autorizacao aberta. A conta aparece aqui ao concluir.');
      }
    });
  }

  Future<void> _openMicrosoftAuthorization({String? accountId}) async {
    await _runCalendarAction(() async {
      final result = await api.startMicrosoftCalendarAuth(
        accountId: accountId,
      );
      if (result.authUrl.isEmpty || result.accountId.isEmpty) {
        throw Exception('backend nao retornou a URL de autorizacao Microsoft');
      }
      await ExternalLauncherService.openUrl(result.authUrl);
      _showSnack(
          'Autorize no navegador. Vou detectar a conexao automaticamente.');
      final connected = await _waitForCalendarConnection(
        provider: 'microsoft',
        accountId: result.accountId,
      );
      if (connected) {
        _showSnack('Conta Microsoft conectada automaticamente.');
      } else {
        _showSnack('Autorizacao aberta. A conta aparece aqui ao concluir.');
      }
    });
  }

  Future<void> _disconnectCalendarAccount(CalendarAccount account) async {
    await _runCalendarAction(() async {
      await api.disconnectCalendarAccount(
        provider: account.provider,
        accountId: account.id,
      );
      await _loadCalendarAccounts();
      _showSnack('Agenda removida: ${account.label}');
    });
  }

  Future<void> _runCalendarAction(Future<void> Function() action) async {
    if (_calendarBusy) return;
    setState(() => _calendarBusy = true);
    try {
      await action();
    } catch (e) {
      _showSnack('Erro na agenda: $e');
    } finally {
      if (mounted) setState(() => _calendarBusy = false);
    }
  }

  Future<bool> _waitForCalendarConnection({
    required String provider,
    required String accountId,
  }) async {
    for (var i = 0; i < 45; i++) {
      await Future.delayed(const Duration(seconds: 2));
      await _loadCalendarAccounts();
      final accounts = _calendarAccounts[provider] ?? const [];
      final connected = accounts.any(
        (account) => account.id == accountId && account.connected,
      );
      if (connected) return true;
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final tabs = [
      'IDENTIDADE',
      'AUTENTICAÇÃO',
      'AGENTES',
      'NOTIFICAÇÕES',
      'AGENDAS',
      'SISTEMA'
    ];

    return Scaffold(
      backgroundColor: AssistantTheme.bg,
      body: Column(
        children: [
          const AssistantTitleBar(),
          Expanded(
            child: Row(
              children: [
                Container(
                  width: 180,
                  color: AssistantTheme.bg2,
                  child: Column(
                    children: [
                      const SizedBox(height: 24),
                      ...List.generate(
                          tabs.length,
                          (i) => _TabBtn(
                                label: tabs[i],
                                active: _tab == i,
                                onTap: () => setState(() => _tab = i),
                              )),
                      const Spacer(),
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          children: [
                            _SaveBtn(onTap: _save),
                            const SizedBox(height: 8),
                            if (Navigator.canPop(context))
                              _CancelBtn(onTap: () => Navigator.pop(context)),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(32),
                    child: [
                      _buildIdentity(),
                      _buildAuth(),
                      _buildAgents(),
                      _buildNotif(),
                      _buildCalendar2(),
                      _buildSystem(),
                    ][_tab],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildIdentity() => _TabContent(title: 'IDENTIDADE', children: [
        _Field('NOME DA ASSISTENTE', _nameCtrl,
            hint: 'Ex: Hannah, Vera, Nexus...'),
        _Field('PRONÚNCIA DO NOME', _pronunciationCtrl,
            hint: 'Opcional. Ex: Raná para Hannah'),
        const _InfoBox(
          'A marca do produto continua INTARQ. O nome e a pronúncia da '
          'assistente pertencem somente ao seu usuário. Sem nome, será usado '
          'Assistant.',
        ),
        _Field('SEU NOME', _userCtrl, hint: 'Como você prefere ser chamado'),
        _Field('PERFIL DE ATENDIMENTO', _personCtrl,
            hint: 'Descreva o tom, foco e preferências de resposta...',
            maxLines: 5),
        _Label('SEXO DA ASSISTENTE'),
        _Dropdown(
          value: _draft.assistantGender,
          items: const {
            'f': 'Feminino',
            'm': 'Masculino',
          },
          onChanged: (v) => setState(() => _draft.assistantGender = v!),
        ),
        const SizedBox(height: 12),
        _Label('IDIOMA'),
        _Dropdown(
          value: _draft.language,
          items: const {
            'pt-BR': 'Português BR',
            'en-US': 'English US',
            'es-ES': 'Español'
          },
          onChanged: (v) => setState(() => _draft.language = v!),
        ),
        const SizedBox(height: 12),
        _Label('MODO DE RESPOSTA PADRÃO'),
        _Dropdown(
          value: _draft.responseMode,
          items: const {
            'single': 'Resposta padrão',
            'multi': 'Consulta paralela',
            'chain': 'Refinamento em etapas',
          },
          onChanged: (v) => setState(() => _draft.responseMode = v!),
        ),
      ]);

  Widget _buildAuth() => _TabContent(title: 'AUTENTICAÇÃO', children: [
        _SectionCard(title: '🔑 TROCAR SENHA', children: [
          _InlineField(_curPassCtrl, hint: 'Senha atual', obscure: true),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
                child: _InlineField(_newPassCtrl,
                    hint: 'Nova senha', obscure: true)),
            const SizedBox(width: 10),
            Expanded(
                child: _InlineField(_newPassCCtrl,
                    hint: 'Confirmar nova senha', obscure: true)),
          ]),
          const SizedBox(height: 10),
          _ActionBtn(
            label: 'Salvar nova senha',
            color: AssistantTheme.c2,
            onTap: _changePassword,
          ),
          _InfoBox(
              'O acesso ao assistente é protegido por usuário e senha, exigidos toda vez que o app inicia sem uma sessão válida.'),
        ]),
        _SectionCard(title: '↪ SESSÃO', children: [
          _ActionBtn(
            label: 'Trocar usuário',
            color: AssistantTheme.c2,
            onTap: _switchUser,
          ),
          _InfoBox(
              'Encerra a sessão atual e abre a tela de login. Os dados locais permanecem separados por conta.'),
        ]),
        if (_account?.isAdmin == true)
          _SectionCard(title: '👥 USUÁRIOS E CONVITES', children: [
            _InfoBox(
                'Somente administradores enviam convites. Cada conta recebe conversas, agenda, notificações, memórias e configurações próprias.'),
            _InlineField(
              _inviteEmailCtrl,
              hint: 'Email do novo usuário',
            ),
            const SizedBox(height: 10),
            _ActionBtn(
              label: _inviteBusy ? 'Enviando...' : 'Enviar convite',
              color: AssistantTheme.c1,
              onTap: _inviteUser,
            ),
            if (_users.isNotEmpty) ...[
              const SizedBox(height: 12),
              ..._users.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    children: [
                      Icon(
                        item.isActive
                            ? Icons.check_circle_outline
                            : Icons.block_outlined,
                        size: 14,
                        color: item.isActive
                            ? AssistantTheme.c3
                            : AssistantTheme.danger,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          item.email.isEmpty
                              ? item.username
                              : '${item.username} — ${item.email}',
                          style: const TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 10.5,
                            color: AssistantTheme.textSecondary,
                          ),
                        ),
                      ),
                      Text(
                        item.role.toUpperCase(),
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 9,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ]),
      ]);

  Future<void> _changePassword() async {
    final current = _curPassCtrl.text;
    final next = _newPassCtrl.text;
    if (current.isEmpty || next.isEmpty) {
      _showSnack('Preencha a senha atual e a nova senha.');
      return;
    }
    if (next != _newPassCCtrl.text) {
      _showSnack('A confirmação de senha não confere.');
      return;
    }
    try {
      await api.changePassword(currentPassword: current, newPassword: next);
      _curPassCtrl.clear();
      _newPassCtrl.clear();
      _newPassCCtrl.clear();
      _showSnack('Senha alterada com sucesso.');
    } catch (e) {
      _showSnack('Erro ao trocar senha: $e');
    }
  }

  Future<void> _switchUser() async {
    await StorageService.clearAuthToken();
    api.logout();
    ref.read(isAuthenticatedProvider.notifier).state = false;
    if (mounted) {
      Navigator.pushNamedAndRemoveUntil(context, '/main', (_) => false);
    }
  }

  Widget _buildAgents() {
    final local = _llmProviders.where((item) => item.kind == 'local').toList();
    final external =
        _llmProviders.where((item) => item.kind == 'external').toList();
    return _TabContent(title: 'AGENTES', children: [
      const _InfoBox(
        'LocalAI e Ollama são gerenciados pela instalação e ficam disponíveis '
        'para todos. Provedores externos, gratuitos ou pagos, pertencem '
        'somente ao usuário conectado.',
      ),
      _SectionCard(title: 'AGENTES CONECTADOS NESTE COMPUTADOR', children: [
        const _InfoBox(
          'Usa o login oficial já mantido pelo Codex ou Claude Code. A INTARQ '
          'não lê, copia nem envia os tokens para o backend. Esse modo executa '
          'o agente localmente e com permissões restritas.',
        ),
        const _InfoBox(
          'Agentes conectados entram na lista de agentes disponíveis junto '
          'com os provedores do backend. Na conversa, toque nos marcadores '
          'do cabeçalho para escolher AUTO (orquestração) ou um agente '
          'específico.',
        ),
        const SizedBox(height: 10),
        if (_connectedAiBusy && _connectedAiStatuses.isEmpty)
          const LinearProgressIndicator()
        else
          ..._connectedAiStatuses.map(_buildConnectedAgent),
        _ActionBtn(
          label: _connectedAiBusy ? 'CONSULTANDO...' : 'ATUALIZAR CONEXÕES',
          onTap: _connectedAiBusy ? null : _loadConnectedAiStatuses,
        ),
      ]),
      _SectionCard(title: 'AGENTES LOCAIS DA APLICAÇÃO', children: [
        if (_llmBusy && local.isEmpty)
          const LinearProgressIndicator()
        else
          ...local.map((item) => ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  item.enabled ? Icons.memory : Icons.cloud_off_outlined,
                  color: item.enabled
                      ? AssistantTheme.c3
                      : AssistantTheme.textMuted,
                ),
                title: Text(item.label,
                    style: const TextStyle(
                        color: AssistantTheme.textPrimary,
                        fontFamily: 'JetBrains Mono')),
                subtitle: Text(
                  '${item.model} · ${item.enabled ? 'gerenciado pela aplicação' : 'não configurado no servidor'}',
                  style: const TextStyle(
                      color: AssistantTheme.textMuted, fontSize: 10),
                ),
              )),
      ]),
      ...external.map(_buildExternalAgent),
      _ActionBtn(
        label: _llmBusy ? 'VERIFICANDO...' : 'SALVAR E VERIFICAR AGENTES',
        color: AssistantTheme.c1,
        onTap: _llmBusy ? null : () => _saveLlmConfig(),
      ),
      const _InfoBox(
        'As chaves são cifradas e permanecem somente no backend. O aplicativo '
        'não salva nem volta a exibir uma chave já cadastrada.',
      ),
    ]);
  }

  Widget _buildConnectedAgent(ConnectedAiStatus status) {
    final state = !status.installed
        ? 'NÃO INSTALADO'
        : status.authenticated
            ? 'CONECTADO'
            : 'SEM LOGIN';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AssistantTheme.bg2,
        border: Border.all(
          color: status.authenticated
              ? AssistantTheme.c3.withOpacity(.5)
              : AssistantTheme.border,
        ),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(
            status.authenticated
                ? Icons.verified_user_outlined
                : Icons.link_off_outlined,
            color: status.authenticated
                ? AssistantTheme.c3
                : AssistantTheme.textMuted,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(status.label,
                style: const TextStyle(
                    color: AssistantTheme.textPrimary,
                    fontFamily: 'JetBrains Mono')),
          ),
          Text(state,
              style: TextStyle(
                  color: status.authenticated
                      ? AssistantTheme.c3
                      : AssistantTheme.textMuted,
                  fontSize: 9,
                  fontFamily: 'JetBrains Mono')),
        ]),
        const SizedBox(height: 6),
        Text(
          [
            if (status.accountLabel.isNotEmpty) status.accountLabel,
            if (status.version.isNotEmpty) status.version,
            status.detail,
          ].join(' · '),
          style: const TextStyle(color: AssistantTheme.textMuted, fontSize: 10),
        ),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(
            child: _ActionBtn(
              label: status.authenticated ? 'RECONECTAR' : 'CONECTAR',
              color: AssistantTheme.c1,
              onTap: !status.installed || _connectedAiBusy
                  ? null
                  : () => _connectConnectedAi(status.id),
            ),
          ),
          if (status.authenticated) ...[
            const SizedBox(width: 8),
            Expanded(
              child: _ActionBtn(
                label: 'DESCONECTAR',
                color: AssistantTheme.danger,
                onTap: _connectedAiBusy
                    ? null
                    : () => _disconnectConnectedAi(status),
              ),
            ),
          ],
        ]),
      ]),
    );
  }

  Widget _buildExternalAgent(LlmProviderConfig item) {
    final index = _llmProviders.indexWhere((entry) => entry.id == item.id);
    final removing = _llmKeysToClear.contains(item.id);
    return _SectionCard(title: item.label.toUpperCase(), children: [
      _Toggle(
        'Ativar para este usuário',
        item.enabled && !removing,
        (value) => setState(() {
          _llmProviders[index] = item.copyWith(enabled: value);
          if (value) _llmKeysToClear.remove(item.id);
        }),
      ),
      _Field('MODELO', _llmModelCtrls[item.id]!, hint: 'Modelo do provedor'),
      _Field(
        'API KEY',
        _llmKeyCtrls[item.id]!,
        hint: item.configured && !removing
            ? 'Configurada — deixe vazio para manter'
            : 'Cole a chave desta conta',
        obscure: true,
      ),
      if (item.configured)
        _ActionBtn(
          label: removing ? 'MANTER CREDENCIAL' : 'REMOVER CREDENCIAL',
          color: removing ? AssistantTheme.c3 : AssistantTheme.danger,
          onTap: () => setState(() {
            if (removing) {
              _llmKeysToClear.remove(item.id);
            } else {
              _llmKeysToClear.add(item.id);
            }
          }),
        ),
    ]);
  }

  Widget _buildNotif() => _TabContent(title: 'NOTIFICAÇÕES', children: [
        _SectionCard(title: '✈️ TELEGRAM', children: [
          _Field('BOT TOKEN', _tgTokenCtrl,
              hint: '123456789:AABBcc...', obscure: true),
          _Field('CHAT ID', _tgChatCtrl,
              hint: 'Seu chat ID (use @userinfobot)'),
          _ActionBtn(
              label: _telegramTestBusy
                  ? '⏳ TESTANDO TELEGRAM...'
                  : '📨 Testar Telegram',
              onTap: _telegramTestBusy ? null : _testTelegram),
          _InfoBox(
              'Obtenha o token em @BotFather e o Chat ID em @userinfobot no Telegram.'),
        ]),
        _SectionCard(title: '💬 WHATSAPP', children: [
          _Label('PROVEDOR'),
          _Dropdown(
            value: _draft.notif.waProvider,
            items: const {
              'callmebot': 'CallMeBot (gratuito)',
              'zapi': 'Z-API',
              'twilio': 'Twilio'
            },
            onChanged: (v) => setState(() => _draft.notif.waProvider = v!),
          ),
          const SizedBox(height: 10),
          _Field('NÚMERO DE DESTINO', _waNumCtrl, hint: '+5511999999999'),
          _Field('API KEY / TOKEN', _waTokCtrl,
              hint: 'Token do provedor escolhido', obscure: true),
          _ActionBtn(
              label: '📱 Testar WhatsApp',
              onTap: () => _showSnack(
                  'Configure o número e token, depois clique "Salvar" antes de testar')),
        ]),
        _SectionCard(title: '⚙ CONFIGURAÇÕES DE ALERTA', children: [
          _Toggle('Notificar com antecedência', _draft.notif.notify15min,
              (v) => setState(() => _draft.notif.notify15min = v)),
          if (_draft.notif.notify15min)
            _Field(
              'ANTECEDÊNCIA EM MINUTOS',
              _reminderMinutesCtrl,
              hint: 'Ex.: 10, 30, 60 ou 1440',
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            ),
          _Toggle('Notificar também no horário', _draft.notif.notifyOnTime,
              (v) => setState(() => _draft.notif.notifyOnTime = v)),
          const _InfoBox(
            'O horário do aviso acompanha o evento no calendário. Para aulas, '
            'altere o horário no cadastro da turma antes de sincronizar a agenda.',
          ),
          _Toggle(
              'Fallback (Telegram → WhatsApp)',
              _draft.notif.fallbackEnabled,
              (v) => setState(() => _draft.notif.fallbackEnabled = v)),
          _Toggle('Incluir link da reunião', _draft.notif.includeLink,
              (v) => setState(() => _draft.notif.includeLink = v)),
        ]),
      ]);

  Widget _buildCalendar2() => _TabContent(title: 'AGENDAS', children: [
        _SectionCard(title: 'CRIAÇÃO DE EVENTOS', children: [
          _InfoBox(
              'Quando autorizada, a assistente cria pedidos claros de eventos sem abrir a confirmação. A primeira conta compatível é usada; se o provedor não for informado, o Google tem preferência. Esta opção vem desligada por segurança.'),
          _Toggle(
            'Autorizar criação automática',
            _draft.calendar.autoCreateEvents,
            (value) => setState(() => _draft.calendar.autoCreateEvents = value),
          ),
        ]),
        _SectionCard(title: 'GOOGLE CALENDAR', children: [
          _InfoBox(
              'Informe as credenciais OAuth uma vez ou use as que ja estao salvas no backend. O botao libera leitura e criacao de eventos. Reconecte contas antigas para autorizar escrita.'),
          _Field('CLIENT ID', _gcalClientCtrl, hint: 'Google OAuth Client ID'),
          _Field('CLIENT SECRET', _gcalSecretCtrl,
              hint: 'Google OAuth Client Secret', obscure: true),
          _ActionBtn(
            label: _calendarBusy ? 'Aguarde...' : 'Conectar Google Agenda',
            onTap: _openGoogleAuthorization,
          ),
          _CalendarAccountList(
            accounts: _calendarAccounts['google'] ?? const [],
            onRemove: _disconnectCalendarAccount,
          ),
        ]),
        _SectionCard(title: 'MICROSOFT (Teams + Outlook)', children: [
          const _InfoBox(
              'Entre com sua conta pessoal, corporativa ou educacional na pagina oficial da Microsoft. Senha, MFA e politicas da organizacao sao tratados somente pela Microsoft; o assistente nunca recebe sua senha.'),
          _ActionBtn(
            label: _calendarBusy ? 'Aguarde...' : 'Conectar Microsoft',
            onTap: () => _openMicrosoftAuthorization(),
          ),
          _CalendarAccountList(
            accounts: _calendarAccounts['microsoft'] ?? const [],
            onRemove: _disconnectCalendarAccount,
            onReconnect: (account) =>
                _openMicrosoftAuthorization(accountId: account.id),
          ),
        ]),
      ]);

  Widget _buildSystem() => _TabContent(title: 'SISTEMA', children: [
        _SectionCard(title: '🌐 CONEXÃO COM O BACKEND', children: [
          _InfoBox(
            'Padrão da distribuição: ${AppConfig.defaultBackendUrl}. '
            'Em produção, esse valor vem de assets/config/app_defaults.json '
            'ou de intarq_config.json ao lado do executável. Use localhost '
            'apenas para desenvolvimento.',
          ),
          _Field('ENDEREÇO DO BACKEND', _backendUrlCtrl,
              hint: 'http://localhost:8000 ou https://seu-app.up.railway.app'),
          _ActionBtn(
            label: _backendTestBusy ? 'TESTANDO...' : 'APLICAR E TESTAR',
            onTap: _backendTestBusy ? () {} : _applyBackendUrl,
          ),
          _ActionBtn(
            label: 'RESTAURAR PADRÃO DO APP',
            onTap: _backendTestBusy ? () {} : _restoreDefaultBackendUrl,
          ),
        ]),
        _SectionCard(title: '🔊 VOZ DA ASSISTENTE', children: [
          _Label('VOZ'),
          _Dropdown(
            value: NeuralTtsService.resolveVoice(
                _draft.ttsVoice, _draft.assistantGender),
            items: NeuralTtsService.voices,
            onChanged: (v) => setState(() => _draft.ttsVoice = v ?? ''),
          ),
          const SizedBox(height: 12),
          _NumberSetting(
            label: 'Velocidade (%)',
            value: _draft.ttsRatePercent,
            min: -50,
            max: 50,
            step: 2,
            onChanged: (v) => setState(() => _draft.ttsRatePercent = v),
          ),
          _NumberSetting(
            label: 'Tom (Hz)',
            value: _draft.ttsPitchHz,
            min: -50,
            max: 50,
            step: 5,
            onChanged: (v) => setState(() => _draft.ttsPitchHz = v),
          ),
          _ActionBtn(
            label: _voiceTestBusy ? 'FALANDO...' : '▶ OUVIR ESTA VOZ',
            onTap: _voiceTestBusy ? () {} : _testVoice,
          ),
          const _InfoBox(
            'Vozes neurais geradas na propria interface, sem custo e sem passar '
            'pelo backend. Sem internet, a assistente usa a voz do Windows.',
          ),
        ]),
        _SectionCard(title: '🎙 MICROFONE DE ENTRADA', children: [
          const _Label('DISPOSITIVO PARA AULAS E COMANDOS DE VOZ'),
          _Dropdown(
            value: _draft.audioInputDeviceId,
            items: _microphoneItems,
            onChanged: _selectMicrophone,
          ),
          const SizedBox(height: 10),
          _ActionBtn(
            label:
                _microphonesBusy ? 'ATUALIZANDO...' : '↻ ATUALIZAR MICROFONES',
            onTap: _microphonesBusy ? () {} : _loadMicrophones,
          ),
          _ActionBtn(
            label: _microphoneTestBusy
                ? 'GRAVANDO 5 SEGUNDOS...'
                : '● GRAVAR TESTE DE 5s E OUVIR',
            onTap: _microphoneTestBusy ? () {} : _testMicrophone,
          ),
          if (_microphonePeakDb != null)
            _InfoBox(
              'Pico captado: ${_microphonePeakDb!.toStringAsFixed(1)} dB. '
              'Se a reproducao estiver baixa ou cortada, confira o volume de entrada no Windows.',
            ),
          const _InfoBox(
            'O dispositivo escolhido sera usado na gravacao de aulas e nos '
            'comandos de voz. Depois de conectar um fone Bluetooth, clique em '
            'ATUALIZAR e escolha a entrada Hands-Free/Headset do fone.',
          ),
        ]),
        _SectionCard(title: '🖥 PREFERÊNCIAS', children: [
          _Toggle('Iniciar minimizado', _draft.startMinimized,
              (v) => setState(() => _draft.startMinimized = v)),
          _Toggle('Iniciar com o sistema', _draft.autoLaunch,
              (v) => setState(() => _draft.autoLaunch = v)),
          _Toggle('Resposta por voz', _draft.ttsEnabled,
              (v) => setState(() => _draft.ttsEnabled = v)),
          _Toggle('Enter envia mensagem', _draft.sendMessageOnEnter,
              (v) => setState(() => _draft.sendMessageOnEnter = v)),
          const _InfoBox(
            'Ligado: Enter envia e Shift+Enter quebra a linha. Desligado: '
            'Enter quebra a linha e Ctrl+Enter envia.',
          ),
          _Toggle(
              'Microfone ativo por nome da assistente',
              _draft.continuousVoiceMode,
              (v) => setState(() => _draft.continuousVoiceMode = v)),
          _NumberSetting(
            label: 'Tentativas para pedir instrução',
            value: _draft.voicePromptRetries,
            min: 1,
            max: 6,
            onChanged: (v) => setState(() => _draft.voicePromptRetries = v),
          ),
        ]),
        _SectionCard(title: '⚠️ DADOS', children: [
          _ActionBtn(
            label: '🗑 Limpar todos os dados',
            color: AssistantTheme.danger,
            onTap: () async {
              final ok = await showDialog<bool>(
                  context: context,
                  builder: (_) => AlertDialog(
                        backgroundColor: AssistantTheme.surface,
                        title: const Text('Confirmar',
                            style:
                                TextStyle(color: AssistantTheme.textPrimary)),
                        content: const Text(
                            'Isso apagará configurações, dados locais e histórico. Continuar?',
                            style:
                                TextStyle(color: AssistantTheme.textSecondary)),
                        actions: [
                          TextButton(
                              onPressed: () => Navigator.pop(context, false),
                              child: const Text('Cancelar')),
                          TextButton(
                              onPressed: () => Navigator.pop(context, true),
                              child: const Text('Apagar',
                                  style:
                                      TextStyle(color: AssistantTheme.danger))),
                        ],
                      ));
              if (ok == true) {
                await StorageService.clearAll();
                if (mounted) Navigator.pushReplacementNamed(context, '/config');
              }
            },
          ),
        ]),
      ]);

  void _showSnack(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(msg,
            style: const TextStyle(fontFamily: 'JetBrains Mono', fontSize: 11)),
        backgroundColor: AssistantTheme.surface2));
  }

  @override
  void dispose() {
    for (final c in [
      _nameCtrl,
      _pronunciationCtrl,
      _userCtrl,
      _personCtrl,
      _curPassCtrl,
      _newPassCtrl,
      _newPassCCtrl,
      _inviteEmailCtrl,
      _tgTokenCtrl,
      _tgChatCtrl,
      _waNumCtrl,
      _waTokCtrl,
      _reminderMinutesCtrl,
      _gcalClientCtrl,
      _gcalSecretCtrl,
      _backendUrlCtrl,
    ]) {
      c.dispose();
    }
    for (final c in [..._llmModelCtrls.values, ..._llmKeyCtrls.values]) {
      c.dispose();
    }
    _voicePreviewPlayer.dispose();
    _microphoneRecorder.dispose();
    _microphonePlayer.dispose();
    super.dispose();
  }
}

class _CalendarAccountList extends StatelessWidget {
  final List<CalendarAccount> accounts;
  final Future<void> Function(CalendarAccount account) onRemove;
  final Future<void> Function(CalendarAccount account)? onReconnect;

  const _CalendarAccountList({
    required this.accounts,
    required this.onRemove,
    this.onReconnect,
  });

  @override
  Widget build(BuildContext context) {
    if (accounts.isEmpty) {
      return const Padding(
        padding: EdgeInsets.only(top: 10),
        child: Text(
          'Nenhuma conta conectada ainda.',
          style: TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 10,
            color: AssistantTheme.textMuted,
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(
        children: accounts
            .map(
              (account) => Container(
                margin: const EdgeInsets.only(bottom: 6),
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                decoration: BoxDecoration(
                  border: Border.all(color: AssistantTheme.border),
                  borderRadius: BorderRadius.circular(3),
                ),
                child: Row(
                  children: [
                    Icon(
                      account.connected
                          ? Icons.check_circle_outline
                          : Icons.pending_outlined,
                      size: 15,
                      color: account.connected
                          ? AssistantTheme.c3
                          : AssistantTheme.textMuted,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            account.label.isEmpty
                                ? account.provider
                                : account.label,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontFamily: 'JetBrains Mono',
                              fontSize: 10.5,
                              color: AssistantTheme.textSecondary,
                            ),
                          ),
                          if (account.email?.isNotEmpty == true)
                            Text(
                              account.email!,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontFamily: 'JetBrains Mono',
                                fontSize: 8.5,
                                color: AssistantTheme.textMuted,
                              ),
                            ),
                        ],
                      ),
                    ),
                    Text(
                      account.statusLabel,
                      style: TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 8,
                        color: account.connected
                            ? AssistantTheme.c3
                            : AssistantTheme.textMuted,
                      ),
                    ),
                    if (onReconnect != null)
                      IconButton(
                        tooltip: 'Reconectar conta',
                        onPressed: () => onReconnect!(account),
                        icon: const Icon(
                          Icons.refresh,
                          size: 16,
                          color: AssistantTheme.c2,
                        ),
                      ),
                    IconButton(
                      onPressed: () => onRemove(account),
                      icon: const Icon(
                        Icons.delete_outline,
                        size: 16,
                        color: AssistantTheme.danger,
                      ),
                    ),
                  ],
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  final String label;
  final TextEditingController ctrl;
  final String? hint;
  final bool obscure;
  final int maxLines;
  final TextInputType? keyboardType;
  final List<TextInputFormatter>? inputFormatters;
  const _Field(this.label, this.ctrl,
      {this.hint,
      this.obscure = false,
      this.maxLines = 1,
      this.keyboardType,
      this.inputFormatters});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label,
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9,
                  letterSpacing: 3,
                  color: AssistantTheme.textMuted)),
          const SizedBox(height: 5),
          TextField(
              controller: ctrl,
              obscureText: obscure,
              maxLines: maxLines,
              keyboardType: keyboardType,
              inputFormatters: inputFormatters,
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 12,
                  color: AssistantTheme.textPrimary),
              decoration: InputDecoration(hintText: hint)),
        ]),
      );
}

class _InlineField extends StatelessWidget {
  final TextEditingController ctrl;
  final String? hint;
  final bool obscure;
  const _InlineField(this.ctrl, {this.hint, this.obscure = false});

  @override
  Widget build(BuildContext context) => TextField(
        controller: ctrl,
        obscureText: obscure,
        style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 12,
            color: AssistantTheme.textPrimary),
        decoration: InputDecoration(hintText: hint),
      );
}

class _Label extends StatelessWidget {
  final String text;
  const _Label(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 5),
        child: Text(text,
            style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                letterSpacing: 3,
                color: AssistantTheme.textMuted)),
      );
}

class _Dropdown extends StatelessWidget {
  final String value;
  final Map<String, String> items;
  final ValueChanged<String?> onChanged;
  const _Dropdown(
      {required this.value, required this.items, required this.onChanged});

  @override
  Widget build(BuildContext context) => DropdownButtonFormField<String>(
        value: items.containsKey(value) ? value : items.keys.first,
        dropdownColor: AssistantTheme.surface,
        style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 12,
            color: AssistantTheme.textPrimary),
        decoration: const InputDecoration(),
        items: items.entries
            .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
            .toList(),
        onChanged: onChanged,
      );
}

class _Toggle extends StatelessWidget {
  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;
  const _Toggle(this.label, this.value, this.onChanged);

  @override
  Widget build(BuildContext context) => Row(children: [
        Text(label,
            style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: AssistantTheme.textSecondary)),
        const Spacer(),
        Switch(
            value: value, onChanged: onChanged, activeColor: AssistantTheme.c3),
      ]);
}

class _NumberSetting extends StatelessWidget {
  final String label;
  final int value;
  final int min;
  final int max;
  final ValueChanged<int> onChanged;

  final int step;

  const _NumberSetting({
    required this.label,
    required this.value,
    required this.onChanged,
    this.min = 0,
    this.max = 10,
    this.step = 1,
  });

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 11,
                    color: AssistantTheme.textSecondary),
              ),
            ),
            _MiniStepButton(
              label: '-',
              onTap: value > min
                  ? () => onChanged((value - step).clamp(min, max))
                  : null,
            ),
            SizedBox(
              width: 34,
              child: Text(
                '$value',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 12,
                  color: AssistantTheme.textPrimary,
                ),
              ),
            ),
            _MiniStepButton(
              label: '+',
              onTap: value < max
                  ? () => onChanged((value + step).clamp(min, max))
                  : null,
            ),
          ],
        ),
      );
}

class _MiniStepButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;

  const _MiniStepButton({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 30,
        height: 28,
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
            padding: EdgeInsets.zero,
            side: BorderSide(color: AssistantTheme.border2.withOpacity(0.8)),
            foregroundColor: AssistantTheme.c1,
          ),
          child: Text(
            label,
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 12,
            ),
          ),
        ),
      );
}

class _SectionCard extends StatelessWidget {
  final String title;
  final List<Widget> children;
  const _SectionCard({required this.title, required this.children});

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
            border: Border.all(color: AssistantTheme.border),
            borderRadius: BorderRadius.circular(4),
            color: AssistantTheme.surface.withOpacity(0.5)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title,
              style: const TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 2,
                  color: AssistantTheme.c1)),
          const SizedBox(height: 12),
          ...children,
        ]),
      );
}

class _InfoBox extends StatelessWidget {
  final String text;
  const _InfoBox(this.text);
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
            border: Border.all(color: AssistantTheme.c2.withOpacity(0.2)),
            borderRadius: BorderRadius.circular(3),
            color: AssistantTheme.c2.withOpacity(0.04)),
        child: Text(text,
            style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 10,
                color: AssistantTheme.textSecondary,
                height: 1.6)),
      );
}

class _ActionBtn extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;
  final Color color;
  const _ActionBtn(
      {required this.label,
      required this.onTap,
      this.color = AssistantTheme.c1});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 4, bottom: 4),
        child: SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            onPressed: onTap,
            style: OutlinedButton.styleFrom(
              side: BorderSide(color: color.withOpacity(0.4)),
              foregroundColor: color,
              padding: const EdgeInsets.symmetric(vertical: 12),
            ),
            child: Text(label,
                style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 3,
                    color: color)),
          ),
        ),
      );
}

class _TabBtn extends StatelessWidget {
  final String label;
  final bool active;
  final VoidCallback onTap;
  const _TabBtn(
      {required this.label, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(3),
            color: active
                ? AssistantTheme.c1.withOpacity(0.08)
                : Colors.transparent,
            border: Border.all(
              color: active ? AssistantTheme.c1 : Colors.transparent,
              width: active ? 1 : 0,
            ),
          ),
          child: Text(label,
              style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  letterSpacing: 2,
                  color:
                      active ? AssistantTheme.c1 : AssistantTheme.textMuted)),
        ),
      );
}

class _SaveBtn extends StatelessWidget {
  final VoidCallback onTap;
  const _SaveBtn({required this.onTap});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: double.infinity,
        child: ElevatedButton(
          onPressed: onTap,
          style: ElevatedButton.styleFrom(
            backgroundColor: AssistantTheme.c1.withOpacity(0.12),
            side: const BorderSide(color: AssistantTheme.c1, width: 1),
            padding: const EdgeInsets.symmetric(vertical: 13),
          ),
          child: const Text('✅  SALVAR',
              style: TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 4,
                  color: AssistantTheme.c1)),
        ),
      );
}

class _CancelBtn extends StatelessWidget {
  final VoidCallback onTap;
  const _CancelBtn({required this.onTap});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: double.infinity,
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
              side: const BorderSide(color: AssistantTheme.border),
              padding: const EdgeInsets.symmetric(vertical: 11)),
          child: const Text('CANCELAR',
              style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  letterSpacing: 2,
                  color: AssistantTheme.textMuted)),
        ),
      );
}

class _TabContent extends StatelessWidget {
  final String title;
  final List<Widget> children;
  const _TabContent({required this.title, required this.children});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: const TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 6,
                  color: AssistantTheme.c1)),
          const SizedBox(height: 4),
          Container(
              height: 1,
              decoration: const BoxDecoration(
                  gradient: LinearGradient(
                      colors: [AssistantTheme.c1, Colors.transparent]))),
          const SizedBox(height: 24),
          ...children,
        ],
      );
}

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';
import '../providers/app_provider.dart';
import '../services/api_service.dart';
import '../services/calendar_service.dart';
import '../services/connected_ai_service.dart';
import '../services/notification_service.dart';
import '../services/storage_service.dart';
import '../models/app_config.dart';
import '../models/hive_adapters.dart';
import '../utils/theme.dart';
import '../widgets/title_bar.dart';
import '../widgets/left_panel.dart';
import '../widgets/chat_panel.dart';
import '../widgets/right_panel.dart';
import '../widgets/auth_dialog.dart';

class MainScreen extends ConsumerStatefulWidget {
  const MainScreen({super.key});

  @override
  ConsumerState<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends ConsumerState<MainScreen> with WindowListener {
  Timer? _calendarTimer;
  Timer? _backendStatusTimer;
  final Map<String, Timer> _eventNotificationTimers = {};
  final Set<String> _deliveredEventNotifications = {};
  bool _backendStatusSyncing = false;

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _initScreen();
    });
  }

  Future<void> _initScreen() async {
    await _syncBackendStatus();
    _startBackendStatusSync();
    unawaited(_syncConnectedAgents());

    if (!ref.read(isAuthenticatedProvider)) {
      final storedToken = await StorageService.loadAuthToken();
      api.setToken(storedToken);
      final account = await api.currentAccount();
      if (account != null) {
        // Cada abertura devolve o prazo cheio ao token guardado: sessao velha
        // expirava no meio de uso longo, como uma aula sendo gravada.
        await api.refreshSession();
        await _activateAccount(account);
        ref.read(isAuthenticatedProvider.notifier).state = true;
      } else {
        await _showAuth();
      }
    }

    if (ref.read(isAuthenticatedProvider)) {
      _startWelcome();
      _startCalendarSync();
    }
  }

  Future<void> _activateAccount(CurrentAccount account) async {
    _clearEventNotificationTimers(clearDelivered: true);
    await HiveScope.setCurrent(
      account.id,
      migrateLegacy: account.isAdmin,
    );
    final hadLocalConfig = HiveConfig.read() != null;
    ref.read(configProvider.notifier).loadForCurrentUser();
    await _syncAssistantProfile(account, preferLocal: hadLocalConfig);
    ref.read(chatProvider.notifier).switchUser();
    ref.read(eventsProvider.notifier).switchUser();
    await _syncBackendStatus(attempts: 1);
  }

  Future<void> _syncAssistantProfile(
    CurrentAccount account, {
    required bool preferLocal,
  }) async {
    if (account.tutorId.isEmpty) return;
    try {
      final backend = await api.getTutorProfile(account.tutorId);
      final local = ref.read(configProvider);
      final backendName = backend['assistant_name']?.toString().trim() ?? '';
      final backendCustomized = !_isDefaultAssistantName(backendName);
      final profileConfig = backend['config'] is Map
          ? Map<String, dynamic>.from(backend['config'] as Map)
          : <String, dynamic>{};
      final backendPronunciation =
          profileConfig['assistant_pronunciation']?.toString().trim() ?? '';
      final localName = local.assistantName.trim();
      final localCustomized = !_isDefaultAssistantName(localName);

      if (preferLocal &&
          (localCustomized ||
              local.assistantPronunciation.trim().isNotEmpty ||
              !backendCustomized)) {
        await api.saveAssistantProfile(
          account,
          local,
          currentProfile: backend,
        );
        return;
      }

      if (!backendCustomized && backendPronunciation.isEmpty) return;
      final synced = AppConfig.fromJson({
        ...local.toJson(),
        'assistantName':
            backendCustomized ? backendName : AppConfig.defaultAssistantName,
        'assistantPronunciation': backendPronunciation,
        'assistantGender': backend['gender']?.toString() ?? 'f',
        'personality': backend['personality']?.toString() ?? '',
        'responseMode': backend['response_mode']?.toString() ?? 'single',
        'ttsEnabled': backend['tts_enabled'] != false,
        'language': backend['locale']?.toString() ?? local.language,
      });
      await ref.read(configProvider.notifier).save(synced);
    } catch (e) {
      debugPrint('[assistantProfile] sync failed: $e');
    }
  }

  bool _isDefaultAssistantName(String value) {
    final normalized = value.trim().toLowerCase();
    return normalized.isEmpty ||
        normalized == 'assistant' ||
        normalized == 'assistente';
  }

  /// Detecta os clientes oficiais (Codex/Claude Code) instalados e logados
  /// neste computador para que entrem na lista de agentes selecionáveis.
  Future<void> _syncConnectedAgents() async {
    try {
      final statuses = await ConnectedAiService.checkAll();
      if (!mounted) return;
      ref.read(configProvider.notifier).setConnectedAgents({
        for (final status in statuses) status.id: status.authenticated,
      });
    } catch (e) {
      debugPrint('[syncConnectedAgents] failed: $e');
    }
  }

  void _startBackendStatusSync() {
    _backendStatusTimer?.cancel();
    _backendStatusTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      _syncBackendStatus(attempts: 1);
    });
  }

  Future<void> _syncBackendStatus({int attempts = 5}) async {
    if (_backendStatusSyncing) return;
    _backendStatusSyncing = true;
    try {
      for (var attempt = 0; attempt < attempts; attempt++) {
        try {
          if (attempt > 0) {
            await Future.delayed(const Duration(seconds: 3));
          }
          final health = api.token == null
              ? await api.health()
              : (await api.getLlmConfig()).raw;
          final active = (health['active_llms'] as List<dynamic>? ?? const [])
              .map((e) => e.toString())
              .toList();
          debugPrint('[syncBackend] active_llms: $active');
          final labels = <String, String>{};
          final rawLabels = health['llm_labels'];
          if (rawLabels is Map) {
            for (final entry in rawLabels.entries) {
              labels[entry.key.toString()] = entry.value.toString();
            }
          }
          final statuses = <String, LlmStatus>{};
          final rawStatuses = health['llm_status'];
          if (rawStatuses is Map) {
            for (final entry in rawStatuses.entries) {
              final value = entry.value;
              if (value is Map) {
                statuses[entry.key.toString()] = LlmStatus.fromJson(
                  value.map((key, value) => MapEntry(key.toString(), value)),
                );
              }
            }
          }
          await ref
              .read(configProvider.notifier)
              .setBackendLlms(active, labels: labels, statuses: statuses);
          return;
        } catch (e) {
          debugPrint('[syncBackend] attempt $attempt failed: $e');
        }
      }
    } finally {
      _backendStatusSyncing = false;
    }
  }

  Future<void> _showAuth() async {
    final config = ref.read(configProvider);
    final authStatus = await api.authStatus();
    final storedUsername = await StorageService.loadAuthUsername() ?? '';
    if (!mounted) return;
    final username = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (_) => AuthDialog(
        assistantName: config.assistantName,
        needsSetup: authStatus.needsSetup,
        inviteRegistrationEnabled: authStatus.inviteRegistrationEnabled,
        registrationRequiresToken: authStatus.registrationRequiresToken,
        registrationDeliveryConfigured:
            authStatus.registrationDeliveryConfigured,
        adminEmailHint: authStatus.adminEmailHint,
        initialUsername: storedUsername,
      ),
    );
    if (username != null) {
      final token = api.token;
      if (token != null) await StorageService.saveAuthToken(token);
      await StorageService.saveAuthUsername(username);
      final account = await api.currentAccount();
      if (account != null) await _activateAccount(account);
      ref.read(isAuthenticatedProvider.notifier).state = true;
    } else {
      await windowManager.close();
    }
  }

  void _startWelcome() {
    final config = ref.read(configProvider);
    final available = config.availableAgents;
    final services = available.isEmpty
        ? config.serviceName('backend')
        : available.map((id) => _welcomeServiceName(config, id)).join(', ');
    final selected = config.effectiveAgent;
    final agentLabel = selected == AppConfig.autoAgent
        ? 'Auto (orquestração entre todos)'
        : _welcomeServiceName(config, selected);
    final user = config.userName.isNotEmpty ? ', ${config.userName}' : '';

    ref.read(chatProvider.notifier).addMessage(ChatMessage(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          role: 'assistant',
          content: '${config.assistantName} pronto.\n\n'
              'Olá$user. Pode falar ou escrever para começar.\n\n'
              '• Serviços: $services\n'
              '• Agente: $agentLabel — toque nos marcadores da conversa '
              'para trocar\n'
              '• Modo: ${AppConfig.responseModeLabel(config.responseMode)}',
          llm: available.isNotEmpty ? available.first : null,
        ));
  }

  String _welcomeServiceName(AppConfig config, String id) {
    const compactNames = {
      'together': 'Together',
      'openrouter': 'OpenRouter',
      'deepseek': 'DeepSeek',
      'grok': 'Grok',
      'localai': 'LocalAI',
      'llama': 'Ollama',
      'hf': 'Hugging Face',
      'codex_cli': 'Codex conectado',
      'claude_cli': 'Claude conectado',
    };
    return compactNames[id] ?? config.serviceName(id);
  }

  void _startCalendarSync() {
    _syncCalendar();
    _calendarTimer =
        Timer.periodic(const Duration(minutes: 5), (_) => _syncCalendar());
  }

  Future<void> _syncCalendar() async {
    final config = ref.read(configProvider);
    final calSvc = CalendarService(config.calendar);
    final events = await calSvc.fetchAllEvents();
    ref.read(eventsProvider.notifier).setEvents(events);
    _scheduleNotifications(events);
  }

  void _scheduleNotifications(List<CalendarEvent> events) {
    final config = ref.read(configProvider);
    final notifSvc = NotificationService(config.notif, config.assistantName);
    final activeKeys = <String>{};

    for (final event in events) {
      if (!event.isUpcoming) continue;
      final reminderMinutes = config.notif.reminderMinutes;
      final ms15 = event.startTime
          .subtract(Duration(minutes: reminderMinutes))
          .difference(DateTime.now())
          .inMilliseconds;
      final ms0 = event.startTime.difference(DateTime.now()).inMilliseconds;

      if (config.notif.notify15min && ms15 > 0 && !event.notified15) {
        final key = '${event.id}:advance:$reminderMinutes';
        activeKeys.add(key);
        _scheduleEventNotification(key, Duration(milliseconds: ms15), () async {
          ref.read(eventsProvider.notifier).markNotified(event.id, true);
          final result = await notifSvc.send(
            notifSvc.buildEventMessage(event, is15min: true),
            event: event,
          );
          ref.read(chatProvider.notifier).addMessage(ChatMessage(
                id: DateTime.now().millisecondsSinceEpoch.toString(),
                role: 'system',
                content: '⏰ **Lembrete:** ${event.title} em '
                    '$reminderMinutes minutos\n${result.summary}',
              ));
        });
      }

      if (config.notif.notifyOnTime && ms0 > 0 && !event.notifiedOnTime) {
        final key = '${event.id}:0';
        activeKeys.add(key);
        _scheduleEventNotification(key, Duration(milliseconds: ms0), () async {
          ref.read(eventsProvider.notifier).markNotified(event.id, false);
          final result = await notifSvc.send(
            notifSvc.buildEventMessage(event, is15min: false),
            event: event,
          );
          ref.read(chatProvider.notifier).addMessage(ChatMessage(
                id: DateTime.now().millisecondsSinceEpoch.toString(),
                role: 'system',
                content: '🔔 **Agora:** ${event.title} está começando!'
                    '\n${result.summary}',
              ));
        });
      }
    }

    final obsolete = _eventNotificationTimers.keys
        .where((key) => !activeKeys.contains(key))
        .toList();
    for (final key in obsolete) {
      _eventNotificationTimers.remove(key)?.cancel();
    }
  }

  void _scheduleEventNotification(
    String key,
    Duration delay,
    Future<void> Function() callback,
  ) {
    if (_deliveredEventNotifications.contains(key) ||
        _eventNotificationTimers.containsKey(key)) {
      return;
    }
    _eventNotificationTimers[key] = Timer(delay, () async {
      _eventNotificationTimers.remove(key);
      if (!_deliveredEventNotifications.add(key)) return;
      await callback();
    });
  }

  void _clearEventNotificationTimers({bool clearDelivered = false}) {
    for (final timer in _eventNotificationTimers.values) {
      timer.cancel();
    }
    _eventNotificationTimers.clear();
    if (clearDelivered) _deliveredEventNotifications.clear();
  }

  @override
  void dispose() {
    _calendarTimer?.cancel();
    _backendStatusTimer?.cancel();
    _clearEventNotificationTimers();
    windowManager.removeListener(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AssistantTheme.bg,
      body: Column(
        children: [
          const AssistantTitleBar(),
          Expanded(
            child: Row(
              children: [
                const LeftPanel(),
                const Expanded(child: ChatPanel()),
                const RightPanel(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

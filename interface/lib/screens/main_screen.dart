import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';
import '../providers/app_provider.dart';
import '../services/api_service.dart';
import '../services/calendar_service.dart';
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

    if (!ref.read(isAuthenticatedProvider)) {
      final storedToken = await StorageService.loadAuthToken();
      api.setToken(storedToken);
      final account = await api.currentAccount();
      if (account != null) {
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
    await HiveScope.setCurrent(
      account.id,
      migrateLegacy: account.isAdmin,
    );
    ref.read(configProvider.notifier).loadForCurrentUser();
    ref.read(chatProvider.notifier).switchUser();
    ref.read(eventsProvider.notifier).switchUser();
    await _syncBackendStatus(attempts: 1);
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
          final health = await api.health();
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
    final services = config.activeList.isEmpty
        ? config.serviceName('backend')
        : config.activeList
            .map((id) => _welcomeServiceName(config, id))
            .join(', ');
    final user = config.userName.isNotEmpty ? ', ${config.userName}' : '';

    ref.read(chatProvider.notifier).addMessage(ChatMessage(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          role: 'assistant',
          content: '${config.assistantName} pronto.\n\n'
              'Olá$user. Pode falar ou escrever para começar.\n\n'
              '• Serviços: $services\n'
              '• Modo: ${AppConfig.responseModeLabel(config.responseMode)}',
          llm: config.activeList.isNotEmpty ? config.activeList.first : null,
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

    for (final event in events) {
      if (!event.isUpcoming) continue;
      final ms15 = event.startTime
          .subtract(const Duration(minutes: 15))
          .difference(DateTime.now())
          .inMilliseconds;
      final ms0 = event.startTime.difference(DateTime.now()).inMilliseconds;

      if (config.notif.notify15min && ms15 > 0 && !event.notified15) {
        Timer(Duration(milliseconds: ms15), () async {
          ref.read(eventsProvider.notifier).markNotified(event.id, true);
          final msg = notifSvc.buildEventMessage(event, is15min: true);
          await notifSvc.send(msg, event: event);
          ref.read(chatProvider.notifier).addMessage(ChatMessage(
                id: DateTime.now().millisecondsSinceEpoch.toString(),
                role: 'system',
                content: '⏰ **Lembrete:** ${event.title} em 15 minutos',
              ));
        });
      }

      if (config.notif.notifyOnTime && ms0 > 0 && !event.notifiedOnTime) {
        Timer(Duration(milliseconds: ms0), () async {
          ref.read(eventsProvider.notifier).markNotified(event.id, false);
          final msg = notifSvc.buildEventMessage(event, is15min: false);
          await notifSvc.send(msg, event: event);
          ref.read(chatProvider.notifier).addMessage(ChatMessage(
                id: DateTime.now().millisecondsSinceEpoch.toString(),
                role: 'system',
                content: '🔔 **Agora:** ${event.title} está começando!',
              ));
        });
      }
    }
  }

  @override
  void dispose() {
    _calendarTimer?.cancel();
    _backendStatusTimer?.cancel();
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

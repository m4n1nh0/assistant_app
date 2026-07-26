import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/app_config.dart';
import '../models/hive_adapters.dart';
import '../services/api_service.dart';

final configProvider = StateNotifierProvider<ConfigNotifier, AppConfig>((ref) {
  return ConfigNotifier();
});

class QueuedChatCommand {
  final String id;
  final String text;

  QueuedChatCommand(this.text)
      : id = DateTime.now().microsecondsSinceEpoch.toString();
}

final queuedChatCommandProvider = StateProvider<QueuedChatCommand?>((ref) {
  return null;
});

class ConfigNotifier extends StateNotifier<AppConfig> {
  ConfigNotifier() : super(AppConfig()) {
    _load();
  }

  void _load() {
    final raw = HiveConfig.read();
    if (raw != null) {
      state = AppConfig.fromJson(raw);
    }
    api.configure(state.backendUrl);
  }

  void loadForCurrentUser() {
    final raw = HiveConfig.read();
    state = raw == null ? AppConfig() : AppConfig.fromJson(raw);
    api.configure(state.backendUrl);
  }

  Future<void> save(AppConfig config) async {
    state = config;
    api.configure(state.backendUrl);
    await HiveConfig.write(config.toSafeJson());
  }

  void replaceInMemory(AppConfig config) {
    state = config;
    api.configure(state.backendUrl);
  }

  Future<void> update(AppConfig Function(AppConfig) updater) async {
    final updated = updater(state);
    await save(updated);
  }

  Future<void> setBackendLlms(
    List<String> llms, {
    Map<String, String>? labels,
    Map<String, LlmStatus>? statuses,
  }) async {
    final active = <String, bool>{};
    for (final id in llms) {
      if (id.trim().isNotEmpty) active[id] = true;
    }
    state = AppConfig.fromJson({
      ...state.toJson(),
      'activeLlms': active,
      'llmLabels': {...state.llmLabels, ...?labels},
      'llmStatus': statuses == null
          ? state.llmStatuses.map((k, v) => MapEntry(k, v.toJson()))
          : statuses.map((k, v) => MapEntry(k, v.toJson())),
    });
    await HiveConfig.write(state.toSafeJson());
  }

  void setMode(String mode) {
    state = AppConfig.fromJson({...state.toJson(), 'responseMode': mode});
    HiveConfig.write(state.toSafeJson());
  }
}

final chatProvider =
    StateNotifierProvider<ChatNotifier, List<ChatMessage>>((ref) {
  return ChatNotifier();
});

class ChatNotifier extends StateNotifier<List<ChatMessage>> {
  ChatNotifier() : super([]);

  void addMessage(ChatMessage msg) {
    state = [...state, msg];
    HiveConversations.append({
      'id': msg.id,
      'role': msg.role,
      'content': msg.content,
      'llm': msg.llm,
      'timestamp': msg.timestamp.toIso8601String(),
    });
  }

  void clear() {
    state = [];
    HiveConversations.clearAll();
  }

  void switchUser() {
    state = [];
  }

  List<Map<String, String>> toApiHistory(int last) {
    final recent = state.where((m) => m.role != 'system').toList();
    final slice =
        recent.length > last ? recent.sublist(recent.length - last) : recent;
    return slice
        .map((m) => {
              'role': m.role == 'assistant' ? 'assistant' : 'user',
              'content': m.content,
            })
        .toList();
  }
}

final eventsProvider =
    StateNotifierProvider<EventsNotifier, List<CalendarEvent>>((ref) {
  return EventsNotifier();
});

class EventsNotifier extends StateNotifier<List<CalendarEvent>> {
  EventsNotifier() : super([]);

  void setEvents(List<CalendarEvent> events) {
    state = events..sort((a, b) => a.startTime.compareTo(b.startTime));
  }

  void switchUser() {
    state = [];
  }

  void addEvent(CalendarEvent event) {
    state = [...state, event]
      ..sort((a, b) => a.startTime.compareTo(b.startTime));
  }

  void markNotified(String id, bool is15) {
    state = state.map((e) {
      if (e.id == id) {
        if (is15) {
          e.notified15 = true;
        } else {
          e.notifiedOnTime = true;
        }
      }
      return e;
    }).toList();
  }
}

final isLoadingProvider = StateProvider<bool>((ref) => false);
final isAuthenticatedProvider = StateProvider<bool>((ref) => false);
final isRecordingProvider = StateProvider<bool>((ref) => false);
final isSpeakingProvider = StateProvider<bool>((ref) => false);
final activeTabProvider = StateProvider<int>((ref) => 0);
final sideTabProvider = StateProvider<String>((ref) => 'chat');

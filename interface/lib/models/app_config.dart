class AppConfig {
  static const serviceLabels = {
    'backend': 'Backend',
    'claude': 'Claude Sonnet 4',
    'gpt': 'GPT-4o',
    'together': 'Together',
    'openrouter': 'OpenRouter',
    'deepseek': 'DeepSeek',
    'gemini': 'Gemini',
    'grok': 'Grok',
    'localai': 'LocalAI',
    'llama': 'Ollama',
    'hf': 'Hugging Face',
  };

  static String serviceLabel(String id) =>
      serviceLabels[id] ?? id.toUpperCase();

  static const responseModeLabels = {
    'single': 'Padrão',
    'multi': 'Paralelo',
    'chain': 'Etapas',
  };

  static String responseModeLabel(String id) =>
      responseModeLabels[id] ?? id.toUpperCase();

  String assistantName;
  String userName;
  String personality;
  String responseMode;
  String language;
  String assistantGender;

  Map<String, bool> activeLlms;
  Map<String, String> llmLabels;
  Map<String, LlmStatus> llmStatuses;

  NotifConfig notif;

  CalendarConfig calendar;

  bool ttsEnabled;
  bool continuousVoiceMode;
  bool sendMessageOnEnter;
  int voicePromptRetries;
  bool startMinimized;
  bool autoLaunch;
  String hotkey;
  String backendUrl;
  String audioInputDeviceId;
  String audioInputDeviceLabel;

  /// Voz neural usada pela interface. Vazio deixa a escolha pelo genero.
  String ttsVoice;

  /// Calibracao da voz: velocidade em % e tom em Hz, ambos relativos ao padrao.
  int ttsRatePercent;
  int ttsPitchHz;

  static const defaultBackendUrl = String.fromEnvironment('APP_BACKEND_URL',
      defaultValue: 'http://localhost:8000');

  AppConfig({
    this.assistantName = 'Assistente',
    this.userName = '',
    this.personality = '',
    this.responseMode = 'single',
    this.language = 'pt-BR',
    this.assistantGender = 'f',
    Map<String, bool>? activeLlms,
    Map<String, String>? llmLabels,
    Map<String, LlmStatus>? llmStatuses,
    NotifConfig? notif,
    CalendarConfig? calendar,
    this.ttsEnabled = true,
    this.continuousVoiceMode = true,
    this.sendMessageOnEnter = true,
    this.voicePromptRetries = 3,
    this.startMinimized = false,
    this.autoLaunch = false,
    this.hotkey = 'ctrl+shift+space',
    this.audioInputDeviceId = '',
    this.audioInputDeviceLabel = '',
    this.ttsVoice = '',
    this.ttsRatePercent = 0,
    this.ttsPitchHz = 0,
    String? backendUrl,
  })  : backendUrl = (backendUrl == null || backendUrl.trim().isEmpty)
            ? defaultBackendUrl
            : backendUrl,
        activeLlms =
            activeLlms ?? {for (final id in serviceLabels.keys) id: false},
        llmLabels = {...serviceLabels, ...?llmLabels},
        llmStatuses = llmStatuses ?? {},
        notif = notif ?? NotifConfig(),
        calendar = calendar ?? CalendarConfig();

  List<String> get activeList =>
      activeLlms.entries.where((e) => e.value).map((e) => e.key).toList();

  String serviceName(String id) => llmLabels[id] ?? serviceLabel(id);
  LlmStatus? serviceStatus(String id) => llmStatuses[id];

  bool get isConfigured => true;

  Map<String, dynamic> toJson() => {
        'assistantName': assistantName,
        'userName': userName,
        'personality': personality,
        'responseMode': responseMode,
        'language': language,
        'assistantGender': assistantGender,
        'activeLlms': activeLlms,
        'llmLabels': llmLabels,
        'llmStatus':
            llmStatuses.map((key, value) => MapEntry(key, value.toJson())),
        'notif': notif.toJson(),
        'calendar': calendar.toJson(),
        'ttsEnabled': ttsEnabled,
        'continuousVoiceMode': continuousVoiceMode,
        'sendMessageOnEnter': sendMessageOnEnter,
        'voicePromptRetries': voicePromptRetries,
        'startMinimized': startMinimized,
        'autoLaunch': autoLaunch,
        'hotkey': hotkey,
        'backendUrl': backendUrl,
        'audioInputDeviceId': audioInputDeviceId,
        'audioInputDeviceLabel': audioInputDeviceLabel,
        'ttsVoice': ttsVoice,
        'ttsRatePercent': ttsRatePercent,
        'ttsPitchHz': ttsPitchHz,
      };

  Map<String, dynamic> toSafeJson() => toJson();

  factory AppConfig.fromJson(Map<String, dynamic> j) {
    final activeLlms = <String, bool>{};
    for (final entry in _map(j['activeLlms']).entries) {
      activeLlms[entry.key] = entry.value == true;
    }

    return AppConfig(
      assistantName: j['assistantName'] ?? 'Assistente',
      userName: j['userName'] ?? '',
      personality: j['personality'] ?? '',
      responseMode: j['responseMode'] ?? 'single',
      language: j['language'] ?? 'pt-BR',
      assistantGender: j['assistantGender'] ?? j['gender'] ?? 'f',
      activeLlms: activeLlms,
      llmLabels: _stringMap(j['llmLabels']),
      llmStatuses: _llmStatusMap(j['llmStatus'] ?? j['llm_status']),
      notif: NotifConfig.fromJson(_map(j['notif'])),
      calendar: CalendarConfig.fromJson(_map(j['calendar'])),
      ttsEnabled: j['ttsEnabled'] ?? true,
      continuousVoiceMode: j['continuousVoiceMode'] ?? true,
      sendMessageOnEnter: j['sendMessageOnEnter'] ?? true,
      voicePromptRetries: _intValue(j['voicePromptRetries'], fallback: 3),
      startMinimized: j['startMinimized'] ?? false,
      autoLaunch: j['autoLaunch'] ?? false,
      hotkey: j['hotkey'] ?? 'ctrl+shift+space',
      backendUrl: j['backendUrl']?.toString(),
      audioInputDeviceId: j['audioInputDeviceId']?.toString() ?? '',
      audioInputDeviceLabel: j['audioInputDeviceLabel']?.toString() ?? '',
      ttsVoice: j['ttsVoice']?.toString() ?? '',
      ttsRatePercent: _intValue(j['ttsRatePercent'], fallback: 0),
      ttsPitchHz: _intValue(j['ttsPitchHz'], fallback: 0),
    );
  }

  static Map<String, dynamic> _map(Object? value) {
    if (value is Map) {
      return value.map((key, value) => MapEntry(key.toString(), value));
    }
    return {};
  }

  static Map<String, String> _stringMap(Object? value) {
    if (value is Map) {
      return value.map(
        (key, value) => MapEntry(key.toString(), value.toString()),
      );
    }
    return {};
  }

  static Map<String, LlmStatus> _llmStatusMap(Object? value) {
    if (value is Map) {
      return value.map(
        (key, value) => MapEntry(
          key.toString(),
          LlmStatus.fromJson(_map(value)),
        ),
      );
    }
    return {};
  }

  static int _intValue(Object? value, {required int fallback}) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '') ?? fallback;
  }
}

class LlmStatus {
  final String id;
  final String label;
  final bool configured;
  final bool online;
  final bool available;
  final bool hasBalanceCheck;
  final bool? balanceOk;
  final String? balance;
  final String? currency;
  final String status;
  final String? error;

  const LlmStatus({
    required this.id,
    required this.label,
    required this.configured,
    required this.online,
    required this.available,
    required this.hasBalanceCheck,
    this.balanceOk,
    this.balance,
    this.currency,
    required this.status,
    this.error,
  });

  factory LlmStatus.fromJson(Map<String, dynamic> json) => LlmStatus(
        id: json['id']?.toString() ?? '',
        label: json['label']?.toString() ?? '',
        configured: json['configured'] == true,
        online: json['online'] == true,
        available: json['available'] == true,
        hasBalanceCheck: json['has_balance_check'] == true ||
            json['hasBalanceCheck'] == true,
        balanceOk: _nullableBool(json['balance_ok'] ?? json['balanceOk']),
        balance: json['balance']?.toString(),
        currency: json['currency']?.toString(),
        status: json['status']?.toString() ?? 'unknown',
        error: json['error']?.toString(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'label': label,
        'configured': configured,
        'online': online,
        'available': available,
        'hasBalanceCheck': hasBalanceCheck,
        'balanceOk': balanceOk,
        'balance': balance,
        'currency': currency,
        'status': status,
        'error': error,
      };

  String get shortStatus {
    if (!configured) return 'SEM CHAVE';
    if (status == 'checking') return 'CHECANDO';
    if (!online) return 'OFF';
    if (balanceOk == false) return 'SEM SALDO';
    return 'ONLINE';
  }

  static bool? _nullableBool(Object? value) {
    if (value == null) return null;
    return value == true;
  }
}

class NotifConfig {
  String tgToken;
  String tgChatId;
  bool tgEnabled;

  String waProvider;
  String waNumber;
  String waToken;
  String waSid;
  bool waEnabled;

  bool notify15min;
  int reminderMinutes;
  bool notifyOnTime;
  bool fallbackEnabled;
  bool includeLink;

  NotifConfig({
    this.tgToken = '',
    this.tgChatId = '',
    this.tgEnabled = false,
    this.waProvider = 'callmebot',
    this.waNumber = '',
    this.waToken = '',
    this.waSid = '',
    this.waEnabled = false,
    this.notify15min = true,
    this.reminderMinutes = 15,
    this.notifyOnTime = true,
    this.fallbackEnabled = true,
    this.includeLink = true,
  });

  Map<String, dynamic> toJson() => {
        'tgToken': tgToken,
        'tgChatId': tgChatId,
        'tgEnabled': tgEnabled,
        'waProvider': waProvider,
        'waNumber': waNumber,
        'waToken': waToken,
        'waSid': waSid,
        'waEnabled': waEnabled,
        'notify15min': notify15min,
        'reminderMinutes': reminderMinutes,
        'notifyOnTime': notifyOnTime,
        'fallbackEnabled': fallbackEnabled,
        'includeLink': includeLink,
      };

  factory NotifConfig.fromJson(Map<String, dynamic> j) => NotifConfig(
        tgToken: j['tgToken'] ?? j['telegram_token'] ?? '',
        tgChatId: j['tgChatId'] ?? j['telegram_chat_id'] ?? '',
        tgEnabled: j['tgEnabled'] ?? j['telegram_enabled'] ?? false,
        waProvider: j['waProvider'] ?? j['wa_provider'] ?? 'callmebot',
        waNumber: j['waNumber'] ?? j['wa_number'] ?? '',
        waToken: j['waToken'] ?? j['wa_token'] ?? '',
        waSid: j['waSid'] ?? j['wa_sid'] ?? '',
        waEnabled: j['waEnabled'] ?? j['wa_enabled'] ?? false,
        notify15min: j['notify15min'] ?? j['notify_15min'] ?? true,
        reminderMinutes: AppConfig._intValue(
          j['reminderMinutes'] ?? j['reminder_minutes'],
          fallback: 15,
        ).clamp(5, 1440),
        notifyOnTime: j['notifyOnTime'] ?? j['notify_on_time'] ?? true,
        fallbackEnabled: j['fallbackEnabled'] ?? j['fallback_enabled'] ?? true,
        includeLink: j['includeLink'] ?? j['include_link'] ?? true,
      );
}

class CalendarConfig {
  String gcalClientId;
  String gcalClientSecret;
  String gcalRefreshToken;
  bool gcalEnabled;

  String msClientId;
  String msClientSecret;
  String msTenantId;
  String msRefreshToken;
  bool msEnabled;
  bool autoCreateEvents;

  CalendarConfig({
    this.gcalClientId = '',
    this.gcalClientSecret = '',
    this.gcalRefreshToken = '',
    this.gcalEnabled = false,
    this.msClientId = '',
    this.msClientSecret = '',
    this.msTenantId = 'common',
    this.msRefreshToken = '',
    this.msEnabled = false,
    this.autoCreateEvents = false,
  });

  Map<String, dynamic> toJson() => {
        'gcalClientId': gcalClientId,
        'gcalClientSecret': gcalClientSecret,
        'gcalRefreshToken': gcalRefreshToken,
        'gcalEnabled': gcalEnabled,
        'msClientId': msClientId,
        'msClientSecret': msClientSecret,
        'msTenantId': msTenantId,
        'msRefreshToken': msRefreshToken,
        'msEnabled': msEnabled,
        'autoCreateEvents': autoCreateEvents,
      };

  factory CalendarConfig.fromJson(Map<String, dynamic> j) => CalendarConfig(
        gcalClientId: j['gcalClientId'] ?? '',
        gcalClientSecret: j['gcalClientSecret'] ?? '',
        gcalRefreshToken: j['gcalRefreshToken'] ?? '',
        gcalEnabled: j['gcalEnabled'] ?? false,
        msClientId: j['msClientId'] ?? '',
        msClientSecret: j['msClientSecret'] ?? '',
        msTenantId: j['msTenantId'] ?? 'common',
        msRefreshToken: j['msRefreshToken'] ?? '',
        msEnabled: j['msEnabled'] ?? false,
        autoCreateEvents:
            j['autoCreateEvents'] ?? j['auto_create_events'] ?? false,
      );
}

class ChatMessage {
  final String id;
  final String role;
  final String content;
  final String? llm;
  final DateTime timestamp;
  final List<LlmResponse>? multiResponses;

  ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    this.llm,
    DateTime? timestamp,
    this.multiResponses,
  }) : timestamp = timestamp ?? DateTime.now();
}

class LlmResponse {
  final String llm;
  final String content;
  final bool isError;
  final int? durationMs;

  LlmResponse({
    required this.llm,
    required this.content,
    this.isError = false,
    this.durationMs,
  });
}

class ChatResult {
  final List<LlmResponse> responses;
  final LaunchAction? action;
  final ShortcutRegistrationAction? registrationAction;
  final ComputerAction? computerAction;
  final CodingAction? codingAction;
  final CalendarCreateAction? calendarCreateAction;
  final EducationOpenAction? educationOpenAction;

  const ChatResult({
    required this.responses,
    this.action,
    this.registrationAction,
    this.computerAction,
    this.codingAction,
    this.calendarCreateAction,
    this.educationOpenAction,
  });

  LlmResponse get firstResponse => responses.isEmpty
      ? LlmResponse(llm: 'backend', content: 'Sem resposta', isError: true)
      : responses.first;
}

class EducationOpenAction {
  final String destination;
  final String reason;
  final bool requiresConfirmation;

  const EducationOpenAction({
    required this.destination,
    required this.reason,
    this.requiresConfirmation = true,
  });

  factory EducationOpenAction.fromJson(Map<String, dynamic> json) =>
      EducationOpenAction(
        destination: json['destination']?.toString() ?? 'lesson',
        reason: json['reason']?.toString() ?? '',
        requiresConfirmation: json['requires_confirmation'] != false &&
            json['requiresConfirmation'] != false,
      );
}

class LaunchAction {
  final String type;
  final String shortcutId;
  final String name;
  final String target;
  final String targetType;
  final String browser;

  const LaunchAction({
    required this.type,
    required this.shortcutId,
    required this.name,
    required this.target,
    required this.targetType,
    this.browser = '',
  });

  bool get isUrl => targetType == 'url';
  bool get isApp => targetType == 'app';
  bool get isCommand => targetType == 'command';

  factory LaunchAction.fromJson(Map<String, dynamic> json) => LaunchAction(
        type: json['type']?.toString() ?? 'launch',
        shortcutId:
            (json['shortcut_id'] ?? json['shortcutId'])?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        target: json['target']?.toString() ?? '',
        targetType:
            (json['target_type'] ?? json['targetType'])?.toString() ?? 'app',
        browser: json['browser']?.toString() ?? '',
      );
}

class ShortcutRegistrationAction {
  final String type;
  final String name;
  final String query;
  final String target;
  final String targetType;
  final List<String> aliases;
  final String? description;
  final bool openAfterRegister;

  const ShortcutRegistrationAction({
    required this.type,
    required this.name,
    required this.query,
    required this.target,
    required this.targetType,
    this.aliases = const [],
    this.description,
    this.openAfterRegister = false,
  });

  bool get isUrl => targetType == 'url';
  bool get isApp => targetType == 'app';
  bool get isCommand => targetType == 'command';

  factory ShortcutRegistrationAction.fromJson(Map<String, dynamic> json) =>
      ShortcutRegistrationAction(
        type: json['type']?.toString() ?? 'register_shortcut',
        name: json['name']?.toString() ?? '',
        query: json['query']?.toString() ?? '',
        target: json['target']?.toString() ?? '',
        targetType:
            (json['target_type'] ?? json['targetType'])?.toString() ?? 'app',
        aliases: (json['aliases'] as List<dynamic>? ?? const [])
            .map((item) => item.toString())
            .where((item) => item.trim().isNotEmpty)
            .toList(),
        description: json['description']?.toString(),
        openAfterRegister: json['open_after_register'] == true ||
            json['openAfterRegister'] == true,
      );
}

class ComputerAction {
  final String type;
  final String actionId;
  final String name;
  final String description;
  final String riskLevel;
  final bool requiresConfirmation;
  final Map<String, dynamic> arguments;

  const ComputerAction({
    required this.type,
    required this.actionId,
    required this.name,
    required this.description,
    required this.riskLevel,
    required this.requiresConfirmation,
    this.arguments = const {},
  });

  factory ComputerAction.fromJson(Map<String, dynamic> json) => ComputerAction(
        type: json['type']?.toString() ?? 'computer_action',
        actionId: (json['action_id'] ?? json['actionId'])?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        description: json['description']?.toString() ?? '',
        riskLevel:
            (json['risk_level'] ?? json['riskLevel'])?.toString() ?? 'low',
        requiresConfirmation: json['requires_confirmation'] == true ||
            json['requiresConfirmation'] == true,
        arguments: AppConfig._map(json['arguments']),
      );
}

class CodingAction {
  final String type;
  final String actionId;
  final String name;
  final String description;
  final String riskLevel;
  final bool requiresConfirmation;
  final Map<String, dynamic> arguments;

  const CodingAction({
    required this.type,
    required this.actionId,
    required this.name,
    required this.description,
    required this.riskLevel,
    required this.requiresConfirmation,
    this.arguments = const {},
  });

  factory CodingAction.fromJson(Map<String, dynamic> json) => CodingAction(
        type: json['type']?.toString() ?? 'coding_action',
        actionId: (json['action_id'] ?? json['actionId'])?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        description: json['description']?.toString() ?? '',
        riskLevel:
            (json['risk_level'] ?? json['riskLevel'])?.toString() ?? 'low',
        requiresConfirmation: json['requires_confirmation'] == true ||
            json['requiresConfirmation'] == true,
        arguments: AppConfig._map(json['arguments']),
      );
}

class CalendarCreateAction {
  final String type;
  final String title;
  final DateTime startTime;
  final DateTime endTime;
  final String timezone;
  final String provider;
  final String? description;
  final String? location;
  final bool requiresConfirmation;

  const CalendarCreateAction({
    required this.type,
    required this.title,
    required this.startTime,
    required this.endTime,
    required this.timezone,
    required this.provider,
    this.description,
    this.location,
    required this.requiresConfirmation,
  });

  factory CalendarCreateAction.fromJson(Map<String, dynamic> json) =>
      CalendarCreateAction(
        type: json['type']?.toString() ?? 'calendar_create',
        title: json['title']?.toString() ?? '',
        startTime: DateTime.parse(
            (json['start_time'] ?? json['startTime']).toString()),
        endTime:
            DateTime.parse((json['end_time'] ?? json['endTime']).toString()),
        timezone: json['timezone']?.toString() ?? 'America/Sao_Paulo',
        provider: json['provider']?.toString() ?? 'auto',
        description: json['description']?.toString(),
        location: json['location']?.toString(),
        requiresConfirmation: json['requires_confirmation'] == true ||
            json['requiresConfirmation'] == true,
      );
}

class ShortcutEntry {
  final String id;
  final String tutorId;
  final String name;
  final String type;
  final String target;
  final List<String> aliases;
  final String? description;
  final int useCount;
  final DateTime? lastUsedAt;
  final DateTime? createdAt;

  const ShortcutEntry({
    required this.id,
    required this.tutorId,
    required this.name,
    required this.type,
    required this.target,
    this.aliases = const [],
    this.description,
    this.useCount = 0,
    this.lastUsedAt,
    this.createdAt,
  });

  bool get isUrl => type == 'url';
  bool get isCommand => type == 'command';
  String get preferredBrowser => _browserFromDescription(description ?? '');
  String get visibleDescription => _stripBrowserMarker(description ?? '');

  factory ShortcutEntry.fromJson(Map<String, dynamic> json) => ShortcutEntry(
        id: json['id']?.toString() ?? '',
        tutorId: (json['tutor_id'] ?? json['tutorId'])?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        type: json['type']?.toString() ?? 'app',
        target: json['target']?.toString() ?? '',
        aliases: (json['aliases'] as List<dynamic>? ?? const [])
            .map((item) => item.toString())
            .where((item) => item.trim().isNotEmpty)
            .toList(),
        description: json['description']?.toString(),
        useCount: AppConfig._intValue(json['use_count'] ?? json['useCount'],
            fallback: 0),
        lastUsedAt: _date(json['last_used_at'] ?? json['lastUsedAt']),
        createdAt: _date(json['created_at'] ?? json['createdAt']),
      );

  static DateTime? _date(Object? value) {
    final text = value?.toString();
    if (text == null || text.isEmpty) return null;
    return DateTime.tryParse(text)?.toLocal();
  }

  static String browserMarker(String browser) {
    final normalized = browser.trim().toLowerCase();
    return normalized.isEmpty ? '' : '[assistant:url_browser=$normalized]';
  }

  static String descriptionWithBrowser(String description, String browser) {
    final clean = _stripBrowserMarker(description).trim();
    final marker = browserMarker(browser);
    if (marker.isEmpty) return clean;
    return clean.isEmpty ? marker : '$clean\n$marker';
  }

  static String _browserFromDescription(String description) {
    final match = RegExp(
      r'\[assistant:url_browser=([a-z0-9_-]+)\]',
      caseSensitive: false,
    ).firstMatch(description);
    final browser = match?.group(1)?.trim().toLowerCase() ?? '';
    const allowed = {
      'chrome',
      'edge',
      'firefox',
      'brave',
      'opera',
      'vivaldi',
      'chromium',
    };
    return allowed.contains(browser) ? browser : '';
  }

  static String _stripBrowserMarker(String description) => description
      .replaceAll(
        RegExp(r'\s*\[assistant:url_browser=[a-z0-9_-]+\]\s*',
            caseSensitive: false),
        '\n',
      )
      .trim();
}

class ShortcutLaunchEntry {
  final String id;
  final String tutorId;
  final String? shortcutId;
  final String shortcutName;
  final String targetType;
  final String target;
  final String status;
  final String source;
  final String? platform;
  final Map<String, dynamic> request;
  final Map<String, dynamic> result;
  final String? error;
  final DateTime launchedAt;

  const ShortcutLaunchEntry({
    required this.id,
    required this.tutorId,
    this.shortcutId,
    required this.shortcutName,
    required this.targetType,
    required this.target,
    required this.status,
    required this.source,
    this.platform,
    this.request = const {},
    this.result = const {},
    this.error,
    required this.launchedAt,
  });

  factory ShortcutLaunchEntry.fromJson(Map<String, dynamic> json) =>
      ShortcutLaunchEntry(
        id: json['id']?.toString() ?? '',
        tutorId: (json['tutor_id'] ?? json['tutorId'])?.toString() ?? '',
        shortcutId: (json['shortcut_id'] ?? json['shortcutId'])?.toString(),
        shortcutName:
            (json['shortcut_name'] ?? json['shortcutName'])?.toString() ?? '',
        targetType:
            (json['target_type'] ?? json['targetType'])?.toString() ?? 'app',
        target: json['target']?.toString() ?? '',
        status: json['status']?.toString() ?? '',
        source: json['source']?.toString() ?? '',
        platform: json['platform']?.toString(),
        request: AppConfig._map(json['request']),
        result: AppConfig._map(json['result']),
        error: json['error']?.toString(),
        launchedAt: ShortcutEntry._date(
              json['launched_at'] ?? json['launchedAt'],
            ) ??
            DateTime.fromMillisecondsSinceEpoch(0),
      );
}

class CalendarEvent {
  final String id;
  final String title;
  final DateTime startTime;
  final DateTime? endTime;
  final String source;
  final String? meetingUrl;
  final String? description;
  bool notified15;
  bool notifiedOnTime;

  CalendarEvent({
    required this.id,
    required this.title,
    required this.startTime,
    this.endTime,
    required this.source,
    this.meetingUrl,
    this.description,
    this.notified15 = false,
    this.notifiedOnTime = false,
  });

  bool get isUpcoming => startTime.isAfter(DateTime.now());
  Duration get timeUntil => startTime.difference(DateTime.now());

  factory CalendarEvent.fromJson(Map<String, dynamic> json) => CalendarEvent(
        id: json['id']?.toString() ?? '',
        title: json['title']?.toString() ?? 'Sem título',
        startTime: DateTime.parse(
          (json['start_time'] ?? json['startTime']).toString(),
        ).toLocal(),
        endTime: (json['end_time'] ?? json['endTime']) != null
            ? DateTime.parse(
                (json['end_time'] ?? json['endTime']).toString(),
              ).toLocal()
            : null,
        source: json['source']?.toString() ?? 'google',
        meetingUrl: (json['meeting_url'] ?? json['meetingUrl'])?.toString(),
        description: json['description']?.toString(),
        notified15: json['notified_15'] == true || json['notified15'] == true,
        notifiedOnTime:
            json['notified_0'] == true || json['notifiedOnTime'] == true,
      );
}

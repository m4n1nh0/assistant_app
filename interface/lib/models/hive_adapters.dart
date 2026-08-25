/// Acesso ao armazenamento local em Hive, isolado por conta.
///
/// O escopo em [HiveScope] e o que impede uma conta de ler o cache de outra na
/// mesma maquina.
library;

import 'package:hive/hive.dart';

void registerHiveAdapters() {
}

/// Escopo do armazenamento local, isolando os dados por conta.
///
/// Sem isso, trocar de usuario na mesma maquina faria uma conta ler o cache da
/// outra.
class HiveScope {
  static String current = 'legacy';

  static Future<void> setCurrent(
    String userId, {
    bool migrateLegacy = false,
  }) async {
    final clean = userId.trim();
    current = clean.isEmpty ? 'legacy' : clean;
    if (!migrateLegacy || current == 'legacy') return;

    final config = Hive.box('config');
    final scopedConfigKey = 'app_config:$current';
    if (config.get(scopedConfigKey) == null &&
        config.get('app_config') != null) {
      await config.put(scopedConfigKey, config.get('app_config'));
    }

    for (final boxName in ['conversations', 'events']) {
      final box = Hive.box(boxName);
      for (final entry in box.toMap().entries) {
        if (entry.value is! Map) continue;
        final data = Map<String, dynamic>.from(entry.value as Map);
        if (data['user_scope'] == null) {
          data['user_scope'] = current;
          await box.put(entry.key, data);
        }
      }
    }
  }
}

/// Leitura e escrita da configuracao no Hive.
class HiveConfig {
  static const _box = 'config';
  static const _key = 'app_config';
  static String get _scopedKey => '$_key:${HiveScope.current}';

  static Map<String, dynamic>? read() {
    final box = Hive.box(_box);
    final raw = HiveScope.current == 'legacy'
        ? box.get(_key)
        : box.get(_scopedKey);
    if (raw == null) return null;
    return Map<String, dynamic>.from(raw as Map);
  }

  static Future<void> write(Map<String, dynamic> data) async {
    final box = Hive.box(_box);
    await box.put(
      HiveScope.current == 'legacy' ? _key : _scopedKey,
      data,
    );
  }

  static Future<void> clear() async {
    final box = Hive.box(_box);
    await box.delete(
      HiveScope.current == 'legacy' ? _key : _scopedKey,
    );
  }
}

/// Cache local das conversas.
class HiveConversations {
  static const _box = 'conversations';

  static List<Map<String, dynamic>> readAll() {
    final box = Hive.box(_box);
    return box.values
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .where((e) => (e['user_scope'] ?? 'legacy') == HiveScope.current)
        .toList();
  }

  static Future<void> append(Map<String, dynamic> msg) async {
    final box = Hive.box(_box);
    await box.add({...msg, 'user_scope': HiveScope.current});
  }

  static Future<void> clearAll() async {
    final box = Hive.box(_box);
    final keys = box.toMap().entries
        .where((entry) {
          if (entry.value is! Map) return false;
          final data = Map<String, dynamic>.from(entry.value as Map);
          return (data['user_scope'] ?? 'legacy') == HiveScope.current;
        })
        .map((entry) => entry.key)
        .toList();
    await box.deleteAll(keys);
  }
}

/// Cache local dos eventos de calendario.
class HiveEvents {
  static const _box = 'events';

  static List<Map<String, dynamic>> readAll() {
    final box = Hive.box(_box);
    return box.values
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .where((e) => (e['user_scope'] ?? 'legacy') == HiveScope.current)
        .toList();
  }

  static Future<void> saveAll(List<Map<String, dynamic>> events) async {
    final box = Hive.box(_box);
    final keys = box.toMap().entries
        .where((entry) {
          if (entry.value is! Map) return false;
          final data = Map<String, dynamic>.from(entry.value as Map);
          return (data['user_scope'] ?? 'legacy') == HiveScope.current;
        })
        .map((entry) => entry.key)
        .toList();
    await box.deleteAll(keys);
    for (final e in events) {
      await box.add({...e, 'user_scope': HiveScope.current});
    }
  }
}

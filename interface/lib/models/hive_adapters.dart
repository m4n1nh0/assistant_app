import 'package:hive/hive.dart';

void registerHiveAdapters() {
}

class HiveConfig {
  static const _box = 'config';
  static const _key = 'app_config';

  static Map<String, dynamic>? read() {
    final box = Hive.box(_box);
    final raw = box.get(_key);
    if (raw == null) return null;
    return Map<String, dynamic>.from(raw as Map);
  }

  static Future<void> write(Map<String, dynamic> data) async {
    final box = Hive.box(_box);
    await box.put(_key, data);
  }

  static Future<void> clear() async {
    final box = Hive.box(_box);
    await box.delete(_key);
  }
}

class HiveConversations {
  static const _box = 'conversations';

  static List<Map<String, dynamic>> readAll() {
    final box = Hive.box(_box);
    return box.values.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  static Future<void> append(Map<String, dynamic> msg) async {
    final box = Hive.box(_box);
    await box.add(msg);
  }

  static Future<void> clearAll() async {
    await Hive.box(_box).clear();
  }
}

class HiveEvents {
  static const _box = 'events';

  static List<Map<String, dynamic>> readAll() {
    final box = Hive.box(_box);
    return box.values.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  static Future<void> saveAll(List<Map<String, dynamic>> events) async {
    final box = Hive.box(_box);
    await box.clear();
    for (final e in events) { await box.add(e); }
  }
}

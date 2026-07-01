import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../models/app_config.dart';
import '../models/hive_adapters.dart';

class StorageService {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  static Future<void> saveConfig(AppConfig config) async {
    await _storage.write(key: 'auth_pin', value: config.auth.pin);
    await _storage.write(key: 'auth_voice', value: config.auth.voicePassphrase);
    await _storage.write(
        key: 'auth_face', value: config.auth.faceEmbedding ?? '');

    await HiveConfig.write(config.toSafeJson());
  }

  static Future<AppConfig?> loadConfig() async {
    final raw = HiveConfig.read();
    if (raw == null) return null;

    var pin = '';
    var voice = '';
    String? face;
    try {
      pin = await _storage.read(key: 'auth_pin') ?? '';
      voice = await _storage.read(key: 'auth_voice') ?? '';
      final storedFace = await _storage.read(key: 'auth_face') ?? '';
      face = storedFace.isEmpty ? null : storedFace;
    } catch (_) {}

    if (raw['auth'] is Map) {
      (raw['auth'] as Map)['pin'] = pin;
      (raw['auth'] as Map)['voicePassphrase'] = voice;
      (raw['auth'] as Map)['faceEmbedding'] = face;
    }

    return AppConfig.fromJson(raw);
  }

  static Future<void> clearAll() async {
    await _storage.deleteAll();
    await HiveConfig.clear();
    await HiveConversations.clearAll();
  }

  static Future<bool> hasConfig() async {
    return HiveConfig.read() != null;
  }
}

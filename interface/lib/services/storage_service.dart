import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../models/app_config.dart';
import '../models/hive_adapters.dart';

class StorageService {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  static Future<void> saveConfig(AppConfig config) async {
    await HiveConfig.write(config.toSafeJson());
  }

  static Future<AppConfig?> loadConfig() async {
    final raw = HiveConfig.read();
    if (raw == null) return null;
    return AppConfig.fromJson(raw);
  }

  static Future<void> saveAuthToken(String token) async {
    await _storage.write(key: 'auth_token', value: token);
  }

  static Future<String?> loadAuthToken() async {
    try {
      return await _storage.read(key: 'auth_token');
    } catch (_) {
      return null;
    }
  }

  static Future<void> clearAuthToken() async {
    await _storage.delete(key: 'auth_token');
  }

  static Future<void> saveAuthUsername(String username) async {
    await _storage.write(key: 'auth_username', value: username);
  }

  static Future<String?> loadAuthUsername() async {
    try {
      return await _storage.read(key: 'auth_username');
    } catch (_) {
      return null;
    }
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

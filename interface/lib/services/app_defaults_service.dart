/// Carrega defaults de distribuicao antes da interface iniciar.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart' show rootBundle;

import '../models/app_config.dart';

class AppDefaultsService {
  static const _assetPath = 'assets/config/app_defaults.json';
  static const _externalFileName = 'intarq_config.json';
  static const _externalConfigDir = 'config';

  static String environment = 'development';
  static String source = 'fallback';

  static Future<void> load() async {
    Map<String, dynamic>? assetDefaults;
    try {
      assetDefaults = _decode(await rootBundle.loadString(_assetPath));
      _apply(assetDefaults, sourceName: _assetPath);
    } catch (_) {
      AppConfig.setDefaultBackendUrl(AppConfig.developmentBackendUrl);
    }

    final externalDefaults = await _loadExternalDefaults();
    if (externalDefaults != null) {
      _apply(externalDefaults, sourceName: _externalFileName);
    } else if (assetDefaults == null) {
      source = 'fallback';
    }
  }

  static Map<String, dynamic> _decode(String raw) {
    final decoded = jsonDecode(raw);
    if (decoded is Map<String, dynamic>) return decoded;
    if (decoded is Map) {
      return decoded.map((key, value) => MapEntry(key.toString(), value));
    }
    return {};
  }

  static void _apply(
    Map<String, dynamic> defaults, {
    required String sourceName,
  }) {
    final backendUrl = defaults['backendUrl']?.toString().trim() ?? '';
    if (backendUrl.isNotEmpty) {
      AppConfig.setDefaultBackendUrl(backendUrl);
    }
    final env = defaults['environment']?.toString().trim() ?? '';
    if (env.isNotEmpty) environment = env;
    source = sourceName;
  }

  static Future<Map<String, dynamic>?> _loadExternalDefaults() async {
    final executable = File(Platform.resolvedExecutable);
    final executableDir = executable.parent;
    final candidates = [
      File('${executableDir.path}${Platform.pathSeparator}$_externalFileName'),
      File(
        '${executableDir.path}${Platform.pathSeparator}'
        '$_externalConfigDir${Platform.pathSeparator}$_externalFileName',
      ),
    ];

    for (final file in candidates) {
      try {
        if (await file.exists()) {
          return _decode(await file.readAsString());
        }
      } catch (_) {
        // Ignora arquivo invalido/sem permissao e segue com o default embarcado.
      }
    }
    return null;
  }
}

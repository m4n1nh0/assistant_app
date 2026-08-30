/// Carrega defaults de distribuicao antes da interface iniciar.
///
/// A ordem e: asset embarcado (`assets/config/app_defaults.json`), depois um
/// `intarq_config.json` ao lado do executavel, que sobrepoe o asset. Sem
/// nenhum dos dois, o app cai para `localhost:8000`.
///
/// Esse fallback e util em desenvolvimento e **perigoso em producao**: um build
/// que saia sem o asset aponta todos os usuarios para a maquina deles. Por isso
/// a falha nao e mais engolida - ela vira log de erro e fica registrada em
/// [loadError], que a tela de configuracao exibe.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show debugPrint;
import 'package:flutter/services.dart' show rootBundle;

import '../models/app_config.dart';

class AppDefaultsService {
  static const _assetPath = 'assets/config/app_defaults.json';
  static const _externalFileName = 'intarq_config.json';
  static const _externalConfigDir = 'config';

  /// Valor usado quando nenhuma fonte de defaults e encontrada.
  static const fallbackSource = 'fallback';

  static String environment = 'development';
  static String source = fallbackSource;

  /// Motivo da falha ao ler o asset embarcado, vazio quando deu certo.
  static String loadError = '';

  /// Diz se o app esta rodando com o endereco de desenvolvimento por falta de
  /// configuracao, e nao por escolha.
  static bool get usingFallback => source == fallbackSource;

  static Future<void> load() async {
    loadError = '';
    Map<String, dynamic>? assetDefaults;
    try {
      assetDefaults = _decode(await rootBundle.loadString(_assetPath));
      _apply(assetDefaults, sourceName: _assetPath);
    } catch (error) {
      // Erro visivel de proposito: sem esta mensagem, um build sem o asset se
      // comporta como se estivesse configurado para localhost, e a unica pista
      // e o app nao conectar.
      loadError = '$error';
      debugPrint(
        '[AppDefaults] ERRO: nao foi possivel ler $_assetPath ($error). '
        'Usando ${AppConfig.developmentBackendUrl} como endereco do backend. '
        'Em producao isto e um build quebrado: confira se o arquivo existe e '
        'se assets/config/ esta declarado no pubspec.yaml.',
      );
      AppConfig.setDefaultBackendUrl(AppConfig.developmentBackendUrl);
    }

    final externalDefaults = await _loadExternalDefaults();
    if (externalDefaults != null) {
      _apply(externalDefaults, sourceName: _externalFileName);
    } else if (assetDefaults == null) {
      source = fallbackSource;
    }

    if (usingFallback) {
      debugPrint(
        '[AppDefaults] nenhuma fonte de configuracao encontrada; '
        'backend padrao = ${AppConfig.defaultBackendUrl}',
      );
    } else {
      debugPrint(
        '[AppDefaults] origem=$source ambiente=$environment '
        'backend=${AppConfig.defaultBackendUrl}',
      );
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
      } catch (error) {
        // Arquivo invalido ou sem permissao nao derruba o app, mas tambem nao
        // pode sumir: quem colocou o arquivo ali espera que ele valha.
        debugPrint(
          '[AppDefaults] ERRO ao ler ${file.path}: $error. '
          'Seguindo com o default embarcado.',
        );
      }
    }
    return null;
  }
}

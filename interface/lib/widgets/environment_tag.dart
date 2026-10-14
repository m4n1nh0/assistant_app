/// Etiqueta de ambiente no cabeçalho: em qual servidor o app está conectado.
///
/// O mesmo app aponta para `localhost` ou para a produção, e o que existe em um não aparece
/// no outro. A etiqueta pergunta ao servidor (`/health/live`) onde ele roda e mostra o
/// ambiente, o endereço e o commit em execução. Produção fica discreta; qualquer outro
/// ambiente chama atenção, para ninguém trabalhar no lugar errado sem perceber.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../services/api_service.dart';
import '../utils/theme.dart';

/// O que o servidor respondeu sobre si mesmo.
class ServerInfo {
  final String environment;
  final String revision;
  final double uptimeSeconds;

  const ServerInfo({this.environment = '', this.revision = '', this.uptimeSeconds = 0});

  factory ServerInfo.fromJson(Map<String, dynamic> json) => ServerInfo(
        environment: json['environment']?.toString() ?? '',
        revision: json['revision']?.toString() ?? '',
        uptimeSeconds: (json['uptime_seconds'] as num?)?.toDouble() ?? 0,
      );
}

typedef ServerInfoFetcher = Future<ServerInfo> Function(String baseUrl);

Future<ServerInfo> fetchServerInfo(String baseUrl) async {
  final response = await http
      .get(Uri.parse('${baseUrl.replaceAll(RegExp(r'/+$'), '')}/health/live'))
      .timeout(const Duration(seconds: 6));
  if (response.statusCode >= 400) throw Exception('HTTP ${response.statusCode}');
  return ServerInfo.fromJson(Map<String, dynamic>.from(jsonDecode(response.body) as Map));
}

/// "assistantapp-production-cabc.up.railway.app" a partir do endereço completo.
String hostOf(String baseUrl) => Uri.tryParse(baseUrl)?.host.isNotEmpty == true
    ? Uri.parse(baseUrl).host
    : baseUrl;

String _uptime(double seconds) {
  final minutes = (seconds / 60).floor();
  if (minutes < 60) return '$minutes min';
  final hours = (minutes / 60).floor();
  return hours < 48 ? '$hours h' : '${(hours / 24).floor()} dias';
}

class EnvironmentTag extends StatefulWidget {
  /// Trocam endereço, consulta e intervalo nos testes.
  final String? baseUrl;
  final ServerInfoFetcher? fetch;
  final Duration refreshEvery;

  const EnvironmentTag({
    super.key,
    this.baseUrl,
    this.fetch,
    this.refreshEvery = const Duration(seconds: 45),
  });

  @override
  State<EnvironmentTag> createState() => _EnvironmentTagState();
}

class _EnvironmentTagState extends State<EnvironmentTag> {
  ServerInfo? _info;
  bool _failed = false;
  String _loadedFor = '';
  Timer? _timer;

  String get _baseUrl => widget.baseUrl ?? api.baseUrl;

  @override
  void initState() {
    super.initState();
    _load();
    if (widget.refreshEvery > Duration.zero) {
      _timer = Timer.periodic(widget.refreshEvery, (_) => _load());
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final url = _baseUrl;
    try {
      final info = await (widget.fetch ?? fetchServerInfo)(url);
      if (!mounted) return;
      setState(() {
        _info = info;
        _failed = false;
        _loadedFor = url;
      });
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final url = _baseUrl;
    // O endereço mudou nas configurações: a etiqueta antiga não vale mais.
    if (_loadedFor.isNotEmpty && _loadedFor != url) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    }
    final info = _info;
    final env = (info?.environment ?? '').toLowerCase();

    final (label, color, strong) = _failed || info == null
        ? ('SEM CONEXÃO', AssistantTheme.textMuted, false)
        : switch (env) {
            'production' => ('PRODUÇÃO', AssistantTheme.c3, false),
            'staging' => ('HOMOLOGAÇÃO', Colors.amber, true),
            'local' => ('LOCAL', Colors.amber, true),
            '' => ('AMBIENTE ?', Colors.amber, true),
            _ => (env.toUpperCase(), Colors.amber, true),
          };

    final details = [
      hostOf(url),
      if (info != null && info.revision.isNotEmpty) 'commit ${info.revision}',
      if (info != null && info.uptimeSeconds > 0) 'no ar há ${_uptime(info.uptimeSeconds)}',
    ].join('  ·  ');

    return Tooltip(
      message: _failed ? 'O servidor em $url não respondeu.' : '$label\n$details\n$url',
      child: Container(
        key: const Key('environment-tag'),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: strong ? color.withOpacity(.22) : Colors.transparent,
          border: Border.all(color: color.withOpacity(strong ? .9 : .5)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(
            label,
            style: TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 9,
              fontWeight: strong ? FontWeight.w800 : FontWeight.w500,
              letterSpacing: 2,
              color: color,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            hostOf(url),
            key: const Key('environment-host'),
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 9,
              color: AssistantTheme.textMuted,
            ),
          ),
        ]),
      ),
    );
  }
}

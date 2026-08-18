import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/app_config.dart';
import '../services/storage_service.dart';
import '../providers/app_provider.dart';
import '../utils/theme.dart';
import '../branding/intarq_brand.dart';

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  Timer? _startupTimer;

  @override
  void initState() {
    super.initState();
    _startupTimer = Timer(const Duration(milliseconds: 1800), _checkConfig);
  }

  @override
  void dispose() {
    _startupTimer?.cancel();
    super.dispose();
  }

  Future<void> _checkConfig() async {
    AppConfig? config;
    try {
      config =
          await StorageService.loadConfig().timeout(const Duration(seconds: 3));
    } catch (e) {
      debugPrint('Falha ao carregar configuracao inicial: $e');
    }

    if (!mounted) return;

    if (config == null) {
      Navigator.pushReplacementNamed(context, '/config');
      return;
    }

    ref.read(configProvider.notifier).replaceInMemory(config);
    if (!mounted) return;

    Navigator.pushReplacementNamed(context, '/main');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AssistantTheme.bg,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const IntarqLockup(width: 390, height: 160, showDescriptor: true),
            const SizedBox(height: 24),
            SizedBox(
              width: 220,
              child: LinearProgressIndicator(
                backgroundColor: AssistantTheme.border,
                valueColor: AlwaysStoppedAnimation<Color>(
                    AssistantTheme.c1.withOpacity(0.8)),
                minHeight: 1,
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              'INICIANDO...',
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                letterSpacing: 4,
                color: AssistantTheme.textMuted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

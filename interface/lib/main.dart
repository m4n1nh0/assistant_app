/// Ponto de entrada do app desktop.
///
/// Inicializa a janela sem barra nativa (`window_manager`), o cache local (`Hive`) e
/// o atalho global (`hotkey_manager`) antes de montar [AssistantApp].
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';
import 'package:hive_flutter/hive_flutter.dart';
import 'package:hotkey_manager/hotkey_manager.dart';

import 'branding/intarq_brand.dart';
import 'screens/splash_screen.dart';
import 'screens/config_screen.dart';
import 'screens/main_screen.dart';
import 'utils/theme.dart';
import 'models/hive_adapters.dart';
import 'services/app_defaults_service.dart';
import 'services/in_app_notification_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await windowManager.ensureInitialized();
  WindowOptions windowOptions = const WindowOptions(
    size: Size(1400, 900),
    minimumSize: Size(1000, 700),
    center: true,
    backgroundColor: Colors.transparent,
    skipTaskbar: false,
    titleBarStyle: TitleBarStyle.hidden,
    title: IntarqBrand.windowTitle,
  );
  await windowManager.waitUntilReadyToShow(windowOptions);
  await windowManager.show();
  await _ensureWindowMaximized();
  await windowManager.focus();

  await Hive.initFlutter();
  registerHiveAdapters();
  await Hive.openBox('config');
  await Hive.openBox('conversations');
  await Hive.openBox('events');

  await AppDefaultsService.load();

  await hotKeyManager.unregisterAll();

  runApp(const ProviderScope(child: AssistantApp()));
}

/// Raiz do app: tema, rota inicial e escopo do Riverpod.
class AssistantApp extends ConsumerWidget {
  const AssistantApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _StartupWindowMaximizer(
      child: MaterialApp(
        navigatorKey: appNavigatorKey,
        title: IntarqBrand.windowTitle,
        debugShowCheckedModeBanner: false,
        theme: AssistantTheme.darkTheme,
        initialRoute: '/',
        routes: {
          '/': (ctx) => const SplashScreen(),
          '/config': (ctx) => const ConfigScreen(),
          '/main': (ctx) => const MainScreen(),
        },
      ),
    );
  }
}

Future<void> _ensureWindowMaximized() async {
  for (final delay in [Duration.zero, const Duration(milliseconds: 120)]) {
    if (delay > Duration.zero) await Future.delayed(delay);
    if (!await windowManager.isMaximized()) {
      await windowManager.maximize();
    }
  }
}

class _StartupWindowMaximizer extends StatefulWidget {
  final Widget child;

  const _StartupWindowMaximizer({required this.child});

  @override
  State<_StartupWindowMaximizer> createState() =>
      _StartupWindowMaximizerState();
}

class _StartupWindowMaximizerState extends State<_StartupWindowMaximizer> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _ensureWindowMaximized();
    });
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

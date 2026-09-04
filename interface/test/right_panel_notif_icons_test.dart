import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hive/hive.dart';

import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/providers/app_provider.dart';
import 'package:assistant_app/widgets/right_panel.dart';

/// Os quatro icones de notificacao trocaram quatro linhas de interruptor no
/// painel; o clique neles e o que substitui a ida ate a tela de configuracao.
void main() {
  setUpAll(() async {
    // Os setters gravam no Hive: sem a caixa aberta o clique estoura.
    final dir = await Directory.systemTemp.createTemp('assistant_right_panel');
    Hive.init(dir.path);
    await Hive.openBox('config');
  });

  // Sem `Hive.close()` no fim: a gravacao sai de dentro do relogio falso do
  // testWidgets e o close ficaria esperando por ela para sempre. A caixa vai
  // embora com o processo, e a pasta e temporaria.

  Future<ProviderContainer> pump(WidgetTester tester, AppConfig config) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    container.read(configProvider.notifier).replaceInMemory(config);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(
          home: Scaffold(body: Row(children: [RightPanel()])),
        ),
      ),
    );
    return container;
  }

  testWidgets('clique no mic inverte a escuta continua', (tester) async {
    final container = await pump(tester, AppConfig(continuousVoiceMode: false));

    await tester.tap(find.byKey(const Key('notif-icon-mic')));
    await tester.pump();

    expect(container.read(configProvider).continuousVoiceMode, isTrue);

    await tester.tap(find.byKey(const Key('notif-icon-mic')));
    await tester.pump();

    expect(container.read(configProvider).continuousVoiceMode, isFalse);
  });

  testWidgets('clique na voz inverte a fala das respostas', (tester) async {
    final container = await pump(tester, AppConfig(ttsEnabled: true));

    await tester.tap(find.byKey(const Key('notif-icon-tts')));
    await tester.pump();

    expect(container.read(configProvider).ttsEnabled, isFalse);
  });

  testWidgets('canal com credencial liga pelo icone', (tester) async {
    final container = await pump(
      tester,
      AppConfig(notif: NotifConfig(tgToken: 'abc', tgEnabled: false)),
    );

    await tester.tap(find.byKey(const Key('notif-icon-telegram')));
    await tester.pump();

    expect(container.read(configProvider).notif.tgEnabled, isTrue);
    // Ligar o canal nao pode mexer na credencial dele.
    expect(container.read(configProvider).notif.tgToken, 'abc');
  });

  testWidgets('canal sem credencial avisa em vez de ligar', (tester) async {
    final container = await pump(tester, AppConfig());

    await tester.tap(find.byKey(const Key('notif-icon-whatsapp')));
    await tester.pump();

    expect(container.read(configProvider).notif.waEnabled, isFalse);
    expect(find.textContaining('sem número'), findsOneWidget);
    expect(find.text('CONFIGURAR'), findsOneWidget);
  });
}

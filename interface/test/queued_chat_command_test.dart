import 'package:assistant_app/providers/app_provider.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Um clique em comando rapido tem de virar um envio so.
///
/// O defeito real: depois de abrir e salvar a configuracao, a pilha de
/// navegacao ficava com duas telas principais, e os dois chats escutavam a
/// mesma fila - cada clique ia duas vezes ao backend.
void main() {
  test('o primeiro a retirar o comando envia; o segundo encontra a fila vazia',
      () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final queue = container.read(queuedChatCommandProvider.notifier);
    final command = QueuedChatCommand('Como verificar uso de CPU?');
    queue.state = command;

    final first = claimQueuedChatCommand(queue, command.id);
    final second = claimQueuedChatCommand(queue, command.id);

    expect(first?.text, 'Como verificar uso de CPU?');
    expect(second, isNull);
    expect(container.read(queuedChatCommandProvider), isNull);
  });

  test('comando antigo nao retira um comando novo da fila', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final queue = container.read(queuedChatCommandProvider.notifier);
    final newer = QueuedChatCommand('Agenda de hoje');
    queue.state = newer;

    expect(claimQueuedChatCommand(queue, 'id-de-outro-clique'), isNull);
    expect(container.read(queuedChatCommandProvider), same(newer));
  });

  testWidgets('dois chats escutando a fila produzem um envio', (tester) async {
    final sent = <String>[];
    final container = ProviderContainer();
    addTearDown(container.dispose);

    Widget listener() => Consumer(builder: (context, ref, _) {
          ref.listen<QueuedChatCommand?>(queuedChatCommandProvider,
              (previous, next) {
            if (next == null || previous?.id == next.id) return;
            WidgetsBinding.instance.addPostFrameCallback((_) {
              final claimed = claimQueuedChatCommand(
                ref.read(queuedChatCommandProvider.notifier),
                next.id,
              );
              if (claimed != null) sent.add(claimed.text);
            });
          });
          return const SizedBox();
        });

    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: Directionality(
        textDirection: TextDirection.ltr,
        child: Column(children: [listener(), listener()]),
      ),
    ));

    container.read(queuedChatCommandProvider.notifier).state =
        QueuedChatCommand('Monitor do Sistema');
    await tester.pump();

    expect(sent, ['Monitor do Sistema']);
  });
}

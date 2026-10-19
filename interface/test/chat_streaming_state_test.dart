import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/providers/app_provider.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('a resposta em escrita cresce na tela e some do historico guardado', () {
    final chat = ChatNotifier();
    chat.startStreaming(ChatMessage(
      id: 's1',
      role: 'assistant',
      content: 'Ola',
      streaming: true,
    ));
    chat.setStreamingContent('s1', 'Ola, mundo');

    expect(chat.state.single.content, 'Ola, mundo');
    expect(chat.state.single.streaming, true);
  });

  test('reset do modelo esvazia so a mensagem em escrita', () {
    final chat = ChatNotifier();
    chat.state = [ChatMessage(id: 'u1', role: 'user', content: 'oi')];
    chat.startStreaming(ChatMessage(
      id: 's1',
      role: 'assistant',
      content: 'tentativa',
      streaming: true,
    ));

    chat.setStreamingContent('s1', '');

    expect(chat.state.first.content, 'oi');
    expect(chat.state.last.content, '');
  });

  test('withContent preserva o resto da mensagem', () {
    final original = ChatMessage(
      id: 's1',
      role: 'assistant',
      content: 'a',
      llm: 'gpt',
      streaming: true,
    );

    final copy = original.withContent('b');

    expect(copy.content, 'b');
    expect(copy.id, 's1');
    expect(copy.llm, 'gpt');
    expect(copy.streaming, true);
    expect(copy.timestamp, original.timestamp);
  });
}

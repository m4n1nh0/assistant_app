import 'package:flutter_test/flutter_test.dart';
import 'package:assistant_app/services/chat_stream.dart';

Stream<String> lines(List<String> items) => Stream.fromIterable(items);

Future<List<ChatStreamEvent>> read(List<String> items) =>
    parseChatStream(lines(items)).toList();

void main() {
  group('parseChatStream', () {
    test('entrega pedacos, reset e o final na ordem em que chegam', () async {
      final events = await read([
        'data: {"reset": true, "done": false}',
        '',
        'data: {"chunk": "Ola, ", "done": false}',
        'data: {"chunk": "mundo", "done": false}',
        'data: {"chunk": "", "done": true, "content": "Ola, mundo", "llm": "gpt"}',
      ]);

      expect(events[0], isA<ChatStreamReset>());
      expect((events[1] as ChatStreamDelta).text, 'Ola, ');
      expect((events[2] as ChatStreamDelta).text, 'mundo');
      final end = events[3] as ChatStreamFinal;
      final responses = end.data['responses'] as List;
      expect(responses.single['content'], 'Ola, mundo');
      expect(responses.single['llm'], 'gpt');
      expect(responses.single['is_error'], false);
    });

    test('o final carrega acao e leituras no formato do corpo de /chat/', () async {
      final events = await read([
        'data: {"chunk": "", "done": true, "content": "Pronto", "llm": "gpt", '
            '"action": {"type": "launch", "name": "Navegador"}, '
            '"tool_results": [{"kind": "quiz", "tool": "t"}]}',
      ]);

      final data = (events.single as ChatStreamFinal).data;
      expect((data['action'] as Map)['name'], 'Navegador');
      expect((data['tool_results'] as List).length, 1);
    });

    test('final sem acao nem leituras vem vazio, nao nulo quebrado', () async {
      final events = await read([
        'data: {"chunk": "", "done": true, "content": "ok", "llm": "gpt"}',
      ]);

      final data = (events.single as ChatStreamFinal).data;
      expect(data['action'], isNull);
      expect(data['tool_results'], isEmpty);
    });

    test('resposta de erro do servidor chega marcada como erro', () async {
      final events = await read([
        'data: {"chunk": "", "done": true, "content": "sem saldo", "llm": "gpt", "is_error": true}',
      ]);

      final r = ((events.single as ChatStreamFinal).data['responses'] as List).single;
      expect(r['is_error'], true);
    });

    test('backend antigo, sem content, usa o ultimo chunk como resposta inteira', () async {
      final events = await read([
        'data: {"chunk": "Nenhum agente disponivel", "done": true}',
      ]);

      final r = ((events.single as ChatStreamFinal).data['responses'] as List).single;
      expect(r['content'], 'Nenhum agente disponivel');
    });

    test('evento de erro vira ChatStreamError', () async {
      final events = await read(['data: {"error": "grafo caiu", "done": true}']);

      expect((events.single as ChatStreamError).message, 'grafo caiu');
    });

    test('ignora linhas estranhas, JSON quebrado e chunks vazios', () async {
      final events = await read([
        ': ping',
        'event: x',
        'data: isto nao e json',
        'data: [1, 2]',
        'data: {"chunk": "", "done": false}',
        'data:',
        'data: {"chunk": "ok", "done": false}',
      ]);

      expect(events.length, 1);
      expect((events.single as ChatStreamDelta).text, 'ok');
    });
  });
}

import 'dart:convert';
import 'dart:io';

import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/llm_service.dart';
import 'package:flutter_test/flutter_test.dart';

/// Servidor de verdade em localhost: o streaming passa pela rede e pelo parser
/// reais, inclusive com uma linha cortada entre dois pacotes.
Future<HttpServer> serve(Future<void> Function(HttpRequest request) handler) async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  server.listen(handler);
  return server;
}

Future<void> sse(HttpRequest request, List<String> packets) async {
  request.response.headers.contentType = ContentType('text', 'event-stream');
  for (final packet in packets) {
    request.response.write(packet);
    await request.response.flush();
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  await request.response.close();
}

void main() {
  late String previousUrl;

  setUp(() => previousUrl = api.baseUrl);
  tearDown(() => api.configure(previousUrl));

  test('mostra os pedacos, descarta no reset e devolve o resultado final', () async {
    final server = await serve((request) async {
      expect(request.uri.path, '/chat/stream');
      await utf8.decoder.bind(request).join();
      await sse(request, [
        'data: {"chunk": "primeira ", "done": false}\n\n',
        'data: {"reset": true, "done": false}\n\n',
        // Uma linha cortada no meio, como a rede faz.
        'data: {"chunk": "Ola, ',
        'mundo", "done": false}\n\n',
        'data: {"chunk": "", "done": true, "content": "Ola, mundo", "llm": "gpt", '
            '"tool_results": []}\n\n',
      ]);
    });
    addTearDown(() => server.close(force: true));
    api.configure('http://127.0.0.1:${server.port}');

    final seen = <String>[];
    var resets = 0;
    final result = await LlmService().callStream(
      const [],
      'oi',
      onDelta: seen.add,
      onReset: () => resets++,
    );

    expect(seen, ['primeira ', 'Ola, mundo']);
    expect(resets, 1);
    expect(result.firstResponse.content, 'Ola, mundo');
    expect(result.firstResponse.llm, 'gpt');
    expect(result.firstResponse.isError, false);
  });

  test('o resultado final vale mais que o texto acumulado', () async {
    final server = await serve((request) async {
      await utf8.decoder.bind(request).join();
      await sse(request, [
        'data: {"chunk": "texto parcial", "done": false}\n\n',
        'data: {"chunk": "", "done": true, "content": "texto corrigido", "llm": "gpt"}\n\n',
      ]);
    });
    addTearDown(() => server.close(force: true));
    api.configure('http://127.0.0.1:${server.port}');

    final result = await LlmService().callStream(
      const [],
      'oi',
      onDelta: (_) {},
      onReset: () {},
    );

    expect(result.firstResponse.content, 'texto corrigido');
  });

  test('erro do turno vira resposta de erro, sem excecao', () async {
    final server = await serve((request) async {
      await utf8.decoder.bind(request).join();
      await sse(request, ['data: {"error": "grafo caiu", "done": true}\n\n']);
    });
    addTearDown(() => server.close(force: true));
    api.configure('http://127.0.0.1:${server.port}');

    final result = await LlmService().callStream(
      const [],
      'oi',
      onDelta: (_) {},
      onReset: () {},
    );

    expect(result.firstResponse.isError, true);
    expect(result.firstResponse.content, contains('grafo caiu'));
  });

  test('sem streaming no backend, cai para a chamada inteira', () async {
    final paths = <String>[];
    final server = await serve((request) async {
      paths.add(request.uri.path);
      await utf8.decoder.bind(request).join();
      if (request.uri.path == '/chat/stream') {
        request.response.statusCode = 404;
        request.response.write('{"detail": "Not Found"}');
      } else {
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'responses': [
            {'llm': 'gpt', 'content': 'resposta inteira'},
          ],
        }));
      }
      await request.response.close();
    });
    addTearDown(() => server.close(force: true));
    api.configure('http://127.0.0.1:${server.port}');

    final seen = <String>[];
    final result = await LlmService().callStream(
      const [],
      'oi',
      onDelta: seen.add,
      onReset: () {},
    );

    expect(paths, ['/chat/stream', '/chat/']);
    expect(seen, isEmpty);
    expect(result.firstResponse.content, 'resposta inteira');
  });

  test('queda no meio do streaming vira erro e nao repete o turno', () async {
    final paths = <String>[];
    final server = await serve((request) async {
      paths.add(request.uri.path);
      await utf8.decoder.bind(request).join();
      request.response.headers.contentType = ContentType('text', 'event-stream');
      request.response.write('data: {"chunk": "meio", "done": false}\n\n');
      await request.response.flush();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      // Fecha a conexao sem o evento final.
      await request.response.close();
    });
    addTearDown(() => server.close(force: true));
    api.configure('http://127.0.0.1:${server.port}');

    final result = await LlmService().callStream(
      const [],
      'oi',
      onDelta: (_) {},
      onReset: () {},
    );

    expect(result.firstResponse.isError, true);
    // Depois do primeiro evento o turno ja pode ter agido: nao repete.
    expect(paths, ['/chat/stream']);
  });
}

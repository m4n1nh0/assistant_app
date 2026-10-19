import 'dart:convert';

/// Um evento da resposta em streaming do chat (`POST /chat/stream`).
///
/// O backend roda o turno inteiro no grafo (ferramentas, agenda, busca nas
/// aulas) e transmite o texto enquanto o modelo o escreve. O `final` e a
/// verdade: o texto acumulado dos pedacos e so uma previa.
sealed class ChatStreamEvent {
  const ChatStreamEvent();
}

/// O modelo recomecou (outra volta do agente, retentativa): descarte o texto
/// parcial que ja estava na tela.
final class ChatStreamReset extends ChatStreamEvent {
  const ChatStreamReset();
}

/// Mais um pedaco do texto da resposta.
final class ChatStreamDelta extends ChatStreamEvent {
  final String text;
  const ChatStreamDelta(this.text);
}

/// Fim do turno. [data] tem o mesmo formato do corpo de `POST /chat/`
/// (`responses`, `action`, `tool_results`), para quem ja le essa resposta
/// aproveitar o mesmo caminho.
final class ChatStreamFinal extends ChatStreamEvent {
  final Map<String, dynamic> data;
  const ChatStreamFinal(this.data);
}

/// O turno falhou no servidor.
final class ChatStreamError extends ChatStreamEvent {
  final String message;
  const ChatStreamError(this.message);
}

/// Le as linhas de um fluxo SSE e entrega os eventos do chat.
///
/// Linhas que nao sao `data:`, JSON invalido e eventos que nao dizem nada
/// (como o ping) sao ignorados em silencio: uma linha estranha nao pode
/// derrubar a resposta que ja esta na tela.
Stream<ChatStreamEvent> parseChatStream(Stream<String> lines) async* {
  await for (final line in lines) {
    if (!line.startsWith('data:')) continue;
    final raw = line.substring(5).trim();
    if (raw.isEmpty) continue;
    final Object? json;
    try {
      json = jsonDecode(raw);
    } on FormatException {
      continue;
    }
    if (json is! Map) continue;
    final event = chatStreamEventFrom(
      json.map((key, value) => MapEntry(key.toString(), value)),
    );
    if (event != null) yield event;
  }
}

/// Um evento `data:` ja decodificado, ou `null` quando ele nao diz nada.
ChatStreamEvent? chatStreamEventFrom(Map<String, dynamic> json) {
  if (json['error'] != null) return ChatStreamError(json['error'].toString());
  if (json['reset'] == true) return const ChatStreamReset();
  if (json['done'] == true) {
    // Sem `content` (backend antigo): o ultimo `chunk` e a resposta inteira.
    final content = (json['content'] ?? json['chunk'] ?? '').toString();
    return ChatStreamFinal({
      'responses': [
        {
          'llm': json['llm']?.toString() ?? 'backend',
          'content': content,
          'is_error': json['is_error'] == true,
        },
      ],
      'action': json['action'],
      'tool_results': json['tool_results'] ?? const [],
    });
  }
  final chunk = json['chunk'];
  if (chunk is String && chunk.isNotEmpty) return ChatStreamDelta(chunk);
  return null;
}

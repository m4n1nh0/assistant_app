/// Atalhos de teclado do campo de mensagem do chat.
library;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

/// Atalhos do campo principal de conversa.
///
/// Com envio por Enter ligado, modificadores ficam livres para inserir uma
/// nova linha. Desligado, Enter vira quebra de linha e Ctrl/Cmd+Enter mantem
/// um atalho de teclado para enviar.
Map<ShortcutActivator, VoidCallback> buildChatInputShortcuts({
  required bool sendOnEnter,
  required VoidCallback onSend,
}) {
  if (sendOnEnter) {
    return {
      const SingleActivator(LogicalKeyboardKey.enter): onSend,
      const SingleActivator(LogicalKeyboardKey.numpadEnter): onSend,
    };
  }
  return {
    const SingleActivator(LogicalKeyboardKey.enter, control: true): onSend,
    const SingleActivator(LogicalKeyboardKey.numpadEnter, control: true):
        onSend,
    const SingleActivator(LogicalKeyboardKey.enter, meta: true): onSend,
    const SingleActivator(LogicalKeyboardKey.numpadEnter, meta: true): onSend,
  };
}

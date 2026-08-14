import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/widgets.dart';

import 'package:assistant_app/utils/chat_input_shortcuts.dart';

void main() {
  test('plain Enter sends when the preference is enabled', () {
    var sends = 0;
    final bindings = buildChatInputShortcuts(
      sendOnEnter: true,
      onSend: () => sends++,
    );

    bindings[const SingleActivator(LogicalKeyboardKey.enter)]!();
    expect(sends, 1);
    expect(
      bindings.containsKey(
        const SingleActivator(LogicalKeyboardKey.enter, shift: true),
      ),
      isFalse,
    );
  });

  test('Enter becomes a newline shortcut when the preference is disabled', () {
    var sends = 0;
    final bindings = buildChatInputShortcuts(
      sendOnEnter: false,
      onSend: () => sends++,
    );

    expect(
      bindings.containsKey(const SingleActivator(LogicalKeyboardKey.enter)),
      isFalse,
    );
    bindings[const SingleActivator(LogicalKeyboardKey.enter, control: true)]!();
    bindings[const SingleActivator(LogicalKeyboardKey.enter, meta: true)]!();
    expect(sends, 2);
  });
}

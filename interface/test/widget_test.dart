import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:assistant_app/main.dart';

void main() {
  testWidgets('app widget can be constructed', (_) async {
    expect(const ProviderScope(child: AssistantApp()), isA<ProviderScope>());
  });
}

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/widgets/chat_panel.dart';

/// Os dez servicos que o backend do usuario devolveu quando a faixa estourou.
const _todos = [
  'backend',
  'claude',
  'gpt',
  'gemini',
  'together',
  'openrouter',
  'deepseek',
  'grok',
  'localai',
  'llama',
  'hf',
];

AppConfig _config(List<String> ativos) => AppConfig(
      activeLlms: {for (final id in _todos) id: ativos.contains(id)},
    );

/// Reproduz o cabecalho da conversa: titulo fixo e os marcadores no resto.
Future<void> _pump(WidgetTester tester, AppConfig config, double width) {
  return tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: width,
          child: Row(
            children: [
              const Text('CONVERSA'),
              const SizedBox(width: 12),
              Expanded(child: ChatServiceChips(config: config)),
            ],
          ),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('mostra um marcador por servico ativo', (tester) async {
    await _pump(tester, _config(['claude', 'gpt', 'llama']), 800);

    expect(find.text('CLAUDE SONNET 4'), findsOneWidget);
    expect(find.text('GPT-4O'), findsOneWidget);
    expect(find.text('OLLAMA'), findsOneWidget);
    // Servico desligado nao aparece.
    expect(find.text('GROK'), findsNothing);
  });

  testWidgets('dez servicos cabem sem estourar a linha', (tester) async {
    // Era esta a largura util do painel quando apareceu o aviso de estouro.
    await _pump(tester, _config(_todos), 640);

    // Um RenderFlex estourado vira excecao no teste: e o traco amarelo e preto
    // que aparecia na tela.
    expect(tester.takeException(), isNull);
    for (final rotulo in ['CLAUDE SONNET 4', 'HUGGING FACE', 'OPENROUTER']) {
      expect(find.text(rotulo), findsOneWidget);
    }
  });

  testWidgets('nenhum marcador fica fora da faixa', (tester) async {
    await _pump(tester, _config(_todos), 640);

    for (final marcador in find.byType(Container).evaluate()) {
      final box = marcador.renderObject as RenderBox;
      final direita = box.localToGlobal(Offset.zero).dx + box.size.width;
      expect(direita, lessThanOrEqualTo(640.0));
    }
  });

  testWidgets('sem servico ativo a faixa ainda nomeia o backend',
      (tester) async {
    await _pump(tester, _config(const []), 800);

    expect(find.text('BACKEND'), findsOneWidget);
  });

  testWidgets('modo conectado mostra somente o agente desktop escolhido',
      (tester) async {
    final config = _config(['claude', 'gpt'])
      ..connectedAgentMode = true
      ..connectedAgentId = 'codex_cli';

    await _pump(tester, config, 800);

    expect(find.text('CODEX CONECTADO'), findsOneWidget);
    expect(find.text('CLAUDE SONNET 4'), findsNothing);
    expect(find.text('GPT-4O'), findsNothing);
  });
}

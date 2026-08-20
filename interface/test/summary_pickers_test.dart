import 'package:assistant_app/models/app_config.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/summary_pickers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Configuracao cheia: e o pior caso de largura, porque o seletor lista todos
/// os provedores ativos mais os agentes conectados.
AppConfig _config() => AppConfig(
      activeLlms: const {
        'claude': true,
        'gpt': true,
        'gemini': true,
        'together': true,
        'deepseek': true,
        'localai': true,
      },
      llmLabels: const {
        'claude': 'Claude Sonnet 4.5',
        'gpt': 'GPT-4o',
        'together': 'Together Llama 3.3 70B Turbo',
      },
      connectedAgents: const {'codex_cli': true, 'claude_cli': true},
    );

Widget _wrap(Widget child, double width) => MaterialApp(
      home: Scaffold(
        body: Center(
          child: SizedBox(width: width, child: child),
        ),
      ),
    );

/// Reproduz a linha de opcoes das duas telas: formato + seletor de IA.
Widget _opcoes(AppConfig config) => Wrap(
      spacing: 12,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        SummaryStylePicker(style: summaryStyleStandard, onChanged: (_) {}),
        SummaryEnginePicker(engine: '', config: config, onChanged: (_) {}),
      ],
    );

/// Copia fiel do bloco de acoes do historico: opcoes em cima, informacao da
/// aula e botoes embaixo. E o conjunto inteiro que precisa caber — foi juntar
/// tudo em uma linha so que espremeu o texto ate uma letra por linha e vazou
/// pelas duas bordas.
Widget _acoesDoHistorico(AppConfig config) => Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _opcoes(config),
        const SizedBox(height: 8),
        Row(
          children: [
            const Expanded(
              child: Text(
                '82 trecho(s), 288 caracteres.',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: () {},
              icon: const Icon(Icons.summarize_outlined, size: 14),
              label: const Text('REFAZER RESUMO',
                  style: TextStyle(fontSize: 10)),
            ),
            const SizedBox(width: 8),
            FilledButton.icon(
              onPressed: () {},
              icon: const Icon(Icons.picture_as_pdf_outlined, size: 14),
              label: const Text('VISUALIZAR PDF',
                  style: TextStyle(fontSize: 10)),
            ),
          ],
        ),
      ],
    );

void main() {
  group('SummaryEnginePicker', () {
    testWidgets('acoes do historico cabem na coluna de detalhe',
        (tester) async {
      // Largura util da coluna de detalhe do historico com o dialogo aberto
      // no tamanho maximo. Com seletores e botoes na mesma linha, era aqui
      // que a interface vazava 26 pixels para a direita.
      await tester.pumpWidget(_wrap(_acoesDoHistorico(_config()), 750));

      expect(tester.takeException(), isNull);
    });

    testWidgets('acoes do historico cabem tambem em janela menor',
        (tester) async {
      await tester.pumpWidget(_wrap(_acoesDoHistorico(_config()), 560));

      expect(tester.takeException(), isNull);
    });

    testWidgets('cabe no painel lateral da aula sem estourar', (tester) async {
      await tester.pumpWidget(_wrap(_opcoes(_config()), 444));

      expect(tester.takeException(), isNull);
    });

    testWidgets('em coluna estreita desce de linha em vez de vazar',
        (tester) async {
      await tester.pumpWidget(_wrap(_opcoes(_config()), 260));

      expect(tester.takeException(), isNull);
    });

    testWidgets('largura nao depende do nome dos provedores', (tester) async {
      // Um provedor com rotulo longo nao pode empurrar os botoes da tela: e o
      // que acontecia quando o dropdown crescia ate o item mais largo.
      final curto = AppConfig(activeLlms: const {'gpt': true});
      await tester.pumpWidget(
        _wrap(SummaryEnginePicker(engine: '', config: curto, onChanged: (_) {}),
            750),
      );
      final estreito = tester.getSize(find.byType(SummaryEnginePicker)).width;

      await tester.pumpWidget(
        _wrap(
          SummaryEnginePicker(
              engine: '', config: _config(), onChanged: (_) {}),
          750,
        ),
      );
      final largo = tester.getSize(find.byType(SummaryEnginePicker)).width;

      expect(estreito, largo);
      expect(tester.takeException(), isNull);
    });

    testWidgets('abre o menu com provedores e agentes conectados',
        (tester) async {
      await tester.pumpWidget(
        _wrap(
          SummaryEnginePicker(
              engine: '', config: _config(), onChanged: (_) {}),
          750,
        ),
      );

      await tester.tap(find.byType(SummaryEnginePicker));
      await tester.pumpAndSettle();

      expect(find.text('Automatico'), findsWidgets);
      expect(find.text('Claude Sonnet 4.5'), findsOneWidget);
      expect(find.text('Codex conectado'), findsOneWidget);
      expect(find.text('Claude conectado'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('selecao invalida volta para automatico', (tester) async {
      // Provedor desativado ou agente que perdeu o login: o seletor nao pode
      // ficar preso em um valor que nao esta mais na lista.
      await tester.pumpWidget(
        _wrap(
          SummaryEnginePicker(
            engine: 'provedor_removido',
            config: _config(),
            onChanged: (_) {},
          ),
          750,
        ),
      );

      expect(find.text('IA: AUTOMATICO'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('summaryEngineLabel', () {
    test('traduz provedor, agente conectado e automatico', () {
      final config = _config();

      expect(summaryEngineLabel('', config), 'automatico');
      expect(summaryEngineLabel('claude', config), 'Claude Sonnet 4.5');
      expect(summaryEngineLabel('claude_cli', config), 'Claude conectado');
      expect(summaryEngineLabel('codex_cli', null), 'Codex conectado');
    });
  });
}

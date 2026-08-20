import 'package:flutter/material.dart';

import '../models/app_config.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

/// Como o motor escolhido aparece escrito na interface.
String summaryEngineLabel(String engine, AppConfig? config) {
  if (engine.isEmpty) return 'automatico';
  if (AppConfig.connectedAgentIds.contains(engine)) {
    return AppConfig.serviceLabel(engine);
  }
  return config?.serviceName(engine) ?? AppConfig.serviceLabel(engine);
}

/// Escolha entre resumo comum e detalhado. Fica ao lado de quem gera o resumo
/// (aula ao vivo e historico) porque a decisao e tomada na hora de gerar, e o
/// custo de escolher errado e uma nova rodada no modelo.
class SummaryStylePicker extends StatelessWidget {
  final String style;
  final ValueChanged<String> onChanged;
  final bool enabled;

  /// Com rotulo no painel da aula, onde ha espaco vertical; sem rotulo na
  /// linha de botoes do historico.
  final bool showLabel;

  const SummaryStylePicker({
    super.key,
    required this.style,
    required this.onChanged,
    this.enabled = true,
    this.showLabel = false,
  });

  @override
  Widget build(BuildContext context) {
    final chips = Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        _chip(
          'COMUM',
          summaryStyleStandard,
          'Resumo em uma tela: fio condutor, topicos, definicoes, tarefas e '
              'duvidas.',
        ),
        _chip(
          'DETALHADO',
          summaryStyleDetailed,
          'Reconstroi a aula: desenvolvimento na ordem em que foi dada, '
              'exemplos resolvidos e pontos de atencao. Demora mais.',
        ),
      ],
    );

    if (!showLabel) return chips;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          'FORMATO DO RESUMO',
          style: TextStyle(
            fontSize: 9,
            letterSpacing: 1.5,
            color: AssistantTheme.textMuted,
          ),
        ),
        const SizedBox(height: 6),
        chips,
      ],
    );
  }

  Widget _chip(String label, String value, String tooltip) {
    final selected = style == value;
    return Tooltip(
      message: tooltip,
      child: ChoiceChip(
        selected: selected,
        onSelected: enabled ? (_) => onChanged(value) : null,
        label: Text(label),
        labelStyle: TextStyle(
          fontSize: 10,
          letterSpacing: 1,
          color: selected ? AssistantTheme.c3 : AssistantTheme.textMuted,
        ),
        labelPadding: const EdgeInsets.symmetric(horizontal: 4),
        showCheckmark: false,
        visualDensity: VisualDensity.compact,
        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
        backgroundColor: AssistantTheme.bg2,
        selectedColor: AssistantTheme.c3.withValues(alpha: 0.22),
        side: BorderSide(
          color: selected ? AssistantTheme.c3 : AssistantTheme.border,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(3),
        ),
      ),
    );
  }
}

/// Escolha de quem escreve o resumo: a fila automatica do backend, um provedor
/// configurado (Claude, GPT, Gemini...) ou um agente conectado que roda no
/// proprio computador (Codex, Claude Code).
///
/// A largura e fixa de proposito. Um `DropdownButton` solto cresce ate caber o
/// item mais largo do menu, e essa largura variavel — que depende do nome dos
/// provedores configurados — estourava a linha de botoes do historico.
class SummaryEnginePicker extends StatelessWidget {
  final String engine;
  final AppConfig config;
  final ValueChanged<String> onChanged;
  final bool enabled;
  final double width;

  const SummaryEnginePicker({
    super.key,
    required this.engine,
    required this.config,
    required this.onChanged,
    this.enabled = true,
    this.width = 208,
  });

  @override
  Widget build(BuildContext context) {
    final backend = config.activeList;
    final connected = config.connectedAgentList;
    // A selecao pode ter perdido validade: provedor desativado, agente que
    // saiu do ar. Nesse caso o seletor volta a mostrar o automatico.
    final current =
        backend.contains(engine) || connected.contains(engine) ? engine : '';

    return Tooltip(
      message: 'Quem escreve o resumo.\n'
          'Automatico: a fila do backend, do gratuito ao pago.\n'
          'Provedor: fixa a geracao nele, sem tentar outro.\n'
          'Agente conectado: roda neste computador e le a aula inteira de '
          'uma vez.',
      child: SizedBox(
        width: width,
        child: DropdownButtonHideUnderline(
          child: DropdownButton<String>(
            value: current,
            isExpanded: true,
            isDense: true,
            focusColor: Colors.transparent,
            dropdownColor: AssistantTheme.surface,
            borderRadius: BorderRadius.circular(3),
            icon: const Icon(Icons.arrow_drop_down,
                size: 16, color: AssistantTheme.textMuted),
            style: const TextStyle(fontSize: 10, color: AssistantTheme.c2),
            selectedItemBuilder: (_) => [
              for (final item in ['', ...backend, ...connected])
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    'IA: ${summaryEngineLabel(item, config).toUpperCase()}',
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 10,
                      letterSpacing: 0.6,
                      color: AssistantTheme.c2,
                    ),
                  ),
                ),
            ],
            items: [
              _item('', 'Automatico'),
              for (final id in backend) _item(id, config.serviceName(id)),
              for (final id in connected) _item(id, AppConfig.serviceLabel(id)),
            ],
            onChanged: enabled ? (value) => onChanged(value ?? '') : null,
          ),
        ),
      ),
    );
  }

  /// Item de uma linha so: item de duas linhas passa da altura que o
  /// `DropdownButton` reserva e vaza pela borda de baixo.
  DropdownMenuItem<String> _item(String value, String label) {
    return DropdownMenuItem(
      value: value,
      child: Text(
        label,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          fontSize: 11,
          color: AssistantTheme.textPrimary,
        ),
      ),
    );
  }
}

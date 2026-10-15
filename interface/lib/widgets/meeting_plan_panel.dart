/// Plano de encontros da mentoria: quais das suas faixas de atendimento servem melhor aos
/// aceitos, pelos horários livres que cada um informou na inscrição.
///
/// Só sugere. A agenda vem da aba Atendimento; a disponibilidade de cada aluno, do campo
/// "horários livres" do formulário. Escolher o dia do encontro continua sendo seu.
library;

import 'package:flutter/material.dart';

import '../models/availability.dart';
import '../services/education_service.dart';
import '../utils/theme.dart';

class MeetingPlanPanel extends StatefulWidget {
  final String formId;
  final EducationService service;

  /// Quantos aceitos a mentoria tinha quando a tela abriu; muda quando entra ou sai alguém
  /// e faz o plano ser recalculado.
  final int accepted;

  const MeetingPlanPanel({
    super.key,
    required this.formId,
    required this.service,
    this.accepted = 0,
  });

  @override
  State<MeetingPlanPanel> createState() => _MeetingPlanPanelState();
}

class _MeetingPlanPanelState extends State<MeetingPlanPanel> {
  MeetingPlan? _plan;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(MeetingPlanPanel old) {
    super.didUpdateWidget(old);
    if (old.accepted != widget.accepted || old.formId != widget.formId) _load();
  }

  Future<void> _load() async {
    try {
      final plan = await widget.service.mentorshipMeetingPlan(widget.formId);
      if (mounted) {
        setState(() {
          _plan = plan;
          _error = '';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _error = '$e'.replaceFirst('Exception: ', ''));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final plan = _plan;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AssistantTheme.bg.withOpacity(.38),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AssistantTheme.c3.withOpacity(.45)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(
            child: Text('PLANO DE ENCONTROS',
                style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1,
                    color: AssistantTheme.c3)),
          ),
          IconButton(
              tooltip: 'Recalcular',
              onPressed: _load,
              icon: const Icon(Icons.refresh, size: 18)),
        ]),
        const SizedBox(height: 4),
        if (_error.isNotEmpty)
          Text(_error, style: const TextStyle(fontSize: 12, color: Colors.redAccent))
        else if (plan == null)
          const Padding(
              padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()))
        else
          ..._body(plan),
      ]),
    );
  }

  List<Widget> _body(MeetingPlan plan) {
    if (plan.accepted == 0) {
      return const [
        _Hint('Ainda não há alunos aceitos. Aceite inscritos para o plano cruzar os '
            'horários livres deles com a sua agenda.')
      ];
    }
    if (!plan.hasSlots) {
      return const [
        _Hint('Você ainda não tem faixas de atendimento para mentoria. Cadastre em '
            'Atendimento (faixas para "todos" ou "só mentoria") e o plano aparece aqui.')
      ];
    }
    return [
      Text(
        '${plan.withAvailability} de ${plan.accepted} aceitos informaram horários livres.',
        style: const TextStyle(fontSize: 12, color: AssistantTheme.textSecondary),
      ),
      const SizedBox(height: 8),
      for (var i = 0; i < plan.options.length; i++) _option(plan, plan.options[i], i == 0),
      if (plan.uncovered.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text(
          'Sem nenhuma das suas faixas: ${plan.uncovered.join(', ')}.',
          key: const Key('plan-uncovered'),
          style: const TextStyle(fontSize: 12, color: Colors.amber),
        ),
      ],
    ];
  }

  Widget _option(MeetingPlan plan, MeetingOption option, bool best) {
    final color = option.count == 0 ? AssistantTheme.textMuted : AssistantTheme.c3;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: best && option.count > 0 ? AssistantTheme.c3 : AssistantTheme.border),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 54,
          padding: const EdgeInsets.symmetric(vertical: 6),
          decoration: BoxDecoration(
            color: color.withOpacity(.12),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Column(children: [
            Text('${option.count}',
                key: Key('plan-count-${option.slotId}'),
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: color)),
            Text('de ${plan.accepted}',
                style: const TextStyle(fontSize: 9, color: AssistantTheme.textMuted)),
          ]),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('${option.weekdayName} ${option.startTime} às ${option.endTime}',
                  style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
              if (best && option.count > 0) ...[
                const SizedBox(width: 8),
                const _Pill('MELHOR OPÇÃO'),
              ],
            ]),
            Text(
              '${availabilityModes[option.mode] ?? option.mode}'
              '${option.location.isEmpty ? '' : ' · ${option.location}'}',
              style: const TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
            ),
            if (option.names.isNotEmpty)
              Text('Conseguem: ${option.names.join(', ')}',
                  style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
          ]),
        ),
      ]),
    );
  }
}

class _Pill extends StatelessWidget {
  final String text;

  const _Pill(this.text);

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: AssistantTheme.c3.withOpacity(.15),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AssistantTheme.c3.withOpacity(.6)),
        ),
        child: Text(text,
            style: const TextStyle(
                fontSize: 9, fontWeight: FontWeight.w800, color: AssistantTheme.c3)),
      );
}

class _Hint extends StatelessWidget {
  final String text;

  const _Hint(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text(text,
            style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
      );
}

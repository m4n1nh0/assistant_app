import 'package:flutter/material.dart';

import '../services/study_time_stats.dart';
import '../utils/theme.dart';

/// Visão ampliada de tempo de estudo para projetar em sala.
///
/// Tudo aqui é lido de longe e por quem não acompanhou a importação, então cada
/// número diz de que conjunto ele fala: a barra traz a porcentagem junto, o
/// ranking declara que é recorte e o rodapé explica o que a planilha não conta.
class StudyTimeDashboard extends StatelessWidget {
  final List<Map<String, dynamic>> records;
  final String title;

  /// Quantas linhas cabem num ranking projetado sem virar lista de telefone.
  static const _rankingSize = 10;

  const StudyTimeDashboard({
    super.key,
    required this.records,
    required this.title,
  });

  @override
  Widget build(BuildContext context) {
    final stats = StudyTimeStats.fromRecords(records);
    return Dialog.fullscreen(
      child: Scaffold(
        appBar: AppBar(title: Text('TEMPO DE ESTUDO  •  $title'), actions: [
          IconButton(
            icon: const Icon(Icons.close),
            tooltip: 'Fechar painel',
            onPressed: () => Navigator.of(context).pop(),
          ),
        ]),
        body: records.isEmpty
            ? const Center(child: Text('Não há registros para o filtro escolhido.'))
            : Padding(
                padding: const EdgeInsets.all(24),
                child: Column(children: [
                  _Metrics(stats: stats),
                  const SizedBox(height: 18),
                  Expanded(
                    child: LayoutBuilder(builder: (context, constraints) {
                      final narrow = constraints.maxWidth < 900;
                      final painels = [
                        _RankingPanel(
                          heading: 'Por disciplina',
                          entries: stats.disciplines,
                          total: stats.totalMinutes,
                          limit: _rankingSize,
                          hiddenMinutes: 0,
                        ),
                        _RankingPanel(
                          heading: 'Alunos que mais estudaram',
                          entries: stats.students,
                          total: stats.totalMinutes,
                          limit: _rankingSize,
                          hiddenMinutes: stats.minutesBeyond(_rankingSize),
                        ),
                        _BandsPanel(stats: stats),
                      ];
                      if (narrow) {
                        return ListView(children: [
                          for (final painel in painels)
                            SizedBox(height: 360, child: painel),
                        ]);
                      }
                      return Row(children: [
                        Expanded(flex: 3, child: painels[0]),
                        const SizedBox(width: 16),
                        Expanded(flex: 4, child: painels[1]),
                        const SizedBox(width: 16),
                        Expanded(flex: 3, child: painels[2]),
                      ]);
                    }),
                  ),
                  const SizedBox(height: 10),
                  _Legend(stats: stats),
                ]),
              ),
      ),
    );
  }
}

/// Faixa de indicadores do topo.
class _Metrics extends StatelessWidget {
  final StudyTimeStats stats;

  const _Metrics({required this.stats});

  @override
  Widget build(BuildContext context) {
    String horas(int minutes) => '${(minutes / 60).toStringAsFixed(1)} h';
    return Wrap(spacing: 16, runSpacing: 12, children: [
      _MetricCard(label: 'Tempo total', value: '${stats.totalHours.toStringAsFixed(1)} horas'),
      _MetricCard(label: 'Alunos com tempo', value: '${stats.studentCount}'),
      _MetricCard(
        label: 'Mediana por aluno',
        value: horas(stats.medianMinutes),
        note: 'metade da turma estudou menos que isso',
      ),
      _MetricCard(
        label: 'Concentração nos 5 primeiros',
        value: '${(stats.topShare() * 100).round()}%',
        note: 'do tempo total da turma',
      ),
      _MetricCard(label: 'Registros', value: '${stats.recordCount}'),
      if (stats.unlinkedRecords > 0)
        _MetricCard(
          label: 'Sem aluno no cadastro',
          value: '${stats.unlinkedRecords}',
          note: 'contam no total, ficam fora do ranking',
          alert: true,
        ),
    ]);
  }
}

class _MetricCard extends StatelessWidget {
  final String label;
  final String value;
  final String note;
  final bool alert;

  const _MetricCard({
    required this.label,
    required this.value,
    this.note = '',
    this.alert = false,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(
            value,
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: alert ? AssistantTheme.c4 : null,
                ),
          ),
          if (note.isNotEmpty) ...[
            const SizedBox(height: 4),
            SizedBox(
              width: 210,
              child: Text(note, style: Theme.of(context).textTheme.bodySmall),
            ),
          ],
        ]),
      ),
    );
  }
}

/// Ranking com barra proporcional ao total, não ao primeiro colocado.
///
/// A barra antiga era um `LinearProgressIndicator`, cuja trilha herdava o
/// dourado do tema: parecia uma segunda série empilhada e não era nada. Aqui a
/// cor cheia é a única informação, e o número ao lado mede a mesma coisa que
/// ela.
class _RankingPanel extends StatelessWidget {
  final String heading;
  final List<StudyTimeEntry> entries;
  final int total;
  final int limit;
  final int hiddenMinutes;

  const _RankingPanel({
    required this.heading,
    required this.entries,
    required this.total,
    required this.limit,
    required this.hiddenMinutes,
  });

  @override
  Widget build(BuildContext context) {
    final shown = entries.take(limit).toList();
    final maior = shown.isEmpty ? 1 : shown.first.minutes;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(heading, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 2),
          Text(
            entries.length > limit
                ? '${shown.length} de ${entries.length}'
                : '${entries.length} no total',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          Expanded(
            child: shown.isEmpty
                ? const Center(child: Text('Nenhum aluno vinculado.'))
                : ListView.builder(
                    itemCount: shown.length,
                    itemBuilder: (context, index) => _Bar(
                      position: index + 1,
                      entry: shown[index],
                      largest: maior,
                    ),
                  ),
          ),
          if (hiddenMinutes > 0) ...[
            const SizedBox(height: 6),
            Text(
              'Os demais ${entries.length - limit} somam '
              '${(hiddenMinutes / 60).toStringAsFixed(1)} h.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ]),
      ),
    );
  }
}

class _Bar extends StatelessWidget {
  final int position;
  final StudyTimeEntry entry;
  final int largest;

  const _Bar({
    required this.position,
    required this.entry,
    required this.largest,
  });

  @override
  Widget build(BuildContext context) {
    final fracao = largest == 0 ? 0.0 : entry.minutes / largest;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(
            width: 26,
            child: Text('$positionº', style: Theme.of(context).textTheme.bodySmall),
          ),
          Expanded(child: Text(entry.label, overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 8),
          Text('${entry.hours.toStringAsFixed(1)} h'),
          const SizedBox(width: 10),
          SizedBox(
            width: 42,
            child: Text(
              '${(entry.share * 100).toStringAsFixed(0)}%',
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        ]),
        const SizedBox(height: 5),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: Stack(children: [
            Container(height: 12, color: AssistantTheme.surface2),
            FractionallySizedBox(
              widthFactor: fracao.clamp(0.0, 1.0),
              child: Container(height: 12, color: AssistantTheme.c1),
            ),
          ]),
        ),
      ]),
    );
  }
}

/// Distribuição por faixa: mostra a turma que o ranking dos dez esconde.
class _BandsPanel extends StatelessWidget {
  final StudyTimeStats stats;

  const _BandsPanel({required this.stats});

  @override
  Widget build(BuildContext context) {
    final maior = stats.bands.fold<int>(
      1,
      (maximo, faixa) => faixa.students > maximo ? faixa.students : maximo,
    );
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Distribuição da turma',
              style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 2),
          Text('alunos por faixa de dedicação',
              style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          for (final faixa in stats.bands)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(faixa.label, overflow: TextOverflow.ellipsis)),
                  Text('${faixa.students}'),
                ]),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: Stack(children: [
                    Container(height: 12, color: AssistantTheme.surface2),
                    FractionallySizedBox(
                      widthFactor: (faixa.students / maior).clamp(0.0, 1.0),
                      child: Container(height: 12, color: AssistantTheme.c3),
                    ),
                  ]),
                ),
              ]),
            ),
          const Spacer(),
          Text(
            'Faixa vazia é turma concentrada num extremo: ou quase ninguém '
            'estudou, ou o esforço está bem distribuído.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ]),
      ),
    );
  }
}

/// Legenda: o que cada cor significa e o que a planilha não conta.
class _Legend extends StatelessWidget {
  final StudyTimeStats stats;

  const _Legend({required this.stats});

  @override
  Widget build(BuildContext context) {
    Widget chave(Color color, String text) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 14,
              height: 14,
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(3),
              ),
            ),
            const SizedBox(width: 6),
            Text(text, style: Theme.of(context).textTheme.bodySmall),
          ],
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: 18, runSpacing: 8, children: [
        chave(AssistantTheme.c1, 'Tempo do aluno ou da disciplina'),
        chave(AssistantTheme.c3, 'Quantidade de alunos na faixa'),
        chave(AssistantTheme.surface2, 'Resto da barra: espaço até o primeiro colocado'),
      ]),
      const SizedBox(height: 6),
      Text(
        'A porcentagem ao lado de cada barra é a fatia do tempo total '
        '(${stats.totalHours.toStringAsFixed(1)} h); o comprimento compara com o '
        'primeiro colocado. Dados importados da planilha: linha com tempo vazio '
        'não entra (vazio não é zero) e matrícula sem aluno no cadastro conta no '
        'total, mas não aparece no ranking por nome.',
        style: Theme.of(context).textTheme.bodySmall,
      ),
    ]);
  }
}

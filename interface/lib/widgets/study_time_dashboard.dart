import 'package:flutter/material.dart';

import '../services/study_time_stats.dart';
import '../utils/theme.dart';
import 'study_time_charts.dart';

/// Painel de tempo de estudo: leitura e recorte, para projetar em sala.
///
/// A tela toda responde a um único [StudyTimeFilter]. Clicar numa fatia da
/// rosca, numa turma ou numa faixa muda esse recorte e **tudo** se recalcula -
/// indicadores, rankings e gráficos. É o que separa um painel de uma figura:
/// aqui a pergunta seguinte se faz na própria tela.
class StudyTimeDashboard extends StatefulWidget {
  final List<Map<String, dynamic>> records;
  final String title;

  /// Recorte já aplicado na aba, para o painel abrir no mesmo assunto.
  final StudyTimeFilter initialFilter;

  const StudyTimeDashboard({
    super.key,
    required this.records,
    required this.title,
    this.initialFilter = const StudyTimeFilter(),
  });

  @override
  State<StudyTimeDashboard> createState() => _StudyTimeDashboardState();
}

class _StudyTimeDashboardState extends State<StudyTimeDashboard> {
  late StudyTimeFilter _filter = widget.initialFilter;

  /// Ranking de alunos: quantos aparecem antes de precisar rolar.
  static const _topRanking = 10;
  bool _showAllStudents = false;

  @override
  Widget build(BuildContext context) {
    final filtrados = _filter.apply(widget.records);
    final stats = StudyTimeStats.fromRecords(filtrados);
    // A paleta vem do conjunto inteiro: a turma não pode trocar de cor quando o
    // professor filtra, senão a comparação entre dois recortes engana.
    final palette = StudyTimePalette(
      StudyTimeStats.fromRecords(widget.records).classes.map((c) => c.label),
    );

    return Dialog.fullscreen(
      child: Scaffold(
        appBar: AppBar(
          title: Text('TEMPO DE ESTUDO  •  ${widget.title}'),
          actions: [
            if (!_filter.isEmpty)
              TextButton.icon(
                icon: const Icon(Icons.filter_alt_off_outlined, size: 16),
                label: const Text('LIMPAR FILTROS'),
                onPressed: () => setState(() => _filter = const StudyTimeFilter()),
              ),
            IconButton(
              icon: const Icon(Icons.close),
              tooltip: 'Fechar painel',
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        ),
        body: widget.records.isEmpty
            ? const Center(child: Text('Não há registros para o filtro escolhido.'))
            : Padding(
                padding: const EdgeInsets.fromLTRB(24, 16, 24, 16),
                child: Column(children: [
                  _FilterBar(
                    records: widget.records,
                    filter: _filter,
                    onChanged: (novo) => setState(() => _filter = novo),
                  ),
                  const SizedBox(height: 12),
                  _Metrics(stats: stats),
                  const SizedBox(height: 16),
                  Expanded(
                    child: filtrados.isEmpty
                        ? const Center(
                            child: Text('Nenhum registro neste recorte. '
                                'Ajuste ou limpe os filtros.'))
                        : LayoutBuilder(builder: (context, constraints) {
                            final painels = [
                              _ClassPanel(
                                stats: stats,
                                palette: palette,
                                selected: _filter.classLabel,
                                onSelect: _toggleClass,
                              ),
                              _StudentPanel(
                                stats: stats,
                                palette: palette,
                                limit: _showAllStudents ? null : _topRanking,
                                onToggleLimit: () => setState(
                                    () => _showAllStudents = !_showAllStudents),
                              ),
                              _BandsPanel(
                                stats: stats,
                                selected: _filter.band,
                                onSelect: _toggleBand,
                              ),
                            ];
                            if (constraints.maxWidth < 1000) {
                              return ListView(children: [
                                for (final painel in painels)
                                  SizedBox(height: 420, child: painel),
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
                  const SizedBox(height: 8),
                  _Footnote(stats: stats),
                ]),
              ),
      ),
    );
  }

  void _toggleClass(String label) => setState(() => _filter = _filter.classLabel == label
      ? _filter.copyWith(clearClass: true)
      : _filter.copyWith(classLabel: label));

  void _toggleBand(String label) => setState(() => _filter = _filter.band == label
      ? _filter.copyWith(clearBand: true)
      : _filter.copyWith(band: label));
}

/// Filtros do painel. Mostram o recorte atual e permitem trocá-lo sem sair.
class _FilterBar extends StatelessWidget {
  final List<Map<String, dynamic>> records;
  final StudyTimeFilter filter;
  final ValueChanged<StudyTimeFilter> onChanged;

  const _FilterBar({
    required this.records,
    required this.filter,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    List<String> valores(String Function(Map<String, dynamic>) leitura) =>
        records.map(leitura).where((v) => v.isNotEmpty).toSet().toList()..sort();

    Widget escolha(String label, List<String> opcoes, String? atual,
        ValueChanged<String?> mudar) {
      // Um valor fora da lista derruba o dropdown - e isso acontece de verdade:
      // o recorte pode vir da aba apontando para uma turma que este conjunto
      // nao tem mais. Ele entra como opcao para poder ser visto e desfeito.
      final lista = [
        ...opcoes,
        if (atual != null && !opcoes.contains(atual)) atual,
      ];
      return SizedBox(
          width: 230,
          child: DropdownButtonFormField<String>(
            value: atual,
            isExpanded: true,
            decoration: InputDecoration(
              labelText: label,
              isDense: true,
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            ),
            items: [
              const DropdownMenuItem(value: null, child: Text('Todos')),
              ...lista.map((v) => DropdownMenuItem(
                  value: v, child: Text(v, overflow: TextOverflow.ellipsis))),
            ],
            onChanged: mudar,
          ));
    }

    return Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        escolha('Disciplina', valores((r) => '${r['discipline_code'] ?? ''}'),
            filter.discipline,
            (v) => onChanged(v == null
                ? filter.copyWith(clearDiscipline: true)
                : filter.copyWith(discipline: v))),
        escolha('Turma (cadastro)', valores(StudyTimeStats.classOf),
            filter.classLabel,
            (v) => onChanged(v == null
                ? filter.copyWith(clearClass: true)
                : filter.copyWith(classLabel: v))),
        escolha('Faixa de dedicação',
            [...StudyTimeStats.bandLimits.keys, StudyTimeStats.topBand],
            filter.band,
            (v) => onChanged(v == null
                ? filter.copyWith(clearBand: true)
                : filter.copyWith(band: v))),
        if (!filter.isEmpty)
          Chip(
            label: const Text('recorte ativo'),
            avatar: const Icon(Icons.filter_alt, size: 14),
            backgroundColor: AssistantTheme.surface2,
          ),
      ],
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
    return Wrap(spacing: 14, runSpacing: 10, children: [
      _MetricCard(
          label: 'Tempo total',
          value: '${stats.totalHours.toStringAsFixed(1)} horas'),
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
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text(
            value,
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  color: alert ? AssistantTheme.c4 : null,
                ),
          ),
          if (note.isNotEmpty) ...[
            const SizedBox(height: 4),
            SizedBox(
              width: 200,
              child: Text(note, style: Theme.of(context).textTheme.bodySmall),
            ),
          ],
        ]),
      ),
    );
  }
}

/// Participação por turma do cadastro, em rosca e legenda clicáveis.
class _ClassPanel extends StatelessWidget {
  final StudyTimeStats stats;
  final StudyTimePalette palette;
  final String? selected;
  final ValueChanged<String> onSelect;

  const _ClassPanel({
    required this.stats,
    required this.palette,
    required this.selected,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return _Panel(
      heading: 'Por turma',
      subtitle: 'turma do seu cadastro, não a sequência da planilha',
      child: ListView(children: [
        StudyTimeDonut(
          entries: stats.classes,
          palette: palette,
          selected: selected,
          onTap: onSelect,
          centerValue: '${stats.totalHours.toStringAsFixed(1)} h',
          centerLabel: selected ?? 'no recorte atual',
        ),
        const SizedBox(height: 14),
        StudyTimeLegend(
          entries: stats.classes,
          palette: palette,
          selected: selected,
          onTap: onSelect,
        ),
        const SizedBox(height: 10),
        Text('Clique numa fatia para filtrar a tela inteira.',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 10),
        _SubRanking(title: 'Por disciplina', entries: stats.disciplines),
      ]),
    );
  }
}

/// Ranking secundário, sem cor própria: serve de contexto, não de filtro.
class _SubRanking extends StatelessWidget {
  final String title;
  final List<StudyTimeEntry> entries;

  const _SubRanking({required this.title, required this.entries});

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(title, style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 6),
      for (final entry in entries)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(entry.label, overflow: TextOverflow.ellipsis)),
              Text('${entry.hours.toStringAsFixed(1)} h'),
              const SizedBox(width: 8),
              SizedBox(
                width: 38,
                child: Text('${(entry.share * 100).toStringAsFixed(0)}%',
                    textAlign: TextAlign.right,
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            ]),
            const SizedBox(height: 4),
            _Track(fraction: entry.share, color: AssistantTheme.c1),
          ]),
        ),
    ]);
  }
}

/// Ranking de alunos, com a turma de cada um e a cor dela.
class _StudentPanel extends StatelessWidget {
  final StudyTimeStats stats;
  final StudyTimePalette palette;

  /// Nulo mostra todos.
  final int? limit;
  final VoidCallback onToggleLimit;

  const _StudentPanel({
    required this.stats,
    required this.palette,
    required this.limit,
    required this.onToggleLimit,
  });

  @override
  Widget build(BuildContext context) {
    final todos = stats.students;
    final mostrados = limit == null ? todos : todos.take(limit!).toList();
    final maior = mostrados.isEmpty ? 1 : mostrados.first.minutes;
    final escondidos = todos.length - mostrados.length;
    return _Panel(
      heading: 'Alunos',
      subtitle: escondidos == 0
          ? '${todos.length} no total, do maior para o menor'
          : '${mostrados.length} de ${todos.length}',
      action: todos.length <= _StudentPanel._minimoParaCortar
          ? null
          : TextButton(
              onPressed: onToggleLimit,
              child: Text(limit == null ? 'VER SÓ O TOPO' : 'VER TODOS'),
            ),
      footer: escondidos == 0
          ? null
          : Text(
              'Os demais $escondidos somam '
              '${(stats.minutesBeyond(mostrados.length) / 60).toStringAsFixed(1)} h.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
      child: mostrados.isEmpty
          ? const Center(child: Text('Nenhum aluno vinculado neste recorte.'))
          : ListView.builder(
              itemCount: mostrados.length,
              itemBuilder: (context, index) => _StudentBar(
                position: index + 1,
                entry: mostrados[index],
                largest: maior,
                color: palette.of(mostrados[index].group),
              ),
            ),
    );
  }

  static const _minimoParaCortar = 10;
}

class _StudentBar extends StatelessWidget {
  final int position;
  final StudyTimeEntry entry;
  final int largest;
  final Color color;

  const _StudentBar({
    required this.position,
    required this.entry,
    required this.largest,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(
            width: 28,
            child: Text('$positionº',
                style: Theme.of(context).textTheme.bodySmall),
          ),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(entry.label, overflow: TextOverflow.ellipsis),
              Text(entry.group,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall),
            ]),
          ),
          const SizedBox(width: 8),
          Text('${entry.hours.toStringAsFixed(1)} h'),
          const SizedBox(width: 10),
          SizedBox(
            width: 40,
            child: Text('${(entry.share * 100).toStringAsFixed(0)}%',
                textAlign: TextAlign.right,
                style: Theme.of(context).textTheme.bodySmall),
          ),
        ]),
        const SizedBox(height: 5),
        _Track(
          fraction: largest == 0 ? 0 : entry.minutes / largest,
          color: color,
        ),
      ]),
    );
  }
}

/// Distribuição por faixa: mostra a turma que o topo do ranking esconde.
class _BandsPanel extends StatelessWidget {
  final StudyTimeStats stats;
  final String? selected;
  final ValueChanged<String> onSelect;

  const _BandsPanel({
    required this.stats,
    required this.selected,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    final maior = stats.bands.fold<int>(
        1, (maximo, faixa) => faixa.students > maximo ? faixa.students : maximo);
    return _Panel(
      heading: 'Distribuição da turma',
      subtitle: 'alunos por faixa de dedicação',
      child: ListView(children: [
        for (final faixa in stats.bands)
          InkWell(
            onTap: () => onSelect(faixa.label),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                      child: Text(faixa.label, overflow: TextOverflow.ellipsis)),
                  Text('${faixa.students}'),
                ]),
                const SizedBox(height: 5),
                _Track(
                  fraction: faixa.students / maior,
                  color: selected == null || selected == faixa.label
                      ? AssistantTheme.c3
                      : AssistantTheme.c3.withValues(alpha: 0.25),
                ),
              ]),
            ),
          ),
        const SizedBox(height: 10),
        Text(
          'Clique numa faixa para ver só esses alunos. Faixa vazia é turma '
          'concentrada num extremo: ou quase ninguém estudou, ou o esforço está '
          'bem distribuído.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ]),
    );
  }
}

/// Barra com trilha explícita.
///
/// A versão antiga era um `LinearProgressIndicator`, cuja trilha herdava o
/// dourado do tema: parecia uma segunda série empilhada e não era nada.
class _Track extends StatelessWidget {
  final double fraction;
  final Color color;

  const _Track({required this.fraction, required this.color});

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(3),
      child: Stack(children: [
        Container(height: 11, color: AssistantTheme.surface2),
        FractionallySizedBox(
          widthFactor: fraction.isNaN ? 0 : fraction.clamp(0.0, 1.0),
          child: Container(height: 11, color: color),
        ),
      ]),
    );
  }
}

class _Panel extends StatelessWidget {
  final String heading;
  final String subtitle;
  final Widget child;
  final Widget? action;

  /// Linha que nao pode depender de rolagem, como o total do que ficou fora.
  final Widget? footer;

  const _Panel({
    required this.heading,
    required this.subtitle,
    required this.child,
    this.action,
    this.footer,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(heading, style: Theme.of(context).textTheme.headlineSmall),
                Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
            if (action != null) action!,
          ]),
          const SizedBox(height: 12),
          Expanded(child: child),
          if (footer != null) ...[
            const SizedBox(height: 8),
            footer!,
          ],
        ]),
      ),
    );
  }
}

/// O que a planilha não conta, dito uma vez, no rodapé.
class _Footnote extends StatelessWidget {
  final StudyTimeStats stats;

  const _Footnote({required this.stats});

  @override
  Widget build(BuildContext context) {
    return Text(
      'A cor é a turma do seu cadastro; a porcentagem é a fatia do tempo do '
      'recorte (${stats.totalHours.toStringAsFixed(1)} h) e o comprimento da '
      'barra compara com o primeiro colocado. Dados importados da planilha: '
      'linha com tempo vazio não entra (vazio não é zero) e matrícula sem aluno '
      'no cadastro conta no total, mas fica fora do ranking e sem turma.',
      style: Theme.of(context).textTheme.bodySmall,
    );
  }
}

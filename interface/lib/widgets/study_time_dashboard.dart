import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Visão ampliada de tempo de estudo para projetar em sala.
class StudyTimeDashboard extends StatelessWidget {
  final List<Map<String, dynamic>> records;
  final String title;

  const StudyTimeDashboard({super.key, required this.records, required this.title});

  @override
  Widget build(BuildContext context) {
    final total = records.fold<int>(0, (sum, row) => sum + (row['minutes'] as num).toInt());
    final linked = records.where((row) => row['student_id'] != null).length;
    final byDiscipline = <String, int>{};
    final byStudentId = <String, MapEntry<String, int>>{};
    for (final row in records) {
      final minutes = (row['minutes'] as num).toInt();
      final code = '${row['discipline_code']}';
      byDiscipline[code] = (byDiscipline[code] ?? 0) + minutes;
      if (row['student_id'] != null && row['student_name'] != null) {
        final id = '${row['student_id']}';
        final name = '${row['student_name']}';
        byStudentId[id] = MapEntry(name, (byStudentId[id]?.value ?? 0) + minutes);
      }
    }
    final disciplines = byDiscipline.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final students = byStudentId.values.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    Widget metric(String label, String value) => Card(
      child: Padding(padding: const EdgeInsets.all(18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(value, style: Theme.of(context).textTheme.headlineMedium),
        ])));
    Widget bar(String label, int minutes, int maximum) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text(label, overflow: TextOverflow.ellipsis)),
          Text('${(minutes / 60).toStringAsFixed(1)} h')]),
        const SizedBox(height: 5),
        LinearProgressIndicator(value: maximum == 0 ? 0 : minutes / maximum,
          minHeight: 12),
      ]));
    return Dialog.fullscreen(child: Scaffold(
      appBar: AppBar(title: Text('TEMPO DE ESTUDO  •  $title'), actions: [
        IconButton(icon: const Icon(Icons.close), tooltip: 'Fechar painel',
          onPressed: () => Navigator.of(context).pop()),
      ]),
      body: records.isEmpty
        ? const Center(child: Text('Não há registros para o filtro escolhido.'))
        : Padding(padding: const EdgeInsets.all(24), child: Column(children: [
          Wrap(spacing: 16, runSpacing: 12, children: [
            metric('Tempo total', '${(total / 60).toStringAsFixed(1)} horas'),
            metric('Registros', '${records.length}'),
            metric('Média por registro', '${(total / records.length).round()} min'),
            metric('Vinculados / pendentes', '$linked / ${records.length - linked}'),
          ]),
          const SizedBox(height: 20),
          Expanded(child: LayoutBuilder(builder: (context, constraints) {
            final narrow = constraints.maxWidth < 900;
            Widget panel(String heading, List<MapEntry<String, int>> entries) =>
              Card(child: Padding(padding: const EdgeInsets.all(20),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(heading, style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 12),
                  Expanded(child: ListView(children: entries.take(10)
                    .map((entry) => bar(entry.key, entry.value,
                      entries.isEmpty ? 0 : math.max(1, entries.first.value)))
                    .toList())),
                ])));
            if (narrow) {
              return ListView(children: [
                SizedBox(height: 360, child: panel('Por disciplina', disciplines)),
                SizedBox(height: 460, child: panel('Alunos vinculados', students)),
              ]);
            }
            return Row(children: [
              Expanded(child: panel('Por disciplina', disciplines)),
              const SizedBox(width: 16),
              Expanded(child: panel('Alunos vinculados', students)),
            ]);
          })),
          const SizedBox(height: 8),
          const Text('Dados importados da planilha. Linhas sem minutos não entram no total; '
            'registros pendentes não mostram nome de aluno.'),
        ])),
    ));
  }
}

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/education_service.dart';
import '../services/study_time_stats.dart';
import '../utils/theme.dart';
import 'study_time_dashboard.dart';

class StudyTimeTab extends StatefulWidget {
  const StudyTimeTab({super.key});

  @override
  State<StudyTimeTab> createState() => _StudyTimeTabState();
}

class _StudyTimeTabState extends State<StudyTimeTab> {
  List<Map<String, dynamic>> rows = [];
  String? discipline, group, course, semester;
  bool pendingOnly = false, busy = false;
  String message = '';

  /// Ordenacao da tabela: por padrao o maior tempo primeiro, que e a pergunta
  /// que se faz olhando esta lista.
  bool sortByMinutes = true, sortAscending = false;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    setState(() => busy = true);
    try {
      final removed = await education.reconcileStudyTimes();
      rows = await education.listStudyTimes();
      if (discipline != null && !rows.any((r) => r['discipline_code'] == discipline)) {
        discipline = null;
      }
      if (semester != null && !rows.any((r) => r['semester'] == semester)) {
        semester = null;
      }
      if (removed > 0) {
        message = '$removed registros de outras disciplinas removidos.';
      }
    } catch (e) {
      message = 'Falha ao carregar tempo de estudo: $e';
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> importFile() async {
    final picked = await FilePicker.pickFiles(
      type: FileType.custom, allowedExtensions: ['xlsx'], withData: true);
    if (picked == null || picked.files.isEmpty) return;
    final file = picked.files.single;
    if (file.bytes == null) {
      setState(() => message = 'Não foi possível ler a planilha.');
      return;
    }
    setState(() => busy = true);
    try {
      final preview = await education.previewStudyTimes(file.bytes!, file.name);
      if (!mounted) return;
      bool includeWithoutStudent = false;
      final approved = await showDialog<bool>(context: context,
        builder: (dialogContext) => StatefulBuilder(
          builder: (dialogContext, update) => AlertDialog(
            title: const Text('Conferir importação de tempo de estudo'),
            content: SizedBox(width: 520, child: SingleChildScrollView(child: Column(
              crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min,
              children: [
                Text('Arquivo: ${file.name}'),
                const SizedBox(height: 10),
                Text('Período na planilha: ${(preview['by_period'] as Map).keys.join(', ')}'),
                Text('Período cadastrado nas disciplinas: ${(preview['registered_periods'] as Map).entries.map((e) => '${e.key}: ${(e.value as List).join(', ')}').join('; ')}'),
                const Text('Se os períodos forem diferentes, confirme apenas se quiser guardar dados históricos ou de teste.'),
                Text('Disciplinas aceitas: ${(preview['by_discipline'] as Map).entries.map((e) => '${e.key} (${e.value})').join(', ')}'),
                const SizedBox(height: 10),
                Text('${preview['accepted_with_minutes']} linhas das suas disciplinas com minutos.'),
                Text('${preview['with_registered_student']} com matrícula localizada no cadastro de alunos.'),
                Text('${preview['without_registered_student']} sem aluno cadastrado com essa matrícula.'),
                Text('${includeWithoutStudent ? preview['new'] : preview['new_with_student']} novos registros; '
                  '${includeWithoutStudent ? preview['corrections'] : preview['corrections_with_student']} registros serão corrigidos.'),
                Text('No modo padrão, ${preview['existing_rows_removed_by_default']} registros da planilha já guardados serão removidos porque a matrícula não encontra aluno agora.'),
                Text('${preview['outside_my_disciplines']} linhas de outras disciplinas excluídas desta importação.'),
                Text('${preview['blank_minutes_in_my_disciplines']} linhas das suas disciplinas com tempo vazio não serão importadas.'),
                const SizedBox(height: 10),
                const Text('Por padrão, linhas sem aluno no cadastro não serão gravadas.'),
                CheckboxListTile(contentPadding: EdgeInsets.zero,
                  title: const Text('Guardar também linhas sem aluno no cadastro'),
                  subtitle: const Text('Elas terão matrícula e minutos, mas nenhum aluno vinculado.'),
                  value: includeWithoutStudent,
                  onChanged: (v) => update(() => includeWithoutStudent = v ?? false)),
              ],
            ))),
            actions: [
              TextButton(onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('Cancelar')),
              ElevatedButton(onPressed: (preview['with_registered_student'] as num).toInt() == 0
                  && !includeWithoutStudent ? null
                  : () => Navigator.pop(dialogContext, true),
                child: const Text('Confirmar importação')),
            ],
          ),
        ));
      if (approved != true) {
        if (mounted) setState(() => message = 'Importação cancelada. Nenhum dado foi gravado.');
        return;
      }
      final result = await education.importStudyTimes(
        file.bytes!, file.name, '${preview['preview_sha256']}',
        includeWithoutStudent: includeWithoutStudent);
      await refresh();
      if (mounted) {
        setState(() => message =
            '${result['created']} novos, ${result['updated']} corrigidos, '
            '${result['linked']} vinculados a alunos, '
            '${result['without_student_not_imported']} sem aluno no cadastro não importados, '
            '${result['pending']} sem aluno no cadastro guardados, '
            '${result['removed_without_student']} registros anteriores sem aluno localizado removidos, '
            '${result['skipped_other_disciplines']} linhas de outras disciplinas não importadas. '
            '${result['skipped_blank_minutes']} linhas tinham a coluna TEMPO DE ESTUDO vazia '
            'e não foram importadas; vazio não significa zero.');
      }
    } catch (e) {
      if (mounted) {
        setState(() => message = 'Importação falhou: $e');
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> deleteAll() async {
    final confirmed = await showDialog<bool>(context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Excluir todos os tempos de estudo?'),
        content: Text('${rows.length} registros importados serão excluídos de todas as suas disciplinas e períodos. Os filtros atuais não limitam esta exclusão.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Excluir todos')),
        ],
      ));
    if (confirmed != true || !mounted) return;
    setState(() => busy = true);
    try {
      final deleted = await education.deleteAllStudyTimes();
      await refresh();
      if (mounted) setState(() => message = '$deleted registros de tempo de estudo excluídos.');
    } catch (error) {
      if (mounted) setState(() => message = 'Falha ao excluir tempos de estudo: $error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    List<String> options(String field) =>
        rows.map((r) => '${r[field] ?? ''}').where((v) => v.isNotEmpty).toSet().toList()..sort();
    Widget filter(String label, String field, String? value, ValueChanged<String?> change) {
      // `isExpanded` e obrigatorio aqui: o nome do curso e longo
      // ("ANALISE E DESENVOLVIMENTO DE SISTEMAS") e sem ele o item selecionado
      // nao recebe a restricao de largura - o ellipsis nao chega a valer e a
      // linha estoura com o aviso amarelo de overflow.
      return SizedBox(width: 210, child: DropdownButtonFormField<String>(
        value: value, isExpanded: true,
        decoration: InputDecoration(labelText: label),
        items: [const DropdownMenuItem(value: null, child: Text('Todos')),
          ...options(field).map((v) => DropdownMenuItem(value: v, child: Text(v,
              overflow: TextOverflow.ellipsis)))],
        onChanged: change,
      ));
    }
    final visible = rows.where((r) =>
      (discipline == null || r['discipline_code'] == discipline) &&
      (group == null || r['group_sequence'] == group) &&
      (course == null || r['course'] == course) &&
      (semester == null || r['semester'] == semester) &&
      (!pendingOnly || r['student_id'] == null)).toList();
    visible.sort((a, b) {
      final compare = sortByMinutes
          ? ((a['minutes'] as num?) ?? 0).compareTo((b['minutes'] as num?) ?? 0)
          : '${a['student_name'] ?? a['enrollment']}'
              .compareTo('${b['student_name'] ?? b['enrollment']}');
      return sortAscending ? compare : -compare;
    });
    final stats = StudyTimeStats.fromRecords(visible);
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            ElevatedButton.icon(onPressed: busy ? null : importFile,
              icon: const Icon(Icons.upload_file), label: const Text('Importar ou corrigir XLSX')),
            ElevatedButton.icon(onPressed: busy ? null : () {
              showDialog<void>(context: context, builder: (_) => StudyTimeDashboard(
                records: visible,
                title: [if (discipline != null) discipline!,
                        if (group != null) 'Turma $group',
                        if (course != null) course!].join(' • ').isEmpty
                    ? 'Minhas disciplinas'
                    : [if (discipline != null) discipline!,
                       if (group != null) 'Turma $group',
                       if (course != null) course!].join(' • '),
              ));
            }, icon: const Icon(Icons.present_to_all),
              label: const Text('Exibir em sala')),
            Text('${visible.length} registros'),
            filter('Disciplina', 'discipline_code', discipline,
              (v) => setState(() => discipline = v)),
            filter('Turma (sequência)', 'group_sequence', group,
              (v) => setState(() => group = v)),
            filter('Curso', 'course', course,
              (v) => setState(() => course = v)),
            filter('Período da planilha', 'semester', semester,
              (v) => setState(() => semester = v)),
            FilterChip(label: const Text('Só sem aluno no cadastro'), selected: pendingOnly,
              onSelected: (v) => setState(() => pendingOnly = v)),
            OutlinedButton.icon(
              onPressed: busy || discipline == null || semester == null ? null : () async {
                final count = rows.where((r) => r['discipline_code'] == discipline
                    && r['semester'] == semester).length;
                final confirmed = await showDialog<bool>(context: context,
                  builder: (dialogContext) => AlertDialog(
                    title: const Text('Remover importação deste período?'),
                    content: Text('$count registros de $discipline em $semester serão excluídos.'),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(dialogContext, false),
                        child: const Text('Cancelar')),
                      TextButton(onPressed: () => Navigator.pop(dialogContext, true),
                        child: const Text('Excluir registros')),
                    ],
                  ));
                if (confirmed != true) return;
                final deleted = await education.deleteStudyTimesForPeriod(discipline!, semester!);
                await refresh();
                if (mounted) setState(() => message = '$deleted registros excluídos de $discipline em $semester.');
              },
              icon: const Icon(Icons.delete_sweep_outlined),
              label: const Text('Remover período importado')),
            OutlinedButton.icon(onPressed: busy || rows.isEmpty ? null : deleteAll,
              icon: const Icon(Icons.delete_forever_outlined),
              label: const Text('Excluir todos os tempos')),
          ]),
        if (message.isNotEmpty) Padding(padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(message)),
        if (visible.isNotEmpty) _SummaryStrip(stats: stats),
        const SizedBox(height: 10),
        Expanded(child: busy ? const Center(child: CircularProgressIndicator()) :
          SingleChildScrollView(child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              sortColumnIndex: sortByMinutes ? 5 : 0,
              sortAscending: sortAscending,
              columns: [
              DataColumn(label: const Text('Matrícula / aluno'),
                onSort: (_, ascending) => setState(() {
                  sortByMinutes = false;
                  sortAscending = ascending;
                })),
              const DataColumn(label: Text('Disciplina')),
              const DataColumn(label: Text('Turma')),
              const DataColumn(label: Text('Curso')),
              const DataColumn(label: Text('Semestre')),
              DataColumn(label: const Text('Minutos'), numeric: true,
                onSort: (_, ascending) => setState(() {
                  sortByMinutes = true;
                  sortAscending = ascending;
                })),
              const DataColumn(label: Text('Corrigir')),
            ], rows: visible.map((r) => DataRow(cells: [
              DataCell(Text('${r['enrollment']}\n${r['student_name'] ?? 'Aluno não cadastrado'}')),
              DataCell(Text('${r['discipline_code']}')),
              DataCell(Text('${r['group_sequence']}')),
              DataCell(Text('${r['course']}')),
              DataCell(Text('${r['semester']}')),
              DataCell(Text('${r['minutes']}')),
              DataCell(IconButton(icon: const Icon(Icons.delete_outline),
                tooltip: 'Excluir registro incorreto', onPressed: () async {
                  final confirmed = await showDialog<bool>(context: context,
                    builder: (dialogContext) => AlertDialog(
                      title: const Text('Excluir tempo de estudo?'),
                      content: Text('Matrícula ${r['enrollment']}: ${r['minutes']} minutos.'),
                      actions: [
                        TextButton(onPressed: () => Navigator.pop(dialogContext, false),
                          child: const Text('Cancelar')),
                        TextButton(onPressed: () => Navigator.pop(dialogContext, true),
                          child: const Text('Excluir')),
                      ],
                    ));
                  if (confirmed != true) return;
                  await education.deleteStudyTime('${r['id']}');
                  await refresh();
                })),
            ])).toList(),
          )))),
      ]),
    );
  }
}

/// Leitura rápida do que está filtrado, acima da tabela.
///
/// A tabela responde "quem estudou quanto"; esta faixa responde "como está a
/// turma" sem precisar abrir o painel de projeção.
class _SummaryStrip extends StatelessWidget {
  final StudyTimeStats stats;

  const _SummaryStrip({required this.stats});

  @override
  Widget build(BuildContext context) {
    Widget item(String label, String value, {String note = '', bool alert = false}) =>
      Padding(padding: const EdgeInsets.only(right: 22),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(fontSize: 10,
            color: AssistantTheme.textMuted)),
          Text(value, style: TextStyle(fontSize: 15,
            color: alert ? AssistantTheme.c4 : AssistantTheme.textPrimary)),
          if (note.isNotEmpty) Text(note, style: const TextStyle(fontSize: 9,
            color: AssistantTheme.textMuted)),
        ]));
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: AssistantTheme.surface,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AssistantTheme.border),
      ),
      child: Wrap(runSpacing: 8, children: [
        item('TEMPO TOTAL', '${stats.totalHours.toStringAsFixed(1)} h'),
        item('ALUNOS', '${stats.studentCount}'),
        item('MEDIANA', '${(stats.medianMinutes / 60).toStringAsFixed(1)} h',
          note: 'metade estudou menos'),
        item('5 PRIMEIROS', '${(stats.topShare() * 100).round()}%',
          note: 'do tempo da turma'),
        if (stats.unlinkedRecords > 0)
          item('SEM ALUNO', '${stats.unlinkedRecords}',
            note: 'fora do ranking', alert: true),
      ]),
    );
  }
}

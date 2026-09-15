import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/education_service.dart';

class StudyTimeTab extends StatefulWidget {
  const StudyTimeTab({super.key});

  @override
  State<StudyTimeTab> createState() => _StudyTimeTabState();
}

class _StudyTimeTabState extends State<StudyTimeTab> {
  List<Map<String, dynamic>> rows = [];
  String? discipline, group, course;
  bool pendingOnly = false, busy = false;
  String message = '';

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    setState(() => busy = true);
    try {
      rows = await education.listStudyTimes();
      message = '';
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
      final result = await education.importStudyTimes(file.bytes!, file.name);
      await refresh();
      if (mounted) {
        setState(() => message =
            '${result['created']} novos, ${result['updated']} corrigidos, '
            '${result['linked']} vinculados, ${result['pending']} pendentes.');
      }
    } catch (e) {
      if (mounted) {
        setState(() => message = 'Importação falhou: $e');
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    List<String> options(String field) =>
        rows.map((r) => '${r[field] ?? ''}').where((v) => v.isNotEmpty).toSet().toList()..sort();
    Widget filter(String label, String field, String? value, ValueChanged<String?> change) {
      return SizedBox(width: 210, child: DropdownButtonFormField<String>(
        value: value, decoration: InputDecoration(labelText: label),
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
      (!pendingOnly || r['student_id'] == null)).toList();
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            ElevatedButton.icon(onPressed: busy ? null : importFile,
              icon: const Icon(Icons.upload_file), label: const Text('Importar ou corrigir XLSX')),
            Text('${visible.length} registros'),
            filter('Disciplina', 'discipline_code', discipline,
              (v) => setState(() => discipline = v)),
            filter('Turma (sequência)', 'group_sequence', group,
              (v) => setState(() => group = v)),
            filter('Curso', 'course', course,
              (v) => setState(() => course = v)),
            FilterChip(label: const Text('Só pendentes'), selected: pendingOnly,
              onSelected: (v) => setState(() => pendingOnly = v)),
          ]),
        if (message.isNotEmpty) Padding(padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(message)),
        const SizedBox(height: 10),
        Expanded(child: busy ? const Center(child: CircularProgressIndicator()) :
          SingleChildScrollView(child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(columns: const [
              DataColumn(label: Text('Matrícula / aluno')),
              DataColumn(label: Text('Disciplina')),
              DataColumn(label: Text('Turma')),
              DataColumn(label: Text('Curso')),
              DataColumn(label: Text('Semestre')),
              DataColumn(label: Text('Minutos')),
              DataColumn(label: Text('Corrigir')),
            ], rows: visible.map((r) => DataRow(cells: [
              DataCell(Text('${r['enrollment']}\n${r['student_name'] ?? 'Pendente'}')),
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

import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/education_service.dart';

class ProjectGroupsTab extends StatefulWidget {
  final String initialText;
  final String initialDisciplineCode;
  final String initialDisciplineHint;

  const ProjectGroupsTab({super.key, this.initialText = '',
    this.initialDisciplineCode = '', this.initialDisciplineHint = ''});

  @override
  State<ProjectGroupsTab> createState() => _ProjectGroupsTabState();
}

class _ProjectGroupsTabState extends State<ProjectGroupsTab> {
  final textController = TextEditingController();
  List<Discipline> disciplines = [];
  List<ClassGroup> classes = [];
  List<Student> students = [];
  List<Map<String, dynamic>> groups = [];
  String? selectedId;
  String message = '';
  bool busy = false;

  @override
  void initState() {
    super.initState();
    textController.text = widget.initialText;
    load();
  }

  @override
  void dispose() {
    textController.dispose();
    super.dispose();
  }

  Future<void> load() async {
    setState(() => busy = true);
    try {
      disciplines = await education.listDisciplines(activeOnly: false);
      classes = await education.listClasses(activeOnly: false);
      students = await education.listStudents(activeOnly: false);
      if (selectedId == null && disciplines.isNotEmpty) {
        final matching = disciplines.where((item) =>
          item.code.toUpperCase() == widget.initialDisciplineCode.toUpperCase()).toList();
        final byHint = disciplines.where((item) => widget.initialDisciplineHint.isNotEmpty
          && item.name.toLowerCase().contains(widget.initialDisciplineHint.toLowerCase())).toList();
        selectedId = matching.isNotEmpty ? matching.first.id
          : byHint.isNotEmpty ? byHint.first.id : disciplines.first.id;
      }
      await loadGroups();
    } catch (error) {
      message = 'Não consegui carregar os grupos: $error';
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadGroups() async {
    groups = await education.listProjectGroups(disciplineId: selectedId);
    if (mounted) setState(() {});
  }

  Future<void> pickText() async {
    final picked = await FilePicker.pickFiles(type: FileType.custom,
      allowedExtensions: ['txt'], withData: true);
    if (picked == null || picked.files.isEmpty) return;
    final bytes = picked.files.single.bytes;
    if (bytes == null) return;
    try {
      textController.text = utf8.decode(bytes).replaceFirst('\uFEFF', '');
    } on FormatException {
      textController.text = latin1.decode(bytes);
    }
    setState(() => message = 'Lista carregada. Confira a disciplina e veja a prévia.');
  }

  Future<void> previewAndImport() async {
    if (selectedId == null || textController.text.trim().isEmpty) return;
    setState(() => busy = true);
    try {
      final preview = await education.previewProjectGroups(
        selectedId!, textController.text);
      if (!mounted) return;
      final confirmed = await showDialog<bool>(context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Conferir grupos antes de cadastrar'),
          content: SizedBox(width: 520, child: SingleChildScrollView(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min,
            children: [
              Text('${preview['discipline_code']} • ${preview['discipline_name']} • ${preview['semester']}'),
              const SizedBox(height: 10),
              Text('${preview['groups']} grupos e ${preview['members']} nomes.'),
              Text('${preview['new_groups']} grupos novos; ${preview['updated_groups']} atualizados.'),
              Text('${preview['members_removed_on_update']} integrantes antigos sairão dos grupos atualizados.'),
              Text('${preview['linked']} nomes com aluno identificado sem ambiguidade.'),
              Text('${preview['names_without_unique_match']} nomes ficarão na lista sem vínculo automático.'),
              const SizedBox(height: 10),
              ...((preview['group_names'] as List).map((item) => Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${item['name']}: ${item['members']} integrantes'
                    '${item['source_note'].toString().isEmpty ? '' : ' • anotação ${item['source_note']}'}',
                    style: Theme.of(context).textTheme.titleMedium),
                  ...((item['names'] as List).map((member) => Text(
                    '• ${member['name']}${member['linked'] == true ? ' ✓' : ' (sem vínculo automático)'}'))),
                  const SizedBox(height: 8),
                ],
              ))),
              if ('${preview['list_context']}'.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text('Observação original: ${preview['list_context']}'),
              ],
              const SizedBox(height: 10),
              const Text('Anotações da lista não serão interpretadas como notas de projeto.'),
            ],
          ))),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
            ElevatedButton(onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Confirmar cadastro')),
          ],
        ));
      if (confirmed != true) {
        if (mounted) setState(() => message = 'Cadastro cancelado. Nenhum grupo foi gravado.');
        return;
      }
      final result = await education.importProjectGroups(
        selectedId!, textController.text, '${preview['preview_sha256']}');
      await loadGroups();
      if (mounted) {
        setState(() => message =
          '${result['created']} grupos criados, ${result['updated']} atualizados; '
          '${result['linked_members']} integrantes vinculados, '
          '${result['names_without_link']} nomes sem vínculo com alunos cadastrados.');
      }
    } catch (error) {
      if (mounted) setState(() => message = 'Falha no cadastro: $error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  List<Student> get roster {
    final ids = classes.where((item) => item.disciplineId == selectedId)
        .map((item) => item.id).toSet();
    return students.where((student) => ids.contains(student.classId)).toList()
      ..sort((a, b) => a.name.compareTo(b.name));
  }

  Future<void> linkMember(Map<String, dynamic> group,
      Map<String, dynamic> member) async {
    String? studentId = member['student_id']?.toString();
    final selected = await showDialog<String?>(context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, update) => AlertDialog(
          title: Text('Vincular ${member['name']}'),
          content: SizedBox(width: 420, child: DropdownButtonFormField<String?>(
            value: studentId,
            decoration: const InputDecoration(labelText: 'Aluno cadastrado'),
            items: [const DropdownMenuItem<String?>(value: null,
              child: Text('Sem vínculo')),
              ...roster.map((student) => DropdownMenuItem<String?>(
                value: student.id, child: Text(student.name,
                  overflow: TextOverflow.ellipsis)))],
            onChanged: (value) => update(() => studentId = value),
          )),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancelar')),
            ElevatedButton(onPressed: () => Navigator.pop(dialogContext,
                studentId ?? ''), child: const Text('Salvar vínculo')),
          ],
        )));
    if (selected == null) return;
    await education.linkProjectGroupMember('${group['id']}',
      '${member['id']}', selected.isEmpty ? null : selected);
    await loadGroups();
  }

  Future<void> editProject(Map<String, dynamic> group) async {
    final title = TextEditingController(text: '${group['project_title'] ?? ''}');
    final description = TextEditingController(text: '${group['project_description'] ?? ''}');
    final review = TextEditingController(text: '${group['review_notes'] ?? ''}');
    final score = TextEditingController(text: group['score']?.toString() ?? '');
    final formKey = GlobalKey<FormState>();
    final saved = await showDialog<bool>(context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Projeto • ${group['name']}'),
        content: SizedBox(width: 560, child: SingleChildScrollView(child: Form(
          key: formKey, child: Column(
          mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: title, decoration: const InputDecoration(labelText: 'Título do projeto')),
            TextField(controller: description, maxLines: 4,
              decoration: const InputDecoration(labelText: 'Descrição e entregas')),
            TextField(controller: review, maxLines: 4,
              decoration: const InputDecoration(labelText: 'Análise e feedback')),
            TextFormField(controller: score,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              validator: (value) => value == null || value.trim().isEmpty
                || (double.tryParse(value.replaceAll(',', '.'))?.isFinite ?? false)
                  ? null : 'Informe um número válido',
              decoration: const InputDecoration(labelText: 'Pontuação registrada (opcional)')),
          ])))),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancelar')),
          ElevatedButton(onPressed: () {
            if (formKey.currentState?.validate() == true) {
              Navigator.pop(dialogContext, true);
            }
          },
            child: const Text('Salvar projeto')),
        ],
      ));
    if (saved == true) {
      await education.updateProjectGroup('${group['id']}', {
        'project_title': title.text,
        'project_description': description.text,
        'review_notes': review.text,
        'score': score.text.trim().isEmpty
          ? null : double.tryParse(score.text.replaceAll(',', '.')),
      });
      await loadGroups();
    }
    title.dispose(); description.dispose(); review.dispose(); score.dispose();
  }

  Future<void> removeGroup(Map<String, dynamic> group) async {
    final confirmed = await showDialog<bool>(context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Excluir ${group['name']}?'),
        content: const Text('Os integrantes e as notas deste grupo serão excluídos.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Excluir grupo')),
        ],
      ));
    if (confirmed != true) return;
    await education.deleteProjectGroup('${group['id']}');
    await loadGroups();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(padding: const EdgeInsets.all(16), child: Column(children: [
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SizedBox(width: 360, child: DropdownButtonFormField<String>(
            value: selectedId,
            decoration: const InputDecoration(labelText: 'Disciplina'),
            items: disciplines.map((item) => DropdownMenuItem(
              value: item.id, child: Text('${item.code} • ${item.name} (${item.semester})',
                overflow: TextOverflow.ellipsis))).toList(),
            onChanged: (value) async {
              setState(() => selectedId = value);
              await loadGroups();
            },
          )),
          OutlinedButton.icon(onPressed: busy ? null : pickText,
            icon: const Icon(Icons.upload_file), label: const Text('Carregar TXT')),
          ElevatedButton.icon(onPressed: busy ? null : previewAndImport,
            icon: const Icon(Icons.fact_check_outlined),
            label: const Text('Conferir e cadastrar grupos')),
          Text('${groups.length} grupos cadastrados'),
        ]),
      const SizedBox(height: 10),
      TextField(controller: textController, minLines: 2, maxLines: 5,
        decoration: const InputDecoration(
          labelText: 'Lista para importar ou colar do chat',
          hintText: 'GRUPO 1\nNOME DO ALUNO\nGRUPO 2\nOUTRO ALUNO',
          border: OutlineInputBorder())),
      if (message.isNotEmpty) Padding(padding: const EdgeInsets.all(8),
        child: Text(message)),
      const SizedBox(height: 8),
      Expanded(child: busy ? const Center(child: CircularProgressIndicator()) :
        groups.isEmpty ? const Center(child: Text('Nenhum grupo cadastrado nesta disciplina.')) :
        ListView(children: groups.map((group) {
          final members = (group['members'] as List).cast<Map<String, dynamic>>();
          return Card(child: Padding(padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text('${group['name']} • ${group['semester']}',
                  style: Theme.of(context).textTheme.titleLarge)),
                IconButton(icon: const Icon(Icons.edit_note), tooltip: 'Editar projeto e análise',
                  onPressed: () => editProject(group)),
                IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Excluir grupo',
                  onPressed: () => removeGroup(group)),
              ]),
              if ('${group['project_title']}'.isNotEmpty)
                Text('Projeto: ${group['project_title']}'),
              if ('${group['project_description']}'.isNotEmpty)
                Text('${group['project_description']}'),
              if ('${group['review_notes']}'.isNotEmpty)
                Text('Análise: ${group['review_notes']}'),
              if (group['score'] != null)
                Text('Pontuação registrada: ${group['score']}'),
              if ('${group['source_note']}'.isNotEmpty)
                Text('Anotações da lista: ${group['source_note']}'),
              const SizedBox(height: 8),
              Wrap(spacing: 8, runSpacing: 6,
                children: members.map((member) => ActionChip(
                  tooltip: member['student_id'] == null
                    ? 'Nome da lista sem vínculo com aluno cadastrado'
                    : 'Vinculado a ${member['student_name']}',
                  avatar: Icon(member['student_id'] == null
                    ? Icons.person_outline : Icons.check_circle_outline, size: 17),
                  label: Text('${member['name']}'
                    '${member['source_note'].toString().isEmpty ? '' : ' (${member['source_note']})'}'),
                  onPressed: () => linkMember(group, member),
                )).toList()),
            ])));
        }).toList())),
    ]));
  }
}

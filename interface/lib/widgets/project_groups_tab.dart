import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/education_service.dart';

String projectGroupDisciplineCode(Discipline item) =>
  RegExp(r'ARA\d{4}', caseSensitive: false).firstMatch(item.code)?.group(0)?.toUpperCase()
    ?? item.code.toUpperCase();

Discipline? inferProjectGroupDiscipline(List<Discipline> disciplines, String source) {
  final upper = source.toUpperCase();
  final code = RegExp(r'ARA\d{4}').firstMatch(upper)?.group(0);
  final period = RegExp(r'20\d{2}[-._][12]').firstMatch(upper)?.group(0)
    ?.replaceAll(RegExp(r'[-_]'), '.');
  List<Discipline> matches = code == null ? [] : disciplines
    .where((item) => projectGroupDisciplineCode(item) == code).toList();
  if (matches.isEmpty && RegExp(r'\bIOT\b').hasMatch(upper)) {
    matches = disciplines.where((item) =>
      '${item.code} ${item.name}'.toUpperCase().contains('IOT')).toList();
  }
  if (period != null) {
    final samePeriod = matches.where((item) => item.semester == period).toList();
    if (samePeriod.isNotEmpty) matches = samePeriod;
  }
  return matches.length == 1 ? matches.single : null;
}

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
  /// Apresentacoes gravadas, por grupo. Ficam aqui para a avaliacao ter ao lado
  /// o que o grupo falou, e nao so a nota.
  Map<String, List<Lesson>> presentations = {};
  String? selectedId;
  String message = '';
  bool busy = false;

  String disciplineCode(Discipline item) => projectGroupDisciplineCode(item);
  Discipline? inferDiscipline(String source) =>
    inferProjectGroupDiscipline(disciplines, source);

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
          widget.initialDisciplineCode.isNotEmpty &&
          disciplineCode(item) == widget.initialDisciplineCode.toUpperCase()).toList();
        final byHint = disciplines.where((item) => widget.initialDisciplineHint.isNotEmpty
          && '${item.code} ${item.name}'.toLowerCase()
            .contains(widget.initialDisciplineHint.toLowerCase())).toList();
        final fromText = inferDiscipline(
          '${widget.initialDisciplineCode} ${widget.initialDisciplineHint} ${widget.initialText}');
        selectedId = matching.length == 1 ? matching.single.id
          : byHint.length == 1 ? byHint.single.id : fromText?.id;
      }
      await loadGroups();
    } catch (error) {
      message = 'Não consegui carregar os grupos: $error';
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadGroups() async {
    groups = selectedId == null ? [] :
      await education.listProjectGroups(disciplineId: selectedId);
    await loadPresentations();
    if (mounted) setState(() {});
  }

  Future<void> loadPresentations() async {
    presentations = {};
    try {
      final gravacoes = await education.listLessons(kind: 'apresentacao', limit: 200);
      for (final gravacao in gravacoes) {
        if (gravacao.groupId.isEmpty) continue;
        presentations.putIfAbsent(gravacao.groupId, () => []).add(gravacao);
      }
    } catch (_) {
      // Sem as gravacoes a aba continua servindo para cadastro e avaliacao.
    }
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
    final inferred = inferDiscipline(picked.files.single.name);
    if (inferred != null) {
      setState(() {
        selectedId = inferred.id;
        message = 'Lista carregada. Disciplina ${disciplineCode(inferred)} sugerida pelo nome do arquivo; confira antes de importar.';
      });
      await loadGroups();
    } else {
      setState(() {
        selectedId = null;
        groups = [];
        message = 'Lista carregada. Selecione a disciplina antes de conferir a prévia.';
      });
    }
  }

  Future<String?> choosePreviewStudent(Map member) async {
    final query = TextEditingController();
    final candidates = (member['candidates'] as List? ?? [])
      .map((item) => Map<String, dynamic>.from(item as Map)).toList();
    final chosen = await showDialog<String>(context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, update) {
          final search = query.text.trim().toLowerCase();
          final available = roster.where((student) => search.isEmpty ||
            student.name.toLowerCase().contains(search) ||
            (student.externalId ?? '').contains(search) ||
            student.aliases.any((alias) => alias.toLowerCase().contains(search))).toList();
          final ordered = search.isEmpty ? <String>{
            ...candidates.map((item) => item['student_id'].toString()),
            ...available.map((student) => student.id),
          }.toList() : available.map((student) => student.id).toList();
          final byId = {for (final student in roster) student.id: student};
          return AlertDialog(
            title: Text('Escolher aluno para ${member['name']}'),
            content: SizedBox(width: 480, height: 430, child: Column(children: [
              TextField(controller: query, autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'Buscar por nome ou matrícula',
                  prefixIcon: Icon(Icons.search)),
                onChanged: (_) => update(() {})),
              const SizedBox(height: 8),
              Expanded(child: ListView(children: ordered.take(80)
                .where((id) => byId.containsKey(id)).map((id) {
                  final student = byId[id]!;
                  final suggested = candidates.where((item) => item['student_id'] == id).toList();
                  return ListTile(
                    title: Text(student.name),
                    subtitle: Text('Matrícula ${student.externalId ?? 'não informada'}'
                      '${suggested.isEmpty ? '' : ' • semelhança ${((suggested.first['confidence'] as num) * 100).round()}%'}'),
                    onTap: () => Navigator.pop(dialogContext, id));
                }).toList())),
            ])),
            actions: [
              TextButton(onPressed: () => Navigator.pop(dialogContext),
                child: const Text('Cancelar')),
              TextButton(onPressed: () => Navigator.pop(dialogContext, ''),
                child: const Text('Deixar sem vínculo')),
            ],
          );
        }));
    query.dispose();
    return chosen;
  }

  Future<void> previewAndImport() async {
    if (selectedId == null) {
      setState(() => message = 'Selecione a disciplina correta para comparar as matrículas.');
      return;
    }
    if (textController.text.trim().isEmpty) return;
    setState(() => busy = true);
    try {
      final preview = await education.previewProjectGroups(
        selectedId!, textController.text);
      if (!mounted) return;
      final choices = <String, String>{};
      var acknowledgedLowMatch = false;
      int linkedAfterReview() {
        var count = 0;
        for (final group in preview['group_names'] as List) {
          for (final member in group['names'] as List) {
            final key = '${group['name']}\u0000${member['name']}';
            if (choices.containsKey(key)
                ? choices[key]!.isNotEmpty : member['linked'] == true) {
              count++;
            }
          }
        }
        return count;
      }
      bool lowMatch() => (preview['roster_count'] as num).toInt() > 0 &&
        linkedAfterReview() * 4 < (preview['members'] as num).toInt();
      final confirmed = await showDialog<bool>(context: context,
        builder: (dialogContext) => StatefulBuilder(
          builder: (dialogContext, update) => AlertDialog(
          title: const Text('Conferir grupos antes de cadastrar'),
          content: SizedBox(width: 620, height: 550,
            child: SingleChildScrollView(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min,
            children: [
              Text('${preview['discipline_code']}'
                '${'${preview['discipline_name']}'.trim().isEmpty ? '' : ' • ${preview['discipline_name']}'}'
                ' • ${preview['semester']}'),
              const SizedBox(height: 10),
              Text('${preview['groups']} grupos e ${preview['members']} nomes.'),
              Text('${preview['new_groups']} grupos novos; ${preview['updated_groups']} atualizados.'),
              Text('${preview['members_removed_on_update']} integrantes antigos sairão dos grupos atualizados.'),
              Text('${linkedAfterReview()} nomes serão vinculados; '
                '${(preview['members'] as num).toInt() - linkedAfterReview()} ficarão sem vínculo.'),
              Text('${preview['roster_count']} alunos ativos nas turmas desta disciplina.'),
              if (lowMatch()) ...[
                const SizedBox(height: 8),
                Text('Poucos nomes correspondem aos alunos desta disciplina. Confira se escolheu a matéria correta antes de importar.',
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
                CheckboxListTile(contentPadding: EdgeInsets.zero,
                  title: const Text('Conferi a disciplina e quero importar mesmo assim'),
                  value: acknowledgedLowMatch,
                  onChanged: (value) => update(() => acknowledgedLowMatch = value ?? false)),
              ],
              if (choices.isNotEmpty) Text('${choices.length} vínculos revisados por você.'),
              const Text('Toque no lápis de um nome para revisar ou escolher outra matrícula.'),
              const SizedBox(height: 10),
              ...((preview['group_names'] as List).map((item) => Column(
                crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${item['name']}: ${item['members']} integrantes'
                    '${item['source_note'].toString().isEmpty ? '' : ' • anotação ${item['source_note']}'}',
                    style: Theme.of(context).textTheme.titleMedium),
                  ...((item['names'] as List).map((member) {
                    final key = '${item['name']}\u0000${member['name']}';
                    final selected = choices[key];
                    final changed = choices.containsKey(key);
                    final manual = roster.where((student) => student.id == selected).toList();
                    final display = changed
                      ? selected == '' ? 'sem vínculo (sua escolha)'
                        : manual.isEmpty ? 'aluno indisponível'
                        : '${manual.first.name} • matrícula ${manual.first.externalId ?? 'não informada'} (sua escolha)'
                      : member['linked'] == true
                        ? '${member['student_name']} • matrícula ${member['enrollment']}'
                          ' • ${member['match_source'] == 'confirmed'
                            ? 'correção confirmada anteriormente'
                            : 'semelhança ${((member['confidence'] as num) * 100).round()}%'}'
                        : 'sem vínculo automático';
                    final suggestions = (member['candidates'] as List? ?? [])
                      .map((candidate) => '${candidate['student_name']}'
                        ' (${((candidate['confidence'] as num) * 100).round()}%)').join(', ');
                    return Padding(padding: const EdgeInsets.only(top: 4),
                      child: Row(children: [
                        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('• ${member['name']} → $display'),
                            if (!changed && member['linked'] != true && suggestions.isNotEmpty)
                              Text('Sugestões: $suggestions',
                                style: Theme.of(context).textTheme.bodySmall),
                            if (!changed && member['linked'] != true && suggestions.isEmpty)
                              Text('Nenhum candidato próximo entre os alunos ativos da disciplina.',
                                style: Theme.of(context).textTheme.bodySmall),
                          ])),
                        IconButton(icon: const Icon(Icons.edit_outlined, size: 18),
                          tooltip: 'Revisar matrícula',
                          onPressed: () async {
                            final picked = await choosePreviewStudent(
                              Map<String, dynamic>.from(member as Map));
                            if (picked != null) update(() => choices[key] = picked);
                          }),
                      ]));
                  })),
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
            ElevatedButton(onPressed: lowMatch() && !acknowledgedLowMatch ? null :
              () => Navigator.pop(dialogContext, true),
              child: const Text('Confirmar cadastro')),
          ],
        )));
      if (confirmed != true) {
        if (mounted) setState(() => message = 'Cadastro cancelado. Nenhum grupo foi gravado.');
        return;
      }
      final result = await education.importProjectGroups(
        selectedId!, textController.text, '${preview['preview_sha256']}',
        memberLinks: choices.entries.map((entry) {
          final parts = entry.key.split('\u0000');
          return <String, dynamic>{'group_name': parts[0], 'member_name': parts[1],
            'student_id': entry.value.isEmpty ? null : entry.value};
        }).toList());
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
    return students.where((student) => student.active && ids.contains(student.classId)).toList()
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

  Future<void> editPenalty(Map<String, dynamic> group) async {
    final controller = TextEditingController(
      text: '${group['penalty_points'] ?? 0}');
    final key = GlobalKey<FormState>();
    final confirmed = await showDialog<bool>(context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Subtração de pontos • ${group['name']}'),
        content: SizedBox(width: 360, child: Form(key: key, child: Column(
          mainAxisSize: MainAxisSize.min, children: [
          TextFormField(controller: controller,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Pontos a subtrair'),
            validator: (value) {
              final number = double.tryParse((value ?? '').replaceAll(',', '.'));
              return number != null && number.isFinite && number >= 0
                ? null : 'Informe zero ou um valor positivo';
            }),
          const SizedBox(height: 8),
          const Text('A penalidade fica registrada neste grupo. Zero a remove.'),
        ]))),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancelar')),
          ElevatedButton(onPressed: () {
            if (key.currentState?.validate() == true) {
              Navigator.pop(dialogContext, true);
            }
          }, child: const Text('Salvar')),
        ],
      ));
    if (confirmed == true) {
      await education.updateProjectGroup('${group['id']}', {
        'penalty_points': double.parse(controller.text.replaceAll(',', '.')),
      });
      await loadGroups();
    }
    controller.dispose();
  }

  Future<void> reviewSuggestedLinks() async {
    if (selectedId == null) return;
    setState(() => busy = true);
    try {
      final rows = await education.projectGroupLinkSuggestions(selectedId!);
      if (!mounted) return;
      final choices = <String, String?>{};
      final confirmed = await showDialog<bool>(context: context,
        builder: (dialogContext) => StatefulBuilder(
          builder: (dialogContext, update) => AlertDialog(
            title: const Text('Conferir nomes e matrículas'),
            content: SizedBox(width: 620, height: 520,
              child: rows.isEmpty ? const Text('Todos os integrantes já têm vínculo.')
                : ListView(children: [
                  const Text('Sugestões por semelhança de nome, restritas às turmas desta disciplina. Confira a matrícula antes de salvar.'),
                  const SizedBox(height: 12),
                  ...rows.map((row) {
                    final candidates = (row['candidates'] as List).cast<Map<String, dynamic>>();
                    if (candidates.isEmpty) {
                      return ListTile(
                        title: Text('${row['member_name']} • ${row['group_name']}'),
                        subtitle: const Text('Nenhuma sugestão; use o vínculo manual no integrante.'));
                    }
                    return Padding(padding: const EdgeInsets.only(bottom: 12),
                      child: DropdownButtonFormField<String>(
                        value: choices['${row['member_id']}'],
                        isExpanded: true,
                        decoration: InputDecoration(labelText:
                          '${row['member_name']} • ${row['group_name']}'),
                        items: [const DropdownMenuItem<String>(value: '',
                          child: Text('Não associar agora')),
                          ...candidates.map((candidate) => DropdownMenuItem<String>(
                            value: '${candidate['student_id']}',
                            child: Text('${candidate['student_name']} • matrícula ${candidate['enrollment']}'
                              ' • ${((candidate['confidence'] as num) * 100).round()}%',
                              overflow: TextOverflow.ellipsis)))],
                        onChanged: (value) => update(() => choices['${row['member_id']}'] = value),
                      ));
                  }),
                ])),
            actions: [
              TextButton(onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('Cancelar')),
              ElevatedButton(onPressed: choices.values.where((id) => id != null && id.isNotEmpty).isEmpty
                ? null : () => Navigator.pop(dialogContext, true),
                child: Text('Confirmar ${choices.values.where((id) => id != null && id.isNotEmpty).length} vínculos')),
            ],
          )));
      if (confirmed == true) {
        final links = choices.entries.where((entry) => entry.value != null && entry.value!.isNotEmpty)
          .map((entry) => {'member_id': entry.key, 'student_id': entry.value!}).toList();
        final linked = await education.confirmProjectGroupLinks(selectedId!, links);
        await loadGroups();
        if (mounted) setState(() => message = '$linked integrantes vinculados após sua confirmação.');
      }
    } catch (error) {
      if (mounted) setState(() => message = 'Falha ao conferir vínculos: $error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> linkUnambiguousNames() async {
    if (selectedId == null) return;
    setState(() => busy = true);
    try {
      final rows = await education.projectGroupLinkSuggestions(selectedId!);
      final safe = rows.where((row) => row['automatic_match'] != null).toList();
      if (!mounted) return;
      if (safe.isEmpty) {
        setState(() => message = 'Nenhum nome sem vínculo tem correspondência inequívoca nesta disciplina.');
        return;
      }
      final confirmed = await showDialog<bool>(context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text('Conferir ${safe.length} vínculos automáticos'),
          content: SizedBox(width: 560, height: 420,
            child: ListView(children: [
              const Text('Confira os nomes e matrículas. Só há correspondências únicas nesta disciplina.'),
              const SizedBox(height: 12),
              ...safe.map((row) {
                final student = row['automatic_match'] as Map<String, dynamic>;
                return ListTile(title: Text('${row['member_name']} → ${student['student_name']}'),
                  subtitle: Text('${row['group_name']} • matrícula ${student['enrollment']}'));
              }),
            ])),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
            ElevatedButton(onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Confirmar vínculos')),
          ],
        ));
      if (confirmed != true) return;
      final links = safe.map((row) => <String, String>{
        'member_id': '${row['member_id']}',
        'student_id': '${(row['automatic_match'] as Map)['student_id']}',
      }).toList();
      final linked = await education.confirmProjectGroupLinks(selectedId!, links);
      await loadGroups();
      if (mounted) setState(() => message = '$linked nomes vinculados após sua confirmação.');
    } catch (error) {
      if (mounted) setState(() => message = 'Falha ao vincular nomes: $error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
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

  Future<void> deleteAll() async {
    setState(() => busy = true);
    try {
      final allGroups = await education.listProjectGroups();
      if (!mounted) return;
      final confirmed = await showDialog<bool>(context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Excluir todos os grupos de projeto?'),
          content: Text('${allGroups.length} grupos, seus integrantes e as correções de vínculo aprendidas serão excluídos de todas as suas disciplinas e períodos. A disciplina selecionada não limita esta exclusão.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
            TextButton(onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Excluir todos os grupos')),
          ],
        ));
      if (confirmed != true) return;
      final deleted = await education.deleteAllProjectGroups();
      await loadGroups();
      if (mounted) setState(() => message = '$deleted grupos de projeto excluídos.');
    } catch (error) {
      if (mounted) setState(() => message = 'Falha ao excluir grupos: $error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(padding: const EdgeInsets.all(16), child: Column(children: [
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SizedBox(width: 360, child: DropdownButtonFormField<String>(
            value: selectedId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Disciplina',
              hintText: 'Escolha a matéria da lista'),
            selectedItemBuilder: (context) => disciplines.map((item) =>
              Align(alignment: Alignment.centerLeft, child: Text(
                '${item.code} • ${item.name} (${item.semester})',
                maxLines: 1, overflow: TextOverflow.ellipsis))).toList(),
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
          ElevatedButton.icon(onPressed: busy || selectedId == null ? null : previewAndImport,
            icon: const Icon(Icons.fact_check_outlined),
            label: const Text('Conferir e cadastrar grupos')),
          OutlinedButton.icon(onPressed: busy || groups.isEmpty ? null : reviewSuggestedLinks,
            icon: const Icon(Icons.person_search_outlined),
            label: const Text('Sugerir nomes e matrículas')),
          OutlinedButton.icon(onPressed: busy || groups.isEmpty ? null : linkUnambiguousNames,
            icon: const Icon(Icons.auto_fix_high_outlined),
            label: const Text('Vincular nomes seguros')),
          OutlinedButton.icon(onPressed: busy ? null : deleteAll,
            icon: const Icon(Icons.delete_forever_outlined),
            label: const Text('Excluir todos os grupos')),
          Text(selectedId == null ? 'Selecione a disciplina' :
            '${groups.length} grupos cadastrados'),
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
      if (groups.isNotEmpty) ...[
        Builder(builder: (context) {
          final notes = groups.map((group) => '${group['source_note'] ?? ''}'
            .split('\n').map((line) => line.trim()).where((line) => line.isNotEmpty).toSet()).toList();
          final common = notes.first.intersection(
            notes.skip(1).fold(notes.first.toSet(), (set, note) => set.intersection(note)));
          if (common.isEmpty) return const SizedBox.shrink();
          return Padding(padding: const EdgeInsets.only(bottom: 10),
            child: Card(child: Padding(padding: const EdgeInsets.all(12),
              child: Row(children: [const Icon(Icons.info_outline),
                const SizedBox(width: 8),
                Expanded(child: Text('Aviso geral da lista: ${common.join(' • ')}'))]))));
        }),
      ],
      Expanded(child: busy ? const Center(child: CircularProgressIndicator()) :
        groups.isEmpty ? Center(child: Text(selectedId == null
          ? 'Selecione a disciplina da lista para ver os grupos.'
          : 'Nenhum grupo cadastrado nesta disciplina.')) :
        ListView(children: groups.map((group) {
          final members = (group['members'] as List).cast<Map<String, dynamic>>();
          final allNotes = groups.map((item) => '${item['source_note'] ?? ''}'
            .split('\n').map((line) => line.trim()).where((line) => line.isNotEmpty).toSet()).toList();
          final commonNotes = allNotes.skip(1).fold(allNotes.first.toSet(),
            (set, notes) => set.intersection(notes));
          final groupNotes = '${group['source_note'] ?? ''}'.split('\n')
            .map((line) => line.trim()).where((line) => line.isNotEmpty && !commonNotes.contains(line)).toList();
          return Card(child: Padding(padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text('${group['name']} • ${group['semester']}',
                  style: Theme.of(context).textTheme.titleLarge)),
                IconButton(icon: const Icon(Icons.edit_note), tooltip: 'Editar projeto e análise',
                  onPressed: () => editProject(group)),
                IconButton(icon: const Icon(Icons.remove_circle_outline),
                  tooltip: 'Registrar subtração de pontos neste grupo',
                  onPressed: () => editPenalty(group)),
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
              if ((group['penalty_points'] as num? ?? 0) > 0)
                Text('Subtração de pontos: −${group['penalty_points']}'),
              if (groupNotes.isNotEmpty)
                Text('Anotação deste grupo: ${groupNotes.join(' • ')}'),
              if ((presentations['${group['id']}'] ?? const []).isNotEmpty) ...[
                const SizedBox(height: 8),
                Text('Apresentações gravadas',
                  style: Theme.of(context).textTheme.labelMedium),
                for (final gravacao in presentations['${group['id']}']!)
                  Padding(padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      [
                        _quando(gravacao.startedAt),
                        gravacao.title,
                        '${gravacao.transcriptChars} caracteres transcritos',
                        if ((gravacao.summary ?? '').isNotEmpty) 'com resumo',
                      ].where((parte) => parte.isNotEmpty).join(' • '),
                      style: Theme.of(context).textTheme.bodySmall)),
              ],
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

String _quando(DateTime? value) {
  if (value == null) return '';
  final local = value.toLocal();
  String dois(int n) => n.toString().padLeft(2, '0');
  return '${dois(local.day)}/${dois(local.month)} ${dois(local.hour)}:${dois(local.minute)}';
}

/// PDFs dos grupos de projeto: a relação de grupos e a ordem de apresentação.
///
/// A relação serve para colar na sala ou conferir a chamada do projeto: cada grupo
/// com os integrantes e a matrícula. A ordem de apresentação leva o resultado do
/// sorteio - posição, dia, representante e situação - com a semente no rodapé, para
/// quem quiser conferir que o sorteio foi limpo.
library;

import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../branding/intarq_brand.dart';
import '../models/group_draw.dart';
import 'education_service.dart';
import 'pdf_common.dart';

/// Integrante como sai no papel.
class GroupListMember {
  final String name;

  /// Matrícula do aluno ligado a este nome; vazia quando o nome da lista ainda
  /// não foi ligado a um aluno cadastrado.
  final String enrollment;

  const GroupListMember({required this.name, this.enrollment = ''});
}

/// Grupo como sai no papel.
class GroupListGroup {
  final String name;
  final String projectTitle;
  final List<GroupListMember> members;

  const GroupListGroup({
    required this.name,
    this.projectTitle = '',
    this.members = const [],
  });
}

/// Compara "Grupo 2" antes de "Grupo 10": nome com número ordena pelo número.
int compareNatural(String a, String b) {
  final parts = RegExp(r'\d+|\D+');
  final left = parts.allMatches(a.toLowerCase()).map((m) => m.group(0)!).toList();
  final right = parts.allMatches(b.toLowerCase()).map((m) => m.group(0)!).toList();
  for (var i = 0; i < left.length && i < right.length; i++) {
    final x = left[i], y = right[i];
    final nx = int.tryParse(x), ny = int.tryParse(y);
    final result = (nx != null && ny != null) ? nx.compareTo(ny) : x.compareTo(y);
    if (result != 0) return result;
  }
  return left.length.compareTo(right.length);
}

/// Monta a relação a partir do que `GET /education/project-groups` devolve.
///
/// A matrícula vem do aluno ligado ao integrante (`student_id`); integrante sem
/// ligação sai sem matrícula, e não com uma inventada pelo nome.
List<GroupListGroup> groupListFrom(
  List<Map<String, dynamic>> groups,
  List<Student> students,
) {
  final byId = {for (final student in students) student.id: student};
  final result = [
    for (final group in groups)
      GroupListGroup(
        name: '${group['name'] ?? ''}'.trim(),
        projectTitle: '${group['project_title'] ?? ''}'.trim(),
        members: [
          for (final member in ((group['members'] as List?) ?? const [])
              .whereType<Map>()
              .toList()
            ..sort((a, b) => ((a['position'] as num?) ?? 0)
                .compareTo((b['position'] as num?) ?? 0)))
            GroupListMember(
              name: '${member['name'] ?? ''}'.trim(),
              enrollment:
                  (byId['${member['student_id'] ?? ''}']?.externalId ?? '').trim(),
            ),
        ],
      ),
  ];
  result.sort((a, b) => compareNatural(a.name, b.name));
  return result;
}

pw.Widget _runningHeader(String left, pw.MemoryImage? brandMark) => pw.Container(
      margin: const pw.EdgeInsets.only(bottom: 12),
      padding: const pw.EdgeInsets.only(top: 24, bottom: 6),
      decoration: const pw.BoxDecoration(
        border: pw.Border(bottom: pw.BorderSide(color: pdfRule)),
      ),
      child: pw.Row(
        mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
        children: [
          pw.Expanded(
            child: pw.Text(
              left,
              style: const pw.TextStyle(fontSize: 8, color: pdfInkSoft),
            ),
          ),
          IntarqBrand.pdfSignature(brandMark, width: 82, height: 30),
        ],
      ),
    );

pw.Widget _cell(
  String text, {
  bool header = false,
  pw.TextAlign align = pw.TextAlign.left,
  PdfColor? color,
  bool bold = false,
}) =>
    pw.Padding(
      padding: const pw.EdgeInsets.symmetric(horizontal: 6, vertical: 4),
      child: pw.Text(
        text,
        textAlign: align,
        style: pw.TextStyle(
          fontSize: header ? 8.5 : 10,
          color: color ?? (header ? pdfInkSoft : pdfInk),
          fontWeight: header || bold ? pw.FontWeight.bold : pw.FontWeight.normal,
        ),
      ),
    );

pw.Document _document(String title) => pw.Document(title: title, author: 'INTARQ');

pw.PageTheme _pageTheme(pw.ThemeData theme) => pw.PageTheme(
      pageFormat: PdfPageFormat.a4,
      margin: const pw.EdgeInsets.fromLTRB(36, 0, 36, 40),
      theme: theme,
    );

/// Relação de grupos de uma disciplina.
Future<Uint8List> buildGroupListPdf({
  required String discipline,
  required List<GroupListGroup> groups,
  String classLabel = '',
  String semester = '',
  bool showEnrollment = true,
  DateTime? generatedAt,
}) async {
  const title = 'Relação de grupos';
  final document = _document(title);
  final brandMark = await IntarqBrand.loadPdfMark();
  final theme = await pdfTheme();
  final students = groups.fold<int>(0, (sum, group) => sum + group.members.length);
  final running = [discipline, classLabel, title]
      .where((part) => part.isNotEmpty)
      .join('   |   ');

  document.addPage(
    pw.MultiPage(
      pageTheme: _pageTheme(theme),
      header: (context) => context.pageNumber == 1
          ? pdfBanner(
              kicker: 'Grupos de projeto',
              title: title,
              subtitle: discipline,
              details: [
                if (classLabel.isNotEmpty) 'Turma $classLabel',
                if (semester.isNotEmpty) 'Semestre $semester',
                '${groups.length} grupo${groups.length == 1 ? "" : "s"}',
                '$students aluno${students == 1 ? "" : "s"}',
                if (generatedAt != null) formatDate(generatedAt),
              ],
              brandMark: brandMark,
            )
          : _runningHeader(running, brandMark),
      footer: pdfFooter,
      build: (context) => [
        pw.SizedBox(height: 10),
        if (groups.isEmpty)
          pw.Text(
            'Esta disciplina não tem grupos cadastrados.',
            style: const pw.TextStyle(fontSize: 11, color: pdfInkSoft),
          ),
        for (final group in groups) _groupBlock(group, showEnrollment),
      ],
    ),
  );
  return document.save();
}

pw.Widget _groupBlock(GroupListGroup group, bool showEnrollment) {
  return pw.Container(
    margin: const pw.EdgeInsets.only(bottom: 12),
    child: pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.Container(
          width: double.infinity,
          padding: const pw.EdgeInsets.symmetric(horizontal: 8, vertical: 5),
          decoration: const pw.BoxDecoration(
            color: pdfPanel,
            border: pw.Border(left: pw.BorderSide(color: pdfAccent, width: 3)),
          ),
          child: pw.Row(
            children: [
              pw.Text(
                group.name.isEmpty ? 'Grupo' : group.name,
                style: pw.TextStyle(
                  fontSize: 11,
                  color: pdfInk,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              if (group.projectTitle.isNotEmpty) ...[
                pw.SizedBox(width: 8),
                pw.Expanded(
                  child: pw.Text(
                    group.projectTitle,
                    style: const pw.TextStyle(fontSize: 9, color: pdfInkSoft),
                  ),
                ),
              ] else
                pw.Spacer(),
              pw.Text(
                '${group.members.length} integrante${group.members.length == 1 ? "" : "s"}',
                style: const pw.TextStyle(fontSize: 8.5, color: pdfInkSoft),
              ),
            ],
          ),
        ),
        pw.Table(
          columnWidths: {
            0: const pw.FixedColumnWidth(24),
            1: const pw.FlexColumnWidth(2.4),
            if (showEnrollment) 2: const pw.FlexColumnWidth(1.2),
          },
          border: const pw.TableBorder(
            horizontalInside: pw.BorderSide(color: pdfRule, width: 0.5),
            bottom: pw.BorderSide(color: pdfRule, width: 0.5),
          ),
          children: [
            for (var i = 0; i < group.members.length; i++)
              pw.TableRow(children: [
                _cell('${i + 1}', color: pdfInkSoft),
                _cell(group.members[i].name),
                if (showEnrollment)
                  _cell(
                    group.members[i].enrollment.isEmpty
                        ? '—'
                        : group.members[i].enrollment,
                    color: group.members[i].enrollment.isEmpty
                        ? pdfInkSoft
                        : pdfInk,
                  ),
              ]),
            if (group.members.isEmpty)
              pw.TableRow(children: [
                _cell(''),
                _cell('Sem integrantes cadastrados.', color: pdfInkSoft),
                if (showEnrollment) _cell(''),
              ]),
          ],
        ),
      ],
    ),
  );
}

PdfColor _statusColor(String status) {
  switch (status) {
    case GroupDrawEntry.statusDone:
      return pdfGood;
    case GroupDrawEntry.statusAbsent:
      return pdfBad;
    case GroupDrawEntry.statusPresenting:
      return pdfAccentDark;
    default:
      return pdfInkSoft;
  }
}

/// Ordem de apresentação sorteada.
Future<Uint8List> buildGroupDrawPdf({
  required GroupDraw draw,
  DateTime? generatedAt,
}) async {
  const title = 'Ordem de apresentação';
  final document = _document(title);
  final brandMark = await IntarqBrand.loadPdfMark();
  final theme = await pdfTheme();
  final days = draw.byDay;
  final pending = draw.notDrawn;
  final running = [draw.discipline, title].where((part) => part.isNotEmpty).join('   |   ');

  document.addPage(
    pw.MultiPage(
      pageTheme: _pageTheme(theme),
      header: (context) => context.pageNumber == 1
          ? pdfBanner(
              kicker: title,
              title: draw.title.isEmpty ? title : draw.title,
              subtitle: draw.discipline,
              details: [
                if (draw.classLabel.isNotEmpty) 'Turma ${draw.classLabel}',
                if (draw.semester.isNotEmpty) 'Semestre ${draw.semester}',
                '${draw.total} grupo${draw.total == 1 ? "" : "s"}',
                if (draw.perDay != null) '${draw.perDay} por dia',
                draw.oneByOne ? 'Sorteio um grupo por vez' : 'Ordem completa',
                if (generatedAt != null) formatDate(generatedAt),
              ],
              brandMark: brandMark,
            )
          : _runningHeader(running, brandMark),
      footer: pdfFooter,
      build: (context) => [
        pw.SizedBox(height: 10),
        if (days.isEmpty)
          pw.Text(
            'Nenhum grupo foi sorteado ainda.',
            style: const pw.TextStyle(fontSize: 11, color: pdfInkSoft),
          ),
        for (final day in days.entries) ...[
          if (days.length > 1 || draw.perDay != null)
            pdfSectionTitle('Dia ${day.key}'),
          _drawTable(day.value),
        ],
        if (pending.isNotEmpty) ...[
          pdfSectionTitle('Ainda não sorteados'),
          pw.Text(
            pending.map((entry) => entry.groupName).join(', '),
            style: const pw.TextStyle(fontSize: 10, color: pdfInkSoft),
          ),
        ],
        pw.SizedBox(height: 18),
        _proof(draw),
      ],
    ),
  );
  return document.save();
}

pw.Widget _drawTable(List<GroupDrawEntry> entries) {
  return pw.Table(
    columnWidths: {
      0: const pw.FixedColumnWidth(48),
      1: const pw.FlexColumnWidth(2.2),
      2: const pw.FlexColumnWidth(2.2),
      3: const pw.FlexColumnWidth(1.2),
    },
    border: const pw.TableBorder(
      horizontalInside: pw.BorderSide(color: pdfRule, width: 0.5),
      bottom: pw.BorderSide(color: pdfRule, width: 0.5),
    ),
    children: [
      pw.TableRow(
        decoration: const pw.BoxDecoration(color: pdfHeader),
        children: [
          _cell('ORDEM', header: true),
          _cell('GRUPO', header: true),
          _cell('REPRESENTANTE', header: true),
          _cell('SITUAÇÃO', header: true),
        ],
      ),
      for (final entry in entries)
        pw.TableRow(children: [
          _cell('${entry.position}º', bold: true),
          _cell(entry.groupName),
          _cell(entry.hasRepresentative ? entry.representativeName : '—',
              color: entry.hasRepresentative ? pdfInk : pdfInkSoft),
          _cell(
            GroupDrawEntry.labelOf(entry.status),
            color: _statusColor(entry.status),
            bold: entry.status != GroupDrawEntry.statusPending,
          ),
        ]),
    ],
  );
}

/// Como conferir o sorteio: a semente e a regra. Quem a tiver refaz a conta.
pw.Widget _proof(GroupDraw draw) => pw.Container(
      width: double.infinity,
      padding: const pw.EdgeInsets.all(8),
      decoration: const pw.BoxDecoration(
        color: pdfPanel,
        border: pw.Border(left: pw.BorderSide(color: pdfRule, width: 3)),
      ),
      child: pw.Column(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          pw.Text(
            draw.verified ? 'Sorteio verificável' : 'ATENÇÃO: a ordem não confere com a semente',
            style: pw.TextStyle(
              fontSize: 9,
              fontWeight: pw.FontWeight.bold,
              color: draw.verified ? pdfInk : pdfBad,
            ),
          ),
          pw.SizedBox(height: 3),
          pw.Text(
            'Semente ${draw.seed} · regra ${draw.algorithm}. A cada passo vence o '
            'grupo de menor SHA-256 de "semente:passo:id do grupo"; quem tiver a '
            'semente e a lista de grupos refaz a conta e chega na mesma ordem.',
            style: const pw.TextStyle(fontSize: 8, color: pdfInkSoft),
          ),
        ],
      ),
    );

/// Inscrição em mentorias: o formulário, os campos que a IA monta e quem se inscreveu.
///
/// Matrícula, nome, e-mail e telefone são sempre pedidos pela página pública e não
/// aparecem em [MentorshipField]; os campos daqui são o resto (idade, curso, horários
/// livres...), que a IA propõe e o professor ajusta antes de publicar.
library;

/// Tipos de campo que a página pública sabe desenhar.
const mentorshipFieldTypes = <String, String>{
  'text': 'Texto curto',
  'textarea': 'Texto longo',
  'number': 'Número',
  'select': 'Escolha uma opção',
  'availability': 'Horários livres',
};

class MentorshipField {
  String id;
  String label;
  String type;
  bool required;
  List<String> options;

  MentorshipField({
    this.id = '',
    required this.label,
    this.type = 'text',
    this.required = false,
    List<String>? options,
  }) : options = options ?? [];

  factory MentorshipField.fromJson(Map<String, dynamic> json) => MentorshipField(
        id: json['id']?.toString() ?? '',
        label: json['label']?.toString() ?? '',
        type: json['type']?.toString() ?? 'text',
        required: json['required'] == true,
        options: [for (final o in (json['options'] as List? ?? const [])) '$o'],
      );

  Map<String, dynamic> toJson() => {
        if (id.isNotEmpty) 'id': id,
        'label': label,
        'type': type,
        'required': required,
        'options': options,
      };
}

class MentorshipForm {
  final String id;
  final String path;
  final String title;
  final String description;
  final String semester;
  final List<MentorshipField> fields;
  final bool active;

  /// `open`, `closed`, `expired` ou `full`.
  final String state;
  final DateTime? closesAt;
  final int? maxSlots;
  final int signups;
  final int pending;
  final int accepted;
  final String? classId;

  const MentorshipForm({
    required this.id,
    required this.path,
    required this.title,
    this.description = '',
    this.semester = '',
    this.fields = const [],
    this.active = true,
    this.state = 'open',
    this.closesAt,
    this.maxSlots,
    this.signups = 0,
    this.pending = 0,
    this.accepted = 0,
    this.classId,
  });

  factory MentorshipForm.fromJson(Map<String, dynamic> json) => MentorshipForm(
        id: '${json['id']}',
        path: json['path']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        description: json['description']?.toString() ?? '',
        semester: json['semester']?.toString() ?? '',
        fields: [
          for (final f in (json['fields'] as List? ?? const []))
            MentorshipField.fromJson(Map<String, dynamic>.from(f as Map)),
        ],
        active: json['active'] != false,
        state: json['state']?.toString() ?? 'open',
        closesAt: DateTime.tryParse(json['closes_at']?.toString() ?? ''),
        maxSlots: (json['max_slots'] as num?)?.toInt(),
        signups: (json['signups'] as num?)?.toInt() ?? 0,
        pending: (json['pending'] as num?)?.toInt() ?? 0,
        accepted: (json['accepted'] as num?)?.toInt() ?? 0,
        classId: json['class_id']?.toString(),
      );

  String url(String baseUrl) =>
      '${baseUrl.replaceAll(RegExp(r'/+$'), '')}$path';

  bool get isOpen => state == 'open';

  String get stateLabel => switch (state) {
        'closed' => 'FECHADO',
        'expired' => 'PRAZO ENCERRADO',
        'full' => 'VAGAS ESGOTADAS',
        _ => 'ABERTO',
      };

  /// "12 inscritos · 8 vagas" (só o primeiro quando não há limite).
  String get summary {
    final slots = maxSlots == null ? '' : ' · $maxSlots vagas';
    return '$signups inscritos$slots';
  }
}

class MentorshipSignup {
  final String id;
  final String enrollment;
  final String name;
  final String email;
  final String phone;
  final Map<String, dynamic> answers;

  /// A matrícula casa com um aluno cadastrado neste semestre.
  final bool knownStudent;

  /// `pending`, `accepted`, `rejected` ou `removed`.
  final String status;
  final DateTime? createdAt;

  const MentorshipSignup({
    required this.id,
    required this.enrollment,
    required this.name,
    this.email = '',
    this.phone = '',
    this.answers = const {},
    this.knownStudent = false,
    this.status = 'pending',
    this.createdAt,
  });

  factory MentorshipSignup.fromJson(Map<String, dynamic> json) => MentorshipSignup(
        id: '${json['id']}',
        enrollment: json['enrollment']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        email: json['email']?.toString() ?? '',
        phone: json['phone']?.toString() ?? '',
        answers: Map<String, dynamic>.from(json['answers'] as Map? ?? const {}),
        knownStudent: json['known_student'] == true,
        status: json['status']?.toString() ?? 'pending',
        createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
      );

  String get statusLabel => switch (status) {
        'accepted' => 'ACEITO',
        'rejected' => 'RECUSADO',
        'removed' => 'REMOVIDO',
        _ => 'PENDENTE',
      };
}

const _days = {
  'seg': 'Seg', 'ter': 'Ter', 'qua': 'Qua', 'qui': 'Qui',
  'sex': 'Sex', 'sab': 'Sáb', 'dom': 'Dom',
};
const _shifts = {'manha': 'manhã', 'tarde': 'tarde', 'noite': 'noite'};

/// "Sáb manhã, Seg noite" a partir dos valores `sab-manha` guardados.
String availabilityText(Object? value) {
  final parts = <String>[];
  for (final item in (value as List? ?? const [])) {
    final bits = '$item'.split('-');
    if (bits.length != 2) continue;
    parts.add('${_days[bits[0]] ?? bits[0]} ${_shifts[bits[1]] ?? bits[1]}');
  }
  return parts.join(', ');
}

/// Atividade que os aceitos entregam pelo link de entrega.
class MentorshipActivity {
  final String id;
  final String title;
  final String instructions;
  final DateTime? dueAt;
  final bool remind;

  /// Quantos aceitos já entregaram, de quantos aceitos há.
  final int delivered;
  final int expected;

  const MentorshipActivity({
    required this.id,
    required this.title,
    this.instructions = '',
    this.dueAt,
    this.remind = true,
    this.delivered = 0,
    this.expected = 0,
  });

  factory MentorshipActivity.fromJson(Map<String, dynamic> json) => MentorshipActivity(
        id: '${json['id']}',
        title: json['title']?.toString() ?? '',
        instructions: json['instructions']?.toString() ?? '',
        dueAt: _utc(json['due_at']),
        remind: json['remind'] != false,
        delivered: (json['delivered'] as num?)?.toInt() ?? 0,
        expected: (json['expected'] as num?)?.toInt() ?? 0,
      );

  bool get overdue => dueAt != null && dueAt!.isBefore(DateTime.now());
}

/// O servidor guarda UTC sem fuso: sem o "Z" o Dart leria como hora local.
DateTime? _utc(Object? value) {
  final text = value?.toString() ?? '';
  if (text.isEmpty) return null;
  final hasZone = RegExp(r'(Z|[+-]\d\d:?\d\d)$').hasMatch(text);
  return DateTime.tryParse(hasZone ? text : '${text}Z')?.toLocal();
}

/// Situação de um aluno em uma atividade: `delivered`, `late`, `overdue` ou `pending`.
class DeliveryCell {
  final String activityId;
  final String status;
  final String? deliveryId;
  final DateTime? deliveredAt;
  final String filename;
  final String textPreview;

  const DeliveryCell({
    required this.activityId,
    required this.status,
    this.deliveryId,
    this.deliveredAt,
    this.filename = '',
    this.textPreview = '',
  });

  factory DeliveryCell.fromJson(Map<String, dynamic> json) => DeliveryCell(
        activityId: '${json['activity_id']}',
        status: json['status']?.toString() ?? 'pending',
        deliveryId: json['delivery_id']?.toString(),
        deliveredAt: _utc(json['delivered_at']),
        filename: json['filename']?.toString() ?? '',
        textPreview: json['text_preview']?.toString() ?? '',
      );

  bool get hasDelivery => deliveryId != null;
}

class DeliveryRow {
  final String signupId;
  final String name;
  final String enrollment;
  final List<DeliveryCell> cells;

  const DeliveryRow({
    required this.signupId,
    required this.name,
    required this.enrollment,
    this.cells = const [],
  });

  factory DeliveryRow.fromJson(Map<String, dynamic> json) => DeliveryRow(
        signupId: '${json['signup_id']}',
        name: json['name']?.toString() ?? '',
        enrollment: json['enrollment']?.toString() ?? '',
        cells: [
          for (final c in (json['cells'] as List? ?? const []))
            DeliveryCell.fromJson(Map<String, dynamic>.from(c as Map)),
        ],
      );
}

/// Aceito que deixou de entregar as últimas atividades vencidas.
class AtRiskStudent {
  final String signupId;
  final String name;
  final String enrollment;
  final int misses;

  const AtRiskStudent({
    required this.signupId,
    required this.name,
    required this.enrollment,
    required this.misses,
  });

  factory AtRiskStudent.fromJson(Map<String, dynamic> json) => AtRiskStudent(
        signupId: '${json['signup_id']}',
        name: json['name']?.toString() ?? '',
        enrollment: json['enrollment']?.toString() ?? '',
        misses: (json['misses'] as num?)?.toInt() ?? 0,
      );
}

class DeliveryDetail {
  final String id;
  final String text;
  final String filename;
  final int fileSize;
  final bool late;
  final DateTime? deliveredAt;

  const DeliveryDetail({
    required this.id,
    this.text = '',
    this.filename = '',
    this.fileSize = 0,
    this.late = false,
    this.deliveredAt,
  });

  factory DeliveryDetail.fromJson(Map<String, dynamic> json) => DeliveryDetail(
        id: '${json['id']}',
        text: json['text']?.toString() ?? '',
        filename: json['filename']?.toString() ?? '',
        fileSize: (json['file_size'] as num?)?.toInt() ?? 0,
        late: json['late'] == true,
        deliveredAt: _utc(json['delivered_at']),
      );

  bool get hasFile => filename.isNotEmpty;
}

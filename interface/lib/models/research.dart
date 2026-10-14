/// Pesquisas científicas: o projeto, as etapas do plano e quem participa.
library;

/// O servidor guarda UTC sem fuso: sem o "Z" o Dart leria como hora local.
DateTime? parseServerUtc(Object? value) {
  final text = value?.toString() ?? '';
  if (text.isEmpty) return null;
  final hasZone = RegExp(r'(Z|[+-]\d\d:?\d\d)$').hasMatch(text);
  return DateTime.tryParse(hasZone ? text : '${text}Z')?.toLocal();
}

const researchStatuses = <String, String>{
  'planning': 'Planejamento',
  'active': 'Em andamento',
  'paused': 'Pausada',
  'done': 'Concluída',
};

const researchRoles = <String, String>{
  'orientando': 'Orientando',
  'coorientador': 'Coorientador',
  'colaborador': 'Colaborador',
};

/// Etapa do plano, ainda sem ser gravada (vinda da IA ou digitada na criação).
class StageDraft {
  String title;
  String description;
  DateTime? dueAt;

  StageDraft({required this.title, this.description = '', this.dueAt});

  factory StageDraft.fromJson(Map<String, dynamic> json) => StageDraft(
        title: json['title']?.toString() ?? '',
        description: json['description']?.toString() ?? '',
        dueAt: parseServerUtc(json['due_at']),
      );

  Map<String, dynamic> toJson() => {
        'title': title,
        'description': description,
        if (dueAt != null) 'due_at': dueAt!.toUtc().toIso8601String(),
      };
}

class ResearchStage {
  final String id;
  final String title;
  final String description;
  final DateTime? dueAt;

  /// `todo`, `doing` ou `done`.
  final String status;

  /// Como a tela pinta: `done`, `doing`, `overdue` (prazo passou) ou `todo`.
  final String state;

  const ResearchStage({
    required this.id,
    required this.title,
    this.description = '',
    this.dueAt,
    this.status = 'todo',
    this.state = 'todo',
  });

  factory ResearchStage.fromJson(Map<String, dynamic> json) => ResearchStage(
        id: '${json['id']}',
        title: json['title']?.toString() ?? '',
        description: json['description']?.toString() ?? '',
        dueAt: parseServerUtc(json['due_at']),
        status: json['status']?.toString() ?? 'todo',
        state: json['state']?.toString() ?? 'todo',
      );

  bool get isDone => status == 'done';
}

class ResearchParticipant {
  final String id;
  final String name;
  final String email;
  final String phone;
  final String enrollment;
  final String institution;
  final String role;

  /// A matrícula casa com um aluno cadastrado.
  final bool knownStudent;

  const ResearchParticipant({
    required this.id,
    required this.name,
    this.email = '',
    this.phone = '',
    this.enrollment = '',
    this.institution = '',
    this.role = 'orientando',
    this.knownStudent = false,
  });

  factory ResearchParticipant.fromJson(Map<String, dynamic> json) => ResearchParticipant(
        id: '${json['id']}',
        name: json['name']?.toString() ?? '',
        email: json['email']?.toString() ?? '',
        phone: json['phone']?.toString() ?? '',
        enrollment: json['enrollment']?.toString() ?? '',
        institution: json['institution']?.toString() ?? '',
        role: json['role']?.toString() ?? 'orientando',
        knownStudent: json['known_student'] == true,
      );

  String get roleLabel => researchRoles[role] ?? role;
}

class ResearchProject {
  final String id;
  final String title;
  final String description;
  final String area;
  final String semester;

  /// `planning`, `active`, `paused` ou `done`.
  final String status;
  final DateTime? startDate;
  final DateTime? endDate;

  final int stages;
  final int done;
  final int overdue;
  final int progress;
  final int participants;
  final DateTime? nextDue;
  final String nextTitle;

  const ResearchProject({
    required this.id,
    required this.title,
    this.description = '',
    this.area = '',
    this.semester = '',
    this.status = 'planning',
    this.startDate,
    this.endDate,
    this.stages = 0,
    this.done = 0,
    this.overdue = 0,
    this.progress = 0,
    this.participants = 0,
    this.nextDue,
    this.nextTitle = '',
  });

  factory ResearchProject.fromJson(Map<String, dynamic> json) => ResearchProject(
        id: '${json['id']}',
        title: json['title']?.toString() ?? '',
        description: json['description']?.toString() ?? '',
        area: json['area']?.toString() ?? '',
        semester: json['semester']?.toString() ?? '',
        status: json['status']?.toString() ?? 'planning',
        startDate: parseServerUtc(json['start_date']),
        endDate: parseServerUtc(json['end_date']),
        stages: (json['stages'] as num?)?.toInt() ?? 0,
        done: (json['done'] as num?)?.toInt() ?? 0,
        overdue: (json['overdue'] as num?)?.toInt() ?? 0,
        progress: (json['progress'] as num?)?.toInt() ?? 0,
        participants: (json['participants'] as num?)?.toInt() ?? 0,
        nextDue: parseServerUtc(json['next_due']),
        nextTitle: json['next_title']?.toString() ?? '',
      );

  String get statusLabel => researchStatuses[status] ?? status;
}

class ResearchDetail {
  final ResearchProject project;
  final List<ResearchStage> stages;
  final List<ResearchParticipant> participants;

  const ResearchDetail({
    required this.project,
    this.stages = const [],
    this.participants = const [],
  });

  factory ResearchDetail.fromJson(Map<String, dynamic> json) => ResearchDetail(
        project: ResearchProject.fromJson(Map<String, dynamic>.from(json['project'] as Map)),
        stages: [
          for (final s in (json['stages'] as List? ?? const []))
            ResearchStage.fromJson(Map<String, dynamic>.from(s as Map)),
        ],
        participants: [
          for (final p in (json['participants'] as List? ?? const []))
            ResearchParticipant.fromJson(Map<String, dynamic>.from(p as Map)),
        ],
      );
}

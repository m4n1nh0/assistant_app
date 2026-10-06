/// Material das apresentações enviado pelos alunos e a gravação de cada grupo.
///
/// O professor cria um link público (um por disciplina, ou por turmas); o aluno
/// entra com a matrícula e envia o PDF/PPTX do grupo. O painel junta, por grupo, o
/// que chegou e o que foi gravado, e diz o que falta para o quiz rápido.
library;

DateTime? _date(Object? value) => DateTime.tryParse('$value');

List<String> _strings(Object? value) => [
      for (final item in (value as List?) ?? const [])
        if ('$item'.isNotEmpty) '$item',
    ];

/// Link de envio de material criado pelo professor.
class MaterialLink {
  final String id;
  final String token;

  /// Caminho público (`/education/material-submit/<token>`); o endereço do servidor
  /// vem do app, por isso a URL completa é montada por [url].
  final String path;
  final String title;
  final String disciplineId;
  final String discipline;
  final List<String> classIds;
  final String classLabel;

  /// `open`, `closed` (o professor fechou) ou `expired` (o prazo passou).
  final String state;
  final DateTime? closesAt;
  final int maxFilesPerGroup;
  final int filesReceived;
  final int groupsSent;
  final int groupsTotal;
  final DateTime? createdAt;

  const MaterialLink({
    required this.id,
    required this.token,
    required this.path,
    this.title = '',
    this.disciplineId = '',
    this.discipline = '',
    this.classIds = const [],
    this.classLabel = '',
    this.state = 'open',
    this.closesAt,
    this.maxFilesPerGroup = 5,
    this.filesReceived = 0,
    this.groupsSent = 0,
    this.groupsTotal = 0,
    this.createdAt,
  });

  factory MaterialLink.fromJson(Map<String, dynamic> json) => MaterialLink(
        id: '${json['id']}',
        token: '${json['token']}',
        path: '${json['path']}',
        title: json['title']?.toString() ?? '',
        disciplineId: json['discipline_id']?.toString() ?? '',
        discipline: json['discipline']?.toString() ?? '',
        classIds: _strings(json['class_ids']),
        classLabel: json['class_label']?.toString() ?? '',
        state: json['state']?.toString() ?? 'open',
        closesAt: _date(json['closes_at']),
        maxFilesPerGroup: (json['max_files_per_group'] as num?)?.toInt() ?? 5,
        filesReceived: (json['files_received'] as num?)?.toInt() ?? 0,
        groupsSent: (json['groups_sent'] as num?)?.toInt() ?? 0,
        groupsTotal: (json['groups_total'] as num?)?.toInt() ?? 0,
        createdAt: _date(json['created_at']),
      );

  bool get isOpen => state == 'open';

  /// Endereço que o aluno abre, no servidor [baseUrl] do app.
  String url(String baseUrl) {
    final base = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    return '$base$path';
  }

  String get stateLabel {
    switch (state) {
      case 'closed':
        return 'Fechado';
      case 'expired':
        return 'Prazo encerrado';
      default:
        return 'Aberto';
    }
  }

  String get progressLabel =>
      '$groupsSent de $groupsTotal grupos enviaram · $filesReceived arquivo(s)';
}

/// Endereço do servidor que só funciona neste computador: o aluno não abre o link.
bool isLocalAddress(String baseUrl) {
  final host = Uri.tryParse(baseUrl)?.host.toLowerCase() ?? '';
  if (host.isEmpty) return false;
  if (host == 'localhost' || host == '::1' || host.endsWith('.local')) return true;
  final parts = host.split('.').map(int.tryParse).toList();
  if (parts.length != 4 || parts.any((part) => part == null)) return false;
  final a = parts[0]!, b = parts[1]!;
  return a == 127 ||
      a == 10 ||
      (a == 192 && b == 168) ||
      (a == 172 && b >= 16 && b <= 31);
}

/// Arquivo que um grupo mandou (ou que o professor ligou ao grupo).
class PresentationFile {
  final String id;
  final String title;
  final String filename;
  final String sourceType;
  final int pageCount;
  final int charCount;
  final bool truncated;
  final String uploaderName;
  final bool fromLink;
  final DateTime? createdAt;

  const PresentationFile({
    required this.id,
    required this.title,
    this.filename = '',
    this.sourceType = 'pdf',
    this.pageCount = 0,
    this.charCount = 0,
    this.truncated = false,
    this.uploaderName = '',
    this.fromLink = false,
    this.createdAt,
  });

  factory PresentationFile.fromJson(Map<String, dynamic> json) =>
      PresentationFile(
        id: '${json['id']}',
        title: json['title']?.toString() ?? '',
        filename: json['filename']?.toString() ?? '',
        sourceType: json['source_type']?.toString() ?? 'pdf',
        pageCount: (json['page_count'] as num?)?.toInt() ?? 0,
        charCount: (json['char_count'] as num?)?.toInt() ?? 0,
        truncated: json['truncated'] == true,
        uploaderName: json['uploader_name']?.toString() ?? '',
        fromLink: json['from_link'] == true,
        createdAt: _date(json['created_at']),
      );

  /// "12 slides", "8 páginas"; sem contagem, só o formato.
  String get sizeLabel {
    final unit = switch (sourceType) {
      'pptx' => pageCount == 1 ? 'slide' : 'slides',
      'pdf' || 'pdf-ocr' => pageCount == 1 ? 'página' : 'páginas',
      _ => '',
    };
    if (pageCount > 0 && unit.isNotEmpty) return '$pageCount $unit';
    return sourceType.toUpperCase();
  }
}

/// Gravação da apresentação de um grupo.
class PresentationRecording {
  final String id;
  final String title;
  final String status;
  final DateTime? startedAt;
  final int segments;
  final bool hasSummary;

  const PresentationRecording({
    required this.id,
    this.title = '',
    this.status = '',
    this.startedAt,
    this.segments = 0,
    this.hasSummary = false,
  });

  factory PresentationRecording.fromJson(Map<String, dynamic> json) =>
      PresentationRecording(
        id: '${json['id']}',
        title: json['title']?.toString() ?? '',
        status: json['status']?.toString() ?? '',
        startedAt: _date(json['started_at']),
        segments: (json['segments'] as num?)?.toInt() ?? 0,
        hasSummary: json['has_summary'] == true,
      );

  /// Só conta como fonte de quiz se tem texto transcrito.
  bool get usable => segments > 0;
}

/// Um grupo com o material enviado e as gravações da apresentação dele.
class PresentationRow {
  final String groupId;
  final String groupName;
  final List<String> classIds;
  final List<PresentationFile> materials;
  final List<PresentationRecording> recordings;

  /// O que falta para o quiz rápido: `material` e/ou `gravação`.
  final List<String> gaps;

  const PresentationRow({
    required this.groupId,
    required this.groupName,
    this.classIds = const [],
    this.materials = const [],
    this.recordings = const [],
    this.gaps = const [],
  });

  factory PresentationRow.fromJson(Map<String, dynamic> json) => PresentationRow(
        groupId: '${json['group_id']}',
        groupName: json['group_name']?.toString() ?? '',
        classIds: _strings(json['class_ids']),
        materials: [
          for (final item in (json['materials'] as List?) ?? const [])
            PresentationFile.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
        recordings: [
          for (final item in (json['recordings'] as List?) ?? const [])
            PresentationRecording.fromJson(
                Map<String, dynamic>.from(item as Map)),
        ],
        gaps: _strings(json['gaps']),
      );

  bool get hasMaterial => materials.isNotEmpty;
  bool get hasRecording => recordings.any((item) => item.usable);

  /// Dá para montar o quiz rápido com pelo menos uma fonte.
  bool get canQuiz => hasMaterial || hasRecording;

  /// Resumo curto para a lista: "2 arquivos · 1 gravação", "sem nada ainda".
  String get statusLabel {
    final parts = [
      if (materials.isNotEmpty)
        '${materials.length} arquivo${materials.length == 1 ? '' : 's'}',
      if (recordings.isNotEmpty)
        '${recordings.length} gravaç${recordings.length == 1 ? 'ão' : 'ões'}',
    ];
    return parts.isEmpty ? 'nada recebido ainda' : parts.join(' · ');
  }
}

/// Quais fontes o professor marcou para o quiz rápido.
class QuickQuizSources {
  final Set<String> materialIds;
  final Set<String> lessonIds;

  const QuickQuizSources({
    this.materialIds = const {},
    this.lessonIds = const {},
  });

  bool get isEmpty => materialIds.isEmpty && lessonIds.isEmpty;
}

/// Pedido de quiz rápido de uma apresentação, no formato do servidor.
///
/// O grupo que apresentou fica de fora (não responde ao quiz sobre o próprio
/// trabalho), e os outros grupos das mesmas turmas jogam. O servidor devolve o
/// quiz já em grupo quando a geração termina.
Map<String, dynamic> buildQuickQuizRequest({
  required PresentationRow group,
  required String disciplineId,
  required QuickQuizSources sources,
  int questions = 8,
  String mode = 'media',
  List<String>? classIds,
}) {
  return {
    'material_ids': sources.materialIds.toList()..sort(),
    'lesson_ids': sources.lessonIds.toList()..sort(),
    'tipo_quiz': 'pratica',
    'quantidade_questoes': questions,
    'tipos_questao': ['multipla_escolha'],
    'titulo': 'Quiz rápido: ${group.groupName}',
    'group_setup': {
      'mode': mode,
      'discipline_id': disciplineId,
      'class_ids': classIds ?? group.classIds,
      'exclude_group_ids': [group.groupId],
    },
  };
}

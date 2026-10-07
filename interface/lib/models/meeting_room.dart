/// Reunião online própria: a sala, quem está nela e a fala transcrita ao vivo.
///
/// Vídeo e áudio passam por um servidor de mídia e **não são gravados**; só a fala é
/// transcrita, com o nome de quem falou, e vira trechos de uma gravação do tipo
/// reunião. Aqui ficam os modelos que a tela do professor lê.
library;

DateTime? _date(Object? value) => DateTime.tryParse('$value');

/// O servidor de vídeo está configurado? Sem ele a sala não abre.
class MeetingConfig {
  final bool configured;
  final String mediaHost;
  final int defaultMaxParticipants;

  /// Variáveis de ambiente que faltam (`LIVEKIT_URL`, `LIVEKIT_API_KEY`...).
  final List<String> missing;

  const MeetingConfig({
    this.configured = false,
    this.mediaHost = '',
    this.defaultMaxParticipants = 30,
    this.missing = const [],
  });

  factory MeetingConfig.fromJson(Map<String, dynamic> json) => MeetingConfig(
        configured: json['configured'] == true,
        mediaHost: json['media_host']?.toString() ?? '',
        defaultMaxParticipants:
            (json['default_max_participants'] as num?)?.toInt() ?? 30,
        missing: [
          for (final item in (json['missing'] as List?) ?? const []) '$item',
        ],
      );
}

class MeetingRoom {
  final String id;
  final String title;

  /// `open` ou `ended`.
  final String status;
  final String joinPath;
  final String hostPath;
  final bool guestsAllowed;
  final int maxParticipants;
  final String lessonId;
  final DateTime? createdAt;
  final DateTime? endedAt;
  final int online;
  final int people;
  final int segments;

  const MeetingRoom({
    required this.id,
    required this.title,
    this.status = 'open',
    this.joinPath = '',
    this.hostPath = '',
    this.guestsAllowed = true,
    this.maxParticipants = 30,
    this.lessonId = '',
    this.createdAt,
    this.endedAt,
    this.online = 0,
    this.people = 0,
    this.segments = 0,
  });

  factory MeetingRoom.fromJson(Map<String, dynamic> json) => MeetingRoom(
        id: '${json['id']}',
        title: json['title']?.toString() ?? '',
        status: json['status']?.toString() ?? 'open',
        joinPath: json['join_path']?.toString() ?? '',
        hostPath: json['host_path']?.toString() ?? '',
        guestsAllowed: json['guests_allowed'] != false,
        maxParticipants: (json['max_participants'] as num?)?.toInt() ?? 30,
        lessonId: json['lesson_id']?.toString() ?? '',
        createdAt: _date(json['created_at']),
        endedAt: _date(json['ended_at']),
        online: (json['online'] as num?)?.toInt() ?? 0,
        people: (json['people'] as num?)?.toInt() ?? 0,
        segments: (json['segments'] as num?)?.toInt() ?? 0,
      );

  bool get isOpen => status == 'open';

  String _join(String baseUrl, String path) {
    final base = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    return '$base$path';
  }

  /// O link que se manda para a turma.
  String joinUrl(String baseUrl) => _join(baseUrl, joinPath);

  /// O link do professor: leva a chave que dá o direito de encerrar para todos. A chave
  /// vai depois do `#`, que o navegador nunca envia ao servidor.
  String hostUrl(String baseUrl) => _join(baseUrl, hostPath);
}

/// Alguém que está (ou esteve) na sala.
class MeetingParticipant {
  final String name;
  final String studentId;
  final bool isHost;

  /// Entrou sem matrícula (não é aluno do cadastro).
  final bool guest;
  final bool online;
  final int seconds;

  /// Quantas falas dele já foram transcritas.
  final int chunks;
  final DateTime? firstJoined;

  const MeetingParticipant({
    required this.name,
    this.studentId = '',
    this.isHost = false,
    this.guest = false,
    this.online = false,
    this.seconds = 0,
    this.chunks = 0,
    this.firstJoined,
  });

  factory MeetingParticipant.fromJson(Map<String, dynamic> json) =>
      MeetingParticipant(
        name: json['name']?.toString() ?? '',
        studentId: json['student_id']?.toString() ?? '',
        isHost: json['is_host'] == true,
        guest: json['guest'] == true,
        online: json['online'] == true,
        seconds: (json['seconds'] as num?)?.toInt() ?? 0,
        chunks: (json['chunks'] as num?)?.toInt() ?? 0,
        firstJoined: _date(json['first_joined']),
      );

  /// "Professor", "Aluno" (matrícula) ou "Convidado".
  String get roleLabel => isHost ? 'Professor' : (guest ? 'Convidado' : 'Aluno');
}

/// Uma fala transcrita: "Nome: texto".
class MeetingLine {
  final String id;
  final int sequence;
  final String text;

  const MeetingLine({required this.id, required this.sequence, required this.text});

  factory MeetingLine.fromJson(Map<String, dynamic> json) => MeetingLine(
        id: '${json['id']}',
        sequence: (json['sequence'] as num?)?.toInt() ?? 0,
        text: json['text']?.toString() ?? '',
      );

  /// Quem falou, ou vazio quando o texto não traz o nome.
  String get speaker => _split().$1;

  /// O que foi dito, sem o nome na frente.
  String get said => _split().$2;

  (String, String) _split() {
    final index = text.indexOf(': ');
    if (index <= 0 || index > 80) return ('', text);
    return (text.substring(0, index), text.substring(index + 2));
  }
}

/// A sala com a presença e o fim da transcrição, como a tela ao vivo precisa.
class MeetingDetail {
  final MeetingRoom room;
  final List<MeetingParticipant> participants;
  final List<MeetingLine> transcript;

  const MeetingDetail({
    required this.room,
    this.participants = const [],
    this.transcript = const [],
  });

  factory MeetingDetail.fromJson(Map<String, dynamic> json) => MeetingDetail(
        room: MeetingRoom.fromJson(json),
        participants: [
          for (final item in (json['participants'] as List?) ?? const [])
            MeetingParticipant.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
        transcript: [
          for (final item in (json['transcript'] as List?) ?? const [])
            MeetingLine.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
      );
}

/// "1 h 05 min", "12 min", "45 s": o tempo que cada um ficou na sala.
String formatMeetingDuration(int seconds) {
  if (seconds < 60) return '$seconds s';
  final minutes = seconds ~/ 60;
  if (minutes < 60) return '$minutes min';
  final hours = minutes ~/ 60;
  final rest = (minutes % 60).toString().padLeft(2, '0');
  return '$hours h $rest min';
}

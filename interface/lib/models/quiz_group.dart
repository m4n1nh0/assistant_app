/// Quiz em grupo, como o professor o enxerga: modo, grupos, representantes e ranking.
///
/// O servidor decide tudo (quem pode entrar, quem representa, quanto o grupo vale);
/// aqui fica a leitura da resposta e o texto de apoio das telas.
library;

class QuizGroupMode {
  /// Todos respondem; o grupo vale a media dos integrantes que entraram.
  static const average = 'media';

  /// So o representante responde; o grupo vale o que ele fez.
  static const representative = 'representante';

  static String label(String mode) =>
      mode == representative ? 'Só o representante responde' : 'Média do grupo';

  static String explanation(String mode) => mode == representative
      ? 'O grupo discute e o representante responde pelos outros. '
          'O grupo vale a pontuação dele.'
      : 'Todos respondem no próprio celular. O grupo vale a média dos '
          'integrantes que entraram.';
}

class QuizGroupMember {
  final String id;
  final String name;

  /// Tem aluno vinculado com matrícula: só assim consegue entrar no quiz.
  final bool eligible;
  final bool joined;
  final int score;
  final int answers;

  const QuizGroupMember({
    required this.id,
    required this.name,
    required this.eligible,
    required this.joined,
    this.score = 0,
    this.answers = 0,
  });

  factory QuizGroupMember.fromJson(Map<String, dynamic> json) => QuizGroupMember(
        id: json['id'].toString(),
        name: json['name']?.toString() ?? '',
        eligible: json['eligible'] == true,
        joined: json['joined'] == true,
        score: (json['score'] as num?)?.toInt() ?? 0,
        answers: (json['answers'] as num?)?.toInt() ?? 0,
      );
}

class QuizGroupRepresentative {
  final String memberId;
  final String name;
  final int round;

  /// `sorteio` ou `manual`.
  final String origin;

  const QuizGroupRepresentative({
    required this.memberId,
    required this.name,
    this.round = 0,
    this.origin = 'sorteio',
  });

  bool get manual => origin == 'manual';

  factory QuizGroupRepresentative.fromJson(Map<String, dynamic> json) =>
      QuizGroupRepresentative(
        memberId: json['member_id'].toString(),
        name: json['name']?.toString() ?? '',
        round: (json['round'] as num?)?.toInt() ?? 0,
        origin: json['origin']?.toString() ?? 'sorteio',
      );
}

class QuizGroupTeam {
  final String id;
  final String name;
  final QuizGroupRepresentative? representative;
  final List<QuizGroupMember> members;

  const QuizGroupTeam({
    required this.id,
    required this.name,
    this.representative,
    this.members = const [],
  });

  List<QuizGroupMember> get eligibleMembers =>
      members.where((member) => member.eligible).toList();

  int get joinedCount => members.where((member) => member.joined).length;

  /// Sem ninguém com matrícula, o grupo não tem como participar.
  bool get blocked => eligibleMembers.isEmpty;

  factory QuizGroupTeam.fromJson(Map<String, dynamic> json) => QuizGroupTeam(
        id: json['id'].toString(),
        name: json['name']?.toString() ?? '',
        representative: json['representative'] is Map
            ? QuizGroupRepresentative.fromJson(
                Map<String, dynamic>.from(json['representative'] as Map))
            : null,
        members: ((json['members'] as List?) ?? const [])
            .map((item) =>
                QuizGroupMember.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList(),
      );
}

class QuizGroupInfo {
  final bool enabled;
  final String mode;
  final String disciplineId;
  final String discipline;
  final String semester;
  final String seed;
  final List<QuizGroupTeam> groups;
  final List<Map<String, dynamic>> ranking;

  const QuizGroupInfo({
    this.enabled = false,
    this.mode = QuizGroupMode.average,
    this.disciplineId = '',
    this.discipline = '',
    this.semester = '',
    this.seed = '',
    this.groups = const [],
    this.ranking = const [],
  });

  bool get byRepresentative => mode == QuizGroupMode.representative;

  /// Grupos que ainda não têm quem responda por eles (só no modo representante).
  List<QuizGroupTeam> get withoutRepresentative => byRepresentative
      ? groups.where((team) => team.representative == null).toList()
      : const [];

  factory QuizGroupInfo.fromJson(Map<String, dynamic> json) {
    if (json['enabled'] != true) return const QuizGroupInfo();
    return QuizGroupInfo(
      enabled: true,
      mode: json['mode']?.toString() ?? QuizGroupMode.average,
      disciplineId: json['discipline_id']?.toString() ?? '',
      discipline: json['discipline']?.toString() ?? '',
      semester: json['semester']?.toString() ?? '',
      seed: json['seed']?.toString() ?? '',
      groups: ((json['groups'] as List?) ?? const [])
          .map((item) =>
              QuizGroupTeam.fromJson(Map<String, dynamic>.from(item as Map)))
          .toList(),
      ranking: ((json['ranking'] as List?) ?? const [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList(),
    );
  }
}

/// Linha de apoio sob o nome do grupo no ranking.
///
/// Na média, a pergunta mostra quantos integrantes entraram (quem não apareceu não
/// entra na conta); com representante, mostra quem responde pelo grupo.
String groupRankingDetail(Map<String, dynamic> row, {required bool showRound}) {
  final partes = <String>[];
  if (row['mode'] == QuizGroupMode.representative) {
    final rep = row['representative']?.toString() ?? '';
    partes.add(rep.isEmpty ? 'sem representante' : 'Representante: $rep');
  } else {
    final entraram = (row['members'] as num?)?.toInt() ?? 0;
    final total = (row['members_total'] as num?)?.toInt() ?? entraram;
    partes.add('$entraram de $total integrantes');
  }
  if (showRound) {
    final pontos = (row['round_score'] as num?)?.toInt() ?? 0;
    partes.add('+$pontos nesta pergunta');
  }
  return partes.join(' · ');
}

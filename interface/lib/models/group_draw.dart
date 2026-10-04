/// Sorteio da ordem de apresentacao dos grupos de projeto.
///
/// O servidor decide a ordem (e a prova: semente + regra SHA-256); aqui fica a
/// leitura do resultado e o que a tela precisa dele - quem esta na vez, quem e o
/// proximo e como a fila se divide em dias.
library;

class GroupDrawEntry {
  final String id;
  final String groupId;
  final String groupName;

  /// Vazio enquanto o grupo nao saiu no sorteio avulso.
  final int? position;
  final int? day;
  final String status;
  final String representativeName;
  final int representativeRound;
  final DateTime? presentedAt;

  const GroupDrawEntry({
    required this.id,
    required this.groupId,
    required this.groupName,
    this.position,
    this.day,
    this.status = statusPending,
    this.representativeName = '',
    this.representativeRound = 0,
    this.presentedAt,
  });

  static const statusPending = 'pendente';
  static const statusPresenting = 'apresentando';
  static const statusDone = 'apresentou';
  static const statusAbsent = 'ausente';

  bool get drawn => position != null;
  bool get hasRepresentative => representativeName.isNotEmpty;

  /// Ainda vai apresentar: pendente ou ja no palco.
  bool get waiting => drawn && (status == statusPending || status == statusPresenting);

  factory GroupDrawEntry.fromJson(Map<String, dynamic> json) => GroupDrawEntry(
        id: json['id'].toString(),
        groupId: json['group_id'].toString(),
        groupName: json['group_name']?.toString() ?? '',
        position: (json['position'] as num?)?.toInt(),
        day: (json['day'] as num?)?.toInt(),
        status: json['status']?.toString() ?? statusPending,
        representativeName: json['representative_name']?.toString() ?? '',
        representativeRound:
            (json['representative_round'] as num?)?.toInt() ?? 0,
        presentedAt: DateTime.tryParse(json['presented_at']?.toString() ?? ''),
      );
}

class GroupDraw {
  final String id;
  final String disciplineId;
  final String discipline;
  final String semester;
  final String title;

  /// `fila` (ordem inteira de uma vez) ou `avulso` (um grupo por clique).
  final String mode;
  final String seed;
  final String algorithm;
  final int? perDay;
  final int total;
  final int remaining;

  /// A ordem gravada bate com a que a semente produz.
  final bool verified;
  final DateTime? createdAt;
  final List<GroupDrawEntry> entries;

  const GroupDraw({
    required this.id,
    required this.disciplineId,
    required this.discipline,
    required this.semester,
    required this.title,
    required this.mode,
    required this.seed,
    required this.algorithm,
    required this.total,
    required this.remaining,
    required this.verified,
    this.perDay,
    this.createdAt,
    this.entries = const [],
  });

  static const modeQueue = 'fila';
  static const modeOneByOne = 'avulso';

  bool get oneByOne => mode == modeOneByOne;
  bool get canDrawNext => oneByOne && remaining > 0;
  bool get finished => remaining == 0;

  /// So os grupos que ja sairam, na ordem da vez.
  List<GroupDrawEntry> get drawn =>
      entries.where((entry) => entry.drawn).toList();

  /// Grupos que ainda nao sairam (modo avulso).
  List<GroupDrawEntry> get notDrawn =>
      entries.where((entry) => !entry.drawn).toList();

  /// Quem esta na vez: o que a professora marcou como apresentando e, sem
  /// isso, o primeiro da fila que ainda nao apresentou.
  GroupDrawEntry? get current {
    for (final entry in drawn) {
      if (entry.status == GroupDrawEntry.statusPresenting) return entry;
    }
    for (final entry in drawn) {
      if (entry.status == GroupDrawEntry.statusPending) return entry;
    }
    return null;
  }

  /// O que vem depois de `current`.
  GroupDrawEntry? get next {
    final atual = current;
    if (atual == null) return null;
    for (final entry in drawn) {
      if (entry.position! > atual.position! &&
          entry.status == GroupDrawEntry.statusPending) {
        return entry;
      }
    }
    return null;
  }

  /// A fila dividida por dia de apresentacao, dia 1 primeiro.
  Map<int, List<GroupDrawEntry>> get byDay {
    final dias = <int, List<GroupDrawEntry>>{};
    for (final entry in drawn) {
      dias.putIfAbsent(entry.day ?? 1, () => []).add(entry);
    }
    return Map.fromEntries(
      dias.entries.toList()..sort((a, b) => a.key.compareTo(b.key)),
    );
  }

  int count(String status) =>
      drawn.where((entry) => entry.status == status).length;

  factory GroupDraw.fromJson(Map<String, dynamic> json) => GroupDraw(
        id: json['id'].toString(),
        disciplineId: json['discipline_id'].toString(),
        discipline: json['discipline']?.toString() ?? '',
        semester: json['semester']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        mode: json['mode']?.toString() ?? modeQueue,
        seed: json['seed']?.toString() ?? '',
        algorithm: json['algorithm']?.toString() ?? '',
        perDay: (json['per_day'] as num?)?.toInt(),
        total: (json['total'] as num?)?.toInt() ?? 0,
        remaining: (json['remaining'] as num?)?.toInt() ?? 0,
        verified: json['verified'] == true,
        createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
        entries: ((json['entries'] as List?) ?? const [])
            .map((item) =>
                GroupDrawEntry.fromJson(Map<String, dynamic>.from(item as Map)))
            .toList(),
      );
}

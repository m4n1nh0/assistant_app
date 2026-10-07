/// Pontos lançados ao grupo de projeto, com histórico.
///
/// Cada lançamento soma (ou, negativo, tira) pontos com motivo e data; o total do
/// grupo é a soma. Na hora de lançar, o professor escolhe se o ponto vale só para o
/// grupo ou também para cada integrante ligado a um aluno (ponto extra de cada um).
library;

/// Maior valor, em módulo, aceito em um lançamento (o servidor recusa acima disso).
const maxGroupPoints = 100.0;

/// Pontos como o professor lê: `+1,5`, `−0,5` (sinal de menos de verdade), `0`.
String formatGroupPoints(num value, {bool sign = true}) {
  final rounded = (value * 1000).round() / 1000;
  if (rounded == 0) return '0';
  var text = rounded.abs().toStringAsFixed(3);
  text = text.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
  text = text.replaceAll('.', ',');
  if (!sign) return rounded < 0 ? '−$text' : text;
  return rounded < 0 ? '−$text' : '+$text';
}

/// Lê o que o professor digitou: aceita vírgula ou ponto, `+`, `-` e o `−` unicode.
/// Devolve `null` quando não é número, é zero ou passa do limite.
double? parseGroupPoints(String input) {
  var text = input.trim().replaceAll('−', '-').replaceAll('–', '-');
  if (text.isEmpty) return null;
  text = text.replaceAll(' ', '').replaceAll(',', '.');
  if (text.startsWith('+')) text = text.substring(1);
  final value = double.tryParse(text);
  if (value == null || !value.isFinite || value == 0) return null;
  if (value.abs() > maxGroupPoints) return null;
  return value;
}

/// Um lançamento do histórico do grupo.
class GroupPointEntry {
  final String id;
  final double points;
  final String reason;
  final DateTime? entryDate;

  /// O lançamento também foi creditado a cada integrante ligado a um aluno.
  final bool creditMembers;

  /// Quantos integrantes receberam o crédito.
  final int creditedCount;

  const GroupPointEntry({
    required this.id,
    required this.points,
    this.reason = '',
    this.entryDate,
    this.creditMembers = false,
    this.creditedCount = 0,
  });

  factory GroupPointEntry.fromJson(Map<String, dynamic> json) => GroupPointEntry(
        id: '${json['id']}',
        points: (json['points'] as num?)?.toDouble() ?? 0,
        reason: json['reason']?.toString() ?? '',
        entryDate: DateTime.tryParse('${json['entry_date']}'),
        creditMembers: json['credit_members'] == true,
        creditedCount: (json['credited_count'] as num?)?.toInt() ?? 0,
      );

  bool get isSubtraction => points < 0;

  /// "só o grupo" ou "creditado a 3 integrantes".
  String get scopeLabel => creditMembers
      ? 'creditado a $creditedCount integrante${creditedCount == 1 ? '' : 's'}'
      : 'só o grupo';
}

/// O histórico completo do grupo e o total.
class GroupPointsHistory {
  final String groupId;
  final String groupName;
  final double total;
  final List<GroupPointEntry> entries;

  const GroupPointsHistory({
    required this.groupId,
    this.groupName = '',
    this.total = 0,
    this.entries = const [],
  });

  factory GroupPointsHistory.fromJson(Map<String, dynamic> json) =>
      GroupPointsHistory(
        groupId: '${json['group_id']}',
        groupName: json['group_name']?.toString() ?? '',
        total: (json['total'] as num?)?.toDouble() ?? 0,
        entries: [
          for (final item in (json['entries'] as List?) ?? const [])
            GroupPointEntry.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
      );
}

/// Quantos integrantes de um grupo têm aluno ligado, e portanto podem receber o crédito.
({int linked, int total}) memberLinkCounts(List<dynamic> members) {
  final list = [for (final item in members) Map<String, dynamic>.from(item as Map)];
  return (
    linked: list.where((member) => member['student_id'] != null).length,
    total: list.length,
  );
}

/// Agenda de atendimento: faixas semanais, exceções por data e o cruzamento com o calendário.
///
/// Os horários são de parede (o relógio de quem atende), sem fuso: "19:00" é 19:00 onde o
/// professor está. Por isso a data e a hora de cada ocorrência são montadas como hora local,
/// sem conversão.
library;

const availabilityModes = <String, String>{
  'ambos': 'Presencial ou online',
  'presencial': 'Presencial',
  'online': 'Online',
};

const availabilityAudiences = <String, String>{
  'todos': 'Todos',
  'graduacao': 'Só graduação',
  'mentoria': 'Só mentoria',
};

const weekdayNames = [
  'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo',
];

class AvailabilitySlot {
  final String id;
  final int weekday;
  final String startTime;
  final String endTime;
  final String mode;
  final String location;
  final String audience;
  final String note;
  final bool active;

  const AvailabilitySlot({
    required this.id,
    required this.weekday,
    required this.startTime,
    required this.endTime,
    this.mode = 'ambos',
    this.location = '',
    this.audience = 'todos',
    this.note = '',
    this.active = true,
  });

  factory AvailabilitySlot.fromJson(Map<String, dynamic> json) => AvailabilitySlot(
        id: '${json['id']}',
        weekday: (json['weekday'] as num?)?.toInt() ?? 0,
        startTime: json['start_time']?.toString() ?? '',
        endTime: json['end_time']?.toString() ?? '',
        mode: json['mode']?.toString() ?? 'ambos',
        location: json['location']?.toString() ?? '',
        audience: json['audience']?.toString() ?? 'todos',
        note: json['note']?.toString() ?? '',
        active: json['active'] != false,
      );

  String get range => '$startTime às $endTime';
}

class AvailabilityException {
  final String id;

  /// AAAA-MM-DD.
  final String day;

  /// `blocked` ou `extra`.
  final String kind;
  final String startTime;
  final String endTime;
  final String mode;
  final String location;
  final String audience;
  final String note;

  const AvailabilityException({
    required this.id,
    required this.day,
    this.kind = 'blocked',
    this.startTime = '',
    this.endTime = '',
    this.mode = 'ambos',
    this.location = '',
    this.audience = 'todos',
    this.note = '',
  });

  factory AvailabilityException.fromJson(Map<String, dynamic> json) => AvailabilityException(
        id: '${json['id']}',
        day: json['day']?.toString() ?? '',
        kind: json['kind']?.toString() ?? 'blocked',
        startTime: json['start_time']?.toString() ?? '',
        endTime: json['end_time']?.toString() ?? '',
        mode: json['mode']?.toString() ?? 'ambos',
        location: json['location']?.toString() ?? '',
        audience: json['audience']?.toString() ?? 'todos',
        note: json['note']?.toString() ?? '',
      );

  bool get isBlocked => kind == 'blocked';
}

/// Uma data concreta da agenda: um atendimento ou um dia bloqueado.
class AvailabilityOccurrence {
  final String date;
  final int weekday;
  final bool blocked;
  final String startTime;
  final String endTime;
  final String mode;
  final String location;
  final String audience;
  final String note;

  /// `weekly`, `extra` ou `blocked`.
  final String source;

  const AvailabilityOccurrence({
    required this.date,
    required this.weekday,
    this.blocked = false,
    this.startTime = '',
    this.endTime = '',
    this.mode = '',
    this.location = '',
    this.audience = '',
    this.note = '',
    this.source = 'weekly',
  });

  factory AvailabilityOccurrence.fromJson(Map<String, dynamic> json) =>
      AvailabilityOccurrence(
        date: json['date']?.toString() ?? '',
        weekday: (json['weekday'] as num?)?.toInt() ?? 0,
        blocked: json['blocked'] == true,
        startTime: json['start_time']?.toString() ?? '',
        endTime: json['end_time']?.toString() ?? '',
        mode: json['mode']?.toString() ?? '',
        location: json['location']?.toString() ?? '',
        audience: json['audience']?.toString() ?? '',
        note: json['note']?.toString() ?? '',
        source: json['source']?.toString() ?? 'weekly',
      );

  DateTime? _at(String time) {
    final day = DateTime.tryParse(date);
    final parts = time.split(':');
    if (day == null || parts.length != 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null) return null;
    return DateTime(day.year, day.month, day.day, hour, minute);
  }

  DateTime? get starts => blocked ? null : _at(startTime);
  DateTime? get ends => blocked ? null : _at(endTime);
}

/// Evento do calendário externo, reduzido ao que o cruzamento precisa.
class BusyEvent {
  final String title;
  final DateTime start;
  final DateTime end;

  const BusyEvent({required this.title, required this.start, required this.end});
}

/// Evento do calendário que cai dentro de um atendimento publicado.
class AvailabilityConflict {
  final AvailabilityOccurrence occurrence;
  final BusyEvent event;

  const AvailabilityConflict(this.occurrence, this.event);
}

/// Cruza os atendimentos com os eventos do calendário. Dia bloqueado não conflita (já não
/// há atendimento); evento sem fim vale uma hora.
List<AvailabilityConflict> findConflicts(
  Iterable<AvailabilityOccurrence> occurrences,
  Iterable<BusyEvent> events,
) {
  final out = <AvailabilityConflict>[];
  for (final occurrence in occurrences) {
    final start = occurrence.starts;
    final end = occurrence.ends;
    if (start == null || end == null) continue;
    for (final event in events) {
      if (event.start.isBefore(end) && start.isBefore(event.end)) {
        out.add(AvailabilityConflict(occurrence, event));
      }
    }
  }
  return out;
}

/// Uma faixa da agenda avaliada para o plano de encontros da mentoria.
class MeetingOption {
  final String slotId;
  final int weekday;
  final String weekdayName;
  final String startTime;
  final String endTime;
  final String mode;
  final String location;
  final int count;
  final List<String> names;

  const MeetingOption({
    required this.slotId,
    required this.weekday,
    required this.weekdayName,
    required this.startTime,
    required this.endTime,
    this.mode = 'ambos',
    this.location = '',
    this.count = 0,
    this.names = const [],
  });

  factory MeetingOption.fromJson(Map<String, dynamic> json) => MeetingOption(
        slotId: '${json['slot_id']}',
        weekday: (json['weekday'] as num?)?.toInt() ?? 0,
        weekdayName: json['weekday_name']?.toString() ?? '',
        startTime: json['start_time']?.toString() ?? '',
        endTime: json['end_time']?.toString() ?? '',
        mode: json['mode']?.toString() ?? 'ambos',
        location: json['location']?.toString() ?? '',
        count: (json['count'] as num?)?.toInt() ?? 0,
        names: [for (final n in (json['names'] as List? ?? const [])) '$n'],
      );
}

class MeetingPlan {
  final int accepted;
  final int withAvailability;
  final bool hasSlots;
  final List<MeetingOption> options;
  final List<String> uncovered;

  const MeetingPlan({
    this.accepted = 0,
    this.withAvailability = 0,
    this.hasSlots = false,
    this.options = const [],
    this.uncovered = const [],
  });

  factory MeetingPlan.fromJson(Map<String, dynamic> json) => MeetingPlan(
        accepted: (json['accepted'] as num?)?.toInt() ?? 0,
        withAvailability: (json['with_availability'] as num?)?.toInt() ?? 0,
        hasSlots: json['has_slots'] == true,
        options: [
          for (final o in (json['options'] as List? ?? const []))
            MeetingOption.fromJson(Map<String, dynamic>.from(o as Map)),
        ],
        uncovered: [for (final n in (json['uncovered'] as List? ?? const [])) '$n'],
      );
}

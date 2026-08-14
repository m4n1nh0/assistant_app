import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_service.dart';
import 'student_csv_parser.dart';

/// Cliente do modo educacao: aulas, trechos de transcricao, resumo,
/// pontuacoes extras e cadastro de turma.
class EducationService {
  final ApiService _api;

  EducationService(this._api);

  String get _baseUrl => _api.baseUrl;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_api.token != null) 'Authorization': 'Bearer ${_api.token}',
      };

  Never _fail(http.Response response) {
    String detail = response.body;
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map && decoded['detail'] != null) {
        detail = decoded['detail'].toString();
      }
    } catch (_) {
      // Mantem o corpo cru quando a resposta nao e JSON.
    }
    throw EducationException('HTTP ${response.statusCode}: $detail');
  }

  dynamic _decode(http.Response response) {
    if (response.statusCode >= 400) _fail(response);
    if (response.body.isEmpty) return null;
    return jsonDecode(response.body);
  }

  // --- Disciplinas ---------------------------------------------------------

  Future<List<Discipline>> listDisciplines({
    bool activeOnly = true,
    String? semester,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/disciplines').replace(
      queryParameters: {
        'active_only': '$activeOnly',
        if (semester != null && semester.isNotEmpty) 'semester': semester,
      },
    );
    final response = await http.get(uri, headers: _headers);
    return (_decode(response) as List<dynamic>)
        .map((item) => Discipline.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<Discipline> createDiscipline({
    required String code,
    String name = '',
    String semester = '',
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/disciplines'),
      headers: _headers,
      body: jsonEncode({
        'code': code,
        'name': name,
        'semester': semester,
      }),
    );
    return Discipline.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<Discipline> updateDiscipline(
    String disciplineId, {
    String? code,
    String? name,
    String? semester,
    bool? active,
  }) async {
    final response = await http.patch(
      Uri.parse('$_baseUrl/education/disciplines/$disciplineId'),
      headers: _headers,
      body: jsonEncode({
        if (code != null) 'code': code,
        if (name != null) 'name': name,
        if (semester != null) 'semester': semester,
        if (active != null) 'active': active,
      }),
    );
    return Discipline.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<void> deleteDiscipline(String disciplineId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/education/disciplines/$disciplineId'),
      headers: _headers,
    );
    _decode(response);
  }

  Future<Semester> updateSemester(String code, {required bool active}) async {
    final response = await http.patch(
      Uri.parse('$_baseUrl/education/semesters/$code'),
      headers: _headers,
      body: jsonEncode({'active': active}),
    );
    return Semester.fromJson(_decode(response) as Map<String, dynamic>);
  }

  // --- Turmas --------------------------------------------------------------

  Future<List<ClassGroup>> listClasses({String? discipline}) async {
    final uri = Uri.parse('$_baseUrl/education/classes').replace(
      queryParameters: {
        if (discipline != null && discipline.isNotEmpty)
          'discipline': discipline,
      },
    );
    final response = await http.get(uri, headers: _headers);
    return (_decode(response) as List<dynamic>)
        .map((item) => ClassGroup.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<ClassGroup> createClass({
    required String code,
    String name = '',
    String? disciplineId,
    List<ClassSchedule> schedules = const [],
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/classes'),
      headers: _headers,
      body: jsonEncode({
        'code': code,
        'name': name,
        if (disciplineId != null) 'discipline_id': disciplineId,
        'schedules': schedules.map((item) => item.toJson()).toList(),
      }),
    );
    return ClassGroup.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<ClassGroup> updateClass(
    String classId, {
    String? code,
    String? name,
    String? disciplineId,
    List<ClassSchedule>? schedules,
    bool? active,
  }) async {
    final response = await http.patch(
      Uri.parse('$_baseUrl/education/classes/$classId'),
      headers: _headers,
      body: jsonEncode({
        if (code != null) 'code': code,
        if (name != null) 'name': name,
        if (disciplineId != null) 'discipline_id': disciplineId,
        if (schedules != null)
          'schedules': schedules.map((item) => item.toJson()).toList(),
        if (active != null) 'active': active,
      }),
    );
    return ClassGroup.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<void> deleteClass(String classId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/education/classes/$classId'),
      headers: _headers,
    );
    _decode(response);
  }

  // --- Aulas ---------------------------------------------------------------

  Future<Lesson> createLesson({
    required String discipline,
    String semester = '',
    String title = '',
    String classGroup = '',
    List<String> classIds = const [],
    String? teacher,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/lessons'),
      headers: _headers,
      body: jsonEncode({
        'discipline': discipline,
        'semester': semester,
        'title': title,
        'class_group': classGroup,
        'class_ids': classIds,
        if (teacher != null) 'teacher': teacher,
      }),
    );
    return Lesson.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<Lesson> updateLesson(
    String lessonId, {
    String? discipline,
    String? title,
    List<String>? classIds,
  }) async {
    final response = await http.patch(
      Uri.parse('$_baseUrl/education/lessons/$lessonId'),
      headers: _headers,
      body: jsonEncode({
        if (discipline != null) 'discipline': discipline,
        if (title != null) 'title': title,
        if (classIds != null) 'class_ids': classIds,
      }),
    );
    return Lesson.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<List<Lesson>> listLessons({
    String? discipline,
    String? semester,
    String? dateFrom,
    String? dateTo,
    int limit = 50,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/lessons').replace(
      queryParameters: {
        if (discipline != null && discipline.isNotEmpty)
          'discipline': discipline,
        if (semester != null && semester.isNotEmpty) 'semester': semester,
        if (dateFrom != null && dateFrom.isNotEmpty) 'date_from': dateFrom,
        if (dateTo != null && dateTo.isNotEmpty) 'date_to': dateTo,
        'limit': '$limit',
      },
    );
    final response = await http.get(uri, headers: _headers);
    final data = _decode(response) as List<dynamic>;
    return data
        .map((item) => Lesson.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<LessonDetail> getLesson(String lessonId,
      {bool includeSegments = true}) async {
    final uri = Uri.parse('$_baseUrl/education/lessons/$lessonId').replace(
      queryParameters: {'include_segments': '$includeSegments'},
    );
    final response = await http.get(uri, headers: _headers);
    return LessonDetail.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<void> deleteLesson(String lessonId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/education/lessons/$lessonId'),
      headers: _headers,
    );
    _decode(response);
  }

  Future<LessonSegment> updateLessonSegment(
    String lessonId,
    String segmentId,
    String text,
  ) async {
    final response = await http.patch(
      Uri.parse(
        '$_baseUrl/education/lessons/$lessonId/segments/$segmentId',
      ),
      headers: _headers,
      body: jsonEncode({'text': text}),
    );
    return LessonSegment.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<Lesson> closeLesson(String lessonId) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/lessons/$lessonId/close'),
      headers: _headers,
    );
    return Lesson.fromJson(_decode(response) as Map<String, dynamic>);
  }

  /// Envia um bloco de audio da aula. O backend transcreve, indexa no Qdrant
  /// e extrai pontuacoes extras citadas no trecho.
  Future<SegmentIngestResult> uploadAudioChunk(
    String lessonId,
    List<int> audioBytes, {
    String filename = 'chunk.wav',
    String language = 'pt',
    int durationMs = 0,
    bool extractPoints = true,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$_baseUrl/education/lessons/$lessonId/audio'),
    );
    if (_api.token != null) {
      request.headers['Authorization'] = 'Bearer ${_api.token}';
    }
    request.files.add(
      http.MultipartFile.fromBytes('file', audioBytes, filename: filename),
    );
    request.fields['language'] = language;
    request.fields['duration_ms'] = '$durationMs';
    request.fields['extract_points'] = '$extractPoints';

    final streamed = await request.send();
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode >= 400) {
      throw EducationException('HTTP ${streamed.statusCode}: $body');
    }
    return SegmentIngestResult.fromJson(
        jsonDecode(body) as Map<String, dynamic>);
  }

  Future<LessonSummary> generateSummary(
    String lessonId, {
    String? llm,
    String focus = '',
    bool closeLesson = false,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/lessons/$lessonId/summary'),
      headers: _headers,
      body: jsonEncode({
        if (llm != null && llm.isNotEmpty) 'llm': llm,
        'focus': focus,
        'close_lesson': closeLesson,
      }),
    );
    return LessonSummary.fromJson(_decode(response) as Map<String, dynamic>);
  }

  // --- Pontuacao extra -----------------------------------------------------

  Future<LessonPoint> addPoint(
    String lessonId, {
    required String studentName,
    required double points,
    String? reason,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/lessons/$lessonId/points'),
      headers: _headers,
      body: jsonEncode({
        'student_name': studentName,
        'points': points,
        if (reason != null) 'reason': reason,
      }),
    );
    return LessonPoint.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<void> deletePoint(String pointId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/education/points/$pointId'),
      headers: _headers,
    );
    _decode(response);
  }

  Future<PointsReport> pointsReport({
    String? dateFrom,
    String? dateTo,
    String? discipline,
    String? classGroup,
    String? studentName,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/points').replace(
      queryParameters: {
        if (dateFrom != null && dateFrom.isNotEmpty) 'date_from': dateFrom,
        if (dateTo != null && dateTo.isNotEmpty) 'date_to': dateTo,
        if (discipline != null && discipline.isNotEmpty)
          'discipline': discipline,
        if (classGroup != null && classGroup.isNotEmpty)
          'class_group': classGroup,
        if (studentName != null && studentName.isNotEmpty)
          'student_name': studentName,
      },
    );
    final response = await http.get(uri, headers: _headers);
    return PointsReport.fromJson(_decode(response) as Map<String, dynamic>);
  }

  // --- Turma ---------------------------------------------------------------

  Future<List<Student>> listStudents({
    String? classId,
    String? classGroup,
    String? discipline,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/students').replace(
      queryParameters: {
        if (classId != null && classId.isNotEmpty) 'class_id': classId,
        if (classGroup != null && classGroup.isNotEmpty)
          'class_group': classGroup,
        if (discipline != null && discipline.isNotEmpty)
          'discipline': discipline,
      },
    );
    final response = await http.get(uri, headers: _headers);
    final data = _decode(response) as List<dynamic>;
    return data
        .map((item) => Student.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<Student> createStudent({
    required String name,
    String? externalId,
    String? classId,
    String classGroup = '',
    String discipline = '',
    List<String> aliases = const [],
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/students'),
      headers: _headers,
      body: jsonEncode({
        'name': name,
        'external_id': externalId,
        if (classId != null) 'class_id': classId,
        'class_group': classGroup,
        'discipline': discipline,
        'aliases': aliases,
      }),
    );
    return Student.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<StudentImportResult> importStudents({
    required String classId,
    required List<StudentCsvRow> students,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/students/import'),
      headers: _headers,
      body: jsonEncode({
        'class_id': classId,
        'students': students
            .map((student) => {
                  'enrollment': student.enrollment,
                  'name': student.name,
                })
            .toList(),
      }),
    );
    return StudentImportResult.fromJson(
      _decode(response) as Map<String, dynamic>,
    );
  }

  Future<Student> updateStudent(
    String studentId, {
    String? name,
    String? classId,
    List<String>? aliases,
  }) async {
    final response = await http.patch(
      Uri.parse('$_baseUrl/education/students/$studentId'),
      headers: _headers,
      body: jsonEncode({
        if (name != null) 'name': name,
        if (classId != null) 'class_id': classId,
        if (aliases != null) 'aliases': aliases,
      }),
    );
    return Student.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<void> deleteStudent(String studentId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/education/students/$studentId'),
      headers: _headers,
    );
    _decode(response);
  }

  // --- Busca e diagnostico -------------------------------------------------

  Future<List<TranscriptHit>> search(
    String query, {
    String? discipline,
    String? lessonId,
    String? dateFrom,
    String? dateTo,
    int limit = 8,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/search').replace(
      queryParameters: {
        'q': query,
        if (discipline != null && discipline.isNotEmpty)
          'discipline': discipline,
        if (lessonId != null && lessonId.isNotEmpty) 'lesson_id': lessonId,
        if (dateFrom != null && dateFrom.isNotEmpty) 'date_from': dateFrom,
        if (dateTo != null && dateTo.isNotEmpty) 'date_to': dateTo,
        'limit': '$limit',
      },
    );
    final response = await http.get(uri, headers: _headers);
    final data = _decode(response) as List<dynamic>;
    return data
        .map((item) => TranscriptHit.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<EmbeddingStatus> embeddingStatus() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/education/embedding-status'),
      headers: _headers,
    );
    return EmbeddingStatus.fromJson(_decode(response) as Map<String, dynamic>);
  }
}

class EducationException implements Exception {
  final String message;

  EducationException(this.message);

  @override
  String toString() => message;
}

// --- Modelos ---------------------------------------------------------------

double _toDouble(dynamic value) =>
    value is num ? value.toDouble() : double.tryParse('$value') ?? 0.0;

int _toInt(dynamic value) =>
    value is num ? value.toInt() : int.tryParse('$value') ?? 0;

DateTime? _toDate(dynamic value) =>
    value == null ? null : DateTime.tryParse(value.toString());

/// Disciplina ministrada: ARA0040 - BANCO DE DADOS.
class Discipline {
  final String id;
  final String code;
  final String name;
  final String label;
  final String semester;
  final int classCount;
  final bool active;

  const Discipline({
    required this.id,
    required this.code,
    required this.name,
    required this.label,
    this.semester = '',
    this.classCount = 0,
    this.active = true,
  });

  factory Discipline.fromJson(Map<String, dynamic> json) => Discipline(
        id: json['id'].toString(),
        code: json['code']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        label: json['label']?.toString() ?? '',
        semester: json['semester']?.toString() ?? '',
        classCount: _toInt(json['class_count']),
        active: json['active'] != false,
      );
}

class Semester {
  final String code;
  final bool active;
  final int disciplineCount;
  final int classCount;

  const Semester({
    required this.code,
    required this.active,
    this.disciplineCount = 0,
    this.classCount = 0,
  });

  factory Semester.fromJson(Map<String, dynamic> json) => Semester(
        code: json['code']?.toString() ?? '',
        active: json['active'] != false,
        disciplineCount: _toInt(json['discipline_count']),
        classCount: _toInt(json['class_count']),
      );
}

/// Dia da semana em que a turma tem aula. 0 = segunda, como no backend.
class ClassSchedule {
  final int weekday;
  final String startTime;
  final String endTime;

  const ClassSchedule({
    required this.weekday,
    this.startTime = '',
    this.endTime = '',
  });

  factory ClassSchedule.fromJson(Map<String, dynamic> json) => ClassSchedule(
        weekday: _toInt(json['weekday']),
        startTime: json['start_time']?.toString() ?? '',
        endTime: json['end_time']?.toString() ?? '',
      );

  Map<String, dynamic> toJson() => {
        'weekday': weekday,
        'start_time': startTime,
        'end_time': endTime,
      };
}

/// Turma como entidade do backend. `label` e o texto que aparece no aluno e
/// na aula, montado a partir do codigo e do nome.
class ClassGroup {
  final String id;
  final String code;
  final String name;
  final String? disciplineId;
  final String discipline;
  final String semester;
  final String label;
  final bool active;
  final int studentCount;
  final List<ClassSchedule> schedules;
  final String scheduleLabel;

  const ClassGroup({
    required this.id,
    required this.code,
    required this.name,
    required this.discipline,
    this.semester = '',
    required this.label,
    this.disciplineId,
    this.active = true,
    this.studentCount = 0,
    this.schedules = const [],
    this.scheduleLabel = '',
  });

  factory ClassGroup.fromJson(Map<String, dynamic> json) => ClassGroup(
        id: json['id'].toString(),
        code: json['code']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        disciplineId: json['discipline_id']?.toString(),
        discipline: json['discipline']?.toString() ?? '',
        semester: json['semester']?.toString() ?? '',
        label: json['label']?.toString() ?? '',
        active: json['active'] != false,
        studentCount: _toInt(json['student_count']),
        schedules: ((json['schedules'] as List<dynamic>?) ?? [])
            .map((item) => ClassSchedule.fromJson(item as Map<String, dynamic>))
            .toList(),
        scheduleLabel: json['schedule_label']?.toString() ?? '',
      );

  /// A turma tem aula neste dia? Recebe o `DateTime.weekday` do Dart, em que
  /// segunda e 1, e compara com o backend, em que segunda e 0.
  bool meetsOn(int dartWeekday) =>
      schedules.any((item) => item.weekday == dartWeekday - 1);

  /// Como a turma aparece nas listas: "3001 Presencial - ARA0040".
  String get display {
    final base = discipline.isEmpty ? label : '$label - $discipline';
    return semester.isEmpty ? base : '$base ($semester)';
  }
}

class Lesson {
  final String id;
  final String discipline;
  final String semester;
  final String title;
  final String classGroup;
  final List<String> classIds;
  final List<String> classLabels;
  final String status;
  final DateTime? startedAt;
  final DateTime? endedAt;
  final String? summary;
  final String? summaryLlm;
  final DateTime? summaryAt;
  final int segmentCount;
  final int transcriptChars;

  Lesson({
    required this.id,
    required this.discipline,
    this.semester = '',
    required this.title,
    required this.classGroup,
    required this.status,
    this.classIds = const [],
    this.classLabels = const [],
    this.startedAt,
    this.endedAt,
    this.summary,
    this.summaryLlm,
    this.summaryAt,
    this.segmentCount = 0,
    this.transcriptChars = 0,
  });

  bool get isClosed => status == 'closed';

  factory Lesson.fromJson(Map<String, dynamic> json) => Lesson(
        id: json['id'].toString(),
        discipline: json['discipline']?.toString() ?? '',
        semester: json['semester']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        classGroup: json['class_group']?.toString() ?? '',
        classIds: ((json['class_ids'] as List<dynamic>?) ?? [])
            .map((item) => item.toString())
            .toList(),
        classLabels: ((json['class_labels'] as List<dynamic>?) ?? [])
            .map((item) => item.toString())
            .toList(),
        status: json['status']?.toString() ?? 'recording',
        startedAt: _toDate(json['started_at']),
        endedAt: _toDate(json['ended_at']),
        summary: json['summary']?.toString(),
        summaryLlm: json['summary_llm']?.toString(),
        summaryAt: _toDate(json['summary_at']),
        segmentCount: _toInt(json['segment_count']),
        transcriptChars: _toInt(json['transcript_chars']),
      );
}

class LessonDetail extends Lesson {
  final List<LessonSegment> segments;
  final List<LessonPoint> points;

  LessonDetail({
    required super.id,
    required super.discipline,
    super.semester,
    required super.title,
    required super.classGroup,
    required super.status,
    super.classIds,
    super.classLabels,
    super.startedAt,
    super.endedAt,
    super.summary,
    super.summaryLlm,
    super.summaryAt,
    super.segmentCount,
    super.transcriptChars,
    this.segments = const [],
    this.points = const [],
  });

  factory LessonDetail.fromJson(Map<String, dynamic> json) {
    final lesson = Lesson.fromJson(json);
    return LessonDetail(
      id: lesson.id,
      discipline: lesson.discipline,
      semester: lesson.semester,
      title: lesson.title,
      classGroup: lesson.classGroup,
      classIds: lesson.classIds,
      classLabels: lesson.classLabels,
      status: lesson.status,
      startedAt: lesson.startedAt,
      endedAt: lesson.endedAt,
      summary: lesson.summary,
      summaryLlm: lesson.summaryLlm,
      summaryAt: lesson.summaryAt,
      segmentCount: lesson.segmentCount,
      transcriptChars: lesson.transcriptChars,
      segments: ((json['segments'] as List<dynamic>?) ?? [])
          .map((item) => LessonSegment.fromJson(item as Map<String, dynamic>))
          .toList(),
      points: ((json['points'] as List<dynamic>?) ?? [])
          .map((item) => LessonPoint.fromJson(item as Map<String, dynamic>))
          .toList(),
    );
  }
}

class LessonSegment {
  final String id;
  final int sequence;
  final String text;
  final double confidence;
  final bool indexed;
  final DateTime? createdAt;

  LessonSegment({
    required this.id,
    required this.sequence,
    required this.text,
    required this.confidence,
    required this.indexed,
    this.createdAt,
  });

  factory LessonSegment.fromJson(Map<String, dynamic> json) => LessonSegment(
        id: json['id'].toString(),
        sequence: _toInt(json['sequence']),
        text: json['text']?.toString() ?? '',
        confidence: _toDouble(json['confidence']),
        indexed: json['indexed'] == true,
        createdAt: _toDate(json['created_at']),
      );
}

class LessonPoint {
  final String id;
  final String lessonId;
  final String? studentId;
  final String studentName;
  final double points;
  final String? reason;
  final String discipline;
  final DateTime? lessonDate;
  final String source;
  final double confidence;
  final String? quote;

  LessonPoint({
    required this.id,
    required this.lessonId,
    required this.studentName,
    required this.points,
    required this.discipline,
    required this.source,
    required this.confidence,
    this.studentId,
    this.reason,
    this.lessonDate,
    this.quote,
  });

  /// Aluno que o backend nao conseguiu casar com o cadastro da turma.
  bool get needsReview => studentId == null && source == 'extracted';

  factory LessonPoint.fromJson(Map<String, dynamic> json) => LessonPoint(
        id: json['id'].toString(),
        lessonId: json['lesson_id']?.toString() ?? '',
        studentId: json['student_id']?.toString(),
        studentName: json['student_name']?.toString() ?? '',
        points: _toDouble(json['points']),
        reason: json['reason']?.toString(),
        discipline: json['discipline']?.toString() ?? '',
        lessonDate: _toDate(json['lesson_date']),
        source: json['source']?.toString() ?? 'extracted',
        confidence: _toDouble(json['confidence']),
        quote: json['quote']?.toString(),
      );
}

class SegmentIngestResult {
  final LessonSegment? segment;
  final bool indexed;
  final String? skippedReason;
  final List<LessonPoint> points;
  final Lesson lesson;

  SegmentIngestResult({
    required this.lesson,
    this.segment,
    this.indexed = false,
    this.skippedReason,
    this.points = const [],
  });

  factory SegmentIngestResult.fromJson(Map<String, dynamic> json) =>
      SegmentIngestResult(
        segment: json['segment'] == null
            ? null
            : LessonSegment.fromJson(json['segment'] as Map<String, dynamic>),
        indexed: json['indexed'] == true,
        skippedReason: json['skipped_reason']?.toString(),
        points: ((json['points'] as List<dynamic>?) ?? [])
            .map((item) => LessonPoint.fromJson(item as Map<String, dynamic>))
            .toList(),
        lesson: Lesson.fromJson(json['lesson'] as Map<String, dynamic>),
      );
}

class LessonSummary {
  final String lessonId;
  final String summary;
  final String llm;
  final DateTime? generatedAt;
  final int usedSegments;
  final List<LessonPoint> points;

  LessonSummary({
    required this.lessonId,
    required this.summary,
    required this.llm,
    required this.usedSegments,
    this.generatedAt,
    this.points = const [],
  });

  factory LessonSummary.fromJson(Map<String, dynamic> json) => LessonSummary(
        lessonId: json['lesson_id']?.toString() ?? '',
        summary: json['summary']?.toString() ?? '',
        llm: json['llm']?.toString() ?? '',
        generatedAt: _toDate(json['generated_at']),
        usedSegments: _toInt(json['used_segments']),
        points: ((json['points'] as List<dynamic>?) ?? [])
            .map((item) => LessonPoint.fromJson(item as Map<String, dynamic>))
            .toList(),
      );
}

class Student {
  final String id;
  final String name;
  final String? classId;
  final String? externalId;
  final String classGroup;
  final String discipline;
  final List<String> aliases;
  final bool active;

  Student({
    required this.id,
    required this.name,
    this.classId,
    this.externalId,
    required this.classGroup,
    required this.discipline,
    this.aliases = const [],
    this.active = true,
  });

  factory Student.fromJson(Map<String, dynamic> json) => Student(
        id: json['id'].toString(),
        name: json['name']?.toString() ?? '',
        classId: json['class_id']?.toString(),
        externalId: json['external_id']?.toString(),
        classGroup: json['class_group']?.toString() ?? '',
        discipline: json['discipline']?.toString() ?? '',
        aliases: ((json['aliases'] as List<dynamic>?) ?? [])
            .map((item) => item.toString())
            .toList(),
        active: json['active'] != false,
      );
}

class StudentImportResult {
  final int created;
  final int updated;
  final int total;

  const StudentImportResult({
    required this.created,
    required this.updated,
    required this.total,
  });

  factory StudentImportResult.fromJson(Map<String, dynamic> json) =>
      StudentImportResult(
        created: (json['created'] as num?)?.toInt() ?? 0,
        updated: (json['updated'] as num?)?.toInt() ?? 0,
        total: (json['total'] as num?)?.toInt() ?? 0,
      );
}

class PointsReportEntry {
  final String studentName;
  final String? studentId;
  final double totalPoints;
  final String discipline;

  /// Turma da aula que gerou os pontos: separa duas turmas da mesma
  /// disciplina no mesmo dia.
  final String classGroup;
  final String lessonDate;
  final List<LessonPoint> entries;

  PointsReportEntry({
    required this.studentName,
    required this.totalPoints,
    required this.discipline,
    required this.lessonDate,
    this.classGroup = '',
    this.studentId,
    this.entries = const [],
  });

  factory PointsReportEntry.fromJson(Map<String, dynamic> json) =>
      PointsReportEntry(
        studentName: json['student_name']?.toString() ?? '',
        studentId: json['student_id']?.toString(),
        totalPoints: _toDouble(json['total_points']),
        discipline: json['discipline']?.toString() ?? '',
        classGroup: json['class_group']?.toString() ?? '',
        lessonDate: json['lesson_date']?.toString() ?? '',
        entries: ((json['entries'] as List<dynamic>?) ?? [])
            .map((item) => LessonPoint.fromJson(item as Map<String, dynamic>))
            .toList(),
      );
}

class PointsReport {
  final double totalPoints;
  final List<PointsReportEntry> students;

  PointsReport({required this.totalPoints, this.students = const []});

  factory PointsReport.fromJson(Map<String, dynamic> json) => PointsReport(
        totalPoints: _toDouble(json['total_points']),
        students: ((json['students'] as List<dynamic>?) ?? [])
            .map((item) =>
                PointsReportEntry.fromJson(item as Map<String, dynamic>))
            .toList(),
      );
}

class TranscriptHit {
  final String id;
  final double score;
  final String lessonId;
  final String discipline;
  final String lessonDate;
  final int sequence;
  final String content;

  TranscriptHit({
    required this.id,
    required this.score,
    required this.lessonId,
    required this.discipline,
    required this.lessonDate,
    required this.sequence,
    required this.content,
  });

  factory TranscriptHit.fromJson(Map<String, dynamic> json) => TranscriptHit(
        id: json['id'].toString(),
        score: _toDouble(json['score']),
        lessonId: json['lesson_id']?.toString() ?? '',
        discipline: json['discipline']?.toString() ?? '',
        lessonDate: json['lesson_date']?.toString() ?? '',
        sequence: _toInt(json['sequence']),
        content: json['content']?.toString() ?? '',
      );
}

class EmbeddingStatus {
  final bool ok;
  final String provider;
  final String? model;
  final int? dimensions;
  final bool semantic;
  final String? error;

  EmbeddingStatus({
    required this.ok,
    required this.provider,
    this.model,
    this.dimensions,
    this.semantic = false,
    this.error,
  });

  factory EmbeddingStatus.fromJson(Map<String, dynamic> json) =>
      EmbeddingStatus(
        ok: json['ok'] == true,
        provider: json['provider']?.toString() ?? '',
        model: json['model']?.toString(),
        dimensions:
            json['dimensions'] == null ? null : _toInt(json['dimensions']),
        semantic: json['semantic'] == true,
        error: json['error']?.toString(),
      );
}

final education = EducationService(api);

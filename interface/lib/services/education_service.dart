import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_service.dart';

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

  // --- Aulas ---------------------------------------------------------------

  Future<Lesson> createLesson({
    required String subject,
    String title = '',
    String classGroup = '',
    String? teacher,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/lessons'),
      headers: _headers,
      body: jsonEncode({
        'subject': subject,
        'title': title,
        'class_group': classGroup,
        if (teacher != null) 'teacher': teacher,
      }),
    );
    return Lesson.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<List<Lesson>> listLessons({
    String? subject,
    String? dateFrom,
    String? dateTo,
    int limit = 50,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/lessons').replace(
      queryParameters: {
        if (subject != null && subject.isNotEmpty) 'subject': subject,
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
    String? subject,
    String? studentName,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/points').replace(
      queryParameters: {
        if (dateFrom != null && dateFrom.isNotEmpty) 'date_from': dateFrom,
        if (dateTo != null && dateTo.isNotEmpty) 'date_to': dateTo,
        if (subject != null && subject.isNotEmpty) 'subject': subject,
        if (studentName != null && studentName.isNotEmpty)
          'student_name': studentName,
      },
    );
    final response = await http.get(uri, headers: _headers);
    return PointsReport.fromJson(_decode(response) as Map<String, dynamic>);
  }

  // --- Turma ---------------------------------------------------------------

  Future<List<Student>> listStudents({
    String? classGroup,
    String? subject,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/students').replace(
      queryParameters: {
        if (classGroup != null && classGroup.isNotEmpty)
          'class_group': classGroup,
        if (subject != null && subject.isNotEmpty) 'subject': subject,
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
    String classGroup = '',
    String subject = '',
    List<String> aliases = const [],
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/education/students'),
      headers: _headers,
      body: jsonEncode({
        'name': name,
        'class_group': classGroup,
        'subject': subject,
        'aliases': aliases,
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
    String? subject,
    String? lessonId,
    String? dateFrom,
    String? dateTo,
    int limit = 8,
  }) async {
    final uri = Uri.parse('$_baseUrl/education/search').replace(
      queryParameters: {
        'q': query,
        if (subject != null && subject.isNotEmpty) 'subject': subject,
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

  Future<List<String>> listSubjects() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/education/subjects'),
      headers: _headers,
    );
    return (_decode(response) as List<dynamic>)
        .map((item) => item.toString())
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

class Lesson {
  final String id;
  final String subject;
  final String title;
  final String classGroup;
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
    required this.subject,
    required this.title,
    required this.classGroup,
    required this.status,
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
        subject: json['subject']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        classGroup: json['class_group']?.toString() ?? '',
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
    required super.subject,
    required super.title,
    required super.classGroup,
    required super.status,
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
      subject: lesson.subject,
      title: lesson.title,
      classGroup: lesson.classGroup,
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
  final String subject;
  final DateTime? lessonDate;
  final String source;
  final double confidence;
  final String? quote;

  LessonPoint({
    required this.id,
    required this.lessonId,
    required this.studentName,
    required this.points,
    required this.subject,
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
        subject: json['subject']?.toString() ?? '',
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
  final String classGroup;
  final String subject;
  final List<String> aliases;
  final bool active;

  Student({
    required this.id,
    required this.name,
    required this.classGroup,
    required this.subject,
    this.aliases = const [],
    this.active = true,
  });

  factory Student.fromJson(Map<String, dynamic> json) => Student(
        id: json['id'].toString(),
        name: json['name']?.toString() ?? '',
        classGroup: json['class_group']?.toString() ?? '',
        subject: json['subject']?.toString() ?? '',
        aliases: ((json['aliases'] as List<dynamic>?) ?? [])
            .map((item) => item.toString())
            .toList(),
        active: json['active'] != false,
      );
}

class PointsReportEntry {
  final String studentName;
  final String? studentId;
  final double totalPoints;
  final String subject;
  final String lessonDate;
  final List<LessonPoint> entries;

  PointsReportEntry({
    required this.studentName,
    required this.totalPoints,
    required this.subject,
    required this.lessonDate,
    this.studentId,
    this.entries = const [],
  });

  factory PointsReportEntry.fromJson(Map<String, dynamic> json) =>
      PointsReportEntry(
        studentName: json['student_name']?.toString() ?? '',
        studentId: json['student_id']?.toString(),
        totalPoints: _toDouble(json['total_points']),
        subject: json['subject']?.toString() ?? '',
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
  final String subject;
  final String lessonDate;
  final int sequence;
  final String content;

  TranscriptHit({
    required this.id,
    required this.score,
    required this.lessonId,
    required this.subject,
    required this.lessonDate,
    required this.sequence,
    required this.content,
  });

  factory TranscriptHit.fromJson(Map<String, dynamic> json) => TranscriptHit(
        id: json['id'].toString(),
        score: _toDouble(json['score']),
        lessonId: json['lesson_id']?.toString() ?? '',
        subject: json['subject']?.toString() ?? '',
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
        dimensions: json['dimensions'] == null
            ? null
            : _toInt(json['dimensions']),
        semantic: json['semantic'] == true,
        error: json['error']?.toString(),
      );
}

final education = EducationService(api);

/// Cliente da central de quizzes: fila de geracao, quizzes e banco de questoes.
///
/// A geracao nao prende mais a tela. O pedido vai para uma fila no servidor
/// (uma geracao por professor por vez), a central acompanha, e o aviso chega
/// quando termina. Quizzes e questoes ja gerados ficam consultaveis e
/// reaproveitaveis, em vez de sumirem depois da aula.
library;

import 'api_service.dart';

/// Estados de um pedido na fila, na ordem do fluxo.
abstract final class QuizJobStatus {
  static const queued = 'queued';
  static const running = 'running';
  static const done = 'done';
  static const error = 'error';
  static const canceled = 'canceled';
}

/// Estados de um quiz gravado.
abstract final class QuizStatus {
  static const draft = 'draft';
  static const open = 'open';
  static const closed = 'closed';
}

class QuizCenterException implements Exception {
  final String message;
  const QuizCenterException(this.message);

  @override
  String toString() => message;
}

List<Map<String, dynamic>> _maps(Object? value) => value is List
    ? value
        .whereType<Map>()
        .map((item) => item.map((k, v) => MapEntry(k.toString(), v)))
        .toList()
    : const [];

List<String> _strings(Object? value) => value is List
    ? value.map((item) => item.toString()).where((s) => s.isNotEmpty).toList()
    : const [];

DateTime? _date(Object? value) =>
    value == null ? null : DateTime.tryParse(value.toString())?.toLocal();

int _int(Object? value, [int fallback = 0]) =>
    value is num ? value.toInt() : int.tryParse('${value ?? ''}') ?? fallback;

/// Um pedido de geracao de quiz.
class QuizJob {
  final String id;
  final String status;
  final String titulo;
  final int total;
  final int prontas;
  final int? position;
  final String message;
  final String error;
  final String quizId;
  final List<Map<String, dynamic>> attempts;
  final DateTime? createdAt;
  final DateTime? finishedAt;
  final bool seen;
  final bool canCancel;
  final bool canRetry;
  final bool canReview;

  const QuizJob({
    required this.id,
    required this.status,
    required this.titulo,
    required this.total,
    this.prontas = 0,
    this.position,
    this.message = '',
    this.error = '',
    this.quizId = '',
    this.attempts = const [],
    this.createdAt,
    this.finishedAt,
    this.seen = false,
    this.canCancel = false,
    this.canRetry = false,
    this.canReview = false,
  });

  bool get isActive =>
      status == QuizJobStatus.queued || status == QuizJobStatus.running;

  /// Terminou de um jeito que merece aviso: pronto ou com erro.
  bool get needsNotice =>
      !seen && (status == QuizJobStatus.done || status == QuizJobStatus.error);

  double? get progress =>
      status == QuizJobStatus.running && total > 0 ? prontas / total : null;

  factory QuizJob.fromJson(Map<String, dynamic> json) => QuizJob(
        id: json['job_id']?.toString() ?? '',
        status: json['status']?.toString() ?? QuizJobStatus.queued,
        titulo: json['titulo']?.toString() ?? 'Quiz',
        total: _int(json['total'], 1),
        prontas: _int(json['prontas']),
        position: json['position'] == null ? null : _int(json['position']),
        message: json['message']?.toString() ?? '',
        error: json['error']?.toString() ?? '',
        quizId: json['quiz_id']?.toString() ?? '',
        attempts: _maps(json['attempts']),
        createdAt: _date(json['created_at']),
        finishedAt: _date(json['finished_at']),
        seen: json['seen'] == true,
        canCancel: json['can_cancel'] == true,
        canRetry: json['can_retry'] == true,
        canReview: json['can_review'] == true,
      );
}

class QuizJobsSnapshot {
  final List<QuizJob> jobs;
  final int active;
  final int unseen;

  const QuizJobsSnapshot({
    this.jobs = const [],
    this.active = 0,
    this.unseen = 0,
  });

  factory QuizJobsSnapshot.fromJson(Map<String, dynamic> json) =>
      QuizJobsSnapshot(
        jobs: _maps(json['jobs']).map(QuizJob.fromJson).toList(),
        active: _int(json['active']),
        unseen: _int(json['unseen']),
      );
}

/// Um quiz gravado, sem as questoes.
class QuizSummary {
  final String id;
  final String titulo;
  final String tipoQuiz;
  final String status;
  final int totalQuestoes;
  final List<String> disciplinas;
  final List<String> fontes;
  final DateTime? createdAt;

  const QuizSummary({
    required this.id,
    required this.titulo,
    required this.status,
    this.tipoQuiz = 'pratica',
    this.totalQuestoes = 0,
    this.disciplinas = const [],
    this.fontes = const [],
    this.createdAt,
  });

  factory QuizSummary.fromJson(Map<String, dynamic> json) => QuizSummary(
        id: json['id']?.toString() ?? '',
        titulo: json['titulo']?.toString() ?? 'Quiz',
        tipoQuiz: json['tipo_quiz']?.toString() ?? 'pratica',
        status: json['status']?.toString() ?? QuizStatus.open,
        totalQuestoes: _int(json['total_questoes']),
        disciplinas: _strings(json['disciplinas']),
        fontes: _maps(json['fontes'])
            .map((f) => f['label']?.toString() ?? '')
            .where((label) => label.isNotEmpty)
            .toList(),
        createdAt: _date(json['created_at']),
      );
}

/// Uma questao do banco, com o quiz de onde veio.
class BankQuestion {
  final String id;
  final String quizId;
  final String quizTitulo;
  final String quizStatus;
  final String tipo;
  final String dificuldade;
  final String enunciado;
  final List<Map<String, dynamic>> opcoes;
  final String respostaCorreta;
  final String justificativa;
  final String topicoOrigem;
  final List<String> conceitos;
  final bool verificado;
  final bool arquivada;
  final bool editavel;
  final List<String> disciplinas;

  const BankQuestion({
    required this.id,
    required this.quizId,
    required this.enunciado,
    this.quizTitulo = '',
    this.quizStatus = QuizStatus.open,
    this.tipo = 'multipla_escolha',
    this.dificuldade = 'medio',
    this.opcoes = const [],
    this.respostaCorreta = '',
    this.justificativa = '',
    this.topicoOrigem = '',
    this.conceitos = const [],
    this.verificado = true,
    this.arquivada = false,
    this.editavel = false,
    this.disciplinas = const [],
  });

  factory BankQuestion.fromJson(Map<String, dynamic> json) => BankQuestion(
        id: json['id']?.toString() ?? '',
        quizId: json['quiz_id']?.toString() ?? '',
        quizTitulo: json['quiz_titulo']?.toString() ?? '',
        quizStatus: json['quiz_status']?.toString() ?? QuizStatus.open,
        tipo: json['tipo']?.toString() ?? 'multipla_escolha',
        dificuldade: json['dificuldade']?.toString() ?? 'medio',
        enunciado: json['enunciado']?.toString() ?? '',
        opcoes: _maps(json['opcoes']),
        respostaCorreta: json['resposta_correta']?.toString() ?? '',
        justificativa: json['justificativa']?.toString() ?? '',
        topicoOrigem: json['topico_origem']?.toString() ?? '',
        conceitos: _strings(json['conceitos_relacionados']),
        verificado: json['verificado'] != false,
        arquivada: json['arquivada'] == true,
        editavel: json['editavel'] == true,
        disciplinas: _strings(json['disciplinas']),
      );

  /// Texto da alternativa correta, para mostrar na lista.
  String get correctText {
    for (final opcao in opcoes) {
      if (opcao['correta'] == true) return opcao['texto']?.toString() ?? '';
    }
    return respostaCorreta;
  }
}

class QuizListResult {
  final List<QuizSummary> quizzes;
  final List<String> disciplinas;
  const QuizListResult(this.quizzes, this.disciplinas);
}

class QuestionBankResult {
  final List<BankQuestion> questions;
  final int total;
  final List<String> disciplinas;
  const QuestionBankResult(this.questions, this.total, this.disciplinas);
}

/// Monta a query string sem os filtros vazios.
String withQuery(String path, Map<String, Object?> params) {
  final query = <String, String>{
    for (final entry in params.entries)
      if (entry.value != null && entry.value.toString().isNotEmpty)
        entry.key: entry.value.toString(),
  };
  if (query.isEmpty) return path;
  return Uri(path: path, queryParameters: query).toString();
}

class QuizCenterService {
  final ApiService api;
  const QuizCenterService(this.api);

  Future<Map<String, dynamic>> _ok(Future<GenericApiResponse> call) async {
    final response = await call;
    if (!response.success) {
      throw QuizCenterException(
        response.error ?? 'Não foi possível falar com o servidor.',
      );
    }
    return response.data;
  }

  // --- fila --------------------------------------------------------------

  Future<QuizJob> enqueue(Map<String, dynamic> request) async =>
      QuizJob.fromJson(
          await _ok(api.post('/education/quiz/generate/async', body: request)));

  Future<QuizJobsSnapshot> listJobs() async =>
      QuizJobsSnapshot.fromJson(await _ok(api.get('/education/quiz/jobs')));

  Future<QuizJob> cancelJob(String jobId) async => QuizJob.fromJson(await _ok(
      api.post('/education/quiz/jobs/$jobId/cancel', body: const {})));

  Future<QuizJob> retryJob(String jobId) async => QuizJob.fromJson(await _ok(
      api.post('/education/quiz/jobs/$jobId/retry', body: const {})));

  Future<void> markSeen(List<String> jobIds) async {
    if (jobIds.isEmpty) return;
    await _ok(api.post('/education/quiz/jobs/seen', body: {'job_ids': jobIds}));
  }

  // --- quizzes -----------------------------------------------------------

  Future<QuizListResult> listQuizzes({
    String status = '',
    String discipline = '',
    String search = '',
  }) async {
    final data = await _ok(api.get(withQuery('/education/quiz', {
      'status': status,
      'discipline': discipline,
      'q': search,
    })));
    return QuizListResult(
      _maps(data['quizzes']).map(QuizSummary.fromJson).toList(),
      _strings(data['disciplinas']),
    );
  }

  /// O quiz com as questoes, no formato da revisao.
  Future<Map<String, dynamic>> quizDetail(String quizId) =>
      _ok(api.get('/education/quiz/$quizId'));

  Future<Map<String, dynamic>> publishQuiz(String quizId) =>
      _ok(api.post('/education/quiz/$quizId/publish', body: const {}));

  Future<void> discardDraft(String quizId) async {
    await _ok(api.delete('/education/quiz/$quizId'));
  }

  // --- banco de questoes -------------------------------------------------

  Future<QuestionBankResult> listQuestions({
    String discipline = '',
    String search = '',
    String dificuldade = '',
    bool includeArchived = false,
    int limit = 50,
    int offset = 0,
  }) async {
    final data = await _ok(api.get(withQuery('/education/quiz/questions', {
      'discipline': discipline,
      'q': search,
      'dificuldade': dificuldade,
      'include_archived': includeArchived ? 'true' : '',
      'limit': limit,
      'offset': offset,
    })));
    return QuestionBankResult(
      _maps(data['questions']).map(BankQuestion.fromJson).toList(),
      _int(data['total']),
      _strings(data['disciplinas']),
    );
  }

  Future<BankQuestion> updateQuestion(
    String questionId,
    Map<String, dynamic> changes,
  ) async =>
      BankQuestion.fromJson(await _ok(
          api.patch('/education/quiz/questions/$questionId', body: changes)));

  /// Apaga (rascunho) ou arquiva (quiz ja liberado). Devolve se arquivou.
  Future<bool> removeQuestion(String questionId) async {
    final data =
        await _ok(api.delete('/education/quiz/questions/$questionId'));
    return data['archived'] == true;
  }

  Future<BankQuestion> restoreQuestion(String questionId) async =>
      BankQuestion.fromJson(await _ok(api.post(
          '/education/quiz/questions/$questionId/restore',
          body: const {})));

  Future<Map<String, dynamic>> createQuizFromQuestions({
    required String titulo,
    required List<String> questionIds,
    String tipoQuiz = 'pratica',
  }) =>
      _ok(api.post('/education/quiz/from-questions', body: {
        'titulo': titulo,
        'question_ids': questionIds,
        'tipo_quiz': tipoQuiz,
      }));
}

final quizCenter = QuizCenterService(api);

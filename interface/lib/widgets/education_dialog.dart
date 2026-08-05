import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../services/education_service.dart';
import '../utils/theme.dart';

class EducationDialog extends StatelessWidget {
  const EducationDialog({super.key});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1020, maxHeight: 760),
        child: DefaultTabController(
          length: 3,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 14, 10, 8),
                child: Row(
                  children: [
                    const Icon(Icons.school_outlined,
                        size: 18, color: AssistantTheme.c3),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        'MODO EDUCACAO',
                        style: TextStyle(
                          fontFamily: 'Rajdhani',
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 3,
                          color: AssistantTheme.textPrimary,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: 'Fechar',
                      icon: const Icon(Icons.close, size: 18),
                      color: AssistantTheme.textSecondary,
                      onPressed: () => Navigator.pop(context),
                    ),
                  ],
                ),
              ),
              const TabBar(
                indicatorColor: AssistantTheme.c3,
                labelColor: AssistantTheme.c3,
                unselectedLabelColor: AssistantTheme.textMuted,
                tabs: [
                  Tab(icon: Icon(Icons.mic_none, size: 17), text: 'AULA'),
                  Tab(
                      icon: Icon(Icons.emoji_events_outlined, size: 17),
                      text: 'PONTUACOES'),
                  Tab(icon: Icon(Icons.groups_outlined, size: 17), text: 'TURMA'),
                ],
              ),
              const Expanded(
                child: TabBarView(
                  children: [
                    _LessonTab(),
                    _PointsTab(),
                    _RosterTab(),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// --- Aula ------------------------------------------------------------------

class _LessonTab extends StatefulWidget {
  const _LessonTab();

  @override
  State<_LessonTab> createState() => _LessonTabState();
}

class _LessonTabState extends State<_LessonTab> {
  /// Duracao de cada bloco de audio enviado ao backend. Blocos curtos dao
  /// retorno rapido na tela; blocos longos gastam menos chamadas de STT.
  static const _chunkDuration = Duration(seconds: 60);

  final _recorder = AudioRecorder();
  final _subjectCtrl = TextEditingController();
  final _titleCtrl = TextEditingController();
  final _classCtrl = TextEditingController();
  final _focusCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();

  Lesson? _lesson;
  Timer? _chunkTimer;
  Timer? _clockTimer;
  String? _currentPath;
  DateTime? _startedAt;

  final _segments = <LessonSegment>[];
  final _points = <LessonPoint>[];
  final _pendingUploads = <_PendingChunk>[];

  var _recording = false;
  var _uploading = false;
  var _summarising = false;
  var _starting = false;
  var _elapsed = Duration.zero;
  var _status = '';
  String? _summary;
  EmbeddingStatus? _embedding;

  @override
  void initState() {
    super.initState();
    _loadEmbeddingStatus();
  }

  @override
  void dispose() {
    _chunkTimer?.cancel();
    _clockTimer?.cancel();
    // Sem await no dispose: o recorder e liberado em background.
    _recorder.dispose();
    _subjectCtrl.dispose();
    _titleCtrl.dispose();
    _classCtrl.dispose();
    _focusCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadEmbeddingStatus() async {
    try {
      final status = await education.embeddingStatus();
      if (mounted) setState(() => _embedding = status);
    } catch (_) {
      // Diagnostico e opcional; a aula funciona sem ele.
    }
  }

  void _setStatus(String message) {
    if (mounted) setState(() => _status = message);
  }

  // --- Ciclo da aula -------------------------------------------------------

  Future<void> _startLesson() async {
    final subject = _subjectCtrl.text.trim();
    if (subject.isEmpty) {
      _setStatus('Informe a disciplina antes de iniciar.');
      return;
    }
    if (!await _recorder.hasPermission()) {
      _setStatus('Microfone nao autorizado pelo sistema.');
      return;
    }

    setState(() => _starting = true);
    try {
      final lesson = await education.createLesson(
        subject: subject,
        title: _titleCtrl.text.trim(),
        classGroup: _classCtrl.text.trim(),
      );
      setState(() {
        _lesson = lesson;
        _segments.clear();
        _points.clear();
        _summary = null;
        _startedAt = DateTime.now();
        _elapsed = Duration.zero;
      });
      await _startRecordingLoop();
      _setStatus('Gravando. Cada bloco de 60s e transcrito e indexado.');
    } catch (e) {
      _setStatus('Nao foi possivel iniciar a aula: $e');
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  Future<void> _startRecordingLoop() async {
    await _startChunk();
    _chunkTimer?.cancel();
    _chunkTimer = Timer.periodic(_chunkDuration, (_) => _rotateChunk());
    _clockTimer?.cancel();
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted || _startedAt == null) return;
      setState(() => _elapsed = DateTime.now().difference(_startedAt!));
    });
    if (mounted) setState(() => _recording = true);
  }

  Future<void> _startChunk() async {
    final supportsWav = await _recorder.isEncoderSupported(AudioEncoder.wav);
    final encoder = supportsWav ? AudioEncoder.wav : AudioEncoder.aacLc;
    final extension = supportsWav ? 'wav' : 'm4a';
    final dir = await getTemporaryDirectory();
    _currentPath = '${dir.path}${Platform.pathSeparator}'
        'lesson_${DateTime.now().millisecondsSinceEpoch}.$extension';

    await _recorder.start(
      RecordConfig(
        encoder: encoder,
        sampleRate: 16000,
        numChannels: 1,
        noiseSuppress: true,
        echoCancel: true,
      ),
      path: _currentPath!,
    );
  }

  /// Fecha o bloco atual e ja abre o proximo, para nao perder a fala que
  /// acontece enquanto o trecho anterior sobe para o backend.
  Future<void> _rotateChunk({bool restart = true}) async {
    final path = await _recorder.stop();
    if (restart) {
      await _startChunk();
    } else {
      _currentPath = null;
    }
    if (path != null) {
      _pendingUploads.add(_PendingChunk(path, _chunkDuration.inMilliseconds));
      unawaited(_drainUploads());
    }
  }

  Future<void> _drainUploads() async {
    if (_uploading) return;
    _uploading = true;
    try {
      while (_pendingUploads.isNotEmpty) {
        final chunk = _pendingUploads.removeAt(0);
        await _uploadChunk(chunk);
      }
    } finally {
      _uploading = false;
      if (mounted) setState(() {});
    }
  }

  Future<void> _uploadChunk(_PendingChunk chunk) async {
    final lesson = _lesson;
    if (lesson == null) return;

    final file = File(chunk.path);
    try {
      if (!await file.exists()) return;
      final bytes = await file.readAsBytes();
      if (bytes.isEmpty) return;

      final result = await education.uploadAudioChunk(
        lesson.id,
        bytes,
        filename: chunk.path.split(Platform.pathSeparator).last,
        durationMs: chunk.durationMs,
      );

      if (!mounted) return;
      setState(() {
        _lesson = result.lesson;
        if (result.segment != null) _segments.add(result.segment!);
        _points.addAll(result.points);
      });
      if (result.points.isNotEmpty) {
        _setStatus('Pontuacao extra registrada: '
            '${result.points.map((p) => p.studentName).join(", ")}');
      } else if (result.skippedReason != null) {
        _setStatus('Bloco ignorado: ${result.skippedReason}');
      } else {
        _setStatus('Bloco ${result.segment?.sequence ?? "?"} transcrito.');
      }
      _scrollToEnd();
    } catch (e) {
      _setStatus('Falha ao enviar bloco: $e');
    } finally {
      try {
        if (await file.exists()) await file.delete();
      } catch (_) {
        // Arquivo temporario: o SO limpa depois.
      }
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.jumpTo(_scrollCtrl.position.maxScrollExtent);
      }
    });
  }

  Future<void> _stopRecording() async {
    _chunkTimer?.cancel();
    _clockTimer?.cancel();
    if (_recording) await _rotateChunk(restart: false);
    if (mounted) setState(() => _recording = false);
    _setStatus('Gravacao pausada. Envie o resumo quando quiser.');
  }

  Future<void> _resumeRecording() async {
    if (_lesson == null || _lesson!.isClosed) return;
    await _startRecordingLoop();
    _setStatus('Gravacao retomada.');
  }

  Future<void> _generateSummary({bool close = false}) async {
    final lesson = _lesson;
    if (lesson == null) return;

    if (_recording) await _stopRecording();
    // Espera os blocos pendentes chegarem ao backend, senao o resumo sai sem
    // o final da aula.
    while (_pendingUploads.isNotEmpty || _uploading) {
      _setStatus('Enviando blocos pendentes antes de resumir...');
      await Future.delayed(const Duration(milliseconds: 400));
    }

    setState(() => _summarising = true);
    _setStatus('Gerando resumo...');
    try {
      final summary = await education.generateSummary(
        lesson.id,
        focus: _focusCtrl.text.trim(),
        closeLesson: close,
      );
      if (!mounted) return;
      setState(() {
        _summary = summary.summary;
        _points
          ..clear()
          ..addAll(summary.points);
      });
      _setStatus('Resumo pronto (${summary.llm}, '
          '${summary.usedSegments} trechos).');
      if (close) {
        final refreshed = await education.getLesson(lesson.id,
            includeSegments: false);
        if (mounted) setState(() => _lesson = refreshed);
      }
    } catch (e) {
      _setStatus('Falha ao gerar resumo: $e');
    } finally {
      if (mounted) setState(() => _summarising = false);
    }
  }

  // --- UI ------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 12, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_embedding != null && !_embedding!.semantic)
            _Banner(
              icon: Icons.warning_amber_outlined,
              color: AssistantTheme.c4,
              text: 'Embeddings em modo hash: a busca nas aulas sera por '
                  'palavra exata. Configure EMBEDDING_PROVIDER no backend.',
            ),
          if (_embedding != null && _embedding!.semantic)
            _Banner(
              icon: Icons.check_circle_outline,
              color: AssistantTheme.c3,
              text: 'Embeddings ${_embedding!.provider}/'
                  '${_embedding!.model} (${_embedding!.dimensions} dims).',
            ),
          const SizedBox(height: 8),
          _lesson == null ? _buildStartForm() : _buildLiveHeader(),
          const SizedBox(height: 10),
          if (_status.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                _status,
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textSecondary),
              ),
            ),
          Expanded(
            child: _lesson == null
                ? const _EmptyState(
                    icon: Icons.mic_none,
                    text: 'Preencha a disciplina e inicie a aula.\n'
                        'O audio e enviado em blocos de 60s, transcrito e '
                        'indexado no Qdrant.',
                  )
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 3, child: _buildTranscript()),
                      const SizedBox(width: 14),
                      Expanded(flex: 2, child: _buildSidePanel()),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildStartForm() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          flex: 2,
          child: _Field(controller: _subjectCtrl, label: 'DISCIPLINA'),
        ),
        const SizedBox(width: 10),
        Expanded(
          flex: 2,
          child: _Field(controller: _titleCtrl, label: 'TEMA DA AULA'),
        ),
        const SizedBox(width: 10),
        Expanded(child: _Field(controller: _classCtrl, label: 'TURMA')),
        const SizedBox(width: 10),
        FilledButton.icon(
          onPressed: _starting ? null : _startLesson,
          icon: const Icon(Icons.fiber_manual_record, size: 15),
          label: Text(_starting ? 'INICIANDO...' : 'INICIAR AULA'),
          style: FilledButton.styleFrom(
            backgroundColor: AssistantTheme.c3,
            foregroundColor: AssistantTheme.bg,
          ),
        ),
      ],
    );
  }

  Widget _buildLiveHeader() {
    final lesson = _lesson!;
    final minutes = _elapsed.inMinutes.toString().padLeft(2, '0');
    final seconds = (_elapsed.inSeconds % 60).toString().padLeft(2, '0');

    return Row(
      children: [
        Icon(
          _recording ? Icons.fiber_manual_record : Icons.pause_circle_outline,
          size: 16,
          color: _recording ? AssistantTheme.danger : AssistantTheme.textMuted,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${lesson.subject}'
                '${lesson.title.isEmpty ? "" : " - ${lesson.title}"}',
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AssistantTheme.textPrimary,
                ),
              ),
              Text(
                '$minutes:$seconds  -  ${lesson.segmentCount} trechos  -  '
                '${lesson.transcriptChars} caracteres'
                '${_pendingUploads.isNotEmpty || _uploading ? "  -  enviando..." : ""}',
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textMuted),
              ),
            ],
          ),
        ),
        if (!lesson.isClosed)
          IconButton(
            tooltip: _recording ? 'Pausar gravacao' : 'Retomar gravacao',
            icon: Icon(_recording ? Icons.pause : Icons.play_arrow, size: 18),
            color: AssistantTheme.c1,
            onPressed: _recording ? _stopRecording : _resumeRecording,
          ),
        const SizedBox(width: 4),
        OutlinedButton.icon(
          onPressed: _summarising ? null : () => _generateSummary(),
          icon: const Icon(Icons.summarize_outlined, size: 15),
          label: Text(_summarising ? 'RESUMINDO...' : 'GERAR RESUMO'),
          style: OutlinedButton.styleFrom(
            foregroundColor: AssistantTheme.c2,
            side: const BorderSide(color: AssistantTheme.border2),
          ),
        ),
        const SizedBox(width: 8),
        if (!lesson.isClosed)
          FilledButton.icon(
            onPressed: _summarising ? null : () => _generateSummary(close: true),
            icon: const Icon(Icons.stop, size: 15),
            label: const Text('ENCERRAR'),
            style: FilledButton.styleFrom(
              backgroundColor: AssistantTheme.surface2,
              foregroundColor: AssistantTheme.textPrimary,
            ),
          ),
      ],
    );
  }

  Widget _buildTranscript() {
    if (_summary != null) {
      return _Panel(
        title: 'RESUMO DA AULA',
        trailing: TextButton(
          onPressed: () => setState(() => _summary = null),
          child: const Text('VER TRANSCRICAO', style: TextStyle(fontSize: 10)),
        ),
        child: SingleChildScrollView(
          child: SelectableText(
            _summary!,
            style: const TextStyle(
                fontSize: 12, height: 1.55, color: AssistantTheme.textPrimary),
          ),
        ),
      );
    }

    return _Panel(
      title: 'TRANSCRICAO AO VIVO',
      child: _segments.isEmpty
          ? const _EmptyState(
              icon: Icons.graphic_eq,
              text: 'O primeiro bloco aparece em ate 60 segundos.',
            )
          : ListView.separated(
              controller: _scrollCtrl,
              itemCount: _segments.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (_, index) {
                final segment = _segments[index];
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          'BLOCO ${segment.sequence}',
                          style: const TextStyle(
                              fontSize: 9,
                              letterSpacing: 1.5,
                              color: AssistantTheme.textMuted),
                        ),
                        const SizedBox(width: 6),
                        Icon(
                          segment.indexed
                              ? Icons.cloud_done_outlined
                              : Icons.cloud_off_outlined,
                          size: 11,
                          color: segment.indexed
                              ? AssistantTheme.c3
                              : AssistantTheme.c4,
                        ),
                      ],
                    ),
                    const SizedBox(height: 3),
                    SelectableText(
                      segment.text,
                      style: const TextStyle(
                          fontSize: 12,
                          height: 1.45,
                          color: AssistantTheme.textPrimary),
                    ),
                  ],
                );
              },
            ),
    );
  }

  Widget _buildSidePanel() {
    return Column(
      children: [
        Expanded(
          child: _Panel(
            title: 'PONTUACOES EXTRAS',
            child: _points.isEmpty
                ? const _EmptyState(
                    icon: Icons.emoji_events_outlined,
                    text: 'Nenhuma pontuacao citada ate agora.',
                  )
                : ListView.separated(
                    itemCount: _points.length,
                    separatorBuilder: (_, __) =>
                        const Divider(height: 14, color: AssistantTheme.border),
                    itemBuilder: (_, index) => _PointTile(
                      point: _points[index],
                      onDelete: () async {
                        try {
                          await education.deletePoint(_points[index].id);
                          setState(() => _points.removeAt(index));
                        } catch (e) {
                          _setStatus('Falha ao remover: $e');
                        }
                      },
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 10),
        _Field(
          controller: _focusCtrl,
          label: 'FOCO DO RESUMO (OPCIONAL)',
          hint: 'ex: datas de prova, formulas',
        ),
      ],
    );
  }
}

class _PendingChunk {
  final String path;
  final int durationMs;

  _PendingChunk(this.path, this.durationMs);
}

// --- Pontuacoes ------------------------------------------------------------

class _PointsTab extends StatefulWidget {
  const _PointsTab();

  @override
  State<_PointsTab> createState() => _PointsTabState();
}

class _PointsTabState extends State<_PointsTab> {
  final _subjectCtrl = TextEditingController();
  final _studentCtrl = TextEditingController();

  DateTime? _from;
  DateTime? _to;
  PointsReport? _report;
  var _loading = false;
  var _status = '';

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _from = DateTime(now.year, now.month, now.day);
    _to = _from;
    _load();
  }

  @override
  void dispose() {
    _subjectCtrl.dispose();
    _studentCtrl.dispose();
    super.dispose();
  }

  String? _iso(DateTime? date) => date?.toIso8601String().split('T').first;

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _status = '';
    });
    try {
      final report = await education.pointsReport(
        dateFrom: _iso(_from),
        dateTo: _iso(_to),
        subject: _subjectCtrl.text.trim(),
        studentName: _studentCtrl.text.trim(),
      );
      if (mounted) setState(() => _report = report);
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao carregar: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _pickDate({required bool isFrom}) async {
    final picked = await showDatePicker(
      context: context,
      initialDate: (isFrom ? _from : _to) ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime(2100),
    );
    if (picked == null) return;
    setState(() => isFrom ? _from = picked : _to = picked);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final report = _report;
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              _DateButton(
                label: 'DE',
                date: _from,
                onTap: () => _pickDate(isFrom: true),
              ),
              const SizedBox(width: 10),
              _DateButton(
                label: 'ATE',
                date: _to,
                onTap: () => _pickDate(isFrom: false),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _Field(
                  controller: _subjectCtrl,
                  label: 'DISCIPLINA',
                  onSubmitted: (_) => _load(),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _Field(
                  controller: _studentCtrl,
                  label: 'ALUNO',
                  onSubmitted: (_) => _load(),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton.icon(
                onPressed: _loading ? null : _load,
                icon: const Icon(Icons.search, size: 15),
                label: const Text('BUSCAR'),
                style: FilledButton.styleFrom(
                  backgroundColor: AssistantTheme.c3,
                  foregroundColor: AssistantTheme.bg,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (_status.isNotEmpty)
            Text(_status,
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.danger)),
          if (report != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                'TOTAL DISTRIBUIDO: ${_formatPoints(report.totalPoints)} '
                'pontos em ${report.students.length} registros',
                style: const TextStyle(
                    fontSize: 11,
                    letterSpacing: 1.2,
                    color: AssistantTheme.textSecondary),
              ),
            ),
          Expanded(
            child: report == null || report.students.isEmpty
                ? const _EmptyState(
                    icon: Icons.emoji_events_outlined,
                    text: 'Nenhuma pontuacao extra no periodo.',
                  )
                : ListView.separated(
                    itemCount: report.students.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, index) {
                      final entry = report.students[index];
                      return Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: AssistantTheme.bg2,
                          border: Border.all(color: AssistantTheme.border),
                          borderRadius: BorderRadius.circular(3),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    entry.studentName,
                                    style: const TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                      color: AssistantTheme.textPrimary,
                                    ),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    '${entry.subject} - ${entry.lessonDate}',
                                    style: const TextStyle(
                                        fontSize: 11,
                                        color: AssistantTheme.textMuted),
                                  ),
                                  ...entry.entries
                                      .where((item) => item.reason != null)
                                      .map((item) => Padding(
                                            padding:
                                                const EdgeInsets.only(top: 4),
                                            child: Text(
                                              '- ${item.reason}',
                                              style: const TextStyle(
                                                  fontSize: 11,
                                                  color: AssistantTheme
                                                      .textSecondary),
                                            ),
                                          )),
                                ],
                              ),
                            ),
                            Text(
                              '+${_formatPoints(entry.totalPoints)}',
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w700,
                                color: AssistantTheme.c3,
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

// --- Turma -----------------------------------------------------------------

class _RosterTab extends StatefulWidget {
  const _RosterTab();

  @override
  State<_RosterTab> createState() => _RosterTabState();
}

class _RosterTabState extends State<_RosterTab> {
  final _nameCtrl = TextEditingController();
  final _classCtrl = TextEditingController();
  final _subjectCtrl = TextEditingController();
  final _aliasCtrl = TextEditingController();

  List<Student> _students = [];
  var _loading = true;
  var _status = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _classCtrl.dispose();
    _subjectCtrl.dispose();
    _aliasCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final students = await education.listStudents();
      if (mounted) setState(() => _students = students);
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao carregar turma: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _add() async {
    final name = _nameCtrl.text.trim();
    if (name.isEmpty) {
      setState(() => _status = 'Informe o nome do aluno.');
      return;
    }
    try {
      await education.createStudent(
        name: name,
        classGroup: _classCtrl.text.trim(),
        subject: _subjectCtrl.text.trim(),
        aliases: _aliasCtrl.text
            .split(',')
            .map((item) => item.trim())
            .where((item) => item.isNotEmpty)
            .toList(),
      );
      _nameCtrl.clear();
      _aliasCtrl.clear();
      setState(() => _status = '');
      await _load();
    } catch (e) {
      setState(() => _status = 'Falha ao cadastrar: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'O cadastro ancora os nomes ouvidos no audio. Sem ele, nomes '
            'proprios saem com a grafia que o transcritor entendeu.',
            style: TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
          ),
          const SizedBox(height: 12),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                flex: 2,
                child: _Field(controller: _nameCtrl, label: 'NOME COMPLETO'),
              ),
              const SizedBox(width: 10),
              Expanded(child: _Field(controller: _classCtrl, label: 'TURMA')),
              const SizedBox(width: 10),
              Expanded(
                child: _Field(controller: _subjectCtrl, label: 'DISCIPLINA'),
              ),
              const SizedBox(width: 10),
              Expanded(
                flex: 2,
                child: _Field(
                  controller: _aliasCtrl,
                  label: 'APELIDOS (SEPARADOS POR VIRGULA)',
                  onSubmitted: (_) => _add(),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton.icon(
                onPressed: _add,
                icon: const Icon(Icons.person_add_alt, size: 15),
                label: const Text('ADICIONAR'),
                style: FilledButton.styleFrom(
                  backgroundColor: AssistantTheme.c3,
                  foregroundColor: AssistantTheme.bg,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (_status.isNotEmpty)
            Text(_status,
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.danger)),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _students.isEmpty
                    ? const _EmptyState(
                        icon: Icons.groups_outlined,
                        text: 'Nenhum aluno cadastrado.',
                      )
                    : ListView.separated(
                        itemCount: _students.length,
                        separatorBuilder: (_, __) => const Divider(
                            height: 12, color: AssistantTheme.border),
                        itemBuilder: (_, index) {
                          final student = _students[index];
                          final tags = [
                            if (student.classGroup.isNotEmpty)
                              student.classGroup,
                            if (student.subject.isNotEmpty) student.subject,
                            if (student.aliases.isNotEmpty)
                              'apelidos: ${student.aliases.join(", ")}',
                          ].join('  -  ');

                          return Row(
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      student.name,
                                      style: const TextStyle(
                                        fontSize: 13,
                                        color: AssistantTheme.textPrimary,
                                      ),
                                    ),
                                    if (tags.isNotEmpty)
                                      Text(
                                        tags,
                                        style: const TextStyle(
                                            fontSize: 10,
                                            color: AssistantTheme.textMuted),
                                      ),
                                  ],
                                ),
                              ),
                              IconButton(
                                tooltip: 'Remover',
                                icon: const Icon(Icons.delete_outline, size: 16),
                                color: AssistantTheme.textMuted,
                                onPressed: () async {
                                  try {
                                    await education.deleteStudent(student.id);
                                    await _load();
                                  } catch (e) {
                                    setState(() =>
                                        _status = 'Falha ao remover: $e');
                                  }
                                },
                              ),
                            ],
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}

// --- Componentes compartilhados --------------------------------------------

String _formatPoints(double value) {
  final rounded = value.toStringAsFixed(2);
  return rounded.endsWith('.00')
      ? rounded.substring(0, rounded.length - 3)
      : rounded;
}

class _Field extends StatelessWidget {
  final TextEditingController controller;
  final String label;
  final String? hint;
  final ValueChanged<String>? onSubmitted;

  const _Field({
    required this.controller,
    required this.label,
    this.hint,
    this.onSubmitted,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 9,
            letterSpacing: 1.5,
            color: AssistantTheme.textMuted,
          ),
        ),
        const SizedBox(height: 4),
        TextField(
          controller: controller,
          onSubmitted: onSubmitted,
          style: const TextStyle(
              fontSize: 12, color: AssistantTheme.textPrimary),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: const TextStyle(
                fontSize: 11, color: AssistantTheme.textMuted),
            isDense: true,
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
            filled: true,
            fillColor: AssistantTheme.bg2,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(3),
              borderSide: const BorderSide(color: AssistantTheme.border),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(3),
              borderSide: const BorderSide(color: AssistantTheme.border),
            ),
          ),
        ),
      ],
    );
  }
}

class _DateButton extends StatelessWidget {
  final String label;
  final DateTime? date;
  final VoidCallback onTap;

  const _DateButton({
    required this.label,
    required this.date,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final text = date == null
        ? '--'
        : '${date!.day.toString().padLeft(2, '0')}/'
            '${date!.month.toString().padLeft(2, '0')}/${date!.year}';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
              fontSize: 9, letterSpacing: 1.5, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 4),
        OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
            foregroundColor: AssistantTheme.textPrimary,
            side: const BorderSide(color: AssistantTheme.border),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          ),
          child: Text(text, style: const TextStyle(fontSize: 12)),
        ),
      ],
    );
  }
}

class _Panel extends StatelessWidget {
  final String title;
  final Widget child;
  final Widget? trailing;

  const _Panel({required this.title, required this.child, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AssistantTheme.bg2,
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 9,
                    letterSpacing: 2,
                    color: AssistantTheme.textMuted,
                  ),
                ),
              ),
              trailing ?? const SizedBox.shrink(),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(child: child),
        ],
      ),
    );
  }
}

class _PointTile extends StatelessWidget {
  final LessonPoint point;
  final VoidCallback onDelete;

  const _PointTile({required this.point, required this.onDelete});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Flexible(
                    child: Text(
                      point.studentName,
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AssistantTheme.textPrimary,
                      ),
                    ),
                  ),
                  if (point.needsReview) ...[
                    const SizedBox(width: 5),
                    const Tooltip(
                      message: 'Nome nao encontrado no cadastro da turma',
                      child: Icon(Icons.help_outline,
                          size: 12, color: AssistantTheme.c4),
                    ),
                  ],
                ],
              ),
              if (point.reason != null)
                Text(
                  point.reason!,
                  style: const TextStyle(
                      fontSize: 10, color: AssistantTheme.textSecondary),
                ),
            ],
          ),
        ),
        Text(
          '+${_formatPoints(point.points)}',
          style: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: AssistantTheme.c3,
          ),
        ),
        IconButton(
          tooltip: 'Remover',
          icon: const Icon(Icons.close, size: 13),
          color: AssistantTheme.textMuted,
          padding: EdgeInsets.zero,
          constraints: const BoxConstraints(minWidth: 26, minHeight: 26),
          onPressed: onDelete,
        ),
      ],
    );
  }
}

class _Banner extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String text;

  const _Banner({required this.icon, required this.color, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        border: Border.all(color: color.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Row(
        children: [
          Icon(icon, size: 13, color: color),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              text,
              style: TextStyle(fontSize: 10, color: color),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final IconData icon;
  final String text;

  const _EmptyState({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 26, color: AssistantTheme.textMuted),
          const SizedBox(height: 8),
          Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(
                fontSize: 11, height: 1.5, color: AssistantTheme.textMuted),
          ),
        ],
      ),
    );
  }
}

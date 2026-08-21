import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:printing/printing.dart';
import 'package:record/record.dart';

import '../models/app_config.dart';
import '../services/api_service.dart';
import '../services/audio_input_service.dart';
import '../services/connected_ai_service.dart';
import '../services/education_service.dart';
import '../services/in_app_notification_service.dart';
import '../services/lesson_pdf_service.dart';
import '../services/student_csv_parser.dart';
import 'summary_pickers.dart';
import '../providers/app_provider.dart';
import '../branding/intarq_brand.dart';
import '../utils/theme.dart';
import 'attendance_tab.dart';
import 'education_dashboard.dart';
import 'quiz_generator_widget.dart';
import 'quiz_qrcode_monitor.dart';
import 'sia_attendance_importer.dart';

/// Ordem das abas: e tambem a ordem de uso. Sem turma cadastrada os nomes
/// ouvidos na aula nao casam com ninguem, entao a turma vem antes.
const _dashboardTab = 0;
const _rosterTab = 1;
const _lessonTab = 2;
const _pointsTab = 3;
const _historyTab = 4;
const _attendanceTab = 5;

/// Turmas conhecidas pelo backend, compartilhadas entre as abas. `null` = a
/// lista ainda nao chegou.
typedef _Classes = ValueNotifier<List<ClassGroup>?>;

class EducationDialog extends StatefulWidget {
  final String startAt;

  const EducationDialog({super.key, this.startAt = 'auto'});

  @override
  State<EducationDialog> createState() => _EducationDialogState();
}

class _EducationDialogState extends State<EducationDialog> {
  /// Turmas compartilhadas entre as abas: TURMA escreve, AULA e PONTUACOES
  /// leem. Uma fonte so evita as duas pontas divergirem.
  final _Classes _classes = ValueNotifier<List<ClassGroup>?>(null);

  int? _initialTab;

  @override
  void initState() {
    super.initState();
    _resolveInitialTab();
  }

  @override
  void dispose() {
    _classes.dispose();
    super.dispose();
  }

  /// Primeira vez (sem turma cadastrada) abre no cadastro. O acesso comum
  /// mostra a visao geral; comandos de aula e chamada continuam abrindo a aba
  /// operacional correspondente.
  Future<void> _resolveInitialTab() async {
    List<ClassGroup>? classes;
    try {
      classes = await education.listClasses();
    } catch (_) {
      // Sem resposta nao da para saber se e a primeira vez: abre na aula.
    }
    if (!mounted) return;
    _classes.value = classes;
    setState(() {
      if (classes != null && classes.isEmpty) {
        _initialTab = _rosterTab;
      } else if (widget.startAt == 'attendance') {
        _initialTab = _attendanceTab;
      } else if (widget.startAt == 'lesson') {
        _initialTab = _lessonTab;
      } else {
        _initialTab = _dashboardTab;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final initialTab = _initialTab;

    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1160, maxHeight: 820),
        child: Column(
          children: [
            _buildHeader(context),
            if (initialTab == null)
              const Expanded(child: Center(child: CircularProgressIndicator()))
            else
              Expanded(
                child: DefaultTabController(
                  length: 7,
                  initialIndex: initialTab,
                  child: Builder(
                    builder: (tabContext) => Column(
                      children: [
                        const TabBar(
                          isScrollable: true,
                          indicatorColor: AssistantTheme.c3,
                          labelColor: AssistantTheme.c3,
                          unselectedLabelColor: AssistantTheme.textMuted,
                          tabs: [
                            Tab(
                                icon: Icon(Icons.dashboard_outlined, size: 17),
                                text: 'VISAO GERAL'),
                            Tab(
                                icon: Icon(Icons.groups_outlined, size: 17),
                                text: '1. TURMAS'),
                            Tab(
                                icon: Icon(Icons.mic_none, size: 17),
                                text: '2. GRAVAR AULA'),
                            Tab(
                                icon:
                                    Icon(Icons.emoji_events_outlined, size: 17),
                                text: '3. PONTUACOES'),
                            Tab(
                                icon: Icon(Icons.history, size: 17),
                                text: '4. HISTORICO'),
                            Tab(
                                icon: Icon(Icons.how_to_reg_outlined, size: 17),
                                text: '5. PRESENCA'),
                            Tab(
                                icon: Icon(Icons.cloud_sync_outlined, size: 17),
                                text: '6. INTEGRACOES'),
                          ],
                        ),
                        Expanded(
                          child: TabBarView(
                            children: [
                              EducationDashboard(
                                classes: _classes,
                                onOpenClasses: () =>
                                    DefaultTabController.of(tabContext)
                                        .animateTo(_rosterTab),
                                onOpenPoints: () =>
                                    DefaultTabController.of(tabContext)
                                        .animateTo(_pointsTab),
                                onOpenHistory: () =>
                                    DefaultTabController.of(tabContext)
                                        .animateTo(_historyTab),
                                onOpenAttendance: () =>
                                    DefaultTabController.of(tabContext)
                                        .animateTo(_attendanceTab),
                                onStartLesson: () =>
                                    DefaultTabController.of(tabContext)
                                        .animateTo(_lessonTab),
                                onOpenAssistant: () =>
                                    Navigator.of(tabContext).pop(),
                              ),
                              _RosterTab(classes: _classes),
                              _LessonTab(classes: _classes),
                              _PointsTab(classes: _classes),
                              _HistoryTab(classes: _classes),
                              AttendanceTab(classes: _classes),
                              _IntegrationsTab(classes: _classes),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 10, 8),
      child: Row(
        children: [
          const IntarqMark(size: 36),
          const SizedBox(width: 10),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'MODO EDUCAÇÃO',
                  style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 3,
                    color: AssistantTheme.c2,
                  ),
                ),
                Text(
                  'Cadastre a turma, grave a aula e distribua pontos falando '
                  'o nome do aluno.',
                  style: TextStyle(
                      fontSize: 11, color: AssistantTheme.textSecondary),
                ),
              ],
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
    );
  }
}

// --- Aula ------------------------------------------------------------------

class _LessonTab extends ConsumerStatefulWidget {
  final _Classes classes;

  const _LessonTab({required this.classes});

  @override
  ConsumerState<_LessonTab> createState() => _LessonTabState();
}

class _LessonTabState extends ConsumerState<_LessonTab> {
  /// Duracao de cada bloco de audio enviado ao backend. Blocos curtos dao
  /// retorno rapido na tela; blocos longos gastam menos chamadas de STT.
  static const _chunkDuration = Duration(seconds: 60);

  final _recorder = AudioRecorder();
  final _titleCtrl = TextEditingController();
  final _focusCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();

  Lesson? _lesson;
  Timer? _chunkTimer;
  Timer? _clockTimer;
  Timer? _retryTimer;
  Timer? _sessionTimer;
  String? _currentPath;
  DateTime? _startedAt;
  InputDevice? _activeInputDevice;
  String _activeInputLabel = 'padrao do sistema';

  final _segments = <LessonSegment>[];
  final _points = <LessonPoint>[];
  final _pendingUploads = <_PendingChunk>[];

  var _recording = false;
  var _uploading = false;
  var _summarising = false;
  var _starting = false;
  var _sessionExpired = false;
  var _elapsed = Duration.zero;
  var _status = '';
  var _summaryStyle = summaryStyleStandard;
  /// Quem escreve o resumo: '' = fila automatica do backend.
  var _summaryEngine = '';
  String? _summary;
  /// Formato do resumo exibido no painel, que pode diferir do escolhido para
  /// a proxima geracao.
  String? _summaryShownStyle;
  EmbeddingStatus? _embedding;

  /// Turmas atendidas pela aula. Mais de uma e aula reunida.
  final _selected = <String>{};

  @override
  void initState() {
    super.initState();
    _loadEmbeddingStatus();
    _preselectSingleClass(widget.classes.value);
    widget.classes.addListener(_onClassesChanged);
  }

  @override
  void dispose() {
    widget.classes.removeListener(_onClassesChanged);
    _chunkTimer?.cancel();
    _clockTimer?.cancel();
    _retryTimer?.cancel();
    _sessionTimer?.cancel();
    // Sem await no dispose: o recorder e liberado em background.
    _recorder.dispose();
    _titleCtrl.dispose();
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

  void _onClassesChanged() {
    if (!mounted) return;
    setState(() => _preselectSingleClass(widget.classes.value));
  }

  /// Marca sozinho o que o horario ja diz: as turmas que tem aula hoje. Com
  /// uma turma so, marca ela mesmo sem horario cadastrado.
  void _preselectSingleClass(List<ClassGroup>? classes) {
    if (_selected.isNotEmpty || classes == null || classes.isEmpty) return;
    final today = DateTime.now().weekday;
    final scheduled =
        classes.where((item) => item.meetsOn(today)).map((item) => item.id);
    if (scheduled.isNotEmpty) {
      _selected.addAll(scheduled);
    } else if (classes.length == 1) {
      _selected.add(classes.first.id);
    }
  }

  List<ClassGroup> get _chosen {
    final classes = widget.classes.value ?? const <ClassGroup>[];
    return classes.where((item) => _selected.contains(item.id)).toList();
  }

  // --- Ciclo da aula -------------------------------------------------------

  Future<void> _startLesson() async {
    final chosen = _chosen;
    if (chosen.isEmpty) {
      _setStatus('Selecione a turma antes de iniciar.');
      return;
    }
    final disciplines = chosen.map((item) => item.discipline).toSet();
    final discipline = disciplines.length == 1 ? disciplines.first : '';
    if (discipline.isEmpty) {
      _setStatus('As turmas escolhidas sao de disciplinas diferentes.');
      return;
    }
    final semesters = chosen.map((item) => item.semester).toSet();
    if (semesters.length > 1) {
      _setStatus('As turmas escolhidas sao de semestres diferentes.');
      return;
    }
    if (!await _recorder.hasPermission()) {
      _setStatus('Microfone nao autorizado pelo sistema.');
      return;
    }

    setState(() => _starting = true);
    try {
      await _resolveInputDevice();
      // Aula de duas horas nao pode esbarrar no fim do token no meio.
      await api.refreshSession();
      final lesson = await education.createLesson(
        discipline: discipline,
        semester:
            semesters.length == 1 ? semesters.first : _currentSemesterCode(),
        title: _titleCtrl.text.trim(),
        classIds: chosen.map((item) => item.id).toList(),
      );
      setState(() {
        _lesson = lesson;
        _segments.clear();
        _points.clear();
        _summary = null;
        _summaryShownStyle = null;
        _startedAt = DateTime.now();
        _elapsed = Duration.zero;
      });
      await _startRecordingLoop();
      _setStatus('Gravando com $_activeInputLabel. Cada bloco de 60s e '
          'transcrito e indexado.');
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
    _sessionTimer?.cancel();
    _sessionTimer = Timer.periodic(
      const Duration(minutes: 20),
      (_) => unawaited(api.refreshSession()),
    );
    if (mounted) setState(() => _recording = true);
  }

  Future<void> _resolveInputDevice() async {
    final config = ref.read(configProvider);
    final devices = await _recorder.listInputDevices();
    final selected = resolveAudioInputDevice(
      devices,
      deviceId: config.audioInputDeviceId,
      deviceLabel: config.audioInputDeviceLabel,
    );
    if (config.audioInputDeviceId.isNotEmpty && selected == null) {
      final name = config.audioInputDeviceLabel.trim().isEmpty
          ? 'selecionado'
          : config.audioInputDeviceLabel.trim();
      throw Exception(
        'o microfone $name nao esta disponivel. Conecte-o ou escolha outro '
        'em Configuracoes > Sistema',
      );
    }
    _activeInputDevice = selected;
    _activeInputLabel = selected?.label ?? 'padrao do sistema';
  }

  Future<void> _startChunk() async {
    final supportsWav = await _recorder.isEncoderSupported(AudioEncoder.wav);
    final encoder = supportsWav ? AudioEncoder.wav : AudioEncoder.aacLc;
    final extension = supportsWav ? 'wav' : 'm4a';
    final dir = await getTemporaryDirectory();
    _currentPath = '${dir.path}${Platform.pathSeparator}'
        'lesson_${DateTime.now().millisecondsSinceEpoch}.$extension';

    await _recorder.start(
      speechRecordConfig(encoder: encoder, device: _activeInputDevice),
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

  /// Envia a fila em ordem. Bloco que falha continua na fila: perder audio de
  /// aula por queda de rede ou sessao expirada nao tem volta.
  Future<void> _drainUploads() async {
    if (_uploading) return;
    _uploading = true;
    try {
      while (_pendingUploads.isNotEmpty) {
        if (!await _uploadChunk(_pendingUploads.first)) {
          _scheduleRetry();
          return;
        }
        _pendingUploads.removeAt(0);
      }
      _retryTimer?.cancel();
      _retryTimer = null;
    } finally {
      _uploading = false;
      if (mounted) setState(() {});
    }
  }

  void _scheduleRetry() {
    _retryTimer?.cancel();
    _retryTimer = Timer.periodic(
      const Duration(seconds: 20),
      (_) => unawaited(_drainUploads()),
    );
  }

  /// `true` quando o bloco pode sair da fila — enviado, vazio ou sumido.
  Future<bool> _uploadChunk(_PendingChunk chunk) async {
    final lesson = _lesson;
    if (lesson == null) return false;

    final file = File(chunk.path);
    try {
      if (!await file.exists()) return true;
      final bytes = await file.readAsBytes();
      if (bytes.isEmpty) {
        await _discard(file);
        return true;
      }

      final result = await education.uploadAudioChunk(
        lesson.id,
        bytes,
        filename: chunk.path.split(Platform.pathSeparator).last,
        durationMs: chunk.durationMs,
      );

      await _discard(file);
      if (!mounted) return true;
      setState(() {
        _lesson = result.lesson;
        _sessionExpired = false;
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
      return true;
    } catch (e) {
      if ('$e'.contains('HTTP 401')) return _handleExpiredSession();
      _setStatus('Falha ao enviar bloco, tentando de novo: $e');
      return false;
    }
  }

  /// Sessao expirada no meio da aula: tenta renovar em silencio e so incomoda
  /// o professor se nao der. O audio fica na fila em qualquer caso.
  Future<bool> _handleExpiredSession() async {
    if (await api.refreshSession()) {
      _setStatus('Sessao renovada, reenviando o bloco...');
      return false;
    }
    if (mounted) setState(() => _sessionExpired = true);
    _setStatus('Sessao expirada. Faca login de novo: '
        '${_pendingUploads.length} bloco(s) seguem guardados aqui.');
    return false;
  }

  Future<void> _discard(File file) async {
    try {
      if (await file.exists()) await file.delete();
    } catch (_) {
      // Arquivo temporario: o SO limpa depois.
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
    _sessionTimer?.cancel();
    if (_recording) await _rotateChunk(restart: false);
    if (mounted) setState(() => _recording = false);
    _setStatus('Gravacao pausada. Envie o resumo quando quiser.');
  }

  Future<void> _resumeRecording() async {
    if (_lesson == null || _lesson!.isClosed) return;
    try {
      await _resolveInputDevice();
      await _startRecordingLoop();
      _setStatus('Gravacao retomada com $_activeInputLabel.');
    } catch (e) {
      _setStatus('Nao foi possivel retomar a gravacao: $e');
    }
  }

  Future<void> _generateSummary({bool close = false}) async {
    final lesson = _lesson;
    if (lesson == null) return;

    if (_recording) await _stopRecording();
    // Espera os blocos pendentes chegarem ao backend, senao o resumo sai sem
    // o final da aula. Com a fila travada (sessao caida, backend fora) o
    // resumo sai assim mesmo em vez de esperar para sempre.
    final deadline = DateTime.now().add(const Duration(seconds: 90));
    while ((_pendingUploads.isNotEmpty || _uploading) &&
        DateTime.now().isBefore(deadline)) {
      _setStatus('Enviando blocos pendentes antes de resumir...');
      await Future.delayed(const Duration(milliseconds: 400));
    }
    if (_pendingUploads.isNotEmpty) {
      _setStatus('${_pendingUploads.length} bloco(s) ainda nao subiram; '
          'o resumo sai sem eles.');
    }

    setState(() => _summarising = true);
    final quem = summaryEngineLabel(_summaryEngine, ref.read(configProvider));
    _setStatus(_summaryStyle == summaryStyleDetailed
        ? 'Gerando resumo detalhado com $quem (leva mais tempo)...'
        : 'Gerando resumo com $quem...');
    try {
      final summary = await _runSummary(
        lessonId: lesson.id,
        style: _summaryStyle,
        engine: _summaryEngine,
        config: ref.read(configProvider),
        focus: _focusCtrl.text.trim(),
        closeLesson: close,
        onProgress: _setStatus,
      );
      InAppNotificationService.showSummaryReady(
        discipline: lesson.discipline,
        title: lesson.title,
        llm: summaryEngineLabel(summary.llm, ref.read(configProvider)),
        usedSegments: summary.usedSegments,
        style: summary.style,
      );
      if (!mounted) return;
      setState(() {
        _summary = summary.summary;
        _summaryShownStyle = summary.style;
        _points
          ..clear()
          ..addAll(summary.points);
      });
      _setStatus('Resumo ${summaryStyleLabel(summary.style).toLowerCase()} '
          'pronto (${summaryEngineLabel(summary.llm, ref.read(configProvider))}, '
          '${summary.usedSegments} trechos).');
      if (close) {
        final refreshed =
            await education.getLesson(lesson.id, includeSegments: false);
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
          _buildAlerts(),
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
                ? const _HowItWorks()
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

  /// Avisos que mudam o resultado da aula: fila de envio parada, turma sem
  /// aluno e busca sem embedding semantico.
  Widget _buildAlerts() {
    return ValueListenableBuilder<List<ClassGroup>?>(
      valueListenable: widget.classes,
      builder: (context, classes, _) {
        final students = (classes ?? const <ClassGroup>[])
            .fold<int>(0, (total, item) => total + item.studentCount);
        final banners = <Widget>[
          if (_sessionExpired || _pendingUploads.isNotEmpty)
            _Banner(
              icon: _sessionExpired
                  ? Icons.lock_clock_outlined
                  : Icons.cloud_upload_outlined,
              color:
                  _sessionExpired ? AssistantTheme.danger : AssistantTheme.c4,
              text: _sessionExpired
                  ? 'Sessao expirada. Entre de novo na conta: os '
                      '${_pendingUploads.length} bloco(s) da aula estao '
                      'guardados e sobem quando a sessao voltar.'
                  : '${_pendingUploads.length} bloco(s) na fila de envio.',
              action: TextButton(
                onPressed: _uploading
                    ? null
                    : () async {
                        if (await api.refreshSession()) {
                          if (mounted) setState(() => _sessionExpired = false);
                        }
                        unawaited(_drainUploads());
                      },
                child: const Text('REENVIAR', style: TextStyle(fontSize: 10)),
              ),
            ),
          if (classes != null && students == 0)
            _Banner(
              icon: Icons.groups_outlined,
              color: AssistantTheme.c4,
              text: classes.isEmpty
                  ? 'Nenhuma turma cadastrada. Sem turma nao ha nomes para '
                      'ancorar a transcricao da aula.'
                  : 'As turmas cadastradas estao sem alunos. Importe a lista '
                      'antes da aula.',
              action: TextButton(
                onPressed: () =>
                    DefaultTabController.of(context).animateTo(_rosterTab),
                child:
                    const Text('ABRIR TURMAS', style: TextStyle(fontSize: 10)),
              ),
            ),
          if (_embedding != null && !_embedding!.semantic)
            _Banner(
              icon: Icons.search_off_outlined,
              color: AssistantTheme.c4,
              text: 'Busca por conteudo indisponivel: a aula fica gravada, mas '
                  'perguntas no chat so acham palavra exata.',
              tooltip: 'Embeddings em modo hash '
                  '(provedor: ${_embedding!.provider}). '
                  'Configure EMBEDDING_PROVIDER no backend.',
            ),
        ];

        if (banners.isEmpty) return const SizedBox(height: 4);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final banner in banners) ...[
              banner,
              const SizedBox(height: 6),
            ],
          ],
        );
      },
    );
  }

  Widget _buildStartForm() {
    return ValueListenableBuilder<List<ClassGroup>?>(
      valueListenable: widget.classes,
      builder: (context, classes, _) {
        final available = classes ?? const <ClassGroup>[];
        final weekday = DateTime.now().weekday;
        final today = available.where((item) => item.meetsOn(weekday)).toList();
        final others =
            available.where((item) => !item.meetsOn(weekday)).toList();
        final chosen = _chosen;
        final students = chosen.fold<int>(
          0,
          (total, item) => total + item.studentCount,
        );

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  flex: 2,
                  child: _Field(controller: _titleCtrl, label: 'TEMA DA AULA'),
                ),
                const SizedBox(width: 10),
                FilledButton.icon(
                  onPressed: _starting || chosen.isEmpty ? null : _startLesson,
                  icon: const Icon(Icons.fiber_manual_record, size: 15),
                  label: Text(_starting ? 'INICIANDO...' : 'INICIAR AULA'),
                  style: FilledButton.styleFrom(
                    backgroundColor: AssistantTheme.c3,
                    foregroundColor: AssistantTheme.bg,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              chosen.isEmpty
                  ? 'TURMAS DESTA AULA'
                  : 'TURMAS DESTA AULA  -  $students ALUNO'
                      '${students == 1 ? "" : "S"}'
                      '${chosen.length > 1 ? "  -  AULA REUNIDA" : ""}',
              style: const TextStyle(
                fontSize: 9,
                letterSpacing: 1.5,
                color: AssistantTheme.textMuted,
              ),
            ),
            const SizedBox(height: 6),
            if (available.isEmpty)
              Text(
                classes == null
                    ? 'Carregando turmas...'
                    : 'Cadastre uma turma na aba TURMAS para iniciar a aula.',
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textMuted),
              )
            else ...[
              if (today.isNotEmpty) ...[
                Text(
                  'HOJE, ${_weekdayName(DateTime.now().weekday).toUpperCase()}',
                  style: const TextStyle(
                    fontSize: 9,
                    letterSpacing: 1.5,
                    color: AssistantTheme.c3,
                  ),
                ),
                const SizedBox(height: 6),
                _buildClassChips(today),
                const SizedBox(height: 10),
              ],
              if (others.isNotEmpty) ...[
                Text(
                  today.isEmpty ? '' : 'OUTRAS TURMAS',
                  style: const TextStyle(
                    fontSize: 9,
                    letterSpacing: 1.5,
                    color: AssistantTheme.textMuted,
                  ),
                ),
                if (today.isNotEmpty) const SizedBox(height: 6),
                _buildClassChips(others),
              ],
            ],
            if (available.length > 1)
              const Padding(
                padding: EdgeInsets.only(top: 6),
                child: Text(
                  'Marque mais de uma turma quando a aula for reunida: os '
                  'alunos de todas entram no reconhecimento de nomes e a '
                  'pontuacao continua separada por turma no relatorio.',
                  style:
                      TextStyle(fontSize: 10, color: AssistantTheme.textMuted),
                ),
              ),
          ],
        );
      },
    );
  }

  Widget _buildClassChips(List<ClassGroup> groups) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final group in groups)
          FilterChip(
            selected: _selected.contains(group.id),
            onSelected: (on) => setState(() {
              if (on) {
                _selected.add(group.id);
              } else {
                _selected.remove(group.id);
              }
            }),
            label: Text(
              '${group.display}  (${group.studentCount})'
              '${group.scheduleLabel.isEmpty ? "" : "  ${group.scheduleLabel}"}',
              style: const TextStyle(fontSize: 11),
            ),
            backgroundColor: AssistantTheme.bg2,
            selectedColor: AssistantTheme.c3.withValues(alpha: 0.22),
            checkmarkColor: AssistantTheme.c3,
            side: const BorderSide(color: AssistantTheme.border),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(3),
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
                '${lesson.discipline}'
                '${lesson.title.isEmpty ? "" : " - ${lesson.title}"}',
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AssistantTheme.textPrimary,
                ),
              ),
              Text(
                '${lesson.classGroup.isEmpty ? "" : "turma "
                    "${lesson.classGroup}  -  "}'
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
            onPressed:
                _summarising ? null : () => _generateSummary(close: true),
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
        title: 'RESUMO DA AULA  -  ${summaryStyleLabel(_summaryShownStyle)}',
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
                  key: ValueKey(segment.id),
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
                        const Spacer(),
                        IconButton(
                          tooltip: 'Corrigir transcricao',
                          visualDensity: VisualDensity.compact,
                          icon: const Icon(Icons.edit_outlined, size: 13),
                          color: AssistantTheme.textMuted,
                          onPressed: () => _editSegment(segment),
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

  Future<void> _editSegment(LessonSegment segment) async {
    final corrected = await _askSegmentCorrection(context, segment);
    if (corrected == null || corrected == segment.text) return;
    try {
      final updated = await education.updateLessonSegment(
        _lesson!.id,
        segment.id,
        corrected,
      );
      final lesson = await education.getLesson(
        _lesson!.id,
        includeSegments: false,
      );
      if (!mounted) return;
      setState(() {
        final index = _segments.indexWhere((item) => item.id == segment.id);
        if (index >= 0) _segments[index] = updated;
        _lesson = lesson;
        _summary = null;
        _summaryShownStyle = null;
        _status = updated.indexed
            ? 'Transcricao corrigida e busca atualizada.'
            : 'Transcricao corrigida; reindexacao pendente.';
      });
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao corrigir trecho: $e');
    }
  }

  Widget _buildSidePanel() {
    final lesson = _lesson;
    return Column(
      children: [
        Expanded(
          child: _Panel(
            title: 'PONTUACOES EXTRAS',
            child: _points.isEmpty
                ? const _EmptyState(
                    icon: Icons.emoji_events_outlined,
                    text: 'Cite o aluno em voz alta durante a aula:\n'
                        '"um ponto extra para o Pedro pela pergunta".\n'
                        'O registro aparece aqui no proximo trecho.',
                  )
                : ListView.separated(
                    itemCount: _points.length,
                    separatorBuilder: (_, __) =>
                        const Divider(height: 14, color: AssistantTheme.border),
                    itemBuilder: (_, index) => _PointTile(
                      key: ValueKey(_points[index].id),
                      point: _points[index],
                      onDelete: () async {
                        try {
                          final pointId = _points[index].id;
                          await education.deletePoint(pointId);
                          setState(() => _points.removeWhere((p) => p.id == pointId));
                        } catch (e) {
                          _setStatus('Falha ao remover: $e');
                        }
                      },
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 10),
        if (lesson != null) ...[
          QuizGeneratorWidget(
            lessonId: lesson.id,
            lessonTitle: lesson.title,
            disciplineName: lesson.discipline,
            onQuizGenerated: () {
              _setStatus('Quiz gerado com sucesso!');
            },
          ),
          const SizedBox(height: 10),
        ],
        // Wrap, e nao Row: o painel lateral encolhe junto com a janela, e o
        // seletor de IA desce para a linha de baixo em vez de vazar.
        Wrap(
          spacing: 12,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.end,
          children: [
            SummaryStylePicker(
              style: _summaryStyle,
              enabled: !_summarising,
              showLabel: true,
              onChanged: (style) => setState(() => _summaryStyle = style),
            ),
            SummaryEnginePicker(
              engine: _summaryEngine,
              config: ref.watch(configProvider),
              enabled: !_summarising,
              onChanged: (engine) => setState(() => _summaryEngine = engine),
            ),
          ],
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

/// Gera o resumo pelo motor escolhido e devolve o que ficou salvo na aula.
///
/// Provedor do backend: o servidor le a transcricao, resume e grava. Agente
/// conectado (Codex, Claude Code): o backend so entrega o prompt, o CLI do
/// usuario escreve o resumo com a aula inteira em uma chamada — a janela dele
/// dispensa a mapa-reducao — e o texto volta para ser gravado na aula.
Future<LessonSummary> _runSummary({
  required String lessonId,
  required String style,
  required String engine,
  AppConfig? config,
  String focus = '',
  bool closeLesson = false,
  void Function(String activity)? onProgress,
}) async {
  if (!AppConfig.connectedAgentIds.contains(engine)) {
    return education.generateSummary(
      lessonId,
      llm: engine.isEmpty ? null : engine,
      focus: focus,
      closeLesson: closeLesson,
      style: style,
    );
  }

  final built = await education.summaryPrompt(
    lessonId,
    style: style,
    focus: focus,
  );
  onProgress?.call(
    '${AppConfig.serviceLabel(engine)} lendo a aula '
    '(${built.transcriptChars} caracteres em uma chamada)...',
  );
  final result = await ConnectedAiService.run(
    agentId: engine,
    prompt: built.prompt,
    systemPrompt: built.systemPrompt,
    language: config?.language ?? 'pt-BR',
    // Aula inteira de uma vez: leva mais que uma resposta de chat.
    timeoutOverride: const Duration(minutes: 15),
    onProgress: onProgress,
  );
  if (result.isError) throw EducationException(result.content);

  return education.saveExternalSummary(
    lessonId,
    summary: result.content,
    llm: engine,
    style: built.style,
    closeLesson: closeLesson,
  );
}

class _PendingChunk {
  final String path;
  final int durationMs;

  _PendingChunk(this.path, this.durationMs);
}

// --- Pontuacoes ------------------------------------------------------------

class _PointsTab extends StatefulWidget {
  final _Classes classes;

  const _PointsTab({required this.classes});

  @override
  State<_PointsTab> createState() => _PointsTabState();
}

class _PointsTabState extends State<_PointsTab> {
  final _disciplineCtrl = TextEditingController();
  final _studentCtrl = TextEditingController();

  DateTime? _from;
  DateTime? _to;
  PointsReport? _report;
  ClassGroup? _selected;
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
    _disciplineCtrl.dispose();
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
      final selected = _selected;
      final report = await education.pointsReport(
        dateFrom: _iso(_from),
        dateTo: _iso(_to),
        discipline: selected?.discipline ?? _disciplineCtrl.text.trim(),
        classGroup: selected?.label,
        studentName: _studentCtrl.text.trim(),
      );
      if (mounted) setState(() => _report = report);
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao carregar: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Apaga a linha inteira do relatorio — um aluno, num dia, numa disciplina.
  /// Serve para limpar pontuacao que o transcritor entendeu errado.
  Future<void> _removeEntry(PointsReportEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Remover pontuacao'),
        content: Text(
          'Apagar ${_formatPoints(entry.totalPoints)} ponto(s) de '
          '${entry.studentName} em ${entry.lessonDate}? '
          'Sao ${entry.entries.length} registro(s).',
          style: const TextStyle(color: AssistantTheme.textPrimary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('REMOVER'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    try {
      for (final point in entry.entries) {
        await education.deletePoint(point.id);
      }
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao remover: $e');
    }
    await _load();
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
                flex: 2,
                child: ValueListenableBuilder<List<ClassGroup>?>(
                  valueListenable: widget.classes,
                  builder: (context, classes, _) {
                    final options = classes ?? const <ClassGroup>[];
                    if (options.isEmpty) {
                      return _Field(
                        controller: _disciplineCtrl,
                        label: 'DISCIPLINA',
                        onSubmitted: (_) => _load(),
                      );
                    }
                    final selected = options
                        .where((item) => item.id == _selected?.id)
                        .firstOrNull;
                    return _ClassDropdown(
                      label: 'TURMA',
                      hint: 'Todas as turmas',
                      allLabel: 'Todas as turmas',
                      options: options,
                      value: selected,
                      onChanged: (value) {
                        setState(() => _selected = value);
                        _load();
                      },
                    );
                  },
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
                                    '${entry.discipline}'
                                    '${entry.classGroup.isEmpty ? "" : " - "
                                        "turma ${entry.classGroup}"}'
                                    ' - ${entry.lessonDate}',
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
                            IconButton(
                              tooltip: 'Remover esta pontuacao',
                              icon: const Icon(Icons.delete_outline, size: 15),
                              color: AssistantTheme.textMuted,
                              onPressed: () => _removeEntry(entry),
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

// --- Turmas ----------------------------------------------------------------

class _RosterTab extends StatefulWidget {
  final _Classes classes;

  const _RosterTab({required this.classes});

  @override
  State<_RosterTab> createState() => _RosterTabState();
}

class _RosterTabState extends State<_RosterTab> {
  final _codeCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
  final _disciplineCtrl = TextEditingController();

  final _enrollmentCtrl = TextEditingController();
  final _studentCtrl = TextEditingController();
  final _aliasCtrl = TextEditingController();

  ClassGroup? _selected;
  Discipline? _newDiscipline;
  List<Discipline> _disciplines = [];
  List<Student> _students = [];
  final Set<String> _selectedStudentIds = {};
  var _loading = true;
  var _importing = false;
  var _deletingStudents = false;
  var _creatingDemo = false;
  var _status = '';
  var _statusIsError = false;

  @override
  void initState() {
    super.initState();
    _loadClasses();
  }

  @override
  void dispose() {
    _codeCtrl.dispose();
    _nameCtrl.dispose();
    _disciplineCtrl.dispose();
    _enrollmentCtrl.dispose();
    _studentCtrl.dispose();
    _aliasCtrl.dispose();
    super.dispose();
  }

  void _report(String message, {bool error = false}) {
    if (!mounted) return;
    setState(() {
      _status = message;
      _statusIsError = error;
    });
  }

  Future<void> _loadClasses({String? keepId}) async {
    setState(() => _loading = true);
    try {
      final disciplines = await education.listDisciplines();
      final classes = await education.listClasses();
      if (!mounted) return;
      widget.classes.value = classes;
      setState(() {
        _disciplines = disciplines;
        _newDiscipline = disciplines
                .where((item) => item.id == _newDiscipline?.id)
                .firstOrNull ??
            (disciplines.isEmpty ? null : disciplines.first);
      });
      final wanted = keepId ?? _selected?.id;
      setState(() {
        _selected = classes.where((item) => item.id == wanted).firstOrNull ??
            (classes.isEmpty ? null : classes.first);
      });
      await _loadStudents();
    } catch (e) {
      _report('Falha ao carregar turmas: $e', error: true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadStudents() async {
    final group = _selected;
    if (group == null) {
      if (mounted) {
        setState(() {
          _students = [];
          _selectedStudentIds.clear();
        });
      }
      return;
    }
    try {
      final students = await education.listStudents(classId: group.id);
      if (mounted) {
        setState(() {
          _students = students;
          final availableIds = students.map((student) => student.id).toSet();
          _selectedStudentIds.retainAll(availableIds);
        });
      }
    } catch (e) {
      _report('Falha ao carregar alunos: $e', error: true);
    }
  }

  // --- Turma ---------------------------------------------------------------

  Future<void> _createClass() async {
    final code = _codeCtrl.text.trim();
    if (code.isEmpty) {
      _report('Informe o codigo da turma.', error: true);
      return;
    }
    if (_newDiscipline == null) {
      _report('Cadastre a disciplina antes da turma.', error: true);
      return;
    }
    try {
      final group = await education.createClass(
        code: code,
        name: _nameCtrl.text.trim(),
        disciplineId: _newDiscipline!.id,
      );
      _codeCtrl.clear();
      _nameCtrl.clear();
      _report('Turma ${group.display} criada.');
      await _loadClasses(keepId: group.id);
    } catch (e) {
      _report('Falha ao criar turma: $e', error: true);
    }
  }

  Future<void> _createPresentationDemo() async {
    if (_creatingDemo) return;
    setState(() => _creatingDemo = true);
    try {
      final result = await education.createPresentationDemo();
      _report(result['message']?.toString() ?? 'Demonstracao criada.');
      await _loadClasses(keepId: result['class_id']?.toString());
    } catch (e) {
      _report('Falha ao criar demonstracao: $e', error: true);
    } finally {
      if (mounted) setState(() => _creatingDemo = false);
    }
  }

  Future<void> _renameClass(ClassGroup group) async {
    final codeCtrl = TextEditingController(text: group.code);
    final nameCtrl = TextEditingController(text: group.name);
    final startCtrl = TextEditingController(
      text: group.schedules.isEmpty ? '' : group.schedules.first.startTime,
    );
    final endCtrl = TextEditingController(
      text: group.schedules.isEmpty ? '' : group.schedules.first.endTime,
    );
    final days = group.schedules.map((item) => item.weekday).toSet();
    var discipline =
        _disciplines.where((item) => item.id == group.disciplineId).firstOrNull;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: const Text('Editar turma'),
          content: SizedBox(
            width: 440,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Expanded(
                        child: _Field(controller: codeCtrl, label: 'CODIGO'),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        flex: 2,
                        child: _Field(
                          controller: nameCtrl,
                          label: 'NOME (EX: PRESENCIAL)',
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  _DisciplineDropdown(
                    disciplines: _disciplines,
                    value: discipline,
                    onChanged: (value) =>
                        setDialogState(() => discipline = value),
                  ),
                  const SizedBox(height: 12),
                  _WeekdayPicker(
                    days: days,
                    startCtrl: startCtrl,
                    endCtrl: endCtrl,
                    onChanged: () => setDialogState(() {}),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'Os dias marcados fazem a turma aparecer como aula de hoje '
                    'na gravacao. Renomear atualiza os alunos vinculados; as '
                    'aulas ja gravadas seguem ligadas a esta turma.',
                    style: TextStyle(
                        fontSize: 11, color: AssistantTheme.textMuted),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('CANCELAR'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('SALVAR'),
            ),
          ],
        ),
      ),
    );
    if (confirmed == true) {
      try {
        await education.updateClass(
          group.id,
          code: codeCtrl.text.trim(),
          name: nameCtrl.text.trim(),
          disciplineId: discipline?.id,
          schedules: [
            for (final day in days)
              ClassSchedule(
                weekday: day,
                startTime: startCtrl.text.trim(),
                endTime: endCtrl.text.trim(),
              ),
          ],
        );
        _report('Turma atualizada.');
        await _loadClasses(keepId: group.id);
      } catch (e) {
        _report('Falha ao atualizar: $e', error: true);
      }
    }
    codeCtrl.dispose();
    nameCtrl.dispose();
    startCtrl.dispose();
    endCtrl.dispose();
  }

  /// Cadastro de disciplina: e ela que agrupa as turmas do mesmo conteudo.
  Future<void> _manageDisciplines() async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _DisciplinesDialog(disciplines: _disciplines),
    );
    await _loadClasses();
  }

  Future<void> _deleteClass(ClassGroup group) async {
    try {
      await education.deleteClass(group.id);
      _report('Turma removida.');
      await _loadClasses(keepId: '');
    } catch (e) {
      _report('$e', error: true);
    }
  }

  // --- Alunos --------------------------------------------------------------

  Future<void> _deleteStudents(List<Student> students) async {
    final group = _selected;
    if (group == null || students.isEmpty || _deletingStudents) return;

    final count = students.length;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: Text(count == 1 ? 'Excluir aluno' : 'Excluir alunos em lote'),
        content: SizedBox(
          width: 440,
          child: Text(
            count == 1
                ? 'Excluir ${students.first.name} da turma ${group.display}? '
                    'As pontuacoes ja registradas serao preservadas.'
                : 'Excluir $count alunos da turma ${group.display}? '
                    'As pontuacoes ja registradas serao preservadas.',
            style: const TextStyle(color: AssistantTheme.textPrimary),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style:
                FilledButton.styleFrom(backgroundColor: AssistantTheme.danger),
            child: Text(count == 1 ? 'EXCLUIR' : 'EXCLUIR $count'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _deletingStudents = true);
    try {
      final result = await education.deleteStudents(
        classId: group.id,
        studentIds: students.map((student) => student.id),
      );
      _selectedStudentIds.clear();
      _report(
        result.deleted == 1
            ? 'Aluno excluido.'
            : '${result.deleted} alunos excluidos.',
      );
      await _loadClasses(keepId: group.id);
    } catch (e) {
      _report('Falha ao excluir alunos: $e', error: true);
    } finally {
      if (mounted) setState(() => _deletingStudents = false);
    }
  }

  Future<void> _addStudent() async {
    final group = _selected;
    if (group == null) {
      _report('Escolha a turma antes de cadastrar o aluno.', error: true);
      return;
    }
    final enrollment = _enrollmentCtrl.text.trim();
    final name = _studentCtrl.text.trim();
    if (enrollment.isEmpty || name.isEmpty) {
      _report('Informe a matricula e o nome do aluno.', error: true);
      return;
    }
    try {
      await education.createStudent(
        name: name,
        externalId: enrollment,
        classId: group.id,
        aliases: _aliasCtrl.text
            .split(',')
            .map((item) => item.trim())
            .where((item) => item.isNotEmpty)
            .toList(),
      );
      _enrollmentCtrl.clear();
      _studentCtrl.clear();
      _aliasCtrl.clear();
      _report('Aluno cadastrado.');
      await _loadClasses(keepId: group.id);
    } catch (e) {
      _report('Falha ao cadastrar: $e', error: true);
    }
  }

  Future<void> _editStudent(Student student) async {
    final nameCtrl = TextEditingController(text: student.name);
    final aliasCtrl = TextEditingController(text: student.aliases.join(', '));
    final classes = widget.classes.value ?? const <ClassGroup>[];
    var target =
        classes.where((item) => item.id == student.classId).firstOrNull;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: const Text('Editar aluno'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _Field(controller: nameCtrl, label: 'NOME COMPLETO'),
                const SizedBox(height: 8),
                _Field(
                  controller: aliasCtrl,
                  label: 'APELIDOS (SEPARADOS POR VIRGULA)',
                ),
                const SizedBox(height: 8),
                _ClassDropdown(
                  label: 'TURMA',
                  hint: 'Selecione a turma',
                  options: classes,
                  value: target,
                  onChanged: (value) => setDialogState(() => target = value),
                ),
                const SizedBox(height: 10),
                const Text(
                  'O apelido resolve nome repetido na turma: com dois Adrian, '
                  'e ele que diz de quem voce falou.',
                  style:
                      TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('CANCELAR'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('SALVAR'),
            ),
          ],
        ),
      ),
    );
    if (confirmed == true) {
      try {
        await education.updateStudent(
          student.id,
          name: nameCtrl.text.trim(),
          classId: target?.id,
          aliases: aliasCtrl.text
              .split(',')
              .map((item) => item.trim())
              .where((item) => item.isNotEmpty)
              .toList(),
        );
        _report('Aluno atualizado.');
        await _loadClasses();
      } catch (e) {
        _report('Falha ao atualizar: $e', error: true);
      }
    }
    nameCtrl.dispose();
    aliasCtrl.dispose();
  }

  Future<void> _importCsv() async {
    final group = _selected;
    if (group == null) {
      _report('Escolha a turma que vai receber os alunos.', error: true);
      return;
    }

    setState(() => _importing = true);
    try {
      final selection = await FilePicker.pickFiles(
        type: FileType.custom,
        allowedExtensions: const ['csv'],
        withData: true,
      );
      if (selection == null || selection.files.isEmpty) return;

      final file = selection.files.single;
      final bytes = file.bytes ??
          (file.path == null ? null : await File(file.path!).readAsBytes());
      if (bytes == null) {
        throw const FormatException(
            'Nao foi possivel ler o arquivo escolhido.');
      }

      late final String content;
      try {
        content = utf8.decode(bytes);
      } on FormatException {
        content = latin1.decode(bytes);
      }
      final rows = parseStudentCsv(content);
      if (!mounted) return;

      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: const Text('Importar alunos'),
          content: SizedBox(
            width: 460,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${rows.length} aluno(s) para ${group.display}.',
                  style: const TextStyle(color: AssistantTheme.textPrimary),
                ),
                const SizedBox(height: 10),
                ...rows.take(5).map(
                      (row) => Text(
                        '${row.enrollment} - ${row.name}',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AssistantTheme.textSecondary,
                        ),
                      ),
                    ),
                if (rows.length > 5)
                  Text(
                    '... e mais ${rows.length - 5}.',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AssistantTheme.textMuted,
                    ),
                  ),
                const SizedBox(height: 10),
                const Text(
                  'Matriculas existentes serao atualizadas e passam para esta '
                  'turma; as demais serao cadastradas.',
                  style: TextStyle(
                    fontSize: 11,
                    color: AssistantTheme.textMuted,
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('CANCELAR'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('IMPORTAR'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;

      final result = await education.importStudents(
        classId: group.id,
        students: rows,
      );
      _report('Importacao concluida: ${result.created} cadastrado(s) e '
          '${result.updated} atualizado(s).');
      await _loadClasses(keepId: group.id);
    } catch (error) {
      final message = error is FormatException ? error.message : '$error';
      _report('Falha ao importar: $message', error: true);
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  // --- UI ------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final classes = widget.classes.value ?? const <ClassGroup>[];

    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Passo 1: a turma e o que ancora os nomes ouvidos na aula. Cada '
            'turma tem a sua lista, e uma aula pode atender mais de uma.',
            style: TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
          ),
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerRight,
            child: OutlinedButton.icon(
              onPressed: _creatingDemo ? null : _createPresentationDemo,
              icon: _creatingDemo
                  ? const SizedBox.square(
                      dimension: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.auto_awesome_outlined, size: 15),
              label: Text(
                _creatingDemo
                    ? 'PREPARANDO...'
                    : 'CRIAR EXEMPLO PARA APRESENTACAO',
                style: const TextStyle(fontSize: 10),
              ),
            ),
          ),
          const SizedBox(height: 8),
          if (_status.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                _status,
                style: TextStyle(
                  fontSize: 11,
                  color: _statusIsError
                      ? AssistantTheme.danger
                      : AssistantTheme.c3,
                ),
              ),
            ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(width: 310, child: _buildClassColumn(classes)),
                      const SizedBox(width: 14),
                      Expanded(child: _buildStudentColumn()),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildClassColumn(List<ClassGroup> classes) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: _Panel(
            title: 'TURMAS',
            trailing: TextButton.icon(
              onPressed: _manageDisciplines,
              icon: const Icon(Icons.menu_book_outlined, size: 14),
              label: const Text('DISCIPLINAS', style: TextStyle(fontSize: 10)),
            ),
            child: classes.isEmpty
                ? const _EmptyState(
                    icon: Icons.school_outlined,
                    text: 'Nenhuma turma.\nCrie a primeira abaixo.',
                  )
                : ListView.separated(
                    itemCount: classes.length,
                    separatorBuilder: (_, __) =>
                        const Divider(height: 10, color: AssistantTheme.border),
                    itemBuilder: (_, index) {
                      final group = classes[index];
                      final selected = group.id == _selected?.id;
                      return InkWell(
                        onTap: () async {
                          setState(() => _selected = group);
                          await _loadStudents();
                        },
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Row(
                            children: [
                              Icon(
                                selected
                                    ? Icons.radio_button_checked
                                    : Icons.radio_button_unchecked,
                                size: 14,
                                color: selected
                                    ? AssistantTheme.c3
                                    : AssistantTheme.textMuted,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      group.label,
                                      style: TextStyle(
                                        fontSize: 12,
                                        fontWeight: selected
                                            ? FontWeight.w600
                                            : FontWeight.w400,
                                        color: AssistantTheme.textPrimary,
                                      ),
                                    ),
                                    Text(
                                      '${group.discipline.isEmpty ? "sem disciplina" : group.discipline}'
                                      '  -  ${group.studentCount} aluno(s)'
                                      '${group.scheduleLabel.isEmpty ? "" : "  -  ${group.scheduleLabel}"}',
                                      style: const TextStyle(
                                          fontSize: 10,
                                          color: AssistantTheme.textMuted),
                                    ),
                                  ],
                                ),
                              ),
                              IconButton(
                                tooltip: 'Editar turma',
                                icon: const Icon(Icons.edit_outlined, size: 14),
                                color: AssistantTheme.textMuted,
                                onPressed: () => _renameClass(group),
                              ),
                              IconButton(
                                tooltip: 'Remover turma',
                                icon:
                                    const Icon(Icons.delete_outline, size: 14),
                                color: AssistantTheme.textMuted,
                                onPressed: () => _deleteClass(group),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ),
        const SizedBox(height: 10),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(child: _Field(controller: _codeCtrl, label: 'CODIGO')),
            const SizedBox(width: 8),
            Expanded(child: _Field(controller: _nameCtrl, label: 'NOME')),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: _DisciplineDropdown(
                disciplines: _disciplines,
                value: _newDiscipline,
                onChanged: (value) => setState(() => _newDiscipline = value),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton.icon(
              onPressed: _createClass,
              icon: const Icon(Icons.add, size: 15),
              label: const Text('CRIAR'),
              style: FilledButton.styleFrom(
                backgroundColor: AssistantTheme.c3,
                foregroundColor: AssistantTheme.bg,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildStudentColumn() {
    final group = _selected;
    final selectedStudents = _students
        .where((student) => _selectedStudentIds.contains(student.id))
        .toList();
    final allSelected =
        _students.isNotEmpty && selectedStudents.length == _students.length;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: _Panel(
            title: group == null
                ? 'ALUNOS'
                : 'ALUNOS DE ${group.display.toUpperCase()}',
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (selectedStudents.isNotEmpty) ...[
                  TextButton.icon(
                    onPressed: _deletingStudents
                        ? null
                        : () => _deleteStudents(selectedStudents),
                    icon: _deletingStudents
                        ? const SizedBox.square(
                            dimension: 13,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.delete_outline, size: 14),
                    label: Text(
                      _deletingStudents
                          ? 'EXCLUINDO...'
                          : 'EXCLUIR (${selectedStudents.length})',
                      style: const TextStyle(fontSize: 10),
                    ),
                  ),
                  const SizedBox(width: 4),
                ],
                TextButton.icon(
                  onPressed: _importing || group == null ? null : _importCsv,
                  icon: const Icon(Icons.upload_file_outlined, size: 14),
                  label: Text(
                    _importing ? 'IMPORTANDO...' : 'IMPORTAR CSV',
                    style: const TextStyle(fontSize: 10),
                  ),
                ),
              ],
            ),
            child: group == null
                ? const _EmptyState(
                    icon: Icons.groups_outlined,
                    text: 'Escolha uma turma ao lado.',
                  )
                : _students.isEmpty
                    ? const _EmptyState(
                        icon: Icons.groups_outlined,
                        text: 'Turma sem alunos.\nImporte o CSV com as '
                            'colunas matricula e nome.',
                      )
                    : Column(
                        children: [
                          Row(
                            children: [
                              Checkbox(
                                value: allSelected,
                                onChanged: _deletingStudents
                                    ? null
                                    : (checked) => setState(() {
                                          if (checked == true) {
                                            _selectedStudentIds.addAll(
                                              _students.map(
                                                (student) => student.id,
                                              ),
                                            );
                                          } else {
                                            _selectedStudentIds.clear();
                                          }
                                        }),
                                visualDensity: VisualDensity.compact,
                              ),
                              Text(
                                selectedStudents.isEmpty
                                    ? 'Selecionar todos'
                                    : '${selectedStudents.length} de '
                                        '${_students.length} selecionados',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AssistantTheme.textMuted,
                                ),
                              ),
                            ],
                          ),
                          const Divider(
                            height: 8,
                            color: AssistantTheme.border,
                          ),
                          Expanded(
                            child: ListView.separated(
                              itemCount: _students.length,
                              separatorBuilder: (_, __) => const Divider(
                                height: 12,
                                color: AssistantTheme.border,
                              ),
                              itemBuilder: (_, index) {
                                final student = _students[index];
                                final tags = [
                                  if (student.externalId?.isNotEmpty == true)
                                    'matricula: ${student.externalId}',
                                  if (student.aliases.isNotEmpty)
                                    'apelidos: ${student.aliases.join(", ")}',
                                ].join('  -  ');

                                return Row(
                                  children: [
                                    Checkbox(
                                      value: _selectedStudentIds
                                          .contains(student.id),
                                      onChanged: _deletingStudents
                                          ? null
                                          : (checked) => setState(() {
                                                if (checked == true) {
                                                  _selectedStudentIds
                                                      .add(student.id);
                                                } else {
                                                  _selectedStudentIds
                                                      .remove(student.id);
                                                }
                                              }),
                                      visualDensity: VisualDensity.compact,
                                    ),
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
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
                                                color: AssistantTheme.textMuted,
                                              ),
                                            ),
                                        ],
                                      ),
                                    ),
                                    IconButton(
                                      tooltip: 'Editar aluno',
                                      icon: const Icon(
                                        Icons.edit_outlined,
                                        size: 15,
                                      ),
                                      color: AssistantTheme.textMuted,
                                      onPressed: _deletingStudents
                                          ? null
                                          : () => _editStudent(student),
                                    ),
                                    IconButton(
                                      tooltip: 'Excluir aluno',
                                      icon: const Icon(
                                        Icons.delete_outline,
                                        size: 15,
                                      ),
                                      color: AssistantTheme.textMuted,
                                      onPressed: _deletingStudents
                                          ? null
                                          : () => _deleteStudents([student]),
                                    ),
                                  ],
                                );
                              },
                            ),
                          ),
                        ],
                      ),
          ),
        ),
        const SizedBox(height: 10),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: _Field(controller: _enrollmentCtrl, label: 'MATRICULA'),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: _Field(controller: _studentCtrl, label: 'NOME COMPLETO'),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _Field(
                controller: _aliasCtrl,
                label: 'APELIDOS',
                onSubmitted: (_) => _addStudent(),
              ),
            ),
            const SizedBox(width: 8),
            FilledButton.icon(
              onPressed: _selected == null ? null : _addStudent,
              icon: const Icon(Icons.person_add_alt, size: 15),
              label: const Text('ADICIONAR'),
              style: FilledButton.styleFrom(
                backgroundColor: AssistantTheme.c3,
                foregroundColor: AssistantTheme.bg,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

// --- Historico de aulas ----------------------------------------------------

class _HistoryTab extends ConsumerStatefulWidget {
  final _Classes classes;

  const _HistoryTab({required this.classes});

  @override
  ConsumerState<_HistoryTab> createState() => _HistoryTabState();
}

class _HistoryTabState extends ConsumerState<_HistoryTab> {
  DateTime? _from;
  DateTime? _to;
  List<Lesson> _lessons = [];
  LessonDetail? _detail;
  var _loading = false;
  var _showTranscript = false;
  var _summarising = false;
  var _exporting = false;
  var _summaryStyle = summaryStyleStandard;
  var _summaryEngine = '';
  var _status = '';

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _to = DateTime(now.year, now.month, now.day);
    _from = _to!.subtract(const Duration(days: 30));
    _load();
  }

  String? _iso(DateTime? date) => date?.toIso8601String().split('T').first;

  String _when(Lesson lesson) {
    final start = lesson.startedAt?.toLocal();
    if (start == null) return 'sem data';
    final day = '${start.day.toString().padLeft(2, '0')}/'
        '${start.month.toString().padLeft(2, '0')}/${start.year}';
    final hour = '${start.hour.toString().padLeft(2, '0')}:'
        '${start.minute.toString().padLeft(2, '0')}';
    return '$day $hour';
  }

  Future<void> _load({String? keepId}) async {
    setState(() {
      _loading = true;
      _status = '';
    });
    try {
      final lessons = await education.listLessons(
        dateFrom: _iso(_from),
        dateTo: _iso(_to),
        limit: 200,
      );
      if (!mounted) return;
      setState(() => _lessons = lessons);
      final wanted = keepId ?? _detail?.id;
      if (wanted != null && lessons.any((item) => item.id == wanted)) {
        await _open(wanted);
      } else if (mounted) {
        setState(() => _detail = null);
      }
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao carregar aulas: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _open(String lessonId) async {
    try {
      final detail = await education.getLesson(lessonId);
      if (mounted) {
        setState(() {
          _detail = detail;
          _showTranscript = detail.summary == null || detail.summary!.isEmpty;
          _summaryStyle = summaryStyleOrStandard(detail.summaryStyle);
        });
      }
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao abrir a aula: $e');
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

  /// Ajuste do vinculo depois da aula: e por aqui que uma aula gravada sem a
  /// turma certa volta a contar para as pessoas certas.
  Future<void> _edit(Lesson lesson) async {
    final titleCtrl = TextEditingController(text: lesson.title);
    final classes = widget.classes.value ?? const <ClassGroup>[];
    final chosen = lesson.classIds.toSet();

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: const Text('Editar aula'),
          content: SizedBox(
            width: 460,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Field(controller: titleCtrl, label: 'TEMA DA AULA'),
                const SizedBox(height: 12),
                const Text(
                  'TURMAS ATENDIDAS',
                  style: TextStyle(
                    fontSize: 9,
                    letterSpacing: 1.5,
                    color: AssistantTheme.textMuted,
                  ),
                ),
                const SizedBox(height: 6),
                if (classes.isEmpty)
                  const Text(
                    'Nenhuma turma cadastrada.',
                    style: TextStyle(
                        fontSize: 11, color: AssistantTheme.textMuted),
                  )
                else
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final group in classes)
                        FilterChip(
                          selected: chosen.contains(group.id),
                          onSelected: (on) => setDialogState(() {
                            if (on) {
                              chosen.add(group.id);
                            } else {
                              chosen.remove(group.id);
                            }
                          }),
                          label: Text(
                            group.display,
                            style: const TextStyle(fontSize: 11),
                          ),
                          backgroundColor: AssistantTheme.bg2,
                          selectedColor:
                              AssistantTheme.c3.withValues(alpha: 0.22),
                          checkmarkColor: AssistantTheme.c3,
                          side: const BorderSide(color: AssistantTheme.border),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(3),
                          ),
                        ),
                    ],
                  ),
                const SizedBox(height: 10),
                const Text(
                  'Trocar a turma vale para o relatorio: a pontuacao de aluno '
                  'reconhecido segue o cadastro dele, e a dos nomes que nao '
                  'casaram passa a contar para a turma escolhida aqui.',
                  style:
                      TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('CANCELAR'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('SALVAR'),
            ),
          ],
        ),
      ),
    );
    if (confirmed == true) {
      try {
        await education.updateLesson(
          lesson.id,
          title: titleCtrl.text.trim(),
          classIds: chosen.toList(),
        );
        await _load(keepId: lesson.id);
        if (mounted) setState(() => _status = 'Aula atualizada.');
      } catch (e) {
        if (mounted) setState(() => _status = 'Falha ao salvar: $e');
      }
    }
    titleCtrl.dispose();
  }

  Future<void> _delete(Lesson lesson) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Apagar aula'),
        content: Text(
          'Apagar a aula de ${_when(lesson)}? A transcricao, o resumo e a '
          'pontuacao dela vao junto.',
          style: const TextStyle(color: AssistantTheme.textPrimary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('APAGAR'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await education.deleteLesson(lesson.id);
      if (mounted) setState(() => _detail = null);
      await _load(keepId: '');
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao apagar: $e');
    }
  }

  void _syncSiaPresence(String lessonId, String lessonTitle) {
    showDialog(
      context: context,
      // Sem fechar ao aplicar: a gravacao final e feita na tela do SIA.
      builder: (_) => SiaAttendanceImporter(refId: lessonId),
    );
  }

  Future<void> _editSegment(LessonDetail detail, LessonSegment segment) async {
    final corrected = await _askSegmentCorrection(context, segment);
    if (corrected == null || corrected == segment.text) return;
    try {
      await education.updateLessonSegment(detail.id, segment.id, corrected);
      await _open(detail.id);
      if (mounted) {
        setState(() {
          _showTranscript = true;
          _status = 'Transcricao corrigida. Gere novamente o resumo da aula.';
        });
      }
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao corrigir trecho: $e');
    }
  }

  /// Resumo de aula antiga: o backend le a transcricao guardada e devolve o
  /// texto, mesmo que a aula ja esteja encerrada.
  Future<void> _summarise(LessonDetail detail) async {
    final config = ref.read(configProvider);
    final quem = summaryEngineLabel(_summaryEngine, config);
    setState(() {
      _summarising = true;
      _status = _summaryStyle == summaryStyleDetailed
          ? 'Gerando resumo detalhado da aula com $quem (leva mais tempo)...'
          : 'Gerando resumo da aula com $quem...';
    });
    try {
      final summary = await _runSummary(
        lessonId: detail.id,
        style: _summaryStyle,
        engine: _summaryEngine,
        config: config,
        onProgress: (activity) {
          if (mounted) setState(() => _status = activity);
        },
      );
      InAppNotificationService.showSummaryReady(
        discipline: detail.discipline,
        title: detail.title,
        llm: summaryEngineLabel(summary.llm, config),
        usedSegments: summary.usedSegments,
        style: summary.style,
      );
      await _open(detail.id);
      if (mounted) {
        setState(() {
          _showTranscript = false;
          _status =
              'Resumo ${summaryStyleLabel(summary.style).toLowerCase()} pronto '
              '(${summaryEngineLabel(summary.llm, config)}, '
              '${summary.usedSegments} trechos).';
        });
      }
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao resumir: $e');
    } finally {
      if (mounted) setState(() => _summarising = false);
    }
  }

  Future<void> _exportPdf(LessonDetail detail) async {
    final summary = detail.summary;
    if (summary == null || summary.isEmpty) {
      setState(() => _status = 'Gere o resumo antes de exportar.');
      return;
    }

    setState(() => _exporting = true);
    try {
      final bytes = await buildLessonSummaryPdf(
        lesson: detail,
        summary: summary,
        points: detail.points,
      );
      if (!mounted) return;
      final fileName = lessonPdfFilename(detail);
      final confirmed = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (_) => _LessonPdfPreviewDialog(
          bytes: bytes,
          fileName: fileName,
        ),
      );
      if (confirmed != true) {
        if (mounted) setState(() => _status = 'Exportacao cancelada.');
        return;
      }
      final path = await FilePicker.saveFile(
        dialogTitle: 'Salvar resumo da aula',
        fileName: fileName,
        type: FileType.custom,
        allowedExtensions: const ['pdf'],
        bytes: bytes,
      );
      if (path == null) return;
      // No desktop o file_picker devolve o caminho e nao grava sozinho.
      final file =
          File(path.toLowerCase().endsWith('.pdf') ? path : '$path.pdf');
      if (!await file.exists() || await file.length() != bytes.length) {
        await file.writeAsBytes(bytes);
      }
      if (mounted) setState(() => _status = 'PDF salvo em ${file.path}');
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao exportar: $e');
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Widget _buildDetailActions(LessonDetail detail, bool hasSummary) {
    final podeResumir = !_summarising && detail.segments.isNotEmpty;

    // Duas linhas: as opcoes do resumo em cima, os botoes embaixo. Tudo na
    // mesma linha nao cabia na coluna do detalhe — os seletores empurravam os
    // botoes para fora e o texto de trechos era espremido ate uma letra por
    // linha.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 12,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SummaryStylePicker(
              style: _summaryStyle,
              enabled: podeResumir,
              onChanged: (style) => setState(() => _summaryStyle = style),
            ),
            SummaryEnginePicker(
              engine: _summaryEngine,
              config: ref.watch(configProvider),
              enabled: podeResumir,
              onChanged: (engine) => setState(() => _summaryEngine = engine),
            ),
          ],
        ),
        const SizedBox(height: 8),
        _buildDetailButtons(detail, hasSummary),
      ],
    );
  }

  Widget _buildDetailButtons(LessonDetail detail, bool hasSummary) {
    return Row(
      children: [
        Expanded(
          child: Text(
            detail.segments.isEmpty
                ? 'Aula sem trechos gravados.'
                : '${detail.segments.length} trecho(s), '
                    '${detail.transcriptChars} caracteres.',
            overflow: TextOverflow.ellipsis,
            style:
                const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
          ),
        ),
        const SizedBox(width: 8),
        OutlinedButton.icon(
          onPressed: _summarising || detail.segments.isEmpty
              ? null
              : () => _summarise(detail),
          icon: const Icon(Icons.summarize_outlined, size: 14),
          label: Text(
            _summarising
                ? 'RESUMINDO...'
                : hasSummary
                    ? 'REFAZER RESUMO'
                    : 'GERAR RESUMO',
            style: const TextStyle(fontSize: 10),
          ),
          style: OutlinedButton.styleFrom(
            foregroundColor: AssistantTheme.c2,
            side: const BorderSide(color: AssistantTheme.border2),
          ),
        ),
        const SizedBox(width: 8),
        FilledButton.icon(
          onPressed:
              _exporting || !hasSummary ? null : () => _exportPdf(detail),
          icon: const Icon(Icons.picture_as_pdf_outlined, size: 14),
          label: Text(
            _exporting ? 'PREPARANDO...' : 'VISUALIZAR PDF',
            style: const TextStyle(fontSize: 10),
          ),
          style: FilledButton.styleFrom(
            backgroundColor: AssistantTheme.c3,
            foregroundColor: AssistantTheme.bg,
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
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
              FilledButton.icon(
                onPressed: _loading ? null : () => _load(),
                icon: const Icon(Icons.refresh, size: 15),
                label: const Text('ATUALIZAR'),
                style: FilledButton.styleFrom(
                  backgroundColor: AssistantTheme.c3,
                  foregroundColor: AssistantTheme.bg,
                ),
              ),
              const Spacer(),
              Text(
                '${_lessons.length} aula(s)',
                style: const TextStyle(
                    fontSize: 11, color: AssistantTheme.textMuted),
              ),
            ],
          ),
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
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(width: 360, child: _buildList()),
                      const SizedBox(width: 14),
                      Expanded(child: _buildDetail()),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildList() {
    return _Panel(
      title: 'AULAS',
      child: _lessons.isEmpty
          ? const _EmptyState(
              icon: Icons.history,
              text: 'Nenhuma aula no periodo.',
            )
          : ListView.separated(
              itemCount: _lessons.length,
              separatorBuilder: (_, __) =>
                  const Divider(height: 12, color: AssistantTheme.border),
              itemBuilder: (_, index) {
                final lesson = _lessons[index];
                final selected = lesson.id == _detail?.id;
                final turmas = lesson.classLabels.isEmpty
                    ? (lesson.classGroup.isEmpty
                        ? 'sem turma'
                        : lesson.classGroup)
                    : lesson.classLabels.join(' + ');

                return InkWell(
                  onTap: () => _open(lesson.id),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      children: [
                        Icon(
                          lesson.isClosed
                              ? Icons.check_circle_outline
                              : Icons.fiber_manual_record,
                          size: 13,
                          color: lesson.isClosed
                              ? AssistantTheme.c3
                              : AssistantTheme.c4,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${_when(lesson)}  -  ${lesson.discipline}'
                                '${lesson.semester.isEmpty ? "" : "  [${lesson.semester}]"}',
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: selected
                                      ? FontWeight.w600
                                      : FontWeight.w400,
                                  color: AssistantTheme.textPrimary,
                                ),
                              ),
                              Text(
                                '$turmas'
                                '${lesson.title.isEmpty ? "" : "  -  ${lesson.title}"}',
                                style: const TextStyle(
                                    fontSize: 10,
                                    color: AssistantTheme.textMuted),
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: 'Editar tema e turmas',
                          icon: const Icon(Icons.edit_outlined, size: 14),
                          color: AssistantTheme.textMuted,
                          onPressed: () => _edit(lesson),
                        ),
                        IconButton(
                          tooltip: 'Apagar aula',
                          icon: const Icon(Icons.delete_outline, size: 14),
                          color: AssistantTheme.textMuted,
                          onPressed: () => _delete(lesson),
                        ),
                        if (lesson.isClosed)
                          IconButton(
                            tooltip: 'Sincronizar presença do SIA',
                            icon: const Icon(Icons.cloud_sync_outlined, size: 14),
                            color: Colors.blue,
                            onPressed: () => _syncSiaPresence(lesson.id, lesson.title),
                          ),
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }

  Widget _buildDetail() {
    final detail = _detail;
    if (detail == null) {
      return const _Panel(
        title: 'AULA',
        child: _EmptyState(
          icon: Icons.article_outlined,
          text: 'Escolha uma aula na lista para ver o resumo, a transcricao '
              'e a pontuacao.',
        ),
      );
    }

    final hasSummary = detail.summary != null && detail.summary!.isNotEmpty;

    return Column(
      children: [
        _buildDetailActions(detail, hasSummary),
        const SizedBox(height: 10),
        Expanded(
          flex: 3,
          child: _Panel(
            title: _showTranscript || !hasSummary
                ? 'TRANSCRICAO  -  ${detail.segments.length} TRECHOS'
                : 'RESUMO  -  ${summaryStyleLabel(detail.summaryStyle)}',
            trailing: hasSummary
                ? TextButton(
                    onPressed: () =>
                        setState(() => _showTranscript = !_showTranscript),
                    child: Text(
                      _showTranscript ? 'VER RESUMO' : 'VER TRANSCRICAO',
                      style: const TextStyle(fontSize: 10),
                    ),
                  )
                : null,
            child: _showTranscript || !hasSummary
                ? (detail.segments.isEmpty
                    ? const Text(
                        'Sem trechos gravados.',
                        style: TextStyle(color: AssistantTheme.textMuted),
                      )
                    : ListView.separated(
                        itemCount: detail.segments.length,
                        separatorBuilder: (_, __) => const Divider(
                          height: 16,
                          color: AssistantTheme.border,
                        ),
                        itemBuilder: (_, index) {
                          final segment = detail.segments[index];
                          return Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                child: SelectableText(
                                  segment.text,
                                  style: const TextStyle(
                                    fontSize: 12,
                                    height: 1.5,
                                    color: AssistantTheme.textPrimary,
                                  ),
                                ),
                              ),
                              IconButton(
                                tooltip: 'Corrigir trecho ${segment.sequence}',
                                visualDensity: VisualDensity.compact,
                                icon: const Icon(Icons.edit_outlined, size: 14),
                                color: AssistantTheme.textMuted,
                                onPressed: () => _editSegment(detail, segment),
                              ),
                            ],
                          );
                        },
                      ))
                : SingleChildScrollView(
                    child: SelectableText(
                      detail.summary!,
                      style: const TextStyle(
                        fontSize: 12,
                        height: 1.5,
                        color: AssistantTheme.textPrimary,
                      ),
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 10),
        Expanded(
          flex: 2,
          child: _Panel(
            title: 'PONTUACOES DESTA AULA',
            child: detail.points.isEmpty
                ? const _EmptyState(
                    icon: Icons.emoji_events_outlined,
                    text: 'Nenhuma pontuacao registrada.',
                  )
                : ListView.separated(
                    itemCount: detail.points.length,
                    separatorBuilder: (_, __) =>
                        const Divider(height: 14, color: AssistantTheme.border),
                    itemBuilder: (_, index) => _PointTile(
                      point: detail.points[index],
                      onDelete: () async {
                        try {
                          await education.deletePoint(detail.points[index].id);
                          await _open(detail.id);
                        } catch (e) {
                          if (mounted) {
                            setState(() => _status = 'Falha ao remover: $e');
                          }
                        }
                      },
                    ),
                  ),
          ),
        ),
      ],
    );
  }
}

class _LessonPdfPreviewDialog extends StatelessWidget {
  final Uint8List bytes;
  final String fileName;

  const _LessonPdfPreviewDialog({
    required this.bytes,
    required this.fileName,
  });

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final width = (size.width - 48).clamp(280.0, 1100.0).toDouble();
    final height = (size.height - 48).clamp(360.0, 820.0).toDouble();

    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      child: SizedBox(
        width: width,
        height: height,
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.fromLTRB(18, 12, 10, 12),
              decoration: const BoxDecoration(
                border: Border(
                  bottom: BorderSide(color: AssistantTheme.border2),
                ),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.preview_outlined,
                    size: 18,
                    color: AssistantTheme.c3,
                  ),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'PRÉ-VISUALIZAÇÃO DO PDF',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.2,
                            color: AssistantTheme.textPrimary,
                          ),
                        ),
                        SizedBox(height: 2),
                        Text(
                          'Confira o documento antes de escolher onde salvar.',
                          style: TextStyle(
                            fontSize: 10,
                            color: AssistantTheme.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Fechar preview',
                    onPressed: () => Navigator.of(context).pop(false),
                    icon: const Icon(Icons.close, size: 18),
                  ),
                ],
              ),
            ),
            Expanded(
              child: PdfPreview(
                build: (_) async => bytes,
                pdfFileName: fileName,
                useActions: false,
                allowPrinting: false,
                allowSharing: false,
                canChangePageFormat: false,
                canChangeOrientation: false,
                canDebug: false,
                maxPageWidth: 720,
                padding: const EdgeInsets.all(18),
                scrollViewDecoration: const BoxDecoration(
                  color: Color(0xFFE6EBF1),
                ),
                pdfPreviewPageDecoration: BoxDecoration(
                  color: Colors.white,
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.18),
                      blurRadius: 12,
                      offset: const Offset(0, 4),
                    ),
                  ],
                ),
                onError: (_, error) => Center(
                  child: Text(
                    'Não foi possível visualizar o PDF: $error',
                    style: const TextStyle(color: AssistantTheme.danger),
                  ),
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              decoration: const BoxDecoration(
                border: Border(
                  top: BorderSide(color: AssistantTheme.border2),
                ),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(false),
                    child: const Text('CANCELAR'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton.icon(
                    onPressed: () => Navigator.of(context).pop(true),
                    icon: const Icon(Icons.save_alt, size: 16),
                    label: const Text('SALVAR PDF'),
                    style: FilledButton.styleFrom(
                      backgroundColor: AssistantTheme.c3,
                      foregroundColor: AssistantTheme.bg,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

const _weekdayLabels = ['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom'];

/// Nome do dia a partir do `DateTime.weekday` (segunda = 1).
String _weekdayName(int dartWeekday) =>
    _weekdayLabels[(dartWeekday - 1).clamp(0, 6)];

class _DisciplineDropdown extends StatelessWidget {
  final List<Discipline> disciplines;
  final Discipline? value;
  final ValueChanged<Discipline?> onChanged;

  const _DisciplineDropdown({
    required this.disciplines,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'DISCIPLINA',
          style: TextStyle(
            fontSize: 9,
            letterSpacing: 1.5,
            color: AssistantTheme.textMuted,
          ),
        ),
        const SizedBox(height: 4),
        DropdownButtonFormField<Discipline>(
          initialValue: value,
          isExpanded: true,
          hint: const Text(
            'Cadastre uma disciplina',
            style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
          ),
          dropdownColor: AssistantTheme.surface,
          style:
              const TextStyle(fontSize: 12, color: AssistantTheme.textPrimary),
          icon: const Icon(Icons.arrow_drop_down,
              size: 18, color: AssistantTheme.textMuted),
          decoration: InputDecoration(
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
          items: [
            for (final discipline in disciplines)
              DropdownMenuItem(
                value: discipline,
                child: Text(discipline.label, overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: onChanged,
        ),
      ],
    );
  }
}

/// Dias da semana da turma, com um horario aplicado a todos eles.
class _WeekdayPicker extends StatelessWidget {
  final Set<int> days;
  final TextEditingController startCtrl;
  final TextEditingController endCtrl;
  final VoidCallback onChanged;

  const _WeekdayPicker({
    required this.days,
    required this.startCtrl,
    required this.endCtrl,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'DIAS DE AULA',
          style: TextStyle(
            fontSize: 9,
            letterSpacing: 1.5,
            color: AssistantTheme.textMuted,
          ),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          children: [
            for (var day = 0; day < 7; day++)
              FilterChip(
                selected: days.contains(day),
                onSelected: (on) {
                  if (on) {
                    days.add(day);
                  } else {
                    days.remove(day);
                  }
                  onChanged();
                },
                label: Text(
                  _weekdayLabels[day],
                  style: const TextStyle(fontSize: 11),
                ),
                backgroundColor: AssistantTheme.bg2,
                selectedColor: AssistantTheme.c3.withValues(alpha: 0.22),
                checkmarkColor: AssistantTheme.c3,
                side: const BorderSide(color: AssistantTheme.border),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(3),
                ),
              ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: _Field(
                controller: startCtrl,
                label: 'INICIO',
                hint: '18:30',
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _Field(
                controller: endCtrl,
                label: 'FIM',
                hint: '21:10',
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// Cadastro de disciplinas, aberto pela aba de turmas.
class _DisciplinesDialog extends StatefulWidget {
  final List<Discipline> disciplines;

  const _DisciplinesDialog({required this.disciplines});

  @override
  State<_DisciplinesDialog> createState() => _DisciplinesDialogState();
}

class _DisciplinesDialogState extends State<_DisciplinesDialog> {
  final _codeCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
  final _semesterCtrl = TextEditingController(text: _currentSemesterCode());

  late List<Discipline> _disciplines = List.of(widget.disciplines);
  var _status = '';

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _codeCtrl.dispose();
    _nameCtrl.dispose();
    _semesterCtrl.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    try {
      final disciplines = await education.listDisciplines(activeOnly: false);
      if (mounted) setState(() => _disciplines = disciplines);
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao carregar: $e');
    }
  }

  Future<void> _create() async {
    final code = _codeCtrl.text.trim();
    final name = _nameCtrl.text.trim();
    if (code.isEmpty && name.isEmpty) {
      setState(() => _status = 'Informe o codigo ou o nome.');
      return;
    }
    try {
      await education.createDiscipline(
        code: code,
        name: name,
        semester: _semesterCtrl.text.trim(),
      );
      _codeCtrl.clear();
      _nameCtrl.clear();
      setState(() => _status = '');
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _status = '$e');
    }
  }

  Future<void> _setActive(Discipline discipline, bool active) async {
    if (!active) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: const Text('Encerrar disciplina'),
          content: Text(
            'Encerrar ${discipline.label}? Ela e suas turmas deixam de aparecer '
            'nas novas aulas, mas todo o historico, alunos, transcricoes e '
            'pontuacoes permanecem guardados.',
            style: const TextStyle(color: AssistantTheme.textPrimary),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('CANCELAR'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('ENCERRAR'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    try {
      await education.updateDiscipline(discipline.id, active: active);
      if (mounted) {
        setState(() => _status = active
            ? 'Disciplina reaberta.'
            : 'Disciplina encerrada; o historico foi preservado.');
      }
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _status = '$e');
    }
  }

  Future<void> _setSemesterActive(String semester, bool active) async {
    if (!active) {
      final affected = _disciplines
          .where((item) => item.semester == semester && item.active)
          .length;
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text('Encerrar semestre $semester'),
          content: Text(
            'As $affected disciplina(s) ativas e suas turmas deixam de '
            'aparecer em novas aulas. Historico, alunos, transcricoes e '
            'pontuacoes permanecem guardados.',
            style: const TextStyle(color: AssistantTheme.textPrimary),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('CANCELAR'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('ENCERRAR SEMESTRE'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    try {
      final result = await education.updateSemester(
        semester,
        active: active,
      );
      if (mounted) {
        setState(() => _status = active
            ? 'Semestre $semester reaberto.'
            : 'Semestre $semester encerrado: '
                '${result.disciplineCount} disciplina(s), '
                '${result.classCount} turma(s).');
      }
      await _reload();
    } catch (e) {
      if (mounted) setState(() => _status = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final semesters = _disciplines
        .map((item) => item.semester)
        .where((item) => item.isNotEmpty)
        .toSet()
        .toList()
      ..sort((a, b) => b.compareTo(a));
    return AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: const Text('Disciplinas'),
      content: SizedBox(
        width: 540,
        height: 460,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'A disciplina agrupa as turmas do mesmo conteudo. Ex.: ARA0040 '
              'com as turmas 3001 e 3002.',
              style:
                  TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
            ),
            const SizedBox(height: 10),
            if (semesters.isNotEmpty)
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  for (final semester in semesters)
                    Builder(builder: (context) {
                      final active = _disciplines.any(
                        (item) => item.semester == semester && item.active,
                      );
                      return OutlinedButton.icon(
                        onPressed: () => _setSemesterActive(semester, !active),
                        icon: Icon(
                          active
                              ? Icons.archive_outlined
                              : Icons.unarchive_outlined,
                          size: 14,
                        ),
                        label: Text(
                          '${active ? "ENCERRAR" : "REABRIR"} $semester',
                          style: const TextStyle(fontSize: 10),
                        ),
                      );
                    }),
                ],
              ),
            if (semesters.isNotEmpty) const SizedBox(height: 10),
            Expanded(
              child: _disciplines.isEmpty
                  ? const _EmptyState(
                      icon: Icons.menu_book_outlined,
                      text: 'Nenhuma disciplina cadastrada.',
                    )
                  : ListView.separated(
                      itemCount: _disciplines.length,
                      separatorBuilder: (_, __) => const Divider(
                          height: 10, color: AssistantTheme.border),
                      itemBuilder: (_, index) {
                        final discipline = _disciplines[index];
                        return Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    discipline.label,
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: discipline.active
                                          ? AssistantTheme.textPrimary
                                          : AssistantTheme.textMuted,
                                    ),
                                  ),
                                  Text(
                                    '${discipline.semester}  -  '
                                    '${discipline.classCount} turma(s)'
                                    '${discipline.active ? "" : "  -  ENCERRADA"}',
                                    style: const TextStyle(
                                        fontSize: 10,
                                        color: AssistantTheme.textMuted),
                                  ),
                                ],
                              ),
                            ),
                            IconButton(
                              tooltip: discipline.active
                                  ? 'Encerrar disciplina'
                                  : 'Reabrir disciplina',
                              icon: Icon(
                                discipline.active
                                    ? Icons.archive_outlined
                                    : Icons.unarchive_outlined,
                                size: 15,
                              ),
                              color: discipline.active
                                  ? AssistantTheme.c4
                                  : AssistantTheme.c3,
                              onPressed: () =>
                                  _setActive(discipline, !discipline.active),
                            ),
                            IconButton(
                              tooltip: 'Remover',
                              icon: const Icon(Icons.delete_outline, size: 15),
                              color: AssistantTheme.textMuted,
                              onPressed: () async {
                                try {
                                  await education
                                      .deleteDiscipline(discipline.id);
                                  await _reload();
                                } catch (e) {
                                  if (mounted) {
                                    setState(() => _status = '$e');
                                  }
                                }
                              },
                            ),
                          ],
                        );
                      },
                    ),
            ),
            if (_status.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(
                  _status,
                  style: const TextStyle(
                      fontSize: 11, color: AssistantTheme.danger),
                ),
              ),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: _Field(
                    controller: _codeCtrl,
                    label: 'CODIGO',
                    hint: 'ARA0040',
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  flex: 2,
                  child: _Field(
                    controller: _nameCtrl,
                    label: 'NOME',
                    hint: 'BANCO DE DADOS',
                    onSubmitted: (_) => _create(),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 82,
                  child: _Field(
                    controller: _semesterCtrl,
                    label: 'SEMESTRE',
                    hint: '2026.2',
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: _create,
                  icon: const Icon(Icons.add, size: 15),
                  label: const Text('CRIAR'),
                  style: FilledButton.styleFrom(
                    backgroundColor: AssistantTheme.c3,
                    foregroundColor: AssistantTheme.bg,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('FECHAR'),
        ),
      ],
    );
  }
}

// --- Componentes compartilhados --------------------------------------------

String _currentSemesterCode() {
  final now = DateTime.now();
  return '${now.year}.${now.month <= 6 ? 1 : 2}';
}

Future<String?> _askSegmentCorrection(
  BuildContext context,
  LessonSegment segment,
) async {
  final controller = TextEditingController(text: segment.text);
  final corrected = await showDialog<String>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      backgroundColor: AssistantTheme.surface,
      title: Text('Corrigir trecho ${segment.sequence}'),
      content: SizedBox(
        width: 560,
        child: TextField(
          controller: controller,
          autofocus: true,
          minLines: 4,
          maxLines: 10,
          style: const TextStyle(
            fontSize: 12,
            height: 1.45,
            color: AssistantTheme.textPrimary,
          ),
          decoration: const InputDecoration(
            hintText: 'Texto correto do que foi falado',
            filled: true,
            fillColor: AssistantTheme.bg2,
            border: OutlineInputBorder(),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('CANCELAR'),
        ),
        FilledButton(
          onPressed: () {
            final value = controller.text.trim();
            if (value.isNotEmpty) Navigator.pop(dialogContext, value);
          },
          child: const Text('SALVAR CORRECAO'),
        ),
      ],
    ),
  );
  controller.dispose();
  return corrected;
}

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
          style:
              const TextStyle(fontSize: 12, color: AssistantTheme.textPrimary),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle:
                const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
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

/// Lista de turmas com a mesma moldura dos campos de texto. Com [allLabel]
/// preenchido ganha uma primeira opcao que representa "sem filtro".
class _ClassDropdown extends StatelessWidget {
  final String label;
  final String hint;
  final List<ClassGroup> options;
  final ClassGroup? value;
  final String? allLabel;
  final ValueChanged<ClassGroup?> onChanged;

  const _ClassDropdown({
    required this.label,
    required this.hint,
    required this.options,
    required this.value,
    required this.onChanged,
    this.allLabel,
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
        DropdownButtonFormField<ClassGroup>(
          initialValue: value,
          isExpanded: true,
          hint: Text(
            hint,
            style:
                const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
          ),
          dropdownColor: AssistantTheme.surface,
          style:
              const TextStyle(fontSize: 12, color: AssistantTheme.textPrimary),
          icon: const Icon(Icons.arrow_drop_down,
              size: 18, color: AssistantTheme.textMuted),
          decoration: InputDecoration(
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
          items: [
            if (allLabel != null)
              DropdownMenuItem(
                value: null,
                child: Text(allLabel!,
                    style: const TextStyle(color: AssistantTheme.textMuted)),
              ),
            for (final option in options)
              DropdownMenuItem(
                value: option,
                child: Text(
                  option.display,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
          onChanged: onChanged,
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

/// Escolha entre resumo comum e detalhado. Fica ao lado de quem gera o resumo
/// (aula ao vivo e historico) porque a decisao e tomada na hora de gerar, e o
/// custo de escolher errado e uma nova rodada no modelo.
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

  const _PointTile({
    super.key,
    required this.point,
    required this.onDelete,
  });

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
  final String? tooltip;
  final Widget? action;

  const _Banner({
    required this.icon,
    required this.color,
    required this.text,
    this.tooltip,
    this.action,
  });

  @override
  Widget build(BuildContext context) {
    final banner = Container(
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
          if (action != null) ...[
            const SizedBox(width: 7),
            action!,
          ],
        ],
      ),
    );

    return tooltip == null ? banner : Tooltip(message: tooltip!, child: banner);
  }
}

/// Tela de partida da aba AULA. Explica o ciclo antes de gravar, porque a
/// pontuacao por voz nao tem botao para ser descoberta sozinha.
class _HowItWorks extends StatelessWidget {
  const _HowItWorks();

  static const _steps = [
    (
      Icons.edit_outlined,
      'Escolha a turma e clique em INICIAR AULA.',
      'A lista vem do cadastro, entao a disciplina da aula nasce igual a dos '
          'alunos. O tema e opcional e ajuda a achar a aula depois.',
    ),
    (
      Icons.mic_none,
      'De aula normalmente.',
      'A cada 60 segundos o audio vira um trecho transcrito aqui na tela.',
    ),
    (
      Icons.emoji_events_outlined,
      'Para dar ponto, cite o aluno em voz alta.',
      'Ex.: "meio ponto extra para a Ana pela participacao". O registro '
          'aparece no painel de pontuacoes no proximo trecho.',
    ),
    (
      Icons.summarize_outlined,
      'Ao terminar, use GERAR RESUMO ou ENCERRAR.',
      'Depois disso da para perguntar sobre a aula no chat do assistente.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final (icon, title, detail) in _steps)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(icon, size: 15, color: AssistantTheme.c3),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              title,
                              style: const TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                                color: AssistantTheme.textPrimary,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              detail,
                              style: const TextStyle(
                                fontSize: 11,
                                height: 1.45,
                                color: AssistantTheme.textMuted,
                              ),
                            ),
                          ],
                        ),
                      ),
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

/// Aba de Integrações - sincroniza presença e dados com sistemas acadêmicos
class _IntegrationsTab extends StatelessWidget {
  final _Classes classes;

  const _IntegrationsTab({required this.classes});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'LANÇAR PRESENÇA',
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            'Leve a chamada feita no INTARQ para o sistema acadêmico, '
            'sem reconferir aluno por aluno.',
            style: TextStyle(fontSize: 12, color: Colors.grey),
          ),
          const SizedBox(height: 24),

          // Card SIA Estácio
          Card(
            elevation: 2,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.cloud_download, size: 24, color: Colors.blue),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Estácio - SIA',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            const Text(
                              'Pauta Eletrônica',
                              style: TextStyle(
                                fontSize: 12,
                                color: Colors.grey,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Marca na Pauta Eletrônica quem fez check-in no INTARQ, '
                    'respeitando abonos e lançamentos bloqueados. A gravação '
                    'final continua sendo sua, no botão Confirmar do SIA.',
                    style: TextStyle(fontSize: 12),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: Colors.blue[50],
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Row(
                      children: [
                        Icon(Icons.cloud_upload_outlined,
                            size: 16, color: Colors.blue),
                        SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Use o ícone de nuvem na aba 5. PRESENÇA, '
                            'na chamada que quer lançar.',
                            style: TextStyle(fontSize: 11),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 24),
          const Divider(),
          const SizedBox(height: 12),
          Text(
            'PRÓXIMAS INTEGRAÇÕES',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            '📋 Google Classroom\n'
            '📊 Canvas LMS\n'
            '🎓 Blackboard\n'
            '⚙️ Sua integração aqui...',
            style: TextStyle(fontSize: 12, color: Colors.grey),
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

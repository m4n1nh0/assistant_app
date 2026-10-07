/// Janela do modo educacao, da gravacao ao relatorio.
///
/// Cobre gravacao em blocos, transcricao, resumo, turmas, alunos, presenca e quiz.
library;

import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:audioplayers/audioplayers.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:printing/printing.dart';
import 'package:record/record.dart';

import '../models/app_config.dart';
import '../services/api_service.dart';
import '../services/audio_input_service.dart';
import '../services/connected_ai_service.dart';
import '../services/education_service.dart';
import '../services/in_app_notification_service.dart';
import '../services/lesson_recovery_service.dart';
import '../services/lesson_pdf_service.dart';
import '../services/student_csv_parser.dart';
import '../services/system_audio_service.dart';
import '../utils/student_roster_diff.dart';
import 'summary_pickers.dart';
import '../providers/app_provider.dart';
import '../branding/intarq_brand.dart';
import '../utils/theme.dart';
import 'attendance_tab.dart';
import 'combined_summary_dialog.dart';
import 'meetings_tab.dart';
import 'education_dashboard.dart';
import 'lesson_recovery_banner.dart';
import 'recording_monitor.dart';
import 'quiz_generator_widget.dart';
import 'materials_panel.dart';
import 'quiz_center.dart';
import 'sia_attendance_importer.dart';
import 'study_time_tab.dart';
import 'project_groups_tab.dart';

/// Ordem das abas: e tambem a ordem de uso. Sem turma cadastrada os nomes
/// ouvidos na aula nao casam com ninguem, entao a turma vem antes.
const _dashboardTab = 0;
const _rosterTab = 1;
const _lessonTab = 2;
const _historyTab = 3;
const _pointsTab = 4;
const _attendanceTab = 5;
const _quizTab = 6;
const _groupsTab = 9;

/// Turmas conhecidas pelo backend, compartilhadas entre as abas. `null` = a
/// lista ainda nao chegou.
typedef _Classes = ValueNotifier<List<ClassGroup>?>;

/// Janela do modo educacao: gravacao, aulas, turmas, alunos e quiz.
///
/// Concentra o fluxo completo da aula, da gravacao em blocos ao resumo e ao
/// relatorio de pontos.
class EducationDialog extends StatefulWidget {
  final String startAt;
  final String initialGroupText;
  final String initialDisciplineCode;
  final String initialDisciplineHint;

  const EducationDialog({super.key, this.startAt = 'auto',
    this.initialGroupText = '', this.initialDisciplineCode = '',
    this.initialDisciplineHint = ''});

  @override
  State<EducationDialog> createState() => _EducationDialogState();
}

class _EducationDialogState extends State<EducationDialog> {
  /// Turmas compartilhadas entre as abas: TURMA escreve, AULA e PONTUACOES
  /// leem. Uma fonte so evita as duas pontas divergirem.
  final _Classes _classes = ValueNotifier<List<ClassGroup>?>(null);
  final ValueNotifier<String?> _quizLessonId = ValueNotifier<String?>(null);

  int? _initialTab;
  bool _maximized = false;

  @override
  void initState() {
    super.initState();
    _resolveInitialTab();
  }

  @override
  void dispose() {
    _classes.dispose();
    _quizLessonId.dispose();
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
      if (widget.startAt == 'groups') {
        _initialTab = _groupsTab;
      } else if (classes != null && classes.isEmpty) {
        _initialTab = _rosterTab;
      } else if (widget.startAt == 'attendance') {
        _initialTab = _attendanceTab;
      } else if (widget.startAt == 'quiz') {
        _initialTab = _quizTab;
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
    final size = MediaQuery.sizeOf(context);

    return PopScope(
      canPop: false,
      child: Dialog(
      insetPadding: _maximized
          ? EdgeInsets.zero
          : const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(4),
        side: const BorderSide(color: AssistantTheme.border2),
      ),
      child: SizedBox(
        width: _maximized ? size.width : math.min(1160, size.width - 48),
        height: _maximized ? size.height : math.min(820, size.height - 48),
        child: Column(
          children: [
            _buildHeader(context),
            if (initialTab == null)
              const Expanded(child: Center(child: CircularProgressIndicator()))
            else
              Expanded(
                child: DefaultTabController(
                  length: 11,
                  initialIndex: initialTab,
                  child: Builder(
                    builder: (tabContext) => Column(
                      children: [
                        LayoutBuilder(builder: (context, constraints) {
                          final compact = constraints.maxWidth < 1250;
                          final tabIconSize = compact ? 14.0 : 17.0;
                          return Row(children: [
                        IconButton(
                          tooltip: 'Aba anterior',
                          iconSize: compact ? 18 : 24,
                          visualDensity: compact ? VisualDensity.compact : VisualDensity.standard,
                          onPressed: () {
                            final controller = DefaultTabController.of(tabContext);
                            if (controller.index > 0) controller.animateTo(controller.index - 1);
                          },
                          icon: const Icon(Icons.chevron_left)),
                        Expanded(child: TabBar(
                          isScrollable: true,
                          tabAlignment: TabAlignment.start,
                          labelStyle: TextStyle(fontSize: compact ? 10 : 12),
                          labelPadding: EdgeInsets.symmetric(horizontal: compact ? 8 : 16),
                          indicatorColor: AssistantTheme.c3,
                          labelColor: AssistantTheme.c3,
                          unselectedLabelColor: AssistantTheme.textMuted,
                          tabs: [
                            Tab(
                                icon: Icon(Icons.dashboard_outlined, size: tabIconSize),
                                text: 'VISAO GERAL'),
                            Tab(
                                icon: Icon(Icons.groups_outlined, size: tabIconSize),
                                text: '1. TURMAS'),
                            Tab(
                                icon: Icon(Icons.mic_none, size: tabIconSize),
                                text: '2. GRAVAR'),
                            Tab(
                                icon: Icon(Icons.history, size: tabIconSize),
                                text: '3. HISTORICO'),
                            Tab(
                                icon:
                                    Icon(Icons.emoji_events_outlined, size: tabIconSize),
                                text: '4. PONTUACOES'),
                            Tab(
                                icon: Icon(Icons.how_to_reg_outlined, size: tabIconSize),
                                text: '5. PRESENCA'),
                            Tab(
                                icon: Icon(Icons.quiz_outlined, size: tabIconSize),
                                text: '6. QUIZ'),
                            Tab(
                                icon: Icon(Icons.folder_open_outlined,
                                    size: tabIconSize),
                                text: '7. MATERIAL'),
                            Tab(icon: Icon(Icons.timer_outlined, size: tabIconSize),
                                text: '8. TEMPO DE ESTUDO'),
                            Tab(icon: Icon(Icons.groups_2_outlined, size: tabIconSize),
                                text: '9. GRUPOS DE PROJETO'),
                            Tab(
                                icon: Icon(Icons.video_camera_front_outlined,
                                    size: tabIconSize),
                                text: '10. REUNIOES'),
                          ],
                        )),
                        IconButton(
                          tooltip: 'Próxima aba',
                          iconSize: compact ? 18 : 24,
                          visualDensity: compact ? VisualDensity.compact : VisualDensity.standard,
                          onPressed: () {
                            final controller = DefaultTabController.of(tabContext);
                            if (controller.index < controller.length - 1) {
                              controller.animateTo(controller.index + 1);
                            }
                          },
                          icon: const Icon(Icons.chevron_right)),
                        ]);
                        }),
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
                                    showDialog<void>(
                                      context: tabContext,
                                      builder: (hintContext) => AlertDialog(
                                        title: const Text('Conversar com a IA'),
                                        content: const Text(
                                          'O Modo Aula permanece aberto. Para voltar ao chat, '
                                          'feche esta janela pelo X.'),
                                        actions: [TextButton(
                                          onPressed: () => Navigator.pop(hintContext),
                                          child: const Text('Entendi'))],
                                      ),
                                    ),
                              ),
                              _RosterTab(classes: _classes),
                              _LessonTab(
                                classes: _classes,
                                onLessonClosedForQuiz: (lesson) {
                                  _quizLessonId.value = lesson.id;
                                  DefaultTabController.of(tabContext)
                                      .animateTo(_quizTab);
                                },
                              ),
                              _HistoryTab(classes: _classes),
                              _PointsTab(classes: _classes),
                              AttendanceTab(classes: _classes),
                              _QuizTab(selectedLessonId: _quizLessonId),
                              const MaterialsPanel(),
                              const StudyTimeTab(),
                              ProjectGroupsTab(
                                initialText: widget.initialGroupText,
                                initialDisciplineCode: widget.initialDisciplineCode,
                                initialDisciplineHint: widget.initialDisciplineHint,
                              ),
                              const MeetingsTab(),
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
            tooltip: _maximized ? 'Restaurar tamanho' : 'Maximizar',
            icon: Icon(_maximized ? Icons.fullscreen_exit : Icons.fullscreen,
                size: 20),
            color: AssistantTheme.textSecondary,
            onPressed: () => setState(() => _maximized = !_maximized),
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
  final ValueChanged<Lesson>? onLessonClosedForQuiz;

  const _LessonTab({
    required this.classes,
    this.onLessonClosedForQuiz,
  });

  @override
  ConsumerState<_LessonTab> createState() => _LessonTabState();
}

class _LessonTabState extends ConsumerState<_LessonTab> {
  /// Duracao de cada bloco de audio enviado ao backend. Blocos curtos dao
  /// retorno rapido na tela; blocos longos gastam menos chamadas de STT.
  static const _chunkDuration = Duration(seconds: 60);

  static const _sourceMic = 'mic';
  static const _sourceMeeting = 'meeting';

  final _recorder = AudioRecorder();

  /// Audio de gravacoes que o app deixou para tras (queda, janela fechada).
  List<RecoverableLesson> _recoverable = const [];
  final Map<String, String> _recoverLabels = {};
  String? _recoveringId;

  /// Medidor ao vivo: so ele se redesenha 5 vezes por segundo, nao a aba inteira.
  final _level = ValueNotifier<LevelReading>(const LevelReading());
  StreamSubscription<Amplitude>? _amplitudeSub;
  Timer? _levelTimer;
  DateTime? _lastSignalAt;
  Duration? _silentFor;
  DateTime? _blockStartedAt;
  int _blockBytes = 0;
  List<InputDevice> _inputDevices = const [];
  bool _switchingDevice = false;

  /// Blocos guardados da aula aberta e o que ja foi entregue de todas as aulas.
  List<StoredChunk> _chunks = const [];
  StoredAudioUsage _usage = const StoredAudioUsage();
  StoredAudioUsage _usageAll = const StoredAudioUsage();
  bool _showChunks = false;
  AudioPlayer? _player;
  String? _playingPath;
  final _systemRecorder = SystemAudioRecorder();
  final _titleCtrl = TextEditingController();
  final _focusCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();

  Lesson? _lesson;

  /// O que esta sendo gravado: `aula`, `apresentacao`, `palestra` ou `reuniao`. O
  /// mecanismo e o mesmo; muda o que precisa estar informado antes de comecar.
  String _kind = 'aula';
  String? _groupId;
  List<Map<String, dynamic>> _groups = const [];

  /// De onde vem o audio: so o microfone, ou o som do computador somado a
  /// ele. Reuniao online precisa do segundo: a voz dos outros participantes
  /// sai pelo fone e nunca passa pelo microfone.
  String _audioSource = _sourceMic;

  /// Captura do som do computador ligada no executavel.
  var _systemCapturing = false;

  /// O ultimo bloco fechou sem som nenhum vindo do computador.
  var _systemSilent = false;

  /// Por que a gravacao parou sozinha no meio da aula (microfone que sumiu).
  String? _captureFailure;
  var _importing = false;

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
    unawaited(_scanRecovery());
    unawaited(_loadInputDevices());
  }

  @override
  void dispose() {
    widget.classes.removeListener(_onClassesChanged);
    _chunkTimer?.cancel();
    _clockTimer?.cancel();
    _retryTimer?.cancel();
    _sessionTimer?.cancel();
    _levelTimer?.cancel();
    _amplitudeSub?.cancel();
    _level.dispose();
    _player?.dispose();
    // Sem await no dispose: o recorder e liberado em background.
    _recorder.dispose();
    if (_systemCapturing) _systemRecorder.stop().ignore();
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

  /// Carrega os grupos de projeto, para gravar a apresentacao de um deles.
  Future<void> _loadGroups() async {
    try {
      final groups = await education.listProjectGroups();
      if (mounted) setState(() => _groups = groups);
    } catch (_) {
      // Sem a lista a tela continua util nos outros tipos.
    }
  }

  bool get _fromMeeting => _audioSource == _sourceMeeting;

  /// O que o formulario diz sobre a gravacao, ja conferido. Nulo quando falta
  /// algo; o motivo vai para a linha de status.
  _LessonForm? _lessonForm() {
    final chosen = _chosen;
    final title = _titleCtrl.text.trim();
    var discipline = '';
    var semester = _currentSemesterCode();
    var classIds = const <String>[];

    if (_kind == 'aula') {
      if (chosen.isEmpty) {
        _setStatus('Selecione a turma antes de iniciar.');
        return null;
      }
      final disciplines = chosen.map((item) => item.discipline).toSet();
      discipline = disciplines.length == 1 ? disciplines.first : '';
      if (discipline.isEmpty) {
        _setStatus('As turmas escolhidas sao de disciplinas diferentes.');
        return null;
      }
      final semesters = chosen.map((item) => item.semester).toSet();
      if (semesters.length > 1) {
        _setStatus('As turmas escolhidas sao de semestres diferentes.');
        return null;
      }
      semester = semesters.length == 1 ? semesters.first : semester;
      classIds = chosen.map((item) => item.id).toList();
    } else if (_kind == 'apresentacao') {
      if ((_groupId ?? '').isEmpty) {
        _setStatus('Escolha o grupo que vai apresentar.');
        return null;
      }
    } else if (title.isEmpty) {
      _setStatus(_kind == 'reuniao'
          ? 'Dê um título à reunião antes de iniciar.'
          : 'Dê um título à palestra antes de iniciar.');
      return null;
    }

    return _LessonForm(
      kind: _kind,
      groupId: _kind == 'apresentacao' ? _groupId : null,
      discipline: discipline,
      semester: semester,
      title: title,
      classIds: classIds,
    );
  }

  /// Cria a gravacao no backend e zera o que a tela mostrava da anterior.
  Future<Lesson> _openLesson(_LessonForm form) async {
    // Gravacao de duas horas nao pode esbarrar no fim do token no meio.
    await api.refreshSession();
    final lesson = await education.createLesson(
      kind: form.kind,
      groupId: form.groupId,
      discipline: form.discipline,
      semester: form.semester,
      title: form.title,
      classIds: form.classIds,
    );
    if (mounted) {
      setState(() {
        _lesson = lesson;
        _segments.clear();
        _points.clear();
        _summary = null;
        _summaryShownStyle = null;
        _startedAt = DateTime.now();
        _elapsed = Duration.zero;
        _systemSilent = false;
      });
    }
    return lesson;
  }

  Future<void> _startLesson() async {
    final form = _lessonForm();
    if (form == null) return;

    if (!await _recorder.hasPermission()) {
      _setStatus('Microfone nao autorizado pelo sistema.');
      return;
    }

    setState(() => _starting = true);
    try {
      await _resolveInputDevice();
      await _openLesson(form);
      await _startRecordingLoop();
      _setStatus(_fromMeeting
          ? 'Gravando o som do computador e o microfone ($_activeInputLabel). '
              'Cada bloco de 60s e transcrito e indexado.'
          : 'Gravando com $_activeInputLabel. Cada bloco de 60s e '
              'transcrito e indexado.');
    } catch (e) {
      _setStatus('Nao foi possivel iniciar a aula: ${_errorText(e)}');
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  /// Reuniao que a propria plataforma ja transcreveu: o texto entra como
  /// trechos da gravacao, com o nome de quem falou e sem audio nenhum.
  Future<void> _importTranscript() async {
    final form = _lesson == null ? _lessonForm() : null;
    if (_lesson == null && form == null) return;

    final input = await _askTranscript(context);
    if (input == null || !mounted) return;

    setState(() => _importing = true);
    _setStatus('Importando a transcricao...');
    try {
      final lesson = _lesson ?? await _openLesson(form!);
      final result = await education.importTranscript(
        lesson.id,
        text: input.text,
        fileBytes: input.bytes,
        filename: input.filename,
      );
      final detail = await education.getLesson(lesson.id);
      if (!mounted) return;
      setState(() {
        _lesson = detail;
        _segments
          ..clear()
          ..addAll(detail.segments);
        _points
          ..clear()
          ..addAll(detail.points);
        _summary = null;
        _summaryShownStyle = null;
      });
      final speakers = result.speakers;
      _setStatus('${result.imported} trecho(s) importado(s)'
          '${speakers.isEmpty ? "" : " de ${speakers.length} participante(s): "
              "${speakers.take(6).join(", ")}"
              "${speakers.length > 6 ? "..." : ""}"}. '
          'Gere o resumo quando quiser.');
      _scrollToEnd();
    } catch (e) {
      _setStatus('Falha ao importar a transcricao: ${_errorText(e)}');
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  /// Erro do executavel chega como PlatformException, cujo texto util e so a
  /// mensagem.
  String _errorText(Object error) =>
      error is PlatformException ? (error.message ?? error.code) : '$error';

  Future<void> _startRecordingLoop() async {
    await _startChunk();
    _chunkTimer?.cancel();
    _chunkTimer = Timer.periodic(_chunkDuration, (_) => _rotateChunk());
    _clockTimer?.cancel();
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted || _startedAt == null) return;
      _tickMonitor();
      setState(() => _elapsed = DateTime.now().difference(_startedAt!));
    });
    _sessionTimer?.cancel();
    _sessionTimer = Timer.periodic(
      const Duration(minutes: 20),
      (_) => unawaited(api.refreshSession()),
    );
    if (mounted) {
      setState(() {
        _recording = true;
        _captureFailure = null;
      });
      _startLevelWatch();
    }
  }

  Future<void> _resolveInputDevice() async {
    final config = ref.read(configProvider);
    final devices = await _recorder.listInputDevices();
    final selected = resolveAudioInputDevice(
      devices,
      deviceId: config.audioInputDeviceId,
      deviceLabel: config.audioInputDeviceLabel,
    );
    final problem = audioInputProblem(
      devices,
      deviceId: config.audioInputDeviceId,
      deviceLabel: config.audioInputDeviceLabel,
    );
    if (problem != null) throw Exception(problem);
    _activeInputDevice = selected;
    _activeInputLabel = selected?.label ?? 'padrao do sistema';
  }

  /// Cada bloco vai para a pasta da propria aula, no disco do app. Se o app cair, o
  /// que ainda nao subiu fica guardado e e oferecido de volta ao reabrir.
  Future<String> _newChunkPath(String extension) =>
      lessonRecovery.newChunkPath(_lesson!.id, extension);

  Future<void> _startChunk() async {
    _blockStartedAt = DateTime.now();
    _blockBytes = 0;
    if (_fromMeeting) {
      _currentPath = await _newChunkPath('wav');
      await _systemRecorder.start(
        path: _currentPath!,
        micDeviceId: _activeInputDevice?.id ?? '',
      );
      _systemCapturing = true;
      return;
    }

    final supportsWav = await _recorder.isEncoderSupported(AudioEncoder.wav);
    final encoder = supportsWav ? AudioEncoder.wav : AudioEncoder.aacLc;
    _currentPath = await _newChunkPath(supportsWav ? 'wav' : 'm4a');

    await _recorder.start(
      speechRecordConfig(encoder: encoder, device: _activeInputDevice),
      path: _currentPath!,
    );
  }

  /// Fecha o bloco atual e ja abre o proximo, para nao perder a fala que
  /// acontece enquanto o trecho anterior sobe para o backend.
  ///
  /// Roda dentro de um Timer: excecao aqui nao chega a ninguem. O bloco que
  /// acabou de fechar entra na fila mesmo quando o proximo nao abre, e a queda
  /// do microfone para a gravacao com aviso em vez de deixar a tela dizendo
  /// "gravando" sobre um arquivo que nao existe.
  Future<void> _rotateChunk({bool restart = true}) async {
    String? path;
    SystemAudioChunk? system;
    Object? failure;
    try {
      if (_systemCapturing) {
        system = await _rotateSystemChunk(restart: restart);
        path = system?.path;
      } else {
        path = await _recorder.stop();
        if (restart) {
          try {
            await _startChunk();
          } catch (_) {
            // Fone Bluetooth que reconecta ou USB que oscila costuma voltar
            // em segundos: uma segunda tentativa, ja relendo a lista.
            await Future<void>.delayed(const Duration(seconds: 2));
            await _resolveInputDevice();
            await _startChunk();
          }
        }
      }
    } catch (e) {
      failure = e;
    }
    if (!restart) _currentPath = null;
    if (path != null) {
      _pendingUploads.add(_PendingChunk(
        path,
        _chunkDuration.inMilliseconds,
        micPeak: system?.micPeak,
        systemPeak: system?.systemPeak,
      ));
      unawaited(_drainUploads());
    }
    if (failure != null) _captureLost(failure);
    unawaited(_refreshChunks());
  }

  void _captureLost(Object error) {
    _chunkTimer?.cancel();
    _clockTimer?.cancel();
    _sessionTimer?.cancel();
    _stopLevelWatch();
    _currentPath = null;
    _systemCapturing = false;
    final reason = _errorText(error).replaceFirst('Exception: ', '');
    if (mounted) {
      setState(() {
        _recording = false;
        _captureFailure = reason;
      });
    }
    _setStatus('A gravacao parou: $reason. O que ja foi gravado esta '
        'guardado; reconecte o microfone e toque em retomar (▶).');
  }

  /// Na captura do som do computador o arquivo e trocado sem parar de gravar.
  Future<SystemAudioChunk?> _rotateSystemChunk({required bool restart}) async {
    final SystemAudioChunk? chunk;
    if (restart) {
      final next = await _newChunkPath('wav');
      chunk = await _systemRecorder.rotate(next);
      _currentPath = next;
    } else {
      chunk = await _systemRecorder.stop();
      _systemCapturing = false;
    }
    if (chunk != null && mounted) {
      setState(() => _systemSilent = chunk!.systemSilent);
    }
    return chunk;
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
      // 44 bytes e so o cabecalho do WAV: bloco em que nada foi captado.
      if (bytes.length <= 44) {
        await _discard(file);
        return true;
      }

      // O nivel que o bloco tinha, para a lista de blocos dizer se o problema foi
      // o microfone (silencio) ou o reconhecimento (tinha som, mas nao entendeu).
      await lessonRecovery.noteChunk(
        lesson.id,
        chunk.path,
        peak: LessonRecoveryService.wavPeak(bytes),
        micPeak: chunk.micPeak,
        systemPeak: chunk.systemPeak,
      );

      final result = await education.uploadAudioChunk(
        lesson.id,
        bytes,
        filename: chunk.path.split(Platform.pathSeparator).last,
        durationMs: chunk.durationMs,
      );

      // O bloco fica guardado ate a aula acabar e o professor decidir limpar: e
      // ele que permite ouvir o que voltou sem fala e reenviar.
      await lessonRecovery.markResult(
        lesson.id,
        file,
        state: result.skippedReason != null ? ChunkState.quiet : ChunkState.sent,
        detail: result.skippedReason ?? '',
      );
      unawaited(_refreshChunks());
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
      unawaited(lessonRecovery.noteFailure(lesson.id, chunk.path, '$e'));
      unawaited(_refreshChunks());
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

  // --- monitor de audio, dispositivo e blocos guardados -----------------------

  /// Abaixo disto (~ -54 dBFS) nao conta como som: e ruido de fundo do dispositivo.
  static const _signalThreshold = 0.002;

  void _startLevelWatch() {
    _stopLevelWatch();
    _lastSignalAt = DateTime.now();
    _silentFor = null;
    if (_fromMeeting) {
      var polling = false;
      _levelTimer = Timer.periodic(const Duration(milliseconds: 250), (_) async {
        if (polling || !_recording) return;
        polling = true;
        try {
          final level = await _systemRecorder.level();
          if (level != null) {
            _onLevel(level.micPeak, level.systemPeak);
            _blockBytes = level.bytes;
          }
        } catch (_) {
          // Sem medidor a gravacao segue: ele so mostra, nao decide nada.
        } finally {
          polling = false;
        }
      });
    } else {
      _amplitudeSub = _recorder
          .onAmplitudeChanged(const Duration(milliseconds: 200))
          .listen(
            (amplitude) => _onLevel(dbToPeak(amplitude.current), 0),
            onError: (_) {},
          );
    }
  }

  void _stopLevelWatch() {
    _levelTimer?.cancel();
    _levelTimer = null;
    _amplitudeSub?.cancel();
    _amplitudeSub = null;
    _level.value = const LevelReading();
    _silentFor = null;
  }

  void _onLevel(double mic, double system) {
    _level.value = LevelReading(mic: mic, system: system);
    if (mic >= _signalThreshold || system >= _signalThreshold) {
      _lastSignalAt = DateTime.now();
    }
  }

  /// A cada segundo: ha quanto tempo nao chega som e quanto do bloco ja foi escrito.
  void _tickMonitor() {
    final last = _lastSignalAt;
    if (last != null) {
      final idle = DateTime.now().difference(last);
      // Na reuniao quem fala e o outro lado: o microfone calado e normal, entao
      // so se avisa quando nada chega de nenhuma das duas origens, e com mais calma.
      final limit = Duration(seconds: _fromMeeting ? 20 : 8);
      _silentFor = idle >= limit ? idle : null;
    }
    if (!_fromMeeting) unawaited(_pollBlockBytes());
  }

  Future<void> _pollBlockBytes() async {
    final path = _currentPath;
    if (path == null) return;
    try {
      _blockBytes = await File(path).length();
    } catch (_) {
      _blockBytes = 0;
    }
  }

  Future<void> _loadInputDevices() async {
    try {
      final devices = await _recorder.listInputDevices();
      if (mounted) setState(() => _inputDevices = devices);
    } catch (_) {
      // Sem a lista a tela mostra so o padrao do sistema.
    }
  }

  /// Guarda o microfone escolhido na configuracao: vale para a proxima aula e e o
  /// mesmo que a tela de Configuracoes mostra.
  Future<void> _saveInputDevice(InputDevice? device) {
    return ref.read(configProvider.notifier).update((config) {
      final next = AppConfig.fromJson(config.toJson());
      next.audioInputDeviceId = device?.id ?? '';
      next.audioInputDeviceLabel = device?.label ?? '';
      return next;
    });
  }

  /// Troca o microfone. Com a gravacao em andamento, fecha o bloco atual (que segue
  /// para a fila) e abre o proximo ja no aparelho novo, sem parar a aula.
  Future<void> _switchInputDevice(InputDevice? device) async {
    if (_switchingDevice) return;
    setState(() => _switchingDevice = true);
    try {
      await _saveInputDevice(device);
      if (!_recording) {
        // Ainda nao ha gravacao: um aparelho que nao responde e so um aviso.
        try {
          await _resolveInputDevice();
          _setStatus('Microfone: $_activeInputLabel.');
        } catch (e) {
          _setStatus('Microfone indisponivel: ${_errorText(e)}');
        }
        return;
      }
      _chunkTimer?.cancel();
      await _rotateChunk(restart: false);
      await _resolveInputDevice();
      await _startChunk();
      _chunkTimer = Timer.periodic(_chunkDuration, (_) => _rotateChunk());
      _lastSignalAt = DateTime.now();
      _silentFor = null;
      _startLevelWatch();
      _setStatus('Gravando com $_activeInputLabel.');
    } catch (e) {
      _captureLost(e);
    } finally {
      if (mounted) setState(() => _switchingDevice = false);
    }
  }

  /// Relê os blocos guardados da aula aberta e o espaço que o áudio entregue ocupa.
  Future<void> _refreshChunks() async {
    try {
      final lesson = _lesson;
      final chunks =
          lesson == null ? const <StoredChunk>[] : await lessonRecovery.chunksOf(lesson.id);
      final usage = await lessonRecovery.usage(lessonId: lesson?.id);
      if (!mounted) return;
      setState(() {
        _chunks = chunks;
        _usage = usage;
      });
    } catch (_) {
      // A lista e informativa: sem ela a gravacao e o envio seguem iguais.
    }
  }

  Future<void> _playChunk(StoredChunk chunk) async {
    final player = _player ??= AudioPlayer()
      ..onPlayerComplete.listen((_) {
        if (mounted) setState(() => _playingPath = null);
      });
    try {
      if (_playingPath == chunk.file.path) {
        await player.stop();
        if (mounted) setState(() => _playingPath = null);
        return;
      }
      await player.stop();
      await player.play(DeviceFileSource(chunk.file.path));
      if (mounted) setState(() => _playingPath = chunk.file.path);
    } catch (e) {
      _setStatus('Nao consegui tocar o bloco: ${_errorText(e)}');
    }
  }

  /// Manda de novo para transcricao um bloco que voltou sem fala ou que falhou.
  Future<void> _resendChunk(StoredChunk chunk) async {
    final lesson = _lesson;
    if (lesson == null) return;
    try {
      var file = chunk.file;
      if (chunk.state == ChunkState.quiet) {
        file = await lessonRecovery.requeue(lesson.id, file);
      }
      if (_pendingUploads.any((item) => item.path == file.path)) return;
      _pendingUploads.add(_PendingChunk(
        file.path,
        chunk.durationMs,
        micPeak: chunk.micPeak,
        systemPeak: chunk.systemPeak,
      ));
      _setStatus('Reenviando o bloco para transcricao...');
      unawaited(_drainUploads());
      await _refreshChunks();
    } catch (e) {
      _setStatus('Nao consegui reenviar o bloco: ${_errorText(e)}');
    }
  }

  Future<void> _openChunkFolder() async {
    final lesson = _lesson;
    if (lesson == null || !Platform.isWindows) return;
    final dir = await lessonRecovery.folderOf(lesson.id);
    if (!await dir.exists()) {
      _setStatus('Ainda nao ha blocos guardados desta aula.');
      return;
    }
    await Process.run('explorer.exe', [dir.path]);
  }

  /// Limpeza pedida pelo professor, a qualquer momento. O que ainda nao subiu fica.
  Future<void> _clearDelivered() async {
    final lesson = _lesson;
    if (lesson == null) return;
    await _offerCleanup(lesson.id, closing: false);
  }

  /// Pergunta se o audio ja entregue desta aula deve sair do computador. Ao encerrar,
  /// a pergunta vem sozinha; o que ainda nao subiu nunca e apagado por aqui.
  Future<void> _offerCleanup(String lessonId, {bool closing = true}) async {
    final usage = await lessonRecovery.usage(lessonId: lessonId);
    if (!mounted || usage.chunks == 0) return;
    final clear = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: Text(closing
            ? 'Aula encerrada. Apagar o audio guardado?'
            : 'Apagar o audio ja entregue?'),
        content: Text(
          '${usage.chunks} bloco(s), ${usage.sizeLabel}, ficam no computador '
          '${closing ? "para o caso de precisar ouvir ou reenviar algo. " : ""}'
          'Ja foram aceitos pelo servidor.'
          '${usage.pending > 0 ? "\n\n${usage.pending} bloco(s) ainda nao foram enviados e continuam guardados." : ""}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('MANTER'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('APAGAR'),
          ),
        ],
      ),
    );
    if (clear == true) {
      final removed = await lessonRecovery.clearDelivered(lessonId: lessonId);
      _setStatus('$removed bloco(s) de audio apagado(s) do computador.');
    }
    await _refreshChunks();
    await _scanRecovery();
  }

  /// Medidor, seletor de microfone e lista de blocos. Aparece antes de gravar (so o
  /// seletor, para escolher o aparelho) e durante a aula.
  Widget _buildMonitorSection() {
    final config = ref.watch(configProvider);
    final resolved = resolveAudioInputDevice(
      _inputDevices,
      deviceId: config.audioInputDeviceId,
      deviceLabel: config.audioInputDeviceLabel,
    );
    final lesson = _lesson;
    final quiet = _chunks.where((chunk) => chunk.state == ChunkState.quiet).length;
    final failed = _chunks
        .where((chunk) =>
            chunk.state == ChunkState.pending && chunk.detail.isNotEmpty)
        .length;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: RecordingMonitor(
            level: _level,
            recording: _recording,
            showSystem: _fromMeeting,
            devices: _inputDevices,
            selectedId: resolved?.id ?? config.audioInputDeviceId,
            selectedLabel: config.audioInputDeviceLabel,
            onSelectDevice: _switchInputDevice,
            onRefreshDevices: _loadInputDevices,
            busy: _switchingDevice || _starting,
            silentFor: _silentFor,
            blockElapsed: _blockStartedAt == null
                ? Duration.zero
                : DateTime.now().difference(_blockStartedAt!),
            blockBytes: _blockBytes,
            idleHint: lesson == null
                ? 'O medidor funciona durante a gravacao. Escolha o microfone '
                    'aqui antes de comecar; a escolha vale tambem em Configuracoes.'
                : null,
          ),
        ),
        if (lesson != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                InkWell(
                  onTap: () => setState(() => _showChunks = !_showChunks),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(
                      children: [
                        Icon(
                          _showChunks ? Icons.expand_less : Icons.expand_more,
                          size: 16,
                          color: AssistantTheme.textMuted,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          'Blocos gravados: ${_chunks.length}'
                          '${quiet > 0 ? " · $quiet sem fala" : ""}'
                          '${failed > 0 ? " · $failed com falha" : ""}',
                          style: TextStyle(
                            fontSize: 11,
                            color: quiet > 0 || failed > 0
                                ? AssistantTheme.c4
                                : AssistantTheme.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                if (_showChunks)
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 230),
                    child: SingleChildScrollView(
                      child: ChunkList(
                        chunks: _chunks,
                        usage: _usage,
                        livePath: _recording ? _currentPath : null,
                        playingPath: _playingPath,
                        onPlay: _playChunk,
                        onResend: _resendChunk,
                        onOpenFolder: _openChunkFolder,
                        onClear: _clearDelivered,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        if (lesson == null && _usageAll.chunks > 0)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                const Icon(Icons.folder_outlined,
                    size: 14, color: AssistantTheme.textMuted),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Audio de aulas guardado neste computador: ${_usageAll.chunks} '
                    'bloco(s), ${_usageAll.sizeLabel}.',
                    style: const TextStyle(
                        fontSize: 10, color: AssistantTheme.textMuted),
                  ),
                ),
                TextButton(
                  onPressed: () async {
                    await lessonRecovery.clearDelivered();
                    await _scanRecovery();
                  },
                  child: const Text('LIMPAR', style: TextStyle(fontSize: 10)),
                ),
              ],
            ),
          ),
      ],
    );
  }

  /// Procura audio guardado de gravacoes interrompidas. A aula que esta gravando
  /// agora fica de fora: os arquivos dela estao em uso.
  Future<void> _scanRecovery() async {
    try {
      final found = await lessonRecovery.scan(ignoreLessonId: _lesson?.id);
      final usage = await lessonRecovery.usage();
      if (!mounted) return;
      setState(() {
        _recoverable = found;
        _usageAll = usage;
      });
      for (final lesson in found) {
        unawaited(_labelRecoverable(lesson.lessonId));
      }
    } catch (_) {
      // Sem a varredura a gravacao continua funcionando; so nao oferece recuperar.
    }
  }

  Future<void> _labelRecoverable(String lessonId) async {
    try {
      final lesson = await education.getLesson(lessonId, includeSegments: false);
      final label = [lesson.discipline, lesson.title]
          .where((part) => part.trim().isNotEmpty)
          .join(' - ');
      if (mounted && label.isNotEmpty) {
        setState(() => _recoverLabels[lessonId] = label);
      }
    } catch (_) {
      // Aula que o servidor nao devolve: o aviso fica sem o nome.
    }
  }

  Future<void> _recoverAudio(RecoverableLesson lesson) async {
    if (_recoveringId != null) return;
    setState(() => _recoveringId = lesson.lessonId);
    _setStatus('Enviando o audio guardado da gravacao interrompida...');
    try {
      // O login pode ter vencido enquanto o app estava fechado.
      await api.refreshSession();
      final result = await lessonRecovery.recover(lesson, (chunk, bytes) async {
        final sent = await education.uploadAudioChunk(
          lesson.lessonId,
          bytes,
          filename: chunk.name,
          durationMs: chunk.durationMs,
        );
        return ChunkDelivery(
          quiet: sent.skippedReason != null,
          detail: sent.skippedReason ?? '',
        );
      });
      if (!mounted) return;
      await _scanRecovery();
      if (result.complete) {
        _setStatus('${result.sent} bloco(s) recuperado(s) e enviados para '
            'transcricao. Abra a aula no historico para ver o texto.');
        unawaited(_offerCleanup(lesson.lessonId));
      } else {
        final reason = '${result.error}'.contains('HTTP 409')
            ? 'a aula ja foi encerrada e o servidor nao aceita mais audio nela'
            : '${result.error}'.replaceFirst('Exception: ', '');
        _setStatus('${result.sent} bloco(s) enviado(s); ${result.remaining} '
            'continuam guardados: $reason');
      }
    } catch (e) {
      _setStatus('Nao consegui recuperar o audio: ${_errorText(e)}');
    } finally {
      if (mounted) setState(() => _recoveringId = null);
    }
  }

  Future<void> _discardRecovery(RecoverableLesson lesson) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Descartar o audio guardado?'),
        content: Text(
          '${lesson.chunks.length} bloco(s), cerca de '
          '${recoveryDuration(lesson.approxSeconds)} de gravacao, saem do '
          'computador. Nao da para recuperar depois.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('CANCELAR'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('DESCARTAR'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await lessonRecovery.discard(lesson.lessonId);
    await _scanRecovery();
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
    _stopLevelWatch();
    if (_recording) await _rotateChunk(restart: false);
    if (mounted) setState(() => _recording = false);
    unawaited(_refreshChunks());
    _setStatus('Gravacao pausada. Envie o resumo quando quiser.');
  }

  Future<void> _resumeRecording() async {
    if (_lesson == null || _lesson!.isClosed) return;
    try {
      await _resolveInputDevice();
      await _startRecordingLoop();
      _setStatus(_fromMeeting
          ? 'Gravacao retomada com o som do computador e $_activeInputLabel.'
          : 'Gravacao retomada com $_activeInputLabel.');
    } catch (e) {
      _setStatus('Nao foi possivel retomar a gravacao: ${_errorText(e)}');
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
        if (refreshed.isClosed) {
          widget.onLessonClosedForQuiz?.call(refreshed);
          unawaited(_offerCleanup(lesson.id));
        }
      }
    } catch (e) {
      _setStatus('Falha ao gerar resumo: $e');
    } finally {
      if (mounted) setState(() => _summarising = false);
    }
  }

  /// Encerra a aula sem passar pelo resumo.
  ///
  /// O ENCERRAR ao lado gera o resumo e so entao fecha: quando o modelo nao
  /// responde, o resumo falha e a aula fica gravando para sempre. Este caminho
  /// so mexe no status, que e o que a tela de quiz e o historico leem.
  Future<void> _closeWithoutSummary() async {
    final lesson = _lesson;
    if (lesson == null) return;
    try {
      final atualizada = await education.setLessonStatus(lesson.id, 'closed');
      if (!mounted) return;
      setState(() => _lesson = atualizada);
      _setStatus('Aula encerrada sem resumo. O quiz aceita a transcricao.');
      widget.onLessonClosedForQuiz?.call(atualizada);
      unawaited(_offerCleanup(lesson.id));
    } catch (e) {
      _setStatus('Falha ao encerrar a aula: $e');
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
          _buildMonitorSection(),
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
          for (final lesson in _recoverable)
            LessonRecoveryBanner(
              lesson: lesson,
              label: _recoverLabels[lesson.lessonId] ?? '',
              busy: _recoveringId == lesson.lessonId,
              onRecover: () => _recoverAudio(lesson),
              onDiscard: () => _discardRecovery(lesson),
            ),
          if (_captureFailure != null && !_recording)
            _Banner(
              icon: Icons.mic_off_outlined,
              color: AssistantTheme.c4,
              text: 'A gravacao parou: $_captureFailure. O que ja foi '
                  'gravado esta guardado. Reconecte o microfone e toque em '
                  'retomar.',
            ),
          if (_recording && _systemCapturing && _systemSilent)
            const _Banner(
              icon: Icons.volume_off_outlined,
              color: AssistantTheme.c4,
              text: 'Nenhum som do computador no ultimo bloco: so o microfone '
                  'foi gravado. Se a reuniao esta em andamento, confira se '
                  'ela toca na saida de som padrao do Windows.',
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

  /// Escolha do que esta sendo gravado, e o que cada tipo exige.
  Widget _buildKindPicker() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'aula', label: Text('Aula'), icon: Icon(Icons.school_outlined, size: 15)),
            ButtonSegment(
                value: 'apresentacao',
                label: Text('Apresentação'),
                icon: Icon(Icons.groups_2_outlined, size: 15)),
            ButtonSegment(
                value: 'palestra',
                label: Text('Palestra'),
                icon: Icon(Icons.campaign_outlined, size: 15)),
            ButtonSegment(
                value: 'reuniao',
                label: Text('Reunião'),
                icon: Icon(Icons.video_camera_front_outlined, size: 15)),
          ],
          selected: {_kind},
          showSelectedIcon: false,
          onSelectionChanged: (value) {
            final kind = value.first;
            setState(() {
              _kind = kind;
              // Na reuniao online a voz dos outros sai pelo fone e nao passa pelo
              // microfone: o som do computador ja vem marcado (e pode ser trocado).
              if (kind == 'reuniao' && SystemAudioRecorder.isSupported) {
                _audioSource = _sourceMeeting;
              }
            });
            if (kind == 'apresentacao' && _groups.isEmpty) _loadGroups();
          },
        ),
        const SizedBox(height: 6),
        Text(
          switch (_kind) {
            'apresentacao' =>
              'A gravação fica no grupo, e herda a disciplina e o período dele.',
            'palestra' =>
              'Sem disciplina e sem turma: o título é o que identifica a palestra. '
                  'Ela também vira fonte de quiz e de busca no chat.',
            'reuniao' =>
              'Sem disciplina e sem turma: o título identifica a reunião. O resumo '
                  'sai com decisões, encaminhamentos e pendências.',
            _ => 'Aula da turma, como sempre: transcrição, resumo e quiz.',
          },
          style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
        if (_kind == 'apresentacao') ...[
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            value: _groupId,
            isExpanded: true,
            decoration: const InputDecoration(
              isDense: true,
              labelText: 'GRUPO QUE VAI APRESENTAR',
            ),
            items: [
              for (final group in _groups)
                DropdownMenuItem(
                  value: group['id']?.toString(),
                  child: Text(
                    [
                      group['name']?.toString() ?? 'Grupo',
                      // Nome de grupo se repete entre disciplinas: sem ela, a
                      // escolha e as cegas.
                      if ((group['discipline']?.toString() ?? '').isNotEmpty)
                        group['discipline'].toString(),
                      if ((group['semester']?.toString() ?? '').isNotEmpty)
                        group['semester'].toString(),
                      if ((group['project_title']?.toString() ?? '').isNotEmpty)
                        group['project_title'].toString(),
                    ].join(' • '),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
            ],
            onChanged: (value) => setState(() => _groupId = value),
          ),
          if (_groups.isEmpty)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                'Nenhum grupo cadastrado. Crie os grupos na aba GRUPOS DE PROJETO.',
                style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
              ),
            ),
        ],
        const SizedBox(height: 12),
      ],
    );
  }

  /// De onde vem o audio. So aparece onde a captura do som do computador
  /// existe.
  Widget _buildSourcePicker() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(
                value: _sourceMic,
                label: Text('Microfone'),
                icon: Icon(Icons.mic_none, size: 15)),
            ButtonSegment(
                value: _sourceMeeting,
                label: Text('Reunião online'),
                icon: Icon(Icons.video_call_outlined, size: 15)),
          ],
          selected: {_audioSource},
          showSelectedIcon: false,
          onSelectionChanged: (value) =>
              setState(() => _audioSource = value.first),
        ),
        const SizedBox(height: 6),
        Text(
          _fromMeeting
              ? 'Grava o som do computador (Meet, Teams) junto com o seu '
                  'microfone. Avise os participantes de que a reunião está '
                  'sendo gravada.'
              : 'Grava só o microfone, como em sala.',
          style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
        ),
        const SizedBox(height: 12),
      ],
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

        final podeIniciar = switch (_kind) {
          'aula' => chosen.isNotEmpty,
          'apresentacao' => (_groupId ?? '').isNotEmpty,
          _ => true,
        };

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildKindPicker(),
            if (SystemAudioRecorder.isSupported) _buildSourcePicker(),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  flex: 2,
                  child: _Field(
                    controller: _titleCtrl,
                    label: switch (_kind) {
                      'apresentacao' => 'TÍTULO DA APRESENTAÇÃO (OPCIONAL)',
                      'palestra' => 'TÍTULO DA PALESTRA',
                      'reuniao' => 'TÍTULO DA REUNIÃO',
                      _ => 'TEMA DA AULA',
                    },
                  ),
                ),
                const SizedBox(width: 10),
                Tooltip(
                  message: 'Reunião já transcrita pelo Teams ou pelo Meet: '
                      'traz o texto pronto, com o nome de quem falou.',
                  child: OutlinedButton.icon(
                    onPressed: _starting || _importing || !podeIniciar
                        ? null
                        : _importTranscript,
                    icon: const Icon(Icons.upload_file_outlined, size: 15),
                    label: Text(
                      _importing ? 'IMPORTANDO...' : 'IMPORTAR TRANSCRIÇÃO',
                    ),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AssistantTheme.c2,
                      side: const BorderSide(color: AssistantTheme.border2),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                FilledButton.icon(
                  onPressed: _starting || _importing || !podeIniciar
                      ? null
                      : _startLesson,
                  icon: const Icon(Icons.fiber_manual_record, size: 15),
                  label: Text(
                    _starting
                        ? 'INICIANDO...'
                        : _kind == 'aula'
                            ? 'INICIAR AULA'
                            : 'INICIAR GRAVAÇÃO',
                  ),
                  style: FilledButton.styleFrom(
                    backgroundColor: AssistantTheme.c3,
                    foregroundColor: AssistantTheme.bg,
                  ),
                ),
              ],
            ),
            // Turma so existe em aula: apresentacao pertence ao grupo e
            // palestra nao pertence a nenhuma.
            if (_kind == 'aula') ...[
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
        if (!lesson.isClosed && !_recording)
          IconButton(
            tooltip: 'Importar transcricao pronta (Teams, Meet)',
            icon: const Icon(Icons.upload_file_outlined, size: 18),
            color: AssistantTheme.c1,
            onPressed: _importing || _summarising ? null : _importTranscript,
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
          IconButton(
            tooltip: 'Encerrar sem gerar resumo',
            icon: const Icon(Icons.stop_circle_outlined, size: 18),
            color: AssistantTheme.textMuted,
            onPressed: _summarising ? null : _closeWithoutSummary,
          ),
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
        title:
            '${summaryHeading(_lesson?.kind ?? _kind)}  -  ${summaryStyleLabel(_summaryShownStyle)}',
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
                          setState(() =>
                              _points.removeWhere((p) => p.id == pointId));
                        } catch (e) {
                          _setStatus('Falha ao remover: $e');
                        }
                      },
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 10),
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

  /// Picos (0 a 1) que a captura da reuniao online mediu no bloco, por origem.
  final double? micPeak;
  final double? systemPeak;

  _PendingChunk(this.path, this.durationMs, {this.micPeak, this.systemPeak});
}

/// O que o formulario de `2. Gravar` informa para abrir uma gravacao.
class _LessonForm {
  final String kind;
  final String? groupId;
  final String discipline;
  final String semester;
  final String title;
  final List<String> classIds;

  const _LessonForm({
    required this.kind,
    required this.groupId,
    required this.discipline,
    required this.semester,
    required this.title,
    required this.classIds,
  });
}

/// Transcricao pronta escolhida pelo professor: texto colado ou arquivo.
class _TranscriptInput {
  final String text;
  final List<int>? bytes;
  final String filename;

  const _TranscriptInput({this.text = '', this.bytes, this.filename = ''});
}

Future<_TranscriptInput?> _askTranscript(BuildContext context) async {
  final controller = TextEditingController();
  final input = await showDialog<_TranscriptInput>(
    context: context,
    builder: (dialogContext) => StatefulBuilder(
      builder: (dialogContext, update) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Importar transcrição da reunião'),
        content: SizedBox(
          width: 560,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Cole o texto ou escolha o arquivo gerado pelo Teams (.vtt, '
                '.docx) ou pelo Meet (.docx, .txt). O nome de quem falou é '
                'mantido em cada trecho.',
                style: TextStyle(
                  fontSize: 11,
                  height: 1.45,
                  color: AssistantTheme.textMuted,
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: controller,
                autofocus: true,
                minLines: 8,
                maxLines: 14,
                onChanged: (_) => update(() {}),
                style: const TextStyle(
                  fontSize: 12,
                  height: 1.45,
                  color: AssistantTheme.textPrimary,
                ),
                decoration: const InputDecoration(
                  hintText: 'Ana Souza: bom dia a todos, vamos começar...',
                  filled: true,
                  fillColor: AssistantTheme.bg2,
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('CANCELAR'),
          ),
          OutlinedButton.icon(
            onPressed: () async {
              final selected = await FilePicker.pickFiles(
                type: FileType.custom,
                allowedExtensions: const ['vtt', 'docx', 'txt', 'srt', 'md'],
                withData: true,
              );
              if (selected == null || selected.files.isEmpty) return;
              final file = selected.files.single;
              final bytes = file.bytes ??
                  (file.path == null
                      ? null
                      : await File(file.path!).readAsBytes());
              if (bytes != null && dialogContext.mounted) {
                Navigator.pop(
                  dialogContext,
                  _TranscriptInput(bytes: bytes, filename: file.name),
                );
              }
            },
            icon: const Icon(Icons.upload_file_outlined, size: 16),
            label: const Text('ESCOLHER ARQUIVO'),
          ),
          FilledButton(
            onPressed: controller.text.trim().isEmpty
                ? null
                : () => Navigator.pop(
                      dialogContext,
                      _TranscriptInput(text: controller.text),
                    ),
            child: const Text('IMPORTAR TEXTO'),
          ),
        ],
      ),
    ),
  );
  controller.dispose();
  return input;
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

// --- Quiz -----------------------------------------------------------------

class _QuizTab extends StatefulWidget {
  final ValueListenable<String?> selectedLessonId;

  const _QuizTab({required this.selectedLessonId});

  @override
  State<_QuizTab> createState() => _QuizTabState();
}

class _QuizTabState extends State<_QuizTab> {
  List<Lesson> _lessons = [];
  Lesson? _selected;
  final _centerKey = GlobalKey<QuizCenterTabsState>();
  var _loading = false;
  var _status = '';

  @override
  void initState() {
    super.initState();
    widget.selectedLessonId.addListener(_onSelectedLessonChanged);
    _load(keepId: widget.selectedLessonId.value);
  }

  @override
  void didUpdateWidget(covariant _QuizTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedLessonId == widget.selectedLessonId) return;
    oldWidget.selectedLessonId.removeListener(_onSelectedLessonChanged);
    widget.selectedLessonId.addListener(_onSelectedLessonChanged);
    _load(keepId: widget.selectedLessonId.value);
  }

  @override
  void dispose() {
    widget.selectedLessonId.removeListener(_onSelectedLessonChanged);
    super.dispose();
  }

  void _onSelectedLessonChanged() {
    final lessonId = widget.selectedLessonId.value;
    if (lessonId == null || lessonId.isEmpty) return;
    final lesson = _findLesson(lessonId, _lessons);
    if (lesson != null) {
      _selectLesson(lesson);
    } else {
      unawaited(_load(keepId: lessonId));
    }
  }

  Lesson? _findLesson(String lessonId, List<Lesson> lessons) {
    for (final lesson in lessons) {
      if (lesson.id == lessonId) return lesson;
    }
    return null;
  }

  Future<void> _load({String? keepId}) async {
    setState(() {
      _loading = true;
      _status = '';
    });
    try {
      // Aula em andamento tambem serve de fonte: o quiz relampago no meio da
      // aula e o caso que mais aparece, e filtrar por encerrada escondia
      // justamente a aula de hoje - inclusive a que ficou aberta porque o
      // resumo falhou na hora de encerrar.
      final lessons = await education.listLessons(limit: 200);
      if (!mounted) return;
      final wanted = keepId ?? _selected?.id;
      final selected = wanted == null ? null : _findLesson(wanted, lessons);
      setState(() {
        _lessons = lessons;
        _selected = selected ?? (lessons.isEmpty ? null : lessons.first);
      });
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao carregar aulas: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _selectLesson(Lesson lesson) {
    setState(() => _selected = lesson);
  }

  String _when(Lesson lesson) {
    final start = lesson.startedAt?.toLocal();
    if (start == null) return 'sem data';
    final day = '${start.day.toString().padLeft(2, '0')}/'
        '${start.month.toString().padLeft(2, '0')}/${start.year}';
    final hour = '${start.hour.toString().padLeft(2, '0')}:'
        '${start.minute.toString().padLeft(2, '0')}';
    return '$day $hour';
  }

  String _lessonTitle(Lesson lesson) =>
      lesson.title.isEmpty ? lesson.discipline : lesson.title;

  Widget _buildList() {
    return _Panel(
      title: 'AULAS',
      trailing: IconButton(
        tooltip: 'Atualizar aulas',
        visualDensity: VisualDensity.compact,
        icon: const Icon(Icons.refresh, size: 15),
        color: AssistantTheme.textMuted,
        onPressed: _loading ? null : () => _load(),
      ),
      child: _loading
          ? const Center(child: CircularProgressIndicator())
          : _lessons.isEmpty
              ? const _EmptyState(
                  icon: Icons.quiz_outlined,
                  text: 'Grave uma aula para criar o quiz dela.',
                )
              : ListView.separated(
                  itemCount: _lessons.length,
                  separatorBuilder: (_, __) =>
                      const Divider(height: 12, color: AssistantTheme.border),
                  itemBuilder: (_, index) {
                    final lesson = _lessons[index];
                    final selected = lesson.id == _selected?.id;
                    final hasSummary =
                        lesson.summary != null && lesson.summary!.isNotEmpty;
                    // O que decide se a aula vira quiz e ter texto, nao estar
                    // encerrada: resumo validado ou transcricao ja gravada.
                    final temTexto = hasSummary || lesson.transcriptChars > 0;
                    final turmas = lesson.classLabels.isEmpty
                        ? (lesson.classGroup.isEmpty
                            ? 'sem turma'
                            : lesson.classGroup)
                        : lesson.classLabels.join(' + ');

                    return InkWell(
                      onTap: () => _selectLesson(lesson),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 5),
                        child: Row(
                          children: [
                            Icon(
                              temTexto
                                  ? Icons.quiz_outlined
                                  : Icons.summarize_outlined,
                              size: 14,
                              color: temTexto
                                  ? AssistantTheme.c3
                                  : AssistantTheme.textMuted,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    '${_when(lesson)}  -  ${lesson.displayLabel}',
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
                                    '${lesson.title.isEmpty ? "" : "  -  ${lesson.title}"}'
                                    '  -  '
                                    '${lesson.isClosed ? "encerrada" : "em andamento"}'
                                    '${hasSummary ? ", com resumo" : ""}',
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontSize: 10,
                                      color: AssistantTheme.textMuted,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
    );
  }

  Widget _buildGenerator() {
    final lesson = _selected;
    if (lesson == null) {
      return const _Panel(
        title: 'QUIZ DA AULA',
        child: _EmptyState(
          icon: Icons.quiz_outlined,
          text: 'Escolha uma aula para preparar o quiz.',
        ),
      );
    }

    final hasSummary = lesson.summary != null && lesson.summary!.isNotEmpty;
    // O gerador aceita resumo ou transcricao, e a aula nao precisa estar
    // encerrada. So aula sem texto nenhum nao tem de onde tirar pergunta.
    if (!hasSummary && lesson.transcriptChars == 0) {
      return const _Panel(
        title: 'QUIZ DA AULA',
        child: _EmptyState(
          icon: Icons.summarize_outlined,
          text: 'Esta aula ainda nao tem texto: sem resumo e sem transcricao '
              'gravada, nao ha de onde tirar as perguntas.',
        ),
      );
    }

    return _Panel(
      title: 'QUIZ DA AULA',
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${lesson.discipline}'
                    '${lesson.title.isEmpty ? "" : "  -  ${lesson.title}"}',
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AssistantTheme.textPrimary,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '${_when(lesson)}  -  '
              '${lesson.isClosed ? "encerrada" : "em andamento"}  -  '
              '${lesson.segmentCount} trecho(s), '
              '${lesson.transcriptChars} caracteres',
              style: const TextStyle(
                  fontSize: 11, color: AssistantTheme.textMuted),
            ),
            const SizedBox(height: 12),
            QuizGeneratorWidget(
              // Chave pela aula: trocar de aula recomeca o pedido com a fonte
              // certa marcada, em vez de herdar a selecao da anterior.
              key: ValueKey(lesson.id),
              lessonId: lesson.id,
              lessonTitle: _lessonTitle(lesson),
              disciplineName: lesson.discipline,
              onQueued: (job) {
                setState(() => _status =
                    'Pedido "${job.titulo}" na fila. Acompanhe na aba FILA.');
                _centerKey.currentState?.showQueue();
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
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
            // Gerar, acompanhar a fila, revisar quizzes e reaproveitar questoes
            // ficam no mesmo lugar: sao etapas do mesmo fluxo.
            child: QuizCenterTabs(
              key: _centerKey,
              generator: Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(width: 360, child: _buildList()),
                    const SizedBox(width: 14),
                    Expanded(child: _buildGenerator()),
                  ],
                ),
              ),
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

  /// O que a lista de alunos mostra. Comeca nos ativos, que e a turma de fato;
  /// desativado so aparece quando o professor vai atras dele.
  _StudentFilter _studentFilter = _StudentFilter.ativos;
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
      // Traz ativos e desativados: o filtro da tela e local, entao alternar
      // nao custa uma ida ao servidor.
      final students = await education.listStudents(
        classId: group.id,
        activeOnly: false,
      );
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

  /// Mostra linha a linha o que a planilha vai fazer e devolve o que aplicar.
  ///
  /// Retorna `null` quando o professor cancela. A lista vem toda marcada -
  /// aceitar o arquivo inteiro e o caso comum - mas cada linha e desmarcavel,
  /// porque a decisao real e por aluno: o que trancou some da planilha e ainda
  /// precisa aparecer na chamada, e as vezes um nome novo e engano do sistema
  /// academico.
  Future<_RosterImportChoice?> _confirmRosterImport(
    ClassGroup group,
    List<StudentCsvRow> rows,
    RosterDiff diff,
  ) async {
    final entries = diff.entries;
    final marcadas = {for (final entry in entries)
      if (entry.action != RosterAction.ausente) entry.key};

    return showDialog<_RosterImportChoice>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) {
          final novos = entries
              .where((e) => e.action == RosterAction.novo && marcadas.contains(e.key))
              .length;
          final ausentes = entries
              .where((e) =>
                  e.action == RosterAction.ausente && marcadas.contains(e.key))
              .length;

          return AlertDialog(
            backgroundColor: AssistantTheme.surface,
            title: const Text('Importar alunos'),
            content: SizedBox(
              width: 620,
              height: 460,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${group.display} · fonte com ${rows.length} linha(s)',
                    style: const TextStyle(color: AssistantTheme.textPrimary),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '$novos a cadastrar · ${diff.kept.length} na turma · '
                    '$ausentes a desativar',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AssistantTheme.textMuted,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Checkbox(
                        value: marcadas.length == entries.length
                            ? true
                            : (marcadas.isEmpty ? false : null),
                        tristate: true,
                        onChanged: (_) => setDialogState(() {
                          if (marcadas.length == entries.length) {
                            marcadas.clear();
                          } else {
                            marcadas
                              ..clear()
                              ..addAll(entries.map((e) => e.key));
                          }
                        }),
                      ),
                      const Text(
                        'Selecionar todos',
                        style: TextStyle(
                          fontSize: 11,
                          color: AssistantTheme.textSecondary,
                        ),
                      ),
                    ],
                  ),
                  const Divider(height: 1, color: AssistantTheme.border),
                  Expanded(
                    child: ListView.builder(
                      itemCount: entries.length,
                      itemBuilder: (_, index) {
                        final entry = entries[index];
                        return _RosterPreviewRow(
                          entry: entry,
                          checked: marcadas.contains(entry.key),
                          onChanged: (marcado) => setDialogState(() {
                            if (marcado) {
                              marcadas.add(entry.key);
                            } else {
                              marcadas.remove(entry.key);
                            }
                          }),
                        );
                      },
                    ),
                  ),
                  if (diff.unmatchable.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(
                        '${diff.unmatchable.length} aluno(s) sem matricula '
                        'cadastrada nao entraram na comparacao.',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                    ),
                  if (ausentes > 0)
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Text(
                        'Desativar tira o aluno das listas e preserva presenca, '
                        'pontos e respostas de quiz ja registrados.',
                        style: TextStyle(
                          fontSize: 11,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                    ),
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text('Alunos ausentes na fonte ficam ativos por padrão. Marque cada ausência se quiser desativá-la.',
                      style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted)),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('CANCELAR'),
              ),
              FilledButton(
                onPressed: marcadas.isEmpty
                    ? null
                    : () => Navigator.pop(
                          dialogContext,
                          _RosterImportChoice(
                            students: [
                              for (final entry in entries)
                                if (entry.row != null &&
                                    marcadas.contains(entry.key))
                                  entry.row!,
                            ],
                            deactivateIds: [
                              for (final entry in entries)
                                if (entry.action == RosterAction.ausente &&
                                    marcadas.contains(entry.key))
                                  entry.studentId!,
                            ],
                          ),
                        ),
                child: const Text('IMPORTAR'),
              ),
            ],
          );
        },
      ),
    );
  }

  /// Devolve a turma um aluno desativado por engano numa importacao.
  Future<void> _reactivateStudent(Student student) async {
    try {
      await education.updateStudent(student.id, active: true);
      _report('${student.name} voltou para a turma.');
      await _loadClasses(keepId: _selected?.id);
    } catch (e) {
      _report('Falha ao reativar: $e', error: true);
    }
  }

  Future<Map<String, dynamic>?> _chooseRosterSource() async {
    final controller = TextEditingController();
    final choice = await showDialog<Map<String, dynamic>>(context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, update) => AlertDialog(
          title: const Text('Importar alunos para a turma'),
          content: SizedBox(width: 560, child: Column(mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Escolha CSV, XML, XLSX, TXT, JSON ou um print; você também pode colar o texto da tela da Estácio.'),
              const SizedBox(height: 10),
              TextField(controller: controller, minLines: 4, maxLines: 9,
                decoration: const InputDecoration(
                  labelText: 'Texto copiado da tela', border: OutlineInputBorder()),
                onChanged: (_) => update(() {})),
              TextButton.icon(onPressed: () async {
                final copied = await Clipboard.getData('text/plain');
                if (copied?.text != null) {
                  controller.text = copied!.text!;
                  update(() {});
                }
              }, icon: const Icon(Icons.content_paste, size: 16),
                label: const Text('Colar da área de transferência')),
            ])),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancelar')),
            OutlinedButton.icon(onPressed: () async {
              final selected = await FilePicker.pickFiles(type: FileType.custom,
                allowedExtensions: const ['csv', 'xml', 'xlsx', 'txt', 'json',
                  'html', 'png', 'jpg', 'jpeg', 'webp', 'bmp'], withData: true);
              if (selected == null || selected.files.isEmpty) return;
              final file = selected.files.single;
              final bytes = file.bytes ??
                (file.path == null ? null : await File(file.path!).readAsBytes());
              if (bytes != null && dialogContext.mounted) {
                Navigator.pop(dialogContext, <String, dynamic>{
                  'bytes': bytes, 'filename': file.name});
              }
            }, icon: const Icon(Icons.upload_file_outlined, size: 16),
              label: const Text('Escolher arquivo ou print')),
            FilledButton(onPressed: controller.text.trim().isEmpty ? null :
              () => Navigator.pop(dialogContext,
                <String, dynamic>{'text': controller.text}),
              child: const Text('Analisar texto')),
          ],
        )));
    controller.dispose();
    return choice;
  }

  Future<StudentCsvRow?> _editSourceStudent(String enrollment, String name) async {
    final enrollmentController = TextEditingController(text: enrollment);
    final nameController = TextEditingController(text: name);
    final edited = await showDialog<StudentCsvRow>(context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Corrigir linha da fonte'),
        content: SizedBox(width: 420, child: Column(mainAxisSize: MainAxisSize.min,
          children: [
            TextField(controller: enrollmentController,
              decoration: const InputDecoration(labelText: 'Matrícula')),
            TextField(controller: nameController,
              decoration: const InputDecoration(labelText: 'Nome completo')),
          ])),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(dialogContext,
            StudentCsvRow(enrollment: enrollmentController.text.trim(),
              name: nameController.text.trim())), child: const Text('Usar correção')),
        ],
      ));
    enrollmentController.dispose(); nameController.dispose();
    return edited;
  }

  Future<_RosterSourceReview?> _reviewRosterSource(Map<String, dynamic> preview) async {
    final columns = (preview['columns'] as List).map((item) => '$item').toList();
    final raw = (preview['rows'] as List).map((item) =>
      (item as List).map((cell) => '$cell').toList()).toList();
    int? enrollmentIndex = (preview['enrollment_column'] as num).toInt() >= 0
      ? (preview['enrollment_column'] as num).toInt() : null;
    int? nameIndex = (preview['name_column'] as num).toInt() >= 0
      ? (preview['name_column'] as num).toInt() : null;
    final corrections = <int, StudentCsvRow>{};
    final rowConfidences = ((preview['row_confidences'] as List?) ?? const [])
        .map((value) => (value as num).toDouble()).toList();
    final analysisConfidence = ((preview['analysis_confidence'] as num?) ?? 0).toDouble();
    final analysisOrigin = '${preview['analysis_origin'] ?? 'parser'}';
    final classes = widget.classes.value ?? const <ClassGroup>[];
    final classIndex = (preview['class_column'] as num?)?.toInt() ?? -1;
    final classHints = ((preview['class_values'] as List?) ?? const [])
        .map((value) => '$value'.trim().toLowerCase()).toSet();
    final disciplineHints = ((preview['discipline_values'] as List?) ?? const [])
        .map((value) => '$value'.trim().toLowerCase()).toSet();
    bool matchesHint(ClassGroup group) {
      final code = group.code.trim().toLowerCase();
      final discipline = group.discipline.toLowerCase();
      final classOk = classHints.isEmpty || classHints.contains(code);
      final disciplineOk = disciplineHints.isEmpty || disciplineHints.any(
        (hint) => discipline.contains(hint) || group.label.toLowerCase().contains(hint));
      return classOk && disciplineOk;
    }
    ClassGroup? selectedGroup = classes.where(matchesHint).length == 1
        ? classes.where(matchesHint).first
        : (_selected != null && classes.any((item) => item.id == _selected!.id)
            ? _selected : null);
    String error = '';
    String cell(List<String> row, int? index) =>
      index == null || index >= row.length ? '' : row[index].trim();

    List<int> visibleRows() {
      if (selectedGroup == null || classIndex < 0 || classHints.isEmpty) {
        return List.generate(raw.length, (index) => index);
      }
      final target = selectedGroup!.code.trim().toLowerCase();
      return [for (var index = 0; index < raw.length; index++)
        if (cell(raw[index], classIndex).toLowerCase() == target) index];
    }

    return showDialog<_RosterSourceReview>(context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, update) => AlertDialog(
          title: Text('Conferir ${preview['source_type']} antes de importar'),
          content: SizedBox(width: 680, height: 520,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${raw.length} linhas detectadas. Confirme as colunas e corrija erros de OCR antes de continuar.'),
              Text('Análise: $analysisOrigin • ${(analysisConfidence * 100).round()}% de confiança',
                style: Theme.of(context).textTheme.bodySmall),
              ...((preview['warnings'] as List).map((warning) => Text('$warning',
                style: TextStyle(color: Theme.of(context).colorScheme.error)))),
              Row(children: [
                Expanded(child: DropdownButtonFormField<int>(value: enrollmentIndex,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Coluna de matrícula'),
                  items: [for (var index = 0; index < columns.length; index++)
                    DropdownMenuItem(value: index, child: Text(columns[index],
                      overflow: TextOverflow.ellipsis))],
                  onChanged: (value) => update(() {
                    enrollmentIndex = value; corrections.clear(); error = '';
                  }))),
                const SizedBox(width: 12),
                Expanded(child: DropdownButtonFormField<int>(value: nameIndex,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Coluna de nome'),
                  items: [for (var index = 0; index < columns.length; index++)
                    DropdownMenuItem(value: index, child: Text(columns[index],
                      overflow: TextOverflow.ellipsis))],
                  onChanged: (value) => update(() {
                    nameIndex = value; corrections.clear(); error = '';
                  }))),
              ]),
              const SizedBox(height: 10),
              DropdownButtonFormField<String>(value: selectedGroup?.id,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Disciplina e turma de destino'),
                items: [for (final group in classes)
                  DropdownMenuItem(value: group.id, child: Text(group.display,
                    overflow: TextOverflow.ellipsis))],
                onChanged: (value) => update(() {
                  selectedGroup = value == null
                      ? null : classes.firstWhere((item) => item.id == value);
                  error = '';
                })),
              if (selectedGroup != null && classHints.isNotEmpty && !matchesHint(selectedGroup!))
                Text('A turma escolhida difere da turma/disciplina identificada na fonte.',
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
              if ('${preview['source_text'] ?? ''}'.isNotEmpty)
                ExpansionTile(title: const Text('Texto reconhecido no print'),
                  children: [SelectableText('${preview['source_text']}')]),
              if (error.isNotEmpty) Text(error,
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
              const SizedBox(height: 8),
              Expanded(child: Builder(builder: (context) {
                final visible = visibleRows();
                return ListView.builder(itemCount: visible.length,
                itemBuilder: (context, index) {
                  final rawIndex = visible[index];
                  final row = raw[rawIndex];
                  final current = corrections[rawIndex] ?? StudentCsvRow(
                    enrollment: cell(row, enrollmentIndex),
                    name: cell(row, nameIndex));
                  return ListTile(dense: true,
                    title: Text(current.name.isEmpty ? 'Nome não identificado' : current.name),
                    subtitle: Text('Matrícula: ${current.enrollment.isEmpty ? 'não identificada' : current.enrollment}'
                      '${rawIndex < rowConfidences.length ? ' • ${(rowConfidences[rawIndex] * 100).round()}%' : ''}'),
                    trailing: IconButton(icon: const Icon(Icons.edit_outlined, size: 18),
                      tooltip: 'Corrigir matrícula e nome', onPressed: () async {
                        final edited = await _editSourceStudent(
                          current.enrollment, current.name);
                        if (edited != null) update(() => corrections[rawIndex] = edited);
                      }));
                });
              })),
            ])),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancelar')),
            FilledButton(onPressed: () {
              if (enrollmentIndex == null || nameIndex == null ||
                  enrollmentIndex == nameIndex) {
                update(() => error = 'Escolha colunas diferentes para matrícula e nome.');
                return;
              }
              if (selectedGroup == null) {
                update(() => error = 'Escolha a disciplina e a turma de destino.');
                return;
              }
              if (classHints.isNotEmpty && !matchesHint(selectedGroup!)) {
                update(() => error = 'Escolha a turma indicada pela fonte antes de continuar.');
                return;
              }
              final students = <StudentCsvRow>[];
              final enrollments = <String>{};
              for (final index in visibleRows()) {
                final row = corrections[index] ?? StudentCsvRow(
                  enrollment: cell(raw[index], enrollmentIndex),
                  name: cell(raw[index], nameIndex));
                if (row.enrollment.isEmpty && row.name.isEmpty) continue;
                if (row.enrollment.isEmpty || row.name.isEmpty) {
                  update(() => error = 'Linha ${index + 1}: corrija matrícula e nome.');
                  return;
                }
                if (!enrollments.add(row.enrollment.toLowerCase())) {
                  update(() => error = 'Matrícula ${row.enrollment} repetida na fonte.');
                  return;
                }
                students.add(row);
              }
              if (students.isEmpty) {
                update(() => error = 'Nenhum aluno válido foi identificado.');
                return;
              }
              Navigator.pop(dialogContext, _RosterSourceReview(selectedGroup!, students));
            }, child: const Text('Continuar para revisão da turma')),
          ],
        )));
  }

  Future<void> _importRosterSource() async {
    setState(() => _importing = true);
    try {
      final source = await _chooseRosterSource();
      if (source == null) return;
      final preview = await education.previewStudentRosterSource(
        bytes: source['bytes'] as List<int>?,
        filename: source['filename']?.toString() ?? '',
        pastedText: source['text']?.toString() ?? '');
      if (!mounted) return;
      final review = await _reviewRosterSource(preview);
      if (review == null || !mounted) return;
      final group = review.group;
      final rows = review.students;
      final roster = _selected?.id == group.id
          ? _students
          : await education.listStudents(classId: group.id, activeOnly: false);

      // A previa compara o arquivo com a turma antes de aplicar: sem isso o
      // professor so descobre o que a planilha fez depois de aplicada.
      final diff = diffRoster(roster: roster, file: rows);
      final escolha = await _confirmRosterImport(group, rows, diff);
      if (escolha == null) return;

      final result = await education.importStudents(
        classId: group.id,
        students: escolha.students,
        deactivateIds: escolha.deactivateIds,
      );
      final partes = [
        '${result.created} cadastrado(s)',
        '${result.updated} atualizado(s)',
        if (result.deactivated > 0) '${result.deactivated} desativado(s)',
      ];
      _report('Importacao concluida: ${partes.join(', ')}.');
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
    final ativos = _students.where((student) => student.active).length;
    final desativados = _students.length - ativos;
    final visiveis = _students.where(_studentFilter.matches).toList();
    final selectedStudents = visiveis
        .where((student) => _selectedStudentIds.contains(student.id))
        .toList();
    final allSelected =
        visiveis.isNotEmpty && selectedStudents.length == visiveis.length;

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
                  onPressed: _importing ? null : _importRosterSource,
                  icon: const Icon(Icons.upload_file_outlined, size: 14),
                  label: Text(
                    _importing ? 'IMPORTANDO...' : 'IMPORTAR ALUNOS',
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
                        text: 'Turma sem alunos.\nImporte um arquivo, print ou texto '
                            'com matrícula e nome.',
                      )
                    : Column(
                        children: [
                          _StudentFilterBar(
                            current: _studentFilter,
                            ativos: ativos,
                            desativados: desativados,
                            onChanged: (filtro) => setState(() {
                              _studentFilter = filtro;
                              // A selecao vale para o que esta na tela: manter
                              // marcado quem sumiu do filtro faria a exclusao
                              // em lote pegar quem nao aparece.
                              _selectedStudentIds.clear();
                            }),
                          ),
                          Row(
                            children: [
                              Checkbox(
                                value: allSelected,
                                onChanged: _deletingStudents
                                    ? null
                                    : (checked) => setState(() {
                                          if (checked == true) {
                                            _selectedStudentIds.addAll(
                                              visiveis.map(
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
                                        '${visiveis.length} selecionados',
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
                              itemCount: visiveis.length,
                              separatorBuilder: (_, __) => const Divider(
                                height: 12,
                                color: AssistantTheme.border,
                              ),
                              itemBuilder: (_, index) {
                                final student = visiveis[index];
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
                                          Row(
                                            children: [
                                              Flexible(
                                                child: Text(
                                                  student.name,
                                                  maxLines: 1,
                                                  overflow:
                                                      TextOverflow.ellipsis,
                                                  style: TextStyle(
                                                    fontSize: 13,
                                                    color: student.active
                                                        ? AssistantTheme
                                                            .textPrimary
                                                        : AssistantTheme
                                                            .textMuted,
                                                  ),
                                                ),
                                              ),
                                              if (!student.active) ...[
                                                const SizedBox(width: 8),
                                                const _StudentTag(
                                                  label: 'DESATIVADO',
                                                  color: AssistantTheme.c4,
                                                ),
                                              ],
                                            ],
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
                                    if (!student.active)
                                      IconButton(
                                        tooltip: 'Reativar aluno',
                                        icon: const Icon(
                                          Icons.restore_outlined,
                                          size: 15,
                                        ),
                                        color: AssistantTheme.c3,
                                        onPressed: _deletingStudents
                                            ? null
                                            : () => _reactivateStudent(student),
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

  /// Gravações marcadas para o resumo conjunto (um dia de apresentações, por exemplo).
  final _selected = <String>{};

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
      setState(() {
        _lessons = lessons;
        _selected.retainAll({for (final lesson in lessons) lesson.id});
      });
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

  /// Encerra ou reabre a aula na mao.
  ///
  /// O ENCERRAR da gravacao passa pelo resumo: quando o modelo falha, a aula
  /// fica gravando para sempre e some das telas que so olham aula encerrada.
  /// Aqui o professor corrige o status sem depender de modelo nenhum.
  Future<void> _toggleStatus(Lesson lesson) async {
    final novo = lesson.isClosed ? 'recording' : 'closed';
    try {
      await education.setLessonStatus(lesson.id, novo);
      if (!mounted) return;
      setState(() => _status = novo == 'closed'
          ? 'Aula encerrada.'
          : 'Aula reaberta: da para continuar gravando nela.');
      await _load(keepId: lesson.id);
    } catch (e) {
      if (mounted) setState(() => _status = 'Falha ao mudar o status: $e');
    }
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

  /// Integrantes do grupo da apresentação, para o cabeçalho do PDF. Sem eles (grupo
  /// apagado, sem rede) o PDF sai só com o nome do grupo.
  Future<List<String>> _presentationMembers(LessonDetail detail) async {
    if (detail.kind != 'apresentacao' || detail.groupId.isEmpty) return const [];
    try {
      final groups = await education.listProjectGroups();
      final group = groups.where((item) => '${item['id']}' == detail.groupId);
      if (group.isEmpty) return const [];
      final members = [
        for (final member in (group.first['members'] as List? ?? const []))
          Map<String, dynamic>.from(member as Map),
      ]..sort((a, b) => ((a['position'] as num?) ?? 0)
          .compareTo((b['position'] as num?) ?? 0));
      return [for (final member in members) '${member['name']}'];
    } catch (_) {
      return const [];
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
        members: await _presentationMembers(detail),
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
        dialogTitle: 'Salvar resumo',
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

  /// Marcar gravações e resumir juntas: o dia de apresentações de grupo, por exemplo.
  Widget _selectionBar() => LessonSelectionBar(
        count: _selected.length,
        total: _lessons.length,
        onToggleAll: () => setState(() {
          if (_selected.length == _lessons.length) {
            _selected.clear();
          } else {
            _selected.addAll(_lessons.map((lesson) => lesson.id));
          }
        }),
        onSummarise: () => showCombinedSummaryDialog(context, lessons: [
          for (final lesson in _lessons)
            if (_selected.contains(lesson.id)) lesson,
        ]),
      );

  Widget _buildList() {
    return _Panel(
      title: 'AULAS',
      child: _lessons.isEmpty
          ? const _EmptyState(
              icon: Icons.history,
              text: 'Nenhuma aula no periodo.',
            )
          : Column(children: [
              _selectionBar(),
              Expanded(child: ListView.separated(
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
                        SizedBox(
                          width: 28,
                          child: Checkbox(
                            key: ValueKey('selecionar-${lesson.id}'),
                            value: _selected.contains(lesson.id),
                            visualDensity: VisualDensity.compact,
                            onChanged: (on) => setState(() => on == true
                                ? _selected.add(lesson.id)
                                : _selected.remove(lesson.id)),
                          ),
                        ),
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
                                '${_when(lesson)}  -  ${lesson.displayLabel}'
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
                          tooltip: lesson.isClosed
                              ? 'Reabrir aula para continuar gravando'
                              : 'Encerrar aula sem gerar resumo',
                          icon: Icon(
                            lesson.isClosed
                                ? Icons.lock_open_outlined
                                : Icons.stop_circle_outlined,
                            size: 14,
                          ),
                          color: AssistantTheme.textMuted,
                          onPressed: () => _toggleStatus(lesson),
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
                            icon:
                                const Icon(Icons.cloud_sync_outlined, size: 14),
                            color: Colors.blue,
                            onPressed: () =>
                                _syncSiaPresence(lesson.id, lesson.title),
                          ),
                      ],
                    ),
                  ),
                );
              },
            )),
            ]),
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

  /// Corrige codigo, nome e semestre de uma disciplina ja cadastrada.
  ///
  /// O codigo e o que liga a disciplina a planilha de tempo de estudo e ao
  /// sistema academico: disciplina salva sem codigo - ou com o codigo colado
  /// dentro do nome - fica fora de toda importacao, em silencio. Sem esta tela
  /// a unica saida era apagar e recadastrar, perdendo turmas e historico.
  Future<void> _editDiscipline(Discipline discipline) async {
    final codeCtrl = TextEditingController(text: discipline.code);
    final nameCtrl = TextEditingController(text: discipline.name);
    final semesterCtrl = TextEditingController(text: discipline.semester);
    final salvou = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AssistantTheme.surface,
        title: const Text('Editar disciplina'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'O codigo precisa ser igual ao da instituicao (ex.: ARA0040), '
                'sozinho no campo. E por ele que a planilha de tempo de estudo '
                'encontra a disciplina.',
                style: TextStyle(
                    fontSize: 11, color: AssistantTheme.textSecondary),
              ),
              const SizedBox(height: 12),
              _Field(controller: codeCtrl, label: 'CODIGO', hint: 'ARA0040'),
              const SizedBox(height: 10),
              _Field(
                  controller: nameCtrl,
                  label: 'NOME',
                  hint: 'BANCO DE DADOS'),
              const SizedBox(height: 10),
              _Field(
                  controller: semesterCtrl,
                  label: 'SEMESTRE',
                  hint: '2026.2'),
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
    );
    final code = codeCtrl.text.trim();
    final name = nameCtrl.text.trim();
    final semester = semesterCtrl.text.trim();
    codeCtrl.dispose();
    nameCtrl.dispose();
    semesterCtrl.dispose();
    if (salvou != true || !mounted) return;
    if (code.isEmpty || name.isEmpty) {
      setState(() => _status = 'Codigo e nome sao obrigatorios.');
      return;
    }
    try {
      await education.updateDiscipline(
        discipline.id,
        code: code,
        name: name,
        semester: semester.isEmpty ? null : semester,
      );
      await _reload();
      if (mounted) {
        setState(() => _status = '');
      }
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
                                  // Sem codigo, a planilha de tempo de estudo
                                  // ignora a disciplina inteira sem avisar.
                                  if (discipline.code.trim().isEmpty)
                                    const Text(
                                      'SEM CODIGO  -  nao entra na importacao '
                                      'de tempo de estudo. Use o lapis.',
                                      style: TextStyle(
                                          fontSize: 10,
                                          color: AssistantTheme.c4),
                                    ),
                                ],
                              ),
                            ),
                            IconButton(
                              tooltip: 'Editar codigo, nome e semestre',
                              icon: const Icon(Icons.edit_outlined, size: 15),
                              color: AssistantTheme.c1,
                              onPressed: () => _editDiscipline(discipline),
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
      'Escolha o que vai gravar: aula, apresentacao de grupo, palestra ou reuniao.',
      'Aula pede a turma - e a disciplina nasce igual a dos alunos. '
          'Apresentacao pede o grupo e herda a disciplina dele. Palestra e '
          'reuniao pedem so o titulo, que e o que as identifica depois.',
    ),
    (
      Icons.mic_none,
      'De aula normalmente.',
      'A cada 60 segundos o audio vira um trecho transcrito aqui na tela.',
    ),
    (
      Icons.video_call_outlined,
      'Reuniao online? Troque a origem do audio ou importe a transcricao.',
      '"Reuniao online" grava o som do computador junto com o microfone, '
          'entao a voz de todos entra. Se o Teams ou o Meet ja transcreveu, '
          'IMPORTAR TRANSCRICAO traz o texto com o nome de quem falou.',
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

/// O que a tela devolve da previa: o que importar e quem desativar.
class _RosterSourceReview {
  final ClassGroup group;
  final List<StudentCsvRow> students;
  const _RosterSourceReview(this.group, this.students);
}

class _RosterImportChoice {
  final List<StudentCsvRow> students;
  final List<String> deactivateIds;

  const _RosterImportChoice({
    required this.students,
    required this.deactivateIds,
  });
}

/// Uma linha da previa, no formato da tabela de cadastro: marcador, acao,
/// matricula e nome.
class _RosterPreviewRow extends StatelessWidget {
  final RosterEntry entry;
  final bool checked;
  final ValueChanged<bool> onChanged;

  const _RosterPreviewRow({
    required this.entry,
    required this.checked,
    required this.onChanged,
  });

  static const _acoes = {
    RosterAction.novo: ('NOVO', AssistantTheme.c3),
    RosterAction.mantido: ('NA TURMA', AssistantTheme.textMuted),
    RosterAction.ausente: ('DESATIVAR', AssistantTheme.c4),
  };

  @override
  Widget build(BuildContext context) {
    final (rotulo, cor) = _acoes[entry.action]!;
    final apagado = !checked;

    return InkWell(
      onTap: () => onChanged(!checked),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            SizedBox(
              width: 34,
              child: Checkbox(
                value: checked,
                visualDensity: VisualDensity.compact,
                onChanged: (valor) => onChanged(valor == true),
              ),
            ),
            SizedBox(
              width: 78,
              child: Text(
                rotulo,
                style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9,
                  letterSpacing: 0.5,
                  color: apagado ? AssistantTheme.border : cor,
                ),
              ),
            ),
            SizedBox(
              width: 108,
              child: Text(
                entry.enrollment.isEmpty ? '—' : entry.enrollment,
                style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  color: apagado
                      ? AssistantTheme.border
                      : AssistantTheme.textMuted,
                ),
              ),
            ),
            Expanded(
              child: Text(
                entry.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12,
                  decoration: apagado ? TextDecoration.lineThrough : null,
                  color: apagado
                      ? AssistantTheme.textMuted
                      : AssistantTheme.textPrimary,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}


/// O recorte da lista de alunos.
enum _StudentFilter {
  ativos('ATIVOS'),
  todos('TODOS'),
  desativados('DESATIVADOS');

  const _StudentFilter(this.label);

  final String label;

  bool matches(Student student) => switch (this) {
        _StudentFilter.ativos => student.active,
        _StudentFilter.todos => true,
        _StudentFilter.desativados => !student.active,
      };
}

/// Alterna o recorte da lista, com a contagem de cada lado.
///
/// A contagem fica no botao de proposito: e ela que responde "sobrou alguem
/// desativado?" sem precisar trocar de aba.
class _StudentFilterBar extends StatelessWidget {
  final _StudentFilter current;
  final int ativos;
  final int desativados;
  final ValueChanged<_StudentFilter> onChanged;

  const _StudentFilterBar({
    required this.current,
    required this.ativos,
    required this.desativados,
    required this.onChanged,
  });

  int _count(_StudentFilter filter) => switch (filter) {
        _StudentFilter.ativos => ativos,
        _StudentFilter.todos => ativos + desativados,
        _StudentFilter.desativados => desativados,
      };

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          for (final filter in _StudentFilter.values) ...[
            _FilterChip(
              label: '${filter.label} ${_count(filter)}',
              selected: filter == current,
              // Sem desativados nao ha o que filtrar: o botao fica visivel para
              // a contagem, mas nao leva a uma lista vazia.
              onTap: filter == _StudentFilter.desativados && desativados == 0
                  ? null
                  : () => onChanged(filter),
            ),
            const SizedBox(width: 6),
          ],
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback? onTap;

  const _FilterChip({
    required this.label,
    required this.selected,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cor = onTap == null
        ? AssistantTheme.border
        : (selected ? AssistantTheme.c1 : AssistantTheme.textMuted);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(3),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          border: Border.all(color: cor.withOpacity(selected ? 0.9 : 0.35)),
          borderRadius: BorderRadius.circular(3),
          color: selected ? cor.withOpacity(0.12) : null,
        ),
        child: Text(
          label,
          style: TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 9,
            letterSpacing: 0.6,
            color: cor,
          ),
        ),
      ),
    );
  }
}

/// Etiqueta curta ao lado do nome do aluno.
class _StudentTag extends StatelessWidget {
  final String label;
  final Color color;

  const _StudentTag({required this.label, required this.color});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
        decoration: BoxDecoration(
          border: Border.all(color: color.withOpacity(0.5)),
          borderRadius: BorderRadius.circular(2),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 8,
            letterSpacing: 0.6,
            color: color,
          ),
        ),
      );
}

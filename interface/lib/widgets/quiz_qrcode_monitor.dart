/// Acompanha, em tempo real, os alunos que entraram no quiz pelo QR Code.
///
/// E a tela que o professor projeta na sala: por isso o texto precisa ser lido
/// de longe. A versao anterior pintava o cartao da pergunta de roxo claro e
/// deixava o texto na cor do tema escuro (cinza claro) - pergunta ilegivel - e
/// nao mostrava as alternativas. Aqui tudo usa as cores do tema escuro de ponta a
/// ponta, a pergunta aparece inteira com as alternativas, e a tela pode ser
/// maximizada: ocupa a janela toda, com letras maiores, a pergunta de um lado e
/// o QR Code e os controles do outro.
library;

import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:window_manager/window_manager.dart';
import 'dart:convert';
import '../services/api_service.dart';
import '../services/quiz_center_service.dart';
import '../utils/theme.dart';

/// Mescla nas estatisticas da tela o quiz devolvido por um comando ao vivo.
///
/// O endpoint de "proxima pergunta" ja responde com a fase atualizada. Esperar
/// o WebSocket para mudar o botao deixava o professor preso em "Iniciar Quiz"
/// -- e cada clique repetido avancava mais uma pergunta para a turma, que
/// pulava sem ter respondido. Devolve `null` quando a resposta nao traz fase,
/// caso em que a tela continua com o que tinha.
Map<String, dynamic>? mesclarQuizAoVivo(
  Map<String, dynamic>? stats,
  dynamic payload,
) {
  if (payload is! Map) return null;
  final quiz = Map<String, dynamic>.from(payload);
  final phase = quiz['live_phase']?.toString();
  if (phase == null || phase.isEmpty) return null;

  final questions = (quiz['questoes'] as List<dynamic>? ?? const [])
      .whereType<Map>()
      .toList();
  final currentId = quiz['current_question_id']?.toString();
  final index = currentId == null
      ? -1
      : questions.indexWhere((q) => q['id']?.toString() == currentId);

  final atual = Map<String, dynamic>.from(stats ?? <String, dynamic>{});
  atual['live_phase'] = phase;
  atual['current_question_id'] = currentId;
  atual['status'] = quiz['status'] ?? atual['status'];
  atual['time_limit_seconds'] =
      quiz['time_limit_seconds'] ?? atual['time_limit_seconds'] ?? 0;
  atual['seconds_remaining'] = quiz['seconds_remaining'];
  atual['current_question'] = index < 0
      ? null
      : {
          'question_id': currentId,
          'index': index,
          'question_text': questions[index]['enunciado']?.toString() ?? '',
          'options': _opcoesParaOProfessor(questions[index], phase),
          // A contagem real vem na proxima rodada do WebSocket; abrir a
          // pergunta ja com o total da anterior seria mentira na tela.
          'total_answers': 0,
        };
  atual['progress'] = atual['progress'] ?? <String, dynamic>{};
  return atual;
}

/// Alternativas da pergunta como o painel as mostra. O gabarito so sai depois
/// que a pergunta fecha: o painel costuma estar projetado para a turma.
List<Map<String, dynamic>> _opcoesParaOProfessor(
  Map<dynamic, dynamic> question,
  String phase,
) {
  final revelar = phase != 'question';
  return [
    for (final option in (question['opcoes'] as List<dynamic>? ?? const [])
        .whereType<Map>())
      {
        'label': option['label']?.toString() ?? '',
        'texto': option['texto']?.toString() ?? '',
        if (revelar) 'correta': option['correta'] == true,
      },
  ];
}

/// Prazos oferecidos ao professor, em segundos. `0` e o modo manual.
const List<int> tempoPorPerguntaOpcoes = [0, 15, 20, 30, 45, 60, 90, 120];

/// "Manual", "30s", "1 min", "1 min 30s".
String formatarTempoPorPergunta(int seconds) {
  if (seconds <= 0) return 'Manual';
  if (seconds < 60) return '${seconds}s';
  final minutos = seconds ~/ 60;
  final resto = seconds % 60;
  return resto == 0 ? '$minutos min' : '$minutos min ${resto}s';
}

/// Relogio da pergunta: "0:45".
String formatarRelogio(int seconds) {
  final total = math.max(0, seconds);
  return '${total ~/ 60}:${(total % 60).toString().padLeft(2, '0')}';
}

/// Widget que exibe QR Code do quiz + monitoramento em tempo real via WebSocket
class QuizQRCodeMonitor extends StatefulWidget {
  final String quizId;
  final String quizTitle;
  final int totalQuestions;
  final VoidCallback? onClose;

  /// So para teste: estatisticas ja prontas, para desenhar a tela sem servidor.
  @visibleForTesting
  final Map<String, dynamic>? initialStats;

  /// So para teste: `false` nao abre o WebSocket nem busca o QR Code.
  @visibleForTesting
  final bool autoConnect;

  const QuizQRCodeMonitor({
    super.key,
    required this.quizId,
    required this.quizTitle,
    required this.totalQuestions,
    this.onClose,
    this.initialStats,
    this.autoConnect = true,
  });

  @override
  State<QuizQRCodeMonitor> createState() => _QuizQRCodeMonitorState();
}

class _QuizQRCodeMonitorState extends State<QuizQRCodeMonitor> {
  /// Sem novidade do backend por mais que isso, a tela do professor esta
  /// velha: o servidor manda estatisticas a cada 2s. Reconecta em vez de
  /// continuar mostrando numeros parados como se fossem os de agora.
  static const Duration _silenceLimit = Duration(seconds: 12);

  /// Letras maiores quando a tela esta maximizada, para ler de longe.
  static const double _maximizedScale = 1.55;

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _freshnessTimer;
  Timer? _retryTimer;
  DateTime? _lastReconnect;

  String? _qrCodeUrl;
  Map<String, dynamic>? _stats;
  DateTime? _lastUpdate;

  /// Quando `seconds_remaining` chegou: o relogio na tela desconta daqui, entre
  /// um pacote e outro, sem depender de os relogios das maquinas concordarem.
  DateTime? _secondsAt;
  bool _isConnecting = true;
  bool _isClosingQuiz = false;
  bool _isChangingQuestion = false;
  bool _isSavingTime = false;
  bool _quizClosed = false;
  bool _maximized = false;
  bool _windowFullscreen = false;
  String? _error;
  int _connectRetries = 0;

  /// Ha quanto tempo o backend nao manda estatisticas novas.
  Duration get _sinceLastUpdate => _lastUpdate == null
      ? Duration.zero
      : DateTime.now().difference(_lastUpdate!);

  bool get _isStale => _lastUpdate == null || _sinceLastUpdate > _silenceLimit;

  double get _scale => _maximized ? _maximizedScale : 1.0;

  /// Segundos que faltam para a pergunta aberta, ou `null` sem prazo.
  int? get _secondsLeft {
    final base = _stats?['seconds_remaining'];
    final at = _secondsAt;
    if (base is! num || at == null) return null;
    return math.max(0, base.toInt() - DateTime.now().difference(at).inSeconds);
  }

  int get _timeLimit => (_stats?['time_limit_seconds'] as num?)?.toInt() ?? 0;

  @override
  void initState() {
    super.initState();
    final inicial = widget.initialStats;
    if (inicial != null) {
      _stats = inicial;
      _lastUpdate = DateTime.now();
      _secondsAt = DateTime.now();
      _isConnecting = false;
      _quizClosed = inicial['status'] == 'closed';
    }
    if (widget.autoConnect) {
      _loadQRCode();
      _connectWebSocket();
    }
    // Reconstroi o rodape de "atualizado ha Xs", o relogio da pergunta e vigia o
    // silencio do servidor.
    _freshnessTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() {});
      if (!widget.autoConnect) return;
      // Uma tentativa por janela de silencio: reconectar a cada segundo so
      // empilharia conexoes sem dar tempo do servidor responder.
      final ultima = _lastReconnect;
      final podeTentar =
          ultima == null || DateTime.now().difference(ultima) > _silenceLimit;
      if (_stats != null && _isStale && _retryTimer == null && podeTentar) {
        _reconnectNow();
      }
    });
  }

  Future<void> _loadQRCode() async {
    try {
      // Busca URL do QR Code
      final response = await api.get(
        '/education/quiz/${widget.quizId}/share-info',
      );

      if (response.success) {
        setState(() {
          _qrCodeUrl = response.data['qrcode_url'];
        });
      }
    } catch (e) {
      debugPrint('Erro ao carregar QR Code: $e');
    }
  }

  void _connectWebSocket() {
    _retryTimer?.cancel();
    _retryTimer = null;

    // Cancela a escuta anterior antes de abrir outra: sem isso, cada
    // reconexao deixava um listener vivo no canal velho e as mensagens
    // chegavam duplicadas.
    _subscription?.cancel();
    _subscription = null;
    try {
      _channel?.sink.close();
    } catch (_) {}
    _channel = null;

    try {
      // Conecta ao WebSocket para monitoramento em tempo real. A URL vem do
      // backend configurado, nao de localhost: o app pode apontar para outra
      // maquina ou para um deploy remoto.
      final channel = WebSocketChannel.connect(
        Uri.parse('${api.wsUrl}/ws/quiz/${widget.quizId}/monitor'),
      );
      _channel = channel;

      // Escuta mensagens
      _subscription = channel.stream.listen(
        (message) {
          final data = jsonDecode(message);
          // `stats_update` chega a cada 2s com o quiz inteiro: logar isso
          // soterrava o console. So o que foge da rotina vai para o log.
          if (data['type'] != 'stats_update') {
            debugPrint('Quiz monitor: ${data['type']}');
          }

          if (!mounted) return;

          setState(() {
            _isConnecting = false;
            _error = null;
            _connectRetries = 0;
          });

          if (data['type'] == 'initial_stats' ||
              data['type'] == 'stats_update') {
            setState(() {
              _stats = data['data'];
              _lastUpdate = DateTime.now();
              _secondsAt = DateTime.now();
              _quizClosed = data['data']?['status'] == 'closed';
            });
          }
        },
        onError: (error) {
          debugPrint('WebSocket error: $error');
          if (!mounted) return;

          setState(() {
            _error = 'Erro na conexão: $error';
            _isConnecting = false;
          });
          _retryConnection();
        },
        onDone: () {
          debugPrint('WebSocket closed');
          if (!mounted) return;
          _retryConnection();
        },
      );

      setState(() {
        _isConnecting = false;
      });
    } catch (e) {
      debugPrint('Erro ao conectar WebSocket: $e');
      if (!mounted) return;

      setState(() {
        _error = 'Erro ao conectar: $e';
        _isConnecting = false;
      });
      _retryConnection();
    }
  }

  /// Reconecta agora, sem esperar a espera progressiva.
  void _reconnectNow() {
    _connectRetries = 0;
    _lastReconnect = DateTime.now();
    _connectWebSocket();
  }

  void _retryConnection() {
    // A aula nao para porque o wifi oscilou: tenta sempre, so espacando as
    // tentativas ate 15s. O limite antigo de 3 tentativas desistia calado e
    // deixava o professor olhando numeros congelados.
    if (_retryTimer != null) return;
    _connectRetries++;
    final espera = Duration(
      seconds: (_connectRetries * 2).clamp(2, 15),
    );
    _retryTimer = Timer(espera, () {
      _retryTimer = null;
      if (mounted) _connectWebSocket();
    });
  }

  @override
  void dispose() {
    _freshnessTimer?.cancel();
    _retryTimer?.cancel();
    _subscription?.cancel();
    try {
      _channel?.sink.close();
    } catch (_) {}
    // Fechar o painel nao pode deixar o app preso em tela cheia.
    if (_windowFullscreen) {
      try {
        windowManager.setFullScreen(false);
      } catch (_) {}
    }
    super.dispose();
  }

  /// Maximiza o painel: ocupa a janela toda e, em desktop, passa a janela para
  /// tela cheia - e o que deixa o quiz ocupar o projetor sem barras.
  Future<void> _toggleMaximized() async {
    final next = !_maximized;
    setState(() => _maximized = next);
    try {
      await windowManager.setFullScreen(next);
      _windowFullscreen = next;
    } catch (_) {
      // Sem gerenciador de janela (teste, outra plataforma): o painel maximizado
      // dentro da janela ja resolve a leitura.
    }
  }

  // --- layout ---------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    final header = _buildHeader();

    return Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: _maximized
          ? EdgeInsets.zero
          : const EdgeInsets.symmetric(horizontal: 40, vertical: 24),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_maximized ? 0 : 12),
      ),
      clipBehavior: Clip.antiAlias,
      child: ConstrainedBox(
        constraints: _maximized
            ? BoxConstraints.tight(size)
            : const BoxConstraints(maxWidth: 680, maxHeight: 820),
        child: Column(
          mainAxisSize: _maximized ? MainAxisSize.max : MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            header,
            Flexible(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final wide = constraints.maxWidth >= 980;
                  return wide ? _buildWideBody() : _buildNarrowBody();
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    final left = _secondsLeft;
    final livePhase = _stats?['live_phase']?.toString() ?? 'lobby';
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: 20,
        vertical: _maximized ? 16 : 14,
      ),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [Colors.purple[500]!, Colors.purple[800]!],
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.qr_code_2, color: Colors.white, size: 24 * _scale),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Quiz ao Vivo',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18 * _scale,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Text(
                  widget.quizTitle,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.85),
                    fontSize: 12 * _scale,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          if (livePhase == 'question' && left != null) ...[
            _CountdownPill(seconds: left, scale: _scale),
            const SizedBox(width: 12),
          ],
          IconButton(
            tooltip: _maximized ? 'Sair da tela cheia' : 'Maximizar a tela',
            onPressed: _toggleMaximized,
            icon: Icon(
              _maximized ? Icons.fullscreen_exit : Icons.fullscreen,
              color: Colors.white,
              size: 24 * math.min(_scale, 1.3),
            ),
          ),
          IconButton(
            tooltip: 'Fechar',
            onPressed: () {
              widget.onClose?.call();
              Navigator.pop(context);
            },
            icon: Icon(
              Icons.close,
              color: Colors.white,
              size: 24 * math.min(_scale, 1.3),
            ),
          ),
        ],
      ),
    );
  }

  /// Tela estreita: uma coluna so. No lobby o QR Code vem primeiro, porque e
  /// ele que a turma precisa escanear; depois, a pergunta e o ranking vem na
  /// frente - antes o QR de 200px empurrava a pergunta para fora da tela.
  Widget _buildNarrowBody() {
    final lobby = (_stats?['live_phase']?.toString() ?? 'lobby') == 'lobby';
    return SingleChildScrollView(
      padding: EdgeInsets.all(_maximized ? 28 : 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (lobby) ...[
            _buildQRCodeSection(),
            const SizedBox(height: 24),
          ],
          _buildLiveSection(),
          if (!lobby) ...[
            const SizedBox(height: 24),
            _buildQRCodeSection(compact: true),
          ],
        ],
      ),
    );
  }

  /// Tela larga (maximizada): a pergunta e o ranking ocupam a maior parte, e o
  /// QR Code com os controles fica numa coluna ao lado.
  Widget _buildWideBody() {
    return Padding(
      padding: const EdgeInsets.all(28),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 3,
            child: SingleChildScrollView(child: _buildLiveSection()),
          ),
          const SizedBox(width: 28),
          SizedBox(
            width: 420,
            child: SingleChildScrollView(
              child: _buildQRCodeSection(compact: false),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildQRCodeSection({bool compact = false}) {
    final qrSize = compact ? 140.0 : (_maximized ? 280.0 : 200.0);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          '📱 Escanear para responder',
          style: TextStyle(
            fontSize: 14 * math.min(_scale, 1.3),
            fontWeight: FontWeight.bold,
            color: AssistantTheme.textPrimary,
          ),
        ),
        const SizedBox(height: 12),
        // Fundo branco: o QR Code precisa de contraste para a camera ler, e o
        // tema escuro o deixaria ilegivel.
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(8),
          ),
          child: _qrCodeUrl != null
              ? Image.network(
                  _qrCodeUrl!,
                  headers: {
                    if (api.token != null)
                      'Authorization': 'Bearer ${api.token}',
                  },
                  width: qrSize,
                  height: qrSize,
                  fit: BoxFit.contain,
                )
              : SizedBox(
                  width: qrSize,
                  height: qrSize,
                  child: const Center(
                    child: CircularProgressIndicator(),
                  ),
                ),
        ),
        const SizedBox(height: 12),
        if (_quizClosed) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.orange.withValues(alpha: 0.14),
              border: Border.all(color: Colors.orange.shade300),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Icon(Icons.lock_clock, color: Colors.orange.shade200),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Quiz encerrado. Novas respostas foram bloqueadas.',
                    style: TextStyle(color: Colors.orange.shade100),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
        ],
        Wrap(
          spacing: 8,
          runSpacing: 8,
          alignment: WrapAlignment.center,
          children: [
            ElevatedButton.icon(
              onPressed: () => _copyQuizLink(),
              icon: const Icon(Icons.content_copy),
              label: const Text('Copiar Link do Quiz'),
            ),
            ElevatedButton.icon(
              onPressed:
                  _quizClosed || _isClosingQuiz ? null : _confirmCloseQuiz,
              icon: _isClosingQuiz
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.stop_circle_outlined),
              label: Text(_quizClosed ? 'Quiz Encerrado' : 'Encerrar Quiz'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red[700],
                foregroundColor: Colors.white,
              ),
            ),
          ],
        ),
      ],
    );
  }

  /// Pergunta, alternativas, controles e ranking: o que muda a cada rodada.
  Widget _buildLiveSection() {
    if (_stats != null) return _buildStatsSection();
    if (_isConnecting) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(20),
          child: CircularProgressIndicator(),
        ),
      );
    }
    if (_error != null) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.red.withValues(alpha: 0.14),
          border: Border.all(color: Colors.red.shade300),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          _error!,
          style: TextStyle(color: Colors.red.shade100),
        ),
      );
    }
    return const SizedBox.shrink();
  }

  Widget _buildStatsSection() {
    final progress = _stats!['progress'] as Map<String, dynamic>? ?? const {};
    final currentQuestion =
        _stats!['current_question'] as Map<String, dynamic>?;
    final livePhase = _stats!['live_phase']?.toString() ?? 'lobby';
    final ranking = _stats!['ranking_top10'] as List<dynamic>? ?? const [];
    final totalAnswers = progress['total_answers'] as int? ?? 0;
    final correct = progress['correct'] as int? ?? 0;
    final incorrect = progress['incorrect'] as int? ?? 0;
    final participants = _stats!['participants'] as int? ?? 0;
    final online = _stats!['participants_online'] as int? ?? participants;
    final totalQuestions =
        _stats!['total_questions'] as int? ?? widget.totalQuestions;
    final names = (_stats!['participant_names'] as List<dynamic>? ?? const [])
        .map((name) => name.toString())
        .where((name) => name.isNotEmpty)
        .toList();
    final showRanking =
        livePhase == 'results' || livePhase == 'finished' || _quizClosed;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          _phaseTitle(livePhase),
          style: TextStyle(
            fontSize: 18 * _scale,
            fontWeight: FontWeight.bold,
            color: AssistantTheme.textPrimary,
          ),
        ),
        const SizedBox(height: 12),
        if (currentQuestion != null) ...[
          _buildQuestionCard(currentQuestion, livePhase, totalQuestions),
          const SizedBox(height: 12),
        ],
        _buildParticipantsLine(
          participants: participants,
          online: online,
          totalAnswers: totalAnswers,
          correct: correct,
          incorrect: incorrect,
        ),
        // No lobby o professor precisa ver quem ja entrou antes de iniciar: e a
        // unica confirmacao de que o QR Code funcionou na sala.
        if (livePhase == 'lobby') ...[
          const SizedBox(height: 10),
          if (names.isEmpty)
            Text(
              'Ninguém entrou ainda. Peça para a turma escanear o QR Code.',
              style: TextStyle(
                fontSize: 13 * _scale,
                color: AssistantTheme.textSecondary,
              ),
            )
          else
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final name in names)
                  Chip(
                    label: Text(
                      name,
                      style: TextStyle(
                        fontSize: 12 * _scale,
                        color: AssistantTheme.textPrimary,
                      ),
                    ),
                    backgroundColor: AssistantTheme.surface2,
                    side: const BorderSide(color: AssistantTheme.border2),
                    visualDensity: VisualDensity.compact,
                  ),
              ],
            ),
        ],
        const SizedBox(height: 16),
        _buildLiveAction(livePhase, currentQuestion, totalQuestions),
        if (!_quizClosed && livePhase != 'finished') ...[
          const SizedBox(height: 14),
          _buildTimeSelector(livePhase),
        ],
        const SizedBox(height: 20),
        if (showRanking) ...[
          Text(
            livePhase == 'results'
                ? 'Ranking · pontos acumulados'
                : 'Ranking Final',
            style: TextStyle(
              fontSize: 17 * _scale,
              fontWeight: FontWeight.bold,
              color: AssistantTheme.textPrimary,
            ),
          ),
          const SizedBox(height: 10),
          _buildRanking(ranking, showRound: livePhase == 'results'),
          if (livePhase == 'results') ...[
            const SizedBox(height: 10),
            Text(
              'Confira o ranking com a turma e chame a próxima pergunta quando '
              'quiser.',
              style: TextStyle(
                fontSize: 13 * _scale,
                color: AssistantTheme.textSecondary,
              ),
            ),
          ],
        ] else if (livePhase == 'question') ...[
          Text(
            _secondsLeft != null
                ? 'O ranking aparece quando o tempo acabar ou quando você '
                    'encerrar a pergunta.'
                : 'Ranking será exibido ao encerrar a pergunta.',
            style: TextStyle(
              fontSize: 13 * _scale,
              color: AssistantTheme.textSecondary,
            ),
          ),
        ] else ...[
          Text(
            'Aguardando iniciar a primeira pergunta.',
            style: TextStyle(
              fontSize: 13 * _scale,
              color: AssistantTheme.textSecondary,
            ),
          ),
        ],
        const SizedBox(height: 12),
        _buildFreshness(),
      ],
    );
  }

  /// A pergunta atual inteira, com as alternativas, no tema escuro: texto claro
  /// sobre fundo escuro, de ponta a ponta.
  Widget _buildQuestionCard(
    Map<String, dynamic> question,
    String phase,
    int totalQuestions,
  ) {
    final options = (question['options'] as List<dynamic>? ?? const [])
        .whereType<Map>()
        .toList();
    final index = (question['index'] as int? ?? 0) + 1;
    final answers = question['total_answers'] ?? 0;
    final reveal = phase != 'question';

    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(16 * math.min(_scale, 1.25)),
      decoration: BoxDecoration(
        color: AssistantTheme.surface2,
        border: Border.all(color: AssistantTheme.border2),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            totalQuestions > 0
                ? 'Pergunta $index de $totalQuestions'
                : 'Pergunta $index',
            style: TextStyle(
              fontSize: 13 * _scale,
              color: Colors.purple.shade200,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            question['question_text']?.toString() ?? '',
            style: TextStyle(
              fontSize: 17 * _scale,
              height: 1.35,
              fontWeight: FontWeight.w700,
              color: AssistantTheme.textPrimary,
            ),
          ),
          if (options.isNotEmpty) ...[
            const SizedBox(height: 14),
            for (final option in options)
              _buildOption(option, reveal: reveal),
          ],
          const SizedBox(height: 10),
          Text(
            'Respostas nesta pergunta: $answers',
            style: TextStyle(
              fontSize: 13 * _scale,
              color: AssistantTheme.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildOption(Map<dynamic, dynamic> option, {required bool reveal}) {
    final correct = reveal && option['correta'] == true;
    final dimmed = reveal && !correct;
    final accent = correct ? Colors.greenAccent.shade400 : AssistantTheme.border2;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: EdgeInsets.symmetric(
        horizontal: 12 * math.min(_scale, 1.25),
        vertical: 10 * math.min(_scale, 1.25),
      ),
      decoration: BoxDecoration(
        color: correct
            ? Colors.green.withValues(alpha: 0.18)
            : AssistantTheme.surface,
        border: Border.all(color: accent, width: correct ? 2 : 1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28 * _scale,
            height: 28 * _scale,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: correct ? Colors.green.shade600 : AssistantTheme.surface2,
              border: Border.all(color: accent),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              option['label']?.toString() ?? '',
              style: TextStyle(
                fontSize: 14 * _scale,
                fontWeight: FontWeight.bold,
                color: AssistantTheme.textPrimary,
              ),
            ),
          ),
          SizedBox(width: 12 * math.min(_scale, 1.25)),
          Expanded(
            child: Text(
              option['texto']?.toString() ?? '',
              style: TextStyle(
                fontSize: 16 * _scale,
                height: 1.3,
                color: dimmed
                    ? AssistantTheme.textSecondary
                    : AssistantTheme.textPrimary,
                fontWeight: correct ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
          ),
          if (correct)
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: Icon(
                Icons.check_circle,
                color: Colors.greenAccent.shade400,
                size: 22 * _scale,
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildParticipantsLine({
    required int participants,
    required int online,
    required int totalAnswers,
    required int correct,
    required int incorrect,
  }) {
    final style = TextStyle(
      fontSize: 13 * _scale,
      color: AssistantTheme.textSecondary,
    );
    return Wrap(
      spacing: 18,
      runSpacing: 4,
      children: [
        Text(
          online == participants
              ? 'Participantes: $participants'
              : 'Participantes: $participants ($online com a tela aberta)',
          style: style,
        ),
        Text('Total: $totalAnswers | $correct acertos | $incorrect erros',
            style: style),
      ],
    );
  }

  /// Mostra se o que esta na tela e de agora.
  ///
  /// Quando o backend parava de mandar novidade, a tela continuava exibindo os
  /// mesmos numeros sem avisar nada -- o professor nao tinha como saber que o
  /// lobby vazio era so uma leitura velha.
  Widget _buildFreshness() {
    final estilo = TextStyle(
      fontSize: 12 * math.min(_scale, 1.3),
      color: AssistantTheme.textSecondary,
    );
    if (_isStale) {
      return Row(
        children: [
          Icon(Icons.sync_problem, size: 16, color: Colors.orange[300]),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              'Sem atualização do servidor há ${_sinceLastUpdate.inSeconds}s. '
              'Reconectando...',
              style: estilo.copyWith(color: Colors.orange[200]),
            ),
          ),
          TextButton(
            onPressed: _reconnectNow,
            child: const Text('Reconectar'),
          ),
        ],
      );
    }

    final segundos = _sinceLastUpdate.inSeconds;
    return Row(
      children: [
        Icon(Icons.wifi_tethering, size: 16, color: Colors.green[300]),
        const SizedBox(width: 6),
        Text(
          segundos <= 1
              ? 'Ao vivo · atualizado agora'
              : 'Ao vivo · atualizado há ${segundos}s',
          style: estilo,
        ),
      ],
    );
  }

  String _phaseTitle(String phase) {
    if (_quizClosed || phase == 'finished') return 'Ranking Final';
    if (phase == 'question') return 'Pergunta Atual';
    if (phase == 'results') return 'Resultado da Pergunta';
    return 'Lobby do Quiz';
  }

  Widget _buildLiveAction(
    String phase,
    Map<String, dynamic>? currentQuestion,
    int totalQuestions,
  ) {
    if (_quizClosed || phase == 'finished') {
      return const SizedBox.shrink();
    }
    final padding = EdgeInsets.symmetric(vertical: 14 * math.min(_scale, 1.3));
    if (phase == 'question') {
      return SizedBox(
        width: double.infinity,
        child: ElevatedButton.icon(
          onPressed: _isChangingQuestion ? null : _closeCurrentQuestion,
          icon: _isChangingQuestion
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.stop_circle_outlined),
          label: Text(
            _secondsLeft != null ? 'Encerrar Agora' : 'Encerrar Pergunta',
            style: TextStyle(fontSize: 15 * math.min(_scale, 1.3)),
          ),
          style: ElevatedButton.styleFrom(
            backgroundColor: Colors.orange[700],
            foregroundColor: Colors.white,
            padding: padding,
          ),
        ),
      );
    }

    final lastQuestion = phase == 'results' &&
        totalQuestions > 0 &&
        ((currentQuestion?['index'] as int? ?? 0) + 1) >= totalQuestions;
    final label = phase == 'results'
        ? (lastQuestion ? 'Ver Ranking Final' : 'Próxima Pergunta')
        : 'Iniciar Quiz';
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton.icon(
        onPressed: _isChangingQuestion ? null : _openNextQuestion,
        icon: _isChangingQuestion
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.navigate_next),
        label: Text(
          label,
          style: TextStyle(fontSize: 15 * math.min(_scale, 1.3)),
        ),
        style: ElevatedButton.styleFrom(padding: padding),
      ),
    );
  }

  /// Tempo por pergunta: acabado o tempo, a pergunta fecha sozinha, o ranking
  /// aparece e o professor chama a proxima. Vale a partir da proxima pergunta.
  Widget _buildTimeSelector(String phase) {
    final atual = _timeLimit;
    final personalizado = !tempoPorPerguntaOpcoes.contains(atual);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AssistantTheme.surface2,
        border: Border.all(color: AssistantTheme.border2),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.timer_outlined,
                  size: 16 * math.min(_scale, 1.3),
                  color: AssistantTheme.textSecondary),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  'Tempo por pergunta',
                  style: TextStyle(
                    fontSize: 13 * math.min(_scale, 1.3),
                    fontWeight: FontWeight.bold,
                    color: AssistantTheme.textPrimary,
                  ),
                ),
              ),
              if (_isSavingTime)
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final seconds in tempoPorPerguntaOpcoes)
                ChoiceChip(
                  label: Text(formatarTempoPorPergunta(seconds)),
                  selected: atual == seconds,
                  onSelected: _isSavingTime || _quizClosed
                      ? null
                      : (_) => _setTimeLimit(seconds),
                ),
              ChoiceChip(
                label: Text(personalizado
                    ? formatarTempoPorPergunta(atual)
                    : 'Outro...'),
                selected: personalizado,
                onSelected: _isSavingTime || _quizClosed
                    ? null
                    : (_) => _askCustomTimeLimit(),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            atual == 0
                ? 'Manual: a pergunta fica aberta até você encerrar.'
                : 'Ao acabar o tempo, a pergunta fecha sozinha e o ranking '
                    'aparece. ${phase == 'question' ? 'Vale a partir da próxima pergunta.' : ''}',
            style: TextStyle(
              fontSize: 12 * math.min(_scale, 1.3),
              color: AssistantTheme.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRanking(List<dynamic> ranking, {required bool showRound}) {
    if (ranking.isEmpty) {
      return Text(
        'Aguardando respostas...',
        style: TextStyle(
          fontSize: 14 * _scale,
          color: AssistantTheme.textSecondary,
        ),
      );
    }
    const medals = [Color(0xFFFFD54F), Color(0xFFCFD8DC), Color(0xFFD7A074)];
    return Column(
      children: ranking.map<Widget>((item) {
        final row = item as Map<String, dynamic>;
        final position = row['position'] as int? ?? 0;
        final medal = position >= 1 && position <= 3 ? medals[position - 1] : null;
        final roundScore = (row['round_score'] as num?)?.toInt() ?? 0;
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: EdgeInsets.symmetric(
            horizontal: 12 * math.min(_scale, 1.25),
            vertical: 10 * math.min(_scale, 1.25),
          ),
          decoration: BoxDecoration(
            color: AssistantTheme.surface2,
            border: Border.all(
              color: medal ?? AssistantTheme.border2,
              width: medal != null ? 1.5 : 1,
            ),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              SizedBox(
                width: 52 * _scale,
                child: Text(
                  '#${row['position'] ?? '-'}',
                  style: TextStyle(
                    fontSize: 18 * _scale,
                    fontWeight: FontWeight.bold,
                    color: medal ?? AssistantTheme.textPrimary,
                  ),
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      row['student_name']?.toString() ?? 'Aluno',
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 16 * _scale,
                        color: AssistantTheme.textPrimary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (showRound)
                      Text(
                        row['round_correct'] == true
                            ? '+$roundScore nesta pergunta'
                            : row['round_correct'] == false
                                ? 'errou esta pergunta'
                                : 'não respondeu',
                        style: TextStyle(
                          fontSize: 12 * _scale,
                          fontWeight: FontWeight.w600,
                          color: row['round_correct'] == true
                              ? Colors.greenAccent.shade400
                              : AssistantTheme.textSecondary,
                        ),
                      ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    '${row['score'] ?? 0} pts',
                    style: TextStyle(
                      fontSize: 17 * _scale,
                      fontWeight: FontWeight.bold,
                      color: AssistantTheme.textPrimary,
                    ),
                  ),
                  if (showRound)
                    Text(
                      'acumulado',
                      style: TextStyle(
                        fontSize: 11 * _scale,
                        color: AssistantTheme.textSecondary,
                      ),
                    ),
                ],
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  // --- comandos ---------------------------------------------------------------

  Future<void> _openNextQuestion() async {
    await _runLiveCommand(
      '/education/quiz/${widget.quizId}/next-question',
      'Pergunta liberada.',
    );
  }

  Future<void> _closeCurrentQuestion() async {
    await _runLiveCommand(
      '/education/quiz/${widget.quizId}/close-question',
      'Pergunta encerrada.',
    );
  }

  /// Aplica na tela o quiz que o proprio comando devolveu.
  void _applyQuizResponse(dynamic payload) {
    final mesclado = mesclarQuizAoVivo(_stats, payload);
    if (mesclado == null) return;
    setState(() {
      _stats = mesclado;
      _secondsAt = DateTime.now();
      _quizClosed = mesclado['status'] == 'closed';
    });
  }

  Future<void> _setTimeLimit(int seconds) async {
    final anterior = _timeLimit;
    setState(() {
      _isSavingTime = true;
      // Otimista: o chip muda na hora; volta se o servidor recusar.
      _stats = {...?_stats, 'time_limit_seconds': seconds};
    });
    try {
      final quiz = await quizCenter.setTimeLimit(widget.quizId, seconds);
      if (!mounted) return;
      // O servidor pode ter ajustado o valor (minimo de 5s): vale o que ele gravou.
      setState(() {
        _stats = {
          ...?_stats,
          'time_limit_seconds': quiz['time_limit_seconds'] ?? seconds,
        };
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            seconds == 0
                ? 'Tempo manual: você encerra cada pergunta.'
                : 'Cada pergunta terá ${formatarTempoPorPergunta(_timeLimit)}.',
          ),
          duration: const Duration(seconds: 2),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _stats = {...?_stats, 'time_limit_seconds': anterior};
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Não consegui mudar o tempo: $e'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _isSavingTime = false);
    }
  }

  Future<void> _askCustomTimeLimit() async {
    final controller = TextEditingController(
      text: _timeLimit > 0 ? '$_timeLimit' : '',
    );
    final seconds = await showDialog<int>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Tempo por pergunta'),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: const InputDecoration(
            labelText: 'Segundos (5 a 600)',
          ),
          onSubmitted: (value) {
            final parsed = int.tryParse(value);
            if (parsed != null && parsed >= 5 && parsed <= 600) {
              Navigator.pop(dialogContext, parsed);
            }
          },
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () {
              final parsed = int.tryParse(controller.text);
              if (parsed != null && parsed >= 5 && parsed <= 600) {
                Navigator.pop(dialogContext, parsed);
              }
            },
            child: const Text('Definir'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (seconds != null) await _setTimeLimit(seconds);
  }

  Future<void> _runLiveCommand(String endpoint, String successMessage) async {
    setState(() {
      _isChangingQuestion = true;
    });

    try {
      final response = await api.post(endpoint, body: {});
      if (!response.success) {
        throw Exception(response.error ?? 'Falha ao atualizar quiz');
      }
      if (!mounted) return;
      _applyQuizResponse(response.data);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(successMessage)),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Erro no quiz: $e'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isChangingQuestion = false;
        });
      }
    }
  }

  Future<void> _copyQuizLink() async {
    final link = '${api.baseUrl}/education/quiz/${widget.quizId}/play';
    await Clipboard.setData(ClipboardData(text: link));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Link copiado: $link'),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  Future<void> _confirmCloseQuiz() async {
    final shouldClose = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Encerrar quiz?'),
        content: const Text(
          'Depois de encerrado, o link e o QR Code não aceitarão novas '
          'respostas. As respostas já recebidas permanecem no relatório.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Encerrar'),
          ),
        ],
      ),
    );

    if (shouldClose == true) {
      await _closeQuiz();
    }
  }

  Future<void> _closeQuiz() async {
    setState(() {
      _isClosingQuiz = true;
    });

    try {
      final response = await api.post(
        '/education/quiz/${widget.quizId}/close',
        body: {},
      );

      if (!response.success) {
        throw Exception(response.error ?? 'Falha ao encerrar quiz');
      }

      if (!mounted) return;
      setState(() {
        _quizClosed = true;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Quiz encerrado.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Erro ao encerrar quiz: $e'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isClosingQuiz = false;
        });
      }
    }
  }
}

/// Relogio da pergunta no cabecalho: fica vermelho nos ultimos 5 segundos.
class _CountdownPill extends StatelessWidget {
  final int seconds;
  final double scale;

  const _CountdownPill({required this.seconds, required this.scale});

  @override
  Widget build(BuildContext context) {
    final urgent = seconds <= 5;
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: 14 * math.min(scale, 1.3),
        vertical: 6 * math.min(scale, 1.3),
      ),
      decoration: BoxDecoration(
        color: urgent ? Colors.red.shade700 : Colors.white.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.white.withValues(alpha: 0.6)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.timer_outlined, color: Colors.white, size: 18 * scale),
          const SizedBox(width: 6),
          Text(
            formatarRelogio(seconds),
            style: TextStyle(
              color: Colors.white,
              fontSize: 18 * scale,
              fontWeight: FontWeight.bold,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }
}

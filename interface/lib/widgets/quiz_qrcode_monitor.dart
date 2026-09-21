/// Acompanha, em tempo real, os alunos que entraram no quiz pelo QR Code.
library;

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import '../services/api_service.dart';

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
  atual['current_question'] = index < 0
      ? null
      : {
          'question_id': currentId,
          'index': index,
          'question_text': questions[index]['enunciado']?.toString() ?? '',
          // A contagem real vem na proxima rodada do WebSocket; abrir a
          // pergunta ja com o total da anterior seria mentira na tela.
          'total_answers': 0,
        };
  atual['progress'] = atual['progress'] ?? <String, dynamic>{};
  return atual;
}

/// Widget que exibe QR Code do quiz + monitoramento em tempo real via WebSocket
class QuizQRCodeMonitor extends StatefulWidget {
  final String quizId;
  final String quizTitle;
  final int totalQuestions;
  final VoidCallback? onClose;

  const QuizQRCodeMonitor({
    super.key,
    required this.quizId,
    required this.quizTitle,
    required this.totalQuestions,
    this.onClose,
  });

  @override
  State<QuizQRCodeMonitor> createState() => _QuizQRCodeMonitorState();
}

class _QuizQRCodeMonitorState extends State<QuizQRCodeMonitor> {
  /// Sem novidade do backend por mais que isso, a tela do professor esta
  /// velha: o servidor manda estatisticas a cada 2s. Reconecta em vez de
  /// continuar mostrando numeros parados como se fossem os de agora.
  static const Duration _silenceLimit = Duration(seconds: 12);

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _freshnessTimer;
  Timer? _retryTimer;
  DateTime? _lastReconnect;

  String? _qrCodeUrl;
  Map<String, dynamic>? _stats;
  DateTime? _lastUpdate;
  bool _isConnecting = true;
  bool _isClosingQuiz = false;
  bool _isChangingQuestion = false;
  bool _quizClosed = false;
  String? _error;
  int _connectRetries = 0;

  /// Ha quanto tempo o backend nao manda estatisticas novas.
  Duration get _sinceLastUpdate => _lastUpdate == null
      ? Duration.zero
      : DateTime.now().difference(_lastUpdate!);

  bool get _isStale => _lastUpdate == null || _sinceLastUpdate > _silenceLimit;

  @override
  void initState() {
    super.initState();
    _loadQRCode();
    _connectWebSocket();
    // Reconstroi o rodape de "atualizado ha Xs" e vigia o silencio do servidor.
    _freshnessTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() {});
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
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: Container(
        constraints: const BoxConstraints(maxWidth: 600, maxHeight: 800),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [Colors.purple[400]!, Colors.purple[600]!],
                  ),
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(8),
                    topRight: Radius.circular(8),
                  ),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.qr_code_2, color: Colors.white),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Quiz ao Vivo',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          Text(
                            widget.quizTitle,
                            style: const TextStyle(
                              color: Colors.white70,
                              fontSize: 12,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      onPressed: () {
                        widget.onClose?.call();
                        Navigator.pop(context);
                      },
                      icon: const Icon(Icons.close, color: Colors.white),
                    ),
                  ],
                ),
              ),

              Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // QR Code Section
                    _buildQRCodeSection(),

                    const SizedBox(height: 24),

                    // Live Quiz Section
                    if (_stats != null)
                      _buildStatsSection()
                    else if (_isConnecting)
                      const Center(
                        child: Padding(
                          padding: EdgeInsets.all(20),
                          child: CircularProgressIndicator(),
                        ),
                      )
                    else if (_error != null)
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.red[100],
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          _error!,
                          style: TextStyle(color: Colors.red[900]),
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

  Widget _buildQRCodeSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        const Text(
          '📱 Escanear para responder',
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            border: Border.all(color: Colors.grey[300]!),
            borderRadius: BorderRadius.circular(8),
          ),
          child: _qrCodeUrl != null
              ? Image.network(
                  _qrCodeUrl!,
                  headers: {
                    if (api.token != null)
                      'Authorization': 'Bearer ${api.token}',
                  },
                  width: 200,
                  height: 200,
                  fit: BoxFit.contain,
                )
              : const SizedBox(
                  width: 200,
                  height: 200,
                  child: Center(
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
              color: Colors.orange[50],
              border: Border.all(color: Colors.orange[200]!),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Icon(Icons.lock_clock, color: Colors.orange[800]),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Quiz encerrado. Novas respostas foram bloqueadas.',
                    style: TextStyle(color: Colors.orange[900]),
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

  Widget _buildStatsSection() {
    final progress = _stats!['progress'] as Map<String, dynamic>;
    final currentQuestion =
        _stats!['current_question'] as Map<String, dynamic>?;
    final livePhase = _stats!['live_phase']?.toString() ?? 'lobby';
    final ranking = (livePhase == 'results'
            ? _stats!['current_ranking_top10']
            : _stats!['ranking_top10']) as List<dynamic>? ??
        [];
    final totalAnswers = progress['total_answers'] as int? ?? 0;
    final correct = progress['correct'] as int? ?? 0;
    final incorrect = progress['incorrect'] as int? ?? 0;
    final participants = _stats!['participants'] as int? ?? 0;
    final online = _stats!['participants_online'] as int? ?? participants;
    final names = (_stats!['participant_names'] as List<dynamic>? ?? const [])
        .map((name) => name.toString())
        .where((name) => name.isNotEmpty)
        .toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          _phaseTitle(livePhase),
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
        const SizedBox(height: 12),
        if (currentQuestion != null) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.purple[50],
              border: Border.all(color: Colors.purple[200]!),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Pergunta ${(currentQuestion['index'] as int? ?? 0) + 1}',
                  style: TextStyle(
                    color: Colors.purple[800],
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  currentQuestion['question_text']?.toString() ?? '',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  'Respostas nesta pergunta: ${currentQuestion['total_answers'] ?? 0}',
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
        ],
        Row(
          children: [
            Expanded(
              child: Text(
                online == participants
                    ? 'Participantes: $participants'
                    : 'Participantes: $participants ($online com a tela aberta)',
              ),
            ),
            Text('Total: $totalAnswers | $correct acertos | $incorrect erros'),
          ],
        ),
        // No lobby o professor precisa ver quem ja entrou antes de iniciar: e a
        // unica confirmacao de que o QR Code funcionou na sala.
        if (livePhase == 'lobby') ...[
          const SizedBox(height: 10),
          if (names.isEmpty)
            Text(
              'Ninguém entrou ainda. Peça para a turma escanear o QR Code.',
              style: Theme.of(context).textTheme.bodySmall,
            )
          else
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final name in names)
                  Chip(
                    label: Text(name, style: const TextStyle(fontSize: 11)),
                    visualDensity: VisualDensity.compact,
                  ),
              ],
            ),
        ],
        const SizedBox(height: 16),
        _buildLiveAction(livePhase),
        const SizedBox(height: 20),
        if (livePhase == 'results' ||
            livePhase == 'finished' ||
            _quizClosed) ...[
          Text(
            livePhase == 'results' ? 'Top 10 da Pergunta' : 'Top 10 Geral',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 10),
          _buildRanking(ranking),
        ] else if (livePhase == 'question') ...[
          const Text('Ranking será exibido ao encerrar a pergunta.'),
        ] else ...[
          const Text('Aguardando iniciar a primeira pergunta.'),
        ],
        const SizedBox(height: 12),
        _buildFreshness(),
      ],
    );
  }

  /// Mostra se o que esta na tela e de agora.
  ///
  /// Quando o backend parava de mandar novidade, a tela continuava exibindo os
  /// mesmos numeros sem avisar nada -- o professor nao tinha como saber que o
  /// lobby vazio era so uma leitura velha.
  Widget _buildFreshness() {
    final estilo = Theme.of(context).textTheme.bodySmall;
    if (_isStale) {
      return Row(
        children: [
          Icon(Icons.sync_problem, size: 16, color: Colors.orange[800]),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              'Sem atualização do servidor há ${_sinceLastUpdate.inSeconds}s. '
              'Reconectando...',
              style: estilo?.copyWith(color: Colors.orange[900]),
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
        Icon(Icons.wifi_tethering, size: 16, color: Colors.green[700]),
        const SizedBox(width: 6),
        Text(
          segundos <= 1
              ? 'Ao vivo · atualizado agora'
              : 'Ao vivo · atualizado há ${segundos}s',
          style: estilo?.copyWith(color: Colors.grey[600]),
        ),
      ],
    );
  }

  String _phaseTitle(String phase) {
    if (_quizClosed || phase == 'finished') return 'Ranking Final';
    if (phase == 'question') return 'Pergunta Atual';
    if (phase == 'results') return 'Ranking da Rodada';
    return 'Lobby do Quiz';
  }

  Widget _buildLiveAction(String phase) {
    if (_quizClosed || phase == 'finished') {
      return const SizedBox.shrink();
    }
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
          label: const Text('Encerrar Pergunta'),
          style: ElevatedButton.styleFrom(
            backgroundColor: Colors.orange[700],
            foregroundColor: Colors.white,
          ),
        ),
      );
    }
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
        label: Text(phase == 'results' ? 'Próxima Pergunta' : 'Iniciar Quiz'),
      ),
    );
  }

  Widget _buildRanking(List<dynamic> ranking) {
    if (ranking.isEmpty) {
      return const Text('Aguardando respostas...');
    }
    return Column(
      children: ranking.map<Widget>((item) {
        final row = item as Map<String, dynamic>;
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: Colors.grey[50],
            border: Border.all(color: Colors.grey[200]!),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              SizedBox(
                width: 44,
                child: Text(
                  '#${row['position'] ?? '-'}',
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              Expanded(
                child: Text(
                  row['student_name']?.toString() ?? 'Aluno',
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                '${row['score'] ?? 0} pts',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

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
      _quizClosed = mesclado['status'] == 'closed';
    });
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

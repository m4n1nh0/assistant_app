/// Acompanha, em tempo real, os alunos que entraram no quiz pelo QR Code.
library;

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import '../services/api_service.dart';

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
  late WebSocketChannel _channel;

  String? _qrCodeUrl;
  Map<String, dynamic>? _stats;
  bool _isConnecting = true;
  bool _isClosingQuiz = false;
  bool _quizClosed = false;
  String? _error;
  int _connectRetries = 0;
  final int _maxRetries = 3;

  @override
  void initState() {
    super.initState();
    _loadQRCode();
    _connectWebSocket();
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
    try {
      // Fecha conexão anterior se existir
      try {
        _channel.sink.close();
      } catch (_) {}

      // Conecta ao WebSocket para monitoramento em tempo real. A URL vem do
      // backend configurado, nao de localhost: o app pode apontar para outra
      // maquina ou para um deploy remoto.
      _channel = WebSocketChannel.connect(
        Uri.parse('${api.wsUrl}/ws/quiz/${widget.quizId}/monitor'),
      );

      // Escuta mensagens
      _channel.stream.listen(
        (message) {
          final data = jsonDecode(message);
          debugPrint('WebSocket message: $data');

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

  void _retryConnection() {
    if (_connectRetries < _maxRetries) {
      _connectRetries++;
      Future.delayed(const Duration(seconds: 3), _connectWebSocket);
    }
  }

  @override
  void dispose() {
    _channel.sink.close();
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
                            'Quiz ao Vivo 📊',
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

                    // Stats Section
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
    final questions = _stats!['questions'] as List<dynamic>? ?? [];
    final totalAnswers = progress['total_answers'] as int? ?? 0;
    final correct = progress['correct'] as int? ?? 0;
    final incorrect = progress['incorrect'] as int? ?? 0;
    final percentage = _stats!['overall_percentage'] as num? ?? 0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Progresso Geral
        Text(
          'Desempenho Geral',
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Respondidas: $totalAnswers'),
                  Text('✅ Acertos: $correct'),
                  Text('❌ Erros: $incorrect'),
                ],
              ),
            ),
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(
                  color: Colors.purple,
                  width: 3,
                ),
              ),
              child: Center(
                child: Text(
                  '${percentage.toInt()}%',
                  style: const TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                    color: Colors.purple,
                  ),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),

        // Taxa de Acerto por Questão
        Text(
          'Por Questão',
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
        ),
        const SizedBox(height: 12),
        if (questions.isNotEmpty)
          ...questions.map<Widget>((q) {
            final qData = q as Map<String, dynamic>;
            final qPercentage = qData['percentage'] as num? ?? 0;
            final correct = qData['correct'] as int? ?? 0;
            final incorrect = qData['incorrect'] as int? ?? 0;
            final total = qData['total_answers'] as int? ?? 0;
            final questionText =
                qData['question_text']?.toString().trim() ?? '';

            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.grey[50],
                  border: Border.all(color: Colors.grey[200]!),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Q${questions.indexOf(q) + 1}',
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    ),
                    if (questionText.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        questionText,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.grey[700],
                        ),
                      ),
                    ],
                    const SizedBox(height: 4),
                    LinearProgressIndicator(
                      value: qPercentage > 0 ? qPercentage / 100 : 0,
                      minHeight: 6,
                      backgroundColor: Colors.grey[300],
                      valueColor: AlwaysStoppedAnimation<Color>(
                        qPercentage >= 50 ? Colors.green : Colors.orange,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '✅ $correct ❌ $incorrect',
                          style: const TextStyle(fontSize: 12),
                        ),
                        Text(
                          '${qPercentage.toInt()}% ($total)',
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            );
          })
        else
          const Text('Aguardando respostas...'),

        const SizedBox(height: 12),
        Text(
          'Atualização em tempo real via WebSocket 🚀',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Colors.grey[600],
              ),
        ),
      ],
    );
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

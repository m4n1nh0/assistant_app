/// Geracao de quiz a partir da aula, com revisao das questoes.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';

typedef QuizGeneratedCallback = void Function(
  String quizId,
  int totalQuestions,
);

/// Widget para gerar e compartilhar quizzes no Modo Educação
class QuizGeneratorWidget extends StatefulWidget {
  final String lessonId;
  final String lessonTitle;
  final String disciplineName;
  final QuizGeneratedCallback? onQuizGenerated;
  final bool showShareDialog;

  const QuizGeneratorWidget({
    super.key,
    required this.lessonId,
    required this.lessonTitle,
    required this.disciplineName,
    this.onQuizGenerated,
    this.showShareDialog = true,
  });

  @override
  State<QuizGeneratorWidget> createState() => _QuizGeneratorWidgetState();
}

class _QuizGeneratorWidgetState extends State<QuizGeneratorWidget> {
  bool _isGenerating = false;
  String? _error;
  String? _generatedQuizId;
  int _questionCount = 10;
  String _quizType = 'pratica';
  String _difficulty = 'mista';

  final List<String> _quizTypes = ['pratica', 'revisao', 'diagnostico'];
  final List<String> _difficulties = ['facil', 'medio', 'dificil', 'mista'];

  String _quizTypeLabel(String value) {
    switch (value) {
      case 'pratica':
        return 'Prática';
      case 'revisao':
        return 'Revisão';
      case 'diagnostico':
        return 'Diagnóstico';
      default:
        return value;
    }
  }

  String _quizTypeDescription(String value) {
    switch (value) {
      case 'pratica':
        return 'Prática reforça o conteúdo da aula com questões diretas.';
      case 'revisao':
        return 'Revisão retoma os principais pontos para consolidar o resumo.';
      case 'diagnostico':
        return 'Diagnóstico identifica lacunas de compreensão depois da aula.';
      default:
        return '';
    }
  }

  String _difficultyLabel(String value) {
    switch (value) {
      case 'facil':
        return 'Fácil';
      case 'medio':
        return 'Médio';
      case 'dificil':
        return 'Difícil';
      case 'mista':
        return 'Mista';
      default:
        return value;
    }
  }

  Future<void> _generateQuiz() async {
    setState(() {
      _isGenerating = true;
      _error = null;
    });

    try {
      // Chama endpoint para gerar quiz
      final response = await api.post(
        '/education/quiz/generate',
        body: {
          'lesson_id': widget.lessonId,
          'tipo_quiz': _quizType,
          'quantidade_questoes': _questionCount,
          'tipos_questao': ['multipla_escolha', 'verdadeiro_falso', 'aberta'],
          'dificuldade': _difficulty,
          'llm': 'auto', // Usa melhor LLM disponível
        },
      );

      if (!response.success) {
        throw Exception(response.error ?? 'Erro ao gerar quiz');
      }

      final quizId = response.data['quiz_id']?.toString() ?? '';
      if (quizId.isEmpty) {
        throw Exception('Resposta sem identificador do quiz');
      }
      final questions = response.data['questoes'];
      final totalQuestions =
          questions is List ? questions.length : _questionCount;

      setState(() {
        _generatedQuizId = quizId;
        _questionCount = totalQuestions.clamp(1, 50).toInt();
      });

      // Callback para notificar parent
      widget.onQuizGenerated?.call(quizId, totalQuestions);

      // Mostra diálogo com opções
      if (mounted && widget.showShareDialog) {
        _showQuizShareDialog(quizId);
      }
    } catch (e) {
      setState(() {
        _error = 'Erro ao gerar quiz: $e';
      });
      _showErrorSnackbar(_error!);
    } finally {
      setState(() {
        _isGenerating = false;
      });
    }
  }

  void _showQuizShareDialog(String quizId) {
    final link = _quizLink(quizId);
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('✨ Quiz Gerado com Sucesso!'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Quiz: ${widget.lessonTitle}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text('Questões geradas: $_questionCount'),
            const SizedBox(height: 16),
            const Text('Compartilhe o link com seus alunos:'),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.grey[100],
                borderRadius: BorderRadius.circular(8),
              ),
              child: SelectableText(
                link,
                style: const TextStyle(
                  fontFamily: 'Courier',
                  fontSize: 12,
                ),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Fechar'),
          ),
          ElevatedButton(
            onPressed: () {
              _copyToClipboard(link);
              Navigator.pop(context);
              _showSuccessSnackbar('Link copiado!');
            },
            child: const Text('Copiar Link'),
          ),
          ElevatedButton(
            onPressed: () {
              _openQuizInBrowser(quizId);
              Navigator.pop(context);
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.green,
            ),
            child: const Text('Abrir Quiz'),
          ),
        ],
      ),
    );
  }

  Future<void> _openQuizInBrowser(String quizId) async {
    final url = Uri.parse(_quizLink(quizId));
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    } else {
      _showErrorSnackbar('Não foi possível abrir o navegador');
    }
  }

  String _quizLink(String quizId) =>
      '${api.baseUrl}/education/quiz/$quizId/play';

  Future<void> _copyToClipboard(String text) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Copiado: $text')),
    );
  }

  void _showErrorSnackbar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red,
      ),
    );
  }

  void _showSuccessSnackbar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.green,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 4,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Título
            Row(
              children: [
                const Icon(Icons.quiz, color: Colors.purple),
                const SizedBox(width: 12),
                Text(
                  'Gerar Quiz',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ],
            ),
            const SizedBox(height: 16),

            // Configuração: Tipo de Quiz
            Row(
              children: [
                Expanded(
                  child: _buildDropdown(
                    label: 'Tipo de Quiz',
                    value: _quizType,
                    items: _quizTypes,
                    itemLabelBuilder: _quizTypeLabel,
                    onChanged: (value) {
                      setState(() => _quizType = value);
                    },
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _buildDropdown(
                    label: 'Dificuldade',
                    value: _difficulty,
                    items: _difficulties,
                    itemLabelBuilder: _difficultyLabel,
                    onChanged: (value) {
                      setState(() => _difficulty = value);
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              _quizTypeDescription(_quizType),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Colors.grey[700],
                  ),
            ),
            const SizedBox(height: 12),

            // Configuração: Número de Questões
            _buildSlider(
              label: 'Número de Questões: $_questionCount',
              value: _questionCount.toDouble(),
              min: 1,
              max: 50,
              onChanged: (value) {
                setState(() => _questionCount = value.toInt());
              },
            ),
            const SizedBox(height: 20),

            // Erro (se houver)
            if (_error != null)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.red[100],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.red),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.error, color: Colors.red),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        _error!,
                        style: const TextStyle(color: Colors.red),
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 12),

            // Botão de Gerar
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _isGenerating ? null : _generateQuiz,
                icon: _isGenerating
                    ? SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          valueColor: AlwaysStoppedAnimation<Color>(
                            Colors.purple[400] ?? Colors.purple,
                          ),
                        ),
                      )
                    : const Icon(Icons.auto_awesome),
                label: Text(
                  _isGenerating ? 'Gerando...' : 'Gerar Quiz com IA',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: Colors.purple,
                ),
              ),
            ),

            // Se quiz foi gerado, mostra link
            if (_generatedQuizId != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.green[50],
                    border: Border.all(color: Colors.green),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.check_circle, color: Colors.green),
                          const SizedBox(width: 8),
                          const Text(
                            'Quiz Gerado!',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.green,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Link para compartilhar:',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      const SizedBox(height: 4),
                      SelectableText(
                        _quizLink(_generatedQuizId!),
                        style: const TextStyle(
                          fontFamily: 'Courier',
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                        children: [
                          ElevatedButton.icon(
                            onPressed: () {
                              _copyToClipboard(_quizLink(_generatedQuizId!));
                            },
                            icon: const Icon(Icons.content_copy),
                            label: const Text('Copiar'),
                          ),
                          ElevatedButton.icon(
                            onPressed: () =>
                                _openQuizInBrowser(_generatedQuizId!),
                            icon: const Icon(Icons.open_in_browser),
                            label: const Text('Abrir'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildDropdown({
    required String label,
    required String value,
    required List<String> items,
    String Function(String value)? itemLabelBuilder,
    required ValueChanged<String> onChanged,
  }) {
    return DropdownButtonFormField<String>(
      value: value,
      decoration: InputDecoration(
        labelText: label,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      ),
      items: items.map((item) {
        return DropdownMenuItem(
          value: item,
          child: Text(itemLabelBuilder?.call(item) ?? item),
        );
      }).toList(),
      onChanged: (newValue) {
        if (newValue != null) onChanged(newValue);
      },
    );
  }

  Widget _buildSlider({
    required String label,
    required double value,
    required double min,
    required double max,
    required ValueChanged<double> onChanged,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.bodyMedium),
        Slider(
          value: value,
          min: min,
          max: max,
          divisions: (max - min).toInt(),
          onChanged: onChanged,
        ),
      ],
    );
  }
}

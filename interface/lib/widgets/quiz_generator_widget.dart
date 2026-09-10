/// Geracao de quiz a partir da aula, com revisao das questoes.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import '../services/education_service.dart';
import 'quiz_preview_dialog.dart';

typedef QuizPublishedCallback = void Function(
  String quizId,
  int totalQuestions,
);

/// Widget para gerar e compartilhar quizzes no Modo Educação
class QuizGeneratorWidget extends StatefulWidget {
  final String lessonId;
  final String lessonTitle;
  final String disciplineName;
  final QuizPublishedCallback? onQuizPublished;
  final bool showShareDialog;

  const QuizGeneratorWidget({
    super.key,
    required this.lessonId,
    required this.lessonTitle,
    required this.disciplineName,
    this.onQuizPublished,
    this.showShareDialog = true,
  });

  @override
  State<QuizGeneratorWidget> createState() => _QuizGeneratorWidgetState();
}

class _QuizGeneratorWidgetState extends State<QuizGeneratorWidget> {
  bool _isGenerating = false;
  bool _isPublishing = false;
  String? _error;

  /// O que o servidor esta fazendo agora, para a espera nao ser uma tela parada.
  String _progress = '';
  String? _generatedQuizId;
  bool _quizPublished = false;
  List<Map<String, dynamic>> _generatedQuestions = const [];

  /// Quantas perguntas a menos vieram em relacao ao pedido.
  int _generatedShortfall = 0;

  /// Resumo do servidor: de quantas fontes o quiz saiu e o que ficou de fora
  /// por nao ter texto. Fonte marcada que nao entrou precisa aparecer aqui.
  String _generatedMessage = '';

  /// Quantas foram efetivamente liberadas para os alunos.
  int _publishedCount = 0;

  /// Tentativas por modelo, para a revisao explicar por que vieram menos
  /// perguntas do que o pedido.
  List<Map<String, dynamic>> _generationAttempts = const [];

  /// Fontes marcadas. Aulas e materiais se somam, em qualquer combinacao: a
  /// revisao de prova junta as aulas do bimestre com a apostila.
  late final Set<String> _lessonIds = {widget.lessonId};
  final Set<String> _materialIds = {};

  List<CourseMaterial> _materials = const [];

  /// Outras aulas da disciplina, para servirem de fonte junto com esta.
  List<Lesson> _lessons = const [];

  int _questionCount = 10;
  String _quizType = 'pratica';
  String _difficulty = 'mista';

  final List<String> _quizTypes = ['pratica', 'revisao', 'diagnostico'];

  @override
  void initState() {
    super.initState();
    _loadSources();
  }

  /// Aulas e materiais da disciplina que podem entrar como fonte.
  ///
  /// Falha em silencio de proposito: sem a lista a tela continua utilizavel,
  /// gerando a partir da aula atual, que ja vem marcada.
  Future<void> _loadSources() async {
    try {
      final items = await education.listMaterials(
        discipline: widget.disciplineName,
      );
      if (mounted) setState(() => _materials = items);
    } catch (_) {}

    try {
      final aulas = await education.listLessons(
        discipline: widget.disciplineName,
        limit: 30,
      );
      if (mounted) setState(() => _lessons = aulas);
    } catch (_) {}
  }
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

  /// Pede a geracao e acompanha ate terminar.
  ///
  /// Escrever as perguntas com a IA passa dos 30s que o cliente HTTP espera, e
  /// o timeout fazia parecer que a geracao tinha falhado quando ela seguia
  /// rodando no servidor. Agora o servidor devolve um `job_id` na hora e a tela
  /// pergunta o andamento; quando termina, o professor tambem e avisado pelos
  /// canais que ele configurou, para poder sair desta tela enquanto espera.
  Future<void> _generateQuiz() async {
    if (_lessonIds.isEmpty && _materialIds.isEmpty) {
      setState(() => _error = 'Marque ao menos uma aula ou material como fonte.');
      _showErrorSnackbar(_error!);
      return;
    }

    setState(() {
      _isGenerating = true;
      _error = null;
      _progress = 'Enviando o conteúdo para a IA...';
    });

    try {
      final response = await api.post(
        '/education/quiz/generate/async',
        body: {
          // Quantas fontes o professor marcar: o servidor junta os textos e
          // grava uma linha por fonte, para a revisao saber de onde cada
          // pergunta saiu.
          'lesson_ids': _lessonIds.toList(),
          'material_ids': _materialIds.toList(),
          'tipo_quiz': _quizType,
          'quantidade_questoes': _questionCount,
          'tipos_questao': ['multipla_escolha'],
          'dificuldade': _difficulty,
          'llm': 'auto', // Usa melhor LLM disponível
        },
      );

      if (!response.success) {
        throw Exception(response.error ?? 'Erro ao gerar quiz');
      }

      final jobId = response.data['job_id']?.toString() ?? '';
      if (jobId.isEmpty) {
        throw Exception('Resposta sem identificador da geração');
      }

      final quiz = await _waitForQuiz(jobId);
      _applyGeneratedQuiz(quiz);
    } catch (e) {
      setState(() {
        _error = 'Erro ao gerar quiz: $e';
      });
      _showErrorSnackbar(_error!);
    } finally {
      setState(() {
        _isGenerating = false;
        _progress = '';
      });
    }
  }

  /// Pergunta o andamento ate o quiz ficar pronto.
  ///
  /// O teto de espera e generoso de proposito: cinquenta perguntas em lotes,
  /// com reescrita de alternativa longa, levam minutos em modelo local.
  Future<Map<String, dynamic>> _waitForQuiz(String jobId) async {
    const intervalo = Duration(seconds: 3);
    const limite = Duration(minutes: 20);
    final comeco = DateTime.now();

    while (DateTime.now().difference(comeco) < limite) {
      await Future<void>.delayed(intervalo);
      if (!mounted) return const {};

      final status = await api.get('/education/quiz/jobs/$jobId');
      if (!status.success) {
        throw Exception(status.error ?? 'Não foi possível acompanhar a geração');
      }

      final estado = status.data['status']?.toString() ?? '';
      final mensagem = status.data['message']?.toString() ?? '';
      if (mensagem.isNotEmpty && mensagem != _progress) {
        setState(() => _progress = mensagem);
      }

      if (estado == 'done') {
        final quiz = status.data['quiz'];
        if (quiz is Map) {
          return quiz.map((key, value) => MapEntry(key.toString(), value));
        }
        throw Exception('Geração terminou sem devolver o quiz');
      }
      if (estado == 'error') {
        throw Exception(
          status.data['error']?.toString() ?? 'A IA não gerou as perguntas',
        );
      }
    }

    throw Exception(
      'A geração passou de 20 minutos. Ela continua no servidor: '
      'você será avisado quando terminar.',
    );
  }

  void _applyGeneratedQuiz(Map<String, dynamic> quiz) {
    final quizId = quiz['quiz_id']?.toString() ?? '';
    if (quizId.isEmpty) {
      throw Exception('Resposta sem identificador do quiz');
    }

    final questions = quiz['questoes'];
    final questionItems = questions is List
        ? questions
            .whereType<Map>()
            .map((item) => item.map(
                  (key, value) => MapEntry(key.toString(), value),
                ))
            .toList()
        : <Map<String, dynamic>>[];

    final rawAttempts = quiz['attempts'];

    setState(() {
      _generatedQuizId = quizId;
      _quizPublished = false;
      _generatedMessage = quiz['message']?.toString() ?? '';
      _generatedQuestions = questionItems;
      _generationAttempts = rawAttempts is List
          ? rawAttempts
              .whereType<Map>()
              .map((item) => item.map((k, v) => MapEntry(k.toString(), v)))
              .toList()
          : const [];
      // O controle guarda o que foi *pedido*. Sobrescrever com o que voltou
      // fazia o numero recuar sozinho e parecer que o campo nao aceitava o
      // valor; a diferenca agora e dita em texto, no lugar de escondida.
      _generatedShortfall =
          questionItems.isNotEmpty && questionItems.length < _questionCount
              ? _questionCount - questionItems.length
              : 0;
    });
  }

  Future<void> _publishQuiz() async {
    final quizId = _generatedQuizId;
    if (quizId == null || _isPublishing) return;

    setState(() {
      _isPublishing = true;
      _error = null;
    });

    try {
      final response = await api.post(
        '/education/quiz/$quizId/publish',
        body: {},
      );

      if (!response.success) {
        throw Exception(response.error ?? 'Erro ao liberar QR Code');
      }

      final questions = response.data['questoes'];
      final totalQuestions =
          questions is List ? questions.length : _questionCount;

      setState(() {
        _quizPublished = true;
        // Campo proprio: `_questionCount` e o pedido do professor e nao pode
        // ser reescrito pelo que saiu.
        _publishedCount = totalQuestions.clamp(1, 50).toInt();
      });

      widget.onQuizPublished?.call(quizId, totalQuestions);

      if (mounted && widget.showShareDialog) {
        _showQuizShareDialog(quizId);
      }
    } catch (e) {
      setState(() {
        _error = 'Erro ao liberar QR Code: $e';
      });
      _showErrorSnackbar(_error!);
    } finally {
      setState(() {
        _isPublishing = false;
      });
    }
  }

  void _showQuizShareDialog(String quizId) {
    final link = _quizLink(quizId);
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('✨ Quiz Liberado com Sucesso!'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Quiz: ${widget.lessonTitle}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text('Questões liberadas: $_publishedCount'),
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

  bool get _hasReviewWarnings => _generatedQuestions.any(
        (question) => question['verificado'] == false,
      );

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

            _buildSourcePicker(),

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
                  _isGenerating ? 'Gerando...' : 'Preparar Perguntas com IA',
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

            // Andamento: a geracao leva minutos, e barra parada sem texto
            // parece travamento.
            if (_isGenerating && _progress.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  '$_progress Você pode fechar esta tela: o aviso chega '
                  'quando o quiz ficar pronto.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),

            // Se quiz foi gerado, mostra perguntas antes de liberar o QR Code.
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
                            'Perguntas preparadas',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.green,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      if (_generatedMessage.isNotEmpty) ...[
                        Text(
                          _generatedMessage,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        const SizedBox(height: 8),
                      ],
                      if (_generatedQuestions.isNotEmpty) ...[
                        Text(
                          'Confira as perguntas antes de liberar o QR Code:',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        const SizedBox(height: 8),
                        if (_hasReviewWarnings) ...[
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: Colors.orange[50],
                              border: Border.all(color: Colors.orange),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Row(
                              children: [
                                const Icon(
                                  Icons.warning_amber_rounded,
                                  color: Colors.orange,
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    'Há perguntas geradas com baixa confiança. Revise antes de liberar.',
                                    style:
                                        Theme.of(context).textTheme.bodySmall,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 8),
                        ],
                        ..._generatedQuestions
                            .take(8)
                            .toList()
                            .asMap()
                            .entries
                            .map((entry) {
                          final index = entry.key;
                          final question = entry.value;
                          final enunciado =
                              question['enunciado']?.toString().trim() ?? '';
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 6),
                            child: Text(
                              '${index + 1}. $enunciado',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          );
                        }),
                        if (_generatedQuestions.length > 8)
                          Text(
                            '+ ${_generatedQuestions.length - 8} pergunta(s)',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        if (_generatedShortfall > 0)
                          Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(
                              'Você pediu $_questionCount e vieram '
                              '${_generatedQuestions.length}. Abra a revisão '
                              'para ver o motivo.',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(color: Colors.orange),
                            ),
                          ),
                        const SizedBox(height: 8),
                        OutlinedButton.icon(
                          onPressed: () => showQuizPreviewDialog(
                            context,
                            questions: _generatedQuestions,
                            requested: _questionCount,
                            attempts: _generationAttempts,
                          ),
                          icon: const Icon(Icons.fact_check_outlined, size: 16),
                          label: const Text('REVISAR PERGUNTAS'),
                        ),
                        const SizedBox(height: 12),
                      ],
                      if (_quizPublished) ...[
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
                      ],
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                        children: [
                          if (!_quizPublished)
                            Expanded(
                              child: ElevatedButton.icon(
                                onPressed: _isPublishing ? null : _publishQuiz,
                                icon: _isPublishing
                                    ? const SizedBox(
                                        height: 18,
                                        width: 18,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                        ),
                                      )
                                    : const Icon(Icons.qr_code_2),
                                label: Text(
                                  _isPublishing
                                      ? 'Liberando...'
                                      : 'Liberar QR Code',
                                ),
                              ),
                            )
                          else ...[
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

  /// Fontes do quiz: aulas da disciplina e materiais importados.
  ///
  /// Multipla escolha de proposito. A aula atual ja vem marcada, porque e o
  /// caminho comum, mas a revisao de prova precisa somar varias aulas com a
  /// apostila - e antes isso obrigava a gerar um quiz por fonte e aplicar tres
  /// QR Codes seguidos.
  Widget _buildSourcePicker() {
    final selecionadas = _lessonIds.length + _materialIds.length;

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Fontes do quiz: $selecionadas marcada(s)',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          Text(
            'Aulas encerradas ou em andamento, e materiais importados. '
            'Pode marcar quantas quiser.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Colors.grey[700],
                ),
          ),
          const SizedBox(height: 6),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: Colors.grey.shade400),
              borderRadius: BorderRadius.circular(8),
            ),
            constraints: const BoxConstraints(maxHeight: 200),
            child: ListView(
              shrinkWrap: true,
              padding: EdgeInsets.zero,
              children: [
                for (final aula in _sourceLessons())
                  _buildSourceTile(
                    titulo: aula.id == widget.lessonId
                        ? 'Aula atual: ${_lessonLabel(aula)}'
                        : 'Aula: ${_lessonLabel(aula)}',
                    detalhe: _lessonHint(aula),
                    marcada: _lessonIds.contains(aula.id),
                    onChanged: (marcar) => setState(() {
                      if (marcar) {
                        _lessonIds.add(aula.id);
                      } else {
                        _lessonIds.remove(aula.id);
                      }
                    }),
                  ),
                for (final material in _materials)
                  _buildSourceTile(
                    titulo: 'Material: '
                        '${material.title.isEmpty ? material.filename : material.title}',
                    detalhe: '${material.pageCount} página(s)',
                    marcada: _materialIds.contains(material.id),
                    onChanged: (marcar) => setState(() {
                      if (marcar) {
                        _materialIds.add(material.id);
                      } else {
                        _materialIds.remove(material.id);
                      }
                    }),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSourceTile({
    required String titulo,
    required String detalhe,
    required bool marcada,
    required ValueChanged<bool> onChanged,
  }) {
    return CheckboxListTile(
      value: marcada,
      dense: true,
      controlAffinity: ListTileControlAffinity.leading,
      contentPadding: const EdgeInsets.symmetric(horizontal: 8),
      title: Text(
        titulo,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: Theme.of(context).textTheme.bodySmall,
      ),
      subtitle: Text(
        detalhe,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              fontSize: 10,
              color: Colors.grey[700],
            ),
      ),
      onChanged: (valor) => onChanged(valor ?? false),
    );
  }

  /// A aula atual primeiro, depois as outras da disciplina.
  ///
  /// A atual entra mesmo quando a listagem nao a trouxe (filtro de semestre,
  /// limite de itens): sem ela a tela abriria sem nenhuma fonte marcada.
  List<Lesson> _sourceLessons() {
    final outras = _lessons.where((aula) => aula.id != widget.lessonId);
    final atual = _lessons.where((aula) => aula.id == widget.lessonId);

    return [
      if (atual.isNotEmpty)
        atual.first
      else
        Lesson(
          id: widget.lessonId,
          discipline: widget.disciplineName,
          title: widget.lessonTitle,
          classGroup: '',
          status: 'closed',
        ),
      ...outras,
    ];
  }

  String _lessonLabel(Lesson aula) =>
      aula.title.isEmpty ? 'sem título' : aula.title;

  /// O que decide se vale marcar a aula: ela tem texto?
  String _lessonHint(Lesson aula) {
    final temResumo = (aula.summary ?? '').trim().isNotEmpty;
    return [
      aula.isClosed ? 'encerrada' : 'em andamento',
      temResumo ? 'com resumo' : 'sem resumo',
      '${aula.transcriptChars} caracteres transcritos',
    ].join(' · ');
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

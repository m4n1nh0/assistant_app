/// Pedido de quiz a partir de aulas e materiais.
///
/// A tela so monta o pedido. A geracao vai para a fila do servidor e o
/// professor acompanha pela central (aba FILA) - revisar, liberar o QR Code e
/// reaproveitar questoes acontece la, com o quiz ja gravado.
library;

import 'package:flutter/material.dart';
import '../services/education_service.dart';
import '../services/quiz_center_service.dart';
import '../services/quiz_queue_watcher.dart';

/// Widget para pedir quizzes no Modo Educação
class QuizGeneratorWidget extends StatefulWidget {
  final String lessonId;
  final String lessonTitle;
  final String disciplineName;

  /// Chamado depois que o pedido entrou na fila, com o pedido criado.
  final ValueChanged<QuizJob>? onQueued;

  const QuizGeneratorWidget({
    super.key,
    required this.lessonId,
    required this.lessonTitle,
    required this.disciplineName,
    this.onQueued,
  });

  @override
  State<QuizGeneratorWidget> createState() => _QuizGeneratorWidgetState();
}

class _QuizGeneratorWidgetState extends State<QuizGeneratorWidget> {
  bool _isSending = false;
  String? _error;

  /// Ultimo pedido enviado, para a confirmacao na tela.
  QuizJob? _lastJob;

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

  /// Coloca o pedido na fila e libera a tela na hora.
  ///
  /// Esperar a geracao aqui prendia o professor por minutos e se perdia ao
  /// fechar a tela. Agora o servidor grava o pedido, a central acompanha e o
  /// aviso chega quando o quiz fica pronto - com o app aberto ou na proxima vez
  /// que abrir.
  Future<void> _generateQuiz() async {
    if (_lessonIds.isEmpty && _materialIds.isEmpty) {
      setState(() => _error = 'Marque ao menos uma aula ou material como fonte.');
      _showErrorSnackbar(_error!);
      return;
    }

    setState(() {
      _isSending = true;
      _error = null;
    });

    try {
      final job = await quizCenter.enqueue({
        'lesson_ids': _lessonIds.toList(),
        'material_ids': _materialIds.toList(),
        'tipo_quiz': _quizType,
        'quantidade_questoes': _questionCount,
        'tipos_questao': ['multipla_escolha'],
        'dificuldade': _difficulty,
        'llm': 'auto',
      });
      if (!mounted) return;
      setState(() => _lastJob = job);
      await quizQueueWatcher.refresh();
      widget.onQueued?.call(job);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'Não foi possível pedir o quiz: $e');
      _showErrorSnackbar(_error!);
    } finally {
      if (mounted) setState(() => _isSending = false);
    }
  }

  void _showErrorSnackbar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red,
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
            Row(
              children: [
                const Icon(Icons.quiz, color: Colors.purple),
                const SizedBox(width: 12),
                Text(
                  'Pedir Quiz',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ],
            ),
            const SizedBox(height: 16),
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
            if (_error != null)
              Container(
                padding: const EdgeInsets.all(12),
                margin: const EdgeInsets.only(bottom: 12),
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
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: _isSending ? null : _generateQuiz,
                icon: _isSending
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.playlist_add),
                label: Text(
                  _isSending ? 'Enviando...' : 'Colocar na Fila de Geração',
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
            if (_lastJob != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.green.withValues(alpha: 0.08),
                    border: Border.all(color: Colors.green),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.check_circle_outline, color: Colors.green),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          '"${_lastJob!.titulo}" entrou na fila. '
                          '${_lastJob!.message} Você será avisado quando '
                          'ficar pronto — pode continuar usando o app.',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
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
                        ? 'Atual: ${aula.displayLabel}'
                        : aula.displayLabel,
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

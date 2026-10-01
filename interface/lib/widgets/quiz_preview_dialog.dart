/// Revisao das perguntas antes de liberar o QR Code.
///
/// A lista do painel mostrava so o enunciado cortado em duas linhas: dava para
/// contar as perguntas, nao para conferir se estavam certas. Como quem responde
/// e a turma inteira e o erro so aparece com o quiz no ar, a revisao precisa
/// mostrar o que o aluno vai ver - alternativas inclusive - e de onde cada
/// pergunta saiu.
///
/// Codex e Claude entram aqui como especialistas: cada um resolve as perguntas
/// sem ver o gabarito, e o que divergiu da chave gravada aparece marcado em cada
/// pergunta, com a sugestao de correcao quando o agente deu uma.
library;

import 'package:flutter/material.dart';

import '../services/quiz_specialist_review.dart';
import '../utils/theme.dart';

/// Roda a revisao pelos agentes e devolve o resultado. `onProgress` informa o
/// que cada agente esta fazendo.
typedef SpecialistReviewHandler = Future<SpecialistReviewOutcome> Function(
  void Function(String message) onProgress,
);

/// Aplica a sugestao de um agente a pergunta e devolve a lista de perguntas ja
/// atualizada, como o servidor a tem.
typedef SuggestionApplier = Future<List<Map<String, dynamic>>> Function(
  String questionId,
  Map<String, dynamic> suggestion,
);

/// Abre a revisao completa das perguntas geradas.
Future<void> showQuizPreviewDialog(
  BuildContext context, {
  required List<Map<String, dynamic>> questions,
  required int requested,
  List<Map<String, dynamic>> attempts = const [],
  String title = 'Revisar perguntas',
  List<Widget> Function(BuildContext dialogContext)? actionsBuilder,
  SpecialistReviewHandler? onSpecialistReview,
  SuggestionApplier? onApplySuggestion,
}) {
  return showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820, maxHeight: 700),
        child: QuizPreview(
          questions: questions,
          requested: requested,
          attempts: attempts,
          title: title,
          actions: actionsBuilder?.call(dialogContext) ?? const [],
          onSpecialistReview: onSpecialistReview,
          onApplySuggestion: onApplySuggestion,
        ),
      ),
    ),
  );
}

class QuizPreview extends StatefulWidget {
  final List<Map<String, dynamic>> questions;
  final int requested;
  final List<Map<String, dynamic>> attempts;
  final String title;

  /// Botoes do fluxo do quiz (liberar, abrir QR, descartar), quando a revisao
  /// foi aberta a partir da central.
  final List<Widget> actions;

  /// Quando informado, mostra o botao que pede a Codex e Claude que revisem.
  final SpecialistReviewHandler? onSpecialistReview;

  /// Quando informado, cada sugestao de agente ganha o botao de aplicar.
  final SuggestionApplier? onApplySuggestion;

  const QuizPreview({
    super.key,
    required this.questions,
    required this.requested,
    required this.attempts,
    this.title = 'Revisar perguntas',
    this.actions = const [],
    this.onSpecialistReview,
    this.onApplySuggestion,
  });

  @override
  State<QuizPreview> createState() => _QuizPreviewState();
}

class _QuizPreviewState extends State<QuizPreview> {
  late List<Map<String, dynamic>> _questions = widget.questions;
  bool _reviewing = false;
  String _progress = '';
  SpecialistReviewOutcome? _outcome;
  String? _applying;

  /// Modelos que falharam, com o motivo. Explica por que vieram menos
  /// perguntas do que o pedido: sem isso aqui o professor so ve o numero
  /// menor, nao a causa.
  List<String> get _failures => [
        for (final attempt in widget.attempts)
          if (attempt['success'] != true)
            '${attempt['llm'] ?? 'modelo'}: '
                '${(attempt['error'] ?? 'sem detalhe').toString().trim()}',
      ];

  Future<void> _runSpecialists() async {
    final handler = widget.onSpecialistReview;
    if (handler == null || _reviewing) return;
    setState(() {
      _reviewing = true;
      _progress = 'Preparando a revisão...';
      _outcome = null;
    });
    try {
      final outcome = await handler((message) {
        if (mounted) setState(() => _progress = message);
      });
      if (!mounted) return;
      setState(() {
        _outcome = outcome;
        final quiz = outcome.quiz;
        final fresh = quiz?['questoes'];
        if (fresh is List) {
          _questions = [
            for (final item in fresh.whereType<Map>())
              item.map((k, v) => MapEntry(k.toString(), v)),
          ];
        }
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _outcome = SpecialistReviewOutcome(
            runs: [
              SpecialistRun(
                agentId: '',
                label: 'Revisão',
                ok: false,
                detail: '$error',
              ),
            ],
          ));
    } finally {
      if (mounted) setState(() => _reviewing = false);
    }
  }

  Future<void> _apply(String questionId, Map<String, dynamic> suggestion) async {
    final applier = widget.onApplySuggestion;
    if (applier == null || _applying != null) return;
    setState(() => _applying = questionId);
    try {
      final fresh = await applier(questionId, suggestion);
      if (!mounted) return;
      setState(() => _questions = fresh);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Sugestão aplicada à pergunta.')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Não apliquei a sugestão: $error'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _applying = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final faltando = widget.requested - _questions.length;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 12, 8),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.title,
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${_questions.length} pergunta(s) · pedido: ${widget.requested}'
                      '${faltando > 0 ? " · $faltando a menos" : ""}',
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              if (widget.onSpecialistReview != null) ...[
                OutlinedButton.icon(
                  onPressed: _reviewing ? null : _runSpecialists,
                  icon: _reviewing
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.verified_outlined, size: 16),
                  label: const Text('REVISAR COM CODEX + CLAUDE'),
                ),
                const SizedBox(width: 6),
              ],
              for (final action in widget.actions) ...[
                action,
                const SizedBox(width: 6),
              ],
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
        ),
        if (_reviewing)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: _ProgressoDaRevisao(message: _progress),
          )
        else if (_outcome != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: _ResultadoDaRevisao(outcome: _outcome!),
          ),
        if (faltando > 0 || _failures.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
            child: _AvisoGeracao(
              faltando: faltando,
              failures: _failures,
            ),
          ),
        const Divider(height: 20),
        Expanded(
          child: _questions.isEmpty
              ? const Center(child: Text('Nenhuma pergunta gerada.'))
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
                  itemCount: _questions.length,
                  separatorBuilder: (_, __) => const Divider(height: 24),
                  itemBuilder: (_, index) {
                    final question = _questions[index];
                    final id = question['id']?.toString() ?? '';
                    return QuestionReviewCard(
                      number: index + 1,
                      question: question,
                      applying: _applying == id,
                      onApplySuggestion: widget.onApplySuggestion == null
                          ? null
                          : (suggestion) => _apply(id, suggestion),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class _ProgressoDaRevisao extends StatelessWidget {
  final String message;

  const _ProgressoDaRevisao({required this.message});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const LinearProgressIndicator(minHeight: 3),
          const SizedBox(height: 6),
          Text(message, style: Theme.of(context).textTheme.bodySmall),
        ],
      );
}

/// O que a revisao dos agentes concluiu, em uma frase.
class _ResultadoDaRevisao extends StatelessWidget {
  final SpecialistReviewOutcome outcome;

  const _ResultadoDaRevisao({required this.outcome});

  @override
  Widget build(BuildContext context) {
    final divergent = (outcome.summary['divergente'] ?? 0) > 0;
    final color = !outcome.anyOk
        ? Colors.orange
        : divergent
            ? Colors.redAccent
            : Colors.green;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        outcome.message,
        style: Theme.of(context)
            .textTheme
            .bodySmall
            ?.copyWith(color: AssistantTheme.textPrimary),
      ),
    );
  }
}

/// Diz por que o resultado veio diferente do pedido.
class _AvisoGeracao extends StatelessWidget {
  final int faltando;
  final List<String> failures;

  const _AvisoGeracao({
    required this.faltando,
    required this.failures,
  });

  @override
  Widget build(BuildContext context) {
    final linhas = [
      if (faltando > 0)
        'Vieram $faltando a menos que o pedido: a aula pode não ter '
            'conteúdo suficiente, ou perguntas frágeis foram descartadas.',
      ...failures.map((f) => 'Falhou — $f'),
    ];

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.orange.withValues(alpha: 0.08),
        border: Border.all(color: Colors.orange),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final linha in linhas)
            Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Text(
                linha,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        ],
      ),
    );
  }
}

/// Nome de tela de um agente revisor.
String specialistName(String agentId) => switch (agentId) {
      'codex_cli' => 'Codex',
      'claude_cli' => 'Claude',
      _ => agentId,
    };

/// O veredito consolidado de uma pergunta, ou `null` sem revisao.
String? reviewStatus(Map<String, dynamic> question) {
  final revisao = question['revisao'];
  if (revisao is! Map) return null;
  final status = revisao['status']?.toString() ?? '';
  return status.isEmpty ? null : status;
}

/// Uma pergunta como o aluno vai ver, mais o que so o professor precisa saber.
class QuestionReviewCard extends StatelessWidget {
  final int number;
  final Map<String, dynamic> question;
  final bool applying;
  final void Function(Map<String, dynamic> suggestion)? onApplySuggestion;

  const QuestionReviewCard({
    super.key,
    required this.number,
    required this.question,
    this.applying = false,
    this.onApplySuggestion,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final options = (question['opcoes'] as List<dynamic>? ?? const [])
        .whereType<Map>()
        .map((item) => item.map((k, v) => MapEntry(k.toString(), v)))
        .toList();
    final tipo = question['tipo']?.toString() ?? 'multipla_escolha';
    final justificativa = question['justificativa']?.toString().trim() ?? '';
    final correta = question['resposta_correta']?.toString().trim() ?? '';
    final status = reviewStatus(question);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 26,
              child: Text('$number.', style: theme.textTheme.bodyMedium),
            ),
            Expanded(
              child: Text(
                question['enunciado']?.toString().trim() ?? '(sem enunciado)',
                style: theme.textTheme.bodyMedium,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Padding(
          padding: const EdgeInsets.only(left: 26),
          child: Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              _Etiqueta(_tipoLabel(tipo)),
              if (question['dificuldade'] != null)
                _Etiqueta('${question['dificuldade']}'),
              if (status != null)
                _statusEtiqueta(question, status)
              else if (question['verificado'] == false)
                const _Etiqueta('NÃO VERIFICADA', color: Colors.orange),
            ],
          ),
        ),
        if (options.isNotEmpty) ...[
          const SizedBox(height: 8),
          ...options.map((option) {
            final correct = option['correta'] == true;
            return Padding(
              padding: const EdgeInsets.only(left: 26, bottom: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    correct
                        ? Icons.check_circle_outline
                        : Icons.radio_button_unchecked,
                    size: 15,
                    color: correct ? Colors.green : theme.disabledColor,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      '${option['label'] ?? ''}. ${option['texto'] ?? ''}',
                      style: theme.textTheme.bodySmall?.copyWith(
                        fontWeight:
                            correct ? FontWeight.w600 : FontWeight.normal,
                      ),
                    ),
                  ),
                ],
              ),
            );
          }),
        ] else if (correta.isNotEmpty) ...[
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.only(left: 26),
            child: Text(
              'Resposta esperada: $correta',
              style: theme.textTheme.bodySmall,
            ),
          ),
        ],
        // Multipla escolha sem alternativa nao e respondivel: o aviso evita
        // liberar o QR Code e so descobrir com a turma na tela.
        if (options.isEmpty && tipo == 'multipla_escolha')
          Padding(
            padding: const EdgeInsets.only(left: 26, top: 6),
            child: Text(
              'Sem alternativas: esta pergunta não pode ser respondida.',
              style: theme.textTheme.bodySmall?.copyWith(color: Colors.red),
            ),
          ),
        if (justificativa.isNotEmpty) ...[
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.only(left: 26),
            child: Text(
              justificativa,
              style: theme.textTheme.bodySmall
                  ?.copyWith(fontStyle: FontStyle.italic),
            ),
          ),
        ],
        if (status != null)
          Padding(
            padding: const EdgeInsets.only(left: 26, top: 8),
            child: _LeituraDosAgentes(
              question: question,
              applying: applying,
              onApplySuggestion: onApplySuggestion,
            ),
          ),
      ],
    );
  }

  Widget _statusEtiqueta(Map<String, dynamic> question, String status) {
    final agentes = (question['revisao'] as Map)['agentes'];
    final nomes = agentes is Map
        ? agentes.keys.map((id) => specialistName(id.toString())).join(' + ')
        : '';
    return switch (status) {
      'aprovada' => _Etiqueta(
          nomes.isEmpty ? 'VERIFICADA' : 'VERIFICADA · $nomes',
          color: Colors.green,
        ),
      'divergente' =>
        const _Etiqueta('DIVERGÊNCIA DE GABARITO', color: Colors.redAccent),
      'sem_gabarito' =>
        const _Etiqueta('SEM GABARITO', color: Colors.orange),
      _ => const _Etiqueta('REVISAR', color: Colors.orange),
    };
  }

  String _tipoLabel(String tipo) => switch (tipo) {
        'verdadeiro_falso' => 'V ou F',
        'aberta' => 'ABERTA',
        _ => 'MÚLTIPLA ESCOLHA',
      };
}

/// O que cada agente concluiu sobre a pergunta: qual alternativa resolveu, se
/// a aula sustenta, os defeitos que apontou e a correcao que sugeriu.
class _LeituraDosAgentes extends StatelessWidget {
  final Map<String, dynamic> question;
  final bool applying;
  final void Function(Map<String, dynamic> suggestion)? onApplySuggestion;

  const _LeituraDosAgentes({
    required this.question,
    required this.applying,
    required this.onApplySuggestion,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final agentes = (question['revisao'] as Map)['agentes'];
    if (agentes is! Map || agentes.isEmpty) return const SizedBox.shrink();
    final key = _storedKey(question);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AssistantTheme.surface2,
        border: Border.all(color: AssistantTheme.border2),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final entry in agentes.entries)
            if (entry.value is Map) ...[
              _linhaDoAgente(
                theme,
                specialistName(entry.key.toString()),
                (entry.value as Map).cast<String, dynamic>(),
                key,
              ),
            ],
        ],
      ),
    );
  }

  Widget _linhaDoAgente(
    ThemeData theme,
    String nome,
    Map<String, dynamic> leitura,
    String key,
  ) {
    final resposta = leitura['resposta']?.toString() ?? '';
    final problemas = (leitura['problemas'] as List? ?? const [])
        .map((p) => p.toString())
        .where((p) => p.isNotEmpty)
        .toList();
    final sugestao = leitura['sugestao'];
    final confere = resposta.isNotEmpty && resposta == key;
    final cor = confere ? Colors.greenAccent : Colors.redAccent;

    final conclusao = resposta.isEmpty
        ? 'não chegou a uma única resposta correta'
        : confere
            ? 'resolveu como $resposta — confere com o gabarito'
            : 'resolveu como $resposta — o gabarito é ${key.isEmpty ? '(vazio)' : key}';

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text.rich(
            TextSpan(children: [
              TextSpan(
                text: '$nome ',
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AssistantTheme.textPrimary,
                ),
              ),
              TextSpan(text: conclusao, style: TextStyle(color: cor)),
              if (leitura['ancorada'] == false)
                const TextSpan(
                  text: ' · a aula não sustenta essa resposta',
                  style: TextStyle(color: Colors.orangeAccent),
                ),
            ]),
            style: theme.textTheme.bodySmall,
          ),
          for (final problema in problemas)
            Padding(
              padding: const EdgeInsets.only(left: 10, top: 2),
              child: Text(
                '• $problema',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: AssistantTheme.textSecondary),
              ),
            ),
          if (sugestao is Map)
            _sugestao(theme, nome, sugestao.cast<String, dynamic>()),
        ],
      ),
    );
  }

  Widget _sugestao(
    ThemeData theme,
    String nome,
    Map<String, dynamic> sugestao,
  ) {
    final opcoes = (sugestao['opcoes'] as List? ?? const [])
        .whereType<Map>()
        .toList();
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          border: Border.all(color: AssistantTheme.border2),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Sugestão de $nome',
              style: theme.textTheme.bodySmall?.copyWith(
                fontWeight: FontWeight.w700,
                color: AssistantTheme.textPrimary,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              sugestao['enunciado']?.toString() ?? '',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: AssistantTheme.textPrimary),
            ),
            for (final opcao in opcoes)
              Text(
                '${opcao['correta'] == true ? '✓' : '·'} '
                '${opcao['label']}. ${opcao['texto']}',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: opcao['correta'] == true
                      ? Colors.greenAccent
                      : AssistantTheme.textSecondary,
                ),
              ),
            if (onApplySuggestion != null)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: applying ? null : () => onApplySuggestion!(sugestao),
                  icon: applying
                      ? const SizedBox(
                          width: 12,
                          height: 12,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.auto_fix_high, size: 14),
                  label: const Text('APLICAR SUGESTÃO'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// Letra da alternativa que o gerador marcou como correta.
  String _storedKey(Map<String, dynamic> question) {
    for (final option in (question['opcoes'] as List? ?? const [])) {
      if (option is Map && option['correta'] == true) {
        return option['label']?.toString().trim().toUpperCase() ?? '';
      }
    }
    return '';
  }
}

class _Etiqueta extends StatelessWidget {
  final String label;
  final Color? color;

  const _Etiqueta(this.label, {this.color});

  @override
  Widget build(BuildContext context) {
    final cor = color ?? Theme.of(context).disabledColor;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        border: Border.all(color: cor),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Text(
        label.toUpperCase(),
        style: TextStyle(fontSize: 9, letterSpacing: 0.5, color: cor),
      ),
    );
  }
}

/// Revisao das perguntas antes de liberar o QR Code.
///
/// A lista do painel mostrava so o enunciado cortado em duas linhas: dava para
/// contar as perguntas, nao para conferir se estavam certas. Como quem responde
/// e a turma inteira e o erro so aparece com o quiz no ar, a revisao precisa
/// mostrar o que o aluno vai ver - alternativas inclusive - e de onde cada
/// pergunta saiu.
library;

import 'package:flutter/material.dart';

/// Abre a revisao completa das perguntas geradas.
Future<void> showQuizPreviewDialog(
  BuildContext context, {
  required List<Map<String, dynamic>> questions,
  required int requested,
  List<Map<String, dynamic>> attempts = const [],
}) {
  return showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760, maxHeight: 640),
        child: _QuizPreview(
          questions: questions,
          requested: requested,
          attempts: attempts,
        ),
      ),
    ),
  );
}

class _QuizPreview extends StatelessWidget {
  final List<Map<String, dynamic>> questions;
  final int requested;
  final List<Map<String, dynamic>> attempts;

  const _QuizPreview({
    required this.questions,
    required this.requested,
    required this.attempts,
  });

  /// Modelos que falharam, com o motivo. Explica por que as perguntas sairam
  /// com cara de modelo: quando nenhum LLM entrega JSON valido, o servidor cai
  /// para um gerador por template, e sem isso aqui o professor so ve o
  /// resultado ruim, nao a causa.
  List<String> get _failures => [
        for (final attempt in attempts)
          if (attempt['success'] != true)
            '${attempt['llm'] ?? 'modelo'}: '
                '${(attempt['error'] ?? 'sem detalhe').toString().trim()}',
      ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final faltando = requested - questions.length;
    final porTemplate =
        questions.where((q) => q['fallback'] == true).length;

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
                      'Revisar perguntas',
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${questions.length} pergunta(s) · pedido: $requested'
                      '${faltando > 0 ? " · $faltando a menos" : ""}',
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
        ),
        if (faltando > 0 || porTemplate > 0)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: _AvisoGeracao(
              faltando: faltando,
              porTemplate: porTemplate,
              failures: _failures,
            ),
          ),
        const Divider(height: 20),
        Expanded(
          child: questions.isEmpty
              ? const Center(child: Text('Nenhuma pergunta gerada.'))
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
                  itemCount: questions.length,
                  separatorBuilder: (_, __) => const Divider(height: 24),
                  itemBuilder: (_, index) => _QuestionCard(
                    number: index + 1,
                    question: questions[index],
                  ),
                ),
        ),
      ],
    );
  }
}

/// Diz por que o resultado veio diferente do pedido.
class _AvisoGeracao extends StatelessWidget {
  final int faltando;
  final int porTemplate;
  final List<String> failures;

  const _AvisoGeracao({
    required this.faltando,
    required this.porTemplate,
    required this.failures,
  });

  @override
  Widget build(BuildContext context) {
    final linhas = [
      if (porTemplate > 0)
        '$porTemplate pergunta(s) foram montadas por template, não pela IA.',
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

/// Uma pergunta como o aluno vai ver, mais o que so o professor precisa saber.
class _QuestionCard extends StatelessWidget {
  final int number;
  final Map<String, dynamic> question;

  const _QuestionCard({required this.number, required this.question});

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
              if (question['fallback'] == true)
                const _Etiqueta('TEMPLATE', color: Colors.orange),
              if (question['verificado'] == false &&
                  question['fallback'] != true)
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
      ],
    );
  }

  String _tipoLabel(String tipo) => switch (tipo) {
        'verdadeiro_falso' => 'V ou F',
        'aberta' => 'ABERTA',
        _ => 'MÚLTIPLA ESCOLHA',
      };
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

/// Resumo executivo do quiz: o veredito, os numeros que importam, o que merece
/// atencao e o que fazer, em linguagem de quem nao vai ler tabela.
///
/// E para quem decide sem ter estado na sala - coordenacao, direcao -, entao:
///
/// - **so numeros agregados, nunca nome de aluno.** O documento circula fora da
///   sala; quem precisa do nome tem o relatorio completo;
/// - **as frases saem de regras sobre os dados, nao de um modelo de IA.** Texto
///   gerado poderia inventar uma conclusao que os numeros nao sustentam, e o
///   leitor executivo nao tem como conferir;
/// - **diz o que nao sabe.** Um quiz e uma amostra de uma aula, e o aluno e o
///   navegador dele: o resumo avisa o limite em vez de fingir certeza.
///
/// Tela e PDF leem o mesmo objeto, para nunca contarem historias diferentes.
library;

import 'quiz_report.dart';

/// Faixas de acerto: acima de [goodRate] o desempenho e bom, abaixo de [warnRate]
/// a turma errou mais do que acertou.
const double goodRate = 70;
const double warnRate = 50;

/// Acima disso o conteudo e dominado, e a pergunta entra nos pontos fortes.
const double strongRate = 85;

/// Menos participantes que isso respondendo e sinal de problema de acesso, nao de
/// aprendizado.
const double lowParticipationRate = 80;

/// Pergunta com menos respostas que isso nao serve de sinal.
const int minAnswersForSignal = 3;

enum Verdict { semDados, bom, atencao, critico }

extension VerdictText on Verdict {
  String get label => switch (this) {
        Verdict.bom => 'Bom desempenho',
        Verdict.atencao => 'Atenção',
        Verdict.critico => 'Abaixo do esperado',
        Verdict.semDados => 'Sem dados',
      };
}

/// Quantos alunos caem em cada faixa de acerto.
class PerformanceBand {
  final String label;
  final int count;

  /// `bom`, `atencao`, `critico` ou `neutro`: o que a faixa significa, para a cor.
  final String tone;

  const PerformanceBand(this.label, this.count, this.tone);
}

/// Uma pergunta resumida para o executivo.
class QuestionHighlight {
  final int number;
  final String enunciado;
  final double percentual;
  final String? maisMarcadaErrada;

  const QuestionHighlight({
    required this.number,
    required this.enunciado,
    required this.percentual,
    this.maisMarcadaErrada,
  });
}

class ExecutiveSummary {
  final Verdict verdict;
  final String headline;

  /// % de quem entrou que respondeu ao menos uma pergunta.
  final double participation;
  final List<PerformanceBand> bands;
  final List<QuestionHighlight> weakest;
  final List<QuestionHighlight> strongest;
  final List<String> findings;
  final List<String> recommendations;

  /// O que o numero nao diz.
  final String caveat;

  const ExecutiveSummary({
    required this.verdict,
    required this.headline,
    required this.participation,
    required this.bands,
    required this.weakest,
    required this.strongest,
    required this.findings,
    required this.recommendations,
    required this.caveat,
  });
}

String _clip(String text, int limit) {
  final clean = text.replaceAll(RegExp(r'\s+'), ' ').trim();
  return clean.length <= limit
      ? clean
      : '${clean.substring(0, limit - 1).trimRight()}…';
}

/// Enunciado para dentro de uma frase: sem a pontuacao final, que colava "?;" e "?." no
/// meio do texto.
String _inline(String text, int limit) =>
    _clip(text, limit).replaceAll(RegExp(r"[s?.!:;,]+$"), "");

String _plural(int n, String one, String many) => n == 1 ? one : many;

const String _caveat =
    'Resultado de um único quiz, uma amostra da aula. Cada participante é um '
    'navegador identificado pelo nome digitado, não uma matrícula. Taxa de acerto = '
    'acertos sobre respostas dadas, só nas perguntas aplicadas.';

/// Monta o resumo a partir do relatorio. Nao refaz conta: usa o que o servidor
/// calculou.
ExecutiveSummary buildExecutiveSummary(QuizReport report) {
  if (report.semDados) {
    return const ExecutiveSummary(
      verdict: Verdict.semDados,
      headline: 'Ninguém participou deste quiz ainda.',
      participation: 0,
      bands: [],
      weakest: [],
      strongest: [],
      findings: [],
      recommendations: [],
      caveat: _caveat,
    );
  }

  final participation = report.participantes == 0
      ? 0.0
      : report.responderam / report.participantes * 100;

  final verdict = report.responderam == 0
      ? Verdict.semDados
      : report.taxaAcerto >= goodRate
          ? Verdict.bom
          : report.taxaAcerto >= warnRate
              ? Verdict.atencao
              : Verdict.critico;

  final headline = switch (verdict) {
    Verdict.bom => 'A turma foi bem: ${formatPercent(report.taxaAcerto)} de acerto, '
        'com ${report.responderam} de ${report.participantes} participantes respondendo.',
    Verdict.atencao =>
      'Desempenho intermediário: ${formatPercent(report.taxaAcerto)} de acerto. '
          'Há pontos da aula a reforçar.',
    Verdict.critico =>
      'Desempenho abaixo do esperado: ${formatPercent(report.taxaAcerto)} de acerto. '
          'O conteúdo precisa ser retomado.',
    Verdict.semDados =>
      'Os ${report.participantes} participantes entraram, mas ninguém respondeu.',
  };

  // --- faixas ------------------------------------------------------------------
  final responded = report.alunos.where((s) => !s.semNenhumaResposta).toList();
  int inRange(double min, double max) =>
      responded.where((s) => s.percentual >= min && s.percentual < max).length;
  final bands = [
    PerformanceBand('90% ou mais', inRange(90, 101), 'bom'),
    PerformanceBand('70% a 89%', inRange(70, 90), 'bom'),
    PerformanceBand('50% a 69%', inRange(50, 70), 'atencao'),
    PerformanceBand('Menos de 50%', inRange(0, 50), 'critico'),
    PerformanceBand('Não responderam', report.semRespostaNenhuma, 'neutro'),
  ];
  final below50 = bands[3].count;

  // --- perguntas ----------------------------------------------------------------
  QuestionHighlight highlight(ReportQuestion q) => QuestionHighlight(
        number: q.indice + 1,
        enunciado: q.enunciado,
        percentual: q.percentual,
        maisMarcadaErrada: q.maisEscolhidaErrada == null
            ? null
            : '${q.maisEscolhidaErrada!.label}'
                '${q.maisEscolhidaErrada!.texto.isEmpty ? '' : ') ${_clip(q.maisEscolhidaErrada!.texto, 36)}'}',
      );

  // Os pontos fracos sao os que o servidor ja apontou (mesma regra da tela do
  // relatorio): dois numeros diferentes para "pergunta fraca" confundiriam.
  final weakest = [
    for (final item in report.perguntasEmAtencao.take(3))
      QuestionHighlight(
        number: item.indice + 1,
        enunciado: item.enunciado,
        percentual: item.percentual,
        maisMarcadaErrada: item.maisEscolhidaErrada == null
            ? null
            : '${item.maisEscolhidaErrada!.label}'
                '${item.maisEscolhidaErrada!.texto.isEmpty ? '' : ') ${_clip(item.maisEscolhidaErrada!.texto, 36)}'}',
      ),
  ];

  final strongest = (report.aplicadas
          .where((q) => q.respostas >= minAnswersForSignal && q.percentual >= strongRate)
          .toList()
        ..sort((a, b) => b.percentual.compareTo(a.percentual)))
      .take(3)
      .map(highlight)
      .toList();

  // --- constatacoes ---------------------------------------------------------------
  final findings = <String>[
    '${report.responderam} de ${report.participantes} participantes responderam '
        '(${formatPercent(participation)}).'
        '${report.semRespostaNenhuma > 0 ? ' ${report.semRespostaNenhuma} ${_plural(report.semRespostaNenhuma, 'entrou', 'entraram')} e não ${_plural(report.semRespostaNenhuma, 'respondeu', 'responderam')}.' : ''}',
    if (strongest.isNotEmpty)
      'Conteúdo dominado: ${strongest.map((q) => 'P${q.number} (${formatPercent(q.percentual)})').join(', ')}.',
    for (final q in weakest)
      'P${q.number} teve só ${formatPercent(q.percentual)} de acerto: '
          '${_inline(q.enunciado, 90)}'
          '${q.maisMarcadaErrada == null ? '' : ' — a turma mais marcou ${q.maisMarcadaErrada}'}.',
    if (below50 > 0 && responded.isNotEmpty)
      '$below50 ${_plural(below50, 'aluno', 'alunos')} '
          '(${formatPercent(below50 / responded.length * 100)} de quem respondeu) '
          '${_plural(below50, 'acertou', 'acertaram')} menos da metade.',
  ];

  // --- recomendacoes ----------------------------------------------------------------
  final recommendations = <String>[
    if (weakest.isNotEmpty)
      'Retomar em aula: ${weakest.map((q) => 'P${q.number} — ${_inline(q.enunciado, 60)}').join('; ')}.',
    if (below50 > 0)
      'Oferecer reforço a $below50 ${_plural(below50, 'aluno', 'alunos')} '
          'que ${_plural(below50, 'acertou', 'acertaram')} menos da metade.',
    if (report.participantes > 0 && participation < lowParticipationRate)
      'Verificar o acesso: ${report.semRespostaNenhuma} '
          '${_plural(report.semRespostaNenhuma, 'participante não respondeu', 'participantes não responderam')} '
          '— QR Code, rede ou tempo curto demais?',
    if (report.perguntasAplicadas < report.totalQuestoes)
      'O quiz foi encerrado com ${report.perguntasAplicadas} de '
          '${report.totalQuestoes} perguntas aplicadas; o resultado cobre só essa parte.',
    if (verdict == Verdict.bom && report.taxaAcerto >= strongRate && weakest.isEmpty)
      'Turma pronta para avançar; considerar perguntas mais difíceis no próximo quiz.',
  ];
  if (recommendations.isEmpty) {
    recommendations.add('Sem ação específica: o desempenho está dentro do esperado.');
  }

  return ExecutiveSummary(
    verdict: verdict,
    headline: headline,
    participation: participation,
    bands: bands,
    weakest: weakest,
    strongest: strongest,
    findings: findings,
    recommendations: recommendations,
    caveat: _caveat,
  );
}

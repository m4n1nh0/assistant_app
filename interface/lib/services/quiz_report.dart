/// Relatorio de desempenho de um quiz: o que o servidor devolve, tipado, mais os
/// formatadores e o CSV.
///
/// O servidor faz as contas (perguntas aplicadas, quem entrou e nao respondeu,
/// pontos de atencao); aqui so se le o resultado e se apresenta - na tela, no PDF
/// e na planilha - sem refazer conta nenhuma, para os tres mostrarem o mesmo
/// numero.
library;

int _int(Object? value, [int fallback = 0]) =>
    value is num ? value.toInt() : int.tryParse('${value ?? ''}') ?? fallback;

double _double(Object? value) =>
    value is num ? value.toDouble() : double.tryParse('${value ?? ''}') ?? 0;

String _str(Object? value) => value?.toString() ?? '';

List<Map<String, dynamic>> _maps(Object? value) => value is List
    ? value
        .whereType<Map>()
        .map((item) => item.map((k, v) => MapEntry(k.toString(), v)))
        .toList()
    : const [];

/// Uma alternativa e quantos alunos a escolheram.
class ReportOption {
  final String label;
  final String texto;
  final int quantidade;
  final bool correta;

  const ReportOption({
    required this.label,
    required this.texto,
    this.quantidade = 0,
    this.correta = false,
  });

  factory ReportOption.fromJson(Map<String, dynamic> json) => ReportOption(
        label: _str(json['label']),
        texto: _str(json['texto']),
        quantidade: _int(json['quantidade']),
        correta: json['correta'] == true,
      );
}

/// O que um aluno fez numa pergunta aplicada.
class ReportAnswer {
  final int indice;

  /// `acertou`, `errou`, `pulou` ou `sem_resposta`.
  final String status;
  final String resposta;
  final int pontos;
  final int? tempoMs;

  const ReportAnswer({
    required this.indice,
    required this.status,
    this.resposta = '',
    this.pontos = 0,
    this.tempoMs,
  });

  factory ReportAnswer.fromJson(Map<String, dynamic> json) => ReportAnswer(
        indice: _int(json['indice']),
        status: _str(json['status']),
        resposta: _str(json['resposta']),
        pontos: _int(json['pontos']),
        tempoMs: json['tempo_ms'] == null ? null : _int(json['tempo_ms']),
      );

  bool get acertou => status == 'acertou';
}

class ReportStudent {
  final String nome;
  final int posicao;
  final int pontos;
  final int acertos;
  final int erros;
  final int puladas;
  final int semResposta;
  final int respondidas;
  final double percentual;
  final int? tempoMedioMs;
  final List<ReportAnswer> porPergunta;

  const ReportStudent({
    required this.nome,
    this.posicao = 0,
    this.pontos = 0,
    this.acertos = 0,
    this.erros = 0,
    this.puladas = 0,
    this.semResposta = 0,
    this.respondidas = 0,
    this.percentual = 0,
    this.tempoMedioMs,
    this.porPergunta = const [],
  });

  factory ReportStudent.fromJson(Map<String, dynamic> json) => ReportStudent(
        nome: _str(json['nome']),
        posicao: _int(json['posicao']),
        pontos: _int(json['pontos']),
        acertos: _int(json['acertos']),
        erros: _int(json['erros']),
        puladas: _int(json['puladas']),
        semResposta: _int(json['sem_resposta']),
        respondidas: _int(json['respondidas']),
        percentual: _double(json['percentual']),
        tempoMedioMs:
            json['tempo_medio_ms'] == null ? null : _int(json['tempo_medio_ms']),
        porPergunta:
            _maps(json['por_pergunta']).map(ReportAnswer.fromJson).toList(),
      );

  /// Entrou e nao respondeu nada.
  bool get semNenhumaResposta => respondidas == 0;
}

class ReportQuestion {
  final int indice;
  final bool aplicada;
  final String enunciado;
  final String correta;
  final int respostas;
  final int acertos;
  final int erros;
  final int semResposta;
  final double percentual;
  final int? tempoMedioMs;
  final List<ReportOption> distribuicao;
  final ReportOption? maisEscolhidaErrada;

  const ReportQuestion({
    required this.indice,
    required this.enunciado,
    this.aplicada = true,
    this.correta = '',
    this.respostas = 0,
    this.acertos = 0,
    this.erros = 0,
    this.semResposta = 0,
    this.percentual = 0,
    this.tempoMedioMs,
    this.distribuicao = const [],
    this.maisEscolhidaErrada,
  });

  factory ReportQuestion.fromJson(Map<String, dynamic> json) => ReportQuestion(
        indice: _int(json['indice']),
        aplicada: json['aplicada'] != false,
        enunciado: _str(json['enunciado']),
        correta: _str(json['correta']),
        respostas: _int(json['respostas']),
        acertos: _int(json['acertos']),
        erros: _int(json['erros']),
        semResposta: _int(json['sem_resposta']),
        percentual: _double(json['percentual']),
        tempoMedioMs:
            json['tempo_medio_ms'] == null ? null : _int(json['tempo_medio_ms']),
        distribuicao:
            _maps(json['distribuicao']).map(ReportOption.fromJson).toList(),
        maisEscolhidaErrada: json['mais_escolhida_errada'] is Map
            ? ReportOption.fromJson(Map<String, dynamic>.from(
                json['mais_escolhida_errada'] as Map))
            : null,
      );

  /// Texto da alternativa com a letra, como o aluno a viu.
  String textoDe(String label) {
    for (final option in distribuicao) {
      if (option.label == label) return option.texto;
    }
    return '';
  }
}

class ReportAttentionQuestion {
  final int indice;
  final String enunciado;
  final double percentual;
  final int respostas;
  final ReportOption? maisEscolhidaErrada;

  const ReportAttentionQuestion({
    required this.indice,
    required this.enunciado,
    required this.percentual,
    this.respostas = 0,
    this.maisEscolhidaErrada,
  });

  factory ReportAttentionQuestion.fromJson(Map<String, dynamic> json) =>
      ReportAttentionQuestion(
        indice: _int(json['indice']),
        enunciado: _str(json['enunciado']),
        percentual: _double(json['percentual']),
        respostas: _int(json['respostas']),
        maisEscolhidaErrada: json['mais_escolhida_errada'] is Map
            ? ReportOption.fromJson(Map<String, dynamic>.from(
                json['mais_escolhida_errada'] as Map))
            : null,
      );
}

class QuizReport {
  final String id;
  final String titulo;
  final String status;
  final int totalQuestoes;
  final int perguntasAplicadas;
  final DateTime? criadoEm;
  final DateTime? encerradoEm;
  final List<String> disciplinas;
  final List<String> fontes;

  final int participantes;
  final int responderam;
  final int semRespostaNenhuma;
  final int acertos;
  final int erros;
  final int puladas;
  final double taxaAcerto;
  final int pontosMedios;
  final int? tempoMedioMs;

  final List<ReportStudent> alunos;
  final List<ReportQuestion> perguntas;
  final List<ReportAttentionQuestion> perguntasEmAtencao;
  final List<String> alunosComDificuldade;
  final List<String> alunosSemResposta;

  const QuizReport({
    required this.id,
    required this.titulo,
    this.status = 'open',
    this.totalQuestoes = 0,
    this.perguntasAplicadas = 0,
    this.criadoEm,
    this.encerradoEm,
    this.disciplinas = const [],
    this.fontes = const [],
    this.participantes = 0,
    this.responderam = 0,
    this.semRespostaNenhuma = 0,
    this.acertos = 0,
    this.erros = 0,
    this.puladas = 0,
    this.taxaAcerto = 0,
    this.pontosMedios = 0,
    this.tempoMedioMs,
    this.alunos = const [],
    this.perguntas = const [],
    this.perguntasEmAtencao = const [],
    this.alunosComDificuldade = const [],
    this.alunosSemResposta = const [],
  });

  factory QuizReport.fromJson(Map<String, dynamic> json) {
    final quiz = Map<String, dynamic>.from(json['quiz'] as Map? ?? const {});
    final resumo = Map<String, dynamic>.from(json['resumo'] as Map? ?? const {});
    final atencao =
        Map<String, dynamic>.from(json['atencao'] as Map? ?? const {});
    List<String> strings(Object? value) => value is List
        ? value.map((item) => item.toString()).where((s) => s.isNotEmpty).toList()
        : const [];

    return QuizReport(
      id: _str(quiz['id']),
      titulo: _str(quiz['titulo']),
      status: _str(quiz['status']).isEmpty ? 'open' : _str(quiz['status']),
      totalQuestoes: _int(quiz['total_questoes']),
      perguntasAplicadas: _int(quiz['perguntas_aplicadas']),
      criadoEm: DateTime.tryParse(_str(quiz['criado_em']))?.toLocal(),
      encerradoEm: DateTime.tryParse(_str(quiz['encerrado_em']))?.toLocal(),
      disciplinas: strings(quiz['disciplinas']),
      fontes: strings(quiz['fontes']),
      participantes: _int(resumo['participantes']),
      responderam: _int(resumo['responderam']),
      semRespostaNenhuma: _int(resumo['sem_resposta_nenhuma']),
      acertos: _int(resumo['acertos']),
      erros: _int(resumo['erros']),
      puladas: _int(resumo['puladas']),
      taxaAcerto: _double(resumo['taxa_acerto']),
      pontosMedios: _int(resumo['pontos_medios']),
      tempoMedioMs:
          resumo['tempo_medio_ms'] == null ? null : _int(resumo['tempo_medio_ms']),
      alunos: _maps(json['alunos']).map(ReportStudent.fromJson).toList(),
      perguntas: _maps(json['perguntas']).map(ReportQuestion.fromJson).toList(),
      perguntasEmAtencao: _maps(atencao['perguntas'])
          .map(ReportAttentionQuestion.fromJson)
          .toList(),
      alunosComDificuldade: strings(atencao['alunos_com_dificuldade']),
      alunosSemResposta: strings(atencao['alunos_sem_resposta']),
    );
  }

  /// So as perguntas que a turma chegou a ver.
  List<ReportQuestion> get aplicadas =>
      perguntas.where((question) => question.aplicada).toList();

  bool get semDados => participantes == 0;
}

// --- formatacao ---------------------------------------------------------------

/// "66,7%", e "100%" sem casa decimal inutil.
String formatPercent(double value) {
  final rounded = value.roundToDouble() == value
      ? value.toStringAsFixed(0)
      : value.toStringAsFixed(1).replaceAll('.', ',');
  return '$rounded%';
}

/// "3,2 s", ou "—" quando nao ha tempo.
String formatSeconds(int? milliseconds) {
  if (milliseconds == null) return '—';
  return '${(milliseconds / 1000).toStringAsFixed(1).replaceAll('.', ',')} s';
}

/// Texto de uma linha para o aluno numa pergunta: "A ✓", "B ✗", "pulou", "—".
String answerCell(ReportAnswer answer) => switch (answer.status) {
      'acertou' => '${answer.resposta} ✓',
      'errou' => '${answer.resposta} ✗',
      'pulou' => 'pulou',
      _ => '—',
    };

// --- CSV ------------------------------------------------------------------------

String _csvField(String value) {
  // Planilha que abre CSV como formula executaria o que comeca com = + - @: o
  // nome do aluno vem de um campo livre, digitado por quem escaneou o QR Code.
  final safe = RegExp(r'^[=+\-@\t\r]').hasMatch(value) ? "'$value" : value;
  return safe.contains(RegExp(r'[";\n\r]'))
      ? '"${safe.replaceAll('"', '""')}"'
      : safe;
}

/// Planilha dos alunos: uma linha por aluno, uma coluna por pergunta aplicada.
///
/// Separador `;`, virgula decimal e BOM no inicio: e o que o Excel em portugues
/// abre sem pedir assistente de importacao e sem estragar os acentos.
String quizReportCsv(QuizReport report) {
  final perguntas = report.aplicadas;
  final header = [
    'Posição',
    'Aluno',
    'Pontos',
    'Acertos',
    'Erros',
    'Puladas',
    'Sem resposta',
    '% de acerto',
    'Tempo médio (s)',
    for (final pergunta in perguntas) 'P${pergunta.indice + 1}',
  ];

  final rows = <List<String>>[header];
  for (final aluno in report.alunos) {
    final byIndex = {for (final item in aluno.porPergunta) item.indice: item};
    rows.add([
      '${aluno.posicao}',
      aluno.nome,
      '${aluno.pontos}',
      '${aluno.acertos}',
      '${aluno.erros}',
      '${aluno.puladas}',
      '${aluno.semResposta}',
      aluno.percentual.toStringAsFixed(1).replaceAll('.', ','),
      aluno.tempoMedioMs == null
          ? ''
          : (aluno.tempoMedioMs! / 1000).toStringAsFixed(1).replaceAll('.', ','),
      for (final pergunta in perguntas)
        byIndex[pergunta.indice] == null
            ? '—'
            : answerCell(byIndex[pergunta.indice]!),
    ]);
  }

  // Linha final com o gabarito: a planilha sozinha ja diz o que era certo.
  rows.add([
    '',
    'Gabarito',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    for (final pergunta in perguntas) pergunta.correta,
  ]);

  final csv = rows.map((row) => row.map(_csvField).join(';')).join('\r\n');
  return '\u{FEFF}$csv\r\n';
}

/// Nome sugerido no dialogo de salvar.
String quizFilename(String title, {String suffix = '', String extension = 'pdf'}) {
  final slug = '$title $suffix'
      .toLowerCase()
      .replaceAll(RegExp(r'[áàâãä]'), 'a')
      .replaceAll(RegExp(r'[éèêë]'), 'e')
      .replaceAll(RegExp(r'[íìîï]'), 'i')
      .replaceAll(RegExp(r'[óòôõö]'), 'o')
      .replaceAll(RegExp(r'[úùûü]'), 'u')
      .replaceAll('ç', 'c')
      .replaceAll(RegExp(r'[^a-z0-9]+'), '-')
      .replaceAll(RegExp(r'^-+|-+$'), '');
  return '${slug.isEmpty ? 'quiz' : slug}.$extension';
}

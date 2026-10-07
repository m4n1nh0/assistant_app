/// Resumo conjunto de várias gravações escolhidas no histórico.
///
/// Pensado para o dia de apresentações de grupo (uma seção por grupo e a comparação
/// entre eles), e vale também para aulas, palestras e reuniões.
library;

/// Uma gravação que entrou no resumo, e de onde veio o texto dela.
class CombinedItem {
  final String id;
  final String label;
  final String kind;
  final String groupName;

  /// `resumo` (o que a gravação já tinha), `gerado` (resumido agora, sem gravar) ou
  /// `transcricao` (a transcrição cortada, quando resumir falhou).
  final String source;

  const CombinedItem({
    required this.id,
    required this.label,
    this.kind = 'aula',
    this.groupName = '',
    this.source = 'resumo',
  });

  factory CombinedItem.fromJson(Map<String, dynamic> json) => CombinedItem(
        id: '${json['id']}',
        label: json['label']?.toString() ?? '',
        kind: json['kind']?.toString() ?? 'aula',
        groupName: json['group_name']?.toString() ?? '',
        source: json['source']?.toString() ?? 'resumo',
      );

  /// Como a fonte aparece na lista de gravações incluídas.
  String get sourceLabel => switch (source) {
        'gerado' => 'resumida agora, a partir da transcrição',
        'transcricao' => 'a partir da transcrição (não deu para resumir)',
        _ => 'a partir do resumo que ela já tinha',
      };
}

/// Gravação que ficou de fora, e por quê.
class CombinedSkipped {
  final String id;
  final String label;
  final String reason;

  const CombinedSkipped({required this.id, required this.label, this.reason = ''});

  factory CombinedSkipped.fromJson(Map<String, dynamic> json) => CombinedSkipped(
        id: '${json['id']}',
        label: json['label']?.toString() ?? '',
        reason: json['reason']?.toString() ?? '',
      );
}

class CombinedSummary {
  final String summary;
  final String llm;
  final String style;
  final String title;
  final String subtitle;

  /// `selecao-apresentacao` quando todas são apresentações de grupo; senão `selecao`.
  final String kind;
  final List<CombinedItem> items;
  final List<CombinedSkipped> skipped;

  const CombinedSummary({
    required this.summary,
    this.llm = '',
    this.style = 'standard',
    this.title = '',
    this.subtitle = '',
    this.kind = 'selecao',
    this.items = const [],
    this.skipped = const [],
  });

  factory CombinedSummary.fromJson(Map<String, dynamic> json) => CombinedSummary(
        summary: json['summary']?.toString() ?? '',
        llm: json['llm']?.toString() ?? '',
        style: json['style']?.toString() ?? 'standard',
        title: json['title']?.toString() ?? '',
        subtitle: json['subtitle']?.toString() ?? '',
        kind: json['kind']?.toString() ?? 'selecao',
        items: [
          for (final item in (json['items'] as List?) ?? const [])
            CombinedItem.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
        skipped: [
          for (final item in (json['skipped'] as List?) ?? const [])
            CombinedSkipped.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
      );

  /// Todas as gravações são do mesmo tipo, ou `null` se há mistura.
  String? get commonKind {
    final kinds = items.map((item) => item.kind).toSet();
    return kinds.length == 1 ? kinds.single : null;
  }

  /// Etiqueta do topo do PDF: "RESUMO DAS APRESENTAÇÕES", "RESUMO DAS AULAS"...
  String get heading => combinedHeading(commonKind);
}

/// Etiqueta do resumo conjunto conforme o tipo (`null`: gravações de tipos misturados).
String combinedHeading(String? kind) => switch (kind) {
      'apresentacao' => 'RESUMO DAS APRESENTAÇÕES',
      'palestra' => 'RESUMO DAS PALESTRAS',
      'reuniao' => 'RESUMO DAS REUNIÕES',
      'aula' => 'RESUMO DAS AULAS',
      _ => 'RESUMO DAS GRAVAÇÕES',
    };

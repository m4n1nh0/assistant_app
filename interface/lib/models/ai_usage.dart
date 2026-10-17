/// Consumo de IA e preços de token, como o backend devolve em `/observability/usage` e
/// `/observability/prices`.
///
/// Os tokens são os que o provedor informou. O custo é uma **estimativa** (preço de tabela), e
/// [AiUsageTotal.unpricedCalls] diz quantas chamadas ficaram sem preço, para um total que parece
/// completo não enganar.
library;

int _int(dynamic value) => value is num ? value.toInt() : int.tryParse('$value') ?? 0;

double _double(dynamic value) =>
    value is num ? value.toDouble() : double.tryParse('$value') ?? 0.0;

class AiUsageTotal {
  final int calls;
  final int errors;
  final int unpricedCalls;
  final int inputTokens;
  final int outputTokens;
  final int cachedTokens;
  final double costUsd;

  const AiUsageTotal({
    this.calls = 0,
    this.errors = 0,
    this.unpricedCalls = 0,
    this.inputTokens = 0,
    this.outputTokens = 0,
    this.cachedTokens = 0,
    this.costUsd = 0,
  });

  factory AiUsageTotal.fromJson(Map<String, dynamic> json) => AiUsageTotal(
        calls: _int(json['calls']),
        errors: _int(json['errors']),
        unpricedCalls: _int(json['unpriced_calls']),
        inputTokens: _int(json['input_tokens']),
        outputTokens: _int(json['output_tokens']),
        cachedTokens: _int(json['cached_tokens']),
        costUsd: _double(json['cost_usd']),
      );

  int get tokens => inputTokens + outputTokens;
}

class AiUsageGroup extends AiUsageTotal {
  /// Chave do grupo (provedor, `provedor/modelo`, dia ou o id do cliente).
  final String key;

  /// Como aparece na tela: o nome do cliente, e não o id.
  final String label;

  const AiUsageGroup({
    required this.key,
    required this.label,
    super.calls,
    super.errors,
    super.unpricedCalls,
    super.inputTokens,
    super.outputTokens,
    super.cachedTokens,
    super.costUsd,
  });

  factory AiUsageGroup.fromJson(Map<String, dynamic> json) {
    final total = AiUsageTotal.fromJson(json);
    return AiUsageGroup(
      key: json['key']?.toString() ?? '',
      label: json['label']?.toString() ?? json['key']?.toString() ?? '',
      calls: total.calls,
      errors: total.errors,
      unpricedCalls: total.unpricedCalls,
      inputTokens: total.inputTokens,
      outputTokens: total.outputTokens,
      cachedTokens: total.cachedTokens,
      costUsd: total.costUsd,
    );
  }
}

class AiUsageSummary {
  final int days;
  final String groupBy;

  /// `mine` (a conta) ou `all` (todos os clientes, só administrador).
  final String scope;
  final AiUsageTotal total;
  final List<AiUsageGroup> groups;

  const AiUsageSummary({
    required this.days,
    required this.groupBy,
    required this.scope,
    required this.total,
    required this.groups,
  });

  factory AiUsageSummary.fromJson(Map<String, dynamic> json) => AiUsageSummary(
        days: _int(json['days']),
        groupBy: json['group_by']?.toString() ?? 'provider',
        scope: json['scope']?.toString() ?? 'mine',
        total: AiUsageTotal.fromJson(Map<String, dynamic>.from(json['total'] as Map? ?? {})),
        groups: [
          for (final item in (json['groups'] as List? ?? const []))
            AiUsageGroup.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
      );
}

/// Preço de um modelo em dólar por milhão de tokens. `model` vazio é o padrão do provedor.
class AiPrice {
  final String id;
  final String provider;
  final String model;
  final double inputPerMtok;
  final double outputPerMtok;
  final double? cachedInputPerMtok;

  /// `manual` (digitado, a sincronização nunca sobrescreve) ou `litellm` (importado).
  final String source;

  const AiPrice({
    required this.id,
    required this.provider,
    this.model = '',
    this.inputPerMtok = 0,
    this.outputPerMtok = 0,
    this.cachedInputPerMtok,
    this.source = 'manual',
  });

  factory AiPrice.fromJson(Map<String, dynamic> json) => AiPrice(
        id: '${json['id']}',
        provider: json['provider']?.toString() ?? '',
        model: json['model']?.toString() ?? '',
        inputPerMtok: _double(json['input_per_mtok']),
        outputPerMtok: _double(json['output_per_mtok']),
        cachedInputPerMtok: json['cached_input_per_mtok'] == null
            ? null
            : _double(json['cached_input_per_mtok']),
        source: json['source']?.toString() ?? 'manual',
      );

  bool get isManual => source == 'manual';
  bool get isFree => inputPerMtok == 0 && outputPerMtok == 0;
  String get modelLabel => model.isEmpty ? 'padrão do provedor' : model;
}

class AiPriceList {
  final List<String> providers;
  final List<AiPrice> prices;

  const AiPriceList({this.providers = const [], this.prices = const []});

  factory AiPriceList.fromJson(Map<String, dynamic> json) => AiPriceList(
        providers: [for (final p in (json['providers'] as List? ?? const [])) '$p'],
        prices: [
          for (final item in (json['prices'] as List? ?? const []))
            AiPrice.fromJson(Map<String, dynamic>.from(item as Map)),
        ],
      );
}

/// Resultado de importar a tabela pública de preços.
class AiPriceSync {
  final int modelsInSource;
  final int added;
  final int updated;
  final int keptManual;

  const AiPriceSync({
    this.modelsInSource = 0,
    this.added = 0,
    this.updated = 0,
    this.keptManual = 0,
  });

  factory AiPriceSync.fromJson(Map<String, dynamic> json) => AiPriceSync(
        modelsInSource: _int(json['models_in_source']),
        added: _int(json['added']),
        updated: _int(json['updated']),
        keptManual: _int(json['kept_manual']),
      );
}

/// Dólar com a precisão que o valor pede: centavos para somas grandes e mais casas para o
/// custo de uma chamada, que é de frações de centavo.
String formatUsd(double value) {
  if (value == 0) return 'US\$ 0,00';
  final digits = value >= 1 ? 2 : (value >= 0.01 ? 3 : 4);
  return 'US\$ ${value.toStringAsFixed(digits).replaceAll('.', ',')}';
}

/// Inteiro com separador de milhar (ponto): `1234567` vira `1.234.567`.
String formatCount(int value) {
  final text = value.abs().toString();
  final out = StringBuffer(value < 0 ? '-' : '');
  for (var i = 0; i < text.length; i++) {
    if (i > 0 && (text.length - i) % 3 == 0) out.write('.');
    out.write(text[i]);
  }
  return out.toString();
}

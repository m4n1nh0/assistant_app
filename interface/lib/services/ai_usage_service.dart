/// Cliente do consumo de IA e da tabela de preços (`/observability/usage` e `/observability/prices`).
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/ai_usage.dart';
import 'api_service.dart';
import 'education_service.dart' show EducationException;

class AiUsageService {
  final ApiService _api;

  AiUsageService(this._api);

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_api.token != null) 'Authorization': 'Bearer ${_api.token}',
      };

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('${_api.baseUrl}/observability$path').replace(queryParameters: query);

  /// Devolve o corpo JSON, ou levanta com o `detail` que o servidor mandou.
  dynamic _decode(http.Response response) {
    if (response.statusCode >= 400) {
      var message = 'Falha ${response.statusCode}';
      try {
        final body = jsonDecode(response.body);
        if (body is Map && body['detail'] != null) message = '${body['detail']}';
      } catch (_) {}
      throw EducationException(message);
    }
    if (response.body.isEmpty) return null;
    return jsonDecode(response.body);
  }

  /// Consumo dos últimos [days] dias. [scopeAll] soma todos os clientes (só administrador).
  Future<AiUsageSummary> usage({
    int days = 30,
    String groupBy = 'provider',
    bool scopeAll = false,
  }) async {
    final response = await http.get(
      _uri('/usage', {
        'days': '$days',
        'group_by': groupBy,
        'scope': scopeAll ? 'all' : 'mine',
      }),
      headers: _headers,
    );
    return AiUsageSummary.fromJson(Map<String, dynamic>.from(_decode(response) as Map));
  }

  Future<AiPriceList> prices({String query = '', String provider = ''}) async {
    final response = await http.get(
      _uri('/prices', {
        if (query.trim().isNotEmpty) 'q': query.trim(),
        if (provider.isNotEmpty) 'provider': provider,
      }),
      headers: _headers,
    );
    return AiPriceList.fromJson(Map<String, dynamic>.from(_decode(response) as Map));
  }

  /// Grava um preço à mão (administrador). `model` vazio é o padrão do provedor.
  Future<AiPrice> savePrice({
    required String provider,
    String model = '',
    required double inputPerMtok,
    required double outputPerMtok,
    double? cachedInputPerMtok,
  }) async {
    final response = await http.put(
      _uri('/prices'),
      headers: _headers,
      body: jsonEncode({
        'provider': provider,
        'model': model,
        'input_per_mtok': inputPerMtok,
        'output_per_mtok': outputPerMtok,
        if (cachedInputPerMtok != null) 'cached_input_per_mtok': cachedInputPerMtok,
      }),
    );
    return AiPrice.fromJson(Map<String, dynamic>.from(_decode(response) as Map));
  }

  Future<void> deletePrice(String id) async {
    _decode(await http.delete(_uri('/prices/$id'), headers: _headers));
  }

  /// Importa a tabela pública de preços (administrador), sem tocar nos preços digitados à mão.
  Future<AiPriceSync> syncPrices() async {
    final response = await http.post(_uri('/prices/sync'), headers: _headers);
    return AiPriceSync.fromJson(Map<String, dynamic>.from(_decode(response) as Map));
  }
}

final aiUsage = AiUsageService(api);

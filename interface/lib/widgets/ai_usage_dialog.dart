/// Consumo de IA e preços de token.
///
/// **Consumo:** quantas chamadas, tokens e quanto custou (estimado) no período, por provedor, modelo
/// ou dia. A conta vê o próprio consumo; o administrador pode somar todos os clientes e ver quanto
/// cada um usou.
///
/// **Preços:** a tabela que calcula o custo. Cada cliente escolhe o próprio modelo, então o preço
/// é por modelo e editável aqui; o administrador também importa a tabela pública da internet,
/// que nunca sobrescreve um preço digitado à mão.
///
/// Os tokens vêm do provedor e são exatos. O custo é uma estimativa, e a tela diz quando há
/// chamadas sem preço, para o total não parecer completo quando não é.
library;

import 'package:flutter/material.dart';

import '../models/ai_usage.dart';
import '../services/ai_usage_service.dart';
import '../utils/theme.dart';

class AiUsageDialog extends StatefulWidget {
  final bool isAdmin;

  /// Trocam serviço nos testes.
  final AiUsageService? service;

  const AiUsageDialog({super.key, required this.isAdmin, this.service});

  static Future<void> show(BuildContext context, {required bool isAdmin}) => showDialog<void>(
        context: context,
        builder: (_) => AiUsageDialog(isAdmin: isAdmin),
      );

  @override
  State<AiUsageDialog> createState() => _AiUsageDialogState();
}

class _AiUsageDialogState extends State<AiUsageDialog> {
  AiUsageService get _service => widget.service ?? aiUsage;

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      insetPadding: const EdgeInsets.all(20),
      child: SizedBox(
        width: 820,
        height: 640,
        child: DefaultTabController(
          length: 2,
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 14, 8, 0),
              child: Row(children: [
                const Expanded(
                  child: Text('Consumo e preços de IA',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                ),
                IconButton(
                  key: const Key('ai-usage-close'),
                  tooltip: 'Fechar',
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: () => Navigator.pop(context),
                ),
              ]),
            ),
            const TabBar(tabs: [Tab(text: 'CONSUMO'), Tab(text: 'PREÇOS')]),
            Expanded(
              child: TabBarView(children: [
                _UsageTab(service: _service, isAdmin: widget.isAdmin),
                _PricesTab(service: _service, isAdmin: widget.isAdmin),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

// --- consumo -----------------------------------------------------------------------------------

const _groupLabels = {
  'provider': 'Provedor',
  'model': 'Modelo',
  'day': 'Dia',
  'tenant': 'Cliente',
};

class _UsageTab extends StatefulWidget {
  final AiUsageService service;
  final bool isAdmin;

  const _UsageTab({required this.service, required this.isAdmin});

  @override
  State<_UsageTab> createState() => _UsageTabState();
}

class _UsageTabState extends State<_UsageTab> {
  int _days = 30;
  String _groupBy = 'provider';
  bool _scopeAll = false;
  bool _loading = true;
  String _error = '';
  AiUsageSummary? _data;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final data = await widget.service
          .usage(days: _days, groupBy: _groupBy, scopeAll: _scopeAll);
      if (mounted) setState(() => _data = data);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<String> get _groups => [
        'provider',
        'model',
        'day',
        if (widget.isAdmin && _scopeAll) 'tenant',
      ];

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Wrap(spacing: 14, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        DropdownButton<int>(
          key: const Key('usage-days'),
          value: _days,
          items: const [
            DropdownMenuItem(value: 7, child: Text('Últimos 7 dias')),
            DropdownMenuItem(value: 30, child: Text('Últimos 30 dias')),
            DropdownMenuItem(value: 90, child: Text('Últimos 90 dias')),
          ],
          onChanged: (value) {
            if (value == null) return;
            _days = value;
            _load();
          },
        ),
        DropdownButton<String>(
          key: const Key('usage-group'),
          value: _groupBy,
          items: [
            for (final g in _groups)
              DropdownMenuItem(value: g, child: Text('Por ${_groupLabels[g]!.toLowerCase()}')),
          ],
          onChanged: (value) {
            if (value == null) return;
            _groupBy = value;
            _load();
          },
        ),
        if (widget.isAdmin)
          SegmentedButton<bool>(
            key: const Key('usage-scope'),
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: false, label: Text('MINHA CONTA')),
              ButtonSegment(value: true, label: Text('TODOS OS CLIENTES')),
            ],
            selected: {_scopeAll},
            onSelectionChanged: (value) {
              _scopeAll = value.first;
              if (!_scopeAll && _groupBy == 'tenant') _groupBy = 'provider';
              _load();
            },
          ),
        IconButton(
          tooltip: 'Atualizar',
          icon: const Icon(Icons.refresh, size: 18),
          onPressed: _loading ? null : _load,
        ),
      ]),
      const SizedBox(height: 12),
      if (_error.isNotEmpty)
        Text(_error, style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
      if (_loading && data == null)
        const Padding(
          padding: EdgeInsets.all(30),
          child: Center(child: CircularProgressIndicator()),
        ),
      if (data != null) ..._content(data),
    ]);
  }

  List<Widget> _content(AiUsageSummary data) {
    final total = data.total;
    return [
      Wrap(spacing: 10, runSpacing: 10, children: [
        _Stat('CHAMADAS', formatCount(total.calls)),
        _Stat('TOKENS', formatCount(total.tokens),
            sub: '${formatCount(total.inputTokens)} entrada · ${formatCount(total.outputTokens)} saída'),
        _Stat('CUSTO ESTIMADO', formatUsd(total.costUsd), key: const Key('usage-cost')),
        if (total.errors > 0) _Stat('COM FALHA', formatCount(total.errors)),
      ]),
      if (total.unpricedCalls > 0)
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Container(
            key: const Key('usage-unpriced'),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AssistantTheme.c4.withOpacity(.12),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: AssistantTheme.c4.withOpacity(.4)),
            ),
            child: Text(
              '${formatCount(total.unpricedCalls)} chamada(s) ficaram sem preço ou sem token '
              'informado (agentes conectados, como o Codex e o Claude Code, rodam no seu '
              'computador e não informam). O custo acima não as inclui.',
              style: const TextStyle(fontSize: 11, height: 1.4),
            ),
          ),
        ),
      const SizedBox(height: 14),
      if (data.groups.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 20),
          child: Text(
            'Nenhum consumo registrado neste período. O consumo é gravado a partir das chamadas '
            'feitas depois que esta função entrou no ar.',
            style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted),
          ),
        )
      else
        _GroupTable(groups: data.groups, title: _groupLabels[data.groupBy] ?? 'Grupo'),
      const SizedBox(height: 12),
      const Text(
        'Os tokens são os informados pelo provedor. O custo é uma estimativa, calculada com o '
        'preço de tabela do modelo (aba PREÇOS): o valor real depende do seu contrato.',
        style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted, height: 1.4),
      ),
    ];
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final String? sub;

  const _Stat(this.label, this.value, {this.sub, super.key});

  @override
  Widget build(BuildContext context) => Container(
        constraints: const BoxConstraints(minWidth: 150),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AssistantTheme.border),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label,
              style: const TextStyle(
                  fontSize: 10, letterSpacing: 1, color: AssistantTheme.textMuted)),
          const SizedBox(height: 4),
          Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          if (sub != null)
            Text(sub!, style: const TextStyle(fontSize: 10, color: AssistantTheme.textMuted)),
        ]),
      );
}

class _GroupTable extends StatelessWidget {
  final List<AiUsageGroup> groups;
  final String title;

  const _GroupTable({required this.groups, required this.title});

  @override
  Widget build(BuildContext context) {
    const head = TextStyle(fontSize: 10, letterSpacing: 1, color: AssistantTheme.textMuted);
    Widget cell(String text, {int flex = 2, TextAlign align = TextAlign.right, TextStyle? style}) =>
        Expanded(flex: flex, child: Text(text, textAlign: align, style: style));
    return Column(children: [
      Row(children: [
        cell(title.toUpperCase(), flex: 4, align: TextAlign.left, style: head),
        cell('CHAMADAS', style: head),
        cell('ENTRADA', style: head),
        cell('SAÍDA', style: head),
        cell('CUSTO', style: head),
      ]),
      const Divider(height: 14),
      for (final group in groups)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            Expanded(
              flex: 4,
              child: Text(group.label,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
            ),
            cell(formatCount(group.calls), style: const TextStyle(fontSize: 12)),
            cell(formatCount(group.inputTokens), style: const TextStyle(fontSize: 12)),
            cell(formatCount(group.outputTokens), style: const TextStyle(fontSize: 12)),
            cell(formatUsd(group.costUsd),
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
          ]),
        ),
    ]);
  }
}

// --- preços ------------------------------------------------------------------------------------

class _PricesTab extends StatefulWidget {
  final AiUsageService service;
  final bool isAdmin;

  const _PricesTab({required this.service, required this.isAdmin});

  @override
  State<_PricesTab> createState() => _PricesTabState();
}

class _PricesTabState extends State<_PricesTab> {
  final _query = TextEditingController();
  AiPriceList _list = const AiPriceList();
  bool _loading = true;
  bool _busy = false;
  String _message = '';
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  void _report(String text, {bool error = false}) {
    if (!mounted) return;
    setState(() {
      _message = text;
      _error = error;
    });
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final list = await widget.service.prices(query: _query.text);
      if (mounted) setState(() => _list = list);
    } catch (e) {
      _report('$e', error: true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _guard(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      _report('$e', error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sync() => _guard(() async {
        _report('Baixando a tabela pública de preços...');
        final result = await widget.service.syncPrices();
        await _load();
        _report('Tabela importada: ${result.added} novo(s), ${result.updated} atualizado(s), '
            '${result.keptManual} preço(s) digitado(s) à mão mantido(s).');
      });

  Future<void> _delete(AiPrice price) => _guard(() async {
        await widget.service.deletePrice(price.id);
        await _load();
        _report('Preço removido: o modelo volta ao padrão do provedor.');
      });

  Future<void> _edit([AiPrice? price]) async {
    final providers = _list.providers.isEmpty ? const ['claude'] : _list.providers;
    var provider = price?.provider ?? providers.first;
    final model = TextEditingController(text: price?.model ?? '');
    String show(double? v) => v == null ? '' : '$v';
    final input = TextEditingController(text: show(price?.inputPerMtok));
    final output = TextEditingController(text: show(price?.outputPerMtok));
    final cached = TextEditingController(text: show(price?.cachedInputPerMtok));
    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: AssistantTheme.surface,
          title: Text(price == null ? 'Novo preço' : 'Editar preço'),
          content: SizedBox(
            width: 420,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                DropdownButtonFormField<String>(
                  initialValue: providers.contains(provider) ? provider : providers.first,
                  decoration: const InputDecoration(labelText: 'PROVEDOR', isDense: true),
                  items: [for (final p in providers) DropdownMenuItem(value: p, child: Text(p))],
                  onChanged: price == null
                      ? (value) => setDialogState(() => provider = value ?? provider)
                      : null,
                ),
                const SizedBox(height: 8),
                TextField(
                  key: const Key('price-model'),
                  controller: model,
                  readOnly: price != null,
                  decoration: const InputDecoration(
                    labelText: 'MODELO (VAZIO = PADRÃO DO PROVEDOR)',
                    hintText: 'ex: claude-sonnet-4-5',
                    isDense: true,
                  ),
                ),
                const SizedBox(height: 8),
                TextField(
                  key: const Key('price-input'),
                  controller: input,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                      labelText: 'ENTRADA, US\$ POR 1 MILHÃO DE TOKENS', isDense: true),
                ),
                const SizedBox(height: 8),
                TextField(
                  key: const Key('price-output'),
                  controller: output,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                      labelText: 'SAÍDA, US\$ POR 1 MILHÃO DE TOKENS', isDense: true),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: cached,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                      labelText: 'ENTRADA EM CACHE (OPCIONAL)', isDense: true),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Modelo gratuito: use 0 e 0. Um preço digitado aqui nunca é sobrescrito pela '
                  'importação da tabela pública.',
                  style: TextStyle(fontSize: 11, color: AssistantTheme.textMuted),
                ),
              ]),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('CANCELAR')),
            FilledButton(
                key: const Key('price-save'),
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('SALVAR')),
          ],
        ),
      ),
    );
    final values = (model.text.trim(), input.text, output.text, cached.text);
    if (saved != true) return;
    double? number(String text) => double.tryParse(text.trim().replaceAll(',', '.'));
    final inValue = number(values.$2), outValue = number(values.$3);
    if (inValue == null || outValue == null || inValue < 0 || outValue < 0) {
      _report('Informe os preços de entrada e saída (zero ou mais).', error: true);
      return;
    }
    final cachedValue = values.$4.trim().isEmpty ? null : number(values.$4);
    await _guard(() async {
      await widget.service.savePrice(
        provider: provider,
        model: values.$1,
        inputPerMtok: inValue,
        outputPerMtok: outValue,
        cachedInputPerMtok: cachedValue,
      );
      await _load();
      _report('Preço salvo.');
    });
  }

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.all(16), children: [
      Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(
          width: 260,
          child: TextField(
            key: const Key('price-search'),
            controller: _query,
            onSubmitted: (_) => _load(),
            decoration: const InputDecoration(
                hintText: 'Buscar modelo', isDense: true, prefixIcon: Icon(Icons.search, size: 18)),
          ),
        ),
        if (widget.isAdmin) ...[
          OutlinedButton.icon(
            key: const Key('price-sync'),
            onPressed: _busy ? null : _sync,
            icon: const Icon(Icons.cloud_download_outlined, size: 16),
            label: const Text('ATUALIZAR DA INTERNET'),
          ),
          FilledButton.tonalIcon(
            key: const Key('price-add'),
            onPressed: _busy ? null : () => _edit(),
            icon: const Icon(Icons.add, size: 16),
            label: const Text('NOVO PREÇO'),
          ),
        ],
      ]),
      const SizedBox(height: 8),
      Text(
        widget.isAdmin
            ? 'Preço por 1 milhão de tokens, em dólar. A tabela pública (LiteLLM) traz centenas de '
                'modelos, mas é preço de tabela, não o do seu contrato, e não cobre todos os '
                'provedores (OpenRouter e Hugging Face ficam de fora): para esses, digite o preço.'
            : 'Preço por 1 milhão de tokens, em dólar. Só administradores editam.',
        style: const TextStyle(fontSize: 11, color: AssistantTheme.textMuted, height: 1.4),
      ),
      if (_message.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(_message,
              key: const Key('price-message'),
              style: TextStyle(
                  fontSize: 12, color: _error ? Colors.redAccent : AssistantTheme.c3)),
        ),
      const SizedBox(height: 10),
      if (_loading)
        const Padding(
            padding: EdgeInsets.all(30), child: Center(child: CircularProgressIndicator()))
      else if (_list.prices.isEmpty)
        const Text(
          'Nenhum preço no banco ainda: o custo usa o preço padrão de cada provedor. '
          'Use ATUALIZAR DA INTERNET para importar a tabela pública.',
          style: TextStyle(fontSize: 12, color: AssistantTheme.textMuted),
        )
      else
        for (final price in _list.prices) _priceRow(price),
    ]);
  }

  Widget _priceRow(AiPrice price) {
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AssistantTheme.border),
      ),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text(price.provider.toUpperCase(),
                  style: const TextStyle(
                      fontSize: 10, letterSpacing: 1, color: AssistantTheme.c1)),
              Text(price.modelLabel,
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
              if (price.isFree) _tag('GRÁTIS', AssistantTheme.c3),
              _tag(price.isManual ? 'DIGITADO' : 'TABELA PÚBLICA',
                  price.isManual ? AssistantTheme.c4 : AssistantTheme.textMuted),
            ]),
            Text(
              'entrada ${formatUsd(price.inputPerMtok)} · saída ${formatUsd(price.outputPerMtok)}'
              '${price.cachedInputPerMtok == null ? '' : ' · cache ${formatUsd(price.cachedInputPerMtok!)}'}',
              style: const TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
            ),
          ]),
        ),
        if (widget.isAdmin) ...[
          IconButton(
            tooltip: 'Editar preço',
            icon: const Icon(Icons.edit_outlined, size: 16),
            onPressed: _busy ? null : () => _edit(price),
          ),
          IconButton(
            tooltip: 'Apagar preço',
            icon: const Icon(Icons.delete_outline, size: 16),
            onPressed: _busy ? null : () => _delete(price),
          ),
        ],
      ]),
    );
  }

  Widget _tag(String text, Color color) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(
          color: color.withOpacity(.15),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(text, style: TextStyle(fontSize: 9, letterSpacing: .6, color: color)),
      );
}

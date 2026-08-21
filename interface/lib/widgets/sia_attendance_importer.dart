import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import '../services/api_service.dart';

/// Importa a presença lançada no SIA da Estácio para uma aula do app.
///
/// O SIA fica atrás do Akamai Bot Manager, que valida o fingerprint do
/// navegador (cookies `_abck` / `bm_sz` / `ak_bmsc`). Por isso quem busca o
/// HTML é o próprio WebView já autenticado — o backend só recebe o HTML pronto
/// e faz o parse. Requisições equivalentes feitas server-side são desafiadas.
class SiaAttendanceImporter extends StatefulWidget {
  final String? lessonId;
  final VoidCallback? onImported;

  const SiaAttendanceImporter({
    this.lessonId,
    this.onImported,
    super.key,
  });

  @override
  State<SiaAttendanceImporter> createState() => _SiaAttendanceImporterState();
}

/// Cookie de autenticação do SIA. Os ~130 `ASPSESSIONID*` que o IIS cria (um
/// por diretório virtual) já existem na tela de login e não servem de sinal.
const _authCookie = 'wrawrsatrsrweasrdxsf';

const _siaOrigin = 'https://sia.estacio.br';

/// Tela de Lançamento de Frequência (módulo 11). O SIA urlencoda o título em
/// windows-1252, não em UTF-8: `ç` vira `%E7`, `ü` vira `%FC`, `ê` vira `%EA`.
const _tituloFrequencia = 'Lan%E7amento%24de%24Freq%FC%EAncia';
const _frequenciaUrl =
    '$_siaOrigin/doc/doc0032a.asp?funcao=DOC-25-9&modulo=11'
    '&titulo=$_tituloFrequencia&hlp=';

class _SiaAttendanceImporterState extends State<SiaAttendanceImporter> {
  final ApiService _apiService = ApiService();

  InAppWebViewController? _webView;
  final Map<String, Completer<String?>> _pendingFetches = {};

  List<dynamic>? _periodos;
  String? _selectedPeriodo;
  List<dynamic>? _turmas;
  String? _selectedTurma;
  Map<String, dynamic>? _attendancePage;
  List<bool>? _selectedStudents;

  bool _loading = false;
  bool _showWebView = true;
  bool _authenticated = false;
  String? _error;
  int _step = 1;

  @override
  void dispose() {
    for (final pending in _pendingFetches.values) {
      if (!pending.isCompleted) pending.complete(null);
    }
    _pendingFetches.clear();
    super.dispose();
  }

  // ---------------------------------------------------------------------
  // Busca dentro do navegador autenticado
  // ---------------------------------------------------------------------

  /// Busca uma URL do SIA de dentro do WebView e devolve o HTML.
  ///
  /// As páginas vêm em windows-1252 sem `charset` no `Content-Type`, então o
  /// corpo é lido como bytes e decodificado explicitamente.
  Future<String?> _fetchViaBrowser(
    String url, {
    Map<String, String>? form,
  }) async {
    final controller = _webView;
    if (controller == null) return null;

    final id = DateTime.now().microsecondsSinceEpoch.toString();
    final completer = Completer<String?>();
    _pendingFetches[id] = completer;

    final init = form == null
        ? "{credentials: 'include'}"
        : "{credentials: 'include', method: 'POST', "
            "headers: {'Content-Type': 'application/x-www-form-urlencoded'}, "
            "body: new URLSearchParams(${jsonEncode(form)}).toString()}";

    await controller.evaluateJavascript(source: '''
      (function () {
        var reply = function (html) {
          window.flutter_inappwebview.callHandler(
            'siaFetch', ${jsonEncode(id)}, html);
        };
        fetch(${jsonEncode(url)}, $init)
          .then(function (r) { return r.arrayBuffer(); })
          .then(function (b) {
            reply(new TextDecoder('windows-1252').decode(b));
          })
          .catch(function () { reply(null); });
      })();
    ''');

    return completer.future.timeout(
      const Duration(seconds: 30),
      onTimeout: () {
        _pendingFetches.remove(id);
        return null;
      },
    );
  }

  Future<dynamic> _parseOnBackend(String endpoint, String html) async {
    final response = await _apiService.post(
      '/education/sia/$endpoint',
      body: {'html': html},
    );
    return response.success ? response.data : null;
  }

  // ---------------------------------------------------------------------
  // Fluxo
  // ---------------------------------------------------------------------

  /// Verifica se o login já ocorreu e, em caso positivo, carrega os períodos.
  Future<void> _checkAuthentication() async {
    if (_authenticated) return;

    try {
      final cookies = await CookieManager.instance().getCookies(
        url: WebUri(_siaOrigin),
      );
      final logged = cookies.any(
        (c) => c.name == _authCookie && c.value.toString().isNotEmpty,
      );
      if (!logged || !mounted) return;

      setState(() {
        _authenticated = true;
        _loading = true;
      });

      final html = await _fetchViaBrowser(_frequenciaUrl);
      if (html == null || !mounted) {
        setState(() => _authenticated = false);
        return;
      }

      final session = await _parseOnBackend('parse-session', html);
      if (session == null || session['valid'] != true) {
        // Cookie existe mas a tela ainda nao e a da pauta: segue no navegador.
        if (mounted) setState(() => _authenticated = false);
        return;
      }

      final periodos = await _parseOnBackend('parse-periodos', html);
      if (!mounted) return;

      setState(() {
        _periodos = (periodos as List<dynamic>?) ?? [];
        _showWebView = false;
        _step = 2;
      });
    } catch (e) {
      debugPrint('Falha ao validar sessao do SIA: $e');
      if (mounted) setState(() => _authenticated = false);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadTurmas() async {
    if (_selectedPeriodo == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final html = await _fetchViaBrowser(
        _frequenciaUrl,
        form: {'num_seq_periodo_academico': _selectedPeriodo!},
      );
      final turmas =
          html == null ? null : await _parseOnBackend('parse-turmas', html);

      if (!mounted) return;
      if (turmas == null) {
        setState(() => _error = 'Nao foi possivel carregar as turmas.');
        return;
      }

      setState(() {
        _turmas = turmas as List<dynamic>;
        _selectedTurma = null;
        _step = 3;
      });
    } catch (e) {
      if (mounted) setState(() => _error = 'Erro ao carregar turmas: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadAttendance() async {
    if (_selectedPeriodo == null || _selectedTurma == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final html = await _fetchViaBrowser(
        '$_siaOrigin/doc/doc0032a.asp',
        form: {
          'selecao': _selectedTurma!,
          'num_seq_periodo_academico': _selectedPeriodo!,
          'acao': 'Continuar',
        },
      );
      final page =
          html == null ? null : await _parseOnBackend('parse-attendance', html);

      if (!mounted) return;
      if (page == null) {
        setState(() => _error = 'Nao foi possivel carregar a pauta.');
        return;
      }

      final students = (page['students'] as List<dynamic>?) ?? [];
      setState(() {
        _attendancePage = page as Map<String, dynamic>;
        _selectedStudents = [
          for (final s in students) s['presente'] == true,
        ];
        _step = 4;
      });
    } catch (e) {
      if (mounted) setState(() => _error = 'Erro ao carregar presenca: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _importAttendance() async {
    final page = _attendancePage;
    final selected = _selectedStudents;
    if (page == null || selected == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final students = page['students'] as List<dynamic>;
      final payload = [
        for (var i = 0; i < students.length; i++)
          {
            'matricula': students[i]['matricula'],
            'nome': students[i]['nome'],
            'presente': selected[i],
          },
      ];

      final response = await _apiService.post(
        '/education/sia/import-attendance',
        body: {
          'lesson_id': widget.lessonId!,
          'students_data': payload,
        },
      );

      if (!mounted) return;
      if (!response.success) {
        setState(() => _error = 'Erro ao importar a presenca.');
        return;
      }

      widget.onImported?.call();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${response.data['imported']} presentes registrados!'),
          backgroundColor: Colors.green,
        ),
      );
      Navigator.pop(context);
    } catch (e) {
      if (mounted) setState(() => _error = 'Erro ao importar: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  // ---------------------------------------------------------------------
  // UI
  // ---------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (widget.lessonId == null || widget.lessonId!.isEmpty) {
      return _dialogShell(
        maxWidth: 600,
        maxHeight: 400,
        child: _buildNoLesson(),
      );
    }

    return _dialogShell(
      maxWidth: _showWebView ? 900 : 600,
      maxHeight: _showWebView ? 900 : 800,
      child: Stack(
        children: [
          // O WebView fica montado o tempo todo: e ele que faz as buscas.
          Offstage(
            offstage: !_showWebView,
            child: _buildLoginWebView(),
          ),
          if (!_showWebView) _buildSelection(),
          if (_loading)
            const Positioned.fill(
              child: ColoredBox(
                color: Color(0x33000000),
                child: Center(child: CircularProgressIndicator()),
              ),
            ),
        ],
      ),
    );
  }

  Widget _dialogShell({
    required double maxWidth,
    required double maxHeight,
    required Widget child,
  }) {
    return Dialog(
      child: Container(
        constraints: BoxConstraints(maxWidth: maxWidth, maxHeight: maxHeight),
        child: child,
      ),
    );
  }

  Widget _header({required IconData icon, required String title, String? subtitle}) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [Colors.blue[400]!, Colors.blue[600]!],
        ),
        borderRadius: const BorderRadius.only(
          topLeft: Radius.circular(8),
          topRight: Radius.circular(8),
        ),
      ),
      child: Row(
        children: [
          Icon(icon, color: Colors.white),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                if (subtitle != null)
                  Text(
                    subtitle,
                    style: const TextStyle(color: Colors.white70, fontSize: 12),
                  ),
              ],
            ),
          ),
          IconButton(
            onPressed: () => Navigator.pop(context),
            icon: const Icon(Icons.close, color: Colors.white),
          ),
        ],
      ),
    );
  }

  Widget _buildNoLesson() {
    return Column(
      children: [
        _header(icon: Icons.cloud_download, title: 'Importar Presença'),
        Expanded(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.info_outline, size: 48, color: Colors.blue),
                  const SizedBox(height: 16),
                  const Text(
                    'Nenhuma aula selecionada',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Abra o histórico e use o ícone de sincronizar '
                    'na aula que deseja preencher.',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 12, color: Colors.grey),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Entendi'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildLoginWebView() {
    return Column(
      children: [
        _header(
          icon: Icons.login,
          title: 'Entrar no SIA',
          subtitle: 'Faça login normalmente — a sessão é lida automaticamente',
        ),
        Expanded(
          child: InAppWebView(
            initialUrlRequest: URLRequest(url: WebUri(_frequenciaUrl)),
            onWebViewCreated: (controller) {
              _webView = controller;
              controller.addJavaScriptHandler(
                handlerName: 'siaFetch',
                callback: (args) {
                  final id = args.isNotEmpty ? args[0] as String? : null;
                  final html = args.length > 1 ? args[1] as String? : null;
                  final pending = _pendingFetches.remove(id);
                  if (pending != null && !pending.isCompleted) {
                    pending.complete(html);
                  }
                },
              );
            },
            onLoadStop: (controller, url) => _checkAuthentication(),
          ),
        ),
      ],
    );
  }

  Widget _buildSelection() {
    final page = _attendancePage;
    final students = (page?['students'] as List<dynamic>?) ?? const [];

    return Column(
      children: [
        _header(
          icon: Icons.cloud_download,
          title: 'Importar Presença',
          subtitle: 'Passo ${_step - 1} de 3',
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionTitle('Período acadêmico'),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: _selectedPeriodo,
                  decoration: _fieldDecoration('Período'),
                  items: [
                    for (final p in _periodos ?? const [])
                      DropdownMenuItem(
                        value: p['value'] as String,
                        child: Text(p['label'] as String),
                      ),
                  ],
                  onChanged: (value) {
                    setState(() => _selectedPeriodo = value);
                    if (value != null) _loadTurmas();
                  },
                ),

                if (_step >= 3) ...[
                  const SizedBox(height: 20),
                  _sectionTitle('Turma'),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    value: _selectedTurma,
                    decoration: _fieldDecoration('Turma'),
                    items: [
                      for (final t in _turmas ?? const [])
                        DropdownMenuItem(
                          value: t['num_seq_turma'] as String,
                          child: Text('${t['disciplina']} — ${t['turma']}'),
                        ),
                    ],
                    onChanged: (value) {
                      setState(() => _selectedTurma = value);
                      if (value != null) _loadAttendance();
                    },
                  ),
                ],

                if (_step >= 4 && page != null) ...[
                  const SizedBox(height: 20),
                  _sectionTitle('Marcar presentes'),
                  const SizedBox(height: 4),
                  Text(
                    '${page['disciplina']} — ${page['turma']}',
                    style: const TextStyle(fontSize: 12, color: Colors.grey),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    height: 250,
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.grey[300]!),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: ListView.separated(
                      itemCount: students.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (_, index) {
                        final student = students[index];
                        return CheckboxListTile(
                          key: ValueKey(student['matricula']),
                          title: Text('${student['nome']}'),
                          subtitle: Text('${student['matricula']}'),
                          value: _selectedStudents![index],
                          onChanged: (value) => setState(
                            () => _selectedStudents![index] = value ?? false,
                          ),
                        );
                      },
                    ),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: _loading ? null : _importAttendance,
                      icon: const Icon(Icons.cloud_upload),
                      label: const Text('Importar presença'),
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        backgroundColor: Colors.blue,
                      ),
                    ),
                  ),
                ],

                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red[50],
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.red),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.error_outline, color: Colors.red),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _error!,
                            style: TextStyle(color: Colors.red[900]),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _sectionTitle(String text) => Text(
        text,
        style: Theme.of(context)
            .textTheme
            .titleMedium
            ?.copyWith(fontWeight: FontWeight.bold),
      );

  InputDecoration _fieldDecoration(String label) => InputDecoration(
        labelText: label,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
      );
}

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import '../services/api_service.dart';

/// Leva a presença registrada no INTARQ para a pauta do SIA da Estácio.
///
/// O professor faz a chamada no app (QR code) e aqui espelha o resultado na
/// Pauta Eletrônica, sem reconferir aluno por aluno. O trabalho acontece dentro
/// de um navegador embutido porque o SIA fica atrás do Akamai Bot Manager, que
/// valida o fingerprint do navegador — requisições server-side são desafiadas.
///
/// A leitura e a marcação são feitas pelo DOM da própria tela, não por parsing
/// de HTML: é o SIA quem diz onde está cada checkbox.
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

/// Abrimos a raiz, e não a tela de frequência direto: o `validateFrame()` do
/// SIA joga para `/404.asp` qualquer página carregada fora do frameset
/// `faixa` / `conteudo` / `principal`. Quem navega até a pauta é o professor.
const _siaEntrada = '$_siaOrigin/';

/// Uma linha da pauta aberta no SIA.
class _LinhaPauta {
  final String matricula;
  final String nome;
  final bool presenteNoSia;

  /// Falta abonada. O SIA recusa presença e abono na mesma linha.
  final bool abonado;

  /// Lançamento travado pela coordenação (`ckdBloqueio_N` preenchido).
  final bool bloqueado;

  _LinhaPauta({
    required this.matricula,
    required this.nome,
    required this.presenteNoSia,
    required this.abonado,
    required this.bloqueado,
  });

  factory _LinhaPauta.fromJson(Map<dynamic, dynamic> json) => _LinhaPauta(
        matricula: '${json['matricula']}',
        nome: '${json['nome']}',
        presenteNoSia: json['presente'] == true,
        abonado: json['abonado'] == true,
        bloqueado: json['bloqueado'] == true,
      );
}

/// O que muda na pauta se a presença do INTARQ for aplicada.
class _Comparacao {
  final List<_LinhaPauta> marcar = [];
  final List<_LinhaPauta> desmarcar = [];
  final List<_LinhaPauta> jaCorretos = [];
  final List<_LinhaPauta> bloqueados = [];

  /// Alunos presentes no INTARQ que não têm linha na pauta do SIA.
  final List<String> semLinhaNoSia = [];

  bool get temMudanca => marcar.isNotEmpty || desmarcar.isNotEmpty;
  int get total =>
      marcar.length + desmarcar.length + jaCorretos.length + bloqueados.length;
}

/// Matrículas variam de formatação entre os dois sistemas; só os dígitos casam.
String _soDigitos(String valor) => valor.replaceAll(RegExp(r'\D'), '');

class _SiaAttendanceImporterState extends State<SiaAttendanceImporter> {
  final ApiService _apiService = ApiService();

  InAppWebViewController? _webView;
  final Map<String, Completer<dynamic>> _pendentes = {};

  List<Map<String, dynamic>>? _presencaIntarq;
  _Comparacao? _comparacao;
  Map<String, dynamic>? _fichaSia;

  bool _loading = false;
  bool _autenticado = false;
  bool _aplicado = false;
  String? _error;

  @override
  void dispose() {
    for (final pendente in _pendentes.values) {
      if (!pendente.isCompleted) pendente.complete(null);
    }
    _pendentes.clear();
    super.dispose();
  }

  // ---------------------------------------------------------------------
  // Ponte com o DOM da pauta
  // ---------------------------------------------------------------------

  /// Funções injetadas na página: acham a pauta entre os frames e operam nela.
  ///
  /// A tela do SIA é um frameset, e `outerHTML` de um frame pai não inclui o
  /// conteúdo dos filhos — por isso a varredura desce em `window.frames`. O
  /// documento válido é o que devolve mais linhas de aluno, sem depender de
  /// texto de cabeçalho nem do `name` dos campos.
  static const _jsPreludio = r'''
    var _siaValor = function (doc, nome) {
      var campo = doc.querySelector('[name="' + nome + '"]');
      return campo ? String(campo.value || '').trim() : '';
    };

    // textContent, e nao innerText: este ultimo depende de layout e volta
    // vazio quando a celula ainda nao foi renderizada.
    var _siaTexto = function (el) {
      return String(el.textContent || '').replace(/\s+/g, ' ').trim();
    };

    // A celula da matricula carrega um <span><font color="red"> usado pelo
    // SIA para avisos; so a sequencia de digitos interessa.
    var _siaMatricula = function (el) {
      var achado = _siaTexto(el).match(/\d{4,}/);
      return achado ? achado[0] : '';
    };

    // A pauta numera os campos por linha: ckdPresenca_1, ckdAbono_1, etc.
    var _siaLinhas = function (doc) {
      var linhas = [];
      var presencas = doc.querySelectorAll('input[name^="ckdPresenca_"]');

      for (var i = 0; i < presencas.length; i++) {
        var chk = presencas[i];
        var idx = chk.name.substring('ckdPresenca_'.length);

        var tr = chk.closest('tr');
        if (!tr) continue;

        var tds = [];
        for (var j = 0; j < tr.children.length; j++) {
          if (tr.children[j].tagName === 'TD') tds.push(tr.children[j]);
        }
        if (tds.length < 3) continue;

        var abono = doc.querySelector('[name="ckdAbono_' + idx + '"]');

        linhas.push({
          elemento: chk,
          indice: idx,
          matricula: _siaMatricula(tds[1]),
          nome: _siaTexto(tds[2]),
          presente: !!chk.checked,
          // Abono e presenca sao excludentes: validForm() recusa os dois
          // juntos, e fctDesabilita() desativa um quando o outro e marcado.
          abonado: !!(abono && abono.checked),
          bloqueado: !!chk.disabled ||
                     _siaValor(doc, 'ckdBloqueio_' + idx) !== ''
        });
      }
      return linhas;
    };

    var _siaDocumentos = function () {
      var docs = [];
      var visitar = function (win) {
        if (!win) return;
        try {
          if (docs.indexOf(win.document) === -1) docs.push(win.document);
        } catch (e) { return; /* origem diferente */ }
        for (var i = 0; i < win.frames.length; i++) {
          try { visitar(win.frames[i]); } catch (e) { /* idem */ }
        }
      };
      // O SIA monta faixa/conteudo/principal, e algumas telas abrem em popup.
      visitar(window.top);
      try { if (window.opener) visitar(window.opener.top); } catch (e) {}
      return docs;
    };

    // O documento da pauta é o que produz mais linhas de aluno.
    var _siaPauta = function () {
      var melhor = null;
      var docs = _siaDocumentos();
      var vistoria = [];

      for (var i = 0; i < docs.length; i++) {
        var linhas = _siaLinhas(docs[i]);
        var rotulo = '';
        try {
          var win = docs[i].defaultView;
          rotulo = (win && win.name ? win.name + ' ' : '') +
                   docs[i].location.pathname;
        } catch (e) { rotulo = '?'; }
        vistoria.push(rotulo + ' → ' + linhas.length);

        if (!melhor || linhas.length > melhor.linhas.length) {
          melhor = { doc: docs[i], linhas: linhas };
        }
      }
      if (melhor) melhor.vistoria = vistoria;
      return melhor;
    };

    var _siaFicha = function (doc) {
      var sel = doc.querySelector('[name="numSeqDataTurma"]');
      return {
        disciplina: _siaValor(doc, 'txtDisciplina'),
        turma: _siaValor(doc, 'txtTurma'),
        periodo: _siaValor(doc, 'nom_fantasia'),
        campus: _siaValor(doc, 'nomCampus'),
        dataAula: (sel && sel.selectedIndex >= 0)
          ? sel.options[sel.selectedIndex].text.trim() : '',
        // "E" lanca por checkbox; "T" lanca tempo em txtPresenca_N.
        forma: _siaValor(doc, 'indFormaLancamento')
      };
    };
  ''';

  /// Roda um trecho de JS na página e espera a resposta pelo handler.
  Future<dynamic> _noNavegador(String corpo) async {
    final controller = _webView;
    if (controller == null) return null;

    final id = DateTime.now().microsecondsSinceEpoch.toString();
    final completer = Completer<dynamic>();
    _pendentes[id] = completer;

    await controller.evaluateJavascript(source: '''
      (function () {
        var responder = function (dados) {
          window.flutter_inappwebview.callHandler(
            'siaPonte', ${jsonEncode(id)}, dados);
        };
        try {
          $_jsPreludio
          $corpo
        } catch (e) {
          responder({ erro: String(e) });
        }
      })();
    ''');

    return completer.future.timeout(
      const Duration(seconds: 15),
      onTimeout: () {
        _pendentes.remove(id);
        return null;
      },
    );
  }

  /// Lê a pauta visível no SIA (linhas + ficha da turma).
  Future<Map<dynamic, dynamic>?> _lerPauta() async {
    final resposta = await _noNavegador('''
      var pauta = _siaPauta();
      if (!pauta || !pauta.linhas.length) {
        responder({ linhas: [], ficha: null,
                    vistoria: pauta ? pauta.vistoria : [] });
      } else {
        var limpas = pauta.linhas.map(function (l) {
          return { matricula: l.matricula, nome: l.nome,
                   presente: l.presente, abonado: l.abonado,
                   bloqueado: l.bloqueado };
        });
        responder({ linhas: limpas, ficha: _siaFicha(pauta.doc),
                    vistoria: pauta.vistoria });
      }
    ''');
    return resposta as Map<dynamic, dynamic>?;
  }

  /// Marca na pauta exatamente quem o INTARQ registrou como presente.
  Future<Map<dynamic, dynamic>?> _aplicarNaPauta(
    Map<String, bool> desejado,
  ) async {
    final resposta = await _noNavegador('''
      var desejado = ${jsonEncode(desejado)};
      var pauta = _siaPauta();
      if (!pauta || !pauta.linhas.length) {
        responder({ erro: 'pauta nao encontrada' });
      } else {
        var relatorio = { marcados: 0, desmarcados: 0, ignorados: 0 };
        pauta.linhas.forEach(function (linha) {
          var alvo = desejado[linha.matricula];
          // Quem tem abono fica de fora: validForm() recusa presenca+abono.
          if (alvo === undefined || linha.bloqueado || linha.abonado) {
            relatorio.ignorados++;
            return;
          }
          if (linha.elemento.checked === alvo) return;
          // click() em vez de .checked: dispara fctDesabilitaPres() da tela,
          // que ajusta o abono correspondente.
          linha.elemento.click();
          if (alvo) relatorio.marcados++; else relatorio.desmarcados++;
        });
        responder(relatorio);
      }
    ''');
    return resposta as Map<dynamic, dynamic>?;
  }

  // ---------------------------------------------------------------------
  // Fluxo
  // ---------------------------------------------------------------------

  Future<void> _verificarLogin() async {
    if (_autenticado) return;
    try {
      final cookies =
          await CookieManager.instance().getCookies(url: WebUri(_siaOrigin));
      final logado = cookies.any(
        (c) => c.name == _authCookie && c.value.toString().isNotEmpty,
      );
      if (logado && mounted) setState(() => _autenticado = true);
    } catch (e) {
      debugPrint('Falha ao ler cookies do SIA: $e');
    }
  }

  Future<List<Map<String, dynamic>>?> _carregarPresencaIntarq() async {
    if (_presencaIntarq != null) return _presencaIntarq;

    final resposta = await _apiService.get(
      '/education/sia/lesson/${widget.lessonId}/attendance',
    );
    if (!resposta.success) return null;

    final presentes = (resposta.data['presentes'] as List<dynamic>?) ?? const [];
    _presencaIntarq = [
      for (final p in presentes) Map<String, dynamic>.from(p as Map),
    ];
    return _presencaIntarq;
  }

  /// Confronta a chamada do INTARQ com a pauta aberta, sem alterar nada ainda.
  Future<void> _comparar() async {
    setState(() {
      _loading = true;
      _error = null;
      _aplicado = false;
    });

    try {
      final intarq = await _carregarPresencaIntarq();
      if (intarq == null) {
        setState(() => _error = 'Não consegui ler a chamada desta aula.');
        return;
      }
      if (intarq.isEmpty) {
        setState(() => _error =
            'Esta aula não tem nenhuma presença registrada no INTARQ.');
        return;
      }

      final pauta = await _lerPauta();
      final linhasJson = (pauta?['linhas'] as List<dynamic>?) ?? const [];
      if (linhasJson.isEmpty) {
        final vistoria = (pauta?['vistoria'] as List<dynamic>?) ?? const [];
        setState(() => _error =
            'Não achei a lista de alunos nesta tela. Abra Pauta Eletrônica → '
            'Lançamento de Frequência com a turma e a data escolhidas.'
            '${vistoria.isEmpty ? '' : '\n\nFrames vistos: '
                '${vistoria.join(', ')}'}');
        return;
      }

      final ficha = (pauta?['ficha'] as Map?)?.cast<String, dynamic>();
      // Modo "T" lanca tempo em txtPresenca_N; marcar checkbox nao se aplica.
      if (ficha != null && ficha['forma'] != '' && ficha['forma'] != 'E') {
        setState(() => _error =
            'Esta turma lança frequência por tempo de aula, não por presença '
            'marcada. O INTARQ não consegue preencher esse formato.');
        return;
      }

      final presentesIntarq = {
        for (final p in intarq) _soDigitos('${p['matricula']}'),
      }..remove('');

      final comparacao = _Comparacao();
      final vistasNaPauta = <String>{};

      for (final json in linhasJson) {
        final linha = _LinhaPauta.fromJson(json as Map<dynamic, dynamic>);
        final chave = _soDigitos(linha.matricula);
        vistasNaPauta.add(chave);

        final devePresente = presentesIntarq.contains(chave);
        if (linha.bloqueado || linha.abonado) {
          comparacao.bloqueados.add(linha);
        } else if (linha.presenteNoSia == devePresente) {
          comparacao.jaCorretos.add(linha);
        } else if (devePresente) {
          comparacao.marcar.add(linha);
        } else {
          comparacao.desmarcar.add(linha);
        }
      }

      comparacao.semLinhaNoSia.addAll([
        for (final p in intarq)
          if (!vistasNaPauta.contains(_soDigitos('${p['matricula']}')))
            '${p['nome']} (${p['matricula']})',
      ]);

      if (!mounted) return;
      setState(() {
        _comparacao = comparacao;
        _fichaSia = ficha;
      });
    } catch (e) {
      if (mounted) setState(() => _error = 'Erro ao comparar: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Aplica a marcação na pauta. Gravar continua sendo ato do professor no SIA.
  Future<void> _aplicar() async {
    final comparacao = _comparacao;
    if (comparacao == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final desejado = <String, bool>{
        for (final l in comparacao.marcar) l.matricula: true,
        for (final l in comparacao.desmarcar) l.matricula: false,
      };

      final relatorio = await _aplicarNaPauta(desejado);
      if (!mounted) return;

      if (relatorio == null || relatorio['erro'] != null) {
        setState(() => _error =
            'Não consegui marcar a pauta: ${relatorio?['erro'] ?? 'sem resposta'}');
        return;
      }

      widget.onImported?.call();
      setState(() {
        _aplicado = true;
        _comparacao = null;
      });

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${relatorio['marcados']} marcados e '
            '${relatorio['desmarcados']} desmarcados na pauta. '
            'Confira e clique em Confirmar no SIA.',
          ),
          backgroundColor: Colors.green,
          duration: const Duration(seconds: 6),
        ),
      );
    } catch (e) {
      if (mounted) setState(() => _error = 'Erro ao aplicar: $e');
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
      return Dialog(
        child: Container(
          constraints: const BoxConstraints(maxWidth: 600, maxHeight: 400),
          child: _buildSemAula(),
        ),
      );
    }

    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      child: Container(
        constraints: const BoxConstraints(maxWidth: 1100, maxHeight: 900),
        child: Column(
          children: [
            _buildHeader(),
            Expanded(
              child: Row(
                children: [
                  Expanded(
                    child: InAppWebView(
                      initialUrlRequest:
                          URLRequest(url: WebUri(_siaEntrada)),
                      onWebViewCreated: (controller) {
                        _webView = controller;
                        controller.addJavaScriptHandler(
                          handlerName: 'siaPonte',
                          callback: (args) {
                            final id =
                                args.isNotEmpty ? args[0] as String? : null;
                            final dados = args.length > 1 ? args[1] : null;
                            final pendente = _pendentes.remove(id);
                            if (pendente != null && !pendente.isCompleted) {
                              pendente.complete(dados);
                            }
                          },
                        );
                      },
                      onLoadStop: (controller, url) => _verificarLogin(),
                    ),
                  ),
                  const VerticalDivider(width: 1),
                  SizedBox(width: 340, child: _buildPainel()),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(16),
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
          const Icon(Icons.upload_file, color: Colors.white),
          const SizedBox(width: 12),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Lançar presença no SIA',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                Text(
                  'A chamada do INTARQ é espelhada na Pauta Eletrônica',
                  style: TextStyle(color: Colors.white70, fontSize: 12),
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

  Widget _buildSemAula() {
    return Column(
      children: [
        _buildHeader(),
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
                    'Abra o histórico e use o ícone de sincronizar na aula '
                    'cuja chamada você quer lançar no SIA.',
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

  Widget _buildPainel() {
    final comparacao = _comparacao;

    return Container(
      color: Colors.grey[50],
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(
                _autenticado ? Icons.check_circle : Icons.hourglass_empty,
                size: 18,
                color: _autenticado ? Colors.green : Colors.grey,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _autenticado
                      ? 'Sessão do SIA ativa'
                      : 'Faça login no SIA ao lado',
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
          const Divider(height: 24),

          if (comparacao == null && !_aplicado) ...[
            const Text(
              '1. Abra a pauta da turma e da data desta aula.\n'
              '2. Confira o que vai mudar.\n'
              '3. Aplique e clique em Confirmar no SIA.',
              style: TextStyle(fontSize: 12, height: 1.6),
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _autenticado && !_loading ? _comparar : null,
              icon: const Icon(Icons.compare_arrows),
              label: const Text('Comparar com a chamada'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.blue,
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ],

          if (_aplicado) ...[
            const Icon(Icons.task_alt, size: 40, color: Colors.green),
            const SizedBox(height: 12),
            const Text(
              'Pauta marcada. Revise ao lado e clique em Confirmar no SIA — '
              'o INTARQ não grava por você.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, height: 1.5),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: _loading ? null : _comparar,
              icon: const Icon(Icons.refresh),
              label: const Text('Comparar de novo'),
            ),
          ],

          if (comparacao != null) Expanded(child: _buildComparacao(comparacao)),

          if (_error != null) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.red[50],
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.red[200]!),
              ),
              child: Text(
                _error!,
                style: TextStyle(fontSize: 12, color: Colors.red[900]),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildComparacao(_Comparacao comparacao) {
    final ficha = _fichaSia;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (ficha != null && '${ficha['disciplina']}'.isNotEmpty) ...[
          Text(
            '${ficha['disciplina']}',
            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
          ),
          Text(
            'Turma ${ficha['turma']} · ${ficha['dataAula']}',
            style: const TextStyle(fontSize: 11, color: Colors.grey),
          ),
          const SizedBox(height: 12),
        ],
        Expanded(
          child: ListView(
            children: [
              _grupo('Marcar presente', comparacao.marcar, Colors.green,
                  Icons.add_task),
              _grupo('Desmarcar', comparacao.desmarcar, Colors.orange,
                  Icons.remove_circle_outline),
              _grupo('Já corretos', comparacao.jaCorretos, Colors.grey,
                  Icons.check),
              _grupo('Abonados ou bloqueados', comparacao.bloqueados,
                  Colors.grey, Icons.lock_outline),
              if (comparacao.semLinhaNoSia.isNotEmpty)
                _avisoSemLinha(comparacao.semLinhaNoSia),
            ],
          ),
        ),
        const SizedBox(height: 12),
        if (!comparacao.temMudanca)
          const Text(
            'A pauta já reflete a chamada do INTARQ.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: Colors.grey),
          )
        else
          ElevatedButton.icon(
            onPressed: _loading ? null : _aplicar,
            icon: const Icon(Icons.done_all),
            label: Text(
              'Aplicar em ${comparacao.marcar.length + comparacao.desmarcar.length} '
              'de ${comparacao.total}',
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.green[700],
              padding: const EdgeInsets.symmetric(vertical: 12),
            ),
          ),
      ],
    );
  }

  Widget _grupo(
    String titulo,
    List<_LinhaPauta> linhas,
    Color cor,
    IconData icone,
  ) {
    if (linhas.isEmpty) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icone, size: 16, color: cor),
              const SizedBox(width: 6),
              Text(
                '$titulo · ${linhas.length}',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                  color: cor,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          for (final linha in linhas.take(30))
            Padding(
              key: ValueKey('${titulo}_${linha.matricula}'),
              padding: const EdgeInsets.only(left: 22, top: 2),
              child: Text(
                linha.nome,
                style: const TextStyle(fontSize: 11),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          if (linhas.length > 30)
            Padding(
              padding: const EdgeInsets.only(left: 22, top: 2),
              child: Text(
                '+ ${linhas.length - 30} outros',
                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ),
        ],
      ),
    );
  }

  Widget _avisoSemLinha(List<String> nomes) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.amber[50],
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: Colors.amber[300]!),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Sem linha nesta pauta · ${nomes.length}',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.bold,
              color: Colors.amber[900],
            ),
          ),
          const SizedBox(height: 2),
          const Text(
            'Presentes no INTARQ que não aparecem nesta turma.',
            style: TextStyle(fontSize: 11, color: Colors.grey),
          ),
          for (final nome in nomes.take(10))
            Padding(
              key: ValueKey('sem_linha_$nome'),
              padding: const EdgeInsets.only(top: 2),
              child: Text(nome, style: const TextStyle(fontSize: 11)),
            ),
        ],
      ),
    );
  }
}

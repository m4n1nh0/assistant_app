/// Importacao da chamada a partir do SIA.
///
/// O WebView autentica e busca o HTML; o backend so faz o parse - o SIA bloqueia
/// requisicao que nao venha de um navegador real.
library;

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
  /// Id de uma chamada (`attendance_sessions`) ou de uma aula (`lessons`).
  ///
  /// A presença fica presa à chamada, não à aula: passar o id da aula reúne
  /// todas as chamadas ligadas a ela — útil quando a aula juntou duas turmas.
  final String? refId;

  final VoidCallback? onImported;

  const SiaAttendanceImporter({
    this.refId,
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

  /// Quantos vão perder o abono para a presença poder ser marcada.
  int get abonosARemover => marcar.where((l) => l.abonado).length;
}

/// Matrículas variam de formatação entre os dois sistemas; só os dígitos casam.
String _soDigitos(String valor) => valor.replaceAll(RegExp(r'\D'), '');

class _SiaAttendanceImporterState extends State<SiaAttendanceImporter> {
  InAppWebViewController? _webView;
  final Map<String, Completer<dynamic>> _pendentes = {};

  List<Map<String, dynamic>>? _presencaIntarq;

  /// Dados da chamada que o backend encontrou (turma, data, como casou).
  Map<String, dynamic>? _chamadaIntarq;

  /// A chamada foi achada por disciplina + data, não pelo vínculo com a aula.
  /// Vale conferir antes de aplicar: pode haver mais de uma no mesmo dia.
  bool get _casouPorHeuristica =>
      _chamadaIntarq?['casado_por'] == 'disciplina+data';

  _Comparacao? _comparacao;
  Map<String, dynamic>? _fichaSia;

  /// Mensagem que o SIA exibe em `#sessionMsg` (ex.: "Lançamento já
  /// realizado!"). Não bloqueia — a tela de Acerto de Frequência existe
  /// justamente para corrigir pauta já lançada — mas pede confirmação.
  String _avisoSia = '';

  /// Turma da pauta aberta. A comparação fica restrita a ela.
  String _turmaFiltrada = '';

  /// Presentes da chamada que são de outra turma — ficam fora deste lançamento.
  int _foraDaTurma = 0;

  /// Quantos ficaram presentes na pauta, para registrar junto do lançamento.
  int _marcadosNaPauta = 0;

  bool _loading = false;
  bool _autenticado = false;
  bool _aplicado = false;
  bool _confirmado = false;
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

    // Lancamento e Acerto de Frequencia diferem no layout: num deles a
    // matricula e o nome ficam em celulas separadas, no outro na mesma. Em vez
    // de fixar as colunas, procuramos a celula com a matricula entre as que
    // vem antes do checkbox de presenca.
    var _siaIdentificar = function (tds, ateIndice) {
      for (var i = 0; i < ateIndice; i++) {
        var texto = _siaTexto(tds[i]);
        var achado = texto.match(/\d{6,}/);
        if (!achado) continue;

        // Nome na mesma celula (depois da matricula) ou na celula seguinte.
        var resto = texto.replace(achado[0], ' ').trim();
        var nome = resto || (i + 1 < ateIndice ? _siaTexto(tds[i + 1]) : '');
        return { matricula: achado[0], nome: nome };
      }
      return null;
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
        var colunaPresenca = -1;
        for (var j = 0; j < tr.children.length; j++) {
          if (tr.children[j].tagName !== 'TD') continue;
          if (tr.children[j].contains(chk)) colunaPresenca = tds.length;
          tds.push(tr.children[j]);
        }
        if (colunaPresenca < 1) continue;

        var aluno = _siaIdentificar(tds, colunaPresenca);
        if (!aluno || !aluno.nome) continue;

        var abono = doc.querySelector('[name="ckdAbono_' + idx + '"]');

        linhas.push({
          elemento: chk,
          abonoElemento: abono,
          indice: idx,
          matricula: aluno.matricula,
          nome: aluno.nome,
          presente: !!chk.checked,
          // Abono e presenca sao excludentes: validForm() recusa os dois
          // juntos, e fctDesabilita() desativa um quando o outro e marcado.
          // Para marcar presenca em quem esta abonado, o abono sai antes.
          abonado: !!(abono && abono.checked),
          // Só `ckdBloqueio_N` significa trava da coordenação. O `disabled` do
          // checkbox costuma ser efeito do abono, e sai junto com ele.
          bloqueado: _siaValor(doc, 'ckdBloqueio_' + idx) !== ''
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

    // A tela de Acerto de Frequencia nao tem os campos do formulario: mostra
    // "2026.2 ARA0040 3001" e "AULA: ..." como texto em faixas azuis.
    var _siaFichaEmTexto = function (doc) {
      var achado = { periodo: '', disciplina: '', turma: '', dataAula: '' };
      var tds = doc.getElementsByTagName('td');

      for (var i = 0; i < tds.length; i++) {
        var texto = _siaTexto(tds[i]);

        var ficha = texto.match(/^(\d{4}\.\d)\s+([A-Z]{2,4}\d{3,5})\s+(\d{3,5})$/);
        if (ficha) {
          achado.periodo = ficha[1];
          achado.disciplina = ficha[2];
          achado.turma = ficha[3];
          continue;
        }

        var aula = texto.match(/^AULA:\s*(.+)$/i);
        if (aula) achado.dataAula = aula[1].trim();
      }
      return achado;
    };

    // O botao Confirmar chama validForm(), que valida a pauta e submete para
    // doc0032c.asp. Se a validacao falhar, a tela usa alert() — por isso ele e
    // interceptado antes, para virar resposta em vez de travar o WebView.
    var _siaConfirmar = function (doc) {
      var win = doc.defaultView;
      var botao = null;
      var inputs = doc.querySelectorAll('input[type="button"]');

      for (var i = 0; i < inputs.length; i++) {
        if (/confirmar/i.test(inputs[i].value || '')) { botao = inputs[i]; break; }
      }
      if (!botao) return { ok: false, motivo: 'Botão Confirmar não encontrado' };

      var alertas = [];
      var alertOriginal = win.alert;
      win.alert = function (msg) { alertas.push(String(msg)); };

      // Erro dentro de um handler de evento nao sobe pelo .click(): sem este
      // listener, uma falha do validForm() passaria por sucesso.
      var erros = [];
      var pegarErro = function (ev) {
        erros.push(String((ev && (ev.message || ev.error)) || 'erro'));
      };
      win.addEventListener('error', pegarErro);

      try {
        botao.click();
      } catch (e) {
        erros.push(String(e));
      } finally {
        win.alert = alertOriginal;
        win.removeEventListener('error', pegarErro);
      }

      if (erros.length) return { ok: false, motivo: erros.join(' / ') };
      if (alertas.length) {
        return { ok: false, motivo: alertas.join(' / '), validacao: true };
      }
      return { ok: true };
    };

    var _siaFicha = function (doc) {
      var sel = doc.querySelector('[name="numSeqDataTurma"]');
      // O SIA usa #sessionMsg para avisos como "Lançamento já realizado!".
      var aviso = doc.querySelector('#sessionMsg');

      var ficha = {
        aviso: aviso ? _siaTexto(aviso) : '',
        disciplina: _siaValor(doc, 'txtDisciplina'),
        turma: _siaValor(doc, 'txtTurma'),
        periodo: _siaValor(doc, 'nom_fantasia'),
        campus: _siaValor(doc, 'nomCampus'),
        dataAula: (sel && sel.selectedIndex >= 0)
          ? sel.options[sel.selectedIndex].text.trim() : '',
        // "E" lanca por checkbox; "T" lanca tempo em txtPresenca_N.
        forma: _siaValor(doc, 'indFormaLancamento')
      };

      if (!ficha.disciplina) {
        var texto = _siaFichaEmTexto(doc);
        ficha.disciplina = ficha.disciplina || texto.disciplina;
        ficha.turma = ficha.turma || texto.turma;
        ficha.periodo = ficha.periodo || texto.periodo;
        ficha.dataAula = ficha.dataAula || texto.dataAula;
      }
      return ficha;
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
        var relatorio = { marcados: 0, desmarcados: 0,
                          abonosRemovidos: 0, ignorados: 0 };

        pauta.linhas.forEach(function (linha) {
          var alvo = desejado[linha.matricula];
          // Bloqueio da coordenacao nao se desfaz por aqui.
          if (alvo === undefined || linha.bloqueado) {
            relatorio.ignorados++;
            return;
          }

          // O SIA recusa presenca + abono na mesma linha e desabilita o
          // checkbox de presenca enquanto o abono estiver marcado.
          if (alvo && linha.abonoElemento && linha.abonoElemento.checked) {
            linha.abonoElemento.click();
            relatorio.abonosRemovidos++;
          }
          // fctDesabilita() costuma reabilitar, mas nem toda tela tem o
          // handler: garantimos que o campo aceite o clique seguinte.
          linha.elemento.disabled = false;

          if (linha.elemento.checked === alvo) return;
          // click() em vez de .checked: dispara fctDesabilitaPres() da tela.
          linha.elemento.click();
          if (alvo) relatorio.marcados++; else relatorio.desmarcados++;
        });
        responder(relatorio);
      }
    ''');
    return resposta as Map<dynamic, dynamic>?;
  }

  /// Clica no Confirmar da pauta e devolve o que o SIA respondeu.
  Future<Map<dynamic, dynamic>?> _confirmarNaPauta() async {
    final resposta = await _noNavegador('''
      var pauta = _siaPauta();
      if (!pauta || !pauta.linhas.length) {
        responder({ ok: false, motivo: 'pauta nao encontrada' });
      } else {
        responder(_siaConfirmar(pauta.doc));
      }
    ''');
    return resposta as Map<dynamic, dynamic>?;
  }

  /// Confere se a tela que veio depois do Confirmar indica gravação.
  Future<Map<dynamic, dynamic>?> _lerResultadoConfirmacao() async {
    final resposta = await _noNavegador(r'''
      var docs = _siaDocumentos();
      var texto = '';
      for (var i = 0; i < docs.length; i++) {
        try {
          if (docs[i].body) texto += ' ' + _siaTexto(docs[i].body);
        } catch (e) {}
      }

      // O SIA nao tem uma mensagem unica de sucesso: aceitamos as variacoes
      // que ele usa e tratamos qualquer "erro/falha" como recusa.
      var sucesso = /lan.amento (j. )?(realizado|efetuado|gravado)/i.test(texto)
                 || /sucesso/i.test(texto)
                 || /dados (gravados|atualizados)/i.test(texto);
      var falha = /erro|falha|n.o foi poss.vel|inv.lid/i.test(texto);

      responder({ sucesso: sucesso && !falha, falha: falha,
                  amostra: texto.substring(0, 300) });
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

  /// Busca a chamada do INTARQ. Em caso de falha guarda o motivo em [_error].
  Future<List<Map<String, dynamic>>?> _carregarPresencaIntarq() async {
    if (_presencaIntarq != null) return _presencaIntarq;

    final rota = '/education/sia/lesson/${widget.refId}/attendance';
    final resposta = await api.get(rota);

    if (!resposta.success) {
      final motivo = resposta.statusCode == 0
          ? 'o backend do INTARQ não respondeu'
          : 'HTTP ${resposta.statusCode}';
      _error = 'Não consegui ler a chamada desta aula ($motivo).\n'
          '${resposta.error ?? ''}\n\nGET $rota';
      return null;
    }

    _chamadaIntarq = resposta.data;
    final presentes =
        (resposta.data['presentes'] as List<dynamic>?) ?? const [];
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
        setState(() {}); // _carregarPresencaIntarq ja preencheu _error
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

      // A pauta do SIA é de uma turma só; a chamada pode ter juntado várias.
      // Restringimos à turma aberta para não tratar aluno de outra turma como
      // ausente, nem oferecer marcação onde ela não existe.
      final turmaDaPauta = _soDigitos('${ficha?['turma'] ?? ''}');
      final daTurma = turmaDaPauta.isEmpty
          ? intarq
          : intarq
              .where((p) =>
                  _soDigitos('${p['turma']}').isEmpty ||
                  _soDigitos('${p['turma']}') == turmaDaPauta)
              .toList();

      _turmaFiltrada = turmaDaPauta;
      _foraDaTurma = intarq.length - daTurma.length;

      final presentesIntarq = {
        for (final p in daTurma) _soDigitos('${p['matricula']}'),
      }..remove('');

      final comparacao = _Comparacao();
      final vistasNaPauta = <String>{};

      for (final json in linhasJson) {
        final linha = _LinhaPauta.fromJson(json as Map<dynamic, dynamic>);
        final chave = _soDigitos(linha.matricula);
        vistasNaPauta.add(chave);

        final devePresente = presentesIntarq.contains(chave);
        if (linha.bloqueado) {
          comparacao.bloqueados.add(linha);
        } else if (linha.abonado && devePresente) {
          // O abono sai para a presença poder entrar.
          comparacao.marcar.add(linha);
        } else if (linha.abonado) {
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
        // Avisos como "Lançamento já realizado!" nao impedem o acerto de
        // frequencia, mas exigem uma confirmacao consciente antes de aplicar.
        _avisoSia = '${ficha?['aviso'] ?? ''}'.trim();
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

    if (_avisoSia.isNotEmpty && !await _confirmarSobrescrita()) return;

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

      _marcadosNaPauta = (relatorio['marcados'] as num?)?.toInt() ?? 0;
      widget.onImported?.call();
      setState(() {
        _aplicado = true;
        _comparacao = null;
      });

      final abonos = relatorio['abonosRemovidos'] ?? 0;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${relatorio['marcados']} marcados e '
            '${relatorio['desmarcados']} desmarcados'
            '${abonos == 0 ? '' : ', $abonos abonos removidos'}. '
            'Agora é só confirmar.',
          ),
          backgroundColor: Colors.green,
          duration: const Duration(seconds: 5),
        ),
      );
    } catch (e) {
      if (mounted) setState(() => _error = 'Erro ao aplicar: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Aciona o Confirmar do SIA, checa o retorno e registra o lançamento.
  ///
  /// A gravação é do SIA; aqui só constatamos que ela aconteceu. Se a tela não
  /// confirmar de forma clara, nada é marcado como transferido — melhor deixar
  /// o professor conferir do que registrar um lançamento que não ocorreu.
  Future<void> _confirmarNoSia() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final clique = await _confirmarNaPauta();
      if (!mounted) return;

      if (clique == null || clique['ok'] != true) {
        final motivo = '${clique?['motivo'] ?? 'sem resposta da tela'}';
        setState(() => _error = clique?['validacao'] == true
            ? 'O SIA recusou o lançamento: $motivo'
            : 'Não consegui acionar o Confirmar: $motivo');
        return;
      }

      // O submit navega para doc0032c.asp; a tela nova leva um instante.
      await Future.delayed(const Duration(seconds: 3));
      final resultado = await _lerResultadoConfirmacao();
      if (!mounted) return;

      if (resultado == null || resultado['sucesso'] != true) {
        setState(() =>
            _error = 'Enviei o Confirmar, mas não reconheci a resposta do SIA. '
                'Verifique na tela se a frequência foi gravada.\n\n'
                '${resultado?['amostra'] ?? ''}');
        return;
      }

      await _registrarTransferencia();
    } catch (e) {
      if (mounted) setState(() => _error = 'Erro ao confirmar: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Anota no INTARQ que esta chamada já foi para o sistema da instituição.
  Future<void> _registrarTransferencia() async {
    final resposta = await api.post(
      '/education/sia/mark-synced',
      body: {
        'ref_id': widget.refId,
        'turma': _turmaFiltrada,
        'marcados': _marcadosNaPauta,
      },
    );

    if (!mounted) return;

    if (!resposta.success) {
      setState(() =>
          _error = 'O SIA gravou a frequência, mas não consegui anotar isso no '
              'INTARQ: ${resposta.error ?? 'HTTP ${resposta.statusCode}'}');
      return;
    }

    widget.onImported?.call();
    setState(() => _confirmado = true);

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Frequência gravada no SIA e marcada como transferida.'),
        backgroundColor: Colors.green,
        duration: Duration(seconds: 5),
      ),
    );
  }

  /// Mantem o WebView e a chamada carregados, mas libera uma nova rodada para
  /// a pauta de outra turma da mesma aula/chamada reunida.
  void _prepararOutraTurma() {
    setState(() {
      _comparacao = null;
      _fichaSia = null;
      _avisoSia = '';
      _turmaFiltrada = '';
      _foraDaTurma = 0;
      _marcadosNaPauta = 0;
      _aplicado = false;
      _confirmado = false;
      _error = null;
    });
  }

  /// Pede confirmação quando a pauta já tem lançamento gravado.
  Future<bool> _confirmarSobrescrita() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        icon: const Icon(Icons.warning_amber, color: Colors.orange, size: 36),
        title: const Text('Esta pauta já foi lançada'),
        content: Text(
          'O SIA está exibindo: "$_avisoSia"\n\n'
          'Aplicar vai alterar marcações que já estão gravadas. '
          'Só continue se a intenção for corrigir o lançamento.',
          style: const TextStyle(fontSize: 13, height: 1.5),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: Colors.orange[800]),
            child: const Text('Corrigir mesmo assim'),
          ),
        ],
      ),
    );
    return ok ?? false;
  }

  // ---------------------------------------------------------------------
  // UI
  // ---------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (widget.refId == null || widget.refId!.isEmpty) {
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
                      initialUrlRequest: URLRequest(url: WebUri(_siaEntrada)),
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
                    'Vá em 5. PRESENÇA e use o ícone de nuvem na chamada '
                    'que quer lançar. A presença fica na chamada, então é '
                    'por lá que se escolhe o que vai para o SIA.',
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
          if (_confirmado) ...[
            const Icon(Icons.verified, size: 40, color: Colors.green),
            const SizedBox(height: 12),
            Text(
              'Frequência da turma $_turmaFiltrada gravada no SIA.\n'
              'A chamada está marcada como transferida.',
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 12, height: 1.5),
            ),
            const SizedBox(height: 16),
            if (_foraDaTurma > 0) ...[
              Text(
                'Faltam $_foraDaTurma presentes de outra turma. '
                'Abra a pauta dela ao lado e sincronize sem fechar esta janela.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 11, color: Colors.orange[900]),
              ),
              const SizedBox(height: 12),
              ElevatedButton.icon(
                onPressed: _loading ? null : _prepararOutraTurma,
                icon: const Icon(Icons.sync),
                label: const Text('Ressincronizar outra turma'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.blue,
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
              ),
              const SizedBox(height: 8),
            ],
            OutlinedButton.icon(
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.check),
              label: const Text('Fechar'),
            ),
          ] else if (_aplicado) ...[
            const Icon(Icons.task_alt, size: 40, color: Colors.green),
            const SizedBox(height: 12),
            const Text(
              'Pauta marcada. Revise ao lado e confirme.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, height: 1.5),
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _loading ? null : _confirmarNoSia,
              icon: const Icon(Icons.send),
              label: const Text('Confirmar no SIA'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.green[700],
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
            const SizedBox(height: 8),
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
        if (_chamadaIntarq != null) ...[
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: _casouPorHeuristica ? Colors.amber[50] : Colors.blue[50],
              borderRadius: BorderRadius.circular(6),
              border: Border.all(
                color: _casouPorHeuristica
                    ? Colors.amber[300]!
                    : Colors.blue[100]!,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Chamada do INTARQ',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: Colors.blueGrey[700],
                  ),
                ),
                Text(
                  '${_chamadaIntarq!['data']} · '
                  'turma ${_chamadaIntarq!['class_group']} · '
                  '${_presencaIntarq?.length ?? 0} presentes',
                  style: const TextStyle(fontSize: 11),
                ),
                if (_casouPorHeuristica)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      'Esta chamada não estava ligada à aula: encontrei pela '
                      'disciplina e pela data. Confira se é a certa.',
                      style: TextStyle(
                        fontSize: 10,
                        color: Colors.amber[900],
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 12),
        ],
        if (_foraDaTurma > 0) ...[
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.blueGrey[50],
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              children: [
                Icon(Icons.filter_alt_outlined,
                    size: 16, color: Colors.blueGrey[700]),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Só a turma $_turmaFiltrada. Outros $_foraDaTurma '
                    'presentes desta chamada são de outra turma — lance a '
                    'pauta delas separadamente.',
                    style: const TextStyle(fontSize: 10),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
        ],
        if (_avisoSia.isNotEmpty) ...[
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.orange[50],
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: Colors.orange[300]!),
            ),
            child: Row(
              children: [
                Icon(Icons.warning_amber, size: 18, color: Colors.orange[800]),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _avisoSia,
                    style: TextStyle(
                      fontSize: 11,
                      color: Colors.orange[900],
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
        ],
        Expanded(
          child: ListView(
            children: [
              _grupo(
                comparacao.abonosARemover == 0
                    ? 'Marcar presente'
                    : 'Marcar presente '
                        '(${comparacao.abonosARemover} perdem o abono)',
                comparacao.marcar,
                Colors.green,
                Icons.add_task,
              ),
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

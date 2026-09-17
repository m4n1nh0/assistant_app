/// Acompanha a fila de quizzes e avisa quando uma geracao termina.
///
/// Roda enquanto o app esta aberto, independente de qual tela esta na frente:
/// o objetivo da fila e o professor pedir o quiz e seguir com a aula. Com pedido
/// ativo pergunta a cada poucos segundos; sem nenhum, espaca bastante.
///
/// Pedido que terminou com o app fechado tambem vira aviso na proxima abertura:
/// o estado "visto" mora no servidor, e so e marcado depois que o aviso sai.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'quiz_center_service.dart';

typedef QuizJobNotice = void Function(QuizJob job);

class QuizQueueWatcher {
  final QuizCenterService service;
  final Duration activeInterval;
  final Duration idleInterval;

  /// O que fazer com cada pedido terminado e ainda nao visto.
  QuizJobNotice? onFinished;

  /// Ultima leitura da fila, para a central e o contador de pendencias.
  final ValueNotifier<QuizJobsSnapshot> snapshot =
      ValueNotifier(const QuizJobsSnapshot());

  Timer? _timer;
  bool _running = false;
  bool _refreshing = false;
  final Set<String> _announced = {};

  QuizQueueWatcher({
    required this.service,
    this.onFinished,
    this.activeInterval = const Duration(seconds: 5),
    this.idleInterval = const Duration(seconds: 30),
  });

  bool get isRunning => _running;

  void start() {
    if (_running) return;
    _running = true;
    unawaited(refresh());
  }

  void stop() {
    _running = false;
    _timer?.cancel();
    _timer = null;
    _announced.clear();
    snapshot.value = const QuizJobsSnapshot();
  }

  /// Le a fila agora. Chamado tambem logo depois de enfileirar ou cancelar,
  /// para a central nao esperar o proximo ciclo.
  Future<void> refresh() async {
    if (_refreshing) return;
    _refreshing = true;
    try {
      final current = await service.listJobs();
      snapshot.value = current;
      await _announce(current);
    } catch (e) {
      // Servidor fora do ar nao pode derrubar o app: tenta de novo no ciclo.
      debugPrint('[QuizQueueWatcher] falha ao ler a fila: $e');
    } finally {
      _refreshing = false;
      _schedule();
    }
  }

  Future<void> _announce(QuizJobsSnapshot current) async {
    final novos = current.jobs
        .where((job) => job.needsNotice && !_announced.contains(job.id))
        .toList();
    if (novos.isEmpty) return;

    for (final job in novos) {
      _announced.add(job.id);
      try {
        onFinished?.call(job);
      } catch (e) {
        debugPrint('[QuizQueueWatcher] aviso falhou: $e');
      }
    }
    try {
      await service.markSeen(novos.map((job) => job.id).toList());
    } catch (_) {
      // Se nao marcou, o `_announced` segura a repeticao nesta sessao.
    }
  }

  void _schedule() {
    _timer?.cancel();
    if (!_running) return;
    final interval =
        snapshot.value.active > 0 ? activeInterval : idleInterval;
    _timer = Timer(interval, () => unawaited(refresh()));
  }
}

final quizQueueWatcher = QuizQueueWatcher(service: quizCenter);

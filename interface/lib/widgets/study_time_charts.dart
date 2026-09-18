/// Gráficos do painel de tempo de estudo, desenhados à mão.
///
/// Sem biblioteca de gráfico: o que o painel precisa é uma rosca e barras, e
/// uma dependência a mais custaria mais do que estas duas classes — ela viria
/// com tema próprio, que teria de ser dobrado no tema do app.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../services/study_time_stats.dart';
import '../utils/theme.dart';

/// Paleta estável por rótulo: a mesma turma recebe a mesma cor em todos os
/// gráficos da tela, que é o que permite ler a rosca e o ranking juntos.
class StudyTimePalette {
  static const _colors = [
    AssistantTheme.c1,
    AssistantTheme.c3,
    AssistantTheme.c2,
    Color(0xFFB07AFF),
    Color(0xFFFF8FA3),
    Color(0xFF7ED4E6),
    Color(0xFFE0B84A),
    Color(0xFF6EE7B7),
  ];

  final Map<String, Color> _byLabel;

  StudyTimePalette(Iterable<String> labels)
      : _byLabel = {
          for (final (index, label) in labels.indexed)
            label: label == semTurma
                ? AssistantTheme.textMuted
                : _colors[index % _colors.length],
        };

  Color of(String label) => _byLabel[label] ?? AssistantTheme.textMuted;
}

/// Rosca de participação. Fatia clicada vira filtro.
class StudyTimeDonut extends StatelessWidget {
  final List<StudyTimeEntry> entries;
  final StudyTimePalette palette;
  final String? selected;
  final ValueChanged<String>? onTap;
  final String centerLabel;
  final String centerValue;

  const StudyTimeDonut({
    super.key,
    required this.entries,
    required this.palette,
    required this.centerLabel,
    required this.centerValue,
    this.selected,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    if (entries.isEmpty) return const SizedBox.shrink();
    return LayoutBuilder(builder: (context, constraints) {
      final lado = math.min(constraints.maxWidth, 190.0);
      return Center(
        child: SizedBox(
          width: lado,
          height: lado,
          child: GestureDetector(
            onTapUp: onTap == null
                ? null
                : (details) {
                    final alvo = _sliceAt(details.localPosition, lado);
                    if (alvo != null) onTap!(alvo);
                  },
            child: CustomPaint(
              painter: _DonutPainter(
                entries: entries,
                palette: palette,
                selected: selected,
              ),
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(centerValue,
                        style: Theme.of(context).textTheme.headlineSmall),
                    Text(centerLabel,
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    });
  }

  /// Qual fatia está sob o toque. Devolve nulo no miolo e fora do círculo, para
  /// clique no vazio não virar filtro por acidente.
  String? _sliceAt(Offset position, double side) {
    final centro = Offset(side / 2, side / 2);
    final vetor = position - centro;
    final distancia = vetor.distance;
    final raio = side / 2;
    if (distancia > raio || distancia < raio * _DonutPainter.holeFactor) {
      return null;
    }
    var angulo = math.atan2(vetor.dy, vetor.dx) + math.pi / 2;
    if (angulo < 0) angulo += 2 * math.pi;

    final total = entries.fold<int>(0, (sum, e) => sum + e.minutes);
    if (total == 0) return null;
    var percorrido = 0.0;
    for (final entry in entries) {
      percorrido += entry.minutes / total * 2 * math.pi;
      if (angulo <= percorrido) return entry.id;
    }
    return entries.last.id;
  }
}

class _DonutPainter extends CustomPainter {
  static const holeFactor = 0.58;

  final List<StudyTimeEntry> entries;
  final StudyTimePalette palette;
  final String? selected;

  _DonutPainter({
    required this.entries,
    required this.palette,
    required this.selected,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final total = entries.fold<int>(0, (sum, e) => sum + e.minutes);
    if (total == 0) return;
    final centro = Offset(size.width / 2, size.height / 2);
    final raio = math.min(size.width, size.height) / 2;
    final largura = raio * (1 - holeFactor);
    var inicio = -math.pi / 2;

    for (final entry in entries) {
      final varredura = entry.minutes / total * 2 * math.pi;
      final destacada = selected == null || selected == entry.id;
      final pincel = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = largura
        ..color = destacada
            ? palette.of(entry.label)
            : palette.of(entry.label).withValues(alpha: 0.25);
      canvas.drawArc(
        Rect.fromCircle(center: centro, radius: raio - largura / 2),
        inicio,
        // A folga evita que fatias vizinhas de cor parecida virem um bloco só.
        math.max(varredura - 0.012, 0.004),
        false,
        pincel,
      );
      inicio += varredura;
    }
  }

  @override
  bool shouldRepaint(_DonutPainter old) =>
      old.entries != entries || old.selected != selected;
}

/// Legenda clicável de uma paleta, com valor e fatia de cada item.
class StudyTimeLegend extends StatelessWidget {
  final List<StudyTimeEntry> entries;
  final StudyTimePalette palette;
  final String? selected;
  final ValueChanged<String>? onTap;

  const StudyTimeLegend({
    super.key,
    required this.entries,
    required this.palette,
    this.selected,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final entry in entries)
          InkWell(
            onTap: onTap == null ? null : () => onTap!(entry.id),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(children: [
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    color: palette.of(entry.label),
                    borderRadius: BorderRadius.circular(3),
                    border: selected == entry.id
                        ? Border.all(color: AssistantTheme.textPrimary, width: 2)
                        : null,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(entry.label,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodyMedium),
                ),
                const SizedBox(width: 8),
                Text('${entry.hours.toStringAsFixed(1)} h',
                    style: Theme.of(context).textTheme.bodyMedium),
                const SizedBox(width: 8),
                SizedBox(
                  width: 38,
                  child: Text('${(entry.share * 100).toStringAsFixed(0)}%',
                      textAlign: TextAlign.right,
                      style: Theme.of(context).textTheme.bodySmall),
                ),
              ]),
            ),
          ),
      ],
    );
  }
}

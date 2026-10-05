/// Painel que mostra se a gravação está de fato captando áudio: medidor de nível ao
/// vivo, seletor de dispositivo e a lista dos blocos gravados com o resultado de cada
/// um (nível, enviado, sem fala), onde dá para ouvir e reenviar.
///
/// "Nenhuma fala reconhecida" sozinho não diz se o microfone estava mudo ou se o
/// reconhecimento não entendeu; o nível de cada bloco separa uma coisa da outra.
library;

import 'dart:math' as math;

import 'package:flutter/foundation.dart' show ValueListenable;

import 'package:flutter/material.dart';
import 'package:record/record.dart';

import '../services/lesson_recovery_service.dart';
import '../utils/theme.dart';

/// O que se mede de cada origem. Zero é silêncio; 1 é o máximo do formato.
class LevelReading {
  final double mic;
  final double system;

  const LevelReading({this.mic = 0, this.system = 0});
}

enum LevelKind { silent, low, good, hot }

/// Faixas em dBFS. Fala normal a uma distância razoável fica entre -30 e -10; abaixo
/// de -60 é dispositivo sem sinal (mudo, desconectado), e acima de -3 distorce.
LevelKind classifyLevel(double peak) {
  final db = peakToDb(peak);
  if (db < -60) return LevelKind.silent;
  if (db < -30) return LevelKind.low;
  if (db < -3) return LevelKind.good;
  return LevelKind.hot;
}

String levelLabel(LevelKind kind) {
  switch (kind) {
    case LevelKind.silent:
      return 'SEM SINAL';
    case LevelKind.low:
      return 'BAIXO';
    case LevelKind.good:
      return 'BOM';
    case LevelKind.hot:
      return 'ALTO DEMAIS';
  }
}

Color levelColor(LevelKind kind) {
  switch (kind) {
    case LevelKind.silent:
      return AssistantTheme.danger;
    case LevelKind.low:
      return AssistantTheme.c4;
    case LevelKind.good:
      return AssistantTheme.c3;
    case LevelKind.hot:
      return AssistantTheme.danger;
  }
}

/// "-23 dB", ou "sem sinal" quando nem aparece no medidor.
String dbText(double peak) {
  final db = peakToDb(peak);
  return db <= -90 ? 'sem sinal' : '${db.round()} dB';
}

/// Barra de nível: cheia em 0 dB, vazia em -60 dB.
class InputLevelMeter extends StatelessWidget {
  final String label;
  final double peak;

  const InputLevelMeter({super.key, required this.label, required this.peak});

  @override
  Widget build(BuildContext context) {
    final kind = classifyLevel(peak);
    final color = levelColor(kind);
    final fill = ((peakToDb(peak) + 60) / 60).clamp(0.0, 1.0);
    return Row(
      children: [
        SizedBox(
          width: 118,
          child: Text(
            label,
            style: const TextStyle(fontSize: 11, color: AssistantTheme.textSecondary),
          ),
        ),
        Expanded(
          child: Container(
            height: 9,
            decoration: BoxDecoration(
              color: AssistantTheme.surface2,
              border: Border.all(color: AssistantTheme.border),
              borderRadius: BorderRadius.circular(2),
            ),
            alignment: Alignment.centerLeft,
            child: FractionallySizedBox(
              widthFactor: fill,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 120),
                decoration: BoxDecoration(
                  color: color,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          width: 118,
          child: Text(
            '${dbText(peak)}  ${levelLabel(kind)}',
            textAlign: TextAlign.right,
            style: TextStyle(fontSize: 10, color: color),
          ),
        ),
      ],
    );
  }
}

/// Medidor ao vivo, dispositivo de entrada e o estado do bloco em gravação.
class RecordingMonitor extends StatelessWidget {
  final ValueListenable<LevelReading> level;

  /// Mostra a barra do som do computador (reunião online).
  final bool showSystem;
  final bool recording;

  final List<InputDevice> devices;

  /// Id do dispositivo escolhido; vazio é o padrão do sistema.
  final String selectedId;
  final String selectedLabel;
  final ValueChanged<InputDevice?> onSelectDevice;
  final VoidCallback onRefreshDevices;
  final bool busy;

  /// Há quanto tempo não chega som nenhum; `null` quando está chegando.
  final Duration? silentFor;

  /// Tempo e tamanho do bloco que está sendo gravado.
  final Duration blockElapsed;
  final int blockBytes;

  /// O que dizer enquanto não está gravando; vazio usa o texto de pausa.
  final String? idleHint;

  const RecordingMonitor({
    super.key,
    required this.level,
    required this.recording,
    required this.devices,
    required this.selectedId,
    required this.onSelectDevice,
    required this.onRefreshDevices,
    this.showSystem = false,
    this.selectedLabel = '',
    this.busy = false,
    this.silentFor,
    this.blockElapsed = Duration.zero,
    this.blockBytes = 0,
    this.idleHint,
  });

  static String _bytes(int bytes) => bytes < 1024 * 1024
      ? '${(bytes / 1024).round()} KB'
      : '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';

  @override
  Widget build(BuildContext context) {
    final saved = selectedId.isNotEmpty &&
        !devices.any((device) => device.id == selectedId);
    final warning = silentFor;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 9, 12, 9),
      decoration: BoxDecoration(
        color: AssistantTheme.surface2,
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.graphic_eq, size: 14, color: AssistantTheme.c1),
              const SizedBox(width: 6),
              const Text(
                'ÁUDIO',
                style: TextStyle(
                  fontSize: 10,
                  letterSpacing: 1.4,
                  color: AssistantTheme.textMuted,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    isExpanded: true,
                    isDense: true,
                    value: selectedId,
                    style: const TextStyle(
                        fontSize: 11, color: AssistantTheme.textPrimary),
                    items: [
                      const DropdownMenuItem(
                        value: '',
                        child: Text('Microfone padrão do Windows'),
                      ),
                      for (final device in devices)
                        DropdownMenuItem(
                          value: device.id,
                          child: Text(
                            device.label.trim().isEmpty
                                ? 'Microfone'
                                : device.label.trim(),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      if (saved)
                        DropdownMenuItem(
                          value: selectedId,
                          child: Text(
                            '${selectedLabel.isEmpty ? "Microfone escolhido" : selectedLabel} (indisponível)',
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: busy
                        ? null
                        : (value) {
                            if (value == null) return;
                            if (value.isEmpty) {
                              onSelectDevice(null);
                              return;
                            }
                            for (final device in devices) {
                              if (device.id == value) {
                                onSelectDevice(device);
                                return;
                              }
                            }
                          },
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Atualizar a lista de microfones',
                visualDensity: VisualDensity.compact,
                icon: const Icon(Icons.refresh, size: 16),
                onPressed: busy ? null : onRefreshDevices,
              ),
            ],
          ),
          const SizedBox(height: 6),
          ValueListenableBuilder<LevelReading>(
            valueListenable: level,
            builder: (context, reading, _) => Column(
              children: [
                InputLevelMeter(
                  label: showSystem ? 'Seu microfone' : 'Microfone',
                  peak: recording ? reading.mic : 0,
                ),
                if (showSystem) ...[
                  const SizedBox(height: 4),
                  InputLevelMeter(
                    label: 'Som do computador',
                    peak: recording ? reading.system : 0,
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 6),
          Text(
            recording
                ? 'Bloco atual: ${blockElapsed.inMinutes}:'
                    '${(blockElapsed.inSeconds % 60).toString().padLeft(2, "0")}'
                    // O tamanho só aparece quando o arquivo já cresceu: sem isso um
                    // gravador que escreve no fim pareceria não estar gravando.
                    '${blockBytes > 44 ? " · ${_bytes(blockBytes)} gravados" : ""}'
                : (idleHint ??
                    'Gravação pausada: o medidor volta quando a gravação voltar.'),
            style: const TextStyle(fontSize: 10, color: AssistantTheme.textMuted),
          ),
          if (recording && warning != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.mic_off_outlined,
                      size: 13, color: AssistantTheme.danger),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Nenhum som chegou nos últimos ${warning.inSeconds} s. '
                      'Fale perto do microfone; se o medidor não se mexer, '
                      'escolha outro dispositivo acima (ou clique em atualizar).',
                      style: const TextStyle(
                          fontSize: 10, color: AssistantTheme.danger),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Rótulo e cor do estado de um bloco.
({String label, Color color}) chunkStatus(StoredChunk chunk, {bool live = false}) {
  if (live) return (label: 'GRAVANDO', color: AssistantTheme.c1);
  switch (chunk.state) {
    case ChunkState.sent:
      return (label: 'TRANSCRITO', color: AssistantTheme.c3);
    case ChunkState.quiet:
      return (label: 'SEM FALA', color: AssistantTheme.c4);
    case ChunkState.pending:
      return chunk.detail.isEmpty
          ? (label: 'AGUARDANDO', color: AssistantTheme.textMuted)
          : (label: 'FALHOU', color: AssistantTheme.danger);
  }
}

/// O que dizer de um bloco que voltou sem fala, a partir do nível que ele tinha.
String? quietExplanation(StoredChunk chunk) {
  if (chunk.state != ChunkState.quiet || chunk.peak == null) return null;
  switch (classifyLevel(chunk.peak!)) {
    case LevelKind.silent:
      return 'O bloco chegou sem sinal: o problema está na captura (microfone '
          'mudo, dispositivo errado ou desconectado).';
    case LevelKind.low:
      return 'O som estava muito baixo: aproxime o microfone ou aumente o '
          'volume de entrada no Windows.';
    default:
      return 'Havia som no bloco, mas o reconhecimento não entendeu fala. Dá para '
          'ouvir e reenviar.';
  }
}

String _clock(DateTime time) =>
    '${time.hour.toString().padLeft(2, "0")}:'
    '${time.minute.toString().padLeft(2, "0")}:'
    '${time.second.toString().padLeft(2, "0")}';

/// Lista dos blocos gravados da aula, com o resultado de cada um.
class ChunkList extends StatelessWidget {
  final List<StoredChunk> chunks;

  /// Arquivo que está sendo gravado agora: não dá para ouvir nem reenviar.
  final String? livePath;
  final String? playingPath;
  final StoredAudioUsage usage;

  final ValueChanged<StoredChunk> onPlay;
  final ValueChanged<StoredChunk> onResend;
  final VoidCallback onOpenFolder;
  final VoidCallback onClear;

  const ChunkList({
    super.key,
    required this.chunks,
    required this.usage,
    required this.onPlay,
    required this.onResend,
    required this.onOpenFolder,
    required this.onClear,
    this.livePath,
    this.playingPath,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
      decoration: BoxDecoration(
        color: AssistantTheme.surface2,
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'BLOCOS GRAVADOS (${chunks.length})',
                  style: const TextStyle(
                    fontSize: 10,
                    letterSpacing: 1.4,
                    color: AssistantTheme.textMuted,
                  ),
                ),
              ),
              TextButton.icon(
                onPressed: onOpenFolder,
                icon: const Icon(Icons.folder_open, size: 14),
                label: const Text('ABRIR PASTA', style: TextStyle(fontSize: 10)),
              ),
              TextButton.icon(
                onPressed: usage.chunks == 0 ? null : onClear,
                icon: const Icon(Icons.delete_sweep_outlined, size: 14),
                label: Text(
                  'LIMPAR ENTREGUES (${usage.chunks} · ${usage.sizeLabel})',
                  style: const TextStyle(fontSize: 10),
                ),
              ),
            ],
          ),
          if (chunks.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 6),
              child: Text(
                'Nenhum bloco gravado ainda. O primeiro aparece quando o '
                'primeiro minuto fechar.',
                style: TextStyle(fontSize: 10, color: AssistantTheme.textMuted),
              ),
            ),
          for (var i = chunks.length - 1; i >= 0; i--) _row(i, chunks[i]),
        ],
      ),
    );
  }

  Widget _row(int index, StoredChunk chunk) {
    final live = livePath != null && chunk.file.path == livePath;
    final status = chunkStatus(chunk, live: live);
    final explanation = live ? null : quietExplanation(chunk);
    final playing = playingPath == chunk.file.path;
    final seconds = (chunk.durationMs / 1000).round();
    final level = chunk.peak == null
        ? null
        : '${dbText(chunk.peak!)} · ${levelLabel(classifyLevel(chunk.peak!)).toLowerCase()}';

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              SizedBox(
                width: 26,
                child: Text(
                  '#${index + 1}',
                  style: const TextStyle(
                      fontSize: 11, color: AssistantTheme.textMuted),
                ),
              ),
              SizedBox(
                width: 62,
                child: Text(
                  _clock(chunk.startedAt),
                  style: const TextStyle(
                      fontSize: 11, color: AssistantTheme.textSecondary),
                ),
              ),
              SizedBox(
                width: 50,
                child: Text(
                  live ? '...' : '${seconds}s',
                  style: const TextStyle(
                      fontSize: 11, color: AssistantTheme.textSecondary),
                ),
              ),
              Expanded(
                child: Text(
                  [
                    if (level != null) 'nível $level',
                    if (chunk.micPeak != null && chunk.systemPeak != null)
                      'mic ${dbText(chunk.micPeak!)} · som do PC ${dbText(chunk.systemPeak!)}',
                  ].join('  ·  '),
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 10,
                    color: chunk.peak == null
                        ? AssistantTheme.textMuted
                        : levelColor(classifyLevel(chunk.peak!)),
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: status.color.withValues(alpha: 0.12),
                  border: Border.all(color: status.color.withValues(alpha: 0.5)),
                  borderRadius: BorderRadius.circular(2),
                ),
                child: Text(
                  status.label,
                  style: TextStyle(fontSize: 9, color: status.color),
                ),
              ),
              IconButton(
                tooltip: playing ? 'Parar' : 'Ouvir este bloco',
                visualDensity: VisualDensity.compact,
                icon: Icon(playing ? Icons.stop_circle_outlined : Icons.play_circle_outline,
                    size: 18),
                onPressed: live ? null : () => onPlay(chunk),
              ),
              IconButton(
                tooltip: 'Reenviar para transcrição',
                visualDensity: VisualDensity.compact,
                icon: const Icon(Icons.replay, size: 17),
                onPressed: live || chunk.state == ChunkState.sent
                    ? null
                    : () => onResend(chunk),
              ),
            ],
          ),
          if (explanation != null)
            Padding(
              padding: const EdgeInsets.only(left: 26, bottom: 2),
              child: Text(
                explanation,
                style: const TextStyle(fontSize: 10, color: AssistantTheme.c4),
              ),
            ),
          if (!live && chunk.state == ChunkState.pending && chunk.detail.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 26, bottom: 2),
              child: Text(
                'Último erro: ${chunk.detail}',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 10, color: AssistantTheme.danger),
              ),
            ),
        ],
      ),
    );
  }
}

/// Converte amplitude em dBFS (o que o plugin de gravação informa) em escala linear.
double dbToPeak(double db) =>
    db <= -120 ? 0 : math.min(1.0, math.pow(10, db / 20).toDouble());

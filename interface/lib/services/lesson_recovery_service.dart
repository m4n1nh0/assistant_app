/// Guarda os blocos de áudio de uma aula em disco, com o resultado de cada um, e
/// recupera o que sobrou de uma gravação interrompida.
///
/// Cada bloco de 60 s vive numa pasta própria da aula (`lesson_chunks/<id da aula>`),
/// dentro da pasta de dados do app e não na temporária do sistema, que a limpeza do
/// Windows pode esvaziar. O bloco **não é apagado quando o servidor o aceita**: fica
/// guardado até o professor encerrar a aula e decidir limpar. É isso que permite
/// ouvir um bloco que voltou sem fala, ver o nível de áudio que ele tinha e reenviá-lo
/// - e que protege a aula de uma queda do app.
///
/// O estado do bloco vai no prefixo do nome, que sobrevive a qualquer queda:
/// `chunk_` ainda não foi aceito pelo servidor, `sent_` foi transcrito e `quiet_`
/// foi aceito mas sem fala reconhecida. Os detalhes (nível, motivo) ficam num
/// `manifest.json` ao lado, que é só informação: se faltar, nada se perde.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';

enum ChunkState {
  /// Gravado e ainda não aceito pelo servidor (ou o envio falhou).
  pending('chunk'),

  /// Aceito e transcrito.
  sent('sent'),

  /// Aceito, mas o servidor não reconheceu fala nele.
  quiet('quiet');

  final String prefix;
  const ChunkState(this.prefix);

  static ChunkState? fromPrefix(String prefix) {
    for (final state in values) {
      if (state.prefix == prefix) return state;
    }
    return null;
  }
}

/// Nível de áudio em dBFS (0 é o máximo; silêncio absoluto vira -120).
double peakToDb(double peak) => peak <= 0
    ? -120
    : (20 * math.log(peak) / math.ln10).clamp(-120, 0).toDouble();

/// Um bloco de áudio guardado.
class RecoverableChunk {
  final File file;
  final int bytes;

  /// Quando o bloco começou a ser gravado, pelo nome do arquivo.
  final DateTime startedAt;

  const RecoverableChunk({
    required this.file,
    required this.bytes,
    required this.startedAt,
  });

  String get name => file.path.split(Platform.pathSeparator).last;

  bool get isWav => name.toLowerCase().endsWith('.wav');

  /// Duração estimada. O WAV de 16 kHz mono de 16 bits ocupa 32 000 bytes por
  /// segundo; outro formato não dá para medir pelo tamanho e vale o bloco inteiro.
  int get durationMs {
    if (!isWav) return 60000;
    return (((bytes - 44).clamp(0, bytes)) / 32).round();
  }
}

/// Bloco guardado com tudo o que se sabe dele, para a lista da tela.
class StoredChunk extends RecoverableChunk {
  final ChunkState state;

  /// Maior amplitude (0 a 1) do bloco inteiro, medida no arquivo.
  final double? peak;

  /// Picos do microfone e do som do computador (reunião online).
  final double? micPeak;
  final double? systemPeak;

  /// Por que o servidor ignorou o bloco, ou o erro do último envio.
  final String detail;

  const StoredChunk({
    required super.file,
    required super.bytes,
    required super.startedAt,
    required this.state,
    this.peak,
    this.micPeak,
    this.systemPeak,
    this.detail = '',
  });

  double? get peakDb => peak == null ? null : peakToDb(peak!);
}

/// As gravações de uma aula que ficaram para trás.
class RecoverableLesson {
  final String lessonId;
  final List<RecoverableChunk> chunks;

  const RecoverableLesson({required this.lessonId, required this.chunks});

  int get totalBytes => chunks.fold(0, (sum, chunk) => sum + chunk.bytes);

  int get approxSeconds =>
      (chunks.fold<int>(0, (sum, chunk) => sum + chunk.durationMs) / 1000)
          .round();
}

/// Quanto áudio já entregue está guardado no computador.
class StoredAudioUsage {
  final int chunks;
  final int bytes;

  /// Blocos que ainda não foram aceitos: ficam mesmo depois de limpar.
  final int pending;

  const StoredAudioUsage({this.chunks = 0, this.bytes = 0, this.pending = 0});

  bool get isEmpty => chunks == 0 && pending == 0;

  String get sizeLabel {
    if (bytes < 1024 * 1024) return '${(bytes / 1024).round()} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}

/// O que o servidor fez com um bloco: aceitou com texto ou sem fala.
class ChunkDelivery {
  final bool quiet;
  final String detail;

  const ChunkDelivery({this.quiet = false, this.detail = ''});
}

/// O que aconteceu ao reenviar uma aula.
class RecoveryResult {
  final int sent;
  final int remaining;

  /// Por que parou; `null` quando enviou tudo.
  final Object? error;

  const RecoveryResult({required this.sent, required this.remaining, this.error});

  bool get complete => error == null && remaining == 0;
}

/// Envia um bloco ao servidor; levanta a exceção quando não conseguir. Devolve o
/// que o servidor fez com ele, ou `null` quando só foi aceito.
typedef ChunkUploader = Future<ChunkDelivery?> Function(
  RecoverableChunk chunk,
  Uint8List bytes,
);

class LessonRecoveryService {
  final Future<Directory> Function() _root;

  /// Serializa as escritas no manifesto: o timer de blocos e o envio chegam juntos.
  Future<void> _manifestQueue = Future.value();

  /// `root` troca a pasta base nos testes.
  LessonRecoveryService({Future<Directory> Function()? root})
      : _root = root ?? _defaultRoot;

  static Future<Directory> _defaultRoot() async {
    final support = await getApplicationSupportDirectory();
    return Directory('${support.path}${Platform.pathSeparator}lesson_chunks');
  }

  static final _chunkName = RegExp(r'^(chunk|sent|quiet)_(\d+)\.(wav|m4a)$');
  static final _safeId = RegExp(r'[^A-Za-z0-9_-]');

  /// O id vira nome de pasta: nada de separador de caminho nem ponto.
  static String safeId(String lessonId) => lessonId.replaceAll(_safeId, '_');

  Future<Directory> _lessonDir(String lessonId) async {
    final root = await _root();
    return Directory('${root.path}${Platform.pathSeparator}${safeId(lessonId)}');
  }

  /// Pasta onde os blocos da aula ficam; útil para o professor abrir no Explorer.
  Future<Directory> folderOf(String lessonId) => _lessonDir(lessonId);

  /// Caminho do próximo bloco da aula; a pasta é criada se não existir.
  Future<String> newChunkPath(String lessonId, String extension) async {
    final dir = await _lessonDir(lessonId);
    await dir.create(recursive: true);
    return '${dir.path}${Platform.pathSeparator}'
        'chunk_${DateTime.now().millisecondsSinceEpoch}.$extension';
  }

  static ({ChunkState state, int stamp, String ext})? _parse(String name) {
    final match = _chunkName.firstMatch(name);
    if (match == null) return null;
    return (
      state: ChunkState.fromPrefix(match.group(1)!)!,
      stamp: int.parse(match.group(2)!),
      ext: match.group(3)!,
    );
  }

  static String _nameOf(FileSystemEntity entity) =>
      entity.path.split(Platform.pathSeparator).last;

  /// Hora de início do bloco, pelo nome do arquivo (`null` se não for um bloco).
  static int? stampOf(String path) =>
      _parse(path.split(Platform.pathSeparator).last)?.stamp;

  // --- varredura ----------------------------------------------------------

  /// Aulas com áudio **ainda não aceito pelo servidor**. `ignoreLessonId` é a aula
  /// que está gravando agora: os arquivos dela estão em uso e não são sobra de nada.
  ///
  /// Arquivo só com o cabeçalho (nada foi captado) é apagado na hora, e pasta que
  /// ficou vazia some.
  Future<List<RecoverableLesson>> scan({String? ignoreLessonId}) async {
    final root = await _root();
    if (!await root.exists()) return const [];
    final ignored = ignoreLessonId == null ? null : safeId(ignoreLessonId);

    final lessons = <RecoverableLesson>[];
    for (final entry in await root.list().toList()) {
      if (entry is! Directory) continue;
      final id = _nameOf(entry);
      if (id == ignored) continue;

      final chunks = <RecoverableChunk>[];
      var anyFile = false;
      for (final item in await entry.list().toList()) {
        if (item is! File) continue;
        final parsed = _parse(_nameOf(item));
        if (parsed == null) continue;
        if (parsed.state != ChunkState.pending) {
          anyFile = true; // bloco ja entregue: a pasta serve de historico
          continue;
        }
        final size = await item.length();
        if (size <= 44) {
          await _delete(item);
          continue;
        }
        anyFile = true;
        chunks.add(RecoverableChunk(
          file: item,
          bytes: size,
          startedAt: DateTime.fromMillisecondsSinceEpoch(parsed.stamp),
        ));
      }

      if (chunks.isEmpty) {
        if (!anyFile) await _deleteDirIfEmpty(entry);
        continue;
      }
      chunks.sort((a, b) => a.startedAt.compareTo(b.startedAt));
      lessons.add(RecoverableLesson(lessonId: id, chunks: chunks));
    }
    lessons.sort((a, b) =>
        a.chunks.first.startedAt.compareTo(b.chunks.first.startedAt));
    return lessons;
  }

  /// Todos os blocos da aula, de qualquer estado, em ordem de gravação, com o que o
  /// manifesto sabe de cada um.
  Future<List<StoredChunk>> chunksOf(String lessonId) async {
    final dir = await _lessonDir(lessonId);
    if (!await dir.exists()) return const [];
    final manifest = await _readManifest(dir);

    final chunks = <StoredChunk>[];
    for (final item in await dir.list().toList()) {
      if (item is! File) continue;
      final parsed = _parse(_nameOf(item));
      if (parsed == null) continue;
      final info = manifest['${parsed.stamp}'] as Map? ?? const {};
      chunks.add(StoredChunk(
        file: item,
        bytes: await item.length(),
        startedAt: DateTime.fromMillisecondsSinceEpoch(parsed.stamp),
        state: parsed.state,
        peak: (info['peak'] as num?)?.toDouble(),
        micPeak: (info['micPeak'] as num?)?.toDouble(),
        systemPeak: (info['systemPeak'] as num?)?.toDouble(),
        detail: info['detail']?.toString() ?? '',
      ));
    }
    chunks.sort((a, b) => a.startedAt.compareTo(b.startedAt));
    return chunks;
  }

  // --- manifesto ----------------------------------------------------------

  Future<Map<String, dynamic>> _readManifest(Directory dir) async {
    try {
      final file = File('${dir.path}${Platform.pathSeparator}manifest.json');
      if (!await file.exists()) return {};
      final decoded = jsonDecode(await file.readAsString());
      return decoded is Map<String, dynamic> ? decoded : {};
    } catch (_) {
      // Manifesto ilegível (queda no meio da escrita): o áudio não depende dele.
      return {};
    }
  }

  Future<void> _updateManifest(
    String lessonId,
    int stamp,
    Map<String, Object?> fields,
  ) {
    final job = _manifestQueue.then((_) async {
      try {
        final dir = await _lessonDir(lessonId);
        if (!await dir.exists()) return;
        final manifest = await _readManifest(dir);
        final current = Map<String, dynamic>.from(
          manifest['$stamp'] as Map? ?? const {},
        );
        fields.forEach((key, value) {
          if (value != null) current[key] = value;
        });
        manifest['$stamp'] = current;
        final file = File('${dir.path}${Platform.pathSeparator}manifest.json');
        await file.writeAsString(jsonEncode(manifest));
      } catch (_) {
        // Detalhe é cortesia: não pode derrubar a gravação.
      }
    });
    _manifestQueue = job;
    return job;
  }

  /// Anota o que se sabe do bloco que acabou de fechar.
  Future<void> noteChunk(
    String lessonId,
    String path, {
    double? peak,
    double? micPeak,
    double? systemPeak,
  }) async {
    final stamp = stampOf(path);
    if (stamp == null) return;
    await _updateManifest(lessonId, stamp, {
      'peak': peak,
      'micPeak': micPeak,
      'systemPeak': systemPeak,
    });
  }

  /// Registra o que o servidor fez com o bloco e o renomeia para o estado novo.
  /// Devolve o arquivo com o nome novo (o antigo deixa de existir).
  Future<File> markResult(
    String lessonId,
    File file, {
    required ChunkState state,
    String detail = '',
  }) async {
    final parsed = _parse(_nameOf(file));
    if (parsed == null) return file;
    var result = file;
    if (parsed.state != state) {
      result = await file.rename(
        '${file.parent.path}${Platform.pathSeparator}'
        '${state.prefix}_${parsed.stamp}.${parsed.ext}',
      );
    }
    await _updateManifest(lessonId, parsed.stamp, {
      'detail': detail,
      'updatedAt': DateTime.now().toIso8601String(),
    });
    return result;
  }

  /// Anota por que um envio falhou, sem mudar o estado do bloco.
  Future<void> noteFailure(String lessonId, String path, String detail) async {
    final stamp = stampOf(path);
    if (stamp == null) return;
    await _updateManifest(lessonId, stamp, {'detail': detail});
  }

  /// Volta um bloco aceito sem fala para a fila de envio.
  Future<File> requeue(String lessonId, File file) =>
      markResult(lessonId, file, state: ChunkState.pending, detail: '');

  // --- limpeza ------------------------------------------------------------

  /// Quanto áudio já entregue está guardado (de uma aula ou de todas).
  Future<StoredAudioUsage> usage({String? lessonId}) async {
    final root = await _root();
    if (!await root.exists()) return const StoredAudioUsage();
    var chunks = 0, bytes = 0, pending = 0;

    for (final entry in await root.list().toList()) {
      if (entry is! Directory) continue;
      if (lessonId != null && _nameOf(entry) != safeId(lessonId)) continue;
      for (final item in await entry.list().toList()) {
        if (item is! File) continue;
        final parsed = _parse(_nameOf(item));
        if (parsed == null) continue;
        if (parsed.state == ChunkState.pending) {
          pending++;
        } else {
          chunks++;
          bytes += await item.length();
        }
      }
    }
    return StoredAudioUsage(chunks: chunks, bytes: bytes, pending: pending);
  }

  /// Apaga o áudio **já entregue** (`sent_` e `quiet_`). O que ainda não foi aceito
  /// pelo servidor nunca é apagado por aqui: seria perder fala que ninguém ouviu.
  /// Sem `lessonId`, vale para todas as aulas. Devolve quantos blocos saíram.
  Future<int> clearDelivered({String? lessonId}) async {
    final root = await _root();
    if (!await root.exists()) return 0;
    var removed = 0;

    for (final entry in await root.list().toList()) {
      if (entry is! Directory) continue;
      if (lessonId != null && _nameOf(entry) != safeId(lessonId)) continue;
      var kept = false;
      for (final item in await entry.list().toList()) {
        if (item is! File) continue;
        final parsed = _parse(_nameOf(item));
        if (parsed == null) continue;
        if (parsed.state == ChunkState.pending) {
          kept = true;
          continue;
        }
        await _delete(item);
        removed++;
      }
      if (!kept) {
        try {
          if (await entry.exists()) await entry.delete(recursive: true);
        } catch (_) {
          // Pasta em uso: a próxima limpeza resolve.
        }
      }
    }
    return removed;
  }

  // --- recuperação --------------------------------------------------------

  /// Reenvia os blocos da aula, em ordem. Para no primeiro que falhar e deixa o
  /// resto como estava. O que subiu **fica guardado** como entregue.
  ///
  /// A ordem importa: o servidor tira a sobreposição entre um bloco e o anterior.
  Future<RecoveryResult> recover(
    RecoverableLesson lesson,
    ChunkUploader upload,
  ) async {
    var sent = 0;
    for (final chunk in lesson.chunks) {
      ChunkDelivery? delivery;
      try {
        final raw = await chunk.file.readAsBytes();
        final bytes = chunk.isWav ? repairWavHeader(raw) : raw;
        delivery = await upload(chunk, bytes);
      } catch (error) {
        await noteFailure(lesson.lessonId, chunk.file.path, '$error');
        return RecoveryResult(
          sent: sent,
          remaining: lesson.chunks.length - sent,
          error: error,
        );
      }
      await markResult(
        lesson.lessonId,
        chunk.file,
        state: (delivery?.quiet ?? false) ? ChunkState.quiet : ChunkState.sent,
        detail: delivery?.detail ?? '',
      );
      sent++;
    }
    return RecoveryResult(sent: sent, remaining: 0);
  }

  /// Apaga todo o áudio guardado da aula, inclusive o que não foi enviado.
  Future<void> discard(String lessonId) async {
    final dir = await _lessonDir(lessonId);
    if (await dir.exists()) await dir.delete(recursive: true);
  }

  Future<void> _delete(File file) async {
    try {
      if (await file.exists()) await file.delete();
    } catch (_) {
      // Arquivo em uso ou já removido: a próxima varredura tenta de novo.
    }
  }

  Future<void> _deleteDirIfEmpty(Directory dir) async {
    try {
      if (await dir.exists() && await dir.list().isEmpty) await dir.delete();
    } catch (_) {
      // Sobra de pasta vazia não atrapalha ninguém.
    }
  }

  // --- WAV ----------------------------------------------------------------

  /// Maior amplitude (0 a 1) de um WAV de 16 bits; `null` se não for um.
  static double? wavPeak(Uint8List input) {
    final data = _dataOffset(input);
    if (data == null) return null;
    final end = input.length - ((input.length - data) % 2);
    final view = ByteData.sublistView(input);
    var peak = 0;
    for (var at = data; at < end; at += 2) {
      final sample = view.getInt16(at, Endian.little).abs();
      if (sample > peak) peak = sample;
    }
    return peak / 32768.0;
  }

  /// Onde começam os dados do WAV (depois da etiqueta `data` e do tamanho).
  static int? _dataOffset(Uint8List input) {
    if (input.length < 12 ||
        String.fromCharCodes(input.sublist(0, 4)) != 'RIFF' ||
        String.fromCharCodes(input.sublist(8, 12)) != 'WAVE') {
      return null;
    }
    var offset = 12;
    while (offset + 8 <= input.length) {
      final tag = String.fromCharCodes(input.sublist(offset, offset + 4));
      if (tag == 'data') return offset + 8;
      final size = ByteData.sublistView(input, offset + 4, offset + 8)
          .getUint32(0, Endian.little);
      final next = offset + 8 + size + (size.isOdd ? 1 : 0);
      if (size == 0xFFFFFFFF || next <= offset || next > input.length) break;
      offset = next;
    }
    return null;
  }

  /// Corrige os tamanhos do cabeçalho de um WAV que a queda deixou incompleto.
  ///
  /// Quem grava só fecha o cabeçalho ao terminar; com o processo morto, os campos
  /// de tamanho ficam zerados ou desatualizados, e um leitor que confia neles lê
  /// zero amostras. Aqui os dois tamanhos passam a refletir o que há no arquivo.
  /// Qualquer coisa que não seja um WAV reconhecível volta como estava.
  static Uint8List repairWavHeader(Uint8List input) {
    final data = _dataOffset(input);
    if (data == null) return input;
    final dataTag = data - 8;

    var length = input.length;
    // Amostra de 16 bits: um byte solto no fim é a escrita cortada ao meio.
    if ((length - data).isOdd) length -= 1;
    final dataSize = length - data;

    final out = Uint8List.fromList(input.sublist(0, length));
    final view = ByteData.sublistView(out);
    view.setUint32(4, length - 8, Endian.little);
    view.setUint32(dataTag + 4, dataSize, Endian.little);
    return out;
  }
}

final lessonRecovery = LessonRecoveryService();

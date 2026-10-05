/// Guarda os blocos de áudio de uma aula em disco e recupera o que sobrou de uma
/// gravação interrompida.
///
/// Cada bloco de 60 s vive numa pasta própria da aula (`lesson_chunks/<id da aula>`),
/// dentro da pasta de dados do app e não na temporária do sistema, que a limpeza do
/// Windows pode esvaziar. Quando o app cai no meio da aula, o que estava na fila de
/// envio some da memória, mas os arquivos ficam; o nome da pasta diz a que aula eles
/// pertencem, e ao reabrir o app oferece enviá-los.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';

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

/// O que aconteceu ao reenviar uma aula.
class RecoveryResult {
  final int sent;
  final int remaining;

  /// Por que parou; `null` quando enviou tudo.
  final Object? error;

  const RecoveryResult({required this.sent, required this.remaining, this.error});

  bool get complete => error == null && remaining == 0;
}

/// Envia um bloco ao servidor; levanta a exceção quando não conseguir.
typedef ChunkUploader = Future<void> Function(
  RecoverableChunk chunk,
  Uint8List bytes,
);

class LessonRecoveryService {
  final Future<Directory> Function() _root;

  /// `root` troca a pasta base nos testes.
  LessonRecoveryService({Future<Directory> Function()? root})
      : _root = root ?? _defaultRoot;

  static Future<Directory> _defaultRoot() async {
    final support = await getApplicationSupportDirectory();
    return Directory('${support.path}${Platform.pathSeparator}lesson_chunks');
  }

  static final _chunkName = RegExp(r'^chunk_(\d+)\.(wav|m4a)$');
  static final _safeId = RegExp(r'[^A-Za-z0-9_-]');

  /// O id vira nome de pasta: nada de separador de caminho nem ponto.
  static String safeId(String lessonId) => lessonId.replaceAll(_safeId, '_');

  Future<Directory> _lessonDir(String lessonId) async {
    final root = await _root();
    return Directory('${root.path}${Platform.pathSeparator}${safeId(lessonId)}');
  }

  /// Caminho do próximo bloco da aula; a pasta é criada se não existir.
  Future<String> newChunkPath(String lessonId, String extension) async {
    final dir = await _lessonDir(lessonId);
    await dir.create(recursive: true);
    return '${dir.path}${Platform.pathSeparator}'
        'chunk_${DateTime.now().millisecondsSinceEpoch}.$extension';
  }

  /// Aulas com áudio guardado. `ignoreLessonId` é a aula que está gravando agora:
  /// os arquivos dela estão em uso e não são sobra de nada.
  ///
  /// Arquivo só com o cabeçalho (nada foi captado) é apagado na hora, e pasta que
  /// ficou vazia some.
  Future<List<RecoverableLesson>> scan({String? ignoreLessonId}) async {
    final root = await _root();
    if (!await root.exists()) return const [];
    final ignored = ignoreLessonId == null ? null : safeId(ignoreLessonId);

    final lessons = <RecoverableLesson>[];
    await for (final entry in root.list()) {
      if (entry is! Directory) continue;
      final id = entry.path.split(Platform.pathSeparator).last;
      if (id == ignored) continue;

      final chunks = <RecoverableChunk>[];
      await for (final item in entry.list()) {
        if (item is! File) continue;
        final match = _chunkName.firstMatch(
          item.path.split(Platform.pathSeparator).last,
        );
        if (match == null) continue;
        final size = await item.length();
        if (size <= 44) {
          await _delete(item);
          continue;
        }
        chunks.add(RecoverableChunk(
          file: item,
          bytes: size,
          startedAt: DateTime.fromMillisecondsSinceEpoch(
            int.parse(match.group(1)!),
          ),
        ));
      }

      if (chunks.isEmpty) {
        await _deleteDirIfEmpty(entry);
        continue;
      }
      chunks.sort((a, b) => a.startedAt.compareTo(b.startedAt));
      lessons.add(RecoverableLesson(lessonId: id, chunks: chunks));
    }
    lessons.sort((a, b) =>
        a.chunks.first.startedAt.compareTo(b.chunks.first.startedAt));
    return lessons;
  }

  /// Reenvia os blocos da aula, em ordem. Para no primeiro que falhar e deixa em
  /// disco o que não subiu; o que subiu é apagado.
  ///
  /// A ordem importa: o servidor tira a sobreposição entre um bloco e o anterior.
  Future<RecoveryResult> recover(
    RecoverableLesson lesson,
    ChunkUploader upload,
  ) async {
    var sent = 0;
    for (final chunk in lesson.chunks) {
      try {
        final raw = await chunk.file.readAsBytes();
        final bytes = chunk.isWav ? repairWavHeader(raw) : raw;
        await upload(chunk, bytes);
      } catch (error) {
        return RecoveryResult(
          sent: sent,
          remaining: lesson.chunks.length - sent,
          error: error,
        );
      }
      await _delete(chunk.file);
      sent++;
    }
    await _deleteDirIfEmpty(await _lessonDir(lesson.lessonId));
    return RecoveryResult(sent: sent, remaining: 0);
  }

  /// Apaga o áudio guardado da aula.
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

  /// Corrige os tamanhos do cabeçalho de um WAV que a queda deixou incompleto.
  ///
  /// Quem grava só fecha o cabeçalho ao terminar; com o processo morto, os campos
  /// de tamanho ficam zerados ou desatualizados, e um leitor que confia neles lê
  /// zero amostras. Aqui os dois tamanhos passam a refletir o que há no arquivo.
  /// Qualquer coisa que não seja um WAV reconhecível volta como estava.
  static Uint8List repairWavHeader(Uint8List input) {
    if (input.length < 12 ||
        String.fromCharCodes(input.sublist(0, 4)) != 'RIFF' ||
        String.fromCharCodes(input.sublist(8, 12)) != 'WAVE') {
      return input;
    }

    // Procura o bloco "data" pulando os blocos anteriores (fmt, LIST...).
    var offset = 12;
    var dataTag = -1;
    while (offset + 8 <= input.length) {
      final tag = String.fromCharCodes(input.sublist(offset, offset + 4));
      if (tag == 'data') {
        dataTag = offset;
        break;
      }
      final size = ByteData.sublistView(input, offset + 4, offset + 8)
          .getUint32(0, Endian.little);
      final next = offset + 8 + size + (size.isOdd ? 1 : 0);
      if (size == 0xFFFFFFFF || next <= offset || next > input.length) break;
      offset = next;
    }
    if (dataTag < 0) return input;

    var length = input.length;
    // Amostra de 16 bits: um byte solto no fim é a escrita cortada ao meio.
    if ((length - (dataTag + 8)).isOdd) length -= 1;
    final dataSize = length - (dataTag + 8);

    final out = Uint8List.fromList(input.sublist(0, length));
    final view = ByteData.sublistView(out);
    view.setUint32(4, length - 8, Endian.little);
    view.setUint32(dataTag + 4, dataSize, Endian.little);
    return out;
  }
}

final lessonRecovery = LessonRecoveryService();

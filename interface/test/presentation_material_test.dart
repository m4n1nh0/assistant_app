import 'dart:convert';

import 'package:assistant_app/models/presentation_material.dart';
import 'package:assistant_app/services/api_service.dart';
import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/services/quiz_center_service.dart';
import 'package:assistant_app/widgets/presentation_material_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:qr_flutter/qr_flutter.dart';

const _discipline = Discipline(
  id: 'd1',
  code: 'ARA0040',
  name: 'BANCO DE DADOS',
  label: 'ARA0040 - BANCO DE DADOS',
  semester: '2026.2',
);

ClassGroup _turma(String id, String code, String name, int weekday) =>
    ClassGroup(
      id: id,
      code: code,
      name: name,
      discipline: 'BANCO DE DADOS',
      label: '$code $name',
      disciplineId: 'd1',
      schedules: [ClassSchedule(weekday: weekday)],
    );

final _turmas = [
  _turma('c-3002', '3002', 'A', 0),
  _turma('c-3030', '3030', 'B', 0),
  _turma('c-qui', '3001', 'Quinta', 3),
];

Map<String, dynamic> _link({
  String id = 'l1',
  String state = 'open',
  List<String> classIds = const [],
  int files = 2,
  int sent = 1,
  int total = 3,
}) =>
    {
      'id': id,
      'token': 'tok$id',
      'path': '/education/material-submit/tok$id',
      'title': 'Slides do projeto',
      'discipline_id': 'd1',
      'discipline': 'ARA0040 - BANCO DE DADOS',
      'class_ids': classIds,
      'class_label': classIds.isEmpty ? '' : '3002 A + 3030 B',
      'state': state,
      'active': state != 'closed',
      'closes_at': null,
      'max_files_per_group': 5,
      'files_received': files,
      'groups_sent': sent,
      'groups_total': total,
      'created_at': '2026-10-06T12:00:00',
    };

Map<String, dynamic> _file(String id, String title,
        {String by = 'Ana Souza', bool link = true}) =>
    {
      'id': id,
      'title': title,
      'filename': '$title.pptx',
      'source_type': 'pptx',
      'page_count': 12,
      'char_count': 3400,
      'truncated': false,
      'uploader_name': by,
      'from_link': link,
      'created_at': '2026-10-06T12:30:00',
    };

Map<String, dynamic> _rec(String id, {int segments = 4}) => {
      'id': id,
      'title': 'Apresentacao: GRUPO 1',
      'status': 'closed',
      'started_at': '2026-10-06T21:00:00',
      'segments': segments,
      'has_summary': false,
    };

Map<String, dynamic> _row(
  String id,
  String name, {
  List<String> classIds = const ['c-3002', 'c-3030'],
  List<Map<String, dynamic>> materials = const [],
  List<Map<String, dynamic>> recordings = const [],
}) {
  final gaps = [
    if (materials.isEmpty) 'material',
    if (!recordings.any((r) => (r['segments'] as int) > 0)) 'gravação',
  ];
  return {
    'group_id': id,
    'group_name': name,
    'class_ids': classIds,
    'materials': materials,
    'recordings': recordings,
    'gaps': gaps,
  };
}

Map<String, dynamic> _courseMaterial(String id, String title,
        {String groupId = ''}) =>
    {
      'id': id,
      'discipline_id': 'd1',
      'discipline': 'ARA0040 - BANCO DE DADOS',
      'title': title,
      'filename': '$title.pdf',
      'source_type': 'pdf',
      'page_count': 10,
      'char_count': 5000,
      'truncated': false,
      'created_at': '2026-10-05T10:00:00',
      'group_id': groupId.isEmpty ? null : groupId,
      'uploader_name': '',
      'from_link': false,
    };

Map<String, dynamic> _lesson(String id, String title, {String kind = 'palestra'}) =>
    {
      'id': id,
      'kind': kind,
      'group_id': null,
      'group_name': '',
      'discipline': '',
      'semester': '2026.2',
      'title': title,
      'class_group': '',
      'class_ids': <String>[],
      'class_labels': <String>[],
      'status': 'closed',
      'started_at': '2026-10-06T20:00:00',
      'segment_count': 6,
      'transcript_chars': 900,
    };

class _Backend {
  List<Map<String, dynamic>> links;
  List<Map<String, dynamic>> rows;
  List<Map<String, dynamic>> materials;
  List<Map<String, dynamic>> lessons;
  final requests = <http.Request>[];

  _Backend({
    List<Map<String, dynamic>>? links,
    List<Map<String, dynamic>>? rows,
    this.materials = const [],
    this.lessons = const [],
  })  : links = links ?? [],
        rows = rows ?? [];

  http.Response handle(http.Request request) {
    requests.add(request);
    final path = request.url.path;
    http.Response json(Object body) => http.Response(jsonEncode(body), 200);
    final body = request.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(request.body) as Map<String, dynamic>;

    if (path.endsWith('/education/material-links')) {
      if (request.method == 'POST') {
        final created = _link(id: 'novo', classIds: [
          for (final id in (body['class_ids'] as List)) '$id'
        ]);
        links = [created, ...links];
        return json(created);
      }
      return json(links);
    }
    final linkMatch = RegExp(r'/education/material-links/(\w+)$').firstMatch(path);
    if (linkMatch != null) {
      final id = linkMatch.group(1)!;
      if (request.method == 'DELETE') {
        links = links.where((l) => l['id'] != id).toList();
        return json({'deleted': id});
      }
      final current = links.firstWhere((l) => l['id'] == id);
      final updated = {
        ...current,
        if (body.containsKey('active')) 'active': body['active'],
        if (body.containsKey('active'))
          'state': body['active'] == true ? 'open' : 'closed',
      };
      links = [for (final l in links) l['id'] == id ? updated : l];
      return json(updated);
    }
    if (path.endsWith('/education/presentations')) return json(rows);
    if (path.endsWith('/education/materials')) return json(materials);
    if (path.endsWith('/group') && path.contains('/materials/')) {
      return json(_courseMaterial('m-x', 'ligado', groupId: '${body['group_id']}'));
    }
    if (path.endsWith('/presentation-group')) {
      return json(_lesson('l-x', 'ligada', kind: 'apresentacao'));
    }
    if (path.endsWith('/education/lessons')) {
      final kind = request.url.queryParameters['kind'];
      return json([
        for (final l in lessons)
          if (l['kind'] == kind) l
      ]);
    }
    return http.Response('{"detail":"inesperado $path"}', 404);
  }

  Map<String, dynamic> bodyOf(String method, String suffix) => jsonDecode(
      requests
          .lastWhere((r) => r.method == method && r.url.path.endsWith(suffix))
          .body) as Map<String, dynamic>;

  bool called(String method, String suffix) =>
      requests.any((r) => r.method == method && r.url.path.endsWith(suffix));
}

class _FakeQuiz extends QuizCenterService {
  _FakeQuiz() : super(ApiService());

  final queued = <Map<String, dynamic>>[];
  Object? error;

  @override
  Future<QuizJob> enqueue(Map<String, dynamic> request) async {
    if (error != null) throw error!;
    queued.add(request);
    return const QuizJob(id: 'job1', status: 'queued', titulo: 'x', total: 8);
  }
}

Future<void> _open(
  WidgetTester tester,
  _Backend backend, {
  _FakeQuiz? quiz,
  Set<String> classFilter = const {},
  String baseUrl = 'https://app.exemplo.com',
  VoidCallback? onQuizQueued,
}) async {
  tester.view.physicalSize = const Size(1500, 2200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(() async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: PresentationMaterialPanel(
          discipline: _discipline,
          classes: _turmas,
          classFilter: classFilter,
          quizService: quiz ?? _FakeQuiz(),
          baseUrl: baseUrl,
          onQuizQueued: onQuizQueued,
        ),
      ),
    ));
    await tester.pumpAndSettle();
  }, () => client);
}

/// Roda uma ação do teste com o cliente simulado ainda ativo.
Future<void> _act(
  WidgetTester tester,
  _Backend backend,
  Future<void> Function() body,
) async {
  final client = MockClient((request) async => backend.handle(request));
  await http.runWithClient(body, () => client);
}

void main() {
  group('modelos', () {
    test('o link junta o endereço do servidor com o caminho', () {
      final link = MaterialLink.fromJson(_link());

      expect(link.url('https://app.exemplo.com'),
          'https://app.exemplo.com/education/material-submit/tokl1');
      expect(link.url('https://app.exemplo.com/'),
          'https://app.exemplo.com/education/material-submit/tokl1');
    });

    test('estado e progresso do link', () {
      final link = MaterialLink.fromJson(_link(state: 'expired'));

      expect(link.isOpen, isFalse);
      expect(link.stateLabel, 'Prazo encerrado');
      expect(link.progressLabel, '1 de 3 grupos enviaram · 2 arquivo(s)');
      expect(MaterialLink.fromJson(_link()).stateLabel, 'Aberto');
      expect(MaterialLink.fromJson(_link(state: 'closed')).stateLabel, 'Fechado');
    });

    test('reconhece endereço que só funciona neste computador', () {
      for (final local in [
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'http://192.168.0.10:8000',
        'http://10.0.0.5',
        'http://172.20.1.1',
        'http://meu-pc.local:8000',
      ]) {
        expect(isLocalAddress(local), isTrue, reason: local);
      }
      for (final publico in [
        'https://app.exemplo.com',
        'https://x.up.railway.app',
        'http://172.32.0.1',
        'http://8.8.8.8',
        '',
      ]) {
        expect(isLocalAddress(publico), isFalse, reason: publico);
      }
    });

    test('grupo com material e gravação transcrita pode ter quiz', () {
      final row = PresentationRow.fromJson(_row('g1', 'GRUPO 1',
          materials: [_file('a', 'Slides')], recordings: [_rec('r1')]));

      expect(row.hasMaterial && row.hasRecording && row.canQuiz, isTrue);
      expect(row.gaps, isEmpty);
      expect(row.statusLabel, '1 arquivo · 1 gravação');
      expect(row.materials.single.sizeLabel, '12 slides');
    });

    test('gravação sem transcrição não conta como fonte', () {
      final row = PresentationRow.fromJson(
          _row('g1', 'GRUPO 1', recordings: [_rec('r1', segments: 0)]));

      expect(row.hasRecording, isFalse);
      expect(row.canQuiz, isFalse);
      expect(row.gaps, ['material', 'gravação']);
      expect(row.statusLabel, '1 gravação');
    });

    test('grupo sem nada diz que nada chegou', () {
      final row = PresentationRow.fromJson(_row('g1', 'GRUPO 1'));

      expect(row.statusLabel, 'nada recebido ainda');
      expect(row.canQuiz, isFalse);
    });

    test('rótulo de páginas e slides', () {
      PresentationFile file(String type, int pages) => PresentationFile(
          id: 'x', title: 't', sourceType: type, pageCount: pages);

      expect(file('pdf', 1).sizeLabel, '1 página');
      expect(file('pdf', 8).sizeLabel, '8 páginas');
      expect(file('pptx', 1).sizeLabel, '1 slide');
      expect(file('docx', 0).sizeLabel, 'DOCX');
    });

    test('pedido do quiz rápido deixa o grupo que apresentou de fora', () {
      final row = PresentationRow.fromJson(_row('g1', 'GRUPO 1'));

      final pedido = buildQuickQuizRequest(
        group: row,
        disciplineId: 'd1',
        sources: const QuickQuizSources(
            materialIds: {'m2', 'm1'}, lessonIds: {'l1'}),
        questions: 10,
        mode: 'representante',
      );

      expect(pedido['material_ids'], ['m1', 'm2']);
      expect(pedido['lesson_ids'], ['l1']);
      expect(pedido['quantidade_questoes'], 10);
      expect(pedido['titulo'], 'Quiz rápido: GRUPO 1');
      expect(pedido['group_setup'], {
        'mode': 'representante',
        'discipline_id': 'd1',
        'class_ids': ['c-3002', 'c-3030'],
        'exclude_group_ids': ['g1'],
      });
    });

    test('material comum não tem grupo; o enviado pelo link tem', () {
      final comum = CourseMaterial.fromJson(_courseMaterial('m1', 'Apostila'));
      final enviado = CourseMaterial.fromJson({
        ..._courseMaterial('m2', 'Slides', groupId: 'g1'),
        'uploader_name': 'Ana',
        'from_link': true,
      });

      expect(comum.groupId, isEmpty);
      expect(comum.fromLink, isFalse);
      expect(enviado.groupId, 'g1');
      expect(enviado.uploaderName, 'Ana');
      expect(enviado.fromLink, isTrue);
    });
  });

  group('link para os alunos', () {
    testWidgets('mostra o link com endereço, estado e progresso', (tester) async {
      final backend = _Backend(links: [_link()]);
      await _open(tester, backend);

      expect(find.text('Slides do projeto'), findsOneWidget);
      expect(
        find.text('https://app.exemplo.com/education/material-submit/tokl1'),
        findsOneWidget,
      );
      expect(find.text('ABERTO'), findsOneWidget);
      expect(find.text('1 de 3 grupos enviaram · 2 arquivo(s)'), findsOneWidget);
      expect(find.byKey(const ValueKey('aviso-endereco-local')), findsNothing);
    });

    testWidgets('avisa quando o endereço do servidor é local', (tester) async {
      final backend = _Backend(links: [_link()]);
      await _open(tester, backend, baseUrl: 'http://localhost:8000');

      expect(find.byKey(const ValueKey('aviso-endereco-local')), findsOneWidget);
    });

    testWidgets('cria o link com as turmas marcadas e o nome', (tester) async {
      final backend = _Backend();
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.enterText(
            find.byKey(const ValueKey('titulo-link')), 'Slides finais');
        await tester.tap(find.byKey(const ValueKey('novo-turma-c-3030')));
        await tester.tap(find.byKey(const ValueKey('novo-turma-c-3002')));
        await tester.pump();
        await tester.ensureVisible(find.byKey(const ValueKey('criar-link')));
        await tester.tap(find.byKey(const ValueKey('criar-link')));
        await tester.pumpAndSettle();
      });

      final body = backend.bodyOf('POST', '/material-links');
      expect(body['discipline_id'], 'd1');
      expect(body['title'], 'Slides finais');
      expect(body['class_ids'], ['c-3002', 'c-3030']);
      expect(body.containsKey('closes_at'), isFalse);
      expect(find.textContaining('Link criado'), findsOneWidget);
      expect(find.byKey(const ValueKey('link-novo')), findsOneWidget);
    });

    testWidgets('as turmas marcadas na tela vêm marcadas no link novo',
        (tester) async {
      final backend = _Backend();
      await _open(tester, backend, classFilter: {'c-3002', 'c-3030'});

      bool marcada(String id) => tester
          .widget<FilterChip>(find.byKey(ValueKey('novo-turma-$id')))
          .selected;
      expect(marcada('c-3002'), isTrue);
      expect(marcada('c-3030'), isTrue);
      expect(marcada('c-qui'), isFalse);
    });

    testWidgets('fecha e reabre o recebimento', (tester) async {
      final backend = _Backend(links: [_link()]);
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.tap(find.byKey(const ValueKey('alternar-l1')));
        await tester.pumpAndSettle();
        expect(backend.bodyOf('PATCH', '/material-links/l1')['active'], false);
        expect(find.text('FECHADO'), findsOneWidget);
        expect(find.text('Recebimento encerrado.'), findsOneWidget);

        await tester.tap(find.byKey(const ValueKey('alternar-l1')));
        await tester.pumpAndSettle();
        expect(backend.bodyOf('PATCH', '/material-links/l1')['active'], true);
        expect(find.text('ABERTO'), findsOneWidget);
      });
    });

    testWidgets('reabrir um link vencido tira o prazo', (tester) async {
      final backend = _Backend(links: [_link(state: 'expired')]);
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.tap(find.byKey(const ValueKey('alternar-l1')));
        await tester.pumpAndSettle();
      });

      final body = backend.bodyOf('PATCH', '/material-links/l1');
      expect(body['active'], true);
      expect(body['clear_deadline'], true);
    });

    testWidgets('apaga o link', (tester) async {
      final backend = _Backend(links: [_link()]);
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.tap(find.byKey(const ValueKey('apagar-l1')));
        await tester.pumpAndSettle();
      });

      expect(backend.called('DELETE', '/material-links/l1'), isTrue);
      expect(find.byKey(const ValueKey('link-l1')), findsNothing);
      expect(find.textContaining('O que já foi enviado continua'), findsOneWidget);
    });

    testWidgets('copia o link para a área de transferência', (tester) async {
      final copiado = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copiado.add((call.arguments as Map)['text'] as String);
          }
          return null;
        },
      );
      addTearDown(() => tester.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null));
      final backend = _Backend(links: [_link()]);
      await _open(tester, backend);

      await tester.tap(find.byKey(const ValueKey('copiar-l1')));
      await tester.pumpAndSettle();

      expect(copiado,
          ['https://app.exemplo.com/education/material-submit/tokl1']);
      expect(find.text('Link copiado.'), findsOneWidget);
    });

    testWidgets('o QR Code leva o mesmo endereço', (tester) async {
      final backend = _Backend(links: [_link()]);
      await _open(tester, backend);

      await tester.tap(find.byKey(const ValueKey('qr-l1')));
      await tester.pumpAndSettle();

      expect(find.byType(QrImageView), findsOneWidget);
      // O endereco aparece na tela do link e, de novo, embaixo do QR Code.
      expect(
        find.text('https://app.exemplo.com/education/material-submit/tokl1'),
        findsNWidgets(2),
      );
    });
  });

  group('grupos', () {
    testWidgets('cada grupo mostra o material e a gravação que tem', (tester) async {
      final backend = _Backend(rows: [
        _row('g1', 'GRUPO 1',
            materials: [_file('a', 'Slides do G1')], recordings: [_rec('r1')]),
        _row('g2', 'GRUPO 2'),
      ]);
      await _open(tester, backend);

      expect(find.text('GRUPOS (2)'), findsOneWidget);
      expect(find.byKey(const ValueKey('chip-material-g1')), findsOneWidget);
      expect(find.text('material ✓'), findsOneWidget);
      expect(find.text('gravação ✓'), findsOneWidget);
      expect(find.text('sem material'), findsOneWidget);
      expect(find.text('sem gravação'), findsOneWidget);
      expect(find.textContaining('Slides do G1 · 12 slides · Ana Souza'),
          findsOneWidget);
      expect(find.textContaining('Apresentacao: GRUPO 1 ·'), findsOneWidget);
      expect(find.text('nada recebido ainda'), findsOneWidget);
    });

    testWidgets('quiz rápido só liga com alguma fonte', (tester) async {
      final backend = _Backend(rows: [
        _row('g1', 'GRUPO 1', materials: [_file('a', 'Slides')]),
        _row('g2', 'GRUPO 2'),
      ]);
      await _open(tester, backend);

      FilledButton botao(String id) => tester
          .widget<FilledButton>(find.byKey(ValueKey('quiz-rapido-$id')));
      expect(botao('g1').onPressed, isNotNull);
      expect(botao('g2').onPressed, isNull);
    });

    testWidgets('as turmas marcadas na tela filtram os grupos', (tester) async {
      final backend = _Backend(rows: [
        _row('g1', 'GRUPO 1', classIds: ['c-3002', 'c-3030']),
        _row('g3', 'GRUPO 3', classIds: ['c-qui']),
      ]);
      await _open(tester, backend, classFilter: {'c-3030'});

      expect(find.text('GRUPOS (1 de 2)'), findsOneWidget);
      expect(find.byKey(const ValueKey('grupo-g1')), findsOneWidget);
      expect(find.byKey(const ValueKey('grupo-g3')), findsNothing);
    });

    testWidgets('solta um material do grupo', (tester) async {
      final backend = _Backend(rows: [
        _row('g1', 'GRUPO 1', materials: [_file('a', 'Slides')]),
      ]);
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.tap(find.byKey(const ValueKey('soltar-material-a')));
        await tester.pumpAndSettle();
      });

      expect(backend.bodyOf('PUT', '/materials/a/group')['group_id'], isNull);
      expect(find.textContaining('Material solto do GRUPO 1'), findsOneWidget);
    });

    testWidgets('liga um material solto da disciplina ao grupo', (tester) async {
      final backend = _Backend(
        rows: [_row('g1', 'GRUPO 1')],
        materials: [
          _courseMaterial('m1', 'Apostila'),
          _courseMaterial('m2', 'Slides do G3', groupId: 'g3'),
        ],
      );
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.tap(find.byKey(const ValueKey('ligar-material-g1')));
        await tester.pumpAndSettle();
        // So o material sem grupo e oferecido.
        expect(find.byKey(const ValueKey('ligar-material-m1')), findsOneWidget);
        expect(find.byKey(const ValueKey('ligar-material-m2')), findsNothing);

        await tester.tap(find.byKey(const ValueKey('ligar-material-m1')));
        await tester.pumpAndSettle();
      });

      expect(backend.bodyOf('PUT', '/materials/m1/group')['group_id'], 'g1');
      expect(find.textContaining('Material ligado ao GRUPO 1'), findsOneWidget);
    });

    testWidgets('sem material solto, explica o caminho', (tester) async {
      final backend = _Backend(rows: [_row('g1', 'GRUPO 1')]);
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.tap(find.byKey(const ValueKey('ligar-material-g1')));
        await tester.pumpAndSettle();
      });

      expect(find.textContaining('Não há material solto'), findsOneWidget);
    });

    testWidgets('liga uma gravação de palestra ao grupo', (tester) async {
      final backend = _Backend(
        rows: [_row('g1', 'GRUPO 1')],
        lessons: [_lesson('l1', 'teste'), _lesson('l2', 'Outra', kind: 'apresentacao')],
      );
      await _open(tester, backend);
      await _act(tester, backend, () async {
        await tester.tap(find.byKey(const ValueKey('ligar-gravacao-g1')));
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('ligar-gravacao-l1')), findsOneWidget);
        expect(find.byKey(const ValueKey('ligar-gravacao-l2')), findsOneWidget);

        await tester.tap(find.byKey(const ValueKey('ligar-gravacao-l1')));
        await tester.pumpAndSettle();
      });

      expect(backend.bodyOf('PUT', '/lessons/l1/presentation-group')['group_id'],
          'g1');
      expect(find.textContaining('Gravação ligada ao GRUPO 1'), findsOneWidget);
    });
  });

  group('quiz rápido', () {
    final rows = [
      _row('g1', 'GRUPO 1',
          materials: [_file('a', 'Slides do G1')], recordings: [_rec('r1')]),
    ];

    testWidgets('gera o quiz com as fontes, sem o grupo que apresentou',
        (tester) async {
      final backend = _Backend(rows: rows);
      final quiz = _FakeQuiz();
      var avisou = false;
      await _open(tester, backend, quiz: quiz, onQuizQueued: () => avisou = true);

      await tester.ensureVisible(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.tap(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.pumpAndSettle();

      expect(find.text('Quiz rápido · GRUPO 1'), findsOneWidget);
      expect(find.byKey(const ValueKey('resumo-quem-joga')), findsOneWidget);
      expect(
        tester.widget<Text>(find.byKey(const ValueKey('resumo-quem-joga'))).data,
        allOf(contains('3002 A · segunda + 3030 B · segunda'),
            contains('GRUPO 1 apresentou e fica de fora')),
      );
      await tester.tap(find.byKey(const ValueKey('gerar-quiz')));
      await tester.pumpAndSettle();

      final pedido = quiz.queued.single;
      expect(pedido['material_ids'], ['a']);
      expect(pedido['lesson_ids'], ['r1']);
      expect(pedido['quantidade_questoes'], 8);
      expect(pedido['titulo'], 'Quiz rápido: GRUPO 1');
      expect((pedido['group_setup'] as Map)['exclude_group_ids'], ['g1']);
      expect((pedido['group_setup'] as Map)['class_ids'], ['c-3002', 'c-3030']);
      expect((pedido['group_setup'] as Map)['mode'], 'media');
      expect(avisou, isTrue);
      expect(find.textContaining('Gerando o quiz rápido do GRUPO 1'),
          findsOneWidget);
    });

    testWidgets('dá para escolher só uma das fontes, o formato e a quantidade',
        (tester) async {
      final backend = _Backend(rows: rows);
      final quiz = _FakeQuiz();
      await _open(tester, backend, quiz: quiz);

      await tester.ensureVisible(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.tap(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('fonte-material-a')));
      await tester.pump();
      await tester.tap(find.text('Só o representante'));
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('quantidade')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('15 perguntas').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('gerar-quiz')));
      await tester.pumpAndSettle();

      final pedido = quiz.queued.single;
      expect(pedido['material_ids'], isEmpty);
      expect(pedido['lesson_ids'], ['r1']);
      expect(pedido['quantidade_questoes'], 15);
      expect((pedido['group_setup'] as Map)['mode'], 'representante');
    });

    testWidgets('sem nenhuma fonte marcada o botão não liga', (tester) async {
      final backend = _Backend(rows: rows);
      await _open(tester, backend);

      await tester.ensureVisible(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.tap(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('fonte-material-a')));
      await tester.tap(find.byKey(const ValueKey('fonte-gravacao-r1')));
      await tester.pump();

      expect(
        tester
            .widget<FilledButton>(find.byKey(const ValueKey('gerar-quiz')))
            .onPressed,
        isNull,
      );
    });

    testWidgets('avisa o que faltou e usa só o que existe', (tester) async {
      final backend = _Backend(rows: [
        _row('g1', 'GRUPO 1', materials: [_file('a', 'Slides do G1')]),
      ]);
      final quiz = _FakeQuiz();
      await _open(tester, backend, quiz: quiz);

      await tester.ensureVisible(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.tap(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.pumpAndSettle();

      expect(find.textContaining('Faltou gravação'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('gerar-quiz')));
      await tester.pumpAndSettle();
      expect(quiz.queued.single['lesson_ids'], isEmpty);
      expect(quiz.queued.single['material_ids'], ['a']);
    });

    testWidgets('gravação sem transcrição não pode ser marcada', (tester) async {
      final backend = _Backend(rows: [
        _row('g1', 'GRUPO 1',
            materials: [_file('a', 'Slides')],
            recordings: [_rec('r1', segments: 0)]),
      ]);
      await _open(tester, backend);

      await tester.ensureVisible(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.tap(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.pumpAndSettle();

      final caixa = tester.widget<CheckboxListTile>(
          find.byKey(const ValueKey('fonte-gravacao-r1')));
      expect(caixa.onChanged, isNull);
      expect(caixa.value, isFalse);
    });

    testWidgets('mostra o erro do servidor se o pedido falhar', (tester) async {
      final backend = _Backend(rows: rows);
      final quiz = _FakeQuiz()..error = EducationException('Fila indisponível');
      await _open(tester, backend, quiz: quiz);

      await tester.ensureVisible(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.tap(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('gerar-quiz')));
      await tester.pumpAndSettle();

      expect(find.text('Fila indisponível'), findsOneWidget);
    });

    testWidgets('cancelar não manda nada', (tester) async {
      final backend = _Backend(rows: rows);
      final quiz = _FakeQuiz();
      await _open(tester, backend, quiz: quiz);

      await tester.ensureVisible(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.tap(find.byKey(const ValueKey('quiz-rapido-g1')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();

      expect(quiz.queued, isEmpty);
    });
  });
}

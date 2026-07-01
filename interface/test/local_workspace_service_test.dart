import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:assistant_app/services/local_workspace_service.dart';

void main() {
  test('inspectWorkspace builds a safe project snapshot', () async {
    final temp =
        await Directory.systemTemp.createTemp('assistant_workspace_test_');
    addTearDown(() async {
      if (await temp.exists()) {
        await temp.delete(recursive: true);
      }
    });

    await File('${temp.path}${Platform.pathSeparator}README.md')
        .writeAsString('# Demo\n\nProjeto de teste.\n');
    await File('${temp.path}${Platform.pathSeparator}pubspec.yaml')
        .writeAsString('name: demo\n');
    await File('${temp.path}${Platform.pathSeparator}.env')
        .writeAsString('TOKEN=secret\n');
    final lib = Directory('${temp.path}${Platform.pathSeparator}lib');
    await lib.create();
    await File('${lib.path}${Platform.pathSeparator}main.dart')
        .writeAsString('void main() {}\n');

    final snapshot = await LocalWorkspaceService.inspectWorkspace(
      rootPath: temp.path,
      query: 'analise o projeto demo',
    );

    expect(snapshot.path, temp.absolute.path);
    expect(snapshot.markers, contains('README.md'));
    expect(snapshot.tree.join('\n'), contains('lib/main.dart'));
    expect(snapshot.tree.join('\n'), isNot(contains('.env')));
    expect(
        snapshot.files.map((file) => file.relativePath), contains('README.md'));
    expect(snapshot.toPromptText(userRequest: 'analise'),
        contains('Contexto local do workspace'));
    expect(snapshot.toPromptText(userRequest: 'analise'),
        isNot(contains('TOKEN=secret')));
    expect(snapshot.toPromptText(userRequest: 'analise', allowEdits: true),
        contains('workspace_edits'));
  });

  test('applyEdits writes only inside workspace', () async {
    final temp =
        await Directory.systemTemp.createTemp('assistant_workspace_edit_test_');
    addTearDown(() async {
      if (await temp.exists()) {
        await temp.delete(recursive: true);
      }
    });

    await LocalWorkspaceService.applyEdits(
      rootPath: temp.path,
      edits: const [
        WorkspaceFileEdit(
          relativePath: 'lib/main.dart',
          content: 'void main() {}\n',
        ),
      ],
    );

    final target = File(
        '${temp.path}${Platform.pathSeparator}lib${Platform.pathSeparator}main.dart');
    expect(await target.readAsString(), 'void main() {}\n');

    await expectLater(
      LocalWorkspaceService.applyEdits(
        rootPath: temp.path,
        edits: const [
          WorkspaceFileEdit(
            relativePath: '../outside.txt',
            content: 'nope',
          ),
        ],
      ),
      throwsA(isA<WorkspaceInspectionException>()),
    );
  });

  test('inspectWorkspace includes files relevant to the user request',
      () async {
    final temp = await Directory.systemTemp
        .createTemp('assistant_workspace_relevance_test_');
    addTearDown(() async {
      if (await temp.exists()) {
        await temp.delete(recursive: true);
      }
    });

    final src = Directory('${temp.path}${Platform.pathSeparator}src');
    final docs = Directory('${temp.path}${Platform.pathSeparator}docs');
    await src.create(recursive: true);
    await docs.create(recursive: true);
    await File('${src.path}${Platform.pathSeparator}payment_service.py')
        .writeAsString('class PaymentService:\n    pass\n');
    await File('${src.path}${Platform.pathSeparator}report_view.dart')
        .writeAsString('class ReportView {}\n');
    await File('${docs.path}${Platform.pathSeparator}payments.md')
        .writeAsString('# Payments\n\nFluxo de payment.\n');

    final snapshot = await LocalWorkspaceService.inspectWorkspace(
      rootPath: temp.path,
      query: 'corrija o bug em payment_service.py no fluxo payment',
      maxTotalChars: 12000,
    );

    final paths = snapshot.files.map((file) => file.relativePath).toList();
    expect(paths, contains('src/payment_service.py'));
    expect(
      snapshot.toPromptText(userRequest: 'corrija payment'),
      contains('class PaymentService'),
    );
  });
}

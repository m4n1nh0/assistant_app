import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:assistant_app/services/project_discovery_service.dart';

void main() {
  test('finds project by folder name under provided roots', () async {
    final temp =
        await Directory.systemTemp.createTemp('assistant_project_test_');
    addTearDown(() async {
      if (await temp.exists()) {
        await temp.delete(recursive: true);
      }
    });

    final root = Directory('${temp.path}${Platform.pathSeparator}workspace');
    final project =
        Directory('${root.path}${Platform.pathSeparator}assistant_app');
    await project.create(recursive: true);
    await File('${project.path}${Platform.pathSeparator}pyproject.toml')
        .writeAsString('[project]\nname = "assistant_app"\n');

    final result = await ProjectDiscoveryService.findProject(
      'assistant_app',
      roots: [root],
      maxDepth: 2,
    );

    expect(result, isNotNull);
    expect(result!.path, project.path);
  });

  test('returns null when project is not found', () async {
    final temp =
        await Directory.systemTemp.createTemp('assistant_project_test_');
    addTearDown(() async {
      if (await temp.exists()) {
        await temp.delete(recursive: true);
      }
    });

    final result = await ProjectDiscoveryService.findProject(
      'missing_project',
      roots: [temp],
      maxDepth: 1,
    );

    expect(result, isNull);
  });
}
